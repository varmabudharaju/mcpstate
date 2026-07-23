"""Backend contract suite — every backend must pass identical semantics."""
import pytest

from mcpstate.backends.base import Record
from mcpstate.backends.sqlite import SQLiteBackend


def make_record(version=1, state=None, updated_at=100.0):
    return Record(
        kind="note",
        state=state or {"v": version},
        version=version,
        created_at=100.0,
        updated_at=updated_at,
        expires_at=None,
        last_writer="t",
    )


@pytest.fixture(params=["sqlite", "redis"])
def backend(request, tmp_path):
    if request.param == "sqlite":
        b = SQLiteBackend(str(tmp_path / "s.db"))
    else:
        import fakeredis

        from mcpstate.backends.redis import RedisBackend

        b = RedisBackend(fakeredis.FakeRedis())
    yield b
    b.close()


def test_get_missing_returns_none(backend):
    assert backend.get("u", "h") is None


def test_put_new_then_get_round_trips(backend):
    rec = make_record()
    assert backend.put_new("u", "note_aaaa2222", rec) is True
    got = backend.get("u", "note_aaaa2222")
    assert got == rec


def test_put_new_refuses_duplicates(backend):
    backend.put_new("u", "h", make_record())
    assert backend.put_new("u", "h", make_record(version=9)) is False


def test_user_scoping_is_total(backend):
    backend.put_new("alice", "h", make_record())
    assert backend.get("bob", "h") is None
    assert backend.delete("bob", "h") is False
    assert backend.list("bob") == []


def test_cas_put_succeeds_only_on_matching_version(backend):
    backend.put_new("u", "h", make_record(version=1))
    assert backend.cas_put("u", "h", 1, make_record(version=2)) is True
    assert backend.cas_put("u", "h", 1, make_record(version=3)) is False
    assert backend.get("u", "h").version == 2


def test_cas_put_on_missing_handle_is_false(backend):
    assert backend.cas_put("u", "h", 1, make_record(version=2)) is False


def test_delete_removes(backend):
    backend.put_new("u", "h", make_record())
    assert backend.delete("u", "h") is True
    assert backend.get("u", "h") is None


def test_list_orders_by_updated_at_desc(backend):
    backend.put_new("u", "old", make_record(updated_at=50.0))
    backend.put_new("u", "new", make_record(updated_at=150.0))
    assert [h for h, _ in backend.list("u")] == ["new", "old"]


def test_sqlite_serves_many_threads_concurrently(tmp_path):
    import threading

    b = SQLiteBackend(str(tmp_path / "mt.db"))
    b.put_new("u", "h", make_record(version=1))
    errors = []

    def reader():
        try:
            for _ in range(50):
                assert b.get("u", "h") is not None
                assert [h for h, _ in b.list("u")] == ["h"]
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    b.close()


def test_sqlite_memory_db_is_shared_across_threads():
    import threading

    b = SQLiteBackend(":memory:")
    b.put_new("u", "h", make_record())
    seen = []
    t = threading.Thread(target=lambda: seen.append(b.get("u", "h")))
    t.start()
    t.join()
    assert seen == [make_record()]
    b.close()


def test_sqlite_memory_backends_are_isolated_from_each_other():
    a = SQLiteBackend(":memory:")
    b = SQLiteBackend(":memory:")
    a.put_new("u", "h", make_record())
    assert b.get("u", "h") is None
    a.close()
    b.close()


def test_sqlite_sets_busy_timeout(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"))
    timeout = b._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    b.close()
    assert timeout >= 5000


def test_redis_list_prunes_dangling_index_members():
    import fakeredis

    from mcpstate.backends.redis import RedisBackend

    b = RedisBackend(fakeredis.FakeRedis())
    b.put_new("u", "note_aaaa2222", make_record())
    # A crash between SET and SADD (or an external flush) can leave an index
    # member with no record. list() must skip it AND prune it from the index.
    b._r.sadd("mcpstate:i:u", "note_gone9999")
    assert [h for h, _ in b.list("u")] == ["note_aaaa2222"]
    assert b._r.smembers("mcpstate:i:u") == {b"note_aaaa2222"}
    b.close()


def test_redis_cas_put_treats_watch_error_subclasses_as_lost_race():
    from redis.exceptions import WatchError

    from mcpstate.backends.redis import RedisBackend

    class CustomWatchError(WatchError):
        """A client library may raise its own subclass; still just a lost race."""

    class StubPipeline:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def watch(self, key):
            raise CustomWatchError()

    class StubClient:
        def pipeline(self):
            return StubPipeline()

    b = RedisBackend(StubClient())
    assert b.cas_put("u", "h", 1, make_record(version=2)) is False


def test_redis_keys_survive_hostile_user_and_handle_strings():
    import fakeredis

    from mcpstate.backends.redis import RedisBackend

    b = RedisBackend(fakeredis.FakeRedis())
    # A user id containing colons must not collide with another user's index set
    # or another (user, handle) split point.
    b.put_new("index:foo", "note_aaaa2222", make_record(state={"who": "hostile"}))
    b.put_new("foo", "note_bbbb2222", make_record(state={"who": "victim"}))
    assert b.get("foo", "note_bbbb2222").state == {"who": "victim"}
    assert b.get("index:foo", "note_aaaa2222").state == {"who": "hostile"}
    assert [h for h, _ in b.list("foo")] == ["note_bbbb2222"]
    assert [h for h, _ in b.list("index:foo")] == ["note_aaaa2222"]
    # And the raw colon-joined form must NOT be addressable as anyone else's data.
    assert b.get("index", "foo:note_aaaa2222") is None
    b.close()
