const { contextBridge, ipcRenderer } = require("electron");
const BACKEND_PORT = process.env.DRUMSHEET_PORT || 8000;

contextBridge.exposeInMainWorld("drumSheetAPI", {
  selectVideoFile: () => ipcRenderer.invoke("select-video-file"),
  openPath: (targetPath) => ipcRenderer.invoke("open-path", targetPath),
  apiBase: `http://127.0.0.1:${BACKEND_PORT}`,
});
