"""SQLite store for conversions, kept on the Railway volume."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversions (
    id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    pages INTEGER,
    size_bytes INTEGER,
    status TEXT NOT NULL,
    progress_page INTEGER DEFAULT 0,
    settings TEXT,
    languages TEXT,
    directions TEXT,
    warnings TEXT,
    error TEXT,
    engine TEXT DEFAULT 'local',
    api_status TEXT,
    api_error TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

JSON_FIELDS = ("settings", "languages", "directions", "warnings")


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for f in JSON_FIELDS:
        d[f] = json.loads(d[f]) if d[f] else None
    return d


def create(file_name: str, pages: int | None, size_bytes: int, status: str = "uploaded") -> dict:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        connect().execute(
            "INSERT INTO conversions (id, file_name, pages, size_bytes, status, created_at) VALUES (?,?,?,?,?,?)",
            (job_id, file_name, pages, size_bytes, status, time.time()),
        )
        connect().commit()
    return get(job_id)


def get(job_id: str) -> dict | None:
    with _lock:
        return _row(connect().execute("SELECT * FROM conversions WHERE id=?", (job_id,)).fetchone())


def list_all() -> list[dict]:
    with _lock:
        rows = connect().execute("SELECT * FROM conversions ORDER BY created_at DESC").fetchall()
    return [_row(r) for r in rows]


def update(job_id: str, **fields) -> None:
    if not fields:
        return
    for f in JSON_FIELDS:
        if f in fields and fields[f] is not None:
            fields[f] = json.dumps(fields[f], ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        connect().execute(f"UPDATE conversions SET {cols} WHERE id=?", (*fields.values(), job_id))
        connect().commit()


def set_status_if(job_id: str, allowed: tuple[str, ...], **fields) -> bool:
    """Update only when the current status is one of ``allowed``; True if it was."""
    for f in JSON_FIELDS:
        if f in fields and fields[f] is not None:
            fields[f] = json.dumps(fields[f], ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    marks = ",".join("?" * len(allowed))
    with _lock:
        cur = connect().execute(
            f"UPDATE conversions SET {cols} WHERE id=? AND status IN ({marks})",
            (*fields.values(), job_id, *allowed),
        )
        connect().commit()
        return cur.rowcount > 0


def delete(job_id: str) -> None:
    with _lock:
        connect().execute("DELETE FROM conversions WHERE id=?", (job_id,))
        connect().commit()


def next_queued() -> dict | None:
    with _lock:
        return _row(connect().execute(
            "SELECT * FROM conversions WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone())


def requeue_interrupted() -> None:
    """After a restart, jobs that were running go back in the queue; their
    finished pages are cached, so they continue where they stopped."""
    with _lock:
        connect().execute("UPDATE conversions SET status='queued' WHERE status='converting'")
        connect().commit()


def kv_get(key: str, default=None):
    with _lock:
        r = connect().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def kv_set(key: str, value) -> None:
    with _lock:
        connect().execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                          (key, json.dumps(value, ensure_ascii=False)))
        connect().commit()
