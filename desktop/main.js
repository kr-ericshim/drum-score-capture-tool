const path = require("path");
const fs = require("fs");
const { app, BrowserWindow, clipboard, dialog, ipcMain, shell } = require("electron");
const { spawn, spawnSync } = require("child_process");

const BACKEND_PORT = Number(process.env.DRUMSHEET_PORT || 8000);
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

let mainWindow = null;
let backendProcess = null;
let setupProcess = null;
let isBackendStopping = false;
let backendReady = false;
let backendStarting = false;
let backendLastError = "";
let setupRunning = false;
let setupPhase = "idle";

function resolveBackendDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend");
  }
  return path.join(__dirname, "..", "backend");
}

function resolveDesktopDir() {
  return __dirname;
}

function existsFile(candidate) {
  try {
    return fs.existsSync(candidate);
  } catch (_) {
    return false;
  }
}

function canLaunchCommand(command, args = ["--version"]) {
  try {
    const probe = spawnSync(command, args, {
      stdio: "ignore",
      windowsHide: true,
      shell: process.platform === "win32",
    });
    if (probe.error) {
      return false;
    }
    return probe.status === 0;
  } catch (_) {
    return false;
  }
}

function sendToRenderer(channel, payload) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send(channel, payload);
}

function getBackendStatePayload() {
  return {
    ready: backendReady,
    starting: backendStarting,
    running: Boolean(backendProcess),
    error: backendLastError,
    setupRunning,
    platform: process.platform,
  };
}

function getSetupStatePayload() {
  return {
    running: setupRunning,
    phase: setupPhase,
  };
}

function emitBackendState() {
  sendToRenderer("backend-state", getBackendStatePayload());
}

function emitSetupState() {
  sendToRenderer("setup-state", getSetupStatePayload());
}

function emitSetupLog(line, level = "info") {
  const text = String(line || "").trim();
  if (!text) {
    return;
  }
  sendToRenderer("setup-log", {
    line: text,
    level,
    timestamp: Date.now(),
  });
}

function emitCommandChunk(label, chunk, level = "info") {
  const text = String(chunk || "");
  if (!text) {
    return;
  }
  const lines = text
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  lines.forEach((line) => emitSetupLog(`[${label}] ${line}`, level));
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

function resolveVenvPythonPath(backendDir) {
  if (process.platform === "win32") {
    return path.join(backendDir, ".venv", "Scripts", "python.exe");
  }
  return path.join(backendDir, ".venv", "bin", "python");
}

function hasNvidiaGpu() {
  if (process.platform !== "win32") {
    return false;
  }
  try {
    const probe = spawnSync("nvidia-smi", [], {
      stdio: "ignore",
      windowsHide: true,
      shell: true,
    });
    return !probe.error && probe.status === 0;
  } catch (_) {
    return false;
  }
}

function runCommandWithLogs({ label, command, args = [], cwd, env = process.env }) {
  return new Promise((resolve, reject) => {
    emitSetupLog(`[${label}] ${command} ${args.join(" ")}`.trim());
    const child = spawn(command, args, {
      cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
      shell: process.platform === "win32",
    });
    setupProcess = child;

    child.stdout.on("data", (chunk) => emitCommandChunk(label, chunk, "info"));
    child.stderr.on("data", (chunk) => emitCommandChunk(label, chunk, "warn"));

    child.once("error", (error) => {
      setupProcess = null;
      reject(new Error(`${label} failed: ${error.message}`));
    });

    child.on("exit", (code) => {
      setupProcess = null;
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${label} failed (exit code ${code})`));
    });
  });
}

async function performGuidedSetup() {
  if (app.isPackaged) {
    throw new Error("배포본에서는 원클릭 개발 세팅을 지원하지 않습니다. 배포용 설치본을 사용해 주세요.");
  }

  const backendDir = resolveBackendDir();
  const desktopDir = resolveDesktopDir();
  const python = findPythonCommand(backendDir);
  const venvPython = resolveVenvPythonPath(backendDir);
  const env = { ...process.env };

  setupPhase = "venv";
  emitSetupState();
  await runCommandWithLogs({
    label: "venv",
    command: python.command,
    args: [...python.prefixArgs, "-m", "venv", path.join(backendDir, ".venv")],
    cwd: backendDir,
    env,
  });

  if (!existsFile(venvPython)) {
    throw new Error(`venv python not found: ${venvPython}`);
  }

  setupPhase = "backend_core";
  emitSetupState();
  await runCommandWithLogs({
    label: "pip-upgrade",
    command: venvPython,
    args: ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
    cwd: backendDir,
    env,
  });

  await runCommandWithLogs({
    label: "backend-core",
    command: venvPython,
    args: ["-m", "pip", "install", "-r", path.join(backendDir, "requirements.txt")],
    cwd: backendDir,
    env,
  });

  setupPhase = "backend_optional";
  emitSetupState();
  await runCommandWithLogs({
    label: "backend-uvr",
    command: venvPython,
    args: ["-m", "pip", "install", "-r", path.join(backendDir, "requirements-uvr.txt")],
    cwd: backendDir,
    env,
  });

  const useCudaTorch = hasNvidiaGpu();
  if (useCudaTorch) {
    emitSetupLog("NVIDIA GPU 감지: CUDA torch 패키지를 설치합니다.");
    await runCommandWithLogs({
      label: "torch-cuda",
      command: venvPython,
      args: ["-m", "pip", "install", "--index-url", "https://download.pytorch.org/whl/cu128", "torch", "torchaudio"],
      cwd: backendDir,
      env,
    });
  } else {
    emitSetupLog("NVIDIA GPU 미감지: CPU torch 패키지를 설치합니다.");
    await runCommandWithLogs({
      label: "torch-cpu",
      command: venvPython,
      args: ["-m", "pip", "install", "torch", "torchaudio"],
      cwd: backendDir,
      env,
    });
  }

  await runCommandWithLogs({
    label: "audio-runtime",
    command: venvPython,
    args: ["-m", "pip", "install", "torchcodec", "soundfile>=0.12.0"],
    cwd: backendDir,
    env,
  });

  setupPhase = "runtime_check";
  emitSetupState();
  await runCommandWithLogs({
    label: "doctor",
    command: venvPython,
    args: [path.join(backendDir, "scripts", "doctor.py")],
    cwd: backendDir,
    env,
  });

  setupPhase = "desktop";
  emitSetupState();
  if (!existsFile(path.join(desktopDir, "package.json"))) {
    throw new Error(`desktop package.json not found: ${desktopDir}`);
  }
  await runCommandWithLogs({
    label: "npm-install",
    command: process.platform === "win32" ? "npm.cmd" : "npm",
    args: ["install"],
    cwd: desktopDir,
    env,
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));

  mainWindow.webContents.on("did-finish-load", () => {
    emitBackendState();
    emitSetupState();
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function waitForBackendReady() {
  const limitMs = 30000;
  const intervalMs = 500;
  const start = Date.now();

  return new Promise((resolve, reject) => {
    const poll = async () => {
      if (Date.now() - start > limitMs) {
        reject(new Error(backendLastError || "backend did not become ready"));
        return;
      }
      if (!backendProcess) {
        reject(new Error(backendLastError || "backend process is not running"));
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
  if (backendProcess) {
    return;
  }

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
    windowsHide: true,
  });

  backendProcess.once("error", (error) => {
    backendLastError = `Failed to start python backend: ${error.message}`;
    backendStarting = false;
    backendReady = false;
    emitBackendState();
  });

  backendProcess.stdout.on("data", (chunk) => {
    console.log("[backend]", chunk.toString("utf8").trim());
  });
  backendProcess.stderr.on("data", (chunk) => {
    console.error("[backend][stderr]", chunk.toString("utf8").trim());
  });

  backendProcess.on("exit", (code) => {
    const expectedStop = isBackendStopping;
    backendProcess = null;
    backendStarting = false;
    backendReady = false;
    if (!expectedStop) {
      backendLastError = `The local processing service stopped unexpectedly (exit: ${code})`;
      console.log(`[backend] exited with ${code}`);
      if (app.isReady() && !setupRunning) {
        dialog.showErrorBox("Backend stopped", "The local processing service stopped unexpectedly.");
      }
    }
    emitBackendState();
  });
}

async function startBackendAndWait({ showDialogOnFail = false } = {}) {
  if (backendReady && backendProcess) {
    return { ok: true };
  }
  if (backendStarting) {
    return { ok: false, error: "backend is already starting" };
  }

  backendStarting = true;
  backendReady = false;
  backendLastError = "";
  isBackendStopping = false;
  emitBackendState();

  try {
    runBackend();
    await waitForBackendReady();
    backendStarting = false;
    backendReady = true;
    backendLastError = "";
    emitBackendState();
    return { ok: true };
  } catch (error) {
    backendStarting = false;
    backendReady = false;
    backendLastError = String(error?.message || error);
    emitBackendState();
    if (showDialogOnFail && app.isReady() && !setupRunning) {
      dialog.showErrorBox("Backend Error", backendLastError);
    }
    return { ok: false, error: backendLastError };
  }
}

async function stopBackend() {
  if (!backendProcess) {
    backendReady = false;
    backendStarting = false;
    emitBackendState();
    return;
  }

  const processRef = backendProcess;
  isBackendStopping = true;
  await new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) {
        return;
      }
      settled = true;
      resolve();
    };

    processRef.once("exit", done);
    try {
      processRef.kill();
    } catch (_) {
      done();
      return;
    }

    setTimeout(() => {
      if (!settled) {
        try {
          processRef.kill("SIGKILL");
        } catch (_) {
          // ignore
        }
        done();
      }
    }, 2500);
  });

  backendProcess = null;
  backendReady = false;
  backendStarting = false;
  emitBackendState();
}

function stopSetupProcess() {
  if (!setupProcess) {
    return;
  }
  try {
    setupProcess.kill();
  } catch (_) {
    // ignore
  }
  setupProcess = null;
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
    if (!targetPath) {
      return;
    }
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

  ipcMain.handle("set-always-on-top", async (_, enabled) => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return false;
    }
    const next = Boolean(enabled);
    mainWindow.setAlwaysOnTop(next, "floating");
    return mainWindow.isAlwaysOnTop();
  });

  ipcMain.handle("get-always-on-top", async () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return false;
    }
    return mainWindow.isAlwaysOnTop();
  });

  ipcMain.handle("get-backend-state", async () => getBackendStatePayload());

  ipcMain.handle("restart-backend", async () => {
    emitSetupLog("백엔드를 다시 연결합니다.");
    await stopBackend();
    return startBackendAndWait({ showDialogOnFail: false });
  });

  ipcMain.handle("run-guided-setup", async () => {
    if (setupRunning) {
      return { ok: false, error: "이미 설치/복구가 실행 중입니다." };
    }

    setupRunning = true;
    setupPhase = "preparing";
    emitSetupState();
    emitBackendState();
    emitSetupLog("원클릭 설치/복구를 시작합니다.");

    try {
      await stopBackend();
      await performGuidedSetup();
      setupPhase = "starting_backend";
      emitSetupState();
      const backendResult = await startBackendAndWait({ showDialogOnFail: false });
      if (!backendResult.ok) {
        throw new Error(backendResult.error || "백엔드를 다시 시작하지 못했습니다.");
      }
      emitSetupLog("설치/복구 완료. 로컬 엔진 연결 성공.", "success");
      return { ok: true };
    } catch (error) {
      const message = String(error?.message || error);
      backendLastError = message;
      emitBackendState();
      emitSetupLog(`오류: ${message}`, "error");
      return { ok: false, error: message };
    } finally {
      setupRunning = false;
      setupPhase = "idle";
      emitSetupState();
      emitBackendState();
    }
  });
}

app.whenReady().then(async () => {
  registerIpc();
  createWindow();
  await startBackendAndWait({ showDialogOnFail: false });
});

app.on("window-all-closed", () => {
  stopSetupProcess();
  if (backendProcess) {
    isBackendStopping = true;
    backendProcess.kill();
    backendProcess = null;
  }
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopSetupProcess();
  if (backendProcess) {
    isBackendStopping = true;
    backendProcess.kill();
    backendProcess = null;
  }
});
