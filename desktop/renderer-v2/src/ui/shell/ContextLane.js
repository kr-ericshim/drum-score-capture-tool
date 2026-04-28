import { escapeAttr, escapeHtml } from "../../lib/html.js";
import { normalizeAssetPath } from "../../lib/paths.js";
import { t } from "../../lib/i18n.js";

const SOURCE_SUMMARY = "Source facts";
const INGEST_STATUS = "Ready to load";
const INSPECTION_VIEW = "Selected result";
const OUTPUT_SUMMARY = "Review summary";
const NEXT_ACTION = "Next action";

function renderSourceLane(state) {
  const locale = state.ui.locale || "ko";
  const metadata = state.source.metadata || {};
  const normalizedPath = String(state.source.filePath || "").replace(/\\/g, "/");
  const directory = normalizedPath ? normalizedPath.split("/").slice(0, -1).join("/") || "/" : t("lane.noSource", { locale });
  const sourceSummaryLabel = escapeHtml(t("lane.sourceSummary", { locale }) || SOURCE_SUMMARY);
  const fileLabel = escapeHtml(t("lane.file", { locale }));
  const resolutionLabel = escapeHtml(t("lane.res", { locale }));
  const lengthLabel = escapeHtml(t("lane.length", { locale }));
  const statusLabel = escapeHtml(t("lane.status", { locale }));
  const ingestStatusLabel = escapeHtml(t("lane.ingestStatus", { locale }) || INGEST_STATUS);
  const directoryLabel = escapeHtml(t("lane.directory", { locale }));
  const nextStepLabel = escapeHtml(t("lane.nextStep", { locale }));
  const safeDisplayName = escapeHtml(state.source.displayName || t("lane.noSource", { locale }));
  const safeResolution = escapeHtml(metadata.resolutionLabel || t("lane.unknown", { locale }));
  const safeDuration = escapeHtml(metadata.durationLabel || "00:00");
  const safeStatus = escapeHtml(state.source.filePath ? t("lane.loaded", { locale }) : t("lane.idle", { locale }));
  const safeDirectory = escapeHtml(directory);
  const safeNextStep = escapeHtml(state.source.filePath ? t("lane.nextRoi", { locale }) : t("lane.nextSelectFile", { locale }));
  return `
    <section class="inspector-panel">
      <p class="inspector-label">${sourceSummaryLabel}</p>
      <dl class="inspector-grid">
        <div><dt>${fileLabel}</dt><dd>${safeDisplayName}</dd></div>
        <div><dt>${resolutionLabel}</dt><dd>${safeResolution}</dd></div>
        <div><dt>${lengthLabel}</dt><dd>${safeDuration}</dd></div>
        <div><dt>${statusLabel}</dt><dd>${safeStatus}</dd></div>
      </dl>
    </section>
    <section class="inspector-panel inspector-panel-fill">
      <p class="inspector-label">${ingestStatusLabel}</p>
      <dl class="inspector-list">
        <div><dt>${directoryLabel}</dt><dd>${safeDirectory}</dd></div>
        <div><dt>${nextStepLabel}</dt><dd>${safeNextStep}</dd></div>
      </dl>
    </section>
  `;
}

function renderReviewLane(state) {
  const locale = state.ui.locale || "en";
  const focused = state.review.pages.find((page) => page.id === state.review.focusedPageId) || state.review.pages[0];
  const sourcePreview = focused?.previewPath || "";
  const reviewDone = state.review.status === "applied";
  const selectedCount = reviewDone
    ? Number(state.review.keptCount || state.review.selectedPageIds.length || 0)
    : state.review.selectedPageIds.length;
  const previewAlt = escapeAttr(state.source.displayName || focused?.title || t("lane.frameAlt", { locale }));
  const previewSrc = sourcePreview ? escapeAttr(normalizeAssetPath(sourcePreview)) : "";
  const inspectionViewLabel = escapeHtml(t("lane.inspectionView", { locale }) || INSPECTION_VIEW);
  const outputSummaryLabel = escapeHtml(t("lane.outputSummary", { locale }) || OUTPUT_SUMMARY);
  const nextActionLabel = escapeHtml(t("lane.nextAction", { locale }) || NEXT_ACTION);
  const previewTone = escapeHtml(focused?.previewKind === "output" ? t("lane.previewOutput", { locale }) : t("lane.previewCapture", { locale }));
  const previewTitle = escapeHtml(focused?.title || t("lane.previewNone", { locale }));
  const focusedPageLabel = escapeHtml(t("lane.focusedPage", { locale }));
  const selectionLabel = escapeHtml(reviewDone ? t("lane.keep", { locale }) : t("lane.selected", { locale }));
  const exportStateLabel = escapeHtml(t("lane.exportState", { locale }));
  const exportStateValue = escapeHtml(state.review.status === "applied" ? t("lane.locked", { locale }) : t("lane.pending", { locale }));
  const totalCountLabel = escapeHtml(t("lane.totalCount", { locale }));
  const pdfReadyLabel = escapeHtml(t("lane.pdfReady", { locale }));
  const pdfReadyValue = escapeHtml(state.review.pdfPath ? t("lane.yes", { locale }) : t("lane.no", { locale }));
  const noteLabel = escapeHtml(reviewDone ? t("lane.openResults", { locale }) : t("lane.chooseCaptures", { locale }));
  const focusedPageValue = escapeHtml(focused?.title || t("lane.noSource", { locale }));
  const noSelectionLabel = escapeHtml(t("lane.noSelection", { locale }));
  return `
    <section class="inspector-panel">
      <p class="inspector-label">${inspectionViewLabel}</p>
      <div class="inspector-frame inspector-frame-review">
        ${sourcePreview ? `<img src="${previewSrc}" alt="${previewAlt}" />` : `<p>${noSelectionLabel}</p>`}
        <span class="inspector-frame-tag">${previewTone} ${previewTitle}</span>
      </div>
    </section>
    <section class="inspector-panel">
      <p class="inspector-label">${outputSummaryLabel}</p>
      <dl class="inspector-list">
        <div><dt>${focusedPageLabel}</dt><dd>${focusedPageValue}</dd></div>
        <div><dt>${selectionLabel}</dt><dd>${selectedCount} / ${state.review.pages.length || 0}</dd></div>
        <div><dt>${exportStateLabel}</dt><dd>${exportStateValue}</dd></div>
      </dl>
    </section>
    <section class="inspector-panel inspector-panel-fill">
      <p class="inspector-label">${nextActionLabel}</p>
      <dl class="inspector-list">
        <div><dt>${totalCountLabel}</dt><dd>${state.review.pages.length}</dd></div>
        <div><dt>${pdfReadyLabel}</dt><dd>${pdfReadyValue}</dd></div>
      </dl>
      <div class="inspector-note">${noteLabel}</div>
    </section>
  `;
}

export function renderContextLane(state) {
  if (state.ui.activeStep === "export") {
    return "";
  }
  if (state.ui.activeStep === "source") {
    return renderSourceLane(state);
  }
  if (state.ui.activeStep === "roi") {
    return "";
  }
  return renderReviewLane(state);
}
