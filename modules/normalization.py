"""
JARVIS Command Normalization Layer (Phase 2)
================================================================
Conservative input normalization that runs AFTER preprocess_input
(phonetic/Tagalog/pronoun correction) but BEFORE the tool router.

Three functions:
1. split_multi_commands(input) — split "do X and do Y" into ["do X", "do Y"]
   ONLY splits when BOTH sides start with imperative verbs.
   Does NOT split "play Drake and Future" (noun after conjunction).
   Does NOT split dependent commands with pronouns ("find X and read it").

2. detect_incomplete(input, history) — detect "play" with no argument
   Only flags when no recent assistant question could resolve it.
   More thorough than clarify_partial (catches "set volume" with no value).

3. strip_leading_fillers(input) — remove "please", "can you" from the start
   Does NOT strip trailing fillers (too risky — "play the song called Please").
   Does NOT strip inside quotes or after "called/named".

Design principle: CONSERVATIVE. When uncertain, don't normalize — let the
tool router or 8B handle it. False splits and false incomplete flags are
worse than no normalization at all.
"""
import os
import sys
import re

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        pass


# ─────────────────────────────────────────────────────────────
# CONFIG (override in config.py)
# ─────────────────────────────────────────────────────────────

NORMALIZATION_ENABLE_SPLIT    = getattr(config, 'NORMALIZATION_ENABLE_SPLIT', True)
NORMALIZATION_ENABLE_INCOMPLETE = getattr(config, 'NORMALIZATION_ENABLE_INCOMPLETE', True)
NORMALIZATION_ENABLE_FILLERS  = getattr(config, 'NORMALIZATION_ENABLE_FILLERS', True)
NORMALIZATION_MAX_SUBCOMMANDS = getattr(config, 'NORMALIZATION_MAX_SUBCOMMANDS', 3)
NORMALIZATION_ENABLE_LOGGING  = getattr(config, 'NORMALIZATION_ENABLE_LOGGING', True)


# ─────────────────────────────────────────────────────────────
# IMPERATIVE VERBS
# ─────────────────────────────────────────────────────────────
# If a conjunction is followed by one of these, it's likely a new command.
# If followed by anything else (noun, adjective), it's part of the same command's argument.

IMPERATIVE_VERBS = {
    # Audio/Music
    "play", "pause", "skip", "next", "previous", "resume", "stop", "mute", "unmute",
    # Apps/System
    "open", "launch", "start", "close", "kill", "end", "quit",
    # Settings
    "set", "change", "adjust", "turn", "increase", "decrease", "lower", "raise",
    # Files
    "find", "search", "look", "locate", "read", "write", "save", "delete", "remove",
    "open", "rename", "move", "copy", "paste",
    # Tasks/Notes
    "create", "add", "note", "remember", "remind",
    # Screen
    "take", "capture", "screenshot",
    # Windows
    "minimize", "maximize", "restore", "focus", "switch", "show", "list", "display",
    # System power
    "shutdown", "sleep", "wake", "restart", "reboot",
    # Organization
    "organize", "clean", "tidy",
    # Code
    "run", "execute",
    # Network
    "check", "test",
    # Git
    "git",
    # Export
    "export", "import", "send",
    # Install
    "uninstall", "install", "enable", "disable",
}

# Verbs that REQUIRE an argument (can't stand alone)
VERBS_REQUIRING_ARGS = {
    "play", "open", "launch", "start", "close", "kill",
    "set", "change", "adjust",
    "find", "search", "look", "locate", "read", "write", "save", "delete", "remove",
    "create", "add", "note", "remember", "remind",
    "take", "capture",
    "run", "execute",
    "check", "test",
    "export", "send",
    "uninstall", "install",
}

# "set" commands that need a value — patterns that are complete
# "set volume to 50" = complete, "set volume" = incomplete, "set volume to" = incomplete
_SET_COMPLETE_PATTERNS = [
    r"set\s+(?:volume|brightness)\s+to\s+\d+",
    r"set\s+(?:volume|brightness)\s+\d+",
    r"set\s+(?:timer|alarm|reminder)\s+for\s+",
    r"set\s+(?:timer|alarm|reminder)\s+\d+",
]

# Conjunctions that might separate commands (checked longest first)
CONJUNCTIONS = [
    " and then ",
    " then also ",
    " and also ",
    " after that ",
    " then ",
    " also ",
    " and ",
]

# Pronouns that indicate the second command depends on the first
DEPENDENT_PRONOUNS = {"it", "that", "this", "them", "him", "her", "the same", "the file", "the note", "the task"}

# Leading fillers (safe to strip — these are always filler when at the start)
LEADING_FILLERS = [
    "hey jarvis ", "jarvis ", "ok jarvis ", "okay jarvis ",
    "please ", "can you ", "could you ", "would you ", "will you ",
    "i want you to ", "i need you to ", "help me ",
    "hi jarvis ", "yo jarvis ",
]


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def _log(action, details):
    """Log normalization decisions for debugging."""
    if not NORMALIZATION_ENABLE_LOGGING:
        return
    try:
        from datetime import datetime
        import json
        log_path = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "normalization_log.jsonl")
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# 1. MULTI-COMMAND SPLITTING
# ─────────────────────────────────────────────────────────────

def _starts_with_imperative_verb(text):
    """Check if text starts with an imperative verb."""
    text = text.strip()
    if not text:
        return False
    first_word = text.split()[0].lower().rstrip(",.!?;:'\"")
    return first_word in IMPERATIVE_VERBS


def _has_dependent_pronoun(text):
    """
    Check if text contains a pronoun that references a previous command's result.
    If so, don't split — the second command depends on the first.
    """
    text_lower = text.lower()
    words = set(re.findall(r'\b\w+\b', text_lower))
    # Check single-word pronouns
    for pronoun in ["it", "that", "this", "them", "him", "her"]:
        if pronoun in words:
            return True
    # Check multi-word pronoun phrases
    for phrase in ["the same", "the file", "the note", "the task"]:
        if phrase in text_lower:
            return True
    return False


def split_multi_commands(user_input):
    """
    Split a multi-command input into sub-commands.
    Only splits when a conjunction connects two imperative verbs.

    Examples:
        "set volume to 50 and play some Drake" → ["set volume to 50", "play some Drake"]
        "play Drake and Future" → ["play Drake and Future"]  (no split — "Future" is not a verb)
        "note that I need milk and eggs" → ["note that I need milk and eggs"]  (no split)
        "find my resume and read it" → ["find my resume and read it"]  (no split — "it" is dependent)

    Returns a list of commands (usually 1, sometimes 2-3).
    """
    if not NORMALIZATION_ENABLE_SPLIT:
        return [user_input]

    text = user_input.strip()
    if not text:
        return [text]

    # Try each conjunction (longest first to avoid partial matches)
    for conj in CONJUNCTIONS:
        lower_text = text.lower()
        search_from = 0

        while True:
            pos = lower_text.find(conj, search_from)
            if pos == -1:
                break

            # What comes after the conjunction
            after = text[pos + len(conj):].strip()
            if not after:
                search_from = pos + len(conj)
                continue

            # Does the second part start with an imperative verb?
            if not _starts_with_imperative_verb(after):
                # Not a verb — don't split here, continue searching
                search_from = pos + len(conj)
                continue

            # Second part starts with a verb — potential split point
            before = text[:pos].strip()

            # Check for dependent pronoun in the second part
            # If "read it" → "it" depends on "find my resume" → don't split, route to 8B
            if _has_dependent_pronoun(after):
                _log("split_skipped_dependent", {
                    "input": user_input[:200],
                    "reason": f"second part '{after[:50]}' has dependent pronoun",
                })
                return [user_input]  # Don't split — route to 8B as a workflow

            # Split here — recursively split the rest
            sub_after = split_multi_commands(after)

            result = [before] + sub_after
            # Cap at max sub-commands
            if len(result) > NORMALIZATION_MAX_SUBCOMMANDS:
                _log("split_capped", {
                    "input": user_input[:200],
                    "split_count": len(result),
                    "max": NORMALIZATION_MAX_SUBCOMMANDS,
                })
                result = result[:NORMALIZATION_MAX_SUBCOMMANDS]

            _log("split_success", {
                "input": user_input[:200],
                "commands": [c[:100] for c in result],
            })
            return result

    # No split point found — single command
    return [user_input]


# ─────────────────────────────────────────────────────────────
# 2. INCOMPLETE COMMAND DETECTION
# ─────────────────────────────────────────────────────────────

def _last_assistant_message_ended_with_question(history):
    """
    Check if the last assistant message ended with a question.
    If so, the current input might be an answer, not an incomplete command.
    """
    if not history:
        return False
    for msg in reversed(history[-3:]):
        if msg.get("role") == "assistant":
            content = msg.get("content", "").strip()
            if content.endswith("?"):
                return True
            break  # Only check the most recent assistant message
    return False


def detect_incomplete(user_input, conversation_history=None):
    """
    Detect incomplete commands (verb with no argument).
    Returns a clarification question, or None if the command seems complete.

    More thorough than clarify_partial:
    - Catches "set volume" (clarify_partial only catches exact "set")
    - Catches "play" and "open" (same as clarify_partial)
    - Skips if the last assistant message was a question (current input is an answer)

    Examples:
        "play" → "Play what, Sir?"
        "open" → "Open what, Sir?"
        "set volume" → "Set volume to what level, Sir?"
        "set volume to" → "Set volume to what level, Sir?"
        "find" → "Find what, Sir?"
        "set volume to 50" → None (complete)
        "play Drake" → None (complete)
    """
    if not NORMALIZATION_ENABLE_INCOMPLETE:
        return None

    text = user_input.lower().strip()
    if not text:
        return None

    # Remove trailing punctuation
    text = text.rstrip(".!?;:")
    words = text.replace("'", "").split()

    if not words:
        return None

    first_word = words[0].rstrip(",.!?;:'\"")

    # Only check verbs that require arguments
    if first_word not in VERBS_REQUIRING_ARGS:
        return None

    # If the last assistant message ended with a question, this might be an answer
    # (e.g., "What should I do?" → "play" means "I want to play")
    if _last_assistant_message_ended_with_question(conversation_history):
        return None

    # Special handling for "set" — needs "X to Y" or "X Y" pattern
    if first_word == "set":
        # Check if it matches a complete "set" pattern
        for pattern in _SET_COMPLETE_PATTERNS:
            if re.search(pattern, text):
                return None
        # "set volume" or "set volume to" or just "set" → incomplete
        if "volume" in words or "brightness" in words:
            return f"Set {words[1] if len(words) > 1 else 'that'} to what level, Sir?"
        elif "timer" in words or "alarm" in words or "reminder" in words:
            return f"For how long, Sir?"
        else:
            return f"Set what, Sir?"

    # For other verbs — check if there's at least 2 words (verb + object)
    if len(words) < 2:
        # Capitalize the verb for the question
        verb_display = first_word.capitalize()
        return f"{verb_display} what, Sir?"

    # "play" with only 1 word after might still be incomplete
    # ("play music" is complete, but "play some" is incomplete)
    # We'll be conservative — if there's at least 1 word after the verb, assume complete.
    # The tool router / 8B can ask for clarification if needed.

    return None


# ─────────────────────────────────────────────────────────────
# 3. LEADING FILLER STRIPPING
# ─────────────────────────────────────────────────────────────

def strip_leading_fillers(user_input):
    """
    Remove filler words from the START of a command.
    Does NOT strip trailing fillers (too risky — "play the song called Please").
    Does NOT strip inside quotes or after "called/named".

    Examples:
        "please open chrome" → "open chrome"
        "can you play some Drake" → "play some Drake"
        "hey jarvis set volume to 50" → "set volume to 50"
        "open the app called Please Don't Crash" → (unchanged — "please" is not at start)
    """
    if not NORMALIZATION_ENABLE_FILLERS:
        return user_input

    text = user_input.strip()
    if not text:
        return user_input

    original = text

    # Iteratively strip leading fillers (handles "hey jarvis please open chrome")
    changed = True
    while changed:
        changed = False
        for filler in LEADING_FILLERS:
            if text.lower().startswith(filler.lower()):
                text = text[len(filler):].strip()
                changed = True
                break

    # If we stripped everything, return the original (safety)
    if not text:
        return original

    return text


# ─────────────────────────────────────────────────────────────
# MAIN NORMALIZATION FUNCTION
# ─────────────────────────────────────────────────────────────

def normalize_command(user_input, conversation_history=None):
    """
    Main entry point. Normalizes user input before routing.

    Returns a dict:
        {
            "type": "single" | "multi" | "clarify",
            "command": "normalized single command",   # for "single"
            "commands": ["cmd1", "cmd2", ...],         # for "multi"
            "clarification": "question to ask user",   # for "clarify"
        }
    """
    if not user_input or not user_input.strip():
        return {"type": "single", "command": user_input}

    # Step 1: Strip leading fillers
    cleaned = strip_leading_fillers(user_input)

    # Step 2: Detect incomplete commands
    clarification = detect_incomplete(cleaned, conversation_history)
    if clarification:
        _log("incomplete_detected", {
            "input": user_input[:200],
            "cleaned": cleaned[:200],
            "clarification": clarification,
        })
        return {"type": "clarify", "clarification": clarification}

    # Step 3: Split multi-commands
    commands = split_multi_commands(cleaned)

    if len(commands) > 1:
        return {"type": "multi", "commands": commands}

    # Single command
    return {"type": "single", "command": commands[0]}


# ─────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing Normalization Layer (Phase 2)...\n")

    # Test 1: Multi-command split
    print("=== Multi-Command Splitting ===")
    test_splits = [
        "set volume to 50 and play some Drake",
        "play Drake and Future",  # Should NOT split
        "note that I need milk and eggs",  # Should NOT split
        "find my resume and read it",  # Should NOT split (dependent pronoun)
        "open chrome and open youtube",  # Should split
        "set volume to 50 then play some jazz",  # Should split
        "pause spotify and open visual studio code",  # Should split
    ]
    for test in test_splits:
        result = split_multi_commands(test)
        split_label = "SPLIT" if len(result) > 1 else "NO SPLIT"
        print(f"  [{split_label}] '{test}'")
        if len(result) > 1:
            for i, cmd in enumerate(result, 1):
                print(f"            {i}. {cmd}")

    # Test 2: Incomplete detection
    print("\n=== Incomplete Command Detection ===")
    test_incomplete = [
        ("play", None),  # Incomplete
        ("open", None),  # Incomplete
        ("set volume", None),  # Incomplete
        ("set volume to 50", None),  # Complete
        ("play Drake", None),  # Complete
        ("find", None),  # Incomplete
        ("hello", None),  # Not a verb requiring args
    ]
    for test, _ in test_incomplete:
        result = detect_incomplete(test, None)
        label = "INCOMPLETE" if result else "COMPLETE"
        print(f"  [{label}] '{test}' → {result or '(complete)'}")

    # Test 3: Filler stripping
    print("\n=== Leading Filler Stripping ===")
    test_fillers = [
        "please open chrome",
        "can you play some Drake",
        "hey jarvis set volume to 50",
        "open the app called Please Don't Crash",  # Should NOT strip
        "would you find my resume",
        "i want you to set volume to 50",
    ]
    for test in test_fillers:
        result = strip_leading_fillers(test)
        changed = "CHANGED" if result != test else "SAME"
        print(f"  [{changed}] '{test}' → '{result}'")

    # Test 4: Full normalization
    print("\n=== Full Normalization ===")
    test_full = [
        "please set volume to 50 and play some Drake",
        "can you play",
        "hey jarvis find my resume and read it",
        "note that I need milk and eggs",
    ]
    for test in test_full:
        result = normalize_command(test, None)
        print(f"  '{test}'")
        print(f"    → type: {result['type']}")
        if result["type"] == "single":
            print(f"    → command: '{result['command']}'")
        elif result["type"] == "multi":
            print(f"    → commands: {result['commands']}")
        elif result["type"] == "clarify":
            print(f"    → clarification: '{result['clarification']}'")
        print()
