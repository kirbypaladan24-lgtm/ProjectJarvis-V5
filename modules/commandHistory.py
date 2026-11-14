"""
Command History and Learning Module for JARVIS
PERF #8: Buffered writes — accumulates up to 10 entries in memory before hitting disk.
         Force-flush is called on clean exit so nothing is lost.
"""
import json
import os
import threading
from datetime import datetime

COMMAND_HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "command_history.json")

# ── Write buffer ──────────────────────────────────────────────────────────────
_history_write_buffer = []          # Pending entries not yet flushed to disk
_history_buffer_lock  = threading.Lock()
_FLUSH_EVERY          = 10          # Flush to disk after this many accumulated entries


def load_command_history():
    if os.path.exists(COMMAND_HISTORY_FILE):
        try:
            with open(COMMAND_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_command_history(history):
    try:
        if len(history) > 2000:
            history = history[-2000:]
        with open(COMMAND_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[CommandHistory Error]: {e}")


def save_command_to_history(user_input, response, intent, success=True):
    """Appends to the in-memory buffer and flushes to disk every _FLUSH_EVERY entries."""
    global _history_write_buffer
    entry = {
        "timestamp":  datetime.now().isoformat(),
        "user_input": user_input,
        "response":   (response or "")[:100],
        "intent":     intent,
        "success":    success
    }
    with _history_buffer_lock:
        _history_write_buffer.append(entry)
        if len(_history_write_buffer) >= _FLUSH_EVERY:
            _do_flush()

def _do_flush():
    """Internal: merges buffer into disk file. Must be called with _history_buffer_lock held."""
    global _history_write_buffer
    if not _history_write_buffer:
        return
    pending   = _history_write_buffer[:]
    _history_write_buffer = []
    try:
        history = load_command_history()
        history.extend(pending)
        save_command_history(history)
    except Exception as e:
        print(f"[CommandHistory Flush Error]: {e}")

def force_flush_history():
    """Call on clean exit to guarantee buffered entries are written to disk."""
    with _history_buffer_lock:
        _do_flush()


def analyze_user_patterns():
    try:
        history = load_command_history()
        if not history:
            return {}
        intent_counts = {}
        for entry in history:
            intent = entry.get("intent", "unknown")
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
        return intent_counts
    except Exception:
        return {}


def suggest_command_shortcuts():
    try:
        patterns = analyze_user_patterns()
        if not patterns:
            return "No patterns found yet."
        sorted_intents = sorted(patterns.items(), key=lambda x: x[1], reverse=True)
        suggestion = "Your most common commands:\n"
        for intent, count in sorted_intents[:3]:
            suggestion += f"  - {intent.replace('_', ' ').title()}: {count} times\n"
        return suggestion
    except Exception:
        return "Could not analyze patterns."


def get_today_commands():
    try:
        from datetime import date
        today = str(date.today())
        history = load_command_history()
        return len([h for h in history if h["timestamp"].startswith(today)])
    except Exception:
        return 0


def get_success_rate():
    try:
        history = load_command_history()
        if not history:
            return 0.0
        successful = sum(1 for h in history if h.get("success", True))
        return round((successful / len(history)) * 100, 2)
    except Exception:
        return 0.0