import test from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../app/session/store.js";
import { createInitialSessionState, formatSecondsLabel } from "../app/session/selectors.js";
import { createSourceController } from "../features/source/sourceController.js";

function deferred() {
  let resolve = () => {};
  let reject = () => {};
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createController(overrides = {}) {
  const store = createStore(createInitialSessionState());
  const controller = createSourceController({
    store,
    readMetadata: async () => ({
      durationSec: 60,
      durationLabel: "01:00",
      resolutionLabel: "1920x1080",
    }),
    formatSecondsLabel,
    resetDownstream(next) {
      next.roi.previewImage = "";
      next.exportConfig.jobId = "";
      next.review.pages = [];
    },
    baseName(filePath) {
      return String(filePath).split("/").pop();
    },
    messages: {
      youtubePrepareError(error) {
        return String(error?.message || error);
      },
      mergePrepareLogs(existing, error) {
        return [...(existing || []), String(error?.message || error)];
      },
    },
    ...overrides,
  });

  return { store, controller };
}

test("controller marks youtube prepare as loading and records the prepare job id", () => {
  const { store, controller } = createController();
  const requestToken = controller.startYoutubePrepare("https://youtu.be/demo");

  controller.applyPrepareJobStarted("source-1", requestToken);

  const state = store.getState();
  assert.equal(state.source.prepareStatus, "loading");
  assert.equal(state.source.prepareJobId, "source-1");
  assert.equal(state.source.prepareStage, "queued");
  assert.equal(state.source.filePath, "");
});

test("controller applies a running prepare snapshot without promoting file state", () => {
  const { store, controller } = createController();
  const requestToken = controller.startYoutubePrepare("https://youtu.be/demo");
  controller.applyPrepareJobStarted("source-1", requestToken);
  controller.applyPrepareJobSnapshot({
    jobId: "source-1",
    status: "running",
    stage: "download",
    progress: 0.42,
    progressMode: "determinate",
    message: "downloading video 42%",
    logLines: ["yt-dlp: download 42%"],
    result: {},
  }, requestToken);

  const state = store.getState();
  assert.equal(state.source.prepareStage, "download");
  assert.equal(state.source.prepareProgress, 0.42);
  assert.equal(state.source.prepareProgressMode, "determinate");
  assert.equal(state.source.prepareMessage, "downloading video 42%");
  assert.equal(state.source.filePath, "");
});

test("controller promotes a completed youtube prepare snapshot into canonical file state", async () => {
  const { store, controller } = createController();
  const requestToken = controller.startYoutubePrepare("https://youtu.be/demo");
  controller.applyPrepareJobStarted("source-1", requestToken);
  const snapshot = {
    jobId: "source-1",
    status: "done",
    stage: "done",
    progress: 1,
    progressMode: "determinate",
    message: "youtube source ready",
    logLines: ["youtube download saved: /tmp/cache/demo.mp4"],
    result: {
      videoPath: "/tmp/cache/demo.mp4",
      fromCache: false,
    },
  };

  controller.applyPrepareJobSnapshot(snapshot, requestToken);
  await controller.completeYoutubePrepare(snapshot, requestToken);

  const state = store.getState();
  assert.equal(state.source.filePath, "/tmp/cache/demo.mp4");
  assert.equal(state.source.preparedFromYouTube, true);
  assert.equal(state.ui.activeStep, "roi");
  assert.equal(state.roi.previewCandidates.length, 3);
  assert.equal(state.roi.selectedPreviewCandidateId, "preview-candidate-2");
  assert.equal(state.roi.frameTime, state.roi.previewCandidates[1].sec);
});

test("controller maps failed prepare snapshots to error state", () => {
  const { store, controller } = createController();
  const requestToken = controller.startYoutubePrepare("https://youtu.be/soft");
  controller.applyPrepareJobStarted("source-1", requestToken);
  controller.applyPrepareJobSnapshot({
    jobId: "source-1",
    status: "error",
    stage: "failed",
    progress: 1,
    progressMode: "indeterminate",
    message: "low resolution 640x360",
    logLines: ["low resolution 640x360"],
    result: {},
  }, requestToken);

  assert.equal(store.getState().source.prepareStatus, "error");
  assert.match(store.getState().source.error, /640x360/);
});

test("controller ignores stale completion after source intent changes", async () => {
  const { store, controller } = createController();
  const requestToken = controller.startYoutubePrepare("https://youtu.be/old");
  await controller.selectLocalFile("/tmp/manual.mp4");

  await controller.completeYoutubePrepare({
    jobId: "source-1",
    status: "done",
    stage: "done",
    progress: 1,
    progressMode: "determinate",
    message: "youtube source ready",
    logLines: [],
    result: {
      videoPath: "/tmp/cache/old.mp4",
      fromCache: false,
    },
  }, requestToken);

  assert.equal(store.getState().source.filePath, "/tmp/manual.mp4");
  assert.equal(store.getState().source.preparedFromYouTube, false);
});

test("editing the youtube url clears stale prepare errors and cached youtube state", () => {
  const { store, controller } = createController();

  store.setState((next) => {
    next.source.prepareStatus = "error";
    next.source.prepareJobId = "source-1";
    next.source.prepareStage = "failed";
    next.source.prepareProgress = 1;
    next.source.prepareProgressMode = "indeterminate";
    next.source.prepareMessage = "low resolution 640x360";
    next.source.prepareFromCache = true;
    next.source.error = "old error";
    next.source.prepareLogs = ["old log"];
    next.source.prepareErrorDetail = "low resolution 640x360";
    next.source.preparedFromYouTube = true;
    next.source.preparedVideoPath = "/tmp/cache/old.mp4";
    return next;
  });

  controller.setYoutubeUrl("https://youtu.be/new");

  const state = store.getState();
  assert.equal(state.source.youtubeUrl, "https://youtu.be/new");
  assert.equal(state.source.prepareStatus, "idle");
  assert.equal(state.source.prepareJobId, "");
  assert.equal(state.source.prepareStage, "");
  assert.equal(state.source.prepareProgress, 0);
  assert.equal(state.source.prepareProgressMode, "indeterminate");
  assert.equal(state.source.prepareMessage, "");
  assert.equal(state.source.prepareFromCache, false);
  assert.equal(state.source.error, "");
  assert.deepEqual(state.source.prepareLogs, []);
  assert.equal(state.source.prepareErrorDetail, "");
  assert.equal(state.source.preparedFromYouTube, false);
  assert.equal(state.source.preparedVideoPath, "");
});

test("controller seeds three representative preview candidates after local file selection", async () => {
  const { store, controller } = createController();

  await controller.selectLocalFile("/tmp/manual.mp4");

  const state = store.getState();
  assert.equal(state.source.archiveSourceKind, "file");
  assert.equal(state.source.archiveSourceKey, "/tmp/manual.mp4");
  assert.equal(state.source.archiveDisplayName, "manual");
  assert.equal(state.ui.activeStep, "roi");
  assert.equal(state.roi.previewCandidates.length, 3);
  assert.deepEqual(
    state.roi.previewCandidates.map((candidate) => candidate.id),
    ["preview-candidate-1", "preview-candidate-2", "preview-candidate-3"],
  );
  assert.equal(state.roi.selectedPreviewCandidateId, "preview-candidate-2");
  assert.equal(state.roi.frameTime, state.roi.previewCandidates[1].sec);
  assert.equal(state.roi.frameTimeLabel, state.roi.previewCandidates[1].label);
});
