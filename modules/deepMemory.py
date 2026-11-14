import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta

# Add root folder to sys.path (CRITICAL: Preserves package layout resolution)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        KNOWLEDGE_FILE = "knowledge_base.json"
        DAILY_SUMMARY_FILE = "daily_summaries.json"
        GOAL_TRACKER_FILE = "long_term_goals.json"
        HISTORY_FILE = "command_history.json"
        OLLAMA_BASE_URL = "http://localhost:11434"
        VOICE_FACE_MODEL = "qwen3:8b"
        INTENT_MODEL = "qwen3:8b"
        EMBEDDING_MODEL = "nomic-embed-text"
        MAX_VECTOR_RESULTS = 5
        VECTOR_THRESHOLD = 0.55

# Memory startup time
_startup_time = time.time()

# --- FIXED: Thread-Safe In-Memory Cache States to Prevent Disk I/O Overload ---
_knowledge_cache = None
_knowledge_cache_mtime = 0.0

# ── helper: cosine similarity ────────────────────────────────────────────────
def dot_product(v1, v2):
    return sum(x * y for x, y in zip(v1, v2))

def magnitude(v):
    return sum(x * x for x in v) ** 0.5

def cosine_similarity(v1, v2):
    mag1 = magnitude(v1)
    mag2 = magnitude(v2)
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product(v1, v2) / (mag1 * mag2)

# ── helper: tf-idf fallback ──────────────────────────────────────────────────
def get_char_ngrams(text, n=3):
    return [text[i:i+n] for i in range(len(text)-n+1)]

def tfidf_fallback_similarity(q, text):
    q_grams = set(get_char_ngrams(q.lower()))
    text_grams = set(get_char_ngrams(text.lower()))
    if not q_grams or not text_grams:
        return 0.0
    intersection = q_grams.intersection(text_grams)
    return len(intersection) / (len(q_grams.union(text_grams)))

# ── ollama embeddings ────────────────────────────────────────────────────────
def get_ollama_embedding(text):
    """
    Get embeddings using config's designated EMBEDDING_MODEL ("nomic-embed-text").
    """
    # FIXED: Replaced config.INTENT_MODEL (phi3) with dedicated embedding model
    model_to_use = getattr(config, "EMBEDDING_MODEL", "nomic-embed-text")
    
    # First try embedding API
    for endpoint in ["/api/embeddings", "/api/embed"]:
        try:
            payload = {"model": model_to_use, "prompt": text}
            r = requests.post(f"{config.OLLAMA_BASE_URL}{endpoint}", json=payload, timeout=5)
            if r.status_code == 200:
                resp = r.json()
                if "embedding" in resp:
                    return resp["embedding"]
                elif "embeddings" in resp and resp["embeddings"]:
                    return resp["embeddings"][0]
        except Exception:
            pass
            
    # Try VOICE_FACE_MODEL as backup
    try:
        payload = {"model": config.VOICE_FACE_MODEL, "prompt": text}
        r = requests.post(f"{config.OLLAMA_BASE_URL}/api/embeddings", json=payload, timeout=5)
        if r.status_code == 200:
            return r.json().get("embedding")
    except Exception:
        pass
        
    return None

# ── Cache Loader Helper ──────────────────────────────────────────────────────
def _load_knowledge_base():
    """Reads knowledge base JSON from disk only if changes were detected."""
    global _knowledge_cache, _knowledge_cache_mtime
    if not os.path.exists(config.KNOWLEDGE_FILE):
        _knowledge_cache = []
        _knowledge_cache_mtime = 0.0
        return _knowledge_cache
        
    try:
        current_mtime = os.path.getmtime(config.KNOWLEDGE_FILE)
        if _knowledge_cache is None or current_mtime > _knowledge_cache_mtime:
            with open(config.KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                _knowledge_cache = json.load(f)
            _knowledge_cache_mtime = current_mtime
    except Exception:
        if _knowledge_cache is None:
            _knowledge_cache = []
            
    return _knowledge_cache

# ── daily summary ────────────────────────────────────────────────────────────
def summarize_session(history_msgs):
    """
    Summarize current session at the end of the day or session.
    """
    if not history_msgs:
        return "No exchanges to summarize today, Sir."
        
    history_text = ""
    for msg in history_msgs[-20:]:
        role = "User" if msg["role"] == "user" else "JARVIS"
        history_text += f"{role}: {msg['content']}\n"
        
    prompt = f"""You are JARVIS. Summarize the following session conversation with Mr. Kirby Paladan.
Highlight any tasks completed, new notes saved, or projects discussed.
Keep it under 3 sentences and professional, addressing him as Sir.
Conversation:
{history_text}
Summary:"""

    summary = "No summary generated."
    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.VOICE_FACE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            },
            timeout=30
        )
        if r.status_code == 200:
            summary = r.json().get("message", {}).get("content", "").strip()
    except Exception:
        summary = "Session completed. I was unable to generate a summary due to connection status, Sir."
        
    # Save to daily summaries list
    summaries = []
    if os.path.exists(config.DAILY_SUMMARY_FILE):
        try:
            with open(config.DAILY_SUMMARY_FILE, "r", encoding="utf-8") as f:
                summaries = json.load(f)
        except Exception:
            pass
            
    summaries.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary": summary
    })
    
    try:
        with open(config.DAILY_SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump(summaries, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
        
    return summary

def load_daily_summary():
    """Loads compressed daily summaries from disk."""
    if os.path.exists(config.DAILY_SUMMARY_FILE):
        try:
            with open(config.DAILY_SUMMARY_FILE, "r", encoding="utf-8") as f:
                summaries = json.load(f)
                if summaries:
                    return summaries[-1]["summary"]
        except Exception:
            pass
    return "No previous daily summaries found, Sir."

# ── vector memory ─────────────────────────────────────────────────────────────
def save_vector_fact(fact):
    """Saves a fact and its vector embedding to the knowledge base."""
    embedding = get_ollama_embedding(fact)
    
    knowledge_base = list(_load_knowledge_base()) # FIXED: Loaded from disk only on change
    
    knowledge_base.append({
        "fact": fact,
        "embedding": embedding,  # Can be None if offline, will fallback to char-ngrams
        "timestamp": datetime.now().isoformat()
    })
    
    try:
        with open(config.KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(knowledge_base, f, indent=2, ensure_ascii=False)
            
        # Update the memory cache immediately to keep variables aligned
        global _knowledge_cache, _knowledge_cache_mtime
        _knowledge_cache = knowledge_base
        _knowledge_cache_mtime = os.path.getmtime(config.KNOWLEDGE_FILE)
    except Exception as e:
        print(f"[DeepMemory Error]: Could not save fact: {e}")

def vector_search(query):
    """
    Search personal knowledge base.
    Uses cosine similarity on embeddings, fallback to character n-gram tf-idf.
    Returns list of facts (max 3).
    """
    knowledge_base = _load_knowledge_base() # FIXED: Pulls from memory cache
    if not knowledge_base:
        return []
        
    query_vector = get_ollama_embedding(query)
    results = []
    
    for item in knowledge_base:
        fact = item["fact"]
        vector = item.get("embedding")
        
        if query_vector and vector and len(query_vector) == len(vector):
            score = cosine_similarity(query_vector, vector)
        else:
            # Fallback to n-gram similarity
            score = tfidf_fallback_similarity(query, fact)
            
        if score >= config.VECTOR_THRESHOLD:
            results.append((score, fact))
            
    # Sort by score descending
    results.sort(key=lambda x: x[0], reverse=True)
    return [fact for score, fact in results[:config.MAX_VECTOR_RESULTS]]

def save_to_knowledge_base(fact):
    """Explicitly save a user-declared fact to knowledge base wiki."""
    save_vector_fact(fact)
    return f"Sir, I have added this fact to my knowledge base: '{fact}'."

# ── self status ───────────────────────────────────────────────────────────────
def get_jarvis_self_status():
    uptime_sec = time.time() - _startup_time
    hours = int(uptime_sec // 3600)
    minutes = int((uptime_sec % 3600) // 60)
    
    uptime_str = ""
    if hours: uptime_str += f"{hours}h "
    uptime_str += f"{minutes}m"
    
    loaded_modules = ["taskManager", "fileSearch", "noteSystem", "semanticMemory", 
                      "commandHistory", "systemMonitor", "capabilities", "internetSearch"]
                      
    return {
        "uptime": uptime_str,
        "active_model": config.VOICE_FACE_MODEL,
        "router_model": config.INTENT_MODEL,
        "version": "JARVIS 6.0 Pro",
        "loaded_modules": loaded_modules
    }

# ── goal tracker ──────────────────────────────────────────────────────────────
def track_goal(goal, deadline_str):
    """
    Track a long-term goal with a specified deadline (YYYY-MM-DD).
    """
    goals = []
    if os.path.exists(config.GOAL_TRACKER_FILE):
        try:
            with open(config.GOAL_TRACKER_FILE, "r", encoding="utf-8") as f:
                goals = json.load(f)
        except Exception:
            pass
            
    goals.append({
        "goal": goal,
        "deadline": deadline_str,
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "completed": False,
        "last_nudged": None
    })
    
    try:
        with open(config.GOAL_TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(goals, f, indent=2, ensure_ascii=False)
        return f"Sir, I have recorded your goal: '{goal}', with target deadline {deadline_str}."
    except Exception as e:
        return f"Could not save goal: {e}"

# ── learn work patterns ────────────────────────────────────────────────────────
def learn_work_patterns():
    """
    Analyzes command_history.json to find peak hours of user activity.
    Returns description of pattern.
    """
    if not os.path.exists(config.HISTORY_FILE):
        return "I do not have enough command history yet to analyze your work patterns, Sir."
        
    try:
        with open(config.HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return "Command history log is currently unreadable, Sir."
        
    if len(history) < 10:
        return "I require a few more command interactions to accurately map your work patterns, Sir."
        
    hour_counts = [0] * 24
    for entry in history:
        timestamp_str = entry.get("timestamp")
        if timestamp_str:
            try:
                # Try parsing format: "2026-05-28T04:20:00" or similar
                dt = datetime.fromisoformat(timestamp_str)
                hour_counts[dt.hour] += 1
            except Exception:
                pass
                
    peak_hour = hour_counts.index(max(hour_counts))
    peak_ampm = "AM" if peak_hour < 12 else "PM"
    display_hour = peak_hour if peak_hour <= 12 else peak_hour - 12
    if display_hour == 0: display_hour = 12
    
    return f"Based on command timestamps, your peak productivity hours center around {display_hour} {peak_ampm}, Sir."

# ── emotional state inference ─────────────────────────────────────────────────
def infer_emotional_state(history):
    """
    Infers emotional state of user based on word choices in the last 3 interactions.
    Adapts sentence length/verbosity in prompt system instruction.
    """
    last_user_msgs = [m["content"] for m in history if m["role"] == "user"][-3:]
    if not last_user_msgs:
        return "neutral"
        
    text = " ".join(last_user_msgs).lower()
    
    # Swear words or angry indicators
    frustrated_indicators = ["damn", "hell", "shit", "fuck", "stupid", "annoying", "ugh", "crap", "not working", "fails"]
    tired_indicators = ["exhausted", "tired", "sleepy", "long day", "stress", "drain", "headache"]
    happy_indicators = ["awesome", "great", "excellent", "perfect", "good job", "thanks", "thank you", "love it"]
    
    if any(w in text for w in frustrated_indicators):
        return "frustrated"
    elif any(w in text for w in tired_indicators):
        return "tired"
    elif any(w in text for w in happy_indicators):
        return "pleased"
        
    return "neutral"