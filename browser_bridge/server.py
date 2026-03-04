from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect

from . import __version__
from .secret import DEFAULT_JWT_SECRET, ensure_non_default_secret
from .state import ClientConnection, state, utc_now_iso

app = FastAPI(title="Browser Bridge", version=__version__)
logger = logging.getLogger("browser_bridge.server")

AUTH_MODE = os.getenv("BRIDGE_AUTH_MODE", "static").strip().lower()
APP_ENV = os.getenv("BRIDGE_ENV", "development").strip().lower()
SHARED_TOKEN = os.getenv("BRIDGE_SHARED_TOKEN", "dev-bridge-token")
OPERATOR_TOKEN = os.getenv("BRIDGE_OPERATOR_TOKEN", SHARED_TOKEN)
JWT_SECRET = os.getenv("BRIDGE_JWT_SECRET", DEFAULT_JWT_SECRET)
JWT_ALG = os.getenv("BRIDGE_JWT_ALG", "HS256")
ENABLE_HTTP_COMPAT = os.getenv("BRIDGE_ENABLE_HTTP_COMPAT", "0") in {"1", "true", "yes"}
MAX_MESSAGE_BYTES = int(os.getenv("BRIDGE_MAX_MESSAGE_BYTES", "1000000"))
AUTH_TIMEOUT_S = float(os.getenv("BRIDGE_AUTH_TIMEOUT_S", "10"))
DEFAULT_COMMAND_TIMEOUT_S = float(os.getenv("BRIDGE_DEFAULT_COMMAND_TIMEOUT_S", "20"))
MAX_COMMAND_TIMEOUT_S = float(os.getenv("BRIDGE_MAX_COMMAND_TIMEOUT_S", "120"))

_COMMAND_ALLOWLIST_RAW = os.getenv("BRIDGE_COMMAND_ALLOWLIST", "").strip()
COMMAND_ALLOWLIST = {v.strip() for v in _COMMAND_ALLOWLIST_RAW.split(",") if v.strip()}

_ALLOWED_CLIENTS_RAW = os.getenv("BRIDGE_ALLOWED_CLIENTS", "").strip()
ALLOWED_CLIENT_KEYS = {v.strip() for v in _ALLOWED_CLIENTS_RAW.split(",") if v.strip()}


class ProtocolError(Exception):
    def __init__(self, message: str, *, code: str = "PROTOCOL_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class AuthedClient:
    instance_id: str
    client_id: str


def _validate_startup_security() -> None:
    if AUTH_MODE not in {"static", "jwt"}:
        raise RuntimeError("BRIDGE_AUTH_MODE must be one of: static, jwt")

    if APP_ENV == "production":
        if AUTH_MODE == "static" and SHARED_TOKEN in {"", "dev-bridge-token"}:
            raise RuntimeError("In production, BRIDGE_SHARED_TOKEN must be set to a strong value")
        if AUTH_MODE == "jwt" and JWT_SECRET in {"", DEFAULT_JWT_SECRET}:
            raise RuntimeError("In production, BRIDGE_JWT_SECRET must be set to a strong value")


def bootstrap_server_auth_secret_for_local_use() -> None:
    global JWT_SECRET
    if AUTH_MODE != "jwt":
        return
    secret, path, created = ensure_non_default_secret(JWT_SECRET)
    if secret != JWT_SECRET:
        JWT_SECRET = secret
        if created:
            logger.warning("Generated local BRIDGE_JWT_SECRET at %s", path)
        else:
            logger.info("Loaded local BRIDGE_JWT_SECRET from %s", path)


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    text = json.dumps(payload)
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Outgoing message exceeds max payload size", code="PAYLOAD_TOO_LARGE")
    return text


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    await websocket.send_text(_safe_json_dumps(payload))


async def _recv_json(websocket: WebSocket, *, timeout_s: float | None = None) -> dict[str, Any]:
    try:
        text = await asyncio.wait_for(websocket.receive_text(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise ProtocolError("Timed out waiting for message", code="TIMEOUT") from exc
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Incoming message exceeds max payload size", code="PAYLOAD_TOO_LARGE")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Invalid JSON payload", code="BAD_JSON") from exc
    if not isinstance(parsed, dict):
        raise ProtocolError("Payload must be an object", code="BAD_PAYLOAD")
    return parsed


def _jwt_claims(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.InvalidTokenError as exc:
        raise ProtocolError("Invalid or expired JWT", code="AUTH_FAILED") from exc
    if not isinstance(claims, dict):
        raise ProtocolError("Invalid JWT payload", code="AUTH_FAILED")
    return claims


def _validate_client_allowlist(instance_id: str, client_id: str) -> None:
    if not ALLOWED_CLIENT_KEYS:
        return
    key = f"{instance_id}:{client_id}"
    if key not in ALLOWED_CLIENT_KEYS:
        raise ProtocolError("Client is not in allowed list", code="AUTH_FAILED")


def _auth_client(payload: dict[str, Any]) -> AuthedClient:
    if payload.get("kind") != "auth":
        raise ProtocolError("First message must be auth", code="AUTH_REQUIRED")

    instance_id = str(payload.get("instance_id") or "").strip()
    client_id = str(payload.get("client_id") or "").strip()
    token = str(payload.get("token") or "").strip()

    if not instance_id or not client_id:
        raise ProtocolError("instance_id and client_id are required", code="AUTH_FAILED")
    if not token:
        raise ProtocolError("token is required", code="AUTH_FAILED")

    if AUTH_MODE == "static":
        if token != SHARED_TOKEN:
            raise ProtocolError("Invalid token", code="AUTH_FAILED")
        _validate_client_allowlist(instance_id, client_id)
    else:
        claims = _jwt_claims(token)
        role = str(claims.get("role") or "")
        if role and role != "client":
            raise ProtocolError("JWT role mismatch", code="AUTH_FAILED")
        claim_instance = str(claims.get("instance_id") or "")
        claim_client = str(claims.get("client_id") or "")
        if claim_instance != instance_id or claim_client != client_id:
            raise ProtocolError("JWT instance/client mismatch", code="AUTH_FAILED")

    return AuthedClient(instance_id=instance_id, client_id=client_id)


def _auth_operator(payload: dict[str, Any]) -> None:
    if payload.get("kind") != "auth":
        raise ProtocolError("First message must be auth", code="AUTH_REQUIRED")

    token = str(payload.get("token") or "").strip()
    if not token:
        raise ProtocolError("token is required", code="AUTH_FAILED")

    if AUTH_MODE == "static":
        if token != OPERATOR_TOKEN:
            raise ProtocolError("Invalid operator token", code="AUTH_FAILED")
    else:
        claims = _jwt_claims(token)
        role = str(claims.get("role") or "")
        if role != "operator":
            raise ProtocolError("JWT role mismatch", code="AUTH_FAILED")


def _to_client_summary(conn: ClientConnection) -> dict[str, Any]:
    return {
        "instance_id": conn.instance_id,
        "client_id": conn.client_id,
        "connected_at": conn.connected_at,
        "last_seen_at": conn.last_seen_at,
    }


async def _send_command_to_client(request: dict[str, Any]) -> dict[str, Any]:
    instance_id = str(request.get("instance_id") or "").strip()
    client_id = str(request.get("client_id") or "").strip()
    command_type = str(request.get("type") or "").strip()

    if not instance_id or not client_id:
        raise ProtocolError("instance_id and client_id are required", code="BAD_REQUEST")
    if not command_type:
        raise ProtocolError("type is required", code="BAD_REQUEST")
    if COMMAND_ALLOWLIST and command_type not in COMMAND_ALLOWLIST:
        raise ProtocolError(f"Command type not allowed: {command_type}", code="COMMAND_NOT_ALLOWED")

    payload = request.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be an object", code="BAD_REQUEST")

    timeout_s_raw = request.get("timeout_s", DEFAULT_COMMAND_TIMEOUT_S)
    try:
        timeout_s = float(timeout_s_raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("timeout_s must be numeric", code="BAD_REQUEST") from exc
    timeout_s = max(1.0, min(timeout_s, MAX_COMMAND_TIMEOUT_S))

    request_id = str(request.get("request_id") or "").strip()
    if not request_id:
        raise ProtocolError("request_id is required", code="BAD_REQUEST")

    not_duplicate = await state.register_request_id(request_id=request_id)
    if not not_duplicate:
        raise ProtocolError("Duplicate request_id", code="DUPLICATE_REQUEST")

    conn = await state.get_client(instance_id=instance_id, client_id=client_id)
    if conn is None:
        raise ProtocolError("Target client not connected", code="CLIENT_NOT_CONNECTED")

    command_id = state.new_command_id()
    future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    conn.pending_results[command_id] = future

    try:
        await _send_json(
            conn.websocket,
            {
                "kind": "command",
                "command_id": command_id,
                "type": command_type,
                "payload": payload,
                "request_id": request_id,
                "sent_at": utc_now_iso(),
            },
        )
        raw_result = await asyncio.wait_for(future, timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise ProtocolError("Command timed out", code="TIMEOUT") from exc
    finally:
        conn.pending_results.pop(command_id, None)

    ok = bool(raw_result.get("ok", False))
    result = raw_result.get("result")
    error = raw_result.get("error")
    if result is not None and not isinstance(result, dict):
        result = {"value": result}

    return {
        "kind": "command_result",
        "command_id": command_id,
        "ok": ok,
        "result": result,
        "error": error,
        "request_id": request_id,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/client")
async def ws_client(websocket: WebSocket) -> None:
    await websocket.accept()

    authed: AuthedClient | None = None
    try:
        auth_msg = await _recv_json(websocket, timeout_s=AUTH_TIMEOUT_S)
        authed = _auth_client(auth_msg)
        await state.register_client(
            instance_id=authed.instance_id,
            client_id=authed.client_id,
            websocket=websocket,
        )
        await _send_json(
            websocket,
            {
                "kind": "auth_ok",
                "instance_id": authed.instance_id,
                "client_id": authed.client_id,
                "ts": utc_now_iso(),
            },
        )

        while True:
            message = await _recv_json(websocket)
            conn = await state.get_client(instance_id=authed.instance_id, client_id=authed.client_id)
            if conn:
                conn.last_seen_at = utc_now_iso()

            kind = message.get("kind")
            if kind == "result":
                command_id = str(message.get("command_id") or "").strip()
                if not command_id or conn is None:
                    continue
                future = conn.pending_results.get(command_id)
                if future and not future.done():
                    future.set_result(message)
            elif kind == "ping":
                await _send_json(websocket, {"kind": "pong", "ts": utc_now_iso()})
    except WebSocketDisconnect:
        pass
    except ProtocolError as exc:
        await _send_json(websocket, {"kind": "auth_error", "code": exc.code, "error": exc.message})
        await websocket.close(code=1008, reason=exc.message)
    finally:
        if authed:
            await state.remove_client(
                instance_id=authed.instance_id,
                client_id=authed.client_id,
                websocket=websocket,
            )


@app.websocket("/ws/operator")
async def ws_operator(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        auth_msg = await _recv_json(websocket, timeout_s=AUTH_TIMEOUT_S)
        _auth_operator(auth_msg)
        await _send_json(websocket, {"kind": "auth_ok", "ts": utc_now_iso()})

        while True:
            message = await _recv_json(websocket)
            kind = message.get("kind")

            if kind == "ping":
                await _send_json(websocket, {"kind": "pong", "ts": utc_now_iso()})
                continue

            if kind == "list_clients":
                clients = [_to_client_summary(c) for c in await state.list_clients()]
                await _send_json(websocket, {"kind": "clients", "clients": clients, "ts": utc_now_iso()})
                continue

            if kind == "connect_status":
                instance_id = str(message.get("instance_id") or "").strip()
                client_id = str(message.get("client_id") or "").strip()
                if not instance_id or not client_id:
                    raise ProtocolError("instance_id and client_id are required", code="BAD_REQUEST")
                conn = await state.get_client(instance_id=instance_id, client_id=client_id)
                await _send_json(
                    websocket,
                    {
                        "kind": "connect_status",
                        "instance_id": instance_id,
                        "client_id": client_id,
                        "connected": conn is not None,
                        "connected_at": conn.connected_at if conn else None,
                        "last_seen_at": conn.last_seen_at if conn else None,
                        "ts": utc_now_iso(),
                    },
                )
                continue

            if kind == "send_command":
                try:
                    result = await _send_command_to_client(message)
                    await _send_json(websocket, result)
                except ProtocolError as exc:
                    await _send_json(
                        websocket,
                        {
                            "kind": "command_result",
                            "ok": False,
                            "error": exc.message,
                            "code": exc.code,
                            "request_id": str(message.get("request_id") or ""),
                        },
                    )
                continue

            raise ProtocolError(f"Unsupported operator message kind: {kind}", code="BAD_REQUEST")

    except WebSocketDisconnect:
        return
    except ProtocolError as exc:
        await _send_json(websocket, {"kind": "auth_error", "code": exc.code, "error": exc.message})
        await websocket.close(code=1008, reason=exc.message)


@app.post("/api/sessions")
async def deprecated_create_session() -> dict[str, Any]:
    if not ENABLE_HTTP_COMPAT:
        raise HTTPException(status_code=410, detail="HTTP session APIs are disabled. Use WS auth protocol.")
    raise HTTPException(status_code=501, detail="HTTP compatibility mode is not implemented in this build.")


@app.get("/api/sessions/{session_id}")
async def deprecated_session_status(session_id: str) -> dict[str, Any]:
    if not ENABLE_HTTP_COMPAT:
        raise HTTPException(status_code=410, detail="HTTP session APIs are disabled. Use WS connect_status.")
    raise HTTPException(status_code=501, detail="HTTP compatibility mode is not implemented in this build.")


@app.post("/api/sessions/{session_id}/command")
async def deprecated_send_command(session_id: str) -> dict[str, Any]:
    if not ENABLE_HTTP_COMPAT:
        raise HTTPException(status_code=410, detail="HTTP command APIs are disabled. Use WS send_command.")
    raise HTTPException(status_code=501, detail="HTTP compatibility mode is not implemented in this build.")


def main() -> None:
    import uvicorn

    bootstrap_server_auth_secret_for_local_use()
    _validate_startup_security()
    uvicorn.run("browser_bridge.server:app", host="0.0.0.0", port=8765, reload=False)


if __name__ == "__main__":
    main()
