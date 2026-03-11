from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from . import __version__
from .secret import secret_file_path, setup_local_secret

LOG_LEVEL_ENV_VAR = "BROWSER_BRIDGE_LOG_LEVEL"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_OPERATOR_WS_URL = "ws://127.0.0.1:8765/ws/operator"
DEFAULT_OPERATOR_TOKEN = "dev-bridge-token"
TOKEN_ENV_VAR = "BRIDGE_OPERATOR_TOKEN"
MAX_MESSAGE_BYTES = int(os.getenv("BRIDGE_MAX_MESSAGE_BYTES", "1000000"))

logger = logging.getLogger("browser_bridge.cli")


class CliError(Exception):
    def __init__(self, message: str, *, hint: str | None = None, exit_code: int = 2) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


def _configure_logging() -> None:
    level_name = os.getenv(LOG_LEVEL_ENV_VAR, DEFAULT_LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _token_from_args(args: argparse.Namespace) -> str:
    token = str(getattr(args, "token", "") or os.getenv(TOKEN_ENV_VAR, DEFAULT_OPERATOR_TOKEN)).strip()
    if not token:
        raise CliError(
            "Missing operator token",
            hint=f"Pass --token or set {TOKEN_ENV_VAR}.",
        )
    return token


async def _send_and_recv(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    url = str(args.server_ws_url).strip()
    if not url:
        raise CliError("Missing --server-ws-url")

    token = _token_from_args(args)

    try:
        async with websockets.connect(url, max_size=MAX_MESSAGE_BYTES) as ws:
            await ws.send(json.dumps({"kind": "auth", "token": token}))
            auth_raw = await ws.recv()
            auth = json.loads(auth_raw)
            if auth.get("kind") != "auth_ok":
                message = str(auth.get("error") or "authentication failed")
                code = str(auth.get("code") or "AUTH_FAILED")
                raise CliError(f"Operator auth failed: {code} {message}", exit_code=1)

            await ws.send(json.dumps(payload))
            raw = await ws.recv()
            return json.loads(raw)
    except CliError:
        raise
    except ConnectionClosed as exc:
        raise CliError(
            f"Connection closed: {exc}",
            hint="Verify server URL/token and that the bridge server is running.",
            exit_code=1,
        ) from exc
    except OSError as exc:
        raise CliError(
            f"Cannot connect to operator WS `{url}`",
            hint="Verify server URL/reachability and TLS settings (ws/wss).",
            exit_code=1,
        ) from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid JSON response from server: {exc}", exit_code=1) from exc


def _result_or_raise(result: dict[str, Any], *, action: str) -> dict[str, Any]:
    kind = str(result.get("kind") or "")
    if kind == "auth_error":
        raise CliError(
            f"{action} failed: {result.get('code', 'AUTH_FAILED')} {result.get('error', '')}".strip(),
            exit_code=1,
        )
    return result


def list_clients(args: argparse.Namespace) -> int:
    logger.info("Listing connected clients")
    result = asyncio.run(_send_and_recv(args, {"kind": "list_clients"}))
    result = _result_or_raise(result, action="list-clients")
    _print_json(result)
    return 0


def connect_status(args: argparse.Namespace) -> int:
    payload = {
        "kind": "connect_status",
        "instance_id": args.instance_id,
        "client_id": args.client_id,
    }
    logger.info("Checking connect status instance_id=%s client_id=%s", args.instance_id, args.client_id)
    result = asyncio.run(_send_and_recv(args, payload))
    result = _result_or_raise(result, action="connect-status")
    _print_json(result)
    return 0


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload_text = args.payload or "{}"
    payload_file = str(getattr(args, "payload_file", "") or "").strip()

    if payload_file:
        if payload_text and payload_text != "{}":
            raise CliError("Use either --payload or --payload-file, not both.")
        try:
            with open(payload_file, "r", encoding="utf-8") as fh:
                payload_text = fh.read()
        except OSError as exc:
            raise CliError(
                f"Cannot read payload file: {payload_file}",
                hint="Check file path and permissions.",
            ) from exc

    try:
        payload = json.loads(payload_text or "{}")
    except json.JSONDecodeError as exc:
        location = f" line {exc.lineno} column {exc.colno}" if exc.lineno and exc.colno else ""
        source_hint = f"payload file `{payload_file}`" if payload_file else "--payload"
        raise CliError(
            f"Invalid JSON in {source_hint}:{location} {exc.msg}",
            hint='Pass valid JSON, e.g. --payload \'{"url":"https://example.com"}\' or use --payload-file request.json.',
        ) from exc

    if not isinstance(payload, dict):
        raise CliError("Invalid payload type", hint="Payload must be a JSON object.")
    return payload


def send_command(args: argparse.Namespace) -> int:
    payload = _load_payload(args)

    request_id = args.request_id or uuid.uuid4().hex
    wire = {
        "kind": "send_command",
        "instance_id": args.instance_id,
        "client_id": args.client_id,
        "type": args.command_type,
        "payload": payload,
        "timeout_s": args.timeout_s,
        "request_id": request_id,
    }

    logger.info(
        "Sending command=%s instance_id=%s client_id=%s request_id=%s",
        args.command_type,
        args.instance_id,
        args.client_id,
        request_id,
    )
    result = asyncio.run(_send_and_recv(args, wire))
    result = _result_or_raise(result, action=f"command {args.command_type}")

    if not bool(result.get("ok", False)):
        code = str(result.get("code") or "COMMAND_FAILED")
        message = str(result.get("error") or "unknown error")
        raise CliError(
            f"command {args.command_type} failed: {code} {message}",
            hint="Check connect-status/list-clients, request timeout, and target instance/client IDs.",
            exit_code=1,
        )

    _print_json(result)
    return 0


def observe(args: argparse.Namespace) -> int:
    args.command_type = "observe"
    args.payload = json.dumps({"max_nodes": args.max_nodes})
    return send_command(args)


def ping_tab(args: argparse.Namespace) -> int:
    args.command_type = "ping_tab"
    args.payload = "{}"
    return send_command(args)


def setup_secret(args: argparse.Namespace) -> int:
    try:
        secret, path = setup_local_secret(secret=args.secret, overwrite=args.force)
    except FileExistsError as exc:
        raise CliError(
            str(exc),
            hint="Use --force to overwrite or reuse the existing secret file.",
            exit_code=1,
        ) from exc
    except RuntimeError as exc:
        raise CliError(f"setup-secret failed: {exc}", exit_code=1) from exc

    payload: dict[str, Any] = {
        "ok": True,
        "secret_file": str(path),
    }
    if args.show_secret:
        payload["secret"] = secret
    else:
        payload["secret_preview"] = f"{secret[:6]}...{secret[-4:]}"
    _print_json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser Bridge CLI (WS-only)")
    parser.add_argument("--server-ws-url", default=DEFAULT_OPERATOR_WS_URL, help="Operator websocket URL")
    parser.add_argument("--token", default="", help=f"Operator token (or {TOKEN_ENV_VAR})")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_cmd = subparsers.add_parser(
        "setup-secret",
        help=(
            "Create and save local server JWT secret. "
            "Server auto-loads this on startup when BRIDGE_JWT_SECRET is still default."
        ),
    )
    setup_cmd.add_argument("--secret", default="", help="Optional explicit secret value")
    setup_cmd.add_argument("--force", action="store_true", help=f"Overwrite existing secret file at {secret_file_path()}")
    setup_cmd.add_argument("--show-secret", action="store_true", help="Print full secret in output")
    setup_cmd.set_defaults(func=setup_secret)

    list_cmd = subparsers.add_parser("list-clients", help="List connected browser clients")
    list_cmd.set_defaults(func=list_clients)

    status_cmd = subparsers.add_parser("connect-status", help="Check if a client is connected")
    status_cmd.add_argument("--instance-id", required=True)
    status_cmd.add_argument("--client-id", required=True)
    status_cmd.set_defaults(func=connect_status)

    send_cmd = subparsers.add_parser("send-command", help="Send raw command to connected client")
    send_cmd.add_argument("--instance-id", required=True)
    send_cmd.add_argument("--client-id", required=True)
    send_cmd.add_argument("--type", dest="command_type", required=True)
    send_cmd.add_argument("--payload", default="{}", help="JSON payload string")
    send_cmd.add_argument("--payload-file", default="", help="Path to JSON payload file")
    send_cmd.add_argument("--timeout-s", type=float, default=20.0)
    send_cmd.add_argument("--request-id", default="", help="Optional idempotency key; auto-generated if omitted")
    send_cmd.set_defaults(func=send_command)

    observe_cmd = subparsers.add_parser("observe", help="Get simplified page snapshot")
    observe_cmd.add_argument("--instance-id", required=True)
    observe_cmd.add_argument("--client-id", required=True)
    observe_cmd.add_argument("--max-nodes", type=int, default=150)
    observe_cmd.add_argument("--timeout-s", type=float, default=20.0)
    observe_cmd.add_argument("--request-id", default="", help="Optional idempotency key; auto-generated if omitted")
    observe_cmd.set_defaults(func=observe)

    ping_cmd = subparsers.add_parser("ping-tab", help="Check if active tab content script is reachable")
    ping_cmd.add_argument("--instance-id", required=True)
    ping_cmd.add_argument("--client-id", required=True)
    ping_cmd.add_argument("--timeout-s", type=float, default=8.0)
    ping_cmd.add_argument("--request-id", default="", help="Optional idempotency key; auto-generated if omitted")
    ping_cmd.set_defaults(func=ping_tab)

    return parser


def main() -> int:
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except CliError as exc:
        logger.error(exc.message)
        if exc.hint:
            logger.error("Hint: %s", exc.hint)
        return int(exc.exit_code)
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
