import test from "node:test";
import assert from "node:assert/strict";

const routes = await import("../renderer-v2/src/app/routes.js");
const selectors = await import("../renderer-v2/src/app/session/selectors.js");
const shell = await import("../renderer-v2/src/ui/shell/ContextLane.js");

test("export remains locked until source and applied roi are both ready", () => {
  const state = selectors.createInitialSessionState();

  state.source.filePath = "/tmp/example.mp4";
  state.roi.frameTime = 12.5;

  assert.equal(routes.canOpenStep(state, "export"), false);

  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];

  assert.equal(routes.canOpenStep(state, "export"), true);
});

test("review remains locked until generated pages exist", () => {
  const state = selectors.createInitialSessionState();

  state.source.filePath = "/tmp/example.mp4";
  state.roi.frameTime = 8;
  state.roi.appliedRect = [
    [0, 0],
    [640, 0],
    [640, 400],
    [0, 400],
  ];

  assert.deepEqual(selectors.getAccessibleSteps(state), ["source", "roi", "export"]);
  assert.equal(routes.canOpenStep(state, "review"), false);

  state.exportConfig.jobId = "job-1";
  state.exportConfig.runStatus = "done";
  state.review.pages = [{ id: "1", title: "페이지 1" }];

  assert.equal(routes.canOpenStep(state, "review"), true);
});

test("roi and export keep the context lane empty until a step needs a true inspector", () => {
  const state = selectors.createInitialSessionState();

  state.ui.activeStep = "roi";
  assert.equal(shell.renderContextLane(state), "");

  state.ui.activeStep = "export";
  assert.equal(shell.renderContextLane(state), "");
});
