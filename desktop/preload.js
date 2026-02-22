const { contextBridge, ipcRenderer } = require("electron");
const BACKEND_PORT = process.env.DRUMSHEET_PORT || 8000;

contextBridge.exposeInMainWorld("drumSheetAPI", {
  selectVideoFile: () => ipcRenderer.invoke("select-video-file"),
  selectAudioSourceFile: () => ipcRenderer.invoke("select-audio-source-file"),
  openPath: (targetPath) => ipcRenderer.invoke("open-path", targetPath),
  copyText: (text) => ipcRenderer.invoke("copy-text", text),
  apiBase: `http://127.0.0.1:${BACKEND_PORT}`,
});
