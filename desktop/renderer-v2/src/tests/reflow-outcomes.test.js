import test from "node:test";
import assert from "node:assert/strict";

import { exportErrorCodeMessage, formatExportJobMessage } from "../app/App.js";
import { createInitialSessionState, deriveReflowInfo, getProcessRailItems, isLayoutConflictPending, isReviewableRun } from "../app/session/selectors.js";
import { renderExportScreen } from "../features/export/ExportScreen.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { t } from "../lib/i18n.js";

const ROI = [[0, 0], [320, 0], [320, 180], [0, 180]];

const NEW_KEYS = [
  "review.reviewRequiredTitle", "review.reviewRequiredDetail", "review.reviewRequiredState", "review.reviewReasonsLabel",
  "export.reviewRequiredTitle", "selector.summary.reviewRequired", "reflow.issue.SOURCE_CLIPPED",
  "reflow.issue.UNCERTAIN_MARK_KEPT", "reflow.issue.TRANSLUCENT_PLATE_GRAY", "reflow.issue.SOURCE_CLASS_UNKNOWN",
  "reflow.issue.LOW_CONTRAST_CONTENT_KEPT", "reflow.issue.CONTENT_LOST_IN_FINISHING",
  "review.staffSizeAutoReducedWide", "review.conflictPendingTitle", "review.conflictPendingDetail", "review.conflictBelowAuto",
  "review.incompleteTitle", "review.incompleteDetail", "review.incompleteDetailNoRanges", "review.incompleteRangesLabel",
  "review.incompleteState", "review.exportInvalid", "export.failedExportInvalid", "export.invalid.INVALID_PLACEMENT_PLAN",
  "export.invalid.EMPTY_EXPORT", "export.invalid.PAGE_COUNT_MISMATCH", "export.invalid.PDF_UNREADABLE",
  "export.failedLayoutConflict", "export.failedUnsupportedSource", "export.incompleteTitle", "export.incompleteDetail",
  "export.incompleteDetailNoRanges", "selector.summary.reviewConflict", "selector.summary.reviewIncomplete",
  "reflow.issue.LEDGER_UNASSESSED", "reflow.issue.LEDGER_REVIEW_REQUIRED", "reflow.issue.LEDGER_VERIFICATION_FAILED",
  "export.failedLedgerVerification", "review.ledgerVerificationFailed", "selector.summary.reviewLedgerFailed",
];

test("every new outcome label exists in Korean and English and differs between them", () => {
  for (const key of NEW_KEYS) {
    for (const locale of ["ko", "en"]) assert.notEqual(t(key, { locale }), key, `${locale} ${key}`);
    assert.notEqual(t(key, { locale: "ko" }), t(key, { locale: "en" }), key);
  }
  assert.equal(t("review.staffSizeAutoReducedWide", { locale: "ko", replacements: { size: "1.3" } }), "악보가 페이지보다 넓어 크기를 1.3mm로 줄였어요.");
  assert.equal(t("review.staffSizeAutoReducedWide", { locale: "en", replacements: { size: "1.3" } }), "Score wider than the page: staff size reduced to 1.3 mm.");
});

test("job error codes map to specific messages; unknown codes keep the backend detail", () => {
  for (const locale of ["ko", "en"]) {
    for (const code of ["INVALID_PLACEMENT_PLAN", "EMPTY_EXPORT", "PAGE_COUNT_MISMATCH", "PDF_UNREADABLE"]) {
      const text = formatExportJobMessage(`${code}: x`, { status: "error", locale, errorCode: code });
      assert.ok(text.startsWith(t(`export.invalid.${code}`, { locale })), `${locale} ${code}`);
    }
    assert.equal(formatExportJobMessage("x", { status: "error", locale, errorCode: "UNSUPPORTED_SOURCE" }), t("export.failedUnsupportedSource", { locale }));
    assert.equal(formatExportJobMessage("x", { status: "error", locale, errorCode: "LAYOUT_CONFLICT" }), t("export.failedLayoutConflict", { locale }));
    assert.equal(formatExportJobMessage("x", { status: "error", locale, errorCode: "LEDGER_VERIFICATION_FAILED" }), t("export.failedLedgerVerification", { locale }));
    assert.equal(formatExportJobMessage("x", { status: "error", locale, errorCode: "VIDEO_DECODE_INCOMPLETE" }), t("export.failedDecodeIncomplete", { locale }));
  }
  assert.equal(exportErrorCodeMessage("SOMETHING_ELSE", "en"), "");
  assert.equal(formatExportJobMessage("job failed: disk full", { status: "error", locale: "en", errorCode: "SOMETHING_ELSE" }), "disk full");
  // the code only applies to failed jobs
  assert.equal(formatExportJobMessage("", { status: "done", locale: "en", errorCode: "LAYOUT_CONFLICT" }), "");
});

test("only recoverable errors with their matching reflow state count as reviewable", () => {
  const state = createInitialSessionState();
  state.exportConfig.runStatus = "error";
  state.exportConfig.errorCode = "LAYOUT_CONFLICT";
  state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow_state: "layout_conflict", reflow: {} });
  assert.equal(isLayoutConflictPending(state), true);
  assert.equal(isReviewableRun(state), true);
  state.exportConfig.errorCode = "PDF_UNREADABLE";
  assert.equal(isReviewableRun(state), false);
  state.exportConfig.errorCode = "LAYOUT_CONFLICT";
  state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow_state: "export_invalid", reflow: {} });
  assert.equal(isReviewableRun(state), false);
  state.exportConfig.errorCode = "LEDGER_VERIFICATION_FAILED";
  assert.equal(isReviewableRun(state), false);
  state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow_state: "ledger_failed", reflow: {} });
  assert.equal(isReviewableRun(state), true);
  assert.equal(state.review.reflow.reviewRequired, true);
  state.exportConfig.errorCode = "PDF_UNREADABLE";
  assert.equal(isReviewableRun(state), false);
  state.exportConfig.runStatus = "done";
  assert.equal(isReviewableRun(state), true);
});

test("review reasons deduplicate by code and retain the public structured explanation", () => {
  const text = "검증 자료가 없어요 / Preservation evidence is missing";
  const state = reviewState({ result: {
    review_required: true,
    review_reasons: [{ code: "LEDGER_UNASSESSED", text }, { text: "uncoded explanation" }],
    reflow: { review_reasons: ["LEDGER_UNASSESSED", { code: "LEDGER_UNASSESSED", text: "internal text" }, { text: "uncoded explanation" }] },
  } });
  assert.deepEqual(state.review.reflow.reviewReasons, [
    { code: "LEDGER_UNASSESSED", text }, { code: "", text: "uncoded explanation" },
  ]);
  for (const locale of ["ko", "en"]) {
    state.ui.locale = locale;
    const localized = t("reflow.issue.LEDGER_UNASSESSED", { locale });
    const html = renderReviewScreen(state);
    assert.equal(html.split(localized).length - 1, 1);
    assert.doesNotMatch(html, /LEDGER_UNASSESSED|internal text/);
    // the reasons are told once, on the review screen
    assert.ok(!renderExportScreen(state).includes(localized));
  }
});

function reviewState({ locale = "en", result = {} } = {}) {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.exportConfig.jobId = "job-1";
  state.exportConfig.runStatus = "done";
  state.exportConfig.formats = ["pdf"];
  state.source.filePath = "/tmp/a.mp4";
  state.roi.appliedRect = ROI;
  state.review.pages = [1, 2].map(n => ({
    id: String(n), kind: "system", systemId: `sys-00${n}`, title: `Line ${n}`, capturePath: `/job/strip_${n}.png`, previewPath: `/job/strip_${n}.png`,
  }));
  state.review.selectedPageIds = ["1", "2"];
  state.review.focusedPageId = "1";
  state.review.status = "applied";
  state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { revision: 1 }, ...result });
  return state;
}

test("a score wider than the page derives its automatic size without a note", () => {
  for (const [status, reason] of [["off", "WHOLE_SYSTEMS_DO_NOT_FIT"], ["fallback_whole_systems", "WHOLE_SYSTEMS_DO_NOT_FIT"], ["measure_lines", "UNITS_DO_NOT_FIT"]]) {
    const measure_reflow = { status, staff_size: { staff_gap_mm: 1.25, staff_gap_mm_requested: 1.5, auto_reduced: true, reason } };
    const info = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: {}, measure_reflow });
    assert.equal(info.autoStaff.kind, "wide", `${status} ${reason}`);
    for (const locale of ["ko", "en"]) {
      const html = renderReviewScreen(reviewState({ locale, result: { measure_reflow } }));
      // derived, but the app's own size choice is not reported
      assert.ok(!html.includes(t("review.staffSizeAutoReducedWide", { locale, replacements: { size: "1.25" } })), `${locale} ${status}`);
      assert.ok(!html.includes(t("review.staffSizeAutoReduced", { locale, replacements: { size: "1.25" } })));
    }
  }
  // the size the user chose stays theirs: not reduced, no note
  const kept = { status: "off", staff_size: { staff_gap_mm: 1.5, staff_gap_mm_requested: 1.5, auto_reduced: false, reason: "FITS" } };
  assert.equal(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: {}, measure_reflow: kept }).autoStaff, null);
});

test("a conflict whose fitting size is below the automatic floor or does not exist says why", () => {
  const conflictResult = (offered, reason) => ({
    reflow_state: "layout_conflict",
    reflow: {
      layout_conflict: { requested_staff_gap_mm: 1.5, largest_fitting_staff_gap_mm: offered, conflicts: [{ system_id: "sys-002" }] },
      page_plan: { staff_size: { reason, auto_min_staff_gap_mm: 1.2 } },
    },
  });
  for (const locale of ["ko", "en"]) {
    const below = renderReviewScreen(reviewState({ locale, result: conflictResult(1.1, "BELOW_AUTO_MINIMUM") }));
    assert.ok(below.includes(t("review.conflictBelowAuto", { locale, replacements: { size: "1.1", min: "1.2" } })));
    assert.ok(below.includes(t("review.conflictPendingTitle", { locale })));
    const none = renderReviewScreen(reviewState({ locale, result: conflictResult(null, "NO_FITTING_SIZE") }));
    assert.ok(none.includes(t("review.conflictNoSize", { locale })));
    assert.doesNotMatch(none, /data-action="review-use-staff-size"/);
  }
});

test("an incomplete chart is labelled on review and export, with every unresolved range, and a long list scrolls by keyboard", () => {
  const unresolved = Array.from({ length: 24 }, (_, i) => [i * 60 + 5, i * 60 + 20.4]);
  const result = { reflow_state: "incomplete", coverage: { status: "incomplete", unresolved, intervals: [] } };
  for (const locale of ["ko", "en"]) {
    const state = reviewState({ locale, result });
    assert.equal(state.review.reflow.unresolvedRanges.length, 24);
    assert.equal(state.review.reflow.unresolvedRanges[0].label, "0:05–0:21");
    assert.equal(state.review.reflow.unresolvedRanges[23].label, "23:05–23:21");
    const review = renderReviewScreen(state);
    assert.ok(review.includes(t("review.incompleteTitle", { locale })));
    assert.ok(review.includes(t("review.incompleteDetail", { locale, replacements: { count: 24 } })));
    assert.equal((review.match(/<li>\d+:\d\d–\d+:\d\d<\/li>/g) || []).length, 24);
    assert.match(review, /<ul class="review-coverage-ranges" aria-label="[^"]+" tabindex="0">/);
    assert.match(review, /review-save-state is-incomplete/);
    const exported = renderExportScreen(state);
    assert.ok(exported.includes(t("export.incompleteTitle", { locale })));
    assert.equal((exported.match(/<li>\d+:\d\d–\d+:\d\d<\/li>/g) || []).length, 24);
    const rail = getProcessRailItems(state).find(item => item.id === "review");
    assert.equal(rail.summary, t("selector.summary.reviewIncomplete", { locale }));
  }
  // coverage may arrive under the reflow record; a complete chart shows nothing
  assert.equal(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { coverage: { status: "incomplete", unresolved: [[1, 2]] } } }).incomplete, true);
  const complete = reviewState({ result: { reflow_state: "done", coverage: { status: "complete", unresolved: [], intervals: [] } } });
  assert.equal(complete.review.reflow.incomplete, false);
  assert.doesNotMatch(renderReviewScreen(complete), /review-coverage-ranges|is-incomplete/);
  assert.doesNotMatch(renderExportScreen(complete), /export-incomplete-note/);
});

test("review-required result stays distinct from incomplete and saved in both locales", () => {
  const codes = ["SOURCE_CLIPPED", "UNCERTAIN_MARK_KEPT", "TRANSLUCENT_PLATE_GRAY"];
  for (const locale of ["ko", "en"]) {
    const state = reviewState({ locale, result: { review_required: true, review_reasons: codes, reflow_state: "review_required" } });
    assert.equal(state.review.reflow.reviewRequired, true);
    assert.equal(state.review.reflow.incomplete, false);
    const review = renderReviewScreen(state);
    const exported = renderExportScreen(state);
    // one note says it: the save state stays about the files, the export screen does not repeat it
    assert.match(review, /data-review-required/);
    assert.doesNotMatch(review, /review-save-state is-incomplete/);
    assert.ok(review.includes(`>${t("review.savedState", { locale })}</span>`));
    assert.ok(!exported.includes(t("export.reviewRequiredTitle", { locale })));
    for (const code of codes) {
      assert.ok(review.includes(t(`reflow.issue.${code}`, { locale })));
      assert.ok(!exported.includes(t(`reflow.issue.${code}`, { locale })));
    }
    assert.equal(getProcessRailItems(state).find(item => item.id === "review").summary, t("selector.summary.reviewRequired", { locale }));
    assert.equal(getProcessRailItems(state).find(item => item.id === "export").summary, t("selector.summary.reviewRequired", { locale }));
  }
});

test("review flags survive nested records, old system-only records and unknown long reasons", () => {
  const codes = ["SOURCE_CLIPPED", "UNCERTAIN_MARK_KEPT", "TRANSLUCENT_PLATE_GRAY"];
  const info = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { review_required: true, review_reasons: [{ code: "SOURCE_CLIPPED" }], systems: [{ included: true, issues: codes }] } });
  assert.equal(info.reviewRequired, true);
  assert.equal(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { systems: [{ issues: codes }] } }).reviewRequired, true);
  assert.equal(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { systems: [{ included: false, issues: codes }] } }).reviewRequired, false);
  const reasons = Array.from({ length: 30 }, (_, i) => `긴 안내 ${i} ` + "긴 내용 ".repeat(30) + " / Long reason " + i + " " + "Very long content ".repeat(30));
  for (const locale of ["ko", "en"]) {
    const state = reviewState({ locale, result: { review_required: true, review_reasons: reasons } });
    // folded until opened, then scrollable by keyboard
    let html = renderReviewScreen(state);
    assert.match(html, /<ul id="reviewReasonsList" class="reflow-review-reasons" aria-label="[^"]+" tabindex="0" hidden>/);
    assert.match(html, /data-action="toggle-more" data-value="reviewReasons" aria-expanded="false"/);
    state.ui.more = { reviewReasons: true };
    html = renderReviewScreen(state);
    assert.match(html, /<ul id="reviewReasonsList" class="reflow-review-reasons" aria-label="[^"]+" tabindex="0" >/);
    assert.equal((html.match(/<li>/g) || []).length, 30);
    assert.ok(html.includes(locale === "ko" ? "긴 안내 29" : "Long reason 29"));
    assert.ok(!html.includes(locale === "ko" ? "Long reason 29" : "긴 안내 29"));
    state.ui.more = {};
    state.exportConfig.runStatus = "running";
    assert.doesNotMatch(renderExportScreen(state), /export-review-required-note/);
    state.exportConfig.runStatus = "error";
    assert.doesNotMatch(renderExportScreen(state), /export-review-required-note/);
  }
});
