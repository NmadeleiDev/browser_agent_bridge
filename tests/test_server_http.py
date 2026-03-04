from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from browser_bridge.server import app


def _create_session(client: TestClient) -> dict[str, str]:
    response = client.post("/api/sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_token"]
    assert body["extension_token"]
    return body


def test_create_session_returns_jwts_and_expiry() -> None:
    client = TestClient(app)
    body = _create_session(client)

    assert body["session_id"]
    assert body["agent_token_expires_at"]
    assert body["extension_token_expires_at"]
    assert body["ws_url"].startswith("ws://127.0.0.1:8765/ws/extension/")


def test_status_requires_bearer_auth() -> None:
    client = TestClient(app)
    body = _create_session(client)

    response = client.get(f"/api/sessions/{body['session_id']}")
    assert response.status_code == 401


def test_status_rejects_bad_token() -> None:
    client = TestClient(app)
    body = _create_session(client)

    response = client.get(
        f"/api/sessions/{body['session_id']}",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert response.status_code == 401


def test_command_requires_request_id() -> None:
    client = TestClient(app)
    body = _create_session(client)

    response = client.post(
        f"/api/sessions/{body['session_id']}/command",
        headers={"Authorization": f"Bearer {body['agent_token']}"},
        json={"type": "observe", "payload": {}, "timeout_s": 2},
    )
    assert response.status_code == 400
    assert "X-Request-ID" in response.text


def test_command_replay_id_is_rejected() -> None:
    client = TestClient(app)
    body = _create_session(client)
    headers = {
        "Authorization": f"Bearer {body['agent_token']}",
        "X-Request-ID": "same-id",
    }

    first = client.post(
        f"/api/sessions/{body['session_id']}/command",
        headers=headers,
        json={"type": "observe", "payload": {}, "timeout_s": 1},
    )
    assert first.status_code == 409
    assert "Extension is not connected" in first.text

    second = client.post(
        f"/api/sessions/{body['session_id']}/command",
        headers=headers,
        json={"type": "observe", "payload": {}, "timeout_s": 1},
    )
    assert second.status_code == 409
    assert "Duplicate X-Request-ID" in second.text


def test_extension_ws_rejects_invalid_origin() -> None:
    client = TestClient(app)
    body = _create_session(client)

    try:
        with client.websocket_connect(
            f"/ws/extension/{body['session_id']}?token={body['extension_token']}",
            headers={"origin": "https://evil.example.com"},
        ):
            pass
    except WebSocketDisconnect as exc:
        assert exc.code == 1008
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected websocket rejection")


def test_extension_ws_rejects_invalid_token() -> None:
    client = TestClient(app)
    body = _create_session(client)

    try:
        with client.websocket_connect(
            f"/ws/extension/{body['session_id']}?token=bad-token",
            headers={"origin": "chrome-extension://devtest"},
        ):
            pass
    except WebSocketDenialResponse as exc:
        assert exc.status_code == 401
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected websocket token rejection")
