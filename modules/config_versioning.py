"""
JARVIS Config Versioning
================================================================
Auto-saves config.py changes and provides rollback.
"""
import os
import sys
import shutil
import difflib
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = "."

_CONFIG_FILE = os.path.join(getattr(config, 'BASE_DIR', '.'), "config.py")
_VERSIONS_DIR = os.path.join(getattr(config, 'BASE_DIR', '.'), "config_versions")


def save_version(reason="manual"):
    """Save current config.py as a versioned backup."""
    if not os.path.exists(_CONFIG_FILE):
        print("[ConfigVersion]: config.py not found")
        return

    os.makedirs(_VERSIONS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_file = os.path.join(_VERSIONS_DIR, f"config_{timestamp}.py")

    shutil.copy2(_CONFIG_FILE, version_file)

    # Save metadata
    meta_file = os.path.join(_VERSIONS_DIR, f"config_{timestamp}.meta")
    with open(meta_file, 'w') as f:
        f.write(f"timestamp: {timestamp}\n")
        f.write(f"reason: {reason}\n")
        f.write(f"saved_at: {datetime.now().isoformat()}\n")

    print(f"[ConfigVersion]: Saved version {timestamp} ({reason})")


def list_versions():
    """List all saved config versions."""
    if not os.path.exists(_VERSIONS_DIR):
        return []

    versions = []
    for fname in sorted(os.listdir(_VERSIONS_DIR), reverse=True):
        if fname.endswith(".py") and fname.startswith("config_"):
            timestamp = fname.replace("config_", "").replace(".py", "")
            meta_file = os.path.join(_VERSIONS_DIR, f"config_{timestamp}.meta")

            reason = "unknown"
            if os.path.exists(meta_file):
                with open(meta_file, 'r') as f:
                    for line in f:
                        if line.startswith("reason:"):
                            reason = line.split(":", 1)[1].strip()

            versions.append({
                "timestamp": timestamp,
                "file": fname,
                "reason": reason,
            })

    return versions


def rollback(timestamp):
    """Rollback config.py to a specific version."""
    version_file = os.path.join(_VERSIONS_DIR, f"config_{timestamp}.py")

    if not os.path.exists(version_file):
        print(f"[ConfigVersion]: Version {timestamp} not found")
        return False

    # Save current as a version before rolling back
    save_version(reason=f"pre-rollback-to-{timestamp}")

    # Restore
    shutil.copy2(version_file, _CONFIG_FILE)
    print(f"[ConfigVersion]: Rolled back to {timestamp}")
    return True


def diff(timestamp):
    """Show diff between current config and a version."""
    version_file = os.path.join(_VERSIONS_DIR, f"config_{timestamp}.py")

    if not os.path.exists(version_file):
        print(f"[ConfigVersion]: Version {timestamp} not found")
        return

    if not os.path.exists(_CONFIG_FILE):
        print("[ConfigVersion]: config.py not found")
        return

    with open(version_file, 'r') as f:
        old_lines = f.readlines()
    with open(_CONFIG_FILE, 'r') as f:
        new_lines = f.readlines()

    diff = difflib.unified_diff(old_lines, new_lines,
                                 fromfile=f"config_{timestamp}.py",
                                 tofile="config.py (current)",
                                 lineterm="")

    print("\n".join(diff))


def auto_save_if_changed():
    """Check if config.py changed since last save, and save if so."""
    if not os.path.exists(_CONFIG_FILE) or not os.path.exists(_VERSIONS_DIR):
        return

    versions = list_versions()
    if not versions:
        return

    latest_version_file = os.path.join(_VERSIONS_DIR, versions[0]["file"])

    # Compare file contents
    with open(latest_version_file, 'r') as f:
        saved_content = f.read()
    with open(_CONFIG_FILE, 'r') as f:
        current_content = f.read()

    if saved_content != current_content:
        save_version(reason="auto-detected-change")


if __name__ == "__main__":
    print("Config Versioning System")
    print(f"Config file: {_CONFIG_FILE}")
    print(f"Versions dir: {_VERSIONS_DIR}")
    print(f"\nVersions: {len(list_versions())}")
    for v in list_versions()[:5]:
        print(f"  {v['timestamp']} ({v['reason']})")
