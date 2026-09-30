"""
SQLite Persistent Memory Manager for Personal AI Assistant.
Provides long-term knowledge storage, user facts, and dialogue history.
"""

import sqlite3
import json
import time
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Iterator
from config import DB_FILE


class MemoryDB:
    """Manages SQLite storage for assistant long-term memory."""

    def __init__(self, db_path=DB_FILE):
        self.db_path = str(db_path)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initializes database tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # User facts & knowledge base
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # Conversation history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    timestamp REAL NOT NULL
                )
            """)

            # System Profile Cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            conn.commit()

    # Fact & Preference Management
    def remember_fact(self, category: str, key: str, value: str) -> None:
        """Stores or updates a persistent fact about the user or system."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO facts (category, key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    category = excluded.category,
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (category, key, value, now, now))
            conn.commit()

    def forget_fact(self, key: str) -> bool:
        """Deletes a fact by key."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM facts WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_facts(self) -> List[Dict[str, Any]]:
        """Returns all stored facts formatted as a list of dicts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category, key, value, updated_at FROM facts ORDER BY category, key")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_facts_summary(self) -> str:
        """Returns formatted string of all remembered user facts for LLM prompt."""
        facts = self.get_all_facts()
        if not facts:
            return "Факты о пользователе пока не сохранены."
        
        lines = []
        for f in facts:
            lines.append(f"- [{f['category']}] {f['key']}: {f['value']}")
        return "\n".join(lines)

    # Conversation History
    def log_message(self, session_id: str, role: str, content: str, tool_calls: Optional[List[Dict]] = None) -> None:
        """Saves a message to the conversation history."""
        tool_calls_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO messages (session_id, role, content, tool_calls, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, role, content, tool_calls_json, time.time()))
            conn.commit()

    def get_recent_messages(self, limit: int = 20, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves recent conversation messages formatted for LLM context."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute("""
                    SELECT role, content, tool_calls FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC LIMIT ?
                """, (session_id, limit))
            else:
                cursor.execute("""
                    SELECT role, content, tool_calls FROM messages
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            messages = []
            for row in reversed(rows):
                msg = {"role": row["role"], "content": row["content"]}
                if row["tool_calls"]:
                    try:
                        msg["tool_calls"] = json.loads(row["tool_calls"])
                    except Exception:
                        pass
                messages.append(msg)
            return messages

    def clear_history(self) -> None:
        """Clears all conversation messages."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages")
            conn.commit()


# Global memory db singleton
memory_db = MemoryDB()
