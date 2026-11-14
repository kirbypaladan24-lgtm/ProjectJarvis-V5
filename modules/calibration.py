"""
JARVIS Calibration Module (Phase 6)
================================================================
Analyzes all JSONL log files produced by Phases 1-5 and generates
a calibration report with actionable recommendations.

Log files analyzed:
    - validation_log.jsonl      (Phase 1 — validation gate decisions)
    - fuzzy_match_log.jsonl     (Phase 1 — 1.5B tool name hallucinations)
    - normalization_log.jsonl   (Phase 2 — multi-command splits, incomplete detection)
    - state_machine_log.jsonl   (Phase 4 — state transitions, cancels, timeouts)
    - multi_command_log.jsonl   (Phase 5 — multi-command executions)

For each log, computes statistics and identifies:
    - Tools with low pass rates (need higher thresholds or removal from 1.5B)
    - Tools with high fuzzy match rates (need pattern matchers)
    - Common arg issues (need contract updates)
    - Normalization split accuracy
    - State machine cancel/timeout rates
    - Multi-command synthesis success rate

Outputs a human-readable report + machine-readable JSON.
Can also auto-apply threshold adjustments via per_tool_thresholds.py.
"""
import os
import sys
import json
from collections import defaultdict, Counter
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
# LOG FILE PATHS
# ═══════════════════════════════════════════════════════════════════════

_BASE = getattr(config, 'BASE_DIR', _PARENT_DIR)

LOG_FILES = {
    "validation":     os.path.join(_BASE, "validation_log.jsonl"),
    "fuzzy_match":    os.path.join(_BASE, "fuzzy_match_log.jsonl"),
    "normalization":  os.path.join(_BASE, "normalization_log.jsonl"),
    "state_machine":  os.path.join(_BASE, "state_machine_log.jsonl"),
    "multi_command":  os.path.join(_BASE, "multi_command_log.jsonl"),
}


# ═══════════════════════════════════════════════════════════════════════
# JSONL READER
# ═══════════════════════════════════════════════════════════════════════

def _read_jsonl(file_path):
    """Read a JSONL file and return a list of dicts. Returns [] if file doesn't exist."""
    if not os.path.exists(file_path):
        return []
    entries = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[Calibration]: Error reading {file_path}: {e}")
    return entries


# ═══════════════════════════════════════════════════════════════════════
# ANALYZERS
# ═══════════════════════════════════════════════════════════════════════

def analyze_validation_log():
    """
    Analyze validation_log.jsonl (Phase 1).
    Computes per-tool: total picks, pass/borderline/fail counts, avg similarity.
    """
    entries = _read_jsonl(LOG_FILES["validation"])
    if not entries:
        return {"total_entries": 0, "tools": {}, "note": "No validation log found."}

    tool_stats = defaultdict(lambda: {
        "total": 0,
        "pass": 0,
        "borderline_pass": 0,
        "fail": 0,
        "similarity_scores": [],
        "arg_issues": [],
    })

    overall_stats = {
        "total_entries": len(entries),
        "pass_rate": 0,
        "fail_rate": 0,
    }

    pass_count = 0
    fail_count = 0

    for entry in entries:
        tool = entry.get("tool_picked", "unknown")
        result = entry.get("result", "unknown")
        details = entry.get("details", {})
        checks = details.get("checks", {})
        sim_info = checks.get("similarity", {})
        sim_score = sim_info.get("score", 0)

        tool_stats[tool]["total"] += 1
        tool_stats[tool]["similarity_scores"].append(sim_score)

        if result == "pass":
            tool_stats[tool]["pass"] += 1
            pass_count += 1
        elif result == "borderline_pass":
            tool_stats[tool]["borderline_pass"] += 1
            pass_count += 1
        elif result == "fail":
            tool_stats[tool]["fail"] += 1
            fail_count += 1

        # Collect arg issues
        arg_info = checks.get("arg_sanity", {})
        issues = arg_info.get("issues", [])
        if issues:
            tool_stats[tool]["arg_issues"].extend(issues)

    # Compute averages
    for tool, stats in tool_stats.items():
        scores = stats["similarity_scores"]
        stats["avg_similarity"] = round(sum(scores) / len(scores), 3) if scores else 0
        stats["pass_rate"] = round((stats["pass"] + stats["borderline_pass"]) / stats["total"], 3) if stats["total"] else 0
        stats["fail_rate"] = round(stats["fail"] / stats["total"], 3) if stats["total"] else 0
        # Keep only top 3 most common arg issues
        if stats["arg_issues"]:
            issue_counts = Counter(stats["arg_issues"])
            stats["common_arg_issues"] = issue_counts.most_common(3)
        del stats["arg_issues"]  # Remove raw list (too verbose)
        del stats["similarity_scores"]  # Already averaged

    overall_stats["pass_rate"] = round(pass_count / len(entries), 3) if entries else 0
    overall_stats["fail_rate"] = round(fail_count / len(entries), 3) if entries else 0

    return {
        "overall": overall_stats,
        "tools": dict(tool_stats),
    }


def analyze_fuzzy_match_log():
    """
    Analyze fuzzy_match_log.jsonl (Phase 1).
    Identifies which tools the 1.5B most often hallucinates.
    """
    entries = _read_jsonl(LOG_FILES["fuzzy_match"])
    if not entries:
        return {"total_entries": 0, "hallucinations": {}, "note": "No fuzzy match log found."}

    hallucination_stats = defaultdict(lambda: {
        "count": 0,
        "matched_to": Counter(),
    })

    for entry in entries:
        hallucinated = entry.get("hallucinated", "unknown")
        matched_to = entry.get("matched_to", "unknown")

        hallucination_stats[hallucinated]["count"] += 1
        hallucination_stats[hallucinated]["matched_to"][matched_to] += 1

    # Convert Counter to dict for JSON serialization
    for h, stats in hallucination_stats.items():
        stats["matched_to"] = dict(stats["matched_to"])

    # Sort by count (most hallucinated first)
    sorted_hallucinations = sorted(
        hallucination_stats.items(),
        key=lambda x: x[1]["count"],
        reverse=True
    )

    return {
        "total_entries": len(entries),
        "hallucinations": dict(sorted_hallucinations),
    }


def analyze_normalization_log():
    """
    Analyze normalization_log.jsonl (Phase 2).
    Computes multi-command split rate, incomplete detection rate, etc.
    """
    entries = _read_jsonl(LOG_FILES["normalization"])
    if not entries:
        return {"total_entries": 0, "actions": {}, "note": "No normalization log found."}

    action_counts = Counter()
    split_examples = []
    incomplete_examples = []

    for entry in entries:
        action = entry.get("action", "unknown")
        action_counts[action] += 1

        details = entry.get("details", {})
        if action == "split_success" and len(split_examples) < 5:
            split_examples.append({
                "input": details.get("input", "")[:100],
                "commands": details.get("commands", []),
            })
        elif action == "incomplete_detected" and len(incomplete_examples) < 5:
            incomplete_examples.append({
                "input": details.get("input", "")[:100],
                "clarification": details.get("clarification", ""),
            })

    return {
        "total_entries": len(entries),
        "actions": dict(action_counts),
        "split_examples": split_examples,
        "incomplete_examples": incomplete_examples,
    }


def analyze_state_machine_log():
    """
    Analyze state_machine_log.jsonl (Phase 4).
    Computes state entry counts, cancel rate, timeout rate, new-command rate.
    """
    entries = _read_jsonl(LOG_FILES["state_machine"])
    if not entries:
        return {"total_entries": 0, "actions": {}, "note": "No state machine log found."}

    action_counts = Counter()
    state_entries = Counter()

    for entry in entries:
        action = entry.get("action", "unknown")
        action_counts[action] += 1

        details = entry.get("details", {})
        if action == "enter_state":
            state = details.get("state", "unknown")
            state_entries[state] += 1

    return {
        "total_entries": len(entries),
        "actions": dict(action_counts),
        "state_entries": dict(state_entries),
    }


def analyze_multi_command_log():
    """
    Analyze multi_command_log.jsonl (Phase 5).
    Computes synthesis success rate, average sub-commands, average elapsed.
    """
    entries = _read_jsonl(LOG_FILES["multi_command"])
    if not entries:
        return {"total_entries": 0, "note": "No multi-command log found."}

    total_executions = 0
    synthesis_success = 0
    synthesis_fallback = 0
    elapsed_times = []
    sub_command_counts = []

    for entry in entries:
        action = entry.get("action", "")
        details = entry.get("details", {})

        if action == "execute_complete":
            total_executions += 1
            elapsed = details.get("elapsed_seconds", 0)
            if elapsed:
                elapsed_times.append(elapsed)
            sub_cmds = details.get("sub_commands", [])
            sub_command_counts.append(len(sub_cmds))
        elif action == "synthesis_success":
            synthesis_success += 1
        elif action == "synthesis_fallback":
            synthesis_fallback += 1

    return {
        "total_entries": len(entries),
        "total_executions": total_executions,
        "synthesis_success_count": synthesis_success,
        "synthesis_fallback_count": synthesis_fallback,
        "synthesis_success_rate": round(synthesis_success / (synthesis_success + synthesis_fallback), 3) if (synthesis_success + synthesis_fallback) else 0,
        "avg_elapsed_seconds": round(sum(elapsed_times) / len(elapsed_times), 2) if elapsed_times else 0,
        "avg_sub_commands": round(sum(sub_command_counts) / len(sub_command_counts), 1) if sub_command_counts else 0,
    }


# ═══════════════════════════════════════════════════════════════════════
# RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════════════

def generate_recommendations(validation_analysis, fuzzy_analysis):
    """
    Generate actionable recommendations based on the analysis.
    Returns a list of recommendation strings.
    """
    recommendations = []

    # Check per-tool pass rates
    tools = validation_analysis.get("tools", {})
    for tool, stats in tools.items():
        if stats["total"] < 3:
            continue  # Not enough data

        pass_rate = stats["pass_rate"]
        avg_sim = stats["avg_similarity"]

        if pass_rate < 0.50:
            recommendations.append(
                f"⚠️  Tool '{tool}' has LOW pass rate ({pass_rate:.0%}, {stats['total']} samples). "
                f"Consider: (a) lowering its sim_pass threshold via per_tool_thresholds.py, "
                f"(b) improving its description in toolRegistry.py, or "
                f"(c) removing it from the 1.5B's repertoire (route to 8B directly)."
            )
        elif pass_rate < 0.70 and avg_sim < 0.50:
            recommendations.append(
                f"⚠️  Tool '{tool}' has borderline pass rate ({pass_rate:.0%}) with low avg similarity ({avg_sim}). "
                f"Consider lowering its sim_pass threshold to 0.50."
            )

        if stats["fail_rate"] > 0.30:
            recommendations.append(
                f"⚠️  Tool '{tool}' has HIGH fail rate ({stats['fail_rate']:.0%}). "
                f"The 1.5B frequently picks it incorrectly. "
                f"Consider adding a pattern matcher in smartRouter.py for this tool's common phrasings."
            )

    # Check fuzzy match patterns
    hallucinations = fuzzy_analysis.get("hallucinations", {})
    for hallucinated, stats in hallucinations.items():
        if stats["count"] >= 3:
            # Find the most common match
            matched_to = stats["matched_to"]
            most_common = max(matched_to, key=matched_to.get) if matched_to else "unknown"
            recommendations.append(
                f"🔧 The 1.5B frequently hallucinates '{hallucinated}' ({stats['count']} times), "
                f"which fuzzy-matches to '{most_common}'. "
                f"Consider adding a pattern matcher for this phrasing in smartRouter.py."
            )

    # Overall pass rate
    overall = validation_analysis.get("overall", {})
    overall_pass = overall.get("pass_rate", 0)
    if overall_pass < 0.70 and overall.get("total_entries", 0) >= 10:
        recommendations.append(
            f"⚠️  Overall validation pass rate is {overall_pass:.0%} (target: >80%). "
            f"Consider lowering VALIDATION_SIM_PASS from {getattr(config, 'VALIDATION_SIM_PASS', 0.60)} "
            f"to 0.50, or improving tool descriptions."
        )
    elif overall_pass > 0.95 and overall.get("total_entries", 0) >= 10:
        recommendations.append(
            f"✅ Overall pass rate is {overall_pass:.0%} — thresholds may be too lenient. "
            f"Consider raising VALIDATION_SIM_PASS to catch more borderline cases."
        )

    if not recommendations:
        recommendations.append("✅ No issues detected. All metrics within normal range.")

    return recommendations


# ═══════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════

def generate_report():
    """
    Generate a full calibration report.
    Returns a dict with all analyses and recommendations.
    """
    print("[Calibration]: Analyzing log files...")

    validation = analyze_validation_log()
    print(f"  [OK] Validation log: {validation.get('overall', {}).get('total_entries', 0)} entries")

    fuzzy = analyze_fuzzy_match_log()
    print(f"  [OK] Fuzzy match log: {fuzzy.get('total_entries', 0)} entries")

    normalization = analyze_normalization_log()
    print(f"  [OK] Normalization log: {normalization.get('total_entries', 0)} entries")

    state_machine = analyze_state_machine_log()
    print(f"  [OK] State machine log: {state_machine.get('total_entries', 0)} entries")

    multi_command = analyze_multi_command_log()
    print(f"  [OK] Multi-command log: {multi_command.get('total_entries', 0)} entries")

    print("[Calibration]: Generating recommendations...")
    recommendations = generate_recommendations(validation, fuzzy)

    return {
        "generated_at": datetime.now().isoformat(),
        "validation": validation,
        "fuzzy_match": fuzzy,
        "normalization": normalization,
        "state_machine": state_machine,
        "multi_command": multi_command,
        "recommendations": recommendations,
    }


def format_report_text(report):
    """Format the report as human-readable text for console output."""
    lines = []
    lines.append("=" * 70)
    lines.append("  JARVIS Calibration Report — Phase 6")
    lines.append(f"  Generated: {report['generated_at']}")
    lines.append("=" * 70)
    lines.append("")

    # Validation
    val = report.get("validation", {})
    overall = val.get("overall", {})
    lines.append("── Phase 1: Validation Gate ──")
    lines.append(f"  Total decisions: {overall.get('total_entries', 0)}")
    lines.append(f"  Overall pass rate: {overall.get('pass_rate', 0):.1%}")
    lines.append(f"  Overall fail rate: {overall.get('fail_rate', 0):.1%}")
    lines.append("")

    tools = val.get("tools", {})
    if tools:
        lines.append("  Per-tool statistics:")
        lines.append(f"  {'Tool':<25} {'Total':>5} {'Pass%':>6} {'Fail%':>6} {'AvgSim':>7}")
        lines.append(f"  {'-'*25} {'-'*5} {'-'*6} {'-'*6} {'-'*7}")
        for tool, stats in sorted(tools.items(), key=lambda x: x[1]["total"], reverse=True):
            lines.append(
                f"  {tool:<25} {stats['total']:>5} "
                f"{stats['pass_rate']:>5.0%} "
                f"{stats['fail_rate']:>5.0%} "
                f"{stats['avg_similarity']:>7.3f}"
            )
    else:
        lines.append("  (No tool data yet — run JARVIS for a few days first)")
    lines.append("")

    # Fuzzy matches
    fuzzy = report.get("fuzzy_match", {})
    lines.append("── Phase 1: Fuzzy Match Hallucinations ──")
    lines.append(f"  Total fuzzy matches: {fuzzy.get('total_entries', 0)}")
    hallucinations = fuzzy.get("hallucinations", {})
    if hallucinations:
        lines.append("  Most hallucinated tool names:")
        for h, stats in list(hallucinations.items())[:5]:
            matched = stats.get("matched_to", {})
            most_common = max(matched, key=matched.get) if matched else "?"
            lines.append(f"    '{h}' → '{most_common}' ({stats['count']} times)")
    else:
        lines.append("  (No hallucinations detected — 1.5B is accurate!)")
    lines.append("")

    # Normalization
    norm = report.get("normalization", {})
    lines.append("── Phase 2: Normalization ──")
    lines.append(f"  Total events: {norm.get('total_entries', 0)}")
    actions = norm.get("actions", {})
    for action, count in sorted(actions.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"    {action}: {count}")
    lines.append("")

    # State machine
    sm = report.get("state_machine", {})
    lines.append("── Phase 4: State Machine ──")
    lines.append(f"  Total events: {sm.get('total_entries', 0)}")
    actions = sm.get("actions", {})
    for action, count in sorted(actions.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"    {action}: {count}")
    state_entries = sm.get("state_entries", {})
    if state_entries:
        lines.append("  State entries:")
        for state, count in state_entries.items():
            lines.append(f"    {state}: {count}")
    lines.append("")

    # Multi-command
    mc = report.get("multi_command", {})
    lines.append("── Phase 5: Multi-Command ──")
    lines.append(f"  Total executions: {mc.get('total_executions', 0)}")
    lines.append(f"  Synthesis success rate: {mc.get('synthesis_success_rate', 0):.1%}")
    lines.append(f"  Avg elapsed: {mc.get('avg_elapsed_seconds', 0)}s")
    lines.append(f"  Avg sub-commands: {mc.get('avg_sub_commands', 0)}")
    lines.append("")

    # Recommendations
    lines.append("── Recommendations ──")
    for rec in report.get("recommendations", []):
        lines.append(f"  {rec}")
    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def save_report_json(report, output_path=None):
    """Save the report as JSON for programmatic access."""
    if output_path is None:
        output_path = os.path.join(_BASE, "calibration_report.json")
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"[Calibration]: Report saved to {output_path}")
        return output_path
    except Exception as e:
        print(f"[Calibration]: Could not save report: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# AUTO-APPLY THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════

def auto_apply_thresholds(report, dry_run=True):
    """
    Automatically apply threshold adjustments based on the report.
    Only applies for tools with enough data (>= 5 samples).

    Args:
        report: The report dict from generate_report()
        dry_run: If True, only print what would change; don't actually save.
    """
    try:
        from per_tool_thresholds import set_thresholds
    except ImportError:
        print("[Calibration]: per_tool_thresholds module not available.")
        return

    tools = report.get("validation", {}).get("tools", {})
    changes = []

    for tool, stats in tools.items():
        if stats["total"] < 5:
            continue  # Not enough data

        pass_rate = stats["pass_rate"]
        avg_sim = stats["avg_similarity"]

        # If pass rate is low AND avg similarity is low, lower the threshold
        if pass_rate < 0.60 and avg_sim < 0.50:
            new_pass = max(0.40, avg_sim - 0.05)
            new_borderline = max(0.25, new_pass - 0.15)
            changes.append({
                "tool": tool,
                "current_pass_rate": pass_rate,
                "avg_similarity": avg_sim,
                "new_sim_pass": new_pass,
                "new_sim_borderline": new_borderline,
            })

            if not dry_run:
                set_thresholds(tool, sim_pass=new_pass, sim_borderline=new_borderline)

    if changes:
        print(f"\n[Calibration]: {'Would apply' if dry_run else 'Applied'} {len(changes)} threshold adjustments:")
        for c in changes:
            print(f"  {c['tool']}: pass={c['new_sim_pass']:.2f}, borderline={c['new_sim_borderline']:.2f} "
                  f"(was failing {1-c['current_pass_rate']:.0%} of the time, avg sim={c['avg_similarity']:.3f})")
    else:
        print("\n[Calibration]: No threshold adjustments needed.")

    return changes


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Calibration Module (Phase 6)...\n")

    report = generate_report()
    print()
    print(format_report_text(report))

    # Save JSON report
    save_report_json(report)

    # Auto-apply (dry run)
    auto_apply_thresholds(report, dry_run=True)
