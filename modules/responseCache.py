import os
import sys
import time
import json

# Add root folder to sys.path (CRITICAL: Resolves parent directory configuration files)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        RESPONSE_CACHE_FILE = "response_cache.json"
        RESPONSE_CACHE_TTL = 300  # 5 minutes
        ENABLE_RESPONSE_CACHE = True

_cache = {}
_cache_loaded = False  # <-- FIXED: Track if memory cache is loaded

def load_cache():
    """Reads JSON once from disk and populates memory cache to prevent redundant disk I/O."""
    global _cache, _cache_loaded
    if _cache_loaded:
        return
        
    if os.path.exists(config.RESPONSE_CACHE_FILE):
        try:
            with open(config.RESPONSE_CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    else:
        _cache = {}
        
    _cache_loaded = True

def save_cache():
    try:
        with open(config.RESPONSE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def get_cached(query):
    """
    Looks up query in cache. If hit and within TTL, returns the response.
    Utilizes the in-memory cache to prevent blocking Disk reads.
    """
    if not getattr(config, "ENABLE_RESPONSE_CACHE", True):
        return None

    load_cache()  # Loads from disk exactly once on first call
    q_key = query.lower().strip()
    if q_key in _cache:
        entry = _cache[q_key]
        timestamp = entry.get("timestamp", 0)
        if time.time() - timestamp < config.RESPONSE_CACHE_TTL:
            print(f"[Cache Hit]: Found cached response for query '{query}'")
            return entry.get("response")
        else:
            # Expired
            del _cache[q_key]
            save_cache()
    return None

def set_cache(query, response):
    """
    Caches the response. Skips dynamic time/news/diagnostic/music queries.
    """
    if not getattr(config, "ENABLE_RESPONSE_CACHE", True):
        return

    q_key = query.lower().strip()
    
    # Skips time/date/news/weather/diagnostics
    skip_keywords = [
        "time", "date", "weather", "news", "specs", "diagnostics", 
        "wifi", "status", "playing", "volume", "brightness", "timer", 
        "reminder", "screentext", "running apps", "clipboard"
    ]
    
    if any(kw in q_key for kw in skip_keywords):
        return
        
    load_cache()  # Ensure cache is initialized before writing
    _cache[q_key] = {
        "response": response,
        "timestamp": time.time()
    }
    save_cache()