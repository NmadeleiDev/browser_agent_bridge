# AGENTS.md - Browser Bridge Setup Runbook

This file tells an autonomous coding agent exactly how to set up and operate the Browser Bridge prototype, and what to ask/say to the human for steps that require browser UI interaction.

## Goal

Bring up the local Python Browser Bridge server + CLI, have the human load the unpacked Chrome extension, connect extension -> server with session credentials, and verify command roundtrip.

## Project Layout

- Python package: `browser_bridge/browser_bridge/`
- Chrome extension: `browser_bridge/extension/`
- Tests: `browser_bridge/tests/`
- Requirements: `browser_bridge/requirements.txt`

## Agent Workflow (Strict Order)

1. Create venv and install dependencies.
2. Start server.
3. Create a session and capture credentials.
4. Instruct human to load unpacked extension and paste server URL + credentials.
5. Instruct human to connect extension.
6. Verify connection with CLI status + observe command.
7. If failing, run targeted diagnostics and explain next action.

## Commands the Agent Should Run

From repo root:

```bash
cd browser_bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m browser_bridge.server
```

Open a second shell (or second terminal tab):

```bash
cd browser_bridge
source .venv/bin/activate
python -m browser_bridge.cli create-session --name local
```

The output includes:

- `session_id`
- `agent_token`
- `extension_token`
- `ws_url`

After human connects extension, verify:

```bash
python -m browser_bridge.cli status --name local
python -m browser_bridge.cli observe --name local
```

Optional deeper check:

```bash
python -m browser_bridge.cli command --name local --type get_html --payload '{"max_chars":40000}'
```

## Exactly What the Agent Should Tell the Human

Use this message template verbatim (fill values):

1. "Open `chrome://extensions` in Chrome."
2. "Enable `Developer mode` (top-right)."
3. "Click `Load unpacked` and select this folder: `<ABS_PATH_TO_REPO>/browser_bridge/extension`."
4. "Open the Browser Bridge extension popup."
5. "Paste these values:"
   - "Bridge Server Base URL: `<SERVER_BASE_URL>`"
   - "Session ID: `<SESSION_ID>`"
   - "Extension Token: `<EXTENSION_TOKEN>`"
6. "Click `Save`, then click `Connect`."
7. "Tell me when popup status shows `connected` so I can run verification commands."

## What the Agent Should Say on Success

After CLI `status` indicates connected and `observe` returns page data:

"Setup is complete. The extension is connected to your local Browser Bridge server and responding to agent commands. I verified with `status` and `observe` roundtrip."

## Troubleshooting Script the Agent Should Use

If `status` shows disconnected:

1. Ask human: "Is the extension popup still showing `connected`?"
2. Ask human to click `Connect` again.
3. Re-run `status`.
4. If still failing, create a new session and repeat credential paste.

If extension cannot connect at all:

1. Confirm server process is running on `http://127.0.0.1:8765`.
2. Confirm `Bridge Server Base URL` host/port is reachable and unchanged.
3. Confirm token is not expired (create fresh session if needed).
4. Confirm extension was loaded from `browser_bridge/extension` (not repo root).

## Remote Ingress Setup (K8s instances)

When Browser Bridge runs inside an instance pod, configure your platform networking so that:

1. Public host routes to the Browser Bridge service port.
2. WebSocket upgrades are enabled end-to-end.
3. NetworkPolicy/firewall allows ingress-controller traffic to the bridge port.
4. If exposed over the internet, TLS certificate is valid for the public host.

Then tell human to set:

- `Bridge Server Base URL = http://<host>:<port>` (local/private) or `https://<ingress-host>` (internet-facing)
- `Session ID = <SESSION_ID>`
- `Extension Token = <EXTENSION_TOKEN>`

`browser_bridge` itself does not assume any specific cluster, DNS zone, or ingress controller.

If command times out:

1. Ensure active Chrome tab is a normal web page (not restricted pages like `chrome://*`).
2. Re-run `observe`.
3. If needed, refresh the active tab and retry.

## Security Notes the Agent Must Mention to Human

- This prototype is local/dev oriented.
- Tokens are sensitive; do not share them.
- For non-local usage, prefer TLS (`https/wss`) and set `BRIDGE_JWT_SECRET` to a strong secret.

## Regression/Test Gate Before Declaring Done

The agent should run:

```bash
cd browser_bridge
source .venv/bin/activate
python -m pytest -v
```

Only declare completion when tests pass and a live `observe` roundtrip succeeds.
