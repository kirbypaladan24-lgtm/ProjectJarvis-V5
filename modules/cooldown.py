"""
JARVIS Tool Cooldown System
================================================================
Suppresses tools that misfire repeatedly.
If a tool misfires 3+ times in 30 seconds, raise the selection bar
or suppress it entirely for a cooldown period.
"""
import os
import sys
import time
import threading
from collections import defaultdict, deque

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════

MISFIRE_WINDOW = 30        # seconds — count misfires in this window
MISFIRE_THRESHOLD = 3      # misfires before cooldown activates
COOLDOWN_DURATION = 60     # seconds — how long to suppress the tool


# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

_misfire_log = defaultdict(deque)  # {tool_name: deque of timestamps}
_cooldown_until = {}  # {tool_name: timestamp when cooldown ends}
_lock = threading.Lock()


# ═════════════════════════════════════════════════════════════
# API
# ═════════════════════════════════════════════════════════════

def log_misfire(tool_name):
    """Log that a tool misfired (was called incorrectly)."""
    now = time.time()
    with _lock:
        # Add to log
        _misfire_log[tool_name].append(now)

        # Prune old entries
        while _misfire_log[tool_name] and now - _misfire_log[tool_name][0] > MISFIRE_WINDOW:
            _misfire_log[tool_name].popleft()

        # Check if threshold reached
        if len(_misfire_log[tool_name]) >= MISFIRE_THRESHOLD:
            _cooldown_until[tool_name] = now + COOLDOWN_DURATION
            print(f"[Cooldown]: '{tool_name}' misfired {len(_misfire_log[tool_name])}x in {MISFIRE_WINDOW}s — on cooldown for {COOLDOWN_DURATION}s")


def log_success(tool_name):
    """Log that a tool call succeeded — resets the misfire counter."""
    with _lock:
        if tool_name in _misfire_log:
            _misfire_log[tool_name].clear()


def is_on_cooldown(tool_name):
    """Check if a tool is currently on cooldown."""
    now = time.time()
    with _lock:
        if tool_name not in _cooldown_until:
            return False
        if now >= _cooldown_until[tool_name]:
            # Cooldown expired — clear it
            del _cooldown_until[tool_name]
            _misfire_log[tool_name].clear()
            return False
        return True


def get_cooldown_remaining(tool_name):
    """Get seconds remaining on cooldown (0 if not on cooldown)."""
    now = time.time()
    with _lock:
        if tool_name not in _cooldown_until:
            return 0
        remaining = _cooldown_until[tool_name] - now
        return max(0, round(remaining))


def get_misfire_count(tool_name):
    """Get current misfire count for a tool (in the window)."""
    now = time.time()
    with _lock:
        # Prune old entries
        while _misfire_log[tool_name] and now - _misfire_log[tool_name][0] > MISFIRE_WINDOW:
            _misfire_log[tool_name].popleft()
        return len(_misfire_log[tool_name])


def get_confidence_penalty(tool_name):
    """
    Returns 0.0-1.0 — how much to penalize this tool's selection confidence.
    0.0 = no penalty, 1.0 = full suppression.
    """
    if is_on_cooldown(tool_name):
        return 1.0  # Full suppression

    misfires = get_misfire_count(tool_name)
    # Each misfire adds 15% penalty, up to 60%
    return min(0.6, misfires * 0.15)


def get_cooldown_status():
    """Get status of all tools on cooldown (for dashboard)."""
    now = time.time()
    with _lock:
        status = {}
        for tool, until in _cooldown_until.items():
            remaining = until - now
            if remaining > 0:
                status[tool] = {
                    "cooldown_remaining": round(remaining),
                    "misfires": len(_misfire_log.get(tool, [])),
                }
        return status


def clear_all():
    """Clear all cooldowns and misfire logs (for testing)."""
    with _lock:
        _misfire_log.clear()
        _cooldown_until.clear()


if __name__ == "__main__":
    # Test
    print("Testing cooldown system...\n")

    print(f"set_volume on cooldown: {is_on_cooldown('set_volume')}")
    print(f"Misfire count: {get_misfire_count('set_volume')}")

    print("\nLogging 3 misfires...")
    log_misfire("set_volume")
    log_misfire("set_volume")
    log_misfire("set_volume")

    print(f"\nset_volume on cooldown: {is_on_cooldown('set_volume')}")
    print(f"Confidence penalty: {get_confidence_penalty('set_volume')}")
    print(f"Cooldown remaining: {get_cooldown_remaining('set_volume')}s")

    print(f"\nCooldown status: {get_cooldown_status()}")
