"""
JARVIS Evaluation Harness
================================================================
50 test queries with expected tool selections.
Run before/after changes to measure routing accuracy.

Usage:
    py -m modules.eval_harness           # Run all tests
    py -m modules.eval_harness --quick   # Run quick subset (10 tests)
"""
import os
import sys
import time
import json

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
_MODULES_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)


# ═════════════════════════════════════════════════════════════
# TEST CASES
# ═════════════════════════════════════════════════════════════
# Each test: (input, expected_tool, expected_tier, description)
# expected_tier: "acknowledgment" | "pattern_match" | "simple_tool_1.5b" | "casual_chat_1.5b" | "qwen3_tool_use"

TESTS = [
    # ── Acknowledgments (Tier 0) ──────────────────────────────
    ("hello", "chat_only", "acknowledgment", "Basic greeting"),
    ("thanks", "chat_only", "acknowledgment", "Thanks acknowledgment"),
    ("ok", "chat_only", "acknowledgment", "OK acknowledgment"),
    ("bye", "chat_only", "acknowledgment", "Farewell"),
    ("thanks jarvis", "chat_only", "acknowledgment", "Thanks with name"),

    # ── Pattern Matching (Tier 1) ─────────────────────────────
    ("set volume to 50", "set_volume", "pattern_match", "Volume set exact"),
    ("set volume to 75 percent", "set_volume", "pattern_match", "Volume with percent"),
    ("mute", "set_volume", "pattern_match", "Mute command"),
    ("set brightness to 80", "set_brightness", "pattern_match", "Brightness set"),
    ("open chrome", "open_app", "pattern_match", "Open app"),
    ("launch spotify", "open_app", "pattern_match", "Launch app"),
    ("play Blinding Lights", "spotify_play", "pattern_match", "Play song"),
    ("play some Drake", "spotify_play", "pattern_match", "Play artist with 'some'"),
    ("pause", "spotify_pause", "pattern_match", "Pause music"),
    ("next song", "spotify_next", "pattern_match", "Next track"),
    ("take a screenshot", "take_screenshot", "pattern_match", "Screenshot"),
    ("set timer for 10 minutes", "set_timer", "pattern_match", "Timer 10 min"),
    ("set timer for 5 minutes called laundry", "set_timer", "pattern_match", "Timer with label"),
    ("note that I need milk", "save_note", "pattern_match", "Save note"),
    ("show my tasks", "list_tasks", "pattern_match", "List tasks"),
    ("list notes", "list_notes", "pattern_match", "List notes"),
    ("system status", "get_system_stats", "pattern_match", "System status"),
    ("what's running", "list_running_apps", "pattern_match", "What's running"),

    # ── 1.5B Simple Dispatch (Tier 2) ─────────────────────────
    ("what's the weather in Tokyo", "get_weather", "simple_tool_1.5b", "Weather with location"),
    ("find my resume", "search_files", "simple_tool_1.5b", "Search for file"),
    ("create a task to call mom tomorrow", "create_task", "simple_tool_1.5b", "Create task with date"),
    ("what's the exchange rate", "get_exchange_rate", "simple_tool_1.5b", "Exchange rate"),
    ("tell me about Elon Musk", "wikipedia_summary", "simple_tool_1.5b", "Wikipedia lookup"),
    ("kill chrome", "kill_process", "simple_tool_1.5b", "Kill process"),

    # ── Casual Chat (Tier 3) ──────────────────────────────────
    ("explain quantum computing", "chat_only", "casual_chat_1.5b", "Knowledge question"),
    ("what's your favorite color", "chat_only", "casual_chat_1.5b", "Personal question"),
    ("what do you think about AI", "chat_only", "casual_chat_1.5b", "Opinion question"),
    ("what's 2 plus 2", "chat_only", "casual_chat_1.5b", "Simple math"),

    # ── Qwen 3 Complex (Tier 4) ───────────────────────────────
    ("read my notes about Python and check if outdated", None, "qwen3_tool_use", "Multi-step: notes + web"),
    ("set volume to 30 and play relaxing jazz", None, "qwen3_tool_use", "Multi-step: volume + spotify"),
    ("find my resume and read it", None, "qwen3_tool_use", "Multi-step: search + read"),

    # ── Edge Cases ────────────────────────────────────────────
    ("is it cold or hot", "chat_only", "casual_chat_1.5b", "Follow-up question"),
    ("is that good", "chat_only", "casual_chat_1.5b", "Judgment question"),
    ("what about Tokyo", "chat_only", "casual_chat_1.5b", "Ambiguous follow-up"),
    ("open it", None, None, "Pronoun resolution (needs context)"),
    ("asdfgh jkl", None, None, "Gibberish input"),

    # ── Disambiguation ────────────────────────────────────────
    ("search Python", None, None, "Ambiguous: web vs file vs semantic"),

    # ── Tagalog ───────────────────────────────────────────────
    ("buksan ang spotify", "open_app", None, "Tagalog: open spotify"),
    ("i-play ang kanta", "spotify_play", None, "Tagalog: play song"),

    # ── System ────────────────────────────────────────────────
    ("shutdown the laptop", "shutdown_system", None, "Shutdown (needs approval)"),
    ("go to sleep", "sleep_system", None, "Sleep mode"),
    ("run diagnostics", "run_diagnostics", None, "Full diagnostics"),
    ("go private", "enable_privacy_mode", None, "Privacy mode"),
    ("what are my specs", "get_laptop_specs", None, "Hardware specs"),
    ("organize my downloads", "organize_downloads", None, "Organize downloads"),
]


def run_tests(quick=False):
    """Run all evaluation tests."""
    from toolRouter import route_with_tools

    tests = TESTS[:10] if quick else TESTS

    results = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }

    print(f"\n{'=' * 60}")
    print(f"  JARVIS Evaluation Harness — {len(tests)} tests")
    print(f"{'=' * 60}\n")

    for i, (user_input, expected_tool, expected_tier, desc) in enumerate(tests, 1):
        print(f"Test {i}/{len(tests)}: {desc}")
        print(f"  Input: \"{user_input}\"")
        print(f"  Expected: tool={expected_tool}, tier={expected_tier}")

        try:
            start = time.time()
            result = route_with_tools(user_input, history=[])
            elapsed = time.time() - start

            actual_tool = result.get("tools_used", ["chat_only"])[0] if result.get("tools_used") else "chat_only"
            actual_tier = result.get("fast_path", "qwen3_tool_use")
            response = result.get("response", "")[:100]

            print(f"  Actual: tool={actual_tool}, tier={actual_tier} ({elapsed:.2f}s)")
            print(f"  Response: \"{response}...\"")

            # Check
            passed = True
            if expected_tool and actual_tool != expected_tool:
                passed = False
                print(f"  ❌ FAIL: Expected tool '{expected_tool}', got '{actual_tool}'")
            if expected_tier and actual_tier != expected_tier:
                passed = False
                print(f"  ❌ FAIL: Expected tier '{expected_tier}', got '{actual_tier}'")

            if passed:
                results["passed"] += 1
                print(f"  ✅ PASS")
            else:
                results["failed"] += 1

            results["details"].append({
                "test": desc,
                "input": user_input,
                "expected_tool": expected_tool,
                "actual_tool": actual_tool,
                "expected_tier": expected_tier,
                "actual_tier": actual_tier,
                "passed": passed,
                "elapsed": round(elapsed, 3),
            })

        except Exception as e:
            results["skipped"] += 1
            print(f"  ⚠️ SKIP: {e}")
            results["details"].append({
                "test": desc,
                "input": user_input,
                "error": str(e),
                "passed": False,
            })

        print()
        time.sleep(0.5)  # Don't overwhelm Ollama

    # Summary
    total = len(tests)
    pass_rate = round(results["passed"] / total * 100, 1) if total > 0 else 0

    print(f"{'=' * 60}")
    print(f"  RESULTS: {results['passed']}/{total} passed ({pass_rate}%)")
    print(f"  Failed: {results['failed']}, Skipped: {results['skipped']}")
    print(f"{'=' * 60}\n")

    # Save results
    results_file = os.path.join(_PARENT_DIR, "eval_results.json")
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {results_file}")

    return results


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    run_tests(quick=quick)
