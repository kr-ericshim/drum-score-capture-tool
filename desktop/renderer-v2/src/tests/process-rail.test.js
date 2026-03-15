import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState, getProcessRailItems } from "../app/session/selectors.js";
import { renderProcessRail } from "../ui/shell/ProcessRail.js";

test("roi rail drops the workbench footer and keeps only the step guidance", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.ui.activeStep = "roi";
  state.source.filePath = "/tmp/video.mp4";

  const markup = renderProcessRail(state, getProcessRailItems(state));

  assert.doesNotMatch(markup, /WORKBENCH STATUS/);
  assert.match(markup, /대표 프레임을 불러온 뒤 ROI를 잡고 다음으로/);
});

test("review rail footer renders output paths in a dedicated wrapping block", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "review";
  state.exportConfig.formats = ["png", "pdf"];
  state.review.outputDir = "/Users/ericshim/Documents/myproject/score_capture_program/backend/jobs/1aadbac1-e23b-471f-ad06-a554f290c9f5/export";
  state.review.selectedPageIds = ["1"];

  const markup = renderProcessRail(state, getProcessRailItems(state));

  assert.match(markup, /rail-path-block/);
  assert.match(markup, /data-path-kind="output-dir"/);
  assert.doesNotMatch(markup, /<span>OUTPUT<\/span>\s*<strong>\/Users\/ericshim/);
  assert.match(markup, />OPEN PDF</);
});
