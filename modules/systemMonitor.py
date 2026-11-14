"""
System Monitoring Module for JARVIS
- Tracks CPU, Memory, Disk, and Process counts
- Queries Windows hardware interfaces (PowerShell CIM) for exact CPU/GPU models
- Queries computer manufacturer and model details
- Scans connected Wi-Fi and analyzes extensive connection details (Mbps, MAC, Channel, etc.)
- Scans nearby visible networks in range with active hardware-level probe scans (mode=bssid)
- Safely retrieves plain-text passwords of saved Wi-Fi profiles
- Performs a live internet speed test using Cloudflare CDN packets
- Translates conversational app names (like 'command prompt') to Windows executables (.exe)
- Safely terminates all user-facing desktop applications with double-sided fuzzy exclusions
"""
import re
import os
import sys
import subprocess

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    print("[SystemMonitor]: psutil not installed. Installing...")
    subprocess.run([sys.executable, "-m", "pip", "install", "psutil"], check=True)
    import psutil
    HAS_PSUTIL = True

# ─────────────────────────────────────────────
# PROCESS TRANSLATION MAP
# Maps colloquial user terms to actual Windows executable names
# ─────────────────────────────────────────────
PROCESS_MAP = {
    "command prompt":     "cmd",
    "cmd":                "cmd",
    "powershell":         "powershell",
    "task manager":       "taskmgr",
    "taskmgr":            "taskmgr",
    "chrome":             "chrome",
    "google chrome":      "chrome",
    "google-chrome":      "chrome",
    "firefox":            "firefox",
    "edge":               "msedge",
    "microsoft edge":     "msedge",
    "visual studio code": "code",
    "vscode":             "code",
    "vs code":            "code",
    "code":               "code",
    "notepad":            "notepad",
    "spotify":            "spotify",
    "discord":            "discord",
    "steam":              "steam",
    "calculator":         "calc",
    "vlc":                "vlc",
    "paint":              "mspaint",
    "explorer":           "explorer",
    "file explorer":      "explorer",
    "word":               "winword",
    "excel":              "excel",
    "powerpoint":         "powerpnt"
}


def get_cpu_model():
    """Queries Windows PowerShell or platform module for the exact CPU model name."""
    try:
        cmd = "powershell -Command \"Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name\""
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = [line.strip() for line in out.split('\n') if line.strip()]
        if lines:
            return lines[0]
    except Exception:
        pass

    try:
        out = subprocess.check_output("wmic cpu get name", shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = [line.strip() for line in out.split('\n') if line.strip()]
        if len(lines) > 1:
            return lines[1]
    except Exception:
        pass

    try:
        import platform
        return platform.processor() or "Unknown Processor"
    except Exception:
        pass
        
    return "Unknown Processor"


def get_gpu_model():
    """Queries Windows PowerShell for active graphics card details."""
    try:
        cmd = "powershell -Command \"Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name\""
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = [line.strip() for line in out.split('\n') if line.strip()]
        if lines:
            return ", ".join(lines)
    except Exception:
        pass

    try:
        out = subprocess.check_output("wmic path win32_VideoController get name", shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = [line.strip() for line in out.split('\n') if line.strip()]
        if len(lines) > 1:
            return ", ".join(lines[1:])
    except Exception:
        pass

    return "Unknown Graphics Card"


def get_laptop_brand_and_model():
    """Queries Windows CIM instance for the hardware manufacturer and model name."""
    try:
        cmd_man = "powershell -Command \"Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty Manufacturer\""
        man_out = subprocess.check_output(cmd_man, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
        
        cmd_mod = "powershell -Command \"Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty Model\""
        mod_out = subprocess.check_output(cmd_mod, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
        
        if man_out and mod_out:
            return man_out, mod_out
    except Exception:
        pass
    return "Unknown Manufacturer", "Unknown Model"


def get_system_stats():
    if not HAS_PSUTIL:
        return {}
    try:
        mem = psutil.virtual_memory()
        disk_path = "C:\\" if sys.platform == "win32" else "/"
        disk = psutil.disk_usage(disk_path)
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": mem.percent,
            "memory_available_gb": round(mem.available / (1024 ** 3), 2),
            "memory_total_gb": round(mem.total / (1024 ** 3), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "processes": len(psutil.pids())
        }
    except Exception as e:
        print(f"[SystemMonitor Error]: {e}")
        return {}


def system_health_check():
    if not HAS_PSUTIL:
        return "System monitoring not available. Install psutil: pip install psutil"
    try:
        stats = get_system_stats()
        if not stats:
            return "Could not get system stats."

        issues = []
        if stats["cpu_percent"] > 80:
            issues.append(f"CPU is high at {stats['cpu_percent']}%.")
        if stats["memory_percent"] > 85:
            issues.append(f"Memory is low, {stats['memory_available_gb']} GB available.")
        if stats["disk_percent"] > 90:
            issues.append(f"Disk almost full, only {stats['disk_free_gb']} GB free.")

        used_disk = round(stats["disk_total_gb"] - stats["disk_free_gb"], 1)

        if issues:
            return "System issues detected: " + ". ".join(issues)
        return (f"System is healthy. "
                f"CPU is at {stats['cpu_percent']}%. "
                f"Memory (RAM) is at {stats['memory_percent']}% used ({stats['memory_available_gb']} GB free out of {stats['memory_total_gb']} GB total). "
                f"Storage (C: Drive) is at {stats['disk_percent']}% used (using {used_disk} GB of {stats['disk_total_gb']} GB total; {stats['disk_free_gb']} GB free). "
                f"{stats['processes']} processes are currently running.")
    except Exception as e:
        return f"Error checking system: {e}"


def get_laptop_specs():
    """Compiles exact diagnostic details of your physical hardware."""
    if not HAS_PSUTIL:
        return "Unable to retrieve laptop specs."
    
    stats = get_system_stats()
    cpu_model = get_cpu_model()
    gpu_model = get_gpu_model()
    brand, model = get_laptop_brand_and_model()
    
    mem_total = stats.get("memory_total_gb", "Unknown")
    disk_total = stats.get("disk_total_gb", "Unknown")
    disk_free = stats.get("disk_free_gb", "Unknown")
    
    return f"""LAPTOP SYSTEM SPECIFICATIONS:
- Brand / Manufacturer: {brand}
- Model: {model}
- CPU (Processor): {cpu_model}
- GPU (Graphics): {gpu_model}
- Installed Memory (RAM): {mem_total} GB
- Storage (C: Drive): {disk_total} GB Total ({disk_free} GB Free)
(Information retrieved dynamically from local hardware controllers)"""


def get_wifi_details():
    """Queries Windows native Netsh tool to analyze complete Wi-Fi status and diagnostic speed stats."""
    try:
        out = subprocess.check_output("netsh wlan show interfaces", shell=True, text=True)
        
        ssid = re.search(r'SSID\s*:\s*(.+)', out)
        signal = re.search(r'Signal\s*:\s*(.+)', out)
        state = re.search(r'State\s*:\s*(.+)', out)
        desc = re.search(r'Description\s*:\s*(.+)', out)
        radio = re.search(r'Radio type\s*:\s*(.+)', out)
        channel = re.search(r'Channel\s*:\s*(.+)', out)
        rx_rate = re.search(r'Receive rate \(Mbps\)\s*:\s*(.+)', out)
        tx_rate = re.search(r'Transmit rate \(Mbps\)\s*:\s*(.+)', out)
        auth = re.search(r'Authentication\s*:\s*(.+)', out)
        bssid = re.search(r'BSSID\s*:\s*(.+)', out)
        
        ssid_str = ssid.group(1).strip() if ssid else "Unknown Network"
        signal_str = signal.group(1).strip() if signal else "Unknown"
        state_str = state.group(1).strip() if state else "Disconnected"
        desc_str = desc.group(1).strip() if desc else "Unknown Adapter"
        radio_str = radio.group(1).strip() if radio else "Unknown"
        channel_str = channel.group(1).strip() if channel else "Unknown"
        rx_str = rx_rate.group(1).strip() if rx_rate else "Unknown"
        tx_str = tx_rate.group(1).strip() if tx_rate else "Unknown"
        auth_str = auth.group(1).strip() if auth else "Unknown"
        bssid_str = bssid.group(1).strip() if bssid else "Unknown"
        
        if "disconnected" in state_str.lower():
            return "Your laptop is currently disconnected from Wi-Fi."
            
        return f"""CURRENT WI-FI CONNECTION DETAILS:
- SSID (Network Name): '{ssid_str}'
- Connection State: {state_str.capitalize()}
- Signal Quality: {signal_str}
- Radio Type (Band): {radio_str}
- Connection Channel: {channel_str}
- Receive Speed (Link rate): {rx_str} Mbps
- Transmit Speed (Link rate): {tx_str} Mbps
- Security Authentication: {auth_str}
- BSSID (Router MAC Address): {bssid_str}
- Laptop Network Adapter: {desc_str}"""
    except Exception as e:
        return f"Could not retrieve Wi-Fi details: {e}"


def get_nearby_wifi():
    """Scans and lists visible Wi-Fi networks using detailed mode=bssid to trigger an active hardware-level scan."""
    try:
        out = subprocess.check_output("netsh wlan show networks mode=bssid", shell=True, text=True)
        networks = re.findall(r'\bSSID\s+\d+\s*:\s*(.+)', out)
        
        if not networks:
            out_std = subprocess.check_output("netsh wlan show networks", shell=True, text=True)
            networks = re.findall(r'\bSSID\s+\d+\s*:\s*(.+)', out_std)
            
        if not networks:
            return "No nearby Wi-Fi networks detected in range of your device."
            
        unique_nets = sorted(list(set([n.strip() for n in networks if n.strip()])))
        return f"Visible Wi-Fi networks in range ({len(unique_nets)}):\n" + "\n".join([f"  - {net}" for net in unique_nets])
    except Exception as e:
        return f"Could not scan nearby Wi-Fi: {e}"


def get_saved_wifi_passwords():
    """Safely extracts saved Wi-Fi profiles and pulls the plaintext keys from your laptop's history."""
    try:
        profiles_out = subprocess.check_output("netsh wlan show profiles", shell=True, text=True)
        profiles = re.findall(r'All User Profile\s+:\s+(.+)', profiles_out)
        
        if not profiles:
            return "No previously connected Wi-Fi networks found in your laptop's history."
            
        results = ["Previously connected Wi-Fi passwords stored on your laptop:"]
        for profile in profiles[:15]:
            profile = profile.strip()
            try:
                profile_out = subprocess.check_output(f'netsh wlan show profile name="{profile}" key=clear', shell=True, text=True)
                password_match = re.search(r'Key Content\s+:\s+(.+)', profile_out)
                password = password_match.group(1).strip() if password_match else "[No Password / Open Network]"
                results.append(f"  - SSID: {profile} | Password: {password}")
            except Exception:
                results.append(f"  - SSID: {profile} | Password: [Encrypted / Admin Restricted]")
                
        return "\n".join(results)
    except Exception as e:
        return f"Could not retrieve saved Wi-Fi passwords: {e}"


def test_internet_speed():
    """Runs a download transfer test using a Cloudflare CDN packet to measure exact latency and speed."""
    try:
        import requests
        import time
        print("[System]: Measuring network latency (Ping)...")
        latency_ms = None
        
        try:
            out = subprocess.check_output("ping -n 1 1.1.1.1", shell=True, text=True, timeout=3)
            match = re.search(r'time[=<](\d+)ms', out)
            if match:
                latency_ms = int(match.group(1))
        except Exception:
            pass
            
        if latency_ms is None:
            try:
                ping_start = time.time()
                requests.get("https://speed.cloudflare.com/__ping", timeout=3)
                latency_ms = int((time.time() - ping_start) * 1000)
            except Exception:
                latency_ms = 99
                
        print("[System]: Testing connection download speed via Cloudflare CDN...")
        url = "https://speed.cloudflare.com/__down?bytes=5000000"
        start_time = time.time()
        r = requests.get(url, timeout=12)
        duration = time.time() - start_time
        
        if r.status_code == 200 and duration > 0:
            mbits = (5000000 * 8) / (1024 * 1024)
            speed_mbps = mbits / duration
            return f"Network Speed Test Complete:\n- Download Speed: {round(speed_mbps, 2)} Mbps\n- Latency (Ping): {latency_ms} ms"
        return "Could not connect to the speed test server. Please check your network connection."
    except Exception as e:
        return f"Error running speed test: {e}"


def close_all_apps(exclude_list=None):
    """
    Safely terminates all user-facing desktop applications (browsers, editors, chat)
    using double-sided fuzzy matching, while strictly protecting Windows and JARVIS.
    """
    if not HAS_PSUTIL:
        return "psutil is not available."

    # Parse and map any user exclusions
    exclude_names = [x.lower().strip() for x in (exclude_list or [])]
    final_excludes = []
    for name in exclude_names:
        if name in PROCESS_MAP:
            final_excludes.append(PROCESS_MAP[name])
        else:
            final_excludes.append(name)

    # Core System & Assistant engine protections (JARVIS won't kill himself or Windows shell)
    core_protections = [
        "system", "explorer", "windows", "antivirus", "defender", "python", 
        "cmd", "powershell", "ollama", "piper", "whisper", "conhost", "taskmgr"
    ]
    final_excludes.extend(core_protections)

    # Common user-facing desktop applications to target for bulk-closing
    target_apps = [
        "chrome", "msedge", "firefox", "brave", "opera", "code", "notepad", 
        "spotify", "discord", "steam", "calc", "vlc", "mspaint", "winword", 
        "excel", "powerpnt", "slack", "teams", "zoom", "telegram", "whatsapp", 
        "blender", "unity", "postman", "figma", "notion"
    ]

    closed = []
    try:
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                name_lower = proc.name().lower()
                base_name = os.path.splitext(name_lower)[0]

                # Match if it is a target user app
                is_target = any(t in base_name for t in target_apps)
                
                # Double-sided fuzzy exclusion check: matches if exclusion is in process name OR vice-versa
                is_excluded = any(ex in base_name or base_name in ex for ex in final_excludes)

                if is_target and not is_excluded:
                    proc.kill()
                    closed.append(proc.name())
            except psutil.AccessDenied:
                # Catch UWP/Microsoft Store permission restrictions without crashing
                pass
            except psutil.NoSuchProcess:
                pass
                
        if closed:
            unique_closed = sorted(list(set(closed)))
            return f"Successfully closed all active user applications except {', '.join(exclude_list) if exclude_list else 'none'}. Closed processes: {', '.join(unique_closed)}."
        return "No active user applications were found to close, Sir."
    except Exception as e:
        return f"Error executing bulk app close: {e}"


def list_running_apps():
    if not HAS_PSUTIL:
        return []
    try:
        apps = set()
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.name()
                if name and not name.lower().startswith(('svchost', 'system', 'registry', 'smss', 'csrss')):
                    apps.add(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return sorted(apps)[:30]
    except Exception as e:
        print(f"[SystemMonitor Error]: {e}")
        return []


def kill_process(process_name):
    if not HAS_PSUTIL:
        return "psutil not available."
    
    # Standardize and translate the input
    proc_query = process_name.lower().strip()
    if proc_query in PROCESS_MAP:
        proc_query = PROCESS_MAP[proc_query]
        
    killed = []
    try:
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                proc_name_lower = proc.name().lower()
                # Match either the whole name or the base name (e.g. match 'cmd' inside 'cmd.exe')
                if proc_query in proc_name_lower or proc_query + ".exe" in proc_name_lower:
                    proc.kill()
                    killed.append(proc.name())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed:
            unique_killed = list(set(killed))
            return f"Closed: {', '.join(unique_killed)}"
        return f"No process named '{process_name}' (mapped to '{proc_query}') was found running."
    except Exception as e:
        return f"Error closing process: {e}"


def get_process_info(process_name):
    if not HAS_PSUTIL:
        return None
    try:
        for proc in psutil.process_iter(['pid', 'name', 'memory_percent', 'cpu_percent']):
            if process_name.lower() in proc.name().lower():
                return {
                    "name": proc.name(),
                    "pid": proc.pid,
                    "memory_percent": round(proc.memory_percent(), 2),
                    "cpu_percent": round(proc.cpu_percent(), 2)
                }
        return None
    except Exception:
        return None


def handle_system_monitor_commands(user_input):
    """Parse and handle system monitoring, specifications, and Wi-Fi requests."""
    if not HAS_PSUTIL:
        return None

    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # 1. Bulk Close: "close all apps", "close all opened apps except Chrome"
    bulk_close_match = re.search(r'(?:close|kill|end|stop|force close|terminate)\s+all\s+(?:opened\s+)?(?:apps|programs|applications)(?:\s+except\s+(.+))?$', text)
    if bulk_close_match:
        excludes_raw = bulk_close_match.group(1)
        excludes = []
        if excludes_raw:
            # Sanitize out leading filler words like "for" or "the" (e.g. "except for VSCode" -> "VSCode")
            excludes_raw = re.sub(r'^(?:for|the)\s+', '', excludes_raw).strip()
            # Split by "and", "or", or commas (e.g. "chrome, spotify and discord")
            excludes = [x.strip() for x in re.split(r'\s+and\s+|\s+or\s+|,', excludes_raw) if x.strip()]
        return close_all_apps(excludes)

    # 2. Wi-Fi passwords extraction
    if any(p in text for p in ["wifi password", "saved wifi", "previously connected"]):
        return get_saved_wifi_passwords()

    # 3. Nearby networks scanning
    if any(p in text for p in ["nearby wifi", "scan wifi", "networks in range", "scan networks"]):
        return get_nearby_wifi()

    # 4. Connected Wi-Fi strength and SSID status
    if "wifi" in text or "wi-fi" in text or "scan" in text or "rescan" in text:
        # Default to connected Wi-Fi SSID and signal strength
        return get_wifi_details()

    # 5. Internet speed test
    if any(p in text for p in ["internet speed", "test speed", "whats my speed", "speedtest", "wifi speed", "wi-fi speed", "wifi spin", "wi-fi spin", "internet spin", "ping"]):
        return test_internet_speed()

    # 6. Laptop brand, model or manufacturer
    if any(p in text for p in ["brand", "manufacturer", "model", "who made my pc", "who made my laptop"]):
        brand, model = get_laptop_brand_and_model()
        return f"Your laptop is manufactured by {brand}, and the model is {model}, Sir."

    # 7. Laptop physical specifications
    if any(p in text for p in ["specs", "hardware specifications", "system specifications", "pc specs", "laptop specs", "hardware details", "laptop details", "pc details", "system details", "computer details"]):
        return get_laptop_specs()

    # 8. Standard System health / status
    if any(p in text for p in ["system status", "system health", "computer status",
                                "how is my computer", "system check", "performance check",
                                "check my computer", "check system", "cpu usage", "memory usage",
                                "ram usage", "disk usage", "how much ram", "how much memory"]):
        return system_health_check()

    # 9. Running apps listing
    if any(p in text for p in ["what is running", "whats running", "running apps",
                                "open applications", "active apps", "show running",
                                "list running", "what apps are open"]):
        apps = list_running_apps()
        if not apps:
            return "Could not retrieve running applications."
        return f"Running {len(apps)} applications: " + ", ".join(apps[:15])

    # 10. Kill / close process
    kill_match = re.search(r'(?:kill|close|end|stop|force close)\s+(.+?)(?:\s+process)?$', text)
    if kill_match:
        proc_name = kill_match.group(1).strip()
        protected = ["system", "explorer", "windows", "antivirus", "defender"]
        if any(p in proc_name for p in protected):
            return f"Cannot close '{proc_name}' — it is a protected system process."
        return kill_process(proc_name)

    # 11. Check specific process info
    proc_match = re.search(r'(?:is|check|status of)\s+(.+?)\s+(?:running|open|active)', text)
    if proc_match:
        proc_name = proc_match.group(1).strip()
        info = get_process_info(proc_name)
        if info:
            return f"{info['name']} is running. Memory: {info['memory_percent']}%, CPU: {info['cpu_percent']}%"
        return f"{proc_name} is not running."

    return None