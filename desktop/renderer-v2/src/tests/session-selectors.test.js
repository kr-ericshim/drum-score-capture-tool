import test from "node:test";
import assert from "node:assert/strict";

import {
  createInitialExportConfig,
  createInitialSessionState,
  createDocumentHeaderState,
  deriveCapturePages,
  getProcessRailItems,
  getStepState,
  getTopBarSummary,
  inferLayoutHintFromRoi,
  isRectValid,
  normalizeDocumentHeader,
  summarizeSelection,
} from "../app/session/selectors.js";

test("source step starts blocked until a file is selected", () => {
  const state = createInitialSessionState();

  const source = getStepState(state, "source");
  const roi = getStepState(state, "roi");

  assert.equal(source.complete, false);
  assert.equal(roi.enabled, false);
  assert.match(roi.blockingReason, /Select a local file|로컬 파일/i);
});

test("initial session state includes a supported locale", () => {
  const state = createInitialSessionState();

  assert.match(state.ui.locale, /^(ko|en)$/);
});

test("initial session state starts in file mode with empty youtube preparation state", () => {
  const state = createInitialSessionState();

  assert.equal(state.source.sourceType, "file");
  assert.equal(state.source.youtubeUrl, "");
  assert.equal(state.source.prepareStatus, "idle");
  assert.equal(state.source.prepareJobId, "");
  assert.equal(state.source.prepareStage, "");
  assert.equal(state.source.prepareProgress, 0);
  assert.equal(state.source.prepareProgressMode, "indeterminate");
  assert.equal(state.source.prepareMessage, "");
  assert.equal(state.source.prepareFromCache, false);
  assert.deepEqual(state.source.prepareLogs, []);
  assert.equal(state.source.preparedFromYouTube, false);
  assert.equal(state.source.preparedVideoPath, "");
  assert.equal(state.source.prepareErrorDetail, "");
  assert.deepEqual(state.source.registryItems, []);
});

test("initial export config includes the document-header contract with today's date", () => {
  const state = createInitialSessionState();

  assert.deepEqual(Object.keys(state.exportConfig.documentHeader).sort(), ["bpm", "date", "memo", "performer", "title"]);
  assert.equal(state.exportConfig.documentHeader.title, "");
  assert.equal(state.exportConfig.documentHeader.performer, "");
  assert.equal(state.exportConfig.documentHeader.bpm, null);
  assert.match(state.exportConfig.documentHeader.date, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(state.exportConfig.documentHeader.memo, "");
});

test("initial export config keeps a clean metadata modal draft separate from confirmed document header", () => {
  const exportConfig = createInitialExportConfig("/tmp/score-library/Take Five.mp4", new Date("2026-04-19T09:00:00Z"));

  assert.deepEqual(exportConfig.metadataModal.draft, exportConfig.documentHeader);
  assert.notEqual(exportConfig.metadataModal.draft, exportConfig.documentHeader);
  assert.equal(exportConfig.metadataModal.isOpen, false);
  assert.equal(exportConfig.metadataModal.dirty, false);
  assert.deepEqual(exportConfig.metadataModal.validation, { title: "", bpm: "" });
  assert.equal(exportConfig.metadataModal.showDiscardConfirm, false);
});

test("export config reset defaults the document title from the source filename stem", () => {
  const exportConfig = createInitialExportConfig("/tmp/score-library/My Autumn Leaves.mp4", new Date("2026-04-19T09:00:00Z"));

  assert.equal(exportConfig.documentHeader.title, "My Autumn Leaves");
  assert.equal(exportConfig.documentHeader.date, "2026-04-19");
});

test("document header helpers normalize title and optional blank fields without placeholders", () => {
  const fallbackHeader = createDocumentHeaderState("/tmp/Take Five.mkv", new Date("2026-04-19T09:00:00Z"));
  const normalized = normalizeDocumentHeader(
    {
      title: "   ",
      performer: "  Dave Brubeck Quartet  ",
      bpm: "128.8",
      date: "",
      memo: "   ",
    },
    fallbackHeader,
  );

  assert.deepEqual(normalized, {
    title: "Take Five",
    performer: "Dave Brubeck Quartet",
    bpm: 128,
    date: "",
    memo: "",
  });
});

test("top bar and process rail prefer youtube prepare progress over file labels while loading", () => {
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.source.youtubeUrl = "https://youtu.be/demo";
  state.source.prepareStatus = "loading";
  state.source.prepareStage = "download";
  state.source.prepareProgress = 0.42;
  state.source.prepareProgressMode = "determinate";
  state.source.prepareMessage = "downloading video 42%";

  const summary = getTopBarSummary(state);
  const railItems = getProcessRailItems(state);

  assert.match(summary.sourceLabel, /42%/);
  assert.match(railItems[0].summary, /42%/);
});

test("roi completion requires both a representative frame and an applied roi", () => {
  const state = createInitialSessionState();
  state.source.filePath = "/tmp/video.mp4";
  state.roi.frameTime = 12.5;
  state.roi.draftRect = [[10, 10], [110, 10], [110, 90], [10, 90]];

  assert.equal(getStepState(state, "roi").complete, false);

  state.roi.appliedRect = state.roi.draftRect;
  assert.equal(getStepState(state, "roi").complete, true);
  assert.equal(getStepState(state, "export").enabled, true);
});

test("deriveCapturePages prefers review candidates and keeps diagnostics aligned", () => {
  const pages = deriveCapturePages({
    review_candidates: ["/tmp/c1.png", "/tmp/c2.png"],
    images: ["/tmp/page1.png"],
    page_diagnostics: [
      { page_index: 1, suspicious: false },
      { page_index: 2, suspicious: true },
    ],
  });

  assert.deepEqual(
    pages.map((page) => page.capturePath),
    ["/tmp/c1.png", "/tmp/c2.png"],
  );
  assert.equal(pages[1].suspicious, true);
});

test("deriveCapturePages falls back to preview images for pdf-only review output", () => {
  const pages = deriveCapturePages({
    preview_images: ["/tmp/preview-1.png", "/tmp/preview-2.png"],
    review_candidates: ["/tmp/preview-1.png", "/tmp/preview-2.png"],
    page_diagnostics: [
      { page_index: 1, suspicious: false },
      { page_index: 2, suspicious: false },
    ],
  });

  assert.equal(pages.length, 2);
  assert.equal(pages[0].previewPath, "file:///tmp/preview-1.png");
});

test("deriveCapturePages keeps review capture previews instead of swapping in finalized pages before review export", () => {
  const pages = deriveCapturePages({
    review_candidates: ["/tmp/capture-1.png", "/tmp/capture-2.png"],
    images: ["/tmp/final-page-1.png", "/tmp/final-page-2.png"],
    page_diagnostics: [
      { page_index: 1, suspicious: false },
      { page_index: 2, suspicious: false },
    ],
  });

  assert.equal(pages[0].capturePath, "/tmp/capture-1.png");
  assert.equal(pages[0].previewPath, "file:///tmp/capture-1.png");
});

test("deriveCapturePages keeps capture previews even after review export is applied", () => {
  const pages = deriveCapturePages({
    review_candidates: ["/tmp/capture-1.png"],
    preview_images: ["/tmp/review-preview-1.png"],
    images: ["/tmp/final-page-1.png"],
    review_export: { kept_count: 1, requested_count: 1 },
  });

  assert.equal(pages.length, 1);
  assert.equal(pages[0].capturePath, "/tmp/capture-1.png");
  assert.equal(pages[0].previewPath, "file:///tmp/capture-1.png");
  assert.equal(pages[0].outputPreviewPath, "file:///tmp/review-preview-1.png");
  assert.equal(pages[0].previewKind, "capture");
});

test("deriveCapturePages drops page diagnostics when capture candidates and final pages do not align", () => {
  const pages = deriveCapturePages({
    review_candidates: ["/tmp/capture-1.png", "/tmp/capture-2.png", "/tmp/capture-3.png"],
    images: ["/tmp/final-page-1.png", "/tmp/final-page-2.png"],
    page_diagnostics: [
      { page_index: 1, suspicious: true },
      { page_index: 2, suspicious: false },
    ],
  });

  assert.equal(pages.length, 3);
  assert.equal(pages[0].suspicious, false);
  assert.equal(pages[1].suspicious, false);
  assert.equal(pages[2].suspicious, false);
});

test("deriveCapturePages normalizes windows preview paths for img rendering", () => {
  const pages = deriveCapturePages({
    review_candidates: ["C:\\exports\\review page #1.png"],
    images: [],
    page_diagnostics: [{ page_index: 1, suspicious: false }],
  });

  assert.equal(pages[0].capturePath, "C:\\exports\\review page #1.png");
  assert.equal(pages[0].previewPath, "file:///C:/exports/review%20page%20%231.png");
});

test("inferLayoutHintFromRoi distinguishes bottom bar, page turn, and scroll layouts", () => {
  const bottomBar = inferLayoutHintFromRoi([[0, 0], [300, 0], [300, 60], [0, 60]]);
  const pageTurn = inferLayoutHintFromRoi([[0, 0], [160, 0], [160, 200], [0, 200]]);
  const fullScroll = inferLayoutHintFromRoi([[0, 0], [240, 0], [240, 180], [0, 180]]);

  assert.equal(bottomBar, "bottom_bar");
  assert.equal(pageTurn, "page_turn");
  assert.equal(fullScroll, "full_scroll");
});

test("selection summary reports kept items", () => {
  assert.equal(summarizeSelection(["1", "2", "3"], new Set(["1", "3"])).keptCount, 2);
});

test("isRectValid only accepts four-point rects", () => {
  assert.equal(isRectValid([[0, 0], [1, 1]]), false);
  assert.equal(isRectValid([[0, 0], [10, 0], [10, 10], [0, 10]]), true);
});
