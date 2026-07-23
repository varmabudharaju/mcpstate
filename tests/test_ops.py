import pytest

from mcpstate.errors import PatchError
from mcpstate.ops import Append, DelKey, Merge, SetKey, apply_ops, op_from_dict


def test_append_to_list_at_path():
    state = {"sources": [1]}
    out = apply_ops(state, [Append("sources", 2)])
    assert out["sources"] == [1, 2]
    assert state["sources"] == [1]  # pure


def test_set_and_del_key_at_nested_path():
    state = {"profile": {"tags": {"a": 1}}}
    out = apply_ops(state, [SetKey("profile.tags", "b", 2), DelKey("profile.tags", "a")])
    assert out["profile"]["tags"] == {"b": 2}


def test_merge_shallow_merges_root():
    out = apply_ops({"a": 1, "b": 1}, [Merge({"b": 2, "c": 3})])
    assert out == {"a": 1, "b": 2, "c": 3}


def test_merge_at_nested_path():
    state = {"profile": {"tags": {"a": 1}, "name": "x"}, "sources": []}
    out = apply_ops(state, [Merge({"tags": {"b": 2}, "role": "dev"}, path="profile")])
    assert out["profile"] == {"tags": {"b": 2}, "name": "x", "role": "dev"}
    assert out["sources"] == []
    with pytest.raises(PatchError):  # merge target must be an object
        apply_ops(state, [Merge({"x": 1}, path="sources")])


def test_merge_wire_form_accepts_optional_path():
    assert op_from_dict({"op": "merge", "mapping": {"x": 1}, "path": "profile"}) == Merge(
        {"x": 1}, "profile"
    )
    assert op_from_dict({"op": "merge", "mapping": {"x": 1}}) == Merge({"x": 1})  # root default


def test_missing_path_raises_patch_error_with_details():
    with pytest.raises(PatchError) as exc:
        apply_ops({}, [Append("nope", 1)])
    assert exc.value.details["path"] == "nope"


def test_wrong_container_type_raises():
    with pytest.raises(PatchError):
        apply_ops({"sources": {}}, [Append("sources", 1)])
    with pytest.raises(PatchError):
        apply_ops({"n": 3}, [SetKey("n", "k", 1)])


def test_op_from_dict_round_trip():
    assert op_from_dict({"op": "append", "path": "s", "value": 1}) == Append("s", 1)
    assert op_from_dict({"op": "set_key", "path": "", "key": "k", "value": 2}) == SetKey("", "k", 2)
    assert op_from_dict({"op": "del_key", "path": "", "key": "k"}) == DelKey("", "k")
    assert op_from_dict({"op": "merge", "mapping": {"x": 1}}) == Merge({"x": 1})
    with pytest.raises(PatchError):
        op_from_dict({"op": "explode"})


def test_get_path_selects_subtree_and_root():
    from mcpstate.ops import get_path

    state = {"profile": {"tags": {"a": 1}}, "sources": [1, 2]}
    assert get_path(state, "profile.tags") == {"a": 1}
    assert get_path(state, "sources") == [1, 2]
    assert get_path(state, "") == state
    with pytest.raises(PatchError):
        get_path(state, "missing.path")
