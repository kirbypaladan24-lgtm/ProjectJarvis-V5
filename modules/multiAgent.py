"""
multiAgent.py — Multi-Agent Task Orchestration for JARVIS
───────────────────────────────────────────────────────────
Uses a three-role pipeline for complex tasks that a single model call can't handle well:

  phi3:mini         → PLANNER   — Decomposes the task into 2–4 concrete subtasks.
                                   Fast, cheap, laser-focused. Runs first, under 5 seconds.

  deepseek-coder    → CODE WORKER — Handles any code-related subtask in parallel.
  qwen2.5:7b        → RESEARCH WORKER — Handles research/writing subtasks in parallel.
  phi3:mini         → VALIDATOR — Quick yes/no sanity check on each worker output.
  qwen2.5:7b        → SYNTHESIZER — Merges all validated worker results into one response.

Why phi3:mini for planning AND validation?
  - Planning: It's fast (< 3s) and excellent at structured decomposition tasks.
              It doesn't need deep knowledge — just needs to break a problem down.
  - Validation: Binary check ("is this output relevant and non-empty?") is exactly
                what a small, cheap model excels at without burning qwen2.5 tokens.

This keeps the two large models (qwen + deepseek) focused only on
actual content generation, where their size matters.
"""

import os
import sys
import re
import json
import time
import queue
import threading
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        AGENT_PLANNER_MODEL     = "qwen3:4b"
        AGENT_WORKER_MODEL      = "qwen3:8b"
        AGENT_CODE_MODEL        = "deepseek-coder:6.7b"
        AGENT_SYNTHESIZER_MODEL = "qwen3:8b"
        AGENT_MAX_WORKERS       = 3
        AGENT_WORKER_TIMEOUT    = 120
        AGENT_COMPLEX_TRIGGERS  = ["research and write", "deep dive", "comprehensive",
                                    "full report", "analyze and summarize"]
        OLLAMA_BASE_URL         = "http://localhost:11434"

# ── Ollama helper ──────────────────────────────────────────────────────────────
def _ask_model(model: str, prompt: str, system: str = "", timeout: int = 60) -> str:
    """Single non-streaming Ollama call. Returns response text."""
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if system:
            payload["system"] = system
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=timeout
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "").strip()
        return f"[Model error: status {r.status_code}]"
    except requests.exceptions.Timeout:
        return "[Worker timed out]"
    except Exception as e:
        return f"[Model error: {e}]"


# ── Step 1: PLANNER (phi3:mini) ────────────────────────────────────────────────
def plan_task(user_request: str) -> list[dict]:
    """
    phi3:mini decomposes the user request into 2–4 concrete subtasks.
    Returns a list of subtask dicts: [{id, description, type}]
    type is one of: "research", "code", "writing", "analysis"
    """
    planner_system = """You are a task decomposition specialist.
Break the user's request into 2 to 4 concrete, independent subtasks.
Each subtask must be self-contained — a worker can complete it without seeing the others.

Classify each subtask type:
- research: finding facts, data, explanations
- code: writing, analyzing, or debugging code
- writing: drafting text, summaries, documents
- analysis: comparing, evaluating, reasoning about data

Reply ONLY with a JSON array. No explanation. Example:
[
  {"id": 1, "description": "Find the top 3 Python web frameworks and their pros/cons", "type": "research"},
  {"id": 2, "description": "Write a comparison table of Flask, Django, and FastAPI", "type": "writing"}
]"""

    print(f"[Planner (phi3:mini)]: Decomposing task...")
    raw = _ask_model(
        config.AGENT_PLANNER_MODEL,
        user_request,
        system=planner_system,
        timeout=20
    )

    # Extract JSON from response — phi3 sometimes adds explanation text
    json_match = re.search(r'\[[\s\S]+\]', raw)
    if not json_match:
        # Fallback: treat the whole request as a single task
        print("[Planner]: Could not parse plan — treating as single task.")
        return [{"id": 1, "description": user_request, "type": "research"}]

    try:
        tasks = json.loads(json_match.group(0))
        # Cap at max workers
        tasks = tasks[:config.AGENT_MAX_WORKERS]
        print(f"[Planner]: {len(tasks)} subtasks created:")
        for t in tasks:
            print(f"  [{t.get('type','?').upper()}] {t.get('description','')}")
        return tasks
    except json.JSONDecodeError:
        print("[Planner]: JSON parse failed — single task fallback.")
        return [{"id": 1, "description": user_request, "type": "research"}]


# ── Step 2: WORKER (parallel) ─────────────────────────────────────────────────
def _worker_fn(subtask: dict, result_queue: queue.Queue, context: str = ""):
    """
    Executes a single subtask using the appropriate model.
    Puts {id, description, type, output} into result_queue when done.
    """
    task_type   = subtask.get("type", "research")
    description = subtask.get("description", "")
    task_id     = subtask.get("id", 0)

    # Route to the right model based on task type
    if task_type == "code":
        model = config.AGENT_CODE_MODEL
        system = ("You are a world-class software engineer. "
                  "Answer concisely and include working code where appropriate.")
    else:
        model = config.AGENT_WORKER_MODEL
        system = ("You are a highly knowledgeable research and writing assistant. "
                  "Provide accurate, well-structured, factual responses.")

    if context:
        prompt = f"Context: {context}\n\nTask: {description}"
    else:
        prompt = description

    print(f"[Worker {task_id} ({model.split(':')[0]})]: Starting — {description[:60]}...")
    start = time.time()
    output = _ask_model(model, prompt, system=system, timeout=config.AGENT_WORKER_TIMEOUT)
    elapsed = round(time.time() - start, 1)
    print(f"[Worker {task_id}]: Done in {elapsed}s — {len(output)} chars")

    result_queue.put({
        "id":          task_id,
        "description": description,
        "type":        task_type,
        "output":      output,
        "elapsed":     elapsed
    })


def run_workers_parallel(subtasks: list[dict], context: str = "") -> list[dict]:
    """
    Spawn one thread per subtask, all running simultaneously.
    Returns list of results in order of completion.
    """
    result_queue = queue.Queue()
    threads = []

    for subtask in subtasks:
        t = threading.Thread(
            target=_worker_fn,
            args=(subtask, result_queue, context),
            daemon=True,
            name=f"agent-worker-{subtask.get('id', 0)}"
        )
        threads.append(t)
        t.start()

    # Wait for all workers (with a generous deadline)
    deadline = time.time() + config.AGENT_WORKER_TIMEOUT + 10
    for t in threads:
        remaining = max(0, deadline - time.time())
        t.join(timeout=remaining)

    results = []
    while not result_queue.empty():
        results.append(result_queue.get_nowait())

    completed_ids = {result.get("id") for result in results}
    for subtask in subtasks:
        subtask_id = subtask.get("id", 0)
        if subtask_id not in completed_ids:
            results.append({
                "id":          subtask_id,
                "description": subtask.get("description", ""),
                "type":        subtask.get("type", "research"),
                "model":       config.AGENT_CODE_MODEL if subtask.get("type") == "code" else config.AGENT_WORKER_MODEL,
                "output":      f"[Worker timed out after {config.AGENT_WORKER_TIMEOUT} seconds]",
                "elapsed":     config.AGENT_WORKER_TIMEOUT
            })

    # Sort results back into subtask order
    results.sort(key=lambda x: x["id"])
    return results


# ── Step 3: VALIDATOR (phi3:mini) ─────────────────────────────────────────────
def validate_outputs(results: list[dict]) -> list[dict]:
    """
    phi3:mini does a quick quality check on each worker output.
    Filters out empty, hallucinated, or completely off-topic responses.
    Fast — phi3 just answers YES/NO per result.
    """
    valid = []
    for result in results:
        if not result.get("output") or len(result["output"].strip()) < 20:
            print(f"[Validator (phi3:mini)]: Worker {result['id']} — SKIP (empty)")
            continue

        prompt = (f"Task: {result['description']}\n\n"
                  f"Output (first 300 chars): {result['output'][:300]}\n\n"
                  f"Is this output relevant and useful for the task? Reply only YES or NO.")

        verdict = _ask_model(config.AGENT_PLANNER_MODEL, prompt, timeout=10)
        if "no" in verdict.lower() and "yes" not in verdict.lower():
            print(f"[Validator (phi3:mini)]: Worker {result['id']} — REJECT")
        else:
            print(f"[Validator (phi3:mini)]: Worker {result['id']} — PASS")
            valid.append(result)

    return valid if valid else results   # If all fail validation, keep all (graceful)


# ── Step 4: SYNTHESIZER (qwen2.5) ─────────────────────────────────────────────
def synthesize_results(original_request: str, validated_results: list[dict]) -> str:
    """
    qwen2.5 merges all validated worker outputs into a single coherent response.
    """
    if not validated_results:
        return "I was unable to gather sufficient information to answer this, Sir."

    # Build a structured prompt with all worker outputs
    parts = []
    for r in validated_results:
        parts.append(f"[Subtask {r['id']}: {r['description']}]\n{r['output']}")

    combined = "\n\n---\n\n".join(parts)

    synth_system = """You are JARVIS, a highly intelligent personal AI assistant.
You have been given the results of multiple parallel research and analysis tasks.
Your job is to synthesize them into a single, coherent, well-structured response.
- Eliminate redundancy
- Preserve all important facts, code, and specifics
- Use a professional but natural spoken tone
- Always address the user as Sir
- Do NOT mention that multiple agents or subtasks were used"""

    prompt = (f"Original request: {original_request}\n\n"
              f"Research results:\n{combined}\n\n"
              f"Synthesize the above into a complete, polished response.")

    print(f"[Synthesizer (qwen2.5)]: Merging {len(validated_results)} results...")
    start = time.time()
    result = _ask_model(
        config.AGENT_SYNTHESIZER_MODEL,
        prompt,
        system=synth_system,
        timeout=90
    )
    print(f"[Synthesizer]: Done in {round(time.time()-start, 1)}s")
    return result


# ── Full pipeline ─────────────────────────────────────────────────────────────
def run_multi_agent(user_request: str, context: str = "",
                    progress_fn=None) -> str:
    """
    Full pipeline: Plan → Workers (parallel) → Validate → Synthesize.

    progress_fn: optional callable(str) for real-time status updates (e.g. speak_async)
    Returns the final synthesized response string.
    """
    start_time = time.time()

    def _progress(msg: str):
        print(f"[MultiAgent]: {msg}")
        if progress_fn:
            progress_fn(msg)

    _progress("Analyzing your request and breaking it down into subtasks...")

    # Step 1: Plan
    subtasks = plan_task(user_request)

    if len(subtasks) == 1:
        _progress("This looks like a straightforward task. Routing directly...")
    else:
        _progress(f"Spawning {len(subtasks)} parallel research agents...")

    # Step 2: Workers in parallel
    results = run_workers_parallel(subtasks, context=context)

    if not results:
        return "I was unable to complete this task — all agents timed out, Sir."

    # Step 3: Validate with phi3:mini
    _progress("Validating agent outputs...")
    validated = validate_outputs(results)

    # Step 4: Synthesize
    _progress("Synthesizing final response...")
    final = synthesize_results(user_request, validated)

    elapsed = round(time.time() - start_time, 1)
    print(f"[MultiAgent]: Complete in {elapsed}s total ({len(validated)} valid results)")

    return final


# ── Trigger detection ─────────────────────────────────────────────────────────
def is_complex_task(user_input: str) -> bool:
    """
    Heuristic check: should this request go to multi-agent instead of single model?
    Uses keyword triggers from config + complexity signals.
    """
    text = user_input.lower()

    # Explicit multi-step language
    if any(t in text for t in config.AGENT_COMPLEX_TRIGGERS):
        return True

    # Long, multi-clause requests (> 20 words with conjunctions)
    words = text.split()
    if len(words) > 20 and any(w in text for w in ["and then", "also", "additionally",
                                                     "as well as", "furthermore",
                                                     "plus", "along with"]):
        return True

    # Explicit scope words
    if any(p in text for p in ["everything about", "all aspects of",
                                "in depth", "thoroughly", "exhaustively"]):
        return True

    return False


# ── Command router ─────────────────────────────────────────────────────────────
def handle_agent_commands(user_input: str, speak_fn=None) -> str | None:
    """
    Direct trigger: user explicitly asks for multi-agent mode.
    Auto-trigger: is_complex_task() returns True (called from process_command).
    """
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # Explicit invocation
    if any(p in text for p in ["multi agent", "multi-agent", "use multiple agents",
                                "spawn agents", "deep research", "full analysis"]):
        return run_multi_agent(user_input, progress_fn=speak_fn)

    return None
