"""
JARVIS Proactive Intelligence
================================================================
JARVIS initiates conversations based on context, not just responds.

Triggers:
- Meeting reminders (15 min before)
- Disk space warnings
- Battery low alerts
- Idle check-ins (after 5 min of inactivity)
- Task due reminders
- Morning briefings
- End-of-day summaries
"""
import os
import sys
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
        BASE_DIR = "."
        IDLE_TIMEOUT_MINUTES = 5


# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

_last_interaction = time.time()
_speak_fn = None
_check_interval = 60  # seconds between proactive checks
_running = False
_thread = None


# ═════════════════════════════════════════════════════════════
# INTERACTION TRACKING
# ═════════════════════════════════════════════════════════════

def record_interaction():
    """Call this whenever the user interacts with JARVIS."""
    global _last_interaction
    _last_interaction = time.time()


def get_idle_time():
    """Get seconds since last interaction."""
    return time.time() - _last_interaction


# ═════════════════════════════════════════════════════════════
# PROACTIVE CHECKS
# ═════════════════════════════════════════════════════════════

def _check_idle():
    """Check if user has been idle and offer help."""
    idle_mins = get_idle_time() / 60
    if idle_mins >= getattr(config, 'IDLE_TIMEOUT_MINUTES', 5):
        # Only fire once per idle period
        if not hasattr(_check_idle, '_fired'):
            _check_idle._fired = True
            return "Still with you, Sir. Say hey Jarvis if you need me."
    else:
        _check_idle._fired = False
    return None


def _check_disk_space():
    """Check disk space and warn if low."""
    try:
        import shutil
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024**3)
        if free_gb < 5:
            return f"Sir, disk space is running low — only {free_gb:.1f} GB free."
    except Exception:
        pass
    return None


def _check_battery():
    """Check battery level and warn if low."""
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged:
            if battery.percent < 20:
                return f"Sir, battery is at {battery.percent}%. You may want to plug in soon."
    except Exception:
        pass
    return None


def _check_due_tasks():
    """Check for tasks due today."""
    try:
        import json
        tasks_file = os.path.join(getattr(config, 'BASE_DIR', '.'), "tasks.json")
        if not os.path.exists(tasks_file):
            return None

        with open(tasks_file, 'r') as f:
            tasks = json.load(f)

        today = datetime.now().strftime("%Y-%m-%d")
        due_today = [t for t in tasks if not t.get("completed") and t.get("due_date") == today]

        if due_today:
            if len(due_today) == 1:
                return f"Sir, you have a task due today: '{due_today[0].get('title', 'Unknown')}'."
            else:
                return f"Sir, you have {len(due_today)} tasks due today."

    except Exception:
        pass
    return None


def _check_morning_briefing():
    """Check if it's morning and we haven't briefed yet today."""
    now = datetime.now()
    if 5 <= now.hour < 12:
        today = now.strftime("%Y-%m-%d")
        if not hasattr(_check_morning_briefing, '_last_brief_date'):
            _check_morning_briefing._last_brief_date = None
        if _check_morning_briefing._last_brief_date != today:
            _check_morning_briefing._last_brief_date = today
            try:
                from morningBriefing import get_morning_briefing
                return get_morning_briefing()
            except Exception:
                return None
    return None


def _check_end_of_day():
    """Check if it's end of day and we haven't summarized yet."""
    now = datetime.now()
    if now.hour == 23:
        today = now.strftime("%Y-%m-%d")
        if not hasattr(_check_end_of_day, '_last_summary_date'):
            _check_end_of_day._last_summary_date = None
        if _check_end_of_day._last_summary_date != today:
            _check_end_of_day._last_summary_date = today
            try:
                from deepMemory import summarize_session
                # This would need conversation history passed in
                return "Sir, it's almost midnight. Would you like me to summarize today's session before you rest?"
            except Exception:
                return None
    return None


# ═════════════════════════════════════════════════════════════
# MAIN LOOP
# ═════════════════════════════════════════════════════════════

def _proactive_loop():
    """Background loop that runs proactive checks."""
    while _running:
        try:
            time.sleep(_check_interval)

            checks = [
                _check_idle,
                _check_disk_space,
                _check_battery,
                _check_due_tasks,
                _check_morning_briefing,
                _check_end_of_day,
            ]

            for check in checks:
                try:
                    message = check()
                    if message and _speak_fn:
                        print(f"\n[Proactive]: {message}")
                        _speak_fn(message)
                        time.sleep(2)  # Don't fire multiple checks at once
                        break  # Only one proactive message per cycle
                except Exception as e:
                    print(f"[Proactive]: Check {check.__name__} failed: {e}")

        except Exception as e:
            print(f"[Proactive]: Loop error: {e}")


def start_proactive_engine(speak_fn=None):
    """Start the proactive intelligence background thread."""
    global _speak_fn, _running, _thread

    if _running:
        return

    _speak_fn = speak_fn
    _running = True
    _thread = threading.Thread(target=_proactive_loop, daemon=True, name="proactive")
    _thread.start()
    print("[Proactive]: Engine started.")


def stop_proactive_engine():
    """Stop the proactive intelligence thread."""
    global _running
    _running = False
    print("[Proactive]: Engine stopped.")


if __name__ == "__main__":
    print("Testing proactive checks...\n")

    print(f"Idle time: {get_idle_time():.1f}s")

    msg = _check_disk_space()
    print(f"Disk check: {msg or 'OK'}")

    msg = _check_battery()
    print(f"Battery check: {msg or 'OK'}")

    msg = _check_due_tasks()
    print(f"Due tasks: {msg or 'None'}")
