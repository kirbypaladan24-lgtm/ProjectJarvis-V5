"""
System Control Module for JARVIS
- Master volume adjustments via Windows Core Audio (pycaw) (Supports old/new Pycaw & Multi-threading)
- Monitor brightness adjustments via screen_brightness_control
- Dynamic Windows app launching, silent uninstallations, and web-app browser fallbacks
- Supports recursive multi-app launching (e.g., "open Chrome and Spotify")
"""
import subprocess
import re
import os
import sys
import webbrowser

# ─────────────────────────────────────────────
# VOLUME CONTROL
# ─────────────────────────────────────────────

def _get_volume_interface():
    """Get the Windows audio volume interface securely, supporting both old and new Pycaw APIs and multi-threading."""
    # Initialize COM on the active background thread if it hasn't been called yet (fixes CoInitialize error)
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass

    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL

    devices = AudioUtilities.GetSpeakers()
    
    # 1. New Pycaw API Check (GetSpeakers returns an AudioDevice wrapper with .EndpointVolume)
    if hasattr(devices, 'EndpointVolume') and devices.EndpointVolume:
        return devices.EndpointVolume

    # 2. Old Pycaw API Fallback (GetSpeakers returns a raw IMMDevice COM pointer)
    try:
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except (AttributeError, Exception):
        # 3. Secure COM Fallback if Activate fails
        try:
            import comtypes.client
            # If devices is an AudioDevice wrapper, extract the underlying COM pointer (_device)
            com_dev = devices._device if hasattr(devices, '_device') else devices
            interface = comtypes.client.CreateObject(
                com_dev,
                interface=IAudioEndpointVolume
            )
            return cast(interface, POINTER(IAudioEndpointVolume))
        except Exception as e:
            raise Exception(f"Failed to initialize master volume interface: {e}")


def set_volume(percent):
    """Set master system volume to a percentage (0-100)."""
    try:
        percent = max(0, min(100, int(percent)))
        volume = _get_volume_interface()
        volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
        return f"System volume set to {percent} percent."
    except Exception as e:
        return f"Volume control error: {e}"


def get_volume():
    """Get current master system volume."""
    try:
        volume = _get_volume_interface()
        current = round(volume.GetMasterVolumeLevelScalar() * 100)
        return f"Current system volume is {current} percent."
    except Exception as e:
        return f"Volume read error: {e}"


# ─────────────────────────────────────────────
# BRIGHTNESS CONTROL
# ─────────────────────────────────────────────

# BRIGHTNESS CONTROL
# ─────────────────────────────────────────────
# Three-path fallback so brightness works on any Windows machine:
#   1. screen_brightness_control (sbc) — works when WMI COM is registered
#   2. PowerShell WMI direct call — bypasses sbc's COM layer
#   3. PowerShell SetBrightness via Monitor API — works on most laptops

def _ps_set_brightness(percent: int) -> bool:
    """Set brightness via PowerShell WMI — bypasses screen_brightness_control COM."""
    percent = max(0, min(100, percent))
    ps_script = (
        f"$mon = Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods; "
        f"$mon.WmiSetBrightness(1, {percent})"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=6
        )
        return r.returncode == 0 and "error" not in r.stderr.lower()
    except Exception:
        return False

def _ps_get_brightness() -> int | None:
    """Read brightness via PowerShell WMI."""
    ps_script = (
        "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=6
        )
        val = r.stdout.strip()
        return int(val) if val.isdigit() else None
    except Exception:
        return None

def _ps_set_brightness_fallback(percent: int) -> bool:
    """Last-resort: use PowerShell's (Get-Brightness) + SendKeys workaround via nircmd if available."""
    try:
        # Try nircmd — lightweight freeware CLI tool common on Windows
        r = subprocess.run(
            ["nircmd", "setbrightness", str(percent)],
            capture_output=True, text=True, timeout=5
        )
        return r.returncode == 0
    except FileNotFoundError:
        pass
    return False


def set_brightness(percent):
    """Set screen brightness to a percentage (0–100). Three-path fallback."""
    percent = max(0, min(100, int(percent)))

    # Path 1: screen_brightness_control
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(percent)
        return f"Brightness set to {percent} percent, Sir."
    except Exception:
        pass

    # Path 2: PowerShell WMI direct
    if _ps_set_brightness(percent):
        return f"Brightness set to {percent} percent, Sir."

    # Path 3: nircmd
    if _ps_set_brightness_fallback(percent):
        return f"Brightness set to {percent} percent, Sir."

    return (f"Brightness control is unavailable on this display, Sir. "
            f"Your monitor may not support software brightness control "
            f"(common on external displays). Adjust it manually using the monitor's buttons.")


def get_brightness() -> str:
    """Get current screen brightness. Falls back to PowerShell WMI."""
    # Path 1: sbc
    try:
        import screen_brightness_control as sbc
        current = sbc.get_brightness()
        if isinstance(current, list):
            current = current[0]
        return f"Current brightness is {current} percent, Sir."
    except Exception:
        pass

    # Path 2: PowerShell WMI
    val = _ps_get_brightness()
    if val is not None:
        return f"Current brightness is {val} percent, Sir."

    return "I was unable to read the current brightness level, Sir."




# ─────────────────────────────────────────────
# APP LAUNCHER & WEB-APP SHORTCUTS
# ─────────────────────────────────────────────

# Built-in Windows app shortcuts & Web-App Fallbacks (Automatically opens in default browser)
BUILTIN_APP_MAP = {
    "chrome":             "chrome",
    "google chrome":      "chrome",
    "firefox":            "firefox",
    "edge":               "msedge",
    "microsoft edge":     "msedge",
    "notepad":            "notepad",
    "calculator":         "calc",
    "calc":               "calc",
    "paint":              "mspaint",
    "file explorer":      "explorer",
    "explorer":           "explorer",
    "task manager":       "taskmgr",
    "control panel":      "control",
    "settings":           "ms-settings:",
    "word":               "winword",
    "microsoft word":     "winword",
    "excel":              "excel",
    "microsoft excel":    "excel",
    "powerpoint":         "powerpnt",
    "vlc":                "vlc",
    "spotify":            "spotify",
    "discord":            "discord",
    "steam":              "steam",
    "vscode":             "code",
    "visual studio code": "code",
    "vs code":            "code",
    "cmd":                "cmd",
    "command prompt":     "cmd",
    "powershell":         "powershell",
    "terminal":           "wt",
    "windows terminal":   "wt",
    "snipping tool":      "snippingtool",
    "camera":             "microsoft.windows.camera:",
    "photos":             "ms-photos:",
    "maps":               "bingmaps:",
    "clock":              "ms-clock:",
    "calendar":           "outlookcal:",
    "mail":               "outlookmail:",
    "weather":            "bingweather:",
    "store":              "ms-windows-store:",
    "microsoft store":    "ms-windows-store:",
    "brave":              "brave",
    "opera":              "opera",
    "obs":                "obs64",
    "obs studio":         "obs64",
    "zoom":               "zoom",
    "teams":              "msteams",
    "microsoft teams":    "msteams",
    "slack":              "slack",
    "telegram":           "telegram",
    "whatsapp":           "whatsapp",
    "skype":              "skype",
    "blender":            "blender",
    "unity":              "unity",
    "android studio":     "studio64",
    "git":                "git-bash",
    "github desktop":     "githubdesktop",
    "postman":            "postman",
    "figma":              "figma",
    "notion":             "notion",
    
    # Web-App Fallbacks (Zero-latency web redirection)
    "canva":              "https://www.canva.com",
    "youtube":            "https://www.youtube.com",
    "gmail":              "https://www.gmail.com",
    "google mail":        "https://www.gmail.com",
    "netflix":            "https://www.netflix.com",
    "facebook":           "https://www.facebook.com",
    "github":             "https://www.github.com",
    "chatgpt":            "https://chat.openai.com",
    "claude":             "https://claude.ai",
    "twitter":            "https://www.twitter.com",
    "x":                  "https://www.x.com",
    "google classroom":   "https://classroom.google.com",
    "classroom":          "https://classroom.google.com",
    "gclass":             "https://classroom.google.com"
}

# Folders to scan for shortcuts and executables
SEARCH_PATHS = [
    os.path.expanduser(r"~\Desktop"),
    os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"),
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    os.path.expanduser(r"~\AppData\Local\Programs"),
    r"C:\Program Files",
    r"C:\Program Files (x86)",
]

_app_cache = {}


def scan_installed_apps():
    global _app_cache
    if _app_cache:
        return _app_cache

    found = {}
    extensions = (".lnk", ".exe", ".url")

    for folder in SEARCH_PATHS:
        if not os.path.exists(folder):
            continue
        for root, dirs, files in os.walk(folder):
            # Skip deep Program Files subdirectories to keep it fast
            depth = root.replace(folder, "").count(os.sep)
            if depth > 3:
                dirs.clear()
                continue
            for fname in files:
                if fname.lower().endswith(extensions):
                    name = os.path.splitext(fname)[0].lower().strip()
                    full_path = os.path.join(root, fname)
                    found[name] = full_path

    _app_cache = found
    return found


def find_best_app_match(query):
    query_lower = query.lower().strip()

    if query_lower in BUILTIN_APP_MAP:
        return query, BUILTIN_APP_MAP[query_lower]

    apps = scan_installed_apps()

    if query_lower in apps:
        return query_lower, apps[query_lower]

    partial_matches = [(name, path) for name, path in apps.items() if query_lower in name]
    if partial_matches:
        partial_matches.sort(key=lambda x: len(x[0]))
        return partial_matches[0]

    reverse_matches = [(name, path) for name, path in apps.items() if name in query_lower]
    if reverse_matches:
        reverse_matches.sort(key=lambda x: len(x[0]), reverse=True)
        return reverse_matches[0]

    query_words = set(query_lower.split())
    scored = []
    for name, path in apps.items():
        name_words = set(name.split())
        overlap = len(query_words & name_words)
        if overlap > 0:
            scored.append((overlap, name, path))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1], scored[0][2]

    return None


def open_app(app_name):
    """Open any application — focuses existing windows first, or launches new/Webbrowser URLs using start shell."""
    query_lower = app_name.lower().strip()

    def _start_windows_target(target):
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)

    # 1. Smart Connection Check: If the app is already open, focus it instead of launching a new one
    try:
        from windowControl import find_window_by_name, focus_window
        # Translate colloquial name to executable mapping (e.g. "visual studio code" -> "code")
        win_query = query_lower
        if win_query in BUILTIN_APP_MAP:
            win_query = BUILTIN_APP_MAP[win_query]
            
        win = find_window_by_name(win_query)
        if win:
            focus_msg = focus_window(win_query)
            return f"Found an active session. {focus_msg}"
    except Exception as e:
        print(f"[Launcher Sync Warning]: {e}")

    # 2. Check if the user wants to open multiple apps (contains 'and', 'or', or commas)
    if any(split_word in query_lower for split_word in [" and ", " or ", ","]):
        apps_to_open = [x.strip() for x in re.split(r'\s+and\s+|\s+or\s+|,', query_lower) if x.strip()]
        if len(apps_to_open) > 1:
            results = []
            for single_app in apps_to_open:
                res = open_app(single_app) # Recursive call
                results.append(res)
            return " ".join(results)

    # Always scan installed apps first
    apps = scan_installed_apps()

    # 3. Exact match in scanned apps
    if query_lower in apps:
        try:
            os.startfile(apps[query_lower])
            return f"Opening {app_name}."
        except Exception as e:
            return f"Could not open {app_name}: {e}"

    # 4. Partial match in scanned apps
    partial = [(name, path) for name, path in apps.items() if query_lower in name]
    if partial:
        partial.sort(key=lambda x: len(x[0]), reverse=True)
        name, path = partial[0]
        try:
            os.startfile(path)
            return f"Opening {app_name}."
        except Exception as e:
            return f"Could not open {app_name}: {e}"

    # 5. Built-in map & Web-App Fallback
    if query_lower in BUILTIN_APP_MAP:
        target = BUILTIN_APP_MAP[query_lower]
        try:
            # If the target is a Web URL, open it in default browser
            if target.startswith(("http://", "https://")):
                webbrowser.open(target)
                return f"Opening {app_name} in your default web browser, Sir."
            else:
                # 💡 FIX: Use the Windows "start" command to automatically query the App Paths Registry.
                # This ensures apps like chrome, msedge, discord open even if missing from your %PATH%.
                _start_windows_target(target)
                return f"Opening {app_name}."
        except Exception as e:
            return f"Could not open {app_name}: {e}"

    # 6. Fuzzy Word Overlap Match
    query_words = set(query_lower.split())
    scored = []
    for name, path in apps.items():
        name_words = set(name.split())
        overlap = len(query_words & name_words)
        if overlap > 0:
            scored.append((overlap, name, path))
    if scored:
        scored.sort(reverse=True)
        _, name, path = scored[0]
        try:
            os.startfile(path)
            return f"Opening {app_name}."
        except Exception as e:
            return f"Could not open {app_name}: {e}"

    # 7. Last resort — ask Windows to find it
    try:
        _start_windows_target(app_name)
        return f"Trying to open {app_name}."
    except Exception as e:
        return f"Could not find '{app_name}'."

# ─────────────────────────────────────────────
# APP UNINSTALLER
# ─────────────────────────────────────────────

def uninstall_app(app_name):
    """Uninstall an application using Windows built-in tools."""
    try:
        # Use winget if available (Windows 10/11)
        result = subprocess.run(
            ["winget", "uninstall", "--name", app_name, "--silent"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return f"{app_name} has been uninstalled successfully."
        else:
            # Fallback: open Programs and Features for manual uninstall
            subprocess.Popen(
                ["control", "appwiz.cpl"],
                shell=True
            )
            return f"Could not auto-uninstall {app_name}. Opening Programs and Features so you can remove it manually."
    except FileNotFoundError:
        # winget not found, open Programs and Features
        subprocess.Popen(["control", "appwiz.cpl"], shell=True)
        return f"Winget is not available. Opening Programs and Features for manual uninstall."
    except Exception as e:
        return f"Uninstall error: {e}"\
        
    # ─────────────────────────────────────────────
# OS POWER CONTROLS (Shutdown & Sleep)
# ─────────────────────────────────────────────

def shutdown_system(speak_fn=None):
    """Safely closes active applications and initiates a native Windows shutdown sequence."""
    try:
        # 1. Close active desktop applications first to prevent data loss
        try:
            import sys
            import os
            modules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
            if modules_path not in sys.path:
                sys.path.insert(0, modules_path)
                
            from systemMonitor import close_all_apps
            print("[Power Control]: Closing all active user applications...")
            close_all_apps()
        except Exception as e:
            print(f"[Power Control Warning]: Could not close apps: {e}")
            pass
            
        msg = "Initiating system power down sequence. Goodbye, Sir."
        print(f"[Power Control]: {msg}")
        
        if speak_fn:
            speak_fn(msg)
            
        # Give the voice engine 2 seconds to finish speaking before triggering shutdown
        import time
        time.sleep(2.0)
            
        # 2. Push native Windows Goodbye Message Box right before shutdown
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "Goodbye, Sir. Powering off system...", "JARVIS Power Control", 0x40 | 0x10000)
        except Exception:
            pass
            
        # 3. Trigger native Windows shutdown (with a 5-second safety delay)
        os.system("shutdown /s /t 5")
        return "System shutting down."
    except Exception as e:
        return f"Error initiating shutdown: {e}"


def sleep_system(speak_fn=None):
    """Puts the monitor into a black, low-power state while keeping JARVIS's ears active."""
    try:
        msg = "Suspending system power states. I am keeping my background ears active, Sir. Sleep well."
        print(f"[Power Control]: {msg}")
        
        if speak_fn:
            speak_fn(msg)
            
        import time
        time.sleep(2.5) # Let the voice finish speaking
        
        import ctypes
        # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) | ES_AWAYMODE_REQUIRED (0x00000040)
        # Instructs Windows to enter Away Mode (screen off, low power, background execution preserved)
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000040)
        
        # Turn off the primary monitor (non-blocking WM_SYSCOMMAND broadcast)
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        
        return "System suspended."
    except Exception as e:
        return f"Error putting system to sleep: {e}"


def wake_system(speak_fn=None):
    """Restores native Windows CPU metrics and wakes up the monitor."""
    try:
        import ctypes
        # Reset Thread Execution State back to standard continuous execution
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        
        # Turn on the primary monitor
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, -1)
        
        # Simulate a 1-pixel mouse move to bypass lock-screens or screensavers instantly
        ctypes.windll.user32.mouse_event(1, 1, 1, 0, 0)
        
        msg = "I am awake, Sir. Welcome back."
        print(f"[Power Control]: {msg}")
        
        if speak_fn:
            speak_fn(msg)
            
        return "System awake."
    except Exception as e:
        return f"Error waking system: {e}"

# ─────────────────────────────────────────────
# COMMAND PARSER — called from JARVIS
# ─────────────────────────────────────────────

def handle_system_command(user_input):
    """
    Parse user input for system control commands.
    Returns a response string if a command was handled, or None if not a system command.
    """
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # ── VOLUME ────────────────────────────────
    vol_set = re.search(r'(?:set|change|adjust|turn)?\s*volume\s*(?:to|at)?\s*(\d+)\s*(?:percent|%)?', text)
    vol_up  = re.search(r'volume\s*(?:up|higher|increase|louder)', text)
    vol_down= re.search(r'volume\s*(?:down|lower|decrease|quieter|softer)', text)
    vol_get = re.search(r'(?:what(?:\'s| is)(?: the)? volume|current volume|volume level)', text)
    mute    = re.search(r'\b(?:mute|silence)(?: the)?(?: volume| sound)?\b', text)
    unmute  = re.search(r'\b(?:unmute|restore)(?: the)?(?: volume| sound)?\b', text)

    if vol_set:
        return set_volume(int(vol_set.group(1)))
    if mute:
        return set_volume(0)
    if unmute:
        return set_volume(50)
    if vol_up:
        try:
            volume = _get_volume_interface()
            current = round(volume.GetMasterVolumeLevelScalar() * 100)
            return set_volume(min(100, current + 10))
        except Exception as e:
            return f"Volume error: {e}"
    if vol_down:
        try:
            volume = _get_volume_interface()
            current = round(volume.GetMasterVolumeLevelScalar() * 100)
            return set_volume(max(0, current - 10))
        except Exception as e:
            return f"Volume error: {e}"
    if vol_get:
        return get_volume()

    # ── BRIGHTNESS ────────────────────────────
    bri_set = re.search(r'(?:set|change|adjust|turn)?\s*brightness\s*(?:to|at)?\s*(\d+)\s*(?:percent|%)?', text)
    bri_up  = re.search(r'brightness\s*(?:up|higher|increase)', text)
    bri_down= re.search(r'brightness\s*(?:down|lower|decrease|dim)', text)
    bri_get = re.search(r'(?:what(?:\'s| is)(?: the)? brightness|current brightness|brightness level)', text)

    if bri_set:
        return set_brightness(int(bri_set.group(1)))
    if bri_up:
        current = _ps_get_brightness()
        if current is None:
            try:
                import screen_brightness_control as sbc
                current = sbc.get_brightness()
                if isinstance(current, list): current = current[0]
            except Exception:
                current = 50
        return set_brightness(min(100, current + 10))
    if bri_down:
        current = _ps_get_brightness()
        if current is None:
            try:
                import screen_brightness_control as sbc
                current = sbc.get_brightness()
                if isinstance(current, list): current = current[0]
            except Exception:
                current = 50
        return set_brightness(max(0, current - 10))
    if bri_get:
        return get_brightness()

    # ── OPEN APP ──────────────────────────────
    open_match = re.search(
        r'(?:open|launch|start|run)\s+(.+?)(?:\s+(?:app|application|program|software))?$',
        text
    )
    if open_match:
        app_name = open_match.group(1).strip()
        return open_app(app_name)

    # ── UNINSTALL APP ─────────────────────────
    uninstall_match = re.search(
        r'(?:uninstall|remove|delete)\s+(.+?)(?:\s+(?:app|application|program|software))?$',
        text
    )
    if uninstall_match:
        app_name = uninstall_match.group(1).strip()
        return uninstall_app(app_name)

    return None


# Test
if __name__ == "__main__":
    print(set_volume(50))
    print(get_volume())
    print(get_brightness())

     # Test edit
