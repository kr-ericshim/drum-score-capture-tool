const { contextBridge, ipcRenderer, webUtils } = require("electron");
const BACKEND_PORT = process.env.DRUMSHEET_PORT || 8000;
const API_BASE = `http://127.0.0.1:${BACKEND_PORT}`;
const desktopVersion = ipcRenderer.sendSync("get-app-version");
const apiToken = ipcRenderer.sendSync("get-session-token") || "";

function authenticatedHeaders(extraHeaders = {}) {
  const requestHeaders = { ...extraHeaders };
  if (apiToken) {
    requestHeaders["X-DrumSheet-Token"] = String(apiToken);
  }
  return requestHeaders;
}

async function readJobAsset(assetPath) {
  const url = new URL(String(assetPath || ""), API_BASE);
  const apiOrigin = new URL(API_BASE).origin;
  if (url.origin !== apiOrigin || !url.pathname.startsWith("/jobs-files/")) {
    throw new Error("job asset path must stay within /jobs-files");
  }
  url.searchParams.delete("token");

  const response = await fetch(url.toString(), { headers: authenticatedHeaders() });
  if (!response.ok) {
    throw new Error(`job asset request failed: ${response.status}`);
  }
  return {
    bytes: await response.arrayBuffer(),
    contentType: String(response.headers.get("content-type") || ""),
  };
}

async function requestJson(apiPath, options = {}) {
  const url = new URL(String(apiPath || ""), API_BASE);
  const apiOrigin = new URL(API_BASE).origin;
  if (url.origin !== apiOrigin) {
    throw new Error("api request must stay within the backend origin");
  }
  url.searchParams.delete("token");

  const method = String(options.method || "GET").toUpperCase();
  const hasBody = options.body !== undefined && options.body !== null;
  const requestHeaders = hasBody ? { "Content-Type": "application/json" } : {};
  const response = await fetch(url.toString(), {
    method,
    headers: authenticatedHeaders(requestHeaders),
    body: hasBody ? String(options.body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  return {
    ok: Boolean(response.ok),
    status: Number(response.status || 0),
    data,
  };
}

contextBridge.exposeInMainWorld("drumSheetAPI", {
  selectVideoFile: () => ipcRenderer.invoke("select-video-file"),
  getPathForFile: (file) => webUtils.getPathForFile(file),
  readJobAsset,
  requestJson,
  openPath: (targetPath) => ipcRenderer.invoke("open-path", targetPath),
  copyText: (text) => ipcRenderer.invoke("copy-text", text),
  setAlwaysOnTop: (enabled) => ipcRenderer.invoke("set-always-on-top", enabled),
  getAlwaysOnTop: () => ipcRenderer.invoke("get-always-on-top"),
  getBackendState: () => ipcRenderer.invoke("get-backend-state"),
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  runGuidedSetup: () => ipcRenderer.invoke("run-guided-setup"),
  onSetupLog: (handler) => {
    const listener = (_, payload) => handler(payload);
    ipcRenderer.on("setup-log", listener);
    return () => ipcRenderer.removeListener("setup-log", listener);
  },
  onSetupState: (handler) => {
    const listener = (_, payload) => handler(payload);
    ipcRenderer.on("setup-state", listener);
    return () => ipcRenderer.removeListener("setup-state", listener);
  },
  onBackendState: (handler) => {
    const listener = (_, payload) => handler(payload);
    ipcRenderer.on("backend-state", listener);
    return () => ipcRenderer.removeListener("backend-state", listener);
  },
  desktopVersion: String(desktopVersion || ""),
  apiBase: API_BASE,
});
