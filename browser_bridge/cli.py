from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import uuid
from typing import Any

import httpx

from . import __version__

CONFIG_ENV_VAR = "BROWSER_BRIDGE_CONFIG"
DEFAULT_CONFIG_PATH = "~/.browser_bridge/sessions.json"
LOG_LEVEL_ENV_VAR = "BROWSER_BRIDGE_LOG_LEVEL"
DEFAULT_LOG_LEVEL = "INFO"

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


def _config_path() -> Path:
    return Path(os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)).expanduser()


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {"version": 1, "default_session_name": None, "sessions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(
            f"Invalid JSON in config file: {path}",
            hint=f"Fix or remove this file, or set {CONFIG_ENV_VAR} to a clean path.",
        ) from exc
    if not isinstance(data, dict):
        raise CliError(
            f"Invalid config format in {path}",
            hint="Config root must be a JSON object.",
        )
    if "sessions" not in data or not isinstance(data["sessions"], dict):
        data["sessions"] = {}
    if "default_session_name" not in data:
        data["default_session_name"] = None
    if "version" not in data:
        data["version"] = 1
    return data


def _save_config(config: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    session_id = getattr(args, "session_id", "") or ""
    agent_token = getattr(args, "agent_token", "") or ""
    if session_id and agent_token:
        return session_id, agent_token

    config = _load_config()
    sessions = config.get("sessions", {})
    name = getattr(args, "name", "") or config.get("default_session_name")
    if not name:
        raise CliError(
            "Missing credentials",
            hint=(
                "Pass --session-id and --agent-token, or create and use a named profile: "
                "`browser-bridge create-session --name local` then `--name local`."
            ),
        )

    profile = sessions.get(name)
    if not isinstance(profile, dict):
        raise CliError(
            f'Session profile "{name}" not found in {_config_path()}',
            hint="Run create-session with --name to create it, or pass explicit credentials.",
        )

    stored_session_id = profile.get("session_id")
    stored_agent_token = profile.get("agent_token")
    if not stored_session_id or not stored_agent_token:
        raise CliError(
            f'Session profile "{name}" is missing session_id or agent_token',
            hint="Re-create the profile with `create-session --name <name>`.",
        )
    return str(stored_session_id), str(stored_agent_token)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _http_error_to_cli_error(exc: httpx.HTTPStatusError, *, action: str) -> CliError:
    detail = exc.response.text.strip()
    hint: str | None = None
    if exc.response.status_code == 401:
        hint = "Token expired/invalid. Create a fresh session or use correct credentials."
    elif exc.response.status_code == 404:
        hint = "Session not found. Create a new session and reconnect extension."
    elif exc.response.status_code == 409:
        hint = "Session not connected or duplicate request ID. Reconnect extension and retry."
    elif exc.response.status_code == 504:
        hint = "Command timed out. Ensure extension is connected and tab is controllable."
    return CliError(
        f"{action} failed: HTTP {exc.response.status_code} {detail}",
        hint=hint,
        exit_code=1,
    )


def _request_error_to_cli_error(exc: httpx.RequestError, *, action: str) -> CliError:
    if isinstance(exc, httpx.TimeoutException):
        return CliError(
            f"{action} failed: request timed out",
            hint="Verify server responsiveness/network path and increase --timeout-s if needed.",
            exit_code=1,
        )
    return CliError(
        f"{action} failed: cannot reach server `{exc.request.url}`",
        hint="Verify --server URL, that browser_bridge.server is running, and network access is allowed.",
        exit_code=1,
    )


def create_session(args: argparse.Namespace) -> int:
    logger.info("Creating session at %s", args.server)
    try:
        response = httpx.post(
            f"{args.server}/api/sessions",
            params={"base_ws_url": args.ws_base},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise _http_error_to_cli_error(exc, action="create-session") from exc
    except httpx.RequestError as exc:
        raise _request_error_to_cli_error(exc, action="create-session") from exc

    body = response.json()
    if args.name:
        config = _load_config()
        config["sessions"][args.name] = {
            "server": args.server,
            "session_id": body["session_id"],
            "agent_token": body["agent_token"],
            "created_at": body.get("agent_token_expires_at"),
        }
        if args.make_default:
            config["default_session_name"] = args.name
        _save_config(config)
        logger.info('Saved session profile "%s" to %s', args.name, _config_path())
        body["saved_as"] = args.name
        body["config_path"] = str(_config_path())
    _print_json(body)
    return 0


def session_status(args: argparse.Namespace) -> int:
    session_id, agent_token = _resolve_credentials(args)
    logger.debug("Fetching session status: session_id=%s", session_id)
    try:
        response = httpx.get(
            f"{args.server}/api/sessions/{session_id}",
            headers={"Authorization": f"Bearer {agent_token}"},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise _http_error_to_cli_error(exc, action="status") from exc
    except httpx.RequestError as exc:
        raise _request_error_to_cli_error(exc, action="status") from exc

    _print_json(response.json())
    return 0


def send_command(args: argparse.Namespace) -> int:
    session_id, agent_token = _resolve_credentials(args)
    payload: dict[str, Any]
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            raise CliError(
                f"Invalid JSON for --payload: {exc.msg}",
                hint='Pass valid JSON, e.g. --payload \'{"url":"https://example.com"}\'.',
            ) from exc
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise CliError("Invalid --payload type", hint="Payload must be a JSON object.")

    request_id = args.request_id or uuid.uuid4().hex

    logger.info("Sending command=%s session_id=%s request_id=%s", args.command_type, session_id, request_id)
    try:
        response = httpx.post(
            f"{args.server}/api/sessions/{session_id}/command",
            headers={
                "Authorization": f"Bearer {agent_token}",
                "X-Request-ID": request_id,
            },
            json={"type": args.command_type, "payload": payload, "timeout_s": args.timeout_s},
            timeout=args.timeout_s + 10.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise _http_error_to_cli_error(exc, action=f"command {args.command_type}") from exc
    except httpx.RequestError as exc:
        raise _request_error_to_cli_error(exc, action=f"command {args.command_type}") from exc

    body = response.json()
    body["request_id"] = request_id
    _print_json(body)
    return 0


def observe(args: argparse.Namespace) -> int:
    args.command_type = "observe"
    args.payload = json.dumps({"max_nodes": args.max_nodes})
    return send_command(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser Bridge CLI")
    parser.add_argument("--server", default="http://127.0.0.1:8765", help="Server base URL")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-session", help="Create a new bridge session")
    create.add_argument(
        "--ws-base",
        default="ws://127.0.0.1:8765",
        help="Public websocket base URL for extension connection",
    )
    create.add_argument("--name", default="", help="Save session credentials under this local profile name")
    create.add_argument(
        "--make-default",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When --name is set, make this profile the default for future commands",
    )
    create.set_defaults(func=create_session)

    status = subparsers.add_parser("status", help="Show session status")
    status.add_argument("--session-id", default="")
    status.add_argument("--agent-token", default="")
    status.add_argument("--name", default="", help="Local saved profile name")
    status.set_defaults(func=session_status)

    command = subparsers.add_parser("command", help="Send raw command")
    command.add_argument("--session-id", default="")
    command.add_argument("--agent-token", default="")
    command.add_argument("--name", default="", help="Local saved profile name")
    command.add_argument("--type", dest="command_type", required=True)
    command.add_argument("--payload", default="{}", help="JSON payload string")
    command.add_argument("--timeout-s", type=float, default=20.0)
    command.add_argument("--request-id", default="", help="Optional idempotency key; auto-generated if omitted")
    command.set_defaults(func=send_command)

    observe_cmd = subparsers.add_parser("observe", help="Get simplified page snapshot")
    observe_cmd.add_argument("--session-id", default="")
    observe_cmd.add_argument("--agent-token", default="")
    observe_cmd.add_argument("--name", default="", help="Local saved profile name")
    observe_cmd.add_argument("--max-nodes", type=int, default=150)
    observe_cmd.add_argument("--timeout-s", type=float, default=20.0)
    observe_cmd.add_argument("--request-id", default="", help="Optional idempotency key; auto-generated if omitted")
    observe_cmd.set_defaults(func=observe)

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
    except Exception as exc:  # pragma: no cover - CLI safety net
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
