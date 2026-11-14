"""
screenUnderstanding.py — Screen Understanding for JARVIS (UPGRADED 2026-08)
─────────────────────────────────────────────────────────
Captures a screenshot of the active desktop, sends it to Qwen 2.5 VL vision model
(uncensored abliterated variant), and returns a natural-language understanding
of what's on screen.

UPGRADED 2026-08:
    - Switched from LLaVA `/api/generate` → Qwen 2.5 VL `/api/chat` with image blocks
    - Better OCR and screen-text reading
    - Uncensored model (no preaching on sensitive content)
    - Added detail_mode toggle for high-quality analysis (uses llama3.2-vision:11b)

Capabilities:
  - Describe the entire screen
  - Read specific UI text (error messages, dialog boxes, notifications)
  - Suggest the next action based on what's visible
  - Execute UI automation based on screen analysis (via pyautogui)
  - Watch the screen for a specific change and alert when detected
"""

import os
import sys
import re
import time
import base64
import threading
import subprocess
import tempfile
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        SCREEN_VISION_MODEL  = "redule26/huihui_ai_qwen2.5-vl-7b-abliterated"
        VISION_MODEL_DETAIL  = "llama3.2-vision:11b"
        SCREEN_SHOT_RESIZE_W = 1280
        SCREEN_SHOT_RESIZE_H = 720
        OLLAMA_BASE_URL      = "http://localhost:11434"
        BROWSER_SCREENSHOT_PATH = "browser_screenshot.png"

# ── Auto-install deps ─────────────────────────────────────────────────────────
try:
    import pyautogui
    from PIL import Image
    _HAS_GUI = True
except ImportError:
    print("[Screen]: Installing pyautogui and Pillow...")
    subprocess.run([sys.executable, "-m", "pip", "install",
                    "pyautogui", "Pillow", "--break-system-packages"],
                   check=True, capture_output=True)
    try:
        import pyautogui
        from PIL import Image
        _HAS_GUI = True
    except Exception:
        _HAS_GUI = False
        print("[Screen]: pyautogui unavailable — screen control disabled.")

pyautogui.FAILSAFE = True   # Move mouse to top-left corner to abort any action

# ── Screenshot ─────────────────────────────────────────────────────────────────
def capture_screen(save_path: str = None) -> str | None:
    """
    Capture the full desktop screenshot, resize for LLaVA efficiency.
    Returns file path or None on failure.
    """
    if not _HAS_GUI:
        return None
    try:
        path = save_path or os.path.join(tempfile.gettempdir(), "jarvis_screen.jpg")
        img  = pyautogui.screenshot()

        # Resize to configured dimensions — smaller = faster LLaVA inference
        img  = img.resize((config.SCREEN_SHOT_RESIZE_W, config.SCREEN_SHOT_RESIZE_H),
                           Image.LANCZOS)
        img.save(path, "JPEG", quality=92)
        return path
    except Exception as e:
        print(f"[Screen]: Screenshot error: {e}")
        return None

# ── Vision query ───────────────────────────────────────────────────────────────
def ask_llava(image_path: str, prompt: str, max_tokens: int = 300, detail_mode: bool = False) -> str:
    """
    Send a screenshot to the vision model and return the response.

    Tries /api/chat (Qwen 2.5 VL format) first, falls back to /api/generate
    (LLaVA format) if the model returns 400 or other errors.
    Set detail_mode=True to use the higher-quality 11B vision model.
    """
    if not os.path.exists(image_path):
        return "Screenshot file not found."

    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        # Pick model based on detail mode
        model = config.VISION_MODEL_DETAIL if detail_mode else config.SCREEN_VISION_MODEL

        # ── Try /api/chat format first (Qwen 2.5 VL native) ──────────────
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": f"data:image/jpeg;base64,{img_b64}"
                            }
                        ]
                    }
                ],
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.1}
            },
            timeout=60
        )
        if r.status_code == 200:
            result = r.json().get("message", {}).get("content", "").strip()
            if result:
                return result
        # If status != 200, fall through to legacy API
    except requests.exceptions.ConnectionError:
        return "Cannot connect to Ollama. Make sure it is running."
    except Exception as e:
        print(f"[Screen]: /api/chat failed ({e}), trying legacy /api/generate format...")

    # ── Fallback: /api/generate format (LLaVA-style) ──────────────────
    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        model = config.VISION_MODEL_DETAIL if detail_mode else config.SCREEN_VISION_MODEL

        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": 0.1}
            },
            timeout=60
        )
        if r.status_code == 200:
            return r.json().get("response", "").strip()
        return f"Vision model returned status {r.status_code}. Both API formats failed."
    except requests.exceptions.ConnectionError:
        return "Cannot connect to Ollama. Make sure it is running."
    except Exception as e:
        return f"Vision error: {e}"

# ── High-level screen actions ─────────────────────────────────────────────────

def describe_screen() -> str:
    """Capture and describe the full desktop in natural language.
    Also stores the description in vision memory for later recall.
    """
    path = capture_screen()
    if not path:
        return "I was unable to capture the screen, Sir."
    result = ask_llava(
        path,
        "Describe everything visible on this desktop screenshot in detail. "
        "Include: open applications, visible text, any error messages, UI elements, "
        "and what the user appears to be doing.",
        max_tokens=400
    )

    # Store in vision memory for later recall ("what was on my screen earlier?")
    try:
        from vision_memory import get_vision_memory
        vm = get_vision_memory()
        vm.store(path, result, source="screen")
    except Exception as e:
        print(f"[Screen]: Memory store error: {e}")

    _cleanup(path)
    return result

def read_screen_text(target: str = None) -> str:
    """
    Extract readable text from screen — optionally focused on a target area
    (e.g. 'the error dialog', 'the notification', 'the terminal output').
    """
    path = capture_screen()
    if not path:
        return "I was unable to capture the screen, Sir."
    if target:
        prompt = (f"Read and transcribe ALL text visible in '{target}' in this screenshot. "
                  f"Reproduce the exact words you can see. Do not summarize — give the full text.")
    else:
        prompt = ("Read and transcribe all visible text in this screenshot. "
                  "Output only the text content you can see, organized by UI region.")
    result = ask_llava(path, prompt, max_tokens=500)
    _cleanup(path)
    return result

def what_should_i_click(goal: str) -> str:
    """
    Analyze screen and suggest exactly what to click/type to achieve a goal.
    Returns a plain-English action description.
    """
    path = capture_screen()
    if not path:
        return "I was unable to capture the screen, Sir."
    prompt = (f"The user wants to: '{goal}'\n"
              f"Looking at this screenshot, describe in ONE sentence what they should click, "
              f"type, or press next to achieve this goal. Be specific about button labels or field names.")
    result = ask_llava(path, prompt, max_tokens=150)
    _cleanup(path)
    return result

def execute_screen_action(instruction: str) -> str:
    """
    Analyze screen, determine the action, execute it with pyautogui.
    Supports: click visible button/link text, type text, press key.
    """
    if not _HAS_GUI:
        return "Screen control (pyautogui) is not available, Sir."

    path = capture_screen()
    if not path:
        return "Could not capture screen to analyze, Sir."

    # Ask LLaVA what coordinates to click or what key to press
    prompt = (f"User instruction: '{instruction}'\n"
              f"On this screenshot (1280x720), what should happen?\n"
              f"Reply in EXACTLY this format:\n"
              f"ACTION: click | type | press\n"
              f"VALUE: <button text to find> OR <text to type> OR <key name>\n"
              f"REASON: <one sentence why>")
    response = ask_llava(path, prompt, max_tokens=100)
    _cleanup(path)

    # Parse the structured response
    action_match = re.search(r"ACTION:\s*(click|type|press)", response, re.IGNORECASE)
    value_match  = re.search(r"VALUE:\s*(.+)", response, re.IGNORECASE)

    if not action_match or not value_match:
        return f"Screen analysis: {response}"

    action = action_match.group(1).lower()
    value  = value_match.group(1).strip()

    try:
        if action == "click":
            # Locate the element on screen by its text (pyautogui image search)
            # Fallback: use pyautogui.locateCenterOnScreen with the full screenshot
            location = pyautogui.locateOnScreen(path, confidence=0.7)
            if location:
                pyautogui.click(pyautogui.center(location))
                return f"Clicked '{value}' on screen, Sir."
            return (f"I understand I should click '{value}' but could not locate it precisely. "
                    f"Please point it out or move your cursor near it, Sir.")
        elif action == "type":
            pyautogui.typewrite(value, interval=0.04)
            return f"Typed '{value}' on screen, Sir."
        elif action == "press":
            pyautogui.press(value.lower())
            return f"Pressed '{value}' key, Sir."
    except Exception as e:
        return f"Screen action error: {e}"

    return f"Completed: {action} '{value}'."

# ── Screen watcher ─────────────────────────────────────────────────────────────
_watcher_thread  = None
_watcher_stop    = threading.Event()

def watch_for_change(target_description: str, speak_fn, check_interval: int = 5):
    """
    Continuously screenshot and check if the described change has appeared.
    Calls speak_fn when detected. Runs for max 10 minutes.
    Example: watch_for_change("the download has finished", speak)
    """
    global _watcher_thread, _watcher_stop
    _watcher_stop.clear()

    def _watch_loop():
        deadline = time.time() + 600   # 10 minute max
        while not _watcher_stop.is_set() and time.time() < deadline:
            time.sleep(check_interval)
            path = capture_screen()
            if not path:
                continue
            prompt = (f"Is this visible on screen: '{target_description}'? "
                      f"Answer only YES or NO.")
            answer = ask_llava(path, prompt, max_tokens=5)
            _cleanup(path)
            if "yes" in answer.lower():
                msg = f"Sir, I detected that {target_description}."
                print(f"[Screen Watcher]: {msg}")
                speak_fn(msg)
                return
        speak_fn(f"Sir, I stopped watching after 10 minutes without detecting: {target_description}.")

    _watcher_thread = threading.Thread(target=_watch_loop, daemon=True, name="screen-watcher")
    _watcher_thread.start()
    return f"Watching the screen for: '{target_description}'. I will alert you when it appears, Sir."

def stop_watching():
    _watcher_stop.set()
    return "Screen watcher stopped, Sir."

# ── Command router ─────────────────────────────────────────────────────────────
def handle_screen_commands(user_input: str, speak_fn=None) -> str | None:
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # Describe screen
    if any(p in text for p in ["what is on screen", "what is on my screen", "describe screen",
                                "describe my screen", "what do you see on screen",
                                "look at my screen", "read my screen"]):
        return describe_screen()

    # Read specific text
    read_match = re.search(r'read(?: the)?\s+(.+?)(?:\s+on (?:my )?screen)?$', text)
    if read_match and "screen" in text:
        target = read_match.group(1).strip()
        return read_screen_text(target)

    if any(p in text for p in ["read the error", "what does the error say",
                                "what is the error", "read the dialog", "read this notification"]):
        return read_screen_text("error dialog or notification")

    # What should I click
    click_goal = re.search(r'how (?:do i|can i|to)\s+(.+?)(?:\s+on (?:my )?screen)?$', text)
    if click_goal and "screen" in text:
        return what_should_i_click(click_goal.group(1).strip())

    # Execute screen action
    if any(p in text for p in ["on screen click", "click on screen", "on screen type",
                                "on screen press"]):
        action_match = re.search(r'(?:on screen|on my screen)\s+(.+)$', text)
        if action_match:
            return execute_screen_action(action_match.group(1).strip())

    # Watch for change
    watch_match = re.search(r'(?:watch|alert me|notify me|tell me)\s+(?:when|if)\s+(.+)$', text)
    if watch_match and speak_fn:
        return watch_for_change(watch_match.group(1).strip(), speak_fn)

    if any(p in text for p in ["stop watching", "stop screen watch", "cancel screen watch"]):
        return stop_watching()

    return None

# ── Helpers ───────────────────────────────────────────────────────────────────
def _cleanup(path: str):
    try:
        if path and os.path.exists(path) and "jarvis_screen" in path:
            os.remove(path)
    except Exception:
        pass
