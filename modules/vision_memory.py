"""
JARVIS Vision Memory
================================================================
Stores LLaVA/Qwen VL descriptions in a vector database.
Enables queries like "what was that thing I showed you yesterday?"

Usage:
    from vision_memory import VisionMemory

    vm = VisionMemory()
    vm.store("capture.jpg", "A red coffee mug on a wooden desk")
    results = vm.search("red mug")
    # Returns: [{"description": "A red coffee mug...", "timestamp": "...", "path": "capture.jpg"}]
"""
import os
import sys
import json
import time
import threading
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = "."
        OLLAMA_BASE_URL = "http://localhost:11434"
        EMBEDDING_MODEL = "nomic-embed-text"


# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

_STORAGE_FILE = os.path.join(getattr(config, 'BASE_DIR', '.'), "vision_memory.json")
_lock = threading.Lock()


# ═════════════════════════════════════════════════════════════
# VISION MEMORY CLASS
# ═════════════════════════════════════════════════════════════

class VisionMemory:
    """Stores and retrieves vision descriptions with embeddings."""

    def __init__(self):
        self._memories = []
        self._load()

    def _load(self):
        """Load memories from disk."""
        with _lock:
            try:
                if os.path.exists(_STORAGE_FILE):
                    with open(_STORAGE_FILE, 'r') as f:
                        self._memories = json.load(f)
                    print(f"[VisionMemory]: Loaded {len(self._memories)} memories.")
            except Exception as e:
                print(f"[VisionMemory]: Load error: {e}")
                self._memories = []

    def _save(self):
        """Save memories to disk."""
        with _lock:
            try:
                with open(_STORAGE_FILE, 'w') as f:
                    json.dump(self._memories, f, indent=2)
            except Exception as e:
                print(f"[VisionMemory]: Save error: {e}")

    def _get_embedding(self, text):
        """Get embedding for a piece of text."""
        try:
            import requests
            # Try /api/embed first
            try:
                r = requests.post(
                    f"{config.OLLAMA_BASE_URL}/api/embed",
                    json={"model": config.EMBEDDING_MODEL, "input": text},
                    timeout=10
                )
                if r.status_code == 200:
                    embeddings = r.json().get("embeddings", [])
                    if embeddings:
                        return embeddings[0]
            except Exception:
                pass

            # Fallback to /api/embeddings
            r = requests.post(
                f"{config.OLLAMA_BASE_URL}/api/embeddings",
                json={"model": config.EMBEDDING_MODEL, "prompt": text},
                timeout=10
            )
            if r.status_code == 200:
                return r.json().get("embedding", [])
        except Exception as e:
            print(f"[VisionMemory]: Embedding error: {e}")
        return None

    def _cosine_similarity(self, a, b):
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def store(self, image_path, description, source="camera"):
        """
        Store a vision memory.

        Args:
            image_path: Path to the image file (for reference)
            description: LLaVA/Qwen VL description of the image
            source: "camera" or "screen"
        """
        # Get embedding for the description
        embedding = self._get_embedding(description)

        entry = {
            "id": len(self._memories) + 1,
            "timestamp": datetime.now().isoformat(),
            "image_path": image_path,
            "description": description,
            "source": source,
            "embedding": embedding,
        }

        with _lock:
            self._memories.append(entry)
            # Keep last 500 memories
            if len(self._memories) > 500:
                self._memories = self._memories[-500:]

        self._save()
        print(f"[VisionMemory]: Stored memory #{entry['id']} ({source})")
        return entry["id"]

    def search(self, query, top_k=5, source=None):
        """
        Search vision memories by semantic similarity.

        Args:
            query: What to search for
            top_k: Max results
            source: Filter by "camera" or "screen" (optional)
        """
        query_emb = self._get_embedding(query)
        if not query_emb:
            # Fallback to keyword search
            return self._keyword_search(query, top_k, source)

        # Score each memory
        scored = []
        for mem in self._memories:
            if source and mem.get("source") != source:
                continue
            if mem.get("embedding"):
                score = self._cosine_similarity(query_emb, mem["embedding"])
            else:
                # No embedding — use keyword match
                if query.lower() in mem.get("description", "").lower():
                    score = 0.5
                else:
                    score = 0.0
            scored.append((score, mem))

        # Sort by score descending
        scored.sort(key=lambda x: -x[0])

        # Return top K
        results = []
        for score, mem in scored[:top_k]:
            results.append({
                "id": mem["id"],
                "description": mem["description"],
                "timestamp": mem["timestamp"],
                "image_path": mem.get("image_path", ""),
                "source": mem.get("source", ""),
                "score": round(score, 3),
            })

        return results

    def _keyword_search(self, query, top_k=5, source=None):
        """Fallback keyword search when embeddings aren't available."""
        query_lower = query.lower()
        scored = []

        for mem in self._memories:
            if source and mem.get("source") != source:
                continue
            desc = mem.get("description", "").lower()
            if query_lower in desc:
                # Simple relevance: count keyword occurrences
                score = desc.count(query_lower) / len(desc.split())
            else:
                score = 0.0
            scored.append((score, mem))

        scored.sort(key=lambda x: -x[0])

        return [{
            "id": mem["id"],
            "description": mem["description"],
            "timestamp": mem["timestamp"],
            "image_path": mem.get("image_path", ""),
            "source": mem.get("source", ""),
            "score": round(score, 3),
        } for score, mem in scored[:top_k]]

    def get_recent(self, limit=10, source=None):
        """Get recent memories."""
        with _lock:
            mems = self._memories[-limit:] if not source else [m for m in self._memories if m.get("source") == source][-limit:]
        return [{
            "id": m["id"],
            "description": m["description"],
            "timestamp": m["timestamp"],
            "source": m.get("source", ""),
        } for m in reversed(mems)]

    def clear(self):
        """Clear all memories."""
        with _lock:
            self._memories = []
        self._save()

    def count(self):
        """Get total memory count."""
        return len(self._memories)


# ═════════════════════════════════════════════════════════════
# SINGLETON
# ═════════════════════════════════════════════════════════════

_vm_instance = None

def get_vision_memory():
    """Get the singleton VisionMemory instance."""
    global _vm_instance
    if _vm_instance is None:
        _vm_instance = VisionMemory()
    return _vm_instance


# ═════════════════════════════════════════════════════════════
# TEST
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Vision Memory...\n")

    # Use temp file for testing
    import tempfile
    _STORAGE_FILE = tempfile.mktemp(suffix=".json")

    vm = VisionMemory()

    # Test store
    print("Storing memories...")
    vm.store("cam1.jpg", "A red coffee mug on a wooden desk next to a laptop", "camera")
    vm.store("cam2.jpg", "A blue pen and a notebook on a white table", "camera")
    vm.store("screen1.jpg", "A code editor with Python code on the screen", "screen")
    vm.store("cam3.jpg", "A red car parked outside the window", "camera")

    print(f"  Stored {vm.count()} memories")

    # Test keyword search (no embeddings needed)
    print("\nKeyword search: 'red'")
    results = vm._keyword_search("red", top_k=3)
    for r in results:
        print(f"  [{r['score']:.3f}] {r['description'][:60]}...")
    assert len(results) >= 2  # "red coffee mug" and "red car"
    print("  ✅ Keyword search works")

    # Test recent
    print("\nRecent memories:")
    recent = vm.get_recent(limit=3)
    for r in recent:
        print(f"  #{r['id']} ({r['source']}): {r['description'][:60]}...")
    assert len(recent) == 3
    print("  ✅ Recent works")

    # Test source filter
    print("\nRecent camera only:")
    camera_recent = vm.get_recent(limit=10, source="camera")
    for r in camera_recent:
        print(f"  #{r['id']} ({r['source']}): {r['description'][:60]}...")
    assert all(r["source"] == "camera" for r in camera_recent)
    print("  ✅ Source filter works")

    # Test clear
    vm.clear()
    assert vm.count() == 0
    print("\n  ✅ Clear works")

    # Cleanup
    os.remove(_STORAGE_FILE)

    print("\nAll Vision Memory tests passed ✅")
