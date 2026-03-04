from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from browser_bridge.server import app
from browser_bridge.state import SessionState, state


def _create_session(client: TestClient) -> dict[str, str]:
    response = client.post("/api/sessions")
    assert response.status_code == 200
    return response.json()


def _get_session_state(session_id: str) -> SessionState:
    session = asyncio.run(state.get_session(session_id))
    assert session is not None
    return session


class _FakeWsSuccess:
    def __init__(self, session: SessionState) -> None:
        self._session = session

    async def send_json(self, command: dict[str, Any]) -> None:
        future = self._session.pending_results[command["command_id"]]
        future.set_result(
            {
                "kind": "result",
                "command_id": command["command_id"],
                "ok": True,
                "result": {"echo_type": command["type"]},
            }
        )


class _FakeWsNoReply:
    async def send_json(self, command: dict[str, Any]) -> None:  # noqa: ARG002
        return None


class _FakeWsError:
    async def send_json(self, command: dict[str, Any]) -> None:  # noqa: ARG002
        raise RuntimeError("socket unavailable")


def test_command_route_success_with_fake_socket() -> None:
    client = TestClient(app)
    created = _create_session(client)
    session = _get_session_state(created["session_id"])
    session.extension_ws = _FakeWsSuccess(session)

    response = client.post(
        f"/api/sessions/{created['session_id']}/command",
        headers={
            "Authorization": f"Bearer {created['agent_token']}",
            "X-Request-ID": "req-success-1",
        },
        json={"type": "observe", "payload": {}, "timeout_s": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["result"]["echo_type"] == "observe"


def test_command_route_timeout_with_fake_socket() -> None:
    client = TestClient(app)
    created = _create_session(client)
    session = _get_session_state(created["session_id"])
    session.extension_ws = _FakeWsNoReply()

    response = client.post(
        f"/api/sessions/{created['session_id']}/command",
        headers={
            "Authorization": f"Bearer {created['agent_token']}",
            "X-Request-ID": "req-timeout-1",
        },
        json={"type": "observe", "payload": {}, "timeout_s": 1},
    )

    assert response.status_code == 504


def test_command_route_socket_error_maps_to_409() -> None:
    client = TestClient(app)
    created = _create_session(client)
    session = _get_session_state(created["session_id"])
    session.extension_ws = _FakeWsError()

    response = client.post(
        f"/api/sessions/{created['session_id']}/command",
        headers={
            "Authorization": f"Bearer {created['agent_token']}",
            "X-Request-ID": "req-sockerr-1",
        },
        json={"type": "observe", "payload": {}, "timeout_s": 1},
    )

    assert response.status_code == 409
    assert "socket unavailable" in response.text


def test_ping_pong_websocket_endpoint() -> None:
    client = TestClient(app)
    created = _create_session(client)

    with client.websocket_connect(
        f"/ws/extension/{created['session_id']}?token={created['extension_token']}",
        headers={"origin": "chrome-extension://devtest"},
    ) as ws:
        ws.send_json({"kind": "ping"})
        pong = ws.receive_json()

    assert pong["kind"] == "pong"
    assert "ts" in pong
