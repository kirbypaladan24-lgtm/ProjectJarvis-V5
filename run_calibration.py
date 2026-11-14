"""
JARVIS Calibration CLI (Phase 6)
================================================================
Run this script to analyze all log files and generate a calibration report.

Usage:
    py run_calibration.py              # Generate report + print to console
    py run_calibration.py --apply      # Generate report + auto-apply threshold adjustments
    py run_calibration.py --json       # Generate report + save as JSON only

This script reads the JSONL log files produced by Phases 1-5:
    - validation_log.jsonl
    - fuzzy_match_log.jsonl
    - normalization_log.jsonl
    - state_machine_log.jsonl
    - multi_command_log.jsonl

And produces a human-readable report with:
    - Per-tool pass/fail rates
    - Most hallucinated tool names
    - Normalization action counts
    - State machine transition stats
    - Multi-command synthesis success rate
    - Actionable recommendations

Run weekly to track accuracy over time and tune thresholds.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))

from calibration import generate_report, format_report_text, save_report_json, auto_apply_thresholds


def main():
    print()
    print("=" * 70)
    print("  JARVIS Calibration Tool — Phase 6")
    print("=" * 70)
    print()

    # Parse args
    apply_changes = "--apply" in sys.argv
    json_only = "--json" in sys.argv

    # Generate the report
    report = generate_report()

    if json_only:
        # Save JSON only, don't print text report
        save_report_json(report)
        print("\nDone. JSON report saved.")
        return

    # Print text report
    print()
    print(format_report_text(report))

    # Save JSON report
    save_report_json(report)

    # Auto-apply threshold adjustments
    print()
    if apply_changes:
        print("── Auto-Applying Threshold Adjustments ──")
        auto_apply_thresholds(report, dry_run=False)
    else:
        print("── Dry Run: Threshold Adjustments (use --apply to save) ──")
        auto_apply_thresholds(report, dry_run=True)

    print()
    print("=" * 70)
    print("  Calibration complete.")
    print("  Report saved to: calibration_report.json")
    print("  Run weekly to track accuracy over time.")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
