import os
import sys
import time
import shutil
import threading
import subprocess

try:
    import psutil
except ImportError:
    psutil = None

# Optional Windows API imports
try:
    import win32gui
    import win32process
    import win32api
    import win32con
    import pywintypes  # For WMI COM Exception Handling
except ImportError:
    win32gui = None
    win32process = None
    win32api = None
    win32con = None
    pywintypes = None

# Add root folder to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        BATTERY_WARN_LOW      = 20
        BATTERY_WARN_CRIT     = 10
        CPU_TEMP_THRESHOLD    = 85
        DISK_FREE_WARN_GB     = 5
        IDLE_TIMEOUT_MINUTES  = 5

# Callbacks for alerts
_speak_callback = print

def register_speak_callback(cb):
    global _speak_callback
    _speak_callback = cb

def log_alert(msg):
    """Prints the system log and vocalizes it cleanly. No screen overlays."""
    print(f"[BodyAwareness Alert]: {msg}")
    if _speak_callback:
        _speak_callback(msg)

# ── 1. ACTIVE WINDOW WATCHER ──────────────────────────────────────────────────
_last_active_window = None

def get_active_window_title():
    if win32gui:
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            return title
        except Exception:
            return None
    else:
        # Fallback to PowerShell
        try:
            cmd = '(Get-Process | Where-Object {$_.MainWindowHandle -eq (Get-ForegroundWindow)}).MainWindowTitle'
            out = subprocess.check_output(["powershell", "-Command", cmd], text=True, timeout=2).strip()
            return out if out else None
        except Exception:
            return None

def _window_watcher_loop():
    global _last_active_window
    while True:
        try:
            title = get_active_window_title()
            if title and title != _last_active_window:
                # Fire event (silent log, or alert if user requested tracking)
                _last_active_window = title
                # We don't speak window changes to avoid annoying the user, but we track it.
        except Exception:
            pass
        time.sleep(2)

def start_window_watcher():
    t = threading.Thread(target=_window_watcher_loop, daemon=True)
    t.start()

# ── 2. BATTERY MONITOR ────────────────────────────────────────────────────────
def _battery_monitor_loop():
    last_state = None  # (percent, plugged)
    warned_low = False
    warned_crit = False
    
    while True:
        if psutil:
            try:
                battery = psutil.sensors_battery()
                if battery:
                    pct = battery.percent
                    plugged = battery.power_plugged
                    
                    if last_state:
                        old_plugged = last_state[1]
                        if plugged and not old_plugged:
                            log_alert("Sir, the charger has been connected.")
                            warned_low = False
                            warned_crit = False
                        elif not plugged and old_plugged:
                            log_alert("Sir, the charger was disconnected. Running on battery power.")
                    
                    # Alert thresholds
                    if not plugged:
                        if pct <= config.BATTERY_WARN_CRIT and not warned_crit:
                            log_alert(f"Warning, Sir. The battery is critically low at {pct} percent. Please connect the charger immediately.")
                            warned_crit = True
                        elif pct <= config.BATTERY_WARN_LOW and not warned_low:
                            log_alert(f"Sir, the battery is low at {pct} percent.")
                            warned_low = True
                    else:
                        warned_low = False
                        warned_crit = False
                        
                    last_state = (pct, plugged)
            except Exception:
                pass
        time.sleep(10)

def start_battery_monitor():
    t = threading.Thread(target=_battery_monitor_loop, daemon=True)
    t.start()

# ── 3. THERMAL MONITOR ────────────────────────────────────────────────────────
def get_cpu_temperature():
    """Tries multiple methods to get CPU temp on Windows."""
    # Method 1: WMI MSAcpi_ThermalZoneTemperature (needs admin)
    try:
        cmd = 'wmic /namespace:\\\\root\\wmi PATH MSAcpi_ThermalZoneTemperature get CurrentTemperature'
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = out.strip().split('\n')
        if len(lines) > 1:
            raw_temp = int(lines[1].strip())
            # WMI temperature is in tenths of Kelvin
            celsius = (raw_temp / 10.0) - 273.15
            return round(celsius, 1)
    except Exception:
        pass
    
    # Method 2: OpenHardwareMonitor WMI (if OHM is running)
    try:
        cmd = 'wmic /namespace:\\\\root\\OpenHardwareMonitor PATH Sensor WHERE "SensorType=\'Temperature\' AND Name LIKE \'%CPU Core%\'" get Value'
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = out.strip().split('\n')
        if len(lines) > 1:
            return round(float(lines[1].strip()), 1)
    except Exception:
        pass

    return None

def _thermal_monitor_loop():
    warned_thermal = False
    while True:
        try:
            temp = get_cpu_temperature()
            if temp and temp > config.CPU_TEMP_THRESHOLD:
                if not warned_thermal:
                    log_alert(f"Alert, Sir! The CPU temperature is running hot at {temp} degrees Celsius. System load should be reduced.")
                    warned_thermal = True
            else:
                warned_thermal = False
        except Exception:
            pass
        time.sleep(15)

def start_thermal_monitor():
    t = threading.Thread(target=_thermal_monitor_loop, daemon=True)
    t.start()

# ── 4. DISK HEALTH & SMART STATUS ─────────────────────────────────────────────
def check_disk_health():
    """Checks SMART status and free space. Returns dictionary of stats."""
    smart_status = "Unknown"
    try:
        out = subprocess.check_output('wmic diskdrive get status', shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = [line.strip() for line in out.strip().split('\n') if line.strip() and 'Status' not in line]
        if lines:
            smart_status = ", ".join(lines)
    except Exception:
        pass

    drive = os.path.splitdrive(os.path.abspath(__file__))[0] or "C:"
    total, used, free = shutil.disk_usage(drive)
    free_gb = free / (1024**3)
    total_gb = total / (1024**3)
    
    return {
        "smart_status": smart_status,
        "free_gb": round(free_gb, 1),
        "total_gb": round(total_gb, 1),
        "free_percent": round((free / total) * 100, 1)
    }

# ── 5. NETWORK MONITOR ────────────────────────────────────────────────────────
def is_connected_to_internet():
    """
    Uses a raw socket connection to Google DNS (8.8.8.8:53).
    Much faster and more reliable than subprocess ping.
    No ICMP packets — no Windows firewall interference.
    """
    try:
        import socket
        socket.setdefaulttimeout(3)
        with socket.create_connection(("8.8.8.8", 53)):
            return True
    except OSError:
        return False

def _network_monitor_loop():
    """
    Requires 3 consecutive failures before declaring connection lost.
    Requires 2 consecutive successes before declaring connection restored.
    This eliminates all false positives from single-packet drops.
    """
    last_online = is_connected_to_internet()
    failure_count = 0
    success_count = 0
    FAIL_THRESHOLD    = 3   # consecutive failures needed to declare offline
    RESTORE_THRESHOLD = 2   # consecutive successes needed to declare restored

    while True:
        try:
            online = is_connected_to_internet()

            if online:
                failure_count = 0
                success_count += 1

                # Only fire restored alert after N consecutive successes
                # AND only if we were previously declared offline
                if not last_online and success_count >= RESTORE_THRESHOLD:
                    log_alert("Sir, internet connection has been restored.")
                    last_online = True
                    success_count = 0

            else:
                success_count = 0
                failure_count += 1

                # Only fire lost alert after N consecutive failures
                if last_online and failure_count >= FAIL_THRESHOLD:
                    log_alert("Sir, the internet connection has been lost. Running in local-only mode.")
                    last_online = False
                    failure_count = 0

        except Exception:
            pass

        time.sleep(10)

def start_network_monitor():
    t = threading.Thread(target=_network_monitor_loop, daemon=True)
    t.start()

# ── 6. IDLE DETECTOR ──────────────────────────────────────────────────────────
def get_seconds_since_last_input():
    if win32api:
        try:
            last_input_tick = win32api.GetLastInputInfo()
            current_tick = win32api.GetTickCount()
            return (current_tick - last_input_tick) / 1000.0
        except Exception:
            pass
    return 0.0

def _idle_detector_loop():
    alerted_idle = False
    while True:
        try:
            idle_secs = get_seconds_since_last_input()
            idle_mins = idle_secs / 60.0
            if idle_mins >= config.IDLE_TIMEOUT_MINUTES:
                if not alerted_idle:
                    log_alert("Still with you, Sir. Say hey Jarvis if you need me.")
                    alerted_idle = True
            else:
                alerted_idle = False
        except Exception:
            pass
        time.sleep(30)

def start_idle_detector():
    if win32api:
        t = threading.Thread(target=_idle_detector_loop, daemon=True)
        t.start()

# ── 7. ADVANCED HARDWARE DEVICE & DRIVE MONITOR (Event-Driven) ─────────────────

_last_notified_devices = {}
_DEBOUNCE_INTERVAL_SECS = 5.0

# Coordinated Pipelined Cache States
_pending_hardware_name = None
_pending_hardware_time = 0.0

def get_drive_letters():
    """Reads logical drive volumes using fast native Win32 calls."""
    if win32api:
        try:
            drives = win32api.GetLogicalDriveStrings()
            return set(drives.split('\x00')[:-1])
        except Exception:
            return set()
    else:
        # Fallback if win32api is missing
        drives = set()
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if os.path.exists(f"{letter}:\\"):
                drives.add(f"{letter}:\\")
        return drives

def _should_notify_device(name):
    """Filters out generic WMI drivers, hubs, and restricts duplicate triggers."""
    global _last_notified_devices
    
    ignore_keywords = [
        "composite device", "input device", "root hub", "generic hub", "hub",  # FIXED: Added "hub" directly to ignore Generic Hubs
        "mass storage device", "controller", "virtual", "host controller",
        "parent", "endpoint", "volume", "device descriptor"
    ]
    name_lower = name.lower()
    
    # Filter out Windows background hub/composite layers
    if any(k in name_lower for k in ignore_keywords):
        return False
        
    now = time.time()
    # Suppress duplicate alerts for the exact same hardware name within 5s
    if name in _last_notified_devices:
        if now - _last_notified_devices[name] < _DEBOUNCE_INTERVAL_SECS:
            return False
            
    _last_notified_devices[name] = now
    return True

def _device_monitor_loop():
    """
    Event-driven background thread utilizing Windows WMI Notification Queries.
    Blocks cleanly at the OS level until a Plug-and-Play USB device change occurs.
    Also handles storage volume letter mapping queries.
    """
    global _pending_hardware_name, _pending_hardware_time
    
    # Initialize COM library for this background thread
    import pythoncom
    pythoncom.CoInitialize()
    
    import win32com.client
    try:
        wmi = win32com.client.GetObject("winmgmts:")
        
        # Query to watch for insertion of any PnP Entity where the DeviceID starts with 'USB'
        insertion_query = (
            "SELECT * FROM __InstanceCreationEvent WITHIN 2 "
            "WHERE TargetInstance ISA 'Win32_PnPEntity' "
            "AND TargetInstance.DeviceID LIKE 'USB%'"
        )
        
        # Query to watch for removal
        removal_query = (
            "SELECT * FROM __InstanceDeletionEvent WITHIN 2 "
            "WHERE TargetInstance ISA 'Win32_PnPEntity' "
            "AND TargetInstance.DeviceID LIKE 'USB%'"
        )
        
        insert_watcher = wmi.ExecNotificationQuery(insertion_query)
        remove_watcher = wmi.ExecNotificationQuery(removal_query)
        
        print("[BodyAwareness]: Advanced Coordinated Hardware Monitor active.")
        
        # Instantiate active drive records for initial state comparison
        last_drives = get_drive_letters()
        last_drive_check_time = time.time()
        
        while True:
            # 1. Check WMI Plug-and-Play Events (waits up to 1000ms)
            try:
                event = insert_watcher.NextEvent(1000)
                device = event.TargetInstance
                name = device.Name or "Unknown Hardware"
                if _should_notify_device(name):
                    # Check if the hardware is a potential storage drive
                    if "device" in name.lower() or "usb" in name.lower() or "disk" in name.lower():
                        # FIXED: Pipeline the announcement! Don't speak yet; wait 3 seconds for the drive mount letter
                        _pending_hardware_name = name
                        _pending_hardware_time = time.time()
                    else:
                        # Non-storage hardware (mouse, camera, etc.) -> Announce immediately
                        log_alert(f"Sir, new hardware connected: {name}.")
            except (pywintypes.com_error, NameError, AttributeError):
                pass
                
            try:
                event = remove_watcher.NextEvent(1000)
                device = event.TargetInstance
                name = device.Name or "Unknown Hardware"
                if _should_notify_device(name):
                    # For removals, we don't need to wait; announce immediately
                    log_alert(f"Sir, hardware disconnected: {name}.")
            except (pywintypes.com_error, NameError, AttributeError):
                pass
                
            # 2. Check Logical Drive Mount Letters (Run check once every 2 seconds)
            now = time.time()
            if now - last_drive_check_time >= 2.0:
                try:
                    current_drives = get_drive_letters()
                    added = current_drives - last_drives
                    removed = last_drives - current_drives
                    
                    if added:
                        drive_str = ', '.join(added)
                        # FIXED: Check if we have a pending hardware name to merge
                        if _pending_hardware_name and (now - _pending_hardware_time < 3.0):
                            log_alert(f"Sir, new storage drive detected: {_pending_hardware_name} on {drive_str}.")
                            _pending_hardware_name = None  # Consume the pending flag
                        else:
                            log_alert(f"Sir, new external storage drive detected: {drive_str}.")
                            
                    if removed:
                        log_alert(f"Sir, storage drive removed: {', '.join(removed)}.")
                        
                    last_drives = current_drives
                except Exception:
                    pass
                last_drive_check_time = now
                
            # 3. Flush expired pending hardware announcements (if no drive letter mounted within 3 seconds)
            if _pending_hardware_name and (now - _pending_hardware_time >= 3.0):
                log_alert(f"Sir, new hardware connected: {_pending_hardware_name}.")
                _pending_hardware_name = None  # Consume the pending flag
                
    except Exception as e:
        print(f"[Device Monitor Error]: {e}")
    finally:
        pythoncom.CoUninitialize()

def start_device_monitor():
    """Spawns the advanced PnP hardware monitor thread."""
    t = threading.Thread(target=_device_monitor_loop, daemon=True)
    t.start()

# ── 8. FULL DIAGNOSTICS ───────────────────────────────────────────────────────
def run_full_diagnostics():
    """Runs all checks and returns a comprehensive markdown diagnostic report."""
    disk = check_disk_health()
    online = is_connected_to_internet()
    active_win = get_active_window_title() or "None"
    
    battery_info = "Not available"
    if psutil:
        batt = psutil.sensors_battery()
        if batt:
            status = "Charging" if batt.power_plugged else "Discharging"
            battery_info = f"{batt.percent}% ({status})"
            
    temp = get_cpu_temperature()
    temp_str = f"{temp} C" if temp else "Not available"
    temp_note_line = "" if temp else "- **CPU Temperature Note**: Windows often blocks this sensor in a normal terminal. Run JARVIS as Administrator, or run OpenHardwareMonitor, if you want CPU temperature included."
    
    cpu_usage = psutil.cpu_percent(interval=0.5) if psutil else "Unknown"
    ram = psutil.virtual_memory() if psutil else None
    ram_usage = f"{ram.percent}% of {round(ram.total / (1024**3), 1)} GB" if ram else "Unknown"
    
    report = f"""# JARVIS System Diagnostics Report
- **Status**: Systems fully operational.
- **Internet Status**: {"Online" if online else "Offline"}
- **Battery**: {battery_info}
- **CPU Temperature**: {temp_str}
{temp_note_line}
- **CPU Usage**: {cpu_usage}%
- **RAM Usage**: {ram_usage}
- **Active Window**: {active_win}
- **Disk Space**: {disk['free_gb']} GB free of {disk['total_gb']} GB ({disk['free_percent']}% free)
- **Disk SMART Health**: {disk['smart_status']}
"""
    return report

def start_all_monitors(speak_cb=None):
    if speak_cb:
        register_speak_callback(speak_cb)
    
    start_window_watcher()
    start_battery_monitor()
    start_thermal_monitor()
    start_network_monitor()
    start_idle_detector()
    start_device_monitor()
    print("[BodyAwareness]: All hardware event monitors running.")
