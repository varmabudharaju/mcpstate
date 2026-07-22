"""mcpstate — durable, user-keyed state for stateless MCP servers.

State that follows the user, not the session.
"""
from .errors import (
    BackendError,
    HandleExpired,
    HandleNotFound,
    McpStateError,
    PatchError,
    StaleWrite,
    StateTooLarge,
)
from .ops import Append, DelKey, Merge, PatchOp, SetKey, apply_ops, op_from_dict
from .store import HandleInfo, HandleStore, Snapshot

__version__ = "0.1.0"

__all__ = [
    "HandleStore",
    "Snapshot",
    "HandleInfo",
    "McpStateError",
    "HandleNotFound",
    "HandleExpired",
    "StaleWrite",
    "PatchError",
    "StateTooLarge",
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
