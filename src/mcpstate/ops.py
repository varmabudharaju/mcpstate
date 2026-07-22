"""Commutative patch operations.

Patches are applied without version checks: adding an item, setting a key, or
merging a mapping commutes with the same operations from another session, so
two devices patching concurrently both land. Only full-state saves need the
version protocol.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Sequence, Union

from .errors import PatchError


@dataclass(frozen=True)
class Append:
    """Append ``value`` to the list at ``path``."""

    path: str
    value: Any


@dataclass(frozen=True)
class SetKey:
    """Set ``key`` to ``value`` in the object at ``path``."""

    path: str
    key: str
    value: Any


@dataclass(frozen=True)
class DelKey:
    """Remove ``key`` from the object at ``path`` (no-op if absent)."""

    path: str
    key: str


@dataclass(frozen=True)
class Merge:
    """Shallow-merge ``mapping`` into the state root."""

    mapping: dict


PatchOp = Union[Append, SetKey, DelKey, Merge]


def _resolve(state: dict, path: str, op_name: str) -> Any:
    node: Any = state
    if path == "":
        return node
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise PatchError(
                f"Path '{path}' does not exist in the state; cannot apply {op_name}. "
                "Load the current state to see its shape.",
                op=op_name,
                path=path,
                reason="path_not_found",
            )
        node = node[part]
    return node


def _apply_one(state: dict, op: PatchOp) -> None:
    if isinstance(op, Append):
        target = _resolve(state, op.path, "append")
        if not isinstance(target, list):
            raise PatchError(
                f"Path '{op.path}' holds a {type(target).__name__}, but append needs a list.",
                op="append",
                path=op.path,
                reason="expected_list",
            )
        target.append(op.value)
    elif isinstance(op, SetKey):
        target = _resolve(state, op.path, "set_key")
        if not isinstance(target, dict):
            raise PatchError(
                f"Path '{op.path}' holds a {type(target).__name__}, but set_key needs an object.",
                op="set_key",
                path=op.path,
                reason="expected_object",
            )
        target[op.key] = op.value
    elif isinstance(op, DelKey):
        target = _resolve(state, op.path, "del_key")
        if not isinstance(target, dict):
            raise PatchError(
                f"Path '{op.path}' holds a {type(target).__name__}, but del_key needs an object.",
                op="del_key",
                path=op.path,
                reason="expected_object",
            )
        target.pop(op.key, None)
    elif isinstance(op, Merge):
        state.update(op.mapping)
    else:  # pragma: no cover - defensive
        raise PatchError(f"Unknown op {op!r}", op=str(op), reason="unknown_op")


def get_path(state: dict, path: str) -> Any:
    """Select the subtree at a dotted ``path`` (``""`` returns the whole state)."""
    return _resolve(state, path, "load")


def apply_ops(state: dict, ops: Sequence[PatchOp]) -> dict:
    """Return a new state with every op applied. The input is never mutated."""
    out = copy.deepcopy(state)
    for op in ops:
        _apply_one(out, op)
    return out


def op_from_dict(d: dict) -> PatchOp:
    """Parse the wire form used by the flagship server's state_patch tool."""
    kind = d.get("op")
    try:
        if kind == "append":
            return Append(d["path"], d["value"])
        if kind == "set_key":
            return SetKey(d["path"], d["key"], d["value"])
        if kind == "del_key":
            return DelKey(d["path"], d["key"])
        if kind == "merge":
            return Merge(d["mapping"])
    except KeyError as missing:
        raise PatchError(
            f"Op '{kind}' is missing required field {missing}.",
            op=str(kind),
            reason="missing_field",
        ) from None
    raise PatchError(
        f"Unknown op '{kind}'. Supported: append, set_key, del_key, merge.",
        op=str(kind),
        reason="unknown_op",
    )
