"""SQLite backend — the zero-config default.

Covers cross-conversation and cross-client continuity on one machine. The
compare-and-swap is a single ``UPDATE ... WHERE version = ?`` statement, which
SQLite executes atomically. Each thread gets its own connection — WAL mode
lets readers proceed while a writer writes — and writes serialize inside
SQLite itself, waiting out contention via the busy timeout.
"""
from __future__ import annotations

import itertools
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

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

_memory_counter = itertools.count()


class SQLiteBackend:
    def __init__(self, path: str) -> None:
        if path == ":memory:":
            # A per-instance shared-cache URI so every thread's connection sees
            # the same in-memory database; a plain :memory: connect would give
            # each thread its own empty one.
            self._path = f"file:mcpstate-mem-{next(_memory_counter)}?mode=memory&cache=shared"
            self._uri = True
        else:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            self._path = str(p)
            self._uri = False
        self._local = threading.local()
        self._registry: list[sqlite3.Connection] = []
        self._registry_lock = threading.Lock()
        self._conn  # connect eagerly: surface path errors and create the schema now

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # timeout doubles as the busy handler: another thread or process
            # writing the same DB (the cross-client axis) waits up to 10s
            # instead of erroring. check_same_thread is off only so close()
            # can reap connections owned by finished threads; each connection
            # is otherwise used solely by the thread that created it.
            conn = sqlite3.connect(
                self._path, timeout=10.0, uri=self._uri, check_same_thread=False
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_SCHEMA)
            conn.commit()
            self._local.conn = conn
            with self._registry_lock:
                self._registry.append(conn)
        return conn

    def _row_to_record(self, row: tuple[Any, ...]) -> Record:
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
        row = self._conn.execute(
            "SELECT kind, state, version, created_at, updated_at, expires_at, last_writer "
            "FROM handles WHERE user = ? AND handle = ?",
            (user, handle),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def put_new(self, user: str, handle: str, record: Record) -> bool:
        conn = self._conn
        cur = conn.execute(
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
        conn.commit()
        return cur.rowcount == 1

    def cas_put(self, user: str, handle: str, expected_version: int, record: Record) -> bool:
        conn = self._conn
        cur = conn.execute(
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
        conn.commit()
        return cur.rowcount == 1

    def delete(self, user: str, handle: str) -> bool:
        conn = self._conn
        cur = conn.execute(
            "DELETE FROM handles WHERE user = ? AND handle = ?", (user, handle)
        )
        conn.commit()
        return cur.rowcount == 1

    def list(self, user: str) -> list[tuple[str, Record]]:
        rows = self._conn.execute(
            "SELECT handle, kind, state, version, created_at, updated_at, expires_at, last_writer "
            "FROM handles WHERE user = ? ORDER BY updated_at DESC",
            (user,),
        ).fetchall()
        return [(row[0], self._row_to_record(row[1:])) for row in rows]

    def close(self) -> None:
        with self._registry_lock:
            conns, self._registry = self._registry, []
            self._local = threading.local()
        for conn in conns:
            conn.close()
