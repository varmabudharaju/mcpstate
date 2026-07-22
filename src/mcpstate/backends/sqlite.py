"""SQLite backend — the zero-config default.

Covers cross-conversation and cross-client continuity on one machine. The
compare-and-swap is a single ``UPDATE ... WHERE version = ?`` statement, which
SQLite executes atomically; a lock serializes connection access across threads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .base import Record

_SCHEMA = """
CREATE TABLE IF NOT EXISTS handles (
  user TEXT NOT NULL,
  handle TEXT NOT NULL,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  expires_at REAL,
  last_writer TEXT,
  PRIMARY KEY (user, handle)
)
"""


class SQLiteBackend:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            path = str(p)
        self._lock = threading.Lock()
        # timeout doubles as the busy handler: a second process writing the same
        # DB (the cross-client axis) waits up to 10s instead of erroring.
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    def _row_to_record(self, row: tuple) -> Record:
        kind, state, version, created_at, updated_at, expires_at, last_writer = row
        return Record(
            kind=kind,
            state=json.loads(state),
            version=version,
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            last_writer=last_writer,
        )

    def get(self, user: str, handle: str) -> Record | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT kind, state, version, created_at, updated_at, expires_at, last_writer "
                "FROM handles WHERE user = ? AND handle = ?",
                (user, handle),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def put_new(self, user: str, handle: str, record: Record) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO handles "
                "(user, handle, kind, state, version, created_at, updated_at, expires_at, last_writer) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user,
                    handle,
                    record.kind,
                    json.dumps(record.state),
                    record.version,
                    record.created_at,
                    record.updated_at,
                    record.expires_at,
                    record.last_writer,
                ),
            )
            self._conn.commit()
        return cur.rowcount == 1

    def cas_put(self, user: str, handle: str, expected_version: int, record: Record) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE handles SET kind = ?, state = ?, version = ?, created_at = ?, "
                "updated_at = ?, expires_at = ?, last_writer = ? "
                "WHERE user = ? AND handle = ? AND version = ?",
                (
                    record.kind,
                    json.dumps(record.state),
                    record.version,
                    record.created_at,
                    record.updated_at,
                    record.expires_at,
                    record.last_writer,
                    user,
                    handle,
                    expected_version,
                ),
            )
            self._conn.commit()
        return cur.rowcount == 1

    def delete(self, user: str, handle: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM handles WHERE user = ? AND handle = ?", (user, handle)
            )
            self._conn.commit()
        return cur.rowcount == 1

    def list(self, user: str) -> list[tuple[str, Record]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT handle, kind, state, version, created_at, updated_at, expires_at, last_writer "
                "FROM handles WHERE user = ? ORDER BY updated_at DESC",
                (user,),
            ).fetchall()
        return [(row[0], self._row_to_record(row[1:])) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
