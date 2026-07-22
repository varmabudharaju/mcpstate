"""HandleStore — the public API. State that follows the user, not the session.

Servers mint opaque handles, the model passes them back as ordinary tool
arguments (the pattern the stateless MCP spec blesses), and this store keeps
what they point to: durable, user-scoped, versioned, TTL'd.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

from .backends.base import Backend, Record
from .errors import (
    BackendError,
    HandleExpired,
    HandleNotFound,
    PatchError,
    StaleWrite,
    StateTooLarge,
)
from .ops import PatchOp, apply_ops

_KIND_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_CREDENTIALS_RE = re.compile(r"://[^@/]*@")
_MAX_TTL_DAYS = 36525  # ~100 years; keeps expires_at well inside the datetime range
_PATCH_MAX_ATTEMPTS = 100  # with backoff, spurious failure is negligible even under load


def _redact(url: str) -> str:
    """Strip userinfo (passwords) from a URL before it enters any error message."""
    return _CREDENTIALS_RE.sub("://***@", url)


def _validate_ttl(ttl_days: float | None) -> float | None:
    if ttl_days is None:
        return None
    if isinstance(ttl_days, bool) or not isinstance(ttl_days, (int, float)):
        raise ValueError(f"ttl_days must be a number, got {type(ttl_days).__name__}")
    import math

    if not math.isfinite(ttl_days):
        raise ValueError("ttl_days must be finite (not inf or nan)")
    if ttl_days <= 0:
        raise ValueError(f"ttl_days must be positive, got {ttl_days}")
    if ttl_days > _MAX_TTL_DAYS:
        raise ValueError(f"ttl_days must be <= {_MAX_TTL_DAYS} (~100 years), got {ttl_days}")
    return ttl_days


def _dt_req(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _dt(ts: float | None) -> datetime | None:
    return None if ts is None else _dt_req(ts)


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
        created_at=_dt_req(rec.created_at),
        updated_at=_dt_req(rec.updated_at),
        expires_at=_dt(rec.expires_at),
        last_writer=rec.last_writer,
        state=rec.state,
    )


class HandleStore:
    DEFAULT_URL = "sqlite:///~/.mcpstate/state.db"
    DEFAULT_MAX_STATE_BYTES = 1_048_576  # 1 MiB

    def __init__(
        self,
        backend: Backend,
        *,
        clock: Callable[[], float] = time.time,
        max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
    ) -> None:
        self._backend = backend
        self._clock = clock
        self._max_state_bytes = max_state_bytes

    def _check_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            raise ValueError(
                f"State root must be a JSON object (dict), got {type(state).__name__}"
            )
        try:
            # allow_nan=False rejects Infinity/NaN, which are invalid JSON and would
            # otherwise persist as immortal, non-interoperable records.
            size = len(json.dumps(state, allow_nan=False).encode())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"State contains values that are not JSON-serializable: {exc}") from None
        except RecursionError:
            raise ValueError(
                "State is too deeply nested to serialize. Flatten it or split the work."
            ) from None
        if size > self._max_state_bytes:
            raise StateTooLarge(
                f"State is {size} bytes; the limit is {self._max_state_bytes}. "
                "Store a summary or split the work across smaller handles.",
                size_bytes=size,
                limit_bytes=self._max_state_bytes,
            )

    @classmethod
    def from_url(cls, url: str | None = None) -> "HandleStore":
        """Construct from a backend URL; None selects the local SQLite default."""
        url = url or cls.DEFAULT_URL
        if url.startswith("sqlite:///"):
            from .backends.sqlite import SQLiteBackend

            path = url[len("sqlite:///"):]
            if not path:
                raise ValueError(
                    "Empty sqlite path. Use sqlite:///path/to.db or sqlite:///:memory:"
                )
            return cls(SQLiteBackend(path))
        if url.startswith(("redis://", "rediss://")):
            try:
                import redis
            except ImportError:
                raise BackendError(
                    'Redis backend requires the redis package: pip install "mcpstate[redis]"',
                    url=_redact(url),
                ) from None
            from .backends.redis import RedisBackend

            return cls(RedisBackend(redis.Redis.from_url(url)))
        raise ValueError(
            f"Unsupported backend URL {_redact(url)!r}. "
            "Supported: sqlite:///path, redis://host[:port]/db"
        )

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
        ttl_days = _validate_ttl(ttl_days)
        self._check_state(state)
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

    def save(
        self,
        handle: str,
        state: dict,
        *,
        user: str,
        expect_version: int,
        writer: str | None = None,
    ) -> Snapshot:
        """Replace the state, declaring which version was read.

        A stale ``expect_version`` raises :class:`StaleWrite` whose payload
        carries the full current snapshot — hand it to the model to merge and
        retry.
        """
        self._check_state(state)
        current = self._load_live(user, handle)
        new = Record(
            kind=current.kind,
            state=state,
            version=expect_version + 1,
            created_at=current.created_at,
            updated_at=self._clock(),
            expires_at=current.expires_at,
            last_writer=writer,
        )
        if current.version != expect_version or not self._backend.cas_put(
            user, handle, expect_version, new
        ):
            # Re-read to attach the winner's state. The handle may have been
            # revoked or expired in the race; surface that accurately rather
            # than a StaleWrite with no current state to merge.
            try:
                latest = _snapshot(handle, self._load_live(user, handle))
            except (HandleNotFound, HandleExpired):
                raise HandleNotFound(
                    f"The state for '{handle}' was deleted or expired while you were "
                    "editing it, and your save (version "
                    f"{expect_version}) did not apply. Start fresh with a new handle.",
                    handle=handle,
                ) from None
            raise StaleWrite(
                f"State was modified by '{latest.last_writer or 'another session'}' at "
                f"{_iso(latest.updated_at)} (now version {latest.version}, you expected "
                f"{expect_version}). Re-read the current state below and re-apply your "
                "change on top of it.",
                current=latest.to_dict(),
                expected_version=expect_version,
            )
        return _snapshot(handle, new)

    def patch(
        self,
        handle: str,
        ops: Sequence[PatchOp],
        *,
        user: str,
        writer: str | None = None,
    ) -> Snapshot:
        """Apply commutative ops with no version check — they cannot conflict.

        A CAS retry loop with backoff: contention re-reads and re-applies, so
        concurrent patches from different sessions all land. A patch that
        produces no change is a no-op — it does not bump the version or
        reassign the writer, so it never steals attribution or induces a
        spurious StaleWrite for a concurrent save.
        """
        for attempt in range(_PATCH_MAX_ATTEMPTS):
            current = self._load_live(user, handle)
            try:
                new_state = apply_ops(current.state, ops)
            except RecursionError:
                raise PatchError(
                    "Applying these ops produced state too deeply nested to store.",
                    reason="too_deep",
                ) from None
            if new_state == current.state:
                return _snapshot(handle, current)  # no-op: do not write
            self._check_state(new_state)
            new = Record(
                kind=current.kind,
                state=new_state,
                version=current.version + 1,
                created_at=current.created_at,
                updated_at=self._clock(),
                expires_at=current.expires_at,
                last_writer=writer,
            )
            if self._backend.cas_put(user, handle, current.version, new):
                return _snapshot(handle, new)
            # Lost the race: back off briefly (bounded, attempt-scaled) and retry.
            time.sleep(min(0.05, 0.0005 * (attempt + 1)))
        raise BackendError(
            f"Patch on '{handle}' failed after {_PATCH_MAX_ATTEMPTS} attempts under "
            "sustained write contention.",
            handle=handle,
        )

    def list(
        self,
        user: str,
        *,
        kind: str | None = None,
        include_expired: bool = False,
    ) -> list[HandleInfo]:
        """The user's handles — metadata only, most recently updated first."""
        now = self._clock()
        infos = []
        for handle, rec in self._backend.list(user):
            if kind is not None and rec.kind != kind:
                continue
            if not include_expired and rec.expires_at is not None and rec.expires_at <= now:
                continue
            infos.append(
                HandleInfo(
                    handle=handle,
                    kind=rec.kind,
                    version=rec.version,
                    created_at=_dt_req(rec.created_at),
                    updated_at=_dt_req(rec.updated_at),
                    expires_at=_dt(rec.expires_at),
                    last_writer=rec.last_writer,
                )
            )
        return infos

    def revoke(self, handle: str, *, user: str) -> None:
        """Delete the handle and its state (expired handles may be revoked too)."""
        if not self._backend.delete(user, handle):
            raise HandleNotFound(
                f"No state exists for handle '{handle}'; nothing to revoke.", handle=handle
            )

    def sweep(self, user: str) -> int:
        """Physically remove the user's expired records; return how many."""
        now = self._clock()
        removed = 0
        for handle, rec in self._backend.list(user):
            if rec.expires_at is not None and rec.expires_at <= now:
                if self._backend.delete(user, handle):
                    removed += 1
        return removed

    def close(self) -> None:
        self._backend.close()
