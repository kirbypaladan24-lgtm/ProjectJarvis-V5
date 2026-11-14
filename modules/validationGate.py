"""
JARVIS Validation Gate (Phase 1)
================================================================
Independent validation layer that runs AFTER the 1.5B picks a tool
but BEFORE the tool is executed.

Three checks:
    1. Embedding similarity — is the picked tool semantically related to the input?
    2. Argument sanity — are the args valid (ranges, placeholders, file existence)?
    3. Verb alignment — does the user's action verb match the tool's primary verb?

Outcomes:
    - PASS (all checks clear) → execute the tool
    - BORDERLINE (similarity 0.40-0.60) → ask 8B for a second opinion
    - FAIL (similarity < 0.40, or arg sanity fails) → escalate to 8B

All decisions are logged to validation_log.jsonl for calibration.
"""
import os
import sys
import json
import time
import threading
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = _PARENT_DIR
        OLLAMA_BASE_URL = "http://localhost:11434"
        VOICE_FACE_MODEL = "qwen3:8b"
        EMBEDDING_MODEL = "nomic-embed-text"

import requests

# Phase 6: Per-tool threshold overrides
try:
    from per_tool_thresholds import get_thresholds as _get_per_tool_thresholds
    _HAS_PER_TOOL_THRESHOLDS = True
except ImportError:
    _HAS_PER_TOOL_THRESHOLDS = False
    def _get_per_tool_thresholds(tool_name):
        return (None, None)


# ─────────────────────────────────────────────────────────────
# CONFIG (sensible defaults — override in config.py)
# ─────────────────────────────────────────────────────────────

# Similarity thresholds (cosine similarity, 0.0 to 1.0)
VALIDATION_SIM_PASS      = getattr(config, 'VALIDATION_SIM_PASS', 0.60)   # >= 0.60 → pass
VALIDATION_SIM_BORDERLINE = getattr(config, 'VALIDATION_SIM_BORDERLINE', 0.40)  # 0.40-0.60 → second opinion
# < 0.40 → fail

# Whether to enable each check
VALIDATION_ENABLE_SIMILARITY = getattr(config, 'VALIDATION_ENABLE_SIMILARITY', True)
VALIDATION_ENABLE_ARG_SANITY = getattr(config, 'VALIDATION_ENABLE_ARG_SANITY', True)
VALIDATION_ENABLE_VERB_ALIGN = getattr(config, 'VALIDATION_ENABLE_VERB_ALIGN', False)  # Off by default — too aggressive
VALIDATION_ENABLE_LOGGING   = getattr(config, 'VALIDATION_ENABLE_LOGGING', True)

# Log file path
_LOG_FILE = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "validation_log.jsonl")
_log_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────
# VERB ALIGNMENT MAP
# ─────────────────────────────────────────────────────────────
# Maps user action verbs → tools that are valid for that verb.
# If the user's first verb is in this map but the picked tool isn't in the list,
# that's a verb mismatch (potential hallucination).
# Disabled by default — kept here for future enablement.

_VERB_TO_TOOLS = {
    "play":      {"spotify_play"},
    "pause":     {"spotify_pause"},
    "skip":      {"spotify_next"},
    "next":      {"spotify_next"},
    "previous":  {"spotify_previous"},
    "open":      {"open_app", "open_file"},
    "launch":    {"open_app"},
    "start":     {"open_app", "spotify_play", "set_timer", "set_recurring_reminder"},
    "close":     {"close_window", "kill_process"},
    "kill":      {"kill_process"},
    "set":       {"set_volume", "set_brightness", "set_timer", "set_recurring_reminder"},
    "find":      {"search_files", "semantic_file_search"},
    "search":    {"search_files", "semantic_file_search", "web_search"},
    "read":      {"read_file", "read_screen_text", "read_clipboard"},
    "save":      {"save_note", "save_fact"},
    "delete":    {"delete_task", "clear_memory"},
    "take":      {"take_screenshot"},
    "capture":   {"take_screenshot"},
    "create":    {"create_task", "save_note"},
    "add":       {"create_task", "save_note"},
    "list":      {"list_tasks", "list_notes", "list_timers", "list_running_apps"},
    "show":      {"list_tasks", "list_notes", "list_timers", "list_running_apps", "take_screenshot"},
    "shutdown":  {"shutdown_system"},
    "sleep":     {"sleep_system"},
    "restart":   {"shutdown_system"},
    "mute":      {"set_volume"},
    "note":      {"save_note"},
    "remember":  {"save_note", "save_fact"},
}


# ─────────────────────────────────────────────────────────────
# PLACEHOLDER DETECTION
# ─────────────────────────────────────────────────────────────
# Values the 1.5B sometimes invents for optional params it shouldn't fill.
_PLACEHOLDER_VALUES = {
    "your current location", "current location", "my location",
    "unknown", "null", "none", "n/a", "na", "default",
    "unspecified", "not specified", "unknown location",
    "today", "now",  # For location params — these aren't locations
    "file", "document",  # For path params — needs a real path
    "song", "music",  # For query params — needs a real song name
    "app", "application",  # For app_name params — needs a real app
    "something", "some text", "placeholder",
}


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def _log_validation(user_input, tool_name, args, result, details):
    """Append a validation decision to the JSONL log for calibration."""
    if not VALIDATION_ENABLE_LOGGING:
        return
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_input": user_input[:200],
            "tool_picked": tool_name,
            "args": {k: str(v)[:100] for k, v in args.items()},
            "result": result,  # "pass", "borderline", "fail"
            "details": details,
        }
        with _log_lock:
            with open(_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[ValidationGate]: Logging failed: {e}")


# ─────────────────────────────────────────────────────────────
# CHECK 1: EMBEDDING SIMILARITY
# ─────────────────────────────────────────────────────────────

def _get_input_embedding(text):
    """Get embedding for user input. Returns vector or None."""
    try:
        # Try /api/embed first (newer Ollama)
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/embed",
            json={"model": config.EMBEDDING_MODEL, "input": text},
            timeout=5
        )
        if r.status_code == 200:
            embs = r.json().get("embeddings", [])
            if embs:
                return embs[0]
    except Exception:
        pass
    try:
        # Fallback to /api/embeddings (older Ollama)
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/embeddings",
            json={"model": config.EMBEDDING_MODEL, "prompt": text},
            timeout=5
        )
        if r.status_code == 200:
            return r.json().get("embedding", [])
    except Exception:
        pass
    return None


def _cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _check_similarity(user_input, tool_name):
    """
    Compute cosine similarity between user input and the picked tool's description.
    Returns (similarity_score, status) where status is 'pass'/'borderline'/'fail'/'skip'.
    """
    if not VALIDATION_ENABLE_SIMILARITY:
        return 0.0, "skip"

    try:
        from toolEmbeddings import _tool_embeddings, _embeddings_initialized
    except Exception:
        return 0.0, "skip"

    # If embeddings aren't loaded yet, skip this check (don't block)
    if not _embeddings_initialized:
        return 0.0, "skip"

    tool_emb = _tool_embeddings.get(tool_name)
    if not tool_emb:
        # Tool has no embedding (maybe newly added) — skip, don't block
        return 0.0, "skip"

    input_emb = _get_input_embedding(user_input)
    if not input_emb:
        return 0.0, "skip"

    score = _cosine_similarity(input_emb, tool_emb)

    # Phase 6: Use per-tool thresholds if available (from per_tool_thresholds.py)
    # Falls back to global thresholds if no override exists for this tool
    if _HAS_PER_TOOL_THRESHOLDS:
        tool_pass, tool_borderline = _get_per_tool_thresholds(tool_name)
        if tool_pass is not None:
            # Per-tool override exists — use it
            if score >= tool_pass:
                return score, "pass"
            elif score >= tool_borderline:
                return score, "borderline"
            else:
                return score, "fail"

    # Global thresholds (default behavior)
    if score >= VALIDATION_SIM_PASS:
        return score, "pass"
    elif score >= VALIDATION_SIM_BORDERLINE:
        return score, "borderline"
    else:
        return score, "fail"


# ─────────────────────────────────────────────────────────────
# CHECK 2: ARGUMENT SANITY
# ─────────────────────────────────────────────────────────────

def _check_arg_sanity(tool_name, args):
    """
    Validate arguments beyond schema types:
      - Required params present and non-empty
      - No placeholder strings
      - Numeric ranges (uses contracts.py if available)
      - File path existence (for read_file, open_file)
    Returns (is_valid, list_of_issues).
    """
    if not VALIDATION_ENABLE_ARG_SANITY:
        return True, []

    issues = []

    # 1. Use contracts.py for schema + range validation
    try:
        from contracts import validate_input
        valid, errors = validate_input(tool_name, args)
        if not valid:
            issues.extend(errors)
            # Schema failures are hard fails — don't continue checking
            return False, issues
    except Exception:
        pass  # contracts.py not available — continue with our own checks

    # 2. Placeholder detection
    for key, value in args.items():
        if isinstance(value, str):
            val_lower = value.lower().strip()
            if val_lower in _PLACEHOLDER_VALUES:
                issues.append(f"Argument '{key}' has placeholder value '{value}'")

    # 3. File path existence (for file-reading tools)
    if tool_name in ("read_file", "open_file") and "path" in args:
        path = args["path"]
        if isinstance(path, str) and not os.path.exists(path):
            issues.append(f"File path does not exist: {path}")

    return len(issues) == 0, issues


# ─────────────────────────────────────────────────────────────
# CHECK 3: VERB ALIGNMENT (disabled by default)
# ─────────────────────────────────────────────────────────────

def _check_verb_alignment(user_input, tool_name):
    """
    Check if the user's first verb aligns with the picked tool.
    Returns (is_aligned, mismatch_detail).
    Disabled by default — too aggressive for natural language.
    """
    if not VALIDATION_ENABLE_VERB_ALIGN:
        return True, None

    words = user_input.lower().strip().split()
    if not words:
        return True, None

    first_verb = words[0].rstrip(",.!?")
    expected_tools = _VERB_TO_TOOLS.get(first_verb)

    # Verb not in map — can't check, assume aligned
    if not expected_tools:
        return True, None

    if tool_name in expected_tools:
        return True, None

    # Special case: "set volume" → first word "set", tool "set_volume" → aligned
    # The verb map already handles this, but double-check compound verbs
    if first_verb == "set" and tool_name.startswith("set_"):
        return True, None

    return False, f"User verb '{first_verb}' doesn't align with tool '{tool_name}' (expected one of {expected_tools})"


# ─────────────────────────────────────────────────────────────
# SECOND OPINION (8B model for borderline cases)
# ─────────────────────────────────────────────────────────────

def _ask_8b_second_opinion(user_input, tool_name, args):
    """
    Ask the 8B model whether the picked tool is correct for this input.
    Only called for borderline similarity scores.
    Returns True if 8B confirms, False if 8B rejects.
    """
    try:
        prompt = f"""You are JARVIS's validation system. A smaller model picked a tool for the user's request.
Decide if the tool selection is CORRECT.

User input: "{user_input}"
Tool picked: {tool_name}
Arguments: {json.dumps(args)}

Reply with EXACTLY one word:
- YES (if the tool is correct for this request)
- NO (if the tool is wrong, or the request needs a different tool, or it's too ambiguous)

Reply:"""

        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.VOICE_FACE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": 5, "temperature": 0.0},
            },
            timeout=15
        )
        if r.status_code == 200:
            answer = r.json().get("message", {}).get("content", "").strip().upper()
            return answer.startswith("YES")
    except Exception as e:
        print(f"[ValidationGate]: 8B second opinion failed: {e}")

    # On error, be conservative — reject (escalate to full 8B routing)
    return False


# ─────────────────────────────────────────────────────────────
# MAIN VALIDATION FUNCTION
# ─────────────────────────────────────────────────────────────

def validate_tool_selection(user_input, tool_name, args):
    """
    Run all validation checks on a tool selection.
    Returns a dict:
        {
            "decision": "pass" | "borderline_pass" | "fail",
            "checks": {
                "similarity": {"score": 0.72, "status": "pass"},
                "arg_sanity": {"valid": True, "issues": []},
                "verb_align": {"aligned": True, "detail": None},
            },
            "reason": "human-readable explanation",
        }
    """
    checks = {}
    reasons = []

    # Check 1: Similarity
    sim_score, sim_status = _check_similarity(user_input, tool_name)
    checks["similarity"] = {"score": round(sim_score, 3), "status": sim_status}
    if sim_status == "fail":
        reasons.append(f"similarity too low ({sim_score:.2f} < {VALIDATION_SIM_BORDERLINE})")
    elif sim_status == "borderline":
        reasons.append(f"similarity borderline ({VALIDATION_SIM_BORDERLINE} <= {sim_score:.2f} < {VALIDATION_SIM_PASS})")
    elif sim_status == "skip":
        reasons.append("similarity check skipped (embeddings not ready)")

    # Check 2: Arg sanity
    args_valid, arg_issues = _check_arg_sanity(tool_name, args)
    checks["arg_sanity"] = {"valid": args_valid, "issues": arg_issues}
    if not args_valid:
        reasons.append(f"argument issues: {'; '.join(arg_issues)}")

    # Check 3: Verb alignment (off by default)
    verb_aligned, verb_detail = _check_verb_alignment(user_input, tool_name)
    checks["verb_align"] = {"aligned": verb_aligned, "detail": verb_detail}
    if not verb_aligned:
        reasons.append(verb_detail)

    # ── Decide ────────────────────────────────────────────────
    # Hard fails: arg sanity failure, verb mismatch (when enabled)
    if not args_valid or not verb_aligned:
        decision = "fail"
        reason = "; ".join(reasons)
    # Similarity fail → fail
    elif sim_status == "fail":
        decision = "fail"
        reason = "; ".join(reasons)
    # Similarity borderline → ask 8B for second opinion
    elif sim_status == "borderline":
        print(f"[ValidationGate]: Borderline similarity ({sim_score:.2f}) — asking 8B for second opinion...")
        confirmed = _ask_8b_second_opinion(user_input, tool_name, args)
        if confirmed:
            decision = "borderline_pass"
            reason = f"borderline similarity ({sim_score:.2f}), 8B confirmed"
        else:
            decision = "fail"
            reason = f"borderline similarity ({sim_score:.2f}), 8B rejected"
    # All checks passed (or skipped)
    else:
        decision = "pass"
        reason = "all checks passed" if not reasons else "; ".join(reasons)

    result = {
        "decision": decision,
        "checks": checks,
        "reason": reason,
    }

    # Log the decision
    _log_validation(user_input, tool_name, args, decision, result)

    return result


# ─────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing Validation Gate...\n")
    print(f"  Similarity pass threshold:  >= {VALIDATION_SIM_PASS}")
    print(f"  Similarity borderline:      {VALIDATION_SIM_BORDERLINE} - {VALIDATION_SIM_PASS}")
    print(f"  Similarity fail:            < {VALIDATION_SIM_BORDERLINE}")
    print(f"  Arg sanity enabled:         {VALIDATION_ENABLE_ARG_SANITY}")
    print(f"  Verb alignment enabled:     {VALIDATION_ENABLE_VERB_ALIGN}")
    print(f"  Logging enabled:            {VALIDATION_ENABLE_LOGGING}")
    print(f"  Log file:                   {_LOG_FILE}")
    print()

    # Test cases (won't work without Ollama running, but shows the API)
    test_cases = [
        ("set volume to 50", "set_volume", {"percent": 50}),
        ("play some Drake", "spotify_play", {"query": "Drake"}),
        ("play some Drake", "set_volume", {"percent": 50}),  # Wrong tool
        ("set volume to 50", "set_volume", {"percent": 150}),  # Bad arg
        ("set volume to 50", "set_volume", {"percent": "your current location"}),  # Placeholder
    ]

    for user_input, tool, args in test_cases:
        print(f"  Input: '{user_input}' → {tool}({args})")
        result = validate_tool_selection(user_input, tool, args)
        print(f"    Decision: {result['decision']}")
        print(f"    Reason:   {result['reason']}")
        print()
