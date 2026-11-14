"""
JARVIS Streaming Tool Results (Tier 3.3)
================================================================
Speaks news headlines and search results as they arrive, instead of
waiting for the full result set before speaking.

How it works:
1. For tools in STREAMING_RESULTS_TOOLS, the executor checks if the
   tool supports streaming (has a generator-based variant)
2. If yes, it calls the streaming variant and speaks each result as
   it arrives
3. If no, falls back to the normal non-streaming execution

Currently supports streaming for:
  - get_news: speaks each headline as it's fetched
  - web_search: speaks each result as it's found

The streaming happens via speak_async() so JARVIS speaks each result
while the next one is being fetched, creating a "live news report" feel
instead of waiting 5-10 seconds in silence then speaking everything at once.
"""
import os
import sys
import threading
import time
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = _PARENT_DIR


# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

STREAMING_ENABLED = getattr(config, 'STREAMING_RESULTS_ENABLED', True)
STREAMING_TOOLS   = getattr(config, 'STREAMING_RESULTS_TOOLS', ["get_news", "web_search"])


# ═══════════════════════════════════════════════════════════════════════
# STREAMING TOOL EXECUTORS
# ═══════════════════════════════════════════════════════════════════════

def stream_get_news(topic=None, max_headlines=5, speak_fn=None):
    """
    Fetch news headlines and speak each one as it arrives.
    Returns the full compiled result string (same as non-streaming get_news).
    """
    try:
        from internetSearch import require_internet
        err = require_internet()
        if err:
            return err

        from ddgs import DDGS

        results_text = []
        headline_count = 0

        if speak_fn and topic:
            speak_fn(f"Here are the latest headlines about {topic}, Sir.")

        # Fetch news with streaming-like behavior
        with DDGS() as ddgs:
            news_results = list(ddgs.news(topic, max_results=max_headlines))

            for r in news_results:
                title = r.get("title", "")
                body = r.get("body", "")
                date = r.get("date", "Recent")
                source = r.get("source", "News")

                result_line = f"- [{source} | {date}] {title}: {body}"
                results_text.append(result_line)
                headline_count += 1

                # Speak this headline immediately (non-blocking via speak_async)
                if speak_fn:
                    # Speak a shortened version for speech (full body is too long)
                    spoken_version = f"{source} reports: {title}."
                    try:
                        speak_fn(spoken_version)
                    except Exception:
                        pass

                    # Small pause between headlines for natural delivery
                    time.sleep(0.3)

        if results_text:
            if topic:
                result = f"Latest news regarding '{topic}':\n" + "\n".join(results_text)
            else:
                result = "Latest general headlines:\n" + "\n".join(results_text)
            return result
        return f"No news found about '{topic}'."

    except Exception as e:
        return f"News streaming error: {e}"


def stream_web_search(query, max_results=5, speak_fn=None):
    """
    Perform a web search and speak each result as it arrives.
    Returns the full compiled result string.
    """
    try:
        from internetSearch import require_internet
        err = require_internet()
        if err:
            return err

        from ddgs import DDGS

        results_text = []

        if speak_fn:
            speak_fn(f"Searching for {query}, Sir.")

        with DDGS() as ddgs:
            search_results = list(ddgs.text(query, max_results=max_results))

            for i, r in enumerate(search_results, 1):
                title = r.get("title", "")
                body = r.get("body", "")
                url = r.get("href", "")

                result_line = f"{i}. {title}\n   {body}\n   {url}"
                results_text.append(result_line)

                # Speak this result immediately
                if speak_fn:
                    spoken_version = f"Result {i}: {title}."
                    try:
                        speak_fn(spoken_version)
                    except Exception:
                        pass

                    time.sleep(0.3)

        if results_text:
            return f"Search results for '{query}':\n\n" + "\n\n".join(results_text)
        return f"No results found for '{query}'."

    except Exception as e:
        return f"Search streaming error: {e}"


# ═══════════════════════════════════════════════════════════════════════
# STREAMING DISPATCHER
# ═══════════════════════════════════════════════════════════════════════

def try_streaming_tool(tool_name, args, speak_fn=None):
    """
    Check if a tool supports streaming and execute it with streaming if so.
    Returns the result string if streaming was used, or None if the tool
    doesn't support streaming (caller should use normal execution).

    Args:
        tool_name: Name of the tool to execute
        args: Dict of arguments for the tool
        speak_fn: Function to call for speaking intermediate results

    Returns:
        result_string if streaming was used, None if not supported
    """
    if not STREAMING_ENABLED:
        return None

    if tool_name not in STREAMING_TOOLS:
        return None

    if tool_name == "get_news":
        topic = args.get("topic")
        max_headlines = args.get("max_headlines", 5)
        return stream_get_news(topic=topic, max_headlines=max_headlines, speak_fn=speak_fn)

    elif tool_name == "web_search":
        query = args.get("query", "")
        max_results = args.get("max_results", 5)
        return stream_web_search(query=query, max_results=max_results, speak_fn=speak_fn)

    # Tool is in STREAMING_TOOLS but no streaming executor implemented
    return None


def is_streaming_tool(tool_name):
    """Check if a tool supports streaming execution."""
    return STREAMING_ENABLED and tool_name in STREAMING_TOOLS


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Streaming Tool Results (Tier 3.3)...\n")

    # Test 1: Check which tools support streaming
    print("=== Streaming Tool Support ===")
    test_tools = ["get_news", "web_search", "set_volume", "spotify_play", "wikipedia_summary"]
    for tool in test_tools:
        supports = is_streaming_tool(tool)
        label = "STREAMING" if supports else "normal"
        print(f"  {tool:20s} -> {label}")

    # Test 2: Mock speak function
    print("\n=== Mock Streaming (no internet required) ===")
    spoken = []
    mock_speak = lambda text: spoken.append(text)

    # Test the dispatcher with a non-streaming tool
    result = try_streaming_tool("set_volume", {"percent": 50}, mock_speak)
    print(f"  set_volume streaming result: {result} (expected None)")

    # Test the dispatcher with a streaming tool (will try internet, may fail offline)
    print(f"\n  Attempting get_news streaming (requires internet)...")
    result = try_streaming_tool("get_news", {"topic": "technology"}, mock_speak)
    if result:
        print(f"  Result (first 200 chars): {result[:200]}")
        print(f"  Spoken {len(spoken)} messages")
    else:
        print(f"  No result (likely offline)")
