const wsUrlInput = document.getElementById("wsUrl");
const instanceIdInput = document.getElementById("instanceId");
const clientIdInput = document.getElementById("clientId");
const authTokenInput = document.getElementById("authToken");
const statusEl = document.getElementById("status");
const lockStatusEl = document.getElementById("lockStatus");

const saveBtn = document.getElementById("saveBtn");
const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const lockBtn = document.getElementById("lockBtn");
const unlockBtn = document.getElementById("unlockBtn");

function setStatus(text) {
  statusEl.textContent = `Status: ${text}`;
}

function setLockStatus(lock) {
  if (!lock?.enabled) {
    lockStatusEl.textContent = "Target: active tab (unlocked)";
    return;
  }
  lockStatusEl.textContent = `Target: locked tab #${lock.tabId} (window #${lock.windowId})`;
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
  setLockStatus(response.lock);
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

async function lockCurrentTab() {
  const response = await callBg({ kind: "lock-current-tab" });
  if (!response?.ok) {
    setStatus(response?.error || "lock failed");
    return;
  }
  setLockStatus(response.lock);
}

async function unlockTab() {
  const response = await callBg({ kind: "unlock-tab" });
  if (!response?.ok) {
    setStatus(response?.error || "unlock failed");
    return;
  }
  setLockStatus(response.lock);
}

saveBtn.addEventListener("click", saveConfig);
connectBtn.addEventListener("click", connect);
disconnectBtn.addEventListener("click", disconnect);
lockBtn.addEventListener("click", lockCurrentTab);
unlockBtn.addEventListener("click", unlockTab);

chrome.runtime.onMessage.addListener((message) => {
  if (message?.kind === "status") {
    const s = message.status || {};
    setStatus(s.connected ? `connected (${s.lastEvent})` : s.lastEvent || "idle");
    setLockStatus(s.lock);
  }
});

loadState();
