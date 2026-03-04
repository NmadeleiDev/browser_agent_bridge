const serverBaseUrlInput = document.getElementById("serverBaseUrl");
const wsUrlInput = document.getElementById("wsUrl");
const sessionIdInput = document.getElementById("sessionId");
const extensionTokenInput = document.getElementById("extensionToken");
const statusEl = document.getElementById("status");
const effectiveWsEl = document.getElementById("effectiveWs");

const saveBtn = document.getElementById("saveBtn");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");

function setStatus(text) {
  statusEl.textContent = `Status: ${text}`;
}

function setEffectiveWs(url) {
  effectiveWsEl.textContent = `Effective WS: ${url || "-"}`;
}

async function callBg(message) {
  return chrome.runtime.sendMessage(message);
}

async function loadState() {
  const response = await callBg({ kind: "load-config" });
  if (!response?.ok) {
    setStatus(response?.error || "failed to load config");
    return;
  }

  const config = response.config;
  serverBaseUrlInput.value = config.serverBaseUrl || "";
  wsUrlInput.value = config.wsUrl || "";
  sessionIdInput.value = config.sessionId || "";
  extensionTokenInput.value = config.extensionToken || "";
  setEffectiveWs(response.effectiveWsUrl || "");
  setStatus(response.connected ? `connected (${response.lastEvent})` : response.lastEvent);
}

async function saveConfig() {
  const response = await callBg({
    kind: "save-config",
    serverBaseUrl: serverBaseUrlInput.value.trim(),
    wsUrl: wsUrlInput.value.trim(),
    sessionId: sessionIdInput.value.trim(),
    extensionToken: extensionTokenInput.value.trim()
  });
  if (!response?.ok) {
    setStatus(response?.error || "save failed");
    return;
  }
  await loadState();
  setStatus("config saved");
}

async function connect() {
  const response = await callBg({
    kind: "connect",
    serverBaseUrl: serverBaseUrlInput.value.trim(),
    wsUrl: wsUrlInput.value.trim(),
    sessionId: sessionIdInput.value.trim(),
    extensionToken: extensionTokenInput.value.trim()
  });
  if (!response?.ok) {
    setStatus(response?.error || "connect failed");
    return;
  }
  setStatus(response.connected ? `connected (${response.lastEvent})` : response.lastEvent);
}

async function disconnect() {
  const response = await callBg({ kind: "disconnect" });
  if (!response?.ok) {
    setStatus(response?.error || "disconnect failed");
    return;
  }
  setStatus("disconnected");
}

saveBtn.addEventListener("click", saveConfig);
connectBtn.addEventListener("click", connect);
disconnectBtn.addEventListener("click", disconnect);

chrome.runtime.onMessage.addListener((message) => {
  if (message?.kind === "status") {
    const s = message.status || {};
    setStatus(s.connected ? `connected (${s.lastEvent})` : s.lastEvent || "idle");
  }
});

loadState();
