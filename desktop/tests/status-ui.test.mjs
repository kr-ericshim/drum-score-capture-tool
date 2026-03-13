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
  const diagnostics = [
    { page_index: 1, suspicious: false },
    { page_index: 2, suspicious: true },
  ];
  const result = renderResultMeta(
    {
      status: "done",
      result: {
        images: ["/tmp/page-1.png"],
        review_candidates: reviewCandidates,
        upscaled_frames: ["/tmp/upscaled-fallback.png"],
        stitched_frames: ["/tmp/stitched-fallback.png"],
        page_diagnostics: diagnostics,
      },
    },
    (status) => status,
  );

  assert.deepEqual(result.capturePaths, reviewCandidates);
  assert.deepEqual(result.pageDiagnostics, diagnostics);
  assert.deepEqual(result.thumbnailDiagnostics, diagnostics);
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

test("renderResultMeta uses preview images for PDF-only review results", () => {
  const result = renderResultMeta(
    {
      status: "done",
      result: {
        images: [],
        preview_images: ["/tmp/review-preview-1.png", "/tmp/review-preview-2.png"],
        review_candidates: ["/tmp/review-preview-1.png", "/tmp/review-preview-2.png"],
        page_diagnostics: [{ page_index: 1, suspicious: false }, { page_index: 2, suspicious: false }],
      },
    },
    (status) => status,
  );

  assert.equal(result.firstImagePath, "/tmp/review-preview-1.png");
  assert.equal(result.hasResultImage, true);
  assert.deepEqual(result.capturePaths, ["/tmp/review-preview-1.png", "/tmp/review-preview-2.png"]);
  assert.match(document.getElementById("resultMeta").textContent, /생성 페이지: 2장|Pages generated: 2/);
});

test("renderResultMeta prefers page diagnostics over duplicated image exports when counting pages", () => {
  const result = renderResultMeta(
    {
      status: "done",
      result: {
        images: [
          "/tmp/page-1.png",
          "/tmp/page-1.jpg",
          "/tmp/page-2.png",
          "/tmp/page-2.jpg",
        ],
        page_diagnostics: [{ page_index: 1, suspicious: false }, { page_index: 2, suspicious: false }],
      },
    },
    (status) => status,
  );

  assert.equal(result.imagePaths.length, 4);
  assert.match(document.getElementById("resultMeta").textContent, /생성 페이지: 2장|Pages generated: 2/);
});

test("renderResultMeta drops review diagnostics when capture candidates and page diagnostics do not align", () => {
  const result = renderResultMeta(
    {
      status: "done",
      result: {
        review_candidates: ["/tmp/capture-1.png", "/tmp/capture-2.png", "/tmp/capture-3.png"],
        images: ["/tmp/page-1.png", "/tmp/page-2.png"],
        page_diagnostics: [{ page_index: 1, suspicious: true }, { page_index: 2, suspicious: false }],
      },
    },
    (status) => status,
  );

  assert.deepEqual(result.capturePaths, ["/tmp/capture-1.png", "/tmp/capture-2.png", "/tmp/capture-3.png"]);
  assert.deepEqual(result.reviewDiagnostics, []);
  assert.deepEqual(result.thumbnailDiagnostics, []);
  assert.deepEqual(result.pageDiagnostics, [{ page_index: 1, suspicious: true }, { page_index: 2, suspicious: false }]);
});
