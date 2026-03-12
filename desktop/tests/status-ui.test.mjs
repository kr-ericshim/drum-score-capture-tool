import test from "node:test";
import assert from "node:assert/strict";

function installBrowserStubs() {
  const nodes = new Map();
  const document = {
    documentElement: { lang: "en" },
    getElementById(id) {
      if (!nodes.has(id)) {
        nodes.set(id, { textContent: "" });
      }
      return nodes.get(id);
    },
  };

  const storage = new Map();
  const window = {
    localStorage: {
      getItem(key) {
        return storage.has(key) ? storage.get(key) : null;
      },
      setItem(key, value) {
        storage.set(key, String(value));
      },
    },
  };

  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: document,
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: window,
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { language: "ko-KR", userLanguage: "ko-KR" },
  });
}

installBrowserStubs();

const { renderResultMeta } = await import("../renderer/modules/status-ui.js");

test("renderResultMeta prefers review candidates for capture preview paths", () => {
  const reviewCandidates = ["/tmp/upscaled-1.png", "/tmp/upscaled-2.png"];
  const result = renderResultMeta(
    {
      status: "done",
      result: {
        images: ["/tmp/page-1.png"],
        review_candidates: reviewCandidates,
        upscaled_frames: ["/tmp/upscaled-fallback.png"],
        stitched_frames: ["/tmp/stitched-fallback.png"],
        page_diagnostics: [{ page_index: 1, suspicious: false }],
      },
    },
    (status) => status,
  );

  assert.deepEqual(result.capturePaths, reviewCandidates);
  assert.deepEqual(result.pageDiagnostics, [{ page_index: 1, suspicious: false }]);
});

test("renderResultMeta falls back to upscaled or stitched paths when review candidates are missing", () => {
  const upscaledResult = renderResultMeta(
    {
      status: "done",
      result: {
        images: ["/tmp/page-1.png"],
        upscaled_frames: ["/tmp/upscaled-only.png"],
      },
    },
    (status) => status,
  );
  assert.deepEqual(upscaledResult.capturePaths, ["/tmp/upscaled-only.png"]);

  const stitchedResult = renderResultMeta(
    {
      status: "done",
      result: {
        images: ["/tmp/page-1.png"],
        stitched_frames: ["/tmp/stitched-only.png"],
      },
    },
    (status) => status,
  );
  assert.deepEqual(stitchedResult.capturePaths, ["/tmp/stitched-only.png"]);
});
