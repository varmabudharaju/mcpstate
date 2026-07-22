# mcpstate — Design

**Date:** 2026-07-22
**Status:** Approved (brainstorm complete)
**Package:** `mcpstate` on PyPI · repo `mcpstate`

## One-liner

A durable state layer for stateless MCP: user-keyed, resumable, conflict-aware
state behind the spec's "mint a handle" pattern — shipped as a Python library
plus a flagship MCP server built on it.

*State that follows the user, not the session.*

## Why now

The MCP spec revision finalizing **2026-07-28** removes sessions entirely:
`Mcp-Session-Id`, the initialize handshake, and SSE resumability are all gone.
The protocol's official answer for state is "mint an explicit handle from a
tool and have the model pass it back as an argument" — and how servers persist
what handles point to is explicitly out of scope. No framework, SDK helper, or
product standardizes that store (closest prior art, `mcp-db`, has 8 stars;
Cloudflare's `McpAgent` resets state on reconnect; PyPI packages `syncmcp` and
`mcp-sync` are config-file sync tools, unrelated). Every stateful MCP server
now needs exactly what this library provides, the week it launches.

## Scope decisions (settled during brainstorm)

1. **Sync model: hand-off (relay baton), not concurrent.** State follows the
   user sequentially across conversations, clients, and devices. One active
   writer at a time is the design assumption; overlapping writers are detected,
   not merged.
2. **Conflict kit in v1 (the "core kit"):**
   - Versioned saves with agent-readable stale-write rejections.
   - Commutative patch ops that bypass version checks.
   - Freshness metadata on every read.
   - Deliberately excluded from v1: CRDTs/merge hooks, advisory leases,
     append-only changelog, push notifications (all roadmap).
3. **Form factor: embedded Python library as the core product, plus a thin
   flagship MCP server built on the public library API.** Sidecar service and
   non-Python support are roadmap.
4. **Conflict resolution philosophy:** the client is an LLM. A rejected stale
   write returns the current state and what changed; the agent re-reads and
   re-applies its intent as a *semantic* merge. v1 makes conflicts visible and
   legible rather than resolving them structurally.

## Components

### 1. Core library (`mcpstate`)

**`HandleStore`** — the single public entry point.

| Method | Behavior |
|---|---|
| `mint(kind, state, *, user, ttl_days=None, writer=None)` | Create a handle (`{kind}_{8-char base32}`), persist initial state at version 1, return the handle string. |
| `get(handle, *, user)` | Return a `Snapshot` (state, version, created_at, updated_at, expires_at, last_writer). Raises `HandleNotFound` or `HandleExpired`. |
| `save(handle, state, *, user, expect_version, writer=None)` | Full-state replace. If the stored version ≠ `expect_version`, raise `StaleWrite` carrying the current `Snapshot` and a human/agent-readable summary. On success, version increments. |
| `patch(handle, ops, *, user, writer=None)` | Apply commuting ops **without** a version check (they can't conflict). Version still increments. |
| `list(user, *, kind=None, include_expired=False)` | Enumerate the user's handles with metadata (not full state) — powers "you have a session from yesterday, resume?" |
| `revoke(handle, *, user)` | Delete the handle and its state. |

Construction: `HandleStore.from_url(url)` where `url` selects the backend
(`sqlite:///path` or `redis://host:port/db`). Default when no URL is given:
`sqlite:///~/.mcpstate/state.db`.

**Patch ops (v1 set):**
- `Append(path, value)` — append to a list at `path`.
- `SetKey(path, key, value)` — set a key in a dict at `path`.
- `DelKey(path, key)` — remove a key from a dict at `path`.
- `Merge(mapping)` — shallow-merge a dict into the state root.

`path` is a dotted path into the JSON state (e.g. `"sources"`,
`"profile.tags"`). A patch whose path does not exist or has the wrong container
type raises `PatchError` (structured, names the path and expected type).

**Backend protocol** — ~6 methods (`read`, `write`, `delete`, `list_keys`,
plus init/close), so community backends are easy. v1 ships:
- `SQLiteBackend` — zero-config default. Covers cross-conversation and
  cross-client continuity on one machine.
- `RedisBackend` — shared backend. Covers multi-instance servers and
  cross-device sync. Write path uses a Lua script (or WATCH/MULTI) so the
  version check-and-increment is atomic.

SQLite writes are wrapped in transactions with `BEGIN IMMEDIATE` so the
version check-and-increment is atomic there too.

**TTL & expiry:** per-handle `ttl_days` (None = no expiry). Expiry is lazy —
checked on access — plus a `store.sweep()` method callers may run
opportunistically. Expired handles are distinguishable from never-existed
until swept.

**Identity:** `user` is a plain string key. Scoping is enforced inside the
store — every operation requires the matching user; there is no cross-user
access path. Where the string comes from:
- Remote servers: the OAuth subject, via the FastMCP helper below.
- Local stdio servers: defaults to `"local"`.
- Anything else: the caller passes whatever stable identifier it has.

### 2. FastMCP integration (`mcpstate.fastmcp`)

A small helper module (no hard dependency on FastMCP for the core library):
- `store_from_env()` — build a `HandleStore` from `MCPSTATE_BACKEND` (falls
  back to the SQLite default).
- `current_user(ctx)` — resolve the user string from a FastMCP request
  context: OAuth subject if auth is configured, else `"local"`.

Server authors compose these in their own tools; we do not wrap or replace
FastMCP's middleware system.

### 3. Flagship server (`mcpstate.server`, CLI: `mcpstate serve`)

An MCP server exposing the store directly to any agent, built entirely on the
public library API (it is the living demo — if the API can't express the
server cleanly, the API is wrong).

Tools:
- `state_save(kind, state, handle=None, expect_version=None, ttl_days=None)` —
  mint when `handle` is None; otherwise a versioned save, and
  `expect_version` is required (the tool description tells the model to pass
  the version it last read). Tool result includes the handle and new version.
- `state_load(handle)` — snapshot with freshness metadata.
- `state_list(kind=None)` — the user's handles with age and last-writer.
- `state_patch(handle, ops)` — commutative mutations.
- `state_delete(handle)` — revoke.

Tool descriptions are written for models: they explain when to mint vs. save,
and that a stale-write error means "re-read, then re-apply your change."

Configuration via env: `MCPSTATE_BACKEND` (backend URL), `MCPSTATE_USER`
(identity override for stdio use). Transport: stdio by default; HTTP via
FastMCP's standard options.

## Data model

One logical table/keyspace, `handles`:

```
user TEXT · handle TEXT (PK with user) · kind TEXT · state JSON ·
version INTEGER · created_at · updated_at · expires_at NULLABLE ·
last_writer TEXT NULLABLE
```

Handles are opaque: `{kind}_` + 8 chars of `secrets`-sourced base32.
Unguessability is defense-in-depth; user scoping is the actual access control.

## Error handling

Every error is a structured, agent-legible payload — designed to be read by a
model and acted on:
- `StaleWrite` — includes the current snapshot, its writer and timestamp, and
  the instruction to re-read and re-apply.
- `HandleExpired` vs `HandleNotFound` — distinguished; expired includes when
  it expired and what the TTL was.
- `PatchError` — names the failing op, path, and expected container type.
- Backend unreachable — fails loud with the backend URL (credentials
  redacted). State is never silently dropped or half-written.

## Testing

- **Backend contract suite:** one parameterized pytest suite run against
  SQLiteBackend and RedisBackend (via fakeredis) — identical semantics
  required from both.
- **Race tests:** two concurrent writers against one handle; assert exactly
  one save wins and the loser receives `StaleWrite` with the winner's
  snapshot. Patch ops from concurrent writers must both land.
- **Integration test:** FastMCP in-memory client runs the full journey —
  mint in "session A", save, disconnect, resume in "session B" as the same
  user, `list`, `get`, continue. Repeat with two different user strings to
  prove isolation.
- **Flagship server end-to-end:** drive `mcpstate serve` through a real MCP
  client round-trip.
- **Visual evidence:** `capture` CLI screenshots of the demo flow for
  README/docs.

Target: same bar as tend/swarm — full suite green via `python3 -m pytest`
before any release.

## Packaging & launch

- Public GitHub repo `mcpstate`; PyPI package `mcpstate` (verified free
  2026-07-22). Python 3.11+. Core deps: stdlib + `redis` as an optional
  extra (`mcpstate[redis]`); FastMCP as an optional extra
  (`mcpstate[fastmcp]`) needed only for the helper module and flagship
  server.
- README leads with the stateless-spec story (July 28 revision) and the
  three-axis continuity pitch: across conversations, across clients, across
  devices.
- v1 roadmap section names what's deliberately out: CRDTs/merge hooks,
  advisory leases, changelog + `changes_since`, push/resource-subscription
  notifications, Postgres backend, sidecar service, TypeScript.

## Out of scope for v1 (roadmap)

| Item | Why deferred |
|---|---|
| CRDTs / merge hooks | Hand-off + agent-mediated merge covers v1; same handle API can host merging later. |
| Advisory activity leases | Nice-to-have visibility; small but not core. |
| Append-only changelog, `changes_since` | Substrate for v2 merging and richer resume UX. |
| Push notifications / MCP resource subscriptions | Needs verification against the final 2026-07-28 spec's server-initiated-message semantics. |
| Postgres backend | Backend protocol makes it a fast-follow. |
| Sidecar service / non-Python | Only once API is proven and demand shows up. |
