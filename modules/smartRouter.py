"""
JARVIS Smart Router Layers
================================================================
Architectural layers that make the 1.5B model function smarter
without upgrading the model itself.

Layers:
    1. PatternMatcher  — regex for common commands (instant, 100% accurate)
    2. EntityTracker   — tracks last file/song/app/note for pronoun resolution
    3. ConfidenceGate  — 1.5B outputs confidence, low → ask user or use Qwen 3
    4. Disambiguator   — when 1.5B is unsure between tools, asks user to choose
    5. ParamValidator  — code-level sanity checks before executing

These layers sit BETWEEN the acknowledgment fast-path and the 1.5B simple
dispatch. They catch easy cases instantly and help the 1.5B with hard cases.
"""
import os
import sys
import re
import json
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


# ═════════════════════════════════════════════════════════════
# LAYER 1: PATTERN MATCHER
# ═════════════════════════════════════════════════════════════
# Regex patterns for very common commands. Bypasses the model entirely.
# 100% accurate, instant (0 ms). Falls through to 1.5B if no match.

_PATTERNS = [
    # ── Volume ──────────────────────────────────────────────
    {
        "pattern": r"^(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})(?:\s*%|\s*percent)?\s*$",
        "tool": "set_volume",
        "args": lambda m: {"percent": max(0, min(100, int(m.group(1))))},
        "response": lambda m: f"Volume set to {m} percent, Sir.",
    },
    {
        "pattern": r"^(?:volume\s+up|make\s+it\s+louder|louder|increase\s+volume)\s*$",
        "tool": "set_volume",
        "args": lambda m: {"_action": "up"},
        "response": lambda m: "Volume increased, Sir.",
    },
    {
        "pattern": r"^(?:volume\s+down|make\s+it\s+quieter|quieter|softer|decrease\s+volume)\s*$",
        "tool": "set_volume",
        "args": lambda m: {"_action": "down"},
        "response": lambda m: "Volume decreased, Sir.",
    },
    {
        "pattern": r"^(?:mute|silence)\s*$",
        "tool": "set_volume",
        "args": lambda m: {"percent": 0},
        "response": lambda m: "Muted, Sir.",
    },

    # ── Brightness ──────────────────────────────────────────
    {
        "pattern": r"^(?:set\s+)?brightness\s+(?:to\s+)?(\d{1,3})(?:\s*%|\s*percent)?\s*$",
        "tool": "set_brightness",
        "args": lambda m: {"percent": max(0, min(100, int(m.group(1))))},
        "response": lambda m: f"Brightness set to {m} percent, Sir.",
    },

    # ── Open apps ───────────────────────────────────────────
    # Exclude "open it", "open that", "open the X" (where X is a noun like note/file/task)
    # These should fall through to entity resolution or the 1.5B.
    {
        "pattern": r"^(?:open|launch|start)\s+(?!it$|that$|the\s+note$|the\s+file$|the\s+task$|the\s+screenshot$|the\s+image$|the\s+document$)(.+?)\s*$",
        "tool": "open_app",
        "args": lambda m: {"app_name": m.group(1).strip()},
        "response": lambda m: f"Opening {m}, Sir.",
    },

    # ── Spotify ─────────────────────────────────────────────
    {
        "pattern": r"^(?:play|put\s+on)\s+(?:some\s+)?(.+?)\s*(?:on\s+spotify)?\s*$",
        "tool": "spotify_play",
        "args": lambda m: {"query": m.group(1).strip()},
        "response": lambda m: f"Playing {m}, Sir.",
    },
    {
        "pattern": r"^(?:pause|stop\s+(?:the\s+)?music)\s*$",
        "tool": "spotify_pause",
        "args": lambda m: {},
        "response": lambda m: "Paused, Sir.",
    },
    {
        "pattern": r"^(?:next|skip)\s*(?:song|track)?\s*$",
        "tool": "spotify_next",
        "args": lambda m: {},
        "response": lambda m: "Next track, Sir.",
    },
    {
        "pattern": r"^(?:previous|last|back)\s*(?:song|track)?\s*$",
        "tool": "spotify_previous",
        "args": lambda m: {},
        "response": lambda m: "Previous track, Sir.",
    },

    # ── Screenshot ──────────────────────────────────────────
    {
        "pattern": r"^(?:take\s+)?(?:a\s+)?screenshot(?:\s+(?:named|called)\s+(\S+))?\s*$",
        "tool": "take_screenshot",
        "args": lambda m: {"filename": m.group(1)} if m.group(1) else {},
        "response": lambda m: "Screenshot taken, Sir.",
    },

    # ── Timer ───────────────────────────────────────────────
    {
        "pattern": r"^(?:set\s+)?(?:a\s+)?(?:timer|reminder)\s+for\s+(\d+)\s*(second|sec|minute|min|hour|hr)s?\s*(?:called\s+(.+))?\s*$",
        "tool": "set_timer",
        "args": lambda m: {
            "duration_seconds": _parse_duration(int(m.group(1)), m.group(2)),
            "label": m.group(3) or "Timer",
        },
        "response": lambda m: "Timer set, Sir.",
    },

    # ── Notes ───────────────────────────────────────────────
    {
        "pattern": r"^(?:note|remember|jot\s+down)\s+(?:that\s+)?(.+?)\s*$",
        "tool": "save_note",
        "args": lambda m: {"title": m.group(1).strip()[:50], "content": m.group(1).strip()},
        "response": lambda m: "Noted, Sir.",
    },

    # ── Tasks ───────────────────────────────────────────────
    {
        "pattern": r"^(?:show|list)\s+(?:my\s+)?(?:tasks|to-?dos?)\s*$",
        "tool": "list_tasks",
        "args": lambda m: {},
        "response": lambda m: None,  # Will use tool result
    },
    {
        "pattern": r"^(?:show|list)\s+(?:my\s+)?(?:notes?)\s*$",
        "tool": "list_notes",
        "args": lambda m: {},
        "response": lambda m: None,
    },
    {
        "pattern": r"^(?:remove|delete|clear)\s+(?:all\s+)?(?:my\s+)?(?:tasks|to-?dos?)\s*$",
        "tool": "_bulk_delete_tasks",
        "args": lambda m: {},
        "response": lambda m: None,
    },
    {
        "pattern": r"^(?:remove|delete|clear)\s+(?:all\s+)?(?:my\s+)?(?:notes?)\s*$",
        "tool": "_bulk_delete_notes",
        "args": lambda m: {},
        "response": lambda m: None,
    },

    # ── System status ───────────────────────────────────────
    {
        "pattern": r"^(?:system\s+status|system\s+health|how'?s?\s+(?:my\s+)?(?:computer|pc|system))\s*$",
        "tool": "get_system_stats",
        "args": lambda m: {},
        "response": lambda m: None,
    },
    {
        "pattern": r"^(?:what'?s\s+running|show\s+running\s+apps|what\s+apps\s+are\s+open)\s*$",
        "tool": "list_running_apps",
        "args": lambda m: {},
        "response": lambda m: None,
    },
    # ── Vision (instant, no LLM) ─────────────────────────────────────
    # "what do you see" → camera_see (webcam)
    {
        "pattern": r"^(?:what(?:'s|s| do)?\s+(?:you\s+)?see|look around|describe what you see|what are you looking at|what(?:'s|s) in front of you|can you see me)\s*\??\s*$",
        "tool": "camera_see",
        "args": lambda m: {},
        "response": lambda m: None,
    },
    # "how do I look" → camera_see with appearance prompt
    {
        "pattern": r"^(?:how(?:'s|s| do)?\s+(?:i|do i)\s+look|how do i look today|do i look good|do i look okay|how does my (?:outfit|shirt|hair|face) look|rate my (?:outfit|fit|look|style))\s*\??\s*$",
        "tool": "camera_see",
        "args": lambda m: {"prompt": "You are JARVIS. The user is asking how they look. Look at the person in the image and give them a genuine, warm, and encouraging assessment of their appearance. Notice their outfit, style, grooming, and overall vibe. Be supportive and specific about what looks good. Address them as 'Sir'. Keep it conversational and under 3-4 sentences."},
        "response": lambda m: None,
    },
    # "what's on my screen" → describe_screen (screenshot)
    {
        "pattern": r"^(?:what(?:'s|s| is)?\s+on\s+(?:my\s+)?(?:screen|monitor|display)|describe (?:my\s+)?screen|read (?:my\s+)?screen|scan (?:my\s+)?screen|what(?:'s|s) showing)\s*\??\s*$",
        "tool": "describe_screen",
        "args": lambda m: {},
        "response": lambda m: None,
    },
    # ── Math (instant, no LLM) ──────────────────────────────────────
    # Catches any expression with numbers and math operators
    # Supports: +, -, *, /, %, parentheses, decimals, "what is", "calculate", "what's"
    {
        "pattern": r"^(?:what(?:'s|s| is)?|calculate|compute|solve)\s+([\d\s\+\-\*\/\%\(\)\.]+)\s*\??\s*$",
        "tool": "quick_calc",
        "args": lambda m: {"expression": m.group(1).strip()},
        "response": lambda m: None,  # Use tool result directly
    },
    # Pure math expression (no prefix word): "2 + 2", "15 * 3", "100 / 5"
    {
        "pattern": r"^([\d\s\+\-\*\/\%\(\)\.]+)\s*(?:=|equals?)?\s*\??\s*$",
        "tool": "quick_calc",
        "args": lambda m: {"expression": m.group(1).strip()},
        "response": lambda m: None,
    },
    # Percentage: "what is 15% of 200", "15 percent of 200"
    {
        "pattern": r"^(?:what(?:'s|s| is)?|calculate|compute)?\s*(\d+\.?\d*)\s*(?:%|percent)\s*(?:of)?\s*(\d+\.?\d*)\s*\??\s*$",
        "tool": "quick_calc",
        "args": lambda m: {"expression": f"({m.group(1)} / 100) * {m.group(2)}"},
        "response": lambda m: None,
    },
]


def _parse_duration(amount, unit):
    """Convert duration to seconds."""
    unit = unit.lower()
    if "sec" in unit:
        return amount
    elif "min" in unit:
        return amount * 60
    elif "hr" in unit or "hour" in unit:
        return amount * 3600
    return amount * 60  # Default to minutes


def try_pattern_match(user_input):
    """
    Try to match the input against common patterns.
    Returns a dict like route_with_tools() if matched, or None.
    """
    if not user_input:
        return None

    text = user_input.strip().lower().rstrip(".!?")

    for pat in _PATTERNS:
        match = re.match(pat["pattern"], text, re.IGNORECASE)
        if match:
            args = pat["args"](match)

            # Handle volume up/down specially
            if args.get("_action") == "up":
                try:
                    from systemControl import _get_volume_interface
                    vol = round(_get_volume_interface().GetMasterVolumeLevelScalar() * 100)
                    args = {"percent": min(100, vol + 10)}
                except Exception:
                    return None  # Can't read current volume — fall through
            elif args.get("_action") == "down":
                try:
                    from systemControl import _get_volume_interface
                    vol = round(_get_volume_interface().GetMasterVolumeLevelScalar() * 100)
                    args = {"percent": max(0, vol - 10)}
                except Exception:
                    return None

            return {
                "tool": pat["tool"],
                "args": args,
                "response_template": pat["response"],
                "match": match,
                "fast_path": "pattern_match",
            }

    return None


# ═════════════════════════════════════════════════════════════
# LAYER 2: ENTITY TRACKER
# ═════════════════════════════════════════════════════════════
# Tracks the last mentioned file, song, app, note, task.
# Auto-injects into 1.5B context so it can resolve "it" reliably.

_entity_lock = threading.Lock()
_entities = {
    "last_file": None,        # Last file path mentioned
    "last_song": None,        # Last song/artist mentioned
    "last_app": None,         # Last app opened
    "last_note": None,        # Last note title
    "last_task": None,        # Last task title
    "last_screenshot": None,  # Last screenshot filename
}


def update_entity(entity_type, value):
    """Update a tracked entity. entity_type: 'last_file', 'last_song', etc."""
    if not value:
        return
    with _entity_lock:
        _entities[entity_type] = value
        # Also save to disk for persistence across restarts
        try:
            entity_file = os.path.join(getattr(config, 'BASE_DIR', '.'), "entity_cache.json")
            with open(entity_file, 'w') as f:
                json.dump(_entities, f, indent=2)
        except Exception:
            pass


def get_entity(entity_type):
    """Get a tracked entity value."""
    with _entity_lock:
        return _entities.get(entity_type)


def get_entity_context():
    """Get a context string of all recent entities for injection into prompts."""
    with _entity_lock:
        lines = []
        if _entities.get("last_file"):
            lines.append(f"Last file mentioned: {_entities['last_file']}")
        if _entities.get("last_song"):
            lines.append(f"Last song mentioned: {_entities['last_song']}")
        if _entities.get("last_app"):
            lines.append(f"Last app opened: {_entities['last_app']}")
        if _entities.get("last_note"):
            lines.append(f"Last note: {_entities['last_note']}")
        if _entities.get("last_task"):
            lines.append(f"Last task: {_entities['last_task']}")
        if _entities.get("last_screenshot"):
            lines.append(f"Last screenshot: {_entities['last_screenshot']}")

        if not lines:
            return ""
        return "RECENT CONTEXT (use these to resolve 'it'):\n" + "\n".join(lines)


def load_entity_cache():
    """Load entity cache from disk at startup."""
    global _entities
    try:
        entity_file = os.path.join(getattr(config, 'BASE_DIR', '.'), "entity_cache.json")
        if os.path.exists(entity_file):
            with open(entity_file, 'r') as f:
                saved = json.load(f)
                with _entity_lock:
                    _entities.update(saved)
            print(f"[EntityTracker]: Loaded {len(_entities)} cached entities.")
    except Exception:
        pass


def resolve_pronoun(user_input):
    """
    Try to resolve 'it' in the user's input using tracked entities.
    Returns the resolved input, or the original if can't resolve.
    """
    if not user_input:
        return user_input

    text_lower = user_input.lower()

    # Only try to resolve if "it" is present
    if " it " not in f" {text_lower} " and not text_lower.endswith(" it"):
        return user_input

    # Try to figure out what "it" refers to based on the action verb
    with _entity_lock:
        # "open it" → last file or screenshot or app
        if "open it" in text_lower:
            if _entities.get("last_screenshot"):
                return user_input.replace(" it", f" {_entities['last_screenshot']}")
            if _entities.get("last_file"):
                return user_input.replace(" it", f" {_entities['last_file']}")

        # "play it" → last song
        if "play it" in text_lower:
            if _entities.get("last_song"):
                return user_input.replace(" it", f" {_entities['last_song']}")

        # "read it" → last file
        if "read it" in text_lower:
            if _entities.get("last_file"):
                return user_input.replace(" it", f" {_entities['last_file']}")

        # "delete it" → last file or note or task
        if "delete it" in text_lower:
            if _entities.get("last_file"):
                return user_input.replace(" it", f" {_entities['last_file']}")

    return user_input


# ═════════════════════════════════════════════════════════════
# LAYER 3: CONFIDENCE GATE
# ═════════════════════════════════════════════════════════════
# The 1.5B outputs a confidence score. If low, we ask the user or use Qwen 3.

CONFIDENCE_THRESHOLD = 0.6  # Below this → ask user or use Qwen 3


def parse_confidence(result):
    """
    Parse confidence from 1.5B output.
    Expected format: TOOL: X / ARGS: Y / CONF: 0.8
    Returns (tool_name, args, confidence) or (None, None, 0.0).
    """
    if not result:
        return None, None, 0.0

    # Check for COMPLEX
    if result.upper().strip().startswith("COMPLEX"):
        return None, None, 0.0

    # Check for AMBIGUOUS
    if result.upper().strip().startswith("AMBIGUOUS"):
        return None, None, 0.0

    tool_match = re.search(r'TOOL:\s*(\w+)', result, re.IGNORECASE)
    args_match = re.search(r'ARGS:\s*(\{.*?\})', result, re.IGNORECASE | re.DOTALL)
    conf_match = re.search(r'CONF:\s*([\d.]+)', result, re.IGNORECASE)

    if not tool_match:
        return None, None, 0.0

    tool_name = tool_match.group(1).strip()
    arguments = {}
    if args_match:
        try:
            arguments = json.loads(args_match.group(1))
        except json.JSONDecodeError:
            arguments = {}

    confidence = 0.7  # Default if not specified
    if conf_match:
        try:
            confidence = float(conf_match.group(1))
        except ValueError:
            confidence = 0.7

    return tool_name, arguments, confidence


# ═════════════════════════════════════════════════════════════
# LAYER 4: DISAMBIGUATOR
# ═════════════════════════════════════════════════════════════
# When the 1.5B is unsure between 2+ tools, it outputs:
#   AMBIGUOUS: tool1, tool2
# We ask the user to choose.

_pending_disambiguation = None  # Stores the ambiguous options


def check_disambiguation(user_input):
    """
    Check if the user is responding to a disambiguation prompt.
    Returns the chosen tool/args if yes, or None.
    """
    global _pending_disambiguation

    if not _pending_disambiguation:
        return None

    text = user_input.lower().strip()

    # User picked a number
    num_match = re.search(r'\b(\d+)\b', text)
    if num_match:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(_pending_disambiguation["options"]):
            chosen = _pending_disambiguation["options"][idx]
            _pending_disambiguation = None
            return chosen

    # User said the tool name or a keyword
    for i, option in enumerate(_pending_disambiguation["options"]):
        tool_name = option.get("tool", "")
        # Check if user said the tool name or a keyword from its description
        if tool_name.lower().replace("_", " ") in text:
            _pending_disambiguation = None
            return option

    # User said "cancel" or "never mind"
    if any(w in text for w in ["cancel", "never mind", "forget it", "nothing"]):
        _pending_disambiguation = None
        return {"cancel": True}

    return None  # Still ambiguous — will re-prompt


def create_disambiguation_prompt(options):
    """Create a disambiguation prompt for the user."""
    global _pending_disambiguation
    _pending_disambiguation = {"options": options}

    lines = ["Sir, I'm not sure which you meant. Did you mean:"]
    for i, opt in enumerate(options, 1):
        lines.append(f"  {i}. {opt.get('description', opt.get('tool', 'Unknown'))}")
    lines.append("\nSay the number, or cancel.")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════
# LAYER 5: PARAMETER VALIDATOR
# ═════════════════════════════════════════════════════════════
# Code-level sanity checks on tool arguments before executing.

_VALIDATORS = {
    "set_volume": lambda args: _validate_range(args, "percent", 0, 100),
    "set_brightness": lambda args: _validate_range(args, "percent", 0, 100),
    "set_timer": lambda args: _validate_positive(args, "duration_seconds"),
    "set_recurring_reminder": lambda args: _validate_positive(args, "interval_seconds"),
}


def _validate_range(args, param, min_val, max_val):
    """Validate that a parameter is within a range."""
    if param in args:
        try:
            val = int(args[param])
            if val < min_val or val > max_val:
                return False, f"{param} must be between {min_val} and {max_val}, got {val}"
        except (ValueError, TypeError):
            return False, f"{param} must be a number"
    return True, None


def _validate_positive(args, param):
    """Validate that a parameter is positive."""
    if param in args:
        try:
            val = int(args[param])
            if val <= 0:
                return False, f"{param} must be positive, got {val}"
        except (ValueError, TypeError):
            return False, f"{param} must be a number"
    return True, None


def validate_args(tool_name, args):
    """
    Validate tool arguments before execution.
    Returns (is_valid, error_message).
    """
    validator = _VALIDATORS.get(tool_name)
    if validator:
        return validator(args)
    return True, None  # No validator — assume valid


# ═════════════════════════════════════════════════════════════
# ENTITY EXTRACTION (from tool results)
# ═════════════════════════════════════════════════════════════

def extract_entities_from_result(tool_name, args, result):
    """Extract entities from tool execution results for future pronoun resolution."""
    result_str = str(result)

    if tool_name == "open_app":
        if "app_name" in args:
            update_entity("last_app", args["app_name"])

    elif tool_name == "spotify_play":
        if "query" in args:
            update_entity("last_song", args["query"])

    elif tool_name == "take_screenshot":
        # Extract filename from result
        # Look for patterns like "screenshot_20260808_051052.png"
        match = re.search(r'[\w_]+\.png', result_str)
        if match:
            update_entity("last_screenshot", match.group(0))

    elif tool_name == "save_note":
        if "title" in args:
            update_entity("last_note", args["title"])

    elif tool_name == "create_task":
        if "title" in args:
            update_entity("last_task", args["title"])

    elif tool_name == "search_files":
        # Extract first file path from result
        match = re.search(r'([A-Z]:\\[^\n]+\.\w+|/\w+[^\n]+\.\w+)', result_str)
        if match:
            update_entity("last_file", match.group(1))

    elif tool_name == "read_file":
        if "path" in args:
            update_entity("last_file", args["path"])


# ═════════════════════════════════════════════════════════════
# INITIALIZATION
# ═════════════════════════════════════════════════════════════

def initialize():
    """Load entity cache at startup."""
    load_entity_cache()


# Auto-init on import
initialize()
