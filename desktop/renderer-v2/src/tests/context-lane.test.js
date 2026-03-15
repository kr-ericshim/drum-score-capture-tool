import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { renderContextLane } from "../ui/shell/ContextLane.js";

test("context lane renders english source guidance when locale is en", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "source";

  const markup = renderContextLane(state);

  assert.match(markup, /SOURCE SUMMARY|INGEST STATUS|NEXT STEP/);
  assert.doesNotMatch(markup, /대표 프레임|먼저 로컬 영상을 선택합니다/);
});

test("context lane renders english review preview labels when locale is en", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "review";
  state.review.pages = [
    {
      id: "1",
      title: "Page 1",
      previewPath: "/tmp/page-1.png",
      previewKind: "output",
    },
  ];
  state.review.focusedPageId = "1";
  state.review.selectedPageIds = ["1"];

  const markup = renderContextLane(state);

  assert.match(markup, /OUTPUT Page 1/);
  assert.match(markup, /OUTPUT SUMMARY|NEXT ACTION/);
  assert.doesNotMatch(markup, /결과 요약|다음 작업/);
});
