import os

import mcpstate
import mcpstate.server as server


def test_version_flag(capsys):
    assert server.main(["--version"]) == 0
    assert mcpstate.__version__ in capsys.readouterr().out


def test_serve_wires_backend_env_and_runs(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(server.mcp, "run", lambda **kw: calls.update(kw))
    url = f"sqlite:///{tmp_path}/cli.db"
    monkeypatch.setenv("MCPSTATE_BACKEND", "sentinel")  # ensure restoration after test
    assert server.main(["serve", "--backend", url]) == 0
    assert os.environ["MCPSTATE_BACKEND"] == url
    assert calls == {}  # stdio default: run() with no kwargs


def test_serve_http_passes_transport(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.mcp, "run", lambda **kw: calls.update(kw))
    assert server.main(["serve", "--transport", "http", "--port", "9000"]) == 0
    assert calls == {"transport": "http", "port": 9000}


def test_serve_http_requires_auth_by_default(monkeypatch):
    monkeypatch.setattr(server.mcp, "run", lambda **kw: None)
    server._require_auth = False
    server.main(["serve", "--transport", "http"])
    assert server._require_auth is True  # fail-closed by default on HTTP


def test_serve_http_allow_anonymous_opt_out(monkeypatch):
    monkeypatch.setattr(server.mcp, "run", lambda **kw: None)
    server._require_auth = True
    server.main(["serve", "--transport", "http", "--allow-anonymous"])
    assert server._require_auth is False
