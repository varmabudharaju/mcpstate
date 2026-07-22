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


# --- versioned save -----------------------------------------------------------
from mcpstate.errors import StaleWrite  # noqa: E402


def test_save_with_matching_version_increments(store):
    h = store.mint("note", {"n": 1}, user="u")
    snap = store.save(h, {"n": 2}, user="u", expect_version=1, writer="phone")
    assert snap.version == 2 and snap.state == {"n": 2} and snap.last_writer == "phone"
    assert store.get(h, user="u").state == {"n": 2}


def test_stale_save_rejected_with_current_state_in_payload(store):
    h = store.mint("note", {"n": 1}, user="u")
    store.save(h, {"n": 2}, user="u", expect_version=1, writer="laptop")
    with pytest.raises(StaleWrite) as exc:
        store.save(h, {"n": 99}, user="u", expect_version=1, writer="phone")
    payload = exc.value.to_payload()
    assert payload["current"]["version"] == 2
    assert payload["current"]["state"] == {"n": 2}
    assert payload["current"]["last_writer"] == "laptop"
    assert payload["expected_version"] == 1
    assert "re-read" in payload["message"].lower() or "re-apply" in payload["message"].lower()
    assert store.get(h, user="u").state == {"n": 2}  # loser did not clobber


def test_save_preserves_created_at_and_ttl(store, clockbox):
    h = store.mint("note", {}, user="u", ttl_days=7)
    created = store.get(h, user="u").created_at
    clockbox.now += 100
    snap = store.save(h, {"x": 1}, user="u", expect_version=1)
    assert snap.created_at == created
    assert snap.expires_at is not None


def test_save_on_missing_and_expired(store, clockbox):
    with pytest.raises(HandleNotFound):
        store.save("note_zzzzzzzz", {}, user="u", expect_version=1)
    h = store.mint("note", {}, user="u", ttl_days=1)
    clockbox.now += 2 * 86400
    with pytest.raises(HandleExpired):
        store.save(h, {}, user="u", expect_version=1)


# --- patch / list / revoke / sweep --------------------------------------------
from mcpstate.ops import Append  # noqa: E402


def test_patch_applies_without_version(store):
    h = store.mint("research", {"sources": []}, user="u")
    store.save(h, {"sources": ["a"]}, user="u", expect_version=1)
    snap = store.patch(h, [Append("sources", "b")], user="u", writer="phone")
    assert snap.state["sources"] == ["a", "b"] and snap.version == 3


def test_list_returns_metadata_without_state(store, clockbox):
    h1 = store.mint("research", {"big": "blob"}, user="u")
    clockbox.now += 10
    h2 = store.mint("note", {}, user="u")
    infos = store.list("u")
    assert [i.handle for i in infos] == [h2, h1]
    assert not hasattr(infos[0], "state")
    assert store.list("u", kind="note")[0].handle == h2


def test_list_hides_expired_unless_asked(store, clockbox):
    h = store.mint("note", {}, user="u", ttl_days=1)
    store.mint("note", {}, user="u")
    clockbox.now += 2 * 86400
    assert len(store.list("u")) == 1
    assert len(store.list("u", include_expired=True)) == 2
    assert h in {i.handle for i in store.list("u", include_expired=True)}


def test_revoke_deletes_and_errors_on_missing(store):
    h = store.mint("note", {}, user="u")
    store.revoke(h, user="u")
    with pytest.raises(HandleNotFound):
        store.get(h, user="u")
    with pytest.raises(HandleNotFound):
        store.revoke(h, user="u")


def test_sweep_removes_only_expired(store, clockbox):
    store.mint("note", {}, user="u", ttl_days=1)
    keep = store.mint("note", {}, user="u")
    clockbox.now += 2 * 86400
    assert store.sweep("u") == 1
    assert [i.handle for i in store.list("u", include_expired=True)] == [keep]
