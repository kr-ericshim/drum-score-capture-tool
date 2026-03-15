import { formatSecondsLabel, isRectValid } from "../../app/session/selectors.js";
import { t } from "../../lib/i18n.js";
import { normalizeAssetPath } from "../../lib/paths.js";

export function buildRoiScreenModel(state) {
  const locale = state.ui.locale || "en";
  const hasSource = Boolean(state.source.filePath);
  const hasPreview = Boolean(state.roi.previewImage);
  const draftReady = isRectValid(state.roi.draftRect);
  const appliedReady = isRectValid(state.roi.appliedRect);
  const durationSec = Number(state.source.metadata?.durationSec || 0);
  const currentTime = Number.isFinite(state.roi.frameTime) ? state.roi.frameTime : 0;

  let statusTone = "idle";
  let statusText = t("roi.status.idle", { locale });
  if (hasPreview && draftReady && !appliedReady) {
    statusTone = "draft";
    statusText = t("roi.status.draft", { locale });
  } else if (hasPreview && appliedReady) {
    statusTone = "ready";
    statusText = t("roi.status.ready", { locale });
  }

  return {
    locale,
    durationSec,
    frameTime: currentTime,
    frameTimeLabel: state.roi.frameTimeLabel || formatSecondsLabel(currentTime),
    loadFrameDisabled: !hasSource || state.roi.status === "loading",
    applyDisabled: !draftReady,
    hasPreview,
    statusTone,
    statusText,
    previewImage: state.roi.previewImage,
    showApplyAction: hasPreview,
  };
}

export function renderRoiScreen(state) {
  const model = buildRoiScreenModel(state);

  return `
    <section class="screen screen-roi" data-screen="roi">
      <div class="roi-workbench">
        <div class="roi-toolbar" data-stitch-region="roi-toolbar">
          <label class="roi-slider-row">
            <span>${t("roi.frame", { locale: model.locale })}</span>
            <input id="frameTimeSlider" type="range" min="0" max="${Math.max(0, model.durationSec)}" step="0.5" value="${model.frameTime}" ${model.durationSec ? "" : "disabled"} />
            <strong id="frameTimeValue">${model.frameTimeLabel}</strong>
          </label>
          <button class="button button-secondary roi-toolbar-action" data-action="load-preview-frame" ${model.loadFrameDisabled ? "disabled" : ""}>${t("roi.loadFrame", { locale: model.locale })}</button>
        </div>
        <div class="roi-stage-frame">
          <div class="roi-stage-surface" id="appStage">
            ${model.previewImage ? `<img id="roiImage" alt="${t("roi.previewAlt", { locale: model.locale })}" src="${normalizeAssetPath(model.previewImage)}" />` : ""}
            <canvas id="roiCanvas"></canvas>
            ${model.hasPreview ? "" : `<div class="stage-placeholder"><p>${t("roi.placeholder", { locale: model.locale })}</p></div>`}
          </div>
          <input id="roiInput" type="hidden" value="${state.roi.appliedRect ? JSON.stringify(state.roi.appliedRect) : ""}" />
        </div>
        <div class="roi-stage-footer" data-stitch-region="roi-actions">
          <p class="roi-stage-helper roi-stage-helper-${model.statusTone}">${model.statusText}</p>
          <div class="roi-stage-actions">
            ${model.showApplyAction ? `<button class="button button-primary" data-action="apply-roi" ${model.applyDisabled ? "disabled" : ""}>${t("roi.apply", { locale: model.locale })}</button>` : ""}
          </div>
        </div>
      </div>
    </section>
  `;
}
