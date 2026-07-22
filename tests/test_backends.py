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
