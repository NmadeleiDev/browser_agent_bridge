# Open Source + PyPI (pipx) Release Plan

- [x] Add packaging metadata (`pyproject.toml`) with runtime/dev extras and console scripts for server + CLI.
- [x] Add package version surface in `browser_bridge/__init__.py`.
- [x] Add repository hygiene files: `.gitignore`, `CONTRIBUTING.md`, GitHub Actions workflows for CI and trusted publishing.
- [x] Update `README.md` for open-source usage and publishing (pipx install, source install, extension flow, security notes).
- [x] Validate with tests and package build (`pytest`, `python -m build`, `twine check`) and update this checklist.

# Reliability + UX Improvements

- [ ] Add content-script auto-recovery in extension background worker (inject + retry when tab receiver is missing).
- [ ] Add a tab-readiness probe command (`ping_tab`) to distinguish websocket-connected vs tab-command-ready.
- [ ] Improve CLI `--server` ergonomics to accept global option after subcommand and add tests.
- [ ] Update README with probe command and new CLI option behavior.
- [ ] Run full tests and mark checklist complete.
- [x] Add content-script auto-recovery in extension background worker (inject + retry when tab receiver is missing).
- [x] Add a tab-readiness probe command (`ping_tab`) to distinguish websocket-connected vs tab-command-ready.
- [x] Improve CLI `--server` ergonomics to accept global option after subcommand and add tests.
- [x] Update README with probe command and new CLI option behavior.
- [x] Run full tests and mark checklist complete.

# Secret Bootstrap Improvements

- [x] Add local secret manager module (read/write/generate + default-secret bootstrap logic).
- [x] Add CLI command `setup-secret` to create server secret before first use.
- [x] Auto-bootstrap local secret in server startup when `BRIDGE_JWT_SECRET` is default.
- [x] Update README for first-run secret setup and env vars.
- [x] Run tests and smoke-check `setup-secret`.

# WS-only Architecture Migration

- [ ] Replace server with WebSocket-first client/operator protocol and multi-client routing.
- [ ] Implement robust WS auth (static token or JWT), secure production defaults, allowlist, payload/timeout/replay guards.
- [ ] Deprecate old HTTP session/command endpoints behind compatibility feature flag disabled by default.
- [ ] Refactor CLI to WS-only operator model: connect-status, list-clients, send-command, observe, ping-tab.
- [ ] Refactor extension popup/background to WS auth model (ws URL + instance/client IDs + token, no HTTP sessions).
- [ ] Add/replace tests for WS auth, routing, disconnect handling, wrong-target errors, CLI failure paths, reconnect.
- [ ] Rewrite README with WS-only architecture, migration notes, threat model, and prod config.
- [ ] Run full test suite and finalize migration notes.
- [x] Replace server with WebSocket-first client/operator protocol and multi-client routing.
- [x] Implement robust WS auth (static token or JWT), secure production defaults, allowlist, payload/timeout/replay guards.
- [x] Deprecate old HTTP session/command endpoints behind compatibility feature flag disabled by default.
- [x] Refactor CLI to WS-only operator model: connect-status, list-clients, send-command, observe, ping-tab.
- [x] Refactor extension popup/background to WS auth model (ws URL + instance/client IDs + token, no HTTP sessions).
- [x] Add/replace tests for WS auth, routing, disconnect handling, wrong-target errors, CLI failure paths, reconnect.
- [x] Rewrite README with WS-only architecture, migration notes, threat model, and prod config.
- [x] Run full test suite and finalize migration notes.
