"""
Background Timer & Reminder Module for JARVIS (UPGRADED)
- Creates non-blocking threads to monitor timer durations
- Accepts speech-callbacks to talk to you when timers fire
- Tracks active end-times so you can check remaining durations
- Supports specific clock-time alarms (e.g., "10:50 PM") with automatic next-day rollover
- Supports flexible voice-transcription separators (e.g., "10.50pm", "10:50 pm", "10 50 pm")
- Uses conversational scramble parsing to extract tasks and times regardless of word order
- Smart AM/PM selection (chooses the closest target time if AM/PM is omitted)
- 2-Minute Grace Window (fires immediately if target time was missed by under 2 minutes)
- Ambiguity Guard (separates raw numbers used in countdowns from specific clock-time alarms)
- Smart Digit Decoder (safely decodes raw unpunctuated numbers like '255' into '2:55')
- Persistent Storage (saves timers to timers.json so they survive restarts/shutdowns)
- Recurring Alarms (loops background threads repeatedly as statement-reminders until the parent task is marked completed)
- Conversational Cancellation (lists active timers by number to stop specific reminders)
- Conversational Courtesy (waits for JARVIS to finish speaking before triggering any background alarms)
"""
import threading
import time
import os
import re
import json
from datetime import datetime, timedelta

# Save in same folder as tasks
TIMERS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "timers.json")
RECURRING_TIMERS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recurring_timers.json")

# Global list of active timers
_active_timers = []
_timer_id_counter = 0

# Nag-state: title of the task most recently nagged about by a recurring thread.
# taskManager/tts.py read this to intercept the user's yes/no reply.
_last_recurring_nag_label = None


def get_last_recurring_nag_label():
    return _last_recurring_nag_label

def set_last_recurring_nag_label(title):
    global _last_recurring_nag_label
    _last_recurring_nag_label = title

def clear_last_recurring_nag_label():
    global _last_recurring_nag_label
    _last_recurring_nag_label = None


def load_persistent_timers():
    """Reads timers.json from disk on startup."""
    if os.path.exists(TIMERS_FILE):
        try:
            with open(TIMERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_persistent_timers(timers_data):
    """Saves active timers to timers.json."""
    try:
        with open(TIMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(timers_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[TimerSystem Error]: {e}")


# ── Recurring timer config persistence ────────────────────────────────────────

def load_recurring_timer_configs():
    """Returns list of {label, interval_seconds} from recurring_timers.json."""
    if os.path.exists(RECURRING_TIMERS_FILE):
        try:
            with open(RECURRING_TIMERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_recurring_timer_config(label, interval_seconds):
    """Upserts a recurring timer config to disk."""
    configs = load_recurring_timer_configs()
    configs = [c for c in configs if c["label"].lower() != label.lower()]
    configs.append({"label": label, "interval_seconds": interval_seconds})
    try:
        with open(RECURRING_TIMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[TimerSystem Error]: {e}")


def remove_recurring_timer_config(label):
    """Removes a recurring timer config from disk (called when task is completed)."""
    configs = load_recurring_timer_configs()
    configs = [c for c in configs if c["label"].lower() != label.lower()]
    try:
        with open(RECURRING_TIMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[TimerSystem Error]: {e}")


def _timer_worker(duration_seconds, timer_id, label, speak_callback):
    """Background worker thread that sleeps, waits for active speech to end, and speaks on finish."""
    global _active_timers  # ← declared FIRST so Python is happy with both read and write below
    end_t = time.time() + duration_seconds
    while time.time() < end_t:
        time.sleep(0.5)
        # If the timer_id is no longer in the list, it was cancelled by the user. Die quietly.
        if not any(t["id"] == timer_id for t in _active_timers):
            return
            
    # Conversational Courtesy: Wait for JARVIS to finish speaking before triggering
    try:
        import tts
        if tts._is_speaking.is_set():
            while tts._is_speaking.is_set(): 
                time.sleep(0.5)
    except Exception: pass

    # Assemble alarm notification
    msg = f"Sir, your timer to {label} has finished!" if label else "Sir, your timer is up!"
        
    # Trigger vocal speech callback
    speak_callback(msg)
    
    # Safely remove this thread from active trackers and update disk
    _active_timers = [t for t in _active_timers if t["id"] != timer_id]
    _update_disk_storage()


def _recurring_timer_worker(interval_seconds, timer_id, label, speak_callback):
    """Background worker: loops indefinitely, nagging the user every interval until the task is done."""
    global _last_recurring_nag_label

    TASKS_FILE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tasks.json"
    )

    while True:
        end_t = time.time() + interval_seconds
        while time.time() < end_t:
            time.sleep(0.5)
            # If user cancelled this specific reminder via voice, kill thread quietly
            if not any(t["id"] == timer_id for t in _active_timers):
                return

        # Check if the task is still incomplete
        try:
            if os.path.exists(TASKS_FILE_PATH):
                with open(TASKS_FILE_PATH, "r", encoding="utf-8") as f:
                    tasks = json.load(f)
                task_found = next((t for t in tasks if t["title"].lower() == label.lower()), None)
                if task_found and task_found.get("completed"):
                    # Task is done — silently exit and clean up config
                    remove_recurring_timer_config(label)
                    return
                elif not task_found:
                    # Task was deleted — clean up and exit
                    remove_recurring_timer_config(label)
                    return
        except Exception:
            pass

        # Conversational Courtesy: wait for JARVIS to finish speaking
        try:
            import tts
            if tts._is_speaking.is_set():
                while tts._is_speaking.is_set():
                    time.sleep(0.5)
        except Exception:
            pass

        # Arm nag-state so tts.py can catch the user's yes/no reply
        _last_recurring_nag_label = label
        msg = (
            f"Sir, this is your recurring reminder to work on: {label}. "
            f"Have you finished it yet?"
        )
        speak_callback(msg)


def _update_disk_storage():
    """Serializes currently running active standard timers to timers.json."""
    serializable = []
    for t in _active_timers:
        # We only save standard future timers to disk (recurring timers are handled dynamically via tasks.json)
        if not t["label"].startswith("Recurring:"):
            serializable.append({
                "label": t["label"],
                "end_time": t["end_time"].isoformat()
            })
    save_persistent_timers(serializable)


def resume_timers_on_startup(speak_callback):
    """
    Scans timers.json on bootup. Resumes any future countdowns,
    and returns a summary of any alarms that expired while offline.
    """
    global _timer_id_counter
    saved_timers = load_persistent_timers()
    if not saved_timers:
        return None

    now = datetime.now()
    active_resumed = []
    missed_alarms = []

    for st in saved_timers:
        try:
            end_time = datetime.fromisoformat(st["end_time"])
            label = st["label"]
            
            if end_time > now:
                # Timer is still in the future -> calculate remaining seconds and resume
                seconds_left = int((end_time - now).total_seconds())
                _timer_id_counter += 1
                tid = _timer_id_counter
                t = threading.Thread(target=_timer_worker, args=(seconds_left, tid, label, speak_callback), daemon=True)
                
                _active_timers.append({
                    "id": tid,
                    "label": label,
                    "end_time": end_time,
                    "thread": t
                })
                t.start()
                active_resumed.append(label)
            else:
                # Timer expired while offline -> log it as a missed alarm
                if now - end_time < timedelta(hours=24):
                    missed_alarms.append((label, end_time.strftime("%I:%M %p")))
        except Exception:
            pass

    # Save the updated list (stripping out the finished/missed ones)
    _update_disk_storage()

    # Generate a spoken summary if any missed alarms or resumed timers occurred
    notifications = []
    if missed_alarms:
        missed_strs = [f"your alarm to {name} at {time_str}" for name, time_str in missed_alarms]
        notifications.append(f"While I was offline, the following reminders expired: {', '.join(missed_strs)}.")
    if active_resumed:
        notifications.append(f"I have successfully resumed {len(active_resumed)} active background timers.")
        
    return " ".join(notifications) if notifications else None


def set_timer(duration_seconds, label, speak_callback, write_to_disk=True):
    """Spawns a background worker thread to monitor the timer."""
    global _timer_id_counter
    _timer_id_counter += 1
    tid = _timer_id_counter
    
    t = threading.Thread(target=_timer_worker, args=(duration_seconds, tid, label, speak_callback), daemon=True)
    
    _active_timers.append({
        "id": tid,
        "label": label if label else "Timer",
        "end_time": datetime.now() + timedelta(seconds=duration_seconds),
        "thread": t
    })
    t.start()
    
    if write_to_disk:
        _update_disk_storage()
    
    # Convert duration to human-readable string
    hours = duration_seconds // 3600
    minutes = (duration_seconds % 3600) // 60
    seconds = duration_seconds % 60
    
    time_str = ""
    if hours: time_str += f"{hours} hour{'s' if hours > 1 else ''} "
    if minutes: time_str += f"{minutes} minute{'s' if minutes > 1 else ''} "
    if seconds and not hours: time_str += f"{seconds} second{'s' if seconds > 1 else ''}"
    
    label_str = f" to {label}" if label else ""
    return f"Timer set{label_str} for {time_str.strip()}."


def set_recurring_timer(interval_seconds, label, speak_callback):
    """Spawns a continuously looping background worker thread and saves config to disk."""
    global _timer_id_counter
    _timer_id_counter += 1
    tid = _timer_id_counter
    
    t = threading.Thread(target=_recurring_timer_worker, args=(interval_seconds, tid, label, speak_callback), daemon=True)
    
    _active_timers.append({
        "id": tid,
        "label": f"Recurring: {label}",
        "end_time": datetime.now() + timedelta(seconds=interval_seconds),
        "thread": t
    })
    t.start()

    # Persist so nag thread is resumed after restart
    save_recurring_timer_config(label, interval_seconds)
    
    # Convert duration to human-readable string
    hours = interval_seconds // 3600
    minutes = (interval_seconds % 3600) // 60
    seconds = interval_seconds % 60
    
    time_str = ""
    if hours: time_str += f"{hours} hour{'s' if hours > 1 else ''} "
    if minutes: time_str += f"{minutes} minute{'s' if minutes > 1 else ''} "
    if seconds and not hours: time_str += f"{seconds} second{'s' if seconds > 1 else ''}"
    
    return f"I have set a recurring reminder. I will check in with you every {time_str.strip()} regarding your task: '{label}', Sir."


def resume_recurring_timers_on_startup(speak_callback):
    """
    Called on boot. Re-spawns recurring nag threads for all tasks that are
    still incomplete. Cleans up configs for tasks that are done or deleted.
    """
    configs = load_recurring_timer_configs()
    if not configs:
        return None

    TASKS_FILE_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tasks.json"
    )
    task_map = {}
    if os.path.exists(TASKS_FILE_PATH):
        try:
            with open(TASKS_FILE_PATH, "r", encoding="utf-8") as f:
                tasks = json.load(f)
            task_map = {t["title"].lower(): t for t in tasks}
        except Exception:
            pass

    resumed = []
    for config in configs:
        label    = config["label"]
        interval = config["interval_seconds"]
        task     = task_map.get(label.lower())

        if task and not task.get("completed"):
            global _timer_id_counter
            _timer_id_counter += 1
            tid = _timer_id_counter
            t = threading.Thread(
                target=_recurring_timer_worker,
                args=(interval, tid, label, speak_callback),
                daemon=True
            )
            _active_timers.append({
                "id": tid,
                "label": f"Recurring: {label}",
                "end_time": datetime.now() + timedelta(seconds=interval),
                "thread": t
            })
            t.start()
            resumed.append(label)
        else:
            # Task is done or gone — prune the stale config
            remove_recurring_timer_config(label)

    if resumed:
        return (
            f"Resumed {len(resumed)} recurring reminder{'s' if len(resumed) != 1 else ''}: "
            + ", ".join(f"'{r}'" for r in resumed) + "."
        )
    return None


def list_timers():
    """Lists remaining durations for all active timers."""
    if not _active_timers:
        return "No active timers running, Sir."
        
    lines = ["Active Timers:"]
    for i, t in enumerate(_active_timers, 1):
        remaining = t["end_time"] - datetime.now()
        rem_sec = int(remaining.total_seconds())
        if rem_sec < 0 and not t["label"].startswith("Recurring:"):
            continue
        hr_rem = rem_sec // 3600
        min_rem = (rem_sec % 3600) // 60
        sec_rem = rem_sec % 60
        
        time_left = ""
        if hr_rem: time_left += f"{hr_rem}h "
        if min_rem: time_left += f"{min_rem}m "
        time_left += f"{sec_rem}s"
        
        lines.append(f"  {i}. {t['label']} — {time_left} remaining")
    return "\n".join(lines)


def cancel_timer(query):
    """
    Cancels a specific timer or recurring reminder.
    - If 'reminder' is in the query, only recurring timers are targeted.
    - If multiple matches exist, prompts with a numbered list.
    - Cancelling a recurring reminder removes the nag thread AND the disk config,
      but the task remains in tasks.json so startup nags continue until it's marked done.
    """
    if not _active_timers:
        return "You have no active reminders or timers to stop, Sir."

    # Decide scope: recurring-only or all timers
    target_recurring = any(w in query for w in ["reminder", "recurring", "repeat"])
    candidates = (
        [t for t in _active_timers if t["label"].startswith("Recurring:")]
        if target_recurring else list(_active_timers)
    )

    if not candidates:
        return "You have no active recurring reminders to stop, Sir."

    # If only one candidate, cancel it immediately
    if len(candidates) == 1:
        entry = candidates[0]
        label = entry["label"]
        _active_timers[:] = [t for t in _active_timers if t["id"] != entry["id"]]
        _update_disk_storage()
        # Strip "Recurring: " prefix for config removal
        clean_label = label.replace("Recurring: ", "")
        if target_recurring:
            remove_recurring_timer_config(clean_label)
            return (
                f"Stopped the recurring reminder for '{clean_label}', Sir. "
                f"I will still remind you at startup until you mark the task as complete."
            )
        return f"I have cancelled the timer for '{label}', Sir."

    # Parse spoken number (e.g. "stop number 2")
    num_match = re.search(r'\b(\d+|one|two|three|four|first|second|third)\b', query.lower())
    if num_match:
        word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "first": 1, "second": 2, "third": 3}
        val = num_match.group(1)
        idx = int(val) - 1 if val.isdigit() else word_to_num.get(val, 1) - 1

        if 0 <= idx < len(candidates):
            entry = candidates[idx]
            label = entry["label"]
            _active_timers[:] = [t for t in _active_timers if t["id"] != entry["id"]]
            _update_disk_storage()
            clean_label = label.replace("Recurring: ", "")
            if target_recurring:
                remove_recurring_timer_config(clean_label)
                return (
                    f"Stopped the recurring reminder for '{clean_label}', Sir. "
                    f"I will still remind you at startup until you mark the task as complete."
                )
            return f"I have cancelled the timer for '{label}', Sir."

    # Multiple candidates, no valid number — ask which one
    scope = "recurring reminders" if target_recurring else "active timers"
    lines = [f"[TIMER_CANCEL_PROMPT] You have multiple {scope}. Which number would you like me to stop?\n"]
    for i, t in enumerate(candidates, 1):
        lines.append(f"  {i}. {t['label']}")
    return "\n".join(lines)


def handle_timer_commands(user_input, speak_callback):
    """Parse and handle timer, countdown, and specific clock-time alarms with ambiguity protection."""
    text = re.sub(r'[.,!;/:]+', '', user_input.lower().strip()) 
    words = text.split()
    
    # 0. Cancel/Stop Timer Overrides
    if any(w in text for w in ["stop", "cancel", "remove", "kill"]) and any(w in text for w in ["timer", "reminder", "alarm"]):
        return cancel_timer(text)

    # 1. Conversational Scramble Parser: Matches "10:50 PM", "10.50pm", "10 50 pm", "9 am", "255 am", "1050 pm"
    time_match = re.search(r'\b(\d{1,4})(?::|\.)?(\d{2})?\s*(am|pm)?\b', text, re.IGNORECASE)
    has_time_context = any(w in text for w in ["at", "when", "clock", "alarm", "remind", "timer", "comes"])
    
    # AMBIGUITY GUARD: Check if this contains a relative duration phrase (e.g. "10 seconds")
    has_duration_phrase = re.search(r'\b\d+\s*(?:second|minute|hour|sec|min|hr)s?\b', text)
    # Check if there is an explicit clock-time format
    has_explicit_clock = re.search(r'\b\d{1,2}(?::|\.)\d{2}\b', text) or \
                         re.search(r'\b\d{1,2}\s*(?:am|pm)\b', text) or \
                         re.search(r'\b\d{3,4}\s*(?:am|pm)\b', text)
    
    skip_clock_parser = has_duration_phrase and not has_explicit_clock
    
    if time_match and has_time_context and not skip_clock_parser:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        period = time_match.group(3)
        
        # SMART DIGIT DECODER
        raw_digits_match = re.match(r'^(\d+)$', time_match.group(1))
        if raw_digits_match and not time_match.group(2):
            digit_str = raw_digits_match.group(1)
            if len(digit_str) == 3:
                hour = int(digit_str[0])
                minute = int(digit_str[1:])
            elif len(digit_str) == 4:
                hour = int(digit_str[:2])
                minute = int(digit_str[2:])
        
        # Simple validation check for hour/minutes boundaries
        if 0 <= hour <= 24 and 0 <= minute <= 59:
            now = datetime.now()
            
            # Convert 12-hour format to 24-hour format if PM is present
            if period:
                period = period.lower()
                if period == "pm" and hour < 12:
                    hour += 12
                elif period == "am" and hour == 12:
                    hour = 0
            else:
                # SMART AM/PM SELECTION: If no AM/PM was spoken, choose the closest target time
                hour_am = hour % 12
                target_am = now.replace(hour=hour_am, minute=minute, second=0, microsecond=0)
                if target_am < now: target_am += timedelta(days=1)
                diff_am = (target_am - now).total_seconds()
                
                hour_pm = (hour % 12) + 12
                target_pm = now.replace(hour=hour_pm, minute=minute, second=0, microsecond=0)
                if target_pm < now: target_pm += timedelta(days=1)
                diff_pm = (target_pm - now).total_seconds()
                
                if diff_am < diff_pm:
                    hour = hour_am
                else:
                    hour = hour_pm
            
            # Extract the raw time string to subtract it from the sentence
            raw_time_string = time_match.group(0)
            label_candidate = text.replace(raw_time_string, "").strip()
            
            # Strip out common conversational filler words to isolate the core task
            fillers = r'\b(remind|me|at|to|for|alarm|timer|when|comes|on|schedule|write|save|log)\b'
            label = re.sub(fillers, '', label_candidate, flags=re.IGNORECASE).strip()
            label = re.sub(r'\s+', ' ', label)  # collapse spaces
            
            if not label:
                label = "Alarm"
                
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # GRACE WINDOW
            time_diff_seconds = (now - target_time).total_seconds()
            if target_time < now and time_diff_seconds <= 120:
                seconds = 1
            else:
                # Normal Next-Day Rollover
                if target_time < now:
                    target_time += timedelta(days=1)
                seconds = int((target_time - now).total_seconds())
                
            return set_timer(seconds, label, speak_callback)

    # 2. Relative countdown timer: "set a timer for 10 minutes", "timer for 30 seconds"
    timer_match = re.search(r'(?:set|start|create)?\s*(?:a\s+)?(?:timer|reminder)\s*(?:for|in)?\s*(\d+)\s*(minute|second|hour)s?(?:\s*(?:to|for)\s+(.+))?$', text)
    if timer_match:
        amount = int(timer_match.group(1))
        unit = timer_match.group(2)
        label = timer_match.group(3).strip() if timer_match.group(3) else None
        
        seconds = amount
        if unit == "minute": seconds = amount * 60
        elif unit == "hour": seconds = amount * 3600
        
        return set_timer(seconds, label, speak_callback)
        
    # 3. Conversational relative reminders: "remind me in 1 hour to stretch"
    remind_match = re.search(r'remind\s+me\s+(?:in|after)\s*(\d+)\s*(minute|second|hour)s?\s*(?:to\s+)?(.+)$', text)
    if remind_match:
        amount = int(remind_match.group(1))
        unit = remind_match.group(2)
        label = remind_match.group(3).strip()
        
        seconds = amount
        if unit == "minute": seconds = amount * 60
        elif unit == "hour": seconds = amount * 3600
        
        return set_timer(seconds, label, speak_callback)

    # 4. List active timers: "show timers", "list timers"
    if any(p in text for p in ["show timers", "list timers", "active timers", "any timers"]):
        return list_timers()
        
    return None