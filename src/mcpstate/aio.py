"""Async facade over :class:`HandleStore` for async MCP servers.

Every call delegates to the sync store via ``asyncio.to_thread``, so backend
I/O — and the patch retry loop's backoff sleeps — never block the event loop.
Semantics, errors, and return types are identical to the sync API.
"""
from __future__ import annotations

import asyncio
from typing import Any, Sequence

from .ops import PatchOp
from .store import KEEP_TTL, HandleInfo, HandleStore, Snapshot, _KeepTtl


class AsyncHandleStore:
    """Wrap a :class:`HandleStore` (or build one with :meth:`from_url`)."""

    def __init__(self, store: HandleStore) -> None:
        self._store = store

    @classmethod
    def from_url(
        cls,
        url: str | None = None,
        *,
        max_state_bytes: int = HandleStore.DEFAULT_MAX_STATE_BYTES,
    ) -> "AsyncHandleStore":
        return cls(HandleStore.from_url(url, max_state_bytes=max_state_bytes))

    async def mint(
        self,
        kind: str,
        state: dict[str, Any],
        *,
        user: str,
        ttl_days: float | None = None,
        writer: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._store.mint, kind, state, user=user, ttl_days=ttl_days, writer=writer
        )

    async def get(self, handle: str, *, user: str) -> Snapshot:
        return await asyncio.to_thread(self._store.get, handle, user=user)

    async def save(
        self,
        handle: str,
        state: dict[str, Any],
        *,
        user: str,
        expect_version: int,
        writer: str | None = None,
        ttl_days: float | None | _KeepTtl = KEEP_TTL,
    ) -> Snapshot:
        return await asyncio.to_thread(
            self._store.save,
            handle,
            state,
            user=user,
            expect_version=expect_version,
            writer=writer,
            ttl_days=ttl_days,
        )

    async def patch(
        self,
        handle: str,
        ops: Sequence[PatchOp],
        *,
        user: str,
        writer: str | None = None,
    ) -> Snapshot:
        return await asyncio.to_thread(
            self._store.patch, handle, ops, user=user, writer=writer
        )

    async def touch(
        self,
        handle: str,
        *,
        user: str,
        ttl_days: float | None,
        writer: str | None = None,
    ) -> Snapshot:
        return await asyncio.to_thread(
            self._store.touch, handle, user=user, ttl_days=ttl_days, writer=writer
        )

    async def list(
        self,
        user: str,
        *,
        kind: str | None = None,
        include_expired: bool = False,
    ) -> list[HandleInfo]:
        return await asyncio.to_thread(
            self._store.list, user, kind=kind, include_expired=include_expired
        )

    async def revoke(self, handle: str, *, user: str) -> None:
        await asyncio.to_thread(self._store.revoke, handle, user=user)

    async def sweep(self, user: str) -> int:
        return await asyncio.to_thread(self._store.sweep, user)

    async def close(self) -> None:
        await asyncio.to_thread(self._store.close)
