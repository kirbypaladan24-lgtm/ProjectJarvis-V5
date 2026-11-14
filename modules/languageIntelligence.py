import os
import sys
import re
import json

# Add root folder to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        PHONETIC_CORRECTIONS = {}
        TAGALOG_MAP = {}
        CUSTOM_SHORTHANDS = {}
        MEMORY_FILE = "ai_memory.json"
        CONTEXT_RESTART_MSGS = 5

def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
            
        previous_row = current_row
        
    return previous_row[-1]

# PERF #6: Module-level constant — was being rebuilt as a list on every call
_CMD_KEYWORDS = frozenset([
    "exit", "clear", "task", "tasks", "file", "files", "note", "notes", "screenshot",
    "internet", "monitor", "capabilities", "spotify", "volume",
    "brightness", "minimize", "maximize", "diagnostics", "history"
])

def fuzzy_correct(text):
    """
    Fuzzy correct common command keywords to prevent minor spelling typos.
    PERF: frozenset O(1) lookup, length pre-filter before Levenshtein, skip short/exact words.
    """
    words = text.split()
    corrected_words = []

    for w in words:
        w_clean = re.sub(r'[^a-zA-Z0-9]', '', w).lower()

        # Skip empty, very short, or already-correct words immediately — no Levenshtein needed
        if not w_clean or len(w_clean) < 3 or w_clean in _CMD_KEYWORDS:
            corrected_words.append(w)
            continue

        best_match = w
        best_dist  = 999

        for keyword in _CMD_KEYWORDS:
            # PERF: Length pre-filter — skip keywords that are too different in length to ever match
            if abs(len(keyword) - len(w_clean)) > 2:
                continue
            dist = levenshtein_distance(w_clean, keyword)
            if dist < best_dist:
                best_dist  = dist
                best_match = keyword

        threshold = 1 if len(w_clean) <= 5 else 2
        if best_dist <= threshold:
            if w.isupper():
                corrected_words.append(best_match.upper())
            elif w[0].isupper():
                corrected_words.append(best_match.capitalize())
            else:
                corrected_words.append(best_match)
        else:
            corrected_words.append(w)

    return " ".join(corrected_words)

def phonetic_correct(text):
    """
    Correct Whisper speech-to-text mishears using the config mishear dictionary.
    """
    text_lower = text.lower().strip()
    
    # Sort phonetic keys by length descending to replace multi-word phrases first
    corrections = sorted(config.PHONETIC_CORRECTIONS.items(), key=lambda x: len(x[0]), reverse=True)
    
    for mishear, correction in corrections:
        # Replace as boundary words or as substring if it's a multi-word phrase
        if mishear in text_lower:
            # Regex replacement with boundary awareness if possible
            pattern = re.compile(r'\b' + re.escape(mishear) + r'\b', re.IGNORECASE)
            text_lower = pattern.sub(correction, text_lower)
            
    return text_lower

def tagalog_translate(text):
    """
    Translates tagalog keywords to english for seamless bilingual routing.
    Example: "Buksan mo ang Spotify" -> "open Spotify"
    """
    text_lower = text.lower().strip()
    words = text_lower.split()
    translated_words = []
    
    for w in words:
        clean_w = re.sub(r'[^a-zA-Z0-9\-]', '', w)
        if clean_w in config.TAGALOG_MAP:
            translated = config.TAGALOG_MAP[clean_w]
            if translated:  # Skip empty mappings (like "mo", "ko", "ang")
                translated_words.append(translated)
        else:
            translated_words.append(w)
            
    return " ".join(translated_words)

def resolve_pronouns(text, context_history):
    """
    Resolves pronouns like "it", "them", "that" to the last referenced object.
    context_history: list of dict representing history (role, content)
    """
    text_lower = text.lower().strip()
    # Do not resolve generic "it" in common question phrases.
    skip_phrases = [
        "what time is it", "what date is it", "what day is it",
        "how much is it", "where is it", "who is it"
    ]
    if any(phrase in text_lower for phrase in skip_phrases):
        return text

    pronouns = ["that file", "this file", "that note", "this note", "them", "it"]
    
    has_pronoun = any(re.search(r'\b' + re.escape(p) + r'\b', text_lower) for p in pronouns)
    if not has_pronoun:
        return text
        
    # Find last target in context_history
    last_target = None
    for msg in reversed(context_history):
        content = msg.get("content", "")
        # Look for system targets first
        if msg.get("role") == "system":
            if "[ACTIVE_TASK_TARGET]" in content:
                last_target = content.replace("[ACTIVE_TASK_TARGET]: ", "").strip()
                break
            elif "[READ_FILE_CONTENT] Path:" in content or "[FILE_LOCATION_FOUND] Path:" in content:
                path = content.split("Path: ")[1].strip()
                last_target = f"file {path}"
                break
        # Or look for file paths in normal assistant responses
        if msg.get("role") == "assistant":
            # Search for typical path patterns
            path_match = re.search(r'([A-Za-z]:\\[^:\n]+?\.[a-zA-Z0-9]+)', content)
            if path_match:
                last_target = f"file {path_match.group(1)}"
                break
            # Look for note names or task titles
            note_match = re.search(r'note "([^"]+)"', content, re.IGNORECASE)
            if note_match:
                last_target = f"note {note_match.group(1)}"
                break
                
    if last_target:
        # Replace pronoun with the last target
        for p in pronouns:
            pattern = re.compile(r'\b' + re.escape(p) + r'\b', re.IGNORECASE)
            if pattern.search(text):
                text = pattern.sub(lambda _match: last_target, text)
                break
                
    return text

def apply_shorthands(text):
    """Applies user-defined shorthands (e.g. 'yt' -> 'open youtube') from config."""
    words = text.lower().split()
    new_words = []
    for w in words:
        clean_w = re.sub(r'[^a-zA-Z0-9]', '', w)
        if clean_w in config.CUSTOM_SHORTHANDS:
            new_words.append(config.CUSTOM_SHORTHANDS[clean_w])
        else:
            new_words.append(w)
    return " ".join(new_words)

def detect_tone(text):
    """
    Detect user tone (e.g., frustration, exhaustion) from phrasing.
    Returns: 'frustrated', 'tired', or 'normal'
    """
    text_lower = text.lower()
    frustrated_indicators = [
        "not working", "stupid", "annoying", "useless", "damn", "wrong",
        "why isn't", "why is it", "crap", "garbage", "waste of time"
    ]
    tired_indicators = [
        "tired", "sleepy", "exhausted", "long day", "sleep", "so late",
        "drained", "break", "resting"
    ]
    
    if any(ind in text_lower for ind in frustrated_indicators):
        return 'frustrated'
    elif any(ind in text_lower for ind in tired_indicators):
        return 'tired'
    return 'normal'

def clarify_partial(text):
    """
    Determines if input is a partial or ambiguous command.
    If so, returns a clarifying prompt to speak. Otherwise returns None.
    """
    text_clean = text.strip().lower()
    # If the user only said "open" or "search" or "delete" without specifying what
    open_commands = ["open", "launch", "run", "start"]
    search_commands = ["search", "find", "locate", "google"]
    delete_commands = ["delete", "remove", "clear", "cancel"]
    
    if text_clean in open_commands:
        return "Which application or file would you like me to open, Sir?"
    if text_clean in search_commands:
        return "What would you like me to search for, Sir?"
    if text_clean in delete_commands:
        return "Which task, file, or timer would you like to delete, Sir?"
        
    return None

def load_context_on_restart():
    """Loads the last N exchanges from memory on startup to rebuild context."""
    if os.path.exists(config.MEMORY_FILE):
        try:
            with open(config.MEMORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            return history[-config.CONTEXT_RESTART_MSGS * 2:]
        except Exception:
            pass
    return []

def preprocess_input(text, history):
    """Runs the entire local preprocessing pipeline on the input string."""
    text = re.sub(r'\b(.{4,80}?)\s+\1\b', r'\1', text, flags=re.IGNORECASE)

    # 1. Phonetic mishear correction
    processed = phonetic_correct(text)
    
    # 2. Tagalog-English keyword translation
    processed = tagalog_translate(processed)
    
    # 3. Apply shorthands
    processed = apply_shorthands(processed)
    
    # 4. Resolve pronouns
    processed = resolve_pronouns(processed, history)
    
    # 5. Fuzzy spelling correction
    processed = fuzzy_correct(processed)
    
    return processed