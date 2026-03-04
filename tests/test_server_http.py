from __future__ import annotations

from fastapi.testclient import TestClient

import browser_bridge.server as server
from browser_bridge.server import app


def test_http_compat_endpoints_disabled_by_default() -> None:
    server.ENABLE_HTTP_COMPAT = False
    client = TestClient(app)

    r1 = client.post("/api/sessions")
    r2 = client.get("/api/sessions/abc")
    r3 = client.post("/api/sessions/abc/command")

    assert r1.status_code == 410
    assert r2.status_code == 410
    assert r3.status_code == 410
