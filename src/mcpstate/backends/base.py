"""Storage protocol. Six methods; implement them and any store works.

Backends persist opaque records keyed by ``(user, handle)``. All conflict
semantics live in the single primitive ``cas_put`` — an atomic write that
succeeds only when the stored version still matches ``expected_version``.
Expiry is not a backend concern; the store applies TTL logic on top.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Record:
    kind: str
    state: dict[str, Any]
    version: int
    created_at: float
    updated_at: float
    expires_at: float | None
    last_writer: str | None


class Backend(Protocol):
    def get(self, user: str, handle: str) -> Record | None:
        """Return the record, or None if absent."""

    def put_new(self, user: str, handle: str, record: Record) -> bool:
        """Create the record. False (and no write) if the handle already exists."""

    def cas_put(self, user: str, handle: str, expected_version: int, record: Record) -> bool:
        """Atomically replace the record iff its version equals expected_version."""

    def delete(self, user: str, handle: str) -> bool:
        """Remove the record. False if it was absent."""

    def list(self, user: str) -> list[tuple[str, Record]]:
        """All of the user's (handle, record) pairs, most recently updated first."""

    def close(self) -> None:
        """Release resources."""
