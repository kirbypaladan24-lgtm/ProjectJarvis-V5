"""
JARVIS Tool Groups (Phase 3)
================================================================
Categorizes all 83 tools into 8 groups to reduce the 1.5B model's
decision space. Instead of picking from 83 flat tools, the 1.5B sees
tools organized by category — providing semantic context that helps
it pick the right tool with fewer hallucinations.

Groups:
    1. CHAT           — conversation, memory, meta tools (7 tools)
    2. MEDIA_CONTROL  — volume, brightness, power, spotify (11 tools)
    3. APPS_WINDOWS   — open/close apps, window management (5 tools)
    4. TASKS_NOTES    — tasks, notes, facts, timers (16 tools)
    5. FILES          — file search, read, compress, diff (9 tools)
    6. INTERNET       — web lookups, calculations (10 tools)
    7. SYSTEM_VISION  — monitor, specs, camera, screen (13 tools)
    8. DEV_TOOLS      — code, git, clipboard, privacy, utilities (12 tools)

How it's used:
    - toolRouter.py's 1.5B dispatch shows tools GROUPED BY CATEGORY
    - The 1.5B outputs GROUP + TOOL + ARGS + CONF in one call
    - Group labels provide semantic context (reduces hallucination)
    - Still a SINGLE model call (no latency doubling)
    - Optionally paired with embedding pre-filter (top 12 tools shown)
"""
import os
import sys

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# ═══════════════════════════════════════════════════════════════════════
# GROUP DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════

TOOL_GROUPS = {
    "CHAT": {
        "description": "Conversation, memory management, and meta-tool operations. Use for greetings, knowledge questions, exporting conversation, clearing memory, or managing JARVIS's own tools.",
        "tools": [
            "chat_only",
            "export_conversation",
            "clear_memory",
            "search_conversation_history",
            "add_tool",
            "approve_tool",
            "list_pending_tools",
        ],
    },
    "MEDIA_CONTROL": {
        "description": "Audio volume, screen brightness, system power, and Spotify music playback control.",
        "tools": [
            "set_volume",
            "get_volume",
            "set_brightness",
            "get_brightness",
            "shutdown_system",
            "sleep_system",
            "spotify_play",
            "spotify_pause",
            "spotify_next",
            "spotify_previous",
            "spotify_now_playing",
        ],
    },
    "APPS_WINDOWS": {
        "description": "Launch/uninstall applications and manage windows (minimize, close, focus).",
        "tools": [
            "open_app",
            "uninstall_app",
            "focus_window",
            "minimize_window",
            "close_window",
        ],
    },
    "TASKS_NOTES": {
        "description": "Task management (to-do list), notes, knowledge base facts, habits, expense logging, and timers/reminders.",
        "tools": [
            "create_task",
            "list_tasks",
            "complete_task",
            "delete_task",
            "save_note",
            "search_notes",
            "list_notes",
            "write_to_notepad",
            "save_fact",
            "recall_facts",
            "set_timer",
            "set_recurring_reminder",
            "list_timers",
            "pomodoro_start",
            "habit_check",
            "expense_log",
        ],
    },
    "FILES": {
        "description": "File search, reading, opening, semantic content search, compression, and file utilities (diff, JSON format).",
        "tools": [
            "search_files",
            "read_file",
            "open_file",
            "semantic_file_search",
            "find_large_files",
            "compress_files",
            "extract_archive",
            "diff_files",
            "json_format",
        ],
    },
    "INTERNET": {
        "description": "Web search, weather, news, Wikipedia, exchange rates, crypto/stock prices, timezone queries, unit conversion, and math calculations.",
        "tools": [
            "web_search",
            "get_weather",
            "get_news",
            "wikipedia_summary",
            "get_exchange_rate",
            "crypto_price",
            "stock_price",
            "get_time_in_timezone",
            "unit_convert",
            "quick_calc",
        ],
    },
    "SYSTEM_VISION": {
        "description": "System monitoring (CPU/RAM/disk specs, running processes, WiFi, internet speed, diagnostics) and vision (camera, screen capture, OCR, screenshot).",
        "tools": [
            "get_system_stats",
            "get_laptop_specs",
            "list_running_apps",
            "kill_process",
            "get_wifi_details",
            "test_internet_speed",
            "get_process_tree",
            "run_diagnostics",
            "camera_see",
            "describe_screen",
            "read_screen_text",
            "take_screenshot",
            "recall_vision",
        ],
    },
    "DEV_TOOLS": {
        "description": "Code execution, Git commands, clipboard, privacy mode, notifications, Downloads organizer, YouTube download, image tools, and QR generation.",
        "tools": [
            "run_code_file",
            "git_command",
            "organize_downloads",
            "read_clipboard",
            "set_clipboard",
            "enable_privacy_mode",
            "disable_privacy_mode",
            "send_notification",
            "youtube_download",
            "image_resize",
            "image_convert",
            "qr_generate",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════
# REVERSE LOOKUP: tool_name → group_name
# ═══════════════════════════════════════════════════════════════════════

_TOOL_TO_GROUP = {}
for _group, _info in TOOL_GROUPS.items():
    for _tool in _info["tools"]:
        _TOOL_TO_GROUP[_tool] = _group


def get_group_for_tool(tool_name):
    """Return the group name for a given tool, or None if not categorized."""
    return _TOOL_TO_GROUP.get(tool_name)


def get_tools_in_group(group_name):
    """Return the list of tool names in a group, or empty list if group doesn't exist."""
    info = TOOL_GROUPS.get(group_name)
    return info["tools"] if info else []


def get_group_description(group_name):
    """Return the description of a group, or empty string if not found."""
    info = TOOL_GROUPS.get(group_name)
    return info["description"] if info else ""


def get_all_group_names():
    """Return list of all group names."""
    return list(TOOL_GROUPS.keys())


def is_valid_group(group_name):
    """Check if a group name is valid."""
    return group_name in TOOL_GROUPS


# ═══════════════════════════════════════════════════════════════════════
# GROUP-STRUCTURED TOOL LIST GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def generate_grouped_tool_list(tool_names=None):
    """
    Generate a compact tool list organized by group for the 1.5B model.

    Args:
        tool_names: If provided, only include these tools (e.g., top 12 from
                    embedding pre-filter). If None, include ALL tools.

    Returns:
        A string listing all tools grouped by category, with group descriptions.
    """
    from toolRegistry import get_tool

    lines = ["Available tools organized by category (pick ONE — extract the argument from the user's request):\n"]

    for group_name, group_info in TOOL_GROUPS.items():
        group_tools = group_info["tools"]

        # Filter to only requested tools if a subset was given
        if tool_names is not None:
            group_tools = [t for t in group_tools if t in tool_names]

        # Skip groups with no tools in the filtered set
        if not group_tools:
            continue

        lines.append(f"\n## {group_name}")
        lines.append(f"  {group_info['description']}")

        for tool_name in group_tools:
            tool = get_tool(tool_name)
            if not tool:
                continue

            # Internal tool format: name, description, parameters are top-level keys
            params = tool.get("parameters", {})
            props = params.get("properties", {})
            required = params.get("required", [])

            # Build compact signature: tool_name(param1, param2?)
            param_strs = []
            for pname, pinfo in props.items():
                optional = "" if pname in required else "?"
                param_strs.append(f"{pname}{optional}")

            signature = f"{tool_name}({', '.join(param_strs)})" if param_strs else f"{tool_name}()"

            # Get first sentence of description (brief one-liner)
            desc = tool.get("description", "").split("\n")[0].strip()
            if len(desc) > 80:
                desc = desc[:77] + "..."

            lines.append(f"  - {signature:<45} — {desc}")

    return "\n".join(lines)


def generate_group_summary():
    """
    Generate a compact summary of just the 8 groups (no individual tools).
    Used when we want the 1.5B to first pick a group, then we show tools.
    """
    lines = ["Tool categories (pick the most relevant category):\n"]
    for group_name, group_info in TOOL_GROUPS.items():
        tool_count = len(group_info["tools"])
        lines.append(f"  {group_name} ({tool_count} tools): {group_info['description'][:100]}...")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# VALIDATION: Ensure all tools are categorized
# ═══════════════════════════════════════════════════════════════════════

def validate_all_tools_categorized():
    """
    Check that every tool in the registry belongs to a group.
    Returns (all_categorized, list_of_uncategorized_tools).
    """
    try:
        from toolRegistry import list_tool_names
        all_tools = set(list_tool_names())
        categorized = set(_TOOL_TO_GROUP.keys())
        uncategorized = all_tools - categorized
        return len(uncategorized) == 0, sorted(uncategorized)
    except Exception as e:
        return False, [f"Error: {e}"]


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Tool Groups (Phase 3)...\n")

    # Test 1: All tools categorized?
    all_cat, uncategorized = validate_all_tools_categorized()
    print(f"All tools categorized: {all_cat}")
    if not all_cat:
        print(f"  Uncategorized tools: {uncategorized}")

    # Test 2: Group sizes
    print(f"\nGroup sizes:")
    total = 0
    for group, info in TOOL_GROUPS.items():
        count = len(info["tools"])
        total += count
        print(f"  {group:20s}: {count:2d} tools")
    print(f"  {'TOTAL':20s}: {total:2d} tools")

    # Test 3: Reverse lookup
    print(f"\nReverse lookup examples:")
    for tool in ["set_volume", "spotify_play", "chat_only", "web_search", "take_screenshot"]:
        group = get_group_for_tool(tool)
        print(f"  {tool:25s} → {group}")

    # Test 4: Grouped tool list (first 500 chars)
    print(f"\nGrouped tool list (preview):\n")
    grouped = generate_grouped_tool_list()
    print(grouped[:800] + "...\n" if len(grouped) > 800 else grouped)

    # Test 5: Filtered grouped list (simulate embedding pre-filter)
    print(f"\nFiltered grouped list (top 5 tools):\n")
    filtered = generate_grouped_tool_list(
        tool_names={"set_volume", "get_volume", "spotify_play", "spotify_pause", "chat_only"}
    )
    print(filtered)
