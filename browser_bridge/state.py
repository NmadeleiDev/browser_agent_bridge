from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionState:
    session_id: str
    created_at: str = field(default_factory=utc_now_iso)
    extension_connected_at: str | None = None
    last_seen_at: str | None = None
    extension_ws: WebSocket | None = None
    pending_results: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    seen_request_ids: dict[str, float] = field(default_factory=dict)


class InMemoryState:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create_session(self) -> SessionState:
        async with self._lock:
            session = SessionState(session_id=self._new_session_id())
            self._sessions[session.session_id] = session
            return session

    async def get_session(self, session_id: str) -> SessionState | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def register_request_id(self, session_id: str, request_id: str, ttl_s: float = 300.0) -> bool:
        now = asyncio.get_running_loop().time()
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            stale = [rid for rid, ts in session.seen_request_ids.items() if now - ts > ttl_s]
            for rid in stale:
                session.seen_request_ids.pop(rid, None)

            if request_id in session.seen_request_ids:
                return False

            session.seen_request_ids[request_id] = now
            return True

    def _new_session_id(self) -> str:
        import secrets

        return secrets.token_urlsafe(12)


state = InMemoryState()
