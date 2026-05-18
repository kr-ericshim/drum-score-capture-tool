#!/usr/bin/env node

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const testsDir = path.resolve(__dirname, "..", "tests");
const testFiles = fs
  .readdirSync(testsDir)
  .filter((name) => name.endsWith(".test.mjs") || name.endsWith(".test.cjs"))
  .sort()
  .map((name) => path.join(testsDir, name));

if (testFiles.length === 0) {
  console.error(`[run-desktop-node-tests] no test files found in ${testsDir}`);
  process.exit(1);
}

const result = spawnSync(process.execPath, ["--test", ...testFiles], {
  stdio: "inherit",
});

if (result.error) {
  console.error(`[run-desktop-node-tests] ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
