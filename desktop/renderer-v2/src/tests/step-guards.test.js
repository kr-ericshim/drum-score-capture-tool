import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState, getAccessibleSteps, getPrimaryAction } from "../app/session/selectors.js";

test("accessible steps grow with workflow completion", () => {
  const state = createInitialSessionState();
  assert.deepEqual(getAccessibleSteps(state), ["source"]);

  state.source.filePath = "/tmp/video.mp4";
  assert.deepEqual(getAccessibleSteps(state), ["source", "roi"]);

  state.roi.frameTime = 3;
  state.roi.appliedRect = [[0, 0], [100, 0], [100, 100], [0, 100]];
  assert.deepEqual(getAccessibleSteps(state), ["source", "roi", "export"]);
});

test("primary action reflects the active step", () => {
  const state = createInitialSessionState();
  let action = getPrimaryAction(state);
  assert.match(action.label, /영상 선택|Choose Video/);

  state.source.filePath = "/tmp/video.mp4";
  state.ui.activeStep = "roi";
  action = getPrimaryAction(state);
  assert.match(action.label, /대표 프레임|Load Frame|불러오기/);
});
