"""
browserAgent.py — Playwright Browser Agent for JARVIS
──────────────────────────────────────────────────────
Gives JARVIS full browser control:
  - Navigate to any URL
  - Click elements by text, label, or role
  - Fill forms by field label or placeholder
  - Scrape structured page content
  - Screenshot the active page
  - AI-guided actions via LLaVA vision + Ollama reasoning

All actions go through the existing approval_gate for safety.
Browser instance persists across commands in the session (reused, not relaunched).

Install: pip install playwright && playwright install chromium
"""

import os
import sys
import re
import subprocess
import threading
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        BROWSER_HEADLESS        = False
        BROWSER_TIMEOUT_MS      = 15000
        BROWSER_SCREENSHOT_PATH = "browser_screenshot.png"
        OLLAMA_BASE_URL         = "http://localhost:11434"
        VOICE_FACE_MODEL        = "qwen2.5:7b-instruct"

# ── Auto-install Playwright ───────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    _HAS_PLAYWRIGHT = True
except ImportError:
    print("[Browser]: Installing playwright...")
    subprocess.run([sys.executable, "-m", "pip", "install", "playwright",
                    "--break-system-packages"], check=True, capture_output=True)
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       capture_output=True)
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
        _HAS_PLAYWRIGHT = True
    except Exception as e:
        print(f"[Browser]: Could not install Playwright: {e}")
        _HAS_PLAYWRIGHT = False

# ── Singleton browser state ───────────────────────────────────────────────────
_pw_instance  = None
_browser      = None
_page         = None
_browser_lock = threading.Lock()

def _get_page():
    """Return the active Playwright page, launching the browser if needed."""
    global _pw_instance, _browser, _page
    with _browser_lock:
        if _page is not None and not _page.is_closed():
            return _page
        if _pw_instance is None:
            _pw_instance = sync_playwright().start()
        _browser = _pw_instance.chromium.launch(headless=config.BROWSER_HEADLESS)
        ctx      = _browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        _page = ctx.new_page()
        _page.set_default_timeout(config.BROWSER_TIMEOUT_MS)
    return _page

def close_browser():
    """Close the browser session cleanly."""
    global _pw_instance, _browser, _page
    with _browser_lock:
        try:
            if _page:
                _page.close()
            if _browser:
                _browser.close()
            if _pw_instance:
                _pw_instance.stop()
        except Exception:
            pass
        _page = _browser = _pw_instance = None

# ── Core actions ──────────────────────────────────────────────────────────────

def navigate(url):
    """Navigate to a URL. Prepends https:// if no scheme given."""
    if not _HAS_PLAYWRIGHT:
        return "Browser agent is not available. Run: pip install playwright && playwright install chromium"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        page = _get_page()
        page.goto(url, wait_until="domcontentloaded")
        title = page.title()
        return f"Navigated to {url}. Page title: {title}"
    except Exception as e:
        return f"Navigation error: {e}"


def click_element(target):
    """
    Click an element by visible text, ARIA label, or CSS selector.
    Tries multiple strategies in order of reliability.
    """
    if not _HAS_PLAYWRIGHT:
        return "Browser agent is not available."
    try:
        page = _get_page()
        # Strategy 1: Exact text match button/link
        for role in ["button", "link", "menuitem"]:
            try:
                page.get_by_role(role, name=re.compile(target, re.IGNORECASE)).first.click()
                return f"Clicked '{target}'."
            except Exception:
                pass
        # Strategy 2: Any element containing the text
        try:
            page.locator(f"text={target}").first.click()
            return f"Clicked element containing '{target}'."
        except Exception:
            pass
        # Strategy 3: CSS/XPath selector directly
        try:
            page.locator(target).first.click()
            return f"Clicked selector '{target}'."
        except Exception:
            pass
        return f"Could not find a clickable element matching '{target}' on the current page, Sir."
    except Exception as e:
        return f"Click error: {e}"


def fill_form(fields: dict):
    """
    Fill multiple form fields. fields = {"label or placeholder": "value", ...}
    Example: fill_form({"Email": "me@example.com", "Password": "hunter2"})
    """
    if not _HAS_PLAYWRIGHT:
        return "Browser agent is not available."
    results = []
    try:
        page = _get_page()
        for label, value in fields.items():
            filled = False
            # Try by label text
            try:
                page.get_by_label(re.compile(label, re.IGNORECASE)).first.fill(str(value))
                filled = True
            except Exception:
                pass
            # Try by placeholder
            if not filled:
                try:
                    page.get_by_placeholder(re.compile(label, re.IGNORECASE)).first.fill(str(value))
                    filled = True
                except Exception:
                    pass
            # Try by name attribute
            if not filled:
                try:
                    page.locator(f"input[name*='{label}']").first.fill(str(value))
                    filled = True
                except Exception:
                    pass
            results.append(f"{'Filled' if filled else 'Could not find'} '{label}'")
        return "Form progress: " + ", ".join(results) + "."
    except Exception as e:
        return f"Form fill error: {e}"


def submit_form():
    """Press Enter or click the most likely submit button on the current page."""
    if not _HAS_PLAYWRIGHT:
        return "Browser agent is not available."
    try:
        page = _get_page()
        for label in ["submit", "sign in", "log in", "login", "search", "go", "send", "continue"]:
            try:
                page.get_by_role("button", name=re.compile(label, re.IGNORECASE)).first.click()
                return f"Clicked submit button."
            except Exception:
                pass
        page.keyboard.press("Enter")
        return "Pressed Enter to submit."
    except Exception as e:
        return f"Submit error: {e}"


def scrape_page(query=None):
    """
    Return clean readable text from the current page.
    If query is given, only return the most relevant paragraph.
    """
    if not _HAS_PLAYWRIGHT:
        return "Browser agent is not available."
    try:
        page  = _get_page()
        title = page.title()
        url   = page.url

        # Extract readable text — strip scripts, styles, nav
        text  = page.evaluate("""() => {
            const remove = document.querySelectorAll('script,style,nav,footer,header,aside');
            remove.forEach(el => el.remove());
            return document.body ? document.body.innerText : '';
        }""")

        # Clean up whitespace
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
        body  = "\n".join(lines[:80])   # First 80 meaningful lines

        if query:
            # Return the most relevant paragraph (simple keyword scoring)
            query_words = set(query.lower().split())
            scored = []
            for para in lines:
                score = sum(1 for w in query_words if w in para.lower())
                if score > 0:
                    scored.append((score, para))
            scored.sort(reverse=True)
            if scored:
                return f"From '{title}' ({url}):\n" + "\n".join(p for _, p in scored[:5])

        return f"Page: {title} ({url})\n\n{body[:3000]}"
    except Exception as e:
        return f"Scrape error: {e}"


def take_screenshot(save_path=None):
    """Take a screenshot of the current page and return the file path."""
    if not _HAS_PLAYWRIGHT:
        return None
    try:
        page = _get_page()
        path = save_path or config.BROWSER_SCREENSHOT_PATH
        page.screenshot(path=path, full_page=False)
        return path
    except Exception as e:
        print(f"[Browser]: Screenshot error: {e}")
        return None


def search_google(query):
    """Open Google and search for a query, then return scraped results."""
    if not _HAS_PLAYWRIGHT:
        return "Browser agent is not available."
    try:
        page = _get_page()
        import urllib.parse
        url  = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        page.goto(url, wait_until="domcontentloaded")
        return scrape_page(query=query)
    except Exception as e:
        return f"Google search error: {e}"


def get_current_url():
    """Return the URL of the currently open page."""
    if not _HAS_PLAYWRIGHT:
        return "Browser agent is not available."
    try:
        return _get_page().url
    except Exception:
        return "No page is currently open."


# ── AI-assisted action (LLaVA vision) ────────────────────────────────────────
def ai_guided_action(instruction):
    """
    Screenshot the current page, send to LLaVA vision model, get the next action.
    Used for complex pages where CSS selectors are unreliable.
    """
    import base64
    path = take_screenshot()
    if not path or not os.path.exists(path):
        return "Could not take a screenshot to analyze the page, Sir."

    with open(path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = f"""You are JARVIS controlling a web browser for the user.
The current page screenshot is attached.
User instruction: "{instruction}"

Describe in plain English EXACTLY what element to click or what text to type to complete this instruction.
Be specific: use button labels, link text, or field names visible on screen.
Reply in one sentence."""

    try:
        r = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": "llava:7b",
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"num_predict": 100, "temperature": 0.1}
            },
            timeout=30
        )
        if r.status_code == 200:
            action = r.json().get("response", "").strip()
            return f"Vision analysis: {action}"
    except Exception as e:
        return f"Vision-guided action error: {e}"
    return "Could not analyze the page visually."


# ── Command router ────────────────────────────────────────────────────────────
def handle_browser_commands(user_input):
    """
    Parse and execute browser commands from natural language.
    Returns response string or None if not a browser command.
    """
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # Navigate
    nav_match = re.search(
        r'(?:open|go to|navigate to|browse to|visit|take me to)\s+(.+)$', text)
    if nav_match:
        target = nav_match.group(1).strip()
        # Check if it looks like a URL or known site
        if any(x in target for x in [".", "http", "www", "youtube", "google", "github",
                                      "facebook", "twitter", "instagram", "reddit",
                                      "spotify", "gmail", "linkedin", "amazon"]):
            # Convert spoken site names to URLs
            known = {
                "youtube": "youtube.com", "google": "google.com",
                "github": "github.com", "facebook": "facebook.com",
                "twitter": "twitter.com", "instagram": "instagram.com",
                "reddit": "reddit.com", "gmail": "mail.google.com",
                "linkedin": "linkedin.com", "amazon": "amazon.com",
            }
            for name, url in known.items():
                if name in target and "." not in target:
                    target = url
                    break
            return navigate(target)

    # Google search via browser
    browser_search = re.search(
        r'(?:browser search|search in browser|google in browser|open browser and search)\s+(?:for\s+)?(.+)$',
        text)
    if browser_search:
        return search_google(browser_search.group(1).strip())

    # Click
    click_match = re.search(r'(?:click|press|tap|select)\s+(?:the\s+)?(?:button\s+)?["\']?(.+?)["\']?(?:\s+button)?$', text)
    if click_match and any(w in text for w in ["click", "press", "tap", "select"]):
        target = click_match.group(1).strip()
        skip = ["screenshot", "photo", "picture", "image"]
        if not any(s in target for s in skip):
            return click_element(target)

    # Screenshot
    if any(p in text for p in ["browser screenshot", "screenshot the browser",
                                "screenshot the page", "screenshot the website",
                                "capture the page", "capture the screen"]):
        path = take_screenshot()
        if path:
            return f"Screenshot saved to {path}, Sir."
        return "Could not take a browser screenshot."

    # What page / current URL
    if any(p in text for p in ["what page", "current page", "what site", "what url",
                                "where is the browser", "what website"]):
        return f"The browser is currently at: {get_current_url()}"

    # Scrape / read page
    if any(p in text for p in ["read the page", "scrape the page", "what does the page say",
                                "read this website", "what is on the page"]):
        return scrape_page()

    # Submit / confirm
    if any(p in text for p in ["submit the form", "click submit", "press submit",
                                "confirm the form", "send the form"]):
        return submit_form()

    # Close browser
    if any(p in text for p in ["close browser", "close the browser", "shut the browser",
                                "exit browser"]):
        close_browser()
        return "Browser closed, Sir."

    # AI-guided action
    ai_match = re.search(r'(?:in the browser|on the page|on the website)\s+(.+)$', text)
    if ai_match:
        return ai_guided_action(ai_match.group(1).strip())

    return None
