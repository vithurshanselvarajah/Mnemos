from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def cli(backend_imports):
    from app import cli as cli_mod

    return cli_mod


def test_cli_master_view_prints_key(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "view_master_key", lambda: "viewed-key")
    rc = cli.cmd_master_view(mock.Mock())
    out = capsys.readouterr().out
    assert rc == 0
    assert "viewed-key" in out


def test_cli_master_rotate_prints_key(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "rotate_master_key", lambda: "rotated-key")
    rc = cli.cmd_master_rotate(mock.Mock())
    out = capsys.readouterr().out
    assert rc == 0
    assert "rotated-key" in out


def test_cli_healthz_uses_default_base(cli, monkeypatch):
    monkeypatch.setattr(cli.settings, "api_port", 9999)
    seen: dict = {}

    class _Resp:
        def __init__(self, body):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self._body

    def _open(url, timeout=None):
        seen["url"] = url
        return _Resp(b'{"status": "ok"}')

    monkeypatch.setattr(cli.urllib.request, "urlopen", _open)
    rc = cli.cmd_healthz(mock.Mock(base=None))
    assert rc == 0
    assert seen["url"] == "http://127.0.0.1:9999/healthz"


def test_cli_healthz_honors_base_override(cli, monkeypatch):
    seen: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"status":"ok"}'

    monkeypatch.setattr(
        cli.urllib.request, "urlopen", lambda url, timeout=None: seen.update(url=url) or _Resp()
    )
    rc = cli.cmd_healthz(mock.Mock(base="http://example.com:1234/"))
    assert rc == 0
    assert seen["url"] == "http://example.com:1234/healthz"


def test_cli_healthz_prints_raw_when_not_json(cli, monkeypatch, capsys):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"plain text"

    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *a, **kw: _Resp())
    rc = cli.cmd_healthz(mock.Mock(base="http://x/"))
    assert rc == 0
    assert "plain text" in capsys.readouterr().out


def test_cli_main_master_view(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "view_master_key", lambda: "k")
    rc = cli.main(["master-key", "view"])
    assert rc == 0
    assert "k" in capsys.readouterr().out


def test_cli_main_master_rotate(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "rotate_master_key", lambda: "k2")
    rc = cli.main(["master-key", "rotate"])
    assert rc == 0
    assert "k2" in capsys.readouterr().out


def test_cli_main_healthz(cli, monkeypatch, capsys):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"status":"ok"}'

    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *a, **kw: _Resp())
    rc = cli.main(["healthz"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok" in out


def test_cli_main_unknown_command_returns_1(cli):
    with pytest.raises(SystemExit):
        cli.main(["bogus"])


def test_cli_main_initializes_db(cli, monkeypatch):
    called = {"init": 0}
    monkeypatch.setattr(cli, "init_db", lambda: called.__setitem__("init", called["init"] + 1))
    monkeypatch.setattr(cli, "view_master_key", lambda: "k")
    cli.main(["master-key", "view"])
    assert called["init"] == 1
