from __future__ import annotations

import argparse
import json

import browser_bridge.cli as cli
import pytest


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


def test_send_command_generates_request_id(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse({"command_id": "c1", "ok": True, "result": {"done": True}, "error": None})

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    args = argparse.Namespace(
        server="http://127.0.0.1:8765",
        session_id="sid",
        agent_token="agt",
        name="",
        command_type="observe",
        payload="{}",
        timeout_s=2.0,
        request_id="",
    )

    code = cli.send_command(args)
    out = capsys.readouterr().out

    assert code == 0
    assert captured["url"].endswith("/api/sessions/sid/command")
    assert captured["headers"]["Authorization"] == "Bearer agt"
    assert captured["headers"]["X-Request-ID"]
    assert '"request_id":' in out


def test_send_command_uses_provided_request_id(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
        captured["headers"] = headers
        return _FakeResponse({"command_id": "c2", "ok": True, "result": {}, "error": None})

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    args = argparse.Namespace(
        server="http://127.0.0.1:8765",
        session_id="sid",
        agent_token="agt",
        name="",
        command_type="click",
        payload='{"selector":"button"}',
        timeout_s=3.0,
        request_id="fixed-id-1",
    )

    code = cli.send_command(args)
    _ = capsys.readouterr().out

    assert code == 0
    assert captured["headers"]["X-Request-ID"] == "fixed-id-1"


def test_create_session_saves_named_profile(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("BROWSER_BRIDGE_CONFIG", str(tmp_path / "sessions.json"))

    def fake_post(url, params=None, timeout=None):  # noqa: ANN001
        return _FakeResponse(
            {
                "session_id": "sid-1",
                "agent_token": "agt-1",
                "extension_token": "ext-1",
                "agent_token_expires_at": "2026-03-04T00:00:00+00:00",
                "extension_token_expires_at": "2026-03-05T00:00:00+00:00",
                "ws_url": "ws://127.0.0.1:8765/ws/extension/sid-1?token=ext-1",
            }
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    args = argparse.Namespace(
        server="http://127.0.0.1:8765",
        ws_base="ws://127.0.0.1:8765",
        name="local",
        make_default=True,
    )
    code = cli.create_session(args)
    out = capsys.readouterr().out

    assert code == 0
    assert '"saved_as": "local"' in out

    config = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    assert config["default_session_name"] == "local"
    assert config["sessions"]["local"]["session_id"] == "sid-1"
    assert config["sessions"]["local"]["agent_token"] == "agt-1"


def test_send_command_uses_named_profile(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("BROWSER_BRIDGE_CONFIG", str(tmp_path / "sessions.json"))
    (tmp_path / "sessions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "default_session_name": None,
                "sessions": {
                    "local": {
                        "server": "http://127.0.0.1:8765",
                        "session_id": "sid-from-config",
                        "agent_token": "agt-from-config",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse({"command_id": "c3", "ok": True, "result": {}, "error": None})

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    args = argparse.Namespace(
        server="http://127.0.0.1:8765",
        session_id="",
        agent_token="",
        name="local",
        command_type="observe",
        payload="{}",
        timeout_s=2.0,
        request_id="",
    )

    code = cli.send_command(args)
    _ = capsys.readouterr().out

    assert code == 0
    assert captured["url"].endswith("/api/sessions/sid-from-config/command")
    assert captured["headers"]["Authorization"] == "Bearer agt-from-config"


def test_status_uses_default_named_profile(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("BROWSER_BRIDGE_CONFIG", str(tmp_path / "sessions.json"))
    (tmp_path / "sessions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "default_session_name": "default",
                "sessions": {
                    "default": {
                        "server": "http://127.0.0.1:8765",
                        "session_id": "sid-default",
                        "agent_token": "agt-default",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def fake_get(url, headers=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse({"session_id": "sid-default", "connected": False})

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    args = argparse.Namespace(
        server="http://127.0.0.1:8765",
        session_id="",
        agent_token="",
        name="",
    )
    code = cli.session_status(args)
    _ = capsys.readouterr().out

    assert code == 0
    assert captured["url"].endswith("/api/sessions/sid-default")
    assert captured["headers"]["Authorization"] == "Bearer agt-default"


def test_send_command_rejects_invalid_payload_json() -> None:
    args = argparse.Namespace(
        server="http://127.0.0.1:8765",
        session_id="sid",
        agent_token="agt",
        name="",
        command_type="navigate",
        payload="{bad-json",
        timeout_s=2.0,
        request_id="",
    )
    with pytest.raises(cli.CliError) as exc:
        cli.send_command(args)
    assert "Invalid JSON for --payload" in exc.value.message
    assert exc.value.hint is not None


def test_resolve_credentials_missing_raises_actionable_error() -> None:
    args = argparse.Namespace(session_id="", agent_token="", name="")
    with pytest.raises(cli.CliError) as exc:
        cli._resolve_credentials(args)
    assert exc.value.message == "Missing credentials"
    assert "create-session --name" in (exc.value.hint or "")
