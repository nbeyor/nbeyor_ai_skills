"""SQLite storage for notes, categories, and reminders."""

import os
import sqlite3
from datetime import datetime
from typing import Optional

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER REFERENCES categories(id),
    content TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER REFERENCES notes(id),
    remind_at TIMESTAMP NOT NULL,
    message TEXT,
    sent INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript(_SCHEMA)
    conn.close()


def _ensure_category(conn: sqlite3.Connection, name: str) -> int:
    """Get or create a category by name. Returns the category id."""
    name = name.strip().lower().replace(" ", "-")
    row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    conn.commit()
    return cursor.lastrowid


def add_note(content: str, category: str) -> dict:
    """Add a note to a category (auto-creates category if needed)."""
    conn = _get_conn()
    cat_id = _ensure_category(conn, category)
    cursor = conn.execute(
        "INSERT INTO notes (category_id, content) VALUES (?, ?)",
        (cat_id, content),
    )
    conn.commit()
    note_id = cursor.lastrowid
    count = conn.execute(
        "SELECT COUNT(*) as c FROM notes WHERE category_id = ? AND status = 'active'",
        (cat_id,),
    ).fetchone()["c"]
    conn.close()
    return {"note_id": note_id, "category": category, "active_count": count}


def list_notes(category: Optional[str] = None, status: str = "active") -> list[dict]:
    """List notes, optionally filtered by category and/or status."""
    conn = _get_conn()
    if category:
        cat_name = category.strip().lower().replace(" ", "-")
        rows = conn.execute(
            """SELECT n.id, n.content, n.status, n.created_at, c.name as category
               FROM notes n JOIN categories c ON n.category_id = c.id
               WHERE c.name = ? AND n.status = ?
               ORDER BY n.created_at DESC""",
            (cat_name, status),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT n.id, n.content, n.status, n.created_at, c.name as category
               FROM notes n JOIN categories c ON n.category_id = c.id
               WHERE n.status = ?
               ORDER BY c.name, n.created_at DESC""",
            (status,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_done(note_id: int) -> dict:
    """Mark a note as done."""
    conn = _get_conn()
    conn.execute(
        "UPDATE notes SET status = 'done', updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(), note_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT n.content, c.name as category FROM notes n JOIN categories c ON n.category_id = c.id WHERE n.id = ?",
        (note_id,),
    ).fetchone()
    conn.close()
    if row:
        return {"note_id": note_id, "content": row["content"], "category": row["category"], "status": "done"}
    return {"error": f"Note {note_id} not found"}


def delete_note(note_id: int) -> dict:
    """Delete a note permanently."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT n.content, c.name as category FROM notes n JOIN categories c ON n.category_id = c.id WHERE n.id = ?",
        (note_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"error": f"Note {note_id} not found"}
    content = row["content"]
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    return {"note_id": note_id, "content": content, "deleted": True}


def list_categories() -> list[dict]:
    """List all categories with counts of active and done notes."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT c.name, c.description,
                  SUM(CASE WHEN n.status = 'active' THEN 1 ELSE 0 END) as active_count,
                  SUM(CASE WHEN n.status = 'done' THEN 1 ELSE 0 END) as done_count
           FROM categories c
           LEFT JOIN notes n ON n.category_id = c.id
           GROUP BY c.id
           ORDER BY c.name""",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_notes(query: str) -> list[dict]:
    """Search notes by content (case-insensitive substring match)."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT n.id, n.content, n.status, n.created_at, c.name as category
           FROM notes n JOIN categories c ON n.category_id = c.id
           WHERE n.content LIKE ?
           ORDER BY n.created_at DESC""",
        (f"%{query}%",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_reminder(
    remind_at: str,
    message: str,
    note_id: Optional[int] = None,
) -> dict:
    """Schedule a reminder. remind_at should be ISO 8601 format."""
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO reminders (note_id, remind_at, message) VALUES (?, ?, ?)",
        (note_id, remind_at, message),
    )
    conn.commit()
    reminder_id = cursor.lastrowid
    conn.close()
    return {"reminder_id": reminder_id, "remind_at": remind_at, "message": message}


def get_due_reminders() -> list[dict]:
    """Get all unsent reminders that are due."""
    conn = _get_conn()
    now = datetime.now().isoformat()
    rows = conn.execute(
        """SELECT r.id, r.note_id, r.remind_at, r.message,
                  n.content as note_content, c.name as category
           FROM reminders r
           LEFT JOIN notes n ON r.note_id = n.id
           LEFT JOIN categories c ON n.category_id = c.id
           WHERE r.sent = 0 AND r.remind_at <= ?
           ORDER BY r.remind_at""",
        (now,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int) -> None:
    """Mark a reminder as sent."""
    conn = _get_conn()
    conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
