const path = require("path");
const fs = require("fs");
const { app, BrowserWindow, clipboard, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");

const BACKEND_PORT = Number(process.env.DRUMSHEET_PORT || 8000);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
let backendProcess;
let isBackendStopping = false;

function resolveBackendDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend");
  }
  return path.join(__dirname, "..", "backend");
}

function existsFile(candidate) {
  try {
    return fs.existsSync(candidate);
  } catch (error) {
    return false;
  }
}

function findPythonCommand(backendDir) {
  const configured = process.env.DRUMSHEET_PYTHON_BIN;
  if (configured && configured.trim()) {
    return configured;
  }

  if (process.platform === "win32") {
    const venvPython = path.join(backendDir, ".venv", "Scripts", "python.exe");
    if (existsFile(venvPython)) {
      return venvPython;
    }
  } else {
    const venvPython = path.join(backendDir, ".venv", "bin", "python3");
    if (existsFile(venvPython)) {
      return venvPython;
    }
    const venvPy = path.join(backendDir, ".venv", "bin", "python");
    if (existsFile(venvPy)) {
      return venvPy;
    }
  }

  return process.platform === "win32" ? "python" : "python3";
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1100,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  window.loadFile(path.join(__dirname, "renderer", "index.html"));
}

function waitForBackendReady() {
  const limitMs = 30000;
  const intervalMs = 500;
  const start = Date.now();

  return new Promise((resolve, reject) => {
    const poll = async () => {
      if (Date.now() - start > limitMs) {
        reject(new Error("backend did not become ready"));
        return;
      }
      try {
        const response = await fetch(`${BACKEND_URL}/health`, { method: "GET" });
        if (response.ok) {
          resolve();
          return;
        }
      } catch (_) {
        // keep polling
      }
      setTimeout(poll, intervalMs);
    };
    poll();
  });
}

function runBackend() {
  const backendDir = resolveBackendDir();
  const runPy = path.join(backendDir, "run.py");
  if (!fs.existsSync(runPy)) {
    throw new Error(`Cannot find backend entrypoint: ${runPy}`);
  }
  const python = findPythonCommand(backendDir);

  const env = {
    ...process.env,
    DRUMSHEET_PORT: String(BACKEND_PORT),
    DRUMSHEET_JOBS_DIR: path.join(backendDir, "jobs"),
    DRUMSHEET_HWACCEL: process.env.DRUMSHEET_HWACCEL || "auto",
    DRUMSHEET_OPENCV_ACCEL: process.env.DRUMSHEET_OPENCV_ACCEL || "auto",
  };
  backendProcess = spawn(python, [runPy], {
    cwd: backendDir,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.once("error", (error) => {
    isBackendStopping = true;
    dialog.showErrorBox("Backend launch failed", `Failed to start python backend: ${error.message}`);
    app.quit();
  });

  backendProcess.stdout.on("data", (chunk) => {
    console.log("[backend]", chunk.toString("utf8").trim());
  });
  backendProcess.stderr.on("data", (chunk) => {
    console.error("[backend][stderr]", chunk.toString("utf8").trim());
  });

  backendProcess.on("exit", (code) => {
    if (isBackendStopping) {
      return;
    }
    console.log(`[backend] exited with ${code}`);
    if (app.isReady()) {
      dialog.showErrorBox("Backend stopped", "The local processing service stopped unexpectedly.");
    }
  });
}

function registerIpc() {
  ipcMain.handle("select-video-file", async () => {
    const result = await dialog.showOpenDialog({
      title: "악보 영상 선택",
      properties: ["openFile"],
      filters: [
        {
          name: "Video Files",
          extensions: ["mp4", "mkv", "mov", "avi", "webm"],
        },
      ],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return "";
    }
    return result.filePaths[0];
  });

  ipcMain.handle("select-audio-source-file", async () => {
    const result = await dialog.showOpenDialog({
      title: "오디오/영상 파일 선택",
      properties: ["openFile"],
      filters: [
        {
          name: "Audio/Video Files",
          extensions: ["mp3", "wav", "mp4"],
        },
      ],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return "";
    }
    return result.filePaths[0];
  });

  ipcMain.handle("open-path", async (_, targetPath) => {
    if (!targetPath) return;
    return shell.openPath(targetPath);
  });

  ipcMain.handle("copy-text", async (_, text) => {
    const value = String(text || "");
    if (!value.trim()) {
      return false;
    }
    clipboard.writeText(value);
    return true;
  });
}

app.whenReady().then(async () => {
  registerIpc();
  try {
    runBackend();
    await waitForBackendReady();
  } catch (error) {
    dialog.showErrorBox("Backend Error", `${error}`);
    app.quit();
    return;
  }
  createWindow();
});

app.on("window-all-closed", () => {
  if (backendProcess) {
    isBackendStopping = true;
    backendProcess.kill();
  }
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (backendProcess) {
    isBackendStopping = true;
    backendProcess.kill();
  }
});
