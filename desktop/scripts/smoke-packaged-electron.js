#!/usr/bin/env node
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

const appName = "Drum Sheet Capture";
const port = Number(process.env.DRUMSHEET_PACKAGED_ELECTRON_SMOKE_PORT || 8125);
const timeoutMs = Number(process.env.DRUMSHEET_PACKAGED_ELECTRON_SMOKE_TIMEOUT_MS || 60000);
const sessionToken = process.env.DRUMSHEET_PACKAGED_ELECTRON_SMOKE_TOKEN || "packaged-electron-smoke-token";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function distRoot() {
  return path.resolve(__dirname, "..", "..", "dist");
}

function candidateExecutables() {
  const root = distRoot();
  if (process.platform === "darwin") {
    return [
      path.join(root, "mac-arm64", `${appName}.app`, "Contents", "MacOS", appName),
      path.join(root, "mac", `${appName}.app`, "Contents", "MacOS", appName),
    ];
  }
  if (process.platform === "win32") {
    return [
      path.join(root, "win-unpacked", `${appName}.exe`),
      path.join(root, "win-ia32-unpacked", `${appName}.exe`),
    ];
  }
  if (process.platform === "linux") {
    return [
      path.join(root, "linux-unpacked", appName),
    ];
  }
  return [];
}

function findPackagedElectronExecutable() {
  const executablePath = candidateExecutables().find((candidate) => fs.existsSync(candidate));
  assert(
    executablePath,
    `Packaged Electron app is missing. Checked: ${candidateExecutables().join(", ")}`,
  );
  return executablePath;
}

function requestJson(pathname) {
  return new Promise((resolve) => {
    const request = http.get(
      {
        hostname: "127.0.0.1",
        port,
        path: pathname,
        timeout: 2500,
        headers: {
          "x-drumsheet-token": sessionToken,
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let data = {};
          try {
            data = text.trim() ? JSON.parse(text) : {};
          } catch (_) {
            data = {};
          }
          resolve({ ok: Boolean(response.statusCode && response.statusCode >= 200 && response.statusCode < 300), data });
        });
      },
    );
    request.on("timeout", () => {
      request.destroy();
      resolve({ ok: false, data: {} });
    });
    request.on("error", () => resolve({ ok: false, data: {} }));
  });
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function smokePackagedElectron() {
  const executablePath = findPackagedElectronExecutable();
  const jobsDir = fs.mkdtempSync(path.join(os.tmpdir(), "drumsheet-packaged-electron-"));
  const logs = [];
  const child = spawn(executablePath, [], {
    env: {
      ...process.env,
      DRUMSHEET_PORT: String(port),
      DRUMSHEET_JOBS_DIR: jobsDir,
      DRUMSHEET_SESSION_TOKEN: sessionToken,
    },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  const rememberLog = (chunk) => {
    logs.push(String(chunk || ""));
    while (logs.join("").length > 12000) {
      logs.shift();
    }
  };
  child.stdout.on("data", rememberLog);
  child.stderr.on("data", rememberLog);

  let exitCode = null;
  child.on("exit", (code) => {
    exitCode = code;
  });

  const deadline = Date.now() + timeoutMs;
  try {
    while (Date.now() < deadline) {
      const health = await requestJson("/health");
      if (health.ok) {
        const runtime = await requestJson("/runtime");
        assert(runtime.ok, "Packaged Electron app started backend but /runtime failed");
        assert(runtime.data && runtime.data.app_version, "/runtime did not return app_version");
        console.log("[smoke-packaged-electron] packaged app started backend successfully");
        console.log(`- electron executable: ${path.relative(path.resolve(__dirname, "..", ".."), executablePath)}`);
        console.log("- runtime metadata: ok");
        return;
      }
      if (exitCode !== null) {
        throw new Error(`Packaged Electron app exited before backend became ready (exit: ${exitCode})`);
      }
      await wait(1000);
    }
    throw new Error(`Timed out waiting for packaged Electron app backend on port ${port}`);
  } catch (error) {
    const output = logs.join("").trim();
    if (output) {
      console.error(output);
    }
    throw error;
  } finally {
    try {
      child.kill();
    } catch (_) {
      // ignore
    }
    fs.rmSync(jobsDir, { recursive: true, force: true });
  }
}

if (require.main === module) {
  smokePackagedElectron().catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[smoke-packaged-electron] ${message}`);
    process.exit(1);
  });
}

module.exports = {
  candidateExecutables,
  findPackagedElectronExecutable,
  requestJson,
  smokePackagedElectron,
};
