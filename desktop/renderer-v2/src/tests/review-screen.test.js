import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";

function createReviewState() {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.review.pages = [
    {
      id: "1",
      title: "페이지 1",
      capturePath: "/tmp/page-1.png",
      previewPath: "file:///tmp/page-1.png",
    },
  ];
  state.review.selectedPageIds = ["1"];
  state.review.focusedPageId = "1";
  return state;
}

test("review apply action stays disabled without a job id even when pages are selected", () => {
  const state = createReviewState();

  const markup = renderReviewScreen(state);

  assert.match(markup, /data-action="apply-review"[^>]*disabled/);
});

test("review apply action stays disabled while review export is running", () => {
  const state = createReviewState();
  state.exportConfig.jobId = "job-1";
  state.review.status = "running";

  const markup = renderReviewScreen(state);

  assert.match(markup, /data-action="apply-review"[^>]*disabled/);
});

test("review screen removes the apply action after review export has already been applied", () => {
  const state = createReviewState();
  state.exportConfig.jobId = "job-1";
  state.review.status = "applied";
  state.review.outputDir = "/tmp/export";
  state.review.pdfPath = "/tmp/export/result.pdf";

  const markup = renderReviewScreen(state);

  assert.doesNotMatch(markup, /data-action="apply-review"/);
  assert.match(markup, /검토 반영 완료|다시 생성할 필요가 없습니다/);
  assert.match(markup, /결과 폴더와 PDF를 엽니다/);
});

test("review screen locks selection controls after review export has already been applied", () => {
  const state = createReviewState();
  state.exportConfig.jobId = "job-1";
  state.review.status = "applied";

  const markup = renderReviewScreen(state);

  assert.match(markup, /data-action="toggle-review-page"[^>]*disabled/);
});

test("review selection controls include page-specific accessible labels", () => {
  const state = createReviewState();
  state.exportConfig.jobId = "job-1";

  const markup = renderReviewScreen(state);

  assert.match(markup, /aria-label="페이지 1 포함 여부"/);
});

test("review screen removes decorative review controls outside the real flow", () => {
  const state = createReviewState();
  state.exportConfig.jobId = "job-1";

  const markup = renderReviewScreen(state);

  assert.doesNotMatch(markup, /Add Frame|RECROP|ZOOM/);
  assert.doesNotMatch(markup, /mode-switch/);
  assert.doesNotMatch(markup, /결과 폴더 열기/);
  assert.match(markup, /data-action="apply-review"/);
});

test("review screen brings the apply action into the review toolbar instead of leaving a detached footer button", () => {
  const state = createReviewState();
  state.exportConfig.jobId = "job-1";

  const markup = renderReviewScreen(state);

  assert.match(markup, /review-toolbar/);
  assert.match(markup, /review-summary-pill/);
  assert.match(markup, /data-action="apply-review"/);
  assert.doesNotMatch(markup, /review-grid-actions/);
});

test("review screen reports kept capture count after review export is applied", () => {
  const state = createReviewState();
  state.exportConfig.jobId = "job-1";
  state.review.status = "applied";
  state.review.keptCount = 3;

  const markup = renderReviewScreen(state);

  assert.match(markup, /유지 3/);
});
