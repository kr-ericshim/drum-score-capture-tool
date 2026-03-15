import { normalizeAssetPath } from "../../lib/paths.js";
import { t } from "../../lib/i18n.js";

const SOURCE_SUMMARY = "SOURCE SUMMARY";
const INGEST_STATUS = "INGEST STATUS";
const INSPECTION_VIEW = "INSPECTION VIEW";
const OUTPUT_SUMMARY = "OUTPUT SUMMARY";
const NEXT_ACTION = "NEXT ACTION";

function renderSourceLane(state) {
  const locale = state.ui.locale || "ko";
  const metadata = state.source.metadata || {};
  const normalizedPath = String(state.source.filePath || "").replace(/\\/g, "/");
  const directory = normalizedPath ? normalizedPath.split("/").slice(0, -1).join("/") || "/" : t("lane.noSource", { locale });
  return `
    <section class="inspector-panel">
      <p class="inspector-label">${t("lane.sourceSummary", { locale }) || SOURCE_SUMMARY}</p>
      <div class="inspector-grid">
        <div><span>${t("lane.file", { locale })}</span><strong>${state.source.displayName || t("lane.noSource", { locale })}</strong></div>
        <div><span>${t("lane.res", { locale })}</span><strong>${metadata.resolutionLabel || t("lane.unknown", { locale })}</strong></div>
        <div><span>${t("lane.length", { locale })}</span><strong>${metadata.durationLabel || "00:00"}</strong></div>
        <div><span>${t("lane.status", { locale })}</span><strong>${state.source.filePath ? t("lane.loaded", { locale }) : t("lane.idle", { locale })}</strong></div>
      </div>
    </section>
    <section class="inspector-panel inspector-panel-fill">
      <p class="inspector-label">${t("lane.ingestStatus", { locale }) || INGEST_STATUS}</p>
      <div class="inspector-list">
        <div><dt>${t("lane.directory", { locale })}</dt><dd>${directory}</dd></div>
        <div><dt>${t("lane.nextStep", { locale })}</dt><dd>${state.source.filePath ? t("lane.nextRoi", { locale }) : t("lane.nextSelectFile", { locale })}</dd></div>
      </div>
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
  return `
    <section class="inspector-panel">
      <p class="inspector-label">${t("lane.inspectionView", { locale }) || INSPECTION_VIEW}</p>
      <div class="inspector-frame inspector-frame-review">
        ${sourcePreview ? `<img src="${normalizeAssetPath(sourcePreview)}" alt="${state.source.displayName || focused?.title || t("lane.frameAlt", { locale })}" />` : `<p>${t("lane.noSelection", { locale })}</p>`}
        <span class="inspector-frame-tag">${focused?.previewKind === "output" ? t("lane.previewOutput", { locale }) : t("lane.previewCapture", { locale })} ${focused?.title || t("lane.previewNone", { locale })}</span>
      </div>
    </section>
    <section class="inspector-panel">
      <p class="inspector-label">${t("lane.outputSummary", { locale }) || OUTPUT_SUMMARY}</p>
      <div class="inspector-list">
        <div><dt>${t("lane.focusedPage", { locale })}</dt><dd>${focused?.title || t("lane.noSource", { locale })}</dd></div>
        <div><dt>${reviewDone ? t("lane.keep", { locale }) : t("lane.selected", { locale })}</dt><dd>${selectedCount} / ${state.review.pages.length || 0}</dd></div>
        <div><dt>${t("lane.exportState", { locale })}</dt><dd>${state.review.status === "applied" ? t("lane.locked", { locale }) : t("lane.pending", { locale })}</dd></div>
      </div>
    </section>
    <section class="inspector-panel inspector-panel-fill">
      <p class="inspector-label">${t("lane.nextAction", { locale }) || NEXT_ACTION}</p>
      <div class="inspector-list">
        <div><dt>${t("lane.totalCount", { locale })}</dt><dd>${state.review.pages.length}</dd></div>
        <div><dt>${t("lane.pdfReady", { locale })}</dt><dd>${state.review.pdfPath ? t("lane.yes", { locale }) : t("lane.no", { locale })}</dd></div>
      </div>
      <div class="inspector-note">${reviewDone ? t("lane.openResults", { locale }) : t("lane.chooseCaptures", { locale })}</div>
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
