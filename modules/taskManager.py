"""
Task Management Module for JARVIS (UPGRADED)
- Adds persistent JSON task tracking
- Compiles tasks by pending, completed, or today's date
- Natively parses and handles list creation, completion, and deletion commands
- Adds get_proactive_reminders_text() to calculate due and overdue tasks dynamically
- Uses natural language date parsing (dateparser) to support "next week", "May 27", "in 3 days", etc.
- Tracks active due/overdue task IDs in memory for conversational confirmation completion
- Triggers conversational recurrence prompt on creation
- Formats startup nags into Numbered Lists for precise conversational selection
"""
import json
import os
import sys
import re
import subprocess
from datetime import datetime, date, timedelta

# Auto-install dateparser if missing
try:
    import dateparser
except ImportError:
    print("[TaskManager]: Installing 'dateparser' library for natural language dates...")
    subprocess.run([sys.executable, "-m", "pip", "install", "dateparser"], check=True)
    import dateparser

TASKS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tasks.json")

# Global list to cache due/overdue task IDs announced in the current bootup session
_active_due_task_ids = []


def load_tasks():
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_tasks(tasks):
    try:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[TaskManager Error]: {e}")


def _next_id(tasks):
    return max((t["id"] for t in tasks), default=0) + 1


def create_task(title, due_date=None, priority="normal"):
    try:
        tasks = load_tasks()
        task = {
            "id": _next_id(tasks),
            "title": title,
            "due_date": due_date,
            "priority": priority,
            "completed": False,
            "notified": False,
            "created_at": datetime.now().isoformat()
        }
        tasks.append(task)
        save_tasks(tasks)
        
        due_str = f" due {due_date}" if due_date else ""
        # 💡 RESTORED: Triggers the conversational RAG prompt inside tts.py
        return f"[TASK_CREATED] Title: {title}\nResponse: Task created: {title}{due_str}. Would you like me to set a recurring reminder while you work on this, Sir?"
    except Exception as e:
        return f"Error creating task: {e}"


def complete_task(task_id):
    try:
        tasks = load_tasks()
        for task in tasks:
            if task["id"] == task_id:
                task["completed"] = True
                task["completed_at"] = datetime.now().isoformat()
                save_tasks(tasks)
                return f"Completed task: {task['title']}"
        return f"Task {task_id} not found."
    except Exception as e:
        return f"Error completing task: {e}"


def complete_task_by_title(title):
    """
    Mark a task complete by exact title match (case-insensitive).
    Used when the user says 'yes I'm done' in response to a recurring nag.
    Also removes the recurring timer config from disk so nag threads stop.
    """
    try:
        tasks = load_tasks()
        for task in tasks:
            if task["title"].lower() == title.lower() and not task.get("completed"):
                task["completed"] = True
                task["completed_at"] = datetime.now().isoformat()
                save_tasks(tasks)
                # Tell timerSystem to drop the config (thread self-exits on next cycle check)
                try:
                    from timerSystem import remove_recurring_timer_config
                    remove_recurring_timer_config(title)
                except Exception:
                    pass
                return f"Excellent, Sir! I have marked '{title}' as complete and cancelled the recurring reminder."
        return f"Task '{title}' is already complete or was not found."
    except Exception as e:
        return f"Error completing task: {e}"


def complete_active_due_task_by_index(index):
    """Completes a specific task from the active bootup cache based on its spoken number (0-based index)."""
    global _active_due_task_ids
    if not _active_due_task_ids:
        return "No active due tasks found in cache to complete, Sir."
        
    if 0 <= index < len(_active_due_task_ids):
        tid = _active_due_task_ids[index]
        res = complete_task(tid)
        return res + " I have updated your database, Sir."
    else:
        return "I could not find a task matching that number in your current list, Sir."


def complete_active_due_tasks():
    """Natively completes ALL tasks currently cached as due/overdue."""
    global _active_due_task_ids
    if not _active_due_task_ids:
        return "No active due tasks found to complete, Sir."
        
    results = []
    task_ids = _active_due_task_ids.copy()
    for tid in task_ids:
        res = complete_task(tid)
        results.append(res)
        
    _active_due_task_ids = []
    return "\n".join(results) + " I have updated your database, Sir."


def list_tasks(filter_by="pending"):
    try:
        tasks = load_tasks()
        today = date.today().isoformat()

        if filter_by == "pending":
            filtered = [t for t in tasks if not t["completed"]]
        elif filter_by == "completed":
            filtered = [t for t in tasks if t["completed"]]
        elif filter_by == "today":
            filtered = [t for t in tasks if (t.get("due_date") or "").startswith(today)]
        else:
            filtered = tasks

        if not filtered:
            return f"No {filter_by} tasks found."

        output = f"{filter_by.capitalize()} tasks ({len(filtered)}):\n"
        for task in filtered[:15]:
            status = "Done" if task["completed"] else "Pending"
            due = f" | due: {task['due_date']}" if task.get("due_date") else ""
            pri = f" [{task['priority']}]" if task.get("priority") != "normal" else ""
            output += f"  {task['id']}. [{status}] {task['title']}{due}{pri}\n"
        return output
    except Exception as e:
        return f"Error listing tasks: {e}"


def delete_task(task_id):
    try:
        tasks = load_tasks()
        original_len = len(tasks)
        tasks = [t for t in tasks if t["id"] != task_id]
        if len(tasks) < original_len:
            save_tasks(tasks)
            return f"Task {task_id} deleted."
        return f"Task {task_id} not found."
    except Exception as e:
        return f"Error deleting task: {e}"


def get_proactive_reminders_text():
    """Checks tasks.json for incomplete deadlines and returns a numbered spoken list."""
    global _active_due_task_ids
    _active_due_task_ids = [] 

    tasks = load_tasks()
    if not tasks:
        return None

    today_str = date.today().isoformat()
    due_today = []
    overdue = []

    for t in tasks:
        if t.get("completed"): continue
        due_date = t.get("due_date")
        if due_date:
            due_date = due_date.strip()
            if due_date == today_str:
                due_today.append((t["id"], t["title"]))
            elif due_date < today_str:
                overdue.append((t["id"], t["title"]))

    if not due_today and not overdue:
        return None

    msg_parts = ["Excuse me, Sir."]
    counter = 1
    
    if due_today:
        msg_parts.append("You have tasks due today:")
        for tid, title in due_today:
            msg_parts.append(f"Number {counter}: '{title}'.")
            _active_due_task_ids.append(tid)
            counter += 1
            
    if overdue:
        msg_parts.append("You also have tasks currently overdue:")
        for tid, title in overdue:
            msg_parts.append(f"Number {counter}: '{title}'.")
            _active_due_task_ids.append(tid)
            counter += 1
    
    total_tasks = len(due_today) + len(overdue)
    if total_tasks > 1:
        msg_parts.append("Have you completed any of these yet? You can reply with the task number, or say 'not yet'.")
    else:
        msg_parts.append("Have you completed this yet?")
    
    return " ".join(msg_parts)


def handle_task_commands(user_input):
    """Parse and handle task commands. Returns result or None."""
    # We do NOT aggressively strip punctuation here so dateparser can read formatted dates correctly
    text_clean = user_input.lower().strip()
    text_no_punct = re.sub(r'[.,!?;:]+', '', text_clean)

    # 1. Create task — Flexible regex to handle "create a task", "make a task", "add task", etc.
    create_patterns = [
        r'(?:create|make|add|set)(?:\s+a)?\s+(?:new\s+)?task\s+(?:for\s+me\s+)?(?:to\s+)?(.+?)(?:\s+(?:by|due|on|for)\s+(.+))?$',
        r'(?:remind me to|task to)\s+(.+?)(?:\s+(?:by|due|on|for)\s+(.+))?$',
    ]
    
    for pattern in create_patterns:
        match = re.search(pattern, text_clean)
        if match:
            title = match.group(1).strip()
            due_raw = match.group(2).strip() if match.lastindex >= 2 and match.group(2) else None
            due_date = None
            
            # Use the powerful natural language dateparser to translate conversational dates
            if due_raw:
                try:
                    # dateparser converts phrases like "next friday" or "May 27" into a physical datetime object
                    parsed = dateparser.parse(due_raw, settings={'PREFER_DATES_FROM': 'future'})
                    if parsed:
                        due_date = parsed.date().isoformat()
                    else:
                        # Fallback if the parser couldn't figure it out
                        due_date = re.sub(r'[^0-9\-]', '', due_raw).strip()
                        if not due_date:
                            due_date = None
                except Exception:
                    pass

            return create_task(title, due_date)

    # 2. Complete task
    complete_match = re.search(r'(?:mark|complete|finish|done|tick off)\s+(?:task\s+)?(\d+)', text_no_punct)
    if complete_match:
        return complete_task(int(complete_match.group(1)))

    complete_title_match = re.search(r'(?:mark|complete|finish|done|tick off)\s+(?:task\s+)?(.+)$', text_no_punct)
    if complete_title_match:
        title = complete_title_match.group(1).strip()
        if title:
            return complete_task_by_title(title)

    # 3. Delete task
    delete_match = re.search(r'(?:delete|remove|cancel|clear)\s+(?:task\s+)?(\d+)', text_no_punct)
    if delete_match:
        return delete_task(int(delete_match.group(1)))

    # 4. List tasks
    if any(p in text_no_punct for p in ["all tasks", "list all", "show all tasks"]):
        return list_tasks("all")
    if any(p in text_no_punct for p in ["completed tasks", "what have i done", "finished tasks", "done tasks"]):
        return list_tasks("completed")
    if any(p in text_no_punct for p in ["today tasks", "todays tasks", "list todays tasks", "due today", "tasks today", "what is due today", "what do i have today"]):
        return list_tasks("today")
    if any(p in text_no_punct for p in ["my tasks", "list tasks", "show tasks", "todo", "to do", "pending tasks", "what do i need"]):
        return list_tasks("pending")

    return None