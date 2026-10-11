import test from "node:test";
import assert from "node:assert/strict";

import {
  createInitialSessionState, deriveCapturePages, deriveOriginalScreens, deriveOutputPages, jobRevision, roiAspect,
} from "../app/session/selectors.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { startReviewExport } from "../lib/api.js";

const ONE_LINE_ROI = [[37, 828], [1892, 828], [1892, 1041], [37, 1041]];  // aspect 8.7
const PAGE_ROI = [[0, 0], [1920, 0], [1920, 986], [0, 986]];  // aspect 1.95

function cleanResult(roi = ONE_LINE_ROI) {
  return {
    output_model: "clean_reflow_v1",
    reflow_state: "done",
    reflow: { revision: 2, applied_roi: roi, systems: [] },
    review_candidates: ["/job/reflow/strips/strip_sys-001.png"],
    capture_diagnostics: { "/job/reflow/strips/strip_sys-001.png": { system_id: "sys-001", t_start: 3 } },
    preview_images: ["/job/export/preview/preview_0001.jpg"],
    pdf: "/job/export/sheet_export.pdf",
  };
}

function originalResult() {
  const dir = "/job/original_screens/screens";
  return {
    output_model: "original_screens_v1",
    reflow_state: "original_screens",
    reflow: { revision: 3, applied_roi: ONE_LINE_ROI },
    original_screens: {
      screens_dir: dir,
      screens: [
        { path: `${dir}/screen_0001.png`, t: 6, candidate: false, reasons: [] },
        { path: `${dir}/screen_0002.png`, t: 71.5, candidate: false, reasons: [] },
        { path: `${dir}/screen_0003.png`, t: 198.5, candidate: true, reasons: ["악보가 아닌 영상 화면이 함께 들어간 것으로 보입니다."] },
      ],
      selected: [`${dir}/screen_0001.png`, `${dir}/screen_0002.png`],
    },
    preview_images: ["/job/original_screens/preview/preview_0001.jpg"],
    pdf: "/job/original_screens/sheet_export.pdf",
    output_dir: "/job/original_screens",
  };
}

function reviewState(result, locale = "en") {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.ui.activeStep = "review";
  state.exportConfig.jobId = "job-1";
  state.exportConfig.runStatus = "done";
  state.exportConfig.formats = ["pdf"];
  state.review.pages = deriveCapturePages(result, locale);
  state.review.outputPages = deriveOutputPages(result);
  state.review.originalScreens = deriveOriginalScreens(result);
  state.review.selectedPageIds = state.review.pages.filter(page => !page.autoExcludeCandidate).map(page => page.id);
  state.review.focusedPageId = state.review.pages[0]?.id || "";
  state.review.pdfPath = result.pdf;
  state.review.outputDir = result.output_dir || "/job/export";
  return state;
}

test("the rebuild button is offered only for a clean chart of a one-line video (ROI aspect >= 2.25)", () => {
  assert.ok(roiAspect(ONE_LINE_ROI) > 8);
  assert.equal(deriveOriginalScreens(cleanResult()).available, true);
  assert.equal(deriveOriginalScreens(cleanResult(PAGE_ROI)).available, false);
  // a result without its applied ROI falls back to the screen's ROI
  const noRoi = cleanResult();
  delete noRoi.reflow.applied_roi;
  assert.equal(deriveOriginalScreens(noRoi, ONE_LINE_ROI).available, true);
  assert.equal(deriveOriginalScreens(noRoi, null).available, false);
  assert.equal(deriveOriginalScreens(originalResult()).available, false);

  const offered = renderReviewScreen(reviewState(cleanResult(), "ko"));
  assert.match(offered, /data-action="rebuild-original-screens"/);
  assert.match(offered, /결과가 이상하면 원본 화면으로 다시 만들기/);
  assert.doesNotMatch(renderReviewScreen(reviewState(cleanResult(PAGE_ROI))), /rebuild-original-screens/);
});

test("original screens become review rows in time order; candidates start unchecked with their reason", () => {
  const result = originalResult();
  const pages = deriveCapturePages(result, "ko");
  assert.deepEqual(pages.map(page => page.title), ["화면 1", "화면 2", "화면 3"]);
  assert.deepEqual(pages.map(page => page.kind), ["screen", "screen", "screen"]);
  assert.deepEqual(pages.map(page => page.timeLabel), ["0:06", "1:11", "3:18"]);
  assert.deepEqual(pages.map(page => page.autoExcludeCandidate), [false, false, true]);
  assert.match(pages[2].warningReason, /영상 화면/);
  assert.equal(jobRevision(result), 3);
  assert.equal(deriveOutputPages(result)[0].path.endsWith("?r=3"), true);
  assert.deepEqual(deriveOriginalScreens(result), { active: true, screensDir: "/job/original_screens/screens", available: false });
});

test("the original screens review shows the mode notice and folder button and hides clean-only tools", () => {
  for (const [locale, notice, open] of [["ko", "원본 화면 모드: 영상 화면을 그대로 담았습니다.", "원본 이미지 폴더 열기"],
    ["en", "Original screens: the video's screens as shown.", "Open original images folder"]]) {
    const html = renderReviewScreen(reviewState(originalResult(), locale));
    assert.ok(html.includes(notice.replace(/'/g, "&#39;")), locale);
    assert.ok(html.includes(open), locale);
    assert.match(html, /data-action="open-original-screens-dir"/);
    assert.match(html, /review-inline-pill-exclude/);
    assert.doesNotMatch(html, /rebuild-original-screens|toggle-measure-reflow|review-move-up|data-action="review-crop"|review-lines/);
    // not mistaken for a pre-clean capture: the rebuild button works
    assert.doesNotMatch(html, /review-reflow-note is-warning/);
    assert.match(html, /data-action="apply-review"(?![^>]*disabled)/);
  }
});

test("original screens requests carry only the output model, formats and a non-empty selection", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  const calls = [];
  Object.defineProperty(globalThis, "window", { configurable: true, value: { drumSheetAPI: { requestJson: async (_path, options) => {
    calls.push(JSON.parse(options.body));
    return { ok: true, data: { images: [] } };
  } } } });
  try {
    await startReviewExport("job", { outputModel: "original_screens_v1", formats: ["pdf"], measureReflow: true, systemOrder: ["a"] });
    await startReviewExport("job", { outputModel: "original_screens_v1", formats: ["pdf"], keepCaptures: ["/s/screen_0002.png"] });
    assert.deepEqual(calls, [
      { output_model: "original_screens_v1", formats: ["pdf"] },
      { output_model: "original_screens_v1", formats: ["pdf"], keep_captures: ["/s/screen_0002.png"] },
    ]);
  } finally { if (previous) Object.defineProperty(globalThis, "window", previous); else delete globalThis.window; }
});

test("clean-review undo history never applies to the original screens of the same job", async () => {
  const { createReviewController } = await import("../features/review/reviewController.js");
  let state = reviewState(cleanResult());
  state.review.pages = ["1", "2", "3"].map(id => ({ id, capturePath: `/strip_${id}.png`, previewPath: `/strip_${id}.png` }));
  state.review.selectedPageIds = ["1", "2", "3"];
  state.review.status = "applied";
  const controller = createReviewController({ getState: () => state, setState: update => { state = update(structuredClone(state)); }, api: {}, root: {}, mountEditor() {} });
  controller.toggle("2", false);
  assert.equal(state.review.canUndo, true);
  // the same job rebuilt as original screens: other rows with the same ids
  const original = reviewState(originalResult());
  state.review.pages = original.review.pages;
  state.review.originalScreens = original.review.originalScreens;
  state.review.selectedPageIds = ["1", "2", "3"];
  await controller.handleAction("review-undo");
  assert.deepEqual(state.review.selectedPageIds, ["1", "2", "3"]);
});
