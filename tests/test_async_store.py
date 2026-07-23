"""AsyncHandleStore delegates to HandleStore off the event loop."""
import pytest

from mcpstate import AsyncHandleStore, StaleWrite
from mcpstate.ops import Append


async def test_async_store_full_round_trip(tmp_path):
    store = AsyncHandleStore.from_url(f"sqlite:///{tmp_path}/a.db")
    h = await store.mint("research", {"sources": []}, user="u", writer="laptop")
    snap = await store.get(h, user="u")
    assert snap.state == {"sources": []} and snap.version == 1
    snap = await store.save(h, {"sources": ["a"]}, user="u", expect_version=1)
    assert snap.version == 2
    snap = await store.patch(h, [Append("sources", "b")], user="u", writer="phone")
    assert snap.state["sources"] == ["a", "b"] and snap.last_writer == "phone"
    snap = await store.touch(h, user="u", ttl_days=7)
    assert snap.expires_at is not None
    infos = await store.list("u")
    assert [i.handle for i in infos] == [h]
    with pytest.raises(StaleWrite):
        await store.save(h, {}, user="u", expect_version=1)
    await store.revoke(h, user="u")
    assert await store.list("u") == []
    assert await store.sweep("u") == 0
    await store.close()


async def test_async_store_wraps_an_existing_sync_store(tmp_path):
    from mcpstate import HandleStore

    sync = HandleStore.from_url(f"sqlite:///{tmp_path}/b.db")
    h = sync.mint("note", {"n": 1}, user="u")
    store = AsyncHandleStore(sync)
    assert (await store.get(h, user="u")).state == {"n": 1}
    await store.close()
