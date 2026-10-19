import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState, getAccessibleSteps } from "../app/session/selectors.js";

test("accessible steps grow with workflow completion", () => {
  const state = createInitialSessionState();
  assert.deepEqual(getAccessibleSteps(state), ["source"]);

  state.source.filePath = "/tmp/video.mp4";
  assert.deepEqual(getAccessibleSteps(state), ["source", "roi"]);

  state.roi.frameTime = 3;
  state.roi.appliedRect = [[0, 0], [100, 0], [100, 100], [0, 100]];
  assert.deepEqual(getAccessibleSteps(state), ["source", "roi", "export"]);
});

