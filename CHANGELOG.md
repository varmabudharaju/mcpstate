# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
