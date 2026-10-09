import test from "node:test";
import assert from "node:assert/strict";
import Module from "node:module";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const preloadPath = path.resolve(process.cwd(), "preload.js");

test("preload fetches the backend session token from Electron IPC", async () => {
  const calls = [];
  let exposed = null;
  const originalLoad = Module._load;

  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "electron") {
      return {
        contextBridge: {
          exposeInMainWorld(name, value) {
            exposed = { name, value };
          },
        },
        ipcRenderer: {
          sendSync(channel) {
            calls.push(channel);
            if (channel === "get-app-version") {
              return "0.1.27";
            }
            if (channel === "get-session-token") {
              return "token-123";
            }
            throw new Error(`unexpected channel: ${channel}`);
          },
          invoke(...args) { calls.push(args); },
          on() {},
          removeListener() {},
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };

  delete require.cache[preloadPath];
  try {
    require(preloadPath);
  } finally {
    Module._load = originalLoad;
    delete require.cache[preloadPath];
  }

  assert.ok(exposed, "preload should expose the bridge API");
  assert.equal(exposed.name, "drumSheetAPI");
  assert.equal(Object.hasOwn(exposed.value, "apiToken"), false);
  assert.equal(typeof exposed.value.requestJson, "function");
  assert.deepEqual(calls, ["get-app-version", "get-session-token"]);
  const saveOptions = { sourcePath: "/tmp/score.pdf", suggestedName: "score", locale: "ko" };
  exposed.value.savePdfAs(saveOptions);
  assert.deepEqual(calls.at(-1), ["save-pdf-as", saveOptions]);
});

test("preload exposes getPathForFile through Electron webUtils", async () => {
  let exposed = null;
  const originalLoad = Module._load;

  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "electron") {
      return {
        contextBridge: {
          exposeInMainWorld(name, value) {
            exposed = { name, value };
          },
        },
        ipcRenderer: {
          sendSync(channel) {
            if (channel === "get-app-version") {
              return "0.1.27";
            }
            if (channel === "get-session-token") {
              return "";
            }
            throw new Error(`unexpected channel: ${channel}`);
          },
          invoke() {},
          on() {},
          removeListener() {},
        },
        webUtils: {
          getPathForFile(file) {
            return file?.path || "";
          },
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };

  delete require.cache[preloadPath];
  try {
    require(preloadPath);
  } finally {
    Module._load = originalLoad;
    delete require.cache[preloadPath];
  }

  assert.ok(exposed, "preload should expose the bridge API");
  const resolved = exposed.value.getPathForFile({ path: "/tmp/drop-source.webm" });
  assert.equal(resolved, "/tmp/drop-source.webm");
});

test("preload reads protected job assets with the session token in a header", async () => {
  let exposed = null;
  const fetchCalls = [];
  const previousFetch = globalThis.fetch;
  const originalLoad = Module._load;

  globalThis.fetch = async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      headers: { get: (name) => (String(name).toLowerCase() === "content-type" ? "image/png" : "") },
      async arrayBuffer() {
        return new Uint8Array([4, 5, 6]).buffer;
      },
    };
  };

  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "electron") {
      return {
        contextBridge: {
          exposeInMainWorld(name, value) {
            exposed = { name, value };
          },
        },
        ipcRenderer: {
          sendSync(channel) {
            if (channel === "get-app-version") {
              return "0.1.27";
            }
            if (channel === "get-session-token") {
              return "token-123";
            }
            throw new Error(`unexpected channel: ${channel}`);
          },
          invoke() {},
          on() {},
          removeListener() {},
        },
        webUtils: {
          getPathForFile(file) {
            return file?.path || "";
          },
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };

  delete require.cache[preloadPath];
  try {
    require(preloadPath);
    const asset = await exposed.value.readJobAsset("/jobs-files/_preview/frame.png");

    assert.equal(asset.contentType, "image/png");
    assert.equal(asset.bytes.byteLength, 3);
    assert.equal(fetchCalls[0].url, "http://127.0.0.1:8000/jobs-files/_preview/frame.png");
    assert.equal(fetchCalls[0].options.headers["X-DrumSheet-Token"], "token-123");
    assert.doesNotMatch(fetchCalls[0].url, /token-123/);
  } finally {
    globalThis.fetch = previousFetch;
    Module._load = originalLoad;
    delete require.cache[preloadPath];
  }
});

test("preload sends JSON API requests with the session token in a header", async () => {
  let exposed = null;
  const fetchCalls = [];
  const previousFetch = globalThis.fetch;
  const originalLoad = Module._load;

  globalThis.fetch = async (url, options = {}) => {
    fetchCalls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      async json() {
        return { job_id: "job-1" };
      },
    };
  };

  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "electron") {
      return {
        contextBridge: {
          exposeInMainWorld(name, value) {
            exposed = { name, value };
          },
        },
        ipcRenderer: {
          sendSync(channel) {
            if (channel === "get-app-version") {
              return "0.1.27";
            }
            if (channel === "get-session-token") {
              return "token-123";
            }
            throw new Error(`unexpected channel: ${channel}`);
          },
          invoke() {},
          on() {},
          removeListener() {},
        },
        webUtils: {
          getPathForFile(file) {
            return file?.path || "";
          },
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };

  delete require.cache[preloadPath];
  try {
    require(preloadPath);
    const result = await exposed.value.requestJson("/jobs", {
      method: "POST",
      body: JSON.stringify({ source_type: "file" }),
    });

    assert.deepEqual(result, { ok: true, status: 200, data: { job_id: "job-1" } });
    assert.equal(fetchCalls[0].url, "http://127.0.0.1:8000/jobs");
    assert.equal(fetchCalls[0].options.method, "POST");
    assert.equal(fetchCalls[0].options.headers["Content-Type"], "application/json");
    assert.equal(fetchCalls[0].options.headers["X-DrumSheet-Token"], "token-123");
    assert.doesNotMatch(fetchCalls[0].url, /token-123/);
  } finally {
    globalThis.fetch = previousFetch;
    Module._load = originalLoad;
    delete require.cache[preloadPath];
  }
});

test("preload honours a caller's own timeout and turns a timeout into a readable Error", async () => {
  let exposed = null;
  const signals = [];
  const previousFetch = globalThis.fetch;
  const previousTimeout = AbortSignal.timeout;
  const originalLoad = Module._load;
  const timeouts = [];
  AbortSignal.timeout = (ms) => { timeouts.push(ms); return previousTimeout.call(AbortSignal, ms); };
  let failWith = null;
  globalThis.fetch = async (url, options = {}) => {
    signals.push(options.signal);
    if (failWith) throw failWith;
    return { ok: true, status: 200, async json() { return {}; } };
  };
  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "electron") {
      return {
        contextBridge: { exposeInMainWorld(name, value) { exposed = { name, value }; } },
        ipcRenderer: {
          sendSync(channel) { return channel === "get-app-version" ? "0.1.27" : "token-123"; },
          invoke() {}, on() {}, removeListener() {},
        },
        webUtils: { getPathForFile: () => "" },
      };
    }
    return originalLoad(request, parent, isMain);
  };
  delete require.cache[preloadPath];
  try {
    require(preloadPath);
    await exposed.value.requestJson("/jobs/job-1");
    await exposed.value.requestJson("/jobs/job-1/review-export", { method: "POST", body: "{}", timeoutMs: 20 * 60 * 1000 });
    assert.deepEqual(timeouts, [30000, 20 * 60 * 1000]);

    // fetch rejects with a DOMException, which contextBridge would hand to the page as {}
    failWith = new DOMException("The operation was aborted due to timeout", "TimeoutError");
    await assert.rejects(
      exposed.value.requestJson("/jobs/job-1/review-export", { method: "POST", body: "{}", timeoutMs: 1000 }),
      (error) => Object.getPrototypeOf(error) === Error.prototype && /^REQUEST_TIMEOUT: POST \/jobs\/job-1\/review-export/.test(error.message),
    );
    failWith = new TypeError("Failed to fetch");
    await assert.rejects(exposed.value.requestJson("/jobs/job-1"), (error) => error.message === "REQUEST_FAILED: Failed to fetch");
  } finally {
    globalThis.fetch = previousFetch;
    AbortSignal.timeout = previousTimeout;
    Module._load = originalLoad;
    delete require.cache[preloadPath];
  }
});
