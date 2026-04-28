import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { buildExportScreenModel, renderExportScreen } from "../features/export/ExportScreen.js";

test("export screen exposes an app-managed destination summary before run", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.displayName = "practice.mp4";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];

  const model = buildExportScreenModel(state);

  assert.equal(model.destinationLabel, "앱 관리 폴더");
  assert.match(model.destinationValue, /작업 실행 후 생성|자동 생성/);
});

test("export screen does not advertise a fallback format when no formats are selected", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.displayName = "practice.mp4";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.formats = [];

  const model = buildExportScreenModel(state);

  assert.equal(model.formatsLabel, "선택 필요");
});

test("export primary action is disabled when no formats are selected", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.displayName = "practice.mp4";
  state.source.filePath = "/tmp/practice.mp4";
  state.roi.frameTime = 5;
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.formats = [];

  const markup = renderExportScreen(state);

  assert.match(markup, /data-action="run-export"[^>]*disabled/);
  assert.match(markup, /최소 하나의 출력 형식|형식을 선택/);
});

test("export screen exposes an accessible progress indicator", () => {
  const state = createInitialSessionState();
  state.source.displayName = "practice.mp4";
  state.source.filePath = "/tmp/practice.mp4";
  state.roi.frameTime = 5;
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.runStatus = "running";
  state.exportConfig.progress = 0.42;

  const markup = renderExportScreen(state);

  assert.match(markup, /role="progressbar"/);
  assert.match(markup, /aria-valuenow="42"/);
});

test("export screen locks format toggles while an export is already running", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.formats = ["png", "pdf"];
  state.exportConfig.runStatus = "running";

  const markup = renderExportScreen(state);

  assert.match(markup, /data-format="pdf" type="checkbox" checked disabled/);
  assert.match(markup, /data-format="png" type="checkbox" checked disabled/);
});

test("export screen clamps overshoot progress before rendering", () => {
  const state = createInitialSessionState();
  state.source.displayName = "practice.mp4";
  state.source.filePath = "/tmp/practice.mp4";
  state.roi.frameTime = 5;
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.runStatus = "running";
  state.exportConfig.progress = 1.4;

  const markup = renderExportScreen(state);

  assert.match(markup, /aria-valuenow="100"/);
  assert.match(markup, /width:100%/);
});

test("export screen removes decorative controls that are not part of the real flow", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.displayName = "practice.mp4";
  state.source.filePath = "/tmp/practice.mp4";
  state.roi.frameTime = 5;
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];

  const markup = renderExportScreen(state);

  assert.doesNotMatch(markup, /DISCARD ANALYSIS/);
  assert.doesNotMatch(markup, /class="path-more"/);
  assert.doesNotMatch(markup, /export-preview-tools/);
  assert.doesNotMatch(markup, /Sheet Density|Binarization Threshold/);
  assert.match(markup, /Processing Profile|처리 프로파일/);
});

test("export screen stays preview-first and avoids generic dashboard copy", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.displayName = "practice.mp4";
  state.source.filePath = "/tmp/practice.mp4";
  state.roi.previewImage = "/tmp/frame.png";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];

  const markup = renderExportScreen(state);

  assert.match(markup, /Preview first/);
  assert.match(markup, /ROI Preview|출력 전 미리보기/);
  assert.doesNotMatch(markup, /SYSTEM STATUS|INSPECTION VIEW|UTILITY RAIL/i);
});

test("export screen avoids fabricated slice and zoom counters in the preview workbench", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.roi.previewImage = "C:\\captures\\frame 1#.png";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];

  const markup = renderExportScreen(state);

  assert.doesNotMatch(markup, /Slice 14\/42|Zoom 100%|EXTRACTION NODE/);
  assert.match(markup, /file:\/\/\/C:\/captures\/frame%201%23\.png/);
});

test("export screen previews the applied ROI crop instead of the whole frame when geometry is available", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.source.metadata = { width: 1920, height: 1080 };
  state.roi.previewImage = "/tmp/frame.png";
  state.roi.appliedRect = [
    [120, 700],
    [1560, 700],
    [1560, 980],
    [120, 980],
  ];

  const markup = renderExportScreen(state);

  assert.match(markup, /export-preview-crop/);
  assert.match(markup, /--crop-x:120;/);
  assert.match(markup, /--crop-w:1440;/);
});

test("export screen uses a wrapping output directory field for long managed paths", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.outputDir = "/Users/ericshim/Documents/myproject/score_capture_program/backend/jobs/1aadbac1-e23b-471f-ad06-a554f290c9f5/export";

  const markup = renderExportScreen(state);

  assert.match(markup, /class="path-field path-field-wrap"/);
});

test("export screen treats missing format arrays as no selection instead of crashing", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.formats = undefined;

  const markup = renderExportScreen(state);

  assert.match(markup, /Select at least one output format|최소 하나의 출력 형식/);
  assert.match(markup, /data-action="run-export"[^>]*disabled/);
});

test("export screen requires a valid roi rect before enabling run", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.exportConfig.formats = ["png"];
  state.roi.appliedRect = { bad: true };

  const model = buildExportScreenModel(state);
  const markup = renderExportScreen(state);

  assert.equal(model.canRun, false);
  assert.match(markup, /data-action="run-export"[^>]*disabled/);
});

test("export screen keeps metadata inputs off the left stack until the modal opens", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.roi.previewImage = "/tmp/frame.png";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.formats = ["pdf"];

  const closedMarkup = renderExportScreen(state);

  assert.doesNotMatch(closedMarkup, /data-action="update-export-metadata"/);
  assert.match(closedMarkup, /PDF 첫 페이지 상단에만 반영됩니다\.|Applies only to the first PDF page\./);

  state.exportConfig.formats = ["png"];
  const pngOnlyMarkup = renderExportScreen(state);
  assert.doesNotMatch(pngOnlyMarkup, /PDF 첫 페이지 상단에만 반영됩니다\.|Applies only to the first PDF page\./);

  state.exportConfig.formats = ["pdf"];
  state.exportConfig.metadataModal.isOpen = true;
  state.exportConfig.metadataModal.draft = {
    title: "Take Five",
    performer: "Dave Brubeck Quartet",
    bpm: "174",
    date: "2026-04-19",
    memo: "",
  };

  const openMarkup = renderExportScreen(state);

  assert.match(openMarkup, /class="export-preview-workbench"/);
  assert.match(openMarkup, /class="export-metadata-overlay"/);
  assert.match(openMarkup, /data-action="update-export-metadata"/);
  assert.match(openMarkup, /PDF 첫 페이지 상단에만 반영됩니다\.|Applies only to the first PDF page\./);
});

test("export screen surfaces export-start failures inside the metadata modal", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = "practice.mp4";
  state.roi.previewImage = "/tmp/frame.png";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.formats = ["pdf"];
  state.exportConfig.error = "backend unavailable";
  state.exportConfig.metadataModal = {
    isOpen: true,
    draft: {
      title: "Blue in Green",
      performer: "",
      bpm: "128",
      date: "2026-04-19",
      memo: "",
    },
    dirty: false,
    validation: { title: "", bpm: "" },
    showDiscardConfirm: false,
  };

  const markup = renderExportScreen(state);

  assert.match(markup, /class="inline-error export-metadata-submit-error"[^>]*>backend unavailable</);
  assert.equal((markup.match(/backend unavailable/g) || []).length, 1);
});

test("export screen escapes dynamic filename, path, and status text before rendering", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.filePath = "/tmp/practice.mp4";
  state.source.displayName = '\"><svg/onload=alert(1)>';
  state.roi.previewImage = "/tmp/frame.png";
  state.roi.appliedRect = [
    [0, 0],
    [320, 0],
    [320, 180],
    [0, 180],
  ];
  state.exportConfig.outputDir = '<script>alert("dir")</script>';
  state.exportConfig.message = '<img src=x onerror=alert(1)>';

  const markup = renderExportScreen(state);

  assert.doesNotMatch(markup, /<script>alert\("dir"\)<\/script>/);
  assert.doesNotMatch(markup, /<img src=x onerror=alert\(1\)>/);
  assert.match(markup, /&lt;script&gt;alert\(&quot;dir&quot;\)&lt;\/script&gt;/);
  assert.match(markup, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(markup, /alt="&quot;&gt;&lt;svg\/onload=alert\(1\)&gt; representative frame"/);
});
