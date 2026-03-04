const DEFAULTS = {
  wsUrl: "",
  instanceId: "",
  clientId: "",
  authToken: "",
  desiredConnected: false,
  lastEvent: "idle"
};

const KEEPALIVE_ALARM = "bridge-keepalive";
const KEEPALIVE_MINUTES = 1;

let ws = null;
let wsConnected = false;
let reconnectTimer = null;
let shouldReconnect = false;
let desiredConnected = false;
let lastEvent = "idle";
let activeConfig = null;

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
      lastEvent
    }
  }).catch(() => {});
}

async function persistRuntimeState() {
  await chrome.storage.local.set({
    desiredConnected,
    lastEvent
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

async function sendToContent(type, payload) {
  const tabId = await activeTabId();
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
    case "click":
    case "type":
    case "scroll":
    case "get_html":
      return sendToContent(type, payload);
    case "ping_tab":
      return sendToContent("ping", payload);
    case "navigate": {
      const tabId = await activeTabId();
      const url = String(payload.url || "");
      if (!url) {
        throw new Error("payload.url is required");
      }
      await chrome.tabs.update(tabId, { url });
      return { navigated: true, url };
    }
    case "screenshot": {
      const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: "png" });
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
          lastEvent
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
        return { ok: true, connected: wsConnected, lastEvent };
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
