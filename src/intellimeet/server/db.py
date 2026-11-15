"""SQLite persistence (stdlib only, thread-safe via a lock)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_is_auto INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL,              -- bot | upload | sample
    meet_link TEXT,
    status TEXT NOT NULL,              -- queued | joining | recording | transcribing | analyzing | completed | failed | cancelled
    stage_message TEXT,
    progress REAL NOT NULL DEFAULT 0,
    duration_requested INTEGER,
    duration_seconds REAL,
    analyze INTEGER NOT NULL DEFAULT 1,
    audio_path TEXT,
    original_filename TEXT,
    transcript_json TEXT,
    analysis_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_meeting ON events(meeting_id);
CREATE INDEX IF NOT EXISTS idx_chat_meeting ON chat_messages(meeting_id);
"""

ACTIVE_STATUSES = ("queued", "joining", "recording", "transcribing", "analyzing")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # --------------------------------------------------------------- helpers
    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    # -------------------------------------------------------------- meetings
    def create_meeting(self, **fields: Any) -> str:
        mid = fields.pop("id", None) or uuid.uuid4().hex[:12]
        fields.setdefault("created_at", now())
        fields.setdefault("status", "queued")
        cols = ["id", *fields.keys()]
        self._exec(
            f"INSERT INTO meetings ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            (mid, *fields.values()),
        )
        return mid

    def update_meeting(self, mid: str, **fields: Any) -> None:
        if not fields:
            return
        for key in ("transcript", "analysis"):
            if key in fields:
                val = fields.pop(key)
                fields[f"{key}_json"] = json.dumps(val) if val is not None else None
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE meetings SET {sets} WHERE id = ?", (*fields.values(), mid))

    def get_meeting_row(self, mid: str) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM meetings WHERE id = ?", (mid,))

    def list_meeting_rows(self, q: str = "", status: str = "") -> list[sqlite3.Row]:
        sql = "SELECT * FROM meetings WHERE 1=1"
        params: list[Any] = []
        if q:
            like = f"%{q.lower()}%"
            sql += " AND (lower(title) LIKE ? OR lower(coalesce(transcript_json,'')) LIKE ? OR lower(coalesce(analysis_json,'')) LIKE ?)"
            params += [like, like, like]
        if status == "active":
            sql += f" AND status IN ({', '.join('?' for _ in ACTIVE_STATUSES)})"
            params += list(ACTIVE_STATUSES)
        elif status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        return self._all(sql, tuple(params))

    def delete_meeting(self, mid: str) -> None:
        self._exec("DELETE FROM meetings WHERE id = ?", (mid,))

    def fail_interrupted(self) -> None:
        self._exec(
            f"UPDATE meetings SET status='failed', error='Interrupted: the server was restarted while this meeting was being processed.' "
            f"WHERE status IN ({', '.join('?' for _ in ACTIVE_STATUSES)})",
            ACTIVE_STATUSES,
        )

    # ---------------------------------------------------------------- events
    def add_event(self, mid: str, stage: str, message: str) -> None:
        self._exec("INSERT INTO events (meeting_id, stage, message, at) VALUES (?, ?, ?, ?)", (mid, stage, message, now()))

    def events(self, mid: str) -> list[dict]:
        return [dict(r) for r in self._all("SELECT stage, message, at FROM events WHERE meeting_id = ? ORDER BY id", (mid,))]

    # ------------------------------------------------------------------ chat
    def add_chat(self, mid: str, role: str, content: str) -> dict:
        at = now()
        cur = self._exec(
            "INSERT INTO chat_messages (meeting_id, role, content, created_at) VALUES (?, ?, ?, ?)", (mid, role, content, at)
        )
        return {"id": cur.lastrowid, "role": role, "content": content, "created_at": at}

    def chat(self, mid: str) -> list[dict]:
        return [
            dict(r)
            for r in self._all(
                "SELECT id, role, content, created_at FROM chat_messages WHERE meeting_id = ? ORDER BY id", (mid,)
            )
        ]

    def clear_chat(self, mid: str) -> None:
        self._exec("DELETE FROM chat_messages WHERE meeting_id = ?", (mid,))
