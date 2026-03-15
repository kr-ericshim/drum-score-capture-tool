import { isRectValid } from "../../app/session/selectors.js";
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
  const formatsLabel = hasFormats ? state.exportConfig.formats.join(", ").toUpperCase() : t("export.formatsRequired", { locale });
  const canRun = Boolean(state.source.filePath) && Boolean(state.roi.appliedRect) && hasFormats && !running;
  const previewSource = state.roi.previewImage ? normalizeAssetPath(state.roi.previewImage) : "";
  const cropBounds = rectToBounds(state.roi.appliedRect);
  const sourceWidth = Number(state.source.metadata?.width || state.roi.imageWidth || 0);
  const sourceHeight = Number(state.source.metadata?.height || state.roi.imageHeight || 0);
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
    primaryActionLabel: running ? t("export.runBusy", { locale }) : t("export.run", { locale }),
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
      </div>
    </section>
  `;
}
