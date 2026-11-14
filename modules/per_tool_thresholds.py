"""
JARVIS Per-Tool Thresholds (Phase 6)
================================================================
Allows overriding the global validation thresholds (VALIDATION_SIM_PASS,
VALIDATION_SIM_BORDERLINE) on a per-tool basis.

Why: Some tools have descriptions that score low on embedding similarity
even when correctly matched (e.g., "shutdown_system" vs "shut down the
computer" might score 0.45). Other tools might be frequently hallucinated
and need a HIGHER threshold.

Usage:
    # In per_tool_thresholds.json (auto-created on first run):
    {
      "shutdown_system": {"sim_pass": 0.50, "sim_borderline": 0.30},
      "spotify_play": {"sim_pass": 0.70, "sim_borderline": 0.50}
    }

    # In validationGate.py:
    from per_tool_thresholds import get_thresholds
    pass_thresh, borderline_thresh = get_thresholds(tool_name)
"""
import os
import sys
import json
import threading
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = _PARENT_DIR
        VALIDATION_SIM_PASS = 0.60
        VALIDATION_SIM_BORDERLINE = 0.40


# Path to the per-tool thresholds JSON file
_THRESHOLDS_FILE = os.path.join(
    getattr(config, 'BASE_DIR', _PARENT_DIR),
    "per_tool_thresholds.json"
)

# In-memory cache
_thresholds_cache = None
_thresholds_mtime = 0.0
_thresholds_lock = threading.Lock()


def _load_thresholds():
    """Load per-tool thresholds from disk, with mtime-based cache."""
    global _thresholds_cache, _thresholds_mtime

    try:
        mtime = os.path.getmtime(_THRESHOLDS_FILE)
    except OSError:
        # File doesn't exist
        return {}

    with _thresholds_lock:
        if _thresholds_cache is not None and mtime == _thresholds_mtime:
            return _thresholds_cache

        try:
            with open(_THRESHOLDS_FILE, 'r', encoding='utf-8') as f:
                _thresholds_cache = json.load(f)
            _thresholds_mtime = mtime
            return _thresholds_cache
        except Exception as e:
            print(f"[PerToolThresholds]: Load failed: {e}")
            return {}


def get_thresholds(tool_name):
    """
    Get the pass and borderline thresholds for a specific tool.
    Falls back to global config values if no override exists.

    Returns:
        (pass_threshold, borderline_threshold)
    """
    overrides = _load_thresholds()
    tool_override = overrides.get(tool_name, {})

    pass_thresh = tool_override.get("sim_pass", getattr(config, 'VALIDATION_SIM_PASS', 0.60))
    borderline_thresh = tool_override.get(
        "sim_borderline",
        getattr(config, 'VALIDATION_SIM_BORDERLINE', 0.40)
    )

    return pass_thresh, borderline_thresh


def set_thresholds(tool_name, sim_pass=None, sim_borderline=None):
    """
    Set per-tool threshold overrides.
    Only updates the provided values; leaves others unchanged.

    Args:
        tool_name: Tool name (e.g., "set_volume")
        sim_pass: Pass threshold (0.0-1.0), or None to keep existing
        sim_borderline: Borderline threshold (0.0-1.0), or None to keep existing
    """
    overrides = _load_thresholds()

    if tool_name not in overrides:
        overrides[tool_name] = {}

    if sim_pass is not None:
        overrides[tool_name]["sim_pass"] = sim_pass
    if sim_borderline is not None:
        overrides[tool_name]["sim_borderline"] = sim_borderline

    # Add timestamp for tracking
    overrides[tool_name]["_updated"] = datetime.now().isoformat()

    with _thresholds_lock:
        try:
            with open(_THRESHOLDS_FILE, 'w', encoding='utf-8') as f:
                json.dump(overrides, f, indent=2, ensure_ascii=False)
            _thresholds_cache = overrides
            _thresholds_mtime = os.path.getmtime(_THRESHOLDS_FILE)
        except Exception as e:
            print(f"[PerToolThresholds]: Save failed: {e}")


def get_all_overrides():
    """Return all per-tool threshold overrides (for the calibration report)."""
    return _load_thresholds()


def clear_override(tool_name):
    """Remove the override for a specific tool (revert to global thresholds)."""
    overrides = _load_thresholds()
    if tool_name in overrides:
        del overrides[tool_name]
        with _thresholds_lock:
            try:
                with open(_THRESHOLDS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(overrides, f, indent=2, ensure_ascii=False)
                _thresholds_cache = overrides
                _thresholds_mtime = os.path.getmtime(_THRESHOLDS_FILE)
            except Exception as e:
                print(f"[PerToolThresholds]: Clear failed: {e}")


def create_default_file():
    """Create an empty thresholds file with a comment header."""
    if not os.path.exists(_THRESHOLDS_FILE):
        try:
            with open(_THRESHOLDS_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f, indent=2)
            print(f"[PerToolThresholds]: Created empty overrides file at {_THRESHOLDS_FILE}")
        except Exception as e:
            print(f"[PerToolThresholds]: Could not create file: {e}")


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Per-Tool Thresholds (Phase 6)...\n")

    # Test 1: Get thresholds for a tool with no override
    p, b = get_thresholds("set_volume")
    print(f"  set_volume (no override): pass={p}, borderline={b}")

    # Test 2: Set an override
    set_thresholds("shutdown_system", sim_pass=0.50, sim_borderline=0.30)
    p, b = get_thresholds("shutdown_system")
    print(f"  shutdown_system (override): pass={p}, borderline={b}")

    # Test 3: Get all overrides
    all_overrides = get_all_overrides()
    print(f"\n  All overrides: {json.dumps(all_overrides, indent=2)}")

    # Test 4: Clear override
    clear_override("shutdown_system")
    p, b = get_thresholds("shutdown_system")
    print(f"\n  shutdown_system (after clear): pass={p}, borderline={b}")

    # Clean up test file
    try:
        os.remove(_THRESHOLDS_FILE)
        print("\n  Cleaned up test file.")
    except Exception:
        pass
