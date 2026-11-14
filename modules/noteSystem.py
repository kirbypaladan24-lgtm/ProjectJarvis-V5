"""
Note Taking & Screen OCR Module for JARVIS
- JSON notes (primary storage, always used)
- Notepad writer (extension — opens Windows Notepad with content)
- Screenshot capture (saves to OneDrive/Pictures/Screenshots folder)
- Context-aware follow-up command routing (e.g., "write that to notepad")
- Silent background file saving (e.g., "write that to a file named specs.txt")
- Optical Character Recognition (OCR) Screen-Reader (via pytesseract) with flexible keyword matching
"""
import json
import os
import re
import subprocess
import tempfile
import time
import shutil
from datetime import datetime

# __file__ is inside modules/ — go one level up to get the project root
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES_FILE = os.path.join(BASE_DIR, "notes.json")

# Screenshot and File save locations
# Screenshots now save to OneDrive/Pictures/Screenshots (user's preferred location)
SCREENSHOT_DIR = r"C:\Users\user\OneDrive\Pictures\Screenshots"
DESKTOP_DIR    = os.path.join(os.path.expanduser("~"), "Desktop")

# Auto-install pytesseract if missing
try:
    import pytesseract
    HAS_TESSERACT_LIB = True
except ImportError:
    print("[NoteSystem]: Installing pytesseract library...")
    try:
        import sys
        subprocess.run([sys.executable, "-m", "pip", "install", "pytesseract"], check=True)
        import pytesseract
        HAS_TESSERACT_LIB = True
    except:
        HAS_TESSERACT_LIB = False

# Auto-configure standard Windows Tesseract path
if HAS_TESSERACT_LIB:
    standard_tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    standard_tess_x86  = r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
    user_tess_path     = os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe")
    
    if os.path.exists(standard_tess_path):
        pytesseract.pytesseract.tesseract_cmd = standard_tess_path
    elif os.path.exists(standard_tess_x86):
        pytesseract.pytesseract.tesseract_cmd = standard_tess_x86
    elif os.path.exists(user_tess_path):
        pytesseract.pytesseract.tesseract_cmd = user_tess_path
    else:
        # Check system PATH
        path_check = shutil.which("tesseract")
        if path_check:
            pytesseract.pytesseract.tesseract_cmd = path_check


def load_notes():
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_notes(notes):
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(notes, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[NoteSystem Error]: {e}")


def save_note(title, content, tags=None):
    try:
        notes = load_notes()
        note = {
            "id": len(notes) + 1,
            "title": title[:80],
            "content": content,
            "tags": tags or [],
            "created_at": datetime.now().isoformat(),
            "modified_at": datetime.now().isoformat()
        }
        notes.append(note)
        save_notes(notes)
        return f"Note saved: {title[:50]}"
    except Exception as e:
        return f"Error saving note: {e}"


def search_notes(query):
    try:
        notes = load_notes()
        results = []
        for note in notes:
            if (query.lower() in note["title"].lower() or
                query.lower() in note["content"].lower() or
                any(query.lower() in tag.lower() for tag in note.get("tags", []))):
                results.append(note)
        return results
    except Exception:
        return []


def delete_note(note_id):
    try:
        notes = load_notes()
        original_len = len(notes)
        notes = [n for n in notes if n["id"] != note_id]
        if len(notes) < original_len:
            save_notes(notes)
            return "Note deleted."
        return "Note not found."
    except Exception as e:
        return f"Error deleting note: {e}"


def list_all_notes():
    try:
        notes = load_notes()
        if not notes:
            return "No notes saved yet."
        output = f"You have {len(notes)} note(s):\n"
        for note in notes[-10:]:
            output += f"  {note['id']}. {note['title'][:50]}\n"
        return output
    except Exception as e:
        return f"Error listing notes: {e}"


def write_to_notepad(title, content):
    """
    Write content to a .txt file and open it in Notepad.
    Also saves to JSON notes so it's searchable.
    """
    try:
        # Save to JSON as well
        save_note(title, content, tags=["notepad"])

        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:60]
        timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename   = f"{safe_title}_{timestamp}.txt"
        txt_path   = os.path.join(BASE_DIR, "notes_txt", filename)

        os.makedirs(os.path.dirname(txt_path), exist_ok=True)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"{title}\n")
            f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("-" * 40 + "\n\n")
            f.write(content)

        subprocess.Popen(["notepad.exe", txt_path])
        return f"Opened in Notepad: {filename}"

    except Exception as e:
        return f"Could not open Notepad: {e}"


def write_to_file(filename, content, folder_path=None):
    """Saves text content to a physical file on the Windows Desktop silently."""
    try:
        if not folder_path:
            folder_path = DESKTOP_DIR
            
        os.makedirs(folder_path, exist_ok=True)
        
        safe_filename = re.sub(r'[\\/:*?"<>|]', '_', filename).strip()
        if not safe_filename.lower().endswith((".txt", ".md", ".log", ".py", ".json")):
            safe_filename += ".txt"
            
        filepath = os.path.join(folder_path, safe_filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
            
        save_note(safe_filename, content, tags=["file_saved"])
        return f"File saved successfully to Desktop as '{safe_filename}'."
    except Exception as e:
        return f"Error writing file: {e}"


def open_note_in_notepad(note_id):
    """Open an existing JSON note in Notepad."""
    try:
        notes = load_notes()
        note  = next((n for n in notes if n["id"] == note_id), None)
        if not note:
            return f"Note {note_id} not found."
        return write_to_notepad(note["title"], note["content"])
    except Exception as e:
        return f"Error opening note: {e}"


def take_screenshot(filename=None):
    """Take a screenshot and save it to OneDrive/Pictures/Screenshots."""
    try:
        try:
            from PIL import ImageGrab
        except ImportError:
            print("[Screenshot]: Installing Pillow...")
            import sys
            subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
            from PIL import ImageGrab

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename  = f"screenshot_{timestamp}.png"

        if not filename.lower().endswith(".png"):
            filename += ".png"

        save_path = os.path.join(SCREENSHOT_DIR, filename)

        img = ImageGrab.grab()
        img.save(save_path)

        return f"Screenshot saved to OneDrive/Pictures/Screenshots/{filename}"

    except Exception as e:
        return f"Screenshot error: {e}"


def take_screenshot_and_open(filename=None):
    """Take a screenshot and open it immediately."""
    result = take_screenshot(filename)
    if "saved to" in result:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = filename if filename else f"screenshot_{timestamp}.png"
            if not fname.lower().endswith(".png"):
                fname += ".png"
            path = os.path.join(SCREENSHOT_DIR, fname)
            if os.path.exists(path):
                os.startfile(path)
        except Exception:
            pass
    return result


def read_screen_text():
    """Captures the active monitor, extracts any visible text using OCR, and returns it."""
    if not HAS_TESSERACT_LIB:
        return "Error: The pytesseract library is not loaded on your system."

    # Validate if the physical Tesseract binary path is configured correctly
    tess_exe = getattr(pytesseract.pytesseract, "tesseract_cmd", None)
    if not tess_exe or not os.path.exists(tess_exe):
        # Scan common installation paths
        common_paths = [
            shutil.which("tesseract"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe")
        ]
        for p in common_paths:
            if p and os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break
        else:
            # If the binary is missing, provide the winget command
            return "[TESSERACT_MISSING_BINARY] Sir, I cannot read your screen because the Tesseract-OCR engine binary is missing. Install it with 'winget install UB.TesseractOCR', then restart the terminal so PATH updates."

    try:
        from PIL import ImageGrab
        print("[NoteSystem]: Capturing screen and executing OCR analysis...")
        
        # Grab primary monitor
        img = ImageGrab.grab()
        
        # Extract text via Tesseract
        text = pytesseract.image_to_string(img)
        
        if not text.strip():
            return "I scanned your screen, but I couldn't find any visible or readable text, Sir."
            
        return text.strip()
    except Exception as e:
        return f"Error executing OCR screen scan: {e}"


def handle_note_commands(user_input, context_text=None):
    """Parse and handle note, screenshot, context-based writing, and OCR commands with keyword tolerance."""
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    wants_save = any(w in text for w in ["write", "put", "save", "log", "keep", "create"])
    wants_notepad = any(w in text for w in ["notepad", "note band", "noteband"])
    wants_file = any(w in text for w in ["file", "document", "txt"])
    has_pronoun = any(p in text.split() for p in ["that", "this", "it", "them", "those", "details", "info", "information", "specs", "specifications", "hardware", "brand"])
    
    # Check if they specified a file name
    name_match = re.search(r'(?:named|called|save as|filename)\s+(\S+)', text)
    specified_name = name_match.group(1).strip() if name_match else None

    # Detect if they are asking to write specific diagnostic/specs context
    wants_context_data = any(w in text for w in ["wifi", "wi-fi", "speed", "spin", "ping", "specs", "specifications", "hardware", "brand", "model", "details"])
    
    # 💡 UPGRADED ACTIVE SCREEN-READER OVERRIDE (Resolves apostrophes and contractions)
    # Triggers if 'screen' is present alongside any reading/scanning keywords
    wants_ocr = "screen" in text and any(w in text for w in ["read", "whats on", "what's on", "what is on", "scan", "ocr", "see"])
    
    if wants_ocr:
        ocr_result = read_screen_text()
        if ocr_result.startswith("[TESSERACT_MISSING_BINARY]"):
            return ocr_result
        if ocr_result.startswith("Error") or ocr_result.startswith("I scanned"):
            return ocr_result
        return f"[OCR_SCREEN_CONTENT] Content:\n{ocr_result}"

    # 2. Context-based silent file writing
    if wants_save and wants_file and not wants_notepad:
        if context_text:
            clean_context = context_text.replace("---", "").strip()
            clean_context = clean_context.replace("`", "")
            
            if specified_name:
                filename = specified_name
            else:
                filename = "saved_context.txt"
                lines = [line.strip() for line in clean_context.split('\n') if line.strip()]
                for line in lines:
                    if len(line) > 5 and not line.startswith("Sir") and not line.startswith("Here"):
                        filename = re.sub(r'[^a-zA-Z0-9]', '_', line[:35]).strip('_').lower() + ".txt"
                        break
            
            return write_to_file(filename, clean_context)
        return "I do not have any previous conversational details cached to write to a file, Sir."

    # 3. Context-based notepad writing (e.g. "write specs" or "write that in notepad")
    if wants_save and (wants_notepad or has_pronoun or wants_context_data) and not wants_file:
        if context_text:
            clean_context = context_text.replace("---", "").strip()
            clean_context = clean_context.replace("`", "")
            title = "Saved Context"
            lines = [line.strip() for line in clean_context.split('\n') if line.strip()]
            for line in lines:
                if len(line) > 5 and not line.startswith("Sir") and not line.startswith("Here"):
                    title = line[:50]
                    break
            return write_to_notepad(title, clean_context)
        elif wants_notepad:
            pass
        else:
            return "I do not have any previous conversational details cached to write down, Sir."

    # 4. SCREENSHOT
    screenshot_triggers = [
        "take a screenshot", "take screenshot", "screenshot",
        "capture screen", "capture my screen", "screen capture",
        "snap my screen", "save screenshot", "grab screenshot"
    ]
    if any(p in text for p in screenshot_triggers):
        name_match = re.search(r'(?:named?|called?|save as|filename)\s+(.+)$', text)
        fname = name_match.group(1).strip() if name_match else None
        open_after = any(p in text for p in ["and open", "then open", "show me", "open it"])
        if open_after:
            return take_screenshot_and_open(fname)
        return take_screenshot(fname)

    # 5. WRITE TO NOTEPAD (Direct content writing)
    notepad_write_triggers = [
        r'(?:write|put|type|open notepad (?:and )?write|open notepad with)\s+(?:in|into|to)?\s*(?:notepad)?\s*(.+)$',
        r'(?:open notepad and (?:write|type))\s+(.+)$',
        r'(?:notepad)\s+(.+)$',
    ]
    for pattern in notepad_write_triggers:
        match = re.search(pattern, text)
        if match:
            content = match.group(1).strip()
            if content and len(content) > 3:
                title = content[:60]
                return write_to_notepad(title, content)

    # "Write [content] in notepad"
    write_match = re.search(r'write\s+(.+?)\s+(?:in|into|to)\s+notepad', text)
    if write_match:
        content = write_match.group(1).strip()
        title   = content[:60]
        return write_to_notepad(title, content)

    # Open existing note in Notepad
    open_notepad_match = re.search(r'open\s+note\s+(\d+)\s+in\s+notepad', text)
    if open_notepad_match:
        return open_note_in_notepad(int(open_notepad_match.group(1)))

    # 6. JSON NOTE COMMANDS
    save_patterns = [
        r'(?:note that|note|remember that|remember|save note|create note|write down)\s+(?:that\s+)?(.+)$',
        r'(?:jot down|add note)\s+(.+)$',
    ]
    for pattern in save_patterns:
        match = re.search(pattern, text)
        if match:
            content = match.group(1).strip()
            return save_note(content[:60], content)

    search_patterns = [
        r'(?:find|search|show|get)\s+(?:my\s+)?note(?:s)?\s+(?:about|on|for|with)\s+(.+)$',
        r'note(?:s)?\s+(?:about|on|for)\s+(.+)$',
    ]
    for pattern in search_patterns:
        match = re.search(pattern, text)
        if match:
            query   = match.group(1).strip()
            results = search_notes(query)
            if results:
                response = f"Found {len(results)} note(s) about '{query}':\n"
                for note in results[:3]:
                    response += f"  - {note['title'][:50]}\n"
                    snippet   = note['content'][:100]
                    response += f"    {snippet}{'...' if len(note['content']) > 100 else ''}\n"
                return response
            return f"No notes found about '{query}'."

    if any(p in text for p in ["show my notes", "list notes", "all notes", "my notes", "show notes"]):
        return list_all_notes()

    delete_match = re.search(r'(?:delete|remove|erase)\s+note\s+(\d+)', text)
    if delete_match:
        return delete_note(int(delete_match.group(1)))

    return None
