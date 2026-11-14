"""
Pre-build tool embeddings cache.
Run this ONCE before running tts.py for the first time.

After this completes, JARVIS will load instantly — no 30-second wait on first query.

Usage:
    py build_tool_cache.py
"""
import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))

print("=" * 60)
print("  JARVIS Tool Embeddings Cache Builder")
print("=" * 60)
print()
print("This will embed all 60 tool descriptions using nomic-embed-text.")
print("It takes about 30-60 seconds, but only needs to run ONCE.")
print("After this, JARVIS will start up instantly.")
print()
print("Make sure Ollama is running: ollama serve")
print()

# Check Ollama is reachable
import requests
try:
    r = requests.get("http://localhost:11434/api/tags", timeout=5)
    if r.status_code != 200:
        print("ERROR: Ollama is not responding. Start it with: ollama serve")
        sys.exit(1)
    models = [m["name"] for m in r.json().get("models", [])]
    if not any("nomic-embed-text" in m for m in models):
        print("ERROR: nomic-embed-text model not found in Ollama.")
        print("Pull it with: ollama pull nomic-embed-text")
        sys.exit(1)
    print(f"[OK] Ollama is running with {len(models)} models available.")
except Exception as e:
    print(f"ERROR: Cannot connect to Ollama: {e}")
    print("Start it with: ollama serve")
    sys.exit(1)

print()
print("Loading tool registry...")
try:
    from toolRegistry import get_all_tools
    tools = get_all_tools()
    print(f"[OK] {len(tools)} tools registered.")
except Exception as e:
    print(f"ERROR loading tool registry: {e}")
    sys.exit(1)

print()
print("Building embeddings cache (this is the one-time slow part)...")
start_time = time.time()

try:
    from toolEmbeddings import initialize_embeddings
    initialize_embeddings()
except Exception as e:
    print(f"ERROR building embeddings: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

elapsed = time.time() - start_time

from toolEmbeddings import get_cache_size, is_initialized

print()
print("=" * 60)
print(f"  DONE in {elapsed:.1f} seconds")
print(f"  Cached {get_cache_size()} tool embeddings")
print(f"  Initialized: {is_initialized()}")
print("=" * 60)
print()
print("You can now run JARVIS — it will start up instantly:")
print()
print("    py tts.py")
print()
