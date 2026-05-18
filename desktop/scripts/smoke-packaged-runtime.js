#!/usr/bin/env node
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const {
  findNewestPackagedBackendMain,
  findPackagedBackendToolExecutable,
  findPackagedRuntimeExecutable,
} = require("./validate-packaged-release");

const port = Number(process.env.DRUMSHEET_PACKAGED_SMOKE_PORT || 8124);
const timeoutMs = Number(process.env.DRUMSHEET_PACKAGED_SMOKE_TIMEOUT_MS || 45000);
const sessionToken = process.env.DRUMSHEET_PACKAGED_SMOKE_TOKEN || "packaged-runtime-smoke-token";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function requestHealth() {
  return new Promise((resolve) => {
    const request = http.get(
      {
        hostname: "127.0.0.1",
        port,
        path: "/health",
        timeout: 2000,
      },
      (response) => {
        response.resume();
        resolve(response.statusCode && response.statusCode >= 200 && response.statusCode < 300);
      },
    );
    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

function requestJson(method, pathname, body) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? "" : JSON.stringify(body);
    const request = http.request(
      {
        hostname: "127.0.0.1",
        port,
        path: pathname,
        method,
        timeout: 5000,
        headers: {
          "x-drumsheet-token": sessionToken,
          ...(payload
            ? {
              "Content-Type": "application/json",
              "Content-Length": Buffer.byteLength(payload),
            }
            : {}),
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let data = {};
          if (text.trim()) {
            try {
              data = JSON.parse(text);
            } catch (error) {
              reject(new Error(`Invalid JSON from ${pathname}: ${text.slice(0, 160)}`));
              return;
            }
          }
          resolve({ statusCode: response.statusCode || 0, data });
        });
      },
    );
    request.on("timeout", () => {
      request.destroy(new Error(`Timed out requesting ${pathname}`));
    });
    request.on("error", reject);
    if (payload) {
      request.write(payload);
    }
    request.end();
  });
}

function runCommand(command, args, { timeoutMs: commandTimeoutMs = 15000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    const output = [];
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`${path.basename(command)} timed out`));
    }, commandTimeoutMs);

    child.stdout.on("data", (chunk) => output.push(String(chunk || "")));
    child.stderr.on("data", (chunk) => output.push(String(chunk || "")));
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(output.join(""));
        return;
      }
      reject(new Error(`${path.basename(command)} exited with ${code}: ${output.join("").trim()}`));
    });
  });
}

async function createFixtureVideo({ packagedBackendMainPath, jobsDir }) {
  const ffmpegPath = findPackagedBackendToolExecutable({
    packagedBackendMainPath,
    toolName: "ffmpeg",
  });
  assert(fs.existsSync(ffmpegPath), `Packaged ffmpeg is missing: ${ffmpegPath}`);

  const sourcePath = path.join(jobsDir, "packaged-smoke-source.mp4");
  await runCommand(ffmpegPath, [
    "-y",
    "-f",
    "lavfi",
    "-i",
    "testsrc=size=640x360:rate=5:duration=1",
    "-pix_fmt",
    "yuv420p",
    sourcePath,
  ]);
  assert(fs.existsSync(sourcePath), `Fixture video was not created: ${sourcePath}`);
  return sourcePath;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function smokePackagedRuntime() {
  const packagedBackendMainPath = findNewestPackagedBackendMain();
  const runtimeExecutablePath = findPackagedRuntimeExecutable({ packagedBackendMainPath });
  assert(
    fs.existsSync(runtimeExecutablePath),
    `Packaged backend runtime is missing: ${runtimeExecutablePath}`,
  );

  const jobsDir = fs.mkdtempSync(path.join(os.tmpdir(), "drumsheet-packaged-runtime-"));
  const logs = [];
  const child = spawn(runtimeExecutablePath, [], {
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
      if (await requestHealth()) {
        console.log("[smoke-packaged-runtime] packaged backend responded to /health");
        console.log(`- runtime executable: ${path.relative(path.resolve(__dirname, "..", ".."), runtimeExecutablePath)}`);
        break;
      }
      if (exitCode !== null) {
        throw new Error(`Packaged backend exited before /health became ready (exit: ${exitCode})`);
      }
      await wait(750);
    }
    if (Date.now() >= deadline) {
      throw new Error(`Timed out waiting for packaged backend /health on port ${port}`);
    }

    const runtime = await requestJson("GET", "/runtime");
    assert(runtime.statusCode >= 200 && runtime.statusCode < 300, `/runtime failed with ${runtime.statusCode}`);
    assert(runtime.data && runtime.data.app_version, "/runtime did not return app_version");

    const fixturePath = await createFixtureVideo({ packagedBackendMainPath, jobsDir });
    const preview = await requestJson("POST", "/preview/frame", {
      source_type: "file",
      file_path: fixturePath,
      start_sec: 0,
    });
    assert(preview.statusCode >= 200 && preview.statusCode < 300, `/preview/frame failed with ${preview.statusCode}`);
    assert(preview.data && preview.data.image_path, "/preview/frame did not return image_path");
    assert(fs.existsSync(preview.data.image_path), `Preview frame is missing: ${preview.data.image_path}`);

    console.log("- runtime metadata: ok");
    console.log("- preview frame extraction: ok");
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
  smokePackagedRuntime().catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[smoke-packaged-runtime] ${message}`);
    process.exit(1);
  });
}

module.exports = {
  createFixtureVideo,
  requestHealth,
  requestJson,
  smokePackagedRuntime,
};
