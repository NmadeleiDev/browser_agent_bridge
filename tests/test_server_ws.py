from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import browser_bridge.server as server
from browser_bridge.server import app
from browser_bridge.state import state


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    state._clients.clear()  # type: ignore[attr-defined]
    state._seen_request_ids.clear()  # type: ignore[attr-defined]
    server.AUTH_MODE = "static"
    server.SHARED_TOKEN = "test-client-token"
    server.OPERATOR_TOKEN = "test-operator-token"


def _auth_client(ws, *, instance_id: str = "inst-1", client_id: str = "client-1", token: str = "test-client-token") -> None:
    ws.send_json(
        {
            "kind": "auth",
            "instance_id": instance_id,
            "client_id": client_id,
            "token": token,
        }
    )
    msg = ws.receive_json()
    assert msg["kind"] == "auth_ok"


def _auth_operator(ws, *, token: str = "test-operator-token") -> None:
    ws.send_json({"kind": "auth", "token": token})
    msg = ws.receive_json()
    assert msg["kind"] == "auth_ok"


def test_ws_auth_success_for_client_and_operator() -> None:
    client = TestClient(app)

    with client.websocket_connect("/ws/client") as ws_client:
        _auth_client(ws_client)

    with client.websocket_connect("/ws/operator") as ws_operator:
        _auth_operator(ws_operator)


def test_ws_auth_failure_rejects_client() -> None:
    client = TestClient(app)

    with client.websocket_connect("/ws/client") as ws_client:
        ws_client.send_json(
            {
                "kind": "auth",
                "instance_id": "inst-1",
                "client_id": "client-1",
                "token": "wrong",
            }
        )
        response = ws_client.receive_json()
        assert response["kind"] == "auth_error"
        assert response["code"] == "AUTH_FAILED"


def test_command_result_roundtrip() -> None:
    client = TestClient(app)

    with client.websocket_connect("/ws/client") as ws_client, client.websocket_connect("/ws/operator") as ws_operator:
        _auth_client(ws_client)
        _auth_operator(ws_operator)

        ws_operator.send_json(
            {
                "kind": "send_command",
                "instance_id": "inst-1",
                "client_id": "client-1",
                "type": "observe",
                "payload": {"max_nodes": 1},
                "timeout_s": 5,
                "request_id": "req-1",
            }
        )

        command = ws_client.receive_json()
        assert command["kind"] == "command"
        assert command["type"] == "observe"

        ws_client.send_json(
            {
                "kind": "result",
                "command_id": command["command_id"],
                "ok": True,
                "result": {"ok": True},
            }
        )

        result = ws_operator.receive_json()
        assert result["kind"] == "command_result"
        assert result["ok"] is True
        assert result["result"] == {"ok": True}


def test_disconnected_client_handling() -> None:
    client = TestClient(app)

    with client.websocket_connect("/ws/operator") as ws_operator:
        _auth_operator(ws_operator)
        ws_operator.send_json(
            {
                "kind": "send_command",
                "instance_id": "inst-1",
                "client_id": "missing",
                "type": "observe",
                "payload": {},
                "timeout_s": 1,
                "request_id": "req-missing",
            }
        )
        result = ws_operator.receive_json()
        assert result["kind"] == "command_result"
        assert result["ok"] is False
        assert result["code"] == "CLIENT_NOT_CONNECTED"


def test_wrong_target_client_routing() -> None:
    client = TestClient(app)

    with client.websocket_connect("/ws/client") as ws_client, client.websocket_connect("/ws/operator") as ws_operator:
        _auth_client(ws_client, instance_id="inst-1", client_id="client-a")
        _auth_operator(ws_operator)

        ws_operator.send_json(
            {
                "kind": "send_command",
                "instance_id": "inst-1",
                "client_id": "client-b",
                "type": "observe",
                "payload": {},
                "timeout_s": 1,
                "request_id": "req-wrong-target",
            }
        )
        result = ws_operator.receive_json()
        assert result["ok"] is False
        assert result["code"] == "CLIENT_NOT_CONNECTED"


def test_extension_reconnect_replaces_old_socket() -> None:
    client = TestClient(app)

    with (
        client.websocket_connect("/ws/client") as ws_client_old,
        client.websocket_connect("/ws/client") as ws_client_new,
        client.websocket_connect("/ws/operator") as ws_operator,
    ):
        _auth_client(ws_client_old, instance_id="inst-1", client_id="client-1")
        _auth_client(ws_client_new, instance_id="inst-1", client_id="client-1")
        _auth_operator(ws_operator)

        ws_operator.send_json(
            {
                "kind": "send_command",
                "instance_id": "inst-1",
                "client_id": "client-1",
                "type": "ping_tab",
                "payload": {},
                "timeout_s": 5,
                "request_id": "req-reconnect",
            }
        )

        command = ws_client_new.receive_json()
        assert command["kind"] == "command"
        assert command["type"] == "ping_tab"

        ws_client_new.send_json(
            {
                "kind": "result",
                "command_id": command["command_id"],
                "ok": True,
                "result": {"ready": True},
            }
        )

        result = ws_operator.receive_json()
        assert result["ok"] is True
        assert result["result"] == {"ready": True}


def test_press_key_command_roundtrip() -> None:
    client = TestClient(app)

    with client.websocket_connect("/ws/client") as ws_client, client.websocket_connect("/ws/operator") as ws_operator:
        _auth_client(ws_client)
        _auth_operator(ws_operator)

        ws_operator.send_json(
            {
                "kind": "send_command",
                "instance_id": "inst-1",
                "client_id": "client-1",
                "type": "press_key",
                "payload": {"key": "Enter", "selector": "input[name=q]"},
                "timeout_s": 5,
                "request_id": "req-press-key",
            }
        )

        command = ws_client.receive_json()
        assert command["kind"] == "command"
        assert command["type"] == "press_key"
        assert command["payload"] == {"key": "Enter", "selector": "input[name=q]"}

        ws_client.send_json(
            {
                "kind": "result",
                "command_id": command["command_id"],
                "ok": True,
                "result": {"pressed": True, "key": "Enter"},
            }
        )

        result = ws_operator.receive_json()
        assert result["kind"] == "command_result"
        assert result["ok"] is True
        assert result["result"] == {"pressed": True, "key": "Enter"}
