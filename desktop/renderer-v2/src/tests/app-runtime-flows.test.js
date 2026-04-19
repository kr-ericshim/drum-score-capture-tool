import test from "node:test";
import assert from "node:assert/strict";

import { createApp } from "../app/App.js";
import { getStepState } from "../app/session/selectors.js";

function deferred() {
  let resolve = () => {};
  let reject = () => {};
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createListenerStore() {
  const listeners = Object.create(null);
  return {
    add(type, handler) {
      (listeners[type] ||= []).push(handler);
    },
    remove(type, handler) {
      const bucket = listeners[type];
      if (!bucket) {
        return;
      }
      const index = bucket.indexOf(handler);
      if (index >= 0) {
        bucket.splice(index, 1);
      }
    },
    async dispatch(type, event) {
      for (const handler of listeners[type] || []) {
        await handler(event);
      }
    },
    syncDispatch(type, event) {
      for (const handler of listeners[type] || []) {
        handler(event);
      }
    },
  };
}

function createDropZoneTarget() {
  const classes = new Set();
  return {
    dataset: { dropZone: "source-ingest" },
    classList: {
      add(token) {
        classes.add(token);
      },
      remove(token) {
        classes.delete(token);
      },
      contains(token) {
        return classes.has(token);
      },
    },
  };
}

function createEventTarget({ action = "", dataset = {}, dropZone = null } = {}) {
  return {
    closest(selector) {
      if (selector === "[data-action]") {
        return action ? { dataset: { action, ...dataset } } : null;
      }
      if (selector === '[data-drop-zone="source-ingest"]') {
        return dropZone;
      }
      return null;
    },
  };
}

function createRoot() {
  const listeners = createListenerStore();
  const sourceDropZone = createDropZoneTarget();
  const stageNodes = {
    "#roiImage": { complete: true, naturalWidth: 1920, naturalHeight: 1080 },
    "#roiCanvas": {
      getContext: () => ({ clearRect() {}, strokeRect() {}, fillRect() {} }),
      addEventListener() {},
      releasePointerCapture() {},
      setPointerCapture() {},
      getBoundingClientRect() {
        return { left: 0, top: 0, width: 1920, height: 1080 };
      },
    },
    "#roiInput": { value: "" },
  };
  const nodes = {
    "#topBar": { innerHTML: "" },
    "#processRail": { innerHTML: "" },
    "#stagePane": {
      innerHTML: "",
      querySelector(selector) {
        return stageNodes[selector] || null;
      },
    },
    "#contextLane": { innerHTML: "" },
    "#statusBar": { innerHTML: "" },
  };

  return {
    innerHTML: "",
    querySelector(selector) {
      return nodes[selector] || null;
    },
    addEventListener(type, handler) {
      listeners.add(type, handler);
    },
    removeEventListener(type, handler) {
      listeners.remove(type, handler);
    },
    async dispatchAction(action, dataset = {}) {
      const target = createEventTarget({ action, dataset });
      await listeners.dispatch("click", { target });
    },
    dispatchInput(target) {
      listeners.syncDispatch("input", { target });
    },
    async dispatchDrag(type, { files = [], insideDropZone = true, relatedInsideDropZone = false } = {}) {
      const event = {
        target: createEventTarget({ dropZone: insideDropZone ? sourceDropZone : null }),
        relatedTarget: relatedInsideDropZone ? createEventTarget({ dropZone: sourceDropZone }) : null,
        dataTransfer: {
          files,
          types: files.length ? ["Files"] : [],
          dropEffect: "none",
        },
        defaultPrevented: false,
        preventDefault() {
          this.defaultPrevented = true;
        },
      };
      await listeners.dispatch(type, event);
      return event;
    },
  };
}

function createDynamicStageRoot() {
  const listeners = createListenerStore();
  let stageVersion = 0;
  const stageNodesByVersion = new Map();

  function createStageNode(selector) {
    if (selector === "#roiImage") {
      return { complete: true, naturalWidth: 1920, naturalHeight: 1080 };
    }
    if (selector === "#roiCanvas") {
      return {
        getContext: () => ({ clearRect() {}, strokeRect() {}, fillRect() {} }),
        addEventListener() {},
        releasePointerCapture() {},
        setPointerCapture() {},
        getBoundingClientRect() {
          return { left: 0, top: 0, width: 1920, height: 1080 };
        },
      };
    }
    if (selector === "#roiInput") {
      return { value: "" };
    }
    return null;
  }

  const nodes = {
    "#topBar": { innerHTML: "" },
    "#processRail": { innerHTML: "" },
    "#stagePane": {
      _innerHTML: "",
      set innerHTML(value) {
        this._innerHTML = value;
        stageVersion += 1;
      },
      get innerHTML() {
        return this._innerHTML;
      },
      querySelector(selector) {
        if (selector === "#roiImage" && !this._innerHTML.includes('id="roiImage"')) {
          return null;
        }
        if (!stageNodesByVersion.has(stageVersion)) {
          stageNodesByVersion.set(stageVersion, {});
        }
        const bucket = stageNodesByVersion.get(stageVersion);
        if (!(selector in bucket)) {
          bucket[selector] = createStageNode(selector);
        }
        return bucket[selector] || null;
      },
    },
    "#contextLane": { innerHTML: "" },
    "#statusBar": { innerHTML: "" },
  };

  return {
    innerHTML: "",
    querySelector(selector) {
      return nodes[selector] || null;
    },
    addEventListener(type, handler) {
      listeners.add(type, handler);
    },
    removeEventListener(type, handler) {
      listeners.remove(type, handler);
    },
    async dispatchAction(action, dataset = {}) {
      const target = createEventTarget({ action, dataset });
      await listeners.dispatch("click", { target });
    },
    dispatchInput(target) {
      listeners.syncDispatch("input", { target });
    },
  };
}

function installBrowserStubs(api = {}) {
  const drumSheetAPI = {
    selectVideoFile: async () => "",
    getPathForFile: (file) => String(file?.path || ""),
    openPath: async () => "",
    copyText: async () => true,
    getBackendState: async () => ({ ready: true, starting: false, running: true, error: "" }),
    onBackendState: () => () => {},
    ...api,
  };

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { drumSheetAPI },
  });
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

const ROI_RECT = [
  [0, 0],
  [320, 0],
  [320, 180],
  [0, 180],
];

const PREVIEW_CANDIDATES = [
  { id: "preview-candidate-1", sec: 24, label: "00:24.0", tone: "alternate" },
  { id: "preview-candidate-2", sec: 39.5, label: "00:39.5", tone: "recommended" },
  { id: "preview-candidate-3", sec: 60, label: "01:00.0", tone: "alternate" },
];

test("late preview response is ignored after frameTime changes within the same source session", async () => {
  installBrowserStubs();
  const preview = deferred();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async () => ({ durationSec: 120, durationLabel: "02:00", resolutionLabel: "1920x1080" }),
    api: {
      requestPreviewFrame: () => preview.promise,
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.source.metadata = { durationSec: 120 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 5;
    next.roi.frameTimeLabel = "00:05.0";
    return next;
  });

  const pending = root.dispatchAction("load-preview-frame");
  await flush();

  root.dispatchInput({
    id: "frameTimeSlider",
    value: "10",
    dataset: {},
  });

  preview.resolve({
    imagePath: "/tmp/preview-old.png",
    sourcePath: "/tmp/preview-old.png",
    diagnostics: [{ code: "old" }],
  });
  await pending;
  await flush();

  assert.ok(app.debug);
  assert.equal(app.debug.getState().roi.previewImage, "");
});

test("frameTime changes clear stale preview, roi, and downstream export state immediately", () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.ui.activeStep = "roi";
    next.roi.frameTime = 5;
    next.roi.frameTimeLabel = "00:05.0";
    next.roi.previewImage = "/tmp/preview.png";
    next.roi.previewSourcePath = "/tmp/preview.png";
    next.roi.diagnostics = [{ code: "loaded" }];
    next.roi.draftRect = ROI_RECT;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.jobId = "job-1";
    next.exportConfig.outputDir = "/tmp/old-export";
    next.exportConfig.pdfPath = "/tmp/old-export/result.pdf";
    next.review.pages = [{ id: "1", title: "페이지 1" }];
    next.review.selectedPageIds = ["1"];
    next.review.outputDir = "/tmp/old-export";
    return next;
  });

  root.dispatchInput({
    id: "frameTimeSlider",
    value: "10",
    dataset: {},
  });

  const state = app.debug.getState();
  assert.equal(state.roi.previewImage, "");
  assert.equal(state.roi.appliedRect, null);
  assert.equal(state.exportConfig.jobId, "");
  assert.equal(state.review.pages.length, 0);
  assert.equal(getStepState(state, "export").enabled, false);
});

test("simplified ROI step remains usable from frame load through apply-roi", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({
      applyDraft() {
        return ROI_RECT;
      },
      setDraft() {},
      destroy() {},
    }),
    api: {
      requestPreviewFrame: async () => ({
        imagePath: "/tmp/preview.png",
        sourcePath: "/tmp/preview.png",
        diagnostics: [],
      }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 1920, height: 1080 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    next.roi.frameTimeLabel = "00:10.0";
    return next;
  });

  await root.dispatchAction("load-preview-frame");
  await flush();

  app.debug.setState((next) => {
    next.roi.draftRect = ROI_RECT;
    return next;
  });

  await root.dispatchAction("apply-roi");

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "export");
  assert.deepEqual(state.roi.appliedRect, ROI_RECT);
  assert.equal(state.exportConfig.layoutHint, "full_scroll");
});

test("runExport does not create a job when zero formats are selected", async () => {
  installBrowserStubs();
  let createJobCalls = 0;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => {
        createJobCalls += 1;
        return "job-1";
      },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.roi.frameTime = 5;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = [];
    next.ui.activeStep = "export";
    return next;
  });

  await root.dispatchAction("run-export");
  await flush();

  assert.equal(createJobCalls, 0);
  assert.match(app.debug.getState().exportConfig.error, /형식|format/i);
});

test("runExport opens the metadata modal before polling when pdf is selected", async () => {
  installBrowserStubs();
  let createJobCalls = 0;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => {
        createJobCalls += 1;
        return "job-1";
      },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, current_step: "done", message: "", result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.roi.frameTime = 5;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["pdf"];
    next.exportConfig.pageFillMode = "balanced";
    next.ui.activeStep = "export";
    return next;
  });

  await root.dispatchAction("run-export");
  await flush();

  const state = app.debug.getState();
  assert.equal(createJobCalls, 0);
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.equal(state.exportConfig.runStatus, "idle");
});

test("applied review selection stays locked when a checkbox input fires later", () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.exportConfig.jobId = "job-1";
    next.exportConfig.runStatus = "done";
    next.review.pages = [{ id: "1", title: "페이지 1", previewPath: "/tmp/page-1.png", capturePath: "/tmp/page-1.png" }];
    next.review.selectedPageIds = ["1"];
    next.review.focusedPageId = "1";
    next.review.status = "applied";
    next.ui.activeStep = "review";
    return next;
  });

  root.dispatchInput({
    dataset: { action: "toggle-review-page", pageId: "1" },
    checked: false,
  });

  const state = app.debug.getState();
  assert.equal(state.review.status, "applied");
  assert.deepEqual(state.review.selectedPageIds, ["1"]);
});

test("a fresh export run clears previous output and review artifacts before polling finishes", async () => {
  installBrowserStubs();
  const job = deferred();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => job.promise,
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.roi.frameTime = 5;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["png"];
    next.exportConfig.outputDir = "/tmp/old-export";
    next.exportConfig.pdfPath = "/tmp/old-export/result.pdf";
    next.review.pages = [{ id: "1", title: "페이지 1" }];
    next.review.selectedPageIds = ["1"];
    next.review.outputDir = "/tmp/old-export";
    next.review.pdfPath = "/tmp/old-export/result.pdf";
    next.ui.activeStep = "export";
    return next;
  });

  const pending = root.dispatchAction("run-export");
  await flush();

  const state = app.debug.getState();
  assert.equal(state.exportConfig.outputDir, "");
  assert.equal(state.exportConfig.pdfPath, "");
  assert.equal(state.review.pages.length, 0);
  assert.equal(state.review.outputDir, "");

  job.resolve({ job_id: "job-1", status: "done", progress: 1, result: {} });
  await pending;
});

test("latest source selection wins when metadata requests resolve out of order", async () => {
  let pickIndex = 0;
  const metadataA = deferred();
  const metadataB = deferred();
  installBrowserStubs({
    selectVideoFile: async () => {
      pickIndex += 1;
      return pickIndex === 1 ? "/tmp/source-a.mp4" : "/tmp/source-b.mp4";
    },
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async (filePath) => {
      if (filePath.endsWith("source-a.mp4")) {
        return metadataA.promise;
      }
      return metadataB.promise;
    },
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  const firstPick = root.dispatchAction("select-source-file");
  const secondPick = root.dispatchAction("select-source-file");
  await flush();

  metadataB.resolve({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" });
  await secondPick;
  metadataA.resolve({ durationSec: 45, durationLabel: "00:45", resolutionLabel: "1280x720" });
  await firstPick;
  await flush();

  const state = app.debug.getState();
  assert.equal(state.source.filePath, "/tmp/source-b.mp4");
  assert.equal(state.source.displayName, "source-b.mp4");
  assert.equal(state.source.metadata.durationLabel, "00:30");
});

test("stale source selection failures do not override a newer successful source", async () => {
  let pickIndex = 0;
  const metadataB = deferred();
  installBrowserStubs({
    selectVideoFile: async () => {
      pickIndex += 1;
      return pickIndex === 1 ? "/tmp/source-a.mp4" : "/tmp/source-b.mp4";
    },
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async (filePath) => {
      if (filePath.endsWith("source-a.mp4")) {
        throw new Error("decode failed");
      }
      return metadataB.promise;
    },
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  const firstPick = root.dispatchAction("select-source-file");
  const secondPick = root.dispatchAction("select-source-file");
  await flush();

  metadataB.resolve({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" });
  await secondPick;
  await firstPick;
  await flush();

  const state = app.debug.getState();
  assert.equal(state.source.status, "ready");
  assert.equal(state.source.displayName, "source-b.mp4");
  assert.equal(state.source.error, "");
});

test("source selection seeds three preview candidates and auto-loads the recommended preview", async () => {
  const previewCalls = [];
  installBrowserStubs({
    selectVideoFile: async () => "/tmp/source-a.mp4",
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async () => ({ durationSec: 120, durationLabel: "02:00", resolutionLabel: "1920x1080" }),
    api: {
      requestPreviewFrame: async ({ startSec }) => {
        previewCalls.push(startSec);
        return {
          imagePath: `/tmp/preview-${startSec}.png`,
          sourcePath: `/tmp/preview-${startSec}.png`,
          diagnostics: [],
        };
      },
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  await root.dispatchAction("select-source-file");
  await flush();

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "roi");
  assert.deepEqual(
    state.roi.previewCandidates.map((candidate) => candidate.sec),
    [24, 39.5, 60],
  );
  assert.equal(state.roi.selectedPreviewCandidateId, "preview-candidate-2");
  assert.equal(state.roi.previewImage, "/tmp/preview-39.5.png");
  assert.deepEqual(previewCalls, [39.5]);
});

test("selecting another preview candidate reloads the frame and relocks downstream steps", async () => {
  installBrowserStubs();
  const previewCalls = [];
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async ({ startSec }) => {
        previewCalls.push(startSec);
        return {
          imagePath: `/tmp/preview-${startSec}.png`,
          sourcePath: `/tmp/preview-${startSec}.png`,
          diagnostics: [],
        };
      },
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 1920, height: 1080 };
    next.ui.activeStep = "roi";
    next.roi.previewCandidates = PREVIEW_CANDIDATES;
    next.roi.selectedPreviewCandidateId = "preview-candidate-2";
    next.roi.frameTime = 39.5;
    next.roi.frameTimeLabel = "00:39.5";
    next.roi.previewImage = "/tmp/preview-39.5.png";
    next.roi.previewSourcePath = "/tmp/preview-39.5.png";
    next.roi.draftRect = ROI_RECT;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.jobId = "job-1";
    next.exportConfig.outputDir = "/tmp/export";
    next.review.pages = [{ id: "1", title: "페이지 1" }];
    next.review.selectedPageIds = ["1"];
    return next;
  });

  await root.dispatchAction("select-preview-candidate", { candidateId: "preview-candidate-3" });
  await flush();

  const state = app.debug.getState();
  assert.equal(state.roi.selectedPreviewCandidateId, "preview-candidate-3");
  assert.equal(state.roi.frameTime, 60);
  assert.equal(state.roi.previewImage, "/tmp/preview-60.png");
  assert.equal(state.roi.appliedRect, null);
  assert.equal(state.exportConfig.jobId, "");
  assert.equal(state.review.pages.length, 0);
  assert.deepEqual(previewCalls, [60]);
});

test("backend-ready app hydrates the persisted media registry and loads a stored source row", async () => {
  installBrowserStubs({
    getBackendState: async () => ({ ready: true, starting: false, running: true, error: "" }),
    onBackendState: () => () => {},
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async () => ({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" }),
    api: {
      getLocalMediaRegistry: async () => ({
        items: [
          {
            filePath: "/tmp/library-source.mkv",
            displayName: "library-source.mkv",
            directory: "/tmp",
            resolutionLabel: "1920x1080",
            durationLabel: "00:30",
            hasScore: true,
          },
        ],
      }),
    },
  });

  await flush();

  let state = app.debug.getState();
  assert.equal(state.source.registryItems.length, 1);
  assert.equal(state.source.registryItems[0].filePath, "/tmp/library-source.mkv");

  await root.dispatchAction("load-registry-source", { filePath: "/tmp/library-source.mkv" });
  await flush();

  state = app.debug.getState();
  assert.equal(state.source.filePath, "/tmp/library-source.mkv");
  assert.equal(state.source.displayName, "library-source.mkv");
  assert.equal(state.ui.activeStep, "roi");
});

test("dropping a local video onto the ingest panel imports it through the existing source flow", async () => {
  let pickerCalls = 0;
  installBrowserStubs({
    selectVideoFile: async () => {
      pickerCalls += 1;
      return "/tmp/dialog-source.mp4";
    },
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async () => ({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  const dragOver = await root.dispatchDrag("dragover", {
    files: [{ path: "/tmp/drop-source.mkv" }],
  });
  const drop = await root.dispatchDrag("drop", {
    files: [{ path: "/tmp/drop-source.mkv" }],
  });
  await flush();

  const state = app.debug.getState();
  assert.equal(dragOver.defaultPrevented, true);
  assert.equal(drop.defaultPrevented, true);
  assert.equal(state.source.filePath, "/tmp/drop-source.mkv");
  assert.equal(state.source.displayName, "drop-source.mkv");
  assert.equal(state.ui.activeStep, "roi");
  assert.equal(pickerCalls, 0);
});

test("dropping a local video still imports when electron resolves the file path instead of File.path", async () => {
  installBrowserStubs({
    getPathForFile: (file) => (file?.name === "drop-source.webm" ? "/tmp/drop-source.webm" : ""),
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async () => ({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  const drop = await root.dispatchDrag("drop", {
    files: [{ name: "drop-source.webm" }],
  });
  await flush();

  const state = app.debug.getState();
  assert.equal(drop.defaultPrevented, true);
  assert.equal(state.source.filePath, "/tmp/drop-source.webm");
  assert.equal(state.source.displayName, "drop-source.webm");
  assert.equal(state.ui.activeStep, "roi");
});

test("dropping an unsupported file onto the ingest panel shows a user-facing error", async () => {
  installBrowserStubs();

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async () => ({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  app.debug.setState((next) => {
    next.ui.locale = "en";
    return next;
  });

  const drop = await root.dispatchDrag("drop", {
    files: [{ path: "/tmp/readme.txt" }],
  });
  await flush();

  const state = app.debug.getState();
  assert.equal(drop.defaultPrevented, true);
  assert.equal(state.source.filePath, "");
  assert.equal(state.source.status, "error");
  assert.equal(state.source.error, "Only mp4, mkv, mov, avi, and webm video files can be dropped here.");
});

test("destroy removes root listeners and backend subscription", async () => {
  let selectCalls = 0;
  let unsubscribeCalls = 0;
  installBrowserStubs({
    selectVideoFile: async () => {
      selectCalls += 1;
      return "/tmp/source-a.mp4";
    },
    onBackendState: () => () => {
      unsubscribeCalls += 1;
    },
  });

  const root = createRoot();
  const app = createApp(root, {
    readVideoMetadata: async () => ({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.destroy();
  await root.dispatchAction("select-source-file");
  await root.dispatchDrag("drop", {
    files: [{ path: "/tmp/source-b.mp4" }],
  });

  assert.equal(selectCalls, 0);
  assert.equal(unsubscribeCalls, 1);
});

test("roi editor keeps the mounted canvas when only the draft rect changes", () => {
  installBrowserStubs();
  let mountCalls = 0;
  let destroyCalls = 0;
  const root = createDynamicStageRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => {
      mountCalls += 1;
      return {
        applyDraft() {
          return ROI_RECT;
        },
        setDraft() {},
        destroy() {
          destroyCalls += 1;
        },
      };
    },
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.ui.activeStep = "roi";
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { width: 1920, height: 1080, durationSec: 60 };
    next.roi.previewImage = "file:///tmp/preview.png";
    next.roi.previewSourcePath = "/tmp/preview.png";
    next.roi.draftRect = ROI_RECT;
    return next;
  });

  assert.equal(mountCalls, 1);

  app.debug.setState((next) => {
    next.roi.draftRect = [
      [10, 10],
      [330, 10],
      [330, 190],
      [10, 190],
    ];
    return next;
  });

  assert.equal(mountCalls, 1);
  assert.equal(destroyCalls, 0);
});

test("open and copy actions report user-facing notices", async () => {
  installBrowserStubs({
    openPath: async () => "ENOENT",
    copyText: async () => false,
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.ui.locale = "ko";
    next.review.outputDir = "/tmp/export";
    next.review.pdfPath = "/tmp/export/result.pdf";
    return next;
  });

  await root.dispatchAction("open-output-dir");
  assert.match(app.debug.getState().ui.inlineNotice, /열지 못했습니다|ENOENT/i);

  await root.dispatchAction("copy-output-dir");
  assert.match(app.debug.getState().ui.inlineNotice, /복사할 경로|복사하지 못했습니다/i);
});

test("locale toggle updates the top bar labels and inline notices", async () => {
  installBrowserStubs({
    copyText: async () => false,
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  await root.dispatchAction("set-locale", { locale: "en" });
  assert.match(root.querySelector("#topBar").innerHTML, /Drum Sheet Capture|Choose video|Language switcher/);

  app.debug.setState((next) => {
    next.review.outputDir = "/tmp/export";
    return next;
  });

  await root.dispatchAction("copy-output-dir");
  assert.match(app.debug.getState().ui.inlineNotice, /Could not copy|No .* path/i);
});

test("locale toggle retranslates a stored youtube prepare error without losing the raw detail", async () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.ui.locale = "ko";
    next.source.prepareStatus = "error";
    next.source.prepareErrorDetail = "low resolution 640x360";
    next.source.error = "저화질 영상으로 감지되어 준비를 중단했습니다: low resolution 640x360";
    return next;
  });

  await root.dispatchAction("set-locale", { locale: "en" });

  const state = app.debug.getState();
  assert.equal(state.source.prepareErrorDetail, "low resolution 640x360");
  assert.match(state.source.error, /low-resolution video was available/i);
  assert.match(state.source.error, /640x360/);
});

test("review apply action is runtime-blocked until export finishes", async () => {
  installBrowserStubs();
  let reviewCalls = 0;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => {
        reviewCalls += 1;
        return {};
      },
    },
  });

  app.debug.setState((next) => {
    next.exportConfig.jobId = "job-1";
    next.exportConfig.runStatus = "running";
    next.review.pages = [{ id: "1", title: "페이지 1", capturePath: "/tmp/page-1.png", previewPath: "/tmp/page-1.png" }];
    next.review.selectedPageIds = ["1"];
    next.ui.activeStep = "review";
    return next;
  });

  await root.dispatchAction("apply-review");

  assert.equal(reviewCalls, 0);
});

test("manual roi bounds input updates the draft rect", () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({
      applyDraft() {
        return ROI_RECT;
      },
      setDraft() {},
      destroy() {},
    }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.ui.activeStep = "roi";
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { width: 1920, height: 1080, durationSec: 60 };
    next.roi.previewImage = "file:///tmp/preview.png";
    next.roi.previewSourcePath = "/tmp/preview.png";
    next.roi.draftRect = ROI_RECT;
    return next;
  });

  root.dispatchInput({
    dataset: { action: "set-roi-bound", field: "x" },
    value: "24",
  });

  assert.deepEqual(app.debug.getState().roi.draftRect, [
    [24, 0],
    [344, 0],
    [344, 180],
    [24, 180],
  ]);
});

test("youtube prepare success promotes the resolved path and enters roi", async () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      createPreviewSourceJob: async () => "source-1",
      getPreviewSourceJob: async () => ({
        jobId: "source-1",
        status: "done",
        stage: "done",
        progress: 1,
        progressMode: "determinate",
        message: "youtube source ready",
        logLines: ["youtube download saved: /tmp/cache/youtube.mp4"],
        result: {
          videoPath: "/tmp/cache/youtube.mp4",
          fromCache: false,
          videoUrl: "/jobs-files/_preview/youtube.mp4",
        },
      }),
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
    readVideoMetadata: async () => ({
      durationSec: 60,
      durationLabel: "01:00",
      resolutionLabel: "1920x1080",
    }),
  });

  app.debug.setState((next) => {
    next.source.sourceType = "youtube";
    next.source.youtubeUrl = "https://youtu.be/demo";
    return next;
  });

  await root.dispatchAction("prepare-source-youtube");

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "roi");
  assert.equal(state.source.filePath, "/tmp/cache/youtube.mp4");
  assert.equal(state.source.preparedFromYouTube, true);
});

test("youtube prepare polls live progress into the source screen, top bar, and process rail before completion", async () => {
  installBrowserStubs();
  const root = createRoot();
  const scheduled = [];
  const previousSetTimeout = globalThis.setTimeout;
  const previousClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = (fn) => {
    scheduled.push(fn);
    return fn;
  };
  globalThis.clearTimeout = () => {};

  const snapshots = [
    {
      jobId: "source-1",
      status: "running",
      stage: "download",
      progress: 0.42,
      progressMode: "determinate",
      message: "downloading video 42%",
      logLines: ["yt-dlp: download 42%"],
      result: {},
    },
    {
      jobId: "source-1",
      status: "done",
      stage: "done",
      progress: 1,
      progressMode: "determinate",
      message: "youtube source ready",
      logLines: ["youtube download saved: /tmp/cache/youtube.mp4"],
      result: {
        videoPath: "/tmp/cache/youtube.mp4",
        fromCache: false,
        videoUrl: "/jobs-files/_preview/youtube.mp4",
      },
    },
  ];

  try {
    const app = createApp(root, {
      exposeTestApi: true,
      api: {
        createPreviewSourceJob: async () => "source-1",
        getPreviewSourceJob: async () => snapshots.shift(),
        requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
        createJob: async () => "job-1",
        getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
        reviewExport: async () => ({}),
      },
      readVideoMetadata: async () => ({
        durationSec: 60,
        durationLabel: "01:00",
        resolutionLabel: "1920x1080",
      }),
    });

    app.debug.setState((next) => {
      next.ui.locale = "en";
      next.source.sourceType = "youtube";
      next.source.youtubeUrl = "https://youtu.be/demo";
      return next;
    });

    const pending = root.dispatchAction("prepare-source-youtube");
    await flush();

    let state = app.debug.getState();
    assert.equal(state.source.prepareStage, "download");
    assert.equal(state.source.prepareProgress, 0.42);
    assert.equal(state.source.filePath, "");
    assert.match(root.querySelector("#topBar").innerHTML, /42%/);
    assert.match(root.querySelector("#processRail").innerHTML, /42%/);
    assert.match(root.querySelector("#stagePane").innerHTML, /42%/);

    const nextPoll = scheduled.shift();
    assert.equal(typeof nextPoll, "function");
    nextPoll();
    await flush();
    await pending;
    await flush();

    state = app.debug.getState();
    assert.equal(state.source.filePath, "/tmp/cache/youtube.mp4");
    assert.equal(state.ui.activeStep, "roi");
  } finally {
    globalThis.setTimeout = previousSetTimeout;
    globalThis.clearTimeout = previousClearTimeout;
  }
});

test("export after prepared youtube submits a file-backed payload", async () => {
  installBrowserStubs();
  let seenPayload = null;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async (payload) => {
        seenPayload = payload;
        return "job-1";
      },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, current_step: "done", message: "", result: {} }),
      reviewExport: async () => ({}),
      preparePreviewSource: async () => ({
        videoPath: "/tmp/cache/youtube.mp4",
        fromCache: false,
        logLines: [],
      }),
    },
  });

  app.debug.setState((next) => {
    next.source.sourceType = "youtube";
    next.source.filePath = "/tmp/cache/youtube.mp4";
    next.source.preparedFromYouTube = true;
    next.roi.previewCandidates = PREVIEW_CANDIDATES;
    next.roi.selectedPreviewCandidateId = "preview-candidate-3";
    next.roi.appliedRect = ROI_RECT;
    next.roi.frameTime = 60;
    next.exportConfig.formats = ["png"];
    next.ui.activeStep = "export";
    return next;
  });

  await root.dispatchAction("run-export");

  assert.equal(seenPayload.source_type, "file");
  assert.equal(seenPayload.file_path, "/tmp/cache/youtube.mp4");
  assert.equal(seenPayload.options.extract.start_sec, 0);
});
