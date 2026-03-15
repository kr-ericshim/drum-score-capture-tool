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
    api: {
      preparePreviewSource: async () => ({
        videoPath: "/tmp/cache/demo.mp4",
        fromCache: false,
        logLines: ["youtube download saved: /tmp/cache/demo.mp4"],
      }),
      ...overrides.api,
    },
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

test("controller promotes a prepared youtube source into canonical file state", async () => {
  const { store, controller } = createController();

  await controller.prepareYoutube("https://youtu.be/demo");

  const state = store.getState();
  assert.equal(state.source.filePath, "/tmp/cache/demo.mp4");
  assert.equal(state.source.preparedFromYouTube, true);
  assert.equal(state.ui.activeStep, "roi");
});

test("controller ignores stale prepare responses after source intent changes", async () => {
  const slow = deferred();
  const { store, controller } = createController({
    api: {
      preparePreviewSource: async () => slow.promise,
    },
  });

  const pending = controller.prepareYoutube("https://youtu.be/old");
  await controller.selectLocalFile("/tmp/manual.mp4");
  slow.resolve({
    videoPath: "/tmp/cache/old.mp4",
    fromCache: false,
    logLines: [],
  });
  await pending;

  assert.equal(store.getState().source.filePath, "/tmp/manual.mp4");
  assert.equal(store.getState().source.preparedFromYouTube, false);
});

test("controller maps low-resolution prepare failures to error state", async () => {
  const { store, controller } = createController({
    api: {
      preparePreviewSource: async () => {
        throw new Error("low resolution 640x360");
      },
    },
  });

  await controller.prepareYoutube("https://youtu.be/soft");

  assert.equal(store.getState().source.prepareStatus, "error");
  assert.match(store.getState().source.error, /640x360/);
});

test("editing the youtube url clears stale prepare errors and cached youtube state", () => {
  const { store, controller } = createController();

  store.setState((next) => {
    next.source.prepareStatus = "error";
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
  assert.equal(state.source.error, "");
  assert.deepEqual(state.source.prepareLogs, []);
  assert.equal(state.source.prepareErrorDetail, "");
  assert.equal(state.source.preparedFromYouTube, false);
  assert.equal(state.source.preparedVideoPath, "");
});
