from __future__ import annotations

import argparse
import json

import browser_bridge.cli as cli
import pytest


def _base_args() -> argparse.Namespace:
    return argparse.Namespace(
        server_ws_url="ws://127.0.0.1:8765/ws/operator",
        token="tok",
    )


def test_send_command_invalid_payload_json() -> None:
    args = _base_args()
    args.instance_id = "inst"
    args.client_id = "client"
    args.command_type = "observe"
    args.payload = "{bad-json"
    args.timeout_s = 2.0
    args.request_id = ""

    with pytest.raises(cli.CliError) as exc:
        cli.send_command(args)
    assert "Invalid JSON for --payload" in exc.value.message


def test_send_command_maps_failure(monkeypatch) -> None:
    args = _base_args()
    args.instance_id = "inst"
    args.client_id = "client"
    args.command_type = "observe"
    args.payload = "{}"
    args.timeout_s = 2.0
    args.request_id = "req1"

    async def fake_send_and_recv(_args, payload):  # noqa: ANN001
        assert payload["kind"] == "send_command"
        return {
            "kind": "command_result",
            "ok": False,
            "code": "CLIENT_NOT_CONNECTED",
            "error": "Target client not connected",
            "request_id": "req1",
        }

    monkeypatch.setattr(cli, "_send_and_recv", fake_send_and_recv)

    with pytest.raises(cli.CliError) as exc:
        cli.send_command(args)
    assert "CLIENT_NOT_CONNECTED" in exc.value.message


def test_ping_tab_maps_to_send_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_send_command(args):  # noqa: ANN001
        captured["command_type"] = args.command_type
        captured["payload"] = args.payload
        return 0

    monkeypatch.setattr(cli, "send_command", fake_send_command)

    args = _base_args()
    args.instance_id = "inst"
    args.client_id = "client"
    args.timeout_s = 8.0
    args.request_id = ""

    code = cli.ping_tab(args)
    assert code == 0
    assert captured["command_type"] == "ping_tab"
    assert captured["payload"] == "{}"


def test_observe_maps_to_send_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_send_command(args):  # noqa: ANN001
        captured["command_type"] = args.command_type
        captured["payload"] = args.payload
        return 0

    monkeypatch.setattr(cli, "send_command", fake_send_command)

    args = _base_args()
    args.instance_id = "inst"
    args.client_id = "client"
    args.max_nodes = 9
    args.timeout_s = 20.0
    args.request_id = ""

    code = cli.observe(args)
    assert code == 0
    assert captured["command_type"] == "observe"
    assert json.loads(str(captured["payload"])) == {"max_nodes": 9}


def test_setup_secret_writes_file(monkeypatch, tmp_path, capsys) -> None:
    secret_path = tmp_path / "jwt_secret"
    monkeypatch.setenv("BRIDGE_JWT_SECRET_FILE", str(secret_path))
    args = argparse.Namespace(secret="", force=False, show_secret=False)

    code = cli.setup_secret(args)
    out = capsys.readouterr().out

    assert code == 0
    body = json.loads(out)
    assert body["ok"] is True
    assert body["secret_file"] == str(secret_path)
    assert "secret_preview" in body


def test_setup_secret_requires_force_to_overwrite(monkeypatch, tmp_path) -> None:
    secret_path = tmp_path / "jwt_secret"
    monkeypatch.setenv("BRIDGE_JWT_SECRET_FILE", str(secret_path))
    secret_path.write_text("already-there\n", encoding="utf-8")

    args = argparse.Namespace(secret="", force=False, show_secret=False)
    with pytest.raises(cli.CliError) as exc:
        cli.setup_secret(args)
    assert "already exists" in exc.value.message
