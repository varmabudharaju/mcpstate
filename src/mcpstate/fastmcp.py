"""FastMCP integration helpers. Optional — the core library never imports FastMCP."""
from __future__ import annotations

import os

from .errors import Unauthenticated
from .store import HandleStore


def store_from_env() -> HandleStore:
    """Build a HandleStore from MCPSTATE_BACKEND (default: local SQLite)."""
    return HandleStore.from_url(os.environ.get("MCPSTATE_BACKEND"))


def current_writer() -> str:
    """A label for who is writing, shown as last_writer in freshness metadata.

    MCPSTATE_WRITER env (e.g. "laptop/claude-code") -> hostname fallback, so
    cross-device hand-offs are attributable out of the box.
    """
    writer = os.environ.get("MCPSTATE_WRITER")
    if writer:
        return writer
    import socket

    return socket.gethostname()


def _oauth_subject() -> str | None:
    """The authenticated caller's identity, issuer-scoped, or None."""
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
        if token is None:
            return None
        claims = getattr(token, "claims", None) or {}
        sub = claims.get("sub")
        if sub:
            issuer = claims.get("iss")
            # Scope by issuer: an OAuth `sub` is only unique within its issuer,
            # so two IdPs can mint the same sub for different humans.
            return f"{issuer}#{sub}" if issuer else str(sub)
        client_id = getattr(token, "client_id", None)
        if client_id:
            return f"client:{client_id}"
    except Exception:
        return None
    return None


def current_user(require_auth: bool = False) -> str:
    """Resolve the state-scoping user for the current request.

    Order: OAuth subject (issuer-scoped, when the server runs with FastMCP
    auth) -> MCPSTATE_USER env -> "local" (single-user stdio servers).

    When ``require_auth`` is set (the server does this on the HTTP transport),
    an unresolvable identity raises :class:`Unauthenticated` instead of falling
    back to the shared "local" bucket — a security boundary must fail closed.
    """
    subject = _oauth_subject()
    if subject:
        return subject
    if require_auth:
        raise Unauthenticated(
            "No authenticated caller could be resolved. This server requires auth "
            "on the HTTP transport so that state stays isolated per user."
        )
    return os.environ.get("MCPSTATE_USER", "local")
