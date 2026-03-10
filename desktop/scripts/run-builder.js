#!/usr/bin/env node
const path = require("path");
const fs = require("fs");
const { spawnSync } = require("child_process");

const [, , target = "dist", profileArg] = process.argv;
const requestedProfile = (profileArg || process.env.DRUMSHEET_DIST_PROFILE || "full").toLowerCase();
const profile = requestedProfile === "release" ? "compact" : requestedProfile;
const action = target === "pack" ? "pack" : "dist";
const signingEnabled = process.env.DRUMSHEET_ENABLE_SIGNING === "true";
const supportedProfiles = new Set(["full", "compact", "lean", "release"]);
if (!["pack", "dist"].includes(action)) {
  console.error("usage: node scripts/run-builder.js <pack|dist> <full|compact|lean|release>");
  process.exit(1);
}
if (!supportedProfiles.has(requestedProfile)) {
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

const stageScript = path.join(__dirname, "..", "..", "backend", "scripts", "stage_runtime_ffmpeg.py");
const pythonCommand = process.platform === "win32" ? "python" : "python3";
const stageResult = spawnSync(pythonCommand, [stageScript], {
  cwd: path.join(__dirname, "..", ".."),
  stdio: "inherit",
  shell: process.platform === "win32",
  env: process.env,
});

if (stageResult.error || stageResult.status !== 0) {
  if (stageResult.error) {
    console.error(`[run-builder] failed to stage ffmpeg runtime: ${stageResult.error.message}`);
  }
  process.exit(stageResult.status || 1);
}

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

process.exit(result.status || 0);
