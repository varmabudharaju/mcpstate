import pytest

from mcpstate import HandleStore


def test_sqlite_url_round_trips(tmp_path):
    store = HandleStore.from_url(f"sqlite:///{tmp_path}/x.db")
    h = store.mint("note", {"a": 1}, user="u")
    assert store.get(h, user="u").state == {"a": 1}
    store.close()


def test_default_url_is_home_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    store = HandleStore.from_url(None)
    store.mint("note", {}, user="u")
    store.close()
    assert (tmp_path / ".mcpstate" / "state.db").exists()


def test_unknown_scheme_raises():
    with pytest.raises(ValueError, match="sqlite"):
        HandleStore.from_url("postgres://nope")


def test_public_exports():
    import mcpstate

    for name in [
        "HandleStore",
        "Snapshot",
        "HandleInfo",
        "McpStateError",
        "HandleNotFound",
        "HandleExpired",
        "StaleWrite",
        "PatchError",
        "BackendError",
        "Append",
        "SetKey",
        "DelKey",
        "Merge",
        "op_from_dict",
    ]:
        assert hasattr(mcpstate, name), name
