import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { renderContextLane } from "../ui/shell/ContextLane.js";

test("context lane stays hidden on source because the source screen already owns that context", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "source";

  const markup = renderContextLane(state);

  assert.equal(markup, "");
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

  assert.match(markup, /Result Page 1/);
  assert.match(markup, /Review summary|Next step/);
  assert.doesNotMatch(markup, /결과 요약|다음 작업/);
});

test("context lane stays hidden for source, roi, and export when there is no selection-specific inspector", () => {
  const state = createInitialSessionState();

  state.ui.activeStep = "source";
  assert.equal(renderContextLane(state), "");

  state.ui.activeStep = "roi";
  assert.equal(renderContextLane(state), "");

  state.ui.activeStep = "export";
  assert.equal(renderContextLane(state), "");
});
