"""
JARVIS Shadow Mode
================================================================
Runs a "shadow" routing path alongside the active path.
Both paths process every input, but only the active path's result
is shown to the user. The shadow path's result is logged for comparison.

This lets you test routing changes safely — you can see what the NEW
router WOULD have picked, without affecting the user experience.

Usage:
    from shadow_mode import shadow_route, get_shadow_stats

    # In toolRouter.py, after getting the real result:
    if shadow_mode.is_enabled():
        shadow_result = shadow_route(user_input, history)
        shadow_mode.log_comparison(user_input, real_result, shadow_result)
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


# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

_enabled = False
_log = []
_lock = threading.Lock()
_MAX_LOG = 500  # Keep last 500 comparisons


# ═════════════════════════════════════════════════════════════
# API
# ═════════════════════════════════════════════════════════════

def enable():
    """Enable shadow mode."""
    global _enabled
    _enabled = True
    print("[ShadowMode]: Enabled — shadow routing will run alongside active path.")


def disable():
    """Disable shadow mode."""
    global _enabled
    _enabled = False
    print("[ShadowMode]: Disabled.")


def is_enabled():
    """Check if shadow mode is enabled."""
    return _enabled


def shadow_route(user_input, history=None):
    """
    Run the shadow routing path.
    This calls the SAME route_with_tools function but logs the result
    instead of returning it to the user.

    In a real A/B test, you'd call a DIFFERENT routing function here
    (e.g., a new experimental router). For now, it uses the same router
    but logs the decision for comparison.

    Returns the shadow result dict.
    """
    if not _enabled:
        return None

    try:
        # Import here to avoid circular dependency
        from toolRouter import _route_with_tools_internal

        start = time.time()
        shadow_result = _route_with_tools_internal(user_input, history)
        elapsed = time.time() - start

        shadow_result["elapsed"] = elapsed
        return shadow_result

    except Exception as e:
        print(f"[ShadowMode]: Shadow route error: {e}")
        return None


def log_comparison(user_input, real_result, shadow_result):
    """
    Log a comparison between the real and shadow routing decisions.
    Called after both paths have run.
    """
    if not _enabled or not shadow_result:
        return

    real_tool = real_result.get("tools_used", ["chat_only"])[0] if real_result.get("tools_used") else "chat_only"
    shadow_tool = shadow_result.get("tools_used", ["chat_only"])[0] if shadow_result.get("tools_used") else "chat_only"

    real_tier = real_result.get("fast_path", "qwen3_tool_use")
    shadow_tier = shadow_result.get("fast_path", "qwen3_tool_use")

    match = (real_tool == shadow_tool) and (real_tier == shadow_tier)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "input": user_input[:200],
        "real_tool": real_tool,
        "real_tier": real_tier,
        "shadow_tool": shadow_tool,
        "shadow_tier": shadow_tier,
        "match": match,
        "real_elapsed": real_result.get("elapsed", 0),
        "shadow_elapsed": shadow_result.get("elapsed", 0),
    }

    with _lock:
        _log.append(entry)
        if len(_log) > _MAX_LOG:
            del _log[:-_MAX_LOG]  # Trim in place instead of reassigning

    # Print mismatches for immediate visibility
    if not match:
        print(f"[ShadowMode]: MISMATCH — real={real_tool}/{real_tier}, shadow={shadow_tool}/{shadow_tier}")


def get_shadow_stats():
    """Get statistics about shadow mode comparisons."""
    with _lock:
        if not _log:
            return {"total": 0, "matches": 0, "mismatches": 0, "match_rate": 0}

        total = len(_log)
        matches = sum(1 for e in _log if e["match"])
        mismatches = total - matches

        # Find most common mismatches
        mismatch_patterns = {}
        for e in _log:
            if not e["match"]:
                key = f"{e['real_tool']} -> {e['shadow_tool']}"
                mismatch_patterns[key] = mismatch_patterns.get(key, 0) + 1

        return {
            "total": total,
            "matches": matches,
            "mismatches": mismatches,
            "match_rate": round(matches / total * 100, 1) if total > 0 else 0,
            "mismatch_patterns": mismatch_patterns,
            "recent": _log[-10:],
        }


def save_log():
    """Save shadow log to disk."""
    try:
        log_file = os.path.join(getattr(config, 'BASE_DIR', '.'), "shadow_log.json")
        with open(log_file, 'w') as f:
            json.dump(_log, f, indent=2)
    except Exception as e:
        print(f"[ShadowMode]: Save error: {e}")


def clear_log():
    """Clear the shadow log."""
    with _lock:
        _log.clear()


if __name__ == "__main__":
    print("Testing shadow mode...\n")

    enable()
    print(f"Enabled: {is_enabled()}")

    # Simulate comparisons
    log_comparison("set volume to 50",
                   {"tools_used": ["set_volume"], "fast_path": "pattern_match", "elapsed": 0.1},
                   {"tools_used": ["set_volume"], "fast_path": "pattern_match", "elapsed": 0.1})

    log_comparison("play Drake",
                   {"tools_used": ["spotify_play"], "fast_path": "pattern_match", "elapsed": 0.1},
                   {"tools_used": ["spotify_play"], "fast_path": "simple_tool_1.5b", "elapsed": 1.5})

    log_comparison("hello",
                   {"tools_used": ["chat_only"], "fast_path": "acknowledgment", "elapsed": 0.0},
                   {"tools_used": ["chat_only"], "fast_path": "casual_chat_1.5b", "elapsed": 1.2})

    stats = get_shadow_stats()
    print(f"\nStats: {stats['total']} comparisons")
    print(f"  Matches: {stats['matches']} ({stats['match_rate']}%)")
    print(f"  Mismatches: {stats['mismatches']}")
    print(f"  Patterns: {stats['mismatch_patterns']}")
