import { STEP_TITLES } from "../../app/types.js";
import { t } from "../../lib/i18n.js";

const STEP_ICONS = {
  source: "01",
  roi: "02",
  export: "03",
  review: "04",
};

const PIPELINE = "PIPELINE";

function renderRailFooter(state) {
  const locale = state.ui.locale || "en";
  if (state.ui.activeStep === "roi") {
    return "";
  }
  if (state.ui.activeStep === "review") {
    const formatLabel = state.exportConfig.formats.length ? state.exportConfig.formats.join(", ").toUpperCase() : t("rail.none", { locale });
    const selectedCount = state.review.status === "applied"
      ? Number(state.review.keptCount || state.review.selectedPageIds.length || 0)
      : state.review.selectedPageIds.length;
    const outputLabel = state.review.outputDir || t("rail.pendingActivation", { locale });
    return `
      <section class="rail-footer rail-footer-actions">
        <p class="rail-footer-label">${t("rail.exportSettings", { locale })}</p>
        <div class="rail-summary-stack">
          <div class="rail-summary-row">
            <span>${t("rail.format", { locale })}</span>
            <strong>${formatLabel}</strong>
          </div>
          <div class="rail-summary-row">
            <span>${state.review.status === "applied" ? t("review.kept", { locale }) : t("review.selected", { locale })}</span>
            <strong>${selectedCount}</strong>
          </div>
        </div>
        <div class="rail-path-block" data-path-kind="output-dir">
          <span>${t("rail.outputDir", { locale })}</span>
          <strong>${outputLabel}</strong>
        </div>
        <button class="rail-action" data-action="open-output-dir" ${state.review.outputDir ? "" : "disabled"}>${t("rail.openFolder", { locale })}</button>
        <button class="rail-action rail-action-primary" data-action="open-output-pdf" ${state.review.pdfPath ? "" : "disabled"}>${t("rail.openPdf", { locale })}</button>
        <button class="rail-action" data-action="copy-output-dir" ${state.review.outputDir ? "" : "disabled"}>${t("rail.copyPath", { locale })}</button>
      </section>
    `;
  }

  return `
    <section class="rail-footer rail-footer-status">
      <p class="rail-footer-label">${t("rail.workbenchStatus", { locale })}</p>
      <div class="rail-footer-row"><span>${t("rail.gpu", { locale })}</span><strong>${state.ui.backend?.ready ? t("rail.active", { locale }) : t("rail.wait", { locale })}</strong></div>
      <div class="rail-footer-row"><span>${t("rail.source", { locale })}</span><strong>${state.source.displayName ? t("rail.loaded", { locale }) : t("rail.idle", { locale })}</strong></div>
    </section>
  `;
}

export function renderProcessRail(state, items) {
  const locale = state.ui.locale || "en";
  return `
    <div class="rail-head">
      <p>${t("rail.pipeline", { locale }) || PIPELINE}</p>
    </div>
    <ol class="process-list">
      ${items.map((item) => `
        <li>
          <button class="process-step ${item.active ? "is-active" : ""} ${item.complete ? "is-complete" : ""}" data-action="open-step" data-step="${item.id}" ${item.enabled ? "" : "disabled"}>
            <span class="process-step-index">${STEP_ICONS[item.id]}</span>
            <span class="process-step-copy">
              <strong>${t(`step.${item.id}`, { locale }) || STEP_TITLES[item.id]}</strong>
              <small>${item.summary}</small>
            </span>
          </button>
        </li>
      `).join("")}
    </ol>
    ${renderRailFooter(state)}
  `;
}
