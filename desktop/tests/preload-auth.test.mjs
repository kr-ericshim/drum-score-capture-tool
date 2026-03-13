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
          invoke() {},
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
  assert.equal(exposed.value.apiToken, "token-123");
  assert.deepEqual(calls, ["get-app-version", "get-session-token"]);
});
