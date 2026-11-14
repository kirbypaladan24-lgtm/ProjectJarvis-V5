"""
File Search and Management Module for JARVIS
- Text extraction for standard files (.txt, .py, .json, .md, .log, .csv, etc.)
- Native PDF extraction fallback via pypdf (with auto-install check)
- Native Word Document fallback via docx (with auto-install check)
- Context-aware follow-up command routing
- Conversational query sanitization (strips "the", "file", "my" from searches)
- Instant local confirmation (yes/no) handling for active sessions
- Alphanumeric normalization to match files regardless of spaces, hyphens, or underscores
- Automatic Context Search (parses previous messages for filenames to open them)
- Active Duplicate Scanner (scans hard drive for identical filenames)
- Conversational Path Locator (reads and returns exact physical file paths)
"""
import os
import sys
import subprocess
import re
import threading
from datetime import datetime

MAX_SEARCH_RESULTS = 10

# Folders to search — user's main areas only, skip system dirs
SEARCH_ROOTS = [
    os.path.expanduser("~\\Desktop"),
    os.path.expanduser("~\\Documents"),
    os.path.expanduser("~\\Downloads"),
    os.path.expanduser("~\\Pictures"),
    os.path.expanduser("~\\Videos"),
    os.path.expanduser("~\\Music"),
    os.path.expanduser("~\\OneDrive"),
]


def normalize_string(s):
    """Strips all non-alphanumeric characters and converts to lowercase for fuzzy symbol matching."""
    return re.sub(r'[^a-zA-Z0-9]', '', s).lower()


def search_files(query, search_path=None, file_type=None):
    """Search for files matching query using alphanumeric normalization. Returns list of full paths."""
    roots = [search_path] if search_path else SEARCH_ROOTS
    results = []

    # Get the normalized search query (e.g. "jarvis test" -> "jarvistest")
    normalized_query = normalize_string(query)
    if not normalized_query:
        return []

    for root in roots:
        if not os.path.exists(root):
            continue
        try:
            for dirpath, dirs, files in os.walk(root):
                # Skip hidden and system folders
                dirs[:] = [d for d in dirs if not d.startswith('.')
                           and d.lower() not in ('node_modules', '__pycache__', '.git', 'cache', 'temp')]

                for fname in files:
                    if file_type and not fname.lower().endswith(file_type.lower()):
                        continue

                    # Normalize both the filename with and without its extension
                    name_only, _ = os.path.splitext(fname)
                    normalized_name_only = normalize_string(name_only)
                    normalized_full_name = normalize_string(fname)

                    # Match if the normalized query is a substring of the normalized filename
                    if normalized_query in normalized_name_only or normalized_query in normalized_full_name:
                        results.append(os.path.join(dirpath, fname))
                        if len(results) >= MAX_SEARCH_RESULTS:
                            return results
        except (PermissionError, OSError):
            continue

    return results


def open_file_with_default_app(filepath):
    """Open a file with its default application."""
    try:
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        os.startfile(filepath)
        return f"Opening {os.path.basename(filepath)}."
    except Exception as e:
        return f"Could not open file: {e}"


def get_file_info(filepath):
    """Get information about a file."""
    try:
        if not os.path.exists(filepath):
            return None
        stat = os.stat(filepath)
        size_mb = stat.st_size / (1024 * 1024)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        return {
            "name": os.path.basename(filepath),
            "path": filepath,
            "size_mb": round(size_mb, 2),
            "modified": modified,
            "extension": os.path.splitext(filepath)[1]
        }
    except Exception as e:
        print(f"[FileSearch Error]: {e}")
        return None


def read_file_content(filepath, max_chars=4000):
    """Reads the content of text files safely, with PDF and DOCX fallback checks."""
    if not os.path.exists(filepath):
        return f"Error: File not found at {filepath}"

    try:
        file_size = os.path.getsize(filepath)
        if file_size > 10 * 1024 * 1024:  # 10MB limit
            return f"Error: File is too large ({file_size / (1024*1024):.1f} MB) to read safely."
    except Exception as e:
        return f"Error checking file size: {e}"

    ext = os.path.splitext(filepath)[1].lower()

    # Binary and media file extensions that cannot be read as text
    binary_extensions = [
        '.exe', '.dll', '.so', '.bin', '.dat', '.zip', '.tar', '.gz', '.rar',
        '.7z', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.mp3', '.mp4',
        '.wav', '.avi', '.mkv', '.mov', '.sys', '.lnk'
    ]
    if ext in binary_extensions:
        return "Error: This is a binary or media file. I can currently only read text-based files."

    # PDF Reader Fallback
    if ext == '.pdf':
        try:
            import pypdf
        except ImportError:
            print("[FileSearch]: Installing 'pypdf' library...")
            subprocess.run([sys.executable, "-m", "pip", "install", "pypdf"], check=True)
            import pypdf
        try:
            reader = pypdf.PdfReader(filepath)
            text = ""
            for i in range(min(len(reader.pages), 5)):  # Limit to first 5 pages
                page_text = reader.pages[i].extract_text()
                if page_text:
                    text += page_text + "\n"
            return text[:max_chars] if text else "Error: Could not extract text from this PDF."
        except Exception as e:
            return f"Error reading PDF: {e}"

    # DOCX Reader Fallback
    if ext == '.docx':
        try:
            import docx
        except ImportError:
            print("[FileSearch]: Installing 'python-docx' library...")
            subprocess.run([sys.executable, "-m", "pip", "install", "python-docx"], check=True)
            import docx
        try:
            doc = docx.Document(filepath)
            text = "\n".join([p.text for p in doc.paragraphs[:100]])  # Limit to 100 paragraphs
            return text[:max_chars] if text else "Error: Could not extract text from this Word document."
        except Exception as e:
            return f"Error reading Word document: {e}"

    # Default plain-text safe reader
    encodings = ['utf-8', 'latin-1', 'cp1252', 'utf-16']
    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read(max_chars)
                # If null bytes are found, it's likely a binary file
                if '\x00' in content:
                    continue
                return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"Error reading file: {e}"

    return "Error: Could not decode file content. It may be encoded in an unsupported binary format."


def sanitize_query(query):
    """Strips conversational filler words from file queries to isolate core filenames."""
    fillers = r'\b(the|my|a|an|file|document|folder|files|find|search)\b'
    cleaned = re.sub(fillers, '', query, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def check_for_duplicates(filepath_or_name):
    """Scans Windows search roots for duplicate files with the same base name."""
    if not filepath_or_name:
        return "I do not have an active file cached to scan for duplicates."

    filename = os.path.basename(filepath_or_name)
    print(f"[FileSearch]: Actively scanning hard drive for duplicates of '{filename}'...")

    results = search_files(filename)

    # Filter to ensure we only count exact base name matches (ignoring paths)
    exact_duplicates = [path for path in results if os.path.basename(path).lower() == filename.lower()]

    if len(exact_duplicates) <= 1:
        return f"No duplicates found. '{filename}' is unique and is the only file with that name on your laptop."

    response = f"I found {len(exact_duplicates)} duplicate files named '{filename}' on your laptop:\n"
    for i, path in enumerate(exact_duplicates, 1):
        info = get_file_info(path)
        size_str = f" ({info['size_mb']} MB)" if info else ""
        response += f"  {i}. {path}{size_str}\n"
    return response


# ─────────────────────────────────────────────
# THREAD-SAFE SEARCH RESULT CACHE
# ─────────────────────────────────────────────
_last_search_results = []
_search_results_lock = threading.Lock()


def _set_results(results):
    """Thread-safe write to the search result cache."""
    global _last_search_results
    with _search_results_lock:
        _last_search_results = results


def _clear_results():
    """Thread-safe clear of the search result cache."""
    global _last_search_results
    with _search_results_lock:
        _last_search_results = []


def _get_results():
    """Thread-safe snapshot read of the search result cache."""
    with _search_results_lock:
        return list(_last_search_results)


def handle_file_commands(user_input, context_text=None):
    """Parse and handle file-related commands with context-aware auto-searching and duplicate/path checks."""
    text = re.sub(r'[.,!?;:]+', '', user_input.lower().strip())

    # Take a safe snapshot of cached results once at the top.
    # All reads in this function use this snapshot.
    # All writes go through _set_results() or _clear_results().
    cached = _get_results()

    # 1. Read/Describe file content by number: "describe file 1" or "read file 2"
    read_num_match = re.search(r'(?:read|describe|explain|whats inside|what is inside|show content of)\s+(?:file\s+)?(\d+)$', text)
    if read_num_match and cached:
        idx = int(read_num_match.group(1)) - 1
        if 0 <= idx < len(cached):
            filepath = cached[idx]
            content = read_file_content(filepath)
            if content.startswith("Error:"):
                return content
            return f"[READ_FILE_CONTENT] Path: {filepath}\nContent:\n{content}"
        return "Invalid file number."

    # 2. Open file by number from last search: "open 1" or "open file 2"
    num_match = re.search(r'^open\s+(?:file\s+)?(\d+)$', text)
    if num_match and cached:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(cached):
            return open_file_with_default_app(cached[idx])
        return "Invalid file number."

    # 3. Handle Ordinal selections ("first", "second", "third", "last")
    ord_map = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1}
    for word, num in ord_map.items():
        if word in text and cached:
            idx = num - 1 if num > 0 else len(cached) - 1
            if 0 <= idx < len(cached):
                filepath = cached[idx]
                wants_open = any(w in text for w in ["open", "launch", "run", "show", "view"])
                if wants_open:
                    return open_file_with_default_app(filepath)
                else:
                    content = read_file_content(filepath)
                    if content.startswith("Error:"):
                        return content
                    return f"[READ_FILE_CONTENT] Path: {filepath}\nContent:\n{content}"

    # 4. Handle simple confirmation if files are cached: "yes", "no", "yeah", etc.
    is_yes = text in ["yes", "yeah", "sure", "ok", "okay", "yup", "yes please", "do it", "confirm"]
    is_no  = text in ["no", "nope", "nah", "cancel", "dont", "dont do it", "stop"]

    if (is_yes or is_no) and cached:
        if is_no:
            _clear_results()
            return "Understood, Sir. I will hold off on opening or describing it."

        if is_yes:
            if len(cached) == 1:
                filepath = cached[0]
                content = read_file_content(filepath)
                if content.startswith("Error:"):
                    return content
                return f"[READ_FILE_CONTENT] Path: {filepath}\nContent:\n{content}"
            else:
                return "Which file number would you like me to open or describe?"

    # 5. Handle file location/path queries: "where is it located", "what is the file path", "give me the file location"
    wants_path = any(w in text for w in ["location", "path", "directory", "folder path", "where is", "where's", "folder"])
    if wants_path:
        has_pronoun = any(p in text.split() for p in ["it", "that", "this", "them", "file", "document", "info", "context"])
        target_file = None

        # A. Context-analyzed previous message (only if cache is empty)
        if not cached and context_text:
            filename_match = re.search(r'`?([a-zA-Z0-9_\-\(\)\s]+\.(?:txt|pdf|docx|png|jpg|py|json))`?', context_text, re.IGNORECASE)
            if filename_match:
                extracted_name = filename_match.group(1).strip()
                autosearch_results = search_files(extracted_name)
                if autosearch_results:
                    _set_results(autosearch_results)
                    cached = autosearch_results  # update local snapshot too

        # B. Cached search results
        if has_pronoun and cached:
            target_file = cached[0]
        else:
            # C. Named check (e.g. "where is hardware.txt located")
            name_query = re.sub(r'\b(whats|what is|give me|the|file|location|path|directory|folder|of|where is|where\'s)\b', '', text).strip()
            name_query = re.sub(r'\s+', ' ', name_query)
            if name_query:
                res = search_files(name_query)
                if res:
                    target_file = res[0]

        if target_file:
            return f"[FILE_LOCATION_FOUND] Path: {target_file}"
        else:
            return "Please specify which file's location you would like me to retrieve, or run a search first."

    # 6. Active Duplicate Scanning: "are there duplicates", "does this file have copies", "find duplicates of stats"
    wants_duplicates = any(w in text for w in ["duplicates", "duplicate", "copies", "copy", "double"])
    if wants_duplicates:
        has_pronoun = any(p in text.split() for p in ["it", "that", "this", "them", "file", "document", "info"])
        target_file = None

        if has_pronoun and cached:
            target_file = cached[0]
        else:
            name_query = re.sub(r'\b(find|search|locate|check|for|duplicates|duplicate|of|copies|copy|the|file|document)\b', '', text).strip()
            name_query = re.sub(r'\s+', ' ', name_query)
            if name_query:
                res = search_files(name_query)
                if res:
                    target_file = res[0]

        if target_file:
            result = check_for_duplicates(target_file)
            return f"[DUPLICATE_FILES_FOUND] {result}"
        else:
            return "Could you specify which file you would like me to check for duplicates, or run a search first?"

    # 7. Handle ambiguous pronoun selections ("open it", "describe it", "explain that")
    wants_open = any(w in text for w in ["open", "launch", "run", "show", "view", "start"])
    wants_read = any(w in text for w in ["read", "describe", "explain", "whats inside", "what is inside", "contents", "summarize", "analyze"])
    has_pronoun = any(p in text.split() for p in ["it", "that", "this", "them", "file", "document", "info", "information"])

    if (wants_open or wants_read) and has_pronoun:
        # If cache is empty, attempt Automatic Context Search from previous message
        if not cached and context_text:
            filename_match = re.search(r'`?([a-zA-Z0-9_\-\(\)\s]+\.(?:txt|pdf|docx|png|jpg|py|json))`?', context_text, re.IGNORECASE)
            if filename_match:
                extracted_name = filename_match.group(1).strip()
                print(f"[FileSearch]: Context-analyzing previous message... Found filename reference: '{extracted_name}'")
                print(f"[FileSearch]: Initiating automatic search for '{extracted_name}'...")
                autosearch_results = search_files(extracted_name)
                if autosearch_results:
                    _set_results(autosearch_results)
                    cached = autosearch_results  # update local snapshot
                else:
                    return f"I found a reference to '{extracted_name}' in our conversation, but I couldn't locate that file on your laptop."
            else:
                return "I don't have any cached file search results, and I couldn't find any file references in our recent conversation."

        if not cached:
            return "I don't have any cached file search results. Please search for a file first."

        # Smart routing: If there is exactly ONE file in cache, auto-execute on it
        if len(cached) == 1:
            filepath = cached[0]
            if wants_open:
                return open_file_with_default_app(filepath)
            else:
                content = read_file_content(filepath)
                if content.startswith("Error:"):
                    return content
                return f"[READ_FILE_CONTENT] Path: {filepath}\nContent:\n{content}"
        else:
            action = "open" if wants_open else "describe"
            return f"Which file number would you like me to {action}?"

    # 8. Standalone number selections: "1", "file 2", "number 3"
    standalone_num_match = re.search(r'^(?:file\s+|number\s+|the\s+)?(\d+)(?:st|nd|rd|th)?$', text)
    if standalone_num_match and cached:
        idx = int(standalone_num_match.group(1)) - 1
        if 0 <= idx < len(cached):
            filepath = cached[idx]
            content = read_file_content(filepath)
            if content.startswith("Error:"):
                return content
            return f"[READ_FILE_CONTENT] Path: {filepath}\nContent:\n{content}"

    # 9. Read/Describe file content by name: "describe the budget.txt file" or "read my script.py"
    read_name_match = re.search(
        r'(?:read|describe|explain|whats inside|what is inside|show content of)\s+(?:my\s+|the\s+)?(?:file\s+)?(.+?)(?:\s+file)?$',
        text
    )
    if read_name_match:
        query = sanitize_query(read_name_match.group(1).strip())
        if query and len(query.split()) <= 4:
            results = search_files(query)
            if results:
                _set_results(results)
                if len(results) == 1:
                    filepath = results[0]
                    content = read_file_content(filepath)
                    if content.startswith("Error:"):
                        return content
                    return f"[READ_FILE_CONTENT] Path: {filepath}\nContent:\n{content}"
                else:
                    response = f"I found multiple files matching '{query}':\n"
                    for i, path in enumerate(results[:5], 1):
                        response += f"  {i}. {os.path.basename(path)}\n"
                    response += "Please say 'describe file 1', 'describe file 2', etc."
                    return response

    # 10. Search files: "find my resume", "search for pdf named invoice", "where is my thesis"
    search_match = re.search(
        r'(?:find|search for|locate|look for|where is|where\'s)\s+(?:my\s+)?(.+?)(?:\s+file(?:s)?)?$',
        text
    )
    if search_match:
        query = sanitize_query(search_match.group(1).strip())
        if not query:
            return "What file would you like me to look for?"

        # Detect file type filter
        file_type = None
        type_map = {
            "pdf": ".pdf", "word": ".docx", "excel": ".xlsx",
            "image": None, "photo": None, "video": None,
            "text": ".txt", "python": ".py", "code": None
        }
        for keyword, ext in type_map.items():
            if keyword in query:
                file_type = ext
                query = query.replace(keyword, "").strip()
                break

        results = search_files(query, file_type=file_type)
        _set_results(results)

        if results:
            if len(results) == 1:
                filename = os.path.basename(results[0])
                response = f"I found one matching file: {filename}.\nWould you like me to open it or describe its contents?"
            else:
                if len(results) > 5:
                    response = f"I found {len(results)} matching files. Here are the first 5:\n"
                else:
                    response = f"I found {len(results)} matching files:\n"
                for i, path in enumerate(results[:5], 1):
                    info = get_file_info(path)
                    size_str = f" ({info['size_mb']} MB)" if info else ""
                    response += f"  {i}. {os.path.basename(path)}{size_str}\n"
                response += "\nWhich file number would you like me to open or describe?"
            return response
        return f"No files found matching '{query}'."

    # 11. Open file by name: "open my resume" or "open the budget file"
    open_match = re.search(
        r'(?:open|show|view)\s+(?:my\s+|the\s+)?(?:file\s+)?(.+?)(?:\s+file)?$',
        text
    )
    if open_match:
        query = sanitize_query(open_match.group(1).strip())
        if query and len(query.split()) <= 3:
            results = search_files(query)
            if results:
                _set_results(results)
                if len(results) == 1:
                    return open_file_with_default_app(results[0])
                response = f"Found {len(results)} files matching '{query}':\n"
                for i, path in enumerate(results[:5], 1):
                    response += f"  {i}. {os.path.basename(path)}\n"
                response += "Say 'open 1', 'open 2', etc."
                return response

    return None