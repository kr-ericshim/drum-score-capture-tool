import { captureRange } from "./captureRange.js";
import { isPdfSelected, isRectValid } from "../../app/session/selectors.js";
import { escapeAttr, escapeHtml } from "../../lib/html.js";
import { t } from "../../lib/i18n.js";
import { normalizeAssetPath } from "../../lib/paths.js";

function checked(formats, value) {
  return Array.isArray(formats) && formats.includes(value) ? "checked" : "";
}

function clampPercent(progress = 0) {
  const value = Math.round(Number(progress || 0) * 100);
  return Math.max(0, Math.min(100, value));
}

function extractMessagePercent(message = "") {
  const match = String(message || "").match(/frame extraction\s+(\d{1,3})%/i);
  if (!match) {
    return null;
  }
  const percent = Number(match[1]);
  if (!Number.isFinite(percent)) {
    return null;
  }
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function formatExportProgressStatus({ currentStep, message, locale, runStatus }) {
  const step = String(currentStep || "").trim().toLowerCase();
  if (runStatus !== "running" && !step) {
    return message || t("export.ready", { locale });
  }
  const framePercent = extractMessagePercent(message);
  if (step === "extracting" || framePercent !== null) {
    if (framePercent !== null) {
      return t("export.progress.extractingFramesPercent", {
        locale,
        replacements: { percent: framePercent },
      });
    }
    return t("export.progress.extractingFrames", { locale });
  }

  const stepKey = `export.progress.step.${step}`;
  const fallback = t("export.progress.step.default", { locale });
  const label = step ? t(stepKey, { locale }) : fallback;
  return label === stepKey ? fallback : label;
}

function rectToBounds(points) {
  if (!isRectValid(points)) {
    return null;
  }
  const xs = points.map((point) => Number(point[0]));
  const ys = points.map((point) => Number(point[1]));
  return {
    x: Math.min(...xs),
    y: Math.min(...ys),
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
  };
}

export function buildExportScreenModel(state) {
  const locale = state.ui.locale || "en";
  const running = state.exportConfig.runStatus === "running";
  const formats = Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [];
  const progress = clampPercent(state.exportConfig.progress);
  const fileName = state.source.displayName || t("export.fileNameEmpty", { locale });
  const hasValidRoi = isRectValid(state.roi.appliedRect);
  const roiSummary = hasValidRoi ? t("export.roiReady", { locale }) : t("export.roiPending", { locale });
  const hasFormats = formats.length > 0;
  const pdfSelected = isPdfSelected(formats);
  const formatsLabel = hasFormats ? formats.join(", ").toUpperCase() : t("export.formatsRequired", { locale });
  const canRun = Boolean(state.source.filePath) && hasValidRoi && hasFormats && !running && !captureRange(state).error;
  const statusMessage = state.exportConfig.message || t("export.ready", { locale });
  const previewSource = state.roi.previewImage ? normalizeAssetPath(state.roi.previewImage) : "";
  const cropBounds = rectToBounds(state.roi.appliedRect);
  const sourceWidth = Number(state.source.metadata?.width || state.roi.imageWidth || 0);
  const sourceHeight = Number(state.source.metadata?.height || state.roi.imageHeight || 0);
  const metadataModal = state.exportConfig.metadataModal || {
    isOpen: false,
    draft: state.exportConfig.documentHeader || {},
    validation: { title: "", bpm: "" },
    showDiscardConfirm: false,
  };
  const hasCropPreview = Boolean(
    previewSource
    && cropBounds
    && cropBounds.width > 0
    && cropBounds.height > 0
    && sourceWidth > 0
    && sourceHeight > 0
  );

  // Whole-video clipping check of the applied region (started by Apply). Apply
  // moves straight here, so its result must be readable and actionable here.
  const clipCheck = state.roi.clipCheck || {};
  const appliedKey = hasValidRoi ? JSON.stringify(state.roi.appliedRect) : "";
  const clipStatus = hasValidRoi && clipCheck.rectKey === appliedKey ? String(clipCheck.status || "idle") : "idle";
  const clipNote = ["loading", "clipped", "error"].includes(clipStatus) ? {
    status: clipStatus,
    heading: t("export.clip.heading", { locale }),
    title: clipStatus === "loading" ? t("export.clip.loading", { locale })
      : clipStatus === "clipped" ? t("export.clip.title", { locale }) : t("export.clip.error", { locale }),
    detail: clipStatus === "clipped" ? t("export.clip.detail", { locale }) : "",
    action: clipStatus === "clipped" && isRectValid(clipCheck.suggestedRect) ? { id: "use-suggested-roi", label: t("export.clip.useSuggested", { locale }) }
      : clipStatus === "error" ? { id: "recheck-roi", label: t("export.clip.retry", { locale }) } : null,
  } : null;

  // Section labels outside the score region: an applied label area, or a found
  // one the user can load as a draft (never applied automatically).
  const labelCheck = state.roi.labelCheck || {};
  const labelApplied = isRectValid(state.roi.labelAppliedRect);
  const labelFound = hasValidRoi && labelCheck.status === "suggested" && labelCheck.rectKey === appliedKey;
  const labelNote = labelApplied ? { status: "applied", heading: t("export.label.heading", { locale }), title: t("export.label.applied", { locale }), detail: "", action: { id: "edit-label-roi", label: t("roi.label.edit", { locale }) } }
    : labelFound ? { status: "found", heading: t("export.label.heading", { locale }), title: t("roi.label.foundTitle", { locale }), detail: t("roi.label.foundDetail", { locale }), action: { id: "use-suggested-label-roi", label: t("export.label.add", { locale }) } }
      : null;

  // The last run made an incomplete chart (unresolved jump-view ranges): said here too, never as a plain success.
  const reflowInfo = state.review?.reflow || null;
  const incompleteNote = !running && state.exportConfig.runStatus === "done" && reflowInfo?.incomplete ? {
    title: t("export.incompleteTitle", { locale }),
    detail: t(reflowInfo.unresolvedRanges?.length ? "export.incompleteDetail" : "export.incompleteDetailNoRanges", { locale }),
    ranges: (reflowInfo.unresolvedRanges || []).map(range => range.label),
    rangesLabel: t("review.incompleteRangesLabel", { locale, replacements: { count: (reflowInfo.unresolvedRanges || []).length } }),
  } : null;

  return {
    running,
    locale,
    clipNote,
    incompleteNote,
    labelNote,
    hasFormats,
    formats,
    canRun,
    pdfSelected,
    progress,
    fileName,
    roiSummary,
    formatsLabel,
    primaryActionLabel: running
      ? t("export.runBusy", { locale })
      : pdfSelected
        ? t("export.runPdf", { locale })
        : t("export.runDirect", { locale }),
    statusMessage,
    showProgressDetails: running || progress > 0,
    showStatusNote:
      !running
      && Boolean(String(statusMessage || "").trim())
      && String(statusMessage || "").trim() !== t("export.ready", { locale })
      && !(progress > 0 && String(statusMessage || "").trim() === formatExportProgressStatus({
        currentStep: state.exportConfig.currentStep,
        message: statusMessage,
        locale,
        runStatus: state.exportConfig.runStatus,
      })),
    progressStatus: formatExportProgressStatus({
      currentStep: state.exportConfig.currentStep,
      message: statusMessage,
      locale,
      runStatus: state.exportConfig.runStatus,
    }),
    progressLabel: `${progress}%`,
    previewSource,
    cropBounds,
    sourceWidth,
    sourceHeight,
    hasCropPreview,
    previewCaption: state.roi.previewImage
      ? t("export.previewCaptionReady", { locale })
      : t("export.previewCaptionEmpty", { locale }),
    // output formats sit folded under "more options"; PDF is the default
    moreOpen: Boolean(state.ui.more?.exportOptions),
    metadata: {
      isOpen: Boolean(metadataModal.isOpen),
      showDiscardConfirm: Boolean(metadataModal.showDiscardConfirm),
      helperText: pdfSelected ? t("export.metadata.helper", { locale }) : "",
      titleLabel: t("export.metadata.label.title", { locale }),
      performerLabel: t("export.metadata.label.performer", { locale }),
      bpmLabel: t("export.metadata.label.bpm", { locale }),
      dateLabel: t("export.metadata.label.date", { locale }),
      memoLabel: t("export.metadata.label.memo", { locale }),
      titlePlaceholder: t("export.metadata.placeholder.title", { locale }),
      performerPlaceholder: t("export.metadata.placeholder.performer", { locale }),
      memoPlaceholder: t("export.metadata.placeholder.memo", { locale }),
      modalTitle: t("export.metadata.title", { locale }),
      confirmLabel: running ? t("export.metadata.confirmBusy", { locale }) : t("export.metadata.confirm", { locale }),
      closeLabel: t("export.metadata.close", { locale }),
      pendingText: running ? t("export.metadata.pending", { locale }) : "",
      discardPrompt: t("export.metadata.discardPrompt", { locale }),
      discardConfirm: t("export.metadata.discardConfirm", { locale }),
      discardCancel: t("export.metadata.discardCancel", { locale }),
      controlsDisabled: running,
      submitError: metadataModal.isOpen ? String(state.exportConfig.error || "") : "",
      validationSummary:
        metadataModal.validation?.title || metadataModal.validation?.bpm
          ? t("export.metadata.validation.summary", { locale })
          : "",
      validation: {
        title: metadataModal.validation?.title || "",
        bpm: metadataModal.validation?.bpm || "",
      },
      draft: {
        title: String(metadataModal.draft?.title ?? ""),
        performer: String(metadataModal.draft?.performer ?? ""),
        bpm: metadataModal.draft?.bpm === null || metadataModal.draft?.bpm === undefined
          ? ""
          : String(metadataModal.draft.bpm),
        date: String(metadataModal.draft?.date ?? ""),
        memo: String(metadataModal.draft?.memo ?? ""),
      },
    },
  };
}

export function renderExportScreen(state) {
  const model = buildExportScreenModel(state);
  const formatInputsDisabled = model.running || model.metadata.isOpen;
  const safeFileNameAttr = escapeAttr(model.fileName);
  const safeStatusMessage = escapeHtml(model.statusMessage);
  const safeProgressStatus = escapeHtml(model.progressStatus);
  const safeProgressLabel = escapeHtml(model.progressLabel);
  const safePreviewCaption = escapeHtml(model.previewCaption);
  const safePreviewSource = escapeAttr(model.previewSource);
  const safeError = state.exportConfig.error && !model.metadata.isOpen ? escapeHtml(state.exportConfig.error) : "";
  const safeMetadataHelper = escapeHtml(model.metadata.helperText);
  const safeMetadataTitle = escapeHtml(model.metadata.modalTitle);
  const safeMetadataTitleValue = escapeAttr(model.metadata.draft.title);
  const safeMetadataPerformerValue = escapeAttr(model.metadata.draft.performer);
  const safeMetadataBpmValue = escapeAttr(model.metadata.draft.bpm);
  const safeMetadataDateValue = escapeAttr(model.metadata.draft.date);
  const safeMetadataMemoValue = escapeHtml(model.metadata.draft.memo);
  const safeValidationSummary = escapeHtml(model.metadata.validationSummary);
  const safeMetadataSubmitError = escapeHtml(model.metadata.submitError);
  const safeTitleError = escapeHtml(model.metadata.validation.title);
  const safeBpmError = escapeHtml(model.metadata.validation.bpm);
  const safeDiscardPrompt = escapeHtml(model.metadata.discardPrompt);

  return `
    <section class="screen screen-export" data-screen="export" aria-labelledby="exportScreenTitle">
      <header class="screen-headline screen-headline-export">
        <div>
          <h1 id="exportScreenTitle" data-screen-heading tabindex="-1">${t("export.title", { locale: model.locale })}</h1>
          <p>${t("export.subtitle", { locale: model.locale })}</p>
        </div>
        <div class="screen-inline-actions">
          ${state.exportConfig.connectionState && state.exportConfig.connectionState !== "connected" ? `<button class="button button-secondary" data-action="reconnect-job">${t("export.reconnect", { locale: model.locale })}</button>` : ""}
          ${state.exportConfig.runStatus === "running" ? `<button class="button button-secondary" data-action="cancel-job">${t("export.cancel", { locale: model.locale })}</button>` : ""}
          ${model.pdfSelected && !model.running ? `<button class="button button-secondary" data-action="edit-export-metadata" ${model.canRun ? "" : "disabled"}>${t("export.editPdfInfo", { locale: model.locale })}</button>` : ""}
          <button class="button button-primary" data-action="run-export" ${model.canRun ? "" : "disabled"}>${model.primaryActionLabel}</button>
        </div>
      </header>
      <div class="export-workbench">
        <div class="export-config-stack" data-stitch-region="export-config">
          ${model.incompleteNote ? `
          <section class="panel export-module export-clip-note export-incomplete-note is-clipped" aria-labelledby="exportIncompleteHeading">
            <h2 id="exportIncompleteHeading" class="visually-hidden">${escapeHtml(model.incompleteNote.title)}</h2>
            <p class="export-clip-text" role="alert"><strong>${escapeHtml(model.incompleteNote.title)}</strong> ${escapeHtml(model.incompleteNote.detail)}</p>
            ${model.incompleteNote.ranges.length ? `<ul class="export-coverage-ranges" aria-label="${escapeAttr(model.incompleteNote.rangesLabel)}" ${model.incompleteNote.ranges.length > 4 ? 'tabindex="0"' : ""}>
              ${model.incompleteNote.ranges.map(label => `<li>${escapeHtml(label)}</li>`).join("")}
            </ul>` : ""}
          </section>` : ""}
          ${model.clipNote ? `
          <section class="panel export-module export-clip-note is-${escapeAttr(model.clipNote.status)}" aria-labelledby="exportClipHeading">
            <h2 id="exportClipHeading" class="visually-hidden">${escapeHtml(model.clipNote.heading)}</h2>
            <p class="export-clip-text" role="${model.clipNote.status === "loading" ? "status" : "alert"}"><strong>${escapeHtml(model.clipNote.title)}</strong>${model.clipNote.detail ? ` ${escapeHtml(model.clipNote.detail)}` : ""}</p>
            ${model.clipNote.action ? `<button class="button button-secondary export-clip-action" data-action="${escapeAttr(model.clipNote.action.id)}" ${model.running ? "disabled" : ""}>${escapeHtml(model.clipNote.action.label)}</button>` : ""}
          </section>` : ""}
          ${model.labelNote ? `
          <section class="panel export-module export-label-note is-${escapeAttr(model.labelNote.status)}" aria-labelledby="exportLabelHeading">
            <h2 id="exportLabelHeading" class="visually-hidden">${escapeHtml(model.labelNote.heading)}</h2>
            <p class="export-clip-text" role="status"><strong>${escapeHtml(model.labelNote.title)}</strong>${model.labelNote.detail ? ` ${escapeHtml(model.labelNote.detail)}` : ""}</p>
            <button class="button button-secondary export-clip-action" data-action="${escapeAttr(model.labelNote.action.id)}" ${model.running ? "disabled" : ""}>${escapeHtml(model.labelNote.action.label)}</button>
          </section>` : ""}
          <section class="panel export-module">
            <div class="panel-heading"><h2>${t("export.range.title", { locale: model.locale })}</h2></div>
            <div class="capture-range-fields">
              ${["rangeStart", "rangeEnd"].map(field => `<label class="capture-range-field">
                <span>${t(`export.range.${field}`, { locale: model.locale })}</span>
                <input type="text" data-action="capture-range" data-field="${field}" value="${escapeAttr(state.exportConfig[field] || "")}" placeholder="${field === "rangeStart" ? "0:00" : t("export.range.endPlaceholder", { locale: model.locale })}" maxlength="24" spellcheck="false" autocomplete="off" aria-describedby="captureRangeHelp${captureRange(state).error ? ' captureRangeError' : ''}" ${captureRange(state).error ? 'aria-invalid="true"' : ''} ${formatInputsDisabled ? "disabled" : ""} />
              </label>`).join("")}
            </div>
            <p id="captureRangeHelp" class="panel-note">${t("export.range.help", { locale: model.locale })}</p>
            ${captureRange(state).error ? `<p id="captureRangeError" class="inline-error" role="alert">${t(`export.range.error.${captureRange(state).error}`, { locale: model.locale })}</p>` : ""}
          </section>
          <section class="panel export-module export-more-module">
            <button type="button" class="export-more-toggle" data-action="toggle-more" data-value="exportOptions" aria-expanded="${model.moreOpen}" aria-controls="exportMoreOptions">${t(model.moreOpen ? "common.less" : "common.more", { locale: model.locale })}</button>
            <div id="exportMoreOptions" class="export-more-body" ${model.moreOpen ? "" : "hidden"}>
              <div class="panel-heading"><h2>${t("export.outputFormat", { locale: model.locale })}</h2></div>
              <div class="segmented-row">
                <label class="segment ${checked(model.formats, "pdf") ? "is-active" : ""}">
                  <input data-action="toggle-format" data-format="pdf" type="checkbox" ${checked(model.formats, "pdf")} ${formatInputsDisabled ? "disabled" : ""} aria-labelledby="exportFormatPdfLabel" ${checked(model.formats, "pdf") ? 'aria-describedby="exportPdfHint"' : ""} />
                  <span><span id="exportFormatPdfLabel">${t("export.pdfDocument", { locale: model.locale })}</span>${checked(model.formats, "pdf") ? `<small id="exportPdfHint" class="export-format-hint">${t("export.pdfMetadataHint", { locale: model.locale })}</small>` : ""}</span>
                </label>
                <label class="segment ${checked(model.formats, "png") ? "is-active" : ""}">
                  <input data-action="toggle-format" data-format="png" type="checkbox" ${checked(model.formats, "png")} ${formatInputsDisabled ? "disabled" : ""} />
                  <span>${t("export.pngMatrix", { locale: model.locale })}</span>
                </label>
                <label class="segment ${checked(model.formats, "jpg") ? "is-active" : ""}">
                  <input data-action="toggle-format" data-format="jpg" type="checkbox" ${checked(model.formats, "jpg")} ${formatInputsDisabled ? "disabled" : ""} />
                  <span>${t("export.jpgImages", { locale: model.locale })}</span>
                </label>
              </div>
            </div>
            ${model.hasFormats ? "" : `<p class="panel-note">${t("export.oneFormatRequired", { locale: model.locale })}</p>`}
            ${safeError ? `<p class="inline-error" role="alert">${safeError}</p>` : ""}
          </section>
        </div>
        <section class="export-preview-workbench" data-stitch-region="export-preview">
          <div class="panel-heading export-preview-heading">

            <h2>${t("export.previewTitle", { locale: model.locale })}</h2>
            ${model.previewCaption === t("export.previewCaptionReady", { locale: model.locale }) ? "" : `<p>${safePreviewCaption}</p>`}
          </div>
          ${model.showProgressDetails ? `
            <div class="export-progress-card">
            <div class="export-progress-summary" role="status" aria-live="polite">
              <span>${safeProgressStatus}</span>
              <strong>${safeProgressLabel}</strong>
            </div>
            <div class="export-progress-strip" role="progressbar" aria-label="${t("export.progressAria", { locale: model.locale })}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${model.progress}">
              <span style="width:${model.progress}%"></span>
            </div>
            </div>
          ` : ""}
          <div class="export-preview-stage">
            ${model.previewSource
              ? model.hasCropPreview
                ? `<div class="export-preview-figure export-preview-crop" style="--crop-x:${model.cropBounds.x}; --crop-y:${model.cropBounds.y}; --crop-w:${model.cropBounds.width}; --crop-h:${model.cropBounds.height}; --image-w:${model.sourceWidth}; --image-h:${model.sourceHeight};">
                    <img src="${safePreviewSource}" alt="${safeFileNameAttr} score region preview" loading="lazy" />
                  </div>`
                : `<div class="export-preview-figure">
                  <img src="${safePreviewSource}" alt="${safeFileNameAttr} representative frame" loading="lazy" />
                </div>`
              : `<div class="export-preview-empty"><p>${t("export.previewEmpty", { locale: model.locale })}</p></div>`}
          </div>
          ${model.showStatusNote ? `<p class="export-preview-note">${safeStatusMessage}</p>` : ""}
        </section>
        ${model.metadata.isOpen ? `
          <div class="export-metadata-overlay">
            <section class="export-metadata-modal export-metadata-sheet" role="dialog" aria-modal="true" aria-labelledby="exportMetadataModalTitle">
              <div class="export-metadata-head">

                <h2 id="exportMetadataModalTitle">${safeMetadataTitle}</h2>
                <p class="export-metadata-helper">${safeMetadataHelper}</p>
              </div>
              <div class="export-metadata-rule" aria-hidden="true"></div>
              ${model.metadata.pendingText ? `<p class="export-metadata-pending" role="status">${escapeHtml(model.metadata.pendingText)}</p>` : ""}
              ${model.metadata.submitError ? `<p class="inline-error export-metadata-submit-error" role="alert">${safeMetadataSubmitError}</p>` : ""}
              ${model.metadata.validationSummary ? `<p class="inline-error export-metadata-error" role="alert">${safeValidationSummary}</p>` : ""}
              <div class="export-metadata-grid">
                <div class="export-metadata-row">
                  <label class="export-metadata-field export-metadata-field-full">
                    <span>${escapeHtml(model.metadata.titleLabel)}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="title"
                      type="text"
                      value="${safeMetadataTitleValue}"
                      placeholder="${escapeAttr(model.metadata.titlePlaceholder)}"
                      autocomplete="off"
                      ${model.metadata.validation.title ? 'aria-invalid="true"' : ""}
                    />
                    ${model.metadata.validation.title ? `<small class="export-metadata-field-error">${safeTitleError}</small>` : ""}
                  </label>
                </div>
                <div class="export-metadata-row export-metadata-row-split">
                  <label class="export-metadata-field">
                    <span>${escapeHtml(model.metadata.performerLabel)}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="performer"
                      type="text"
                      value="${safeMetadataPerformerValue}"
                      placeholder="${escapeAttr(model.metadata.performerPlaceholder)}"
                      autocomplete="off"
                    />
                  </label>
                  <label class="export-metadata-field">
                    <span>${escapeHtml(model.metadata.bpmLabel)}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="bpm"
                      type="text"
                      value="${safeMetadataBpmValue}"
                      inputmode="numeric"
                      autocomplete="off"
                      ${model.metadata.validation.bpm ? 'aria-invalid="true"' : ""}
                    />
                    ${model.metadata.validation.bpm ? `<small class="export-metadata-field-error">${safeBpmError}</small>` : ""}
                  </label>
                </div>
                <div class="export-metadata-row">
                  <label class="export-metadata-field">
                    <span>${escapeHtml(model.metadata.dateLabel)}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="date"
                      type="date"
                      value="${safeMetadataDateValue}"
                    />
                  </label>
                </div>
                <div class="export-metadata-row">
                  <label class="export-metadata-field export-metadata-field-full">
                    <span>${escapeHtml(model.metadata.memoLabel)}</span>
                    <textarea
                      data-action="update-export-metadata"
                      data-field="memo"
                      rows="2"
                      placeholder="${escapeAttr(model.metadata.memoPlaceholder)}"
                    >${safeMetadataMemoValue}</textarea>
                  </label>
                </div>
              </div>
              ${model.metadata.showDiscardConfirm ? `
                <div class="export-metadata-discard" role="alert">
                  <p>${safeDiscardPrompt}</p>
                  <div class="export-metadata-discard-actions">
                    <button class="button button-secondary" data-action="discard-export-metadata" ${model.metadata.controlsDisabled ? "disabled" : ""}>${escapeHtml(model.metadata.discardConfirm)}</button>
                    <button class="button button-secondary" data-action="continue-export-metadata" ${model.metadata.controlsDisabled ? "disabled" : ""}>${escapeHtml(model.metadata.discardCancel)}</button>
                  </div>
                </div>
              ` : ""}
              <div class="export-metadata-actions">
                <button class="button button-secondary" data-action="close-export-metadata" ${model.metadata.controlsDisabled ? "disabled" : ""}>${model.metadata.closeLabel}</button>
                <button class="button button-primary" data-action="confirm-export-metadata" ${model.metadata.controlsDisabled ? "disabled" : ""}>${model.metadata.confirmLabel}</button>
              </div>
            </section>
          </div>
        ` : ""}
      </div>
    </section>
  `;
}
