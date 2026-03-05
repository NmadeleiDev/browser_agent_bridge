# README Image + Positioning Copy

- [x] Fix broken README image path by adding a committed image asset under `docs/images/`.
- [x] Update README intro copy to explicitly position this project as a super fast alternative to traditional vision-based browser control systems.
- [x] Verify README renders image from repository path and mark checklist complete.

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

# Operator Token Hardening

- [x] Enforce `BRIDGE_OPERATOR_TOKEN` complexity policy at server startup (min length + mixed character classes).
- [x] Add tests for weak/strong operator token validation behavior.
- [x] Update README security notes for operator token complexity requirements.
- [x] Run tests and mark checklist complete.

# Extension Background Persistence

- [x] Confirm root cause of popup closing -> `Status: idle` regression in MV3 service worker lifecycle.
- [x] Persist extension runtime connection state/intention and restore it after worker restart.
- [x] Add periodic wake/reconnect mechanism (`chrome.alarms`) so bridge stays connected without popup open.
- [x] Validate extension behavior + run Python tests to ensure no backend regressions.

# Extension Tab Locking

- [x] Add persistent locked-tab state (`tabId/windowId`) in extension background runtime.
- [x] Route all command execution to locked tab when set (instead of active focused tab).
- [x] Add popup controls to lock current tab and unlock back to active-tab targeting.
- [x] Validate with JS syntax checks and Python test suite.

# Adaptive Post-Command Page-Load Wait

- [x] Add adaptive tab-load waiter in extension background with max wait cap (default 10s).
- [x] Apply adaptive waiting to commands that can trigger navigation (`navigate`, `click`, `type`), but return fast when tab is already complete.
- [x] Include wait diagnostics in command response (waited ms, completed vs timed out, final tab status).
- [x] Update README command docs to describe adaptive wait behavior and payload override.
- [x] Run test suite and mark checklist complete.

# Browser Bridge CLI Skill

- [x] Create `skills/` directory with a Browser Bridge CLI skill.
- [x] Document environment setup and dependency installation for local repo usage.
- [x] Document server spin-up flow (auth env vars + startup command).
- [x] Document extension connection steps and required popup values.
- [x] Document CLI command usage (status/list/observe/ping/send-command with examples).

# Human-like Typing in Extension

- [x] Define `type` command behavior for human-like input (event sequence, delays, clear-vs-append policy).
- [x] Implement character-by-character typing in `extension/content.js` with safe defaults and payload overrides.
- [x] Keep compatibility for existing workflows (same `type` command shape still works).
- [x] Update README command docs with new `type` payload options.
- [x] Run regression checks (`pytest -v` + JS syntax check) and mark checklist complete.
