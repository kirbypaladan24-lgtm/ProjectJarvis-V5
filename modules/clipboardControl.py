"""
Clipboard Control Module for JARVIS
- Reads and writes to the Windows clipboard (using pyperclip)
- Prepares text context (grammar, translation, summaries) for LLM ingestion
- Safely writes clipboard scripts to disk for background execution
"""
import subprocess
import sys
import re

# Auto-install pyperclip if missing
try:
    import pyperclip
except ImportError:
    print("[Clipboard]: Installing pyperclip library...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyperclip"], check=True)
    import pyperclip


def get_clipboard():
    """Reads the current plaintext content of the Windows clipboard."""
    try:
        return pyperclip.paste().strip()
    except Exception as e:
        return f"Error reading clipboard: {e}"


def set_clipboard(text):
    """Writes plaintext content back onto the Windows clipboard."""
    try:
        pyperclip.copy(text)
        return "Copied to clipboard successfully, Sir."
    except Exception as e:
        return f"Error writing to clipboard: {e}"


def handle_clipboard_commands(user_input):
    """Parse and handle clipboard-related commands."""
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())
    
    has_clipboard = any(w in text for w in ["clipboard", "copied", "copy", "whats on", "what is on"])
    
    # Check for developer "run code" commands
    if "run" in text and ("code" in text or "script" in text):
        content = get_clipboard()
        if not content:
            return "Your clipboard is currently empty, Sir."
        return f"[RUN_CLIPBOARD_CODE] Content:\n{content}"

    # General reading/modifying queries
    wants_read = any(w in text for w in ["read", "get", "show", "explain", "summarize", "translate", "fix", "correct", "analyze"])
    
    if wants_read or has_clipboard:
        content = get_clipboard()
        if not content:
            return "Your clipboard is currently empty, Sir."
        if content.startswith("Error:"):
            return content
        return f"[CLIPBOARD_CONTENT] Content:\n{content}"
        
    return None