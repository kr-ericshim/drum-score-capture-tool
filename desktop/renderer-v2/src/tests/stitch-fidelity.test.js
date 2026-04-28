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
import { renderContextLane } from "../ui/shell/ContextLane.js";
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

test("top bar exposes locale toggle state with pressed semantics", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";

  const markup = renderTopBar(state, {
    sourceLabel: "song.mp4",
    stepLabel: "source",
    stepState: { enabled: true, complete: false },
  });

  assert.match(markup, /topbar-locale-group/);
  assert.match(markup, /data-locale="en" aria-pressed="true"/);
  assert.match(markup, /data-locale="ko" aria-pressed="false"/);
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
  assert.match(markup, /영역 지정/);
  assert.match(markup, /class="topbar-roi"/);
  assert.match(markup, /class="topbar-balance"/);
  assert.match(markup, /class="topbar-tools topbar-tools-compact"/);
  assert.doesNotMatch(markup, /DRUM SHEET CAPTURE|ENGINE_READY|ENGINE_WAITING/);
});

test("source screen exposes ingest zone and media registry structure", () => {
  const state = createInitialSessionState();
  const markup = renderSourceScreen(state);

  assert.match(markup, /data-stitch-region="source-ingest"/);
  assert.match(markup, /data-stitch-region="source-registry"/);
  assert.match(markup, /Reopen recent|다시 열기/);
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

  assert.match(markup, /Saved output|현재 출력 결과/);
  assert.match(markup, /Open PDF/);
  assert.match(markup, /Copy path|경로 복사/);
});

test("shell surfaces reject generic workbench vocabulary and keep task-first labels", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.ui.activeStep = "source";
  state.ui.backend = { ready: true };
  state.source.filePath = "/tmp/video.mp4";
  state.source.displayName = "video.mp4";
  state.source.metadata = {
    resolutionLabel: "1920x1080",
    durationLabel: "01:24",
  };

  const reviewState = createInitialSessionState();
  reviewState.ui.locale = "en";
  reviewState.ui.activeStep = "review";

  const topBarMarkup = renderTopBar(state, {
    sourceLabel: "video.mp4",
    stepLabel: "source",
    stepState: { enabled: true, complete: false },
  });
  const railMarkup = renderProcessRail(state, getProcessRailItems(state));
  const laneMarkup = renderContextLane(reviewState);

  assert.match(topBarMarkup, />Drum Sheet Capture</);
  assert.match(topBarMarkup, /Processor ready/);
  assert.match(railMarkup, />Steps</);
  assert.match(railMarkup, />Ready</);
  assert.match(laneMarkup, />Selected result</);

  const combinedMarkup = `${topBarMarkup} ${railMarkup} ${laneMarkup}`;
  assert.doesNotMatch(combinedMarkup, /Workflow|System status|Inspection view|ENGINE_READY|WORKBENCH STATUS|PIPELINE/);
  assert.doesNotMatch(railMarkup, /SYSTEM RESOURCES|BUFFER|32%/);
});
