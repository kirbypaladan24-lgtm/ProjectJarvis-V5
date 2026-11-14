"""
JARVIS Metrics System
================================================================
Tracks latency, tool success/failure, errors, and token costs.
Logs to metrics.json for the telemetry dashboard.

This module is imported by toolRouter.py and toolExecutor.py.
"""
import os
import sys
import json
import time
import threading
from datetime import datetime, date
from collections import defaultdict, deque

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = "."

_METRICS_FILE = os.path.join(getattr(config, 'BASE_DIR', '.'), "metrics.json")
_LOCK = threading.RLock()  # Reentrant lock — allows same thread to acquire multiple times

# In-memory metrics
_metrics = {
    "latency": {
        "acknowledgment": [],
        "pattern_match": [],
        "simple_tool_1.5b": [],
        "casual_chat_1.5b": [],
        "qwen3_tool_use": [],
    },
    "tool_calls": defaultdict(lambda: {"success": 0, "failure": 0}),
    "errors": defaultdict(int),
    "tier_distribution": defaultdict(int),
    "daily_volume": defaultdict(int),
    "token_budget": {
        "calls_today": 0,
        "calls_this_hour": 0,
        "last_hour_reset": time.time(),
        "last_day_reset": time.time(),
    },
    "feedback": {
        "likely_correct": 0,
        "likely_wrong": 0,
    },
}

# Keep only last 1000 latency samples per tier
MAX_SAMPLES = 1000


def record_latency(tier, elapsed_seconds):
    """Record latency for a routing tier."""
    with _LOCK:
        if tier in _metrics["latency"]:
            _metrics["latency"][tier].append(round(elapsed_seconds, 3))
            if len(_metrics["latency"][tier]) > MAX_SAMPLES:
                _metrics["latency"][tier] = _metrics["latency"][tier][-MAX_SAMPLES:]
        _metrics["tier_distribution"][tier] += 1
        today = date.today().isoformat()
        _metrics["daily_volume"][today] += 1
        _check_budget()


def record_tool_call(tool_name, success=True):
    """Record a tool call result."""
    with _LOCK:
        if success:
            _metrics["tool_calls"][tool_name]["success"] += 1
        else:
            _metrics["tool_calls"][tool_name]["failure"] += 1
        _metrics["token_budget"]["calls_today"] += 1
        _metrics["token_budget"]["calls_this_hour"] += 1
        _check_budget()


def record_error(error_code, details=""):
    """Record an error with classification."""
    with _LOCK:
        _metrics["errors"][error_code] += 1
        if details:
            print(f"[Metrics] Error {error_code}: {details}")


def record_feedback(correct=True):
    """Record implicit feedback (user repeated command = likely wrong)."""
    with _LOCK:
        if correct:
            _metrics["feedback"]["likely_correct"] += 1
        else:
            _metrics["feedback"]["likely_wrong"] += 1


def _check_budget():
    """Check token/cost budget and alert if exceeded."""
    now = time.time()
    budget = _metrics["token_budget"]

    # Reset hourly counter
    if now - budget["last_hour_reset"] > 3600:
        budget["calls_this_hour"] = 0
        budget["last_hour_reset"] = now

    # Reset daily counter
    if now - budget["last_day_reset"] > 86400:
        budget["calls_today"] = 0
        budget["last_day_reset"] = now

    # Hard caps
    if budget["calls_this_hour"] > 200:
        record_error("BUDGET_HOUR_EXCEEDED")
    if budget["calls_today"] > 2000:
        record_error("BUDGET_DAY_EXCEEDED")

    # Soft alerts
    if budget["calls_this_hour"] == 160:  # 80%
        print("[Metrics] WARNING: 80% of hourly budget used (160/200 calls)")
    if budget["calls_today"] == 1600:
        print("[Metrics] WARNING: 80% of daily budget used (1600/2000 calls)")


def get_latency_stats():
    """Get latency percentiles per tier."""
    with _LOCK:
        stats = {}
        for tier, samples in _metrics["latency"].items():
            if not samples:
                stats[tier] = {"p50": 0, "p90": 0, "p99": 0, "count": 0, "avg": 0}
                continue
            sorted_s = sorted(samples)
            n = len(sorted_s)
            stats[tier] = {
                "p50": sorted_s[n // 2],
                "p90": sorted_s[int(n * 0.9)],
                "p99": sorted_s[int(n * 0.99)],
                "avg": round(sum(sorted_s) / n, 3),
                "count": n,
            }
        return stats


def get_tool_stats():
    """Get tool success/failure rates."""
    with _LOCK:
        result = {}
        for tool, counts in _metrics["tool_calls"].items():
            total = counts["success"] + counts["failure"]
            rate = round(counts["success"] / total * 100, 1) if total > 0 else 0
            result[tool] = {
                "success": counts["success"],
                "failure": counts["failure"],
                "total": total,
                "success_rate": rate,
            }
        return result


def get_all_metrics():
    """Get all metrics for dashboard."""
    with _LOCK:
        return {
            "latency": get_latency_stats(),
            "tool_calls": get_tool_stats(),
            "errors": dict(_metrics["errors"]),
            "tier_distribution": dict(_metrics["tier_distribution"]),
            "daily_volume": dict(_metrics["daily_volume"]),
            "token_budget": dict(_metrics["token_budget"]),
            "feedback": dict(_metrics["feedback"]),
            "timestamp": datetime.now().isoformat(),
        }


def save_to_disk():
    """Save metrics to JSON file for dashboard."""
    try:
        data = get_all_metrics()
        with open(_METRICS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Metrics] Save failed: {e}")


def load_from_disk():
    """Load metrics from disk at startup."""
    global _metrics
    try:
        if os.path.exists(_METRICS_FILE):
            with open(_METRICS_FILE, 'r') as f:
                saved = json.load(f)
                # Restore tool_calls as defaultdict
                if "tool_calls" in saved:
                    _metrics["tool_calls"] = defaultdict(lambda: {"success": 0, "failure": 0}, saved["tool_calls"])
                if "errors" in saved:
                    _metrics["errors"] = defaultdict(int, saved["errors"])
                if "tier_distribution" in saved:
                    _metrics["tier_distribution"] = defaultdict(int, saved["tier_distribution"])
                if "daily_volume" in saved:
                    _metrics["daily_volume"] = defaultdict(int, saved["daily_volume"])
                if "feedback" in saved:
                    _metrics["feedback"] = saved["feedback"]
            print(f"[Metrics]: Loaded from disk.")
    except Exception as e:
        print(f"[Metrics]: Load failed: {e}")


# Auto-save thread
_save_thread = None
_save_running = False


def start_auto_save(interval=60):
    """Start background thread to save metrics every N seconds."""
    global _save_thread, _save_running
    if _save_running:
        return
    _save_running = True

    def _saver():
        while _save_running:
            time.sleep(interval)
            save_to_disk()

    _save_thread = threading.Thread(target=_saver, daemon=True, name="metrics-saver")
    _save_thread.start()
    print("[Metrics]: Auto-save started (60s interval).")


def stop_auto_save():
    """Stop the auto-save thread."""
    global _save_running
    _save_running = False
    save_to_disk()


# Load on import
load_from_disk()
