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

// A page-turn video: three distinct two-system pages, each shown long enough to be
// placed by the clean-reflow pipeline (displays under ~1.5 s are listed short).
const fixture = {
  width: 960,
  height: 360,
  rate: 5,
  pageSeconds: 4,
  pages: 3,
  staffGap: 12,
  systemTops: [110, 240],
  staffLeft: 60,
  staffRight: 900,
  barsPerSystem: 4,
  slotsPerBar: 8,
};
fixture.durationSec = fixture.pages * fixture.pageSeconds;
fixture.roi = [[20, 20], [fixture.width - 20, 20], [fixture.width - 20, fixture.height - 20], [20, fixture.height - 20]];

function fixtureFilterGraph() {
  const { staffGap: gap, staffLeft: left, staffRight: right, barsPerSystem, slotsPerBar } = fixture;
  const barWidth = (right - left) / barsPerSystem;
  const drawing = [`color=c=white:size=${fixture.width}x${fixture.height}:rate=${fixture.rate}:duration=${fixture.durationSec}`];
  const box = (x, y, w, h, enable) => {
    drawing.push(`drawbox=x=${Math.round(x)}:y=${Math.round(y)}:w=${w}:h=${h}:color=black:t=fill${enable ? `:enable='${enable}'` : ""}`);
  };
  for (const top of fixture.systemTops) {
    for (let line = 0; line < 5; line += 1) {
      box(left, top + line * gap, right - left, 2);
    }
    for (let bar = 0; bar <= barsPerSystem; bar += 1) {
      box(left + bar * barWidth, top, 2, 4 * gap + 2);
    }
  }
  for (let page = 0; page < fixture.pages; page += 1) {
    const enable = `between(t,${page * fixture.pageSeconds},${(page + 1) * fixture.pageSeconds - 0.001})`;
    fixture.systemTops.forEach((top, system) => {
      for (let bar = 0; bar < barsPerSystem; bar += 1) {
        for (let slot = 0; slot < slotsPerBar; slot += 1) {
          // Each page has its own groove so its displays are distinct content.
          const k = page * 97 + system * 31 + bar * 11 + slot * 7;
          if ((k * 5 + page) % 3 === 0) {
            continue;
          }
          const x = left + bar * barWidth + ((slot + 0.5) * barWidth) / slotsPerBar - 6;
          const line = [1.5, 2.5, 3.5][(k + slot + page) % 3];
          const y = top + line * gap - 4;
          box(x, y, 12, 9, enable);
          box(x + 10, top - 2 * gap, 2, y - (top - 2 * gap) + 4, enable);
        }
      }
    });
  }
  return drawing.join(",");
}

async function createFixtureVideo({ packagedBackendMainPath, jobsDir, ffmpegPath: ffmpegOverride }) {
  const ffmpegPath = ffmpegOverride || findPackagedBackendToolExecutable({
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
    fixtureFilterGraph(),
    "-c:v",
    "mpeg4",
    "-q:v",
    "2",
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
  const packagedFfmpegPath = findPackagedBackendToolExecutable({
    packagedBackendMainPath,
    toolName: "ffmpeg",
  });
  const packagedFfprobePath = findPackagedBackendToolExecutable({
    packagedBackendMainPath,
    toolName: "ffprobe",
  });
  assert(
    fs.existsSync(runtimeExecutablePath),
    `Packaged backend runtime is missing: ${runtimeExecutablePath}`,
  );
  assert(fs.existsSync(packagedFfmpegPath), `Packaged ffmpeg is missing: ${packagedFfmpegPath}`);
  assert(fs.existsSync(packagedFfprobePath), `Packaged ffprobe is missing: ${packagedFfprobePath}`);

  const jobsDir = fs.mkdtempSync(path.join(os.tmpdir(), "drumsheet-packaged-runtime-"));
  const logs = [];
  const child = spawn(runtimeExecutablePath, [], {
    env: {
      ...process.env,
      DRUMSHEET_PORT: String(port),
      DRUMSHEET_JOBS_DIR: jobsDir,
      DRUMSHEET_SESSION_TOKEN: sessionToken,
      DRUMSHEET_FFMPEG_BIN: packagedFfmpegPath,
      DRUMSHEET_FFPROBE_BIN: packagedFfprobePath,
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

    const created = await requestJson("POST", "/jobs", {
      source_type: "file",
      file_path: fixturePath,
      options: {
        extract: { fps: 1, start_sec: 0, end_sec: fixture.durationSec },
        detect: { roi: fixture.roi, auto_fit: false },
        rectify: { auto: false },
        stitch: { enable: false },
        upscale: { enable: false },
        export: { formats: ["png", "pdf"] },
      },
    });
    assert(created.statusCode === 200 && created.data.job_id, `Capture job creation failed: ${JSON.stringify(created)}`);
    const jobDeadline = Date.now() + timeoutMs;
    let completed = null;
    while (Date.now() < jobDeadline) {
      const status = await requestJson("GET", `/jobs/${created.data.job_id}`);
      assert(status.statusCode === 200, `Capture status failed: ${JSON.stringify(status)}`);
      assert(!["failed", "error", "cancelled"].includes(status.data.status), `Capture job failed: ${JSON.stringify(status.data)}`);
      if (status.data.status === "done") {
        completed = status.data;
        break;
      }
      await wait(500);
    }
    assert(completed, "Timed out waiting for packaged capture/export job");
    const result = completed.result || {};
    assert(result.output_model === "clean_reflow_v1", `Capture job did not use clean reflow: ${result.output_model}`);
    const placed = (result.reflow?.systems || []).filter((system) => system.included).length;
    const expected = fixture.pages * fixture.systemTops.length;
    assert(placed === expected, `Clean reflow placed ${placed} systems, expected ${expected}`);
    const files = await requestJson("GET", `/jobs/${created.data.job_id}/files`);
    assert(files.statusCode === 200, `Capture files failed: ${JSON.stringify(files)}`);
    assert(files.data.images?.length > 0, "Capture job returned no images");
    for (const file of files.data.images) {
      assert(fs.readFileSync(file).subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])), `Invalid PNG output: ${file}`);
    }
    assert(files.data.pdf && fs.readFileSync(files.data.pdf).subarray(0, 5).toString() === "%PDF-", "Capture job did not produce a PDF file");

    console.log("- runtime metadata: ok");
    console.log("- preview frame extraction: ok");
    console.log(`- synthetic score video clean-reflow capture (${placed} systems) and PNG/PDF export: ok`);
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
  fixture,
  requestHealth,
  requestJson,
  smokePackagedRuntime,
};
