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
      metadata: null,
      status: "idle",
      error: "",
      youtubeUrl: "",
      preparedFromYouTube: false,
      prepareStatus: "idle",
      prepareLogs: [],
      preparedVideoPath: "",
      prepareErrorDetail: "",
    },
    roi: {
      frameTime: null,
      frameTimeLabel: "00:00.0",
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
    exportConfig: {
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
    },
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
  return width / height >= 2.25 ? "bottom_bar" : "full_scroll";
}

export function getStepState(state, step) {
  const locale = state.ui.locale || "en";
  const sourceReady = Boolean(state.source.filePath);
  const roiReady = sourceReady && Number.isFinite(state.roi.frameTime) && isRectValid(state.roi.appliedRect);
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
        blockingReason: sourceReady ? "" : t("selector.blocking.sourceRequired", { locale }),
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
        : t("selector.primary.runExport", { locale }),
      disabled: !getStepState(state, "export").enabled || state.exportConfig.runStatus === "running" || !hasFormats,
    };
  }
  if (activeStep === "review") {
    const reviewLocked = !state.exportConfig.jobId || state.review.status === "running" || state.review.status === "applied";
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
  const hasReviewExport = Boolean(result.review_export);
  let capturePaths = finalImages;
  let previewKind = "output";
  if (reviewCandidates.length) {
    capturePaths = reviewCandidates;
    previewKind = "capture";
  } else if (Array.isArray(result.upscaled_frames) && result.upscaled_frames.length) {
    capturePaths = result.upscaled_frames;
    previewKind = "capture";
  } else if (Array.isArray(result.stitched_frames) && result.stitched_frames.length) {
    capturePaths = result.stitched_frames;
    previewKind = "capture";
  } else if (previewImages.length) {
    capturePaths = previewImages;
  }
  const alignedDiagnostics = pageDiagnostics.length === capturePaths.length ? pageDiagnostics : [];

  return capturePaths.map((capturePath, index) => {
    const diagnostic = alignedDiagnostics[index] || {};
    const outputPreviewPath = previewImages[index] || finalImages[index] || capturePath;
    return {
      id: `${index + 1}`,
      index: index + 1,
      title: t("selector.pageTitle", { locale, replacements: { index: index + 1 } }),
      capturePath,
      previewPath: normalizeAssetPath(capturePath),
      outputPreviewPath: normalizeAssetPath(outputPreviewPath),
      previewKind,
      exportLocked: hasReviewExport,
      suspicious: alignedDiagnostics.length > 0 ? Boolean(diagnostic?.suspicious) : false,
      diagnostics: diagnostic,
    };
  });
}

export function getTopBarSummary(state) {
  const locale = state.ui.locale || "en";
  const sourceLabel = state.source.displayName || fileBaseName(state.source.filePath) || t("selector.sourceFallback", { locale });
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
    let summary = t("selector.summary.idle", { locale });
    if (step === "source" && state.source.displayName) {
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
