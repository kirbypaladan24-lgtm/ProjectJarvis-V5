"""
JARVIS A/B Testing Framework
================================================================
Routes a percentage of commands to different routing strategies
and compares real user experience.

Usage:
    from ab_testing import ABTest

    # In config.py:
    # AB_TEST_CONFIG = {
    #     "routing_v2": {"control": 50, "treatment": 50},
    # }

    # In toolRouter.py:
    ab = ABTest("routing_v2")
    if ab.is_treatment():
        result = new_routing_path(user_input)
    else:
        result = old_routing_path(user_input)
    ab.log_result(user_input, result, user_satisfied=True)
"""
import os
import sys
import json
import random
import hashlib
import threading
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = "."


# ═════════════════════════════════════════════════════════════
# STATE
# ═════════════════════════════════════════════════════════════

_results_file = os.path.join(getattr(config, 'BASE_DIR', '.'), "ab_test_results.json")
_lock = threading.Lock()


# ═════════════════════════════════════════════════════════════
# A/B TEST CLASS
# ═════════════════════════════════════════════════════════════

class ABTest:
    """
    A/B test for routing strategies.
    Uses a hash of the user input to deterministically assign
    to control or treatment (same input always gets same group).
    """

    def __init__(self, test_name, control_pct=50):
        """
        Args:
            test_name: Name of the test (e.g., "routing_v2")
            control_pct: Percentage of commands that go to control (0-100)
        """
        self.test_name = test_name
        self.control_pct = control_pct

    def _hash_input(self, user_input):
        """Hash the input to a 0-100 number for deterministic assignment."""
        h = hashlib.md5(user_input.encode()).hexdigest()
        return int(h[:8], 16) % 100

    def is_treatment(self, user_input):
        """
        Check if this input should go to the treatment group.
        Uses deterministic hashing so same input always gets same group.
        """
        bucket = self._hash_input(user_input)
        return bucket >= self.control_pct

    def is_control(self, user_input):
        """Check if this input should go to the control group."""
        return not self.is_treatment(user_input)

    def log_result(self, user_input, result, user_satisfied=None):
        """
        Log the result of an A/B test command.

        Args:
            user_input: The user's input
            result: The routing result dict
            user_satisfied: True if user was satisfied, False if not, None if unknown
        """
        group = "treatment" if self.is_treatment(user_input) else "control"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "test_name": self.test_name,
            "group": group,
            "input": user_input[:200],
            "tool": result.get("tools_used", ["chat_only"])[0] if result.get("tools_used") else "chat_only",
            "tier": result.get("fast_path", "qwen3_tool_use"),
            "elapsed": result.get("elapsed", 0),
            "success": result.get("success", False),
            "satisfied": user_satisfied,
        }

        with _lock:
            try:
                results = []
                if os.path.exists(_results_file):
                    with open(_results_file, 'r') as f:
                        results = json.load(f)
                results.append(entry)
                # Keep last 1000
                if len(results) > 1000:
                    results = results[-1000:]
                with open(_results_file, 'w') as f:
                    json.dump(results, f, indent=2)
            except Exception as e:
                print(f"[ABTest]: Log error: {e}")


# ═════════════════════════════════════════════════════════════
# ANALYSIS
# ═════════════════════════════════════════════════════════════

def get_test_results(test_name=None):
    """
    Get A/B test results, optionally filtered by test name.
    Returns summary statistics.
    """
    with _lock:
        try:
            if not os.path.exists(_results_file):
                return {"total": 0, "control": {}, "treatment": {}}

            with open(_results_file, 'r') as f:
                results = json.load(f)

            if test_name:
                results = [r for r in results if r.get("test_name") == test_name]

        except Exception as e:
            print(f"[ABTest]: Load error: {e}")
            return {"total": 0, "control": {}, "treatment": {}}

    # Split by group
    control = [r for r in results if r.get("group") == "control"]
    treatment = [r for r in results if r.get("group") == "treatment"]

    def _stats(group):
        if not group:
            return {"count": 0}
        total = len(group)
        satisfied = [r for r in group if r.get("satisfied") is True]
        unsatisfied = [r for r in group if r.get("satisfied") is False]
        avg_elapsed = sum(r.get("elapsed", 0) for r in group) / total if total > 0 else 0
        success_rate = sum(1 for r in group if r.get("success")) / total * 100 if total > 0 else 0

        return {
            "count": total,
            "satisfied": len(satisfied),
            "unsatisfied": len(unsatisfied),
            "satisfaction_rate": round(len(satisfied) / max(len(satisfied) + len(unsatisfied), 1) * 100, 1),
            "avg_elapsed": round(avg_elapsed, 3),
            "success_rate": round(success_rate, 1),
        }

    return {
        "total": len(results),
        "control": _stats(control),
        "treatment": _stats(treatment),
    }


def clear_results():
    """Clear all A/B test results."""
    with _lock:
        try:
            if os.path.exists(_results_file):
                os.remove(_results_file)
        except Exception as e:
            print(f"[ABTest]: Clear error: {e}")


# ═════════════════════════════════════════════════════════════
# TEST
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing A/B Testing Framework...\n")

    # Clear previous results
    clear_results()

    # Create test
    ab = ABTest("routing_test", control_pct=50)

    # Test deterministic assignment
    test_inputs = ["hello", "set volume to 50", "play Drake", "take screenshot", "what's the weather"]

    print("Assignment test:")
    for inp in test_inputs:
        is_treat = ab.is_treatment(inp)
        print(f"  '{inp}' → {'treatment' if is_treat else 'control'}")

    # Verify determinism
    for inp in test_inputs:
        assert ab.is_treatment(inp) == ab.is_treatment(inp), f"Non-deterministic for '{inp}'"
    print("  ✅ Deterministic assignment verified")

    # Log some results
    print("\nLogging results...")
    for inp in test_inputs:
        group = "treatment" if ab.is_treatment(inp) else "control"
        result = {
            "tools_used": ["chat_only"],
            "fast_path": "pattern_match" if "volume" in inp else "casual_chat_1.5b",
            "elapsed": 0.5 if group == "control" else 1.2,
            "success": True,
        }
        satisfied = "volume" in inp  # Simulate: control does better on volume
        ab.log_result(inp, result, user_satisfied=satisfied)

    # Get results
    print("\nGetting results...")
    stats = get_test_results("routing_test")
    print(f"  Total: {stats['total']}")
    print(f"  Control: {stats['control']}")
    print(f"  Treatment: {stats['treatment']}")

    assert stats["total"] == len(test_inputs)
    assert stats["control"]["count"] + stats["treatment"]["count"] == stats["total"]

    print("\nAll A/B tests passed ✅")

    # Cleanup
    clear_results()
