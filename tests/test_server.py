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
