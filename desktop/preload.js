const { contextBridge, ipcRenderer } = require("electron");
const BACKEND_PORT = process.env.DRUMSHEET_PORT || 8000;

contextBridge.exposeInMainWorld("drumSheetAPI", {
  selectVideoFile: () => ipcRenderer.invoke("select-video-file"),
  selectAudioSourceFile: () => ipcRenderer.invoke("select-audio-source-file"),
  openPath: (targetPath) => ipcRenderer.invoke("open-path", targetPath),
  copyText: (text) => ipcRenderer.invoke("copy-text", text),
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
  apiBase: `http://127.0.0.1:${BACKEND_PORT}`,
});
