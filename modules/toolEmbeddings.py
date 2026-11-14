"""
JARVIS Tool Embeddings (UPGRADED 2026-08)
================================================================
Caches embeddings of all tool descriptions.
Used to pre-filter which tools to show Qwen 3 based on user input.

FIXES:
    - Caches embeddings to disk (embed once, load instantly forever)
    - Initializes in background thread at startup (first query doesn't block)
    - Falls back to "all tools" if not ready yet (no waiting)
"""
import os
import sys
import json
import time
import threading

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        OLLAMA_BASE_URL = "http://localhost:11434"
        EMBEDDING_MODEL = "nomic-embed-text"
        TOOL_PRE_FILTER_K = 12
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import requests


# ─────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────

_tool_embeddings = {}  # {tool_name: embedding_vector}
_embeddings_lock = threading.Lock()
_embeddings_initialized = False
_init_in_progress = False
_init_failed = False

# Cache file path — embeddings persist across runs
_CACHE_FILE = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "tool_embeddings_cache.json")


# ─────────────────────────────────────────────────────────────
# EMBEDDING API
# ─────────────────────────────────────────────────────────────

def _get_embedding(text):
    """Get embedding for a piece of text from Ollama."""
    # Try the /api/embed endpoint first (newer Ollama)
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/embed",
            json={
                "model": config.EMBEDDING_MODEL,
                "input": text,
            },
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            embeddings = data.get("embeddings", [])
            if embeddings:
                return embeddings[0]
    except Exception:
        pass

    # Fallback to /api/embeddings (older Ollama)
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/embeddings",
            json={
                "model": config.EMBEDDING_MODEL,
                "prompt": text,
            },
            timeout=10
        )
        if response.status_code == 200:
            return response.json().get("embedding", [])
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


# ─────────────────────────────────────────────────────────────
# DISK CACHE
# ─────────────────────────────────────────────────────────────

def _load_cache_from_disk():
    """Load cached embeddings from disk if available."""
    global _tool_embeddings
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                _tool_embeddings = json.load(f)
            print(f"[ToolEmbeddings]: Loaded {len(_tool_embeddings)} cached embeddings from disk.")
            return True
    except Exception as e:
        print(f"[ToolEmbeddings]: Cache load failed: {e}")
    return False


def _save_cache_to_disk():
    """Save current embeddings to disk for future runs."""
    try:
        with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_tool_embeddings, f)
        print(f"[ToolEmbeddings]: Saved {len(_tool_embeddings)} embeddings to cache.")
    except Exception as e:
        print(f"[ToolEmbeddings]: Cache save failed: {e}")


# ─────────────────────────────────────────────────────────────
# INITIALIZATION (background thread)
# ─────────────────────────────────────────────────────────────

def initialize_embeddings_async():
    """
    Start background thread to load/init embeddings.
    Non-blocking — returns immediately. Embeddings become available when ready.
    """
    global _init_in_progress

    with _embeddings_lock:
        if _embeddings_initialized or _init_in_progress:
            return
        _init_in_progress = True

    t = threading.Thread(target=_init_worker, daemon=True, name="tool-embeddings-init")
    t.start()
    return t


def _init_worker():
    """Background worker: load from disk if available, otherwise embed all tools."""
    global _embeddings_initialized, _init_in_progress, _init_failed

    try:
        # Step 1: Try to load from disk cache (instant)
        if _load_cache_from_disk():
            with _embeddings_lock:
                _embeddings_initialized = True
                _init_in_progress = False
            return

        # Step 2: No cache — embed all tool descriptions (slow, one-time)
        from toolRegistry import get_all_tools

        tools = get_all_tools()
        print(f"[ToolEmbeddings]: First-run setup — embedding {len(tools)} tools (one-time, ~30 seconds)...")

        for i, tool in enumerate(tools):
            name = tool["function"]["name"]
            description = tool["function"]["description"]

            emb = _get_embedding(description)
            if emb:
                with _embeddings_lock:
                    _tool_embeddings[name] = emb
            else:
                print(f"[ToolEmbeddings]: Failed to embed '{name}'")

            # Progress update every 10 tools
            if (i + 1) % 10 == 0:
                print(f"[ToolEmbeddings]: {i + 1}/{len(tools)} done...")

        # Save to disk for next run
        _save_cache_to_disk()

        with _embeddings_lock:
            _embeddings_initialized = True
            _init_in_progress = False

        print(f"[ToolEmbeddings]: Ready — {len(_tool_embeddings)} embeddings loaded.")

    except Exception as e:
        print(f"[ToolEmbeddings]: Init failed: {e}")
        with _embeddings_lock:
            _init_failed = True
            _init_in_progress = False


def initialize_embeddings():
    """Synchronous init — blocks until done. Only use at startup or in tests."""
    _init_worker()


# ─────────────────────────────────────────────────────────────
# QUERY (returns immediately, falls back if not ready)
# ─────────────────────────────────────────────────────────────

def select_relevant_tools(user_input, top_k=None):
    """
    Return the top-K most relevant tools for the given user input.

    If embeddings aren't ready yet (still loading in background), returns ALL tools
    so the router can proceed without waiting. Next query will benefit from the cache.
    """
    if top_k is None:
        top_k = getattr(config, 'TOOL_PRE_FILTER_K', 12)

    # Lazy init — start background thread if not started
    if not _embeddings_initialized and not _init_in_progress:
        initialize_embeddings_async()

    # If not ready yet, return all tools (graceful fallback — no blocking!)
    if not _embeddings_initialized:
        from toolRegistry import get_all_tools
        return get_all_tools()

    # If init failed, also return all tools
    if _init_failed or not _tool_embeddings:
        from toolRegistry import get_all_tools
        return get_all_tools()

    # Embed user input
    query_emb = _get_embedding(user_input)
    if not query_emb:
        from toolRegistry import get_all_tools
        return get_all_tools()

    # Score each tool
    with _embeddings_lock:
        scores = [(name, _cosine_similarity(query_emb, emb))
                  for name, emb in _tool_embeddings.items()]

    # Sort by score descending
    scores.sort(key=lambda x: -x[1])

    # Get top-K tool names
    top_names = [name for name, _ in scores[:top_k]]

    # Always include chat_only
    if "chat_only" not in top_names:
        top_names.append("chat_only")

    # Convert to Ollama tool format
    from toolRegistry import get_tool, _tool_to_ollama_format
    result = []
    for name in top_names:
        tool = get_tool(name)
        if tool:
            result.append(_tool_to_ollama_format(tool))

    return result


def is_initialized():
    """Check if embeddings have been loaded."""
    return _embeddings_initialized


def get_cache_size():
    """Return number of cached tool embeddings."""
    return len(_tool_embeddings)


# ─────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing tool embeddings (with disk cache)...")

    # First call — may take 30s if no cache exists
    print("\n--- Test 1: 'set volume to 50' ---")
    selected = select_relevant_tools("set volume to 50", top_k=5)
    for t in selected:
        print(f"  - {t['function']['name']}")

    print(f"\nCache size: {get_cache_size()}")
    print(f"Initialized: {is_initialized()}")

    # Second call — should be instant
    print("\n--- Test 2: 'play some Drake' (should be instant) ---")
    selected = select_relevant_tools("play some Drake", top_k=5)
    for t in selected:
        print(f"  - {t['function']['name']}")
