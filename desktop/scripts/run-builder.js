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

function logBuildArtifactContract(currentAction) {
  if (currentAction === "pack") {
    console.log("[run-builder] pack validates the unpacked packaged app only.");
    console.log("[run-builder] pack does not generate installers or latest*.yml metadata; use dist when release artifacts are required.");
    return;
  }
  console.log("[run-builder] dist generates installer artifacts and release metadata.");
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
  require("./media-tool-policy").validateMediaTools(path.join(projectRoot, "backend", "bin"));
}

function findBuildPython() {
  const backendDir = path.join(projectRoot, "backend");
  const defaultCandidates = process.platform === "win32"
    ? [
        path.join(backendDir, ".venv-build", "Scripts", "python.exe"),
        path.join(backendDir, ".venv", "Scripts", "python.exe"),
        "py",
        "python",
      ]
    : [
        path.join(backendDir, ".venv-build", "bin", "python"),
        path.join(backendDir, ".venv", "bin", "python3"),
        path.join(backendDir, ".venv", "bin", "python"),
        "python3",
        "python",
      ];

  const candidates = process.env.DRUMSHEET_BUILD_PYTHON
    ? [process.env.DRUMSHEET_BUILD_PYTHON] : defaultCandidates;
  for (const candidate of candidates) {
    const version = spawnSync(candidate, [...(candidate === "py" ? ["-3"] : []), "-c", "import sys; print(\".\".join(map(str, sys.version_info[:2])))"], { encoding: "utf8" });
    if (version.stdout?.trim() !== "3.11") continue;
    const probeArgs = candidate === "py" ? ["-3", "-m", "PyInstaller", "--version"] : ["-m", "PyInstaller", "--version"];
    const probe = spawnSync(candidate, probeArgs, {
      stdio: "ignore",
      shell: process.platform === "win32",
    });
    if (!probe.error && probe.status === 0) {
      return candidate;
    }
  }

  console.error("[run-builder] no Python 3.11 interpreter with PyInstaller found for frozen backend build.");
  console.error("[run-builder] install build dependencies first: use Python 3.11 and backend/requirements-build.lock; set DRUMSHEET_BUILD_PYTHON to its executable");
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
logBuildArtifactContract(action);

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

if (!validator.status && action === "dist") {
  const filename = `ffmpeg-8.1.2-${process.platform}-${process.arch}-source.tar.gz`;
  fs.copyFileSync(path.join(projectRoot, ".tmp", "media-tools", filename), path.join(projectRoot, "dist", filename));
}
process.exit(validator.status || 0);
