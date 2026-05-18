import test from "node:test";
import assert from "node:assert/strict";
import EventEmitter from "node:events";
import Module from "node:module";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const mainPath = require.resolve("../main.js");
const actualChildProcess = require("node:child_process");

function nextTick() {
  return new Promise((resolve) => setImmediate(resolve));
}

test("main process startup contract loads renderer-v2 through the isolated preload bridge", async () => {
  const originalLoad = Module._load;
  const previousFetch = globalThis.fetch;
  const windows = [];
  const ipcHandles = new Map();
  const ipcSyncChannels = [];
  const spawnCalls = [];
  let healthChecks = 0;

  class FakeBrowserWindow extends EventEmitter {
    constructor(options) {
      super();
      this.options = options;
      this.loadedFile = "";
      this.webContents = new EventEmitter();
      this.webContents.send = () => {};
      windows.push(this);
    }

    loadFile(filePath) {
      this.loadedFile = filePath;
    }

    isDestroyed() {
      return false;
    }

    setAlwaysOnTop(enabled) {
      this.alwaysOnTop = Boolean(enabled);
    }

    isAlwaysOnTop() {
      return Boolean(this.alwaysOnTop);
    }
  }

  const app = new EventEmitter();
  app.isPackaged = false;
  app.isReady = () => true;
  app.getVersion = () => "0.1.27";
  app.quit = () => {};
  app.whenReady = () => Promise.resolve();

  const electronMock = {
    app,
    BrowserWindow: FakeBrowserWindow,
    clipboard: { writeText() {} },
    dialog: {
      async showOpenDialog() {
        return { canceled: true, filePaths: [] };
      },
      showErrorBox() {},
    },
    ipcMain: {
      handle(channel, handler) {
        ipcHandles.set(channel, handler);
      },
      on(channel, handler) {
        ipcSyncChannels.push(channel);
        app.on(`ipc:${channel}`, handler);
      },
    },
    shell: { openPath: async () => "" },
  };

  const fakeBackend = new EventEmitter();
  fakeBackend.stdout = new EventEmitter();
  fakeBackend.stderr = new EventEmitter();
  fakeBackend.kill = () => {
    fakeBackend.emit("exit", 0);
  };

  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === "electron") {
      return electronMock;
    }
    if (request === "child_process") {
      return {
        ...actualChildProcess,
        spawn(command, args, options) {
          spawnCalls.push({ command, args, options });
          return fakeBackend;
        },
        spawnSync() {
          return { status: 0, stdout: `${process.execPath}\n` };
        },
      };
    }
    return originalLoad(request, parent, isMain);
  };

  globalThis.fetch = async (url) => {
    healthChecks += 1;
    assert.equal(String(url), "http://127.0.0.1:8000/health");
    return { ok: true };
  };

  delete require.cache[mainPath];
  try {
    require(mainPath);
    await nextTick();
    await nextTick();

    assert.equal(windows.length, 1);
    assert.equal(windows[0].loadedFile, path.resolve(process.cwd(), "renderer-v2", "index.html"));
    assert.equal(windows[0].options.webPreferences.preload, path.resolve(process.cwd(), "preload.js"));
    assert.equal(windows[0].options.webPreferences.contextIsolation, true);
    assert.equal(windows[0].options.webPreferences.nodeIntegration, false);
    assert.equal(ipcHandles.has("get-backend-state"), true);
    assert.deepEqual(ipcSyncChannels, ["get-app-version", "get-session-token"]);
    assert.equal(spawnCalls.length, 1);
    assert.equal(spawnCalls[0].options.env.DRUMSHEET_SESSION_TOKEN.length, 48);
    assert.equal(healthChecks, 1);
  } finally {
    Module._load = originalLoad;
    globalThis.fetch = previousFetch;
    delete require.cache[mainPath];
  }
});
