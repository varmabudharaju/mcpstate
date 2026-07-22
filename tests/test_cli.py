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
    assert server.main(["serve", "--backend", url]) == 0
    assert os.environ["MCPSTATE_BACKEND"] == url
    assert calls == {}  # stdio default: run() with no kwargs


def test_serve_http_passes_transport(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.mcp, "run", lambda **kw: calls.update(kw))
    assert server.main(["serve", "--transport", "http", "--port", "9000"]) == 0
    assert calls == {"transport": "http", "port": 9000}
