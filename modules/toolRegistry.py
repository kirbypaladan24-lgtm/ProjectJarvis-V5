"""
JARVIS Tool Registry
================================================================
Central catalog of all tools JARVIS can call via the LLM tool-use protocol.

Each tool has:
    - name:           short, model-friendly identifier
    - description:    WHEN to use, examples, and when NOT to use
    - parameters:     JSON schema for arguments
    - function:       Python callable that executes the tool
    - needs_approval: True for destructive actions
    - specialist:     optional model name for delegated execution

This module is imported by toolRouter.py and tts.py.
It does NOT import tts.py (avoids circular dependency).
"""
import os
import sys

# Add parent directory to path so we can import systemControl, spotifyControl, etc.
_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

# Also add modules directory
_MODULES_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)


# ─────────────────────────────────────────────────────────────
# REGISTRY DATA
# ─────────────────────────────────────────────────────────────

_TOOLS = []


def register_tool(name, description, parameters, function,
                  needs_approval=False, specialist=None,
                  examples=None, dont_use_for=None):
    """Register a tool in the catalog."""
    full_desc = description
    if examples:
        full_desc += "\n\nExamples: " + "; ".join(examples)
    if dont_use_for:
        full_desc += "\n\nDo NOT use for: " + "; ".join(dont_use_for)

    _TOOLS.append({
        "name": name,
        "description": full_desc,
        "parameters": parameters,
        "function": function,
        "needs_approval": needs_approval,
        "specialist": specialist,
    })


def get_all_tools():
    """Return all registered tools in Ollama tool format."""
    return [_tool_to_ollama_format(t) for t in _TOOLS]


def get_tool(name):
    """Get a single tool's full definition by name."""
    for t in _TOOLS:
        if t["name"] == name:
            return t
    return None


def get_tool_function(name):
    """Get just the callable for a tool."""
    t = get_tool(name)
    return t["function"] if t else None


def list_tool_names():
    """Return list of all registered tool names."""
    return [t["name"] for t in _TOOLS]


def _tool_to_ollama_format(tool):
    """Convert internal tool dict to Ollama tools format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        }
    }


# ─────────────────────────────────────────────────────────────
# TOOL DEFINITIONS
# ─────────────────────────────────────────────────────────────

# === META / CONVERSATION ===

def _chat_only(**kwargs):
    """No-op tool. Signals that no other tool is needed."""
    return "No tool needed. Respond directly to the user."

register_tool(
    name="chat_only",
    description=(
        "DEFAULT tool. Use when no other tool is needed - for greetings, "
        "general conversation, knowledge questions, opinions, explanations, "
        "follow-up clarifications, or anything where you can answer from your "
        "own knowledge. When in doubt, use this. "
        "IMPORTANT: Selecting this tool does NOT mean 'skip answering'. You MUST "
        "still provide a complete answer to the user's question in your response."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    },
    function=_chat_only,
    examples=["hello", "what do you think about", "explain quantum computing",
              "thanks", "what can you do", "who are you"],
    dont_use_for=["actions on the system (use specific tool)",
                  "looking up current info (use web_search)"],
)


def _export_conversation(**kwargs):
    try:
        from conversationExport import export_conversation
        return export_conversation([])
    except Exception as e:
        return f"Error exporting conversation: {e}"

register_tool(
    name="export_conversation",
    description="Export the current conversation to a Markdown file on the Desktop.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_export_conversation,
    examples=["export conversation", "save our conversation"],
)


def _clear_memory(**kwargs):
    try:
        from tts import conversation_history, save_memory
        conversation_history.clear()
        save_memory(conversation_history)
        return "Memory cleared."
    except Exception as e:
        return f"Error clearing memory: {e}"

register_tool(
    name="clear_memory",
    description="Clear the conversation history. Useful when starting a fresh topic.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_clear_memory,
    needs_approval=True,
    examples=["clear memory", "wipe conversation", "start fresh"],
)


# === SYSTEM CONTROL ===

def _set_volume(percent):
    from systemControl import set_volume
    return set_volume(int(percent))

register_tool(
    name="set_volume",
    description="Set the master system volume to a specific percentage (0-100).",
    parameters={
        "type": "object",
        "properties": {
            "percent": {"type": "integer", "description": "Volume level 0-100"}
        },
        "required": ["percent"]
    },
    function=_set_volume,
    examples=["set volume to 50", "make it louder", "mute", "volume up"],
    dont_use_for=["Spotify volume specifically", "media player volume"],
)


def _get_volume(**kwargs):
    from systemControl import get_volume
    return get_volume()

register_tool(
    name="get_volume",
    description="Read the current master system volume level.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_get_volume,
    examples=["what's the volume", "current volume level"],
)


def _set_brightness(percent):
    from systemControl import set_brightness
    return set_brightness(int(percent))

register_tool(
    name="set_brightness",
    description="Set the screen brightness to a specific percentage (0-100).",
    parameters={
        "type": "object",
        "properties": {
            "percent": {"type": "integer", "description": "Brightness level 0-100"}
        },
        "required": ["percent"]
    },
    function=_set_brightness,
    examples=["set brightness to 50", "dim the screen", "brightness up"],
)


def _get_brightness(**kwargs):
    from systemControl import get_brightness
    return get_brightness()

register_tool(
    name="get_brightness",
    description="Read the current screen brightness level.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_get_brightness,
)


def _open_app(app_name):
    from systemControl import open_app
    return open_app(app_name)

register_tool(
    name="open_app",
    description=(
        "Launch an application or open a web app. Supports multiple apps in one call "
        "(e.g., 'open chrome and vscode'). Web apps (youtube, gmail, github, etc.) "
        "open in the default browser."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "Name of app or website to open"}
        },
        "required": ["app_name"]
    },
    function=_open_app,
    examples=["open chrome", "launch spotify", "open youtube", "open vscode"],
)


def _uninstall_app(app_name):
    from systemControl import uninstall_app
    return uninstall_app(app_name)

register_tool(
    name="uninstall_app",
    description="Uninstall an application using winget. Requires user approval.",
    parameters={
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "Name of app to uninstall"}
        },
        "required": ["app_name"]
    },
    function=_uninstall_app,
    needs_approval=True,
    examples=["uninstall notepad", "remove discord"],
)


def _shutdown_system(**kwargs):
    from systemControl import shutdown_system
    return shutdown_system()

register_tool(
    name="shutdown_system",
    description="Shut down the computer. Requires user approval.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_shutdown_system,
    needs_approval=True,
    examples=["shutdown", "power off", "turn off computer"],
)


def _sleep_system(**kwargs):
    from systemControl import sleep_system
    return sleep_system()

register_tool(
    name="sleep_system",
    description="Put the computer to sleep. JARVIS keeps listening for wake words.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_sleep_system,
    examples=["go to sleep", "suspend computer", "sleep mode"],
)


# === SPOTIFY / MUSIC ===

def _spotify_play(query):
    from spotifyControl import handle_spotify_command
    return handle_spotify_command(f"play {query}")

register_tool(
    name="spotify_play",
    description="Play a song, artist, or playlist on Spotify. Requires Spotify to be running.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Song name, artist, or playlist"}
        },
        "required": ["query"]
    },
    function=_spotify_play,
    examples=["play Blinding Lights", "play some Drake", "play relaxing jazz"],
)


def _spotify_pause(**kwargs):
    from spotifyControl import handle_spotify_command
    return handle_spotify_command("pause")

register_tool(
    name="spotify_pause",
    description="Pause the currently playing Spotify track.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_spotify_pause,
    examples=["pause", "stop the music", "pause spotify"],
)


def _spotify_next(**kwargs):
    from spotifyControl import handle_spotify_command
    return handle_spotify_command("next")

register_tool(
    name="spotify_next",
    description="Skip to the next Spotify track.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_spotify_next,
    examples=["next song", "skip this", "next"],
)


def _spotify_previous(**kwargs):
    from spotifyControl import handle_spotify_command
    return handle_spotify_command("previous")

register_tool(
    name="spotify_previous",
    description="Go back to the previous Spotify track.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_spotify_previous,
    examples=["previous song", "go back", "last song"],
)


def _spotify_now_playing(**kwargs):
    from spotifyControl import handle_spotify_command
    return handle_spotify_command("what's playing")

register_tool(
    name="spotify_now_playing",
    description="Get info about the currently playing Spotify track.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_spotify_now_playing,
    examples=["what song is this", "what's playing", "now playing"],
)


# === TASKS ===

def _create_task(title, due_date=None, priority="normal"):
    from taskManager import create_task
    return create_task(title, due_date, priority)

register_tool(
    name="create_task",
    description=(
        "Add a task to the to-do list. Supports natural language due dates "
        "like 'tomorrow', 'friday', 'next week', '2026-12-25'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task title"},
            "due_date": {"type": "string", "description": "Optional due date (natural language or YYYY-MM-DD)"},
            "priority": {"type": "string", "description": "low, normal, or high", "enum": ["low", "normal", "high"]}
        },
        "required": ["title"]
    },
    function=_create_task,
    examples=["create task to call mom tomorrow",
              "add task submit report by Friday",
              "remind me to call dentist"],
)


def _list_tasks(filter_by="pending"):
    from taskManager import list_tasks
    return list_tasks(filter_by)

register_tool(
    name="list_tasks",
    description="List tasks. Filter options: pending, completed, today, all.",
    parameters={
        "type": "object",
        "properties": {
            "filter_by": {"type": "string", "description": "pending|completed|today|all",
                          "enum": ["pending", "completed", "today", "all"]}
        },
        "required": []
    },
    function=_list_tasks,
    examples=["show my tasks", "list tasks", "what do I need to do", "tasks today"],
)


def _complete_task(identifier):
    from taskManager import complete_task, complete_task_by_title
    try:
        if isinstance(identifier, int) or identifier.isdigit():
            return complete_task(int(identifier))
        else:
            return complete_task_by_title(identifier)
    except Exception as e:
        return f"Error completing task: {e}"

register_tool(
    name="complete_task",
    description="Mark a task as done by its ID number or title.",
    parameters={
        "type": "object",
        "properties": {
            "identifier": {"type": "string", "description": "Task ID (number) or title"}
        },
        "required": ["identifier"]
    },
    function=_complete_task,
    examples=["complete task 1", "mark task 3 done", "finish task 2"],
)


def _delete_task(task_id):
    from taskManager import tasks, save_tasks
    try:
        tid = int(task_id)
        for t in tasks:
            if t["id"] == tid:
                tasks.remove(t)
                save_tasks(tasks)
                return f"Task {tid} deleted."
        return f"Task {tid} not found."
    except Exception as e:
        return f"Error deleting task: {e}"

register_tool(
    name="delete_task",
    description="Delete a task by ID. Requires user approval.",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "Task ID to delete"}
        },
        "required": ["task_id"]
    },
    function=_delete_task,
    needs_approval=True,
    examples=["delete task 2", "remove task 5"],
)


# === NOTES ===

def _save_note(title, content=None, tags=None):
    from noteSystem import save_note
    if content is None:
        content = title
    return save_note(title, content, tags or [])

register_tool(
    name="save_note",
    description="Save a text note. Use when user says 'note that', 'remember', or 'jot down'.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Note title (short summary)"},
            "content": {"type": "string", "description": "Full note content (defaults to title)"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"}
        },
        "required": ["title"]
    },
    function=_save_note,
    examples=["note that I need groceries", "remember to call mom", "jot down meeting at 3pm"],
)


def _search_notes(query):
    from noteSystem import search_notes
    return search_notes(query)

register_tool(
    name="search_notes",
    description="Search saved notes by keyword.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword to search for"}
        },
        "required": ["query"]
    },
    function=_search_notes,
    examples=["find my note about Python", "show notes about meetings"],
)


def _list_notes(**kwargs):
    from noteSystem import list_all_notes
    return list_all_notes()

register_tool(
    name="list_notes",
    description="List all saved notes.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_list_notes,
    examples=["show my notes", "list notes", "all notes"],
)


def _write_to_notepad(title, content):
    from noteSystem import write_to_notepad
    return write_to_notepad(title, content)

register_tool(
    name="write_to_notepad",
    description="Open content in Windows Notepad for editing.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Filename (without extension)"},
            "content": {"type": "string", "description": "Text to put in Notepad"}
        },
        "required": ["title", "content"]
    },
    function=_write_to_notepad,
    examples=["write hello world in notepad", "open notepad with my code"],
)


def _take_screenshot(filename=None):
    from noteSystem import take_screenshot
    return take_screenshot(filename)

register_tool(
    name="take_screenshot",
    description="Capture the screen and save it as a PNG.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Optional filename (without extension)"}
        },
        "required": []
    },
    function=_take_screenshot,
    examples=["take a screenshot", "screenshot", "capture my screen",
              "take screenshot named budget"],
)


# === FILES ===

def _search_files(query, file_type=None):
    from fileSearch import search_files
    return search_files(query, file_type=file_type)

register_tool(
    name="search_files",
    description="Search for files by name across user folders (Desktop, Documents, Downloads, etc.).",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Filename or part of name to search for"},
            "file_type": {"type": "string", "description": "Optional file extension filter (e.g., 'pdf', 'docx')"}
        },
        "required": ["query"]
    },
    function=_search_files,
    examples=["find my resume", "search for invoice PDF", "locate my Unity project"],
)


def _read_file(path):
    from fileSearch import read_file_content
    return read_file_content(path)

register_tool(
    name="read_file",
    description="Read the contents of a file. Supports .txt, .md, .py, .js, .json, .csv, .pdf, .docx, .xlsx.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full file path or filename to read"}
        },
        "required": ["path"]
    },
    function=_read_file,
    examples=["read tts.py", "what's in that file", "explain requirements.txt"],
)


def _open_file(path):
    from fileSearch import open_file_with_default_app
    return open_file_with_default_app(path)

register_tool(
    name="open_file",
    description="Open a file with its default application.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to open"}
        },
        "required": ["path"]
    },
    function=_open_file,
    examples=["open file 1", "open my budget.xlsx"],
)


def _semantic_file_search(query):
    try:
        from fileContentIndex import content_search
        results = content_search(query, top_k=5)
        if not results:
            return "No semantically matching files found."
        out = ["Found these files matching your query:"]
        for r in results:
            out.append(f"\n- {r['path']} (score: {r.get('score', 0):.2f})")
            snippet = r.get('snippet', '')[:200]
            out.append(f"  Snippet: {snippet}...")
        return "\n".join(out)
    except Exception as e:
        return f"Semantic file search error: {e}"

register_tool(
    name="semantic_file_search",
    description=(
        "Search INSIDE file contents using semantic AI. Use when the user asks "
        "'what file talks about X' or 'find documents mentioning Y'. Much smarter "
        "than filename search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Concept or topic to search for"}
        },
        "required": ["query"]
    },
    function=_semantic_file_search,
    examples=["what file talks about authentication",
              "find documents mentioning machine learning"],
)


# === TIMERS ===

def _set_timer(duration_seconds, label=None):
    from timerSystem import set_timer
    # We can't easily pass speak_callback here; the router will handle speech.
    return set_timer(int(duration_seconds), label or "Timer",
                     speak_callback=None, write_to_disk=True)

register_tool(
    name="set_timer",
    description="Set a countdown timer. Examples: 'remind me in 10 minutes', 'set timer for 2 hours'.",
    parameters={
        "type": "object",
        "properties": {
            "duration_seconds": {"type": "integer", "description": "Duration in seconds"},
            "label": {"type": "string", "description": "Optional label for the timer"}
        },
        "required": ["duration_seconds"]
    },
    function=_set_timer,
    examples=["remind me in 10 minutes", "set timer for 2 hours"],
)


def _set_recurring_reminder(interval_seconds, label):
    from timerSystem import set_recurring_timer
    return set_recurring_timer(int(interval_seconds), label, speak_callback=None)

register_tool(
    name="set_recurring_reminder",
    description="Set a recurring reminder. Examples: 'remind me every hour to stretch'.",
    parameters={
        "type": "object",
        "properties": {
            "interval_seconds": {"type": "integer", "description": "Interval in seconds"},
            "label": {"type": "string", "description": "What to remind about"}
        },
        "required": ["interval_seconds", "label"]
    },
    function=_set_recurring_reminder,
    examples=["remind me every hour to stretch", "every 30 minutes drink water"],
)


def _list_timers(**kwargs):
    from timerSystem import list_timers
    return list_timers()

register_tool(
    name="list_timers",
    description="List all active timers and reminders.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_list_timers,
    examples=["show my timers", "what reminders do I have"],
)


# === INTERNET ===

def _web_search(query):
    from internetSearch import web_search
    return web_search(query)

register_tool(
    name="web_search",
    description="Search the web via DuckDuckGo. Use for current info, tutorials, docs.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"]
    },
    function=_web_search,
    examples=["search for Python tutorials", "google quantum computing", "look up TypeScript"],
)


def _get_weather(location=None):
    from internetSearch import get_weather
    return get_weather(location)

register_tool(
    name="get_weather",
    description="Get weather for a location. Auto-detects if no location given.",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name (optional)"}
        },
        "required": []
    },
    function=_get_weather,
    examples=["what's the weather", "weather in Manila", "how hot is it in Tokyo"],
)


def _get_news(topic=None):
    from internetSearch import get_news
    return get_news(topic)

register_tool(
    name="get_news",
    description="Get latest news headlines. Optional topic filter.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Optional topic (e.g., 'AI', 'sports')"}
        },
        "required": []
    },
    function=_get_news,
    examples=["latest news", "news about AI", "what's happening"],
)


def _wikipedia_summary(topic):
    from internetSearch import wikipedia_summary
    return wikipedia_summary(topic)

register_tool(
    name="wikipedia_summary",
    description="Get a Wikipedia summary of a topic.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic to look up"}
        },
        "required": ["topic"]
    },
    function=_wikipedia_summary,
    examples=["tell me about Elon Musk", "what is blockchain", "wiki Python"],
)


def _get_exchange_rate(**kwargs):
    from internetSearch import get_exchange_rate
    return get_exchange_rate()

register_tool(
    name="get_exchange_rate",
    description="Get current currency exchange rates (USD base).",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_get_exchange_rate,
    examples=["exchange rate", "how much is 1 dollar in pesos"],
)


# === SYSTEM MONITOR ===

def _get_system_stats(**kwargs):
    from systemMonitor import get_system_stats
    return get_system_stats()

register_tool(
    name="get_system_stats",
    description="Get a CPU/RAM/disk usage snapshot.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_get_system_stats,
    examples=["system status", "how's my computer", "CPU usage", "RAM usage"],
)


def _get_laptop_specs(**kwargs):
    from systemMonitor import get_laptop_specs
    return get_laptop_specs()

register_tool(
    name="get_laptop_specs",
    description="Get hardware specifications (CPU, GPU, RAM, disk, brand).",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_get_laptop_specs,
    examples=["what are my specs", "system specs", "laptop specifications"],
)


def _list_running_apps(**kwargs):
    from systemMonitor import list_running_apps
    return list_running_apps()

register_tool(
    name="list_running_apps",
    description="List currently running applications and processes.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_list_running_apps,
    examples=["what's running", "show running apps", "what apps are open"],
)


def _kill_process(name):
    from systemMonitor import kill_process
    return kill_process(name)

register_tool(
    name="kill_process",
    description="Kill a process by name. Requires user approval.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Process name to kill"}
        },
        "required": ["name"]
    },
    function=_kill_process,
    needs_approval=True,
    examples=["close Notepad", "kill Chrome", "force close a program"],
)


def _get_wifi_details(**kwargs):
    from systemMonitor import get_wifi_details
    return get_wifi_details()

register_tool(
    name="get_wifi_details",
    description="Get connected WiFi information (SSID, signal, etc.).",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_get_wifi_details,
    examples=["wifi status", "what wifi am I connected to"],
)


def _test_internet_speed(**kwargs):
    from systemMonitor import test_internet_speed
    return test_internet_speed()

register_tool(
    name="test_internet_speed",
    description="Run an internet speed test (takes about 10 seconds).",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_test_internet_speed,
    examples=["speed test", "check my internet speed"],
)


# === WINDOW CONTROL ===

def _focus_window(app_name):
    from windowControl import focus_window
    return focus_window(app_name)

register_tool(
    name="focus_window",
    description="Bring a window to the foreground by app name.",
    parameters={
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "Application name"}
        },
        "required": ["app_name"]
    },
    function=_focus_window,
    examples=["focus chrome", "switch to spotify"],
)


def _minimize_window(target="active"):
    from windowControl import minimize_active_window, minimize_all_windows
    if target == "all":
        return minimize_all_windows()
    return minimize_active_window()

register_tool(
    name="minimize_window",
    description="Minimize the active window or all windows.",
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "'active' (default) or 'all'",
                       "enum": ["active", "all"]}
        },
        "required": []
    },
    function=_minimize_window,
    examples=["minimize this", "minimize all windows", "show desktop"],
)


def _close_window(target="active"):
    from windowControl import close_active_window
    return close_active_window()

register_tool(
    name="close_window",
    description="Close the active window.",
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Currently only 'active' supported"}
        },
        "required": []
    },
    function=_close_window,
    examples=["close this window", "close active window"],
)


# === VISION ===

def _camera_see(prompt=None, **kwargs):
    import cameraAccess
    # Pass None to let cameraAccess.see() use its default JARVIS personality prompt
    return cameraAccess.see(prompt=prompt)

register_tool(
    name="camera_see",
    description=(
        "Capture from the webcam and describe what's visible. Use for 'what do you see', "
        "'look at this', 'what am I holding'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Optional specific question about the image"}
        },
        "required": []
    },
    function=_camera_see,
    examples=["what do you see", "look around", "describe what you see",
              "what am I holding"],
)


def _describe_screen(**kwargs):
    from screenUnderstanding import describe_screen
    return describe_screen()

register_tool(
    name="describe_screen",
    description="Capture and describe what's currently on the screen.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_describe_screen,
    examples=["what's on my screen", "describe my desktop"],
)


def _read_screen_text(target=None):
    from screenUnderstanding import read_screen_text
    return read_screen_text(target)

register_tool(
    name="read_screen_text",
    description="OCR text from the screen. Use for 'what does this say', 'read the screen'.",
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Optional region to focus on"}
        },
        "required": []
    },
    function=_read_screen_text,
    examples=["what does this say", "read the screen", "read this text"],
)


# === MEMORY / KNOWLEDGE ===

def _save_fact(fact):
    from deepMemory import save_to_knowledge_base
    return save_to_knowledge_base(fact)

register_tool(
    name="save_fact",
    description=(
        "Save a long-term fact to the knowledge base. Use for 'remember that X' "
        "where X is a permanent fact, not a temporary note."
    ),
    parameters={
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "The fact to remember"}
        },
        "required": ["fact"]
    },
    function=_save_fact,
    examples=["remember that my API key is XYZ",
              "save fact that the server IP is 192.168.1.10"],
)


def _recall_facts(query):
    from deepMemory import vector_search
    results = vector_search(query)
    if not results:
        return "No relevant facts found in knowledge base."
    out = ["Found these relevant facts:"]
    for r in results:
        out.append(f"- {r}")
    return "\n".join(out)

register_tool(
    name="recall_facts",
    description="Recall facts from the knowledge base by semantic search.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to recall"}
        },
        "required": ["query"]
    },
    function=_recall_facts,
    examples=["what do you remember about my server",
              "recall facts about Python"],
)


def _search_conversation_history(query):
    from conversationExport import search_history
    return search_history(query)

register_tool(
    name="search_conversation_history",
    description="Search past conversations by keyword. Use for 'what did we talk about regarding X'.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword to search for"}
        },
        "required": ["query"]
    },
    function=_search_conversation_history,
    examples=["what did we talk about regarding Python",
              "search history for meeting notes"],
)


# === CODE & DEVELOPMENT ===

def _run_code_file(path):
    from autonomousExecution import run_code_file
    return run_code_file(path, speak_fn=None)

register_tool(
    name="run_code_file",
    description=(
        "Execute a code file. Supports .py, .js, .ts, .go, .rb, .pl, .sh, .bat, "
        ".ps1, .cpp, .c, .cs. Requires user approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the code file"}
        },
        "required": ["path"]
    },
    function=_run_code_file,
    needs_approval=True,
    examples=["run test.py", "execute script.js", "run main.go"],
)


def _git_command(action, message=None):
    from autonomousExecution import git_voice_control
    cmd = f"git {action}"
    if action == "commit" and message:
        cmd = f"git commit -m {message}"
    return git_voice_control(cmd, work_dir=os.getcwd(),
                             speak_fn=None, input_fn=None)

register_tool(
    name="git_command",
    description="Run a git command. Actions: status, pull, commit, push. Commit messages auto-generated if not provided.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "status|pull|commit|push",
                       "enum": ["status", "pull", "commit", "push"]},
            "message": {"type": "string", "description": "Commit message (only for commit)"}
        },
        "required": ["action"]
    },
    function=_git_command,
    needs_approval=True,
    examples=["git status", "git pull", "git commit", "git push"],
)


def _organize_downloads(**kwargs):
    from autonomousExecution import organize_downloads
    downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
    return organize_downloads(downloads_path, speak_fn=None, input_fn=None)

register_tool(
    name="organize_downloads",
    description="Categorize and organize files in the Downloads folder. Requires user approval.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_organize_downloads,
    needs_approval=True,
    examples=["organize downloads", "organize download folder"],
)


# === CLIPBOARD ===

def _read_clipboard(**kwargs):
    from clipboardControl import get_clipboard
    return get_clipboard()

register_tool(
    name="read_clipboard",
    description="Read the current clipboard contents.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_read_clipboard,
    examples=["what's on my clipboard", "read clipboard"],
)


def _set_clipboard(text):
    from clipboardControl import set_clipboard
    return set_clipboard(text)

register_tool(
    name="set_clipboard",
    description="Write text to the clipboard.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to put on clipboard"}
        },
        "required": ["text"]
    },
    function=_set_clipboard,
    examples=["copy this to clipboard", "put that on clipboard"],
)


# === PRIVACY ===

def _enable_privacy_mode(**kwargs):
    from privacyMode import enable_privacy_mode
    return enable_privacy_mode()

register_tool(
    name="enable_privacy_mode",
    description="Enable privacy mode — stops all memory saving and conversation logging.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_enable_privacy_mode,
    examples=["go private", "enable privacy mode"],
)


def _disable_privacy_mode(**kwargs):
    from privacyMode import disable_privacy_mode
    return disable_privacy_mode()

register_tool(
    name="disable_privacy_mode",
    description="Disable privacy mode — resume normal memory saving.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_disable_privacy_mode,
    examples=["stop private mode", "disable privacy mode"],
)


# === DIAGNOSTICS ===

def _run_diagnostics(**kwargs):
    from bodyAwareness import run_full_diagnostics
    return run_full_diagnostics()

register_tool(
    name="run_diagnostics",
    description="Run a full system diagnostics report (battery, CPU, RAM, disk, network).",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_run_diagnostics,
    examples=["run diagnostics", "system health check", "full diagnostic"],
)


# === NEW TOOLS (Phase 5 Expansion) ===

def _quick_calc(expression):
    """Safe arithmetic calculator with percentage support."""
    import re
    expr = expression.lower().strip()

    # Handle "X% of Y" → "(X/100)*Y"
    pct_of_match = re.match(r'^(\d+\.?\d*)\s*%\s*of\s*(\d+\.?\d*)$', expr)
    if pct_of_match:
        pct = float(pct_of_match.group(1))
        val = float(pct_of_match.group(2))
        result = (pct / 100) * val
        return f"{pct}% of {val} = {result}"

    # Handle "X%" → X/100
    expr = re.sub(r'(\d+\.?\d*)\s*%', r'(\1/100)', expr)

    # Remove words like "what's", "calculate", "what is"
    expr = re.sub(r"(what's|whats|what is|calculate|how much is|how much)\s*", "", expr)

    # Only allow numbers and basic operators
    clean = re.sub(r'[^0-9+\-*/.() ]', '', expr)
    if not clean.strip():
        return "Error: invalid expression"
    try:
        result = eval(clean, {"__builtins__": {}}, {})
        return f"{clean.strip()} = {result}"
    except Exception as e:
        return f"Error calculating '{expression}': {e}"

register_tool(
    name="quick_calc",
    description="Calculate a math expression. Use for 'what's 15% of 245', 'what's 2+2', 'calculate 25 * 4'.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Math expression to evaluate"}
        },
        "required": ["expression"]
    },
    function=_quick_calc,
    examples=["what's 15% of 245", "what's 2+2", "calculate 25 * 4", "what is 100 / 3"],
)


def _find_large_files(min_size_mb=100):
    """Find large files on disk."""
    import os
    results = []
    min_bytes = min_size_mb * 1024 * 1024

    search_roots = [
        os.path.expanduser("~"),
    ]

    for root_dir in search_roots:
        if not os.path.exists(root_dir):
            continue
        for root, dirs, files in os.walk(root_dir):
            # Skip hidden/system directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'AppData')]

            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    size = os.path.getsize(fpath)
                    if size >= min_bytes:
                        size_mb = size / (1024 * 1024)
                        results.append((size_mb, fpath))
                except (OSError, PermissionError):
                    continue

            # Limit to prevent infinite scanning
            if len(results) > 50:
                break

    results.sort(reverse=True)
    if not results:
        return f"No files larger than {min_size_mb} MB found."

    lines = [f"Largest files (>= {min_size_mb} MB):"]
    for size_mb, path in results[:20]:
        lines.append(f"  {size_mb:.1f} MB - {path}")
    return "\n".join(lines)

register_tool(
    name="find_large_files",
    description="Find the largest files on your disk. Use for 'what's eating my disk space', 'find large files'.",
    parameters={
        "type": "object",
        "properties": {
            "min_size_mb": {"type": "integer", "description": "Minimum file size in MB (default 100)"}
        },
        "required": []
    },
    function=_find_large_files,
    examples=["what's eating my disk space", "find large files", "find files bigger than 500 MB"],
)


def _compress_files(paths, output_path):
    """Create a ZIP archive."""
    import zipfile
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                if os.path.isfile(path):
                    zf.write(path, os.path.basename(path))
                elif os.path.isdir(path):
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            fpath = os.path.join(root, file)
                            arcname = os.path.relpath(fpath, path)
                            zf.write(fpath, arcname)
        return f"Created archive: {output_path}"
    except Exception as e:
        return f"Error creating archive: {e}"

register_tool(
    name="compress_files",
    description="Create a ZIP archive of files or folders.",
    parameters={
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file/folder paths to compress"},
            "output_path": {"type": "string", "description": "Path for the output .zip file"}
        },
        "required": ["paths", "output_path"]
    },
    function=_compress_files,
    needs_approval=True,
    examples=["zip these files", "create an archive of my documents"],
)


def _extract_archive(path, output_dir=None):
    """Extract a ZIP archive."""
    import zipfile
    try:
        if output_dir is None:
            output_dir = os.path.dirname(path) or "."

        with zipfile.ZipFile(path, 'r') as zf:
            zf.extractall(output_dir)

        return f"Extracted {path} to {output_dir}"
    except Exception as e:
        return f"Error extracting: {e}"

register_tool(
    name="extract_archive",
    description="Extract a ZIP archive.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the .zip file"},
            "output_dir": {"type": "string", "description": "Output directory (optional, defaults to same dir)"}
        },
        "required": ["path"]
    },
    function=_extract_archive,
    examples=["unzip this file", "extract this archive"],
)


def _json_format(text):
    """Pretty-print JSON text."""
    import json
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

register_tool(
    name="json_format",
    description="Pretty-print (format) JSON text. Use for 'format this JSON', 'pretty print JSON'.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "JSON text to format"}
        },
        "required": ["text"]
    },
    function=_json_format,
    examples=["format this JSON", "pretty print this JSON"],
)


def _diff_files(path1, path2):
    """Show diff between two files."""
    import difflib
    try:
        with open(path1, 'r', errors='ignore') as f:
            lines1 = f.readlines()
        with open(path2, 'r', errors='ignore') as f:
            lines2 = f.readlines()

        diff = list(difflib.unified_diff(lines1, lines2,
                                          fromfile=path1, tofile=path2, lineterm=""))
        if not diff:
            return "Files are identical."
        return "\n".join(diff[:100])  # Limit output
    except Exception as e:
        return f"Error diffing files: {e}"

register_tool(
    name="diff_files",
    description="Show the differences between two files. Use for 'what changed between these files'.",
    parameters={
        "type": "object",
        "properties": {
            "path1": {"type": "string", "description": "First file path"},
            "path2": {"type": "string", "description": "Second file path"}
        },
        "required": ["path1", "path2"]
    },
    function=_diff_files,
    examples=["what changed between these files", "diff file1.txt file2.txt"],
)


def _send_notification(title, message):
    """Send a Windows toast notification."""
    try:
        # Try win10toast
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=5)
            return f"Notification sent: {title}"
        except ImportError:
            pass

        # Fallback: use PowerShell
        import subprocess
        ps_script = f'''
        [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.Visible = $true
        $notify.ShowBalloonTip(5000, "{title}", "{message}", [System.Windows.Forms.ToolTipIcon]::Info)
        Start-Sleep -Seconds 6
        $notify.Dispose()
        '''
        subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=10)
        return f"Notification sent: {title}"
    except Exception as e:
        return f"Notification error: {e}"

register_tool(
    name="send_notification",
    description="Show a Windows desktop notification. Use for 'notify me', 'send a notification'.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Notification title"},
            "message": {"type": "string", "description": "Notification message"}
        },
        "required": ["title", "message"]
    },
    function=_send_notification,
    examples=["notify me that dinner is ready", "send a notification"],
)


def _get_time_in_timezone(timezone_name):
    """Get current time in a specific timezone."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        return f"Current time in {timezone_name}: {now.strftime('%I:%M %p on %A, %B %d')}"
    except Exception as e:
        return f"Error: {e}. Try timezone names like 'America/New_York', 'Asia/Tokyo', 'Europe/London'."

register_tool(
    name="get_time_in_timezone",
    description="Get the current time in a specific timezone. Use for 'what time is it in Tokyo', 'what time is it in London'.",
    parameters={
        "type": "object",
        "properties": {
            "timezone_name": {"type": "string", "description": "Timezone name (e.g., 'Asia/Tokyo', 'America/New_York', 'Europe/London')"}
        },
        "required": ["timezone_name"]
    },
    function=_get_time_in_timezone,
    examples=["what time is it in Tokyo", "what time is it in New York", "what time is it in London"],
)


def _expense_log(amount, category, description=""):
    """Log an expense."""
    import json
    from datetime import datetime

    # Get base dir from config or default to parent of modules/
    try:
        import config
        base_dir = getattr(config, 'BASE_DIR', None)
    except ImportError:
        base_dir = None
    if not base_dir:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    expense_file = os.path.join(base_dir, "expenses.json")
    expenses = []
    if os.path.exists(expense_file):
        with open(expense_file, 'r') as f:
            expenses = json.load(f)

    expenses.append({
        "timestamp": datetime.now().isoformat(),
        "amount": amount,
        "category": category,
        "description": description,
    })

    with open(expense_file, 'w') as f:
        json.dump(expenses, f, indent=2)

    return f"Expense logged: {amount} for {category}"

register_tool(
    name="expense_log",
    description="Log an expense. Use for 'I spent 250 pesos on lunch', 'log expense'.",
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount spent"},
            "category": {"type": "string", "description": "Category (food, transport, etc.)"},
            "description": {"type": "string", "description": "Optional description"}
        },
        "required": ["amount", "category"]
    },
    function=_expense_log,
    examples=["I spent 250 pesos on lunch", "log expense 500 for transport"],
)


# === MORE NEW TOOLS ===

def _crypto_price(symbol="bitcoin"):
    """Get current crypto price from CoinGecko (free, no API key)."""
    try:
        import requests
        # Map common symbols to CoinGecko IDs
        symbol_map = {
            "bitcoin": "bitcoin", "btc": "bitcoin",
            "ethereum": "ethereum", "eth": "ethereum",
            "solana": "solana", "sol": "solana",
            "cardano": "cardano", "ada": "cardano",
            "dogecoin": "dogecoin", "doge": "dogecoin",
            "ripple": "ripple", "xrp": "ripple",
        }
        coin_id = symbol_map.get(symbol.lower(), symbol.lower())

        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if coin_id in data:
                price = data[coin_id]["usd"]
                return f"Current {symbol} price: ${price:,.2f} USD"
            else:
                return f"Could not find crypto '{symbol}'. Try: bitcoin, ethereum, solana, etc."
        return f"API error: {r.status_code}"
    except Exception as e:
        return f"Error fetching crypto price: {e}"

register_tool(
    name="crypto_price",
    description="Get current cryptocurrency price. Use for 'what's Bitcoin at', 'crypto price'.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Crypto symbol (bitcoin, ethereum, solana, etc.)"}
        },
        "required": []
    },
    function=_crypto_price,
    examples=["what's Bitcoin at", "crypto price for ethereum", "how much is solana"],
)


def _qr_generate(text, filename=None):
    """Generate a QR code."""
    try:
        import subprocess
        import sys
        # Try to import qrcode, install if missing
        try:
            import qrcode
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "qrcode"],
                         capture_output=True, check=True, timeout=30)
            import qrcode

        if not filename:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"qr_code_{timestamp}.png"

        if not filename.endswith(".png"):
            filename += ".png"

        # Save to Desktop
        import os
        save_path = os.path.join(os.path.expanduser("~"), "Desktop", filename)

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(save_path)

        return f"QR code generated and saved to Desktop/{filename}"
    except Exception as e:
        return f"QR code error: {e}"

register_tool(
    name="qr_generate",
    description="Generate a QR code for text or a URL. Saves to Desktop as PNG.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text or URL to encode in the QR code"},
            "filename": {"type": "string", "description": "Optional filename (without extension)"}
        },
        "required": ["text"]
    },
    function=_qr_generate,
    examples=["make a QR code for https://google.com", "generate QR code for hello world"],
)


def _unit_convert(value, from_unit, to_unit):
    """Convert between units (length, weight, temperature)."""
    try:
        # Normalize units
        from_u = from_unit.lower().strip()
        to_u = to_unit.lower().strip()

        # Temperature conversions
        temp_units = {"c": "celsius", "celsius": "celsius", "c": "c",
                      "f": "fahrenheit", "fahrenheit": "fahrenheit",
                      "k": "kelvin", "kelvin": "kelvin"}

        if from_u in temp_units and to_u in temp_units:
            val = float(value)
            # Convert to Celsius first
            if from_u in ("f", "fahrenheit"):
                val = (val - 32) * 5/9
            elif from_u in ("k", "kelvin"):
                val = val - 273.15

            # Convert from Celsius to target
            if to_u in ("f", "fahrenheit"):
                result = val * 9/5 + 32
            elif to_u in ("k", "kelvin"):
                result = val + 273.15
            else:
                result = val

            return f"{value}°{from_u.upper()} = {result:.2f}°{to_u.upper()}"

        # Length conversions (to meters)
        length_to_m = {
            "m": 1, "meter": 1, "meters": 1,
            "km": 1000, "kilometer": 1000, "kilometers": 1000,
            "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
            "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
            "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
            "ft": 0.3048, "feet": 0.3048, "foot": 0.3048,
            "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
            "mi": 1609.34, "mile": 1609.34, "miles": 1609.34,
        }

        if from_u in length_to_m and to_u in length_to_m:
            val = float(value)
            meters = val * length_to_m[from_u]
            result = meters / length_to_m[to_u]
            return f"{value} {from_u} = {result:.4f} {to_u}"

        # Weight conversions (to grams)
        weight_to_g = {
            "g": 1, "gram": 1, "grams": 1,
            "kg": 1000, "kilogram": 1000, "kilograms": 1000,
            "mg": 0.001, "milligram": 0.001, "milligrams": 0.001,
            "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592,
            "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
        }

        if from_u in weight_to_g and to_u in weight_to_g:
            val = float(value)
            grams = val * weight_to_g[from_u]
            result = grams / weight_to_g[to_u]
            return f"{value} {from_u} = {result:.4f} {to_u}"

        return f"Could not convert {from_unit} to {to_unit}. Supported: temperature (C/F/K), length (m/km/cm/in/ft/mi), weight (g/kg/lb/oz)"

    except ValueError:
        return f"Invalid value: {value} is not a number"
    except Exception as e:
        return f"Conversion error: {e}"

register_tool(
    name="unit_convert",
    description="Convert between units (temperature, length, weight). Use for 'convert 100 F to C', 'how many feet in 5 meters'.",
    parameters={
        "type": "object",
        "properties": {
            "value": {"type": "number", "description": "Value to convert"},
            "from_unit": {"type": "string", "description": "Source unit (C, F, K, m, km, ft, kg, lb, etc.)"},
            "to_unit": {"type": "string", "description": "Target unit"}
        },
        "required": ["value", "from_unit", "to_unit"]
    },
    function=_unit_convert,
    examples=["convert 100 F to C", "how many feet in 5 meters", "convert 10 kg to pounds"],
)


def _pomodoro_start(work_minutes=25, break_minutes=5):
    """Start a pomodoro timer."""
    try:
        import threading
        import time

        work_sec = work_minutes * 60
        break_sec = break_minutes * 60

        def _pomodoro_loop():
            print(f"[Pomodoro]: Work session started ({work_minutes} min)")
            time.sleep(work_sec)
            print(f"[Pomodoro]: Break time! ({break_minutes} min)")
            # Could integrate with TTS here
            time.sleep(break_sec)
            print("[Pomodoro]: Session complete!")

        t = threading.Thread(target=_pomodoro_loop, daemon=True)
        t.start()

        return f"Pomodoro started: {work_minutes} min work, {break_minutes} min break."
    except Exception as e:
        return f"Pomodoro error: {e}"

register_tool(
    name="pomodoro_start",
    description="Start a pomodoro timer (work/break cycle). Default: 25 min work, 5 min break.",
    parameters={
        "type": "object",
        "properties": {
            "work_minutes": {"type": "integer", "description": "Work duration in minutes (default 25)"},
            "break_minutes": {"type": "integer", "description": "Break duration in minutes (default 5)"}
        },
        "required": []
    },
    function=_pomodoro_start,
    examples=["start pomodoro", "start a 25 minute pomodoro", "pomodoro with 50 min work"],
)


# === MORE TOOLS (Round 2) ===

def _stock_price(symbol):
    """Get stock price from a free API."""
    try:
        import requests
        # Using a free stock API (no key needed for basic queries)
        # Yahoo Finance unofficial endpoint
        symbol = symbol.upper().strip()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            data = r.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice", 0)
                currency = meta.get("currency", "USD")
                change = meta.get("chartPreviousClose", price) - price
                change_pct = (change / price * 100) if price else 0
                direction = "up" if change > 0 else "down"
                return f"{symbol} is currently ${price:,.2f} {currency} ({direction} {abs(change_pct):.2f}%)"
            return f"Could not find stock '{symbol}'."
        return f"API error: {r.status_code}"
    except Exception as e:
        return f"Error fetching stock price: {e}"

register_tool(
    name="stock_price",
    description="Get current stock price. Use for 'how's AAPL doing', 'stock price for Tesla'.",
    parameters={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Stock ticker symbol (e.g., AAPL, TSLA, MSFT)"}
        },
        "required": ["symbol"]
    },
    function=_stock_price,
    examples=["how's AAPL doing", "stock price for TSLA", "what's Microsoft trading at"],
)


def _image_resize(input_path, width=None, height=None, output_path=None):
    """Resize an image."""
    try:
        from PIL import Image
        import os

        img = Image.open(input_path)
        orig_w, orig_h = img.size

        if width and height:
            new_size = (int(width), int(height))
        elif width:
            ratio = width / orig_w
            new_size = (int(width), int(orig_h * ratio))
        elif height:
            ratio = height / orig_h
            new_size = (int(orig_w * ratio), int(height))
        else:
            return "Error: must specify width or height"

        resized = img.resize(new_size, Image.LANCZOS)

        if not output_path:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_resized{ext}"

        resized.save(output_path)
        return f"Image resized from {orig_w}x{orig_h} to {new_size[0]}x{new_size[1]} and saved to {output_path}"
    except Exception as e:
        return f"Image resize error: {e}"

register_tool(
    name="image_resize",
    description="Resize an image to a specific width/height. Use for 'resize this image to 800x600'.",
    parameters={
        "type": "object",
        "properties": {
            "input_path": {"type": "string", "description": "Path to the input image"},
            "width": {"type": "integer", "description": "Target width (optional if height given)"},
            "height": {"type": "integer", "description": "Target height (optional if width given)"},
            "output_path": {"type": "string", "description": "Output path (optional)"}
        },
        "required": ["input_path"]
    },
    function=_image_resize,
    examples=["resize image to 800x600", "resize photo to width 1024"],
)


def _image_convert(input_path, format="jpg"):
    """Convert image format."""
    try:
        from PIL import Image
        import os

        img = Image.open(input_path)
        base = os.path.splitext(input_path)[0]
        output_path = f"{base}.{format.lower()}"

        # Handle PNG to JPG (remove alpha channel)
        if format.lower() in ("jpg", "jpeg") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        img.save(output_path, format.upper())
        return f"Image converted to {format.upper()} and saved to {output_path}"
    except Exception as e:
        return f"Image convert error: {e}"

register_tool(
    name="image_convert",
    description="Convert an image to a different format (jpg, png, webp). Use for 'convert this PNG to JPG'.",
    parameters={
        "type": "object",
        "properties": {
            "input_path": {"type": "string", "description": "Path to the input image"},
            "format": {"type": "string", "description": "Target format (jpg, png, webp)", "enum": ["jpg", "jpeg", "png", "webp"]}
        },
        "required": ["input_path", "format"]
    },
    function=_image_convert,
    examples=["convert this PNG to JPG", "convert image to webp"],
)


def _youtube_download(url, audio_only=False):
    """Download a YouTube video using yt-dlp."""
    try:
        import subprocess
        import sys

        # Ensure yt-dlp is installed
        try:
            import yt_dlp
        except ImportError:
            print("[YouTube]: Installing yt-dlp...")
            subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp"],
                         capture_output=True, check=True, timeout=60)

        import os
        download_dir = os.path.join(os.path.expanduser("~"), "Downloads")

        if audio_only:
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
                'quiet': True,
            }
        else:
            ydl_opts = {
                'format': 'best[ext=mp4]',
                'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
                'quiet': True,
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown')

        kind = "MP3 audio" if audio_only else "MP4 video"
        return f"Downloaded '{title}' as {kind} to your Downloads folder, Sir."
    except Exception as e:
        return f"YouTube download error: {e}"

register_tool(
    name="youtube_download",
    description="Download a YouTube video as MP4 or extract audio as MP3. Saves to Downloads folder.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "YouTube video URL"},
            "audio_only": {"type": "boolean", "description": "If true, extract MP3 audio only (default false)"}
        },
        "required": ["url"]
    },
    function=_youtube_download,
    examples=["download this YouTube video https://youtube.com/watch?v=...", "download as MP3 https://youtube.com/watch?v=..."],
)


def _get_process_tree():
    """Get a tree view of running processes."""
    try:
        import psutil

        # Get all processes
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'ppid', 'cpu_percent', 'memory_percent']):
            try:
                info = p.info
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Build tree by parent-child relationship
        by_ppid = {}
        for p in procs:
            ppid = p.get('ppid', 0)
            if ppid not in by_ppid:
                by_ppid[ppid] = []
            by_ppid[ppid].append(p)

        # Print top-level processes (ppid 0 or 1)
        lines = ["Process Tree (top processes):"]
        top_procs = sorted(by_ppid.get(0, []) + by_ppid.get(1, []), key=lambda x: x.get('memory_percent', 0), reverse=True)

        for proc in top_procs[:15]:
            name = proc.get('name', 'Unknown')
            pid = proc.get('pid', 0)
            mem = proc.get('memory_percent', 0)
            lines.append(f"  {name} (PID:{pid}, Mem:{mem:.1f}%)")

            # Show children
            children = by_ppid.get(pid, [])
            for child in sorted(children, key=lambda x: x.get('memory_percent', 0), reverse=True)[:3]:
                cname = child.get('name', 'Unknown')
                cpid = child.get('pid', 0)
                cmem = child.get('memory_percent', 0)
                lines.append(f"    └─ {cname} (PID:{cpid}, Mem:{cmem:.1f}%)")

        return "\n".join(lines)
    except Exception as e:
        return f"Process tree error: {e}"

register_tool(
    name="get_process_tree",
    description="Show running processes in a tree view. Use for 'what's running in a tree', 'show process tree'.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_get_process_tree,
    examples=["show process tree", "what's running in a tree"],
)


def _habit_check(habit_name):
    """Check off a daily habit."""
    try:
        import json
        import os
        from datetime import datetime

        # Get base dir from config or default to parent of modules/
        try:
            import config
            base_dir = getattr(config, 'BASE_DIR', None)
        except ImportError:
            base_dir = None

        if not base_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        habit_file = os.path.join(base_dir, "habits.json")
        habits = {}
        if os.path.exists(habit_file):
            with open(habit_file, 'r') as f:
                habits = json.load(f)

        today = datetime.now().strftime("%Y-%m-%d")

        if habit_name not in habits:
            habits[habit_name] = []

        if today not in habits[habit_name]:
            habits[habit_name].append(today)

        with open(habit_file, 'w') as f:
            json.dump(habits, f, indent=2)

        streak = len(habits[habit_name])
        return f"Habit '{habit_name}' checked off for today. Total days: {streak}."
    except Exception as e:
        return f"Habit check error: {e}"

register_tool(
    name="habit_check",
    description="Check off a daily habit. Use for 'I drank water today', 'habit check exercise'.",
    parameters={
        "type": "object",
        "properties": {
            "habit_name": {"type": "string", "description": "Name of the habit to check off"}
        },
        "required": ["habit_name"]
    },
    function=_habit_check,
    examples=["I drank water today", "habit check exercise", "mark habit meditation done"],
)


def _recall_vision(query):
    """Search vision memory for past camera/screen descriptions."""
    try:
        from vision_memory import get_vision_memory
        vm = get_vision_memory()
        results = vm.search(query, top_k=3)
        if not results:
            return "I don't have any vision memories matching that, Sir."

        lines = [f"I found {len(results)} matching vision memories, Sir:"]
        for r in results:
            lines.append(f"\n[{r['timestamp']}] ({r['source']}, score: {r['score']})")
            lines.append(f"  {r['description'][:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Vision memory error: {e}"

register_tool(
    name="recall_vision",
    description="Search past camera/screen descriptions. Use for 'what did you see earlier', 'what was on my screen before'.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for in vision memory"}
        },
        "required": ["query"]
    },
    function=_recall_vision,
    examples=["what did you see earlier", "what was on my screen before", "do you remember seeing a red mug"],
)


# === TOOL DISCOVERY TOOLS ===

def _add_tool(description):
    """Generate a tool skeleton from a description."""
    try:
        from tool_discovery import generate_tool_skeleton
        tool = generate_tool_skeleton(description)
        if "error" in tool:
            return f"Error generating tool: {tool['error']}"
        return (f"Generated tool '{tool['name']}', Sir.\n\n"
                f"Description: {tool['description']}\n"
                f"Parameters: {tool['parameters']}\n\n"
                f"Code:\n{tool['code']}\n\n"
                f"Say 'approve tool {tool['name']}' to register it, or 'reject tool {tool['name']}' to discard.")
    except Exception as e:
        return f"Error: {e}"

register_tool(
    name="add_tool",
    description="Generate a new tool from a description. Use for 'add a tool that does X', 'create a tool for Y'.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What the tool should do"}
        },
        "required": ["description"]
    },
    function=_add_tool,
    examples=["add a tool that converts Celsius to Fahrenheit", "create a tool for generating passwords"],
)


def _approve_tool(tool_name):
    """Approve a pending tool for registration."""
    try:
        from tool_discovery import approve_tool
        return approve_tool(tool_name)
    except Exception as e:
        return f"Error: {e}"

register_tool(
    name="approve_tool",
    description="Approve a pending tool to register it. Use after 'add tool' generates a skeleton.",
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {"type": "string", "description": "Name of the pending tool to approve"}
        },
        "required": ["tool_name"]
    },
    function=_approve_tool,
    examples=["approve tool celsius_to_fahrenheit"],
)


def _list_pending_tools(**kwargs):
    """List all pending tools awaiting review."""
    try:
        from tool_discovery import get_pending_tools
        pending = get_pending_tools()
        if not pending:
            return "No pending tools, Sir."
        lines = [f"{len(pending)} pending tool(s):"]
        for t in pending:
            lines.append(f"  - {t['name']}: {t['description']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"

register_tool(
    name="list_pending_tools",
    description="List all pending tools awaiting review.",
    parameters={"type": "object", "properties": {}, "required": []},
    function=_list_pending_tools,
    examples=["show pending tools", "list pending tools"],
)


# === INITIALIZATION ===

print(f"[ToolRegistry]: Loaded {len(_TOOLS)} tools: {', '.join(t['name'] for t in _TOOLS[:5])}, ...")

# Load any approved custom tools at startup
try:
    from tool_discovery import load_all_custom_tools
    load_all_custom_tools()
except Exception as e:
    print(f"[ToolRegistry]: Could not load custom tools: {e}")

# ═══════════════════════════════════════════════════════════════════════
# KNOWLEDGE INJECTOR TOOL (Tier 4)
# ═══════════════════════════════════════════════════════════════════════
# Searches the user's personal knowledge files (PDFs, Word docs, text files)
# Drop files in the knowledge/ directory and JARVIS can answer questions about them.
try:
    from knowledgeInjector import search_knowledge_tool

    register_tool(
        name="search_knowledge",
        description=(
            "Search the user's personal knowledge files (PDFs, Word docs, text files, JSON) "
            "that have been dropped in the knowledge/ directory. Use when the user asks about "
            "their own documents, files, notes, resume, meeting notes, project documentation, "
            "or any content they've provided. Returns relevant excerpts from their files. "
            "Examples: 'what does my resume say', 'what did I write about X', "
            "'find my notes on Y', 'what's in my project documentation'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in the knowledge files"}
            },
            "required": ["query"]
        },
        function=lambda query: search_knowledge_tool(query),
        examples=[
            "what's in my resume",
            "what did I write about the project",
            "find my notes on API design",
            "what does my documentation say about X"
        ],
        dont_use_for=[
            "general knowledge questions (use web_search instead)",
            "current events/news (use get_news instead)"
        ],
    )
    print("[ToolRegistry]: Knowledge injector tool registered.")
except ImportError:
    print("[ToolRegistry]: Knowledge injector not available (knowledgeInjector.py missing)")
except Exception as e:
    print(f"[ToolRegistry]: Could not register knowledge tool: {e}")
