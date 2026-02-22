const path = require("path");
const fs = require("fs");
const { app, BrowserWindow, clipboard, dialog, ipcMain, shell } = require("electron");
const { spawn, spawnSync } = require("child_process");

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

function canLaunchCommand(command, args = ["--version"]) {
  try {
    const probe = spawnSync(command, args, {
      stdio: "ignore",
      windowsHide: true,
    });
    if (probe.error) {
      return false;
    }
    return probe.status === 0;
  } catch (_) {
    return false;
  }
}

function resolveBundledBinary(backendDir, baseName) {
  const fileName = process.platform === "win32" ? `${baseName}.exe` : baseName;
  const candidates = [
    path.join(backendDir, "bin", fileName),
    path.join(backendDir, "bin", baseName, fileName),
    path.join(backendDir, "bin", "ffmpeg", fileName),
    path.join(backendDir, "ffmpeg", fileName),
    path.join(backendDir, "ffmpeg", "bin", fileName),
    path.join(backendDir, "tools", "ffmpeg", fileName),
    path.join(backendDir, "tools", "ffmpeg", "bin", fileName),
    path.join(backendDir, "third_party", "ffmpeg", fileName),
    path.join(backendDir, "third_party", "ffmpeg", "bin", fileName),
    path.join(backendDir, "vendor", "ffmpeg", fileName),
    path.join(backendDir, "vendor", "ffmpeg", "bin", fileName),
  ];
  for (const candidate of candidates) {
    if (existsFile(candidate)) {
      return candidate;
    }
  }
  return "";
}

function resolveFfmpegBinaries(backendDir) {
  const fromEnvFfmpeg = (process.env.DRUMSHEET_FFMPEG_BIN || "").trim();
  const fromEnvFfprobe = (process.env.DRUMSHEET_FFPROBE_BIN || "").trim();

  const ffmpegBin = fromEnvFfmpeg || resolveBundledBinary(backendDir, "ffmpeg");
  let ffprobeBin = fromEnvFfprobe || resolveBundledBinary(backendDir, "ffprobe");

  if (!ffprobeBin && ffmpegBin && existsFile(ffmpegBin)) {
    const ffprobeName = process.platform === "win32" ? "ffprobe.exe" : "ffprobe";
    const sibling = path.join(path.dirname(ffmpegBin), ffprobeName);
    if (existsFile(sibling)) {
      ffprobeBin = sibling;
    }
  }

  return {
    ffmpegBin,
    ffprobeBin,
  };
}

function findPythonCommand(backendDir) {
  const candidates = [];
  const configured = process.env.DRUMSHEET_PYTHON_BIN;
  if (configured && configured.trim()) {
    candidates.push({
      command: configured.trim(),
      prefixArgs: [],
      label: "env:DRUMSHEET_PYTHON_BIN",
    });
  }

  if (process.platform === "win32") {
    const venvPython = path.join(backendDir, ".venv", "Scripts", "python.exe");
    if (existsFile(venvPython)) {
      candidates.push({
        command: venvPython,
        prefixArgs: [],
        label: "venv-python",
      });
    }
    candidates.push({ command: "py", prefixArgs: ["-3.11"], label: "py -3.11" });
    candidates.push({ command: "py", prefixArgs: ["-3"], label: "py -3" });
    candidates.push({ command: "py", prefixArgs: [], label: "py" });
    candidates.push({ command: "python", prefixArgs: [], label: "python" });
  } else {
    const venvPython = path.join(backendDir, ".venv", "bin", "python3");
    if (existsFile(venvPython)) {
      candidates.push({
        command: venvPython,
        prefixArgs: [],
        label: "venv-python3",
      });
    }
    const venvPy = path.join(backendDir, ".venv", "bin", "python");
    if (existsFile(venvPy)) {
      candidates.push({
        command: venvPy,
        prefixArgs: [],
        label: "venv-python",
      });
    }
    candidates.push({ command: "python3", prefixArgs: [], label: "python3" });
    candidates.push({ command: "python", prefixArgs: [], label: "python" });
  }

  for (const candidate of candidates) {
    if (canLaunchCommand(candidate.command, [...candidate.prefixArgs, "--version"])) {
      return candidate;
    }
  }

  const checked = candidates
    .map((candidate) => `${candidate.label}: ${candidate.command} ${candidate.prefixArgs.join(" ")}`.trim())
    .join("\n");
  throw new Error(
    `No runnable Python interpreter found.\nChecked:\n${checked}\n` +
      "Install Python 3.11 (64-bit) or set DRUMSHEET_PYTHON_BIN to a valid python executable.",
  );
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
  console.log(`[backend] python launcher: ${python.label} -> ${python.command} ${python.prefixArgs.join(" ")}`.trim());
  const bins = resolveFfmpegBinaries(backendDir);
  if (bins.ffmpegBin) {
    console.log(`[backend] ffmpeg bin: ${bins.ffmpegBin}`);
  }
  if (bins.ffprobeBin) {
    console.log(`[backend] ffprobe bin: ${bins.ffprobeBin}`);
  }

  const env = {
    ...process.env,
    DRUMSHEET_PORT: String(BACKEND_PORT),
    DRUMSHEET_JOBS_DIR: path.join(backendDir, "jobs"),
    DRUMSHEET_HWACCEL: process.env.DRUMSHEET_HWACCEL || "auto",
    DRUMSHEET_OPENCV_ACCEL: process.env.DRUMSHEET_OPENCV_ACCEL || "auto",
    ...(bins.ffmpegBin ? { DRUMSHEET_FFMPEG_BIN: bins.ffmpegBin } : {}),
    ...(bins.ffprobeBin ? { DRUMSHEET_FFPROBE_BIN: bins.ffprobeBin } : {}),
  };
  backendProcess = spawn(python.command, [...python.prefixArgs, runPy], {
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
