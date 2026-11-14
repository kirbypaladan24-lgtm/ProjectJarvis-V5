"""
JARVIS Multi-Command Execution with Synthesis (Phase 5)
================================================================
Replaces the recursive process_command() approach for multi-commands
with a unified execute + synthesize flow.

When the normalization layer (Phase 2) splits "set volume to 50 and play
some Drake" into ["set volume to 50", "play some Drake"], this module:

1. Executes each sub-command through route_with_tools() independently
   (collecting results WITHOUT speaking them individually)
2. Sends all results to the 1.5B model for synthesis into ONE natural
   sentence
3. Speaks the synthesized response once

This produces: "Done, Sir — volume set to 50 and playing Drake."
Instead of:    "Volume set to 50, Sir. Playing Drake, Sir."

Dependent commands (detected by Phase 2's pronoun check) are NOT split
and route to the 8B as a single workflow — that's handled upstream.
"""
import os
import sys
import json
import re
import time
import requests
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        OLLAMA_BASE_URL = "http://localhost:11434"
        CASUAL_CHAT_MODEL = "qwen2.5:1.5b-instruct"
        BASE_DIR = _PARENT_DIR


# ═══════════════════════════════════════════════════════════════════════
# CONFIG (override in config.py)
# ═══════════════════════════════════════════════════════════════════════

MULTI_COMMAND_ENABLED          = getattr(config, 'MULTI_COMMAND_ENABLED', True)
MULTI_COMMAND_SYNTHESIS_ENABLED = getattr(config, 'MULTI_COMMAND_SYNTHESIS_ENABLED', True)
MULTI_COMMAND_MAX_TOKENS       = getattr(config, 'MULTI_COMMAND_MAX_TOKENS', 120)
MULTI_COMMAND_TEMPERATURE      = getattr(config, 'MULTI_COMMAND_TEMPERATURE', 0.4)
MULTI_COMMAND_ENABLE_LOG       = getattr(config, 'MULTI_COMMAND_ENABLE_LOG', True)
MULTI_COMMAND_TIMEOUT          = getattr(config, 'MULTI_COMMAND_TIMEOUT', 10)

_LOG_FILE = os.path.join(getattr(config, 'BASE_DIR', _PARENT_DIR), "multi_command_log.jsonl")


# ═══════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════

def _log(action, details):
    if not MULTI_COMMAND_ENABLE_LOG:
        return
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# RESPONSE CLEANING
# ═══════════════════════════════════════════════════════════════════════

def _strip_sir(text):
    """
    Remove trailing 'Sir' from a response for cleaner synthesis.
    The synthesized response will add 'Sir' itself.
    """
    if not text:
        return text
    # Remove trailing ", Sir." or ", Sir" or " Sir." or " Sir"
    text = re.sub(r'[,\s]+Sir\.?\s*$', '', text, flags=re.IGNORECASE)
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════
# SUB-COMMAND EXECUTION
# ═══════════════════════════════════════════════════════════════════════

def _execute_single_sub_command(sub_cmd, history, speak_fn):
    """
    Execute a single sub-command through the tool router.
    Returns a dict with: command, tool, response, success.
    Does NOT speak the response — that's handled by the synthesizer.
    """
    # Preprocess (phonetic, Tagalog, shorthands, pronouns) — but NOT normalization
    # (normalization already happened upstream before the split)
    try:
        from languageIntelligence import preprocess_input
        processed = preprocess_input(sub_cmd, history)
    except Exception:
        processed = sub_cmd

    # Route through the tool router
    # speak_fn is passed for:
    #   - Thinking interjection ("Let me check...")
    #   - Approval gate prompts ("Confirm shutdown?")
    # But the final response is RETURNED, not spoken
    try:
        from toolRouter import route_with_tools
        tool_result = route_with_tools(processed, history, speak_fn=speak_fn)

        if tool_result and tool_result.get("success"):
            response = tool_result.get("response", "").strip()
            tools_used = tool_result.get("tools_used", [])
            tool_name = tools_used[0] if tools_used else "chat_only"
            return {
                "command": sub_cmd,
                "tool": tool_name,
                "response": response,
                "success": True,
            }
        else:
            error_msg = tool_result.get("response", "could not execute") if tool_result else "no result"
            return {
                "command": sub_cmd,
                "tool": "failed",
                "response": error_msg,
                "success": False,
            }
    except Exception as e:
        return {
            "command": sub_cmd,
            "tool": "error",
            "response": f"error: {e}",
            "success": False,
        }


# ═══════════════════════════════════════════════════════════════════════
# RESPONSE SYNTHESIS
# ═══════════════════════════════════════════════════════════════════════

def _synthesize_responses(results, speak_fn):
    """
    Send all tool results to the 1.5B model and get a natural combined response.
    Falls back to concatenated responses if synthesis fails or is disabled.

    Args:
        results: List of dicts from _execute_single_sub_command()
        speak_fn: Function to speak the final response

    Returns:
        The synthesized (or fallback) response string.
    """
    # If only one result, just return it (shouldn't happen, but safety)
    if len(results) == 1:
        response = results[0]["response"]
        speak_fn(response)
        return response

    # If synthesis is disabled, concatenate responses
    if not MULTI_COMMAND_SYNTHESIS_ENABLED:
        return _concatenate_responses(results, speak_fn)

    # Build the synthesis prompt
    prompt_lines = ["You executed these commands for the user:"]
    for i, r in enumerate(results, 1):
        # Strip "Sir" from individual responses for cleaner synthesis
        clean_response = _strip_sir(r["response"])
        prompt_lines.append(f'{i}. "{r["command"]}" → {clean_response}')

    prompt_lines.append("")
    prompt_lines.append('Combine these results into ONE natural, concise sentence. Address the user as "Sir" once at the end.')
    prompt_lines.append('Do NOT repeat "Sir" for each result. Do NOT list them separately.')
    prompt_lines.append('')
    prompt_lines.append('Examples:')
    prompt_lines.append('  "Done, Sir — volume set to 50 and playing Drake."')
    prompt_lines.append('  "Opening chrome and youtube, Sir."')
    prompt_lines.append('  "Volume at 50 and brightness at 80, Sir."')

    prompt = "\n".join(prompt_lines)

    # Call 1.5B for synthesis
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'),
                "messages": [
                    {"role": "system", "content": "You are JARVIS. Address the user as Sir. Be concise and natural."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {
                    "num_predict": MULTI_COMMAND_MAX_TOKENS,
                    "temperature": MULTI_COMMAND_TEMPERATURE,
                },
                "keep_alive": config.get_keep_alive(getattr(config, 'CASUAL_CHAT_MODEL', 'qwen2.5:1.5b-instruct'))
            },
            timeout=MULTI_COMMAND_TIMEOUT
        )
        response.raise_for_status()
        synthesized = response.json().get("message", {}).get("content", "").strip()

        if synthesized:
            speak_fn(synthesized)
            _log("synthesis_success", {
                "results_count": len(results),
                "synthesized": synthesized[:200],
            })
            return synthesized
    except requests.exceptions.ConnectionError:
        print("[MultiCommand]: Cannot connect to Ollama for synthesis — using fallback.")
    except Exception as e:
        print(f"[MultiCommand]: Synthesis failed: {e}")

    # Fallback: concatenate responses
    return _concatenate_responses(results, speak_fn)


def _concatenate_responses(results, speak_fn):
    """
    Fallback: concatenate individual responses into one string and speak once.
    Still produces a single speak() call (not robotic serial).
    """
    parts = []
    for r in results:
        if r["success"] and r["response"]:
            # Strip "Sir" from each part, add it once at the end
            clean = _strip_sir(r["response"])
            if clean:
                parts.append(clean)

    if not parts:
        fallback = "Done, Sir."
    elif len(parts) == 1:
        fallback = f"{parts[0]}, Sir."
    else:
        # Join with "and" for the last item
        if len(parts) == 2:
            fallback = f"{parts[0]} and {parts[1]}, Sir."
        else:
            fallback = f"{', '.join(parts[:-1])}, and {parts[-1]}, Sir."

    speak_fn(fallback)
    _log("synthesis_fallback", {
        "results_count": len(results),
        "fallback": fallback[:200],
    })
    return fallback


# ═══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

def execute_multi_command(sub_commands, speak_fn, history, original_input=None):
    """
    Execute multiple independent sub-commands and synthesize a combined response.

    Args:
        sub_commands: List of command strings (already split by normalization)
        speak_fn: Function to speak the final synthesized response
        history: Conversation history list (for context)
        original_input: The original un-split user input (for logging)

    Returns:
        The synthesized response string.
    """
    if not MULTI_COMMAND_ENABLED:
        # If disabled, fall back to recursive process_command (old behavior)
        # This shouldn't happen since the caller checks, but safety first
        return None

    start_time = time.time()

    print(f"[MultiCommand]: Executing {len(sub_commands)} sub-commands...")

    # Tier 2.2: Parallelize execution for independent sub-commands
    # Use ThreadPoolExecutor since route_with_tools() makes HTTP calls to Ollama
    # (I/O-bound, so threads are appropriate; GIL is released during requests)
    if len(sub_commands) > 1 and getattr(config, 'MULTI_COMMAND_PARALLEL', True):
        print(f"[MultiCommand]: Running {len(sub_commands)} sub-commands in parallel...")
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Submit all sub-commands in parallel
        with ThreadPoolExecutor(max_workers=min(len(sub_commands), 3)) as executor:
            # Use a dict to preserve order: {future: index}
            future_to_index = {}
            for i, sub_cmd in enumerate(sub_commands):
                print(f"[MultiCommand]: ({i+1}/{len(sub_commands)}) '{sub_cmd}' (submitted)")
                future = executor.submit(_execute_single_sub_command, sub_cmd, history, speak_fn)
                future_to_index[future] = i

            # Collect results in original order
            results = [None] * len(sub_commands)
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    print(f"[MultiCommand]: Sub-command {idx+1} failed: {e}")
                    results[idx] = {
                        "command": sub_commands[idx],
                        "tool": "error",
                        "response": f"error: {e}",
                        "success": False,
                    }
    else:
        # Sequential fallback (single command or parallel disabled)
        results = []
        for i, sub_cmd in enumerate(sub_commands):
            print(f"[MultiCommand]: ({i+1}/{len(sub_commands)}) '{sub_cmd}'")
            result = _execute_single_sub_command(sub_cmd, history, speak_fn)
            results.append(result)
            status = "OK" if result["success"] else "FAIL"
            print(f"[MultiCommand]:   -> [{status}] {result['tool']}: {result['response'][:80]}")

    # Brief log of each result (parallel path)
    if len(sub_commands) > 1 and getattr(config, 'MULTI_COMMAND_PARALLEL', True):
        for i, result in enumerate(results):
            if result:
                status = "OK" if result["success"] else "FAIL"
                print(f"[MultiCommand]:   -> [{status}] {result['tool']}: {result['response'][:80]}")

    # Synthesize the combined response
    synthesized = _synthesize_responses(results, speak_fn)

    elapsed = time.time() - start_time

    _log("execute_complete", {
        "original_input": (original_input or "")[:200],
        "sub_commands": [c[:100] for c in sub_commands],
        "results": [{"tool": r["tool"], "success": r["success"]} for r in results],
        "synthesized": synthesized[:200],
        "elapsed_seconds": round(elapsed, 2),
    })

    print(f"[MultiCommand]: Done in {elapsed:.1f}s — {synthesized[:80]}...")

    return synthesized


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Multi-Command (Phase 5)...\n")

    # Test 1: Strip "Sir"
    print("=== Strip 'Sir' ===")
    test_texts = [
        "Volume set to 50 percent, Sir.",
        "Playing Drake, Sir",
        "Done, Sir.",
        "Opening chrome, Sir. Opening youtube, Sir.",
    ]
    for text in test_texts:
        result = _strip_sir(text)
        print(f"  '{text}' → '{result}'")

    # Test 2: Concatenate responses (fallback)
    print("\n=== Concatenate Responses (Fallback) ===")
    test_results = [
        {"command": "set volume to 50", "tool": "set_volume", "response": "Volume set to 50 percent, Sir.", "success": True},
        {"command": "play some Drake", "tool": "spotify_play", "response": "Playing Drake, Sir.", "success": True},
    ]
    # Mock speak function
    spoken = []
    mock_speak = lambda text: spoken.append(text)

    result = _concatenate_responses(test_results, mock_speak)
    print(f"  Spoken: {spoken}")
    print(f"  Result: '{result}'")

    # Test 3: Three results
    print("\n=== Three Results ===")
    test_results_3 = [
        {"command": "set volume to 50", "tool": "set_volume", "response": "Volume set to 50, Sir.", "success": True},
        {"command": "set brightness to 80", "tool": "set_brightness", "response": "Brightness set to 80, Sir.", "success": True},
        {"command": "play jazz", "tool": "spotify_play", "response": "Playing jazz, Sir.", "success": True},
    ]
    spoken.clear()
    result = _concatenate_responses(test_results_3, mock_speak)
    print(f"  Spoken: {spoken}")
    print(f"  Result: '{result}'")

    # Test 4: One failed
    print("\n=== One Failed ===")
    test_results_fail = [
        {"command": "set volume to 50", "tool": "set_volume", "response": "Volume set to 50, Sir.", "success": True},
        {"command": "unknown command", "tool": "failed", "response": "could not execute", "success": False},
    ]
    spoken.clear()
    result = _concatenate_responses(test_results_fail, mock_speak)
    print(f"  Spoken: {spoken}")
    print(f"  Result: '{result}'")
