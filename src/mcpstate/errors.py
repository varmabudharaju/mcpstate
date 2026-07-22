"""Structured, agent-legible errors.

Every error renders to a JSON payload a model can read and act on: a stable
``code``, a message written as an instruction, and the details needed to
recover (for example, the current state inside a stale-write rejection).
"""
from __future__ import annotations

from typing import Any


class McpStateError(Exception):
    """Base class for all runtime state errors."""

    code = "mcpstate_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        """Render as a structured payload suitable for a tool result."""
        return {"code": self.code, "message": str(self), **self.details}


class HandleNotFound(McpStateError):
    """The handle does not exist for this user (never minted, or revoked)."""

    code = "handle_not_found"


class HandleExpired(McpStateError):
    """The handle existed but its TTL has elapsed."""

    code = "handle_expired"


class StaleWrite(McpStateError):
    """A versioned save lost a race; details carry the current snapshot."""

    code = "stale_write"


class PatchError(McpStateError):
    """A patch op could not be applied to the state's shape."""

    code = "patch_error"


class StateTooLarge(McpStateError):
    """The state exceeds the store's configured size limit."""

    code = "state_too_large"


class BackendError(McpStateError):
    """The storage backend failed or is misconfigured."""

    code = "backend_error"
