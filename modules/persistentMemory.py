"""
Tier 3.1: Persistent Cross-Session Memory for deepMemory.py

Adds auto-learning capability that extracts facts from conversations
and persists them across sessions. Currently, facts are only saved when
the user explicitly says "save fact" or "remember that". This new system
automatically identifies memorable information and stores it.

New functions:
  - auto_learn_from_exchange(user_msg, assistant_msg) — called after each exchange
  - extract_facts_with_llm(text) — uses 8B to identify memorable facts
  - get_relevant_memories(query, max_results=3) — retrieves facts for context injection
  - build_memory_context(query) — returns formatted memory string for system prompt
  - cleanup_old_memories(max_age_days=90) — prunes stale entries

Storage format (persistent_memory.json):
  [
    {
      "fact": "User's name is Kirby",
      "category": "personal_info",
      "embedding": [...],
      "timestamp": "2026-08-09T...",
      "source": "auto_learned" | "explicit",
      "confidence": 0.85
    }
  ]
"""
import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = _PARENT_DIR
        OLLAMA_BASE_URL = "http://localhost:11434"
        VOICE_FACE_MODEL = "qwen3:8b"
        EMBEDDING_MODEL = "nomic-embed-text"
        KNOWLEDGE_FILE = os.path.join(_PARENT_DIR, "knowledge_base.json")

import requests

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

PERSISTENT_MEMORY_ENABLED    = getattr(config, 'PERSISTENT_MEMORY_ENABLED', True)
PERSISTENT_MEMORY_FILE       = getattr(config, 'PERSISTENT_MEMORY_FILE',
    os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "persistent_memory.json"))
PERSISTENT_MEMORY_MAX_FACTS  = getattr(config, 'PERSISTENT_MEMORY_MAX_FACTS', 500)
PERSISTENT_MEMORY_MAX_AGE_DAYS = getattr(config, 'PERSISTENT_MEMORY_MAX_AGE_DAYS', 90)
PERSISTENT_MEMORY_THRESHOLD  = getattr(config, 'PERSISTENT_MEMORY_THRESHOLD', 0.55)
PERSISTENT_MEMORY_AUTO_LEARN_INTERVAL = getattr(config, 'PERSISTENT_MEMORY_AUTO_LEARN_INTERVAL', 5)
PERSISTENT_MEMORY_ENABLE_LOG = getattr(config, 'PERSISTENT_MEMORY_ENABLE_LOG', True)

# Categories for organizing facts
_FACT_CATEGORIES = {
    "personal_info": ["name is", "my name", "i am", "i'm", "i live", "i work", "my job", "my birthday"],
    "preferences": ["i like", "i prefer", "i love", "i hate", "i don't like", "favorite", "i always"],
    "schedule": ["i have", "meeting at", "appointment", "deadline", "i need to", "i should"],
    "project": ["working on", "project", "building", "developing", "my code", "the repo"],
    "environment": ["my laptop", "my pc", "my computer", "i use", "running on", "connected to"],
}

# Patterns that should NOT be auto-learned (transient commands, not facts)
_SKIP_PATTERNS = [
    "what's the weather", "set volume", "play ", "pause", "open ", "close ",
    "search for", "find ", "take a screenshot", "set timer", "set brightness",
    "hello", "thanks", "bye", "ok", "yes", "no", "cancel", "confirm",
]

# ═══════════════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════════════

_memory_cache = None
_memory_cache_mtime = 0.0
_memory_lock = threading.Lock()
_exchange_count = 0  # Counter for auto-learn interval


# ═══════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════

def _log(action, details):
    if not PERSISTENT_MEMORY_ENABLE_LOG:
        return
    try:
        log_path = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "memory_log.jsonl")
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
# STORAGE
# ═══════════════════════════════════════════════════════════════════════

def _load_memory():
    """Load persistent memory from disk with mtime-based cache."""
    global _memory_cache, _memory_cache_mtime

    if not os.path.exists(PERSISTENT_MEMORY_FILE):
        _memory_cache = []
        _memory_cache_mtime = 0.0
        return []

    try:
        mtime = os.path.getmtime(PERSISTENT_MEMORY_FILE)
        if _memory_cache is not None and mtime == _memory_cache_mtime:
            return _memory_cache

        with open(PERSISTENT_MEMORY_FILE, 'r', encoding='utf-8') as f:
            _memory_cache = json.load(f)
        _memory_cache_mtime = mtime
        return _memory_cache
    except Exception as e:
        print(f"[PersistentMemory]: Load failed: {e}")
        return []


def _save_memory(memories):
    """Save memories to disk and update cache."""
    global _memory_cache, _memory_cache_mtime

    with _memory_lock:
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(PERSISTENT_MEMORY_FILE), exist_ok=True)

            with open(PERSISTENT_MEMORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(memories, f, indent=2, ensure_ascii=False)
            _memory_cache = memories
            _memory_cache_mtime = os.path.getmtime(PERSISTENT_MEMORY_FILE)
            return True
        except Exception as e:
            print(f"[PersistentMemory]: Save failed: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════
# EMBEDDING (reuse from deepMemory if available, otherwise inline)
# ═══════════════════════════════════════════════════════════════════════

def _get_embedding(text):
    """Get embedding for a piece of text."""
    try:
        from deepMemory import get_ollama_embedding
        return get_ollama_embedding(text)
    except Exception:
        # Fallback: inline embedding
        try:
            r = requests.post(
                f"{config.OLLAMA_BASE_URL}/api/embed",
                json={"model": config.EMBEDDING_MODEL, "input": text},
                timeout=5
            )
            if r.status_code == 200:
                embs = r.json().get("embeddings", [])
                if embs:
                    return embs[0]
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
# FACT EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

def _should_skip(user_msg):
    """Check if this message should be skipped (transient command, not a fact)."""
    msg_lower = user_msg.lower().strip()
    if len(msg_lower) < 10:
        return True
    for pattern in _SKIP_PATTERNS:
        if pattern in msg_lower:
            return True
    return False


def _categorize_fact(fact):
    """Categorize a fact based on keywords."""
    fact_lower = fact.lower()
    for category, keywords in _FACT_CATEGORIES.items():
        if any(kw in fact_lower for kw in keywords):
            return category
    return "general"


def extract_facts_with_llm(text):
    """
    Use the 8B model to extract memorable facts from a conversation exchange.
    Returns a list of fact strings.
    """
    prompt = f"""You are JARVIS's memory system. Analyze the following text and extract any FACTS worth remembering about the user.

A "fact worth remembering" is:
- Personal information (name, location, job, birthday)
- Preferences (likes, dislikes, favorites)
- Recurring patterns (always checks news at 8am, always pauses spotify before meetings)
- Project context (working on X, deadline for Y)
- Environment details (laptop model, setup details)

NOT worth remembering:
- Transient commands (set volume, play music, open chrome)
- Questions (what's the weather)
- Greetings (hello, thanks, bye)
- Tool results (weather data, search results)

Text to analyze:
"{text[:1000]}"

Extract facts as a JSON array of strings. If no facts found, return empty array [].
Examples:
["User's name is Kirby", "User works as a software developer", "User prefers dark mode"]
[]

Respond with ONLY the JSON array:"""

    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.VOICE_FACE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": 100, "temperature": 0.2},
                "keep_alive": config.get_keep_alive(config.VOICE_FACE_MODEL),
                "format": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            timeout=15
        )
        if response.status_code == 200:
            content = response.json().get("message", {}).get("content", "").strip()
            try:
                facts = json.loads(content)
                if isinstance(facts, list):
                    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]
            except json.JSONDecodeError:
                pass
    except Exception as e:
        print(f"[PersistentMemory]: Fact extraction error: {e}")

    return []


def _is_duplicate(new_fact, memories, threshold=0.85):
    """Check if a fact is too similar to an existing one."""
    new_embedding = _get_embedding(new_fact)
    if not new_embedding:
        # Fallback to text comparison
        new_lower = new_fact.lower()
        for mem in memories:
            if new_lower in mem.get("fact", "").lower() or mem.get("fact", "").lower() in new_lower:
                return True
        return False

    for mem in memories:
        mem_embedding = mem.get("embedding")
        if mem_embedding and len(mem_embedding) == len(new_embedding):
            sim = _cosine_similarity(new_embedding, mem_embedding)
            if sim >= threshold:
                return True
    return False


def save_fact(fact, category=None, source="auto_learned", confidence=0.8):
    """
    Save a fact to persistent memory.
    Returns True if saved, False if duplicate or failed.
    """
    if not PERSISTENT_MEMORY_ENABLED:
        return False

    fact = fact.strip()
    if not fact or len(fact) < 5:
        return False

    memories = list(_load_memory())

    # Check for duplicates
    if _is_duplicate(fact, memories):
        return False

    # Categorize
    if category is None:
        category = _categorize_fact(fact)

    # Get embedding
    embedding = _get_embedding(fact)

    # Add to memory
    memory_entry = {
        "fact": fact,
        "category": category,
        "embedding": embedding,
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "confidence": confidence,
    }

    memories.append(memory_entry)

    # Enforce max facts (remove oldest if over limit)
    if len(memories) > PERSISTENT_MEMORY_MAX_FACTS:
        memories = memories[-PERSISTENT_MEMORY_MAX_FACTS:]

    if _save_memory(memories):
        _log("fact_saved", {"fact": fact[:100], "category": category, "source": source})
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# AUTO-LEARNING
# ═══════════════════════════════════════════════════════════════════════

def auto_learn_from_exchange(user_msg, assistant_msg):
    """
    Called after each conversation exchange. Periodically extracts facts
    from the exchange and saves them to persistent memory.

    The extraction runs every N exchanges (PERSISTENT_MEMORY_AUTO_LEARN_INTERVAL)
    to avoid calling the LLM on every single message (which would add latency).

    Args:
        user_msg: The user's message text
        assistant_msg: JARVIS's response text
    """
    global _exchange_count

    if not PERSISTENT_MEMORY_ENABLED:
        return

    # Skip transient commands
    if _should_skip(user_msg):
        return

    _exchange_count += 1

    # Only extract every N exchanges
    if _exchange_count % PERSISTENT_MEMORY_AUTO_LEARN_INTERVAL != 0:
        return

    # Build the text to analyze (last few exchanges for context)
    text = f"User: {user_msg}\nJARVIS: {assistant_msg}"

    # Run extraction in a background thread to avoid blocking
    def _extract_and_save():
        try:
            facts = extract_facts_with_llm(text)
            if facts:
                print(f"[PersistentMemory]: Extracted {len(facts)} facts from exchange")
                for fact in facts:
                    save_fact(fact, source="auto_learned")
        except Exception as e:
            print(f"[PersistentMemory]: Auto-learn error: {e}")

    threading.Thread(target=_extract_and_save, daemon=True).start()


def get_relevant_memories(query, max_results=3):
    """
    Retrieve memories relevant to a query using embedding similarity.
    Returns a list of fact strings.
    """
    if not PERSISTENT_MEMORY_ENABLED:
        return []

    memories = _load_memory()
    if not memories:
        return []

    query_embedding = _get_embedding(query)
    if not query_embedding:
        # Fallback: return most recent memories
        recent = sorted(memories, key=lambda m: m.get("timestamp", ""), reverse=True)
        return [m["fact"] for m in recent[:max_results]]

    # Score each memory
    scored = []
    for mem in memories:
        mem_embedding = mem.get("embedding")
        if mem_embedding and len(mem_embedding) == len(query_embedding):
            score = _cosine_similarity(query_embedding, mem_embedding)
        else:
            # Fallback to text matching
            score = _text_similarity(query, mem.get("fact", ""))

        if score >= PERSISTENT_MEMORY_THRESHOLD:
            scored.append((score, mem["fact"]))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    return [fact for score, fact in scored[:max_results]]


def _text_similarity(a, b):
    """Simple text similarity fallback when embeddings aren't available."""
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    if not a_words or not b_words:
        return 0.0
    intersection = a_words.intersection(b_words)
    return len(intersection) / max(len(a_words), len(b_words))


def build_memory_context(query):
    """
    Build a formatted memory context string for injection into the system prompt.
    Returns a string like:
      "Known facts about the user:
       - User's name is Kirby
       - User prefers dark mode"
    Or empty string if no relevant memories.
    """
    if not PERSISTENT_MEMORY_ENABLED:
        return ""

    memories = get_relevant_memories(query, max_results=3)
    if not memories:
        return ""

    lines = ["Known facts about the user (from persistent memory):"]
    for fact in memories:
        lines.append(f"  - {fact}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# MAINTENANCE
# ═══════════════════════════════════════════════════════════════════════

def cleanup_old_memories(max_age_days=None):
    """
    Remove memories older than max_age_days.
    Called automatically on startup or manually.
    """
    if max_age_days is None:
        max_age_days = PERSISTENT_MEMORY_MAX_AGE_DAYS

    memories = _load_memory()
    if not memories:
        return 0

    cutoff = datetime.now() - timedelta(days=max_age_days)
    cutoff_str = cutoff.isoformat()

    original_count = len(memories)
    memories = [m for m in memories if m.get("timestamp", "") >= cutoff_str]
    removed = original_count - len(memories)

    if removed > 0:
        _save_memory(memories)
        _log("cleanup", {"removed": removed, "remaining": len(memories)})
        print(f"[PersistentMemory]: Cleaned up {removed} old memories (max age: {max_age_days} days)")

    return removed


def get_memory_stats():
    """Return statistics about the persistent memory store."""
    memories = _load_memory()
    if not memories:
        return {"total": 0, "categories": {}, "sources": {}}

    categories = {}
    sources = {}
    for m in memories:
        cat = m.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1
        src = m.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    return {
        "total": len(memories),
        "categories": categories,
        "sources": sources,
        "file": PERSISTENT_MEMORY_FILE,
    }


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Persistent Memory (Tier 3.1)...\n")

    # Test 1: Categorization
    print("=== Fact Categorization ===")
    test_facts = [
        "User's name is Kirby",
        "User prefers dark mode",
        "User has a meeting at 3pm",
        "User is working on project jarvis",
        "User's laptop is an ASUS ROG",
    ]
    for fact in test_facts:
        cat = _categorize_fact(fact)
        print(f"  {cat:15s} | {fact}")

    # Test 2: Skip detection
    print("\n=== Skip Detection ===")
    test_msgs = [
        ("set volume to 50", True),
        ("hello", True),
        ("my name is Kirby and I work as a developer", False),
        ("what's the weather", True),
        ("I prefer using VS Code for Python development", False),
    ]
    for msg, expected in test_msgs:
        result = _should_skip(msg)
        label = "SKIP" if result else "KEEP"
        match = "OK" if result == expected else "FAIL"
        print(f"  [{match}] [{label}] '{msg}'")

    # Test 3: Memory stats
    print(f"\n=== Memory Stats ===")
    stats = get_memory_stats()
    print(f"  {stats}")
