import test from "node:test";
import assert from "node:assert/strict";
import { createReviewController } from "../features/review/reviewController.js";
import { createInitialSessionState, deriveCapturePages } from "../app/session/selectors.js";
import { restoreSession, saveSession } from "../app/session/persistence.js";

test("saved captures can be excluded, restored with undo, and cropped without replacing their identity", async () => {
  let state = createInitialSessionState();
  state.exportConfig.jobId = "job-1";
  state.review.pages = [{ id: "1", capturePath: "/original.png", previewPath: "/original.png" }];
  state.review.focusedPageId = "1";
  state.review.selectedPageIds = ["1"];
  state.review.status = "applied";
  const controller = createReviewController({ getState: () => state, setState: update => { state = update(structuredClone(state)); }, api: {}, root: {}, mountEditor() {} });
  controller.toggle("1", false);
  assert.deepEqual(state.review.selectedPageIds, []);
  assert.equal(state.review.status, "idle");
  await controller.handleAction("review-undo");
  assert.deepEqual(state.review.selectedPageIds, ["1"]);
  await controller.handleAction("review-redo");
  assert.deepEqual(state.review.selectedPageIds, []);
  const pages = deriveCapturePages({ review_candidates: ["/original.png", "/excluded.png"], capture_edits: { "/original.png": { image_path: "/edited.png", roi: [[0,0],[20,0],[20,20],[0,20]] } }, review_export: { selected_captures: ["/original.png"] } });
  assert.equal(pages.length, 2);
  assert.equal(pages[0].capturePath, "/original.png");
  assert.match(pages[0].previewPath, /edited\.png$/);
  assert.equal(pages[1].exportLocked, false);
});

test("session recovery preserves job and ROI but never persists temporary blob URLs", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const state = createInitialSessionState();
  state.source.filePath = "/video.mp4";
  state.exportConfig.jobId = "in-progress-job";
  state.exportConfig.runStatus = "running";
  state.roi.previewImage = "blob:expired-on-reload";
  state.roi.previewSourcePath = "/preview.png";
  state.roi.appliedRect = [[10,10],[30,10],[30,40],[10,40]];
  saveSession(storage, state);
  const restored = restoreSession(storage, createInitialSessionState());
  assert.equal(restored.exportConfig.jobId, "in-progress-job");
  assert.deepEqual(restored.roi.appliedRect, state.roi.appliedRect);
  assert.equal(restored.roi.previewImage, "/preview.png");
  assert.equal(restored.ui.activeStep, "export");
  assert.equal(restoreSession({ getItem: () => "broken-json" }, createInitialSessionState()).source.filePath, "");
});

test("session recovery remembers whether the saved files were built from the review draft", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  let state = createInitialSessionState();
  state.source.filePath = "/video.mp4";
  state.exportConfig.jobId = "job-1";
  state.review.jobRevision = 2;
  state.review.pages = [{ id: "1", capturePath: "/one.png" }, { id: "2", capturePath: "/two.png" }];
  state.review.selectedPageIds = ["1"];
  state.review.status = "applied";
  saveSession(storage, state);
  let restored = restoreSession(storage, createInitialSessionState());
  assert.deepEqual(restored.review.restoredSelectedPaths, ["/one.png"]);
  assert.equal(restored.review.restoredApplied, true);
  // saved again before the job is read back: the marker is kept with the draft
  saveSession(storage, restored);
  assert.equal(restoreSession(storage, createInitialSessionState()).review.restoredApplied, true);
  // a selection change after the build makes the saved files the previous ones
  const controller = createReviewController({ getState: () => state, setState: update => { state = update(structuredClone(state)); }, api: {}, root: {}, mountEditor() {} });
  controller.toggle("2", true);
  saveSession(storage, state);
  restored = restoreSession(storage, createInitialSessionState());
  assert.deepEqual(restored.review.restoredSelectedPaths, ["/one.png", "/two.png"]);
  assert.equal(restored.review.restoredApplied, false);
  // drafts saved before the marker existed cannot tell
  values.set("drum-sheet-session-v1", JSON.stringify({ version: 1, source: { filePath: "/video.mp4" }, exportConfig: { jobId: "job-1" }, review: { jobId: "job-1", revision: 2, selectedPaths: ["/one.png"] } }));
  assert.equal(restoreSession(storage, createInitialSessionState()).review.restoredApplied, false);
});

test("review keyboard navigation works after clicking a capture thumbnail", async () => {
  let state = createInitialSessionState();
  state.ui.activeStep = "review";
  state.exportConfig.jobId = "job-keys";
  state.review.pages = [{id:"1",capturePath:"/one.png"},{id:"2",capturePath:"/two.png"}];
  state.review.focusedPageId = "1";
  state.review.selectedPageIds = ["1","2"];
  const controller = createReviewController({ getState: () => state, setState: f => { state=f(structuredClone(state)); }, root:{}, api:{} });
  const target = {tagName:"BUTTON",dataset:{action:"focus-review-page"}};
  controller.handleKey({key:"ArrowRight",target,preventDefault(){}});
  assert.equal(state.review.focusedPageId,"2");
  controller.handleKey({key:" ",target,preventDefault(){}});
  assert.deepEqual(state.review.selectedPageIds,["1"]);
  await controller.handleAction("review-undo");
  assert.deepEqual(state.review.selectedPageIds,["1","2"]);
});


test("review filtering keeps navigation and keyboard selection on a visible capture", async () => {
  let state = createInitialSessionState();
  state.ui.activeStep = "review";
  state.exportConfig.jobId = "job-filter";
  state.review.pages = [{ id: "1" }, { id: "2", suspicious: true }, { id: "3", suspicious: true }];
  state.review.focusedPageId = "1";
  state.review.selectedPageIds = ["1", "2", "3"];
  state.review.cropping = true;
  const controller = createReviewController({ getState: () => state, setState: f => { state = f(structuredClone(state)); }, root: {}, api: {} });
  await controller.handleAction("review-filter", "suspicious");
  assert.equal(state.review.focusedPageId, "2");
  assert.equal(state.review.cropping, false);
  controller.handleKey({ key: " ", target: { tagName: "DIV" }, preventDefault() {} });
  assert.deepEqual(state.review.selectedPageIds, ["1", "3"]);
  await controller.handleAction("review-next");
  assert.equal(state.review.focusedPageId, "3");
  state.review.pages.forEach(page => { page.suspicious = false; });
  await controller.handleAction("review-filter", "suspicious");
  assert.equal(state.review.focusedPageId, "");
});


test("viewer inclusion action resolves the filtered capture and respects rebuilding", async () => {
  let state = createInitialSessionState();
  state.exportConfig.jobId = "viewer-toggle";
  state.review.pages = [{ id: "1" }, { id: "2", suspicious: true }];
  state.review.filter = "suspicious";
  state.review.focusedPageId = "1";
  state.review.selectedPageIds = ["1", "2"];
  const controller = createReviewController({ getState: () => state, setState: f => { state = f(structuredClone(state)); }, root: {}, api: {} });
  await controller.handleAction("review-toggle-focused");
  assert.deepEqual(state.review.selectedPageIds, ["1"]);
  await controller.handleAction("review-undo");
  assert.deepEqual(state.review.selectedPageIds, ["1", "2"]);
  state.review.status = "running";
  await controller.handleAction("review-toggle-focused");
  assert.deepEqual(state.review.selectedPageIds, ["1", "2"]);
});

test("include all leaves other moments, short displays and exclusion candidates as they were", async () => {
  let state = createInitialSessionState();
  state.exportConfig.jobId = "job-select-all";
  state.review.pages = [
    { id: "1" }, { id: "2" },
    { id: "3", minorityAlternate: true },
    { id: "4", transitionFragment: true },
    { id: "5", autoExcludeCandidate: true },
    { id: "6", minorityAlternate: true },
  ];
  state.review.selectedPageIds = ["6"];
  const controller = createReviewController({ getState: () => state, setState: f => { state = f(structuredClone(state)); }, root: {}, api: {} });
  await controller.handleAction("review-select-all");
  assert.deepEqual(state.review.selectedPageIds, ["1", "2", "6"]);
  await controller.handleAction("review-undo");
  assert.deepEqual(state.review.selectedPageIds, ["6"]);
});
