import pytest

from mcpstate.backends.sqlite import SQLiteBackend
from mcpstate.errors import HandleExpired, HandleNotFound
from mcpstate.store import HandleStore


@pytest.fixture
def clockbox():
    class Box:  # controllable clock
        now = 1_000_000.0

        def __call__(self):
            return self.now

    return Box()


@pytest.fixture
def store(tmp_path, clockbox):
    s = HandleStore(SQLiteBackend(str(tmp_path / "s.db")), clock=clockbox)
    yield s
    s.close()


def test_mint_returns_kind_prefixed_opaque_handle(store):
    h = store.mint("research", {"sources": []}, user="u")
    assert h.startswith("research_") and len(h) == len("research_") + 8


def test_mint_then_get_round_trips_with_metadata(store, clockbox):
    h = store.mint("note", {"text": "hi"}, user="u", writer="laptop")
    snap = store.get(h, user="u")
    assert snap.state == {"text": "hi"}
    assert snap.version == 1
    assert snap.last_writer == "laptop"
    assert snap.created_at.timestamp() == clockbox.now


def test_get_unknown_handle_raises_not_found(store):
    with pytest.raises(HandleNotFound):
        store.get("note_zzzzzzzz", user="u")


def test_get_is_user_scoped(store):
    h = store.mint("note", {}, user="alice")
    with pytest.raises(HandleNotFound):
        store.get(h, user="bob")


def test_ttl_expiry_is_lazy_and_distinguished(store, clockbox):
    h = store.mint("note", {}, user="u", ttl_days=1)
    clockbox.now += 2 * 86400
    with pytest.raises(HandleExpired) as exc:
        store.get(h, user="u")
    assert exc.value.details["ttl_days"] == 1


def test_invalid_kind_rejected(store):
    with pytest.raises(ValueError):
        store.mint("Bad Kind!", {}, user="u")


def test_non_dict_state_rejected(store):
    with pytest.raises(ValueError):
        store.mint("note", ["not", "a", "dict"], user="u")
