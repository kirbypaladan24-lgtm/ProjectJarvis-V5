"""
JARVIS State Machine (Phase 4)
================================================================
Generalizes the _awaiting_confirmation event into a full state machine
that handles multi-turn interactions:

States:
    IDLE                    — normal operation, no state active
    AWAITING_APPROVAL       — "Confirm shutdown?" (yes/no)
    AWAITING_DISAMBIGUATION — "Did you mean file A or file B?" (pick option)
    AWAITING_ARG            — "Set volume to what?" (provide a value)
    AWAITING_CLARIFICATION  — "I didn't understand, can you rephrase?"

Features:
    1. Universal cancel — "cancel", "never mind", "forget it" work in ANY state
    2. 30-second timeout — auto-clears state if user doesn't respond
    3. New-command detector — if input starts with action verb AND state is
       not AWAITING_ARG, treat as a new command (clear state, process normally)
    4. Thread-safe — lock protects all state transitions
    5. Backward compatible — sets _awaiting_confirmation event when active,
       so existing hotkey/auto-listen code routes input correctly

Usage:
    from stateMachine import state_machine

    # Enter a state
    state_machine.enter_state(
        state="AWAITING_APPROVAL",
        prompt="Confirm shutdown? Say confirm or cancel.",
        speak_fn=speak,
        timeout=30
    )

    # Wait for response (blocks)
    status, text = state_machine.wait_for_response(timeout=60)
    # status: "answer", "cancelled", "timeout", "new_command"
    # text: the user's input (for "answer" and "new_command")

    # Clear state manually
    state_machine.clear()
"""
import os
import sys
import queue
import threading
import time

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        pass


# ═══════════════════════════════════════════════════════════════════════
# CONFIG (override in config.py)
# ═══════════════════════════════════════════════════════════════════════

STATE_MACHINE_ENABLED      = getattr(config, 'STATE_MACHINE_ENABLED', True)
STATE_MACHINE_TIMEOUT      = getattr(config, 'STATE_MACHINE_TIMEOUT', 30)    # seconds
STATE_MACHINE_ENABLE_LOG   = getattr(config, 'STATE_MACHINE_ENABLE_LOG', True)

# Universal cancel phrases — work in ANY state
CANCEL_PHRASES = {
    "cancel", "never mind", "nevermind", "forget it", "forget that",
    "scratch that", "abort", "stop", "never mind that", "no forget that",
    "disregard", "ignore that", "cancel that", "cancel it",
}

# Action verbs for new-command detection (imported from normalization.py)
# If the input starts with one of these AND state != AWAITING_ARG,
# treat it as a new command (cancel current state, process normally)
try:
    from normalization import IMPERATIVE_VERBS
except ImportError:
    # Fallback if normalization.py not available
    IMPERATIVE_VERBS = {
        "play", "pause", "open", "launch", "start", "close", "kill",
        "set", "find", "search", "read", "write", "save", "delete",
        "create", "add", "take", "shutdown", "sleep", "restart",
        "run", "execute", "check", "test", "note", "remember",
        "show", "list", "minimize", "maximize", "focus",
    }


# ═══════════════════════════════════════════════════════════════════════
# STATE CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

IDLE                    = "IDLE"
AWAITING_APPROVAL       = "AWAITING_APPROVAL"
AWAITING_DISAMBIGUATION = "AWAITING_DISAMBIGUATION"
AWAITING_ARG            = "AWAITING_ARG"
AWAITING_CLARIFICATION  = "AWAITING_CLARIFICATION"


# ═══════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════

def _log(action, details):
    if not STATE_MACHINE_ENABLE_LOG:
        return
    try:
        from datetime import datetime
        import json
        log_path = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "state_machine_log.jsonl")
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# STATE MACHINE CLASS
# ═══════════════════════════════════════════════════════════════════════

class StateMachine:
    """
    Thread-safe state machine for multi-turn interactions.

    Uses an external queue (typically _confirmation_queue from tts.py) for
    receiving input from all channels (keyboard, hotkey voice, auto-listen).
    This ensures backward compatibility with existing routing code.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._current_state = IDLE
        self._state_data = {}       # {prompt, options, context, ...}
        self._response_queue = None # Set by init_state_machine()
        self._awaiting_event = None # Set by init_state_machine() (for backward compat)
        self._speak_fn = None       # Set by init_state_machine()
        self._timeout_thread = None
        self._timeout_event = None

    def init_state_machine(self, awaiting_event, response_queue, speak_fn):
        """
        Wire in the existing _awaiting_confirmation event and _confirmation_queue
        from tts.py. Called once at startup.

        Args:
            awaiting_event: threading.Event — set when any state is active
            response_queue: queue.Queue — input from all channels goes here
            speak_fn: callable — function to speak prompts
        """
        self._awaiting_event = awaiting_event
        self._response_queue = response_queue
        self._speak_fn = speak_fn
        print("[StateMachine]: Initialized with confirmation event + queue.")

    def is_active(self):
        """Returns True if any state is active (not IDLE)."""
        with self._lock:
            return self._current_state != IDLE

    def get_current_state(self):
        """Returns the current state name."""
        with self._lock:
            return self._current_state

    def enter_state(self, state, prompt=None, options=None, context=None,
                    timeout=None, speak_fn=None):
        """
        Enter a new state. Clears any previous state first.

        Args:
            state: One of the state constants (AWAITING_APPROVAL, etc.)
            prompt: Text to speak to the user
            options: List of options (for AWAITING_DISAMBIGUATION)
            context: Dict of arbitrary context data
            timeout: Seconds before auto-clear (None = use default)
            speak_fn: Override speak function
        """
        if not STATE_MACHINE_ENABLED:
            return

        # Clear any existing state first
        self.clear()

        timeout = timeout if timeout is not None else STATE_MACHINE_TIMEOUT
        speak = speak_fn or self._speak_fn

        with self._lock:
            self._current_state = state
            self._state_data = {
                "prompt": prompt,
                "options": options or [],
                "context": context or {},
                "entered_at": time.time(),
                "timeout": timeout,
            }

            # Set the backward-compat event so hotkey/auto-listen threads route input
            if self._awaiting_event:
                self._awaiting_event.set()

        # Speak the prompt (outside lock to avoid holding it during TTS)
        if prompt and speak:
            try:
                speak(prompt)
            except Exception as e:
                print(f"[StateMachine]: Speak error: {e}")

        # Start timeout thread
        self._start_timeout(timeout)

        _log("enter_state", {
            "state": state,
            "prompt": (prompt or "")[:200],
            "timeout": timeout,
        })

    def clear(self):
        """Clear the current state and return to IDLE."""
        with self._lock:
            if self._current_state == IDLE:
                return
            old_state = self._current_state
            self._current_state = IDLE
            self._state_data = {}

            # Clear the backward-compat event
            if self._awaiting_event:
                self._awaiting_event.clear()

        # Stop timeout thread (outside lock)
        self._stop_timeout()

        _log("clear_state", {"previous_state": old_state})

    def _start_timeout(self, timeout):
        """Start a daemon thread that clears the state after timeout seconds."""
        self._timeout_event = threading.Event()

        def _timeout_worker():
            if self._timeout_event.wait(timeout):
                return  # Event was set (stop requested)
            # Timeout expired — clear the state
            if self.is_active():
                print(f"[StateMachine]: State timed out after {timeout}s — clearing.")
                speak = self._speak_fn
                self.clear()
                if speak:
                    try:
                        speak("Timed out, Sir.")
                    except Exception:
                        pass

        self._timeout_thread = threading.Thread(target=_timeout_worker, daemon=True)
        self._timeout_thread.start()

    def _stop_timeout(self):
        """Stop the timeout thread."""
        if self._timeout_event:
            self._timeout_event.set()
            self._timeout_event = None
        self._timeout_thread = None

    def handle_input(self, text):
        """
        Process input text when a state is active.
        Called by wait_for_response() after getting text from the queue.

        Returns:
            (status, text) where status is:
                "answer"      — text is a valid answer to the current state's question
                "cancelled"   — user said a cancel phrase
                "new_command" — text is a new command (action verb at start)
        """
        if not text or not text.strip():
            return ("answer", text)

        text_lower = text.lower().strip()
        # Strip leading fillers for cancel/verb detection
        text_clean = text_lower.rstrip(".!?;:")

        # Check universal cancel phrases
        # Match whole words, not substrings ("cancel" shouldn't match "cancellation")
        words = set(text_clean.replace("'", "").split())
        for cancel_phrase in CANCEL_PHRASES:
            if " " in cancel_phrase:
                # Multi-word phrase — check substring
                if cancel_phrase in text_clean:
                    _log("cancel_detected", {"input": text[:200], "phrase": cancel_phrase})
                    return ("cancelled", text)
            else:
                # Single word — check word match
                if cancel_phrase in words:
                    _log("cancel_detected", {"input": text[:200], "phrase": cancel_phrase})
                    return ("cancelled", text)

        # Check new-command detection
        # Skip for AWAITING_ARG — the user might be providing a value that starts with a verb
        # (e.g., "play" as the answer to "play what?" — "play" is a valid song/artist query)
        with self._lock:
            current_state = self._current_state

        if current_state != AWAITING_ARG and current_state != AWAITING_CLARIFICATION:
            first_word = text_clean.split()[0] if text_clean.split() else ""
            if first_word in IMPERATIVE_VERBS:
                _log("new_command_detected", {
                    "input": text[:200],
                    "verb": first_word,
                    "previous_state": current_state,
                })
                return ("new_command", text)

        return ("answer", text)

    def wait_for_response(self, timeout=60):
        """
        Block until a response arrives or timeout expires.
        Reads from the response queue (typically _confirmation_queue).

        Returns:
            (status, text) where status is:
                "answer"      — user provided a valid answer
                "cancelled"   — user said a cancel phrase
                "timeout"     — no response within timeout
                "new_command" — user started a new command (text contains the command)
        """
        if not self._response_queue:
            return ("timeout", "")

        try:
            raw_text = self._response_queue.get(timeout=timeout)
        except queue.Empty:
            return ("timeout", "")

        # Process the input through cancel/new-command detection
        status, text = self.handle_input(raw_text)

        if status == "new_command":
            # Clear the state — the new command will be processed by the caller
            self.clear()

        if status == "cancelled":
            # Clear the state
            self.clear()

        return (status, text)

    def route_input(self, text):
        """
        Called from process_command() when a state is active.
        Puts the text into the response queue for wait_for_response() to pick up.

        Returns True if the input was handled (should not be processed as a new command).
        Returns False if the input should be processed normally.

        Note: The actual cancel/new-command detection happens in wait_for_response(),
        not here. This just routes the text to the queue.
        """
        if not self.is_active():
            return False

        if self._response_queue:
            self._response_queue.put(text)
        return True

    def get_state_data(self):
        """Return a copy of the current state data dict."""
        with self._lock:
            return dict(self._state_data)


# ═══════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════

state_machine = StateMachine()


# ═══════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS (for toolExecutor.py and other modules)
# ═══════════════════════════════════════════════════════════════════════

def ask_for_approval_stateful(action_type, description, speak_fn=None, timeout=60):
    """
    Ask user for approval using the state machine.
    Returns True if approved, False if denied/cancelled/timed out.

    If user starts a new command during approval, the new command is
    processed recursively and this function returns False (not approved).
    """
    if not STATE_MACHINE_ENABLED:
        # Fallback to simple yes/no without state machine
        return True  # Approve by default if state machine is disabled

    if action_type not in getattr(config, 'APPROVAL_REQUIRED_ACTIONS', []):
        return True  # Action doesn't require approval

    speak = speak_fn or state_machine._speak_fn
    if speak is None:
        print(f"[StateMachine]: No speak function — denying {action_type}")
        return False

    prompt = f"Sir, I need your confirmation to {description}. Say confirm to proceed, or cancel to abort."

    state_machine.enter_state(
        state=AWAITING_APPROVAL,
        prompt=prompt,
        context={"action_type": action_type, "description": description},
        timeout=timeout,
        speak_fn=speak,
    )

    status, text = state_machine.wait_for_response(timeout=timeout)

    if status == "answer":
        resp_lower = text.lower().strip()
        confirm_words = ["confirm", "yes", "yeah", "yep", "yup", "ok", "okay", "proceed", "do it", "go ahead", "sure"]
        cancel_words = ["cancel", "no", "nope", "abort", "stop", "don't", "deny"]

        if any(w in resp_lower for w in confirm_words):
            return True
        elif any(w in resp_lower for w in cancel_words):
            return False
        else:
            # Ambiguous — ask once more
            state_machine.enter_state(
                state=AWAITING_APPROVAL,
                prompt="I didn't catch that. Please say confirm or cancel.",
                timeout=30,
                speak_fn=speak,
            )
            status2, text2 = state_machine.wait_for_response(timeout=30)
            if status2 == "answer":
                return any(w in text2.lower() for w in confirm_words)
            return False

    elif status == "cancelled":
        try:
            speak("Cancelled, Sir.")
        except Exception:
            pass
        return False

    elif status == "timeout":
        try:
            speak("Approval timed out, Sir.")
        except Exception:
            pass
        return False

    elif status == "new_command":
        # User started a new command — process it recursively
        # The state was already cleared by wait_for_response()
        try:
            speak("Cancelled. ")
        except Exception:
            pass
        # Process the new command
        # Note: This requires process_command to be passed in or available globally
        # For now, just return False — the text is logged for debugging
        _log("new_command_during_approval", {
            "action_type": action_type,
            "new_command": text[:200],
        })
        # The new command text is in the queue or needs to be re-injected
        # The caller (process_command) will handle this via the existing routing
        return False

    return False


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing State Machine (Phase 4)...\n")

    # Test 1: Cancel phrase detection
    print("=== Cancel Phrase Detection ===")
    sm = StateMachine()
    sm._current_state = AWAITING_APPROVAL  # Simulate active state
    test_cancels = [
        "cancel", "never mind", "forget it", "abort", "stop",
        "cancel that", "scratch that", "nevermind",
    ]
    for test in test_cancels:
        status, _ = sm.handle_input(test)
        label = "CANCEL" if status == "cancelled" else "NOT CANCEL"
        print(f"  [{label}] '{test}' → {status}")

    # Test 2: New command detection
    print("\n=== New Command Detection ===")
    sm._current_state = AWAITING_APPROVAL
    test_new_cmds = [
        "play some Drake", "open chrome", "set volume to 50",
        "shutdown the computer", "find my resume",
    ]
    for test in test_new_cmds:
        status, _ = sm.handle_input(test)
        label = "NEW CMD" if status == "new_command" else "ANSWER"
        print(f"  [{label}] '{test}' → {status}")

    # Test 3: AWAITING_ARG should NOT trigger new-command detection
    print("\n=== AWAITING_ARG (no new-command detection) ===")
    sm._current_state = AWAITING_ARG
    test_args = [
        "play",           # Could be a song name
        "open",           # Could be a file name
        "fifty percent",  # A value
    ]
    for test in test_args:
        status, _ = sm.handle_input(test)
        label = "NEW CMD" if status == "new_command" else "ANSWER"
        print(f"  [{label}] '{test}' → {status}")

    # Test 4: Normal answers
    print("\n=== Normal Answers ===")
    sm._current_state = AWAITING_APPROVAL
    test_answers = [
        "confirm", "yes", "no", "yeah", "ok",
        "Tokyo", "50", "the first one",
    ]
    for test in test_answers:
        status, _ = sm.handle_input(test)
        label = "ANSWER" if status == "answer" else "OTHER"
        print(f"  [{label}] '{test}' → {status}")

    # Test 5: State transitions
    print("\n=== State Transitions ===")
    sm._current_state = IDLE
    print(f"  Initial state: {sm.get_current_state()}")
    print(f"  is_active: {sm.is_active()}")
    sm._current_state = AWAITING_APPROVAL
    print(f"  After enter AWAITING_APPROVAL: {sm.get_current_state()}")
    print(f"  is_active: {sm.is_active()}")
    sm.clear()
    print(f"  After clear: {sm.get_current_state()}")
    print(f"  is_active: {sm.is_active()}")
