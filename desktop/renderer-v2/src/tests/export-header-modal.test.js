import test from "node:test";
import assert from "node:assert/strict";

import { createApp } from "../app/App.js";

const ROI_RECT = [
  [0, 0],
  [320, 0],
  [320, 180],
  [0, 180],
];

function createRoot() {
  const listeners = {
    click: [],
    input: [],
  };
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
      listeners[type]?.push(handler);
    },
    removeEventListener(type, handler) {
      const bucket = listeners[type];
      if (!bucket) {
        return;
      }
      const index = bucket.indexOf(handler);
      if (index >= 0) {
        bucket.splice(index, 1);
      }
    },
    async dispatchAction(action, dataset = {}) {
      const target = {
        closest(selector) {
          if (selector !== "[data-action]") {
            return null;
          }
          return { dataset: { action, ...dataset } };
        },
      };
      for (const handler of listeners.click) {
        await handler({ target });
      }
    },
    dispatchInput(target) {
      for (const handler of listeners.input) {
        handler({ target });
      }
    },
  };
}

function installBrowserStubs(api = {}) {
  const drumSheetAPI = {
    selectVideoFile: async () => "",
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

function seedExportState(app, formats = ["pdf"]) {
  app.debug.setState((next) => {
    next.source.filePath = "/tmp/source-a.mp4";
    next.source.displayName = "source-a.mp4";
    next.roi.frameTime = 5;
    next.roi.appliedRect = ROI_RECT;
    next.exportConfig.formats = formats.slice();
    next.ui.activeStep = "export";
    return next;
  });
}

test("png-only export bypasses metadata modal and creates a job immediately", async () => {
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

  seedExportState(app, ["png"]);

  await root.dispatchAction("run-export");
  await flush();

  const state = app.debug.getState();
  assert.equal(createJobCalls, 1);
  assert.equal(state.exportConfig.metadataModal.isOpen, false);
});

test("dirty metadata close requires explicit discard confirmation", async () => {
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

  seedExportState(app);
  app.debug.setState((next) => {
    next.exportConfig.metadataModal = {
      isOpen: true,
      draft: {
        title: "Blue in Green",
        performer: "",
        bpm: "",
        date: "2026-04-19",
        memo: "",
      },
      dirty: true,
      validation: { title: "", bpm: "" },
      showDiscardConfirm: false,
    };
    return next;
  });

  await root.dispatchAction("close-export-metadata");
  await flush();

  const state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.equal(state.exportConfig.metadataModal.showDiscardConfirm, true);
});

test("metadata input strips non-digit bpm values at the interaction layer", () => {
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

  seedExportState(app);
  app.debug.setState((next) => {
    next.exportConfig.metadataModal = {
      isOpen: true,
      draft: {
        title: "Blue in Green",
        performer: "",
        bpm: "",
        date: "2026-04-19",
        memo: "",
      },
      dirty: false,
      validation: { title: "", bpm: "" },
      showDiscardConfirm: false,
    };
    return next;
  });

  root.dispatchInput({
    dataset: { action: "update-export-metadata", field: "bpm" },
    value: "12a8",
  });

  const state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.draft.bpm, "128");
  assert.equal(state.exportConfig.metadataModal.dirty, true);
});

test("confirm-export-metadata blocks blank titles before job creation", async () => {
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

  seedExportState(app);
  app.debug.setState((next) => {
    next.exportConfig.metadataModal = {
      isOpen: true,
      draft: {
        title: "   ",
        performer: "",
        bpm: "128",
        date: "2026-04-19",
        memo: "",
      },
      dirty: true,
      validation: { title: "", bpm: "" },
      showDiscardConfirm: false,
    };
    return next;
  });

  await root.dispatchAction("confirm-export-metadata");
  await flush();

  const state = app.debug.getState();
  assert.equal(createJobCalls, 0);
  assert.match(state.exportConfig.metadataModal.validation.title, /제목|title/i);
});

test("confirm-export-metadata normalizes the draft into payload-safe document header values", async () => {
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
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  seedExportState(app);
  app.debug.setState((next) => {
    next.exportConfig.metadataModal = {
      isOpen: true,
      draft: {
        title: "  Blue in Green  ",
        performer: "  Bill Evans Trio  ",
        bpm: "128",
        date: "",
        memo: "   half-time feel  ",
      },
      dirty: true,
      validation: { title: "", bpm: "" },
      showDiscardConfirm: false,
    };
    return next;
  });

  await root.dispatchAction("confirm-export-metadata");
  await flush();

  assert.deepEqual(seenPayload.options.export.document_header, {
    title: "Blue in Green",
    performer: "Bill Evans Trio",
    bpm: 128,
    date: "",
    memo: "half-time feel",
  });
  assert.deepEqual(app.debug.getState().exportConfig.documentHeader, {
    title: "Blue in Green",
    performer: "Bill Evans Trio",
    bpm: 128,
    date: "",
    memo: "half-time feel",
  });
});
