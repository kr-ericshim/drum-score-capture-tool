import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState, deriveCapturePages, needsAttention } from "../app/session/selectors.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { createReviewController } from "../features/review/reviewController.js";

function similarResult() {
  return {
    review_candidates: ["/job/rectified/frame_0000.png", "/job/rectified/frame_0004.png", "/job/rectified/frame_0009.png"],
    similar_capture_pairs: [
      {
        kept: "/job/rectified/frame_0004.png",
        candidate: "/job/rectified/frame_0009.png",
        reason: "small_change",
        metrics: {
          verdict: "ambiguous",
          reason: "small_change",
          frame_size: [1400, 900],
          change_boxes: [[700, 450, 28, 18], [140, 90, 14, 9]],
        },
      },
    ],
  };
}

function reviewState(result, locale = "ko") {
  const state = createInitialSessionState();
  state.ui.locale = locale;
  state.review.pages = deriveCapturePages(result, locale);
  state.review.selectedPageIds = state.review.pages.map((page) => page.id);
  state.review.focusedPageId = "3";
  state.exportConfig.jobId = "job-1";
  return state;
}

test("deriveCapturePages attaches similar-pair info to the candidate page with normalized change boxes", () => {
  const pages = deriveCapturePages(similarResult());

  assert.equal(pages[0].similarTo, null);
  assert.equal(pages[1].similarTo, null);
  assert.equal(pages[2].similarTo.referenceId, "2");
  assert.equal(pages[2].similarTo.referenceIndex, 2);
  assert.equal(pages[2].similarTo.reason, "small_change");
  assert.equal(pages[2].similarTo.changeCount, 2);
  assert.deepEqual(pages[2].similarTo.changeBoxes[0], { left: 0.5, top: 0.5, width: 0.02, height: 0.02 });
  assert.equal(needsAttention(pages[2]), true);
  assert.equal(needsAttention(pages[1]), false);
});

test("deriveCapturePages matches similar pairs by file name when capture paths were rewritten", () => {
  const result = similarResult();
  result.review_candidates = ["/moved/frame_0000.png", "/moved/frame_0004.png", "/moved/frame_0009.png"];

  const pages = deriveCapturePages(result);

  assert.equal(pages[2].similarTo.referenceId, "2");
});

test("deriveCapturePages ignores malformed similar pairs", () => {
  const pages = deriveCapturePages({
    review_candidates: ["/a.png", "/b.png"],
    similar_capture_pairs: [{ kept: "/a.png" }, null, { candidate: "/b.png", metrics: { change_boxes: "nope" } }],
  });

  assert.equal(pages[0].similarTo, null);
  assert.equal(pages[1].similarTo.changeCount, 0);
  assert.equal(pages[1].similarTo.reason, "small_change");
});

test("review screen flags the near-identical page and explains the reason with a compare action", () => {
  const state = reviewState(similarResult());

  const markup = renderReviewScreen(state);

  assert.match(markup, /review-inline-pill-similar">비슷한 페이지</);
  assert.match(markup, /기준: 페이지 2/);
  assert.match(markup, /바뀐 부분 2곳/);
  assert.match(markup, /data-action="review-compare" aria-pressed="false"[^>]*>나란히 비교</);
  assert.match(markup, /data-action="focus-review-page" data-page-id="2">페이지 2 보기</);
  assert.doesNotMatch(markup, /review-compare-stage/);
});

test("review screen renders the side-by-side compare stage with highlighted change boxes", () => {
  const state = reviewState(similarResult(), "en");
  state.review.compare = true;

  const markup = renderReviewScreen(state);

  assert.match(markup, /review-compare-stage is-stacked/);
  assert.match(markup, /is-reference[\s\S]*frame_0004\.png[\s\S]*Page 2 · reference/);
  assert.match(markup, /is-current[\s\S]*frame_0009\.png[\s\S]*Page 3 · this page/);
  assert.equal((markup.match(/class="review-change-box"/g) || []).length, 4);
  assert.match(markup, /left:50\.00%;top:50\.00%;width:2\.00%;height:2\.00%/);
  assert.match(markup, /data-action="review-compare" aria-pressed="true"[^>]*>Close compare</);
  assert.doesNotMatch(markup, /review-full-image/);
});

test("portrait pages compare side by side", () => {
  const result = similarResult();
  result.similar_capture_pairs[0].metrics.frame_size = [900, 1300];
  const state = reviewState(result, "en");
  state.review.compare = true;

  const markup = renderReviewScreen(state);

  assert.match(markup, /review-compare-stage is-side-by-side/);
});

test("review screen explains a playhead reset without change boxes", () => {
  const result = similarResult();
  result.similar_capture_pairs[0].reason = "playhead_reset";
  result.similar_capture_pairs[0].metrics.change_boxes = [];
  const state = reviewState(result);

  const markup = renderReviewScreen(state);

  assert.match(markup, /재생선이 처음으로 돌아가서/);
  assert.match(markup, /기준: 페이지 2/);
});

test("attention filter includes near-identical pages", () => {
  const state = reviewState(similarResult());
  state.review.filter = "suspicious";

  const markup = renderReviewScreen(state);

  assert.match(markup, /data-value="suspicious" aria-pressed="true">확인 필요 <span>1<\/span>/);
  assert.equal((markup.match(/<article class="review-card/g) || []).length, 1);
  assert.match(markup, /frame_0009\.png/);
});

test("review controller toggles compare and leaves it when cropping starts", async () => {
  let state = reviewState(similarResult());
  const controller = createReviewController({
    getState: () => state,
    setState: (update) => { state = update(structuredClone(state)); },
    api: {},
    root: {},
    mountEditor() {},
  });

  await controller.handleAction("review-compare");
  assert.equal(state.review.compare, true);
  await controller.handleAction("review-compare");
  assert.equal(state.review.compare, false);
  await controller.handleAction("review-compare");
  await controller.handleAction("review-crop");
  assert.equal(state.review.cropping, true);
  assert.equal(state.review.compare, false);
});
