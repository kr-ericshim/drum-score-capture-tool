import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const config = require("../electron-builder.config.js");

test("electron builder packages only desktop runtime files", () => {
  assert.deepEqual(config.files, [
    "main.js",
    "preload.js",
    "renderer-entry.js",
    "backend-launch-policy.js",
    "backend-job-paths.js",
    "save-pdf-as.js",
    "package.json",
    "renderer-v2/index.html",
    "renderer-v2/src/**/*",
    "!renderer-v2/src/tests{,/**/*}",
  ]);
  assert.equal(config.files.includes("tests/**/*"), false);
  assert.equal(config.files.includes("scripts/**/*"), false);
  assert.equal(config.files.includes("package-lock.json"), false);
});

test("electron builder keeps only product-supported Electron locales", () => {
  assert.deepEqual(config.electronLanguages, ["en", "ko"]);
});
