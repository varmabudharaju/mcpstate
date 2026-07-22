"""Regression tests for the post-review hardening pass."""
import pytest

from mcpstate import Append, HandleStore, SetKey, StateTooLarge
from mcpstate.backends.sqlite import SQLiteBackend
from mcpstate.errors import PatchError
from mcpstate.ops import op_from_dict


@pytest.fixture
def clockbox():
    class Box:
        now = 1_000_000.0

        def __call__(self):
            return self.now

    return Box()


@pytest.fixture
def store(tmp_path, clockbox):
    s = HandleStore(SQLiteBackend(str(tmp_path / "h.db")), clock=clockbox)
    yield s
    s.close()


# --- ttl_days poison-handle DoS (CRITICAL) -----------------------------------
@pytest.mark.parametrize("bad", [1e15, 1e12, 1e9, float("inf"), float("nan"), 0, -1, "7", True])
def test_mint_rejects_dangerous_ttl(store, bad):
    with pytest.raises(ValueError):
        store.mint("note", {}, user="u", ttl_days=bad)


def test_normal_ttl_still_works(store):
    h = store.mint("note", {}, user="u", ttl_days=7)
    assert store.get(h, user="u").version == 1


def test_one_handle_cannot_break_list_for_the_user(store, clockbox):
    # Even if a huge ttl slipped in historically, list must never throw.
    store.mint("note", {}, user="u", ttl_days=30)
    store.mint("note", {"a": 1}, user="u")
    assert len(store.list("u")) == 2  # no exception


# --- non-finite state values (invalid JSON / immortal handles) ---------------
def test_non_finite_state_values_rejected(store):
    with pytest.raises(ValueError, match="JSON"):
        store.mint("note", {"x": float("inf")}, user="u")
    with pytest.raises(ValueError, match="JSON"):
        store.mint("note", {"x": float("nan")}, user="u")


# --- malformed patch ops must be PatchError, never a raw exception -----------
def test_op_from_dict_rejects_malformed_ops():
    for bad in [
        {"op": "merge", "mapping": "oops"},
        {"op": "merge", "mapping": [1, 2]},
        {"op": "set_key", "path": "", "key": [1, 2], "value": 1},
        {"op": "del_key", "path": "", "key": {"x": 1}},
        {"op": "append"},  # missing path/value
        "not-even-a-dict",
        123,
    ]:
        with pytest.raises(PatchError):
            op_from_dict(bad)


def test_deeply_nested_patch_is_clean_error_not_crash(store):
    h = store.mint("deep", {"a": {}}, user="u")
    ops = []
    path = "a"
    for _ in range(5000):
        ops.append(SetKey(path, "a", {}))
        path += ".a"
    with pytest.raises((PatchError, StateTooLarge, ValueError)):
        store.patch(h, ops, user="u")
    assert store.get(h, user="u").state == {"a": {}}  # original intact


# --- empty / no-op patch must not bump version or steal attribution ----------
def test_empty_patch_is_a_no_op(store):
    h = store.mint("research", {"sources": ["a"]}, user="u", writer="laptop")
    snap = store.patch(h, [], user="u", writer="phone")
    assert snap.version == 1  # unchanged
    assert snap.last_writer == "laptop"  # attribution not stolen


def test_noop_patch_does_not_induce_spurious_conflict(store):
    h = store.mint("research", {"sources": ["a"]}, user="u")
    # A reader holds version 1; a no-op patch must not advance the version.
    store.patch(h, [SetKey("", "sources", ["a"])], user="u")  # same value
    store.save(h, {"sources": ["a", "b"]}, user="u", expect_version=1)  # must still succeed


# --- patch under heavy contention must not raise spuriously -------------------
def test_patch_survives_heavy_contention(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    s = HandleStore(SQLiteBackend(str(tmp_path / "c.db")))
    h = s.mint("r", {"items": []}, user="u")

    def worker(w):
        for i in range(20):
            s.patch(h, [Append("items", f"{w}-{i}")], user="u")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))
    snap = s.get(h, user="u")
    assert len(snap.state["items"]) == 8 * 20  # every patch landed
    s.close()


# --- stale-write recovery when the handle vanishes mid-conflict --------------
def test_stale_save_on_deleted_handle_is_legible(store):
    from mcpstate.errors import McpStateError

    h = store.mint("note", {"n": 1}, user="u")
    store.save(h, {"n": 2}, user="u", expect_version=1)  # -> v2
    store.revoke(h, user="u")  # winner deletes it
    # A save with the now-stale version must raise a clean McpStateError,
    # not a raw exception, even though the recovery re-read finds nothing.
    with pytest.raises(McpStateError):
        store.save(h, {"n": 99}, user="u", expect_version=1)


# --- from_url edge cases -----------------------------------------------------
def test_from_url_empty_sqlite_path_is_guided_error():
    with pytest.raises(ValueError, match="path"):
        HandleStore.from_url("sqlite:///")


def test_from_url_memory_still_works():
    s = HandleStore.from_url("sqlite:///:memory:")
    h = s.mint("note", {"a": 1}, user="u")
    assert s.get(h, user="u").state == {"a": 1}
    s.close()


# --- Redis reserved-word namespace isolation ---------------------------------
def test_redis_user_named_index_is_isolated():
    import fakeredis

    from mcpstate.backends.redis import RedisBackend
    from mcpstate.backends.base import Record

    b = RedisBackend(fakeredis.FakeRedis())

    def rec(who):
        return Record("note", {"who": who}, 1, 100.0, 100.0, None, None)

    b.put_new("index", "note_aaaa2222", rec("hostile"))
    b.put_new("victim", "note_bbbb2222", rec("victim"))
    assert b.get("victim", "note_bbbb2222").state == {"who": "victim"}
    assert [h for h, _ in b.list("victim")] == ["note_bbbb2222"]
    assert [h for h, _ in b.list("index")] == ["note_aaaa2222"]
    b.close()
