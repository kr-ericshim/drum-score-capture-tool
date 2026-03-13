import test from "node:test";
import assert from "node:assert/strict";

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
  },
});

Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    language: "en-US",
    userLanguage: "en-US",
  },
});

const { buildApiHeaders } = await import("../renderer/modules/job-api.js");

test("buildApiHeaders adds the session token when present", () => {
  assert.deepEqual(buildApiHeaders("token-123"), {
    "X-DrumSheet-Token": "token-123",
  });
});

test("buildApiHeaders preserves explicit headers and content type", () => {
  assert.deepEqual(
    buildApiHeaders("token-123", {
      "Content-Type": "application/json",
    }),
    {
      "Content-Type": "application/json",
      "X-DrumSheet-Token": "token-123",
    },
  );
});
