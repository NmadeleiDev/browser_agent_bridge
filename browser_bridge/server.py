from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from . import __version__
from .state import SessionState, state, utc_now_iso

app = FastAPI(title="Browser Bridge", version=__version__)

JWT_SECRET = os.getenv("BRIDGE_JWT_SECRET", "dev-insecure-change-me")
JWT_ALG = "HS256"
AGENT_TOKEN_TTL_S = int(os.getenv("BRIDGE_AGENT_TOKEN_TTL_S", "3600"))
EXT_TOKEN_TTL_S = int(os.getenv("BRIDGE_EXTENSION_TOKEN_TTL_S", "86400"))

DEFAULT_ALLOWED_ORIGIN_PREFIXES = ["chrome-extension://", "http://localhost", "http://127.0.0.1"]
ALLOWED_ORIGIN_PREFIXES = [
    value.strip()
    for value in os.getenv("BRIDGE_ALLOWED_ORIGIN_PREFIXES", ",".join(DEFAULT_ALLOWED_ORIGIN_PREFIXES)).split(",")
    if value.strip()
]


class CreateSessionResponse(BaseModel):
    session_id: str
    agent_token: str
    extension_token: str
    ws_url: str
    agent_token_expires_at: str
    extension_token_expires_at: str


class SessionStatusResponse(BaseModel):
    session_id: str
    connected: bool
    created_at: str
    extension_connected_at: str | None
    last_seen_at: str | None
    pending_commands: int


class CommandRequest(BaseModel):
    type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_s: float = Field(default=20.0, ge=1.0, le=120.0)


class CommandResponse(BaseModel):
    command_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


def _issue_token(session_id: str, role: str, ttl_s: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_s)
    claims = {
        "sub": session_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALG), expires.isoformat()


def _decode_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if not isinstance(claims, dict):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return claims


def _ensure_role_and_session(claims: dict[str, Any], expected_role: str, session_id: str) -> None:
    role = claims.get("role")
    sub = claims.get("sub")
    if role != expected_role or sub != session_id:
        raise HTTPException(status_code=401, detail="Token role/session mismatch")


def _extract_bearer(auth_header: str | None) -> str:
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    return parts[1].strip()


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return False
    return any(origin.startswith(prefix) for prefix in ALLOWED_ORIGIN_PREFIXES)


async def get_agent_session(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> SessionState:
    token = _extract_bearer(authorization)
    claims = _decode_token(token)
    _ensure_role_and_session(claims=claims, expected_role="agent", session_id=session_id)

    session = await state.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/sessions", response_model=CreateSessionResponse)
async def create_session(base_ws_url: str = Query(default="ws://127.0.0.1:8765")) -> CreateSessionResponse:
    session = await state.create_session()
    agent_token, agent_exp = _issue_token(session.session_id, "agent", AGENT_TOKEN_TTL_S)
    extension_token, ext_exp = _issue_token(session.session_id, "extension", EXT_TOKEN_TTL_S)
    return CreateSessionResponse(
        session_id=session.session_id,
        agent_token=agent_token,
        extension_token=extension_token,
        ws_url=(
            f"{base_ws_url}/ws/extension/{session.session_id}"
            f"?token={extension_token}"
        ),
        agent_token_expires_at=agent_exp,
        extension_token_expires_at=ext_exp,
    )


@app.get("/api/sessions/{session_id}", response_model=SessionStatusResponse)
async def session_status(session: SessionState = Depends(get_agent_session)) -> SessionStatusResponse:
    return SessionStatusResponse(
        session_id=session.session_id,
        connected=session.extension_ws is not None,
        created_at=session.created_at,
        extension_connected_at=session.extension_connected_at,
        last_seen_at=session.last_seen_at,
        pending_commands=len(session.pending_results),
    )


@app.post("/api/sessions/{session_id}/command", response_model=CommandResponse)
async def send_command(
    payload: CommandRequest,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    session: SessionState = Depends(get_agent_session),
) -> CommandResponse:
    if not request_id:
        raise HTTPException(status_code=400, detail="Missing X-Request-ID header")

    not_duplicate = await state.register_request_id(session_id=session.session_id, request_id=request_id)
    if not not_duplicate:
        raise HTTPException(status_code=409, detail="Duplicate X-Request-ID (possible replay)")

    ws = session.extension_ws
    if ws is None:
        raise HTTPException(status_code=409, detail="Extension is not connected")

    command_id = secrets.token_urlsafe(10)
    future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    session.pending_results[command_id] = future

    command = {
        "kind": "command",
        "command_id": command_id,
        "type": payload.type,
        "payload": payload.payload,
        "sent_at": utc_now_iso(),
        "request_id": request_id,
    }

    try:
        await ws.send_json(command)
        raw_result = await asyncio.wait_for(future, timeout=payload.timeout_s)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Command timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Extension socket unavailable") from exc
    finally:
        session.pending_results.pop(command_id, None)

    ok = bool(raw_result.get("ok", False))
    result = raw_result.get("result")
    error = raw_result.get("error")
    if result is not None and not isinstance(result, dict):
        result = {"value": result}

    return CommandResponse(command_id=command_id, ok=ok, result=result, error=error)


@app.websocket("/ws/extension/{session_id}")
async def extension_ws(websocket: WebSocket, session_id: str, token: str = Query(...)) -> None:
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    claims = _decode_token(token)
    _ensure_role_and_session(claims=claims, expected_role="extension", session_id=session_id)

    session = await state.get_session(session_id)
    if session is None:
        await websocket.close(code=1008, reason="Session does not exist")
        return

    await websocket.accept()

    if session.extension_ws is not None:
        await session.extension_ws.close(code=1012, reason="Replaced by a new connection")

    session.extension_ws = websocket
    session.extension_connected_at = utc_now_iso()
    session.last_seen_at = utc_now_iso()

    try:
        while True:
            message = await websocket.receive_text()
            session.last_seen_at = utc_now_iso()
            parsed = json.loads(message)
            if not isinstance(parsed, dict):
                continue

            kind = parsed.get("kind")
            if kind == "result":
                command_id = parsed.get("command_id")
                if not isinstance(command_id, str):
                    continue
                future = session.pending_results.get(command_id)
                if future and not future.done():
                    future.set_result(parsed)
            elif kind == "ping":
                await websocket.send_json({"kind": "pong", "ts": utc_now_iso()})
    except WebSocketDisconnect:
        pass
    finally:
        if session.extension_ws is websocket:
            session.extension_ws = None
        for command_id, future in list(session.pending_results.items()):
            if not future.done():
                future.set_result(
                    {
                        "kind": "result",
                        "command_id": command_id,
                        "ok": False,
                        "error": "Extension disconnected",
                    }
                )


def main() -> None:
    import uvicorn

    uvicorn.run("browser_bridge.server:app", host="0.0.0.0", port=8765, reload=False)


if __name__ == "__main__":
    main()
