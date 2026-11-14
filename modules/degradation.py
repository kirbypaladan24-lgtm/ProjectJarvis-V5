"""
JARVIS Graceful Degradation Matrix
================================================================
Explicit fallback chain for every component.
When a component fails, automatically fall back to the next.

Usage:
    from degradation import with_fallback, DegradationError

    @with_fallback("qwen3", fallback_chain=["llama3.2", "1.5b", "pattern_only"])
    def call_qwen3(prompt):
        ...
"""
import os
import sys
import functools
import threading

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═════════════════════════════════════════════════════════════
# DEGRADATION STATE
# ═════════════════════════════════════════════════════════════

# Track which components are currently "down" (with cooldown)
_component_status = {}  # {component: {"available": bool, "last_fail": timestamp, "fail_count": int}}
_lock = threading.Lock()

# Cooldown period: if a component fails, don't retry for 60 seconds
COOLDOWN_SECONDS = 60


# ═════════════════════════════════════════════════════════════
# FALLBACK CHAINS
# ═════════════════════════════════════════════════════════════

FALLBACK_CHAINS = {
    "qwen3": ["llama3.2-uncensored", "1.5b", "pattern_only", "acknowledgment_only"],
    "llama3.2-uncensored": ["1.5b", "pattern_only", "acknowledgment_only"],
    "1.5b": ["pattern_only", "acknowledgment_only"],
    "nomic-embed": ["skip_prefilter", "all_tools"],
    "vision_qwen_vl": ["vision_llava_format", "vision_skip"],
    "spotify_api": ["spotify_app_direct", "skip"],
    "internet": ["skip_web_tools", "chat_only"],
    "telegram": ["skip", "console_only"],
}


def mark_component_failed(component):
    """Mark a component as failed (will be on cooldown for 60s)."""
    import time
    with _lock:
        _component_status[component] = {
            "available": False,
            "last_fail": time.time(),
            "fail_count": _component_status.get(component, {}).get("fail_count", 0) + 1,
        }
        print(f"[Degradation]: '{component}' marked as failed (cooldown {COOLDOWN_SECONDS}s)")


def mark_component_available(component):
    """Mark a component as available again."""
    with _lock:
        if component in _component_status:
            _component_status[component]["available"] = True
            _component_status[component]["fail_count"] = 0


def is_available(component):
    """Check if a component is available (not on cooldown)."""
    import time
    with _lock:
        status = _component_status.get(component)
        if not status:
            return True  # Default: available
        if status["available"]:
            return True
        # Check if cooldown expired
        if time.time() - status["last_fail"] > COOLDOWN_SECONDS:
            status["available"] = True
            return True
        return False


def get_fallback(component):
    """Get the next fallback in the chain for a component."""
    chain = FALLBACK_CHAINS.get(component, [])
    for fallback in chain:
        if is_available(fallback):
            return fallback
    return None


def get_status_report():
    """Get a status report of all components."""
    import time
    with _lock:
        report = {}
        for comp, status in _component_status.items():
            report[comp] = {
                "available": status["available"] or (time.time() - status["last_fail"] > COOLDOWN_SECONDS),
                "fail_count": status["fail_count"],
                "last_fail_ago": round(time.time() - status["last_fail"], 0) if status.get("last_fail") else None,
            }
        return report


# ═════════════════════════════════════════════════════════════
# DECORATOR
# ═════════════════════════════════════════════════════════════

def with_fallback(component, fallback_chain=None):
    """
    Decorator that catches exceptions and marks the component as failed.
    The caller should check is_available() before calling and use get_fallback() to find alternatives.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not is_available(component):
                raise DegradationError(f"Component '{component}' is on cooldown")
            try:
                result = func(*args, **kwargs)
                mark_component_available(component)
                return result
            except Exception as e:
                mark_component_failed(component)
                raise
        return wrapper
    return decorator


class DegradationError(Exception):
    """Raised when a component is on cooldown."""
    pass


# ═════════════════════════════════════════════════════════════
# MODEL FALLBACK
# ═════════════════════════════════════════════════════════════

def get_available_model(preferred_model, model_type="chat"):
    """
    Get an available model, falling back through the chain if needed.
    model_type: "chat" | "vision" | "embedding"
    """
    try:
        import config
    except ImportError:
        return preferred_model

    if model_type == "chat":
        chain = [
            preferred_model,
            getattr(config, 'FALLBACK_MODEL', 'artifish/llama3.2-uncensored'),
            getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
        ]
    elif model_type == "vision":
        chain = [
            preferred_model,
            getattr(config, 'VISION_MODEL_DETAIL', 'llama3.2-vision:11b'),
            getattr(config, 'VISION_MODEL_FAST', 'redule26/huihui_ai_qwen2.5-vl-7b-abliterated'),
        ]
    elif model_type == "embedding":
        chain = [preferred_model]
    else:
        chain = [preferred_model]

    for model in chain:
        if is_available(model):
            return model

    # All on cooldown — return the preferred one anyway (last resort)
    return preferred_model


def check_ollama_health():
    """Quick health check of Ollama."""
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def get_system_health():
    """Get overall system health for the dashboard."""
    ollama_ok = check_ollama_health()

    return {
        "ollama": "healthy" if ollama_ok else "down",
        "components": get_status_report(),
        "timestamp": __import__('datetime').datetime.now().isoformat(),
    }
