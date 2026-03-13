#!/usr/bin/env node
const path = require("path");
const fs = require("fs");
const { spawnSync } = require("child_process");
const { SUPPORTED_BUILD_PROFILES, resolveBuildProfilePolicy } = require("./build-profile-policy.js");

const [, , target = "dist", profileArg] = process.argv;
const requestedProfile = (profileArg || process.env.DRUMSHEET_DIST_PROFILE || "full").toLowerCase();
const policy = resolveBuildProfilePolicy(requestedProfile);
const profile = policy.builderProfile;
const action = target === "pack" ? "pack" : "dist";
const signingEnabled = process.env.DRUMSHEET_ENABLE_SIGNING === "true";
const projectRoot = path.join(__dirname, "..", "..");
if (!["pack", "dist"].includes(action)) {
  console.error("usage: node scripts/run-builder.js <pack|dist> <full|compact|lean|release>");
  process.exit(1);
}
if (!SUPPORTED_BUILD_PROFILES.has(requestedProfile)) {
  console.error(`[run-builder] unsupported profile: ${requestedProfile}`);
  console.error("supported profiles: full | compact | lean | release");
  process.exit(1);
}

const localBuilder = process.platform === "win32"
  ? path.join(__dirname, "..", "node_modules", ".bin", "electron-builder.cmd")
  : path.join(__dirname, "..", "node_modules", ".bin", "electron-builder");

let command = localBuilder;
let args = [
  "--config",
  path.join(__dirname, "..", "electron-builder.config.js"),
  "--publish",
  "never",
];
if (action === "pack") {
  args.unshift("--dir");
}

if (!fs.existsSync(localBuilder)) {
  console.warn(`[run-builder] local electron-builder executable not found: ${localBuilder}`);
  command = "npx";
  args = ["electron-builder", ...args];
}

function stageRuntimeFfmpeg() {
  const ffmpegPath = require("ffmpeg-static");
  const ffprobeStatic = require("ffprobe-static");
  const ffprobePath = ffprobeStatic && ffprobeStatic.path;
  if (!ffmpegPath || !ffprobePath) {
    console.error("[run-builder] ffmpeg-static / ffprobe-static could not resolve platform binaries.");
    process.exit(1);
  }

  const backendBinDir = path.join(__dirname, "..", "..", "backend", "bin");
  fs.mkdirSync(backendBinDir, { recursive: true });

  const ffmpegName = process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg";
  const ffprobeName = process.platform === "win32" ? "ffprobe.exe" : "ffprobe";
  const copies = [
    [ffmpegPath, path.join(backendBinDir, ffmpegName)],
    [ffprobePath, path.join(backendBinDir, ffprobeName)],
  ];

  for (const [source, target] of copies) {
    if (fs.existsSync(target)) {
      fs.chmodSync(target, 0o755);
      fs.unlinkSync(target);
    }
    fs.copyFileSync(source, target);
    fs.chmodSync(target, 0o755);
    console.log(`[run-builder] staged runtime binary: ${target}`);
  }
}

function findBuildPython() {
  const backendDir = path.join(projectRoot, "backend");
  const candidates = process.platform === "win32"
    ? [
        path.join(backendDir, ".venv", "Scripts", "python.exe"),
        "py",
        "python",
      ]
    : [
        path.join(backendDir, ".venv", "bin", "python3"),
        path.join(backendDir, ".venv", "bin", "python"),
        "python3",
        "python",
      ];

  for (const candidate of candidates) {
    const probeArgs = candidate === "py" ? ["-3", "-m", "PyInstaller", "--version"] : ["-m", "PyInstaller", "--version"];
    const probe = spawnSync(candidate, probeArgs, {
      stdio: "ignore",
      shell: process.platform === "win32",
    });
    if (!probe.error && probe.status === 0) {
      return candidate;
    }
  }

  console.error("[run-builder] no Python interpreter with PyInstaller found for frozen backend build.");
  console.error("[run-builder] install build dependencies first: backend/.venv/bin/pip install -r backend/requirements-build.txt");
  process.exit(1);
}

function ensureFrozenBackendRuntime() {
  if (!policy.requiresFrozenBackend) {
    return;
  }

  const python = findBuildPython();
  const buildScript = path.join(projectRoot, "backend", "scripts", "build_frozen_backend.py");
  const args = python === "py" ? ["-3", buildScript] : [buildScript];
  const result = spawnSync(python, args, {
    cwd: projectRoot,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.error || result.status !== 0) {
    console.error("[run-builder] frozen backend build failed.");
    process.exit(result.status || 1);
  }
}

stageRuntimeFfmpeg();
ensureFrozenBackendRuntime();

const result = spawnSync(command, args, {
  cwd: path.join(__dirname, ".."),
  stdio: "inherit",
  shell: process.platform === "win32",
  env: {
    ...process.env,
    DRUMSHEET_DIST_PROFILE: profile,
    DRUMSHEET_ENABLE_SIGNING: signingEnabled ? "true" : "false",
    CSC_IDENTITY_AUTO_DISCOVERY: signingEnabled ? (process.env.CSC_IDENTITY_AUTO_DISCOVERY || "true") : "false",
  },
});

if (result.error) {
  const code = result.error.code ? ` (code: ${result.error.code})` : "";
  console.error(`[run-builder] failed to execute ${command}: ${result.error.message}${code}`);
  console.error("[run-builder] args:", args.join(" "));
  process.exit(1);
}

if (result.status && result.status !== 0) {
  process.exit(result.status);
}

const validator = spawnSync(
  process.execPath,
  [path.join(__dirname, "validate-packaged-release.js"), action],
  {
    cwd: path.join(__dirname, ".."),
    stdio: "inherit",
    shell: false,
    env: process.env,
  },
);

if (validator.error) {
  const code = validator.error.code ? ` (code: ${validator.error.code})` : "";
  console.error(`[run-builder] failed to execute packaged release validator: ${validator.error.message}${code}`);
  process.exit(1);
}

process.exit(validator.status || 0);
