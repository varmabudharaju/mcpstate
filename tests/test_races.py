"""Concurrency proofs: exactly one stale writer wins; concurrent patches all land."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from mcpstate import Append, HandleStore, StaleWrite
from mcpstate.backends.sqlite import SQLiteBackend


@pytest.fixture(params=["sqlite", "redis"])
def store(request, tmp_path):
    if request.param == "sqlite":
        backend = SQLiteBackend(str(tmp_path / "s.db"))
    else:
        import fakeredis

        from mcpstate.backends.redis import RedisBackend

        backend = RedisBackend(fakeredis.FakeRedis())
    s = HandleStore(backend)
    yield s
    s.close()


def test_exactly_one_concurrent_save_wins(store):
    h = store.mint("note", {"n": 0}, user="u")

    def try_save(i):
        try:
            store.save(h, {"n": i}, user="u", expect_version=1, writer=f"w{i}")
            return "won"
        except StaleWrite:
            return "stale"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(try_save, range(8)))
    assert results.count("won") == 1
    assert results.count("stale") == 7
    assert store.get(h, user="u").version == 2


def test_concurrent_patches_all_land(store):
    h = store.mint("research", {"sources": []}, user="u")

    def patch_many(worker):
        for i in range(25):
            store.patch(h, [Append("sources", f"{worker}-{i}")], user="u")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(patch_many, ["a", "b"]))
    snap = store.get(h, user="u")
    assert len(snap.state["sources"]) == 50
    assert snap.version == 51
