# browser-agent-bridge

WebSocket-only browser bridge for remotely controlling a local Chrome extension.

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
export BRIDGE_OPERATOR_TOKEN='change-me-strong-operator-token'
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

### 4) Operator CLI usage

```bash
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'change-me-strong-operator-token' list-clients
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'change-me-strong-operator-token' connect-status --instance-id local-instance --client-id chrome-main
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'change-me-strong-operator-token' ping-tab --instance-id local-instance --client-id chrome-main
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token 'change-me-strong-operator-token' observe --instance-id local-instance --client-id chrome-main
```

Raw command:

```bash
browser-bridge --server-ws-url ws://127.0.0.1:8765/ws/operator --token '...' \
  send-command --instance-id local-instance --client-id chrome-main \
  --type get_html --payload '{"max_chars":40000}'
```

## Security Hardening

- Use TLS in non-local deployments (`wss://`).
- Use strong static tokens or JWT secret.
- Optional command allowlist: `BRIDGE_COMMAND_ALLOWLIST=observe,ping_tab,get_html`.
- Optional allowed clients allowlist in static mode: `BRIDGE_ALLOWED_CLIENTS=instance1:client1,instance2:client2`.
- Request idempotency/replay guard is enforced by `request_id` dedup window.
- Max payload limit is enforced by `BRIDGE_MAX_MESSAGE_BYTES`.

## Deprecated HTTP Endpoints

Old session-based HTTP endpoints are deprecated and disabled by default:
- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `POST /api/sessions/{session_id}/command`

Behavior:
- default (`BRIDGE_ENABLE_HTTP_COMPAT=0`): returns `410 Gone` with migration hint.
- compatibility flag on: currently returns `501` stub in this build.

## Migration from HTTP Session Model

Old flow:
- create session over HTTP
- paste `session_id` + token into extension
- send commands over HTTP per session

New flow:
- extension directly authenticates to `/ws/client` with `instance_id` + `client_id` + token/JWT
- operator authenticates to `/ws/operator`
- commands routed over WS by `(instance_id, client_id)`

No session creation API is required.

## Testing

```bash
pytest -v
```

Coverage includes WS auth success/failure, command routing, disconnect handling, wrong target routing, CLI failure paths, and reconnect replacement behavior.

## License

MIT (see `LICENSE`).
