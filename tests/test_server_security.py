from __future__ import annotations

import browser_bridge.server as server
import pytest


@pytest.fixture(autouse=True)
def _restore_server_globals():
    original_auth_mode = server.AUTH_MODE
    original_app_env = server.APP_ENV
    original_shared_token = server.SHARED_TOKEN
    original_operator_token = server.OPERATOR_TOKEN
    try:
        yield
    finally:
        server.AUTH_MODE = original_auth_mode
        server.APP_ENV = original_app_env
        server.SHARED_TOKEN = original_shared_token
        server.OPERATOR_TOKEN = original_operator_token


def test_validate_startup_security_rejects_weak_operator_token() -> None:
    server.AUTH_MODE = "static"
    server.APP_ENV = "development"
    server.OPERATOR_TOKEN = "too-simple-token"

    with pytest.raises(RuntimeError, match="BRIDGE_OPERATOR_TOKEN"):
        server._validate_startup_security()


def test_validate_startup_security_accepts_strong_operator_token() -> None:
    server.AUTH_MODE = "static"
    server.APP_ENV = "development"
    server.OPERATOR_TOKEN = "Str0ng!Operator#42"

    server._validate_startup_security()

