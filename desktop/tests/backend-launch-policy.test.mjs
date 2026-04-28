import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const policy = require("../backend-launch-policy.js");

function writeFile(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, "x");
}

test("decidePackagedBackendLaunchMode prefers python when the frozen runtime is older than bundled source", () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "backend-launch-policy-"));
  const runtimePath = path.join(workspace, "runtime", "drumsheet-backend");
  const sourcePath = path.join(workspace, "app", "main.py");

  writeFile(runtimePath);
  writeFile(sourcePath);
  fs.utimesSync(runtimePath, new Date("2026-03-13T09:00:00.000Z"), new Date("2026-03-13T09:00:00.000Z"));
  fs.utimesSync(sourcePath, new Date("2026-04-20T02:30:00.000Z"), new Date("2026-04-20T02:30:00.000Z"));

  const decision = policy.decidePackagedBackendLaunchMode({
    runtimeExecutablePath: runtimePath,
    sourceEntryPath: sourcePath,
    pythonAvailable: true,
  });

  assert.equal(decision.mode, "python");
  assert.equal(decision.reason, "runtime-stale");
  assert.equal(decision.staleRuntime, true);
});

test("decidePackagedBackendLaunchMode keeps the frozen runtime when no python fallback is available", () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "backend-launch-policy-"));
  const runtimePath = path.join(workspace, "runtime", "drumsheet-backend");
  const sourcePath = path.join(workspace, "app", "main.py");

  writeFile(runtimePath);
  writeFile(sourcePath);
  fs.utimesSync(runtimePath, new Date("2026-03-13T09:00:00.000Z"), new Date("2026-03-13T09:00:00.000Z"));
  fs.utimesSync(sourcePath, new Date("2026-04-20T02:30:00.000Z"), new Date("2026-04-20T02:30:00.000Z"));

  const decision = policy.decidePackagedBackendLaunchMode({
    runtimeExecutablePath: runtimePath,
    sourceEntryPath: sourcePath,
    pythonAvailable: false,
  });

  assert.equal(decision.mode, "runtime");
  assert.equal(decision.reason, "runtime-stale-no-python");
  assert.equal(decision.staleRuntime, true);
});

test("decidePackagedBackendLaunchMode keeps the frozen runtime when it is at least as new as bundled source", () => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "backend-launch-policy-"));
  const runtimePath = path.join(workspace, "runtime", "drumsheet-backend");
  const sourcePath = path.join(workspace, "app", "main.py");

  writeFile(runtimePath);
  writeFile(sourcePath);
  fs.utimesSync(runtimePath, new Date("2026-04-20T02:30:00.000Z"), new Date("2026-04-20T02:30:00.000Z"));
  fs.utimesSync(sourcePath, new Date("2026-04-20T02:29:59.000Z"), new Date("2026-04-20T02:29:59.000Z"));

  const decision = policy.decidePackagedBackendLaunchMode({
    runtimeExecutablePath: runtimePath,
    sourceEntryPath: sourcePath,
    pythonAvailable: true,
  });

  assert.equal(decision.mode, "runtime");
  assert.equal(decision.reason, "runtime-current");
  assert.equal(decision.staleRuntime, false);
});
