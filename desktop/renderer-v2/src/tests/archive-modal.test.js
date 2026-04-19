import test from "node:test";
import assert from "node:assert/strict";

import { createInitialSessionState } from "../app/session/selectors.js";
import { renderTopBar } from "../ui/shell/TopBar.js";

test("top bar renders archive button in both default and ROI layouts", () => {
  const sourceState = createInitialSessionState();
  sourceState.ui.locale = "en";

  const sourceMarkup = renderTopBar(sourceState, {
    sourceLabel: "No source selected",
    stepLabel: "source",
    stepState: { enabled: true, complete: false },
  });

  assert.match(sourceMarkup, /data-action="open-archive"/);

  const roiState = createInitialSessionState();
  roiState.ui.locale = "en";
  roiState.ui.activeStep = "roi";

  const roiMarkup = renderTopBar(roiState, {
    sourceLabel: "practice.mp4",
    stepLabel: "roi",
    stepState: { enabled: true, complete: false },
  });

  assert.match(roiMarkup, /data-action="open-archive"/);
});

test("archive modal returns empty markup when closed", async () => {
  const { renderArchiveModal } = await import("../features/archive/ArchiveModal.js");
  const state = createInitialSessionState();

  assert.equal(renderArchiveModal(state), "");
});

test("archive modal renders detail actions from selected row", async () => {
  const { renderArchiveModal } = await import("../features/archive/ArchiveModal.js");
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.archive.isOpen = true;
  state.archive.selectedSourceKey = "source-1";
  state.archive.items = [
    {
      sourceKey: "source-1",
      displayName: "Autumn Leaves",
      completedAt: 1713526200,
      pdfPath: "/tmp/autumn-leaves.pdf",
      outputDir: "/tmp/autumn-leaves",
    },
  ];

  const markup = renderArchiveModal(state);

  assert.match(markup, /Autumn Leaves/);
  assert.match(markup, /data-action="back-archive-detail"/);
  assert.match(markup, /data-action="open-archive-pdf"/);
  assert.match(markup, /data-action="open-archive-folder"/);
});

test("archive modal shows empty state and disables missing-path actions", async () => {
  const { renderArchiveModal } = await import("../features/archive/ArchiveModal.js");
  const emptyState = createInitialSessionState();
  emptyState.ui.locale = "en";
  emptyState.archive.isOpen = true;

  const emptyMarkup = renderArchiveModal(emptyState);

  assert.match(emptyMarkup, /No saved final PDFs yet\.|아직 저장된 최종 PDF가 없습니다\./);

  const detailState = createInitialSessionState();
  detailState.ui.locale = "en";
  detailState.archive.isOpen = true;
  detailState.archive.selectedSourceKey = "source-2";
  detailState.archive.items = [
    {
      sourceKey: "source-2",
      displayName: "Blue Rondo",
      completedAt: 1713526200,
      pdfPath: "",
      outputDir: "",
    },
  ];

  const detailMarkup = renderArchiveModal(detailState);

  assert.match(detailMarkup, /data-action="open-archive-pdf"[^>]*disabled/);
  assert.match(detailMarkup, /data-action="open-archive-folder"[^>]*disabled/);
});

test("archive modal shows an explicit loading state instead of stale rows during refresh", async () => {
  const { renderArchiveModal } = await import("../features/archive/ArchiveModal.js");
  const state = createInitialSessionState();
  state.ui.locale = "en";
  state.archive.isOpen = true;
  state.archive.status = "loading";
  state.archive.items = [
    {
      sourceKey: "source-3",
      displayName: "Stale Library Row",
      completedAt: 1713526200,
      pdfPath: "/tmp/stale.pdf",
      outputDir: "/tmp/stale",
    },
  ];

  const markup = renderArchiveModal(state);

  assert.match(markup, /Loading archive\.\.\.|보관함을 불러오는 중입니다\./);
  assert.doesNotMatch(markup, /Stale Library Row/);
});
