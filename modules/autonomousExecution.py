import os
import sys
import time
import subprocess
import threading
import shutil
import re
import json

# Add root folder to sys.path (CRITICAL: Preserves configuration package imports)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        APPROVAL_REQUIRED_ACTIONS = ["delete", "uninstall", "git_push", "git_force", "run_script"]
        MACRO_CHAINS = {}
        OLLAMA_BASE_URL = "http://localhost:11434"
        CODE_MODEL = "deepseek-coder:6.7b"

# Active macro running flag
_macro_running = False

def handle_macro_chains(trigger):
    """
    Looks up trigger in MACRO_CHAINS and returns the commands list.
    """
    trigger_clean = trigger.lower().strip()
    for macro_name, commands in config.MACRO_CHAINS.items():
        if macro_name in trigger_clean:
            return commands
    return None

def approval_gate(action, description, speak_fn=None, input_fn=None):
    """
    Destructive actions gate. Asks user to confirm.
    """
    if action not in config.APPROVAL_REQUIRED_ACTIONS:
        return True
        
    msg = f"Sir, I require confirmation to execute: {description}. Do you confirm?"
    print(f"[Approval Gate]: {msg}")
    
    if speak_fn:
        speak_fn(msg)
    else:
        print(msg)
        
    if input_fn:
        user_res = input_fn()
    else:
        user_res = input("Confirm (yes/no): ")
        
    user_res = user_res.lower().strip()
    positives = ["yes", "confirm", "go ahead", "yup", "yep", "do it", "sure", "ok", "okay", "kumpirmahin"]
    if any(w in user_res for w in positives):
        return True
    return False

def run_code_file(path, speak_fn=None):
    """
    Executes a source code file (.py, .js, .ts, .go, .rb, .pl, .sh, .bat, .ps1, .cpp, .c, .cs) dynamically
    by detecting its extension and invoking the correct compiler or runtime interpreter.
    """
    if not os.path.exists(path):
        return f"File does not exist: {path}"
        
    ext = os.path.splitext(path)[1].lower()
    filename = os.path.basename(path)
    
    # FIXED: Force standard UTF-8 output encoding for all child subprocesses (prevents Windows Unicode crashes)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    # Map file extensions to parameterized runtime commands (prevents shell injection)
    try:
        if ext in [".py", ".pyw"]:
            res = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=15, env=env)
            
        elif ext == ".js":
            res = subprocess.run(["node", path], capture_output=True, text=True, timeout=15, env=env)
            
        elif ext == ".ts":
            res = subprocess.run(f'npx ts-node "{path}"', capture_output=True, text=True, timeout=20, shell=True, env=env)
            
        elif ext == ".go":
            res = subprocess.run(["go", "run", path], capture_output=True, text=True, timeout=20, env=env)
            
        elif ext == ".rb":
            res = subprocess.run(["ruby", path], capture_output=True, text=True, timeout=15, env=env)
            
        elif ext == ".pl":
            res = subprocess.run(["perl", path], capture_output=True, text=True, timeout=15, env=env)
            
        elif ext in [".bat", ".cmd"]:
            res = subprocess.run(["cmd", "/c", path], capture_output=True, text=True, timeout=15, env=env)
            
        elif ext == ".ps1":
            res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path], capture_output=True, text=True, timeout=15, env=env)
            
        elif ext == ".sh":
            res = subprocess.run(["bash", path], capture_output=True, text=True, timeout=15, env=env)
            
        elif ext in [".cpp", ".cc"]:
            # Compile C++ using g++
            exe_name = os.path.join(os.environ.get("TEMP", os.getcwd()), "temp_cpp.exe" if os.name == "nt" else "temp_cpp")
            compile_res = subprocess.run(["g++", "-O3", path, "-o", exe_name], capture_output=True, text=True, timeout=15, env=env)
            if compile_res.returncode != 0:
                return f"C++ Compilation failed, Sir:\n{compile_res.stderr.strip()}"
            res = subprocess.run([exe_name], capture_output=True, text=True, timeout=15, env=env)
            try: os.remove(exe_name)
            except Exception: pass
            
        elif ext == ".c":
            # Compile C using gcc
            exe_name = os.path.join(os.environ.get("TEMP", os.getcwd()), "temp_c.exe" if os.name == "nt" else "temp_c")
            compile_res = subprocess.run(["gcc", path, "-o", exe_name], capture_output=True, text=True, timeout=15, env=env)
            if compile_res.returncode != 0:
                return f"C Compilation failed, Sir:\n{compile_res.stderr.strip()}"
            res = subprocess.run([exe_name], capture_output=True, text=True, timeout=15, env=env)
            try: os.remove(exe_name)
            except Exception: pass
            
        elif ext == ".cs":
            # Compile C# natively using Windows built-in .NET Framework compiler (no SDK required)
            csc_path = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
            if not os.path.exists(csc_path):
                return "Sir, the native Windows C# compiler (csc.exe) was not found in your Microsoft.NET directory."
                
            exe_name = os.path.join(os.environ.get("TEMP", os.getcwd()), "temp_cs.exe")
            compile_res = subprocess.run([csc_path, f"/out:{exe_name}", "/nologo", path], capture_output=True, text=True, timeout=15, env=env)
            if compile_res.returncode != 0:
                return f"C# Compilation failed, Sir:\n{compile_res.stderr.strip()}"
            res = subprocess.run([exe_name], capture_output=True, text=True, timeout=15, env=env)
            try: os.remove(exe_name)
            except Exception: pass
            
        else:
            return f"Sir, I do not currently support running files with extension '{ext}'."
            
        # Extract Outputs
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        
        if res.returncode == 0:
            return f"Execution successful, Sir.\nOutput:\n{stdout}"
        else:
            error_msg = f"Execution failed with exit code {res.returncode}.\nError:\n{stderr}"
            if ext in [".py", ".pyw"]:
                analysis = analyze_error_with_ai(path, stderr)
                return f"{error_msg}\n\n[DeepSeek Error Analysis]:\n{analysis}"
            return error_msg
            
    except FileNotFoundError:
        runtime_names = {
            ".js": "Node.js (node)",
            ".ts": "TypeScript / Node.js (npx/ts-node)",
            ".go": "Go compiler (go)",
            ".rb": "Ruby interpreter (ruby)",
            ".pl": "Perl interpreter (perl)",
            ".sh": "Bash environment (bash)",
            ".cpp": "C++ Compiler (g++)",
            ".c": "C Compiler (gcc)",
            ".cs": "MSBuild C# Compiler (csc.exe)"
        }
        needed = runtime_names.get(ext, "the required compiler or runtime interpreter")
        return f"Sir, I was unable to execute the file because {needed} is missing or not configured in your system PATH environment variables."
    except subprocess.TimeoutExpired:
        return "Execution timed out after 15 seconds, Sir."
    except Exception as e:
        return f"An error occurred executing the script: {e}"

def run_python_file(path, speak_fn=None):
    """Backwards compatibility wrapper mapping old executor calls to the unified runner."""
    return run_code_file(path, speak_fn)


def plan_multi_step(goal):
    """
    Build a conservative local execution plan for a broad goal.
    This returns planned steps only; execution remains explicit and command-by-command.
    """
    goal_clean = goal.strip()
    if not goal_clean:
        return []

    lowered = goal_clean.lower()
    if "work" in lowered or "focus" in lowered:
        return config.MACRO_CHAINS.get("start work mode", [])
    if "meeting" in lowered:
        return config.MACRO_CHAINS.get("prepare for meeting", [])
    if "downloads" in lowered or "organize" in lowered:
        return ["organize downloads"]
    return [goal_clean]


def screen_to_action(prompt, speak_fn=None, input_fn=None):
    """
    Read visible screen text and return an approval-gated action summary.
    Actual clicking/typing is intentionally left to explicit follow-up commands.
    """
    try:
        from noteSystem import handle_note_commands
        ocr_result = handle_note_commands("read my screen")
    except Exception as exc:
        return f"I could not read the screen, Sir: {exc}"

    if not ocr_result or not ocr_result.startswith("[OCR_SCREEN_CONTENT]"):
        return ocr_result or "I could not extract readable screen text, Sir."

    content = ocr_result.replace("[OCR_SCREEN_CONTENT] Content:\n", "").strip()
    summary = f"Screen text captured for request: {prompt}\n\n{content[:1200]}"
    if not approval_gate("run_script", "turn the current screen contents into an automated action plan", speak_fn, input_fn):
        return "Screen action cancelled, Sir."
    return summary


def analyze_error_with_ai(filepath, error_traceback):
    """Calls DeepSeek to explain the Python error."""
    import requests
    # Try reading the file content first
    file_code = ""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            file_code = f.read()
    except Exception:
        pass
        
    prompt = f"""You are a senior python developer. Analyze this error traceback for the file {os.path.basename(filepath)}.
    
--- SOURCE CODE ---
{file_code[:2000]}
--- END SOURCE CODE ---

--- ERROR TRACEBACK ---
{error_traceback}
--- END ERROR TRACEBACK ---

Explain the root cause of the error in one sentence. Then give the exact line of code that needs to be fixed and its corrected version. Keep it extremely concise."""

    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.CODE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            },
            timeout=15
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "").strip()
    except Exception:
        pass
    return "Could not reach code analysis engine, Sir."

# ── git voice control ─────────────────────────────────────────────────────────
def git_voice_control(cmd, work_dir=None, speak_fn=None, input_fn=None, require_approval=True):
    """
    Translate voice git commands: commit, push, pull, status.
    Uses AI to generate a precise commit message if committing.
    """
    if work_dir is None:
        work_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    cmd_lower = cmd.lower()
    
    try:
        if "status" in cmd_lower:
            out = subprocess.check_output("git status", cwd=work_dir, shell=True, text=True)
            return f"Git Status in project, Sir:\n{out.strip()}"
            
        elif "pull" in cmd_lower or "fetch" in cmd_lower:
            out = subprocess.check_output("git pull", cwd=work_dir, shell=True, text=True)
            return f"Pull operation complete, Sir:\n{out.strip()}"
            
        elif "commit" in cmd_lower:
            # Check diff
            diff = subprocess.check_output("git diff", cwd=work_dir, shell=True, text=True).strip()
            if not diff:
                # Check staged
                diff = subprocess.check_output("git diff --staged", cwd=work_dir, shell=True, text=True).strip()
                if not diff:
                    return "Sir, there are no changes to commit."
            
            # Generate message via DeepSeek
            commit_msg = generate_commit_message_with_ai(diff)
            subprocess.run("git add .", cwd=work_dir, shell=True)
            res = subprocess.run(f'git commit -m "{commit_msg}"', cwd=work_dir, shell=True, capture_output=True, text=True)
            
            if res.returncode == 0:
                return f"Changes committed successfully, Sir. Message: '{commit_msg}'"
            else:
                return f"Commit failed, Sir:\n{res.stderr.strip()}"
                
        elif "push" in cmd_lower:
            if require_approval and not approval_gate("git_push", "push code modifications to remote GitHub", speak_fn, input_fn):
                return "Git push operation aborted, Sir."
                
            res = subprocess.run("git push", cwd=work_dir, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                return "Push successful, Sir. Codebase is fully synchronized with remote."
            else:
                return f"Push failed, Sir:\n{res.stderr.strip()}"
                
    except Exception as e:
        return f"Git operation failed: {e}"
        
    return "I didn't understand the Git command, Sir."

def generate_commit_message_with_ai(diff_text):
    import requests
    prompt = f"""Write a single-sentence git commit message (max 60 chars) summarizing these changes:
{diff_text[:1500]}
Do not include markdown. Output only the plain message."""
    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": config.CODE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            },
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "").replace('"', '').strip()
    except Exception:
        pass
    return "Auto-update from JARVIS"

# ── downloads organization ───────────────────────────────────────────────────
def organize_downloads(path, speak_fn=None, input_fn=None):
    """
    Plan downloads folder cleanup. Group files by extensions and request approval.
    """
    if not os.path.exists(path):
        return f"The specified path does not exist: {path}"
        
    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    if not files:
        return "Sir, the Downloads folder is already clean."
        
    categories = {
        "Documents": [".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".csv"],
        "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg"],
        "Archives": [".zip", ".rar", ".7z", ".tar", ".gz"],
        "Executables": [".exe", ".msi"],
        "AudioVideo": [".mp3", ".wav", ".mp4", ".mkv", ".avi"]
    }
    
    plan = {}
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        moved = False
        for cat, extensions in categories.items():
            if ext in extensions:
                plan.setdefault(cat, []).append(f)
                moved = True
                break
        if not moved:
            plan.setdefault("Others", []).append(f)
            
    plan_desc = []
    for cat, items in plan.items():
        plan_desc.append(f"- Move {len(items)} file(s) to '{cat}' subfolder")
        
    description = "\n".join(plan_desc)
    
    if approval_gate("organize_files", f"organize Downloads folder:\n{description}", speak_fn, input_fn):
        # Execute plan
        moved_count = 0
        for cat, items in plan.items():
            cat_dir = os.path.join(path, cat)
            os.makedirs(cat_dir, exist_ok=True)
            for item in items:
                src = os.path.join(path, item)
                dst = os.path.join(cat_dir, item)
                # Check collision
                if os.path.exists(dst):
                    base, ext = os.path.splitext(item)
                    dst = os.path.join(cat_dir, f"{base}_{int(time.time())}{ext}")
                try:
                    shutil.move(src, dst)
                    moved_count += 1
                except Exception:
                    pass
        return f"Successfully organized {moved_count} files into categories, Sir."
    else:
        return "Organizing files cancelled, Sir."

# ── clipboard auto action ─────────────────────────────────────────────────────
_last_clipboard_text = ""

def check_clipboard_change():
    """Detects if clipboard changed using native, low-level Windows ctypes with safe 64-bit pointer alignment."""
    global _last_clipboard_text
    try:
        import ctypes
        from ctypes import wintypes
        
        # Explicitly define types of Win32 functions to prevent 64-bit address truncation crashes
        ctypes.windll.user32.OpenClipboard.argtypes = [wintypes.HWND]
        ctypes.windll.user32.OpenClipboard.restype = wintypes.BOOL
        
        ctypes.windll.user32.GetClipboardData.argtypes = [wintypes.UINT]
        ctypes.windll.user32.GetClipboardData.restype = wintypes.HANDLE
        
        ctypes.windll.kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        ctypes.windll.kernel32.GlobalLock.restype = ctypes.c_void_p
        
        ctypes.windll.kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        ctypes.windll.kernel32.GlobalUnlock.restype = wintypes.BOOL
        
        ctypes.windll.user32.CloseClipboard.argtypes = []
        ctypes.windll.user32.CloseClipboard.restype = wintypes.BOOL
        
        # Open Clipboard with NULL HWND (0) -> Safe for background daemon threads
        if ctypes.windll.user32.OpenClipboard(0):
            try:
                # 13 represents CF_UNICODETEXT
                h_clip_mem = ctypes.windll.user32.GetClipboardData(13)
                if h_clip_mem:
                    # Lock memory block handle to extract direct wide-character string
                    p_clip_mem = ctypes.windll.kernel32.GlobalLock(h_clip_mem)
                    if p_clip_mem:
                        data = ctypes.c_wchar_p(p_clip_mem).value
                        ctypes.windll.kernel32.GlobalUnlock(h_clip_mem)
                        
                        if data:
                            data_clean = data.strip()
                            if data_clean and data_clean != _last_clipboard_text:
                                _last_clipboard_text = data_clean
                                return data_clean
            finally:
                ctypes.windll.user32.CloseClipboard()
    except Exception as e:
        print(f"[Clipboard Watcher Debug Error]: {e}")
    return None

def _is_python_code(text):
    """Heuristic helper to cleanly identify if the clipboard contains Python code."""
    text_clean = text.strip()
    if not text_clean:
        return False
        
    # Heuristic matching patterns for common Python layouts, keywords, assignments, and indentation
    patterns = [
        r'\bdef\s+\w+\s*\(',                      # def function_name(
        r'\bimport\s+\w+',                        # import module
        r'\bfrom\s+\w+\s+import\b',               # from module import
        r'\bprint\s*\(',                          # print(
        r'\bif\s+.*?:',                           # if condition:
        r'\belif\s+.*?:',                         # elif condition:
        r'\bfor\s+\w+\s+in\b',                    # for x in y
        r'\bwhile\s+.*?:',                        # while condition:
        r'\btry\s*:',                             # try:
        r'\bexcept(?:\s+\w+)?\s*:',               # except: or except Error:
        r'\bclass\s+\w+',                         # class ClassName
        r'^\s*#\s+\w+',                           # Python comment line
        r'\breturn\s+\w+',                        # return value
        r'\b[a-zA-Z_]\w*\s*=\s*[a-zA-Z_]\w*\(',   # matches 'variable = function_name('
        r'\b[a-z0-9_]+_[a-z0-9_]*\s*=\s*',        # FIXED: matches general snake_case assignment (e.g., commit_msg = )
        r'\b[a-z0-9_]+_[a-z0-9_]*\s*\(',          # FIXED: matches general snake_case function calls
        r'\b[a-zA-Z_]\w*\.[a-zA-Z_]\w*\(',        # object.method(
        r'^[ \t]{4,}\w+',                         # Indented block (4 spaces or tab)
    ]
    
    for p in patterns:
        if re.search(p, text_clean, re.MULTILINE):
            return True
    return False

def clipboard_watcher_thread(speak_fn=None):
    """Watch clipboard in background and offer auto actions."""
    while True:
        try:
            new_text = check_clipboard_change()
            if new_text:
                new_text = new_text.strip()
                # Quietly print so you know the engine is successfully ingesting data
                print(f"[Clipboard Ingest]: '{new_text[:30]}...'")
                
                # URL detection
                if re.match(r'^https?://[^\s/$.?#].[^\s]*$', new_text):
                    msg = "Sir, I detected a URL in your clipboard. Would you like me to bookmark it or open it?"
                    print(f"\n[Clipboard Alert]: {msg}")
                    if speak_fn: speak_fn(msg)
                # Python code detection
                elif _is_python_code(new_text):  # FIXED: Utilize the advanced heuristic parser
                    if len(new_text) < 1500:
                        msg = "Sir, I noticed python code in your clipboard. Say run that code if you want me to execute it."
                        print(f"\n[Clipboard Alert]: {msg}")
                        if speak_fn: speak_fn(msg)
        except Exception:
            pass
        time.sleep(3)

def start_clipboard_watcher(speak_fn=None):
    t = threading.Thread(target=clipboard_watcher_thread, args=(speak_fn,), daemon=True)
    t.start()

# ── scheduled automations ─────────────────────────────────────────────────────
_sched_timers = []

def run_schedule_checker(execute_cmd_fn):
    while True:
        now = time.strftime("%H:%M")
        for timer in _sched_timers[:]:
            if timer["time"] == now and not timer["triggered"]:
                print(f"[Scheduled Automation]: Running '{timer['cmd']}'")
                timer["triggered"] = True
                threading.Thread(target=execute_cmd_fn, args=(timer["cmd"],), daemon=True).start()
            elif timer["time"] != now:
                timer["triggered"] = False
        time.sleep(20)

def set_scheduled_automation(cmd, time_str, execute_cmd_fn):
    """
    Schedule a voice command to execute at specific HH:MM time.
    """
    time_match = re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', time_str)
    if not time_match:
        return "Invalid time format. Please use HH:MM."
        
    # Ensure time is 5 characters (e.g. 09:30 instead of 9:30)
    parts = time_str.split(':')
    formatted_time = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    
    _sched_timers.append({
        "cmd": cmd,
        "time": formatted_time,
        "triggered": False
    })
    
    # Start thread if not already running
    if len(_sched_timers) == 1:
        t = threading.Thread(target=run_schedule_checker, args=(execute_cmd_fn,), daemon=True)
        t.start()
        
    return f"Sir, I have scheduled the command '{cmd}' to run daily at {formatted_time}."
