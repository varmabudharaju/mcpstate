"""The flagship mcpstate MCP server — durable agent memory built on the public library API.

Add it to any MCP client config and every agent gains state that survives
conversations, clients, and (with a shared Redis backend) devices. Tool
descriptions are written for the model: they teach the mint-vs-save
distinction and the stale-write recovery loop.
"""
from __future__ import annotations

from fastmcp import FastMCP

from .errors import McpStateError
from .fastmcp import current_user, current_writer, store_from_env
from .ops import op_from_dict
from .store import HandleStore

mcp = FastMCP("mcpstate")

_store: HandleStore | None = None


def _get_store() -> HandleStore:
    global _store
    if _store is None:
        _store = store_from_env()
    return _store


def _fail(err: McpStateError) -> dict:
    return {"ok": False, "error": err.to_payload()}


@mcp.tool
def state_save(
    kind: str,
    state: dict,
    handle: str | None = None,
    expect_version: int | None = None,
    ttl_days: float | None = None,
) -> dict:
    """Persist state durably. Omit `handle` to CREATE (mints and returns a new handle —
    remember it and pass it in later calls). Pass `handle` to UPDATE an existing state;
    then `expect_version` is REQUIRED — pass the version you last read. If you get a
    `stale_write` error, another session changed the state: read `error.current.state`,
    re-apply your change on top of it, and save again with the new version."""
    store = _get_store()
    user = current_user()
    try:
        if handle is None:
            new_handle = store.mint(kind, state, user=user, ttl_days=ttl_days,
                                    writer=current_writer())
            return {"ok": True, "handle": new_handle, "version": 1}
        if expect_version is None:
            return {
                "ok": False,
                "error": {
                    "code": "expect_version_required",
                    "message": "Updating an existing handle requires expect_version — "
                    "pass the version from your last state_load or state_save.",
                },
            }
        snap = store.save(handle, state, user=user, expect_version=expect_version,
                          writer=current_writer())
        return {"ok": True, "handle": handle, "version": snap.version}
    except McpStateError as err:
        return _fail(err)


@mcp.tool
def state_load(handle: str) -> dict:
    """Load durable state by handle. Returns the state plus freshness metadata
    (version, updated_at, last_writer) — keep the version for your next state_save."""
    try:
        snap = _get_store().get(handle, user=current_user())
        return {"ok": True, **snap.to_dict()}
    except McpStateError as err:
        return _fail(err)


@mcp.tool
def state_list(kind: str | None = None) -> dict:
    """List this user's durable state handles (most recently updated first) with
    metadata but not full state. Use at the start of a session to offer resuming
    earlier work, e.g. 'there is a research session from yesterday'."""
    try:
        infos = _get_store().list(current_user(), kind=kind)
        return {"ok": True, "handles": [i.to_dict() for i in infos]}
    except McpStateError as err:
        return _fail(err)


@mcp.tool
def state_patch(handle: str, ops: list[dict]) -> dict:
    """Apply additive mutations without version checks — they cannot conflict with
    other sessions. Each op is one of:
    {"op": "append", "path": "sources", "value": ...} — append to a list,
    {"op": "set_key", "path": "", "key": "k", "value": ...} — set a key in an object,
    {"op": "del_key", "path": "", "key": "k"} — remove a key,
    {"op": "merge", "mapping": {...}} — shallow-merge into the state root.
    `path` is dotted (e.g. "profile.tags"); "" means the state root.
    Prefer patch over save for adding items — it never gets a stale_write."""
    try:
        parsed = [op_from_dict(o) for o in ops]
        snap = _get_store().patch(handle, parsed, user=current_user(), writer=current_writer())
        return {"ok": True, **snap.to_dict()}
    except McpStateError as err:
        return _fail(err)


@mcp.tool
def state_delete(handle: str) -> dict:
    """Permanently delete durable state. Only do this when the user asks or the
    work it tracks is truly finished."""
    try:
        _get_store().revoke(handle, user=current_user())
        return {"ok": True, "handle": handle, "deleted": True}
    except McpStateError as err:
        return _fail(err)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from . import __version__

    parser = argparse.ArgumentParser(
        prog="mcpstate",
        description="Durable, user-keyed state for stateless MCP servers.",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the mcpstate MCP server")
    serve.add_argument("--backend", help="backend URL (sqlite:///path or redis://...)")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "serve":
        if args.backend:
            os.environ["MCPSTATE_BACKEND"] = args.backend
        global _store
        _store = None
        if args.transport == "http":
            mcp.run(transport="http", port=args.port)
        else:
            mcp.run()
        return 0
    parser.print_help()
    return 0
