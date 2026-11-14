"""
JARVIS Knowledge File Injector (Tier 4)
================================================================
Allows you to feed JARVIS personal knowledge files (PDFs, Word docs,
text files, JSON) that it indexes and can search semantically.

How it works:
1. Drop files in the knowledge/ directory
2. At startup, JARVIS indexes them (extracts text, chunks, embeds)
3. When you ask a question, relevant chunks are retrieved via
   cosine similarity and injected into the system prompt
4. A new tool "search_knowledge" is registered that the 1.5B/8B
   can call for explicit knowledge lookups

Supported file types:
  - PDF (.pdf)
  - Word (.docx, .doc)
  - Text (.txt, .md, .log, .ini, .cfg)
  - JSON (.json)
  - Excel (.xlsx) — bonus, already supported

The injector watches the knowledge/ directory for changes and
re-indexes automatically when files are added, modified, or deleted.
"""
import os
import sys
import json
import time
import threading
import traceback
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = _PARENT_DIR
        OLLAMA_BASE_URL = "http://localhost:11434"
        EMBEDDING_MODEL = "nomic-embed-text"


# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

KNOWLEDGE_INJECTOR_ENABLED = getattr(config, 'KNOWLEDGE_INJECTOR_ENABLED', True)
KNOWLEDGE_DIR = getattr(config, 'KNOWLEDGE_DIR',
    os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "knowledge"))
KNOWLEDGE_INDEX_FILE = getattr(config, 'KNOWLEDGE_INDEX_FILE',
    os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "knowledge_index.json"))
KNOWLEDGE_WATCH_INTERVAL = getattr(config, 'KNOWLEDGE_WATCH_INTERVAL', 10)  # seconds
KNOWLEDGE_MAX_CHUNKS_INJECTED = getattr(config, 'KNOWLEDGE_MAX_CHUNKS_INJECTED', 3)
KNOWLEDGE_SIMILARITY_THRESHOLD = getattr(config, 'KNOWLEDGE_SIMILARITY_THRESHOLD', 0.55)
KNOWLEDGE_CHUNK_CHARS = getattr(config, 'KNOWLEDGE_CHUNK_CHARS', 800)
KNOWLEDGE_CHUNK_OVERLAP = getattr(config, 'KNOWLEDGE_CHUNK_OVERLAP', 100)
KNOWLEDGE_MAX_FILE_MB = getattr(config, 'KNOWLEDGE_MAX_FILE_MB', 20)
KNOWLEDGE_ENABLE_LOG = getattr(config, 'KNOWLEDGE_ENABLE_LOG', True)

# Supported file extensions
KNOWLEDGE_EXTENSIONS = ['.pdf', '.docx', '.doc', '.txt', '.md', '.json', '.log', '.ini', '.cfg', '.xlsx']


# ═══════════════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════════════

_index = {}  # {chunk_id: {text, embedding, filepath, chunk_idx, mtime}}
_index_lock = threading.Lock()
_watcher_thread = None
_watcher_running = threading.Event()
_last_index_time = 0.0


# ═══════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════

def _log(action, details):
    if not KNOWLEDGE_ENABLE_LOG:
        return
    try:
        log_path = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "knowledge_log.jsonl")
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# TEXT EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

def _extract_text(filepath):
    """Extract plaintext from a file. Returns string or None."""
    ext = os.path.splitext(filepath)[1].lower()

    try:
        # Plain text files
        if ext in ('.txt', '.md', '.log', '.ini', '.cfg', '.json'):
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        # PDF
        if ext == '.pdf':
            try:
                import pypdf
                reader = pypdf.PdfReader(filepath)
                return "\n".join(p.extract_text() or "" for p in reader.pages)
            except ImportError:
                import subprocess
                subprocess.run([sys.executable, "-m", "pip", "install", "pypdf"],
                             check=True, capture_output=True)
                import pypdf
                reader = pypdf.PdfReader(filepath)
                return "\n".join(p.extract_text() or "" for p in reader.pages)

        # Word documents
        if ext in ('.docx', '.doc'):
            try:
                import docx
                doc = docx.Document(filepath)
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                import subprocess
                subprocess.run([sys.executable, "-m", "pip", "install", "python-docx"],
                             check=True, capture_output=True)
                import docx
                doc = docx.Document(filepath)
                return "\n".join(p.text for p in doc.paragraphs)

        # Excel (bonus)
        if ext == '.xlsx':
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

    except Exception as e:
        print(f"[KnowledgeInjector]: Error extracting {os.path.basename(filepath)}: {e}")
        return None

    return None


# ═══════════════════════════════════════════════════════════════════════
# CHUNKING
# ═══════════════════════════════════════════════════════════════════════

def _chunk_text(text):
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + KNOWLEDGE_CHUNK_CHARS
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - KNOWLEDGE_CHUNK_OVERLAP
        if start >= len(text):
            break
    return chunks


# ═══════════════════════════════════════════════════════════════════════
# EMBEDDING
# ═══════════════════════════════════════════════════════════════════════

def _get_embedding(text):
    """Get embedding from Ollama nomic-embed-text."""
    try:
        import requests
        # Try /api/embed first (newer Ollama)
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/embed",
            json={"model": config.EMBEDDING_MODEL, "input": text},
            timeout=10
        )
        if r.status_code == 200:
            embs = r.json().get("embeddings", [])
            if embs:
                return embs[0]
    except Exception:
        pass

    try:
        # Fallback to /api/embeddings
        import requests
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/embeddings",
            json={"model": config.EMBEDDING_MODEL, "prompt": text},
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("embedding")
    except Exception:
        pass

    return None


def _cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════════════════
# INDEXING
# ═══════════════════════════════════════════════════════════════════════

def _index_file(filepath):
    """Index a single file: extract, chunk, embed, store."""
    try:
        filename = os.path.basename(filepath)

        # Skip README files and other system-generated files
        if filename.upper() in ('README.TXT', 'README.MD', 'README'):
            return 0

        stat = os.stat(filepath)
        mtime = stat.st_mtime
        size_mb = stat.st_size / (1024 * 1024)

        if size_mb > KNOWLEDGE_MAX_FILE_MB:
            print(f"[KnowledgeInjector]: Skipping {filename} ({size_mb:.1f}MB > {KNOWLEDGE_MAX_FILE_MB}MB limit)")
            return 0

        # Check if already indexed and unchanged
        existing_chunks = [c for c in _index.values() if c.get("filepath") == filepath]
        if existing_chunks and existing_chunks[0].get("mtime") == mtime:
            return 0  # Already indexed, no changes

        # Remove old chunks for this file
        with _index_lock:
            to_remove = [k for k, v in _index.items() if v.get("filepath") == filepath]
            for k in to_remove:
                del _index[k]

        # Extract text
        text = _extract_text(filepath)
        if not text or len(text.strip()) < 20:
            return 0

        # Smart chunking: if the text is small enough (< 2000 chars),
        # keep it as ONE chunk to avoid cutting data in half.
        # This is critical for tables, grades, and structured documents
        # where chunk boundaries can split rows.
        if len(text) <= 2000:
            chunks = [text.strip()]
        else:
            chunks = _chunk_text(text)

        if not chunks:
            return 0

        # Embed each chunk
        new_chunks = {}
        chunk_count = 0
        for i, chunk in enumerate(chunks):
            embedding = _get_embedding(chunk)
            if embedding:
                chunk_id = f"{filename}_{i}"
                new_chunks[chunk_id] = {
                    "text": chunk,
                    "embedding": embedding,
                    "filepath": filepath,
                    "filename": filename,
                    "chunk_idx": i,
                    "mtime": mtime,
                }
                chunk_count += 1

        # Add to index
        with _index_lock:
            _index.update(new_chunks)

        return chunk_count

    except Exception as e:
        print(f"[KnowledgeInjector]: Error indexing {os.path.basename(filepath)}: {e}")
        return 0


def index_knowledge_directory(verbose=False):
    """
    Scan the knowledge directory and index all supported files.
    Returns total number of chunks indexed.
    """
    global _last_index_time

    if not os.path.exists(KNOWLEDGE_DIR):
        os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
        # Create README
        readme_path = os.path.join(KNOWLEDGE_DIR, "README.txt")
        if not os.path.exists(readme_path):
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(KNOWLEDGE_README)
        if verbose:
            print(f"[KnowledgeInjector]: Created knowledge directory at {KNOWLEDGE_DIR}")
        return 0

    total_chunks = 0
    files_indexed = 0

    for filename in os.listdir(KNOWLEDGE_DIR):
        filepath = os.path.join(KNOWLEDGE_DIR, filename)
        if not os.path.isfile(filepath):
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext not in KNOWLEDGE_EXTENSIONS:
            continue

        chunks = _index_file(filepath)
        if chunks > 0:
            files_indexed += 1
            total_chunks += chunks
            if verbose:
                print(f"[KnowledgeInjector]: Indexed '{filename}' — {chunks} chunks")

    _last_index_time = time.time()

    if verbose and total_chunks > 0:
        print(f"[KnowledgeInjector]: Index complete — {files_indexed} files, {total_chunks} chunks")
    elif verbose and total_chunks == 0:
        print(f"[KnowledgeInjector]: No files to index (drop files in {KNOWLEDGE_DIR})")

    _log("index_complete", {"files": files_indexed, "chunks": total_chunks})
    return total_chunks


# ═══════════════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════════════

def search_knowledge(query, max_results=None, min_score=None):
    """
    Search the knowledge index for chunks relevant to the query.
    Returns list of dicts: [{filename, filepath, snippet, score}]

    Tier 4 Smart: Uses a LOW threshold (0.30) by default so JARVIS always
    finds potentially relevant content. The caller decides whether to use it.
    """
    if max_results is None:
        max_results = KNOWLEDGE_MAX_CHUNKS_INJECTED

    # Smart: use a low threshold for auto-injection so we catch more relevant content
    if min_score is None:
        min_score = 0.30  # Low threshold — always search, let the model decide relevance

    with _index_lock:
        if not _index:
            return []

    # ── FILENAME-BASED MATCHING ──────────────────────────────────────
    # Check if any words in the query match words in the filenames.
    # If so, boost those files' scores significantly.
    # This helps when the user names files descriptively:
    #   "show me my enrolled subjects" → matches "Subjects and schedule.pdf"
    #   "whats my grades" → matches "Parsu-Grades-1st year college.pdf"
    query_words = set(query.lower().replace("-", " ").replace("_", " ").split())
    filename_boost = {}  # {filename: boost_amount}

    with _index_lock:
        all_filenames = set(c.get("filename", "") for c in _index.values())

    for filename in all_filenames:
        if not filename:
            continue
        # Extract words from filename (remove extension, split on spaces/hyphens/underscores)
        fname_clean = filename.lower()
        # Remove common extensions
        for ext in ['.pdf', '.docx', '.doc', '.txt', '.md', '.json', '.xlsx', '.csv']:
            fname_clean = fname_clean.replace(ext, '')
        fname_words = set(fname_clean.replace("-", " ").replace("_", " ").split())

        # Count how many query words match filename words
        matching_words = query_words.intersection(fname_words)
        if matching_words:
            # Boost: 0.15 per matching word (capped at 0.45)
            boost = min(0.45, len(matching_words) * 0.15)
            filename_boost[filename] = boost
            print(f"[KnowledgeInjector]: Filename match — '{filename}' boosted by {boost:.2f} (matched: {matching_words})")

    # Get query embedding
    query_embedding = _get_embedding(query)
    if not query_embedding:
        # If embedding fails but we have filename matches, return those files' chunks
        if filename_boost:
            with _index_lock:
                fallback_results = []
                for chunk_id, chunk_data in _index.items():
                    fname = chunk_data.get("filename", "")
                    if fname in filename_boost:
                        fallback_results.append({
                            "filename": fname,
                            "filepath": chunk_data["filepath"],
                            "snippet": chunk_data["text"][:1200].strip(),
                            "score": filename_boost[fname],
                            "chunk_idx": chunk_data["chunk_idx"],
                        })
            if fallback_results:
                return fallback_results[:max_results]
        return []

    # Score all chunks
    scored = []
    with _index_lock:
        for chunk_id, chunk_data in _index.items():
            chunk_emb = chunk_data.get("embedding")
            fname = chunk_data.get("filename", "")
            if chunk_emb and len(chunk_emb) == len(query_embedding):
                score = _cosine_similarity(query_embedding, chunk_emb)
                # Apply filename boost
                if fname in filename_boost:
                    score += filename_boost[fname]
                if score >= min_score:
                    scored.append({
                        "filename": fname,
                        "filepath": chunk_data["filepath"],
                        "snippet": chunk_data["text"][:1200].strip(),
                        "score": round(score, 3),
                        "chunk_idx": chunk_data["chunk_idx"],
                    })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    return scored[:max_results]


def build_knowledge_manifest():
    """
    Build a manifest of all knowledge files — a summary of what's available.
    This is injected into the system prompt so the 8B always knows what
    knowledge files exist and what they contain.

    Returns a string like:
      "Knowledge files available:
       - my_resume.pdf (24 chunks): John Doe, Software Engineer, 5 years experience...
       - project_notes.md (8 chunks): Project Jarvis, Phase 6, routing upgrade...
       - api_docs.json (3 chunks): REST API, endpoints, authentication..."
    """
    with _index_lock:
        if not _index:
            return ""

        # Group chunks by file
        files = {}
        for chunk_data in _index.values():
            filepath = chunk_data.get("filepath", "")
            if filepath not in files:
                files[filepath] = {
                    "filename": chunk_data["filename"],
                    "chunks": [],
                    "count": 0,
                }
            files[filepath]["chunks"].append(chunk_data["text"])
            files[filepath]["count"] += 1

    if not files:
        return ""

    lines = [f"Knowledge files available ({len(files)} files, {sum(f['count'] for f in files.values())} chunks):"]
    for filepath, info in files.items():
        # Use the first chunk as a preview (first 100 chars)
        preview = info["chunks"][0][:100].strip().replace("\n", " ") if info["chunks"] else ""
        lines.append(f"  - {info['filename']} ({info['count']} chunks): {preview}...")

    return "\n".join(lines)


def build_knowledge_context(query):
    """
    Build a formatted knowledge context string for injection into the system prompt.

    Tier 4 Smart: ALWAYS searches (low threshold 0.30), and includes:
    1. A manifest of all available knowledge files (so the 8B knows what exists)
    2. The top 3 most relevant chunks for this specific query

    This means JARVIS always knows what knowledge files are available,
    and proactively includes relevant content without needing keyword detection.
    """
    if not KNOWLEDGE_INJECTOR_ENABLED:
        return ""

    # Always include the manifest (so the 8B knows what files exist)
    manifest = build_knowledge_manifest()

    # Always search with low threshold (catch more relevant content)
    # Use up to 10 chunks for auto-injection (generous, but not overwhelming)
    results = search_knowledge(query, max_results=10, min_score=0.30)

    if not manifest and not results:
        return ""

    lines = []

    # Include manifest if we have knowledge files
    if manifest:
        lines.append(manifest)
        lines.append("")

    # Include relevant chunks if found
    if results:
        lines.append("Relevant excerpts for this query:")
        for r in results:
            lines.append(f"  [{r['filename']} (relevance: {r['score']})]")
            lines.append(f"  {r['snippet'][:800]}")  # Up to 800 chars per chunk in auto-injection
            lines.append("")
    elif manifest:
        lines.append("(No highly relevant excerpts found for this query, but the files above are available — use search_knowledge tool if needed.)")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# DIRECTORY WATCHER
# ═══════════════════════════════════════════════════════════════════════

def _watcher_loop():
    """Background thread that watches the knowledge directory for changes."""
    while _watcher_running.is_set():
        try:
            # Check if any files changed
            if os.path.exists(KNOWLEDGE_DIR):
                current_mtime = os.path.getmtime(KNOWLEDGE_DIR)
                if current_mtime != getattr(_watcher_loop, '_last_dir_mtime', 0):
                    _watcher_loop._last_dir_mtime = current_mtime
                    # Re-index
                    chunks = index_knowledge_directory(verbose=False)
                    if chunks > 0:
                        print(f"[KnowledgeInjector]: Re-indexed — {len(_index)} total chunks")
        except Exception as e:
            print(f"[KnowledgeInjector]: Watcher error: {e}")

        time.sleep(KNOWLEDGE_WATCH_INTERVAL)


def start_knowledge_watcher():
    """Start the background knowledge directory watcher."""
    global _watcher_thread

    if not KNOWLEDGE_INJECTOR_ENABLED:
        return

    if _watcher_thread is not None and _watcher_thread.is_alive():
        return

    # Do an initial index
    chunks = index_knowledge_directory(verbose=True)

    # Start the watcher thread
    _watcher_running.set()
    _watcher_thread = threading.Thread(target=_watcher_loop, daemon=True, name="knowledge-watcher")
    _watcher_thread.start()
    print(f"[KnowledgeInjector]: Watching '{KNOWLEDGE_DIR}' for changes (interval: {KNOWLEDGE_WATCH_INTERVAL}s)")


def stop_knowledge_watcher():
    """Stop the background watcher."""
    _watcher_running.clear()
    if _watcher_thread:
        _watcher_thread.join(timeout=2)


# ═══════════════════════════════════════════════════════════════════════
# TOOL FUNCTION (for toolRegistry)
# ═══════════════════════════════════════════════════════════════════════

def search_knowledge_tool(query):
    """
    Tool function for the tool registry.
    Searches knowledge files and returns formatted results.
    Uses a low threshold (0.25) to catch as much relevant content as possible.
    Returns up to 20 results with FULL chunk content (no truncation).
    """
    # Max 20 chunks × ~800 chars = ~16,000 chars ≈ 4,000 tokens
    # Well within the 8B's 32K context window
    results = search_knowledge(query, max_results=20, min_score=0.25)
    if not results:
        return "No relevant information found in your knowledge files, Sir."

    # ── FILE ISOLATION: Group results by filename and keep only the MOST relevant file ──
    # This prevents mixing data from different files (e.g., grades PDF + schedule PDF)
    # when the user is asking about one specific topic.
    from collections import defaultdict
    file_groups = defaultdict(list)
    for r in results:
        file_groups[r['filename']].append(r)

    # Calculate average relevance per file
    file_avg_scores = {}
    for filename, chunks in file_groups.items():
        avg_score = sum(c['score'] for c in chunks) / len(chunks)
        file_avg_scores[filename] = avg_score

    # Sort files by average relevance (highest first)
    sorted_files = sorted(file_avg_scores.items(), key=lambda x: x[1], reverse=True)

    # Keep only the TOP file (most relevant)
    # If the top file's average score is significantly higher than the second,
    # only use the top file. If they're close (within 0.1), include both.
    best_file = sorted_files[0][0]
    best_score = sorted_files[0][1]

    if len(sorted_files) > 1:
        second_score = sorted_files[1][1]
        if best_score - second_score > 0.1:
            # Clear winner — only use the best file
            results = file_groups[best_file]
            print(f"[KnowledgeInjector]: File isolation — using only '{best_file}' (avg: {best_score:.3f}, 2nd: {second_score:.3f})")
        else:
            # Scores are close — include both files but label them clearly
            print(f"[KnowledgeInjector]: Multiple files relevant — keeping top files (scores within 0.1)")
    else:
        results = file_groups[best_file]

    lines = [f"Found {len(results)} relevant results from '{best_file}':"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n{i}. [{r['filename']} (relevance: {r['score']})]")
        lines.append(f"   {r['snippet']}")

    result_str = "\n".join(lines)

    # Generous limit — 20,000 chars ≈ 5,000 tokens (well within 32K context)
    if len(result_str) > 20000:
        result_str = result_str[:20000] + "\n... (some results truncated to fit context)"

    return result_str


# ═══════════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════════

def get_knowledge_stats():
    """Return statistics about the knowledge index."""
    with _index_lock:
        total_chunks = len(_index)
        files = set(c.get("filepath", "") for c in _index.values())
        return {
            "total_chunks": total_chunks,
            "total_files": len(files),
            "files": list(files),
            "directory": KNOWLEDGE_DIR,
            "last_index_time": datetime.fromtimestamp(_last_index_time).isoformat() if _last_index_time else None,
        }


# ═══════════════════════════════════════════════════════════════════════
# README
# ═══════════════════════════════════════════════════════════════════════

KNOWLEDGE_README = """JARVIS Knowledge Files Directory
================================

Drop files here that you want JARVIS to know about. The system will:
1. Extract text from each file
2. Chunk the text into ~800 character pieces
3. Embed each chunk with nomic-embed-text
4. Index them for semantic search

When you ask a question, JARVIS searches this index and injects
relevant content into its context, giving you answers based on
your actual documents.

SUPPORTED FILE TYPES:
  - PDF (.pdf)
  - Word (.docx, .doc)
  - Text (.txt, .md, .log, .ini, .cfg)
  - JSON (.json)
  - Excel (.xlsx)

EXAMPLE USES:
  - Drop your resume here → ask "What's in my resume?"
  - Drop meeting notes → ask "What did I decide last week?"
  - Drop API documentation → ask "What's the endpoint for X?"
  - Drop project notes → ask "What's the status of project Y?"

The system watches this directory for changes. When you add, modify,
or delete files, the index updates automatically within 10 seconds.

MAX FILE SIZE: 20 MB per file
CHUNK SIZE: 800 characters with 100 character overlap
"""


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Knowledge Injector (Tier 4)...\n")

    # Test 1: Check directory
    print("=== Knowledge Directory ===")
    print(f"  Path: {KNOWLEDGE_DIR}")
    print(f"  Exists: {os.path.exists(KNOWLEDGE_DIR)}")

    # Test 2: Index
    print(f"\n=== Indexing ===")
    chunks = index_knowledge_directory(verbose=True)
    print(f"  Total chunks: {chunks}")

    # Test 3: Stats
    print(f"\n=== Stats ===")
    stats = get_knowledge_stats()
    print(f"  {stats}")

    # Test 4: Search (if any files exist)
    if chunks > 0:
        print(f"\n=== Test Search ===")
        results = search_knowledge("test query")
        print(f"  Found {len(results)} results")
    else:
        print(f"\n=== No files to search ===")
        print(f"  Drop files in {KNOWLEDGE_DIR} to test search")
