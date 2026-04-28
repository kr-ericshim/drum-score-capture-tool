import test from "node:test";
import assert from "node:assert/strict";

import { createApp } from "../app/App.js";
import { createInitialSessionState } from "../app/session/selectors.js";
import { renderExportScreen } from "../features/export/ExportScreen.js";

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
    compositionend: [],
    change: [],
    keydown: [],
  };
  const documentStub = {
    activeElement: null,
    documentElement: { lang: "en" },
    querySelector() {
      return null;
    },
  };
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: documentStub,
  });
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
  let dynamicStageNodes = {};

  function createFocusableStageNode(dataset = {}, value = "") {
    return {
      dataset,
      value,
      selectionStart: value.length,
      selectionEnd: value.length,
      focus() {
        documentStub.activeElement = this;
      },
      setSelectionRange(start, end) {
        this.selectionStart = start;
        this.selectionEnd = end;
      },
    };
  }

  function rebuildStageNodes(markup) {
    const previousDynamicNodes = new Set(Object.values(dynamicStageNodes));
    if (previousDynamicNodes.has(documentStub.activeElement)) {
      documentStub.activeElement = null;
    }
    dynamicStageNodes = {};
    if (markup.includes("data-screen-heading")) {
      dynamicStageNodes["[data-screen-heading]"] = createFocusableStageNode();
    }
    const buttonRegex = /<button\b[\s\S]*?data-action="([^"]+)"[\s\S]*?>([\s\S]*?)<\/button>/g;
    for (const match of markup.matchAll(buttonRegex)) {
      const [, action] = match;
      const selector = `[data-action="${action}"]`;
      dynamicStageNodes[selector] = createFocusableStageNode({ action });
    }
    const inputRegex = /<input\b[\s\S]*?data-action="update-export-metadata"[\s\S]*?data-field="([^"]+)"[\s\S]*?value="([^"]*)"[\s\S]*?\/>/g;
    for (const match of markup.matchAll(inputRegex)) {
      const [, field, value] = match;
      const selector = `[data-action="update-export-metadata"][data-field="${field}"]`;
      dynamicStageNodes[selector] = createFocusableStageNode(
        { action: "update-export-metadata", field },
        value,
      );
    }
    const textareaRegex = /<textarea\b[\s\S]*?data-action="update-export-metadata"[\s\S]*?data-field="([^"]+)"[\s\S]*?>([\s\S]*?)<\/textarea>/g;
    for (const match of markup.matchAll(textareaRegex)) {
      const [, field, value] = match;
      const selector = `[data-action="update-export-metadata"][data-field="${field}"]`;
      dynamicStageNodes[selector] = createFocusableStageNode(
        { action: "update-export-metadata", field },
        value,
      );
    }
  }

  const stagePane = {
    _innerHTML: "",
    set innerHTML(value) {
      this._innerHTML = value;
      rebuildStageNodes(value);
    },
    get innerHTML() {
      return this._innerHTML;
    },
    querySelector(selector) {
      return stageNodes[selector] || dynamicStageNodes[selector] || null;
    },
    setAttribute() {},
    focus() {
      documentStub.activeElement = this;
    },
  };

  const nodes = {
    "#topBar": { innerHTML: "" },
    "#processRail": { innerHTML: "" },
    "#stagePane": stagePane,
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
    dispatchInput(target, eventInit = {}) {
      for (const handler of listeners.input) {
        handler({ target, ...eventInit });
      }
    },
    dispatchCompositionEnd(target, eventInit = {}) {
      for (const handler of listeners.compositionend) {
        handler({ target, ...eventInit });
      }
    },
    dispatchChange(target, eventInit = {}) {
      for (const handler of listeners.change) {
        handler({ target, ...eventInit });
      }
    },
    dispatchKeyDown(eventInit = {}) {
      for (const handler of listeners.keydown) {
        handler({ preventDefault() {}, ...eventInit });
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

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
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

test("escape on a dirty metadata modal opens the discard confirmation instead of silently closing", async () => {
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

  root.dispatchKeyDown({ key: "Escape" });
  await flush();

  const state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.equal(state.exportConfig.metadataModal.showDiscardConfirm, true);
});

test("closing the metadata modal during Korean composition preserves the live draft and opens discard confirmation", async () => {
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
  await root.dispatchAction("run-export");
  await flush();

  app.debug.setState((next) => {
    next.exportConfig.documentHeader.title = "";
    next.exportConfig.metadataModal.draft.title = "";
    next.exportConfig.metadataModal.dirty = false;
    return next;
  });

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);
  titleInput.value = "노래";

  root.dispatchInput(titleInput, { isComposing: true });
  await flush();

  await root.dispatchAction("close-export-metadata");
  await flush();

  const state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.equal(state.exportConfig.metadataModal.showDiscardConfirm, true);
  assert.equal(state.exportConfig.metadataModal.draft.title, "노래");
});

test("run-export is ignored while the metadata modal is already open", async () => {
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
        title: "Unreleased Draft",
        performer: "Tester",
        bpm: "128",
        date: "2026-04-19",
        memo: "keep me",
      },
      dirty: true,
      validation: { title: "", bpm: "" },
      showDiscardConfirm: false,
    };
    return next;
  });

  await root.dispatchAction("run-export");
  await flush();

  assert.deepEqual(app.debug.getState().exportConfig.metadataModal.draft, {
    title: "Unreleased Draft",
    performer: "Tester",
    bpm: "128",
    date: "2026-04-19",
    memo: "keep me",
  });
});

test("open-step is ignored while the metadata modal is open", async () => {
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
        title: "Keep Modal State",
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

  await root.dispatchAction("open-step", { step: "roi" });
  await flush();

  const state = app.debug.getState();
  assert.equal(state.ui.activeStep, "export");
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.equal(state.exportConfig.metadataModal.draft.title, "Keep Modal State");
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

  const bpmInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="bpm"]');
  assert.ok(bpmInput);
  bpmInput.value = "12a8";

  root.dispatchInput(bpmInput);

  let state = app.debug.getState();
  assert.equal(bpmInput.value, "128");
  assert.equal(state.exportConfig.metadataModal.draft.bpm, "");
  assert.equal(state.exportConfig.metadataModal.dirty, false);

  root.dispatchChange(bpmInput);

  state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.draft.bpm, "128");
  assert.equal(state.exportConfig.metadataModal.dirty, true);
});

test("metadata typing preserves focus on the same field after rerender", async () => {
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
  await root.dispatchAction("run-export");
  await flush();

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);
  titleInput.focus();
  titleInput.value = "A";
  titleInput.setSelectionRange(1, 1);

  root.dispatchInput(titleInput);
  await flush();

  const activeElement = globalThis.document?.activeElement;
  assert.ok(activeElement, "expected focus to stay within the metadata modal");
  assert.equal(activeElement.dataset?.field, "title");
  assert.equal(activeElement.value, "A");
  assert.equal(activeElement.selectionStart, 1);
  assert.equal(activeElement.selectionEnd, 1);
});

test("metadata typing keeps the title input mounted while the user is entering text", async () => {
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
  await root.dispatchAction("run-export");
  await flush();

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);
  titleInput.focus();
  titleInput.value = "곽";

  root.dispatchInput(titleInput, { isComposing: false });
  await flush();

  const rerenderedTitleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.equal(rerenderedTitleInput, titleInput);
  assert.equal(globalThis.document?.activeElement, titleInput);
  assert.equal(rerenderedTitleInput?.value, "곽");
});

test("metadata modal moves focus into the title field on open and back to the run button on close", async () => {
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
  const runButton = root.querySelector("#stagePane")?.querySelector?.('[data-action="run-export"]');
  assert.ok(runButton);
  runButton.focus();

  await root.dispatchAction("run-export");
  await flush();

  let activeElement = globalThis.document?.activeElement;
  assert.ok(activeElement);
  assert.equal(activeElement.dataset?.field, "title");

  await root.dispatchAction("close-export-metadata");
  await flush();
  await root.dispatchAction("discard-export-metadata");
  await flush();

  activeElement = globalThis.document?.activeElement;
  assert.ok(activeElement);
  assert.equal(activeElement.dataset?.action, "run-export");
  app.destroy();
});

test("metadata composition input keeps draft state untouched until the field commits", async () => {
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
  await root.dispatchAction("run-export");
  await flush();

  app.debug.setState((next) => {
    next.exportConfig.documentHeader.title = "";
    next.exportConfig.metadataModal.draft.title = "";
    next.exportConfig.metadataModal.dirty = false;
    return next;
  });

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);
  titleInput.focus();

  titleInput.value = "ㄴ";
  root.dispatchInput(titleInput, { isComposing: true });
  await flush();

  let state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.draft.title, "");
  assert.equal(globalThis.document?.activeElement, titleInput);

  titleInput.value = "노";
  titleInput.setSelectionRange(1, 1);
  root.dispatchInput(titleInput, { isComposing: false });
  await flush();

  state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.draft.title, "");
  assert.equal(globalThis.document?.activeElement, titleInput);

  root.dispatchChange(titleInput);
  await flush();

  state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.draft.title, "노");
  assert.equal(globalThis.document?.activeElement?.dataset?.field, "title");
});

test("metadata compositionend preserves the final title in the live input until the field commits", async () => {
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
  await root.dispatchAction("run-export");
  await flush();

  app.debug.setState((next) => {
    next.exportConfig.documentHeader.title = "";
    next.exportConfig.metadataModal.draft.title = "";
    next.exportConfig.metadataModal.dirty = false;
    return next;
  });

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);

  titleInput.value = "노래";
  root.dispatchCompositionEnd(titleInput);
  await flush();

  let state = app.debug.getState();
  assert.equal(titleInput.value, "노래");
  assert.equal(state.exportConfig.metadataModal.draft.title, "");
  assert.equal(state.exportConfig.metadataModal.dirty, false);

  root.dispatchChange(titleInput);
  await flush();

  state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.draft.title, "노래");
  assert.equal(state.exportConfig.metadataModal.dirty, true);
});

test("metadata title input preserves the live Korean composition text across modal rerenders", async () => {
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
  await root.dispatchAction("run-export");
  await flush();

  app.debug.setState((next) => {
    next.exportConfig.documentHeader.title = "";
    next.exportConfig.metadataModal.draft.title = "";
    next.exportConfig.metadataModal.dirty = false;
    return next;
  });

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);
  titleInput.focus();
  titleInput.value = "야";
  titleInput.setSelectionRange(1, 1);

  root.dispatchInput(titleInput, { isComposing: true });
  await flush();

  app.debug.setState((next) => {
    next.exportConfig.error = "temporary error";
    return next;
  });
  await flush();

  const rerenderedTitleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(rerenderedTitleInput);
  assert.equal(rerenderedTitleInput.value, "야");
  assert.equal(globalThis.document?.activeElement, rerenderedTitleInput);
  assert.equal(rerenderedTitleInput.selectionStart, 1);
  assert.equal(rerenderedTitleInput.selectionEnd, 1);
});

test("metadata title normalizes decomposed Hangul jamo before the field commits", async () => {
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
  await root.dispatchAction("run-export");
  await flush();

  app.debug.setState((next) => {
    next.exportConfig.documentHeader.title = "";
    next.exportConfig.metadataModal.draft.title = "";
    next.exportConfig.metadataModal.dirty = false;
    return next;
  });

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);

  titleInput.value = "야아";
  root.dispatchCompositionEnd(titleInput);
  await flush();

  let state = app.debug.getState();
  assert.equal(titleInput.value, "야아");
  assert.equal(state.exportConfig.metadataModal.draft.title, "");

  root.dispatchChange(titleInput);
  await flush();

  state = app.debug.getState();
  const rerenderedTitleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.equal(state.exportConfig.metadataModal.draft.title, "야아");
  assert.equal(rerenderedTitleInput?.value, "야아");
});

test("confirm-export-metadata uses the live title input when IME composition has not synced the draft yet", async () => {
  installBrowserStubs();
  let createJobCalls = 0;
  let seenPayload = null;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async (payload) => {
        createJobCalls += 1;
        seenPayload = payload;
        return "job-1";
      },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, result: {} }),
      reviewExport: async () => ({}),
    },
  });

  seedExportState(app);
  await root.dispatchAction("run-export");
  await flush();

  app.debug.setState((next) => {
    next.exportConfig.documentHeader.title = "";
    next.exportConfig.metadataModal.draft.title = "";
    next.exportConfig.metadataModal.dirty = false;
    return next;
  });

  const titleInput = root.querySelector("#stagePane")?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  assert.ok(titleInput);
  titleInput.focus();
  titleInput.value = "노래";

  root.dispatchInput(titleInput, { isComposing: true });
  await flush();

  await root.dispatchAction("confirm-export-metadata");
  await flush();

  const state = app.debug.getState();
  assert.equal(createJobCalls, 1);
  assert.equal(state.exportConfig.metadataModal.isOpen, false);
  assert.equal(state.exportConfig.metadataModal.validation.title, "");
  assert.deepEqual(seenPayload.options.export.document_header, {
    title: "노래",
    performer: "",
    bpm: null,
    date: state.exportConfig.documentHeader.date,
    memo: "",
  });
});

test("confirm-export-metadata keeps the modal open and preserves values when export start fails", async () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => {
        throw new Error("backend unavailable");
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
        title: "Blue in Green",
        performer: "Bill Evans Trio",
        bpm: "128",
        date: "2026-04-19",
        memo: "half-time feel",
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
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.deepEqual(state.exportConfig.metadataModal.draft, {
    title: "Blue in Green",
    performer: "Bill Evans Trio",
    bpm: 128,
    date: "2026-04-19",
    memo: "half-time feel",
  });
  assert.doesNotMatch(state.exportConfig.message, /starting/i);
  assert.match(state.exportConfig.error, /backend unavailable/i);
  assert.match(root.querySelector("#stagePane")?.innerHTML || "", /backend unavailable/i);
});

test("confirm-export-metadata ignores close attempts while export start is still pending", async () => {
  installBrowserStubs();
  const pendingJob = deferred();
  const jobPoll = deferred();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => pendingJob.promise,
      getJob: async () => jobPoll.promise,
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

  const pending = root.dispatchAction("confirm-export-metadata");
  await flush();

  await root.dispatchAction("close-export-metadata");
  await flush();

  let state = app.debug.getState();
  assert.equal(state.exportConfig.runStatus, "running");
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.match(root.querySelector("#stagePane")?.innerHTML || "", /PDF 생성 준비 중|Preparing PDF export/i);
  assert.match(root.querySelector("#stagePane")?.innerHTML || "", /출력을 시작하는 중입니다|Starting the export/i);

  pendingJob.resolve("job-1");
  await pending;
  await flush();

  state = app.debug.getState();
  assert.equal(state.exportConfig.jobId, "job-1");
  assert.equal(state.exportConfig.runStatus, "running");
  assert.equal(state.exportConfig.metadataModal.isOpen, false);

  jobPoll.resolve({ job_id: "job-1", status: "done", progress: 1, result: {} });
  await flush();
});

test("confirm-export-metadata closes the modal and surfaces backend ROI failure through job polling", async () => {
  installBrowserStubs();
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      createJob: async () => "job-1",
      getJob: async () => ({
        job_id: "job-1",
        status: "error",
        progress: 1,
        current_step: "failed",
        message: "job failed: ROI is unsafe for capture",
        result: {},
      }),
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
  await flush();

  const state = app.debug.getState();
  assert.equal(state.exportConfig.metadataModal.isOpen, false);
  assert.equal(state.exportConfig.jobId, "job-1");
  assert.equal(state.exportConfig.runStatus, "error");
  assert.match(state.exportConfig.error, /unsafe/i);
  assert.match(root.querySelector("#stagePane")?.innerHTML || "", /ROI is unsafe for capture/i);
});

test("confirm-export-metadata surfaces a blocking error when export prerequisites disappear after the modal opens", async () => {
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
    next.roi.appliedRect = null;
    next.exportConfig.metadataModal = {
      isOpen: true,
      draft: {
        title: "Blue in Green",
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
  assert.equal(state.exportConfig.runStatus, "idle");
  assert.equal(state.exportConfig.metadataModal.isOpen, true);
  assert.match(state.exportConfig.error, /ROI|대표 프레임/i);
  assert.match(root.querySelector("#stagePane")?.innerHTML || "", /ROI|대표 프레임/i);
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

test("confirm-export-metadata keeps export capture at the source beginning after ROI frame selection", async () => {
  installBrowserStubs();
  let seenPayload = null;
  const root = createRoot();
  const app = createApp(root, {
    exposeTestApi: true,
    api: {
      requestPreviewFrame: async () => ({ imagePath: "", sourcePath: "", diagnostics: [] }),
      requestPreviewRoiHealth: async () => ({
        riskLevel: "info",
        summary: "샘플 프레임 3개 기준으로 ROI를 점검했습니다.",
        diagnostics: [],
      }),
      createJob: async (payload) => {
        seenPayload = payload;
        return "job-1";
      },
      getJob: async () => ({ job_id: "job-1", status: "done", progress: 1, current_step: "done", message: "", result: {} }),
      reviewExport: async () => ({}),
    },
  });

  seedExportState(app);
  app.debug.setState((next) => {
    next.roi.frameTime = 12.8;
    next.exportConfig.metadataModal = {
      isOpen: true,
      draft: {
        title: "Blue in Green",
        performer: "Bill Evans Trio",
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

  assert.ok(seenPayload);
  assert.equal(app.debug.getState().roi.frameTime, 12.8);
  assert.equal(seenPayload.options.extract.start_sec, 0);
  assert.equal(app.debug.getState().exportConfig.metadataModal.isOpen, false);
});

test("rendered metadata modal uses paper-surface classes and responsive row hooks", () => {
  const state = createInitialSessionState();
  state.ui.locale = "ko";
  state.source.filePath = "/tmp/source-a.mp4";
  state.source.displayName = "source-a.mp4";
  state.roi.previewImage = "/tmp/frame.png";
  state.roi.appliedRect = ROI_RECT;
  state.exportConfig.formats = ["pdf"];
  state.exportConfig.metadataModal = {
    isOpen: true,
    draft: {
      title: "Blue in Green",
      performer: "Bill Evans Trio",
      bpm: "128",
      date: "2026-04-19",
      memo: "half-time feel",
    },
    dirty: true,
    validation: { title: "", bpm: "" },
    showDiscardConfirm: true,
  };

  const markup = renderExportScreen(state);

  assert.match(markup, /class="export-metadata-overlay"/);
  assert.match(markup, /class="export-metadata-modal export-metadata-sheet"/);
  assert.match(markup, /class="export-metadata-grid"/);
  assert.match(markup, /class="export-metadata-row export-metadata-row-split"/);
  assert.match(markup, /class="export-metadata-actions"/);
  assert.match(markup, /class="export-metadata-discard"/);
});
