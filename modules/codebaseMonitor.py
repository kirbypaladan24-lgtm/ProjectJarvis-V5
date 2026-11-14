"""
Codebase Monitor Module for JARVIS (UPGRADED)
- Maps the internal architecture of the assistant
- Tracks file modification timestamps to detect user edits in real-time
- Provides raw source code context for LLM architectural analysis
- Integrates a lightweight, non-blocking background thread file-watcher
"""
import os
import json
import re
import time
import threading
from datetime import datetime

# Get the root directory of the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_FILE = os.path.join(BASE_DIR, "project_snapshot.json")

# FIXED: Thread-lock to protect snapshot reads/writes across concurrent threads
_monitor_lock = threading.Lock()
_watcher_running = False

def get_project_files():
    """Returns a list of all relevant Python files in the project."""
    project_files = []
    # Scan root
    for file in os.listdir(BASE_DIR):
        if file.endswith(".py"):
            project_files.append(os.path.join(BASE_DIR, file))
    
    # Scan modules folder
    modules_path = os.path.join(BASE_DIR, "modules")
    if os.path.exists(modules_path):
        for file in os.listdir(modules_path):
            if file.endswith(".py"):
                project_files.append(os.path.join(modules_path, file))
    
    return project_files

def check_for_code_changes():
    """Compares current file timestamps with the last known snapshot. (Thread-safe)"""
    files = get_project_files()
    current_state = {}
    for f in files:
        try:
            current_state[os.path.basename(f)] = os.path.getmtime(f)
        except Exception:
            continue
    
    changes = []
    global _monitor_lock
    with _monitor_lock: # Protect file transactions from simultaneous thread access
        if os.path.exists(SNAPSHOT_FILE):
            try:
                with open(SNAPSHOT_FILE, "r") as f:
                    old_state = json.load(f)
                
                for filename, mtime in current_state.items():
                    if filename not in old_state:
                        changes.append(f"New file added: {filename}")
                    elif mtime > old_state[filename]:
                        changes.append(f"File edited: {filename}")
            except Exception:
                pass
                
        # Save the new state
        try:
            with open(SNAPSHOT_FILE, "w") as f:
                json.dump(current_state, f, indent=2)
        except Exception:
            pass
        
    return changes

def get_codebase_context():
    """Reads all project code and returns it as a formatted string for the LLM."""
    files = get_project_files()
    context = "JARVIS SOURCE CODE BLUEPRINT:\n\n"
    
    for fpath in files:
        filename = os.path.basename(fpath)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                code = f.read()
                context += f"--- FILE: {filename} ---\n{code}\n\n"
        except Exception:
            continue
            
    return context

def handle_codebase_commands(user_input):
    """Router for codebase-related queries."""
    text = user_input.lower()
    
    if any(w in text for w in ["what changed", "changes", "did i edit", "what have i added", "what file", "which file", "exactly", "how many"]):
        changes = check_for_code_changes()
        if not changes:
            return "I haven't detected any changes to my source code since our last session, Sir."
        
        count = len(changes)
        content = f"COUNT: {count} files changed.\nDETAILS:\n" + "\n".join(changes)
        return f"[CODE_CHANGES_DETECTED] Content:\n{content}"

    if any(w in text for w in ["suggest", "improve", "bugs", "weakspots", "errors", "analyze your code", "how do you work"]):
        return f"[CODEBASE_ANALYSIS_REQUEST] Content:\n{get_codebase_context()}"

    return None

# ── REAL-TIME BACKGROUND WATCHER LOOP ─────────────────────────────────────────

def codebase_watcher_loop(speak_fn):
    """Monitors codebase file-saves in real-time while JARVIS is running."""
    print("[Codebase]: Real-time file-save watcher active.")
    
    # Initialize the baseline state so we don't spam historical alerts on startup
    check_for_code_changes()
    
    while True:
        try:
            time.sleep(4)  # Scan modification times once every 4 seconds (0% CPU impact)
            changes = check_for_code_changes()
            if changes:
                # Filter to only speak about actual edits, ignoring raw addition reports
                filenames = [
                    c.replace("File edited: ", "").strip() 
                    for c in changes 
                    if c.startswith("File edited: ")
                ]
                
                # Filter out system and data files, only alert on code
                filenames = [f for f in filenames if f.endswith(".py")]
                
                if filenames:
                    if len(filenames) == 1:
                        file_list_str = f"the file {filenames[0]}"
                    else:
                        file_list_str = f"the files {', '.join(filenames[:-1])} and {filenames[-1]}"
                    
                    msg = f"Sir, I noticed that you have just saved changes to {file_list_str}."
                    print(f"\n[Codebase Alert]: {msg}")
                    if speak_fn:
                        speak_fn(msg)  # Non-blocking voice announcement
        except Exception as e:
            print(f"[Codebase Watcher Thread Error]: {e}")

def start_codebase_watcher(speak_fn=None):
    """Spawns the real-time background file monitor thread."""
    global _watcher_running
    if not _watcher_running:
        t = threading.Thread(target=codebase_watcher_loop, args=(speak_fn,), daemon=True)
        t.start()
        _watcher_running = True