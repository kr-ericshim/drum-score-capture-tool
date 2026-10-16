import { formatSecondsLabel, hasPendingRoiDraft, isRectValid } from "../../app/session/selectors.js";
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
  const hasPendingDraft = hasPendingRoiDraft(state);
  const durationSec = Number(state.source.metadata?.durationSec || 0);
  const currentTime = Number.isFinite(state.roi.frameTime) ? state.roi.frameTime : 0;

  let statusTone = "idle";
  let statusText = t("roi.status.idle", { locale });
  if (state.roi.status === "loading") {
    statusTone = "loading";
    statusText = t("roi.status.loading", { locale });
  } else if (hasPreview && state.roi.autoRoiStatus === "loading") {
    statusTone = "loading";
    statusText = t("roi.status.autoDetecting", { locale });
  } else if (hasPreview && hasPendingDraft) {
    statusTone = "draft";
    const evidence = state.roi.autoRoiEvidence === "high" ? "High" : "Medium";
    statusText = state.roi.autoRoiStatus === "suggested"
      ? t(`roi.status.autoSuggested${evidence}`, { locale })
      : t("roi.status.draft", { locale });
    if (appliedReady) {
      statusText += getPendingStatusSuffix(locale);
    }
  } else if (hasPreview && appliedReady) {
    statusTone = "ready";
    statusText = t("roi.status.ready", { locale });
  } else if (hasPreview && state.roi.autoRoiStatus === "not_found") {
    statusTone = "idle";
    statusText = t("roi.status.autoNotFound", { locale });
  }

  // Warning for the applied region only, and only for the region the check
  // was run on.
  const clipCheck = state.roi.clipCheck || {};
  const clipWarning = appliedReady && clipCheck.status === "clipped" && clipCheck.rectKey === rectKey(state.roi.appliedRect)
    ? {
      title: t("roi.clip.title", { locale }),
      detail: t("roi.clip.detail", { locale }),
      actionLabel: t("roi.clip.useSuggested", { locale }),
      actionDisabled: !isRectValid(clipCheck.suggestedRect) || rectKey(clipCheck.suggestedRect) === rectKey(state.roi.draftRect),
    }
    : null;

  // Optional section-label area (labels drawn outside the score region).
  const labelMode = state.roi.editTarget === "labels";
  const labelCheck = state.roi.labelCheck || {};
  const labelApplied = isRectValid(state.roi.labelAppliedRect);
  const labelSuggested = appliedReady && labelCheck.status === "suggested" && labelCheck.rectKey === rectKey(state.roi.appliedRect);
  const labelArea = !hasPreview ? null : {
    mode: labelMode ? "editing" : labelApplied ? "applied" : labelSuggested ? "suggested" : "none",
    applyDisabled: !isRectValid(state.roi.labelDraftRect),
    hasApplied: labelApplied,
    canAdd: appliedReady,
  };

  return {
    locale,
    clipWarning,
    labelArea,
    labelMode,
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
    canvasLabel: labelMode ? t("roi.label.canvas", { locale }) : getCanvasLabel(locale),
    placeholderText: t(state.roi.status === "loading" ? "roi.placeholderLoading" : "roi.placeholder", { locale }),
    // the white-edge fit sits folded under "more options"
    moreOpen: Boolean(state.ui.more?.roiOptions),
  };
}

function renderLabelArea(area, locale) {
  if (!area) return "";
  const tt = key => escapeHtml(t(`roi.label.${key}`, { locale }));
  if (area.mode === "editing") {
    return `
      <div class="roi-label-area is-editing" role="group" aria-label="${tt("canvas")}">
        <p class="roi-label-area-text"><strong>${tt("editingTitle")}</strong> ${tt("editingDetail")}</p>
        <div class="roi-label-area-actions">
          <button class="button button-primary" data-action="apply-label-roi" ${area.applyDisabled ? "disabled" : ""}>${tt("apply")}</button>
          ${area.hasApplied ? `<button class="button button-secondary" data-action="remove-label-roi">${tt("remove")}</button>` : ""}
          <button class="button button-secondary" data-action="edit-score-roi">${tt("back")}</button>
        </div>
      </div>`;
  }
  if (area.mode === "applied") {
    return `
      <div class="roi-label-area is-applied" role="status">
        <p class="roi-label-area-text">${tt("applied")}</p>
        <div class="roi-label-area-actions">
          <button class="button button-secondary" data-action="edit-label-roi">${tt("edit")}</button>
          <button class="button button-secondary" data-action="remove-label-roi">${tt("remove")}</button>
        </div>
      </div>`;
  }
  if (area.mode === "suggested") {
    return `
      <div class="roi-label-area is-suggested" role="status">
        <p class="roi-label-area-text"><strong>${tt("foundTitle")}</strong> ${tt("foundDetail")}</p>
        <button class="button button-secondary" data-action="use-suggested-label-roi">${tt("useSuggested")}</button>
      </div>`;
  }
  return area.canAdd ? `<button class="button button-secondary roi-label-add" data-action="edit-label-roi">${tt("addArea")}</button>` : "";
}

export function renderRoiScreen(state) {
  const model = buildRoiScreenModel(state);

  return `
    <section class="screen screen-roi" data-screen="roi" aria-labelledby="roiScreenTitle">
      <header class="screen-headline screen-headline-roi">
        <div><h1 id="roiScreenTitle" data-screen-heading tabindex="-1">${escapeHtml(t("topbar.step.roi", { locale: model.locale }))}</h1>
        <p>${escapeHtml(t("roi.workspaceHelp", { locale: model.locale }))}</p></div>
        <p class="workspace-source-name" title="${escapeHtml(state.source.displayName || "")}">${escapeHtml(state.source.displayName || "")}</p>
      </header>
      <div class="roi-workbench">
      <aside class="roi-controls">
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
        <div class="roi-stage-footer" data-stitch-region="roi-actions">
          ${renderLabelArea(model.labelArea, model.locale)}
          ${model.clipWarning && !model.labelMode ? `
            <div class="roi-clip-warning" role="status">
              <p class="roi-clip-warning-text"><strong>${escapeHtml(model.clipWarning.title)}</strong> ${escapeHtml(model.clipWarning.detail)}</p>
              <button class="button button-secondary roi-clip-warning-action" data-action="use-suggested-roi" ${model.clipWarning.actionDisabled ? "disabled" : ""}>${escapeHtml(model.clipWarning.actionLabel)}</button>
            </div>
          ` : ""}
          <div class="roi-capture-options" ${model.labelMode ? "hidden" : ""}>
            <p class="roi-stage-helper roi-stage-helper-${escapeHtml(model.statusTone)}" aria-live="polite">${state.roi.autoFit ? escapeHtml(t("roi.autoFitHelp", { locale: model.locale })) : model.statusTone === "ready" ? "" : escapeHtml(model.statusText)}</p>
            <button type="button" class="roi-more-toggle" data-action="toggle-more" data-value="roiOptions" aria-expanded="${model.moreOpen}" aria-controls="roiMoreOptions">${escapeHtml(t(model.moreOpen ? "common.less" : "common.more", { locale: model.locale }))}</button>
            <div id="roiMoreOptions" ${model.moreOpen ? "" : "hidden"}>
              <label class="roi-auto-fit-option"><input type="checkbox" data-action="toggle-roi-auto-fit" ${state.roi.autoFit ? "checked" : ""} /> ${escapeHtml(t("roi.autoFit", { locale: model.locale }))}</label>
            </div>
          </div>
          <div class="roi-stage-actions" ${model.labelMode ? "hidden" : ""}>
            ${model.showApplyAction && ["draft", "ready"].includes(model.statusTone) ? `<span class="roi-apply-state is-${model.statusTone}">${escapeHtml(t(`roi.applyState.${model.statusTone}`, { locale: model.locale }))}</span>` : ""}
            ${model.showApplyAction ? `<button class="button button-primary" data-action="apply-roi" ${model.applyDisabled ? "disabled" : ""}>${escapeHtml(t("roi.apply", { locale: model.locale }))}</button>` : ""}
          </div>
        </div>
      </aside>
        <div class="roi-stage-frame">
          <div class="roi-stage-surface" id="appStage">
            ${model.previewImage ? `<img id="roiImage" alt="${escapeHtml(t("roi.previewAlt", { locale: model.locale }))}" src="${escapeHtml(normalizeAssetPath(model.previewImage))}" />` : ""}
            <canvas id="roiCanvas" tabindex="${model.hasPreview ? "0" : "-1"}" aria-label="${escapeHtml(model.canvasLabel)}" aria-describedby="roiCanvasHelp"></canvas>
            <p id="roiCanvasHelp" class="visually-hidden">${escapeHtml(model.canvasHelp)}</p>
            ${model.hasPreview ? "" : `<div class="stage-placeholder"><p>${escapeHtml(model.placeholderText)}</p></div>`}
          </div>
          <input id="roiInput" type="hidden" value="${escapeHtml(state.roi.appliedRect ? JSON.stringify(state.roi.appliedRect) : "")}" />
        </div>
      </div>
    </section>
  `;
}
