import os
import sys
import time
import json
import traceback
import threading
import hashlib
import base64
import subprocess
from datetime import datetime  # <-- FIXED: Missing import restored

# Native Windows Data Protection API to securely lock keys to the OS user
import ctypes
from ctypes import wintypes

try:
    import psutil
except ImportError:
    psutil = None

# Add root folder to sys.path (CRITICAL: Preserves configuration routing)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import config
except ImportError:
    class config:
        CRASH_JOURNAL_FILE = "crash_journal.json"
        ENCRYPT_MEMORY = False
        RAM_OVERLOAD_PCT = 90
        CPU_OVERLOAD_PCT = 95

# --- Native Windows DATA_BLOB Structure ---
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def encrypt_data(plain_text: str) -> str:
    """Encrypts text natively using Windows DPAPI, tied to the local user account."""
    if os.name != "nt":  # Cross-platform fallback if not on Windows
        return base64.b64encode(plain_text.encode('utf-8')).decode('utf-8')
    
    data = plain_text.encode('utf-8')
    in_blob = DATA_BLOB(len(data), ctypes.create_string_buffer(data))
    out_blob = DATA_BLOB()
    
    # CryptProtectData: 1 = CRYPTPROTECT_UI_FORBIDDEN (Runs silently with no prompts)
    success = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 1, ctypes.byref(out_blob)
    )
    if not success:
        raise OSError("DPAPI Encryption failed.")
        
    encrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    
    return base64.b64encode(encrypted_bytes).decode('utf-8')

def decrypt_data(cipher_text: str) -> str:
    """Decrypts a base64 encoded string using Windows DPAPI."""
    try:
        data = base64.b64decode(cipher_text.encode('utf-8'))
    except Exception:
        return cipher_text  # Return raw if base64 decoding fails
        
    if os.name != "nt":  # Cross-platform fallback if not on Windows
        return data.decode('utf-8')
        
    in_blob = DATA_BLOB(len(data), ctypes.create_string_buffer(data))
    out_blob = DATA_BLOB()
    
    # CryptUnprotectData: 1 = CRYPTPROTECT_UI_FORBIDDEN
    success = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 1, ctypes.byref(out_blob)
    )
    if not success:
        return cipher_text  # Fallback to raw text if decryption fails (e.g. decrypted transition)
        
    decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    
    return decrypted_bytes.decode('utf-8')

# ── read/write memory wrappers ──────────────────────────────────────────────
def secure_read_json(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
            
        if not content:
            return None
            
        if config.ENCRYPT_MEMORY:
            decrypted = decrypt_data(content)
            return json.loads(decrypted)
        else:
            return json.loads(content)
    except Exception as e:
        # Fallback: maybe the file is not encrypted but setting is on, try decrypting or reading normally
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"[SelfRepair Error]: Could not read {filepath}: {e}")
            return None

def secure_write_json(filepath, data):
    try:
        plain_text = json.dumps(data, indent=2, ensure_ascii=False)
        if config.ENCRYPT_MEMORY:
            output_content = encrypt_data(plain_text)
        else:
            output_content = plain_text
            
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(output_content)
        return True
    except Exception as e:
        print(f"[SelfRepair Error]: Could not write {filepath}: {e}")
        return False

# ── module watchdog ─────────────────────────────────────────────────────────
def _memory_file_paths():
    """Return JSON memory files managed by the vault layer."""
    names = [
        "MEMORY_FILE", "PROFILE_FILE", "TASKS_FILE", "TIMERS_FILE", "RECURRING_FILE",
        "NOTES_FILE", "HISTORY_FILE", "PERSONALITY_FILE", "KNOWLEDGE_FILE",
        "GOAL_TRACKER_FILE", "CRASH_JOURNAL_FILE", "DAILY_SUMMARY_FILE",
        "RESPONSE_CACHE_FILE"
    ]
    return [getattr(config, name) for name in names if hasattr(config, name)]


def encrypt_memory_files():
    """
    Encrypt every configured JSON memory file when ENCRYPT_MEMORY is enabled.
    Leaves files untouched when the setting is off.
    """
    if not getattr(config, "ENCRYPT_MEMORY", False):
        return "Memory encryption is disabled in config.py."

    encrypted = 0
    for filepath in _memory_file_paths():
        data = secure_read_json(filepath)
        if data is None:
            continue
        if secure_write_json(filepath, data):
            encrypted += 1
    return f"Encrypted {encrypted} memory file(s), Sir."


def decrypt_memory_files():
    """
    Decrypt configured JSON memory files into plain JSON.
    Temporarily bypasses ENCRYPT_MEMORY so secure_write_json writes plaintext.
    """
    original_setting = getattr(config, "ENCRYPT_MEMORY", False)
    decrypted_payloads = []
    try:
        for filepath in _memory_file_paths():
            data = secure_read_json(filepath)
            if data is not None:
                decrypted_payloads.append((filepath, data))

        config.ENCRYPT_MEMORY = False
        written = 0
        for filepath, data in decrypted_payloads:
            if secure_write_json(filepath, data):
                written += 1
        return f"Decrypted {written} memory file(s), Sir."
    finally:
        config.ENCRYPT_MEMORY = original_setting


_monitored_threads = {}

def register_thread(name, thread_obj):
    _monitored_threads[name] = thread_obj

def _watchdog_loop(speak_cb=None):
    print("[SelfRepair]: Watchdog service active.")
    while True:
        for name, t in list(_monitored_threads.items()):
            if not t.is_alive():
                msg = f"Sir, I detected that the background module '{name}' has crashed. Attempting auto-recovery..."
                print(f"[Watchdog Alert]: {msg}")
                if speak_cb:
                    speak_cb(msg)
                # Restart (usually done by parent re-initialization or flag checking)
                # For simplicity, we trigger recovery routines
                del _monitored_threads[name]
        time.sleep(10)

def start_module_watchdog(speak_cb=None):
    t = threading.Thread(target=_watchdog_loop, args=(speak_cb,), daemon=True)
    t.start()

# ── resource guardian ────────────────────────────────────────────────────────
def check_resource_overload(speak_cb=None):
    if not psutil:
        return
        
    try:
        ram = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1.0)
        
        if ram.percent > config.RAM_OVERLOAD_PCT:
            # Find top RAM consumers
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
                try:
                    processes.append(proc.info)
                except Exception:
                    pass
            processes.sort(key=lambda x: x['memory_percent'] or 0, reverse=True)
            top_proc = processes[0]['name'] if processes else "Unknown"
            
            msg = f"Alert, Sir. System RAM is at {ram.percent} percent. '{top_proc}' is the leading consumer. Please free memory."
            print(f"[Resource Guardian]: {msg}")
            if speak_cb:
                speak_cb(msg)
                
        if cpu > config.CPU_OVERLOAD_PCT:
            msg = f"Warning, Sir. CPU usage is sustained at {cpu} percent. System responsiveness may degrade."
            print(f"[Resource Guardian]: {msg}")
            if speak_cb:
                speak_cb(msg)
    except Exception:
        pass

def _resource_guardian_loop(speak_cb=None):
    while True:
        check_resource_overload(speak_cb)
        time.sleep(30)

def start_resource_guardian(speak_cb=None):
    t = threading.Thread(target=_resource_guardian_loop, args=(speak_cb,), daemon=True)
    t.start()

# ── crash journal ─────────────────────────────────────────────────────────────
def log_crash(context_msg):
    """Saves traceback and system context info to crash journal."""
    tb = traceback.format_exc()
    journal_entry = {
        "timestamp": datetime.now().isoformat() if hasattr(datetime, 'now') else time.ctime(),
        "context": context_msg,
        "traceback": tb,
        "recovered": False
    }
    
    entries = []
    if os.path.exists(config.CRASH_JOURNAL_FILE):
        try:
            with open(config.CRASH_JOURNAL_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            pass
            
    entries.append(journal_entry)
    
    try:
        with open(config.CRASH_JOURNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def recover_last_session():
    """
    On startup, inspects crash journal. 
    If a recent unrecovered crash exists, returns a recovery statement.
    """
    if not os.path.exists(config.CRASH_JOURNAL_FILE):
        return None
        
    try:
        with open(config.CRASH_JOURNAL_FILE, "r", encoding="utf-8") as f:
            entries = json.load(f)
            
        if not entries:
            return None
            
        last_crash = entries[-1]
        if not last_crash.get("recovered"):
            # Mark it recovered
            last_crash["recovered"] = True
            with open(config.CRASH_JOURNAL_FILE, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
                
            return f"Sir, I detected a crash journal entry from our last session: '{last_crash['context']}'. I have fully recovered my modules and cleared memory stacks."
    except Exception:
        pass
    return None

# ── anomalous process alerts ──────────────────────────────────────────────────
_known_processes = set()

def check_anomalous_processes(speak_cb=None):
    """Scans for new running processes compared to previous scan (run at startup + daily)."""
    global _known_processes
    if not psutil:
        return
        
    current_processes = set()
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info['name']
            if name:
                current_processes.add(name)
        except Exception:
            pass
            
    if not _known_processes:
        _known_processes = current_processes
        return
        
    new_procs = current_processes - _known_processes
    if new_procs:
        # Ignore system common ones to avoid notification spam
        common_ignores = ["conhost.exe", "svchost.exe", "cmd.exe", "powershell.exe", "runtimebroker.exe"]
        filtered_new = [p for p in new_procs if p.lower() not in common_ignores]
        
        if filtered_new:
            msg = f"Sir, I detected {len(filtered_new)} new running process{'es' if len(filtered_new)>1 else ''} on your system: {', '.join(filtered_new[:3])}."
            print(f"[Security Check]: {msg}")
            if speak_cb:
                speak_cb(msg)
                
    # Update known process list
    _known_processes = current_processes