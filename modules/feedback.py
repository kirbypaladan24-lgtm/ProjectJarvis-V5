"""
JARVIS Implicit Feedback Loop
================================================================
Detects user dissatisfaction signals and tags routing decisions
as "likely correct" or "likely wrong".

Signals:
- User repeats a command within 30s = likely wrong
- User says "no" or "cancel" after a tool call = wrong tool
- User re-phrases the same request = misrouted
- Silence/no follow-up = likely correct
"""
import os
import sys
import time
import threading
from collections import deque
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════

REPEAT_WINDOW = 30          # seconds — if user repeats within this window, likely wrong
CANCEL_KEYWORDS = [         # words that indicate wrong tool was called
    "no", "nope", "cancel", "stop", "wrong", "not that",
    "i meant", "i wanted", "not what i wanted", "try again",
    "never mind", "forget it", "different",
]
REPHRASE_THRESHOLD = 0.6    # similarity threshold for rephrasing detection


# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

_recent_commands = deque(maxlen=20)  # [(timestamp, input, tool_used, tier)]
_feedback_log = []
_lock = threading.Lock()


# ═════════════════════════════════════════════════════════════
# TRACKING
# ═════════════════════════════════════════════════════════════

def record_command(user_input, tool_used, tier):
    """Record a command for feedback tracking."""
    now = time.time()

    # Check for repeat/rephrase within window
    is_repeat = _check_repeat(user_input, now)
    is_cancel = _check_cancel(user_input)

    with _lock:
        _recent_commands.append({
            "timestamp": now,
            "input": user_input.lower().strip(),
            "tool": tool_used,
            "tier": tier,
            "is_repeat": is_repeat,
            "is_cancel": is_cancel,
        })

        # If this is a repeat or cancel, tag the PREVIOUS command as likely wrong
        if is_repeat or is_cancel:
            if len(_recent_commands) >= 2:
                prev = _recent_commands[-2]
                prev["likely_wrong"] = True
                _log_feedback(prev, "likely_wrong", "repeat" if is_repeat else "cancel")

                # Record in metrics
                try:
                    from metrics import record_feedback
                    record_feedback(correct=False)
                except Exception:
                    pass
        else:
            # Tag the previous command as likely correct (user didn't complain)
            if len(_recent_commands) >= 2:
                prev = _recent_commands[-2]
                if not prev.get("likely_wrong"):
                    try:
                        from metrics import record_feedback
                        record_feedback(correct=True)
                    except Exception:
                        pass


def _check_repeat(user_input, now):
    """Check if user is repeating/rephrasing a recent command."""
    normalized = user_input.lower().strip()

    with _lock:
        for cmd in _recent_commands:
            # Within time window?
            if now - cmd["timestamp"] > REPEAT_WINDOW:
                continue

            # Exact repeat?
            if cmd["input"] == normalized:
                return True

            # Similar? (simple word overlap check)
            prev_words = set(cmd["input"].split())
            curr_words = set(normalized.split())

            if prev_words and curr_words:
                overlap = len(prev_words & curr_words) / max(len(prev_words | curr_words), 1)
                if overlap > REPHRASE_THRESHOLD:
                    return True

    return False


def _check_cancel(user_input):
    """Check if user is canceling or expressing dissatisfaction."""
    normalized = user_input.lower().strip()

    for keyword in CANCEL_KEYWORDS:
        if keyword in normalized:
            return True

    return False


def _log_feedback(command, verdict, reason):
    """Log a feedback event."""
    with _lock:
        _feedback_log.append({
            "timestamp": datetime.now().isoformat(),
            "command": command.get("input", ""),
            "tool": command.get("tool", ""),
            "tier": command.get("tier", ""),
            "verdict": verdict,
            "reason": reason,
        })

        # Keep only last 200
        if len(_feedback_log) > 200:
            _feedback_log = _feedback_log[-200:]

        print(f"[Feedback]: Tagged '{command.get('input', '')[:50]}' as {verdict} (reason: {reason})")


def get_feedback_stats():
    """Get feedback statistics for dashboard."""
    with _lock:
        if not _feedback_log:
            return {"total": 0, "likely_wrong": 0, "likely_correct": 0}

        wrong = sum(1 for f in _feedback_log if f["verdict"] == "likely_wrong")
        return {
            "total": len(_feedback_log),
            "likely_wrong": wrong,
            "likely_correct": len(_feedback_log) - wrong,
            "recent": _feedback_log[-10:],
        }


def get_misrouted_commands():
    """Get commands that were tagged as likely wrong (for prompt improvement)."""
    with _lock:
        return [f for f in _feedback_log if f["verdict"] == "likely_wrong"]


def save_feedback_log():
    """Save feedback log to disk."""
    try:
        import json
        log_file = os.path.join(getattr(__import__('config'), 'BASE_DIR', '.'), "feedback_log.json")
        with open(log_file, 'w') as f:
            json.dump(_feedback_log, f, indent=2)
    except Exception as e:
        print(f"[Feedback]: Save error: {e}")


if __name__ == "__main__":
    # Test
    print("Testing feedback loop...\n")

    record_command("set volume to 50", "set_volume", "pattern_match")
    print("Recorded: set volume to 50")

    record_command("set volume to 50", "set_volume", "pattern_match")
    print("Recorded: set volume to 50 (repeat)")

    record_command("open chrome", "open_app", "pattern_match")
    print("Recorded: open chrome")

    record_command("no that's wrong", "chat_only", "acknowledgment")
    print("Recorded: cancel")

    print(f"\nFeedback stats: {get_feedback_stats()}")
