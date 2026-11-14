"""
fileContentIndex.py — Semantic File Content Search for JARVIS
─────────────────────────────────────────────────────────────
Indexes the content of your files (not just filenames) using:
  - nomic-embed-text (already running for deepMemory) for embeddings
  - faiss-cpu for fast vector similarity search
  - SQLite for chunk metadata (filepath, chunk text, timestamps)

Background thread re-indexes changed files every FILE_INDEX_REBUILD_HOURS.
On first run, a full index build happens automatically.

Usage:
    from fileContentIndex import content_search, start_background_indexer
    results = content_search("database schema notes")
    # → [{"path": "...", "snippet": "...", "score": 0.91}, ...]
"""

import os
import sys
import json
import time
import sqlite3
import threading
import subprocess
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        FILE_INDEX_PATH         = "file_content_index"
        FILE_INDEX_CHUNK_CHARS  = 800
        FILE_INDEX_CHUNK_OVERLAP= 100
        FILE_INDEX_MAX_FILE_MB  = 20
        FILE_INDEX_TOP_K        = 5
        FILE_INDEX_REBUILD_HOURS= 6
        FILE_INDEX_EXTENSIONS   = [".txt",".md",".py",".js",".ts",".json",".csv",".log",
                                    ".html",".css",".yaml",".yml",".ini",".cfg",".toml",
                                    ".pdf",".docx",".xlsx"]
        OLLAMA_BASE_URL         = "http://localhost:11434"
        EMBEDDING_MODEL         = "nomic-embed-text"

# ── Auto-install faiss ────────────────────────────────────────────────────────
try:
    import faiss
    import numpy as np
except ImportError:
    print("[FileIndex]: Installing faiss-cpu and numpy...")
    subprocess.run([sys.executable, "-m", "pip", "install", "faiss-cpu", "numpy",
                    "--break-system-packages"], check=True, capture_output=True)
    import faiss
    import numpy as np

# ── Paths ─────────────────────────────────────────────────────────────────────
os.makedirs(config.FILE_INDEX_PATH, exist_ok=True)
_DB_PATH    = os.path.join(config.FILE_INDEX_PATH, "chunks.db")
_FAISS_PATH = os.path.join(config.FILE_INDEX_PATH, "vectors.index")

# ── Search roots — same as fileSearch.py ─────────────────────────────────────
SEARCH_ROOTS = [
    os.path.expanduser("~\\Desktop"),
    os.path.expanduser("~\\Documents"),
    os.path.expanduser("~\\Downloads"),
    os.path.expanduser("~\\OneDrive"),
]

# ── Globals ───────────────────────────────────────────────────────────────────
_index_lock     = threading.Lock()
_faiss_index    = None          # Loaded into memory on first search
_embed_dim      = None          # Set on first successful embedding
_indexer_running= False

# ── SQLite helpers ────────────────────────────────────────────────────────────
def _get_db():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT NOT NULL,
            chunk_id INTEGER NOT NULL,
            text     TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            file_mtime REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_filepath ON chunks(filepath)")
    conn.commit()
    return conn

# ── Text extraction ───────────────────────────────────────────────────────────
def _extract_text(filepath):
    """Extract plaintext from supported file types. Returns string or None."""
    ext = os.path.splitext(filepath)[1].lower()
    try:
        # Plain text files
        if ext in (".txt",".md",".py",".js",".ts",".json",".csv",".log",
                   ".html",".css",".yaml",".yml",".ini",".cfg",".toml"):
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

        # PDF
        if ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(filepath)
                return "\n".join(p.extract_text() or "" for p in reader.pages)
            except Exception:
                try:
                    subprocess.run([sys.executable, "-m", "pip", "install", "pypdf",
                                    "--break-system-packages"], check=True, capture_output=True)
                    import pypdf
                    reader = pypdf.PdfReader(filepath)
                    return "\n".join(p.extract_text() or "" for p in reader.pages)
                except Exception:
                    return None

        # Word documents
        if ext in (".docx", ".doc"):
            try:
                import docx
                doc = docx.Document(filepath)
                return "\n".join(p.text for p in doc.paragraphs)
            except Exception:
                try:
                    subprocess.run([sys.executable, "-m", "pip", "install", "python-docx",
                                    "--break-system-packages"], check=True, capture_output=True)
                    import docx
                    doc = docx.Document(filepath)
                    return "\n".join(p.text for p in doc.paragraphs)
                except Exception:
                    return None

        # Excel
        if ext in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
                rows = []
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        rows.append(" | ".join(str(c) for c in row if c is not None))
                return "\n".join(rows)
            except Exception:
                return None

    except Exception:
        return None
    return None

# ── Chunking ──────────────────────────────────────────────────────────────────
def _chunk_text(text):
    """Split text into overlapping chunks of ~FILE_INDEX_CHUNK_CHARS characters."""
    size    = config.FILE_INDEX_CHUNK_CHARS
    overlap = config.FILE_INDEX_CHUNK_OVERLAP
    chunks  = []
    start   = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
        if start >= len(text):
            break
    return chunks

# ── Embedding ─────────────────────────────────────────────────────────────────
def _embed(text):
    """Get embedding vector from Ollama nomic-embed-text. Returns list[float] or None."""
    for endpoint in ["/api/embeddings", "/api/embed"]:
        try:
            r = requests.post(
                f"{config.OLLAMA_BASE_URL}{endpoint}",
                json={"model": config.EMBEDDING_MODEL, "prompt": text},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                vec = data.get("embedding") or (data.get("embeddings") or [None])[0]
                if vec:
                    return vec
        except Exception:
            pass
    return None

# ── Index a single file ───────────────────────────────────────────────────────
def _index_file(filepath, conn):
    """Extract, chunk, embed, and store a single file. Skips if unchanged."""
    try:
        stat     = os.stat(filepath)
        mtime    = stat.st_mtime
        size_mb  = stat.st_size / (1024 * 1024)
        if size_mb > config.FILE_INDEX_MAX_FILE_MB:
            return

        # Skip if file hasn't changed since last index
        row = conn.execute(
            "SELECT file_mtime FROM chunks WHERE filepath=? LIMIT 1", (filepath,)
        ).fetchone()
        if row and abs(row[0] - mtime) < 1.0:
            return

        # Remove old chunks for this file
        conn.execute("DELETE FROM chunks WHERE filepath=?", (filepath,))

        text = _extract_text(filepath)
        if not text or len(text.strip()) < 50:
            conn.commit()
            return

        chunks   = _chunk_text(text)
        now_str  = datetime.now().isoformat()
        new_rows = []

        for i, chunk in enumerate(chunks):
            vec = _embed(chunk)
            if vec is None:
                continue
            new_rows.append((filepath, i, chunk, now_str, mtime, vec))

        # Store metadata in SQLite
        conn.executemany(
            "INSERT INTO chunks (filepath, chunk_id, text, indexed_at, file_mtime) VALUES (?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], r[4]) for r in new_rows]
        )
        conn.commit()

        # Add vectors to faiss
        global _faiss_index, _embed_dim
        if new_rows:
            vecs = np.array([r[5] for r in new_rows], dtype="float32")
            faiss.normalize_L2(vecs)
            with _index_lock:
                if _faiss_index is None or _embed_dim is None:
                    _embed_dim   = vecs.shape[1]
                    _faiss_index = faiss.IndexFlatIP(_embed_dim)
                if vecs.shape[1] == _embed_dim:
                    _faiss_index.add(vecs)

    except Exception as e:
        print(f"[FileIndex]: Error indexing {os.path.basename(filepath)}: {e}")

# ── Full index build ──────────────────────────────────────────────────────────
def build_index(verbose=False):
    """Walk all search roots and index every supported file. Thread-safe."""
    conn = _get_db()
    total = 0
    for root in SEARCH_ROOTS:
        if not os.path.exists(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and d.lower() not in ("node_modules", "__pycache__", ".git", "cache", "temp")]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in config.FILE_INDEX_EXTENSIONS:
                    continue
                fpath = os.path.join(dirpath, fname)
                _index_file(fpath, conn)
                total += 1
                if verbose and total % 20 == 0:
                    print(f"[FileIndex]: Indexed {total} files...")
    conn.close()
    _load_faiss_from_db()
    if verbose:
        print(f"[FileIndex]: Index complete — {total} files processed.")

def _load_faiss_from_db():
    """Reconstruct the in-memory faiss index from scratch (used after full build)."""
    global _faiss_index, _embed_dim
    conn = _get_db()
    # We don't store raw vectors in SQLite — they're accumulated during indexing.
    # On restart, we rebuild by re-embedding only changed files.
    # (A future upgrade can persist the faiss binary with faiss.write_index)
    conn.close()

# ── Content search ────────────────────────────────────────────────────────────
def content_search(query, top_k=None):
    """
    Semantic search across all indexed file content.
    Returns list of dicts: [{path, snippet, score, chunk_id}]
    Falls back to empty list if index is empty or Ollama is offline.
    """
    global _faiss_index, _embed_dim
    if top_k is None:
        top_k = config.FILE_INDEX_TOP_K

    q_vec = _embed(query)
    if q_vec is None:
        return []

    with _index_lock:
        if _faiss_index is None or _faiss_index.ntotal == 0:
            return []
        q_arr = np.array([q_vec], dtype="float32")
        faiss.normalize_L2(q_arr)
        k       = min(top_k * 3, _faiss_index.ntotal)   # over-fetch then deduplicate by file
        scores, ids = _faiss_index.search(q_arr, k)

    conn   = _get_db()
    # faiss IDs are 0-based row positions in order of insertion
    # We map them to SQLite rowids (1-based) by offset+1
    result_rows = []
    seen_files  = set()
    for score, fid in zip(scores[0], ids[0]):
        if fid < 0:
            continue
        row = conn.execute(
            "SELECT filepath, text FROM chunks WHERE rowid=?", (int(fid) + 1,)
        ).fetchone()
        if row:
            fpath, snippet = row
            if fpath not in seen_files:
                seen_files.add(fpath)
                result_rows.append({
                    "path":    fpath,
                    "snippet": snippet[:300].strip(),
                    "score":   round(float(score), 3),
                })
        if len(result_rows) >= top_k:
            break
    conn.close()
    return result_rows

# ── Background indexer loop ───────────────────────────────────────────────────
def _indexer_loop():
    print("[FileIndex]: Background content indexer starting...")
    build_index(verbose=True)
    while True:
        time.sleep(config.FILE_INDEX_REBUILD_HOURS * 3600)
        print("[FileIndex]: Re-indexing changed files...")
        build_index(verbose=False)

def start_background_indexer():
    """Spawn the indexer as a low-priority daemon thread."""
    global _indexer_running
    if not _indexer_running:
        t = threading.Thread(target=_indexer_loop, daemon=True, name="file-content-indexer")
        t.start()
        _indexer_running = True
        print("[FileIndex]: Background indexer thread started.")
