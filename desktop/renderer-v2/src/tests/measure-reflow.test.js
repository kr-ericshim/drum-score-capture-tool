import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState, deriveReflowInfo } from "../app/session/selectors.js";
import { restoreSession, saveSession } from "../app/session/persistence.js";
import { buildExportScreenModel, renderExportScreen } from "../features/export/ExportScreen.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { reviewExport } from "../lib/api.js";
import { t } from "../lib/i18n.js";

const ROI = [[0, 0], [320, 0], [320, 180], [0, 180]];

function memoryStorage() {
  const values = new Map();
  return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
}

function exportState(locale = "ko") {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.source.filePath = "/tmp/a.mp4";
  state.source.displayName = "a.mp4";
  state.roi.appliedRect = ROI;
  return state;
}

function reviewState({ locale = "ko", measureResult = null } = {}) {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.exportConfig.jobId = "job-1";
  state.exportConfig.runStatus = "done";
  state.exportConfig.formats = ["pdf"];
  state.review.pages = [1, 2].map(n => ({
    id: String(n), kind: "system", systemId: `sys-00${n}`, title: `Line ${n}`, capturePath: `/job/strip_${n}.png`, previewPath: `/job/strip_${n}.png`,
  }));
  state.review.selectedPageIds = ["1", "2"];
  state.review.focusedPageId = "1";
  state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { revision: 1 }, ...(measureResult ? { measure_reflow: measureResult } : {}) });
  return state;
}

test("measure layout labels exist in Korean and English", () => {
  const keys = ["export.layout.title", "export.layout.measure", "export.layout.measureHint", "review.measureFallback", "review.measureFallbackReason", "review.measureHint"];
  for (const key of keys) {
    for (const locale of ["ko", "en"]) assert.notEqual(t(key, { locale }), key, `${locale} ${key}`);
    assert.notEqual(t(key, { locale: "ko" }), t(key, { locale: "en" }), key);
  }
  assert.equal(t("export.layout.measure", { locale: "ko" }), "마디 단위로 다시 배치 (한 줄 약 4마디)");
  assert.equal(t("export.layout.measure", { locale: "en" }), "Rearrange by measure (about 4 per line)");
  assert.equal(t("review.measureFallback", { locale: "ko" }), "마디 배치를 적용하지 못해 원래 줄 그대로 내보냈어요.");
  assert.equal(t("review.measureFallback", { locale: "en" }), "Couldn't rearrange by measure; exported the original lines.");
});

test("measure reflow is on by default in a new session", () => {
  assert.equal(createInitialSessionState().exportConfig.measureReflow, true);
});

test("the layout toggle lives on the review screen only; the export screen keeps the default", () => {
  for (const locale of ["ko", "en"]) {
    const state = exportState(locale);
    const html = renderExportScreen(state);
    assert.doesNotMatch(html, /data-action="toggle-measure-reflow"/);
    assert.doesNotMatch(html, /exportLayoutHeading/);
    assert.equal(state.exportConfig.measureReflow, true);
  }
});

test("the review screen offers the same toggle next to the rebuild hint", () => {
  for (const locale of ["ko", "en"]) {
    const state = reviewState({ locale });
    let html = renderReviewScreen(state);
    const input = html.match(/<input type="checkbox" data-action="toggle-measure-reflow"[^>]*>/)[0];
    assert.match(input, / checked /);
    assert.match(input, /aria-describedby="reviewMeasureReflowHint"/);
    assert.ok(html.includes(t("export.layout.measure", { locale })));
    assert.ok(html.includes(t("review.measureHint", { locale })));
    state.review.status = "running";
    html = renderReviewScreen(state);
    assert.match(html.match(/<input type="checkbox" data-action="toggle-measure-reflow"[^>]*>/)[0], /disabled/);
  }
});

test("a whole-system fallback is reported on the review screen with its reason code", () => {
  const info = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: {}, measure_reflow: { requested: true, applied: false, status: "fallback_whole_systems", reason: "NO_STAFF_GAP" } });
  assert.deepEqual(info.measureReflow, { status: "fallback_whole_systems", applied: false, fellBack: true, reason: "NO_STAFF_GAP" });
  for (const locale of ["ko", "en"]) {
    const html = renderReviewScreen(reviewState({ locale, measureResult: { status: "fallback_whole_systems", reason: "NO_STAFF_GAP" } }));
    assert.ok(html.includes(t("review.measureFallback", { locale }).replace("'", "&#39;")));
    assert.ok(html.includes(t("review.measureFallbackReason", { locale, replacements: { reason: "NO_STAFF_GAP" } })));
  }
  // applied, off and unknown records show no fallback notice
  for (const measureResult of [{ status: "measure_lines" }, { status: "off" }, null, { status: "bogus" }]) {
    const html = renderReviewScreen(reviewState({ locale: "en", measureResult }));
    assert.doesNotMatch(html, /rearrange by measure; exported/);
  }
  assert.equal(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: {} }).measureReflow, null);
});

test("a dense chart's smaller staff size is derived but not reported on the review screen", () => {
  const reduced = { status: "measure_lines", requested: true, applied: true, reason: null,
    staff_size: { staff_gap_mm: 1.3, staff_gap_mm_requested: 1.5, auto_reduced: true, reason: "DENSE_LINES_NOT_FULL" } };
  assert.deepEqual(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: {}, measure_reflow: reduced }).autoStaff, { usedMm: 1.3, requestedMm: 1.5, reason: "DENSE_LINES_NOT_FULL", kind: "dense" });
  assert.equal(t("review.staffSizeAutoReduced", { locale: "ko", replacements: { size: "1.3" } }), "빽빽한 악보라 크기를 1.3mm로 줄였어요.");
  assert.equal(t("review.staffSizeAutoReduced", { locale: "en", replacements: { size: "1.3" } }), "Dense score: staff size reduced to 1.3 mm.");
  // the automatic size is the app's own choice: the review screen does not report it
  for (const locale of ["ko", "en"]) {
    const html = renderReviewScreen(reviewState({ locale, measureResult: reduced }));
    assert.ok(!html.includes(t("review.staffSizeAutoReduced", { locale, replacements: { size: "1.3" } })), locale);
    assert.doesNotMatch(html, /data-action="review-use-staff-size"/);
  }
  // full at the chosen size, whole systems, or an older record: no note
  const unchanged = { ...reduced, staff_size: { staff_gap_mm: 1.5, staff_gap_mm_requested: 1.5, auto_reduced: false, reason: "LINES_FULL" } };
  for (const measureResult of [unchanged, { status: "measure_lines" }, { status: "off", staff_size: reduced.staff_size }, null]) {
    assert.equal(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: {}, ...(measureResult ? { measure_reflow: measureResult } : {}) }).autoStaff, null);
    assert.doesNotMatch(renderReviewScreen(reviewState({ locale: "en", measureResult })), /Dense score/);
  }
});

test("the layout choice survives saving and restoring a session; older sessions restore as on", () => {
  const storage = memoryStorage();
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/a.mp4";
  state.exportConfig.measureReflow = false;
  saveSession(storage, state);
  assert.equal(JSON.parse(storage.getItem("drum-sheet-session-v1")).exportConfig.measureReflow, false);
  assert.equal(restoreSession(storage, createInitialSessionState()).exportConfig.measureReflow, false);

  const saved = JSON.parse(storage.getItem("drum-sheet-session-v1"));
  delete saved.exportConfig.measureReflow;  // a session saved before the toggle existed
  storage.setItem("drum-sheet-session-v1", JSON.stringify(saved));
  assert.equal(restoreSession(storage, createInitialSessionState()).exportConfig.measureReflow, true);
});

test("reviewExport sends measure_reflow only when the caller chooses", async () => {
  const previousWindow = globalThis.window;
  const bodies = [];
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { drumSheetAPI: { async requestJson(pathname, options) { bodies.push(JSON.parse(options.body)); return { ok: true, status: 200, data: {} }; } } },
  });
  try {
    await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"] });
    await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"], measureReflow: false });
    await reviewExport("job-1", { keepCaptures: ["/a.png"], formats: ["pdf"], measureReflow: true });
  } finally {
    Object.defineProperty(globalThis, "window", { configurable: true, value: previousWindow });
  }
  assert.equal("measure_reflow" in bodies[0], false);
  assert.equal(bodies[1].measure_reflow, false);
  assert.equal(bodies[2].measure_reflow, true);
});
