const wsUrlInput = document.getElementById("wsUrl");
const instanceIdInput = document.getElementById("instanceId");
const clientIdInput = document.getElementById("clientId");
const authTokenInput = document.getElementById("authToken");
const statusEl = document.getElementById("status");

const saveBtn = document.getElementById("saveBtn");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");

function setStatus(text) {
  statusEl.textContent = `Status: ${text}`;
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
  wsUrlInput.value = config.wsUrl || "";
  instanceIdInput.value = config.instanceId || "";
  clientIdInput.value = config.clientId || "";
  authTokenInput.value = config.authToken || "";
  setStatus(response.connected ? `connected (${response.lastEvent})` : response.lastEvent);
}

async function saveConfig() {
  const response = await callBg({
    kind: "save-config",
    wsUrl: wsUrlInput.value.trim(),
    instanceId: instanceIdInput.value.trim(),
    clientId: clientIdInput.value.trim(),
    authToken: authTokenInput.value.trim()
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
    wsUrl: wsUrlInput.value.trim(),
    instanceId: instanceIdInput.value.trim(),
    clientId: clientIdInput.value.trim(),
    authToken: authTokenInput.value.trim()
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
