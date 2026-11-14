import os
import sys
import json
import re
from datetime import datetime

# Add root folder to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import config
except ImportError:
    class config:
        HISTORY_FILE = "command_history.json"

def get_desktop_path():
    """Returns the desktop path on Windows/other systems."""
    return os.path.join(os.path.expanduser("~"), "Desktop")

def export_conversation(history):
    """
    Saves current conversation history as Markdown to Desktop.
    """
    if not history:
        return "Sir, there is no conversation history to export in this session."
        
    desktop = get_desktop_path()
    os.makedirs(desktop, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(desktop, f"JARVIS_Conversation_Export_{timestamp}.md")
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# JARVIS Conversation Export\n")
            f.write(f"*Exported on: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}*\n\n")
            f.write("---\n\n")
            
            for msg in history:
                role = msg.get("role", "unknown").capitalize()
                if role == "User":
                    role_str = "### You"
                elif role == "Assistant":
                    role_str = "### JARVIS"
                else:
                    role_str = f"### {role}"
                    
                content = msg.get("content", "")
                f.write(f"{role_str}:\n{content}\n\n")
                f.write("---\n\n")
                
        return f"Sir, I have successfully exported our conversation as a Markdown file to your Desktop: 'JARVIS_Conversation_Export_{timestamp}.md'."
    except Exception as e:
        return f"Failed to export conversation: {e}"

def search_history(query):
    """
    Search past command history for keyword scoring.
    Returns matched interactions.
    """
    if not os.path.exists(config.HISTORY_FILE):
        return "I have no past history logs to search, Sir."
        
    try:
        with open(config.HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return "History database is currently unreadable, Sir."
        
    if not history:
        return "History database is empty, Sir."
        
    query_words = set(re.sub(r'[^a-zA-Z0-9 ]', '', query.lower()).split())
    # Skip generic search filler words
    fillers = {"search", "find", "history", "what", "did", "we", "talk", "about", "regarding", "for", "in"}
    search_terms = query_words - fillers
    if not search_terms:
        search_terms = query_words
        
    matches = []
    for entry in history:
    # FIXED: Map correctly to the storage key "user_input"
        user_cmd = entry.get("user_input", entry.get("command", ""))
        response = entry.get("response", "")
        
        # Calculate matching score
        score = 0
        cmd_lower = user_cmd.lower()
        res_lower = response.lower()
        
        for term in search_terms:
            if term in cmd_lower:
                score += 3  # Higher weight for queries in command
            if term in res_lower:
                score += 1
                
        if score > 0:
            matches.append((score, user_cmd, response, entry.get("timestamp", "")))
            
    # Sort matches by score descending
    matches.sort(key=lambda x: x[0], reverse=True)
    
    if not matches:
        return f"Sir, I could find no record of our discussions regarding '{query}'."
        
    results = [f"Sir, I found {len(matches)} match{'es' if len(matches)>1 else ''} in our history logs:"]
    for i, (score, cmd, res, ts) in enumerate(matches[:3], 1):
        clean_res = res[:150] + "..." if len(res) > 150 else res
        results.append(f"  {i}. Command: '{cmd}' -> '{clean_res}'")
        
    return "\n".join(results)
