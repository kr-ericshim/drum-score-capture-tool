import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { buildSourceScreenModel, renderSourceScreen } from "../features/source/SourceScreen.js";

test("source screen promotes file selection before metadata", () => {
  const state = createInitialSessionState();
  const model = buildSourceScreenModel(state);

  assert.equal(model.primaryAction.disabled, false);
  assert.match(model.primaryAction.label, /영상 선택|Choose Video/);
  assert.equal(model.fileMeta.length, 0);
  assert.equal(model.secondaryAction, null);
});

test("source screen exposes compact metadata after file selection", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/song.mp4";
  state.source.displayName = "song.mp4";
  state.source.metadata = { durationLabel: "02:31", resolutionLabel: "1920x1080" };

  const model = buildSourceScreenModel(state);

  assert.deepEqual(model.fileMeta, [
    { label: "파일", value: "song.mp4" },
    { label: "길이", value: "02:31" },
    { label: "해상도", value: "1920x1080" },
  ]);
});

test("source screen keeps only the real file-pick action", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/song.mp4";
  state.source.displayName = "song.mp4";
  state.source.metadata = { durationLabel: "02:31", resolutionLabel: "1920x1080" };

  const markup = renderSourceScreen(state);

  assert.match(markup, /data-action="select-source-file"/);
  assert.doesNotMatch(markup, /SCAN DIRECTORY|폴더 스캔/);
  assert.doesNotMatch(markup, /<button[^>]*>LOAD<\/button>/);
  assert.match(markup, /사용 중|ACTIVE/);
});

test("source registry reflects the actual selected file directory instead of a placeholder path", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/Users/tester/Videos/song.mp4";
  state.source.displayName = "song.mp4";
  state.source.metadata = { durationLabel: "02:31", resolutionLabel: "1920x1080" };

  const markup = renderSourceScreen(state);

  assert.match(markup, /\/Users\/tester\/Videos\//);
  assert.doesNotMatch(markup, /\/local\/session\//);
  assert.doesNotMatch(markup, /session_capture\.mp4/);
});

test("source screen renders english helper copy when locale is en", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";

  const markup = renderSourceScreen(state);

  assert.match(markup, /Choose Video|Open Local Video|Local Media Registry/i);
  assert.doesNotMatch(markup, /현재 1차 플로우는|로컬 영상 불러오기/);
});

test("source screen renders youtube controls and preparation log region", () => {
  const state = createInitialSessionState();

  const markup = renderSourceScreen(state);

  assert.match(markup, /YouTube|유튜브/i);
  assert.match(markup, /prepare-source-youtube/);
  assert.match(markup, /youtube-log|source-prepare-log|Preparation Log|준비 로그/i);
  assert.match(markup, /type="url"/);
  assert.match(markup, /inputmode="url"/);
});

test("source screen disables youtube prepare while loading and shows low-quality warning copy", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.prepareStatus = "loading";
  state.source.error = "YouTube preparation stopped because only a low-resolution video was available: low resolution 640x360";
  state.source.prepareErrorDetail = "low resolution 640x360";
  state.source.prepareLogs = ["low resolution 640x360"];

  const markup = renderSourceScreen(state);

  assert.match(markup, /prepare-source-youtube\" disabled/);
  assert.match(markup, /low-resolution warning|quality gate|640x360/i);
});

test("source screen keeps youtube prepare disabled until a youtube link is entered", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.youtubeUrl = "not-a-youtube-link";

  const markup = renderSourceScreen(state);

  assert.match(markup, /prepare-source-youtube\" disabled/);
  assert.match(markup, /Paste a valid YouTube link/i);
});
