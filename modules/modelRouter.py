import os
import sys
import requests
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        VOICE_FACE_MODEL     = "qwen2.5:7b-instruct"
        INTENT_MODEL         = "fervent_mcclintock/Qwen2.5-Coder-0.5B-Instruct:Q8_0"
        CODE_MODEL           = "deepseek-coder:6.7b"
        FALLBACK_MODEL       = "llama3:instruct"
        CONFIDENCE_THRESHOLD = 0.70
        OLLAMA_BASE_URL      = "http://localhost:11434"

_health_cache            = None
_health_cache_last_checked = 0.0
_HEALTH_CACHE_TTL        = 60.0   # 60s — models don't restart mid-session


def _fetch_health(timeout: float) -> dict | None:
    """
    Single attempt to fetch /api/tags and build a health dict.
    Returns None on any network/timeout failure.
    Returns the health dict (may have all-False) on success.
    """
    health = {
        config.VOICE_FACE_MODEL: False,
        config.INTENT_MODEL:     False,
        config.CODE_MODEL:       False,
        config.FALLBACK_MODEL:   False,
    }
    try:
        r = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        if r.status_code != 200:
            return None

        # Case-insensitive substring match handles digest suffixes and mixed-case model names
        available = [m["name"].lower() for m in r.json().get("models", [])]
        if not available:
            return None   # Empty list = Ollama still loading — don't cache yet

        for m_key in health:
            key_lower = m_key.lower()
            if any(key_lower in name or name in key_lower for name in available):
                health[m_key] = True

        return health
    except Exception:
        return None


def check_model_health(force: bool = False) -> dict:
    """
    Return a {model_name: bool} health map.
    Uses a 60s TTL cache. On startup (force=True) retries up to 3x with longer timeout
    so the brain board doesn't poison the cache with false FAILs.
    """
    global _health_cache, _health_cache_last_checked

    now = time.time()
    if (not force
            and _health_cache is not None
            and (now - _health_cache_last_checked) < _HEALTH_CACHE_TTL):
        return _health_cache

    # Startup path: retry with progressively longer timeouts
    attempts = [(3.0, 0), (5.0, 1.0), (8.0, 2.0)] if force else [(5.0, 0)]

    for timeout, wait in attempts:
        if wait:
            time.sleep(wait)
        result = _fetch_health(timeout)
        if result is not None:
            _health_cache            = result
            _health_cache_last_checked = time.time()

            # Print a debug line only on startup so you can see what Ollama returned
            if force:
                passing = [k for k, v in result.items() if v]
                print(f"[ModelRouter]: {len(passing)}/{len(result)} models healthy.")
            return result

    # All attempts failed — return last cache or all-False without caching
    if _health_cache is not None:
        return _health_cache
    return {k: False for k in [config.VOICE_FACE_MODEL, config.INTENT_MODEL,
                                config.CODE_MODEL, config.FALLBACK_MODEL]}


def get_active_models() -> list:
    return [m for m, ok in check_model_health().items() if ok]


def route_request(user_input, intent, confidence) -> str:
    health = check_model_health()

    if confidence < config.CONFIDENCE_THRESHOLD:
        if health.get(config.FALLBACK_MODEL):
            return config.FALLBACK_MODEL

    if intent in ("code", "codebase") or "code" in intent:
        if health.get(config.CODE_MODEL):
            return config.CODE_MODEL

    if health.get(config.VOICE_FACE_MODEL):
        return config.VOICE_FACE_MODEL

    for m in [config.VOICE_FACE_MODEL, config.FALLBACK_MODEL,
              config.INTENT_MODEL, config.CODE_MODEL]:
        if health.get(m):
            return m

    return config.VOICE_FACE_MODEL   # Ultimate fallback — attempt anyway


def escalate_to_fallback(user_input, system_prompt, history) -> str:
    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model":    config.FALLBACK_MODEL,
                "messages": history + [{"role": "user", "content": user_input}],
                "stream":   False,
                "system":   system_prompt,
            },
            timeout=60
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"Error escalating to fallback model: {e}"
    return "I am having trouble routing this request, Sir."