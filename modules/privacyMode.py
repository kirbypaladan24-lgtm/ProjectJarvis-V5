import os
import sys
import time
import threading

# Add root folder to sys.path (CRITICAL: Resolves parent directory configuration files)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        PRIVACY_REMINDER_MINS = 10

# State flags
_privacy_mode_enabled = False
_reminder_thread_started = False
_privacy_stop_event = threading.Event()  # FIXED: Event flag to cleanly terminate thread

def is_privacy_mode_active():
    global _privacy_mode_enabled
    return _privacy_mode_enabled

def enable_privacy_mode(speak_cb=None):
    global _privacy_mode_enabled
    _privacy_mode_enabled = True
    _privacy_stop_event.clear()  # Reset the stop event signal
    
    msg = "Privacy Mode is now active, Sir. I will stop writing to any log files on disk, and I will wipe our current session's command history from memory on exit."
    print(f"[Privacy Mode]: {msg}")
    if speak_cb:
        speak_cb(msg)
    
    # Start reminder thread if not already running
    start_privacy_reminder_thread(speak_cb)
    return msg

def disable_privacy_mode(speak_cb=None):
    global _privacy_mode_enabled
    _privacy_mode_enabled = False
    _privacy_stop_event.set()  # FIXED: Signal the worker thread to exit immediately
    
    msg = "Privacy Mode is now disabled, Sir. Standard session logging has been restored."
    print(f"[Privacy Mode]: {msg}")
    if speak_cb:
        speak_cb(msg)
    return msg

def _privacy_reminder_loop(speak_cb=None):
    global _reminder_thread_started
    try:
        # FIXED: Wait uses native OS-level interrupts instead of blocking time.sleep()
        # Returns True immediately when set() is called, exiting the loop
        while not _privacy_stop_event.wait(config.PRIVACY_REMINDER_MINS * 60):
            if _privacy_mode_enabled:
                msg = "Sir, this is a courteous reminder that Privacy Mode is still active. None of our current interactions are being logged."
                print(f"[Privacy Mode Reminder]: {msg}")
                if speak_cb:
                    speak_cb(msg)
    finally:
        # FIXED: Reset thread-started flag so a new thread can spawn if re-enabled later
        _reminder_thread_started = False

def start_privacy_reminder_thread(speak_cb=None):
    global _reminder_thread_started
    # FIXED: Lockout prevention wrapper
    if not _reminder_thread_started:
        t = threading.Thread(target=_privacy_reminder_loop, args=(speak_cb,), daemon=True)
        t.start()
        _reminder_thread_started = True