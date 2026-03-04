const DEFAULTS = {
  wsUrl: "",
  instanceId: "",
  clientId: "",
  authToken: "",
  desiredConnected: false,
  lastEvent: "idle",
  lockedTabId: null,
  lockedWindowId: null
};

const KEEPALIVE_ALARM = "bridge-keepalive";
const KEEPALIVE_MINUTES = 1;
const DEFAULT_POST_COMMAND_WAIT_MS = 10000;
const MAX_POST_COMMAND_WAIT_MS = 10000;
const LOAD_STATUS_POLL_MS = 150;

let ws = null;
let wsConnected = false;
let reconnectTimer = null;
let shouldReconnect = false;
let desiredConnected = false;
let lastEvent = "idle";
let activeConfig = null;
let lockedTabId = null;
let lockedWindowId = null;

async function loadConfig() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return {
    wsUrl: String(stored.wsUrl || ""),
    instanceId: String(stored.instanceId || ""),
    clientId: String(stored.clientId || ""),
    authToken: String(stored.authToken || "")
  };
}

async function saveConfig(config) {
  await chrome.storage.local.set(config);
}

function emitStatus() {
  chrome.runtime.sendMessage({
    kind: "status",
    status: {
      connected: wsConnected,
      lastEvent,
      lock: lockState()
    }
  }).catch(() => {});
}

async function persistRuntimeState() {
  await chrome.storage.local.set({
    desiredConnected,
    lastEvent,
    lockedTabId,
    lockedWindowId
  });
}

function updateStatus(event, connected = wsConnected) {
  wsConnected = connected;
  lastEvent = event;
  emitStatus();
  persistRuntimeState().catch(() => {});
}

async function activeTabId() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab || typeof tab.id !== "number") {
    throw new Error("No active tab available");
  }
  return tab.id;
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab || typeof tab.id !== "number" || typeof tab.windowId !== "number") {
    throw new Error("No active tab available");
  }
  return tab;
}

function lockState() {
  return {
    enabled: typeof lockedTabId === "number",
    tabId: lockedTabId,
    windowId: lockedWindowId
  };
}

async function lockCurrentTab() {
  const tab = await activeTab();
  lockedTabId = tab.id;
  lockedWindowId = tab.windowId;
  await persistRuntimeState();
  return lockState();
}

async function unlockTab() {
  lockedTabId = null;
  lockedWindowId = null;
  await persistRuntimeState();
  return lockState();
}

async function targetTabId() {
  if (typeof lockedTabId !== "number") {
    return activeTabId();
  }
  try {
    const tab = await chrome.tabs.get(lockedTabId);
    if (typeof lockedWindowId === "number" && tab.windowId !== lockedWindowId) {
      throw new Error("Locked tab window changed");
    }
    return tab.id;
  } catch {
    await unlockTab();
    updateStatus("lock-lost", wsConnected);
    throw new Error("Locked tab is no longer available. Re-lock a tab in the extension popup.");
  }
}

function isReceiverMissingError(err) {
  const message = String(err?.message || err || "");
  return message.includes("Receiving end does not exist");
}

function waitMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function injectContentScript(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"]
  });
}

function parseLoadWaitConfig(payload) {
  const waitFlag = payload?.wait_for_load;
  const requested = Number(payload?.wait_for_load_ms ?? DEFAULT_POST_COMMAND_WAIT_MS);
  const boundedWaitMs = Number.isFinite(requested)
    ? Math.max(0, Math.min(Math.round(requested), MAX_POST_COMMAND_WAIT_MS))
    : DEFAULT_POST_COMMAND_WAIT_MS;

  return {
    enabled: waitFlag !== false && boundedWaitMs > 0,
    maxWaitMs: boundedWaitMs
  };
}

async function waitForTabComplete(tabId, maxWaitMs) {
  const startedAt = Date.now();
  let lastStatus = "unknown";

  while (true) {
    const tab = await chrome.tabs.get(tabId);
    lastStatus = String(tab?.status || "unknown");
    const elapsedMs = Date.now() - startedAt;

    if (lastStatus === "complete") {
      return {
        waited_ms: elapsedMs,
        completed: true,
        timed_out: false,
        final_status: lastStatus
      };
    }
    if (elapsedMs >= maxWaitMs) {
      return {
        waited_ms: elapsedMs,
        completed: false,
        timed_out: true,
        final_status: lastStatus
      };
    }
    await waitMs(Math.min(LOAD_STATUS_POLL_MS, maxWaitMs - elapsedMs));
  }
}

async function maybeWaitForLoad(tabId, payload) {
  const config = parseLoadWaitConfig(payload);
  if (!config.enabled) {
    const tab = await chrome.tabs.get(tabId);
    return {
      waited_ms: 0,
      completed: String(tab?.status || "unknown") === "complete",
      timed_out: false,
      final_status: String(tab?.status || "unknown"),
      enabled: false,
      max_wait_ms: config.maxWaitMs
    };
  }

  const waited = await waitForTabComplete(tabId, config.maxWaitMs);
  return {
    ...waited,
    enabled: true,
    max_wait_ms: config.maxWaitMs
  };
}

async function sendToContent(type, payload, tabIdOverride = null) {
  const tabId = typeof tabIdOverride === "number" ? tabIdOverride : await targetTabId();
  let response;
  try {
    response = await chrome.tabs.sendMessage(tabId, { type, payload });
  } catch (err) {
    if (!isReceiverMissingError(err)) {
      throw err;
    }
    updateStatus("tab-recovering");
    await injectContentScript(tabId);
    await waitMs(80);
    response = await chrome.tabs.sendMessage(tabId, { type, payload });
  }
  if (!response?.ok) {
    throw new Error(response?.error || "Content script command failed");
  }
  updateStatus("tab-ready");
  return response.result || {};
}

async function executeCommand(command) {
  const type = command.type;
  const payload = command.payload || {};

  switch (type) {
    case "observe":
    case "scroll":
    case "get_html":
      return sendToContent(type, payload);
    case "click":
    case "type": {
      const tabId = await targetTabId();
      const result = await sendToContent(type, payload, tabId);
      return {
        ...result,
        load_wait: await maybeWaitForLoad(tabId, payload)
      };
    }
    case "ping_tab":
      return sendToContent("ping", payload);
    case "navigate": {
      const tabId = await targetTabId();
      const url = String(payload.url || "");
      if (!url) {
        throw new Error("payload.url is required");
      }
      await chrome.tabs.update(tabId, { url });
      return {
        navigated: true,
        url,
        load_wait: await maybeWaitForLoad(tabId, payload)
      };
    }
    case "screenshot": {
      const tabId = await targetTabId();
      const tab = await chrome.tabs.get(tabId);
      if (!tab.active) {
        throw new Error("Locked tab is not visible. Activate that tab before screenshot.");
      }
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
      const maxChars = Number(payload.max_chars || 500000);
      return {
        format: "png-data-url",
        truncated: dataUrl.length > maxChars,
        image: dataUrl.slice(0, maxChars)
      };
    }
    default:
      throw new Error(`Unsupported command type: ${type}`);
  }
}

function closeSocket() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
}

async function disconnectWs() {
  shouldReconnect = false;
  desiredConnected = false;
  closeSocket();
  updateStatus("disconnected", false);
  await persistRuntimeState();
}

function scheduleReconnect() {
  if (!shouldReconnect || !desiredConnected || reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    try {
      await connectWs(activeConfig);
    } catch {
      scheduleReconnect();
    }
  }, 2000);
}

function validateConfig(config) {
  if (!config.wsUrl.trim()) {
    throw new Error("wsUrl is required");
  }
  if (!config.instanceId.trim()) {
    throw new Error("instanceId is required");
  }
  if (!config.clientId.trim()) {
    throw new Error("clientId is required");
  }
  if (!config.authToken.trim()) {
    throw new Error("authToken is required");
  }
}

async function connectWs(configOverride = null) {
  const config = configOverride || await loadConfig();
  validateConfig(config);

  closeSocket();
  shouldReconnect = true;
  desiredConnected = true;
  activeConfig = config;
  await persistRuntimeState();

  ws = new WebSocket(config.wsUrl.trim());

  ws.onopen = () => {
    updateStatus("authenticating", false);
    ws.send(JSON.stringify({
      kind: "auth",
      instance_id: config.instanceId,
      client_id: config.clientId,
      token: config.authToken
    }));
  };

  ws.onclose = () => {
    updateStatus("socket-closed", false);
    scheduleReconnect();
  };

  ws.onerror = () => {
    updateStatus("socket-error");
  };

  ws.onmessage = async (evt) => {
    try {
      const parsed = JSON.parse(evt.data);
      const kind = parsed.kind;

      if (kind === "auth_ok") {
        updateStatus("connected", true);
        return;
      }

      if (kind === "auth_error") {
        desiredConnected = false;
        shouldReconnect = false;
        updateStatus(`auth-error:${parsed.code || "AUTH_FAILED"}`, false);
        persistRuntimeState().catch(() => {});
        ws.close();
        return;
      }

      if (kind === "pong") {
        return;
      }

      if (kind !== "command") {
        return;
      }

      const commandId = parsed.command_id;
      if (!commandId) {
        return;
      }

      try {
        const result = await executeCommand(parsed);
        ws.send(JSON.stringify({
          kind: "result",
          command_id: commandId,
          ok: true,
          result
        }));
      } catch (err) {
        ws.send(JSON.stringify({
          kind: "result",
          command_id: commandId,
          ok: false,
          error: String(err?.message || err)
        }));
      }
    } catch {
      // Ignore malformed payloads.
    }
  };
}

async function ensureKeepaliveAlarm() {
  const existing = await chrome.alarms.get(KEEPALIVE_ALARM);
  if (!existing) {
    chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: KEEPALIVE_MINUTES });
  }
}

async function restoreRuntimeState() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  desiredConnected = Boolean(stored.desiredConnected);
  lastEvent = String(stored.lastEvent || "idle");
  lockedTabId = typeof stored.lockedTabId === "number" ? stored.lockedTabId : null;
  lockedWindowId = typeof stored.lockedWindowId === "number" ? stored.lockedWindowId : null;
  activeConfig = {
    wsUrl: String(stored.wsUrl || ""),
    instanceId: String(stored.instanceId || ""),
    clientId: String(stored.clientId || ""),
    authToken: String(stored.authToken || "")
  };
}

async function bootstrap() {
  await ensureKeepaliveAlarm();
  await restoreRuntimeState();
  if (desiredConnected) {
    try {
      await connectWs(activeConfig);
    } catch {
      updateStatus("reconnect-waiting", false);
      scheduleReconnect();
    }
  } else {
    emitStatus();
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const run = async () => {
    switch (message?.kind) {
      case "save-config":
        await saveConfig({
          wsUrl: String(message.wsUrl || ""),
          instanceId: String(message.instanceId || ""),
          clientId: String(message.clientId || ""),
          authToken: String(message.authToken || "")
        });
        return { ok: true };
      case "load-config": {
        const config = await loadConfig();
        return {
          ok: true,
          config,
          connected: wsConnected,
          lastEvent,
          lock: lockState()
        };
      }
      case "connect": {
        const cfg = {
          wsUrl: String(message.wsUrl || ""),
          instanceId: String(message.instanceId || ""),
          clientId: String(message.clientId || ""),
          authToken: String(message.authToken || "")
        };
        await saveConfig(cfg);
        await connectWs(cfg);
        return { ok: true, connected: wsConnected, lastEvent };
      }
      case "disconnect":
        await disconnectWs();
        return { ok: true, connected: false, lastEvent };
      case "status":
        return { ok: true, connected: wsConnected, lastEvent, lock: lockState() };
      case "lock-current-tab":
        return { ok: true, lock: await lockCurrentTab() };
      case "unlock-tab":
        return { ok: true, lock: await unlockTab() };
      default:
        return { ok: false, error: "Unknown message kind" };
    }
  };

  run()
    .then((result) => sendResponse(result))
    .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));

  return true;
});

chrome.runtime.onInstalled.addListener(async () => {
  const current = await loadConfig();
  await saveConfig({
    ...current,
    desiredConnected,
    lastEvent
  });
  await ensureKeepaliveAlarm();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId !== lockedTabId) {
    return;
  }
  unlockTab().catch(() => {});
  updateStatus("lock-lost", wsConnected);
});

chrome.runtime.onStartup.addListener(() => {
  bootstrap().catch(() => {});
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm?.name !== KEEPALIVE_ALARM) {
    return;
  }
  if (!desiredConnected || wsConnected) {
    return;
  }
  connectWs(activeConfig).catch(() => {
    updateStatus("reconnect-waiting", false);
    scheduleReconnect();
  });
});

bootstrap().catch(() => {});
