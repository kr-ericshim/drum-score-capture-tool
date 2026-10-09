import test from "node:test";
import assert from "node:assert/strict";

import { normalizeReviewHypotheses } from "../lib/api.js";
import { createInitialSessionState, deriveReflowInfo } from "../app/session/selectors.js";
import { createReviewController } from "../features/review/reviewController.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";

const RESPONSE = {
  job_id: "job-1", status: "review_required", export_revision: 2,
  counts: { hypotheses: 3, bundles: 1, boundaries_safe: 40, boundaries_unknown: 5, pages: 4,
    by_code: { SOURCE_FOREGROUND_MISSING_OR_CHANGED: 1, DISPLAY_UNRESOLVED: 2 }, user_excluded: { displays: 1, items: 7 } },
  total: 3, offset: 0, limit: 2,
  hypotheses: [
    { id: "i1:SOURCE_FOREGROUND_MISSING_OR_CHANGED", item_id: "i1", display_id: "strip:sys-002", system_id: "sys-002",
      timestamp_sec: 42.25, status: "fail", code: "SOURCE_FOREGROUND_MISSING_OR_CHANGED", page_index: 2,
      raw_crop: "/w/export/review_hypotheses/i1_raw.png", primary_crop: "/w/export/review_hypotheses/i1_primary.png", crop_scale: 1 },
    { id: "i2:DISPLAY_UNRESOLVED", item_id: "i2", display_id: "occ:9", system_id: null, timestamp_sec: null,
      status: "unresolved", code: "DISPLAY_UNRESOLVED", page_index: null, raw_crop: "/w/export/review_hypotheses/i2_raw.png",
      primary_crop: null, crop_scale: 1 },
  ],
};

function reviewState(locale = "ko") {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.exportConfig.jobId = "job-1";
  state.exportConfig.runStatus = "done";
  state.review.jobRevision = 2;
  state.review.pages = [
    { id: "a", kind: "system", systemId: "sys-001", title: "줄 1", capturePath: "/s1.png", previewPath: "/s1.png" },
    { id: "b", kind: "system", systemId: "sys-002", title: "줄 2", capturePath: "/s2.png", previewPath: "/s2.png" },
  ];
  state.review.selectedPageIds = ["a", "b"];
  state.review.focusedPageId = "a";
  state.review.reflow = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { revision: 2,
    ledger_summary: { status: "review_required", review_hypotheses: 3 } } });
  return state;
}

function controllerFor(holder, api) {
  return createReviewController({ getState: () => holder.state, setState: update => { holder.state = update(structuredClone(holder.state)); },
    api, root: {}, mountEditor() {} });
}

test("hypothesis responses are normalized with counts, statuses and same-scale crop paths", () => {
  const page = normalizeReviewHypotheses(RESPONSE);
  assert.equal(page.status, "review_required");
  assert.equal(page.counts.hypotheses, 3);
  assert.equal(page.counts.boundariesUnknown, 5);
  assert.equal(page.counts.userExcludedItems, 7);
  assert.equal(page.items.length, 2);
  assert.equal(page.items[0].timestampSec, 42.25);
  assert.match(page.items[0].rawCrop, /^file:\/\/.*i1_raw\.png$/);
  assert.equal(page.items[1].primaryCrop, "");
  assert.equal(page.items[1].systemId, "");
  assert.equal(normalizeReviewHypotheses({ status: "unassessed" }).items.length, 0);
  const capped = normalizeReviewHypotheses({ hypotheses: [{ ...RESPONSE.hypotheses[0], raw_crop: "", primary_crop: null }] });
  assert.equal(capped.items[0].rawCrop, "");
  const state = reviewState("en");
  state.review.hypotheses = { ...state.review.hypotheses, open: true, status: "ready", items: capped.items, total: 1 };
  assert.match(renderReviewScreen(state), /No image/);
});

test("the ledger summary of a job result becomes the toolbar count", () => {
  const info = deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: { ledger_summary: { status: "pass", review_hypotheses: 0 } } });
  assert.deepEqual(info.ledger, { status: "pass", reviewHypotheses: 0 });
  assert.equal(deriveReflowInfo({ output_model: "clean_reflow_v1", reflow: {} }).ledger, null);
  const markup = renderReviewScreen(reviewState("en"));
  assert.match(markup, /data-action="review-hypotheses"[^>]*aria-pressed="false"[^>]*>Items to check 3</);
  const clean = reviewState("en");
  clean.review.reflow.ledger = { status: "pass", reviewHypotheses: 0 };
  assert.doesNotMatch(renderReviewScreen(clean), /data-action="review-hypotheses"/);
});

test("opening items to check loads one page, shows raw and result side by side, and loads more", async () => {
  const holder = { state: reviewState("ko") };
  const calls = [];
  const api = { async getReviewHypotheses(jobId, options) {
    calls.push([jobId, options.offset]);
    const data = options.offset ? { ...RESPONSE, offset: 2, hypotheses: [{ ...RESPONSE.hypotheses[1], id: "i3", item_id: "i3" }] } : RESPONSE;
    return normalizeReviewHypotheses(data);
  } };
  const controller = controllerFor(holder, api);
  await controller.handleAction("review-hypotheses");
  assert.deepEqual(calls, [["job-1", 0]]);
  assert.equal(holder.state.review.hypotheses.open, true);
  assert.equal(holder.state.review.hypotheses.status, "ready");
  let markup = renderReviewScreen(holder.state);
  assert.match(markup, /is-hypotheses/);
  assert.match(markup, /확인 필요 3개 · 다른 순간 1개 · 마디 경계 확실 40 \/ 불확실 5 · 4쪽/);
  assert.match(markup, /원본 화면 · 00:42\.2|원본 화면 · 00:42\.3/);
  assert.match(markup, /만든 결과 · 2쪽/);
  assert.match(markup, /검사 실패/);
  assert.match(markup, /결과에 없음/);
  assert.match(markup, /data-action="review-hypothesis-system" data-value="b">줄 2 보기/);
  assert.match(markup, /data-action="review-hypotheses-more"[^>]*>더 보기 \(2 \/ 3\)/);
  await controller.handleAction("review-hypotheses-more");
  assert.deepEqual(calls, [["job-1", 0], ["job-1", 2]]);
  assert.equal(holder.state.review.hypotheses.items.length, 3);
  assert.doesNotMatch(renderReviewScreen(holder.state), /review-hypotheses-more/);
  // closing and reopening the same revision does not reload
  await controller.handleAction("review-hypotheses");
  assert.equal(holder.state.review.hypotheses.open, false);
  await controller.handleAction("review-hypotheses");
  assert.equal(calls.length, 2);
});

test("a hypothesis leads to its system, and Escape closes the view", async () => {
  const holder = { state: reviewState("en") };
  const controller = controllerFor(holder, { getReviewHypotheses: async () => normalizeReviewHypotheses(RESPONSE) });
  await controller.handleAction("review-hypotheses");
  await controller.handleAction("review-hypothesis-system", "b");
  assert.equal(holder.state.review.hypotheses.open, false);
  assert.equal(holder.state.review.focusedPageId, "b");
  await controller.handleAction("review-hypotheses");
  holder.state.ui.activeStep = "review";
  controller.handleKey({ key: "Escape", target: { tagName: "DIV" }, preventDefault() {} });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(holder.state.review.hypotheses.open, false);
});

test("a failed load shows a retry, and an answer for another job is dropped", async () => {
  const holder = { state: reviewState("en") };
  let fail = true;
  const controller = controllerFor(holder, { async getReviewHypotheses() {
    if (fail) throw new Error("server unavailable");
    holder.state.exportConfig.jobId = "job-2";
    return normalizeReviewHypotheses(RESPONSE);
  } });
  await controller.handleAction("review-hypotheses");
  assert.equal(holder.state.review.hypotheses.status, "error");
  assert.match(renderReviewScreen(holder.state), /role="alert"[\s\S]*data-action="review-hypotheses-retry"/);
  fail = false;
  await controller.handleAction("review-hypotheses-retry");
  assert.equal(holder.state.review.hypotheses.items.length, 0);
  assert.notEqual(holder.state.review.hypotheses.status, "ready");
});

test("page view and items to check do not show at the same time", async () => {
  const holder = { state: reviewState("en") };
  holder.state.review.outputPages = [{ index: 1, path: "/p1.png" }];
  const controller = controllerFor(holder, { getReviewHypotheses: async () => normalizeReviewHypotheses(RESPONSE) });
  await controller.handleAction("review-page-preview");
  assert.equal(holder.state.review.pagePreview, true);
  await controller.handleAction("review-hypotheses");
  assert.equal(holder.state.review.pagePreview, false);
  await controller.handleAction("review-page-preview");
  assert.equal(holder.state.review.hypotheses.open, false);
  assert.equal(holder.state.review.pagePreview, true);
});
