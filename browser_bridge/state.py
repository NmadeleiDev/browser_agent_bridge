from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import secrets
from typing import Any

from fastapi import WebSocket


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ClientConnection:
    instance_id: str
    client_id: str
    websocket: WebSocket
    connected_at: str = field(default_factory=utc_now_iso)
    last_seen_at: str = field(default_factory=utc_now_iso)
    pending_results: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)


class BridgeState:
    def __init__(self) -> None:
        self._clients: dict[tuple[str, str], ClientConnection] = {}
        self._seen_request_ids: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def register_client(self, *, instance_id: str, client_id: str, websocket: WebSocket) -> ClientConnection:
        key = (instance_id, client_id)
        async with self._lock:
            existing = self._clients.get(key)
            if existing and existing.websocket is not websocket:
                await existing.websocket.close(code=1012, reason="Replaced by a new connection")
                for command_id, future in list(existing.pending_results.items()):
                    if not future.done():
                        future.set_result(
                            {
                                "kind": "result",
                                "command_id": command_id,
                                "ok": False,
                                "error": "Client replaced by new connection",
                            }
                        )
            conn = ClientConnection(instance_id=instance_id, client_id=client_id, websocket=websocket)
            self._clients[key] = conn
            return conn

    async def remove_client(self, *, instance_id: str, client_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            key = (instance_id, client_id)
            existing = self._clients.get(key)
            if not existing or existing.websocket is not websocket:
                return
            self._clients.pop(key, None)
            for command_id, future in list(existing.pending_results.items()):
                if not future.done():
                    future.set_result(
                        {
                            "kind": "result",
                            "command_id": command_id,
                            "ok": False,
                            "error": "Client disconnected",
                        }
                    )

    async def get_client(self, *, instance_id: str, client_id: str) -> ClientConnection | None:
        async with self._lock:
            return self._clients.get((instance_id, client_id))

    async def list_clients(self) -> list[ClientConnection]:
        async with self._lock:
            return list(self._clients.values())

    async def register_request_id(self, request_id: str, ttl_s: float = 300.0) -> bool:
        now = asyncio.get_running_loop().time()
        async with self._lock:
            stale = [rid for rid, ts in self._seen_request_ids.items() if now - ts > ttl_s]
            for rid in stale:
                self._seen_request_ids.pop(rid, None)

            if request_id in self._seen_request_ids:
                return False

            self._seen_request_ids[request_id] = now
            return True

    def new_command_id(self) -> str:
        return secrets.token_urlsafe(10)


state = BridgeState()
