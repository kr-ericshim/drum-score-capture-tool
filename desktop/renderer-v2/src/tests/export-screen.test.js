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
