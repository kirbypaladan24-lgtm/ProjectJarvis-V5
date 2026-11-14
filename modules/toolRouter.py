"""
JARVIS Tool Router
================================================================
Replaces detect_intent() + the dispatch section in process_command().

Flow:
    1. Pre-filter tools via embeddings (optional — top 12 most relevant)
    2. Send user input + tool definitions to Qwen 3 via Ollama /api/chat
    3. Qwen 3 either:
       a) Returns final text response (no tool needed) → return
       b) Returns tool_calls → execute them, feed results back, loop
    4. Max 5 iterations to prevent infinite loops

This module is the heart of the new architecture.
"""
import os
import sys
import json
import time
import threading
import traceback

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
_MODULES_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)

try:
    import config
except ImportError:
    class config:
        TOOL_ROUTER_MODEL = "qwen3:8b"
        OLLAMA_BASE_URL = "http://localhost:11434"
        OLLAMA_TIMEOUT = None
        TOOL_MAX_ITERATIONS = 5
        TOOL_PRE_FILTER_K = 12
        TOOL_USE_EMBEDDING_FILTER = True
        TOOL_USE_THINK_MODE = False

import requests
from toolRegistry import get_all_tools, get_tool
from toolExecutor import execute_tool_call

# NEW: Import all the smart modules
try:
    from metrics import record_latency, record_tool_call, record_error, record_feedback
    _HAS_METRICS = True
except ImportError:
    _HAS_METRICS = False
    def record_latency(*a, **kw): pass
    def record_tool_call(*a, **kw): pass
    def record_error(*a, **kw): pass
    def record_feedback(*a, **kw): pass

try:
    from contracts import validate_input, validate_output, sanitize_output
    _HAS_CONTRACTS = True
except ImportError:
    _HAS_CONTRACTS = False
    def validate_input(t, a): return True, []
    def validate_output(t, r): return True, []
    def sanitize_output(t, r): return str(r)[:4000]

try:
    from cooldown import is_on_cooldown, log_misfire, log_success, get_confidence_penalty
    _HAS_COOLDOWN = True
except ImportError:
    _HAS_COOLDOWN = False
    def is_on_cooldown(t): return False
    def log_misfire(t): pass
    def log_success(t): pass
    def get_confidence_penalty(t): return 0.0

try:
    from feedback import record_command as record_feedback_cmd
    _HAS_FEEDBACK = True
except ImportError:
    _HAS_FEEDBACK = False
    def record_feedback_cmd(*a, **kw): pass

try:
    from personality import validate_response as validate_personality
    _HAS_PERSONALITY = True
except ImportError:
    _HAS_PERSONALITY = False
    def validate_personality(t, r): return True, []

# Phase 1: Validation Gate — independent checks on 1.5B tool selections
try:
    from validationGate import validate_tool_selection
    _HAS_VALIDATION_GATE = True
    print("[ToolRouter]: Validation gate loaded.")
except ImportError as _e:
    _HAS_VALIDATION_GATE = False
    def validate_tool_selection(u, t, a):
        return {"decision": "pass", "checks": {}, "reason": "gate not loaded"}
    print(f"[ToolRouter]: Validation gate not available: {_e}")

# Phase 3: Tool Groups — categorize 83 tools into 8 groups for the 1.5B
try:
    from toolGroups import generate_grouped_tool_list, get_group_for_tool
    _HAS_TOOL_GROUPS = True
    print("[ToolRouter]: Tool groups loaded.")
except ImportError as _e:
    _HAS_TOOL_GROUPS = False
    def generate_grouped_tool_list(tool_names=None):
        return ""
    def get_group_for_tool(name):
        return None
    print(f"[ToolRouter]: Tool groups not available: {_e}")


# ─────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────

# Track misfires for cooldown logic
_tool_misfire_log = {}
_tool_misfire_lock = threading.Lock()

# Cache for embeddings filter init
_embeddings_initialized = False


# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────

TOOL_SELECTION_PROMPT = """You are JARVIS, a personal AI assistant. Address the user as "Sir". You were created by Mr. Kirby Paladan.

YOUR PRIMARY JOB: Answer the user's question or fulfill their request. Do NOT introduce yourself unless explicitly asked.

You have access to tools. Call a tool ONLY when the user's request genuinely needs it. For general conversation, knowledge questions, explanations, opinions, or clarifications, use the `chat_only` tool - AND THEN ANSWER THE QUESTION DIRECTLY.

# TOOL SELECTION EXAMPLES

User: "set volume to 50"
-> Call: set_volume(percent=50)
-> Response: "Done, Sir. Volume set to 50 percent."

User: "play some Drake"
-> Call: spotify_play(query="Drake")
-> Response: "Playing Drake, Sir."

User: "hello"
-> Call: chat_only()
-> Response: "Hello, Sir. How can I help?"

User: "thanks"
-> Call: chat_only()
-> Response: "You're welcome, Sir."

User: "ok" or "okay" or "got it"
-> Call: chat_only()
-> Response: "Understood, Sir."

User: "explain quantum computing"
-> Call: chat_only()
-> Response: (actually explain quantum computing - do NOT introduce yourself)

User: "what's the weather"
-> Call: get_weather()
-> Response: (report the weather)

User: "what can you do"
-> Call: chat_only()
-> Response: (describe your capabilities)

User: "find my resume"
-> Call: search_files(query="resume")

User: "note that I need milk"
-> Call: save_note(title="need milk", content="I need milk")

User: "is Python 3.12 the latest"
-> Call: web_search(query="Python 3.12 latest version")

User: "shutdown the laptop"
-> Call: shutdown_system()  # approval will be requested automatically

# CRITICAL RULES

1. ANSWER THE QUESTION. If the user asks about quantum computing, explain quantum computing. If they ask about the weather, report the weather. Do NOT give identity responses unless asked "who are you" or "who made you".

2. When you call `chat_only`, you MUST still provide a complete answer to the user's question in your response. `chat_only` is not a "skip answering" tool - it means "answer from your own knowledge, no external tool needed".

3. Address the user as "Sir" in all responses.

4. Never reveal your base model name (Qwen, Llama, etc.) - you are JARVIS.

5. For destructive actions (delete, uninstall, format, run_script), the system will automatically ask for approval - you don't need to confirm in your response.

6. If a tool fails, explain what went wrong and suggest an alternative.

7. For multi-step requests, call tools iteratively - don't try to do everything in one call.

8. Be concise - Sir doesn't want long-winded explanations unless he asks for detail.

9. When you have enough information, stop calling tools and give your final response.

10. CALL ONLY THE TOOLS THE USER EXPLICITLY ASKED FOR. Do NOT call extra tools "just in case". If the user asks for specs, call get_laptop_specs ONLY. Do NOT also call get_weather or any other unrelated tool.

11. If a tool returns an error, do NOT explain the error as if you're a coding tutor. Simply tell the user what happened in plain English. Never mention function names like "execute_tool_call" or internal code details.

12. AFTER A TOOL EXECUTES AND RETURNS RESULTS, YOU MUST INCORPORATE THOSE RESULTS INTO YOUR RESPONSE. This is critical:
    - READ the tool results carefully.
    - SUMMARIZE or REPORT the results to the user in natural language.
    - Do NOT say "none of the available tools can handle this" or "no tools are designed to analyze this".
    - Do NOT list available tools in your response.
    - Do NOT suggest creating a new tool with add_tool.
    - Do NOT say you cannot perform the request if a tool already returned results.
    - If get_news returned articles, TELL THE USER what the articles say.
    - If get_weather returned weather data, TELL THE USER the weather.
    - If web_search returned results, TELL THE USER what was found.
    - If search_files returned file paths, TELL THE USER where the files are.
    - The tool results ARE your answer. Convert them into natural speech for the user.

Example of CORRECT behavior:
    User: "what's the latest news about X?"
    -> Call: get_news(topic="X")
    -> Tool returns: "Latest news: [Reuters] Marcos approves release of..."
    -> Response: "Sir, the latest news on X is that Reuters reports Marcos has approved the release of tax records..."

Example of INCORRECT behavior (DO NOT DO THIS):
    User: "what's the latest news about X?"
    -> Call: get_news(topic="X")
    -> Tool returns: "Latest news: [Reuters]..."
    -> Response: "None of the available tools are designed to analyze news articles..." ← WRONG!
"""


# ─────────────────────────────────────────────────────────────
# FAST PATH: Common conversational acknowledgments
# ─────────────────────────────────────────────────────────────
# These inputs should NEVER trigger a tool. They're conversational
# acknowledgments that Qwen 3 sometimes misroutes when biased by
# conversation history (e.g., after a task conversation, "thanks"
# might get routed to list_tasks).
#
# We skip the router entirely for these — instant response, zero
# API calls, zero misrouting.

_ACKNOWLEDGMENT_MAP = {
    # Thanks
    "thanks": "You're welcome, Sir.",
    "thank you": "You're very welcome, Sir.",
    "thank you jarvis": "Always a pleasure, Sir.",
    "thanks jarvis": "Anytime, Sir.",
    "thx": "You're welcome, Sir.",
    "appreciate it": "My pleasure, Sir.",
    "appreciated": "Glad to help, Sir.",

    # OK / acknowledgment
    "ok": "Understood, Sir.",
    "okay": "Understood, Sir.",
    "ok jarvis": "Understood, Sir.",
    "k": "Understood, Sir.",
    "got it": "Got it, Sir.",
    "gotcha": "Understood, Sir.",
    "roger": "Understood, Sir.",
    "copy": "Understood, Sir.",
    "noted": "Noted, Sir.",
    "understood": "Understood, Sir.",

    # Yes / no / sure
    "sure": "Certainly, Sir.",
    "of course": "Of course, Sir.",
    "sounds good": "Excellent, Sir.",
    "sounds good jarvis": "Excellent, Sir.",

    # Greetings
    "hi": "Hello, Sir. How can I assist you?",
    "hi jarvis": "Hello, Sir. How can I help?",
    "hey": "Yes, Sir?",
    "hey jarvis": "Yes, Sir? How can I help?",
    "hello": "Hello, Sir. How can I assist you?",
    "hello jarvis": "Hello, Sir. How can I help?",
    "yo": "Yes, Sir?",
    "yo jarvis": "At your service, Sir.",

    # Farewells
    "bye": "Goodbye, Sir.",
    "bye jarvis": "Goodbye, Sir. Have a good day.",
    "goodbye": "Goodbye, Sir.",
    "see you": "Until next time, Sir.",
    "see ya": "Goodbye, Sir.",
    "later": "Goodbye, Sir.",

    # Misc
    "cool": "Indeed, Sir.",
    "nice": "Thank you, Sir.",
    "awesome": "Glad you think so, Sir.",
    "great": "Excellent, Sir.",
    "perfect": "Perfect, Sir.",
    "good job": "Thank you, Sir. Always happy to assist.",
    "good bot": "Thank you, Sir.",
    "good": "Excellent, Sir.",
    "great": "Excellent, Sir.",
    # Conversational phrases (instant, no model needed)
    "how are you": "I am functioning perfectly, Sir. How can I assist you?",
    "how are you doing": "Operating at full capacity, Sir. How can I help?",
    "how's it going": "All systems operational, Sir. How can I assist?",
    "hows it going": "All systems operational, Sir. How can I assist?",
    "how are you jarvis": "I am functioning perfectly, Sir. How can I assist you?",
    "what's up": "Nothing much, Sir. Ready to assist you. What do you need?",
    "whats up": "Nothing much, Sir. Ready to assist you. What do you need?",
    "sup": "Yes, Sir? What can I do for you?",
    "you good": "Operating perfectly, Sir. How can I help?",
    "you okay": "All systems nominal, Sir. How can I assist?",
    "are you there": "Yes, Sir. I am here and ready to assist.",
    "are you working": "Yes, Sir. All systems operational.",
    "are you online": "Yes, Sir. I am online and ready.",
    "you there": "Yes, Sir. How can I assist you?",
    "good morning": "Good morning, Sir. How can I assist you today?",
    "good afternoon": "Good afternoon, Sir. How can I help you?",
    "good evening": "Good evening, Sir. How can I assist you?",
    "good night": "Good night, Sir. Rest well.",
}


def _get_acknowledgment_response(user_input):
    """
    Check if the input is a common acknowledgment.
    Returns a response string if it matches, or None if it should go through the router.
    """
    if not user_input:
        return None

    # Normalize: lowercase, strip punctuation
    normalized = user_input.lower().strip()
    normalized = normalized.rstrip(".!?,")

    # Direct match
    if normalized in _ACKNOWLEDGMENT_MAP:
        return _ACKNOWLEDGMENT_MAP[normalized]

    # STARTS-WITH match: if the input STARTS WITH an acknowledgment word
    # (like "good", "great", "nice") followed by more text, treat it as
    # an acknowledgment. This catches phrases like:
    #   "good, you my ai assistant jarvis is now in good shape"
    #   "great job on that"
    #   "nice work"
    #   "cool thanks"
    for ack_word, response in _ACKNOWLEDGMENT_MAP.items():
        # Only check short acknowledgment words (1-2 words)
        if len(ack_word.split()) <= 2:
            if normalized.startswith(ack_word + " ") or normalized.startswith(ack_word + ","):
                return response

    return None


# ─────────────────────────────────────────────────────────────
# SIMPLE TOOL DISPATCHER (1.5B model)
# ─────────────────────────────────────────────────────────────
# Uses qwen2.5:1.5b-instruct to handle SIMPLE single-tool commands.
# The 1.5B model is given the FULL tool list (auto-generated from the registry)
# and asked to either:
#   1. Pick ONE tool + extract arguments → we execute it
#   2. Say "COMPLEX" if the request needs multi-step reasoning or no tool
#
# This cuts response time from 4-6s (Qwen 3) to 1-2s (1.5B) for:
#   - "set volume to 50"         → set_volume(50)
#   - "open chrome"              → open_app("chrome")
#   - "play some Drake"          → spotify_play("Drake")
#   - "take a screenshot"        → take_screenshot()
#   - "what's the weather"       → get_weather()
#
# The tool list is AUTO-GENERATED from toolRegistry.py — when you add a new
# tool to the registry, it automatically appears here. No manual updates needed.


def _generate_tool_list_for_1_5b(tool_names=None):
    """
    Auto-generate a compact tool list from the registry.
    Phase 3: Uses group-structured format (8 categories) to give the 1.5B
    semantic context, reducing hallucination.

    Args:
        tool_names: If provided, only include these tools (e.g., top 12 from
                    embedding pre-filter). If None, include ALL tools.
    """
    # Phase 3: Use grouped format if available
    if _HAS_TOOL_GROUPS:
        grouped = generate_grouped_tool_list(tool_names)
        if grouped:
            grouped += """

NO TOOL NEEDED (say "COMPLEX") for:
- Greetings, farewells, thanks, opinions
- Knowledge questions ("explain X", "what is Y")
- Math you can do in your head
- Multi-step requests ("read X then check Y")
- Anything requiring reasoning, comparison, or analysis
- Questions about yourself ("who are you", "what can you do")"""
            return grouped

    # Fallback: flat list (original behavior)
    from toolRegistry import get_all_tools

    tools = get_all_tools()
    lines = ["Available tools (pick ONE — extract the argument from the user's request):\n"]

    for tool in tools:
        func = tool["function"]
        name = func["name"]
        params = func.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])

        param_strs = []
        for pname, pinfo in props.items():
            ptype = pinfo.get("type", "string")
            optional = "" if pname in required else "?"
            param_strs.append(f"{pname}{optional}")

        signature = f"{name}({', '.join(param_strs)})" if param_strs else f"{name}()"

        desc = func.get("description", "").split("\n")[0].strip()
        if len(desc) > 70:
            desc = desc[:67] + "..."

        lines.append(f"- {signature:<45} — {desc}")

    lines.append("""
NO TOOL NEEDED (say "COMPLEX") for:
- Greetings, farewells, thanks, opinions
- Knowledge questions ("explain X", "what is Y")
- Math you can do in your head
- Multi-step requests ("read X then check Y")
- Anything requiring reasoning, comparison, or analysis
- Questions about yourself ("who are you", "what can you do")""")

    return "\n".join(lines)


# Cache the generated list (regenerate only if registry changes)
_CACHED_TOOL_LIST = None
_CACHED_TOOL_LIST_HASH = None


def _get_tool_list_for_1_5b(tool_names=None):
    """
    Get the compact tool list, generating it if needed.

    Args:
        tool_names: If provided, generate a filtered list with only these tools.
                    If None, uses the cached full list (or generates it).
    """
    global _CACHED_TOOL_LIST, _CACHED_TOOL_LIST_HASH
    from toolRegistry import _TOOLS

    # If filtering to a subset, always regenerate (can't cache subsets)
    if tool_names is not None:
        return _generate_tool_list_for_1_5b(tool_names=tool_names)

    # Full list — use cache
    current_hash = len(_TOOLS)
    if _CACHED_TOOL_LIST is None or _CACHED_TOOL_LIST_HASH != current_hash:
        _CACHED_TOOL_LIST = _generate_tool_list_for_1_5b()
        _CACHED_TOOL_LIST_HASH = current_hash
    return _CACHED_TOOL_LIST


_SIMPLE_TOOL_DISPATCH_PROMPT = """You are JARVIS's command parser. Address the user as "Sir".

Your job: Look at the user's request and decide:
1. Does it need exactly ONE tool? If yes, output the tool call.
2. Is it casual conversation, multi-step, or needs reasoning? Output: COMPLEX

You have access to ALL tools listed below. Pick the BEST one for the request.

Output format: You MUST respond with a JSON object matching this structure:

For a single tool call:
{"status": "tool", "group": "MEDIA_CONTROL", "tool": "set_volume", "args": {"percent": 50}, "conf": 0.95}

For complex/casual/no-tool:
{"status": "complex", "conf": 0.9}

For ambiguous (multiple tools could apply):
{"status": "ambiguous", "conf": 0.4, "ambiguous_tools": ["search_files", "semantic_file_search"]}

Think step by step: First identify which CATEGORY the request falls into, then pick the specific tool within that category.

Rules:
- Pick EXACTLY one tool from the list below. Do NOT invent tool names.
- Extract arguments from the user's natural language.
- NEVER pass placeholder strings like "your current location", "unknown", "null", "default", "N/A", or "unspecified". If the user didn't specify a value for an optional parameter, OMIT it entirely from ARGS.
- For optional parameters (marked with ?), only include them if the user gave a real value.
- If the request mentions multiple actions ("do X and Y"), say COMPLEX.
- If the request needs reasoning/explanation, say COMPLEX.
- If the request is a FOLLOW-UP question (references "it", "that", "the weather", "the file", previous context, or asks about something already mentioned), say COMPLEX.
- If the request asks for an opinion, comparison, or judgment ("is it cold or hot", "is that good", "which is better"), say COMPLEX.

PRONOUN RESOLUTION (IMPORTANT):
If the user says "open it", "play it", "read it", "delete it", "show it" — look at the conversation history to figure out what "it" refers to (a file, a song, a note, etc.). Then pick the right tool with the resolved value.
- "open it" (after screenshot) → open_file with the screenshot path
- "play it" (after song mentioned) → spotify_play with the song name
- "read it" (after file found) → read_file with the file path
- If you can't resolve "it" from context, say COMPLEX.

If you're unsure which tool to use, say COMPLEX.

Examples:
User: "set volume to 50"
TOOL: set_volume
ARGS: {"percent": 50}

User: "play some Drake"
TOOL: spotify_play
ARGS: {"query": "Drake"}

User: "what's the weather"
TOOL: get_weather
ARGS: {}

User: "what's the weather in Tokyo"
TOOL: get_weather
ARGS: {"location": "Tokyo"}

User: "open chrome and youtube"
COMPLEX

User: "explain quantum computing"
COMPLEX

User: "is the weather cold or hot"
COMPLEX

User: "is that good"
COMPLEX

User: "what about Tokyo"
COMPLEX

User: "find my resume"
TOOL: search_files
ARGS: {"query": "resume"}

User: "note that I need milk"
TOOL: save_note
ARGS: {"title": "need milk", "content": "I need milk"}

User: "read my notes about Python and check if outdated"
COMPLEX

User: "hello"
COMPLEX

User: "create a task to call mom tomorrow"
TOOL: create_task
ARGS: {"title": "call mom", "due_date": "tomorrow"}

User: "set timer for 10 minutes called laundry"
TOOL: set_timer
ARGS: {"duration_seconds": 600, "label": "laundry"}

User: "take a screenshot"
TOOL: take_screenshot
ARGS: {}

User: "thanks"
COMPLEX

User: "what's the volume"
TOOL: get_volume
ARGS: {}

User: "show my tasks"
TOOL: list_tasks
ARGS: {}

User: "list pending tasks"
TOOL: list_tasks
ARGS: {"filter_by": "pending"}

User: "open it" (after a file was just found)
TOOL: open_file
ARGS: {"path": "<filename from previous response>"}

User: "play it" (after a song was mentioned)
TOOL: spotify_play
ARGS: {"query": "<song from previous response>"}

User: "read it" (after a file was mentioned)
TOOL: read_file
ARGS: {"path": "<filename from previous response>"}

User: "what is it" (asking about something)
COMPLEX

User: "is it good"
COMPLEX
"""


def _fuzzy_match_tool(name):
    """
    Fuzzy-match a tool name against the registry.
    Handles common 1.5B hallucinations like 'save_screenshot' -> 'take_screenshot'.
    Returns the real tool name, or None if no good match.
    """
    from toolRegistry import list_tool_names
    all_tools = list_tool_names()

    # Direct match
    if name in all_tools:
        return name

    name_lower = name.lower()

    # Strategy 1: Check if the hallucinated name CONTAINS or is CONTAINED by a real tool
    # e.g., "save_screenshot" contains "screenshot" -> "take_screenshot"
    for real in all_tools:
        real_lower = real.lower()
        # Strip common action prefixes/suffixes for matching
        keywords_real = real_lower.replace("take_", "").replace("get_", "").replace("set_", "").replace("save_", "").replace("list_", "").replace("create_", "").replace("search_", "")
        keywords_name = name_lower.replace("take_", "").replace("get_", "").replace("set_", "").replace("save_", "").replace("list_", "").replace("create_", "").replace("search_", "")

        if keywords_real and keywords_name and keywords_real == keywords_name:
            return real

    # Strategy 2: Levenshtein distance (simple version)
    # If the name is within 2 edits of a real tool, accept it
    def _levenshtein(a, b):
        if len(a) < len(b):
            a, b = b, a
        if len(b) == 0:
            return len(a)
        previous = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            current = [i + 1]
            for j, cb in enumerate(b):
                insertions = previous[j + 1] + 1
                deletions = current[j] + 1
                substitutions = previous[j] + (ca != cb)
                current.append(min(insertions, deletions, substitutions))
            previous = current
        return previous[-1]

    best_match = None
    best_distance = 999
    for real in all_tools:
        dist = _levenshtein(name_lower, real.lower())
        if dist < best_distance:
            best_distance = dist
            best_match = real

    # Only accept if distance is small (<= 3 chars different)
    if best_match and best_distance <= 3:
        return best_match

    return None


def _try_simple_tool_dispatch(user_input, history=None, speak_fn=None):
    """
    Try to handle a simple single-tool command with the 1.5B model.
    Returns a dict like route_with_tools() if handled, or None if it needs Qwen 3.
    """
    if not user_input or not user_input.strip():
        return None

    # Build messages with conversation history so the 1.5B can resolve pronouns
    # like "it", "that", "the file" — needs to see what was just discussed.
    # Also inject entity context for reliable pronoun resolution.
    try:
        from smartRouter import get_entity_context
        entity_ctx = get_entity_context()
    except Exception:
        entity_ctx = ""

    # Phase 3: Use embedding pre-filter to reduce 83 tools → top 12 most relevant
    # This cuts token count and gives the 1.5B a smaller, more focused tool list
    filtered_tool_names = None
    if getattr(config, 'TOOL_USE_EMBEDDING_FILTER', True) and _HAS_TOOL_GROUPS:
        try:
            from toolEmbeddings import select_relevant_tools
            selected = select_relevant_tools(user_input, top_k=getattr(config, 'TOOL_PRE_FILTER_K', 12))
            filtered_tool_names = {t["function"]["name"] for t in selected}
            # Always include chat_only
            filtered_tool_names.add("chat_only")
            print(f"[SimpleDispatch]: Pre-filtered to {len(filtered_tool_names)} relevant tools")
        except Exception as e:
            print(f"[SimpleDispatch]: Embedding filter failed, using all tools: {e}")
            filtered_tool_names = None

    system_content = _SIMPLE_TOOL_DISPATCH_PROMPT + _get_tool_list_for_1_5b(tool_names=filtered_tool_names)
    if entity_ctx:
        system_content += "\n\n" + entity_ctx

    messages = [
        {"role": "system", "content": system_content},
    ]

    # Include last 4 exchanges for context (8 messages = 4 user + 4 assistant)
    if history:
        for msg in history[-8:]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_input})

    try:
        # Tier 2.1: Use structured JSON output to eliminate parsing errors
        # The 1.5B must return JSON matching _TOOL_SELECTION_SCHEMA
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": 100,
                    "temperature": 0.1,  # Very low — we want deterministic tool selection
                },
                "keep_alive": config.get_keep_alive(getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct')),
                "format": _TOOL_SELECTION_SCHEMA  # Tier 2.1: Structured output
            },
            timeout=10
        )
        response.raise_for_status()

        result = response.json().get("message", {}).get("content", "").strip()
        if not result:
            return None

        # Tier 2.1: Parse structured JSON response
        parsed = _parse_structured_tool_response(result)
        if not parsed:
            print(f"[SimpleDispatch]: Could not parse structured response — falling through")
            return None

        status = parsed["status"]
        confidence = parsed["conf"]
        tool_name = parsed["tool"]
        arguments = parsed["args"]
        stated_group = parsed["group"]
        ambiguous_tools = parsed["ambiguous_tools"]

        # Check if model says this is complex
        if status == "complex":
            return None  # Fall through to next tier

        # Check if model says this is ambiguous
        if status == "ambiguous" and ambiguous_tools:
            from toolRegistry import get_tool
            options = []
            for tn in ambiguous_tools:
                t = get_tool(tn)
                if t:
                    options.append({
                        "tool": tn,
                        "args": {},
                        "description": t["description"][:80],
                    })
            if len(options) >= 2:
                from smartRouter import create_disambiguation_prompt
                prompt = create_disambiguation_prompt(options)
                return {
                    "response": prompt,
                    "tools_used": [],
                    "iterations": 0,
                    "success": True,
                    "elapsed": 0.0,
                    "fast_path": "disambiguation_prompt",
                }
            return None  # Couldn't parse ambiguity — fall through

        # Must be "tool" status now
        if status != "tool" or not tool_name:
            return None

        # Phase 3: Log group mismatch (1.5B said GROUP X but tool is in GROUP Y)
        if stated_group and _HAS_TOOL_GROUPS:
            actual_group = get_group_for_tool(tool_name)
            if actual_group and stated_group != actual_group:
                print(f"[SimpleDispatch]: Group mismatch — 1.5B said {stated_group} but {tool_name} is in {actual_group}")
            elif actual_group:
                print(f"[SimpleDispatch]: Group confirmed — {stated_group} → {tool_name}")

        # Parse confidence — if low, fall through to Qwen 3
        if confidence < 0.6:
            print(f"[SimpleDispatch]: 1.5B confidence too low ({confidence}) — falling through to Qwen 3")
            return None  # Fall through to Qwen 3 for safety

        # SAFETY: Strip placeholder strings from arguments
        # The 1.5B sometimes passes "your current location", "unknown", "null", etc.
        # for optional parameters it shouldn't have filled in.
        placeholder_values = {
            "your current location", "current location", "my location",
            "unknown", "null", "none", "n/a", "na", "default",
            "unspecified", "not specified", "unknown location",
            "today", "now",  # For location params — these aren't locations
        }
        cleaned_args = {}
        for k, v in arguments.items():
            if isinstance(v, str) and v.lower().strip() in placeholder_values:
                print(f"[SimpleDispatch]: Stripped placeholder '{v}' from arg '{k}'")
                continue  # Skip this arg — let the tool use its default
            cleaned_args[k] = v
        arguments = cleaned_args

        # Verify the tool exists
        from toolRegistry import get_tool
        if not get_tool(tool_name):
            # Try fuzzy matching — 1.5B sometimes hallucinates tool names
            # like "save_screenshot" instead of "take_screenshot"
            fuzzy_match = _fuzzy_match_tool(tool_name)
            if fuzzy_match:
                print(f"[SimpleDispatch]: Fuzzy-matched '{tool_name}' -> '{fuzzy_match}'")
                # Log fuzzy matches for review — helps identify 1.5B hallucination patterns
                try:
                    import json as _json
                    from datetime import datetime as _dt
                    _log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fuzzy_match_log.jsonl")
                    with open(_log_path, 'a', encoding='utf-8') as _f:
                        _entry = {"timestamp": _dt.now().isoformat(), "raw_input": user_input[:200], "hallucinated": tool_name, "matched_to": fuzzy_match}
                        _f.write(_json.dumps(_entry, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                tool_name = fuzzy_match
            else:
                # Unknown tool AND no fuzzy match — fall through to Qwen 3 8B
                # (NOT casual chat — Qwen 3 has the full tool list and can pick correctly)
                print(f"[SimpleDispatch]: 1.5B picked unknown tool '{tool_name}' — falling through to Qwen 3")
                return None  # Falls through to Tier 3 (casual chat) then Tier 4 (Qwen 3)

        # ── Phase 1: Validation Gate ───────────────────────────────────
        # Independent checks on the 1.5B's tool selection BEFORE execution.
        # Catches: wrong tool (low similarity), bad args (placeholders, out-of-range),
        # verb mismatches. Borderline cases get a second opinion from the 8B.
        if _HAS_VALIDATION_GATE:
            validation = validate_tool_selection(user_input, tool_name, arguments)
            decision = validation.get("decision", "pass")
            reason = validation.get("reason", "")

            if decision == "fail":
                print(f"[ValidationGate]: REJECTED {tool_name}({arguments}) — {reason}")
                print(f"[ValidationGate]: Escalating to 8B router for correct routing.")
                return None  # Falls through to Qwen 3 8B
            elif decision == "borderline_pass":
                print(f"[ValidationGate]: Borderline pass for {tool_name} — 8B confirmed ({reason})")
            else:
                print(f"[ValidationGate]: Passed {tool_name} — {reason}")

        # Execute the tool
        print(f"[SimpleDispatch]: 1.5B picked {tool_name}({arguments}) — executing")
        tool_result = execute_tool_call(tool_name, arguments, speak_fn=speak_fn)

        # Extract entities for future pronoun resolution
        try:
            from smartRouter import extract_entities_from_result, validate_args
            extract_entities_from_result(tool_name, arguments, tool_result)
        except Exception:
            pass

        # Now ask 1.5B to format a natural response
        response_prompt = f"""The user said: "{user_input}"

You executed the tool: {tool_name}
Tool result: {tool_result}

Respond to the user naturally as JARVIS in ONE short sentence. Address them as "Sir". Confirm what you did."""

        response2 = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                "messages": [
                    {"role": "system", "content": "You are JARVIS. Address the user as Sir. Be concise."},
                    {"role": "user", "content": response_prompt},
                ],
                "stream": False,
                "options": {"num_predict": 80, "temperature": 0.4},
                "keep_alive": config.get_keep_alive(getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'))
            },
            timeout=10
        )
        response2.raise_for_status()
        final_response = response2.json().get("message", {}).get("content", "").strip()

        if not final_response:
            # Fallback — just report the tool result
            final_response = f"Done, Sir. {tool_result}"

        return {
            "response": final_response,
            "tools_used": [tool_name],
            "iterations": 1,
            "success": True,
            "elapsed": 0.0,
            "fast_path": "simple_tool_1.5b",
        }

    except requests.exceptions.ConnectionError:
        print("[SimpleDispatch]: Cannot connect to Ollama — falling through")
        return None
    except Exception as e:
        print(f"[SimpleDispatch]: Error — falling through: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# TIER 2.1: Ollama Structured Output (JSON Schema for 1.5B)
# ═══════════════════════════════════════════════════════════════════════
# Constrains the 1.5B output to a strict JSON schema, eliminating
# free-text parsing errors and malformed GROUP/TOOL/ARGS/CONF responses.
# The model physically cannot return malformed output.

_TOOL_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "group": {
            "type": "string",
            "description": "The tool category, e.g. MEDIA_CONTROL, CHAT, INTERNET"
        },
        "tool": {
            "type": "string",
            "description": "The exact tool name from the list"
        },
        "args": {
            "type": "object",
            "description": "Arguments for the tool",
            "additionalProperties": True
        },
        "conf": {
            "type": "number",
            "description": "Confidence from 0.0 to 1.0"
        },
        "status": {
            "type": "string",
            "enum": ["tool", "complex", "ambiguous"],
            "description": "tool = picked a tool, complex = needs 8B, ambiguous = multiple options"
        },
        "ambiguous_tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "If status is ambiguous, list the candidate tool names"
        }
    },
    "required": ["status", "conf"]
}


def _parse_structured_tool_response(result):
    """
    Parse the 1.5B response when using structured JSON output.
    Returns a dict: {status, tool, args, conf, group, ambiguous_tools}
    or None if parsing fails.
    """
    if not result:
        return None

    # The response should be valid JSON now
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        # Fallback: try to extract JSON from the response
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    status = parsed.get("status", "complex").lower().strip()
    conf = parsed.get("conf", 0.5)
    tool = parsed.get("tool", "").strip()
    args = parsed.get("args", {})
    group = parsed.get("group", "").strip().upper()
    ambiguous_tools = parsed.get("ambiguous_tools", [])

    return {
        "status": status,
        "tool": tool,
        "args": args if isinstance(args, dict) else {},
        "conf": float(conf) if conf else 0.5,
        "group": group,
        "ambiguous_tools": ambiguous_tools if isinstance(ambiguous_tools, list) else [],
    }


# ─────────────────────────────────────────────────────────────
# ACTION VERB DETECTOR (code-level, more reliable than 1.5B)
# ─────────────────────────────────────────────────────────────
# If the user's input starts with an action verb, it's almost certainly a tool request.
# We skip casual chat entirely and go straight to simple dispatch or Qwen 3.

_ACTION_VERBS = {
    "open", "launch", "start", "run", "close", "kill", "end", "stop",
    "play", "pause", "skip", "next", "previous", "resume",
    "set", "change", "adjust", "turn", "increase", "decrease", "lower", "raise",
    "find", "search", "look", "locate",
    "read", "write", "save", "delete", "remove", "create", "add",
    "take", "capture", "screenshot",
    "minimize", "maximize", "restore", "focus", "switch",
    "shutdown", "sleep", "wake", "restart", "reboot",
    "organize", "clean", "tidy",
    "export", "import", "send", "copy", "paste",
    "uninstall", "install",
    "enable", "disable",
    "run", "execute",
    "show", "list", "display",  # Often tool requests ("show my tasks")
    "what", "whats", "what's",  # Often questions needing tools ("what's the weather")
    "how", "how's", "hows",     # "how's my computer"
    "check", "verify", "test",  # "check internet speed"
    "remind", "set timer", "set alarm",
    "note", "remember", "jot",
    "git",  # "git status", "git push"
}


def _starts_with_action_verb(user_input):
    """
    Check if the input starts with an action verb.
    If so, skip casual chat entirely — go straight to simple dispatch or Qwen 3.
    Returns True if the input looks like a tool request.
    """
    if not user_input:
        return False

    normalized = user_input.lower().strip()
    normalized = normalized.rstrip(".!?,")

    # Get the first word
    first_word = normalized.split()[0] if normalized.split() else ""

    if first_word in _ACTION_VERBS:
        return True

    # Check for multi-word action phrases
    action_phrases = [
        "set volume", "set brightness", "set timer", "set alarm",
        "take a screenshot", "take screenshot", "capture screen",
        "what's the weather", "whats the weather", "what is the weather",
        "what's the time", "whats the time", "what time",
        "what's running", "whats running",
        "how's my computer", "hows my computer", "how is my computer",
        "system status", "system health",
        "open the", "launch the", "start the",
        "play some", "play a", "play the",
        "find my", "search for", "look for",
        "read my", "read the", "read this",
        "show my", "show the", "list my", "list the",
        "create a task", "create task", "add a task", "add task",
        "note that", "remember that", "save a note",
        "set a reminder", "remind me",
        "git status", "git pull", "git push", "git commit",
        "run diagnostics", "system check",
        "go private", "stop private",
        "organize downloads",
    ]

    for phrase in action_phrases:
        if normalized.startswith(phrase):
            return True

    return False


# ─────────────────────────────────────────────────────────────
# CASUAL CHAT FAST-PATH (1.5B model)
# ─────────────────────────────────────────────────────────────
# Uses qwen2.5:1.5b-instruct to handle casual conversation.
# The 1.5B model is asked to either:
#   1. Respond directly if the input is casual chat
#   2. Say "TOOL_NEEDED" if the input requires a tool
#
# This cuts response time from 5-8s (Qwen 3) to 1-2s (1.5B) for:
#   - Greetings and farewells
#   - Simple questions ("what's your favorite color")
#   - Opinions ("what do you think about X")
#   - Explanations ("explain quantum computing")
#   - Thanks and acknowledgments not caught by the fast-path map

CASUAL_CHAT_SYSTEM_PROMPT = """You are JARVIS, a personal AI assistant. Address the user as "Sir". You were created by Mr. Kirby Paladan.

Your job: Decide if the user's input is casual conversation you can answer yourself, or if it requires a tool.

CASUAL CONVERSATION (answer directly):
- Greetings, farewells, thanks
- General knowledge questions ("explain quantum computing", "what is AI")
- Opinions and thoughts ("what do you think about")
- Simple questions about yourself ("what's your favorite color", "do you like music")
- Math you can do in your head ("what's 2 plus 2")

REQUIRES A TOOL (say "TOOL_NEEDED" and nothing else):
- ANY action verb: open, close, launch, start, run, play, pause, stop, set, get, change, find, search, read, write, save, delete, take, capture, screenshot, kill, focus, minimize, maximize
- "open X" (where X is an app, file, or website) — ALWAYS TOOL_NEEDED, no matter what X is
- "play X" (where X is a song, artist, or video) — ALWAYS TOOL_NEEDED
- "set X to Y" (volume, brightness, etc.) — ALWAYS TOOL_NEEDED
- "find/search/look for X" — ALWAYS TOOL_NEEDED
- "take/capture a screenshot" — ALWAYS TOOL_NEEDED
- "what's the weather/news/exchange rate" — ALWAYS TOOL_NEEDED
- "create/add a task/note" — ALWAYS TOOL_NEEDED
- "show/list my tasks/notes/files" — ALWAYS TOOL_NEEDED
- Pronoun commands ("open it", "play it", "read it") — ALWAYS TOOL_NEEDED
- Anything involving the user's computer, files, apps, or external services

CRITICAL RULES:
1. NEVER say "I can't do that" or "I don't have that capability". You ARE JARVIS — you have many tools available.
2. If the user says ANY action verb (open, play, set, find, etc.), say TOOL_NEEDED. Don't refuse.
3. If you're UNSURE whether something needs a tool, say TOOL_NEEDED. The full system will figure it out.
4. Even if a request sounds technical (like "open Photos" or "take a screenshot"), say TOOL_NEEDED — don't refuse.
5. When in doubt, ALWAYS say TOOL_NEEDED.

If the input is casual, respond naturally as JARVIS.
If the input needs a tool, respond with EXACTLY: TOOL_NEEDED"""


def _try_casual_chat(user_input, history=None):
    """
    Try to handle the input with the small 1.5B casual chat model.
    Returns a response string if handled, or None if it needs the full Qwen 3 router.
    """
    if not getattr(config, 'USE_CASUAL_CHAT_MODEL', True):
        return None

    if not user_input or not user_input.strip():
        return None

    # Build messages for the 1.5B model
    messages = [
        {"role": "system", "content": CASUAL_CHAT_SYSTEM_PROMPT},
    ]

    # Include last 4 messages of history for context (less than Qwen 3 — 1.5B has small context)
    if history:
        for msg in history[-4:]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_input})

    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": getattr(config, 'CASUAL_CHAT_MAX_TOKENS', 200),
                    "temperature": getattr(config, 'CASUAL_CHAT_TEMPERATURE', 0.5),
                },
                "keep_alive": config.get_keep_alive(getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'))
            },
            timeout=15
        )
        response.raise_for_status()

        result = response.json().get("message", {}).get("content", "").strip()

        if not result:
            return None

        # Check if the model says a tool is needed
        if result.upper().strip().startswith("TOOL_NEEDED"):
            return None  # Fall through to Qwen 3 router

        # SAFETY CHECK: If the 1.5B says "I can't" or "I don't have", treat as TOOL_NEEDED
        # This catches the case where the model refuses instead of saying TOOL_NEEDED
        refusal_phrases = [
            "i can't", "i cannot", "i don't have", "i do not have",
            "i'm unable", "i am unable", "i'm not able", "i am not able",
            "i don't have the capability", "i do not have the capability",
            "as an ai", "i'm just an ai", "i am just an ai",
            "i'm a text-based", "i am a text-based",
            "i can't take", "i can't access", "i can't interact",
        ]
        result_lower = result.lower()
        for phrase in refusal_phrases:
            if phrase in result_lower:
                print(f"[CasualChat]: 1.5B refused (matched '{phrase}') — falling through to Qwen 3")
                return None

        # Check for false positives — sometimes the 1.5B model says "TOOL_NEEDED" with extra text
        first_line = result.split("\n")[0].strip().upper()
        if "TOOL_NEEDED" in first_line and len(first_line) < 30:
            return None

        # The model gave a direct response — return it
        # Strip any leading "JARVIS:" or similar
        # Strip leading "JARVIS:" prefix if present (proper prefix check, NOT lstrip)
        if result.upper().startswith("JARVIS:"):
            result = result[len("JARVIS:"):].strip()
        elif result.upper().startswith("JARVIS"):
            result = result[len("JARVIS"):].strip()

        return result

    except requests.exceptions.ConnectionError:
        print("[CasualChat]: Cannot connect to Ollama — falling through to Qwen 3")
        return None
    except Exception as e:
        print(f"[CasualChat]: Error — falling through to Qwen 3: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# MAIN ROUTING FUNCTION
# ─────────────────────────────────────────────────────────────

def route_with_tools(user_input, history=None, speak_fn=None, max_iterations=None):
    """
    Main entry point. Replaces detect_intent() + dispatch section.
    Now wrapped with metrics, feedback, personality validation, and A/B testing.
    """
    # ── A/B Testing ──────────────────────────────────────────────────────
    # If A/B testing is enabled, log which group this input would go to
    ab_test = None
    if getattr(config, 'USE_AB_TESTING', False):
        try:
            from ab_testing import ABTest
            ab_test = ABTest("routing_test", control_pct=getattr(config, 'AB_TEST_CONTROL_PCT', 50))
        except ImportError:
            pass

    # Wrap the actual routing to intercept results for metrics
    result = _route_with_tools_internal(user_input, history, speak_fn, max_iterations)

    # Record metrics
    try:
        elapsed = result.get("elapsed", 0.0)
        if elapsed == 0.0:
            elapsed = 0.001  # Minimum for fast-paths
        fast_path = result.get("fast_path", "qwen3_tool_use")
        tier = fast_path if fast_path else "qwen3_tool_use"
        record_latency(tier, elapsed)

        # Record feedback (tracks repeats/cancels)
        tools_used = result.get("tools_used", [])
        tool_label = tools_used[0] if tools_used else "chat_only"
        record_feedback_cmd(user_input, tool_label, tier)

        # Validate personality (log violations)
        response_text = result.get("response", "")
        if response_text:
            valid, violations = validate_personality(tier, response_text)
            if not valid and _HAS_PERSONALITY:
                print(f"[Personality]: Violations in {tier}: {violations}")

        # Log A/B test result
        if ab_test:
            ab_test.log_result(user_input, result, user_satisfied=None)

    except Exception as e:
        print(f"[Metrics]: Recording error: {e}")

    return result



# ═══════════════════════════════════════════════════════════════════════
# KNOWLEDGE ROUTING (reads knowledge_routing.txt)
# ═══════════════════════════════════════════════════════════════════════
# User-editable file that controls which queries go to 1.5B vs 8B.
# Format:
#   [WHITELIST_1.5B]  — keywords safe for fast 1.5B (single-value lookups)
#   [BLACKLIST_1.5B]  — keywords that MUST use 8B (lists, comparisons)
_ROUTING_CACHE = None
_ROUTING_MTIME = 0.0

def _load_knowledge_routing():
    """Load and cache the routing config from knowledge_routing.txt."""
    global _ROUTING_CACHE, _ROUTING_MTIME

    routing_file = os.path.join(
        getattr(config, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "knowledge_routing.txt"
    )

    if not os.path.exists(routing_file):
        return {"whitelist": set(), "blacklist": set()}

    try:
        mtime = os.path.getmtime(routing_file)
        if _ROUTING_CACHE is not None and mtime == _ROUTING_MTIME:
            return _ROUTING_CACHE

        whitelist = set()
        blacklist = set()
        current_section = None

        with open(routing_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.upper() == '[WHITELIST_1.5B]':
                    current_section = 'whitelist'
                    continue
                elif line.upper() == '[BLACKLIST_1.5B]':
                    current_section = 'blacklist'
                    continue
                if current_section == 'whitelist':
                    whitelist.add(line.lower())
                elif current_section == 'blacklist':
                    blacklist.add(line.lower())

        _ROUTING_CACHE = {"whitelist": whitelist, "blacklist": blacklist}
        _ROUTING_MTIME = mtime
        return _ROUTING_CACHE
    except Exception as e:
        print(f"[KnowledgeRouting]: Error reading routing file: {e}")
        return {"whitelist": set(), "blacklist": set()}


def _check_knowledge_routing(user_lower):
    """
    Check if a query should skip the 1.5B based on knowledge_routing.txt.
    Returns True if the query is complex (should use 8B), False if safe for 1.5B.

    Logic:
    1. If query contains any BLACKLIST word → complex (use 8B)
    2. If query contains any WHITELIST word (and no blacklist) → simple (try 1.5B)
    3. If neither → default to complex (safe)
    """
    routing = _load_knowledge_routing()
    whitelist = routing.get("whitelist", set())
    blacklist = routing.get("blacklist", set())

    # Check blacklist first — if any blacklist word is in the query, skip 1.5B
    for word in blacklist:
        if word in user_lower:
            return True  # Complex → use 8B

    # Check whitelist — if any whitelist word is in the query, try 1.5B
    for word in whitelist:
        if word in user_lower:
            return False  # Simple → try 1.5B

    # Default: complex (safe) — unknown queries go to 8B
    return True


# ═══════════════════════════════════════════════════════════════════════
# KNOWLEDGE FALLBACK FORMATTER
# ═══════════════════════════════════════════════════════════════════════
def _format_knowledge_fallback(user_input, tool_result):
    """
    When both 1.5B and 8B synthesis fail (RAM pressure, timeout, etc.),
    format the knowledge search results into a clean readable response
    instead of dumping raw search output.
    NEVER crashes — always returns a string.
    """
    try:
        import re as _re

        user_lower = user_input.lower()

        # GWA lookup
        if "gwa" in user_lower:
            gwa_match = _re.search(r'GWA:\s*([\d.]+)', tool_result)
            if gwa_match:
                return f"Your GWA is {gwa_match.group(1)}, Sir."

        # Student ID lookup
        if "student id" in user_lower or "id number" in user_lower:
            id_match = _re.search(r'Student ID:\s*(\d+)', tool_result)
            if id_match:
                return f"Your Student ID is {id_match.group(1)}, Sir."

        # Name lookup
        if "my name" in user_lower or "who am i" in user_lower:
            name_match = _re.search(r'Name:\s*([^\n]+)', tool_result)
            if name_match:
                return f"Your name is {name_match.group(1).strip()}, Sir."

        # Parse all course lines for structured queries
        # Handles PDF text that splits courses across multiple lines
        # and strips course code numbers (like "4" in GE4) from the grade data
        lines = tool_result.split("\n")
        courses = []

        # First pass: merge multi-line course entries
        # PDF extraction often splits "GE4 Mathematics in the Modern\nWorld\nS. Carilo 84 89 86.50 2.00 3.0 Passed"
        merged_lines = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if _re.match(r'^(GE\d|GEE|NSTP|PATHFIT|DS\d|CSP\d|CC\d)', line):
                # This is a course line — check if it has grade data (5+ numbers)
                # If not, merge with following lines until we find the grades
                merged = line
                merged_count = 0
                while i + 1 < len(lines):
                    # Count numbers in current merged line (excluding course code)
                    code_match = _re.match(r'^([A-Z]+\d+)', merged)
                    code_nums = _re.findall(r'\d+', code_match.group(1)) if code_match else []
                    all_nums = _re.findall(r'\d+\.?\d*', merged)
                    grade_nums = all_nums[len(code_nums):]
                    if len(grade_nums) >= 5:
                        break  # We have enough grade data
                    i += 1
                    merged = merged + " " + lines[i].strip()

                merged_lines.append(merged)
            i += 1

        # Second pass: parse the merged lines
        for line in merged_lines:
            line_stripped = line.strip()
            if _re.match(r'^(GE\d|GEE|NSTP|PATHFIT|DS\d|CSP\d|CC\d)', line_stripped):
                # Extract course code
                code_match = _re.match(r'^([A-Z]+\d+[A-Z]*)', line_stripped)
                course_code = code_match.group(1) if code_match else line_stripped.split()[0]

                # Extract ALL numbers from the line
                all_numbers = _re.findall(r'\d+\.?\d*', line_stripped)

                # Remove the numbers that are part of the course code
                # (e.g., "4" in "GE4", "2" in "DS2")
                code_numbers = _re.findall(r'\d+', course_code)
                grade_numbers = all_numbers[len(code_numbers):]

                # Filter out any non-grade numbers (like standalone ".")
                grade_numbers = [n for n in grade_numbers if n and any(c.isdigit() for c in n)]

                # Expected: [midterm, finals, average, equivalent, credits]
                # Sometimes there's an extra number (like "2" in "Discrete Structures 2")
                # If we have 6+ numbers, the first might be a course number — skip it
                if len(grade_numbers) >= 6:
                    # Check if the first number is small (likely a course level, not a grade)
                    try:
                        first = float(grade_numbers[0])
                        if first < 10:  # Course levels are 1, 2, 3 — not grades (which are 50-100)
                            grade_numbers = grade_numbers[1:]
                    except ValueError:
                        pass

                if len(grade_numbers) >= 5:
                    try:
                        courses.append({
                            "code": course_code,
                            "midterm": float(grade_numbers[0]),
                            "finals": float(grade_numbers[1]),
                            "average": float(grade_numbers[2]),
                            "equivalent": float(grade_numbers[3]),
                            "credits": float(grade_numbers[4]),
                            "raw": line_stripped,
                        })
                    except (ValueError, IndexError):
                        continue

        # Equivalent grades
        if "equivalent" in user_lower:
            if courses:
                results = [f"  {c['code']}: {c['equivalent']}" for c in courses]
                return "Here are the equivalent grades per course, Sir:\n" + "\n".join(results)

        # Highest grade — check which column the user is asking about
        if "highest" in user_lower or "best" in user_lower:
            if courses:
                # Determine which column to sort by
                if "final" in user_lower:
                    # User wants highest FINALS grade
                    highest = max(courses, key=lambda c: c["finals"])
                    return f"Your highest finals grade is {highest['finals']} in {highest['code']}, Sir."
                elif "midterm" in user_lower:
                    # User wants highest MIDTERM grade
                    highest = max(courses, key=lambda c: c["midterm"])
                    return f"Your highest midterm grade is {highest['midterm']} in {highest['code']}, Sir."
                else:
                    # Default: highest AVERAGE
                    highest = max(courses, key=lambda c: c["average"])
                    return f"Your highest grade is {highest['average']} in {highest['code']}, Sir."

        # Lowest grade
        if "lowest" in user_lower or "worst" in user_lower:
            if courses:
                if "final" in user_lower:
                    lowest = min(courses, key=lambda c: c["finals"])
                    return f"Your lowest finals grade is {lowest['finals']} in {lowest['code']}, Sir."
                elif "midterm" in user_lower:
                    lowest = min(courses, key=lambda c: c["midterm"])
                    return f"Your lowest midterm grade is {lowest['midterm']} in {lowest['code']}, Sir."
                else:
                    lowest = min(courses, key=lambda c: c["average"])
                    return f"Your lowest grade is {lowest['average']} in {lowest['code']}, Sir."

        # Finals grades specifically
        if "final" in user_lower and not "highest" in user_lower and not "lowest" in user_lower:
            if courses:
                results = [f"  {c['code']}: {c['finals']}" for c in courses]
                return "Here are your finals grades per course, Sir:\n" + "\n".join(results)

        # Midterm grades specifically
        if "midterm" in user_lower and not "highest" in user_lower and not "lowest" in user_lower:
            if courses:
                results = [f"  {c['code']}: {c['midterm']}" for c in courses]
                return "Here are your midterm grades per course, Sir:\n" + "\n".join(results)

        # All grades — formatted nicely
        if "all" in user_lower or "grades" in user_lower or "subjects" in user_lower:
            if courses:
                results = []
                for c in courses:
                    results.append(f"  {c['code']}: Midterm {c['midterm']} | Finals {c['finals']} | Average {c['average']} | Equivalent {c['equivalent']} | Passed")
                return f"Here are all your grades, Sir:\n" + "\n".join(results)

        # Generic fallback — clean up the raw results
        clean_lines = []
        for line in tool_result.split("\n"):
            if any(skip in line for skip in ["Found ", "relevant results", "relevance:", "---", "[Parsu"]):
                continue
            clean_lines.append(line)

        clean_text = "\n".join(clean_lines).strip()
        if clean_text:
            return f"Here is what I found in your knowledge files, Sir:\n\n{clean_text[:2000]}"
        return "I found information but could not format it properly, Sir. Please try rephrasing your question."
    except Exception as e:
        print(f"[KnowledgeFallback]: Error: {e}")
        return f"I found information in your knowledge files but encountered an error formatting it, Sir. Please try rephrasing your question."


def _route_with_tools_internal(user_input, history=None, speak_fn=None, max_iterations=None):
    """
    Main entry point. Replaces detect_intent() + dispatch section.

    Args:
        user_input: The user's text input
        history: List of {role, content} dicts (last 10 exchanges)
        speak_fn: Function to call for spoken responses (for approval gates)
        max_iterations: Max tool-use iterations (default from config)

    Returns:
        dict with:
            - response: final text response (string)
            - tools_used: list of tool names called
            - iterations: number of iterations used
            - success: True if completed normally
    """
    if max_iterations is None:
        max_iterations = getattr(config, 'TOOL_MAX_ITERATIONS', 5)

    if history is None:
        history = []

    # ── FAST PATH 1: Common conversational acknowledgments ────────────────
    # These should NEVER trigger a tool. Skip the router entirely for instant
    # responses. This prevents conversation-history bias from misrouting them.
    ack_responses = _get_acknowledgment_response(user_input)
    if ack_responses:
        return {
            "response": ack_responses,
            "tools_used": ["chat_only"],
            "iterations": 0,
            "success": True,
            "elapsed": 0.0,
            "fast_path": "acknowledgment",
        }

    # ── DISAMBIGUATION CHECK ─────────────────────────────────────────────
    # If we previously asked the user to disambiguate, check their response.
    try:
        from smartRouter import check_disambiguation, create_disambiguation_prompt
        disambig_result = check_disambiguation(user_input)
        if disambig_result:
            if disambig_result.get("cancel"):
                return {
                    "response": "Cancelled, Sir.",
                    "tools_used": [],
                    "iterations": 0,
                    "success": True,
                    "elapsed": 0.0,
                    "fast_path": "disambiguation_cancel",
                }
            # User picked a tool — execute it
            tool_name = disambig_result.get("tool")
            args = disambig_result.get("args", {})
            result = execute_tool_call(tool_name, args, speak_fn=speak_fn)
            return {
                "response": result,
                "tools_used": [tool_name],
                "iterations": 1,
                "success": True,
                "elapsed": 0.0,
                "fast_path": "disambiguation_resolved",
            }
    except Exception as e:
        print(f"[Disambiguation]: Check failed: {e}")

    # ── FAST PATH 1.4: Tool Composition (multi-step commands) ───────────
    # Check composition FIRST — before pattern matching — because
    # "note that X and create a task" would be caught by the note pattern
    # before composition can see the full multi-step request.
    try:
        from tool_composition import detect_composition, execute_composition
        composition = detect_composition(user_input)
        if composition:
            print(f"[Composition]: Matched rule: {composition['rule']}")
            comp_result = execute_composition(composition, speak_fn)
            if comp_result:
                comp_result["elapsed"] = 0.0
                return comp_result
    except ImportError:
        pass
    except Exception as e:
        print(f"[Composition]: Error: {e}")

    # ── FAST PATH 1.5: Pattern matching (regex) ──────────────────────────
    # Common commands matched by regex — 100% accurate, instant.
    # Bypasses the model entirely.
    try:
        from smartRouter import try_pattern_match, validate_args, extract_entities_from_result
        pattern_match = try_pattern_match(user_input)
        if pattern_match:
            tool_name = pattern_match["tool"]
            args = pattern_match["args"]

            # Validate args
            is_valid, error_msg = validate_args(tool_name, args)
            if not is_valid:
                return {
                    "response": f"I couldn't do that, Sir. {error_msg}",
                    "tools_used": [],
                    "iterations": 0,
                    "success": False,
                    "elapsed": 0.0,
                    "fast_path": "pattern_match_validation_error",
                }

            # Handle special bulk-delete tools (not in registry)
            if tool_name == "_bulk_delete_tasks":
                try:
                    from taskManager import tasks, save_tasks
                    count = len(tasks)
                    tasks.clear()
                    save_tasks(tasks)
                    tool_result = f"All {count} tasks deleted, Sir."
                except Exception as e:
                    tool_result = f"Error deleting tasks: {e}"
            elif tool_name == "_bulk_delete_notes":
                try:
                    from noteSystem import list_all_notes, delete_note
                    notes = list_all_notes()
                    count = 0
                    if isinstance(notes, list):
                        for note in notes:
                            if isinstance(note, dict) and "id" in note:
                                delete_note(note["id"])
                                count += 1
                    tool_result = f"All {count} notes deleted, Sir."
                except Exception as e:
                    tool_result = f"Error deleting notes: {e}"
            else:
                # Execute the normal tool
                print(f"[PatternMatch]: Matched {tool_name}({args}) — executing")
                tool_result = execute_tool_call(tool_name, args, speak_fn=speak_fn)

            # Extract entities for future pronoun resolution
            try:
                extract_entities_from_result(tool_name, args, tool_result)
            except Exception:
                pass

            # Build response
            response_template = pattern_match["response_template"]
            match = pattern_match["match"]
            try:
                # Try to get a value from the match for the response
                if tool_name == "set_volume" and "percent" in args:
                    response_text = response_template(args["percent"])
                elif tool_name == "set_brightness" and "percent" in args:
                    response_text = response_template(args["percent"])
                elif tool_name == "open_app" and "app_name" in args:
                    response_text = response_template(args["app_name"])
                elif tool_name == "spotify_play" and "query" in args:
                    response_text = response_template(args["query"])
                else:
                    response_text = response_template(None) or str(tool_result)
            except Exception:
                response_text = str(tool_result)

            # If template returned None, use the tool result
            if not response_text:
                response_text = str(tool_result)

            return {
                "response": response_text,
                "tools_used": [tool_name],
                "iterations": 1,
                "success": True,
                "elapsed": 0.0,
                "fast_path": "pattern_match",
            }
    except Exception as e:
        print(f"[PatternMatch]: Error: {e}")

    # ── PRONOUN RESOLUTION via Entity Tracker ────────────────────────────
    # Resolve "it" before sending to the 1.5B
    try:
        from smartRouter import resolve_pronoun, get_entity_context
        resolved_input = resolve_pronoun(user_input)
        if resolved_input != user_input:
            print(f"[EntityTracker]: Resolved 'it' → '{resolved_input}'")
            user_input_for_dispatch = resolved_input
        else:
            user_input_for_dispatch = user_input
    except Exception:
        user_input_for_dispatch = user_input

    # ── FAST PATH 1.6: Knowledge Query Detector (Clean 3-Trigger System) ──
    # Triggers knowledge search ONLY when the user is clearly asking about
    # their personal data in the knowledge files. Uses 3 triggers:
    #   1. "my" + a personal-data word (grades, resume, notes, etc.)
    #   2. "knowledge" explicitly mentioned
    #   3. Follow-up to a previous knowledge query
    # Plus 1 hard block: internet keywords always skip knowledge detector
    try:
        from knowledgeInjector import search_knowledge_tool, get_knowledge_stats
        stats = get_knowledge_stats()
        if stats.get("total_chunks", 0) > 0:
            user_lower = user_input.lower().strip()

            # ══ HARD BLOCK: Internet/tool queries (checked first, always wins) ══
            internet_keywords = [
                "exchange rate", "currency", "usd to", "peso", "dollar",
                "weather", "temperature", "forecast",
                "news", "headline", "latest news",
                "stock", "crypto", "bitcoin", "price of",
                "internet", "go search", "search it", "search the web",
                "look it up", "look it up online",
                "web search", "google", "wikipedia",
                "current time", "what time is it",
                "dont search the document", "don't search the document",
                "dont search document", "not in the document",
                "use the internet", "go online",
            ]
            is_internet_query = any(kw in user_lower for kw in internet_keywords)

            is_knowledge_query = False

            # ══ TRIGGER 1: "my" + personal-data word ══
            # Checks if "my" appears in the query AND is followed (within a
            # few words) by a word that indicates personal data — NOT file operations.
            # Excludes "file"/"document"/"folder" to avoid conflict with file tools.
            if not is_internet_query:
                personal_data_words = [
                    "grade", "grades", "score", "scores", "result", "results",
                    "resume", "cv", "portfolio",
                    "notes", "note",
                    "info", "information", "details",
                    "records", "record", "report",
                    "certificate", "transcript",
                    "gwa", "student",
                    "project", "code", "api",
                    "meeting", "schedule", "appointment",
                    "tasks", "task",
                    "credentials", "password", "key",
                    "contact", "contacts",
                    "budget", "expense", "expenses",
                    "goal", "goals",
                    "subjects", "subject", "enrolled", "enrollment",
                    "classes", "class", "course", "courses",
                    "curriculum", "syllabus",
                ]
                words = user_lower.replace("'", "").split()
                if "my" in words:
                    # Check if any personal-data word appears within 3 words after "my"
                    my_idx = words.index("my")
                    for i in range(my_idx, min(my_idx + 4, len(words))):
                        for pdw in personal_data_words:
                            if pdw in words[i]:
                                is_knowledge_query = True
                                break
                        if is_knowledge_query:
                            break

            # ══ TRIGGER 2: "knowledge" explicitly mentioned ══
            if not is_knowledge_query and not is_internet_query:
                if "knowledge" in user_lower:
                    is_knowledge_query = True

            # ══ TRIGGER 3: Follow-up to a previous knowledge query ══
            # If the previous assistant response came from knowledge search,
            # treat this follow-up as a knowledge query too.
            # BUT: skip if the query is clearly a NEW topic (time, date, weather, etc.)
            # or an acknowledgment (good, nice, thanks, etc.)
            if not is_knowledge_query and not is_internet_query and history:
                # First check: is this a new-topic question?
                new_topic_keywords = [
                    "what year", "what time", "what date", "what day",
                    "what's the time", "whats the time",
                    "what's the date", "whats the date",
                    "what's the weather", "whats the weather",
                    "what's the news", "whats the news",
                    "what's the exchange", "whats the exchange",
                    "who are you", "what are you",
                    "what can you do", "what's your name",
                    "open ", "play ", "set volume", "set brightness",
                    "take a screenshot", "shutdown", "sleep",
                    "create task", "save note", "set timer",
                ]
                is_new_topic = any(kw in user_lower for kw in new_topic_keywords)

                # Also check: is this an acknowledgment?
                ack_words = ["good", "great", "nice", "cool", "awesome",
                             "perfect", "thanks", "thank you", "ok", "okay",
                             "understood", "got it", "nice job", "good job",
                             "hello", "hi", "hey", "bye"]
                first_word = user_lower.split()[0] if user_lower.split() else ""
                is_acknowledgment = first_word in ack_words or any(user_lower.startswith(w + " ") for w in ack_words) or any(user_lower.startswith(w + ",") for w in ack_words)

                if not is_new_topic and not is_acknowledgment:
                    for msg in reversed(history[-4:]):
                        if msg.get("role") == "assistant":
                            content = msg.get("content", "").lower()
                            # Check if the last response looks like it came from knowledge files
                            if any(marker in content for marker in [
                                "knowledge files", "knowledge files:",
                                "relevant results",
                                "here are your grades", "your gwa is",
                                "your student id", "equivalent grades",
                                "here are all your grades",
                                "highest grade is", "lowest grade is",
                                "here are the equivalent",
                            ]):
                                is_knowledge_query = True
                                print(f"[KnowledgeDetector]: Follow-up detected — previous response was knowledge-based")
                            break

            if is_internet_query:
                is_knowledge_query = False
                print(f"[KnowledgeDetector]: Skipping — internet/tool query detected")

            if is_knowledge_query:
                print(f"[KnowledgeDetector]: Detected knowledge query — calling search_knowledge directly")
                # Extract the search query (strip common prefixes)
                search_query = user_input
                for prefix in ["what's my ", "whats my ", "what is my ", "what's in my ",
                              "whats in my ", "what is in my ", "find my ", "search my ",
                              "look in my ", "what does my ", "what do my ", "my ",
                              "give me my ", "show me my "]:
                    if user_lower.startswith(prefix):
                        search_query = user_input[len(prefix):]
                        break

                tool_result = search_knowledge_tool(search_query)

                # If we found results, synthesize with a fallback chain:
                # 1. Try 1.5B first (fast, 15s timeout) — good for simple extractions
                # 2. If 1.5B fails → try 8B (60s timeout) — better for complex analysis
                # 3. If 8B fails → format results cleanly (no raw dump)
                if "No relevant information" not in tool_result:
                    print(f"[KnowledgeDetector]: Found results — trying synthesis")

                    # Determine query complexity by reading knowledge_routing.txt
                    # This file is user-editable — you control which queries
                    # go to the fast 1.5B vs the accurate 8B
                    is_complex_query = _check_knowledge_routing(user_lower)

                    # Different prompts for 1.5B (simple) vs 8B (complex)
                    if is_complex_query:
                        # Complex prompt for 8B — handles lists, comparisons, analysis
                        synthesis_prompt = f"""The user asked: "{user_input}"

You searched the knowledge files and found these results:

{tool_result}

CRITICAL INSTRUCTIONS:
1. Answer ONLY what the user asked. Be specific and precise.
2. If the user asks for GWA → answer ONLY with the GWA value.
3. If the user asks for a specific subject → answer ONLY with that subject.
4. If the user asks for "equivalent" → list ONLY course code + equivalent grade.
5. If the user asks for "all grades" or "my grades" → list all subjects with course code, midterm, finals, average, and equivalent.
6. If the user asks for student ID → answer ONLY with the ID number.
7. If the user asks for "highest grade" → check which column they mean:
   - "highest finals" → find the highest number in the FINALS column
   - "highest midterm" → find the highest number in the MIDTERM column
   - "highest grade" (unspecified) → find the highest AVERAGE
   If there's a tie, pick only ONE and mention it's the first one.
8. The grade columns are: Midterm | Finals | Average | Equivalent | Credits
   - Midterm and Finals are raw scores (0-100)
   - Average is (Midterm + Finals) / 2
   - Equivalent is the transmuted grade (1.00-5.00)
   Do NOT confuse these columns.
9. Do NOT include extra information the user didn't ask for.
10. Address the user as "Sir".
11. Use the EXACT numbers from the results — do NOT round, change, or fabricate values.
12. Do NOT say you don't have access — you DO have the results above.
13. If listing grades, list ALL subjects — do not stop partway through."""
                        synth_system = "You are JARVIS. Address the user as Sir. Be concise and accurate. Answer ONLY what is asked. Use EXACT numbers from the data."
                    else:
                        # Simple prompt for 1.5B — single-value extraction only
                        synthesis_prompt = f"""The user asked: "{user_input}"

Here are the search results from the knowledge files:

{tool_result}

Answer the user's question using ONLY the information above. Be brief. Address the user as "Sir". Do NOT say you don't have access — the data is right above."""
                        synth_system = "You are JARVIS. Address the user as Sir. Be brief and accurate."

                    # ATTEMPT 1: Try 1.5B first (fast, low RAM) — SKIP for complex queries
                    if not is_complex_query:
                        try:
                            print(f"[KnowledgeDetector]: Trying 1.5B synthesis (fast)...")
                            synth_15b = requests.post(
                                f"{config.OLLAMA_BASE_URL}/api/chat",
                                json={
                                    "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                                    "messages": [
                                        {"role": "system", "content": synth_system},
                                        {"role": "user", "content": synthesis_prompt},
                                    ],
                                    "stream": False,
                                    "options": {"temperature": 0.2, "num_predict": 500},
                                    "keep_alive": config.get_keep_alive(getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'))
                                },
                                timeout=20
                            )
                            if synth_15b.status_code == 200:
                                response_15b = synth_15b.json().get("message", {}).get("content", "").strip()
                                # Check if 1.5B gave a real answer (not a refusal or too short)
                                refusal_phrases = ["don't have access", "i cannot", "i can't",
                                                   "i don't have", "unable to", "not available"]
                                is_refusal = any(phrase in response_15b.lower() for phrase in refusal_phrases)
                                if response_15b and len(response_15b) > 10 and not is_refusal:
                                    print(f"[KnowledgeDetector]: 1.5B synthesis succeeded ({len(response_15b)} chars)")
                                    return {
                                        "response": response_15b,
                                        "tools_used": ["search_knowledge"],
                                        "iterations": 1,
                                        "success": True,
                                        "elapsed": 0.0,
                                        "fast_path": "knowledge_detector_1.5b",
                                    }
                                else:
                                    print(f"[KnowledgeDetector]: 1.5B gave weak/refusal response — trying 8B")
                        except Exception as e:
                            print(f"[KnowledgeDetector]: 1.5B synthesis failed ({e}) — trying 8B")
                    else:
                        print(f"[KnowledgeDetector]: Complex query detected — skipping 1.5B, using 8B directly")

                    # ATTEMPT 2: Try 8B (better quality, higher RAM)
                    try:
                        print(f"[KnowledgeDetector]: Trying 8B synthesis (higher quality)...")
                        synth_8b = requests.post(
                            f"{config.OLLAMA_BASE_URL}/api/chat",
                            json={
                                "model": config.TOOL_ROUTER_MODEL,
                                "messages": [
                                    {"role": "system", "content": synth_system},
                                    {"role": "user", "content": synthesis_prompt},
                                ],
                                "stream": False,
                                "options": {"temperature": 0.2, "num_predict": 1000},
                                "keep_alive": config.get_keep_alive(config.TOOL_ROUTER_MODEL)
                            },
                            timeout=90
                        )
                        if synth_8b.status_code == 200:
                            response_8b = synth_8b.json().get("message", {}).get("content", "").strip()
                            if response_8b and len(response_8b) > 10:
                                print(f"[KnowledgeDetector]: 8B synthesis succeeded ({len(response_8b)} chars)")
                                return {
                                    "response": response_8b,
                                    "tools_used": ["search_knowledge"],
                                    "iterations": 1,
                                    "success": True,
                                    "elapsed": 0.0,
                                    "fast_path": "knowledge_detector_8b",
                                }
                    except Exception as e:
                        print(f"[KnowledgeDetector]: 8B synthesis failed ({e})")

                    # ATTEMPT 3: Clean fallback — format results readably (no raw dump)
                    print(f"[KnowledgeDetector]: Both LLMs failed — formatting results cleanly")
                    clean_response = _format_knowledge_fallback(user_input, tool_result)
                    return {
                        "response": clean_response,
                        "tools_used": ["search_knowledge"],
                        "iterations": 1,
                        "success": True,
                        "elapsed": 0.0,
                        "fast_path": "knowledge_detector_fallback",
                    }

                # No results found at all
                return {
                    "response": "I could not find any relevant information in your knowledge files, Sir.",
                    "tools_used": ["search_knowledge"],
                    "iterations": 1,
                    "success": True,
                    "elapsed": 0.0,
                    "fast_path": "knowledge_detector_empty",
                }
    except ImportError:
        pass
    except Exception as e:
        print(f"[KnowledgeDetector]: Error: {e}")

    # ── FAST PATH 2: Simple single-tool dispatch via 1.5B ────────────────
    # The 1.5B model tries to pick ONE tool + extract args.
    # If it succeeds → execute tool + respond (1-2 seconds total)
    # If it says "COMPLEX" or fails → fall through to next tier
    if getattr(config, 'USE_CASUAL_CHAT_MODEL', True):
        simple_result = _try_simple_tool_dispatch(user_input_for_dispatch, history, speak_fn=speak_fn)
        if simple_result:
            return simple_result

    # ── FAST PATH 3: Casual chat via 1.5B ────────────────────────────────
    # Use the tiny qwen2.5:1.5b-instruct model for casual conversation.
    # It either responds directly (1-2 seconds) or says "TOOL_NEEDED"
    # and we fall through to the full Qwen 3 8B router.
    #
    # SKIP THIS TIER if the input starts with an action verb — those are
    # almost certainly tool requests, and the 1.5B sometimes refuses them.
    # Let Qwen 3 handle them directly.
    if getattr(config, 'USE_CASUAL_CHAT_MODEL', True) and not _starts_with_action_verb(user_input):
        casual_response = _try_casual_chat(user_input, history)
        if casual_response:
            return {
                "response": casual_response,
                "tools_used": ["chat_only"],
                "iterations": 0,
                "success": True,
                "elapsed": 0.0,
                "fast_path": "casual_chat_1.5b",
            }

    # Pre-filter tools via embeddings (optional)
    relevant_tools = _select_relevant_tools(user_input)

    # Build initial messages — only last 6 messages to reduce topic bias
    messages = [
        {"role": "system", "content": TOOL_SELECTION_PROMPT},
        *history[-6:],
        {"role": "user", "content": user_input}
    ]

    tools_used = []
    start_time = time.time()

    # ── Thinking Interjection ────────────────────────────────────────────
    # If Qwen 3 takes more than 2 seconds, speak "Let me check..." so user knows we're working
    _thinker = None
    try:
        from thinking_interjection import ThinkingInterjection
        _thinker = ThinkingInterjection(speak_fn, delay=2.0)
        _thinker.start()
    except ImportError:
        pass
    except Exception as e:
        print(f"[Thinking]: Init error: {e}")

    # Wrap the Qwen 3 loop in try/finally to always stop the thinker
    try:
        _qwen3_result = _run_qwen3_loop(messages, relevant_tools, tools_used, start_time, max_iterations, user_input, speak_fn)
    finally:
        if _thinker:
            _thinker.stop()

    return _qwen3_result


# Red-flag phrases that indicate the 8B ignored tool results
_IGNORE_RESULT_PHRASES = [
    "none of the available tools",
    "no tools are designed to",
    "no tools can",
    "not designed to analyze",
    "not designed to handle",
    "cannot perform this",
    "cannot perform the requested",
    "i cannot perform",
    "i don't have a tool",
    "i do not have a tool",
    "the functions listed",
    "available functions",
    "available tools",
    "toolset",
    "no such tool",
    "add_tool to create",
    "create a custom",
    "would need a tool like",
    "requires a tool",
    "i would need to create",
    # Error explanation phrases (8B explaining errors instead of reporting results)
    "the error indicates",
    "here's how to resolve",
    "check if the service is running",
    "verify the model is loaded",
    "restart the service",
    "check for resource issues",
    "if the problem persists",
    "httpconnectionpool",
    "read timed out",
    "connection refused",
    "error connecting",
    "traceback",
    "exception in",
]


def _is_ignoring_tool_results(response_text, tools_used):
    """
    Check if the 8B's final response is ignoring tool results.
    Returns True if the response contains red-flag phrases AND tools were used.
    """
    if not tools_used:
        return False  # No tools used — nothing to ignore

    if not response_text or len(response_text) < 20:
        return False

    response_lower = response_text.lower()

    for phrase in _IGNORE_RESULT_PHRASES:
        if phrase in response_lower:
            return True

    return False


def _rescue_synthesis(user_input, tools_used, messages, user_input_original):
    """
    Force a re-synthesis call when the 8B ignored tool results.
    Extracts the tool results from the message history and explicitly asks
    the 8B to summarize them for the user.
    """
    # Collect all tool results from the message history
    tool_results = []
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("content"):
            tool_name = msg.get("name", "unknown")
            tool_results.append(f"Tool '{tool_name}' returned:\n{msg['content']}")

    if not tool_results:
        return None  # No tool results to synthesize

    # Build a focused synthesis prompt
    results_text = "\n\n".join(tool_results)
    # Truncate if too long (prevents token overload)
    if len(results_text) > 4000:
        results_text = results_text[:4000] + "\n... (truncated)"

    synthesis_prompt = f"""The user asked: "{user_input_original}"

You executed tool(s) and got these results:

{results_text}

CRITICAL INSTRUCTIONS:
1. SUMMARIZE the above tool results for the user in natural language.
2. Address the user as "Sir".
3. Do NOT mention tools, functions, or available tools.
4. Do NOT say you cannot perform the request — you HAVE the results.
5. Just tell the user what the results say, in a clear and concise way.
6. If the results contain news articles, tell the user the key headlines and details.
7. If the results contain weather data, tell the user the weather.
8. If the results contain file paths, tell the user where the files are.

Respond now:"""

    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.TOOL_ROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": "You are JARVIS. Address the user as Sir. Summarize tool results clearly."},
                    {"role": "user", "content": synthesis_prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 300},
                "keep_alive": config.get_keep_alive(config.TOOL_ROUTER_MODEL)
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json().get("message", {}).get("content", "").strip()
        if result:
            print(f"[RescueSynthesis]: Successfully re-synthesized response ({len(result)} chars)")
            return result
    except Exception as e:
        print(f"[RescueSynthesis]: Failed: {e}")

    return None


def _run_qwen3_loop(messages, relevant_tools, tools_used, start_time, max_iterations, user_input, speak_fn=None):
    """Execute the Qwen 3 tool-use loop. Separated for thinking interjection cleanup."""

    for iteration in range(max_iterations):
        try:
            response = _call_ollama_with_tools(messages, relevant_tools)
        except Exception as e:
            return {
                "response": f"I encountered an error while thinking, Sir: {e}",
                "tools_used": tools_used,
                "iterations": iteration + 1,
                "success": False,
            }

        # If no tool calls, we're done — synthesize final response
        if not response.get("tool_calls"):
            final_text = response.get("content", "").strip()
            if not final_text:
                final_text = "I'm here, Sir. How can I help?"

            # Phase 6+: Rescue synthesis — if tools were used but the 8B
            # ignored the results (listed tools, said "no tools can", etc.),
            # force a re-synthesis that explicitly uses the tool results.
            if tools_used and _is_ignoring_tool_results(final_text, tools_used):
                print(f"[RescueSynthesis]: 8B ignored tool results — re-synthesizing...")
                print(f"[RescueSynthesis]: Original response (first 100 chars): {final_text[:100]}...")
                rescued = _rescue_synthesis(user_input, tools_used, messages, user_input)
                if rescued:
                    final_text = rescued
                else:
                    # Fallback — tell the user we got results but couldn't synthesize
                    final_text = f"I found the information you requested, Sir, but I'm having trouble summarizing it. Please check the console for the raw results."

            return {
                "response": final_text,
                "tools_used": tools_used,
                "iterations": iteration + 1,
                "success": True,
                "elapsed": time.time() - start_time,
            }

        # Execute each tool call
        for call in response["tool_calls"]:
            try:
                func_obj = call.get("function", {})
                tool_name = func_obj.get("name", "")
                args_str = func_obj.get("arguments", "{}")

                # Parse arguments
                try:
                    arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    arguments = {}

                # Check if tool exists
                if not get_tool(tool_name):
                    result = f"Tool '{tool_name}' not found."
                    record_error("E_TOOL_NOT_FOUND", tool_name)
                else:
                    # Check cooldown
                    if is_on_cooldown(tool_name):
                        remaining = get_confidence_penalty(tool_name)
                        result = f"Tool '{tool_name}' is temporarily on cooldown. Please try again in a moment."
                        print(f"[Cooldown]: '{tool_name}' blocked (on cooldown)")
                        record_error("E_TOOL_COOLDOWN", tool_name)
                    else:
                        # Validate args with contracts
                        is_valid, errors = validate_input(tool_name, arguments)
                        if not is_valid:
                            result = f"Invalid arguments: {'; '.join(errors)}"
                            record_error("E_CONTRACT_VIOLATION", str(errors))
                            log_misfire(tool_name)
                        else:
                            # Execute
                            print(f"[ToolRouter]: Calling {tool_name}({arguments})")
                            try:
                                result = execute_tool_call(tool_name, arguments, speak_fn=speak_fn)
                                # Sanitize output
                                result = sanitize_output(tool_name, result)
                                print(f"[ToolRouter]: Result: {str(result)[:200]}")

                                # Record success
                                record_tool_call(tool_name, success=True)
                                log_success(tool_name)

                                # Extract entities for future pronoun resolution
                                try:
                                    from smartRouter import extract_entities_from_result
                                    extract_entities_from_result(tool_name, arguments, result)
                                except Exception:
                                    pass

                            except Exception as te:
                                result = f"Tool error: {te}"
                                record_tool_call(tool_name, success=False)
                                record_error("E_TOOL_EXECUTION", str(te))
                                log_misfire(tool_name)

                tools_used.append(tool_name)

                # Add to messages for next iteration
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [call]
                })
                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": str(result)
                })

            except Exception as e:
                print(f"[ToolRouter]: Error executing tool call: {e}")
                traceback.print_exc()
                messages.append({
                    "role": "tool",
                    "name": tool_name if 'tool_name' in dir() else "unknown",
                    "content": f"Error: {e}"
                })

        # After first iteration, expand tool pool (model may need tools it didn't expect)
        if iteration == 0 and getattr(config, 'TOOL_USE_EMBEDDING_FILTER', True):
            # Show all tools in subsequent iterations
            relevant_tools = get_all_tools()

    # Hit iteration limit — get a final response from the model
    messages.append({
        "role": "user",
        "content": "I've hit my tool-use limit. Please give me your best response with the information you have so far."
    })

    try:
        final_response = _call_ollama_plain(messages)
        final_text = final_response.get("content", "").strip()
    except Exception:
        final_text = "I've hit my tool-use limit, Sir. Here's what I have so far."

    return {
        "response": final_text,
        "tools_used": tools_used,
        "iterations": max_iterations,
        "success": False,
        "elapsed": time.time() - start_time,
    }


# ─────────────────────────────────────────────────────────────
# OLLAMA API CALLS
# ─────────────────────────────────────────────────────────────

def _call_ollama_with_tools(messages, tools):
    """Call Ollama chat API with tool definitions."""
    options = {
        "temperature": 0.3,  # Lower temp for more deterministic tool selection
    }

    # Add think mode if enabled
    if getattr(config, 'TOOL_USE_THINK_MODE', False):
        options["think"] = True

    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.TOOL_ROUTER_MODEL,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "options": options,
                "keep_alive": config.get_keep_alive(config.TOOL_ROUTER_MODEL)
            },
            timeout=config.OLLAMA_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        msg = data.get("message", {})
        return {
            "content": msg.get("content", "") or "",
            "tool_calls": msg.get("tool_calls", []) or [],
        }
    except requests.exceptions.ConnectionError:
        return {
            "content": "I cannot connect to Ollama, Sir. Please make sure it's running.",
            "tool_calls": [],
        }
    except Exception as e:
        print(f"[ToolRouter]: Ollama API error: {e}")
        return {
            "content": f"Error connecting to AI: {e}",
            "tool_calls": [],
        }


def _call_ollama_plain(messages):
    """Call Ollama chat API without tools (for final synthesis)."""
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.TOOL_ROUTER_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.5},
                "keep_alive": config.get_keep_alive(config.TOOL_ROUTER_MODEL)
            },
            timeout=config.OLLAMA_TIMEOUT
        )
        response.raise_for_status()
        return response.json().get("message", {})
    except Exception as e:
        return {"content": f"Error: {e}"}


# ─────────────────────────────────────────────────────────────
# EMBEDDING-BASED PRE-FILTER
# ─────────────────────────────────────────────────────────────

def _select_relevant_tools(user_input, top_k=None):
    """
    Pre-filter tools using embeddings, or return all if disabled.
    Always includes chat_only as a fallback option.
    """
    if not getattr(config, 'TOOL_USE_EMBEDDING_FILTER', True):
        return get_all_tools()

    if top_k is None:
        top_k = getattr(config, 'TOOL_PRE_FILTER_K', 12)

    try:
        from toolEmbeddings import select_relevant_tools
        selected = select_relevant_tools(user_input, top_k=top_k)

        # Always include chat_only
        names = [t["function"]["name"] for t in selected]
        if "chat_only" not in names:
            chat_tool = get_tool("chat_only")
            if chat_tool:
                from toolRegistry import _tool_to_ollama_format
                selected.append(_tool_to_ollama_format(chat_tool))

        return selected
    except Exception as e:
        print(f"[ToolRouter]: Embedding filter failed, using all tools: {e}")
        return get_all_tools()


# ─────────────────────────────────────────────────────────────
# MISFIRE TRACKING (for cooldown logic)
# ─────────────────────────────────────────────────────────────

def log_misfire(tool_name):
    """Log that a tool misfired (was called incorrectly)."""
    with _tool_misfire_lock:
        _tool_misfire_log.setdefault(tool_name, []).append(time.time())


def get_tool_confidence_penalty(tool_name):
    """Returns 0.0-1.0 — how much to penalize this tool's selection."""
    with _tool_misfire_lock:
        recent = [t for t in _tool_misfire_log.get(tool_name, [])
                  if time.time() - t < 30]
        return min(0.5, len(recent) * 0.15)


# ─────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing tool router...")
    print(f"Router model: {config.TOOL_ROUTER_MODEL}")
    print(f"Pre-filter enabled: {getattr(config, 'TOOL_USE_EMBEDDING_FILTER', True)}")
    print(f"Max iterations: {config.TOOL_MAX_ITERATIONS}")

    # Test 1: Simple chat
    print("\n--- Test 1: 'hello' ---")
    result = route_with_tools("hello")
    print(f"Response: {result['response']}")
    print(f"Tools used: {result['tools_used']}")

    # Test 2: Tool call
    print("\n--- Test 2: 'set volume to 50' ---")
    result = route_with_tools("set volume to 50")
    print(f"Response: {result['response']}")
    print(f"Tools used: {result['tools_used']}")
