# browser-agent-bridge

WebSocket-only browser bridge for remotely controlling a local Chrome extension.

## Why This Exists

Traditional browser relays often rely on LLM vision to understand web pages at each step. In practice, that approach is:

1. Expensive: it consumes many tokens to repeatedly analyze visual page state.
2. Slow: repeated visual analysis adds latency at every interaction step.
3. Error-prone: visual perception includes noise that is less relevant than structured HTML for deterministic control.

This project exists as an HTML-first relay: the browser-side extension exposes structured observations and preprocessed HTML, so remote agents can interact with websites with lower cost, lower latency, and more reliable control.

## Architecture (WS-only)

```text
Operator CLI (remote/local)
    |
    |  ws(s)://.../ws/operator   (auth)
    v
Bridge Server
    ^
    |  ws(s)://.../ws/client     (auth)
    |
Chrome Extension (local browser)
    |
    +-- content script commands: observe/click/type/get_html/ping_tab/etc.
```

The extension connects outbound to server. Operator sends commands through server to a specific `(instance_id, client_id)`.

## Protocol

### Client -> Server
- `auth`: `{kind, instance_id, client_id, token}`
- `result`: `{kind, command_id, ok, result|error}`
- `ping`

### Server -> Client
- `auth_ok` / `auth_error`
- `command`: `{kind, command_id, type, payload, request_id, sent_at}`
- `pong`

### Operator -> Server
- `auth`: `{kind, token}`
- `list_clients`
- `connect_status`: `{kind, instance_id, client_id}`
- `send_command`: `{kind, instance_id, client_id, type, payload, timeout_s, request_id}`
- `ping`

### Server -> Operator
- `auth_ok` / `auth_error`
- `clients`
- `connect_status`
- `command_result`
- `pong`

## Auth Modes

Set `BRIDGE_AUTH_MODE`:

- `static` (default): compare token against `BRIDGE_SHARED_TOKEN` (for clients) and `BRIDGE_OPERATOR_TOKEN` (for operator; defaults to shared token).
  - `BRIDGE_OPERATOR_TOKEN` must be at least 16 chars and include lowercase, uppercase, digit, and symbol.
- `jwt`: validate JWT with `BRIDGE_JWT_SECRET`/`BRIDGE_JWT_ALG`.
  - Client JWT should include matching `instance_id` and `client_id` claims.
  - Operator JWT should include `role=operator`.

### Production safety

- `BRIDGE_ENV=production` enforces strong auth config:
  - static mode: `BRIDGE_SHARED_TOKEN` must not be empty/dev default.
  - jwt mode: `BRIDGE_JWT_SECRET` must not be default.

## Install (pipx recommended)

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install browser-agent-bridge
```

## Quick Start

### 1) (Optional) Generate local JWT secret file

```bash
browser-bridge setup-secret
```

If `BRIDGE_AUTH_MODE=jwt` and `BRIDGE_JWT_SECRET` is still default, server startup auto-loads/creates local secret file (`~/.browser_bridge/jwt_secret` or `BRIDGE_JWT_SECRET_FILE`).

### 2) Start server

```bash
# static mode example
export BRIDGE_AUTH_MODE=static
export BRIDGE_SHARED_TOKEN='change-me-strong-token'
export BRIDGE_OPERATOR_TOKEN='Str0ng!Operator#42'
browser-bridge-server
```

### 3) Load extension

1. Open `chrome://extensions`
2. Enable Developer mode
3. Load unpacked `extension/`
4. In popup fill:
   - `Bridge Server WS URL`: `ws://127.0.0.1:8765/ws/client` (or `wss://.../ws/client`)
   - `Instance ID`: e.g. `local-instance`
   - `Client ID`: e.g. `chrome-main`
   - `Auth Token / JWT`: client token
5. Save + Connect

Connected tab preview:

![Connected tab preview](docs/images/connected-tab-preview.png)

### 4) Operator CLI usage

```bash
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'Str0ng!Operator#42' list-clients
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'Str0ng!Operator#42' connect-status --instance-id local-instance --client-id chrome-main
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'Str0ng!Operator#42' ping-tab --instance-id local-instance --client-id chrome-main
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'Str0ng!Operator#42' observe --instance-id local-instance --client-id chrome-main
```

Raw command:

```bash
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token '...' \
  send-command --instance-id local-instance --client-id chrome-main \
  --type get_html --payload '{"max_chars":40000}'
```

## Security Hardening

- Use TLS in non-local deployments (`wss://`).
- Use strong static tokens or JWT secret. Operator static token must include mixed-case letters, digits, symbols, and be 16+ chars.
- Optional command allowlist: `BRIDGE_COMMAND_ALLOWLIST=observe,ping_tab,get_html`.
- Optional allowed clients allowlist in static mode: `BRIDGE_ALLOWED_CLIENTS=instance1:client1,instance2:client2`.
- Request idempotency/replay guard is enforced by `request_id` dedup window.
- Max payload limit is enforced by `BRIDGE_MAX_MESSAGE_BYTES`.

## Testing

```bash
pytest -v
```

Coverage includes WS auth success/failure, command routing, disconnect handling, wrong target routing, CLI failure paths, and reconnect replacement behavior.

## Contributing

Contributions are very welcome.

If you want to help, great places to start are:
- bug fixes and reliability improvements
- new command handlers and protocol hardening
- better docs and examples
- tests for real-world edge cases

Quick contributor workflow:
1. Fork the repo and create a focused branch.
2. Run tests locally (`pytest -v`).
3. Open a PR with a clear description, motivation, and test notes.

For detailed guidelines, see [CONTRIBUTING.md](/Users/grigorijpotemkin/pets/browser_agent_bridge/CONTRIBUTING.md).

If you have ideas but no patch yet, opening an issue/discussion is also appreciated.

## License

MIT (see `LICENSE`).

---

Created by the creator of [openclaw-setup.me](https://openclaw-setup.me/).
