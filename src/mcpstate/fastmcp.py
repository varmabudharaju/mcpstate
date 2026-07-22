"""FastMCP integration helpers. Optional — the core library never imports FastMCP."""
from __future__ import annotations

import os

from .store import HandleStore


def store_from_env() -> HandleStore:
    """Build a HandleStore from MCPSTATE_BACKEND (default: local SQLite)."""
    return HandleStore.from_url(os.environ.get("MCPSTATE_BACKEND"))


def current_user() -> str:
    """Resolve the state-scoping user for the current request.

    Order: OAuth subject (when the server runs with FastMCP auth) ->
    MCPSTATE_USER env -> "local" (single-user stdio servers). Never raises.
    """
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
        if token is not None:
            claims = getattr(token, "claims", None) or {}
            subject = claims.get("sub") or getattr(token, "client_id", None)
            if subject:
                return str(subject)
    except Exception:
        pass
    return os.environ.get("MCPSTATE_USER", "local")
