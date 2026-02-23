#!/usr/bin/env node
const path = require("path");
const fs = require("fs");
const { spawnSync } = require("child_process");

const [, , target = "dist", profileArg] = process.argv;
const profile = (profileArg || process.env.DRUMSHEET_DIST_PROFILE || "full").toLowerCase();
const action = target === "pack" ? "pack" : "dist";
const supportedProfiles = new Set(["full", "compact", "lean"]);
if (!["pack", "dist"].includes(action)) {
  console.error("usage: node scripts/run-builder.js <pack|dist> <full|compact|lean>");
  process.exit(1);
}
if (!supportedProfiles.has(profile)) {
  console.error(`[run-builder] unsupported profile: ${profile}`);
  console.error("supported profiles: full | compact | lean");
  process.exit(1);
}

const localBuilder = process.platform === "win32"
  ? path.join(__dirname, "..", "node_modules", ".bin", "electron-builder.cmd")
  : path.join(__dirname, "..", "node_modules", ".bin", "electron-builder");

let command = localBuilder;
let args = ["--config", path.join(__dirname, "..", "electron-builder.config.js")];
if (action === "pack") {
  args.unshift("--dir");
}

if (!fs.existsSync(localBuilder)) {
  console.warn(`[run-builder] local electron-builder executable not found: ${localBuilder}`);
  command = "npx";
  args = ["electron-builder", ...args];
}

const result = spawnSync(command, args, {
  cwd: path.join(__dirname, ".."),
  stdio: "inherit",
  shell: process.platform === "win32",
  env: {
    ...process.env,
    DRUMSHEET_DIST_PROFILE: profile,
  },
});

if (result.error) {
  const code = result.error.code ? ` (code: ${result.error.code})` : "";
  console.error(`[run-builder] failed to execute ${command}: ${result.error.message}${code}`);
  console.error("[run-builder] args:", args.join(" "));
  process.exit(1);
}

process.exit(result.status || 0);
