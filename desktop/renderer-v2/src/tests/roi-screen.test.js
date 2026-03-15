import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { buildRoiScreenModel, renderRoiScreen } from "../features/roi/RoiScreen.js";

test("roi screen distinguishes draft and applied states", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/video.mp4";
  state.source.metadata = { durationSec: 120, durationLabel: "02:00" };
  state.roi.frameTime = 15;
  state.roi.frameTimeLabel = "00:15.0";
  state.roi.previewImage = "/tmp/frame.png";
  state.roi.draftRect = [[10, 10], [110, 10], [110, 90], [10, 90]];

  let model = buildRoiScreenModel(state);
  assert.equal(model.statusTone, "draft");
  assert.match(model.statusText, /프레임을 확인한 뒤 ROI를 확정하세요/);

  state.roi.appliedRect = state.roi.draftRect;
  model = buildRoiScreenModel(state);
  assert.equal(model.statusTone, "ready");
  assert.match(model.statusText, /확정/);
});

test("roi screen enables frame loading after source selection", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/video.mp4";

  const model = buildRoiScreenModel(state);
  assert.equal(model.loadFrameDisabled, false);
});

test("roi screen removes fake tool buttons and keeps only frame-load/apply actions", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/video.mp4";
  state.source.metadata = { durationSec: 120 };

  const markup = renderRoiScreen(state);

  assert.match(markup, /data-action="load-preview-frame"/);
  assert.doesNotMatch(markup, /data-action="apply-roi"/);
  assert.doesNotMatch(markup, /aria-label="포인터"|aria-label="이동"|aria-label="확대"|aria-label="축소"|aria-label="처음"/);
});

test("roi screen normalizes preview image paths for local rendering", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/video.mp4";
  state.source.metadata = { durationSec: 120 };
  state.roi.previewImage = "C:\\captures\\frame 1#.png";

  const markup = renderRoiScreen(state);

  assert.match(markup, /file:\/\/\/C:\/captures\/frame%201%23\.png/);
});

test("roi screen does not render a broken image element before a preview frame exists", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/video.mp4";
  state.source.metadata = { durationSec: 120 };

  const markup = renderRoiScreen(state);

  assert.doesNotMatch(markup, /id="roiImage"/);
  assert.match(markup, /대표 프레임을 불러오면 여기서 ROI를 지정합니다/);
});

test("roi screen keeps frame controls simple before and after preview load", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.filePath = "/tmp/video.mp4";
  state.source.metadata = { durationSec: 120 };

  let markup = renderRoiScreen(state);
  assert.match(markup, /id="frameTimeSlider"/);
  assert.match(markup, /LOAD FRAME/);
  assert.doesNotMatch(markup, /ROI RECT|DRAG ON FRAME/);
  assert.doesNotMatch(markup, /data-stitch-region="roi-transport"/);

  state.roi.previewImage = "/tmp/frame.png";
  state.roi.draftRect = [[10, 10], [110, 10], [110, 90], [10, 90]];
  markup = renderRoiScreen(state);
  assert.match(markup, /APPLY ROI/);
  assert.match(markup, /Inspect the frame, then lock the ROI/);
});
