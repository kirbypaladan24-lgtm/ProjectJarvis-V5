"""
JARVIS Tool Composition System
================================================================
Allows tools to call other tools automatically based on context.
For example: "find my resume and read it" → search_files + read_file

This is how Claude/GPT work — they don't just pick ONE tool,
they chain tools together iteratively.

Composition Rules:
    - "find X and read it"     → search_files → read_file(top result)
    - "find X and open it"     → search_files → open_file(top result)
    - "take a screenshot and open it" → take_screenshot → open_file(screenshot)
    - "search for X and summarize" → web_search → chat_only(summarize)
    - "note X and create a task" → save_note → create_task

Usage:
    from tool_composition import detect_composition, execute_composition

    composition = detect_composition("find my resume and read it")
    if composition:
        results = execute_composition(composition)
"""
import os
import sys
import re

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
_MODULES_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)


# ═════════════════════════════════════════════════════════════
# COMPOSITION RULES
# ═════════════════════════════════════════════════════════════
# Each rule: (regex pattern, [tool calls to execute in sequence])
# $1, $2 etc. in args are replaced with regex capture groups

COMPOSITION_RULES = [
    # "find X and read it" → search_files → read_file
    {
        "pattern": r"(?:find|search for|locate)\s+(.+?)\s+and\s+read\s+it",
        "tools": [
            {"name": "search_files", "args": {"query": "$1"}},
            {"name": "_read_top_result", "args": {}},
        ],
        "description": "Find a file and read its contents",
    },
    # "find X and open it" → search_files → open_file
    {
        "pattern": r"(?:find|search for|locate)\s+(.+?)\s+and\s+open\s+it",
        "tools": [
            {"name": "search_files", "args": {"query": "$1"}},
            {"name": "_open_top_result", "args": {}},
        ],
        "description": "Find a file and open it",
    },
    # "take a screenshot and open it" → take_screenshot → open_file
    {
        "pattern": r"take\s+(?:a\s+)?screenshot\s+and\s+open\s+it",
        "tools": [
            {"name": "take_screenshot", "args": {}},
            {"name": "_open_last_screenshot", "args": {}},
        ],
        "description": "Take a screenshot and open it",
    },
    # "note X and create a task" → save_note → create_task
    {
        "pattern": r"note\s+(?:that\s+)?(.+?)\s+and\s+create\s+(?:a\s+)?task",
        "tools": [
            {"name": "save_note", "args": {"title": "$1", "content": "$1"}},
            {"name": "create_task", "args": {"title": "$1"}},
        ],
        "description": "Save a note and create a task",
    },
    # "search for X and summarize" → web_search → (chat handles summary)
    {
        "pattern": r"search\s+for\s+(.+?)\s+and\s+summarize",
        "tools": [
            {"name": "web_search", "args": {"query": "$1"}},
            {"name": "_summarize_result", "args": {}},
        ],
        "description": "Search the web and summarize results",
    },
    # "what's the weather in X and is it cold" → get_weather → (chat analyzes)
    {
        "pattern": r"what'?s\s+the\s+weather\s+in\s+(\w+)\s+and\s+(.+)",
        "tools": [
            {"name": "get_weather", "args": {"location": "$1"}},
            {"name": "_analyze_weather", "args": {"question": "$2"}},
        ],
        "description": "Get weather and answer a question about it",
    },
]


# ═════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (internal tools for composition)
# ═════════════════════════════════════════════════════════════

def _read_top_result(prev_result, **kwargs):
    """Read the first file from a search_files result."""
    try:
        import re
        # Try to extract a file path from the search results
        match = re.search(r'([A-Z]:\\[^\n]+\.\w+|/\w+[^\n]+\.\w+)', str(prev_result))
        if match:
            from toolRegistry import get_tool_function
            read_fn = get_tool_function("read_file")
            if read_fn:
                return read_fn(path=match.group(1))
        return f"Could not find a file path in the search results."
    except Exception as e:
        return f"Error reading top result: {e}"


def _open_top_result(prev_result, **kwargs):
    """Open the first file from a search_files result."""
    try:
        import re
        match = re.search(r'([A-Z]:\\[^\n]+\.\w+|/\w+[^\n]+\.\w+)', str(prev_result))
        if match:
            from toolRegistry import get_tool_function
            open_fn = get_tool_function("open_file")
            if open_fn:
                return open_fn(path=match.group(1))
        return f"Could not find a file path in the search results."
    except Exception as e:
        return f"Error opening top result: {e}"


def _open_last_screenshot(prev_result, **kwargs):
    """Open the last screenshot taken."""
    try:
        from smartRouter import get_entity
        screenshot = get_entity("last_screenshot")
        if screenshot:
            from toolRegistry import get_tool_function
            open_fn = get_tool_function("open_file")
            if open_fn:
                return open_fn(path=screenshot)
        return "No recent screenshot found."
    except Exception as e:
        return f"Error opening screenshot: {e}"


def _summarize_result(prev_result, **kwargs):
    """Summarize the previous tool result using the LLM."""
    try:
        import requests
        import config
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                "messages": [
                    {"role": "system", "content": "Summarize the following in 2-3 sentences. Address the user as Sir."},
                    {"role": "user", "content": str(prev_result)[:2000]},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 150},
            },
            timeout=15
        )
        if response.status_code == 200:
            return response.json().get("message", {}).get("content", "").strip()
        return "Could not summarize the results."
    except Exception as e:
        return f"Summarize error: {e}"


def _analyze_weather(prev_result, question, **kwargs):
    """Answer a question about weather data."""
    try:
        import requests
        import config
        prompt = f"Weather data: {prev_result}\n\nUser question: {question}\n\nAnswer the question based on the weather data. Address the user as Sir."
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                "messages": [
                    {"role": "system", "content": "You are JARVIS. Answer questions about weather data concisely."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 100},
            },
            timeout=15
        )
        if response.status_code == 200:
            return response.json().get("message", {}).get("content", "").strip()
        return "Could not analyze the weather data."
    except Exception as e:
        return f"Analysis error: {e}"


# ═════════════════════════════════════════════════════════════
# DETECTION AND EXECUTION
# ═════════════════════════════════════════════════════════════

def detect_composition(user_input):
    """
    Check if the user's input matches a composition rule.
    Returns a composition dict if matched, or None.
    """
    if not user_input:
        return None

    text = user_input.lower().strip()

    for rule in COMPOSITION_RULES:
        match = re.search(rule["pattern"], text, re.IGNORECASE)
        if match:
            # Substitute capture groups into tool args
            tools = []
            for tool_call in rule["tools"]:
                args = {}
                for key, val in tool_call["args"].items():
                    if isinstance(val, str) and val.startswith("$"):
                        # Replace $1, $2 etc. with capture groups
                        group_num = int(val[1:])
                        try:
                            args[key] = match.group(group_num)
                        except IndexError:
                            args[key] = val
                    else:
                        args[key] = val
                tools.append({"name": tool_call["name"], "args": args})

            return {
                "rule": rule["description"],
                "tools": tools,
                "match": match,
            }

    return None


def execute_composition(composition, speak_fn=None):
    """
    Execute a composition (sequence of tool calls).
    Returns a dict with the final response and all tool results.
    """
    if not composition:
        return None

    from toolExecutor import execute_tool_call

    results = []
    prev_result = None

    for i, tool_call in enumerate(composition["tools"]):
        tool_name = tool_call["name"]
        args = tool_call["args"]

        # If it's a helper function (starts with _), call it directly
        if tool_name.startswith("_"):
            helper = globals().get(tool_name)
            if helper:
                result = helper(prev_result, **args)
            else:
                result = f"Helper function '{tool_name}' not found."
        else:
            # Execute via tool executor
            print(f"[Composition]: Step {i+1}/{len(composition['tools'])} — calling {tool_name}({args})")
            result = execute_tool_call(tool_name, args)

        results.append({"tool": tool_name, "result": result})
        prev_result = result
        print(f"[Composition]: Result: {str(result)[:100]}")

    # The final result is the response
    final_result = results[-1]["result"] if results else "Composition produced no results."

    return {
        "response": final_result,
        "tools_used": [r["tool"] for r in results],
        "all_results": results,
        "iterations": len(results),
        "success": True,
        "fast_path": "composition",
    }


# ═════════════════════════════════════════════════════════════
# TEST
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Tool Composition System...\n")

    # Test detection
    tests = [
        ("find my resume and read it", "Find a file and read its contents"),
        ("find my resume and open it", "Find a file and open it"),
        ("take a screenshot and open it", "Take a screenshot and open it"),
        ("note that I need milk and create a task", "Save a note and create a task"),
        ("search for Python tutorials and summarize", "Search the web and summarize results"),
        ("what's the weather in Tokyo and is it cold", "Get weather and answer a question about it"),
        ("hello", None),  # Should not match
        ("set volume to 50", None),  # Should not match
    ]

    for user_input, expected_desc in tests:
        comp = detect_composition(user_input)
        if expected_desc is None:
            assert comp is None, f"Should not match: '{user_input}'"
            print(f"  ✅ No match: \"{user_input}\"")
        else:
            assert comp is not None, f"Should match: '{user_input}'"
            assert comp["rule"] == expected_desc, f"Wrong rule: expected '{expected_desc}', got '{comp['rule']}'"
            print(f"  ✅ Matched: \"{user_input}\" → {comp['rule']} ({len(comp['tools'])} steps)")

    print("\nAll detection tests passed ✅")
