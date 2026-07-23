# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.2.0 - 2026-07-23

### Added

- TTL renewal: `HandleStore.touch()` resets a handle's expiry from now (or
  clears it with `ttl_days=None`); `save()` accepts `ttl_days` (default
  `KEEP_TTL` leaves expiry unchanged); new flagship tool `state_touch`, and
  `state_save` renews expiry on update when `ttl_days` is passed. Previously
  a TTL was fixed at mint forever.
- `AsyncHandleStore`: async facade with identical semantics — every call runs
  via `asyncio.to_thread`, so async MCP servers never block the event loop.
- The `merge` patch op accepts an optional dotted `path` (default `""` = state
  root), matching the other ops.
- The 1 MiB state cap is now truly configurable for the flagship server:
  `MCPSTATE_MAX_STATE_BYTES` env var, plus `from_url(..., max_state_bytes=)`.

### Changed

- SQLite backend: one WAL connection per thread instead of a single
  lock-serialized connection — concurrent readers no longer queue behind every
  other operation. `sqlite:///:memory:` now uses a per-instance shared-cache
  database so all threads see the same state.
- Redis backend: `list()` fetches all records with one `MGET` instead of N
  `GET`s and prunes dangling index members; `WatchError` subclasses are
  correctly treated as lost CAS races.
- mypy runs in `--strict` mode; CI matrix extended to Python 3.13 and 3.14.

### Fixed

- Docs now state patch-op semantics precisely (append is conflict-free;
  same-key `set_key`/`merge` resolve last-write-wins), document Redis
  durability caveats, and note that `kind` is ignored on `state_save` updates.

## 0.1.0 - 2026-07-22

### Added

- `HandleStore`: mint, get, versioned save, commutative patch, list, revoke,
  and sweep — durable state behind opaque handles, scoped to a user, with
  per-handle TTL and lazy expiry.
- Conflict kit: compare-and-swap saves with agent-legible `StaleWrite`
  rejections carrying the full current snapshot; `Append`/`SetKey`/`DelKey`/
  `Merge` patch ops that apply without version checks; freshness metadata
  (version, updated_at, last_writer) on every read.
- Backends: SQLite (zero-config default) and Redis (shared reach for
  multi-instance and cross-device sync), both behind a six-method protocol
  verified by a shared contract test suite and concurrency race proofs.
- Structured error hierarchy: `handle_not_found` vs `handle_expired`
  distinguished, `patch_error` with path diagnostics, `backend_error`.
- FastMCP helpers: `store_from_env()` (`MCPSTATE_BACKEND`) and
  `current_user()` (OAuth subject → `MCPSTATE_USER` → `"local"`).
- Flagship MCP server (`mcpstate serve`): `state_save`, `state_load`,
  `state_list`, `state_patch`, `state_delete` tools built on the public
  library API; stdio and HTTP transports.
- Documentation: README with architecture and conflict-flow diagrams,
  concepts guide (hand-off sync, the conflict ladder, honest limits).
- Hardening: Redis keys percent-encoded against namespace collision from
  hostile user/handle strings; credentials redacted from every error message;
  early JSON-serializability validation; 1 MiB state size guard with
  structured `state_too_large` error; explicit SQLite busy timeout for
  multi-process use; writer attribution (`MCPSTATE_WRITER`/hostname) on all
  flagship writes; selective `state_load(path=...)` subtree reads;
  opportunistic expiry sweep during `state_list`; `py.typed` marker with a
  clean mypy pass; CI (ruff, mypy, pytest on 3.11/3.12) and PyPI Trusted
  Publishing workflows.
