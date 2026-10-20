"""
SQLite storage for ECHO. The database file is created automatically at
``database/echo.db`` the first time the app runs. All queries are parameterised.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

log = logging.getLogger("echo.db")

DB_PATH = Path(__file__).resolve().parent / "echo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT,
    image_path      TEXT,
    extracted_text  TEXT,
    extracted_fields TEXT,          -- JSON object of facts shown to the user
    important_date  TEXT,           -- ISO date or NULL
    date_type       TEXT,
    date_method     TEXT,
    confidence      REAL,
    source          TEXT DEFAULT 'image',   -- 'image' | 'demo_text'
    is_demo         INTEGER DEFAULT 0,
    explanation     TEXT,           -- JSON list of sentences
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    status          TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS reminders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id     INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    reminder_date TEXT NOT NULL,
    days_before   INTEGER NOT NULL,
    message       TEXT,
    status        TEXT DEFAULT 'pending',  -- 'pending' | 'done'
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT,
    scan_type   TEXT,        -- 'image' | 'demo_text'
    ocr_text    TEXT,
    category    TEXT,
    confidence  REAL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_date ON memories(important_date);
CREATE INDEX IF NOT EXISTS idx_reminders_memory ON reminders(memory_id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> bool:
    """Create tables if needed. Returns True if the database was newly created."""
    is_new = not DB_PATH.exists()
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    return is_new


def db_ok() -> bool:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error as exc:
        log.error("Database check failed: %s", exc)
        return False


def _row_to_memory(row: sqlite3.Row) -> dict:
    m = dict(row)
    for key, default in (("extracted_fields", {}), ("explanation", [])):
        try:
            m[key] = json.loads(m.get(key) or "null") or default
        except (TypeError, ValueError):
            m[key] = default
    return m


_MEMORY_SELECT = """
SELECT m.*, r.id AS reminder_id, r.reminder_date, r.days_before, r.status AS reminder_status, r.message AS reminder_message
FROM memories m
LEFT JOIN reminders r ON r.id = (SELECT id FROM reminders WHERE memory_id = m.id ORDER BY id DESC LIMIT 1)
"""


# ------------------------------------------------------------------ memories
def create_memory(data: dict) -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO memories (title, category, description, image_path, extracted_text, extracted_fields,
                   important_date, date_type, date_method, confidence, source, is_demo, explanation,
                   created_at, updated_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (data["title"], data["category"], data.get("description"), data.get("image_path"),
             data.get("extracted_text"), json.dumps(data.get("extracted_fields") or {}),
             data.get("important_date"), data.get("date_type"), data.get("date_method"),
             data.get("confidence"), data.get("source", "image"), int(bool(data.get("is_demo"))),
             json.dumps(data.get("explanation") or []), now, now),
        )
        return cur.lastrowid


def get_memory(memory_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(_MEMORY_SELECT + " WHERE m.id = ?", (memory_id,)).fetchone()
    return _row_to_memory(row) if row else None


def list_memories(search: str = "", category: str = "", limit: Optional[int] = None) -> list[dict]:
    sql = _MEMORY_SELECT + " WHERE m.status = 'active'"
    params: list = []
    if search:
        sql += " AND (m.title LIKE ? OR m.description LIKE ? OR m.category LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if category:
        sql += " AND m.category = ?"
        params.append(category)
    sql += " ORDER BY m.created_at DESC, m.id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_memory(r) for r in rows]


def update_memory(memory_id: int, fields: dict) -> bool:
    allowed = {"title", "category", "description", "important_date", "date_type", "date_method", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    assignments = ", ".join(f"{k} = ?" for k in updates)  # keys come from the allow-list above
    with get_connection() as conn:
        cur = conn.execute(f"UPDATE memories SET {assignments}, updated_at = ? WHERE id = ?",
                           (*updates.values(), _now(), memory_id))
        return cur.rowcount > 0


def delete_memory(memory_id: int) -> Optional[str]:
    """Delete a memory and its reminders. Returns its image path (for cleanup) or None."""
    with get_connection() as conn:
        row = conn.execute("SELECT image_path FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM reminders WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return row["image_path"] or ""


def delete_demo_memories() -> int:
    with get_connection() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM memories WHERE is_demo = 1").fetchall()]
        for mid in ids:
            conn.execute("DELETE FROM reminders WHERE memory_id = ?", (mid,))
        conn.execute("DELETE FROM memories WHERE is_demo = 1")
    return len(ids)


def count_demo_memories() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM memories WHERE is_demo = 1").fetchone()[0]


# ----------------------------------------------------------------- reminders
def upsert_reminder(memory_id: int, reminder_date: str, days_before: int, message: str) -> int:
    """One active reminder per memory: replace any existing one."""
    with get_connection() as conn:
        conn.execute("DELETE FROM reminders WHERE memory_id = ?", (memory_id,))
        cur = conn.execute(
            "INSERT INTO reminders (memory_id, reminder_date, days_before, message, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)", (memory_id, reminder_date, int(days_before), message, _now()))
        return cur.lastrowid


def delete_reminders_for(memory_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM reminders WHERE memory_id = ?", (memory_id,))


def set_reminder_status(reminder_id: int, status: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
        return cur.rowcount > 0


def due_reminders(today_iso: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT r.*, m.title, m.category, m.important_date, m.date_type FROM reminders r
               JOIN memories m ON m.id = r.memory_id
               WHERE r.status = 'pending' AND r.reminder_date <= ? AND m.status = 'active'
               ORDER BY m.important_date""", (today_iso,)).fetchall()
    return [dict(r) for r in rows]


# -------------------------------------------------------------- scan history
def add_scan_history(filename: Optional[str], scan_type: str, ocr_text: str, category: str, confidence: float) -> None:
    with get_connection() as conn:
        conn.execute("INSERT INTO scan_history (filename, scan_type, ocr_text, category, confidence, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (filename, scan_type, ocr_text, category, confidence, _now()))


def recent_scans(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, filename, scan_type, category, confidence, created_at FROM scan_history "
                            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ settings
def get_setting(key: str, default=None):
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return row["value"]


def set_setting(key: str, value) -> None:
    with get_connection() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
