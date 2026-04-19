import { isPdfSelected, isRectValid } from "../../app/session/selectors.js";
import { t } from "../../lib/i18n.js";
import { normalizeAssetPath } from "../../lib/paths.js";

function checked(formats, value) {
  return formats.includes(value) ? "checked" : "";
}

function buildProfileRows(state) {
  const locale = state.ui.locale || "en";
  return [
    { label: t("export.captureFps", { locale }), value: "1 FPS" },
    { label: t("export.pageFill", { locale }), value: String(state.exportConfig.pageFillMode || "performance").toUpperCase() },
    { label: t("export.layoutHint", { locale }), value: String(state.exportConfig.layoutHint || "auto").toUpperCase() },
  ];
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
  const progress = Math.round((Number(state.exportConfig.progress || 0)) * 100);
  const fileName = state.source.displayName || t("export.fileNameEmpty", { locale });
  const roiSummary = state.roi.appliedRect ? t("export.roiReady", { locale }) : t("export.roiPending", { locale });
  const hasFormats = Array.isArray(state.exportConfig.formats) && state.exportConfig.formats.length > 0;
  const pdfSelected = isPdfSelected(state.exportConfig.formats);
  const formatsLabel = hasFormats ? state.exportConfig.formats.join(", ").toUpperCase() : t("export.formatsRequired", { locale });
  const canRun = Boolean(state.source.filePath) && Boolean(state.roi.appliedRect) && hasFormats && !running;
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

  return {
    running,
    locale,
    hasFormats,
    canRun,
    progress,
    fileName,
    roiSummary,
    formatsLabel,
    destinationLabel: t("export.destinationLabel", { locale }),
    destinationValue: state.exportConfig.outputDir || t("export.destinationValue", { locale }),
    primaryActionLabel: running
      ? t("export.runBusy", { locale })
      : pdfSelected
        ? t("export.runPdf", { locale })
        : t("export.runDirect", { locale }),
    statusMessage: state.exportConfig.message || t("export.ready", { locale }),
    previewSource,
    cropBounds,
    sourceWidth,
    sourceHeight,
    hasCropPreview,
    previewCaption: state.roi.previewImage
      ? t("export.previewCaptionReady", { locale })
      : t("export.previewCaptionEmpty", { locale }),
    profileRows: buildProfileRows(state),
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
      confirmLabel: t("export.metadata.confirm", { locale }),
      closeLabel: t("export.metadata.close", { locale }),
      discardPrompt: t("export.metadata.discardPrompt", { locale }),
      discardConfirm: t("export.metadata.discardConfirm", { locale }),
      discardCancel: t("export.metadata.discardCancel", { locale }),
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

  return `
    <section class="screen screen-export" data-screen="export">
      <header class="screen-headline screen-headline-export">
        <div>
          <h1>${t("export.title", { locale: model.locale })}</h1>
          <p>${t("export.subtitle", { locale: model.locale })}</p>
        </div>
        <div class="screen-inline-actions">
          <button class="button button-primary" data-action="run-export" ${model.canRun ? "" : "disabled"}>${model.primaryActionLabel}</button>
        </div>
      </header>
      <div class="export-workbench">
        <div class="export-config-stack" data-stitch-region="export-config">
          <section class="panel export-module">
            <div class="panel-heading">
              <h2>${t("export.fileSettings", { locale: model.locale })}</h2>
              <p>${t("export.outputFormat", { locale: model.locale })}</p>
            </div>
            <div class="segmented-row">
              <label class="segment ${checked(state.exportConfig.formats, "pdf") ? "is-active" : ""}">
                <input data-action="toggle-format" data-format="pdf" type="checkbox" ${checked(state.exportConfig.formats, "pdf")} />
                <span>${t("export.pdfDocument", { locale: model.locale })}</span>
              </label>
              <label class="segment ${checked(state.exportConfig.formats, "png") ? "is-active" : ""}">
                <input data-action="toggle-format" data-format="png" type="checkbox" ${checked(state.exportConfig.formats, "png")} />
                <span>${t("export.pngMatrix", { locale: model.locale })}</span>
              </label>
            </div>
            ${model.metadata.helperText ? `<p class="panel-note export-metadata-hint">${model.metadata.helperText}</p>` : ""}
          </section>
          <section class="panel export-module">
            <div class="panel-heading">
              <h2>${t("export.processingProfile", { locale: model.locale })}</h2>
              <p>${t("export.processingProfileHelp", { locale: model.locale })}</p>
            </div>
            <div class="export-profile-list">
              ${model.profileRows.map((item) => `
                <div class="export-profile-row">
                  <span>${item.label}</span>
                  <strong>${item.value}</strong>
                </div>
              `).join("")}
            </div>
          </section>
          <section class="panel export-module">
            <div class="panel-heading">
              <h2>${t("export.outputDirectory", { locale: model.locale })}</h2>
              <p>${model.destinationLabel}</p>
            </div>
            <div class="path-row path-row-static">
              <div class="path-field path-field-wrap">${model.destinationValue}</div>
            </div>
            ${model.hasFormats ? "" : `<p class="panel-note">${t("export.oneFormatRequired", { locale: model.locale })}</p>`}
            ${state.exportConfig.error ? `<p class="inline-error" role="alert">${state.exportConfig.error}</p>` : ""}
          </section>
        </div>
        <section class="export-preview-workbench" data-stitch-region="export-preview">
          <div class="panel-heading export-preview-heading">
            <h2>${t("export.previewTitle", { locale: model.locale })}</h2>
            <p>${model.previewCaption}</p>
          </div>
          <div class="export-progress-strip" role="progressbar" aria-label="${t("export.progressAria", { locale: model.locale })}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${model.progress}">
            <span style="width:${model.progress}%"></span>
          </div>
          <div class="export-preview-stage">
            ${model.previewSource
              ? model.hasCropPreview
                ? `<div class="export-preview-figure export-preview-crop" style="--crop-x:${model.cropBounds.x}; --crop-y:${model.cropBounds.y}; --crop-w:${model.cropBounds.width}; --crop-h:${model.cropBounds.height}; --image-w:${model.sourceWidth}; --image-h:${model.sourceHeight};">
                    <img src="${model.previewSource}" alt="${model.fileName} roi preview" loading="lazy" />
                    <span class="export-preview-badge">${model.roiSummary}</span>
                  </div>`
                : `<div class="export-preview-figure">
                  <img src="${model.previewSource}" alt="${model.fileName} representative frame" loading="lazy" />
                  <span class="export-preview-badge">${model.roiSummary}</span>
                </div>`
              : `<div class="export-preview-empty"><p>${t("export.previewEmpty", { locale: model.locale })}</p></div>`}
          </div>
          <p class="export-preview-note">${model.statusMessage}</p>
        </section>
        ${model.metadata.isOpen ? `
          <div class="export-metadata-overlay">
            <section class="export-metadata-modal export-metadata-sheet" role="dialog" aria-modal="true" aria-labelledby="exportMetadataModalTitle">
              <div class="export-metadata-head">
                <p class="export-metadata-kicker">${t("export.title", { locale: model.locale })}</p>
                <h2 id="exportMetadataModalTitle">${model.metadata.modalTitle}</h2>
                <p class="export-metadata-helper">${model.metadata.helperText}</p>
              </div>
              <div class="export-metadata-rule" aria-hidden="true"></div>
              ${model.metadata.validationSummary ? `<p class="inline-error export-metadata-error" role="alert">${model.metadata.validationSummary}</p>` : ""}
              <div class="export-metadata-grid">
                <div class="export-metadata-row">
                  <label class="export-metadata-field export-metadata-field-full">
                    <span>${model.metadata.titleLabel}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="title"
                      type="text"
                      value="${model.metadata.draft.title}"
                      placeholder="${model.metadata.titlePlaceholder}"
                      autocomplete="off"
                      ${model.metadata.validation.title ? 'aria-invalid="true"' : ""}
                    />
                    ${model.metadata.validation.title ? `<small class="export-metadata-field-error">${model.metadata.validation.title}</small>` : ""}
                  </label>
                </div>
                <div class="export-metadata-row export-metadata-row-split">
                  <label class="export-metadata-field">
                    <span>${model.metadata.performerLabel}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="performer"
                      type="text"
                      value="${model.metadata.draft.performer}"
                      placeholder="${model.metadata.performerPlaceholder}"
                      autocomplete="off"
                    />
                  </label>
                  <label class="export-metadata-field">
                    <span>${model.metadata.bpmLabel}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="bpm"
                      type="text"
                      value="${model.metadata.draft.bpm}"
                      inputmode="numeric"
                      autocomplete="off"
                      ${model.metadata.validation.bpm ? 'aria-invalid="true"' : ""}
                    />
                    ${model.metadata.validation.bpm ? `<small class="export-metadata-field-error">${model.metadata.validation.bpm}</small>` : ""}
                  </label>
                </div>
                <div class="export-metadata-row export-metadata-row-split">
                  <label class="export-metadata-field">
                    <span>${model.metadata.dateLabel}</span>
                    <input
                      data-action="update-export-metadata"
                      data-field="date"
                      type="date"
                      value="${model.metadata.draft.date}"
                    />
                  </label>
                </div>
                <div class="export-metadata-row">
                  <label class="export-metadata-field export-metadata-field-full">
                    <span>${model.metadata.memoLabel}</span>
                    <textarea
                      data-action="update-export-metadata"
                      data-field="memo"
                      rows="2"
                      placeholder="${model.metadata.memoPlaceholder}"
                    >${model.metadata.draft.memo}</textarea>
                  </label>
                </div>
              </div>
              ${model.metadata.showDiscardConfirm ? `
                <div class="export-metadata-discard" role="alert">
                  <p>${model.metadata.discardPrompt}</p>
                  <div class="export-metadata-discard-actions">
                    <button class="button button-secondary" data-action="discard-export-metadata">${model.metadata.discardConfirm}</button>
                    <button class="button button-secondary" data-action="continue-export-metadata">${model.metadata.discardCancel}</button>
                  </div>
                </div>
              ` : ""}
              <div class="export-metadata-actions">
                <button class="button button-primary" data-action="confirm-export-metadata">${model.metadata.confirmLabel}</button>
                <button class="button button-secondary" data-action="close-export-metadata">${model.metadata.closeLabel}</button>
              </div>
            </section>
          </div>
        ` : ""}
      </div>
    </section>
  `;
}
