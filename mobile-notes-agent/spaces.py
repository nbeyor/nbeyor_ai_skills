"""Multi-space storage manager. Each space is its own SQLite database file."""

import os
import sqlite3
from datetime import datetime
from typing import Optional

from config import DATA_DIR

# -- Schemas per space type --------------------------------------------------

_CHECKLIST_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    priority INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_NOTEBOOK_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT NOT NULL,
    tags TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS spaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    space_type TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    space_slug TEXT,
    item_id INTEGER,
    remind_at TIMESTAMP NOT NULL,
    message TEXT NOT NULL,
    sent INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

SPACE_TYPES = {"checklist", "notebook"}


# -- Connection helpers -------------------------------------------------------

def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _meta_conn() -> sqlite3.Connection:
    _ensure_data_dir()
    conn = sqlite3.connect(os.path.join(DATA_DIR, "meta.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _space_conn(slug: str) -> sqlite3.Connection:
    _ensure_data_dir()
    conn = sqlite3.connect(os.path.join(DATA_DIR, f"{slug}.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Initialize the meta database."""
    conn = _meta_conn()
    conn.executescript(_META_SCHEMA)
    conn.close()


# -- Space management --------------------------------------------------------

def _get_space(slug: str) -> Optional[dict]:
    """Look up a space by slug. Returns None if not found."""
    conn = _meta_conn()
    row = conn.execute("SELECT * FROM spaces WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _normalize_slug(name: str) -> str:
    return name.strip().lower().replace(" ", "-")


def create_space(
    slug: str,
    display_name: str,
    space_type: str,
    description: str = "",
) -> dict:
    """Register a new space in meta.db and create its database file."""
    slug = _normalize_slug(slug)
    if space_type not in SPACE_TYPES:
        return {"error": f"Invalid space_type '{space_type}'. Must be one of: {', '.join(SPACE_TYPES)}"}

    existing = _get_space(slug)
    if existing:
        return {"error": f"Space '{slug}' already exists", "space": existing}

    conn = _meta_conn()
    conn.execute(
        "INSERT INTO spaces (slug, display_name, space_type, description) VALUES (?, ?, ?, ?)",
        (slug, display_name, space_type, description),
    )
    conn.commit()
    conn.close()

    # Create the space's database with the appropriate schema
    schema = _CHECKLIST_SCHEMA if space_type == "checklist" else _NOTEBOOK_SCHEMA
    sconn = _space_conn(slug)
    sconn.executescript(schema)
    sconn.close()

    return {"slug": slug, "display_name": display_name, "space_type": space_type, "created": True}


def _ensure_space(slug: str, space_type: str = "checklist") -> dict:
    """Get or create a space. Returns the space dict."""
    slug = _normalize_slug(slug)
    space = _get_space(slug)
    if space:
        return space
    display_name = slug.replace("-", " ").title()
    result = create_space(slug, display_name, space_type)
    if "error" in result:
        return result
    return _get_space(slug)


def list_spaces() -> list[dict]:
    """List all spaces with item counts."""
    conn = _meta_conn()
    rows = conn.execute("SELECT * FROM spaces ORDER BY display_name").fetchall()
    conn.close()

    result = []
    for row in rows:
        space = dict(row)
        space["item_count"] = _count_items(space["slug"], space["space_type"])
        result.append(space)
    return result


def _count_items(slug: str, space_type: str) -> int:
    """Count items in a space's database."""
    db_path = os.path.join(DATA_DIR, f"{slug}.db")
    if not os.path.exists(db_path):
        return 0
    sconn = _space_conn(slug)
    table = "items" if space_type == "checklist" else "entries"
    try:
        count = sconn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()["c"]
    except sqlite3.OperationalError:
        count = 0
    sconn.close()
    return count


# -- Item CRUD (dispatches based on space type) ------------------------------

def add_item(
    space_slug: str,
    content: str,
    # checklist-specific
    priority: Optional[int] = None,
    # notebook-specific
    title: Optional[str] = None,
    tags: Optional[str] = None,
    # auto-create space if missing
    space_type: str = "checklist",
) -> dict:
    """Add an item to a space. Auto-creates the space if it doesn't exist."""
    space = _ensure_space(space_slug, space_type)
    if "error" in space:
        return space
    slug = space["slug"]
    st = space["space_type"]

    sconn = _space_conn(slug)
    if st == "checklist":
        cursor = sconn.execute(
            "INSERT INTO items (content, priority) VALUES (?, ?)",
            (content, priority),
        )
        sconn.commit()
        item_id = cursor.lastrowid
        count = sconn.execute("SELECT COUNT(*) as c FROM items WHERE status = 'active'").fetchone()["c"]
        sconn.close()
        return {"item_id": item_id, "space": slug, "active_count": count}
    else:  # notebook
        cursor = sconn.execute(
            "INSERT INTO entries (title, content, tags) VALUES (?, ?, ?)",
            (title, content, tags or ""),
        )
        sconn.commit()
        item_id = cursor.lastrowid
        count = sconn.execute("SELECT COUNT(*) as c FROM entries").fetchone()["c"]
        sconn.close()
        return {"item_id": item_id, "space": slug, "total_entries": count}


def list_items(
    space_slug: str,
    status: Optional[str] = None,
    tag: Optional[str] = None,
) -> list[dict]:
    """List items from a space. For checklists, filter by status. For notebooks, filter by tag."""
    space = _get_space(_normalize_slug(space_slug))
    if not space:
        return [{"error": f"Space '{space_slug}' not found"}]

    slug = space["slug"]
    st = space["space_type"]
    sconn = _space_conn(slug)

    if st == "checklist":
        filter_status = status or "active"
        rows = sconn.execute(
            "SELECT * FROM items WHERE status = ? ORDER BY priority IS NULL, priority, created_at DESC",
            (filter_status,),
        ).fetchall()
    else:  # notebook
        if tag:
            rows = sconn.execute(
                "SELECT * FROM entries WHERE tags LIKE ? ORDER BY created_at DESC",
                (f"%{tag}%",),
            ).fetchall()
        else:
            rows = sconn.execute("SELECT * FROM entries ORDER BY created_at DESC").fetchall()

    sconn.close()
    items = [dict(r) for r in rows]
    for item in items:
        item["space"] = slug
        item["space_type"] = st
    return items


def update_item(
    space_slug: str,
    item_id: int,
    content: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    title: Optional[str] = None,
    tags: Optional[str] = None,
) -> dict:
    """Update an item in a space. Supports marking done, editing content, etc."""
    space = _get_space(_normalize_slug(space_slug))
    if not space:
        return {"error": f"Space '{space_slug}' not found"}

    slug = space["slug"]
    st = space["space_type"]
    sconn = _space_conn(slug)
    now = datetime.now().isoformat()

    if st == "checklist":
        # Build SET clause dynamically
        updates = ["updated_at = ?"]
        params = [now]
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        params.append(item_id)
        sconn.execute(f"UPDATE items SET {', '.join(updates)} WHERE id = ?", params)
        sconn.commit()
        row = sconn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    else:  # notebook
        updates = ["updated_at = ?"]
        params = [now]
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if tags is not None:
            updates.append("tags = ?")
            params.append(tags)
        params.append(item_id)
        sconn.execute(f"UPDATE entries SET {', '.join(updates)} WHERE id = ?", params)
        sconn.commit()
        row = sconn.execute("SELECT * FROM entries WHERE id = ?", (item_id,)).fetchone()

    sconn.close()
    if row:
        result = dict(row)
        result["space"] = slug
        return result
    return {"error": f"Item {item_id} not found in space '{slug}'"}


def delete_item(space_slug: str, item_id: int) -> dict:
    """Delete an item from a space."""
    space = _get_space(_normalize_slug(space_slug))
    if not space:
        return {"error": f"Space '{space_slug}' not found"}

    slug = space["slug"]
    st = space["space_type"]
    table = "items" if st == "checklist" else "entries"
    sconn = _space_conn(slug)

    row = sconn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if not row:
        sconn.close()
        return {"error": f"Item {item_id} not found in space '{slug}'"}

    content = row["content"]
    sconn.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
    sconn.commit()
    sconn.close()
    return {"item_id": item_id, "content": content, "space": slug, "deleted": True}


def search(query: str, space_slug: Optional[str] = None) -> list[dict]:
    """Search across one or all spaces by keyword."""
    if space_slug:
        spaces_to_search = [_get_space(_normalize_slug(space_slug))]
        spaces_to_search = [s for s in spaces_to_search if s]
    else:
        conn = _meta_conn()
        spaces_to_search = [dict(r) for r in conn.execute("SELECT * FROM spaces").fetchall()]
        conn.close()

    results = []
    for space in spaces_to_search:
        slug = space["slug"]
        st = space["space_type"]
        db_path = os.path.join(DATA_DIR, f"{slug}.db")
        if not os.path.exists(db_path):
            continue

        sconn = _space_conn(slug)
        if st == "checklist":
            rows = sconn.execute(
                "SELECT * FROM items WHERE content LIKE ? ORDER BY created_at DESC",
                (f"%{query}%",),
            ).fetchall()
        else:
            rows = sconn.execute(
                "SELECT * FROM entries WHERE content LIKE ? OR title LIKE ? OR tags LIKE ? ORDER BY created_at DESC",
                (f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()
        sconn.close()

        for row in rows:
            item = dict(row)
            item["space"] = slug
            item["space_type"] = st
            results.append(item)

    return results


# -- Reminders (global, stored in meta.db) -----------------------------------

def set_reminder(
    remind_at: str,
    message: str,
    space_slug: Optional[str] = None,
    item_id: Optional[int] = None,
) -> dict:
    """Schedule a reminder. Optionally link it to a space and item."""
    conn = _meta_conn()
    cursor = conn.execute(
        "INSERT INTO reminders (space_slug, item_id, remind_at, message) VALUES (?, ?, ?, ?)",
        (space_slug, item_id, remind_at, message),
    )
    conn.commit()
    reminder_id = cursor.lastrowid
    conn.close()
    return {"reminder_id": reminder_id, "remind_at": remind_at, "message": message}


def get_due_reminders() -> list[dict]:
    """Get all unsent reminders that are due."""
    conn = _meta_conn()
    now = datetime.now().isoformat()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE sent = 0 AND remind_at <= ? ORDER BY remind_at",
        (now,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        reminder = dict(row)
        # If linked to a space/item, fetch the item content for context
        if reminder.get("space_slug") and reminder.get("item_id"):
            space = _get_space(reminder["space_slug"])
            if space:
                sconn = _space_conn(space["slug"])
                table = "items" if space["space_type"] == "checklist" else "entries"
                item_row = sconn.execute(f"SELECT * FROM {table} WHERE id = ?", (reminder["item_id"],)).fetchone()
                sconn.close()
                if item_row:
                    reminder["linked_content"] = item_row["content"]
                    reminder["linked_space"] = space["display_name"]
        results.append(reminder)
    return results


def mark_reminder_sent(reminder_id: int) -> None:
    """Mark a reminder as sent."""
    conn = _meta_conn()
    conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
