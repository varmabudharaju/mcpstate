from mcpstate.fastmcp import current_user, store_from_env


def test_store_from_env_uses_env_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("MCPSTATE_BACKEND", f"sqlite:///{tmp_path}/env.db")
    store = store_from_env()
    store.mint("note", {}, user="u")
    store.close()
    assert (tmp_path / "env.db").exists()


def test_store_from_env_reads_max_state_bytes(monkeypatch, tmp_path):
    from mcpstate.errors import StateTooLarge

    monkeypatch.setenv("MCPSTATE_BACKEND", f"sqlite:///{tmp_path}/cap.db")
    monkeypatch.setenv("MCPSTATE_MAX_STATE_BYTES", "100")
    store = store_from_env()
    with pytest.raises(StateTooLarge):
        store.mint("note", {"blob": "x" * 200}, user="u")
    store.close()


def test_store_from_env_rejects_garbage_max_state_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("MCPSTATE_BACKEND", f"sqlite:///{tmp_path}/cap.db")
    monkeypatch.setenv("MCPSTATE_MAX_STATE_BYTES", "a lot")
    with pytest.raises(ValueError, match="MCPSTATE_MAX_STATE_BYTES"):
        store_from_env()


def test_current_user_prefers_env_override(monkeypatch):
    monkeypatch.setenv("MCPSTATE_USER", "varma")
    assert current_user() == "varma"


def test_current_user_defaults_to_local(monkeypatch):
    monkeypatch.delenv("MCPSTATE_USER", raising=False)
    assert current_user() == "local"


def test_current_writer_prefers_env(monkeypatch):
    from mcpstate.fastmcp import current_writer

    monkeypatch.setenv("MCPSTATE_WRITER", "laptop/claude-code")
    assert current_writer() == "laptop/claude-code"


def test_current_writer_defaults_to_hostname(monkeypatch):
    import socket

    from mcpstate.fastmcp import current_writer

    monkeypatch.delenv("MCPSTATE_WRITER", raising=False)
    assert current_writer() == socket.gethostname()


def test_current_user_require_auth_raises_when_unresolved(monkeypatch):
    from mcpstate.errors import Unauthenticated

    monkeypatch.delenv("MCPSTATE_USER", raising=False)
    with pytest.raises(Unauthenticated):
        current_user(require_auth=True)


import pytest  # noqa: E402
