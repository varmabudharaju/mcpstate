"""HandleStore — the public API. State that follows the user, not the session.

Servers mint opaque handles, the model passes them back as ordinary tool
arguments (the pattern the stateless MCP spec blesses), and this store keeps
what they point to: durable, user-scoped, versioned, TTL'd.
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

from .backends.base import Backend, Record
from .errors import BackendError, HandleExpired, HandleNotFound, StaleWrite
from .ops import PatchOp, apply_ops

_KIND_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def _dt(ts: float | None) -> datetime | None:
    return None if ts is None else datetime.fromtimestamp(ts, tz=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat()


@dataclass(frozen=True)
class HandleInfo:
    """Metadata about a handle — everything except the state itself."""

    handle: str
    kind: str
    version: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    last_writer: str | None

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "kind": self.kind,
            "version": self.version,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "expires_at": _iso(self.expires_at),
            "last_writer": self.last_writer,
        }


@dataclass(frozen=True)
class Snapshot(HandleInfo):
    """A handle's state plus the freshness metadata needed to save it back."""

    state: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {**super().to_dict(), "state": self.state}


def _snapshot(handle: str, rec: Record) -> Snapshot:
    return Snapshot(
        handle=handle,
        kind=rec.kind,
        version=rec.version,
        created_at=_dt(rec.created_at),
        updated_at=_dt(rec.updated_at),
        expires_at=_dt(rec.expires_at),
        last_writer=rec.last_writer,
        state=rec.state,
    )


class HandleStore:
    def __init__(self, backend: Backend, *, clock: Callable[[], float] = time.time) -> None:
        self._backend = backend
        self._clock = clock

    def _load_live(self, user: str, handle: str) -> Record:
        rec = self._backend.get(user, handle)
        if rec is None:
            raise HandleNotFound(
                f"No state exists for handle '{handle}'. It may never have existed, "
                "or it was revoked. Use list to see available handles.",
                handle=handle,
            )
        if rec.expires_at is not None and rec.expires_at <= self._clock():
            ttl_days = round((rec.expires_at - rec.created_at) / 86400, 3)
            raise HandleExpired(
                f"Handle '{handle}' expired at {_iso(_dt(rec.expires_at))} "
                f"(TTL was {ttl_days} days). Mint a new handle to start fresh.",
                handle=handle,
                expired_at=_iso(_dt(rec.expires_at)),
                ttl_days=ttl_days,
            )
        return rec

    def mint(
        self,
        kind: str,
        state: dict,
        *,
        user: str,
        ttl_days: float | None = None,
        writer: str | None = None,
    ) -> str:
        """Create durable state and return its opaque handle."""
        if not _KIND_RE.match(kind):
            raise ValueError(f"Invalid kind {kind!r}: must match ^[a-z][a-z0-9-]{{0,31}}$")
        if not isinstance(state, dict):
            raise ValueError(
                f"State root must be a JSON object (dict), got {type(state).__name__}"
            )
        now = self._clock()
        expires_at = None if ttl_days is None else now + ttl_days * 86400
        record = Record(
            kind=kind,
            state=state,
            version=1,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
            last_writer=writer,
        )
        for _ in range(5):
            handle = f"{kind}_" + "".join(secrets.choice(_ALPHABET) for _ in range(8))
            if self._backend.put_new(user, handle, record):
                return handle
        raise BackendError("Could not mint a unique handle after 5 attempts.", kind=kind)

    def get(self, handle: str, *, user: str) -> Snapshot:
        """Load current state with freshness metadata."""
        return _snapshot(handle, self._load_live(user, handle))

    def close(self) -> None:
        self._backend.close()
