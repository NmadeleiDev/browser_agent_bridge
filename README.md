# browser-agent-bridge

Browser Bridge server + CLI for controlling a Chrome extension over WebSocket.

This repository contains:

- Python package: `browser_bridge/` (server + CLI)
- Chrome extension: `extension/` (unpacked dev-mode install)

## Features

- Session-based auth with separate `agent_token` and `extension_token`
- FastAPI server with HTTP command API + extension WebSocket endpoint
- CLI for session creation, status checks, and command execution
- Replay protection via `X-Request-ID`

## Install (Recommended: pipx)

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install browser-agent-bridge
```

Verify:

```bash
browser-bridge --version
browser-bridge-server --help
```

Upgrade:

```bash
pipx upgrade browser-agent-bridge
```

## Install From Source

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick Start

### 1) Start server

```bash
browser-bridge-server
```

Server defaults to `http://127.0.0.1:8765`.

### 2) Create session

```bash
browser-bridge create-session --name local
```

Example output:

```json
{
  "agent_token": "...",
  "agent_token_expires_at": "...",
  "extension_token": "...",
  "extension_token_expires_at": "...",
  "saved_as": "local",
  "session_id": "...",
  "ws_url": "ws://127.0.0.1:8765/ws/extension/...?..."
}
```

### 3) Load extension (unpacked)

1. Open `chrome://extensions`.
2. Enable `Developer mode`.
3. Click `Load unpacked`.
4. Select the `extension/` folder from this repository.
5. Open extension popup and fill:
   - `Bridge Server Base URL`: `http://127.0.0.1:8765`
   - `Session ID`: the `session_id` from CLI
   - `Extension Token`: the `extension_token` from CLI
6. Click `Save`, then `Connect`.

### 4) Verify roundtrip

```bash
browser-bridge status --name local
browser-bridge observe --name local
```

Optional raw command examples:

```bash
browser-bridge command --name local --type get_html --payload '{"max_chars":50000}'
browser-bridge command --name local --type click --payload '{"selector":"button"}'
```

## Server Configuration

Environment variables:

- `BRIDGE_JWT_SECRET` (required for non-dev usage)
- `BRIDGE_AGENT_TOKEN_TTL_S` (default: `3600`)
- `BRIDGE_EXTENSION_TOKEN_TTL_S` (default: `86400`)
- `BRIDGE_ALLOWED_ORIGIN_PREFIXES` (comma-separated origin prefixes)

## Security Notes

- Prototype is development-oriented.
- Tokens are sensitive. Do not share them.
- For non-local deployments, use `https://` and `wss://`.
- Set a strong `BRIDGE_JWT_SECRET` for any non-local usage.

## Testing

```bash
pytest -v
```

## Build

```bash
python -m build
python -m twine check dist/*
```

## CI and Publishing

GitHub Actions workflows:

- `.github/workflows/ci.yml`: tests + package checks
- `.github/workflows/publish.yml`: publishes to PyPI on tag push (`v*`)

### PyPI trusted publishing setup

1. Create project `browser-agent-bridge` on PyPI.
2. Add Trusted Publisher in PyPI settings:
   - Owner: your GitHub org/user
   - Repository: this repository
   - Workflow: `publish.yml`
   - Environment: `pypi`
3. In GitHub settings, create environment `pypi` (optional protection rules).

### Release

```bash
pytest -v
python -m build
python -m twine check dist/*
git tag v0.1.0
git push origin v0.1.0
```

Tag push triggers the publish workflow.

## License

MIT (see `LICENSE`).
