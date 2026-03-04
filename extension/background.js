const DEFAULTS = {
  serverBaseUrl: "",
  wsUrl: "",
  sessionId: "",
  extensionToken: ""
};

let ws = null;
let wsConnected = false;
let reconnectTimer = null;
let shouldReconnect = false;
let lastEvent = "idle";

async function loadConfig() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return {
    serverBaseUrl: String(stored.serverBaseUrl || ""),
    wsUrl: String(stored.wsUrl || ""),
    sessionId: String(stored.sessionId || ""),
    extensionToken: String(stored.extensionToken || "")
  };
}

async function saveConfig(config) {
  await chrome.storage.local.set(config);
}

function trimSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function toWsScheme(base) {
  if (base.startsWith("wss://") || base.startsWith("ws://")) {
    return base;
  }
  if (base.startsWith("https://")) {
    return `wss://${base.slice("https://".length)}`;
  }
  if (base.startsWith("http://")) {
    return `ws://${base.slice("http://".length)}`;
  }
  throw new Error("serverBaseUrl must start with https://, http://, wss://, or ws://");
}

function deriveWsUrl(config) {
  const explicit = trimSlash(config.wsUrl);
  if (explicit) {
    return explicit;
  }

  const base = trimSlash(config.serverBaseUrl);
  const sessionId = String(config.sessionId || "").trim();
  const token = String(config.extensionToken || "").trim();

  if (!base) {
    throw new Error("Configure serverBaseUrl or wsUrl");
  }
  if (!sessionId) {
    throw new Error("sessionId is required");
  }
  if (!token) {
    throw new Error("extensionToken is required");
  }

  const wsBase = toWsScheme(base);
  return `${wsBase}/ws/extension/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(token)}`;
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

async function activeTabId() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab || typeof tab.id !== "number") {
    throw new Error("No active tab available");
  }
  return tab.id;
}

async function sendToContent(type, payload) {
  const tabId = await activeTabId();
  const response = await chrome.tabs.sendMessage(tabId, { type, payload });
  if (!response?.ok) {
    throw new Error(response?.error || "Content script command failed");
  }
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

function stopWs() {
  shouldReconnect = false;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
  wsConnected = false;
  lastEvent = "disconnected";
  emitStatus();
}

function scheduleReconnect() {
  if (!shouldReconnect || reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    try {
      await connectWs();
    } catch {
      scheduleReconnect();
    }
  }, 2000);
}

async function connectWs(configOverride = null) {
  const config = configOverride || await loadConfig();
  const wsUrl = deriveWsUrl(config);

  stopWs();
  shouldReconnect = true;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    wsConnected = true;
    lastEvent = "connected";
    emitStatus();
  };

  ws.onclose = () => {
    wsConnected = false;
    lastEvent = "socket-closed";
    emitStatus();
    scheduleReconnect();
  };

  ws.onerror = () => {
    lastEvent = "socket-error";
    emitStatus();
  };

  ws.onmessage = async (evt) => {
    try {
      const parsed = JSON.parse(evt.data);
      if (parsed.kind === "pong") {
        return;
      }
      if (parsed.kind !== "command") {
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

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const run = async () => {
    switch (message?.kind) {
      case "save-config":
        await saveConfig({
          serverBaseUrl: String(message.serverBaseUrl || ""),
          wsUrl: String(message.wsUrl || ""),
          sessionId: String(message.sessionId || ""),
          extensionToken: String(message.extensionToken || "")
        });
        return { ok: true };
      case "load-config": {
        const config = await loadConfig();
        let effectiveWsUrl = "";
        try {
          effectiveWsUrl = deriveWsUrl(config);
        } catch {
          effectiveWsUrl = "";
        }
        return {
          ok: true,
          config,
          effectiveWsUrl,
          connected: wsConnected,
          lastEvent
        };
      }
      case "connect":
        if (
          typeof message.serverBaseUrl === "string" ||
          typeof message.wsUrl === "string" ||
          typeof message.sessionId === "string" ||
          typeof message.extensionToken === "string"
        ) {
          const cfg = {
            serverBaseUrl: String(message.serverBaseUrl || ""),
            wsUrl: String(message.wsUrl || ""),
            sessionId: String(message.sessionId || ""),
            extensionToken: String(message.extensionToken || "")
          };
          await saveConfig(cfg);
          await connectWs(cfg);
          return { ok: true, connected: wsConnected, lastEvent };
        }
        await connectWs();
        return { ok: true, connected: wsConnected, lastEvent };
      case "disconnect":
        stopWs();
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
  await saveConfig(current);
});
