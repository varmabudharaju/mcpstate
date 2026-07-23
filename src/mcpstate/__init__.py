"""mcpstate — durable, user-keyed state for stateless MCP servers.

State that follows the user, not the session.
"""
from .aio import AsyncHandleStore
from .errors import (
    BackendError,
    HandleExpired,
    HandleNotFound,
    InternalError,
    McpStateError,
    PatchError,
    StaleWrite,
    StateTooLarge,
    Unauthenticated,
)
from .ops import Append, DelKey, Merge, PatchOp, SetKey, apply_ops, op_from_dict
from .store import KEEP_TTL, HandleInfo, HandleStore, Snapshot

__version__ = "0.2.0"

__all__ = [
    "HandleStore",
    "AsyncHandleStore",
    "Snapshot",
    "HandleInfo",
    "KEEP_TTL",
    "McpStateError",
    "HandleNotFound",
    "HandleExpired",
    "StaleWrite",
    "PatchError",
    "StateTooLarge",
    "Unauthenticated",
    "InternalError",
    "BackendError",
    "Append",
    "SetKey",
    "DelKey",
    "Merge",
    "PatchOp",
    "apply_ops",
    "op_from_dict",
    "__version__",
]
