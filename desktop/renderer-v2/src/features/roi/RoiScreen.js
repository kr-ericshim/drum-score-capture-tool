import { formatSecondsLabel, isRectValid } from "../../app/session/selectors.js";
import { t } from "../../lib/i18n.js";
import { normalizeAssetPath } from "../../lib/paths.js";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function rectKey(rect) {
  return isRectValid(rect) ? JSON.stringify(rect) : "";
}

function getPendingStatusSuffix(locale) {
  if (locale === "ko") {
    return " 현재 변경 내용은 아직 적용되지 않았습니다.";
  }
  return " There are pending changes that still need to be applied.";
}

function getCanvasHelp(locale) {
  if (locale === "ko") {
    return "Tab으로 영역 편집 캔버스에 포커스한 뒤, 방향키로 영역을 이동하세요. 1에서 4까지 숫자 키로 모서리를 선택하고, 0 키로 전체 이동으로 돌아갈 수 있습니다. Shift를 함께 누르면 더 크게 조절합니다.";
  }
  return "Tab to the score-region canvas, then use the arrow keys to move the region. Press 1 through 4 to pick a corner handle, press 0 to switch back to moving the whole region, and hold Shift for larger adjustments.";
}

function getCanvasLabel(locale) {
  if (locale === "ko") {
    return "악보 영역 편집 캔버스";
  }
  return "Score-region editor canvas";
}

export function buildRoiScreenModel(state) {
  const locale = state.ui.locale || "en";
  const hasSource = Boolean(state.source.filePath);
  const hasPreview = Boolean(state.roi.previewImage);
  const previewCandidates = Array.isArray(state.roi.previewCandidates) ? state.roi.previewCandidates : [];
  const draftReady = isRectValid(state.roi.draftRect);
  const appliedReady = isRectValid(state.roi.appliedRect);
  const hasPendingDraft = draftReady && (!appliedReady || rectKey(state.roi.draftRect) !== rectKey(state.roi.appliedRect));
  const durationSec = Number(state.source.metadata?.durationSec || 0);
  const currentTime = Number.isFinite(state.roi.frameTime) ? state.roi.frameTime : 0;

  let statusTone = "idle";
  let statusText = t("roi.status.idle", { locale });
  if (state.roi.status === "loading") {
    statusTone = "loading";
    statusText = t("roi.status.loading", { locale });
  } else if (hasPreview && hasPendingDraft) {
    statusTone = "draft";
    statusText = t("roi.status.draft", { locale });
    if (appliedReady) {
      statusText += getPendingStatusSuffix(locale);
    }
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
    previewCandidates: previewCandidates.map((candidate, index) => ({
      ...candidate,
      title: t(index === 0 ? "roi.candidateEarlier" : index === 1 ? "roi.candidateRecommended" : "roi.candidateLater", { locale }),
      active: candidate.id === state.roi.selectedPreviewCandidateId,
    })),
    applyDisabled: !draftReady || !hasPendingDraft,
    hasPreview,
    statusTone,
    statusText,
    previewImage: state.roi.previewImage,
    showApplyAction: hasPreview,
    canvasHelp: getCanvasHelp(locale),
    canvasLabel: getCanvasLabel(locale),
    placeholderText: t(state.roi.status === "loading" ? "roi.placeholderLoading" : "roi.placeholder", { locale }),
  };
}

export function renderRoiScreen(state) {
  const model = buildRoiScreenModel(state);

  return `
    <section class="screen screen-roi" data-screen="roi" aria-labelledby="roiScreenTitle">
      <h1 id="roiScreenTitle" class="visually-hidden" data-screen-heading tabindex="-1">${escapeHtml(t("topbar.step.roi", { locale: model.locale }))}</h1>
      <div class="roi-workbench">
        <div class="roi-toolbar" data-stitch-region="roi-toolbar">
          <label class="roi-slider-row">
            <span>${escapeHtml(t("roi.frame", { locale: model.locale }))}</span>
            <input id="frameTimeSlider" type="range" min="0" max="${escapeHtml(Math.max(0, model.durationSec))}" step="0.5" value="${escapeHtml(model.frameTime)}" ${model.durationSec ? "" : "disabled"} />
            <strong id="frameTimeValue">${escapeHtml(model.frameTimeLabel)}</strong>
          </label>
          <button class="button button-secondary roi-toolbar-action" data-action="load-preview-frame" ${model.loadFrameDisabled ? "disabled" : ""}>${escapeHtml(t("roi.loadFrame", { locale: model.locale }))}</button>
        </div>
        ${model.previewCandidates.length ? `
          <div class="roi-candidate-strip" data-stitch-region="roi-candidates">
            <p class="roi-candidate-heading">${escapeHtml(t("roi.candidatesTitle", { locale: model.locale }))}</p>
            <div class="roi-candidate-list" role="group" aria-label="${escapeHtml(t("roi.candidatesTitle", { locale: model.locale }))}">
              ${model.previewCandidates.map((candidate) => `
                <button
                  class="roi-candidate ${candidate.active ? "is-active" : ""}"
                  data-action="select-preview-candidate"
                  data-candidate-id="${escapeHtml(candidate.id)}"
                  aria-pressed="${candidate.active ? "true" : "false"}"
                >
                  <span class="roi-candidate-kicker">${escapeHtml(candidate.title)}</span>
                  <strong>${escapeHtml(candidate.label)}</strong>
                </button>
              `).join("")}
            </div>
          </div>
        ` : ""}
        <div class="roi-stage-frame">
          <div class="roi-stage-surface" id="appStage">
            ${model.previewImage ? `<img id="roiImage" alt="${escapeHtml(t("roi.previewAlt", { locale: model.locale }))}" src="${escapeHtml(normalizeAssetPath(model.previewImage))}" />` : ""}
            <canvas id="roiCanvas" tabindex="${model.hasPreview ? "0" : "-1"}" aria-label="${escapeHtml(model.canvasLabel)}" aria-describedby="roiCanvasHelp"></canvas>
            <p id="roiCanvasHelp" class="visually-hidden">${escapeHtml(model.canvasHelp)}</p>
            ${model.hasPreview ? "" : `<div class="stage-placeholder"><p>${escapeHtml(model.placeholderText)}</p></div>`}
          </div>
          <input id="roiInput" type="hidden" value="${escapeHtml(state.roi.appliedRect ? JSON.stringify(state.roi.appliedRect) : "")}" />
        </div>
        <div class="roi-stage-footer" data-stitch-region="roi-actions">
          <p class="roi-stage-helper roi-stage-helper-${escapeHtml(model.statusTone)}" aria-live="polite">${escapeHtml(model.statusText)}</p>
          <div class="roi-stage-actions">
            ${model.showApplyAction ? `<button class="button button-primary" data-action="apply-roi" ${model.applyDisabled ? "disabled" : ""}>${escapeHtml(t("roi.apply", { locale: model.locale }))}</button>` : ""}
          </div>
        </div>
      </div>
    </section>
  `;
}
