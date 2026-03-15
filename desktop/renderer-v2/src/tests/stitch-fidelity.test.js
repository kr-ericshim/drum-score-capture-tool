import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { renderSourceScreen } from "../features/source/SourceScreen.js";
import { renderRoiScreen } from "../features/roi/RoiScreen.js";
import { renderExportScreen } from "../features/export/ExportScreen.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { mountShell } from "../ui/shell/AppShell.js";
import { renderTopBar } from "../ui/shell/TopBar.js";
import { renderProcessRail } from "../ui/shell/ProcessRail.js";
import { getProcessRailItems } from "../app/session/selectors.js";

function createShellRoot() {
  const nodes = {
    "#topBar": { innerHTML: "" },
    "#processRail": { innerHTML: "" },
    "#stagePane": { innerHTML: "", querySelector: () => null },
    "#contextLane": { innerHTML: "" },
    "#statusBar": { innerHTML: "" },
  };

  return {
    innerHTML: "",
    querySelector(selector) {
      return nodes[selector] || null;
    },
  };
}

test("shell includes a persistent footer status bar for Stitch chrome", () => {
  const root = createShellRoot();
  mountShell(root);

  assert.match(root.innerHTML, /id="statusBar"/);
});

test("top bar drops the generic workflow-v2 meta-chip identity", () => {
  const state = createInitialSessionState();
  const markup = renderTopBar(state, {
    sourceLabel: "소스 미선택",
    stepLabel: "source",
    stepState: { enabled: true, complete: false },
  });

  assert.doesNotMatch(markup, /Core Workflow v2/);
  assert.doesNotMatch(markup, /meta-chip/);
  assert.doesNotMatch(markup, /aria-label="도움말"|aria-label="설정"/);
});

test("roi top bar collapses to source and step only", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.ui.activeStep = "roi";

  const markup = renderTopBar(state, {
    sourceLabel: "song.mp4",
    stepLabel: "roi",
    stepState: { enabled: true, complete: false },
  });

  assert.match(markup, /song\.mp4/);
  assert.match(markup, /ROI 프레임 선택/);
  assert.doesNotMatch(markup, /DRUM SHEET CAPTURE|ENGINE_READY|ENGINE_WAITING/);
});

test("source screen exposes ingest zone and media registry structure", () => {
  const state = createInitialSessionState();
  const markup = renderSourceScreen(state);

  assert.match(markup, /data-stitch-region="source-ingest"/);
  assert.match(markup, /data-stitch-region="source-registry"/);
  assert.match(markup, /Local Media Registry|미디어 레지스트리/);
});

test("roi screen exposes a simplified frame scrubber and action bar around the stage", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/video.mp4";
  state.source.metadata = { durationSec: 120 };

  const markup = renderRoiScreen(state);

  assert.match(markup, /data-stitch-region="roi-toolbar"/);
  assert.match(markup, /data-stitch-region="roi-actions"/);
  assert.doesNotMatch(markup, /ROI RECT|DRAG ON FRAME/);
});

test("export screen keeps the simplified config stack and roi preview workbench", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/source.mp4";
  state.source.displayName = "source.mp4";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];

  const markup = renderExportScreen(state);

  assert.match(markup, /data-stitch-region="export-config"/);
  assert.match(markup, /data-stitch-region="export-preview"/);
  assert.doesNotMatch(markup, /data-stitch-region="export-metrics"/);
  assert.match(markup, /class="export-preview-note"/);
});

test("review screen uses a grid-first review workspace instead of preview-first strip layout", () => {
  const state = createInitialSessionState();
  state.exportConfig.jobId = "job-1";
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

  const markup = renderReviewScreen(state);

  assert.match(markup, /data-stitch-region="review-grid"/);
  assert.doesNotMatch(markup, /Add Frame|프레임 추가/);
  assert.doesNotMatch(markup, /큰 미리보기/);
});

test("review process rail keeps export settings and finalize actions in the left column", () => {
  const state = createInitialSessionState();
  state.ui.activeStep = "review";
  state.exportConfig.jobId = "job-1";
  state.review.outputDir = "/tmp/export";
  state.review.pdfPath = "/tmp/export/result.pdf";

  const markup = renderProcessRail(state, getProcessRailItems(state));

  assert.match(markup, /EXPORT SETTINGS/);
  assert.match(markup, /OPEN PDF/);
  assert.match(markup, /COPY PATH|경로 복사/);
});

test("source process rail uses live workbench status instead of fabricated system resource meters", () => {
  const state = createInitialSessionState();
  state.ui.activeStep = "source";

  const markup = renderProcessRail(state, getProcessRailItems(state));

  assert.match(markup, /WORKBENCH STATUS/);
  assert.doesNotMatch(markup, /SYSTEM RESOURCES|BUFFER|32%/);
});
