"""
JARVIS Self-Knowledge & Capabilities Module (UPGRADED)
Gives JARVIS full awareness of what it can do,
guides users through commands, and answers capability questions.
"""
import re

# ─────────────────────────────────────────────
# FULL CAPABILITY MAP
# Each category: description + example phrases
# ─────────────────────────────────────────────

CAPABILITIES = {
    "System Control": {
        "description": "Control your PC hardware and settings directly.",
        "commands": [
            ("Set volume",         ["set volume to 70%", "make it louder", "volume up", "mute", "unmute"]),
            ("Set brightness",     ["set brightness to 50%", "dim the screen", "brightness up", "brightness down"]),
            ("Open any app",       ["open Chrome", "launch Spotify", "open VS Code", "open Unity"]),
            ("Uninstall app",      ["uninstall Notepad", "remove Discord"]),
            ("Close/kill app",     ["close Notepad", "kill Chrome", "end Spotify"]),
        ],
        "tip": "You can say things naturally — 'can you make it a bit louder' works just as well as 'volume up'."
    },

    "Music & Spotify": {
        "description": "Control Spotify playback (Premium required for full control).",
        "commands": [
            ("Play a song",        ["play Blinding Lights", "put on some Drake", "play relaxing jazz"]),
            ("Pause music",        ["pause", "stop the music", "pause Spotify"]),
            ("Resume music",       ["resume", "continue playing", "unpause"]),
            ("Skip track",         ["next song", "skip this", "next one"]),
            ("Previous track",     ["previous song", "go back", "last song"]),
            ("What's playing",     ["what song is this", "what's playing", "now playing"]),
            ("Spotify volume",     ["Spotify volume to 60"]),
        ],
        "tip": "Without Premium, JARVIS opens Spotify with the search loaded. You press play."
    },

    "Camera & Vision": {
        "description": "Use your webcam to see and analyze what's in front of it.",
        "commands": [
            ("Describe scene",     ["what do you see", "look around", "describe what you see"]),
            ("Identify object",    ["what is this", "what am I holding", "identify this"]),
            ("Read text",          ["read this", "what does this say"]),
            ("Analyze person",     ["what am I wearing", "who is in front of you"]),
            ("Analyze environment",["what's on my desk", "what's in front of me"]),
        ],
        "tip": "Just say anything that implies looking — 'can you see me' or 'take a look at this' both work."
    },

    "Notes & Notepad": {
        "description": "Save notes to JSON or write them directly to Notepad.",
        "commands": [
            ("Save a note",        ["note that I need groceries", "remember to call mom", "jot down meeting at 3pm"]),
            ("Find notes",         ["find my note about Python", "show notes about meetings"]),
            ("List all notes",     ["show my notes", "list notes", "all notes"]),
            ("Delete a note",      ["delete note 3", "remove note 1"]),
            ("Write to Notepad",   ["write hello world in Notepad", "open Notepad with my code", "put this in Notepad"]),
            ("Open note in Notepad",["open note 2 in Notepad"]),
            ("Save to file",       ["write that to a file", "save that to a file named specs", "write that to a file called notes"]),
        ],
        "tip": "Notes are saved to both JSON (searchable) and optionally to a .txt file opened in Notepad."
    },

    "Tasks": {
        "description": "Manage your to-do list and tasks.",
        "commands": [
            ("Create task",        ["create task finish Unity project", "add task submit report by Friday", "remind me to call dentist"]),
            ("List tasks",         ["show my tasks", "list tasks", "what do I need to do", "pending tasks"]),
            ("Complete task",      ["mark task 1 done", "complete task 3", "finish task 2"]),
            ("Delete task",        ["delete task 2", "remove task 5", "cancel task 1"]),
            ("Today's tasks",      ["tasks today", "what's due today"]),
            ("Completed tasks",    ["show completed tasks", "what have I done"]),
        ],
        "tip": "Tasks persist across sessions — they're saved to tasks.json in your project folder."
    },

    "File Search": {
        "description": "Search, open, and read files on your computer.",
        "commands": [
            ("Find a file",        ["find my resume", "search for invoice PDF", "locate my Unity project"]),
            ("Open a file",        ["open file 1", "open my budget.xlsx"]),
            ("Read file contents", ["read tts.py", "explain what is inside requirements.txt", "what's in that file"]),
            ("Find duplicates",    ["find duplicate copies of notes.txt"]),
        ],
        "tip": "After searching, say 'open 1', 'open 2' etc. to open results by number."
    },

    "Screenshots": {
        "description": "Capture your screen and save it.",
        "commands": [
            ("Take screenshot",    ["take a screenshot", "screenshot", "capture my screen"]),
            ("Named screenshot",   ["take screenshot named budget", "screenshot called meeting"]),
            ("Screenshot & open",  ["take a screenshot and open it", "screenshot and show me"]),
        ],
        "tip": "Screenshots are saved to Desktop/Screenshots/ as PNG files with a timestamp."
    },

    "Internet Search": {
        "description": "Search the web, get weather, news, and Wikipedia summaries. Only works when connected.",
        "commands": [
            ("Web search",         ["search for Python tutorials", "google quantum computing", "look up TypeScript"]),
            ("Weather",            ["what's the weather in Manila", "weather", "how hot is it in Tokyo"]),
            ("News",               ["latest news", "news about AI", "what's happening in the world"]),
            ("Wikipedia",          ["tell me about Elon Musk", "what is blockchain", "wiki Python"]),
            ("Exchange rates",     ["exchange rate", "how much is 1 dollar in pesos", "currency rates"]),
        ],
        "tip": "If you're offline, JARVIS will tell you and not attempt any search."
    },

    "System Monitor": {
        "description": "Check your computer's health, performance, and running processes.",
        "commands": [
            ("System status",      ["system status", "system health", "how is my computer", "CPU usage", "RAM usage"]),
            ("Running apps",       ["what's running", "show running apps", "what apps are open"]),
            ("Check process",      ["is Discord running", "check Chrome process"]),
            ("Kill process",       ["close Notepad", "kill Chrome", "force close a program"]),
            ("PC specs",           ["what are my specs", "system specs", "laptop specifications"]),
        ],
        "tip": "Requires psutil — install with: pip install psutil"
    },

    "Listening Modes": {
        "description": "Control how JARVIS listens for your voice.",
        "commands": [
            ("Auto mode",          ["auto mode", "always listen", "hands free mode", "background mode"]),
            ("Convo mode",         ["conversation mode", "convo mode", "free talk", "open mic"]),
            ("Silent mode",        ["silent mode", "go silent", "sleep mode"]),
            ("Speak mode",         ["speak mode", "push to talk", "manual mode"]),
            ("Text mode",          ["text mode", "type mode", "keyboard mode"]),
            ("Wake words",         ["hey Jarvis", "wake up Jarvis", "Jarvis are you there", "yo Jarvis"]),
            ("Sleep words",        ["go to sleep", "that's all", "thanks Jarvis", "bye Jarvis"]),
        ],
        "tip": "In auto/silent mode, say a wake word first. JARVIS stays awake for 30 seconds after, then sleeps again."
    },

    "AI Model Switching": {
        "description": "Switch between different AI models for different tasks.",
        "commands": [
            ("High performance",   ["high performance mode", "performance mode", "boost mode"]),
            ("Smart/code mode",    ["smart mode", "code mode", "developer mode"]),
            ("Fast mode",          ["fast mode", "speed mode", "light mode"]),
            ("secondary mode",    ["secondary mode", "unrestricted mode"]),
            ("Reset to default",   ["set default", "default mode", "reset mode"]),
            ("Camera detail",      ["detail cam mode", "high detail camera"]),
            ("Camera fast",        ["fast cam mode", "quick camera"]),
        ],
        "tip": "High performance mode switches both JARVIS and the camera to the best models simultaneously."
    },

    "Memory & Learning": {
        "description": "JARVIS remembers your conversations and learns your patterns.",
        "commands": [
            ("Clear memory",       ["clear", "wipe memory", "start fresh"]),
            ("Set your name",      ["my name is John", "call me Sir"]),
            ("Command history",    ["what are my most common commands", "show my usage patterns"]),
        ],
        "tip": "Memory is saved after every response. Even if JARVIS crashes, your history is preserved."
    },
}


# ─────────────────────────────────────────────
# QUERY MATCHERS
# ─────────────────────────────────────────────

CAPABILITY_QUESTION_TRIGGERS = [
    "what can you do", "what are you capable of", "your capabilities",
    "what do you know", "what are your features", "show me your features",
    "list your capabilities", "what are your abilities", "what are your skills",
    "full list of commands", "show commands", "all commands", "list commands",
    "what commands", "help me", "show help", "what functions", "your functions",
    "what features", "capabilities", "what can i ask you", "what can i say to you",
    "what do you support", "what are your powers", "what can jarvis do",
]

CATEGORY_QUESTION_TRIGGERS = {
    "System Control":    ["volume", "brightness", "open app", "system control", "control my pc"],
    "Music & Spotify":   ["spotify", "music", "play song", "song commands"],
    "Camera & Vision":   ["camera", "vision", "see", "look at"],
    "Notes & Notepad":   ["note", "notepad", "write", "save note", "reminder"],
    "Tasks":             ["task", "todo", "to do", "remind me", "task manager"],
    "File Search":       ["file", "search file", "find file", "document"],
    "Screenshots":       ["screenshot", "capture screen", "screen capture"],
    "Internet Search":   ["internet", "search web", "weather", "news", "google"],
    "System Monitor":    ["monitor", "system status", "cpu", "ram", "running apps", "specs"],
    "Listening Modes":   ["listening mode", "voice mode", "auto mode", "silent mode", "wake word"],
    "AI Model Switching":["model", "switch model", "performance mode", "smart mode"],
    "Memory & Learning": ["memory", "remember", "learning", "history", "patterns"],
}

HOW_TO_TRIGGERS = [
    "how do i", "how can i", "how to", "how do i use", "show me how",
    "teach me", "guide me", "help me use", "how does", "example of",
    "give me an example", "what do i say to", "how do i test",
]


def get_full_capabilities_text():
    """Return the full capability list as readable text for display."""
    lines = ["JARVIS FULL CAPABILITIES\n" + "=" * 40]
    for i, (category, data) in enumerate(CAPABILITIES.items(), 1):
        lines.append(f"\n{i}. {category.upper()}")
        lines.append(f"   {data['description']}")
        lines.append("   Commands:")
        for cmd_name, examples in data["commands"]:
            lines.append(f"     - {cmd_name}: \"{examples[0]}\"")
        lines.append(f"   Tip: {data['tip']}")
    lines.append("\n" + "=" * 40)
    lines.append("Say 'how do I use [feature]' for a guided walkthrough.")
    lines.append("Say 'show me [category] commands' for specific help.")
    return "\n".join(lines)


def get_full_capabilities_spoken():
    """Return a shorter spoken version of capabilities."""
    categories = list(CAPABILITIES.keys())
    spoken = (
        "I have a wide range of capabilities, Sir. "
        "I can control your system — volume, brightness, and apps. "
        "I can play music on Spotify, use your camera to see things, "
        "take screenshots, save notes and tasks, search your files, "
        "monitor your system health, search the internet when connected, "
        "and switch between different AI models. "
        f"In total I have {len(categories)} capability categories. "
        "I can show you the full command list, or guide you through any specific feature. "
        "Would you like the full list, or help with a specific one?"
    )
    return spoken


def get_category_help(category_name):
    """Return detailed help for a specific category."""
    data = CAPABILITIES.get(category_name)
    if not data:
        return None

    lines = [f"{category_name} — {data['description']}\n"]
    lines.append("Example commands you can say:")
    for cmd_name, examples in data["commands"]:
        lines.append(f"\n  {cmd_name}:")
        for ex in examples[:2]:
            lines.append(f"    - \"{ex}\"")
    lines.append(f"\nTip: {data['tip']}")
    lines.append(f"\nWant to try one? Just say it and I will handle it.")
    return "\n".join(lines)


def get_category_help_spoken(category_name):
    """Shorter spoken version of category help."""
    data = CAPABILITIES.get(category_name)
    if not data:
        return None

    example_cmds = []
    for cmd_name, examples in data["commands"][:4]:
        example_cmds.append(f'"{examples[0]}"')

    spoken = (
        f"For {category_name}, {data['description']} "
        f"For example, you can say: {', '.join(example_cmds)}. "
        f"{data['tip']} "
        f"Want to try one of these now?"
    )
    return spoken


def find_matching_category(text):
    """Find which capability category the user is asking about."""
    text_lower = text.lower()
    for category, triggers in CATEGORY_QUESTION_TRIGGERS.items():
        if any(t in text_lower for t in triggers):
            return category
    return None


def generate_howto_guide(text):
    """
    Generate a guided walkthrough based on what the user wants to learn.
    Returns (spoken_response, print_response) tuple.
    """
    text_lower = text.lower()

    # Match to a category
    category = find_matching_category(text_lower)

    if category:
        data = CAPABILITIES[category]
        spoken = get_category_help_spoken(category)
        printed = get_category_help(category)
        return spoken, printed

    # Generic how-to
    spoken = (
        "I can guide you through any of my features, Sir. "
        "Tell me which one you want to learn — for example, "
        "say 'how do I use the camera', 'how do I save notes', "
        "'how do I search files', or 'how do I control the volume'. "
        "I will walk you through it step by step."
    )
    printed = (
        "Available feature guides:\n" +
        "\n".join(f"  - {cat}" for cat in CAPABILITIES.keys()) +
        "\n\nSay 'how do I use [feature name]' to get started."
    )
    return spoken, printed


def handle_capability_commands(user_input):
    """
    Main entry point. Returns (spoken, printed) tuple or None if not a capability question.
    spoken  = what JARVIS says aloud
    printed = what gets printed to terminal (may include full command list)
    """
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())
    words = text.split()

    # 1. Smart check for full capabilities question
    is_full_capabilities = any(t in text for t in CAPABILITY_QUESTION_TRIGGERS) or \
                           (any(w in words for w in ["commands", "command", "features", "feature", "abilities", "functions", "skills"]) and 
                            any(w in words for w in ["all", "list", "show", "have", "you", "your", "forgot", "get"]))
    
    if is_full_capabilities:
        spoken  = get_full_capabilities_spoken()
        printed = get_full_capabilities_text()
        return spoken, printed

    # 2. How-to / guided walkthrough
    if any(t in text for t in HOW_TO_TRIGGERS) or "how" in words:
        return generate_howto_guide(text)

    # 3. Category-specific help: "show me note commands", "what are the file commands"
    category_q = re.search(
        r'(?:show|list|tell me|what are|give me)\s+(?:me\s+)?(?:the\s+)?(.+?)\s+commands?',
        text
    )
    if category_q:
        query = category_q.group(1).strip()
        category = find_matching_category(query)
        if category:
            spoken  = get_category_help_spoken(category)
            printed = get_category_help(category)
            return spoken, printed

    return None