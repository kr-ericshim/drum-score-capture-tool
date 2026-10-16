import test from "node:test";
import { buildRoiScreenModel } from "../features/roi/RoiScreen.js";
import assert from "node:assert/strict";

import { createApp } from "../app/App.js";
import { createInitialSessionState, getStepState } from "../app/session/selectors.js";
import { t } from "../lib/i18n.js";

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

function createElementNode(overrides = {}) {
  const attributes = new Map();
  const node = {
    innerHTML: "",
    hidden: false,
    inert: false,
    dataset: {},
    setAttribute(name, value) {
      attributes.set(name, String(value));
    },
    getAttribute(name) {
      return attributes.has(name) ? attributes.get(name) : null;
    },
    removeAttribute(name) {
      attributes.delete(name);
    },
    hasAttribute(name) {
      return attributes.has(name);
    },
    focus() {
      if (globalThis.document) {
        globalThis.document.activeElement = node;
      }
    },
    querySelector() {
      return null;
    },
  };
  Object.defineProperties(node, Object.getOwnPropertyDescriptors(overrides));
  return node;
}

function createRoot() {
  const listeners = createListenerStore();
  const sourceDropZone = createDropZoneTarget();
  const modalNodes = {
    dialog: createElementNode({ dataset: { archiveDialog: "true" } }),
  };
  const stageNodes = {
    "#roiImage": { complete: true, naturalWidth: 1920, naturalHeight: 1080 },
    "#roiCanvas": {
      getContext: () => ({ clearRect() {}, strokeRect() {}, fillRect() {}, beginPath() {}, rect() {}, fill() {} }),
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
    '[data-shell="renderer-v2"]': createElementNode({ dataset: {} }),
    "#topBar": createElementNode(),
    "#workspaceShell": createElementNode(),
    "#processRail": createElementNode(),
    "#stagePane": createElementNode({
      querySelector(selector) {
        return stageNodes[selector] || null;
      },
    }),
    "#contextLane": createElementNode(),
    "#statusBar": createElementNode(),
    "#shellModalLayer": createElementNode({
      querySelector(selector) {
        if (!this.innerHTML) {
          return null;
        }
        if (selector === "[data-archive-dialog]") {
          return modalNodes.dialog;
        }
        return null;
      },
    }),
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
    async dispatchKeydown(key) {
      const event = {
        key,
        defaultPrevented: false,
        preventDefault() {
          this.defaultPrevented = true;
        },
      };
      await listeners.dispatch("keydown", event);
      return event;
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
    if (selector === ".review-grid") {
      return { scrollTop: 0, scrollLeft: 0 };
    }
    if (selector === '[data-action="toggle-review-page"]') {
      return {
        dataset: { action: "toggle-review-page", pageId: "1" },
        focus() {
          const scroller = nodes["#stagePane"].querySelector(".review-grid");
          if (scroller) {
            scroller.scrollTop = 0;
          }
          globalThis.document.activeElement = this;
        },
      };
    }
    if (selector === '[data-action="toggle-review-page"][data-page-id="5"]') {
      return {
        dataset: { action: "toggle-review-page", pageId: "5" },
        focus() {
          globalThis.document.activeElement = this;
        },
      };
    }
    if (selector === "#roiImage") {
      return { complete: true, naturalWidth: 1920, naturalHeight: 1080 };
    }
    if (selector === "#roiCanvas") {
      return {
        getContext: () => ({ clearRect() {}, strokeRect() {}, fillRect() {}, beginPath() {}, rect() {}, fill() {} }),
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
    '[data-shell="renderer-v2"]': createElementNode({ dataset: {} }),
    "#topBar": createElementNode(),
    "#workspaceShell": createElementNode(),
    "#processRail": createElementNode(),
    "#stagePane": createElementNode({
      _innerHTML: "",
      set innerHTML(value) {
        this._innerHTML = value;
        stageVersion += 1;
      },
      get innerHTML() {
        return this._innerHTML;
      },
      querySelector(selector) {
        if (selector === ".review-grid" && !this._innerHTML.includes('class="review-grid"')) {
          return null;
        }
        if (selector.startsWith('[data-action="toggle-review-page"') && !this._innerHTML.includes('data-action="toggle-review-page"')) {
          return null;
        }
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
    }),
    "#contextLane": createElementNode(),
    "#statusBar": createElementNode(),
    "#shellModalLayer": createElementNode(),
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
    async dispatchKeydown(key) {
      const event = {
        key,
        defaultPrevented: false,
        preventDefault() {
          this.defaultPrevented = true;
        },
      };
      await listeners.dispatch("keydown", event);
      return event;
    },
    dispatchInput(target) {
      listeners.syncDispatch("input", { target });
    },
  };
}

function createDocumentStub() {
  return {
    activeElement: null,
    documentElement: { lang: "en" },
    querySelector() {
      return null;
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
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: createDocumentStub(),
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
  const revokedUrls = [];
  const previousRevokeObjectUrl = globalThis.URL.revokeObjectURL;
  globalThis.URL.revokeObjectURL = (url) => {
    revokedUrls.push(String(url));
  };
  const preview = deferred();
  const root = createRoot();
  try {
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
      imagePath: "blob:preview-old",
      sourcePath: "/tmp/preview-old.png",
      diagnostics: [{ code: "old" }],
    });
    await pending;
    await flush();

    assert.ok(app.debug);
    assert.equal(app.debug.getState().roi.previewImage, "");
    assert.deepEqual(revokedUrls, ["blob:preview-old"]);
  } finally {
    globalThis.URL.revokeObjectURL = previousRevokeObjectUrl;
  }
});

test("destroy revokes the active protected preview blob url", () => {
  installBrowserStubs();
  const revokedUrls = [];
  const previousRevokeObjectUrl = globalThis.URL.revokeObjectURL;
  globalThis.URL.revokeObjectURL = (url) => {
    revokedUrls.push(String(url));
  };
  const root = createRoot();
  try {
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
      next.roi.previewImage = "blob:active-preview";
      return next;
    });

    app.destroy();

    assert.deepEqual(revokedUrls, ["blob:active-preview"]);
  } finally {
    globalThis.URL.revokeObjectURL = previousRevokeObjectUrl;
  }
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

test("preview loading places an automatic ROI suggestion in the editable draft only", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const suggested = [[20, 100], [300, 100], [300, 175], [20, 175]];
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({
        imagePath: "/tmp/preview.png",
        sourcePath: "/tmp/preview.png",
        diagnostics: [],
      }),
      requestAutoRoi: async () => ({
        status: "suggested",
        roi: suggested,
        evidenceLevel: "high",
        diagnostics: { supporting_frames: 3 },
      }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 320, height: 180 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    return next;
  });

  await root.dispatchAction("load-preview-frame");
  await flush();

  const state = app.debug.getState();
  assert.deepEqual(state.roi.draftRect, suggested);
  assert.equal(state.roi.appliedRect, null);
  assert.equal(state.roi.autoRoiStatus, "suggested");
  assert.equal(state.roi.autoRoiEvidence, "high");
});

test("late automatic ROI does not overwrite a draft drawn while detection runs", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const pendingSuggestion = deferred();
  const manual = [[30, 30], [280, 30], [280, 150], [30, 150]];
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({
        imagePath: "/tmp/preview.png",
        sourcePath: "/tmp/preview.png",
        diagnostics: [],
      }),
      requestAutoRoi: () => pendingSuggestion.promise,
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 320, height: 180 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    return next;
  });

  const loading = root.dispatchAction("load-preview-frame");
  await flush();
  app.debug.setState((next) => {
    next.roi.draftRect = manual;
    next.roi.autoRoiUserEdited = true;
    return next;
  });
  pendingSuggestion.resolve({
    status: "suggested",
    roi: [[20, 100], [300, 100], [300, 175], [20, 175]],
    evidenceLevel: "high",
    diagnostics: {},
  });
  await loading;

  assert.deepEqual(app.debug.getState().roi.draftRect, manual);
});

test("an applied fractional auto suggestion lets export start", async () => {
  // packaged app, 2026-10-14: the auto ROI arrived with fractional corners, the editor applied
  // rounded ones, and "apply the region first" blocked export while the region step said applied
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const suggested = [[20.44, 100], [300, 100], [300, 175.6], [20.44, 175.6]];
  const rounded = [[20, 100], [300, 100], [300, 176], [20, 176]];
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({ applyDraft() { return rounded; }, setDraft() {}, destroy() {} }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "/tmp/preview.png", sourcePath: "/tmp/preview.png", diagnostics: [] }),
      requestAutoRoi: async () => ({ status: "suggested", roi: suggested, evidenceLevel: "high", diagnostics: {} }),
      requestPreviewRoiHealth: async () => ({ riskLevel: "ok", diagnostics: [], envelope: { status: "found", clipped: false } }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 320, height: 180 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    return next;
  });
  await root.dispatchAction("load-preview-frame");
  await flush();
  assert.deepEqual(app.debug.getState().roi.draftRect, suggested);

  await root.dispatchAction("apply-roi");
  await flush();
  let state = app.debug.getState();
  assert.deepEqual(state.roi.appliedRect, rounded);
  assert.equal(state.ui.activeStep, "export");
  assert.equal(buildRoiScreenModel(state).statusTone, "ready");

  await root.dispatchAction("run-export");
  await flush();
  state = app.debug.getState();
  assert.equal(state.exportConfig.error, "", state.exportConfig.error);
  assert.equal(state.exportConfig.metadataModal?.isOpen, true, "PDF export continues to the document details");

  // a fractional draft equal to the applied box to the pixel is not a pending change either
  app.debug.setState((next) => {
    next.roi.draftRect = suggested;
    return next;
  });
  assert.equal(buildRoiScreenModel(app.debug.getState()).applyDisabled, true);
  app.debug.setState((next) => {
    next.roi.draftRect = rounded;
    return next;
  });

});

test("an automatic suggestion that arrives after apply does not reopen the applied region", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const pendingSuggestion = deferred();
  const applied = [[30, 30], [280, 30], [280, 150], [30, 150]];
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({ applyDraft() { return applied; }, setDraft() {}, destroy() {} }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "/tmp/preview.png", sourcePath: "/tmp/preview.png", diagnostics: [] }),
      requestAutoRoi: () => pendingSuggestion.promise,
      requestPreviewRoiHealth: async () => ({ riskLevel: "ok", diagnostics: [], envelope: { status: "found", clipped: false } }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 320, height: 180 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    return next;
  });
  const loading = root.dispatchAction("load-preview-frame");
  await flush();
  app.debug.setState((next) => {
    next.roi.draftRect = applied;
    return next;
  });
  await root.dispatchAction("apply-roi");
  pendingSuggestion.resolve({ status: "suggested", roi: [[20.5, 100], [300, 100], [300, 175], [20.5, 175]], evidenceLevel: "high", diagnostics: {} });
  await loading;
  await flush();
  const state = app.debug.getState();
  assert.deepEqual(state.roi.appliedRect, applied);
  assert.deepEqual(state.roi.draftRect, applied, "the late suggestion stays out of the applied region's draft");
  assert.equal(getStepState(state, "export").enabled, true);
});

test("applying a region runs the clipping check; the larger area loads only as a draft", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const suggested = [[0, 20], [320, 20], [320, 180], [0, 180]];
  const healthCalls = [];
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
      requestPreviewFrame: async () => ({ imagePath: "/tmp/preview.png", sourcePath: "/tmp/preview.png", diagnostics: [] }),
      requestPreviewRoiHealth: async (request) => {
        healthCalls.push(request);
        return { riskLevel: "warning", diagnostics: [], envelope: { status: "found", clipped: true, suggestedRoi: suggested } };
      },
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 320, height: 180 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    return next;
  });
  await root.dispatchAction("load-preview-frame");
  await flush();
  app.debug.setState((next) => {
    next.roi.draftRect = ROI_RECT;
    return next;
  });
  await root.dispatchAction("apply-roi");
  await flush();

  let state = app.debug.getState();
  assert.equal(healthCalls.length, 1);
  assert.deepEqual(healthCalls[0].roi, ROI_RECT);
  assert.equal(state.roi.clipCheck.status, "clipped");
  assert.deepEqual(state.roi.appliedRect, ROI_RECT);

  app.debug.setState((next) => {
    next.ui.activeStep = "roi";
    return next;
  });
  await flush();
  assert.equal(healthCalls.length, 1, "the same applied region is not checked twice");

  await root.dispatchAction("use-suggested-roi");
  state = app.debug.getState();
  assert.deepEqual(state.roi.draftRect, suggested);
  assert.deepEqual(state.roi.appliedRect, ROI_RECT, "the suggestion is not applied automatically");
  assert.equal(state.roi.autoRoiUserEdited, true);
});

test("a clipping result for a region that is no longer applied is ignored", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const pending = deferred();
  const other = [[30, 30], [280, 30], [280, 150], [30, 150]];
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({ applyDraft() { return ROI_RECT; }, setDraft() {}, destroy() {} }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "/tmp/preview.png", sourcePath: "/tmp/preview.png", diagnostics: [] }),
      requestPreviewRoiHealth: () => pending.promise,
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 320, height: 180 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    next.roi.draftRect = ROI_RECT;
    return next;
  });
  await root.dispatchAction("apply-roi");
  app.debug.setState((next) => {
    next.roi.appliedRect = other;
    next.roi.clipCheck = { status: "idle", rectKey: JSON.stringify(other), suggestedRect: null };
    return next;
  });
  pending.resolve({ envelope: { status: "found", clipped: true, suggestedRoi: [[0, 0], [320, 0], [320, 180], [0, 180]] } });
  await flush();
  const state = app.debug.getState();
  assert.notEqual(state.roi.clipCheck.status, "clipped");
  assert.deepEqual(state.roi.draftRect, ROI_RECT);
});

test("same-frame apply-roi relocks export and clears stale review outputs", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const nextRect = [
    [12, 12],
    [332, 12],
    [332, 192],
    [12, 192],
  ];
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({
      applyDraft() {
        return nextRect;
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
    next.roi.previewImage = "/tmp/preview.png";
    next.roi.draftRect = nextRect;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.jobId = "job-stale";
    next.exportConfig.runStatus = "done";
    next.review.pages = [{ id: "1", title: "페이지 1", capturePath: "/tmp/page-1.png", previewPath: "file:///tmp/page-1.png" }];
    next.review.selectedPageIds = ["1"];
    return next;
  });

  await root.dispatchAction("apply-roi");

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "export");
  assert.deepEqual(state.roi.appliedRect, nextRect);
  assert.equal(state.exportConfig.jobId, "");
  assert.equal(state.exportConfig.runStatus, "idle");
  assert.equal(state.review.pages.length, 0);
  assert.equal(getStepState(state, "export").enabled, true);
  assert.equal(getStepState(state, "review").enabled, false);
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

test("runExport skips the client-side ROI health preflight and creates a job immediately", async () => {
  installBrowserStubs();
  let createJobCalls = 0;
  let roiHealthCalls = 0;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      requestPreviewRoiHealth: async () => {
        roiHealthCalls += 1;
        return {
          riskLevel: "critical",
          summary: "ROI is unsafe for capture",
          diagnostics: [{ code: "roi_margin_tight", level: "critical" }],
        };
      },
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
    next.exportConfig.formats = ["png"];
    next.exportConfig.jobId = "job-old";
    next.exportConfig.outputDir = "/tmp/old-export";
    next.exportConfig.pdfPath = "/tmp/old-export/result.pdf";
    next.review.pages = [{ id: "page-1", capturePath: "/tmp/old-export/page-1.png" }];
    next.review.selectedPageIds = ["page-1"];
    next.review.outputDir = "/tmp/old-export";
    next.review.pdfPath = "/tmp/old-export/result.pdf";
    next.ui.activeStep = "export";
    return next;
  });

  await root.dispatchAction("run-export");
  await flush();

  const state = app.debug.getState();
  assert.equal(roiHealthCalls, 0);
  assert.equal(createJobCalls, 1);
  assert.equal(state.exportConfig.runStatus, "done");
  assert.equal(state.exportConfig.jobId, "job-1");
  assert.equal(state.exportConfig.outputDir, "");
  assert.equal(state.exportConfig.pdfPath, "");
  assert.equal(state.review.pages.length, 0);
  assert.equal(state.review.outputDir, "");
  assert.equal(state.review.pdfPath, "");
  assert.deepEqual(state.roi.diagnostics, []);
});

test("runExport leaves backend exclude candidates out of the default review selection", async () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({
        job_id: "job-1",
        status: "done",
        progress: 1,
        result: {
          review_candidates: ["/tmp/capture-1.png", "/tmp/capture-2.png", "/tmp/capture-3.png", "/tmp/capture-4.png"],
          images: ["/tmp/page-1.png", "/tmp/page-2.png", "/tmp/page-3.png"],
          page_diagnostics: [
            { page_index: 1, suspicious: false, recommended_action: "keep" },
            {
              page_index: 2,
              suspicious: true,
              diagnostic_codes: ["video_frame_content"],
              recommended_action: "exclude",
              warning_reasons: ["악보가 아닌 영상 화면이 함께 들어간 것으로 보입니다."],
            },
            {
              page_index: 3,
              suspicious: true,
              diagnostic_codes: ["sparse_score_page"],
              recommended_action: "review",
            },
          ],
          dropped_pages: [
            {
              page_index: 4,
              suspicious: true,
              diagnostic_codes: ["mostly_blank_page"],
              recommended_action: "exclude",
            },
          ],
        },
      }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.roi.frameTime = 5;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["png"];
    next.ui.activeStep = "export";
    return next;
  });

  await root.dispatchAction("run-export");
  await flush();

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "review");
  assert.deepEqual(state.review.selectedPageIds, ["1", "3"]);
  assert.equal(state.review.pages[1].autoExcludeCandidate, true);
  assert.equal(state.review.pages[2].autoExcludeCandidate, false);
  assert.equal(state.review.pages[3].autoExcludeCandidate, true);
});

test("runExport prevents duplicate jobs when re-entered before job creation resolves", async () => {
  installBrowserStubs();
  let createJobCalls = 0;
  let roiHealthCalls = 0;
  const pendingJob = deferred();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      requestPreviewRoiHealth: async () => {
        roiHealthCalls += 1;
        return {
          riskLevel: "info",
          summary: "",
          diagnostics: [],
        };
      },
      createJob: async () => {
        createJobCalls += 1;
        return pendingJob.promise;
      },
      getJob: async (jobId) => ({ job_id: jobId, status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.roi.frameTime = 5;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["png"];
    next.ui.activeStep = "export";
    return next;
  });

  const first = root.dispatchAction("run-export");
  const second = root.dispatchAction("run-export");
  await flush();

  pendingJob.resolve("job-1");

  await first;
  await second;
  await flush();

  assert.equal(roiHealthCalls, 0);
  assert.equal(createJobCalls, 1);
  assert.equal(app.debug.getState().exportConfig.jobId, "job-1");
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

test("applied review selection becomes editable when a checkbox changes", () => {
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
  assert.equal(state.review.status, "idle");
  assert.deepEqual(state.review.selectedPageIds, []);
  assert.equal(state.review.canUndo, true);
});

test("review checkbox rerender preserves the review grid scroll position", () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
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
    next.review.pages = Array.from({ length: 8 }, (_, index) => {
      const pageNumber = index + 1;
      return {
        id: String(pageNumber),
        title: `페이지 ${pageNumber}`,
        previewPath: `/tmp/page-${pageNumber}.png`,
        capturePath: `/tmp/page-${pageNumber}.png`,
      };
    });
    next.review.selectedPageIds = next.review.pages.map((page) => page.id);
    next.review.focusedPageId = "1";
    next.ui.activeStep = "review";
    return next;
  });

  const stagePane = root.querySelector("#stagePane");
  const beforeScroller = stagePane.querySelector(".review-grid");
  beforeScroller.scrollTop = 512;
  beforeScroller.scrollLeft = 24;
  globalThis.document.activeElement = {
    dataset: { action: "toggle-review-page", pageId: "5" },
  };

  root.dispatchInput({
    dataset: { action: "toggle-review-page", pageId: "5" },
    checked: false,
  });

  const afterScroller = stagePane.querySelector(".review-grid");
  const state = app.debug.getState();
  assert.equal(afterScroller.scrollTop, 512);
  assert.equal(afterScroller.scrollLeft, 24);
  assert.equal(globalThis.document.activeElement?.dataset?.pageId, "5");
  assert.deepEqual(state.review.selectedPageIds, ["1", "2", "3", "4", "6", "7", "8"]);
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
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      getArchiveLibrary: async () => ({
        items: [
          {
            sourceKey: "/tmp/library-source.mkv",
            sourceKind: "file",
            displayName: "library-source",
            completedAt: 1713526200,
            sourcePath: "/tmp/library-source.mkv",
            pdfPath: "/tmp/library-source.pdf",
            outputDir: "/tmp",
          },
        ],
      }),
      getLocalMediaRegistry: async () => ({
        items: [
          {
            filePath: "/tmp/library-source.mkv",
            displayName: "library-source.mkv",
            directory: "/tmp",
            resolutionLabel: "1920x1080",
            durationLabel: "00:30",
            hasScore: true,
            sourceOrigin: "prepared",
            youtubeUrl: "https://www.youtube.com/watch?v=library-source",
          },
        ],
      }),
    },
  });

  await flush();

  let state = app.debug.getState();
  assert.equal(state.source.registryItems.length, 1);
  assert.equal(state.source.registryItems[0].filePath, "/tmp/library-source.mkv");
  assert.equal(state.archive.items.length, 1);
  assert.equal(state.archive.items[0].sourceKey, "/tmp/library-source.mkv");

  await root.dispatchAction("load-registry-source", {
    filePath: "/tmp/library-source.mkv",
    displayName: "Take Five Drum Lesson",
    sourceOrigin: "prepared",
    youtubeUrl: "https://www.youtube.com/watch?v=library-source",
  });
  await flush();

  state = app.debug.getState();
  assert.equal(state.source.filePath, "/tmp/library-source.mkv");
  assert.equal(state.source.displayName, "Take Five Drum Lesson");
  assert.equal(state.source.archiveSourceKind, "youtube");
  assert.equal(state.source.archiveSourceKey, "https://www.youtube.com/watch?v=library-source");
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
  assert.match(root.querySelector("#topBar").innerHTML, /Drum Sheet Capture|Source|Language switcher/);

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

test("starting a new youtube prepare clears stale export and review state immediately", async () => {
  installBrowserStubs();
  const root = createRoot();
  const scheduled = [];
  const previousSetTimeout = globalThis.setTimeout;
  const previousClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = () => {
    scheduled.push(true);
    return 1;
  };
  globalThis.clearTimeout = () => {};

  try {
    const app = createApp(root, {
      exposeTestApi: true,
      api: {
        createPreviewSourceJob: async () => "source-1",
        getPreviewSourceJob: async () => ({
          jobId: "source-1",
          status: "running",
          stage: "download",
          progress: 0.42,
          progressMode: "determinate",
          message: "downloading video 42%",
          logLines: ["yt-dlp: download 42%"],
          result: {},
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
      next.source.filePath = "/tmp/stale.mp4";
      next.source.displayName = "stale.mp4";
      next.source.metadata = { durationSec: 60 };
      next.roi.previewImage = "/tmp/stale-preview.png";
      next.roi.appliedRect = ROI_RECT;
      next.exportConfig.jobId = "job-stale";
      next.exportConfig.runStatus = "done";
      next.review.pages = [{ id: "1", title: "페이지 1", capturePath: "/tmp/page-1.png", previewPath: "file:///tmp/page-1.png" }];
      next.review.selectedPageIds = ["1"];
      return next;
    });

    await root.dispatchAction("prepare-source-youtube");

    const state = app.debug.getState();
    assert.equal(state.ui.activeStep, "source");
    assert.equal(state.source.filePath, "");
    assert.equal(state.exportConfig.jobId, "");
    assert.equal(state.review.pages.length, 0);
    assert.equal(state.source.prepareStatus, "loading");
  } finally {
    globalThis.setTimeout = previousSetTimeout;
    globalThis.clearTimeout = previousClearTimeout;
  }
});

test("youtube prepare surfaces metadata hydration failure instead of leaving a false-ready state", async () => {
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
    readVideoMetadata: async () => {
      throw new Error("metadata probe failed");
    },
  });

  app.debug.setState((next) => {
    next.source.sourceType = "youtube";
    next.source.youtubeUrl = "https://youtu.be/demo";
    next.source.filePath = "/tmp/stale.mp4";
    next.source.metadata = { durationSec: 60 };
    next.roi.previewImage = "/tmp/stale-preview.png";
    next.exportConfig.jobId = "job-stale";
    return next;
  });

  await root.dispatchAction("prepare-source-youtube");

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "source");
  assert.equal(state.source.prepareStatus, "error");
  assert.match(state.source.error, /metadata probe failed/);
  assert.equal(state.source.filePath, "");
  assert.equal(state.source.metadata, null);
  assert.equal(state.roi.previewImage, "");
  assert.equal(state.exportConfig.jobId, "");
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

test("export after prepared youtube submits a file-backed payload without inheriting preview time", async () => {
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
  assert.equal(app.debug.getState().roi.frameTime, 60);
  assert.equal(seenPayload.options.extract.start_sec, 0);
});

test("youtube url flow exports with youtube identity and refreshes the media registry", async () => {
  installBrowserStubs();
  let seenPayload = null;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async (payload) => {
        seenPayload = payload;
        return "job-yt";
      },
      getJob: async () => ({
        job_id: "job-yt",
        status: "done",
        progress: 1,
        current_step: "done",
        message: "",
        result: {
          images: ["/tmp/export/page_0001.png"],
          output_dir: "/tmp/export",
          pdf: "/tmp/export/sheet_export.pdf",
          source_video_path: "/tmp/cache/youtube.mp4",
        },
      }),
      getLocalMediaRegistry: async () => ({
        items: [
          {
            filePath: "/tmp/cache/youtube.mp4",
            displayName: "Take Five Drum Lesson",
            directory: "/tmp/cache",
            resolutionLabel: "1920x1080",
            durationLabel: "04:12",
            hasScore: true,
            sourceOrigin: "job",
            youtubeUrl: "https://www.youtube.com/watch?v=abc12345678",
          },
        ],
      }),
      getArchiveLibrary: async () => ({ items: [] }),
      reviewExport: async () => ({}),
    },
  });

  app.debug.setState((next) => {
    next.source.sourceType = "youtube";
    next.source.youtubeUrl = "https://www.youtube.com/watch?v=abc12345678";
    next.source.filePath = "/tmp/cache/youtube.mp4";
    next.source.displayName = "Take Five Drum Lesson";
    next.source.preparedFromYouTube = true;
    next.source.archiveSourceKind = "youtube";
    next.source.archiveSourceKey = "https://www.youtube.com/watch?v=abc12345678";
    next.source.archiveDisplayName = "Take Five Drum Lesson";
    next.source.metadata = { durationSec: 252, durationLabel: "04:12", resolutionLabel: "1920x1080" };
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["png"];
    next.ui.activeStep = "export";
    return next;
  });

  await root.dispatchAction("run-export");
  await flush();
  await flush();

  assert.equal(seenPayload.source_type, "file");
  assert.equal(seenPayload.file_path, "/tmp/cache/youtube.mp4");
  assert.deepEqual(seenPayload.source_identity, {
    kind: "youtube",
    key: "https://www.youtube.com/watch?v=abc12345678",
    display_name: "Take Five Drum Lesson",
  });

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "review");
  assert.equal(state.source.registryItems.length, 1);
  assert.equal(state.source.registryItems[0].hasScore, true);
  assert.equal(state.source.registryItems[0].youtubeUrl, "https://www.youtube.com/watch?v=abc12345678");
});

test("buildJobPayload includes archive source identity for prepared youtube sources", () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, current_step: "done", message: "", result: {} }),
      reviewExport: async () => ({}),
    },
  });
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/cache/abc123.mp4";
  state.source.archiveSourceKind = "youtube";
  state.source.archiveSourceKey = "https://www.youtube.com/watch?v=abc123";
  state.source.archiveDisplayName = "Take Five Drum Lesson";
  state.roi.appliedRect = ROI_RECT;

  const payload = app.debug.buildJobPayload(state);

  assert.deepEqual(payload.source_identity, {
    kind: "youtube",
    key: "https://www.youtube.com/watch?v=abc123",
    display_name: "Take Five Drum Lesson",
  });
});

test("archive state starts closed and empty", () => {
  const state = createInitialSessionState();

  assert.deepEqual(state.archive, {
    isOpen: false,
    status: "idle",
    items: [],
    error: "",
    selectedSourceKey: "",
  });
});

test("archive modal mounts at the shell root, makes the shell inert, and closes on Escape", async () => {
  installBrowserStubs({
    getBackendState: async () => ({ ready: true, starting: false, running: true, error: "" }),
    onBackendState: () => () => {},
  });

  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      getArchiveLibrary: async () => ({
        items: [
          {
            sourceKey: "source-a",
            sourceKind: "file",
            displayName: "Archive Source A",
            completedAt: 1713526200,
            pdfPath: "/tmp/source-a.pdf",
            outputDir: "/tmp/source-a",
          },
        ],
      }),
    },
  });

  await flush();
  const opener = createElementNode();
  opener.focus();
  await root.dispatchAction("open-archive");
  await flush();

  assert.equal(app.debug.getState().archive.isOpen, true);
  assert.doesNotMatch(root.querySelector("#stagePane").innerHTML, /data-archive-modal/);
  assert.match(root.querySelector("#shellModalLayer").innerHTML, /data-archive-modal/);
  assert.equal(root.querySelector("#topBar").inert, true);
  assert.equal(root.querySelector("#workspaceShell").inert, true);
  assert.equal(root.querySelector("#statusBar").inert, true);
  assert.equal(root.querySelector("#topBar").getAttribute("aria-hidden"), "true");
  assert.equal(globalThis.document.activeElement, root.querySelector("#shellModalLayer").querySelector("[data-archive-dialog]"));

  const escapeEvent = await root.dispatchKeydown("Escape");
  await flush();

  assert.equal(escapeEvent.defaultPrevented, true);
  assert.equal(app.debug.getState().archive.isOpen, false);
  assert.equal(root.querySelector("#shellModalLayer").innerHTML, "");
  assert.equal(root.querySelector("#topBar").inert, false);
  assert.equal(root.querySelector("#workspaceShell").inert, false);
  // A dismissed, empty notice stays out of the tab order after the dialog closes.
  assert.equal(root.querySelector("#statusBar").inert, true);
  assert.equal(root.querySelector("#topBar").getAttribute("aria-hidden"), null);
  assert.equal(globalThis.document.activeElement, opener);
});

test("archive runtime wiring covers retry loading, selection, and open path actions", async () => {
  installBrowserStubs({
    getBackendState: async () => ({ ready: false, starting: false, running: false, error: "" }),
    onBackendState: () => () => {},
  });

  const archiveRequest = deferred();
  const openPathCalls = [];
  globalThis.window.drumSheetAPI.openPath = async (targetPath) => {
    openPathCalls.push(targetPath);
    return "";
  };

  let archiveRequests = 0;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      getArchiveLibrary: async () => {
        archiveRequests += 1;
        return archiveRequest.promise;
      },
    },
  });

  app.debug.setState((next) => {
    next.ui.backend = { ready: true, starting: false, running: true, error: "" };
    next.archive.isOpen = true;
    next.archive.status = "error";
    next.archive.error = "archive failed";
    next.archive.items = [
      {
        sourceKey: "source-b",
        sourceKind: "file",
        displayName: "Stale Archive Item",
        completedAt: 1713526200,
        pdfPath: "/tmp/stale.pdf",
        outputDir: "/tmp/stale",
      },
    ];
    return next;
  });

  await root.dispatchAction("retry-archive");
  await flush();

  assert.equal(archiveRequests, 1);
  assert.equal(app.debug.getState().archive.status, "loading");
  assert.match(root.querySelector("#shellModalLayer").innerHTML, /Loading archive\.\.\.|보관함을 불러오는 중입니다\./);
  assert.doesNotMatch(root.querySelector("#shellModalLayer").innerHTML, /Stale Archive Item/);

  archiveRequest.resolve({
    items: [
      {
        sourceKey: "source-c",
        sourceKind: "file",
        displayName: "Archive Source C",
        completedAt: 1713526200,
        pdfPath: "/tmp/source-c.pdf",
        outputDir: "/tmp/source-c",
      },
    ],
  });
  await flush();

  await root.dispatchAction("select-archive-item", { sourceKey: "source-c" });
  assert.equal(app.debug.getState().archive.selectedSourceKey, "source-c");

  await root.dispatchAction("open-archive-pdf", { sourceKey: "source-c" });
  await root.dispatchAction("open-archive-folder", { sourceKey: "source-c" });

  assert.deepEqual(openPathCalls, ["/tmp/source-c.pdf", "/tmp/source-c"]);

  await root.dispatchAction("close-archive");
  assert.equal(app.debug.getState().archive.isOpen, false);
  assert.equal(app.debug.getState().archive.selectedSourceKey, "");
});

test("status bar exposes backend recovery controls when backend is not ready", async () => {
  let restartCalls = 0;
  let setupCalls = 0;
  installBrowserStubs({
    getBackendState: async () => ({ ready: false, starting: false, running: false, error: "backend down" }),
    onBackendState: () => () => {},
    restartBackend: async () => {
      restartCalls += 1;
      return "";
    },
    runGuidedSetup: async () => {
      setupCalls += 1;
      return "";
    },
  });

  const root = createRoot();
  createApp(root, { exposeTestApi: true });
  await flush();

  assert.match(root.querySelector("#statusBar").innerHTML, /restart-backend/);
  assert.match(root.querySelector("#statusBar").innerHTML, /run-guided-setup/);

  await root.dispatchAction("restart-backend");
  await root.dispatchAction("run-guided-setup");

  assert.equal(restartCalls, 1);
  assert.equal(setupCalls, 1);
});

test("late review apply result is ignored after a newer source is loaded", async () => {
  installBrowserStubs();
  const reviewExportRequest = deferred();
  const refreshedJob = deferred();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    readVideoMetadata: async () => ({ durationSec: 30, durationLabel: "00:30", resolutionLabel: "1920x1080" }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      reviewExport: async () => {
        await reviewExportRequest.promise;
        return {};
      },
      getJob: async () => refreshedJob.promise,
    },
  });

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/old-source.mp4";
    next.source.displayName = "old-source.mp4";
    next.source.metadata = { durationSec: 120 };
    next.ui.activeStep = "review";
    next.roi.appliedRect = ROI_RECT;
    next.roi.draftRect = ROI_RECT;
    next.exportConfig.jobId = "job-1";
    next.exportConfig.runStatus = "done";
    next.exportConfig.formats = ["png"];
    next.review.pages = [{ id: "1", title: "페이지 1", capturePath: "/tmp/capture-1.png", previewPath: "file:///tmp/capture-1.png", selectionMode: "captures" }];
    next.review.selectedPageIds = ["1"];
    return next;
  });

  const pendingApply = root.dispatchAction("apply-review");
  await flush();
  await root.dispatchAction("load-registry-source", {
    filePath: "/tmp/new-source.mp4",
    displayName: "new-source.mp4",
    sourceOrigin: "job",
    youtubeUrl: "",
  });
  await flush();

  reviewExportRequest.resolve({});
  refreshedJob.resolve({
    job_id: "job-1",
    status: "done",
    progress: 1,
    current_step: "done",
    message: "",
    result: {
      images: ["/tmp/stale-page.png"],
      output_dir: "/tmp/stale-export",
      pdf: "/tmp/stale-export/result.pdf",
      review_export: { kept_count: 1, requested_count: 1, selection_mode: "captures" },
    },
  });
  await pendingApply;
  await flush();

  const state = app.debug.getState();
  assert.equal(state.source.filePath, "/tmp/new-source.mp4");
  assert.equal(state.exportConfig.jobId, "");
  assert.equal(state.review.pages.length, 0);
  assert.equal(state.ui.activeStep, "roi");
});

test("a transient poll failure reconnects to the same job without creating another capture", async () => {
  installBrowserStubs();
  const root = createRoot();
  let created = 0, reads = 0;
  const app = createApp(root, { exposeTestApi: true, api: {
    createJob: async () => { created++; return "reconnect-job"; },
    getJob: async () => {
      reads++;
      if (reads === 1) throw new Error("connection interrupted");
      return { job_id: "reconnect-job", status: "done", progress: 1, result: { review_candidates: ["/capture.png"] } };
    },
  }});
  app.debug.setState(next => {
    next.source.filePath = "/video.mp4";
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["png"];
    next.ui.activeStep = "export";
    return next;
  });
  await root.dispatchAction("run-export");
  await flush();
  assert.equal(app.debug.getState().exportConfig.runStatus, "running");
  assert.equal(app.debug.getState().exportConfig.connectionState, "reconnecting");
  await root.dispatchAction("reconnect-job");
  await flush();
  assert.equal(app.debug.getState().exportConfig.runStatus, "done");
  assert.equal(created, 1);
  assert.equal(reads, 2);
  app.destroy();
});

function createSavedSessionStorage(jobId) {
  const values = new Map([["drum-sheet-session-v1", JSON.stringify({
    version: 1,
    source: { filePath: "/video.mp4", sourceType: "file", displayName: "video.mp4" },
    roi: { appliedRect: ROI_RECT },
    exportConfig: { formats: ["png"], jobId, runStatus: "done" },
    review: { jobId, revision: 1, selectedPaths: ["/capture-1.png"], systemOrder: ["system-1"] },
  })]]);
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    saved: () => JSON.parse(values.get("drum-sheet-session-v1") || "null"),
  };
}

async function settle() {
  for (let index = 0; index < 6; index += 1) await flush();
}

test("a restored job that no longer exists is forgotten and points back to making the files again", async () => {
  installBrowserStubs();
  const root = createRoot();
  const storage = createSavedSessionStorage("gone-job");
  let reads = 0;
  const app = createApp(root, { exposeTestApi: true, storage, api: {
    getJob: async () => { reads++; throw Object.assign(new Error("job not found"), { status: 404 }); },
  }});
  await settle();
  const state = app.debug.getState();
  assert.equal(reads, 1);
  assert.equal(state.exportConfig.jobId, "");
  assert.equal(state.exportConfig.runStatus, "idle");
  assert.equal(state.exportConfig.error, "");
  assert.equal(state.ui.activeStep, "export");
  assert.equal(state.ui.inlineNotice, t("export.restoredJobMissing", { locale: state.ui.locale }));
  assert.equal(state.source.filePath, "/video.mp4");
  assert.deepEqual(state.roi.appliedRect, ROI_RECT);
  const statusBar = root.querySelector("#statusBar").innerHTML;
  assert.doesNotMatch(statusBar, new RegExp(t("support.failureTitle", { locale: state.ui.locale })));
  assert.equal(storage.saved().exportConfig.jobId, "");
  assert.equal(storage.saved().review.selectedPaths, null);
  assert.equal(storage.saved().review.jobId, "");
  assert.equal(storage.saved().review.systemOrder, null);
  assert.equal(storage.saved().review.applied, false);
  assert.equal(storage.saved().source.filePath, "/video.mp4");
  app.destroy();

  // The next launch starts clean instead of asking the backend for the missing job again.
  const relaunched = createApp(createRoot(), { exposeTestApi: true, storage, api: {
    getJob: async () => { reads++; throw Object.assign(new Error("job not found"), { status: 404 }); },
  }});
  await settle();
  assert.equal(reads, 1);
  assert.equal(relaunched.debug.getState().ui.inlineNotice, "");
  relaunched.destroy();
});

for (const [label, failure] of [
  ["a server error", Object.assign(new Error("internal error"), { status: 503 })],
  ["a network failure", new Error("connection refused")],
]) {
  test(`${label} while restoring keeps the saved job and retries`, async () => {
    installBrowserStubs();
    const root = createRoot();
    const storage = createSavedSessionStorage("live-job");
    let reads = 0;
    const app = createApp(root, { exposeTestApi: true, storage, api: {
      getJob: async () => {
        reads++;
        if (reads === 1) throw failure;
        return { job_id: "live-job", status: "done", progress: 1, result: { review_candidates: ["/capture-1.png"] } };
      },
    }});
    await settle();
    let state = app.debug.getState();
    assert.equal(state.exportConfig.jobId, "live-job");
    assert.equal(state.exportConfig.connectionState, "reconnecting");
    assert.equal(state.ui.activeStep, "export");
    assert.equal(state.ui.inlineNotice, "");
    assert.equal(storage.saved().exportConfig.jobId, "live-job");
    assert.deepEqual(storage.saved().review.selectedPaths, ["/capture-1.png"]);
    assert.equal(storage.saved().review.jobId, "live-job");
    await root.dispatchAction("reconnect-job");
    await settle();
    state = app.debug.getState();
    assert.equal(state.exportConfig.runStatus, "done");
    assert.equal(state.exportConfig.jobId, "live-job");
    assert.equal(reads, 2);
    app.destroy();
  });
}

test("PDF open and Save As dispatch separate actions without changing the original output", async t => {
  const opened = [];
  const saves = [];
  const pending = deferred();
  installBrowserStubs({
    openPath: async path => { opened.push(path); return ""; },
    savePdfAs: async options => { saves.push(options); return pending.promise; },
  });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true, api: {} });
  t.after(() => app.destroy());
  app.debug.setState(s => {
    s.ui.locale = "ko";
    s.source.displayName = "practice.mp4";
    s.exportConfig.documentHeader.title = "연습 악보";
    s.review.pdfPath = "/tmp/export/score.pdf";
    s.review.outputDir = "/tmp/export";
    return s;
  });
  await root.dispatchAction("open-output-pdf");
  assert.deepEqual(opened, ["/tmp/export/score.pdf"]);
  assert.equal(saves.length, 0);
  const save = root.dispatchAction("save-output-pdf-as");
  await flush();
  assert.equal(app.debug.getState().ui.savingPdfAs, true);
  await root.dispatchAction("save-output-pdf-as");
  assert.equal(saves.length, 1);
  assert.deepEqual(saves[0], { sourcePath: "/tmp/export/score.pdf", suggestedName: "연습 악보", locale: "ko" });
  pending.resolve({ canceled: false, filePath: "/tmp/my-score.pdf" });
  await save;
  assert.equal(app.debug.getState().ui.savingPdfAs, false);
  assert.match(app.debug.getState().ui.inlineNotice, /PDF 복사본을 저장했습니다: \/tmp\/my-score.pdf/);
  assert.equal(app.debug.getState().review.pdfPath, "/tmp/export/score.pdf");
  assert.equal(opened.length, 1);
});

test("Save As cancellation is quiet and errors allow retry", async t => {
  let fail = false;
  installBrowserStubs({ savePdfAs: async () => {
    if (fail) throw new Error("EACCES");
    return { canceled: true };
  } });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true, api: {} });
  t.after(() => app.destroy());
  app.debug.setState(s => { s.ui.locale = "ko"; s.review.pdfPath = "/tmp/score.pdf"; s.ui.inlineNotice = ""; return s; });
  await root.dispatchAction("save-output-pdf-as");
  assert.equal(app.debug.getState().ui.inlineNotice, "");
  assert.equal(app.debug.getState().ui.savingPdfAs, false);
  fail = true;
  await root.dispatchAction("save-output-pdf-as");
  assert.match(app.debug.getState().ui.inlineNotice, /PDF를 저장하지 못했습니다: EACCES/);
  assert.equal(app.debug.getState().ui.savingPdfAs, false);
});

test('capture range inputs reach the job payload without clearing existing review output', async () => {
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true });
  app.debug.setState(s => {
    s.source.filePath='/fixture.mp4';s.source.metadata={durationSec:200};
    s.roi.appliedRect=[[0,0],[100,0],[100,100],[0,100]];
    s.review.pdfPath='/previous/score.pdf';return s;
  });
  root.dispatchInput({dataset:{action:'capture-range',field:'rangeStart'},value:'1:30'});
  root.dispatchInput({dataset:{action:'capture-range',field:'rangeEnd'},value:'2:00'});
  const state=app.debug.getState();
  assert.equal(state.review.pdfPath,'/previous/score.pdf');
  assert.equal(app.debug.buildJobPayload(state).options.extract.start_sec,90);
  assert.equal(app.debug.buildJobPayload(state).options.extract.end_sec,120);
  app.debug.setState(s=>{s.exportConfig.runStatus='running';return s;});
  root.dispatchInput({dataset:{action:'capture-range',field:'rangeStart'},value:'10'});
  assert.equal(app.debug.getState().exportConfig.rangeStart,'1:30');
  app.destroy();
});

test("an update that needs a newer OS points to the download page instead of installing", async () => {
  installBrowserStubs({
    checkReleaseUpdate: async () => ({
      status: "available", version: "0.2.0", canInstall: false, currentVersion: "0.1.37",
      requiredOs: { platform: "darwin", version: "13.0" },
    }),
    onReleaseUpdateState: () => () => {},
  });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true });
  await flush();
  const statusBar = root.querySelector("#statusBar").innerHTML;
  assert.match(statusBar, /macOS 13\.0/);
  assert.match(statusBar, /data-action="open-release-page"/);
  assert.match(statusBar, /data-action="dismiss-release-update"/);
  assert.doesNotMatch(statusBar, /data-action="download-release-update"/);
  app.destroy();
});

test("release update moves from available to download to restart, and waits for running work", async () => {
  let pushState = () => {};
  const calls = [];
  const available = { status: "available", version: "0.2.0", canInstall: true, currentVersion: "0.1.34" };
  installBrowserStubs({
    checkReleaseUpdate: async (options) => { calls.push(["check", options]); return available; },
    onReleaseUpdateState: (handler) => { pushState = handler; return () => { pushState = () => {}; }; },
    downloadReleaseUpdate: async () => {
      calls.push(["download"]);
      pushState({ status: "downloading", version: "0.2.0", progress: 42 });
      return { status: "ready", version: "0.2.0" };
    },
    installReleaseUpdate: async (options) => { calls.push(["install", options]); return { status: "installing", version: "0.2.0" }; },
  });
  const root = createRoot();
  let jobStatus = "running";
  let createJobCalls = 0;
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      createJob: async () => { createJobCalls += 1; return "job-1"; },
      getJob: async () => ({ job_id: "job-1", status: jobStatus, progress: 0.3, result: {} }),
      cancelJob: async () => { jobStatus = "cancelled"; },
    },
  });
  await flush();
  const statusBar = () => root.querySelector("#statusBar").innerHTML;
  assert.deepEqual(calls[0], ["check", { manual: false }]);
  assert.match(statusBar(), /0\.2\.0/);
  assert.match(statusBar(), /data-action="download-release-update"/);
  assert.match(statusBar(), /data-action="dismiss-release-update"/);
  assert.match(root.querySelector("#topBar").innerHTML, /topbar-update has-update/);

  pushState({ status: "downloading", version: "0.2.0", progress: 42 });
  assert.match(statusBar(), /42%/);
  assert.doesNotMatch(statusBar(), /data-action="download-release-update"/);

  await root.dispatchAction("download-release-update");
  assert.match(statusBar(), /data-action="install-release-update"(?! disabled)/);

  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.roi.frameTime = 5;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["png"];
    next.ui.activeStep = "export";
    return next;
  });
  await root.dispatchAction("run-export");
  await flush();
  assert.match(statusBar(), /data-action="install-release-update" disabled/);
  await root.dispatchAction("install-release-update");
  assert.equal(calls.some(([name]) => name === "install"), false, "a running capture is never interrupted");

  await root.dispatchAction("cancel-job");
  await flush();
  await flush();
  assert.match(statusBar(), /data-action="install-release-update">/);
  await root.dispatchAction("install-release-update");
  assert.deepEqual(calls.at(-1), ["install", { unsavedWork: false }]);
  assert.match(statusBar(), /(Installing the update|설치하고 있습니다)/);
  assert.equal(root.querySelector("#workspaceShell").inert, true, "nothing new can start while installing");
  assert.equal(root.querySelector("#topBar").inert, true);
  const jobsBefore = createJobCalls;
  assert.equal(jobsBefore, 1);
  await root.dispatchAction("run-export");
  assert.equal(createJobCalls, jobsBefore);
  app.destroy?.();
});

test("manual update check reports the latest version, a failure, or source runs", async () => {
  for (const [result, pattern] of [
    [{ status: "current", currentVersion: "0.1.34" }, /0\.1\.34/],
    [{ status: "error", error: "check" }, /(Could not check|확인하지 못했습니다)/],
    [{ status: "unsupported" }, /(running from source|개발 실행)/],
  ]) {
    const calls = [];
    installBrowserStubs({
      checkReleaseUpdate: async (options) => {
        calls.push(options);
        return options?.manual ? result : { status: "idle" };
      },
    });
    const root = createRoot();
    const app = createApp(root, { exposeTestApi: true });
    await flush();
    assert.match(root.querySelector("#topBar").innerHTML, /data-action="check-release-update"/);
    await root.dispatchAction("check-release-update");
    assert.deepEqual(calls.at(-1), { manual: true });
    assert.match(app.debug.getState().ui.inlineNotice, pattern);
    app.destroy?.();
  }
});

test("an unapplied score region or an open page crop keeps the update from restarting the app", async () => {
  const calls = [];
  installBrowserStubs({
    checkReleaseUpdate: async () => ({ status: "ready", version: "0.2.0" }),
    installReleaseUpdate: async (options) => { calls.push(options); return { status: "ready", version: "0.2.0", error: "busy" }; },
  });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true });
  await flush();
  const statusBar = () => root.querySelector("#statusBar").innerHTML;
  assert.match(statusBar(), /data-action="install-release-update">/);

  app.debug.setState((next) => {
    next.roi.appliedRect = ROI_RECT;
    next.roi.draftRect = [[10, 10], [300, 10], [300, 170], [10, 170]];
    return next;
  });
  assert.match(statusBar(), /data-action="install-release-update" disabled/);
  assert.match(statusBar(), /(unsaved edits|적용하지 않은 편집)/);

  app.debug.setState((next) => {
    next.roi.draftRect = ROI_RECT;
    next.review.cropping = true;
    return next;
  });
  assert.match(statusBar(), /data-action="install-release-update" disabled/);

  app.debug.setState((next) => { next.review.cropping = false; return next; });
  await root.dispatchAction("install-release-update");
  assert.deepEqual(calls, [{ unsavedWork: false }]);
  assert.match(statusBar(), /(unsaved edits|적용하지 않은 편집)/, "work the backend still reports keeps the install waiting");
  app.destroy?.();
});

test("macOS manual fallback offers to reopen the installer window", async () => {
  let opened = 0;
  installBrowserStubs({
    checkReleaseUpdate: async () => ({ status: "manual", version: "0.2.0", reason: "swap-failed" }),
    openReleaseInstaller: async () => { opened += 1; return true; },
  });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true });
  await flush();
  assert.match(root.querySelector("#statusBar").innerHTML, /(could not be installed automatically|자동으로 설치하지 못했습니다)/);
  await root.dispatchAction("open-release-installer");
  assert.equal(opened, 1);
  app.destroy?.();
});

test("problem report dialog captures the screen first, validates, sends the draft, and starts over once sent", async () => {
  const calls = [];
  const send = deferred();
  installBrowserStubs({
    prepareBugReport: async (detail) => { calls.push(["prepare", detail]); return { configured: true, diagnostics: "log line <b>", screenshotPreview: "data:image/jpeg;base64,AAAA" }; },
    sendBugReport: (input) => { calls.push(["send", input]); return send.promise; },
  });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true });
  await flush();
  app.debug.setState((next) => { next.review.error = "Review failed"; return next; });
  const modal = () => root.querySelector("#shellModalLayer").innerHTML;

  assert.match(root.querySelector("#topBar").innerHTML, /data-action="open-bug-report"/);
  assert.match(root.querySelector("#statusBar").innerHTML, /data-action="open-bug-report"/);
  await root.dispatchAction("open-bug-report");
  assert.deepEqual(calls[0], ["prepare", "Review failed"]);
  assert.match(modal(), /data-bug-report-dialog/);
  assert.match(modal(), /log line &lt;b&gt;/);
  assert.doesNotMatch(modal(), /data:image\/jpeg/, "the screenshot is opt-in");
  assert.equal(root.querySelector("#workspaceShell").inert, true);

  await root.dispatchAction("send-bug-report");
  assert.equal(calls.length, 1, "an empty description is not sent");
  assert.match(modal(), /data-bug-report-field="description"[^>]*aria-invalid="true"/);

  root.dispatchInput({ type: "checkbox", checked: true, dataset: { bugReportField: "includeScreenshot" } });
  assert.match(modal(), /src="data:image\/jpeg;base64,AAAA"/);
  root.dispatchInput({ type: "email", value: "bad", dataset: { bugReportField: "email" } });
  root.dispatchInput({ type: "textarea", value: "x", dataset: { bugReportField: "description" } });
  await root.dispatchAction("send-bug-report");
  assert.match(modal(), /data-bug-report-field="email"[^>]*aria-describedby="bugReportEmailHint bugReportError-email"/);
  assert.equal(calls.length, 1, "a malformed reply address is not sent");
  const before = modal();
  root.dispatchInput({ type: "textarea", value: "Page 2 is missing", dataset: { bugReportField: "description" } });
  root.dispatchInput({ type: "email", value: "me@example.com", dataset: { bugReportField: "email" } });
  app.debug.setState((next) => { next.ui.inlineNotice = "unrelated"; return next; });
  assert.equal(modal(), before, "typing and unrelated renders do not rebuild the dialog under the caret");

  const pending = root.dispatchAction("send-bug-report");
  await flush();
  assert.match(modal(), /data-action="send-bug-report" disabled/);
  assert.equal((await root.dispatchKeydown("Escape")).defaultPrevented, true);
  assert.match(modal(), /data-bug-report-dialog/, "the dialog stays open while sending");
  send.resolve({ status: "sent" });
  await pending;
  assert.deepEqual(calls[1], ["send", {
    description: "Page 2 is missing", steps: "", email: "me@example.com", includeDiagnostics: true, includeScreenshot: true, locale: app.debug.getState().ui.locale,
  }]);
  assert.match(modal(), /(Report sent|보고를 보냈습니다)/);

  await root.dispatchAction("close-bug-report");
  assert.equal(modal(), "");
  assert.equal(root.querySelector("#workspaceShell").inert, false);
  await root.dispatchAction("open-bug-report");
  assert.match(modal(), /<textarea rows="4" data-bug-report-field="description"[^>]*><\/textarea>/, "a sent report starts over");
  app.destroy?.();
});

test("a failed send keeps the draft and offers GitHub without the reply address", async () => {
  const issues = [];
  installBrowserStubs({
    prepareBugReport: async () => ({ configured: true, diagnostics: "log", screenshotPreview: "" }),
    sendBugReport: async () => ({ status: "error", reason: "rate-limited" }),
    openBugReportIssue: async (input) => { issues.push(input); return { opened: true, copied: true }; },
  });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true });
  await flush();
  const modal = () => root.querySelector("#shellModalLayer").innerHTML;
  await root.dispatchAction("open-bug-report");
  root.dispatchInput({ type: "textarea", value: "Crash on export", dataset: { bugReportField: "description" } });
  root.dispatchInput({ type: "email", value: "me@example.com", dataset: { bugReportField: "email" } });
  await root.dispatchAction("send-bug-report");
  assert.match(modal(), /role="alert"/);
  assert.match(modal(), /data-action="open-bug-report-issue"/);

  await root.dispatchAction("open-bug-report-issue");
  assert.deepEqual(issues, [{ description: "Crash on export", steps: "", includeDiagnostics: true, includeScreenshot: false }]);
  assert.match(modal(), /(Diagnostics copied|진단 로그를 클립보드에 복사)/);

  await root.dispatchKeydown("Escape");
  assert.equal(modal(), "");
  await root.dispatchAction("open-bug-report");
  assert.match(modal(), />Crash on export<\/textarea>/, "an unsent draft survives closing");
  app.destroy?.();
});

test("without a relay the dialog goes straight to GitHub and asks for nothing that would be public", async () => {
  installBrowserStubs({ prepareBugReport: async () => ({ configured: false, diagnostics: "log", screenshotPreview: "data:image/jpeg;base64,AAAA" }) });
  const root = createRoot();
  const app = createApp(root, { exposeTestApi: true });
  await flush();
  await root.dispatchAction("open-bug-report");
  const modal = root.querySelector("#shellModalLayer").innerHTML;
  assert.match(modal, /data-action="open-bug-report-issue"/);
  assert.doesNotMatch(modal, /data-action="send-bug-report"/);
  assert.doesNotMatch(modal, /data-bug-report-field="email"/);
  assert.doesNotMatch(modal, /data-bug-report-field="includeScreenshot"/);
  assert.match(modal, /(GitHub issues are public|누구나 볼 수 있으니)/);
  app.destroy?.();
});

test("after Apply the export step shows the region check and its suggested area returns to the ROI step as a draft", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const suggested = [[0, 40], [1920, 40], [1920, 1080], [0, 1080]];
  const health = deferred();
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({ applyDraft() { return ROI_RECT; }, setDraft() {}, destroy() {} }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "/tmp/preview.png", sourcePath: "/tmp/preview.png", diagnostics: [] }),
      requestPreviewRoiHealth: () => health.promise,
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
    next.roi.draftRect = ROI_RECT;
    return next;
  });
  await root.dispatchAction("apply-roi");
  let state = app.debug.getState();
  assert.equal(state.ui.activeStep, "export");
  assert.equal(state.roi.clipCheck.status, "loading");
  assert.match(root.querySelector("#stagePane").innerHTML, /export-clip-note is-loading/);

  health.resolve({ envelope: { status: "found", clipped: true, suggestedRoi: suggested } });
  await flush();
  state = app.debug.getState();
  assert.equal(state.roi.clipCheck.status, "clipped");
  assert.match(root.querySelector("#stagePane").innerHTML, /data-action="use-suggested-roi"/);

  await root.dispatchAction("use-suggested-roi");
  state = app.debug.getState();
  assert.equal(state.ui.activeStep, "roi");
  assert.deepEqual(state.roi.draftRect, suggested);
  assert.deepEqual(state.roi.appliedRect, ROI_RECT, "applying stays a separate user action");
});

test("a failed region check after Apply offers a retry on the export step", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  let calls = 0;
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({ applyDraft() { return ROI_RECT; }, setDraft() {}, destroy() {} }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      requestPreviewRoiHealth: async () => { calls += 1; if (calls === 1) throw new Error("backend busy"); return { envelope: { status: "found", clipped: false } }; },
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.ui.activeStep = "roi";
    next.roi.draftRect = ROI_RECT;
    return next;
  });
  await root.dispatchAction("apply-roi");
  await flush();
  assert.equal(app.debug.getState().roi.clipCheck.status, "error");
  assert.match(root.querySelector("#stagePane").innerHTML, /data-action="recheck-roi"/);
  await root.dispatchAction("recheck-roi");
  await flush();
  assert.equal(app.debug.getState().roi.clipCheck.status, "clear");
  assert.doesNotMatch(root.querySelector("#stagePane").innerHTML, /export-clip-note/);
});

test("after a restart the region check waits for the processor instead of showing a failed check", async () => {
  let backendHandler = null;
  installBrowserStubs({
    getBackendState: async () => ({ ready: false, starting: true, running: false, error: "" }),
    onBackendState: (handler) => { backendHandler = handler; return () => {}; },
  });
  const root = createDynamicStageRoot();
  const healthCalls = [];
  const storage = memoryStorage();
  storage.setItem("drum-sheet-session-v1", JSON.stringify({
      version: 1,
      source: { filePath: "/tmp/source-a.mp4", displayName: "source-a.mp4", metadata: { durationSec: 120, width: 1920, height: 1080 } },
      roi: { appliedRect: ROI_RECT, frameTime: 10, imageWidth: 1920, imageHeight: 1080 },
      exportConfig: { formats: ["png"], jobId: "" },
      review: {},
  }));
  const app = createApp(root, {
    exposeTestApi: true,
    storage,
    mountRoiEditor: () => ({ applyDraft() { return ROI_RECT; }, setDraft() {}, destroy() {} }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      requestPreviewRoiHealth: async (payload) => {
        healthCalls.push(payload);
        // the processor is still starting: the request never reaches it
        if (!app.debug.getState().ui.backend?.ready) throw new Error("REQUEST_FAILED: connect ECONNREFUSED");
        return { envelope: { status: "found", clipped: false } };
      },
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  await flush();
  await flush();

  let state = app.debug.getState();
  assert.equal(state.ui.activeStep, "roi", "a restored session without a job opens on the region step");
  assert.deepEqual(state.roi.appliedRect, ROI_RECT);
  assert.equal(healthCalls.length, 0, "no check is sent while the processor is starting");
  assert.notEqual(state.roi.clipCheck.status, "error");

  app.debug.setState((next) => { next.ui.activeStep = "export"; return next; });
  assert.doesNotMatch(root.querySelector("#stagePane").innerHTML, /export-clip-note is-error|data-action="recheck-roi"/,
    "the export step shows no failed check before any check ran");
  app.debug.setState((next) => { next.ui.activeStep = "roi"; return next; });
  await flush();
  assert.equal(healthCalls.length, 0);

  backendHandler({ ready: true, starting: false, running: true, error: "" });
  await flush();
  await flush();
  state = app.debug.getState();
  assert.equal(healthCalls.length, 1, "the check runs once the processor is ready");
  assert.deepEqual(healthCalls[0].roi, ROI_RECT);
  assert.equal(state.roi.clipCheck.status, "clear");
  assert.deepEqual(state.roi.appliedRect, ROI_RECT, "the check never changes the applied region");
  app.destroy?.();
});

test("a region check cut off because the processor stopped is not reported as a failed check", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const pending = deferred();
  let calls = 0;
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: () => ({ applyDraft() { return ROI_RECT; }, setDraft() {}, destroy() {} }),
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      requestPreviewRoiHealth: async () => { calls += 1; if (calls === 1) return pending.promise; return { envelope: { status: "found", clipped: false } }; },
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  await flush();
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.ui.activeStep = "roi";
    next.roi.draftRect = ROI_RECT;
    return next;
  });
  await root.dispatchAction("apply-roi");
  assert.equal(app.debug.getState().roi.clipCheck.status, "loading");
  app.debug.setState((next) => { next.ui.backend = { ready: false, starting: true, running: false, error: "" }; return next; });
  pending.reject(new Error("REQUEST_FAILED: connect ECONNREFUSED"));
  await flush();
  await flush();
  assert.equal(app.debug.getState().roi.clipCheck.status, "idle");
  assert.equal(app.debug.getState().ui.activeStep, "export");
  assert.doesNotMatch(root.querySelector("#stagePane").innerHTML, /export-clip-note is-error|data-action="recheck-roi"/);

  // Once the processor is back, the cut-off check reruns on the export step.
  app.debug.setState((next) => { next.ui.backend = { ready: true, starting: false, running: true, error: "" }; return next; });
  await flush();
  await flush();
  assert.equal(calls, 2);
  assert.equal(app.debug.getState().roi.clipCheck.status, "clear");
  app.destroy?.();
});

test("rebuilding a clean reflow chart sends the arranged system order with the selection", async () => {
  installBrowserStubs();
  const root = createRoot();
  const calls = [];
  const strips = ["/j/strip_sys-001.png", "/j/strip_sys-002.png", "/j/strip_sys-003.png"];
  const result = {
    output_model: "clean_reflow_v1", review_candidates: strips, preview_images: ["/j/p1.jpg"], pdf: "/j/out.pdf", images: ["/j/p1.png"],
    capture_diagnostics: Object.fromEntries(strips.map((p, i) => [p, { system_id: `sys-00${i + 1}`, recommended_action: "keep" }])),
  };
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result }),
      reviewExport: async (jobId, body) => { calls.push(body); return {}; },
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.roi.appliedRect = ROI_RECT;
    next.roi.draftRect = ROI_RECT;
    next.exportConfig.jobId = "job-1";
    next.exportConfig.runStatus = "done";
    next.exportConfig.formats = ["pdf"];
    next.ui.activeStep = "review";
    return next;
  });
  await root.dispatchAction("reconnect-job");
  await flush();
  app.debug.setState((next) => {
    const [a, b, c] = next.review.pages;
    next.review.pages = [c, a, b];
    next.review.selectedPageIds = [c.id, b.id];
    return next;
  });
  await root.dispatchAction("apply-review");
  await flush();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].systemOrder, [strips[2], strips[0], strips[1]]);
  assert.deepEqual(calls[0].keepCaptures, [strips[2], strips[1]]);
});

test("an other-moment alternate starts unchecked and can be placed instead of its system or with it", async () => {
  installBrowserStubs();
  const root = createRoot();
  const calls = [];
  const strips = ["/j/strip_sys-001.png", "/j/alt/strip_sys-001-alt1.png", "/j/strip_sys-002.png"];
  const diag = {
    [strips[0]]: { system_id: "sys-001", recommended_action: "keep", suspicious: true, diagnostic_codes: ["MINORITY_CONTENT_DROPPED"] },
    [strips[1]]: { system_id: "sys-001-alt1", recommended_action: "exclude", suspicious: true, alternate_of: "sys-001",
      diagnostic_codes: ["MINORITY_ALTERNATE"] },
    [strips[2]]: { system_id: "sys-002", recommended_action: "keep" },
  };
  const result = {
    output_model: "clean_reflow_v1", review_candidates: strips, preview_images: ["/j/p1.jpg"], pdf: "/j/out.pdf", images: ["/j/p1.png"],
    capture_diagnostics: diag, auto_excluded_captures: [strips[1]],
  };
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result }),
      reviewExport: async (jobId, body) => { calls.push(body); return {}; },
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.roi.appliedRect = ROI_RECT;
    next.roi.draftRect = ROI_RECT;
    next.exportConfig.jobId = "job-1";
    next.exportConfig.runStatus = "done";
    next.exportConfig.formats = ["pdf"];
    next.ui.activeStep = "review";
    return next;
  });
  await root.dispatchAction("reconnect-job");
  await flush();
  const pages = app.debug.getState().review.pages;
  assert.deepEqual(pages.map(page => page.capturePath), strips); // listed right after its system
  assert.equal(pages[1].minorityAlternate, true);
  assert.deepEqual(app.debug.getState().review.selectedPageIds, [pages[0].id, pages[2].id]); // unchecked
  // instead of its system
  app.debug.setState((next) => { next.review.selectedPageIds = [pages[1].id, pages[2].id]; return next; });
  await root.dispatchAction("apply-review");
  await flush();
  assert.deepEqual(calls[0].keepCaptures, [strips[1], strips[2]]);
  assert.deepEqual(calls[0].systemOrder, strips);
  // with its system
  app.debug.setState((next) => { next.review.selectedPageIds = [pages[0].id, pages[1].id, pages[2].id]; return next; });
  await root.dispatchAction("apply-review");
  await flush();
  assert.deepEqual(calls[1].keepCaptures, strips);
});

function reflowJob({ revision = 1, suggestions = "done", pairs = [], extraReflow = {} } = {}) {
  const strips = [1, 2, 3, 4].map(n => `/job/reflow/strips/strip_sys-00${n}.png`);
  return {
    job_id: "job-r",
    status: "done",
    progress: 1,
    result: {
      output_model: "clean_reflow_v1",
      reflow_state: "done",
      reflow: { revision, suggestions_state: suggestions, staff_gap_mm: 1.5, ...extraReflow },
      review_candidates: strips,
      auto_excluded_captures: [],
      capture_diagnostics: Object.fromEntries(strips.map((path, i) => [path, { system_id: `sys-00${i + 1}`, t_start: i * 10, recommended_action: "keep", diagnostic_codes: [] }])),
      similar_capture_pairs: pairs,
      images: ["/job/export/images/page_0001.png"],
      preview_images: ["/job/export/preview/preview_0001.jpg"],
      pdf: "/job/export/sheet_export.pdf",
    },
  };
}

function memoryStorage() {
  const values = new Map();
  return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
}

async function openReflowApp({ storage, getJob, reviewExport = async () => ({}) }) {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    storage,
    api: { requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }), getJob, reviewExport },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source.mp4";
    next.exportConfig.jobId = "job-r";
    next.exportConfig.formats = ["pdf"];
    return next;
  });
  await root.dispatchAction("reconnect-job");
  await flush();
  return { app, root };
}

test("an unsaved system order and selection survive a restart onto the same job revision only", async () => {
  const storage = memoryStorage();
  const first = await openReflowApp({ storage, getJob: async () => reflowJob({ revision: 2 }) });
  assert.deepEqual(first.app.debug.getState().review.pages.map(page => page.systemId), ["sys-001", "sys-002", "sys-003", "sys-004"]);
  first.app.debug.setState((next) => { next.review.focusedPageId = "3"; return next; });
  await first.root.dispatchAction("review-move-up");
  await first.root.dispatchAction("review-move-up");
  first.root.dispatchInput({ dataset: { action: "toggle-review-page", pageId: "2" }, checked: false });
  const edited = first.app.debug.getState().review;
  assert.deepEqual(edited.pages.map(page => page.systemId), ["sys-003", "sys-001", "sys-002", "sys-004"]);
  first.app.destroy();

  // restart: the backend still has revision 2 -> the draft order and selection come back
  const second = await openReflowApp({ storage, getJob: async () => reflowJob({ revision: 2 }) });
  const restored = second.app.debug.getState().review;
  assert.deepEqual(restored.pages.map(page => page.systemId), ["sys-003", "sys-001", "sys-002", "sys-004"]);
  assert.deepEqual(restored.pages.filter(page => restored.selectedPageIds.includes(page.id)).map(page => page.systemId), ["sys-003", "sys-001", "sys-004"]);
  assert.equal(restored.status, "idle");
  second.app.destroy();

  // restart onto a newer revision (rebuilt elsewhere): the stale draft is not applied
  const storage3 = memoryStorage();
  const third0 = await openReflowApp({ storage: storage3, getJob: async () => reflowJob({ revision: 2 }) });
  third0.app.debug.setState((next) => { next.review.focusedPageId = "3"; return next; });
  await third0.root.dispatchAction("review-move-up");
  third0.app.destroy();
  const third = await openReflowApp({ storage: storage3, getJob: async () => reflowJob({ revision: 3 }) });
  assert.deepEqual(third.app.debug.getState().review.pages.map(page => page.systemId), ["sys-001", "sys-002", "sys-003", "sys-004"]);
  third.app.destroy();
});

test("after a restart the review screen still calls the PDF saved when the restored draft built it", async () => {
  const savedJob = (selected = [0, 2, 3]) => {
    const job = reflowJob({ revision: 2 });
    const strips = job.result.review_candidates;
    job.result.review_export = { revision: 1, kept_count: selected.length, selection_mode: "captures", selected_captures: selected.map(i => strips[i]), selected_pages: [], system_order: strips };
    return job;
  };
  const stage = root => root.querySelector("#stagePane").innerHTML;
  const storage = memoryStorage();
  // the PDF was just rebuilt from systems 1, 3 and 4
  const first = await openReflowApp({ storage, getJob: async () => savedJob() });
  assert.equal(first.app.debug.getState().review.status, "applied");
  assert.match(stage(first.root), /data-action="open-output-pdf"[^>]*>Open saved PDF/);
  first.app.destroy();

  // restart onto the same revision: the restored draft is the one the PDF was built from
  const second = await openReflowApp({ storage, getJob: async () => savedJob() });
  const restored = second.app.debug.getState().review;
  assert.deepEqual(restored.pages.filter(page => restored.selectedPageIds.includes(page.id)).map(page => page.systemId), ["sys-001", "sys-003", "sys-004"]);
  assert.equal(restored.status, "applied");
  assert.match(stage(second.root), /data-action="open-output-pdf"[^>]*>Open saved PDF/);
  assert.match(stage(second.root), /data-action="save-output-pdf-as" aria-label="Save PDF as…"/);
  assert.doesNotMatch(stage(second.root), /data-action="open-output-pdf"[^>]*>Open PDF</);
  // changing the selection afterwards makes it the previous PDF, as before
  second.root.dispatchInput({ dataset: { action: "toggle-review-page", pageId: "2" }, checked: true });
  await flush();
  assert.equal(second.app.debug.getState().review.status, "idle");
  assert.match(stage(second.root), /data-action="open-output-pdf"[^>]*>Open PDF</);
  second.app.destroy();

  // that edit was not rebuilt before closing: the next restart keeps the previous-PDF labels
  const third = await openReflowApp({ storage, getJob: async () => savedJob() });
  assert.equal(third.app.debug.getState().review.selectedPageIds.length, 4);
  assert.equal(third.app.debug.getState().review.status, "idle");
  assert.match(stage(third.root), /data-action="open-output-pdf"[^>]*>Open PDF</);
  third.app.destroy();

  // marked saved, but the job's saved selection differs from the draft: do not claim a match
  const mismatch = memoryStorage();
  (await openReflowApp({ storage: mismatch, getJob: async () => savedJob() })).app.destroy();
  const fourth = await openReflowApp({ storage: mismatch, getJob: async () => savedJob([0, 1]) });
  assert.equal(fourth.app.debug.getState().review.status, "idle");
  fourth.app.destroy();

  // a session saved before this marker existed cannot tell, so it stays pending
  const legacy = memoryStorage();
  (await openReflowApp({ storage: legacy, getJob: async () => savedJob() })).app.destroy();
  const saved = JSON.parse(legacy.getItem("drum-sheet-session-v1"));
  delete saved.review.applied;
  legacy.setItem("drum-sheet-session-v1", JSON.stringify(saved));
  const fifth = await openReflowApp({ storage: legacy, getJob: async () => savedJob() });
  assert.equal(fifth.app.debug.getState().review.status, "idle");
  fifth.app.destroy();
});

test("looks-similar suggestions that arrive after the job is done do not reset the user's edits", async () => {
  let calls = 0;
  const pair = [{ kept: "/job/reflow/strips/strip_sys-001.png", candidate: "/job/reflow/strips/strip_sys-003.png", reason: "looks_similar", metrics: {} }];
  const timers = [];
  const realSetTimeout = globalThis.setTimeout;
  globalThis.setTimeout = (fn) => { timers.push(fn); return timers.length; };
  try {
    const { app, root } = await openReflowApp({
      storage: null,
      getJob: async () => (++calls === 1 ? reflowJob({ suggestions: "pending" }) : reflowJob({ suggestions: "done", pairs: pair })),
    });
    let review = app.debug.getState().review;
    assert.equal(review.reflow.suggestionsState, "pending");
    assert.equal(review.pages[2].similarTo, null);
    // the user edits while suggestions are computed
    root.dispatchInput({ dataset: { action: "toggle-review-page", pageId: "4" }, checked: false });
    app.debug.setState((next) => { next.review.focusedPageId = "2"; return next; });
    await root.dispatchAction("review-move-up");
    // the follow-up poll merges the suggestion only
    const followUp = timers.shift();
    await followUp();
    await flush();
    review = app.debug.getState().review;
    assert.equal(review.reflow.suggestionsState, "done");
    assert.deepEqual(review.pages.map(page => page.systemId), ["sys-002", "sys-001", "sys-003", "sys-004"]);
    assert.ok(!review.selectedPageIds.includes("4"));
    const third = review.pages.find(page => page.systemId === "sys-003");
    assert.equal(third.similarTo.reason, "looks_similar");
    assert.equal(third.similarTo.referenceId, "1");
    app.destroy();
  } finally {
    globalThis.setTimeout = realSetTimeout;
  }
});

test("a layout conflict on rebuild is shown, and the smaller size is sent only as the user's explicit choice", async () => {
  const calls = [];
  let conflict = true;
  const { app, root } = await openReflowApp({
    storage: null,
    getJob: async () => reflowJob(conflict ? { extraReflow: { layout_conflict: { requested_staff_gap_mm: 1.5, largest_fitting_staff_gap_mm: 1.2, conflicts: [{ system_id: "sys-002" }] } } } : { revision: 2 }),
    reviewExport: async (jobId, payload) => {
      calls.push(payload);
      if (!Number.isFinite(payload.staffGapMm)) throw Object.assign(new Error("LAYOUT_CONFLICT: sys-002 do not fit the page at 1.5 mm"), { status: 409 });
      conflict = false;
      return {};
    },
  });
  await root.dispatchAction("apply-review");
  await flush();
  let review = app.debug.getState().review;
  assert.equal(review.status, "error");
  assert.match(review.error, /does not fit the page/);
  assert.equal(review.reflow.conflict.offeredMm, 1.2);
  assert.equal(calls.length, 1);
  assert.equal("staffGapMm" in calls[0], false);  // never reduced without the user's choice
  await root.dispatchAction("review-use-staff-size", { size: "1.2" });
  await flush();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].staffGapMm, 1.2);
  review = app.debug.getState().review;
  assert.equal(review.reflow.conflict, null);
  app.destroy();
});

test("a section-label area outside the score region is suggested as a draft and sent only after the user applies it", async () => {
  installBrowserStubs();
  const root = createDynamicStageRoot();
  const labelSuggestion = [[10, 2], [120, 2], [120, 18], [10, 18]];
  const labelCalls = [];
  const jobs = [];
  let editorDraft = null;
  const app = createApp(root, {
    exposeTestApi: true,
    mountRoiEditor: ({ initialPoints }) => {
      editorDraft = initialPoints;
      return { applyDraft() { return editorDraft; }, setDraft(points) { editorDraft = points; }, destroy() {} };
    },
    api: {
      requestPreviewFrame: async () => ({ imagePath: "/tmp/preview.png", sourcePath: "/tmp/preview.png", diagnostics: [] }),
      requestPreviewRoiHealth: async () => ({ riskLevel: "info", diagnostics: [], envelope: { status: "found", clipped: false } }),
      requestLabelRegion: async (request) => { labelCalls.push(request); return { status: "suggested", labelRoi: labelSuggestion, evidence: {} }; },
      createJob: async (payload) => { jobs.push(payload); return "job-1"; },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.metadata = { durationSec: 120, width: 320, height: 180 };
    next.ui.activeStep = "roi";
    next.roi.frameTime = 10;
    return next;
  });
  await root.dispatchAction("load-preview-frame");
  await flush();
  app.debug.setState((next) => { next.roi.draftRect = ROI_RECT; return next; });
  await root.dispatchAction("apply-roi");
  await flush();
  let state = app.debug.getState();
  assert.equal(labelCalls.length, 1);
  assert.deepEqual(labelCalls[0].roi, ROI_RECT);
  assert.equal(state.roi.labelCheck.status, "suggested");
  assert.equal(state.roi.labelAppliedRect, null, "a suggestion is never applied by itself");
  assert.equal(state.roi.labelDraftRect, null);

  // the user loads it as an editable draft on the region step
  await root.dispatchAction("use-suggested-label-roi");
  state = app.debug.getState();
  assert.equal(state.ui.activeStep, "roi");
  assert.equal(state.roi.editTarget, "labels");
  assert.deepEqual(state.roi.labelDraftRect, labelSuggestion);
  assert.deepEqual(state.roi.appliedRect, ROI_RECT, "the score region is unchanged");
  // ... edits it and applies it
  editorDraft = [[12, 1], [130, 1], [130, 20], [12, 20]];
  await root.dispatchAction("apply-label-roi");
  state = app.debug.getState();
  assert.deepEqual(state.roi.labelAppliedRect, [[12, 1], [130, 1], [130, 20], [12, 20]]);
  assert.equal(state.roi.editTarget, "score");

  app.debug.setState((next) => { next.ui.activeStep = "export"; next.exportConfig.formats = ["png"]; return next; });
  await root.dispatchAction("run-export");
  await flush();
  assert.deepEqual(jobs[0].options.detect.label_roi, [[12, 1], [130, 1], [130, 20], [12, 20]]);
  assert.deepEqual(jobs[0].options.detect.roi, ROI_RECT);

  // removing it: the next job has no label area
  await root.dispatchAction("remove-label-roi");
  assert.equal(app.debug.getState().roi.labelAppliedRect, null);
  app.destroy();
});

test("the score layout toggle is sent with a new job and with each rebuild, and marks saved files as pending", async () => {
  installBrowserStubs();
  const jobs = [];
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async (payload) => { jobs.push(payload); return "job-1"; },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, current_step: "done", message: "", result: {} }),
      reviewExport: async () => ({}),
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source.mp4";
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = ["png"];
    next.ui.activeStep = "export";
    return next;
  });
  await root.dispatchAction("run-export");
  await flush();
  assert.equal(jobs[0].options.measure_reflow, true, "on by default");
  root.dispatchInput({ dataset: { action: "toggle-measure-reflow" }, checked: false });
  assert.equal(app.debug.getState().exportConfig.measureReflow, false);
  // a format change keeps the layout choice
  root.dispatchInput({ dataset: { action: "toggle-format", format: "jpg" }, checked: true });
  assert.equal(app.debug.getState().exportConfig.measureReflow, false);
  await root.dispatchAction("run-export");
  await flush();
  assert.equal(jobs[1].options.measure_reflow, false);
  app.destroy();

  const calls = [];
  const { app: reviewApp, root: reviewRoot } = await openReflowApp({
    storage: null,
    getJob: async () => reflowJob({ revision: calls.length + 1, extraReflow: {} }),
    reviewExport: async (jobId, payload) => { calls.push(payload); return {}; },
  });
  await reviewRoot.dispatchAction("apply-review");
  await flush();
  assert.equal(calls[0].measureReflow, true);
  reviewApp.debug.setState((next) => { next.review.status = "applied"; return next; });  // files saved
  reviewRoot.dispatchInput({ dataset: { action: "toggle-measure-reflow" }, checked: false });
  assert.equal(reviewApp.debug.getState().review.status, "idle", "files made with the other layout are pending again");
  await reviewRoot.dispatchAction("apply-review");
  await flush();
  assert.equal(calls[1].measureReflow, false);
  // the toggle is ignored while a rebuild runs
  reviewApp.debug.setState((next) => { next.review.status = "running"; return next; });
  const target = { dataset: { action: "toggle-measure-reflow" }, checked: true };
  reviewRoot.dispatchInput(target);
  assert.equal(reviewApp.debug.getState().exportConfig.measureReflow, false);
  assert.equal(target.checked, false);
  reviewApp.destroy();
});

test("a rebuild that fell back to whole systems shows the notice from the job record", async () => {
  const { app } = await openReflowApp({
    storage: null,
    getJob: async () => {
      const job = reflowJob();
      job.result.measure_reflow = { requested: true, applied: false, status: "fallback_whole_systems", reason: "LINE_WIDTH_MISMATCH" };
      return job;
    },
  });
  const info = app.debug.getState().review.reflow;
  assert.equal(info.measureReflow.fellBack, true);
  assert.equal(info.measureReflow.reason, "LINE_WIDTH_MISMATCH");
  app.destroy();
});

// A real jump-view job (2026-10-07): 14 wide strips, measure lines at an automatically reduced
// staff size, an OVERLAY_UNRECOVERED warning written in both languages. Paths are shortened and
// the large page plan is left out.
const JUMP_VIEW_JOB_URL = new URL("./fixtures/jump-view-review-job.json", import.meta.url);

async function loadJumpViewJob() {
  const { readFile } = await import("node:fs/promises");
  return JSON.parse(await readFile(JUMP_VIEW_JOB_URL, "utf8"));
}

async function openJumpViewApp({ locale, getJob, reviewExport, api = {} }) {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    storage: null,
    api: { requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }), getJob, reviewExport, ...api },
  });
  app.debug.setState((next) => {
    next.ui.locale = locale;
    next.source.filePath = "/tmp/source.mp4";
    next.roi.appliedRect = ROI_RECT;
    next.roi.draftRect = ROI_RECT;
    next.exportConfig.jobId = "cd90c1eb-fe4c-4533-8c7b-0a537aab2119";
    next.exportConfig.formats = ["png", "pdf"];
    return next;
  });
  await root.dispatchAction("reconnect-job");
  await flush();
  return { app, root };
}

function failureText(state) {
  return [state.source.error, state.roi.error, state.exportConfig.error, state.review.error].filter(Boolean).join("\n");
}

for (const locale of ["ko", "en"]) {
  test(`the rebuilt jump-view job renders as saved with no failure toast (${locale})`, async () => {
    const job = await loadJumpViewJob();
    const { app, root } = await openJumpViewApp({
      locale,
      getJob: async () => structuredClone(job),
      reviewExport: async () => ({ images: job.result.images, pdf: job.result.pdf, output_dir: job.result.output_dir, kept_count: 14, measure_reflow: job.result.measure_reflow }),
    });
    await root.dispatchAction("apply-review");
    await flush();
    await flush();
    const state = app.debug.getState();
    assert.equal(failureText(state), "");
    assert.equal(state.review.status, "applied");
    assert.equal(state.review.selectedPageIds.length, 14);
    assert.equal(state.review.reflow.autoStaff.usedMm, 1.3);
    const stage = root.querySelector("#stagePane").innerHTML;
    const status = root.querySelector("#statusBar").innerHTML;
    assert.doesNotMatch(stage + status, /\[object Object\]/);
    assert.doesNotMatch(status, new RegExp(t("support.failureTitle", { locale })));
    assert.match(stage, new RegExp(t("review.savedState", { locale })));
    // the playback-mark note on line 1 is shown in the UI language only
    const note = /<p class="review-risk-note">([^<]*)<\/p>/.exec(stage)?.[1] || "";
    assert.equal(note, locale === "ko" ? "재생 표시가 남아 있을 수 있습니다" : "A playback mark may remain");
    app.destroy();
  });
}

test("a rebuild whose answer is lost shows a readable message, never [object Object]", async () => {
  const job = await loadJumpViewJob();
  for (const [thrown, expected] of [
    [{}, t("error.unknown", { locale: "ko" })],
    [new Error("REQUEST_TIMEOUT: POST /jobs/x/review-export did not answer within 30 s"), t("error.requestTimeout", { locale: "ko" })],
    [Object.assign(new Error("review export failed: 디스크가 가득 찼습니다 / The disk is full"), { status: 500 }), "review export failed: 디스크가 가득 찼습니다"],
  ]) {
    const { app, root } = await openJumpViewApp({
      locale: "ko",
      getJob: async () => structuredClone(job),
      reviewExport: async () => { throw thrown; },
    });
    await root.dispatchAction("apply-review");
    await flush();
    await flush();
    const state = app.debug.getState();
    assert.equal(state.review.status, "error");
    assert.equal(state.review.error, expected);
    assert.doesNotMatch(root.querySelector("#stagePane").innerHTML + root.querySelector("#statusBar").innerHTML, /\[object Object\]/);
    app.destroy();
  }
});

test("a rebuild that timed out on the way but finished on the backend is shown as applied", async () => {
  const job = await loadJumpViewJob();
  const before = structuredClone(job);
  before.result.reflow.revision = 1;
  delete before.result.review_export;
  let finished = false;
  const { app, root } = await openJumpViewApp({
    locale: "ko",
    getJob: async () => structuredClone(finished ? job : before),
    reviewExport: async () => { finished = true; throw new Error("REQUEST_TIMEOUT: POST /jobs/x/review-export did not answer within 30 s"); },
  });
  assert.equal(app.debug.getState().review.jobRevision, 1);
  await root.dispatchAction("apply-review");
  await flush();
  await flush();
  const state = app.debug.getState();
  assert.equal(failureText(state), "");
  assert.equal(state.review.status, "applied");
  assert.equal(state.review.jobRevision, 2);
  assert.equal(state.ui.inlineNotice, t("notice.review.applied", { locale: "ko" }));
  app.destroy();
});

function exportTask(fields = {}) {
  return { taskId: "t1", jobId: "cd90c1eb-fe4c-4533-8c7b-0a537aab2119", revision: 3, state: "running", stage: "planning",
    progress: 0, cancelRequested: false, result: null, errorCode: "", error: "", errorStatus: null, ...fields };
}

for (const locale of ["ko", "en"]) {
  test(`a background rebuild shows its stage and progress and can be cancelled, keeping the previous files (${locale})`, async () => {
    const job = await loadJumpViewJob();
    const outcome = deferred();
    const cancels = [];
    let report = null;
    const { app, root } = await openJumpViewApp({
      locale,
      getJob: async () => structuredClone(job),
      reviewExport: async (jobId, body, { onTask }) => {
        report = onTask;
        onTask(exportTask({ state: "queued", stage: "queued" }));
        return outcome.promise;
      },
      api: { cancelReviewExport: async (jobId, taskId) => { cancels.push([jobId, taskId]); return exportTask({ cancelRequested: true }); } },
    });
    assert.equal(app.debug.getState().review.status, "applied");
    const pending = root.dispatchAction("apply-review");
    await flush();
    report(exportTask({ stage: "sizing", progress: 0.42 }));
    let stage = root.querySelector("#stagePane").innerHTML;
    assert.equal(app.debug.getState().review.status, "running");
    assert.match(stage, /role="progressbar"[^>]*aria-valuenow="42"/);
    assert.match(stage, new RegExp(`${t("review.rebuildStage.sizing", { locale })} · 42%`));
    assert.match(stage, /data-action="cancel-review-export"[^>]*>/);
    assert.doesNotMatch(stage, /data-action="cancel-review-export"[^>]*aria-disabled/);
    assert.doesNotMatch(stage, /data-action="apply-review"/);  // the rebuild button gives way to the progress
    await root.dispatchAction("cancel-review-export");
    assert.deepEqual(cancels, [["cd90c1eb-fe4c-4533-8c7b-0a537aab2119", "t1"]]);
    stage = root.querySelector("#stagePane").innerHTML;
    assert.match(stage, new RegExp(`${t("review.rebuildStage.cancelling", { locale })} · 42%`));
    assert.match(stage, /data-action="cancel-review-export"[^>]*aria-disabled="true"/);
    await root.dispatchAction("cancel-review-export");  // a second click sends nothing
    assert.equal(cancels.length, 1);
    outcome.reject(Object.assign(new Error("EXPORT_CANCELLED: the rebuild was cancelled"), { code: "EXPORT_CANCELLED", cancelled: true }));
    await pending;
    const state = app.debug.getState();
    assert.equal(state.review.status, "applied");
    assert.equal(state.review.exportTask, null);
    assert.equal(failureText(state), "");
    assert.equal(state.ui.inlineNotice, t("review.rebuildCancelled", { locale }));
    stage = root.querySelector("#stagePane").innerHTML;
    assert.doesNotMatch(stage, /role="progressbar"/);
    assert.match(stage, /data-action="apply-review"/);
    app.destroy();
  });
}

test("Cancel pressed before the backend named the task is sent once the task is known", async () => {
  const job = await loadJumpViewJob();
  const outcome = deferred();
  const cancels = [];
  let report = null;
  const { app, root } = await openJumpViewApp({
    locale: "en",
    getJob: async () => structuredClone(job),
    reviewExport: async (jobId, body, { onTask }) => { report = onTask; return outcome.promise; },
    api: { cancelReviewExport: async (jobId, taskId) => { cancels.push(taskId); return exportTask({ cancelRequested: true }); } },
  });
  const pending = root.dispatchAction("apply-review");
  await flush();
  await root.dispatchAction("cancel-review-export");
  assert.deepEqual(cancels, []);
  assert.equal(app.debug.getState().review.exportTask.cancelRequested, true);
  report(exportTask({ state: "queued", stage: "queued" }));
  await flush();
  assert.deepEqual(cancels, ["t1"]);
  report(exportTask({ stage: "planning", progress: 0.05 }));
  await flush();
  assert.deepEqual(cancels, ["t1"]);
  outcome.reject(Object.assign(new Error("EXPORT_CANCELLED"), { code: "EXPORT_CANCELLED", cancelled: true }));
  await pending;
  assert.equal(app.debug.getState().ui.inlineNotice, t("review.rebuildCancelled", { locale: "en" }));
  app.destroy();
});

test("a failed background rebuild shows the backend's reason in the UI language", async () => {
  const job = await loadJumpViewJob();
  for (const [thrown, expected] of [
    [Object.assign(new Error("EXPORT_INTERRUPTED: 처리기가 다시 시작되어 ... / The processor restarted"), { status: 500, code: "EXPORT_INTERRUPTED" }), t("review.exportInterrupted", { locale: "en" })],
    [Object.assign(new Error("UNCUT_STRIP_UNAVAILABLE: ... / ..."), { status: 409, code: "UNCUT_STRIP_UNAVAILABLE" }), t("review.uncutStripUnavailable", { locale: "en" })],
    [Object.assign(new Error("review export failed: 디스크가 가득 찼습니다 / The disk is full"), { status: 500, code: "EXPORT_FAILED" }), "The disk is full"],
  ]) {
    const { app, root } = await openJumpViewApp({
      locale: "en",
      getJob: async () => structuredClone(job),
      reviewExport: async (jobId, body, { onTask }) => { onTask(exportTask({ stage: "rendering", progress: 0.7 })); throw thrown; },
    });
    await root.dispatchAction("apply-review");
    await flush();
    const state = app.debug.getState();
    assert.equal(state.review.status, "error");
    assert.equal(state.review.error, expected);
    assert.equal(state.review.exportTask, null);
    assert.doesNotMatch(root.querySelector("#stagePane").innerHTML, /role="progressbar"/);
    app.destroy();
  }
});

test("after a reload, a rebuild still running on the backend is followed to its result", async () => {
  const job = await loadJumpViewJob();
  const before = structuredClone(job);
  before.result.reflow.revision = 1;
  let finished = false;
  const outcome = deferred();
  let report = null;
  const { app, root } = await openJumpViewApp({
    locale: "ko",
    getJob: async () => structuredClone(finished ? job : before),
    reviewExport: async () => { throw new Error("not started from this window"); },
    api: {
      getReviewExportTask: async () => exportTask({ stage: "writing", progress: 0.85 }),
      waitForReviewExport: async (jobId, task, { onTask }) => { report = onTask; return outcome.promise; },
    },
  });
  await flush();
  await flush();
  let state = app.debug.getState();
  assert.equal(state.review.status, "running");
  assert.equal(state.review.exportTask.taskId, "t1");
  let stage = root.querySelector("#stagePane").innerHTML;
  assert.match(stage, new RegExp(`${t("review.rebuildStage.writing", { locale: "ko" })} · 85%`));
  report(exportTask({ stage: "writing", progress: 0.97 }));
  assert.match(root.querySelector("#stagePane").innerHTML, /aria-valuenow="97"/);
  finished = true;
  outcome.resolve({ kept_count: 14, revision: 2 });
  await flush(); await flush(); await flush();
  state = app.debug.getState();
  assert.equal(state.review.status, "applied");
  assert.equal(state.review.jobRevision, 2);
  assert.equal(state.review.exportTask, null);
  assert.equal(state.ui.inlineNotice, t("notice.review.applied", { locale: "ko" }));
  app.destroy();

  // nothing running (or an older backend without tasks): the screen opens as saved
  const idle = await openJumpViewApp({
    locale: "ko",
    getJob: async () => structuredClone(job),
    api: { getReviewExportTask: async () => null, waitForReviewExport: async () => { throw new Error("must not wait"); } },
  });
  await flush();
  assert.equal(idle.app.debug.getState().review.status, "applied");
  idle.app.destroy();
});

test("a rebuild refused because one is already running follows the running one", async () => {
  const job = await loadJumpViewJob();
  const outcome = deferred();
  let lookups = 0;
  const { app, root } = await openJumpViewApp({
    locale: "en",
    getJob: async () => structuredClone(job),
    reviewExport: async () => { throw Object.assign(new Error("EXPORT_IN_PROGRESS: ... / This score's PDF is already being rebuilt. [task t9]"), { status: 409, code: "EXPORT_IN_PROGRESS" }); },
    api: {
      // nothing ran when the screen opened; another window's rebuild runs when this one asks
      getReviewExportTask: async () => (++lookups === 1 ? null : exportTask({ taskId: "t9", stage: "sizing", progress: 0.4 })),
      waitForReviewExport: async () => outcome.promise,
    },
  });
  await flush();
  assert.equal(app.debug.getState().review.status, "applied");
  await root.dispatchAction("apply-review");
  await flush();
  let state = app.debug.getState();
  assert.equal(state.ui.inlineNotice, t("review.exportInProgress", { locale: "en" }));
  assert.equal(state.review.status, "running");
  assert.equal(state.review.exportTask.taskId, "t9");
  assert.equal(failureText(state), "");
  assert.match(root.querySelector("#stagePane").innerHTML, /aria-valuenow="40"/);
  outcome.resolve({ kept_count: 14 });
  await flush(); await flush(); await flush();
  state = app.debug.getState();
  assert.equal(state.review.status, "applied");
  assert.equal(state.review.exportTask, null);
  app.destroy();
});

// STRATEGY Step 2A job outcomes: a pending layout conflict, an export that may not be published,
// a refused composited source, and an incomplete chart.
function conflictJob() {
  const job = reflowJob();
  job.status = "error";
  job.error_code = "LAYOUT_CONFLICT";
  job.message = "LAYOUT_CONFLICT: sys-002 do not fit the page at 1.5 mm; largest staff size that fits: 1.10 mm";
  Object.assign(job.result, {
    reflow_state: "layout_conflict", images: [], pdf: null, preview_images: [],
    measure_reflow: { requested: true, applied: false, status: "fallback_whole_systems", reason: "NO_FEASIBLE_LINE_BREAKS" },
  });
  job.result.reflow.layout_conflict = { requested_staff_gap_mm: 1.5, largest_fitting_staff_gap_mm: 1.1, conflicts: [{ system_id: "sys-002", kind: "too_wide" }] };
  job.result.reflow.page_plan = { staff_size: { staff_gap_mm: 1.5, staff_gap_mm_requested: 1.5, auto_reduced: false, reason: "BELOW_AUTO_MINIMUM", largest_fitting_staff_gap_mm: 1.1, auto_min_staff_gap_mm: 1.2 } };
  return job;
}

for (const locale of ["ko", "en"]) {
  test(`a job stopped at a layout conflict opens review, explains it, and can be resolved there (${locale})`, async () => {
    const calls = [];
    let resolved = false;
    installBrowserStubs();
    const root = createRoot();
    const app = createApp(root, {
      exposeTestApi: true,
      storage: null,
      api: {
        requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
        getJob: async () => (resolved ? reflowJob({ revision: 2 }) : conflictJob()),
        reviewExport: async (jobId, payload) => { calls.push(payload); resolved = true; return {}; },
      },
    });
    app.debug.setState((next) => {
      next.ui.locale = locale;
      next.source.filePath = "/tmp/source.mp4";
      next.exportConfig.jobId = "job-r";
      next.exportConfig.formats = ["pdf"];
      return next;
    });
    await root.dispatchAction("reconnect-job");
    await flush();
    let state = app.debug.getState();
    assert.equal(state.exportConfig.runStatus, "error");
    assert.equal(state.exportConfig.errorCode, "LAYOUT_CONFLICT");
    assert.equal(state.exportConfig.error, t("export.failedLayoutConflict", { locale }));
    assert.equal(state.ui.activeStep, "review");
    assert.equal(getStepState(state, "review").enabled, true);
    assert.equal(getStepState(state, "review").complete, false);
    assert.equal(state.review.reflow.conflictPending, true);
    assert.equal(state.review.reflow.conflict.sizeReason, "BELOW_AUTO_MINIMUM");
    const stage = root.querySelector("#stagePane").innerHTML;
    assert.ok(stage.includes(t("review.conflictPendingTitle", { locale })));
    assert.ok(stage.includes(t("review.conflictBelowAuto", { locale, replacements: { size: "1.1", min: "1.2" } })));
    assert.ok(stage.includes(t("review.useSmallerStaff", { locale, replacements: { size: "1.1" } })));
    // the rebuild button is usable (review export resolves the conflict)
    assert.doesNotMatch(stage.match(/<button[^>]*data-action="apply-review"[^>]*>/)[0], /disabled/);
    await root.dispatchAction("review-use-staff-size", { size: "1.1" });
    await flush();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].staffGapMm, 1.1);
    state = app.debug.getState();
    assert.equal(state.exportConfig.runStatus, "done");
    assert.equal(state.exportConfig.errorCode, "");
    assert.equal(state.review.reflow.conflict, null);
    app.destroy();
  });
}

function ledgerFailedJob() {
  const job = reflowJob();
  job.status = "error";
  job.error_code = "LEDGER_VERIFICATION_FAILED";
  job.message = "LEDGER_VERIFICATION_FAILED: preservation failed";
  Object.assign(job.result, {
    reflow_state: "ledger_failed", review_required: true,
    review_reasons: [{ code: "LEDGER_VERIFICATION_FAILED", text: "보존 검증 실패 / Preservation failed" }],
    images: [], pdf: null, preview_images: [],
  });
  job.result.reflow.review_reasons = ["LEDGER_VERIFICATION_FAILED"];
  return job;
}

for (const locale of ["ko", "en"]) {
  test(`a ledger failure opens review and permits a rebuild without claiming completion (${locale})`, async () => {
    let resolved = false;
    let rebuilds = 0;
    const { app, root } = await openReflowApp({
      storage: null,
      getJob: async () => resolved ? reflowJob({ revision: 2 }) : ledgerFailedJob(),
      reviewExport: async () => { rebuilds += 1; resolved = true; return {}; },
    });
    app.debug.setState((next) => { next.ui.locale = locale; return next; });
    await root.dispatchAction("reconnect-job");
    await flush();
    const state = app.debug.getState();
    assert.equal(state.ui.activeStep, "review");
    assert.equal(state.exportConfig.runStatus, "error");
    assert.equal(state.exportConfig.error, t("export.failedLedgerVerification", { locale }));
    assert.equal(getStepState(state, "review").enabled, true);
    assert.equal(getStepState(state, "review").complete, false);
    assert.equal(state.review.reflow.state, "ledger_failed");
    assert.equal(state.review.reflow.reviewReasons.length, 1);
    const stage = root.querySelector("#stagePane").innerHTML;
    assert.ok(stage.includes(t("reflow.issue.LEDGER_VERIFICATION_FAILED", { locale })));
    assert.match(stage, /aria-label="[^"]+" tabindex="0"/);
    assert.doesNotMatch(stage.match(/<button[^>]*data-action="apply-review"[^>]*>/)[0], /disabled/);
    await root.dispatchAction("apply-review");
    await flush();
    assert.equal(rebuilds, 1);
    assert.equal(app.debug.getState().exportConfig.runStatus, "done");
    assert.equal(app.debug.getState().exportConfig.errorCode, "");
    app.destroy();
  });

  test(`a failed review rebuild localizes the ledger error and preserves the draft (${locale})`, async () => {
    let failed = false;
    const { app, root } = await openReflowApp({
      storage: null,
      getJob: async () => failed ? ledgerFailedJob() : reflowJob(),
      reviewExport: async () => {
        failed = true;
        throw Object.assign(new Error("LEDGER_VERIFICATION_FAILED: preservation failed"), { status: 500, code: "LEDGER_VERIFICATION_FAILED" });
      },
    });
    app.debug.setState((next) => { next.ui.locale = locale; next.review.focusedPageId = "3"; return next; });
    await root.dispatchAction("review-move-up");
    root.dispatchInput({ dataset: { action: "toggle-review-page", pageId: "2" }, checked: false });
    const before = app.debug.getState().review;
    await root.dispatchAction("apply-review");
    await flush();
    const after = app.debug.getState().review;
    assert.equal(after.status, "error");
    assert.equal(after.error, t("review.ledgerVerificationFailed", { locale }));
    assert.deepEqual(after.pages.map(page => page.systemId), before.pages.map(page => page.systemId));
    assert.deepEqual(after.selectedPageIds, before.selectedPageIds);
    assert.equal(after.pdfPath, before.pdfPath);
    assert.equal(after.reflow.state, "ledger_failed");
    app.destroy();
  });
}

test("reconnecting a ledger failure resumes a running review rebuild", async () => {
  installBrowserStubs();
  const root = createRoot();
  const outcome = deferred();
  let finished = false;
  let waits = 0;
  const app = createApp(root, {
    exposeTestApi: true, storage: null,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      getJob: async () => {
        if (!finished) return ledgerFailedJob();
        const job = reflowJob({ revision: 2 });
        job.result.review_export = { kept_count: 4, revision: 2 };
        return job;
      },
      getReviewExportTask: async () => exportTask({ stage: "writing", progress: 0.85 }),
      waitForReviewExport: async () => { waits += 1; return outcome.promise; },
    },
  });
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source.mp4";
    next.exportConfig.jobId = "job-r";
    next.exportConfig.formats = ["pdf"];
    return next;
  });
  await root.dispatchAction("reconnect-job");
  await flush(); await flush();
  assert.equal(waits, 1);
  assert.equal(app.debug.getState().ui.activeStep, "review");
  assert.equal(app.debug.getState().review.status, "running");
  assert.equal(app.debug.getState().review.exportTask.taskId, "t1");
  finished = true;
  outcome.resolve({ kept_count: 4, revision: 2 });
  await flush(); await flush(); await flush();
  assert.equal(app.debug.getState().exportConfig.runStatus, "done");
  assert.equal(app.debug.getState().review.status, "applied");
  assert.equal(app.debug.getState().review.exportTask, null);
  app.destroy();
});

test("an unrelated job error does not open review", async () => {
  const job = conflictJob();
  job.error_code = "PDF_UNREADABLE";
  job.result.reflow_state = "export_invalid";
  const { app } = await openReflowApp({ storage: null, getJob: async () => structuredClone(job) });
  const state = app.debug.getState();
  assert.notEqual(state.ui.activeStep, "review");
  assert.equal(getStepState(state, "review").enabled, false);
  app.destroy();
});

for (const code of ["INVALID_PLACEMENT_PLAN", "EMPTY_EXPORT", "PAGE_COUNT_MISMATCH", "PDF_UNREADABLE"]) {
  test(`an export that may not be published (${code}) gets its own message, for the job and for a rebuild`, async () => {
    const job = reflowJob();
    job.status = "error";
    job.error_code = code;
    job.message = `${code}: detail`;
    Object.assign(job.result, { reflow_state: "export_invalid", images: [], pdf: null, preview_images: [] });
    const failed = await openReflowApp({ storage: null, getJob: async () => structuredClone(job) });
    for (const locale of ["ko", "en"]) {
      failed.app.debug.setState((next) => { next.ui.locale = locale; return next; });
      await failed.root.dispatchAction("reconnect-job");
      await flush();
      const expected = t("export.failedExportInvalid", { locale, replacements: { reason: t(`export.invalid.${code}`, { locale }) } });
      assert.equal(failed.app.debug.getState().exportConfig.error, expected);
      assert.notEqual(expected, t("export.failed", { locale }));
    }
    failed.app.destroy();

    // a background review export that fails verification keeps the previous files and says why
    const rebuild = await openReflowApp({
      storage: null,
      getJob: async () => reflowJob(),
      reviewExport: async () => { throw Object.assign(new Error(`${code}: detail`), { status: 500, code }); },
    });
    await rebuild.root.dispatchAction("apply-review");
    await flush();
    const review = rebuild.app.debug.getState().review;
    assert.equal(review.status, "error");
    assert.equal(review.error, t("review.exportInvalid", { locale: "en", replacements: { reason: t(`export.invalid.${code}`, { locale: "en" }) } }));
    rebuild.app.destroy();
  });
}

test("notation drawn over live video is explained, not reported as a generic failure", async () => {
  const job = reflowJob();
  job.status = "error";
  job.error_code = "UNSUPPORTED_SOURCE";
  job.message = "UNSUPPORTED_SOURCE: notation composited over live video";
  Object.assign(job.result, { reflow_state: "unsupported_source", source_class: { class: "composited_live" }, images: [], pdf: null, review_candidates: [] });
  const { app, root } = await openReflowApp({ storage: null, getJob: async () => structuredClone(job) });
  for (const locale of ["ko", "en"]) {
    app.debug.setState((next) => { next.ui.locale = locale; return next; });
    await root.dispatchAction("reconnect-job");
    await flush();
    const state = app.debug.getState();
    assert.equal(state.exportConfig.error, t("export.failedUnsupportedSource", { locale }));
    assert.notEqual(state.ui.activeStep, "review");
  }
  app.destroy();
});

test("an incomplete chart opens review labelled incomplete with its unresolved time ranges", async () => {
  const job = reflowJob();
  job.result.reflow_state = "incomplete";
  job.result.coverage = { status: "incomplete", unresolved: [[61.2, 75.8], [130, 142.5]], intervals: [] };
  for (const locale of ["ko", "en"]) {
    const { app, root } = await openReflowApp({ storage: null, getJob: async () => structuredClone(job) });
    app.debug.setState((next) => { next.ui.locale = locale; return next; });
    const state = app.debug.getState();
    assert.equal(state.ui.activeStep, "review");
    assert.equal(state.review.reflow.incomplete, true);
    assert.deepEqual(state.review.reflow.unresolvedRanges.map(range => range.label), ["1:01–1:16", "2:10–2:23"]);
    const stage = root.querySelector("#stagePane").innerHTML;
    assert.ok(stage.includes(t("review.incompleteTitle", { locale })));
    assert.ok(stage.includes("<li>1:01–1:16</li>") && stage.includes("<li>2:10–2:23</li>"));
    assert.ok(stage.includes(t("review.incompleteState", { locale })));
    assert.doesNotMatch(stage, /review-save-state is-saved/);
    app.destroy();
  }
});

test("the review opens on the A4 pages; picking a system shows it, and folded reasons open and close", async () => {
  const job = reflowJob({ revision: 1 });
  job.result.review_required = true;
  job.result.review_reasons = ["SOURCE_CLIPPED", "UNCERTAIN_MARK_KEPT"];
  const { app, root } = await openReflowApp({ storage: memoryStorage(), getJob: async () => job });
  const stage = () => root.querySelector("#stagePane").innerHTML;
  const state = () => app.debug.getState();
  assert.equal(state().review.outputPages.length, 1);
  assert.match(stage(), /review-viewer-surface is-pages/);
  assert.match(stage(), /data-value="reviewReasons" aria-expanded="false"/);
  await root.dispatchAction("toggle-more", { value: "reviewReasons" });
  await flush();
  assert.equal(state().ui.more.reviewReasons, true);
  assert.match(stage(), /data-value="reviewReasons" aria-expanded="true"/);
  await root.dispatchAction("toggle-more", { value: "reviewReasons" });
  await flush();
  assert.equal(state().ui.more.reviewReasons, false);
  const second = state().review.pages[1].id;
  await root.dispatchAction("focus-review-page", { pageId: second });
  await flush();
  assert.equal(state().review.focusedPageId, second);
  assert.equal(state().review.pagePreview, false);
  assert.doesNotMatch(stage(), /review-viewer-surface is-pages/);
  app.destroy();
});
