import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState, deriveCapturePages, deriveOutputPages, deriveReflowInfo, localizePageTitle } from "../app/session/selectors.js";
import { restoreSession, saveSession } from "../app/session/persistence.js";
import { createReviewController } from "../features/review/reviewController.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { buildExportScreenModel, renderExportScreen } from "../features/export/ExportScreen.js";
import { renderRoiScreen } from "../features/roi/RoiScreen.js";
import { pagePreviewOn } from "../features/review/lineCheck.js";

const ROI = [[0, 700], [1920, 700], [1920, 1080], [0, 1080]];

function reflowResult() {
  const strips = ["/job/reflow/strips/strip_sys-001.png", "/job/reflow/strips/strip_sys-002.png", "/job/reflow/strips/strip_sys-003.png", "/job/reflow/strips/strip_sys-004.png"];
  return {
    output_model: "clean_reflow_v1",
    reflow_state: "done",
    review_candidates: strips,
    auto_excluded_captures: [strips[3]],
    capture_diagnostics: {
      [strips[0]]: { system_id: "sys-001", t_start: 6, recommended_action: "keep", diagnostic_codes: [] },
      [strips[1]]: { system_id: "sys-002", t_start: 72.5, recommended_action: "keep", diagnostic_codes: [] },
      [strips[2]]: { system_id: "sys-003", t_start: 130, recommended_action: "keep", diagnostic_codes: [] },
      [strips[3]]: { system_id: "sys-004", t_start: 150, recommended_action: "exclude", suspicious: true, diagnostic_codes: ["SHORT_DISPLAY"], warning_reasons: ["Shown only briefly"] },
    },
    similar_capture_pairs: [{ kept: strips[0], candidate: strips[2], reason: "looks_similar", metrics: { reason: "looks_similar" } }],
    images: ["/job/export/images/page_0001.png"],
    preview_images: ["/job/export/preview/preview_0001.jpg", "/job/export/preview/preview_0002.jpg"],
    pdf: "/job/export/sheet_export.pdf",
  };
}

function reviewState(locale = "en") {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.ui.activeStep = "review";
  state.exportConfig.jobId = "job-1";
  state.exportConfig.runStatus = "done";
  state.exportConfig.formats = ["pdf"];
  state.review.pages = deriveCapturePages(reflowResult(), locale);
  state.review.outputPages = deriveOutputPages(reflowResult());
  state.review.selectedPageIds = ["1", "2", "3"];
  state.review.focusedPageId = "3";
  return state;
}

test("reflow systems become review items named by their video order with time and a looks-similar flag", () => {
  const pages = deriveCapturePages(reflowResult(), "ko");
  assert.deepEqual(pages.map(page => page.title), ["줄 1", "줄 2", "줄 3", "줄 4"]);
  assert.deepEqual(pages.map(page => page.kind), ["system", "system", "system", "system"]);
  assert.equal(pages[1].timeLabel, "1:12");
  assert.equal(pages[2].similarTo.reason, "looks_similar");
  // a result stored by the earlier build said "repeat": shown with the same appearance-only wording
  const older = reflowResult();
  older.similar_capture_pairs[0].reason = "repeat";
  assert.equal(deriveCapturePages(older, "en")[2].similarTo.reason, "looks_similar");
  assert.equal(pages[2].similarTo.referenceId, "1");
  assert.equal(pages[3].autoExcludeCandidate, true);
  // a rearranged list keeps each system's name
  const moved = reflowResult();
  moved.review_candidates = [moved.review_candidates[2], moved.review_candidates[0], moved.review_candidates[1], moved.review_candidates[3]];
  assert.deepEqual(deriveCapturePages(moved, "en").map(page => page.title), ["System 3", "System 1", "System 2", "System 4"]);
  assert.equal(deriveOutputPages(reflowResult()).length, 2);
  assert.deepEqual(deriveOutputPages({ preview_images: ["/x.png"] }), []);
  // the same files rewritten by a rebuild load again: the revision is part of the address
  const rebuilt = deriveOutputPages({ output_model: "clean_reflow_v1", preview_images: ["/job/export/preview/preview_0001.jpg"], reflow: { revision: 5 } });
  assert.equal(rebuilt[0].path, "file:///job/export/preview/preview_0001.jpg?r=5");
});

test("review screen offers order controls, a prominent compare, one-click leave-out and the page view", () => {
  for (const locale of ["ko", "en"]) {
    // the pages are the default view; order controls show while one system is viewed
    assert.match(renderReviewScreen(reviewState(locale)), /review-viewer-surface is-pages/);
    assert.doesNotMatch(renderReviewScreen(reviewState(locale)), /data-action="review-move-up"/);
    const single = reviewState(locale);
    single.review.pagePreview = false;
    const html = renderReviewScreen(single);
    assert.match(html, locale === "ko" ? /줄 검토/ : /Review systems/);
    assert.match(html, /data-action="review-move-up"/);
    assert.match(html, /data-action="review-move-down"/);
    assert.match(html, /data-action="review-remove-duplicate"/);
    assert.match(html, locale === "ko" ? /이 줄 빼기/ : /Leave this one out/);
    assert.match(html, locale === "ko" ? /비슷해 보임/ : /Looks similar/);
    assert.match(html, locale === "ko" ? /줄 1와\(과\) 비슷해 보입니다/ : /Looks similar to System 1/);
    // no visible claim of an established duplicate or repeat
    const visible = html.replace(/<[^>]+>/g, " ");
    assert.doesNotMatch(visible, locale === "ko" ? /중복|반복/ : /[Dd]uplicate|[Rr]epeat/);
    // compare is the prominent action for a system that looks similar
    assert.match(html, /class="button button-primary" data-action="review-compare"/);
    assert.match(html, /data-action="review-page-preview"/);
    // systems are not cropped in this slice: no crop tools
    assert.doesNotMatch(html, /data-action="review-crop"/);
  }
  const state = reviewState("en");
  state.review.pagePreview = true;
  const html = renderReviewScreen(state);
  assert.match(html, /review-viewer-surface is-pages/);
  assert.equal((html.match(/class="review-page-image"/g) || []).length, 2);
  assert.match(html, /Pages from the last build/);
});

test("move up/down rearranges systems, undo restores the order, and a repeat is removed in one click", async () => {
  let state = reviewState("en");
  const controller = createReviewController({ getState: () => state, setState: update => { state = update(structuredClone(state)); }, api: {}, root: {}, mountEditor() {} });
  await controller.handleAction("review-move-up");
  assert.deepEqual(state.review.pages.map(page => page.title), ["System 1", "System 3", "System 2", "System 4"]);
  assert.equal(state.review.status, "idle");
  await controller.handleAction("review-move-up");
  assert.deepEqual(state.review.pages.map(page => page.title), ["System 3", "System 1", "System 2", "System 4"]);
  await controller.handleAction("review-move-up"); // already first: no change
  assert.equal(state.review.pages[0].title, "System 3");
  await controller.handleAction("review-undo");
  assert.deepEqual(state.review.pages.map(page => page.title), ["System 1", "System 3", "System 2", "System 4"]);
  await controller.handleAction("review-remove-duplicate");
  assert.deepEqual(state.review.selectedPageIds, ["1", "2"]);
  await controller.handleAction("review-undo");
  assert.deepEqual(state.review.selectedPageIds.sort(), ["1", "2", "3"]);
  // the pages are the default view: the first toggle shows one system, the next the pages again
  await controller.handleAction("review-page-preview");
  assert.equal(state.review.pagePreview, false);
  await controller.handleAction("review-page-preview");
  assert.equal(state.review.pagePreview, true);
});

test("export step shows the region check started by Apply: loading, clipped with action, error with retry", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/v.mp4";
  state.roi.appliedRect = ROI;
  state.ui.activeStep = "export";
  const key = JSON.stringify(ROI);
  for (const locale of ["ko", "en"]) {
    state.ui.locale = locale;
    state.roi.clipCheck = { status: "loading", rectKey: key, suggestedRect: null };
    let html = renderExportScreen(state);
    assert.match(html, /export-clip-note is-loading/);
    assert.match(html, locale === "ko" ? /확인하는 중/ : /Checking the region/);
    assert.doesNotMatch(html, /export-clip-action/);

    state.roi.clipCheck = { status: "clipped", rectKey: key, suggestedRect: [[0, 600], [1920, 600], [1920, 1080], [0, 1080]] };
    html = renderExportScreen(state);
    assert.match(html, /export-clip-note is-clipped/);
    assert.match(html, /role="alert"/);
    assert.match(html, /data-action="use-suggested-roi"/);
    assert.match(html, locale === "ko" ? /추천 영역 사용/ : /Use suggested area/);

    state.roi.clipCheck = { status: "error", rectKey: key, suggestedRect: null };
    html = renderExportScreen(state);
    assert.match(html, /data-action="recheck-roi"/);
  }
  // a result for another region, or a clear result, shows nothing
  state.roi.clipCheck = { status: "clipped", rectKey: "[[1,2]]", suggestedRect: ROI };
  assert.equal(buildExportScreenModel(state).clipNote, null);
  state.roi.clipCheck = { status: "clear", rectKey: key, suggestedRect: null };
  assert.equal(buildExportScreenModel(state).clipNote, null);
});

test("review notes report a layout conflict with the explicit smaller-size choice, pending suggestions and exclusions", () => {
  const result = reflowResult();
  result.reflow_state = "layout_conflict";
  result.reflow = {
    revision: 1, staff_gap_mm: 1.5, suggestions_state: "pending",
    exclusions: { short_listed_excluded: ["sys-004"], hidden: 12 },
    layout_conflict: { requested_staff_gap_mm: 1.5, largest_fitting_staff_gap_mm: 1.1, conflicts: [{ system_id: "sys-002", kind: "too_wide" }] },
  };
  const info = deriveReflowInfo(result);
  assert.deepEqual(info.conflict.systemNumbers, [2]);
  assert.equal(info.listedShort, 1);
  assert.equal(info.hiddenShort, 12);
  for (const locale of ["ko", "en"]) {
    const state = reviewState(locale);
    state.review.reflow = info;
    const html = renderReviewScreen(state);
    assert.match(html, /review-reflow-note is-conflict" role="alert"/);
    assert.match(html, /data-action="review-use-staff-size" data-size="1.1"/);
    assert.match(html, locale === "ko" ? /이 문서만 1\.1 mm로 만들기/ : /Use 1\.1 mm for this document/);
    assert.match(html, locale === "ko" ? /줄 2은\(는\) 오선 간격 1\.5 mm/ : /System 2 is wider or taller than A4 at a 1\.5 mm/);
    assert.match(html, locale === "ko" ? /비슷해 보이는 줄을 찾는 중/ : /Looking for systems that look similar/);
    assert.match(html, locale === "ko" ? /짧게 스친 화면 1개/ : /1 briefly shown displays/);
    assert.match(html, locale === "ko" ? /짧은 화면 12개는 넣지 않았습니다/ : /12 brief displays whose content/);
  }
  // no size fits: only leaving the system out is offered
  result.reflow.layout_conflict.largest_fitting_staff_gap_mm = null;
  const state = reviewState("en");
  state.review.reflow = deriveReflowInfo(result);
  let html = renderReviewScreen(state);
  assert.doesNotMatch(html, /data-action="review-use-staff-size"/);
  assert.match(html, /does not fit even at the smallest size/);
  // after the choice: the smaller size is shown with a way back
  result.reflow.layout_conflict = undefined;
  result.reflow.staff_gap_mm = 1.1;
  result.reflow.staff_gap_mm_default = 1.5;
  state.review.reflow = deriveReflowInfo(result);
  html = renderReviewScreen(state);
  assert.match(html, /This document uses a smaller 1\.1 mm staff gap/);
  assert.match(html, /data-action="review-use-staff-size" data-size="1.5"[^>]*>Back to 1\.5 mm/);
});

test("a capture made before clean charts explains itself and cannot be rebuilt raw", () => {
  for (const locale of ["ko", "en"]) {
    const state = reviewState(locale);
    state.review.pages = deriveCapturePages({ review_candidates: ["/job/review/capture_0001.png"], images: ["/job/export/images/page_0001.png"] }, locale);
    state.review.selectedPageIds = ["1"];
    state.review.focusedPageId = "1";
    state.review.reflow = null;
    const html = renderReviewScreen(state);
    assert.match(html, locale === "ko" ? /깨끗한 악보 기능 이전에 만든 캡처/ : /made before clean charts/);
    assert.match(html, /data-action="apply-review"[^>]*disabled/);
  }
});

test("an unsaved system order and selection are saved with their job revision", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const state = reviewState("en");
  state.source.filePath = "/video.mp4";
  state.review.jobRevision = 3;
  state.review.pages = [state.review.pages[2], state.review.pages[0], state.review.pages[1], state.review.pages[3]];
  state.review.selectedPageIds = ["3", "1"];
  saveSession(storage, state);
  const saved = JSON.parse([...values.values()][0]).review;
  assert.deepEqual(saved, {
    jobId: "job-1", revision: 3,
    selectedPaths: ["/job/reflow/strips/strip_sys-003.png", "/job/reflow/strips/strip_sys-001.png"],
    systemOrder: ["sys-003", "sys-001", "sys-002", "sys-004"],
    // an unsaved draft: the saved files were not built from it
    applied: false,
  });
  const restored = restoreSession(storage, createInitialSessionState());
  assert.deepEqual(restored.review.restoredDraftKey, { jobId: "job-1", revision: 3 });
  assert.deepEqual(restored.review.restoredSystemOrder, ["sys-003", "sys-001", "sys-002", "sys-004"]);
  // saving again before the job is loaded keeps the restored draft
  saveSession(storage, restored);
  assert.deepEqual(JSON.parse([...values.values()][0]).review.systemOrder, ["sys-003", "sys-001", "sys-002", "sys-004"]);
});

test("region step and export step show the section-label area states in both languages", () => {
  const label = [[10, 2], [120, 2], [120, 18], [10, 18]];
  for (const locale of ["ko", "en"]) {
    const state = createInitialSessionState();
    state.ui.locale = locale;
    state.source.filePath = "/v.mp4";
    state.roi.previewImage = "/p.png";
    state.roi.appliedRect = ROI;
    state.roi.draftRect = ROI;
    // nothing found yet: a manual add is offered
    let html = renderRoiScreen(state);
    assert.match(html, /data-action="edit-label-roi"/);
    // found: loaded only by the user
    state.roi.labelCheck = { status: "suggested", rectKey: JSON.stringify(ROI), suggestedRect: label };
    html = renderRoiScreen(state);
    assert.match(html, /data-action="use-suggested-label-roi"/);
    assert.match(html, locale === "ko" ? /구간 표시가 있는 것 같습니다/ : /Section labels seem to appear outside/);
    state.ui.activeStep = "export";
    let exportHtml = renderExportScreen(state);
    assert.match(exportHtml, /export-label-note is-found/);
    assert.match(exportHtml, /data-action="use-suggested-label-roi"/);
    // editing: apply / back; the score apply button is hidden
    state.roi.editTarget = "labels";
    state.roi.labelDraftRect = label;
    html = renderRoiScreen(state);
    assert.match(html, /data-action="apply-label-roi"/);
    assert.match(html, /data-action="edit-score-roi"/);
    assert.match(html, /class="roi-stage-actions" hidden/);
    assert.match(html, locale === "ko" ? /구간 표시 영역 편집 캔버스/ : /Section-label area editor canvas/);
    // applied
    state.roi.editTarget = "score";
    state.roi.labelAppliedRect = label;
    html = renderRoiScreen(state);
    assert.match(html, /roi-label-area is-applied/);
    assert.match(html, /data-action="remove-label-roi"/);
    exportHtml = renderExportScreen(state);
    assert.match(exportHtml, /export-label-note is-applied/);
  }
});

// Audit round 2, P2: Q8 listed 45 short transition fragments as 45 separate unchecked rows.
function fragmentResult(count = 45) {
  const base = reflowResult();
  const strips = [...base.review_candidates.slice(0, 3)];
  const diagnostics = { ...base.capture_diagnostics };
  delete diagnostics[base.review_candidates[3]];
  for (let k = 0; k < count; k += 1) {
    const path = `/job/reflow/strips/strip_sys-${String(k + 4).padStart(3, "0")}.png`;
    strips.splice(1 + (k % 3), 0, path); // interleaved with the systems, as in video order
    diagnostics[path] = { system_id: `sys-${String(k + 4).padStart(3, "0")}`, t_start: 10 + k, recommended_action: "exclude", suspicious: true,
      diagnostic_codes: ["SHORT_DISPLAY"], warning_reasons: ["Shown only briefly"] };
  }
  return { ...base, review_candidates: strips, capture_diagnostics: diagnostics, auto_excluded_captures: strips.filter(p => diagnostics[p].diagnostic_codes.length) };
}

function fragmentState(locale = "en", count = 45) {
  const state = reviewState(locale);
  state.review.pages = deriveCapturePages(fragmentResult(count), locale);
  const systems = state.review.pages.filter(page => !page.transitionFragment).map(page => page.id);
  state.review.selectedPageIds = systems;
  state.review.focusedPageId = systems[0];
  return state;
}

test("many short transition fragments are one collapsed group, each still restorable", async () => {
  for (const locale of ["ko", "en"]) {
    let state = fragmentState(locale);
    const fragments = state.review.pages.filter(page => page.transitionFragment);
    assert.equal(fragments.length, 45);
    let html = renderReviewScreen(state);
    assert.match(html, locale === "ko" ? /짧은 전환 화면 \(45\)/ : /Transition fragments \(45\)/);
    assert.match(html, /data-action="review-toggle-fragments" aria-expanded="false" aria-controls="reviewFragmentList"/);
    // collapsed: only the three systems are rows
    assert.equal((html.match(/data-action="toggle-review-page"/g) || []).length, 3);
    const controller = createReviewController({ getState: () => state, setState: update => { state = update(structuredClone(state)); }, api: {}, root: {}, mountEditor() {} });
    // ← → walk the visible rows only
    await controller.handleAction("review-next");
    await controller.handleAction("review-next");
    await controller.handleAction("review-next");
    assert.equal(state.review.pages.find(page => page.id === state.review.focusedPageId).transitionFragment, false);
    await controller.handleAction("review-toggle-fragments");
    html = renderReviewScreen(state);
    assert.match(html, /aria-expanded="true"/);
    assert.equal((html.match(/data-action="toggle-review-page"/g) || []).length, 48);
    assert.match(html, locale === "ko" ? /페이지 넘김/ : /page turns/);
    // one fragment restored on its own; the group says how many are included
    controller.toggle(fragments[7].id, true);
    assert.ok(state.review.selectedPageIds.includes(fragments[7].id));
    html = renderReviewScreen(state);
    assert.match(html, locale === "ko" ? /1개 포함/ : /1 included/);
    // closing the group moves the view off a hidden fragment
    state.review.focusedPageId = fragments[7].id;
    await controller.handleAction("review-toggle-fragments");
    assert.equal(state.review.pages.find(page => page.id === state.review.focusedPageId).transitionFragment, false);
    assert.ok(state.review.selectedPageIds.includes(fragments[7].id)); // still included while collapsed
  }
});

test("a single short display stays an ordinary row", () => {
  const html = renderReviewScreen(fragmentState("en", 1));
  assert.doesNotMatch(html, /review-toggle-fragments/);
  assert.equal((html.match(/data-action="toggle-review-page"/g) || []).length, 4);
});

// Blocker 1 (audit round 4): marks shown only for a moment are never dropped silently. The
// system is flagged MINORITY_CONTENT_DROPPED and each "other moment" alternate is listed
// unchecked right after it (several are one collapsed group), titled with its system.
function alternateResult(count = 1) {
  const base = reflowResult();
  const strips = [...base.review_candidates.slice(0, 3)];
  const diagnostics = { ...base.capture_diagnostics };
  delete diagnostics[base.review_candidates[3]];
  const systems = [{ id: "sys-001", issues: [] }, { id: "sys-002", issues: [] }, { id: "sys-003", issues: [] }];
  for (let k = 0; k < count; k += 1) {
    const owner = `sys-00${(k % 3) + 1}`;
    const id = `${owner}-alt${Math.floor(k / 3) + 1}`;
    const path = `/job/reflow/strips/alt/strip_${id}.png`;
    strips.splice(strips.indexOf(`/job/reflow/strips/strip_${owner}.png`) + 1, 0, path);
    diagnostics[path] = { system_id: id, t_start: 20 + k, recommended_action: "exclude", suspicious: true, alternate_of: owner,
      diagnostic_codes: ["MINORITY_ALTERNATE"], warning_reasons: ["같은 줄의 다른 순간입니다 / Another moment of the line above, with the marks it leaves out"] };
    const main = `/job/reflow/strips/strip_${owner}.png`;
    diagnostics[main] = { ...diagnostics[main], suspicious: true, diagnostic_codes: ["MINORITY_CONTENT_DROPPED"] };
    systems.find(s => s.id === owner).issues = ["MINORITY_CONTENT_DROPPED"];
    systems.push({ id, issues: ["MINORITY_ALTERNATE"], included: false });
  }
  return { ...base, review_candidates: strips, capture_diagnostics: diagnostics, auto_excluded_captures: strips.filter(p => diagnostics[p].alternate_of),
    reflow: { systems, revision: 1 } };
}

test("an other-moment alternate is listed unchecked after its system, named by it, without a separate chart note", () => {
  for (const locale of ["ko", "en"]) {
    const result = alternateResult(1);
    const pages = deriveCapturePages(result, locale);
    assert.deepEqual(pages.map(page => page.title), locale === "ko"
      ? ["줄 1", "줄 1 · 다른 순간 1", "줄 2", "줄 3"] : ["System 1", "System 1 · other moment 1", "System 2", "System 3"]);
    assert.equal(pages[1].minorityAlternate, true);
    assert.equal(pages[1].autoExcludeCandidate, true);
    assert.equal(pages[0].suspicious, true);
    const info = deriveReflowInfo(result);
    assert.equal(info.minorityLines, 1);
    const state = reviewState(locale);
    state.review.pages = pages;
    state.review.reflow = info;
    state.review.selectedPageIds = ["1", "3", "4"];
    const html = renderReviewScreen(state);
    // the alternate row itself says it: no separate chart note
    assert.doesNotMatch(html, locale === "ko" ? /1개 줄에서 잠깐만 보인 표시가 빠졌습니다/ : /Marks shown only for a moment are left out of some system images \(1\)/);
    assert.doesNotMatch(html, /review-toggle-alternates/); // one alternate stays an ordinary row
    assert.equal((html.match(/data-action="toggle-review-page"/g) || []).length, 4);
  }
});

test("several other-moment alternates are one collapsed group, each still includable", async () => {
  for (const locale of ["ko", "en"]) {
    let state = reviewState(locale);
    state.review.pages = deriveCapturePages(alternateResult(5), locale);
    const alternates = state.review.pages.filter(page => page.minorityAlternate);
    assert.equal(alternates.length, 5);
    state.review.selectedPageIds = state.review.pages.filter(page => !page.minorityAlternate).map(page => page.id);
    state.review.focusedPageId = state.review.selectedPageIds[0];
    let html = renderReviewScreen(state);
    assert.match(html, locale === "ko" ? /다른 순간 \(5\)/ : /Other moments \(5\)/);
    assert.match(html, /data-action="review-toggle-alternates" aria-expanded="false" aria-controls="reviewAlternateList"/);
    assert.equal((html.match(/data-action="toggle-review-page"/g) || []).length, 3);
    const controller = createReviewController({ getState: () => state, setState: update => { state = update(structuredClone(state)); }, api: {}, root: {}, mountEditor() {} });
    await controller.handleAction("review-toggle-alternates");
    html = renderReviewScreen(state);
    assert.equal((html.match(/data-action="toggle-review-page"/g) || []).length, 8);
    assert.match(html, locale === "ko" ? /그 표시가 있습니다/ : /These moments show them/);
    controller.toggle(alternates[2].id, true);
    assert.ok(state.review.selectedPageIds.includes(alternates[2].id));
    html = renderReviewScreen(state);
    assert.match(html, locale === "ko" ? /1개 포함/ : /1 included/);
    state.review.focusedPageId = alternates[2].id;
    await controller.handleAction("review-toggle-alternates");
    assert.equal(state.review.pages.find(page => page.id === state.review.focusedPageId).minorityAlternate, false);
  }
});

test("review titles follow a language switch without changing ids or order", () => {
  const strips = ["/job/reflow/strips/strip_jmp-01-002.png", "/job/reflow/strips/strip_jmp-01-001.png", "/job/reflow/strips/alt/strip_jmp-01-001-alt1.png"];
  const result = { output_model: "clean_reflow_v1", review_candidates: strips, capture_diagnostics: {
    [strips[0]]: { system_id: "jmp-01-002", t_start: 12 },
    [strips[1]]: { system_id: "jmp-01-001", t_start: 4 },
    [strips[2]]: { system_id: "jmp-01-001-alt1", t_start: 6, diagnostic_codes: ["MINORITY_ALTERNATE"] },
  } };
  const ko = deriveCapturePages(result, "ko");
  assert.deepEqual(ko.map(page => page.title), ["줄 2", "줄 1", "줄 1 · 다른 순간 1"]);
  const en = ko.map(page => ({ ...page, title: localizePageTitle(page, "en") }));
  assert.deepEqual(en.map(page => page.title), ["System 2", "System 1", "System 1 · other moment 1"]);
  assert.deepEqual(en.map(page => page.title), deriveCapturePages(result, "en").map(page => page.title));
  assert.deepEqual(en.map(page => [page.id, page.capturePath]), ko.map(page => [page.id, page.capturePath]));
  assert.deepEqual(en.map(page => localizePageTitle(page, "ko")), ko.map(page => page.title));
  assert.equal(localizePageTitle({ kind: "capture", index: 3 }, "en"), "Page 3");
});

test("until a view is chosen the pages show, unless a jump video's line check opens by itself", async () => {
  const state = reviewState("en");
  assert.equal(state.review.pagePreview, null);
  assert.equal(pagePreviewOn(state), true);
  // seams the app verified need no look: still the pages
  const line = seams => ({ id: "l1", page: 1, rect: [0, 0, 10, 10], pageSize: [100, 100], sources: [], seams });
  state.review.reflow = { lines: [line([{ id: "s0", status: "verified", xFrac: 0.5 }])] };
  assert.equal(pagePreviewOn(state), true);
  // a seam to check opens the line check instead
  state.review.reflow = { lines: [line([{ id: "s1", status: "resolved", xFrac: 0.5 }])] };
  assert.equal(pagePreviewOn(state), false);
  state.review.pagePreview = true;
  assert.equal(pagePreviewOn(state), true);
  // comparing two systems leaves the pages
  let live = reviewState("en");
  live.review.focusedPageId = "3";
  const controller = createReviewController({ getState: () => live, setState: update => { live = update(structuredClone(live)); }, api: {}, root: {}, mountEditor() {} });
  await controller.handleAction("review-compare");
  assert.equal(live.review.compare, true);
  assert.equal(live.review.pagePreview, false);
  assert.match(renderReviewScreen(live), /review-viewer-surface is-comparing/);
});
