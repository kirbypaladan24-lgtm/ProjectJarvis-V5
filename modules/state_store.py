"""
JARVIS SQLite State Store
================================================================
Migrates JSON state files to a single SQLite database.
Provides faster queries, ACID transactions, and better concurrency.

Tables:
    - tasks        (replaces tasks.json)
    - notes        (replaces notes.json)
    - timers       (replaces timers.json)
    - memory       (replaces ai_memory.json)
    - commands     (replaces command_history.json)
    - entities     (replaces entity_cache.json)
    - knowledge    (replaces knowledge_base.json)

Usage:
    from state_store import StateStore
    db = StateStore()
    db.add_task("call mom", due_date="tomorrow")
    tasks = db.get_tasks(filter_by="pending")
"""
import os
import sys
import json
import sqlite3
import threading
from datetime import datetime

_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

try:
    import config
except ImportError:
    class config:
        BASE_DIR = "."


# ═════════════════════════════════════════════════════════════
# STATE STORE
# ═════════════════════════════════════════════════════════════

_DB_PATH = os.path.join(getattr(config, 'BASE_DIR', '.'), "jarvis_state.db")
_lock = threading.Lock()


class StateStore:
    """SQLite-backed state store for JARVIS."""

    def __init__(self, db_path=None):
        self.db_path = db_path or _DB_PATH
        self._local = threading.local()  # Thread-local connection
        self._init_db()

    def _get_conn(self):
        """Get a thread-local SQLite connection (persists per thread)."""
        if not hasattr(self._local, 'conn'):
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._get_conn() as conn:
            # Tasks
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_date TEXT,
                    priority TEXT DEFAULT 'normal',
                    completed INTEGER DEFAULT 0,
                    notified INTEGER DEFAULT 0,
                    created_at TEXT,
                    completed_at TEXT
                )
            """)

            # Notes
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT,
                    tags TEXT,  -- JSON array
                    created_at TEXT,
                    modified_at TEXT
                )
            """)

            # Timers
            conn.execute("""
                CREATE TABLE IF NOT EXISTS timers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    end_timestamp REAL,
                    label TEXT,
                    is_recurring INTEGER DEFAULT 0,
                    interval_seconds INTEGER,
                    active INTEGER DEFAULT 1,
                    created_at TEXT
                )
            """)

            # Memory (conversation history)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT
                )
            """)

            # Commands (history)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_input TEXT,
                    response TEXT,
                    intent TEXT,
                    success INTEGER DEFAULT 1,
                    timestamp TEXT
                )
            """)

            # Entities (for pronoun resolution)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                )
            """)

            # Knowledge base
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT NOT NULL,
                    embedding TEXT,  -- JSON array
                    created_at TEXT
                )
            """)

            # Expenses
            conn.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount REAL,
                    category TEXT,
                    description TEXT,
                    timestamp TEXT
                )
            """)

            conn.commit()

    # ═════════════════════════════════════════════════════════════
    # TASKS
    # ═════════════════════════════════════════════════════════════

    def add_task(self, title, due_date=None, priority="normal"):
        """Add a task. Returns the new task ID."""
        with _lock, self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO tasks (title, due_date, priority, created_at) VALUES (?, ?, ?, ?)",
                (title, due_date, priority, datetime.now().isoformat())
            )
            conn.commit()
            return cursor.lastrowid

    def get_tasks(self, filter_by="pending"):
        """Get tasks. filter_by: pending|completed|today|all."""
        with self._get_conn() as conn:
            if filter_by == "pending":
                rows = conn.execute("SELECT * FROM tasks WHERE completed=0 ORDER BY created_at DESC").fetchall()
            elif filter_by == "completed":
                rows = conn.execute("SELECT * FROM tasks WHERE completed=1 ORDER BY completed_at DESC").fetchall()
            elif filter_by == "today":
                today = datetime.now().strftime("%Y-%m-%d")
                rows = conn.execute("SELECT * FROM tasks WHERE completed=0 AND due_date=? ORDER BY created_at DESC", (today,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()

            return [dict(r) for r in rows]

    def complete_task(self, task_id):
        """Mark a task as completed."""
        with _lock, self._get_conn() as conn:
            conn.execute(
                "UPDATE tasks SET completed=1, completed_at=? WHERE id=?",
                (datetime.now().isoformat(), task_id)
            )
            conn.commit()

    def delete_task(self, task_id):
        """Delete a task."""
        with _lock, self._get_conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            conn.commit()

    def delete_all_tasks(self):
        """Delete all tasks."""
        with _lock, self._get_conn() as conn:
            conn.execute("DELETE FROM tasks")
            conn.commit()

    # ═════════════════════════════════════════════════════════════
    # NOTES
    # ═════════════════════════════════════════════════════════════

    def add_note(self, title, content=None, tags=None):
        """Add a note. Returns the new note ID."""
        if content is None:
            content = title
        tags_json = json.dumps(tags or [])
        with _lock, self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO notes (title, content, tags, created_at, modified_at) VALUES (?, ?, ?, ?, ?)",
                (title, content, tags_json, datetime.now().isoformat(), datetime.now().isoformat())
            )
            conn.commit()
            return cursor.lastrowid

    def get_notes(self, search_query=None):
        """Get notes, optionally filtered by search query."""
        with self._get_conn() as conn:
            if search_query:
                rows = conn.execute(
                    "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? ORDER BY created_at DESC",
                    (f"%{search_query}%", f"%{search_query}%")
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def delete_note(self, note_id):
        """Delete a note."""
        with _lock, self._get_conn() as conn:
            conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
            conn.commit()

    # ═════════════════════════════════════════════════════════════
    # MEMORY
    # ═════════════════════════════════════════════════════════════

    def add_memory(self, role, content):
        """Add a conversation memory entry."""
        with _lock, self._get_conn() as conn:
            conn.execute(
                "INSERT INTO memory (role, content, timestamp) VALUES (?, ?, ?)",
                (role, content, datetime.now().isoformat())
            )
            conn.commit()

    def get_memory(self, limit=20):
        """Get recent memory entries."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memory ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_memory(self):
        """Clear all memory."""
        with _lock, self._get_conn() as conn:
            conn.execute("DELETE FROM memory")
            conn.commit()

    # ═════════════════════════════════════════════════════════════
    # COMMANDS
    # ═════════════════════════════════════════════════════════════

    def add_command(self, user_input, response, intent="", success=True):
        """Log a command."""
        with _lock, self._get_conn() as conn:
            conn.execute(
                "INSERT INTO commands (user_input, response, intent, success, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user_input, response[:500], intent, 1 if success else 0, datetime.now().isoformat())
            )
            conn.commit()

    def get_commands(self, limit=50):
        """Get recent commands."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM commands ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # ═════════════════════════════════════════════════════════════
    # ENTITIES (for pronoun resolution)
    # ═════════════════════════════════════════════════════════════

    def set_entity(self, key, value):
        """Set an entity value."""
        with _lock, self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entities (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, datetime.now().isoformat())
            )
            conn.commit()

    def get_entity(self, key):
        """Get an entity value."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM entities WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def get_all_entities(self):
        """Get all entities."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM entities").fetchall()
            return {r["key"]: r["value"] for r in rows}

    # ═════════════════════════════════════════════════════════════
    # EXPENSES
    # ═════════════════════════════════════════════════════════════

    def add_expense(self, amount, category, description=""):
        """Log an expense."""
        with _lock, self._get_conn() as conn:
            conn.execute(
                "INSERT INTO expenses (amount, category, description, timestamp) VALUES (?, ?, ?, ?)",
                (amount, category, description, datetime.now().isoformat())
            )
            conn.commit()

    def get_expenses(self, limit=50):
        """Get recent expenses."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM expenses ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # ═════════════════════════════════════════════════════════════
    # MIGRATION FROM JSON
    # ═════════════════════════════════════════════════════════════

    def migrate_from_json(self):
        """Migrate existing JSON files to SQLite."""
        base = getattr(config, 'BASE_DIR', '.')
        migrated = {}

        # Migrate tasks.json
        tasks_file = os.path.join(base, "tasks.json")
        if os.path.exists(tasks_file):
            try:
                with open(tasks_file) as f:
                    tasks = json.load(f)
                for t in tasks:
                    self.add_task(
                        t.get("title", "Unknown"),
                        due_date=t.get("due_date"),
                        priority=t.get("priority", "normal")
                    )
                migrated["tasks"] = len(tasks)
            except Exception as e:
                print(f"[StateStore]: tasks.json migration error: {e}")

        # Migrate notes.json
        notes_file = os.path.join(base, "notes.json")
        if os.path.exists(notes_file):
            try:
                with open(notes_file) as f:
                    notes = json.load(f)
                for n in notes:
                    self.add_note(
                        n.get("title", ""),
                        content=n.get("content"),
                        tags=n.get("tags", [])
                    )
                migrated["notes"] = len(notes)
            except Exception as e:
                print(f"[StateStore]: notes.json migration error: {e}")

        return migrated


# ═════════════════════════════════════════════════════════════
# SINGLETON
# ═════════════════════════════════════════════════════════════

_db_instance = None

def get_db():
    """Get the singleton StateStore instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = StateStore()
    return _db_instance


if __name__ == "__main__":
    print("Testing StateStore...\n")

    # Use in-memory DB for testing
    db = StateStore(":memory:")

    # Test tasks
    task_id = db.add_task("Test task", due_date="2026-08-08")
    print(f"Added task: ID={task_id}")

    tasks = db.get_tasks("pending")
    print(f"Pending tasks: {len(tasks)}")
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Test task"

    db.complete_task(task_id)
    tasks = db.get_tasks("pending")
    assert len(tasks) == 0
    tasks = db.get_tasks("completed")
    assert len(tasks) == 1
    print("Tasks: ✅")

    # Test notes
    note_id = db.add_note("Test note", "This is a test")
    notes = db.get_notes()
    assert len(notes) == 1
    notes = db.get_notes("test")
    assert len(notes) == 1
    print("Notes: ✅")

    # Test memory
    db.add_memory("user", "hello")
    db.add_memory("assistant", "Hi there")
    memory = db.get_memory()
    assert len(memory) == 2
    print("Memory: ✅")

    # Test entities
    db.set_entity("last_file", "test.txt")
    assert db.get_entity("last_file") == "test.txt"
    entities = db.get_all_entities()
    assert "last_file" in entities
    print("Entities: ✅")

    # Test expenses
    db.add_expense(250, "food", "lunch")
    expenses = db.get_expenses()
    assert len(expenses) == 1
    assert expenses[0]["amount"] == 250
    print("Expenses: ✅")

    print("\nAll StateStore tests passed ✅")
