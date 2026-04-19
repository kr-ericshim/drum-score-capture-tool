import { STEP_TITLES } from "../../app/types.js";
import { getSourcePrepareSummary } from "../../app/session/selectors.js";
import { escapeHtml } from "../../lib/html.js";
import { t } from "../../lib/i18n.js";

const STEP_ICONS = {
  source: "01",
  roi: "02",
  export: "03",
  review: "04",
};

const PIPELINE = "Workflow";

function renderRailFooter(state) {
  const locale = state.ui.locale || "en";
  const preparingLabel = getSourcePrepareSummary(state, locale);
  if (state.ui.activeStep === "roi") {
    return "";
  }
  if (state.ui.activeStep === "review") {
    const formatLabel = state.exportConfig.formats.length ? state.exportConfig.formats.join(", ").toUpperCase() : t("rail.none", { locale });
    const selectedCount = state.review.status === "applied"
      ? Number(state.review.keptCount || state.review.selectedPageIds.length || 0)
      : state.review.selectedPageIds.length;
    const outputLabel = state.review.outputDir || t("rail.pendingActivation", { locale });
    const exportSettingsLabel = escapeHtml(t("rail.exportSettings", { locale }));
    const formatText = escapeHtml(formatLabel);
    const formatFieldLabel = escapeHtml(t("rail.format", { locale }));
    const selectionLabel = escapeHtml(state.review.status === "applied" ? t("review.kept", { locale }) : t("review.selected", { locale }));
    const outputDirLabel = escapeHtml(t("rail.outputDir", { locale }));
    const safeOutputLabel = escapeHtml(outputLabel);
    const openFolderLabel = escapeHtml(t("rail.openFolder", { locale }));
    const openPdfLabel = escapeHtml(t("rail.openPdf", { locale }));
    const copyPathLabel = escapeHtml(t("rail.copyPath", { locale }));
    return `
      <section class="rail-footer rail-footer-actions">
        <p class="rail-footer-label">${exportSettingsLabel}</p>
        <div class="rail-summary-stack">
          <div class="rail-summary-row">
            <span>${formatFieldLabel}</span>
            <strong>${formatText}</strong>
          </div>
          <div class="rail-summary-row">
            <span>${selectionLabel}</span>
            <strong>${selectedCount}</strong>
          </div>
        </div>
        <div class="rail-path-block" data-path-kind="output-dir">
          <span>${outputDirLabel}</span>
          <strong>${safeOutputLabel}</strong>
        </div>
        <button class="rail-action" data-action="open-output-dir" ${state.review.outputDir ? "" : "disabled"}>${openFolderLabel}</button>
        <button class="rail-action rail-action-primary" data-action="open-output-pdf" ${state.review.pdfPath ? "" : "disabled"}>${openPdfLabel}</button>
        <button class="rail-action" data-action="copy-output-dir" ${state.review.outputDir ? "" : "disabled"}>${copyPathLabel}</button>
      </section>
    `;
  }

  const workbenchStatusLabel = escapeHtml(t("rail.workbenchStatus", { locale }));
  const gpuLabel = escapeHtml(t("rail.gpu", { locale }));
  const sourceLabel = escapeHtml(t("rail.source", { locale }));
  const gpuStatus = escapeHtml(state.ui.backend?.ready ? t("rail.active", { locale }) : t("rail.wait", { locale }));
  const sourceStatus = escapeHtml(preparingLabel || (state.source.displayName ? t("rail.loaded", { locale }) : t("rail.idle", { locale })));
  return `
    <section class="rail-footer rail-footer-status">
      <p class="rail-footer-label">${workbenchStatusLabel}</p>
      <div class="rail-footer-row"><span>${gpuLabel}</span><strong>${gpuStatus}</strong></div>
      <div class="rail-footer-row"><span>${sourceLabel}</span><strong>${sourceStatus}</strong></div>
    </section>
  `;
}

export function renderProcessRail(state, items) {
  const locale = state.ui.locale || "en";
  const pipelineLabel = escapeHtml(t("rail.pipeline", { locale }) || PIPELINE);
  return `
    <div class="rail-head">
      <p>${pipelineLabel}</p>
    </div>
    <ol class="process-list">
      ${items.map((item) => `
        <li>
          <button class="process-step ${item.active ? "is-active" : ""} ${item.complete ? "is-complete" : ""}" data-action="open-step" data-step="${item.id}" ${item.active ? 'aria-current="step"' : ""} ${item.enabled ? "" : `disabled aria-disabled="true"`}>
            <span class="process-step-index">${STEP_ICONS[item.id]}</span>
            <span class="process-step-copy">
              <strong>${escapeHtml(t(`step.${item.id}`, { locale }) || STEP_TITLES[item.id])}</strong>
              <small>${escapeHtml(item.summary)}</small>
            </span>
          </button>
        </li>
      `).join("")}
    </ol>
    ${renderRailFooter(state)}
  `;
}
