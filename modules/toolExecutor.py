"""
JARVIS Tool Executor
================================================================
Safely executes tool calls. Handles:
    - Approval gates for destructive actions
    - Error handling and result formatting
    - Specialist model delegation (e.g., code → DeepSeek)
    - Async execution for long-running tools

Called by toolRouter.py. Never calls toolRouter.py (no circular dep).
"""
import os
import sys
import json
import threading
import traceback

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        APPROVAL_REQUIRED_ACTIONS = []


# ─────────────────────────────────────────────────────────────
# APPROVAL GATE
# ─────────────────────────────────────────────────────────────

# These are imported lazily to avoid circular imports with tts.py
_awaiting_confirmation = None
_confirmation_queue = None
_speak_fn = None


def set_confirmation_handlers(awaiting_event, confirmation_queue, speak_fn):
    """
    Called by tts.py at startup to wire in the existing approval gate system.
    This lets us reuse the approval gate infrastructure already in place.
    """
    global _awaiting_confirmation, _confirmation_queue, _speak_fn
    _awaiting_confirmation = awaiting_event
    _confirmation_queue = confirmation_queue
    _speak_fn = speak_fn


def ask_for_approval(action_type, description, speak_fn=None):
    """
    Ask user for approval for a destructive action.
    Phase 4: Uses the state machine for cancel/timeout/new-command handling.
    Returns True if approved, False otherwise.
    """
    speak = speak_fn or _speak_fn
    if speak is None:
        print(f"[Approval]: No speak function wired — denying {action_type}")
        return False

    # Check if action even requires approval
    if action_type not in getattr(config, 'APPROVAL_REQUIRED_ACTIONS', []):
        return True

    # Phase 4: Use state machine if available
    try:
        from stateMachine import state_machine, AWAITING_APPROVAL
        if state_machine.is_active():
            # State machine already active — shouldn't happen, but handle gracefully
            print(f"[Approval]: State machine already active — denying {action_type}")
            return False

        prompt = f"Sir, I need your confirmation to {description}. Say confirm to proceed, or cancel to abort."

        state_machine.enter_state(
            state=AWAITING_APPROVAL,
            prompt=prompt,
            context={"action_type": action_type, "description": description},
            timeout=60,
            speak_fn=speak,
        )

        status, text = state_machine.wait_for_response(timeout=60)

        if status == "answer":
            resp_lower = text.lower().strip()
            confirm_words = ["confirm", "yes", "yeah", "yep", "yup", "ok", "okay", "proceed", "do it", "go ahead", "sure"]
            cancel_words = ["cancel", "no", "nope", "abort", "stop", "don't", "deny"]

            if any(w in resp_lower for w in confirm_words):
                return True
            elif any(w in resp_lower for w in cancel_words):
                return False
            else:
                # Ambiguous — ask once more
                state_machine.enter_state(
                    state=AWAITING_APPROVAL,
                    prompt="I didn't catch that. Please say confirm or cancel.",
                    timeout=30,
                    speak_fn=speak,
                )
                status2, text2 = state_machine.wait_for_response(timeout=30)
                if status2 == "answer":
                    return any(w in text2.lower() for w in confirm_words)
                return False

        elif status == "cancelled":
            # State was already cleared by wait_for_response()
            return False

        elif status == "timeout":
            try:
                speak("Approval timed out, Sir.")
            except Exception:
                pass
            return False

        elif status == "new_command":
            # User started a new command during approval.
            # State was already cleared by wait_for_response().
            # The new command text is in `text` — we need to re-inject it.
            # But we can't call process_command() from here (circular import).
            # Instead, put it back in the confirmation queue — process_command()
            # will pick it up after this function returns.
            # Actually, the input was already routed through process_command()
            # which put it in _confirmation_queue. wait_for_response() read it.
            # So we just return False (not approved) and the new command needs
            # to be re-processed. We put it back in the queue.
            try:
                speak("Cancelled. ")
            except Exception:
                pass
            # Re-inject the new command into the confirmation queue
            # process_command() will route it normally since state is cleared
            if state_machine._response_queue and text:
                state_machine._response_queue.put(text)
            return False

        return False

    except ImportError:
        # State machine not available — fall back to legacy behavior
        pass

    # Legacy fallback (original code)
    if _awaiting_confirmation is None or _confirmation_queue is None:
        print(f"[Approval]: System not initialized — denying {action_type}")
        return False

    try:
        _awaiting_confirmation.set()
        speak(f"Sir, I need your confirmation to {description}. Say confirm to proceed, or cancel to abort.")
        response = _confirmation_queue.get(timeout=60)
        _awaiting_confirmation.clear()

        resp_lower = response.lower().strip()
        confirm_words = ["confirm", "yes", "yeah", "yep", "yup", "ok", "okay", "proceed", "do it", "go ahead"]
        cancel_words = ["cancel", "no", "nope", "abort", "stop", "don't"]

        if any(w in resp_lower for w in confirm_words):
            return True
        elif any(w in resp_lower for w in cancel_words):
            return False
        else:
            speak(f"I didn't catch that. Please say confirm or cancel.")
            response2 = _confirmation_queue.get(timeout=30)
            _awaiting_confirmation.clear()
            return any(w in response2.lower() for w in confirm_words)

    except Exception as e:
        print(f"[Approval]: Error during approval gate: {e}")
        if _awaiting_confirmation is not None:
            _awaiting_confirmation.clear()
        return False


# ─────────────────────────────────────────────────────────────
# TOOL EXECUTION
# ─────────────────────────────────────────────────────────────

def execute_tool_call(tool_name, arguments, speak_fn=None):
    """
    Execute a single tool call by name with given arguments.
    Returns a string result (or dict serialized to string).

    Tier 3.3: If the tool supports streaming and speak_fn is provided,
    tries streaming execution first (speaks results as they arrive).
    """
    from toolRegistry import get_tool

    tool = get_tool(tool_name)
    if tool is None:
        return f"Error: Tool '{tool_name}' not found in registry."

    # Check approval gate
    if tool["needs_approval"]:
        approved = ask_for_approval(tool_name, tool["description"][:80])
        if not approved:
            return "Action cancelled — user did not approve."

    # Tier 3.3: Try streaming execution for supported tools
    if speak_fn:
        try:
            from streamingResults import try_streaming_tool
            streaming_result = try_streaming_tool(tool_name, arguments, speak_fn)
            if streaming_result is not None:
                print(f"[ToolExecutor]: Used streaming execution for {tool_name}")
                return streaming_result
        except ImportError:
            pass
        except Exception as e:
            print(f"[ToolExecutor]: Streaming failed, falling back to normal: {e}")

    # Execute the function (normal non-streaming path)
    try:
        # arguments is a dict; some tools accept kwargs
        func = tool["function"]
        if not arguments:
            result = func()
        else:
            # Filter to only the parameters the function accepts
            result = func(**arguments)

        # Normalize result to string
        if result is None:
            return "Tool executed successfully (no output)."
        elif isinstance(result, str):
            return result
        elif isinstance(result, (dict, list)):
            # Truncate long results to avoid token bloat
            s = json.dumps(result, indent=2, default=str)
            if len(s) > 4000:
                s = s[:4000] + "\n... (truncated)"
            return s
        else:
            return str(result)

    except TypeError as e:
        # Argument mismatch — try with no args
        try:
            result = func()
            return str(result) if result else "Tool executed successfully."
        except Exception:
            return f"Argument error in '{tool_name}': {e}\nExpected: {tool['parameters']}"
    except Exception as e:
        tb = traceback.format_exc()
        return f"Error executing '{tool_name}': {e}\n{tb}"


def execute_tool_calls_parallel(tool_calls):
    """
    Execute multiple tool calls in parallel.
    tool_calls: list of (tool_name, arguments) tuples.
    Returns list of results in same order.
    """
    results = [None] * len(tool_calls)
    threads = []

    def worker(idx, name, args):
        results[idx] = execute_tool_call(name, args)

    for i, (name, args) in enumerate(tool_calls):
        t = threading.Thread(target=worker, args=(i, name, args))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=30)  # 30s timeout per tool

    return results


# ─────────────────────────────────────────────────────────────
# SPECIALIST DELEGATION
# ─────────────────────────────────────────────────────────────

def delegate_to_specialist(model_name, prompt, system_prompt=""):
    """
    Delegate a task to a specialist model (e.g., DeepSeek for code).
    Used by tools that need a different model for execution.
    """
    try:
        import requests
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {"temperature": 0.2}
            },
            timeout=120
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")
    except Exception as e:
        return f"Specialist error: {e}"


# ─────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing tool executor...")
    from toolRegistry import list_tool_names
    print(f"Available tools: {list_tool_names()}")
    print(f"\nExecuting chat_only test:")
    result = execute_tool_call("chat_only", {})
    print(f"Result: {result}")
