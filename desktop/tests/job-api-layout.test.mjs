import test from "node:test";
import assert from "node:assert/strict";

const domNodes = new Map();

function setNode(id, value) {
  domNodes.set(id, value);
  return value;
}

Object.defineProperty(globalThis, "window", {
  configurable: true,
  value: {
    localStorage: {
      getItem() {
        return null;
      },
      setItem() {},
    },
  },
});

Object.defineProperty(globalThis, "document", {
  configurable: true,
  value: {
    documentElement: { lang: "en" },
    getElementById(id) {
      return domNodes.get(id) || null;
    },
    querySelector(selector) {
      if (selector === 'input[name="sourceType"]:checked') {
        return { value: "file" };
      }
      return null;
    },
    querySelectorAll(selector) {
      if (selector === ".format:checked") {
        return [{ value: "pdf" }];
      }
      return [];
    },
  },
});

Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    language: "en-US",
    userLanguage: "en-US",
  },
});

const { buildPayload } = await import("../renderer/modules/job-api.js");

test("buildPayload infers page_turn layout for near-square roi in legacy fallback", () => {
  domNodes.clear();
  setNode("captureSensitivity", { value: "medium" });
  setNode("enableStitch", { checked: false });
  setNode("roiInput", { value: JSON.stringify([[10, 10], [510, 10], [510, 500], [10, 500]]) });
  setNode("overlapThreshold", { value: "0.2" });
  setNode("enableUpscale", { checked: false });
  setNode("upscaleFactor", { value: "2.0" });
  setNode("startSec", { value: "" });
  setNode("endSec", { value: "" });
  setNode("filePath", { value: "/tmp/demo.mp4" });

  const payload = buildPayload();

  assert.equal(payload.options.detect.layout_hint, "page_turn");
  assert.equal(payload.options.stitch.layout_hint, "page_turn");
});
