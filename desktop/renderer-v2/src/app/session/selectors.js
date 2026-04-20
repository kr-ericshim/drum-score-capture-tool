import { normalizeAssetPath } from "../../lib/paths.js";
import { DEFAULT_FORMATS, STEP_ORDER } from "../types.js";
import { detectInitialLocale, t } from "../../lib/i18n.js";

function fileBaseName(filePath = "") {
  const normalized = String(filePath || "").replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  return normalized.split("/").pop() || normalized;
}

function fileTitleFromPath(filePath = "") {
  const baseName = fileBaseName(filePath).trim();
  if (!baseName) {
    return "";
  }
  if (baseName.startsWith(".") && !baseName.slice(1).includes(".")) {
    return baseName;
  }
  return baseName.replace(/\.[^.]+$/, "");
}

function padDatePart(value) {
  return String(value).padStart(2, "0");
}

function formatDocumentDate(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return formatDocumentDate(new Date());
  }
  return `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}`;
}

function hasOwnValue(target, key) {
  return Boolean(target) && Object.prototype.hasOwnProperty.call(target, key);
}

function normalizeUnicodeText(value) {
  return String(value ?? "").normalize("NFC");
}

function normalizeOptionalText(value) {
  return normalizeUnicodeText(value).trim();
}

function compareableHeaderValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return normalizeUnicodeText(value);
}

function normalizeBpmValue(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const text = String(value).trim();
  if (!text) {
    return null;
  }
  const parsed = Number.parseInt(text, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export function createDocumentHeaderState(sourceFilePath = "", today = new Date()) {
  return {
    title: fileTitleFromPath(sourceFilePath),
    performer: "",
    bpm: null,
    date: formatDocumentDate(today),
    memo: "",
  };
}

export function normalizeDocumentHeader(documentHeader = {}, fallbackHeader = createDocumentHeaderState()) {
  const fallback = {
    title: normalizeOptionalText(fallbackHeader.title),
    performer: normalizeOptionalText(fallbackHeader.performer),
    bpm: normalizeBpmValue(fallbackHeader.bpm),
    date: normalizeOptionalText(fallbackHeader.date),
    memo: normalizeOptionalText(fallbackHeader.memo),
  };
  const normalizedTitle = hasOwnValue(documentHeader, "title")
    ? normalizeOptionalText(documentHeader.title)
    : fallback.title;

  return {
    title: normalizedTitle || fallback.title,
    performer: hasOwnValue(documentHeader, "performer")
      ? normalizeOptionalText(documentHeader.performer)
      : fallback.performer,
    bpm: hasOwnValue(documentHeader, "bpm")
      ? normalizeBpmValue(documentHeader.bpm)
      : fallback.bpm,
    date: hasOwnValue(documentHeader, "date")
      ? normalizeOptionalText(documentHeader.date)
      : fallback.date,
    memo: hasOwnValue(documentHeader, "memo")
      ? normalizeOptionalText(documentHeader.memo)
      : fallback.memo,
  };
}

export function sanitizeDocumentHeaderDraftField(field, value) {
  if (field === "bpm") {
    return String(value ?? "").replace(/\D/g, "");
  }
  return normalizeUnicodeText(value);
}

export function isPdfSelected(formats = []) {
  return Array.isArray(formats) && formats.includes("pdf");
}

export function isExportMetadataDirty(draft = {}, confirmed = {}) {
  return compareableHeaderValue(draft.title) !== compareableHeaderValue(confirmed.title)
    || compareableHeaderValue(draft.performer) !== compareableHeaderValue(confirmed.performer)
    || compareableHeaderValue(draft.bpm) !== compareableHeaderValue(confirmed.bpm)
    || compareableHeaderValue(draft.date) !== compareableHeaderValue(confirmed.date)
    || compareableHeaderValue(draft.memo) !== compareableHeaderValue(confirmed.memo);
}

export function validateExportMetadataDraft(draft = {}, locale = "en") {
  const title = normalizeOptionalText(draft.title);
  const bpm = compareableHeaderValue(draft.bpm).trim();
  return {
    title: title ? "" : t("export.metadata.validation.titleRequired", { locale }),
    bpm: !bpm || /^\d+$/.test(bpm) ? "" : t("export.metadata.validation.bpmDigits", { locale }),
  };
}

export function createExportMetadataModalState(
  sourceFilePath = "",
  today = new Date(),
  documentHeader = createDocumentHeaderState(sourceFilePath, today),
) {
  const fallbackHeader = createDocumentHeaderState(sourceFilePath, today);
  const confirmed = normalizeDocumentHeader(documentHeader, fallbackHeader);
  return {
    isOpen: false,
    draft: {
      ...confirmed,
    },
    dirty: false,
    validation: {
      title: "",
      bpm: "",
    },
    showDiscardConfirm: false,
  };
}

export function createInitialExportConfig(sourceFilePath = "", today = new Date()) {
  const documentHeader = createDocumentHeaderState(sourceFilePath, today);
  return {
    formats: DEFAULT_FORMATS.slice(),
    outputDir: "",
    pageFillMode: "performance",
    layoutHint: "auto",
    jobId: "",
    runStatus: "idle",
    progress: 0,
    currentStep: "",
    message: "",
    pdfPath: "",
    error: "",
    documentHeader,
    metadataModal: createExportMetadataModalState(sourceFilePath, today, documentHeader),
  };
}

function normalizedPrepareProgress(value) {
  const progress = Number(value || 0);
  if (!Number.isFinite(progress)) {
    return 0;
  }
  return Math.max(0, Math.min(1, progress));
}

function preparePercentLabel(progress) {
  return `${Math.round(normalizedPrepareProgress(progress) * 100)}%`;
}

function roundToHalfSecond(value) {
  return Math.round(Number(value || 0) * 2) / 2;
}

function clampFrameSecond(value, durationSec) {
  if (!Number.isFinite(durationSec) || durationSec <= 0) {
    return roundToHalfSecond(value);
  }
  return Math.max(0, Math.min(roundToHalfSecond(value), roundToHalfSecond(durationSec)));
}

export function buildRepresentativeFrameCandidates(durationSec) {
  const duration = Number(durationSec || 0);
  const defaultCandidates = [0, 5, 10];
  const rawTimes = Number.isFinite(duration) && duration > 0
    ? duration <= 12
      ? [0, duration * 0.45, Math.max(duration * 0.85, duration - 0.5)]
      : [duration * 0.2, duration * 0.33, duration * 0.5]
    : defaultCandidates;
  const maxDuration = Number.isFinite(duration) && duration > 0 ? duration : null;
  const normalizedTimes = [];
  rawTimes.forEach((value, index) => {
    let nextValue = clampFrameSecond(value, maxDuration);
    if (index > 0 && nextValue <= normalizedTimes[index - 1]) {
      nextValue = clampFrameSecond(normalizedTimes[index - 1] + 0.5, maxDuration);
    }
    normalizedTimes.push(nextValue);
  });

  return normalizedTimes.map((sec, index) => ({
    id: `preview-candidate-${index + 1}`,
    sec,
    label: formatSecondsLabel(sec),
    tone: index === 1 ? "recommended" : "alternate",
  }));
}

function isPrepareActive(source = {}) {
  return source.prepareStatus === "loading";
}

export function getSourcePrepareSummary(state, locale = state?.ui?.locale || "en") {
  const source = state?.source || {};
  if (!isPrepareActive(source)) {
    return "";
  }
  const stage = String(source.prepareStage || "queued");
  const stageLabel = t(`source.prepareStage.${stage}`, { locale });
  if (source.prepareProgressMode === "determinate") {
    return t("source.prepareStageProgress", {
      locale,
      replacements: {
        stage: stageLabel,
        percent: preparePercentLabel(source.prepareProgress),
      },
    });
  }
  return stageLabel;
}

function rectBounds(points) {
  const xs = points.map((point) => Number(point[0]));
  const ys = points.map((point) => Number(point[1]));
  return {
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
  };
}

export function createInitialSessionState() {
  return {
    source: {
      sourceType: "file",
      filePath: "",
      displayName: "",
      archiveSourceKind: "",
      archiveSourceKey: "",
      archiveDisplayName: "",
      metadata: null,
      status: "idle",
      error: "",
      youtubeUrl: "",
      preparedFromYouTube: false,
      prepareStatus: "idle",
      prepareJobId: "",
      prepareStage: "",
      prepareProgress: 0,
      prepareProgressMode: "indeterminate",
      prepareMessage: "",
      prepareFromCache: false,
      prepareLogs: [],
      preparedVideoPath: "",
      prepareErrorDetail: "",
      registryItems: [],
    },
    roi: {
      frameTime: null,
      frameTimeLabel: "00:00.0",
      previewCandidates: [],
      selectedPreviewCandidateId: "",
      previewImage: "",
      previewSourcePath: "",
      diagnostics: [],
      draftRect: null,
      appliedRect: null,
      imageWidth: 0,
      imageHeight: 0,
      status: "idle",
      error: "",
    },
    exportConfig: createInitialExportConfig(),
    review: {
      pages: [],
      selectedPageIds: [],
      focusedPageId: "",
      status: "idle",
      error: "",
      keptCount: 0,
      outputDir: "",
      pdfPath: "",
    },
    archive: {
      isOpen: false,
      status: "idle",
      items: [],
      error: "",
      selectedSourceKey: "",
    },
    ui: {
      locale: detectInitialLocale(),
      activeStep: "source",
      busyAction: "",
      blockingReason: "",
      inlineNotice: "",
      backend: {
        ready: false,
        starting: true,
        running: false,
        error: "",
      },
    },
  };
}

export function isRectValid(points) {
  if (!Array.isArray(points) || points.length !== 4) {
    return false;
  }
  return points.every((point) => Array.isArray(point) && point.length === 2 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])));
}

export function inferLayoutHintFromRoi(points) {
  if (!isRectValid(points)) {
    return "full_scroll";
  }
  const { width, height } = rectBounds(points);
  if (width <= 0 || height <= 0) {
    return "full_scroll";
  }
  const aspect = width / height;
  if (aspect >= 2.25) {
    return "bottom_bar";
  }
  if (aspect <= 1.05) {
    return "page_turn";
  }
  return "full_scroll";
}

function hasPendingRoiDraft(state) {
  if (!isRectValid(state?.roi?.draftRect)) {
    return false;
  }
  if (!isRectValid(state?.roi?.appliedRect)) {
    return true;
  }
  return JSON.stringify(state.roi.draftRect) !== JSON.stringify(state.roi.appliedRect);
}

export function getStepState(state, step) {
  const locale = state.ui.locale || "en";
  const sourceReady = Boolean(state.source.filePath);
  const roiDirty = hasPendingRoiDraft(state);
  const roiReady = sourceReady && Number.isFinite(state.roi.frameTime) && isRectValid(state.roi.appliedRect) && !roiDirty;
  const exportReady = Boolean(state.exportConfig.jobId) && state.exportConfig.runStatus === "done" && state.review.pages.length > 0;
  const reviewReady = state.exportConfig.runStatus === "done" && state.review.pages.length > 0;

  switch (step) {
    case "source":
      return {
        enabled: true,
        complete: sourceReady,
        blockingReason: "",
      };
    case "roi":
      return {
        enabled: sourceReady,
        complete: roiReady,
        blockingReason: !sourceReady
          ? t("selector.blocking.sourceRequired", { locale })
          : roiDirty
            ? t("selector.blocking.roiDirty", { locale })
            : "",
      };
    case "export":
      return {
        enabled: roiReady,
        complete: exportReady,
        blockingReason: roiReady ? "" : t("selector.blocking.roiRequired", { locale }),
      };
    case "review":
      return {
        enabled: reviewReady,
        complete: reviewReady,
        blockingReason: reviewReady ? "" : t("selector.blocking.reviewRequired", { locale }),
      };
    default:
      return {
        enabled: false,
        complete: false,
        blockingReason: "",
      };
  }
}

export function getAccessibleSteps(state) {
  const accessible = [];
  for (const step of STEP_ORDER) {
    const stepState = getStepState(state, step);
    if (!stepState.enabled && step !== "source") {
      break;
    }
    accessible.push(step);
  }
  if (getStepState(state, "review").enabled && !accessible.includes("review")) {
    accessible.push("review");
  }
  return accessible;
}

export function getPrimaryAction(state) {
  const locale = state.ui.locale || "en";
  const activeStep = state.ui.activeStep;
  if (activeStep === "source") {
    return { id: "select-source-file", label: t("selector.primary.selectSource", { locale }), disabled: false };
  }
  if (activeStep === "roi") {
    if (!state.source.filePath) {
      return { id: "select-source-file", label: t("selector.primary.selectSource", { locale }), disabled: false };
    }
    if (!state.roi.previewImage) {
      return { id: "load-preview-frame", label: t("selector.primary.loadFrame", { locale }), disabled: false };
    }
    return {
      id: "apply-roi",
      label: t("selector.primary.applyRoi", { locale }),
      disabled: !isRectValid(state.roi.draftRect),
    };
  }
  if (activeStep === "export") {
    const hasFormats = Array.isArray(state.exportConfig.formats) && state.exportConfig.formats.length > 0;
    return {
      id: "run-export",
      label: state.exportConfig.runStatus === "running"
        ? t("selector.primary.runExportBusy", { locale })
        : isPdfSelected(state.exportConfig.formats)
          ? t("selector.primary.runExportPdf", { locale })
          : t("selector.primary.runExportDirect", { locale }),
      disabled: !getStepState(state, "export").enabled || state.exportConfig.runStatus === "running" || !hasFormats,
    };
  }
  if (activeStep === "review") {
    const hasFormats = Array.isArray(state.exportConfig.formats) && state.exportConfig.formats.length > 0;
    const reviewLocked = !state.exportConfig.jobId
      || state.exportConfig.runStatus !== "done"
      || state.review.status === "running"
      || state.review.status === "applied"
      || !hasFormats
      || hasPendingRoiDraft(state);
    return {
      id: "apply-review",
      label: state.review.status === "running"
        ? t("selector.primary.applyReviewBusy", { locale })
        : state.review.status === "applied"
          ? t("selector.primary.applyReviewDone", { locale })
          : t("selector.primary.applyReview", { locale }),
      disabled: state.review.selectedPageIds.length === 0 || reviewLocked,
    };
  }
  return { id: "", label: "", disabled: true };
}

export function summarizeSelection(allIds = [], selectedIds = new Set()) {
  const totalCount = Array.isArray(allIds) ? allIds.length : 0;
  let keptCount = 0;
  for (const id of allIds) {
    if (selectedIds.has(id)) {
      keptCount += 1;
    }
  }
  return { totalCount, keptCount };
}

export function deriveCapturePages(result = {}, locale = "en") {
  const pageDiagnostics = Array.isArray(result.page_diagnostics) ? result.page_diagnostics : [];
  const previewImages = Array.isArray(result.preview_images) ? result.preview_images : [];
  const reviewCandidates = Array.isArray(result.review_candidates) ? result.review_candidates : [];
  const finalImages = Array.isArray(result.images) ? result.images : [];
  const reviewSelectionMode = String(result.review_export?.selection_mode || "");
  const hasReviewExport = Boolean(result.review_export);
  let capturePaths = finalImages;
  let previewKind = "output";
  let selectionMode = "pages";
  if (reviewSelectionMode === "pages" && finalImages.length) {
    capturePaths = finalImages;
    previewKind = "output";
    selectionMode = "pages";
  } else if (reviewCandidates.length) {
    capturePaths = reviewCandidates;
    previewKind = "capture";
    selectionMode = "captures";
  } else if (Array.isArray(result.upscaled_frames) && result.upscaled_frames.length) {
    capturePaths = result.upscaled_frames;
    previewKind = "capture";
    selectionMode = "captures";
  } else if (Array.isArray(result.stitched_frames) && result.stitched_frames.length) {
    capturePaths = result.stitched_frames;
    previewKind = "capture";
    selectionMode = "captures";
  } else if (previewImages.length) {
    capturePaths = previewImages;
  }
  const alignedDiagnostics = pageDiagnostics.length === capturePaths.length ? pageDiagnostics : [];

  return capturePaths.map((capturePath, index) => {
    const diagnostic = alignedDiagnostics[index] || {};
    const warningReasons = Array.isArray(diagnostic?.warning_reasons)
      ? diagnostic.warning_reasons.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    const warningReason = warningReasons[0]
      || String(diagnostic?.warning_reason || diagnostic?.warningReason || "").trim();
    const outputPreviewPath = previewImages[index] || finalImages[index] || capturePath;
    return {
      id: `${index + 1}`,
      index: index + 1,
      title: t("selector.pageTitle", { locale, replacements: { index: index + 1 } }),
      capturePath,
      previewPath: normalizeAssetPath(capturePath),
      outputPreviewPath: normalizeAssetPath(outputPreviewPath),
      previewKind,
      selectionMode,
      exportLocked: hasReviewExport,
      suspicious: alignedDiagnostics.length > 0 ? Boolean(diagnostic?.suspicious) : false,
      warningReason,
      diagnostics: diagnostic,
    };
  });
}

export function getTopBarSummary(state) {
  const locale = state.ui.locale || "en";
  const preparingLabel = getSourcePrepareSummary(state, locale);
  const sourceLabel = preparingLabel || state.source.displayName || fileBaseName(state.source.filePath) || t("selector.sourceFallback", { locale });
  const stepState = getStepState(state, state.ui.activeStep);
  return {
    sourceLabel,
    stepLabel: state.ui.activeStep,
    stepState,
  };
}

export function getProcessRailItems(state) {
  const locale = state.ui.locale || "en";
  return STEP_ORDER.map((step) => {
    const stepState = getStepState(state, step);
    const preparingLabel = getSourcePrepareSummary(state, locale);
    let summary = t("selector.summary.idle", { locale });
    if (step === "source" && preparingLabel) {
      summary = preparingLabel;
    } else if (step === "source" && state.source.displayName) {
      summary = state.source.displayName;
    } else if (step === "roi") {
      summary = stepState.complete
        ? t("selector.summary.roiReady", { locale })
        : stepState.enabled
          ? t("selector.summary.roiGuide", { locale })
          : t("selector.summary.previousRequired", { locale });
    } else if (step === "export") {
      summary = state.exportConfig.runStatus === "running"
        ? t("selector.summary.exportRunning", { locale })
        : stepState.complete
          ? t("selector.summary.exportDone", { locale })
          : stepState.enabled
            ? t("selector.summary.exportReady", { locale })
            : t("selector.summary.exportBlocked", { locale });
    } else if (step === "review") {
      summary = stepState.complete
        ? t("selector.summary.reviewCount", { locale, replacements: { count: state.review.pages.length } })
        : t("selector.summary.reviewWaiting", { locale });
    }

    return {
      id: step,
      title: step,
      enabled: stepState.enabled,
      complete: stepState.complete,
      active: state.ui.activeStep === step,
      summary,
    };
  });
}

export function formatSecondsLabel(value) {
  const sec = Number(value);
  if (!Number.isFinite(sec) || sec < 0) {
    return "00:00.0";
  }
  const minutes = Math.floor(sec / 60);
  const seconds = sec - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(1).padStart(4, "0")}`;
}
