import pytest
from fastmcp import Client

import mcpstate.server as server


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch, tmp_path):
    monkeypatch.setenv("MCPSTATE_BACKEND", f"sqlite:///{tmp_path}/srv.db")
    monkeypatch.setenv("MCPSTATE_USER", "tester")
    server._store = None
    yield
    server._store = None


async def call(name, **args):
    async with Client(server.mcp) as client:
        result = await client.call_tool(name, args)
        return result.data


async def test_save_mints_then_versions():
    minted = await call("state_save", kind="research", state={"sources": []})
    assert minted["ok"] and minted["version"] == 1
    handle = minted["handle"]
    saved = await call(
        "state_save", kind="research", state={"sources": ["a"]}, handle=handle, expect_version=1
    )
    assert saved["ok"] and saved["version"] == 2


async def test_save_existing_requires_expect_version():
    minted = await call("state_save", kind="note", state={})
    res = await call("state_save", kind="note", state={}, handle=minted["handle"])
    assert res["ok"] is False
    assert "expect_version" in res["error"]["message"]


async def test_stale_write_surfaces_current_state():
    minted = await call("state_save", kind="note", state={"n": 1})
    h = minted["handle"]
    await call("state_save", kind="note", state={"n": 2}, handle=h, expect_version=1)
    res = await call("state_save", kind="note", state={"n": 99}, handle=h, expect_version=1)
    assert res["ok"] is False
    assert res["error"]["code"] == "stale_write"
    assert res["error"]["current"]["state"] == {"n": 2}


async def test_load_list_patch_delete_round_trip():
    minted = await call("state_save", kind="research", state={"sources": []})
    h = minted["handle"]
    patched = await call(
        "state_patch", handle=h, ops=[{"op": "append", "path": "sources", "value": "arxiv"}]
    )
    assert patched["ok"] and patched["state"]["sources"] == ["arxiv"]
    loaded = await call("state_load", handle=h)
    assert loaded["ok"] and loaded["state"]["sources"] == ["arxiv"]
    listing = await call("state_list")
    assert listing["ok"] and listing["handles"][0]["handle"] == h
    deleted = await call("state_delete", handle=h)
    assert deleted["ok"]
    missing = await call("state_load", handle=h)
    assert missing["ok"] is False and missing["error"]["code"] == "handle_not_found"


async def test_flagship_writes_carry_writer_label(monkeypatch):
    monkeypatch.setenv("MCPSTATE_WRITER", "test-device/claude")
    minted = await call("state_save", kind="note", state={"n": 1})
    loaded = await call("state_load", handle=minted["handle"])
    assert loaded["last_writer"] == "test-device/claude"
    await call("state_save", kind="note", state={"n": 2},
               handle=minted["handle"], expect_version=1)
    patched = await call("state_patch", handle=minted["handle"],
                         ops=[{"op": "merge", "mapping": {"m": True}}])
    assert patched["last_writer"] == "test-device/claude"


async def test_state_load_selective_path():
    minted = await call("state_save", kind="research",
                        state={"sources": ["a", "b"], "notes": {"draft": "long text"}})
    partial = await call("state_load", handle=minted["handle"], path="sources")
    assert partial["ok"] and partial["state"] == ["a", "b"]
    assert partial["path"] == "sources"
    bad = await call("state_load", handle=minted["handle"], path="nope.deep")
    assert bad["ok"] is False and bad["error"]["code"] == "patch_error"


async def test_state_list_sweeps_expired_records(tmp_path):
    from mcpstate import HandleStore
    from mcpstate.backends.sqlite import SQLiteBackend

    class Box:
        now = 1_000_000.0

        def __call__(self):
            return self.now

    clock = Box()
    backend = SQLiteBackend(str(tmp_path / "sweep.db"))
    server._store = HandleStore(backend, clock=clock)
    server._store.mint("note", {}, user="tester", ttl_days=1)
    keep = server._store.mint("note", {}, user="tester")
    clock.now += 2 * 86400
    listing = await call("state_list")
    assert [h["handle"] for h in listing["handles"]] == [keep]
    assert [h for h, _ in backend.list("tester")] == [keep]  # physically swept


async def test_state_touch_extends_then_clears_expiry():
    minted = await call("state_save", kind="research", state={}, ttl_days=1)
    h = minted["handle"]
    touched = await call("state_touch", handle=h, ttl_days=30)
    assert touched["ok"] and touched["expires_at"] is not None
    cleared = await call("state_touch", handle=h)  # omitted ttl -> persistent
    assert cleared["ok"] and cleared["expires_at"] is None
    missing = await call("state_touch", handle="research_zzzzzzzz", ttl_days=1)
    assert missing["ok"] is False and missing["error"]["code"] == "handle_not_found"


async def test_state_save_update_renews_ttl_only_when_given():
    minted = await call("state_save", kind="note", state={"n": 1}, ttl_days=1)
    h = minted["handle"]
    kept = await call("state_save", kind="note", state={"n": 2}, handle=h, expect_version=1)
    loaded = await call("state_load", handle=h)
    assert kept["ok"] and loaded["expires_at"] is not None  # omitted -> unchanged
    renewed = await call(
        "state_save", kind="note", state={"n": 3}, handle=h, expect_version=2, ttl_days=90
    )
    assert renewed["ok"]
    reloaded = await call("state_load", handle=h)
    assert reloaded["expires_at"] > loaded["expires_at"]


async def test_malformed_ops_return_structured_error_not_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("MCPSTATE_BACKEND", f"sqlite:///{tmp_path}/m.db")
    server._store = None
    minted = await call("state_save", kind="note", state={})
    res = await call("state_patch", handle=minted["handle"],
                     ops=[{"op": "merge", "mapping": "not-a-dict"}])
    assert res["ok"] is False and res["error"]["code"] == "patch_error"


async def test_backend_failure_returns_internal_error_not_crash(monkeypatch):
    class BoomStore:
        def get(self, *a, **k):
            raise RuntimeError("redis exploded with secret://user:pass@host")

    monkeypatch.setattr(server, "_store", None)
    monkeypatch.setattr(server, "_get_store", lambda: BoomStore())
    res = await call("state_load", handle="note_x")
    assert res["ok"] is False and res["error"]["code"] == "internal_error"
    assert "pass@host" not in res["error"]["message"]  # no detail leak
