from mcpstate.fastmcp import current_user, store_from_env


def test_store_from_env_uses_env_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("MCPSTATE_BACKEND", f"sqlite:///{tmp_path}/env.db")
    store = store_from_env()
    store.mint("note", {}, user="u")
    store.close()
    assert (tmp_path / "env.db").exists()


def test_current_user_prefers_env_override(monkeypatch):
    monkeypatch.setenv("MCPSTATE_USER", "varma")
    assert current_user() == "varma"


def test_current_user_defaults_to_local(monkeypatch):
    monkeypatch.delenv("MCPSTATE_USER", raising=False)
    assert current_user() == "local"
