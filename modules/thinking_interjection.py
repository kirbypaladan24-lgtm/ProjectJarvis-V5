"""
JARVIS Thinking Interjection
================================================================
When JARVIS takes more than N seconds to respond, it says something
like "Let me check..." or "Thinking..." so the user knows it's working.

This prevents the awkward silence where the user wonders if JARVIS
crashed or didn't hear them.

Usage:
    from thinking_interjection import ThinkingInterjection

    # In toolRouter.py, before calling Qwen 3:
    thinker = ThinkingInterjection(speak_fn)
    thinker.start("Let me check that for you, Sir.")
    result = route_with_qwen3(...)
    thinker.stop()  # Cancels if not already fired
"""
import os
import sys
import threading
import time
import random

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════

# How many seconds to wait before speaking the interjection
INTERJECTION_DELAY = 2.0  # seconds

# Things JARVIS says while thinking
INTERJECTION_PHRASES = [
    "Let me check that for you, Sir.",
    "One moment, Sir.",
    "Thinking, Sir...",
    "Let me look into that, Sir.",
    "Just a moment, Sir.",
    "Checking that now, Sir.",
    "Let me find out, Sir.",
]

# Things JARVIS says for longer operations (5+ seconds)
LONG_WAIT_PHRASES = [
    "This is taking a moment, Sir. Still working on it.",
    "Almost there, Sir.",
    "Still processing, Sir. Thank you for your patience.",
]


# ═════════════════════════════════════════════════════════════
# THINKING INTERJECTION CLASS
# ═════════════════════════════════════════════════════════════

class ThinkingInterjection:
    """
    Background timer that speaks an interjection after N seconds.
    Call .start() before a long operation, .stop() after it completes.
    """

    def __init__(self, speak_fn=None, delay=INTERJECTION_DELAY):
        self.speak_fn = speak_fn
        self.delay = delay
        self._timer = None
        self._fired = False
        self._long_timer = None
        self._long_fired = False

    def start(self, custom_phrase=None):
        """Start the thinking timer. After delay, speak the interjection."""
        self._fired = False
        self._long_fired = False

        phrase = custom_phrase or random.choice(INTERJECTION_PHRASES)

        def _fire():
            if not self._fired and self.speak_fn:
                self._fired = True
                try:
                    self.speak_fn(phrase)
                except Exception as e:
                    print(f"[Thinking]: Speak error: {e}")

        self._timer = threading.Timer(self.delay, _fire)
        self._timer.daemon = True
        self._timer.start()

        # Also set a long-wait timer (5 seconds)
        def _fire_long():
            if not self._long_fired and self.speak_fn:
                self._long_fired = True
                try:
                    self.speak_fn(random.choice(LONG_WAIT_PHRASES))
                except Exception as e:
                    print(f"[Thinking]: Long speak error: {e}")

        self._long_timer = threading.Timer(5.0, _fire_long)
        self._long_timer.daemon = True
        self._long_timer.start()

    def stop(self):
        """Stop the timer. If it hasn't fired yet, the interjection is cancelled."""
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._long_timer:
            self._long_timer.cancel()
            self._long_timer = None

    def fired(self):
        """Check if the interjection was spoken."""
        return self._fired


# ═════════════════════════════════════════════════════════════
# CONTEXT MANAGER VERSION
# ═════════════════════════════════════════════════════════════

class ThinkingContext:
    """Context manager for thinking interjection."""

    def __init__(self, speak_fn=None, phrase=None):
        self.thinker = ThinkingInterjection(speak_fn)
        self.phrase = phrase

    def __enter__(self):
        self.thinker.start(self.phrase)
        return self.thinker

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.thinker.stop()
        return False


# ═════════════════════════════════════════════════════════════
# TEST
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing ThinkingInterjection...\n")

    # Test 1: Timer fires after delay
    spoken = []
    def mock_speak(text):
        spoken.append(text)
        print(f"  [SPOKEN]: {text}")

    print("Test 1: 2-second delay (should fire)")
    thinker = ThinkingInterjection(mock_speak, delay=0.5)
    thinker.start()
    time.sleep(1.0)
    print(f"  Fired: {thinker.fired()}")
    assert thinker.fired()
    assert len(spoken) >= 1
    thinker.stop()
    print("  ✅ Passed\n")

    # Test 2: Timer cancelled before firing
    spoken.clear()
    print("Test 2: Cancelled before firing")
    thinker = ThinkingInterjection(mock_speak, delay=2.0)
    thinker.start()
    time.sleep(0.5)
    thinker.stop()
    time.sleep(2.5)
    print(f"  Fired: {thinker.fired()}")
    assert not thinker.fired()
    assert len(spoken) == 0
    print("  ✅ Passed\n")

    # Test 3: Context manager
    spoken.clear()
    print("Test 3: Context manager (quick operation, no fire)")
    with ThinkingContext(mock_speak) as t:
        time.sleep(0.1)  # Quick operation
    time.sleep(1.0)
    print(f"  Fired: {t.fired()}")
    assert not t.fired()
    print("  ✅ Passed\n")

    # Test 4: Slow operation (fires, then stop)
    spoken.clear()
    print("Test 4: Slow operation (should fire)")
    thinker = ThinkingInterjection(mock_speak, delay=0.5)
    thinker.start()
    time.sleep(1.0)  # Wait past the 0.5s delay
    print(f"  Fired: {thinker.fired()}")
    assert thinker.fired()
    assert len(spoken) >= 1
    thinker.stop()
    print("  ✅ Passed\n")

    print("All tests passed ✅")
