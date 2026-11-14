"""
Window Control Module for JARVIS (UPGRADED)
- Minimizes, maximizes, restores, and closes active desktop windows
- Switches focus to specific open programs (e.g., "switch to VS Code")
- Uses native Windows User32 APIs via ctypes for 100% reliable window manipulation
- Includes a Window Alias Map to translate nicknames (e.g., "command prompt" -> "cmd")
"""
import re
import sys
import subprocess
import ctypes

# Win32 ShowWindow States
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010

# ─────────────────────────────────────────────
# WINDOW ALIAS MAP
# Maps colloquial nicknames to keywords found in actual window titles
# ─────────────────────────────────────────────
WINDOW_ALIAS_MAP = {
    "command prompt":     ["cmd", "command prompt", "terminal"],
    "cmd":                ["cmd", "command prompt"],
    "powershell":         ["powershell"],
    "vscode":             ["visual studio code", "code", ".py", ".js"],
    "visual studio code": ["visual studio code", "code"],
    "browser":            ["chrome", "edge", "firefox", "brave"],
    "chrome":             ["google chrome", "chrome"],
    "google chrome":      ["google chrome", "chrome"],
    "spotify":            ["spotify"],
    "discord":            ["discord"],
    "notepad":            ["notepad"],
    "calculator":         ["calculator", "calc"],
    "explorer":           ["explorer", "this pc", "documents", "downloads"],
    "file explorer":      ["explorer", "this pc", "documents", "downloads"]
}

# Auto-install pygetwindow if missing
try:
    import pygetwindow as gw
except ImportError:
    print("[WindowControl]: Installing pygetwindow and pyrect libraries...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "pygetwindow", "pyrect"], check=True)
        import pygetwindow as gw
    except Exception as e:
        print(f"[WindowControl Error]: Could not install pygetwindow: {e}")
        gw = None


def get_active_window_handle():
    """Retrieves the HWND handle of the currently focused window."""
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def get_window_title(hwnd):
    """Retrieves the title of a window by its handle."""
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
    except Exception:
        pass
    return "Unknown Window"


def close_active_window():
    """Closes the currently focused window using native WM_CLOSE messaging."""
    hwnd = get_active_window_handle()
    if hwnd:
        title = get_window_title(hwnd)
        try:
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return f"Closed active window: {title[:50]}."
        except Exception as e:
            return f"Failed to close window: {e}"
    return "No active window found to close, Sir."


def minimize_active_window():
    """Minimizes the currently focused window natively."""
    hwnd = get_active_window_handle()
    if hwnd:
        try:
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            return "Minimized active window, Sir."
        except Exception as e:
            return f"Failed to minimize window: {e}"
    return "No active window found to minimize, Sir."


def maximize_active_window():
    """Maximizes the currently focused window natively."""
    hwnd = get_active_window_handle()
    if hwnd:
        try:
            ctypes.windll.user32.ShowWindow(hwnd, SW_MAXIMIZE)
            return "Maximized active window, Sir."
        except Exception as e:
            return f"Failed to maximize window: {e}"
    return "No active window found to maximize, Sir."


def minimize_all_windows():
    """Minimizes all active windows to show the Desktop, protecting core shell layers."""
    if not gw: return "Window control is not available."
    try:
        windows = gw.getAllWindows()
        count = 0
        for win in windows:
            if win.title and not win.isMinimized and win.title not in ["", "Program Manager"]:
                try:
                    ctypes.windll.user32.ShowWindow(win._hWnd, SW_MINIMIZE)
                    count += 1
                except Exception:
                    pass
        return f"Minimized {count} windows. Showing Desktop, Sir."
    except Exception as e:
        return f"Error minimizing windows: {e}"


def restore_all_windows():
    """Restores/un-minimizes all active windows in memory."""
    if not gw: return "Window control is not available."
    try:
        windows = gw.getAllWindows()
        count = 0
        for win in windows:
            if win.title and win.isMinimized:
                try:
                    ctypes.windll.user32.ShowWindow(win._hWnd, SW_RESTORE)
                    count += 1
                except Exception:
                    pass
        return f"Restored {count} windows, Sir."
    except Exception as e:
        return f"Error restoring windows: {e}"


def find_window_by_name(name):
    """Fuzzy searches active window titles using aliases and keywords."""
    if not gw: return None
    query = name.lower().strip()
    
    # 1. Expand the query using our Alias Map (e.g. "command prompt" -> ["cmd", "command prompt"])
    search_keywords = [query]
    if query in WINDOW_ALIAS_MAP:
        search_keywords.extend(WINDOW_ALIAS_MAP[query])

    try:
        all_windows = gw.getWindowsWithTitle("")
        
        # 2. Level 1 Search: Look for any keyword inside the window title
        for win in all_windows:
            win_title = win.title.lower()
            if any(keyword in win_title for keyword in search_keywords):
                return win
                
        # 3. Level 2 Search: Split keywords and look for partial word overlaps
        words_in_query = set(query.split())
        for win in all_windows:
            win_words = set(win.title.lower().split())
            if words_in_query & win_words:
                return win
    except Exception:
        pass
    return None


def focus_window(app_name):
    """Brings a specific running window to the front natively, bypassing Focus Stealing Prevention."""
    win = find_window_by_name(app_name)
    if win:
        try:
            # Restore/Un-minimize first
            ctypes.windll.user32.ShowWindow(win._hWnd, SW_RESTORE)
            
            # Simulate a tap of the system ALT key to unlock Focus Stealing Prevention
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)      # ALT Key Down
            ctypes.windll.user32.SetForegroundWindow(win._hWnd)   # Force Foreground
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)      # ALT Key Up
            
            return f"Switched to {win.title[:40]}, Sir."
        except Exception as e:
            return f"Found '{app_name}', but could not activate focus: {e}"
    return f"I couldn't find any active window matching '{app_name}' on your desktop, Sir."


def handle_window_commands(user_input):
    """Parse and handle window manipulation commands."""
    if not gw: return None
        
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())
    
    # 1. Minimize All / Show Desktop
    if any(p in text for p in ["minimize all", "show desktop", "hide all windows", "clear screen"]):
        return minimize_all_windows()
        
    # 2. Restore All
    if any(p in text for p in ["restore all", "show all windows", "bring back windows"]):
        return restore_all_windows()

    # 3. Minimize specific window
    minimize_match = re.search(r'(?:minimize|hide)\s+(?:the\s+)?(?:active\s+)?(?:window\s+)?(?:called|named|for\s+)?(.+)?$', text)
    if minimize_match:
        app_name = minimize_match.group(1)
        if not app_name or app_name.strip() in ["it", "this", "window", "active"]:
            return minimize_active_window()
        win = find_window_by_name(app_name.strip())
        if win:
            ctypes.windll.user32.ShowWindow(win._hWnd, SW_MINIMIZE)
            return f"Minimized {win.title[:40]}."
        return f"Could not find any window matching '{app_name}'."

    # 4. Maximize specific window
    maximize_match = re.search(r'(?:maximize|expand|full screen)\s+(?:the\s+)?(?:active\s+)?(?:window\s+)?(?:called|named|for\s+)?(.+)?$', text)
    if maximize_match:
        app_name = maximize_match.group(1)
        if not app_name or app_name.strip() in ["it", "this", "window", "active"]:
            return maximize_active_window()
        win = find_window_by_name(app_name.strip())
        if win:
            ctypes.windll.user32.ShowWindow(win._hWnd, SW_MAXIMIZE)
            return f"Maximized {win.title[:40]}."
        return f"Could not find any window matching '{app_name}'."

    # 5. Focus/Switch window
    focus_match = re.search(r'(?:switch to|focus|show|bring up|go to)\s+(?:the\s+)?(?:window\s+)?(?:called|named\s+)?(.+)$', text)
    if focus_match:
        app_name = focus_match.group(1).strip()
        if not any(w in app_name for w in ["file", "document", "notepad"]):
            return focus_window(app_name)

    # 6. Close active window
    if any(p in text for p in ["close this window", "close active window", "close current window"]):
        return close_active_window()

    return None