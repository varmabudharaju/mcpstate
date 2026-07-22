"""Redis backend — shared reach.

Point multiple server instances (or the same server on several machines) at
one Redis and state follows the user across all of them: this is the backend
that turns hand-off into cross-device sync. CAS uses an optimistic
WATCH/MULTI transaction so it works on any Redis-compatible server.

The module never imports the ``redis`` package — behavior comes entirely from
the injected client, so the core library stays dependency-free and tests can
use fakeredis.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from .base import Record

_PREFIX = "mcpstate"


def _q(part: str) -> str:
    # Percent-encode so a user or handle containing ':' (an OAuth sub like
    # "org:alice") cannot collide with the key layout.
    return quote(part, safe="")


# Records and indexes live under disjoint prefixes ("h" vs "i") so no username
# — even the literal "index" — can ever land in the index keyspace.
def _key(user: str, handle: str) -> str:
    return f"{_PREFIX}:h:{_q(user)}:{_q(handle)}"


def _index(user: str) -> str:
    return f"{_PREFIX}:i:{_q(user)}"


def _dump(record: Record) -> str:
    return json.dumps(
        {
            "kind": record.kind,
            "state": record.state,
            "version": record.version,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "expires_at": record.expires_at,
            "last_writer": record.last_writer,
        }
    )


def _load(raw: bytes | str) -> Record:
    d = json.loads(raw)
    return Record(
        kind=d["kind"],
        state=d["state"],
        version=d["version"],
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        expires_at=d["expires_at"],
        last_writer=d["last_writer"],
    )


class RedisBackend:
    def __init__(self, client: Any) -> None:
        self._r = client

    def get(self, user: str, handle: str) -> Record | None:
        raw = self._r.get(_key(user, handle))
        return _load(raw) if raw is not None else None

    def put_new(self, user: str, handle: str, record: Record) -> bool:
        created = bool(self._r.set(_key(user, handle), _dump(record), nx=True))
        if created:
            self._r.sadd(_index(user), handle)
        return created

    def cas_put(self, user: str, handle: str, expected_version: int, record: Record) -> bool:
        key = _key(user, handle)
        with self._r.pipeline() as pipe:
            try:
                pipe.watch(key)
                raw = pipe.get(key)
                if raw is None or _load(raw).version != expected_version:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(key, _dump(record))
                pipe.execute()
                return True
            except Exception as exc:
                # WatchError means a concurrent write landed first: the CAS loses.
                # Caught by name so this module imports without the redis package.
                if type(exc).__name__ == "WatchError":
                    return False
                raise

    def delete(self, user: str, handle: str) -> bool:
        removed = self._r.delete(_key(user, handle)) == 1
        self._r.srem(_index(user), handle)
        return removed

    def list(self, user: str) -> list[tuple[str, Record]]:
        handles = [
            h.decode() if isinstance(h, bytes) else h for h in self._r.smembers(_index(user))
        ]
        out = []
        for handle in handles:
            raw = self._r.get(_key(user, handle))
            if raw is not None:
                out.append((handle, _load(raw)))
        out.sort(key=lambda pair: pair[1].updated_at, reverse=True)
        return out

    def close(self) -> None:
        close = getattr(self._r, "close", None)
        if close:
            close()
