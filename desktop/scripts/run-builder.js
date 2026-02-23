#!/usr/bin/env node
const path = require("path");
const { spawnSync } = require("child_process");

const [, , target = "dist", profileArg] = process.argv;
const profile = (profileArg || process.env.DRUMSHEET_DIST_PROFILE || "full").toLowerCase();
const action = target === "pack" ? "pack" : "dist";
if (!["pack", "dist"].includes(action)) {
  console.error("usage: node scripts/run-builder.js <pack|dist> <full|lean>");
  process.exit(1);
}

const command = process.platform === "win32"
  ? path.join(__dirname, "..", "node_modules", ".bin", "electron-builder.cmd")
  : path.join(__dirname, "..", "node_modules", ".bin", "electron-builder");
const args = ["--config", path.join(__dirname, "..", "electron-builder.config.js")];
if (action === "pack") {
  args.unshift("--dir");
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
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status || 0);
