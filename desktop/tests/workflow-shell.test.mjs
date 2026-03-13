import test from "node:test";
import assert from "node:assert/strict";

const shell = await import("../renderer/modules/workflow-shell.js");

test("resolveWorkflowActiveStep falls back from stale review step when there is no result", () => {
  assert.equal(
    shell.resolveWorkflowActiveStep({
      manualOpenStep: "review",
      progressStep: "source",
      hasResultOutput: false,
      openedStep: "review",
    }),
    "source",
  );
});

test("resolveWorkflowActiveStep preserves the review step when result output exists", () => {
  assert.equal(
    shell.resolveWorkflowActiveStep({
      manualOpenStep: "review",
      progressStep: "review",
      hasResultOutput: true,
      openedStep: "review",
    }),
    "review",
  );
});
