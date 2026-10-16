import { captureRange } from "../features/export/captureRange.js";
import { bridge, readVideoMetadata } from "./bridge.js";
import { createStore } from "./session/store.js";
import { restoreSession, saveSession } from "./session/persistence.js";
import {
  createDocumentHeaderState,
  createExportMetadataModalState,
  createInitialExportConfig,
  createInitialSessionState,
  deriveCapturePages,
  createReviewHypothesesState,
  deriveOutputPages,
  deriveOriginalScreens,
  deriveReflowInfo,
  localizePageTitle,
  isLayoutConflictPending,
  isLedgerFailurePending,
  isReviewableRun,
  jobRevision,
  formatSecondsLabel,
  getProcessRailItems,
  getSourcePrepareSummary,
  getTopBarSummary,
  inferLayoutHintFromRoi,
  isExportMetadataDirty,
  isPdfSelected,
  isRectValid,
  normalizeDocumentHeader,
  sanitizeDocumentHeaderDraftField,
  validateExportMetadataDraft,
} from "./session/selectors.js";
import { canRunExport, createRuntimeGuards, hasDirtyRoiDraft, invalidatePreviewFlow } from "./session/runtimeSafety.js";
import { canOpenStep } from "./routes.js";
import { mountShell } from "../ui/shell/AppShell.js";
import { createWorkspaceMotion } from "../ui/shell/workspaceMotion.js";
import { renderTopBar } from "../ui/shell/TopBar.js";
import { renderProcessRail } from "../ui/shell/ProcessRail.js";
import { renderContextLane } from "../ui/shell/ContextLane.js";
import { renderSourceScreen } from "../features/source/SourceScreen.js";
import { createSourceController } from "../features/source/sourceController.js";
import { renderRoiScreen } from "../features/roi/RoiScreen.js";
import { patchRoiStage } from "../features/roi/patchRoiStage.js";
import { renderExportScreen } from "../features/export/ExportScreen.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { createReviewController } from "../features/review/reviewController.js";
import { syncThumbShape } from "../features/review/thumbShape.js";
import { pendingSeamRejections } from "../features/review/lineCheck.js";
import { renderArchiveModal } from "../features/archive/ArchiveModal.js";
import { createBugReportDraft, createBugReportState, renderBugReportModal } from "../features/support/BugReportModal.js";
import { mountRoiEditor } from "../features/roi/roiEditor.js";
import {
  createJob,
  cancelJob,
  cropCapture,
  createPreviewSourceJob,
  getArchiveLibrary,
  getCacheUsage,
  clearCache,
  getJob,
  getLocalMediaRegistry,
  getPreviewSourceJob,
  preparePreviewSource,
  requestAutoRoi,
  requestPreviewFrame,
  requestLabelRegion,
  requestPreviewRoiHealth,
  reviewExport,
  getReviewExportTask,
  waitForReviewExport,
  cancelReviewExport,
  getReviewHypotheses,
} from "../lib/api.js";
import { escapeHtml } from "../lib/html.js";
import { describeError, errorDetailText, t } from "../lib/i18n.js";
import { baseName } from "../lib/paths.js";
import { persistLocale } from "../lib/i18n.js";
import { mergePrepareLogs, notice, youtubePrepareDetail, youtubePrepareError } from "../lib/messages.js";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

const SOURCE_DROP_ZONE_SELECTOR = '[data-drop-zone="source-ingest"]';
const STAGE_SCROLL_RESTORE_SELECTORS = [".review-grid", ".review-viewer-surface"];
const SUPPORTED_VIDEO_EXTENSIONS = new Set(["mp4", "mkv", "mov", "avi", "webm"]);
const EXPORT_METADATA_TAB_TARGETS = [
  { action: "update-export-metadata", field: "title" },
  { action: "update-export-metadata", field: "performer" },
  { action: "update-export-metadata", field: "bpm" },
  { action: "update-export-metadata", field: "date" },
  { action: "update-export-metadata", field: "memo" },
  { action: "confirm-export-metadata" },
  { action: "close-export-metadata" },
];

function fileExtension(filePath = "") {
  const normalized = String(filePath || "").replace(/\\/g, "/").trim();
  const fileName = normalized.split("/").pop() || "";
  const dotIndex = fileName.lastIndexOf(".");
  if (dotIndex < 0) {
    return "";
  }
  return fileName.slice(dotIndex + 1).toLowerCase();
}

function isSupportedVideoPath(filePath = "") {
  const normalized = String(filePath || "").trim();
  if (!normalized) {
    return false;
  }
  return SUPPORTED_VIDEO_EXTENSIONS.has(fileExtension(normalized));
}

/** Job/task error codes of a composed export that may not be published as done (STRATEGY Step 2A). */
export const EXPORT_INVALID_CODES = ["INVALID_PLACEMENT_PLAN", "EMPTY_EXPORT", "PAGE_COUNT_MISMATCH", "PDF_UNREADABLE"];

/** Review export refusals of a jump-view join rebuild (SEAM_REJECT_DESIGN.md); each has its own message. */
const SEAM_REPAIR_CODES = ["SEAM_REPAIR_SOURCE_UNAVAILABLE", "SEAM_REPAIR_SELECTION", "SEAM_REPAIR_INCOMPATIBLE", "STALE_REVISION", "SEAM_UNKNOWN"];

/** The user-facing message for a failed job's error code, or "" when the code has no specific one. */
export function exportErrorCodeMessage(errorCode, locale = "en") {
  const code = String(errorCode || "");
  if (EXPORT_INVALID_CODES.includes(code)) {
    return t("export.failedExportInvalid", { locale, replacements: { reason: t(`export.invalid.${code}`, { locale }) } });
  }
  if (code === "LAYOUT_CONFLICT") return t("export.failedLayoutConflict", { locale });
  if (code === "LEDGER_VERIFICATION_FAILED") return t("export.failedLedgerVerification", { locale });
  if (code === "UNSUPPORTED_SOURCE") return t("export.failedUnsupportedSource", { locale });
  if (code === "UNSUPPORTED_LAYOUT") return t("export.failedUnsupportedLayout", { locale });
  if (code === "NO_SCORE_SYSTEMS") return t("export.failedNoSystems", { locale });
  if (code === "VIDEO_DECODE_INCOMPLETE") return t("export.failedDecodeIncomplete", { locale });
  return "";
}

export function formatExportJobMessage(message, { status = "", locale = "en", errorCode = "" } = {}) {
  if (status === "cancelled") return t("export.cancelled", { locale });
  // The progress card already says the run finished; the backend's English log line adds nothing.
  if (status === "done") return "";
  if (String(status || "").toLowerCase() === "error") {
    const coded = exportErrorCodeMessage(errorCode, locale);
    if (coded) return coded;
  }
  const raw = String(message || "").trim();
  if (!raw) {
    return "";
  }
  const detail = raw.replace(/^job failed:\s*/i, "").trim();
  if (String(status || "").toLowerCase() === "error") {
    if (/horizontal-scroll score is not supported/i.test(detail)) {
      return t("export.failedUnsupportedLayout", { locale });
    }
    if (/no score system was found/i.test(detail)) {
      return t("export.failedNoSystems", { locale });
    }
    if (/roi is unsafe|unsafe for capture|score region|representative frame/i.test(detail)) {
      return t("export.failedRegionUnsafe", { locale });
    }
    return detail || t("export.failed", { locale });
  }
  return raw;
}

function dataTransferHasFiles(dataTransfer) {
  if (!dataTransfer) {
    return false;
  }
  const files = Array.from(dataTransfer.files || []);
  if (files.length > 0) {
    return true;
  }
  const types = Array.from(dataTransfer.types || []);
  return types.includes("Files");
}

function getTransferFiles(dataTransfer) {
  if (!dataTransfer) {
    return [];
  }
  const files = Array.from(dataTransfer.files || []);
  if (files.length > 0) {
    return files;
  }
  const items = Array.from(dataTransfer.items || []);
  return items
    .map((item) => item?.getAsFile?.())
    .filter(Boolean);
}

async function getDroppedVideoPath(dataTransfer, runtimeBridge) {
  const files = getTransferFiles(dataTransfer);
  for (const file of files) {
    const filePath = String(runtimeBridge.getPathForFile(file) || file?.path || "").trim();
    if (isSupportedVideoPath(filePath)) {
      return filePath;
    }
  }
  return "";
}

function findSourceDropZone(target) {
  return target?.closest?.(SOURCE_DROP_ZONE_SELECTOR) || null;
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

function boundsToRect(bounds, maxWidth, maxHeight) {
  const width = Math.max(1, Math.round(Number(bounds.width || 0)));
  const height = Math.max(1, Math.round(Number(bounds.height || 0)));
  const clampedWidth = clamp(width, 1, maxWidth);
  const clampedHeight = clamp(height, 1, maxHeight);
  const x = clamp(Math.round(Number(bounds.x || 0)), 0, Math.max(0, maxWidth - clampedWidth));
  const y = clamp(Math.round(Number(bounds.y || 0)), 0, Math.max(0, maxHeight - clampedHeight));

  return [
    [x, y],
    [x + clampedWidth, y],
    [x + clampedWidth, y + clampedHeight],
    [x, y + clampedHeight],
  ];
}

function rectMatches(a, b) {
  if (!isRectValid(a) || !isRectValid(b)) {
    return false;
  }
  return JSON.stringify(a) === JSON.stringify(b);
}

function syncDocumentChrome(locale) {
  const doc = globalThis?.document;
  if (!doc) {
    return;
  }
  if (doc.documentElement) {
    doc.documentElement.lang = locale === "ko" ? "ko" : "en";
  }
  const skipLink = typeof doc.querySelector === "function" ? doc.querySelector(".skip-link") : null;
  if (skipLink) {
    skipLink.textContent = t("app.skipLink", { locale });
  }
}

function exportMetadataTabSelector(target) {
  if (!target?.action) {
    return "";
  }
  if (target.field) {
    return `[data-action="${target.action}"][data-field="${target.field}"]`;
  }
  return `[data-action="${target.action}"]`;
}

function cssAttributeValue(value) {
  return String(value ?? "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function exportMetadataTabTargetIndex(element) {
  const action = String(element?.dataset?.action || "");
  const field = String(element?.dataset?.field || "");
  return EXPORT_METADATA_TAB_TARGETS.findIndex((target) => (
    target.action === action && String(target.field || "") === field
  ));
}

function focusAdjacentExportMetadataTarget(stagePane, currentElement, reverse = false) {
  const currentIndex = exportMetadataTabTargetIndex(currentElement);
  if (currentIndex < 0 || !stagePane) {
    return false;
  }

  const direction = reverse ? -1 : 1;
  for (let offset = 1; offset <= EXPORT_METADATA_TAB_TARGETS.length; offset += 1) {
    const nextIndex = (
      currentIndex + (direction * offset) + EXPORT_METADATA_TAB_TARGETS.length
    ) % EXPORT_METADATA_TAB_TARGETS.length;
    const selector = exportMetadataTabSelector(EXPORT_METADATA_TAB_TARGETS[nextIndex]);
    const nextElement = selector ? stagePane.querySelector?.(selector) : null;
    if (nextElement && !nextElement.disabled && typeof nextElement.focus === "function") {
      nextElement.focus();
      return true;
    }
  }
  return false;
}

function captureStageInputFocus() {
  const activeElement = globalThis?.document?.activeElement;
  // Focusable regions without an action (the review canvas) name themselves so keyboard shortcuts keep working after a re-render.
  if (activeElement?.dataset?.focusKey) {
    return { selector: `[data-focus-key="${cssAttributeValue(activeElement.dataset.focusKey)}"]`, selectionStart: null, selectionEnd: null };
  }
  if (!activeElement?.dataset?.action) {
    return null;
  }
  if (["update-export-metadata", "capture-range"].includes(activeElement.dataset.action) && activeElement.dataset.field) {
    return {
      selector: `[data-action="${activeElement.dataset.action}"][data-field="${activeElement.dataset.field}"]`,
      selectionStart: Number.isInteger(activeElement.selectionStart) ? activeElement.selectionStart : null,
      selectionEnd: Number.isInteger(activeElement.selectionEnd) ? activeElement.selectionEnd : null,
    };
  }
  if (activeElement.dataset.action === "toggle-review-page" && activeElement.dataset.pageId) {
    return {
      selector: `[data-action="toggle-review-page"][data-page-id="${cssAttributeValue(activeElement.dataset.pageId)}"]`,
      selectionStart: Number.isInteger(activeElement.selectionStart) ? activeElement.selectionStart : null,
      selectionEnd: Number.isInteger(activeElement.selectionEnd) ? activeElement.selectionEnd : null,
    };
  }
  const actionSelector = `[data-action="${activeElement.dataset.action}"]`;
  // One action on many cards (the seam answers, the line toggles): keep focus on the same card.
  const value = activeElement.dataset.value;
  return {
    selector: value ? `${actionSelector}[data-value="${cssAttributeValue(value)}"]` : actionSelector,
    fallbackSelector: value ? actionSelector : "",
    selectionStart: Number.isInteger(activeElement.selectionStart) ? activeElement.selectionStart : null,
    selectionEnd: Number.isInteger(activeElement.selectionEnd) ? activeElement.selectionEnd : null,
  };
}

// While a PDF rebuild runs its Cancel button takes the Rebuild button's place (and back), so focus follows it.
const FOCUS_STAND_INS = {
  '[data-action="apply-review"]': '[data-action="cancel-review-export"]',
  '[data-action="cancel-review-export"]': '[data-action="apply-review"]',
};

function restoreStageInputFocus(stagePane, snapshot) {
  if (!stagePane || !snapshot?.selector) {
    return;
  }
  let nextField = stagePane.querySelector?.(snapshot.selector);
  if (!nextField && snapshot.fallbackSelector) {
    nextField = stagePane.querySelector?.(snapshot.fallbackSelector);
  }
  if (!nextField && FOCUS_STAND_INS[snapshot.selector]) {
    nextField = stagePane.querySelector?.(FOCUS_STAND_INS[snapshot.selector]);
  }
  if (typeof nextField?.focus !== "function") {
    return;
  }
  nextField.focus();
  if (
    typeof nextField.setSelectionRange === "function"
    && Number.isInteger(snapshot.selectionStart)
    && Number.isInteger(snapshot.selectionEnd)
  ) {
    nextField.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
  }
}

function captureStageScrollSnapshot(stagePane) {
  if (!stagePane || typeof stagePane.querySelector !== "function") {
    return [];
  }
  return STAGE_SCROLL_RESTORE_SELECTORS
    .map((selector) => {
      const element = stagePane.querySelector(selector);
      if (!element) {
        return null;
      }
      return {
        selector,
        scrollTop: Number(element.scrollTop || 0),
        scrollLeft: Number(element.scrollLeft || 0),
      };
    })
    .filter(Boolean);
}

function restoreStageScrollSnapshot(stagePane, snapshot) {
  if (!stagePane || !Array.isArray(snapshot) || !snapshot.length || typeof stagePane.querySelector !== "function") {
    return;
  }
  snapshot.forEach((item) => {
    const element = stagePane.querySelector(item.selector);
    if (!element) {
      return;
    }
    element.scrollTop = item.scrollTop;
    element.scrollLeft = item.scrollLeft;
  });
}

function captureLiveExportMetadataDraft(stagePane, draft = {}) {
  const nextDraft = {
    ...draft,
  };
  const fields = ["title", "performer", "bpm", "date", "memo"];
  fields.forEach((field) => {
    const input = stagePane?.querySelector?.(`[data-action="update-export-metadata"][data-field="${field}"]`);
    if (!input || typeof input.value !== "string") {
      return;
    }
    nextDraft[field] = sanitizeDocumentHeaderDraftField(field, input.value);
  });
  return nextDraft;
}

function restoreLiveExportMetadataDraft(stagePane, draft = {}) {
  const fields = ["title", "performer", "bpm", "date", "memo"];
  fields.forEach((field) => {
    const input = stagePane?.querySelector?.(`[data-action="update-export-metadata"][data-field="${field}"]`);
    if (!input || typeof input.value !== "string") {
      return;
    }
    input.value = sanitizeDocumentHeaderDraftField(field, draft[field] ?? "");
  });
}

function captureLiveMetadataTextInputSnapshot() {
  const activeElement = globalThis?.document?.activeElement;
  if (activeElement?.dataset?.action !== "update-export-metadata" || !activeElement.dataset.field) {
    return null;
  }
  const field = String(activeElement.dataset.field || "");
  if (!field || field === "bpm" || field === "date" || typeof activeElement.value !== "string") {
    return null;
  }
  return {
    selector: `[data-action="update-export-metadata"][data-field="${field}"]`,
    value: sanitizeDocumentHeaderDraftField(field, activeElement.value),
  };
}

function restoreLiveMetadataTextInputSnapshot(stagePane, snapshot) {
  if (!stagePane || !snapshot?.selector) {
    return;
  }
  const nextField = stagePane.querySelector?.(snapshot.selector);
  if (!nextField || typeof nextField.value !== "string") {
    return;
  }
  nextField.value = snapshot.value;
}

function captureStageFocusRestoreSelector(activeElement) {
  if (activeElement?.dataset?.action) {
    return `[data-action="${activeElement.dataset.action}"]`;
  }
  return "[data-screen-heading]";
}

function focusMetadataTitleField(stagePane) {
  const titleField = stagePane?.querySelector?.('[data-action="update-export-metadata"][data-field="title"]');
  if (typeof titleField?.focus === "function") {
    titleField.focus();
  }
}

function focusExportRunButton(stagePane) {
  const runButton = stagePane?.querySelector?.('[data-action="run-export"]');
  if (typeof runButton?.focus === "function") {
    runButton.focus();
    return;
  }
  const heading = stagePane?.querySelector?.("[data-screen-heading]");
  if (typeof heading?.focus === "function") {
    heading.focus();
  } else if (typeof stagePane?.focus === "function") {
    stagePane.focus();
  }
}

function releasePreviewImageUrl(value) {
  const url = String(value || "");
  if (!url.startsWith("blob:") || typeof globalThis.URL?.revokeObjectURL !== "function") {
    return;
  }
  globalThis.URL.revokeObjectURL(url);
}

export function createApp(root, dependencies = {}) {
  const runtimeBridge = dependencies.bridge || bridge;
  const readMetadata = dependencies.readVideoMetadata || readVideoMetadata;
  const runtimeApi = dependencies.api
    ? {
      getArchiveLibrary: async () => ({ items: [] }),
      getCacheUsage: async () => ({ totalPaths: 0, totalBytes: 0, totalHuman: "0 B" }),
      clearCache: async () => ({ clearedPaths: 0, reclaimedBytes: 0, reclaimedHuman: "0 B", skippedPaths: [] }),
      getLocalMediaRegistry: async () => ({ items: [] }),
      requestPreviewRoiHealth: async () => ({
        riskLevel: "info",
        summary: "",
        diagnostics: [],
        sampledFrames: 0,
        checkedSeconds: [],
        metrics: {},
      }),
      requestAutoRoi: async () => ({
        status: "not_found",
        roi: null,
        evidenceLevel: "low",
        layoutHint: "",
        isDarkMode: false,
        diagnostics: {},
      }),
      requestLabelRegion: async () => ({ status: "not_found", labelRoi: null, evidence: {} }),
      ...dependencies.api,
    }
    : {
      createJob,
      cancelJob,
      cropCapture,
      createPreviewSourceJob,
      getArchiveLibrary,
      getCacheUsage,
      clearCache,
      getJob,
      getLocalMediaRegistry,
      getPreviewSourceJob,
      preparePreviewSource,
      requestAutoRoi,
      requestPreviewFrame,
      requestLabelRegion,
      requestPreviewRoiHealth,
      reviewExport,
      getReviewExportTask,
      waitForReviewExport,
      cancelReviewExport,
      getReviewHypotheses,
    };
  const mountShellImpl = dependencies.mountShell || mountShell;
  const mountRoiEditorImpl = dependencies.mountRoiEditor || mountRoiEditor;
  const storage = dependencies.storage || (!dependencies.exposeTestApi && typeof window !== "undefined" ? window.localStorage : null);
  const store = createStore(restoreSession(storage, createInitialSessionState()));
  const shell = mountShellImpl(root);
  const workspaceMotion = createWorkspaceMotion(root, shell);
  const sourceController = createSourceController({
    store,
    readMetadata,
    formatSecondsLabel,
    resetDownstream,
    baseName,
    messages: {
      mergePrepareLogs,
      youtubePrepareDetail,
      youtubePrepareError,
    },
  });
  let releaseUpdate = { status: "idle" };
  // Kept out of the store: the report form is not part of the persisted session.
  let bugReport = createBugReportState();
  let bugReportPreparing = false;
  let bugReportRestoreFocusTarget = null;
  let lastBugReportOpen = false;
  let destroyed = false;
  let roiEditor = null;
  let mountingRoiEditor = false;
  let roiEditorKey = "";
  let roiEditorNodes = null;
  let activePoll = null;
  let activeSuggestionPoll = null;
  // a job id whose rebuild was cancelled before its start request answered
  let pendingExportCancel = "";
  let activeJobHandle = null;
  let activeSourcePreparePoll = null;
  let activeSourcePrepareHandle = null;
  let activeSourceSelection = 0;
  let lastRenderedStep = "";
  let lastTopBarMarkup = "";
  let lastProcessRailMarkup = "";
  let lastContextLaneMarkup = "";
  let lastStageMarkup = "";
  let lastReviewFocusKey = "";
  let lastArchiveMarkup = "";
  let lastStatusMarkup = "";
  let lastBackendReady = false;
  let lastArchiveOpen = false;
  let lastMetadataModalOpen = false;
  let archiveRestoreFocusTarget = null;
  let metadataRestoreFocusSelector = '[data-action="run-export"]';
  let registryRefreshToken = 0;
  let archiveRefreshToken = 0;
  let activeSourceDropZone = null;
  const runtimeGuards = createRuntimeGuards();
  let pollFailures = 0;
  let restorePending = Boolean(store.getState().exportConfig.jobId);
  // The job reference restored from the last session, until the backend confirms it still exists.
  let restoredJobId = restorePending ? String(store.getState().exportConfig.jobId) : "";
  const stopPersistence = store.subscribe(state => saveSession(storage, state));
  const reviewController = createReviewController({ getState: store.getState, setState, api: runtimeApi, mountEditor: mountRoiEditorImpl, root });

  function setState(updater) {
    const previousPreviewImage = String(store.getState().roi?.previewImage || "");
    const nextState = store.setState(updater);
    const nextPreviewImage = String(nextState.roi?.previewImage || "");
    if (previousPreviewImage && previousPreviewImage !== nextPreviewImage) {
      releasePreviewImageUrl(previousPreviewImage);
    }
    return nextState;
  }

  function getSelectedPreviewCandidate(state = store.getState()) {
    const selectedId = String(state.roi.selectedPreviewCandidateId || "");
    if (!selectedId) {
      return null;
    }
    return (state.roi.previewCandidates || []).find((candidate) => candidate.id === selectedId) || null;
  }

  function sourceDocumentDisplayName(source = store.getState().source) {
    return String(source?.displayName || source?.archiveDisplayName || "").trim();
  }

  function resetDownstream(next) {
    const sourceDisplayName = sourceDocumentDisplayName(next.source);
    next.roi = {
      frameTime: 0,
      frameTimeLabel: "00:00.0",
      previewCandidates: [],
      selectedPreviewCandidateId: "",
      previewImage: "",
      previewSourcePath: "",
      diagnostics: [],
      autoRoiStatus: "idle",
      autoRoiEvidence: "",
      autoRoiDiagnostics: {},
      autoRoiUserEdited: false,
      draftRect: null,
      appliedRect: null,
      imageWidth: 0,
      imageHeight: 0,
      status: "idle",
      error: "",
    };
    next.exportConfig = createInitialExportConfig(next.source.filePath, new Date(), sourceDisplayName);
    next.review = {
      pages: [],
      selectedPageIds: [],
      focusedPageId: "",
      status: "idle",
      error: "",
      keptCount: 0,
      outputDir: "",
      pdfPath: "",
      outputPages: [],
      exportTask: null,
      hypotheses: createReviewHypothesesState(),
    };
  }

  function resetReviewState(next) {
    next.review = {
      pages: [],
      selectedPageIds: [],
      focusedPageId: "",
      status: "idle",
      error: "",
      keptCount: 0,
      outputDir: "",
      pdfPath: "",
      outputPages: [],
      exportTask: null,
      hypotheses: createReviewHypothesesState(),
    };
  }

  function invalidateExportReviewState(next) {
    const sourceDisplayName = sourceDocumentDisplayName(next.source);
    const currentExportConfig = next.exportConfig || createInitialExportConfig(next.source.filePath, new Date(), sourceDisplayName);
    const fallbackDocumentHeader = createDocumentHeaderState(next.source.filePath, new Date(), sourceDisplayName);
    const documentHeader = normalizeDocumentHeader(currentExportConfig.documentHeader, fallbackDocumentHeader);
    const nextExportConfig = createInitialExportConfig(next.source.filePath, new Date(), sourceDisplayName);
    nextExportConfig.formats = Array.isArray(currentExportConfig.formats)
      ? currentExportConfig.formats.slice()
      : nextExportConfig.formats;
    nextExportConfig.pageFillMode = currentExportConfig.pageFillMode || nextExportConfig.pageFillMode;
    nextExportConfig.layoutHint = currentExportConfig.layoutHint || nextExportConfig.layoutHint;
    nextExportConfig.measureReflow = currentExportConfig.measureReflow !== false;
    nextExportConfig.documentHeader = documentHeader;
    nextExportConfig.metadataModal = createExportMetadataModalState(next.source.filePath, new Date(), documentHeader, sourceDisplayName);
    next.exportConfig = nextExportConfig;
    resetReviewState(next);
  }

  function resetCurrentSourceSession() {
    stopPolling();
    stopSourcePreparePolling();
    activeJobHandle = null;
    activeSourcePrepareHandle = null;
    runtimeGuards.bumpSourceSession();
  }

  function stageMarkup(state) {
    if (state.ui.activeStep === "source") return renderSourceScreen(state);
    if (state.ui.activeStep === "roi") return renderRoiScreen(state);
    if (state.ui.activeStep === "export") return renderExportScreen(state);
    return renderReviewScreen(state);
  }

  function syncArchiveShellState(isArchiveOpen) {
    const shellSurfaces = [shell.topBar, shell.workspaceShell, shell.statusBar];
    for (const surface of shellSurfaces) {
      if (!surface) {
        continue;
      }
      surface.inert = isArchiveOpen;
      if (isArchiveOpen) {
        surface.setAttribute?.("aria-hidden", "true");
      } else {
        surface.removeAttribute?.("aria-hidden");
      }
    }
  }

  function focusArchiveDialog() {
    const dialog = shell.modalLayer?.querySelector?.("[data-archive-dialog]");
    dialog?.focus?.();
  }

  function destroyRoiEditor() {
    if (roiEditor) {
      roiEditor.destroy();
      roiEditor = null;
    }
    roiEditorKey = "";
    roiEditorNodes = null;
  }

  function attachRoiEditor(state) {
    if (mountingRoiEditor) return;
    if (state.ui.activeStep !== "roi" || !state.roi.previewImage) {
      destroyRoiEditor();
      return;
    }
    const image = shell.stagePane.querySelector("#roiImage");
    const canvas = shell.stagePane.querySelector("#roiCanvas");
    const input = shell.stagePane.querySelector("#roiInput");
    if (!image || !canvas || !input) {
      destroyRoiEditor();
      return;
    }
    const labels = state.roi.editTarget === "labels";
    const draftKey = labels ? "labelDraftRect" : "draftRect";
    const appliedKey = labels ? "labelAppliedRect" : "appliedRect";
    const nextKey = `${state.roi.previewSourcePath || state.roi.previewImage}|${labels ? "labels" : "score"}`;
    const nodesChanged = !roiEditorNodes
      || roiEditorNodes.image !== image
      || roiEditorNodes.canvas !== canvas
      || roiEditorNodes.input !== input;
    if (roiEditor && roiEditorKey === nextKey && !nodesChanged) {
      roiEditor.setDraft?.(state.roi[draftKey] || state.roi[appliedKey] || null);
      return;
    }
    destroyRoiEditor();
    mountingRoiEditor = true;
    try {
      roiEditor = mountRoiEditorImpl({
        image,
        canvas,
        input,
        initialPoints: state.roi[draftKey] || state.roi[appliedKey],
        onDraftChange(points) {
          if (rectMatches(points, store.getState().roi[draftKey])) {
            return;
          }
          setState((next) => {
            next.roi[draftKey] = points;
            return next;
          });
        },
        onUserEdit() {
          if (labels) return;
          setState((next) => {
            next.roi.autoRoiUserEdited = true;
            return next;
          });
        },
      });
      roiEditorKey = nextKey;
      roiEditorNodes = { image, canvas, input };
    } finally {
      mountingRoiEditor = false;
    }
    const latestRoi = store.getState().roi;
    roiEditor?.setDraft?.(latestRoi[draftKey] || latestRoi[appliedKey] || null);
  }

  function render() {
    const state = store.getState();
    const locale = state.ui.locale || "en";
    const isMetadataModalOpen = Boolean(state.exportConfig?.metadataModal?.isOpen);
    const metadataModalChanged = isMetadataModalOpen !== lastMetadataModalOpen;
    if (isMetadataModalOpen && !lastMetadataModalOpen) {
      metadataRestoreFocusSelector = captureStageFocusRestoreSelector(globalThis?.document?.activeElement);
    }
    syncDocumentChrome(locale);
    const stepLabel = t(`topbar.step.${state.ui.activeStep}`, { locale });
    const topBarSummary = getTopBarSummary(state);
    const sourceStatusLabel = getSourcePrepareSummary(state, locale)
      || state.source.displayName
      || "";
    const laneMarkup = renderContextLane(state);
    const topBarMarkup = renderTopBar(state, topBarSummary, releaseUpdate);
    const processRailMarkup = renderProcessRail(state, getProcessRailItems(state));
    const stageMarkupValue = stageMarkup(state);
    const bugReportMarkup = renderBugReportModal(bugReport, locale);
    const archiveMarkupValue = bugReportMarkup || renderArchiveModal(state);
    const archiveMarkupChanged = archiveMarkupValue !== lastArchiveMarkup;
    const isArchiveOpen = Boolean(state.archive?.isOpen) && !bugReport.isOpen;
    if (!isMetadataModalOpen && lastMetadataModalOpen) {
      workspaceMotion.leave(shell.stagePane.querySelector?.('.export-metadata-overlay'));
    }
    if (!isArchiveOpen && !bugReport.isOpen && (lastArchiveOpen || lastBugReportOpen)) {
      workspaceMotion.leave(shell.modalLayer.querySelector?.('.archive-overlay'));
    }
    const engineStatus = escapeHtml(state.ui.backend?.ready ? t("status.engineReady", { locale }) : t("status.engineWaiting", { locale }));
    const sourceStatus = escapeHtml(sourceStatusLabel
      ? t("status.sourceLabel", { locale, replacements: { label: sourceStatusLabel } })
      : t("status.sourceIdle", { locale }));
    const backendMessage = state.ui.backend?.error
      ? t("support.engineFailed", { locale })
      : t("support.engineStarting", { locale });
    const hasFailure = Boolean(state.ui.backend?.error || state.source.error || state.roi.error || state.exportConfig.error || state.review.error);
    const releaseUpdateMarkup = renderReleaseUpdateGroup(locale, hasFailure);
    const inlineNotice = escapeHtml(state.ui.inlineNotice || (!state.ui.backend?.ready ? backendMessage : hasFailure ? t("support.failureHelp", { locale }) : releaseUpdateMarkup ? "" : t("status.sessionStable", { locale })));
    const pagesStatus = escapeHtml(state.review.pages.length
      ? t("status.pagesCount", { locale, replacements: { count: state.review.pages.length } })
      : t("status.pagesEmpty", { locale }));
    const recoveryActions = state.ui.backend?.ready || state.ui.backend?.starting || state.ui.backend?.setupRunning
      ? ""
      : `
        <div class="status-bar-group status-bar-recovery">
          <button class="button button-secondary" data-action="restart-backend">${escapeHtml(t("status.restartBackend", { locale }))}</button>
          <button class="button button-secondary" data-action="run-guided-setup">${escapeHtml(t("status.runSetup", { locale }))}</button>
        </div>
      `;
    const statusMarkup = `
      <div class="status-bar-group">
        <span>${engineStatus}</span>
        <span>${sourceStatus}</span>
      </div>
      <div class="status-bar-group status-bar-group-notice">
        ${hasFailure ? `<strong class="status-bar-title">${escapeHtml(t("support.failureTitle", { locale }))}</strong>` : ""}
        <span>${inlineNotice}</span>
      </div>
      <div class="status-bar-group">
        <span>${pagesStatus}</span>
      </div>
      ${recoveryActions}
      ${hasFailure ? `<div class="status-bar-group status-bar-recovery">
        <button class="button button-ghost" data-action="copy-diagnostics">${t("support.copy", { locale })}</button>
        <button class="button button-primary" data-action="open-bug-report">${t("support.issue", { locale })}</button>
      </div>` : ""}
      ${releaseUpdateMarkup}
    `;
    if (shell.appShell) {
      shell.appShell.dataset.step = state.ui.activeStep;
    }
    shell.processRail?.setAttribute?.("aria-label", t("app.aria.workflowSteps", { locale }));
    shell.contextLane?.setAttribute?.("aria-label", t("app.aria.inspectionDetails", { locale }));
    shell.stagePane?.setAttribute?.("aria-label", t("app.aria.stagePane", { locale, replacements: { step: stepLabel } }));
    if (topBarMarkup !== lastTopBarMarkup) {
      replaceKeepingFocus(shell.topBar, topBarMarkup);
      lastTopBarMarkup = topBarMarkup;
    }
    if (processRailMarkup !== lastProcessRailMarkup) {
      shell.processRail.innerHTML = processRailMarkup;
      lastProcessRailMarkup = processRailMarkup;
    }
    if (laneMarkup !== lastContextLaneMarkup) {
      shell.contextLane.innerHTML = laneMarkup;
      lastContextLaneMarkup = laneMarkup;
    }
    shell.contextLane.hidden = !laneMarkup.trim();
    if (stageMarkupValue !== lastStageMarkup) {
      const focusSnapshot = captureStageInputFocus();
      const scrollSnapshot = captureStageScrollSnapshot(shell.stagePane);
      const liveMetadataDraftSnapshot = isMetadataModalOpen
        ? captureLiveExportMetadataDraft(shell.stagePane, state.exportConfig?.metadataModal?.draft)
        : null;
      const liveMetadataTextInputSnapshot = captureLiveMetadataTextInputSnapshot();
      if (!patchRoiStage(shell.stagePane, stageMarkupValue)) shell.stagePane.innerHTML = stageMarkupValue;
      lastStageMarkup = stageMarkupValue;
      restoreLiveExportMetadataDraft(shell.stagePane, liveMetadataDraftSnapshot);
      restoreLiveMetadataTextInputSnapshot(shell.stagePane, liveMetadataTextInputSnapshot);
      restoreStageScrollSnapshot(shell.stagePane, scrollSnapshot);
      restoreStageInputFocus(shell.stagePane, focusSnapshot);
    }
    if (archiveMarkupChanged) {
      if (bugReport.isOpen && lastBugReportOpen) replaceBugReportKeepingFocus(archiveMarkupValue);
      else shell.modalLayer.innerHTML = archiveMarkupValue;
      lastArchiveMarkup = archiveMarkupValue;
    }
    syncArchiveShellState(isArchiveOpen || bugReport.isOpen);
    if (isUpdateInstalling()) {
      // The app is about to quit; only the status message stays readable.
      if (shell.topBar) shell.topBar.inert = true;
      if (shell.workspaceShell) shell.workspaceShell.inert = true;
    }
    const statusNeedsAttention = !state.ui.backend?.ready || hasFailure || Boolean(releaseUpdateMarkup) || Boolean(String(state.ui.inlineNotice || "").trim());
    shell.statusBar?.setAttribute?.("data-attention", statusNeedsAttention ? "true" : "false");
    const statusIsInert = !statusNeedsAttention || isArchiveOpen || bugReport.isOpen;
    shell.statusBar?.setAttribute?.("aria-hidden", statusIsInert ? "true" : "false");
    if (shell.statusBar) shell.statusBar.inert = statusIsInert;
    shell.statusBar?.setAttribute?.("data-tone", hasFailure ? "danger" : !state.ui.backend?.ready || ["downloading", "installing"].includes(releaseUpdate?.status) ? "progress" : "info");
    if (statusMarkup !== lastStatusMarkup) {
      // When the focused update control goes away, keep focus on the next update action or the dock button.
      replaceKeepingFocus(shell.statusBar, statusMarkup, () => shell.statusBar.querySelector?.("button:not([disabled])")
        || shell.topBar?.querySelector?.('[data-action="check-release-update"]'));
      lastStatusMarkup = statusMarkup;
    }
    attachRoiEditor(state);
    maybeCheckAppliedRoi(state);
    reviewController.syncEditor();
    if (isMetadataModalOpen && !lastMetadataModalOpen) {
      workspaceMotion.enter(shell.stagePane.querySelector?.('.export-metadata-overlay'));
    }
    if ((isArchiveOpen && !lastArchiveOpen) || (bugReport.isOpen && !lastBugReportOpen)) {
      workspaceMotion.enter(shell.modalLayer.querySelector?.('.archive-overlay'));
    }
    const reviewFocusKey = state.ui.activeStep === "review" ? `${state.review.filter}:${state.review.focusedPageId}` : "";
    if (reviewFocusKey && reviewFocusKey !== lastReviewFocusKey) {
      shell.stagePane.querySelector?.('.review-card.is-focused')?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    }
    lastReviewFocusKey = reviewFocusKey;
    if (isArchiveOpen && !lastArchiveOpen) {
      archiveRestoreFocusTarget = globalThis?.document?.activeElement || null;
    }
    if (isArchiveOpen && (archiveMarkupChanged || !lastArchiveOpen)) {
      focusArchiveDialog();
    } else if (!isArchiveOpen && lastArchiveOpen) {
      const nextFocusTarget = archiveRestoreFocusTarget;
      archiveRestoreFocusTarget = null;
      nextFocusTarget?.focus?.();
    }
    lastArchiveOpen = isArchiveOpen;
    if (bugReport.isOpen && !lastBugReportOpen) {
      shell.modalLayer.querySelector?.('[data-bug-report-field="description"]')?.focus?.();
    } else if (!bugReport.isOpen && lastBugReportOpen) {
      const nextFocusTarget = bugReportRestoreFocusTarget;
      bugReportRestoreFocusTarget = null;
      nextFocusTarget?.focus?.();
    }
    lastBugReportOpen = bugReport.isOpen;
    if (metadataModalChanged) {
      if (isMetadataModalOpen) {
        focusMetadataTitleField(shell.stagePane);
      } else {
        const restoreTarget = shell.stagePane.querySelector?.(metadataRestoreFocusSelector);
        if (typeof restoreTarget?.focus === "function") {
          restoreTarget.focus();
        } else {
          focusExportRunButton(shell.stagePane);
        }
      }
    }
    lastMetadataModalOpen = isMetadataModalOpen;
    if (state.ui.activeStep !== lastRenderedStep) {
      if (lastRenderedStep) workspaceMotion.step();
      lastRenderedStep = state.ui.activeStep;
      const heading = shell.stagePane.querySelector?.("[data-screen-heading]");
      if (typeof heading?.focus === "function") {
        heading.focus();
      } else if (typeof shell.stagePane.focus === "function") {
        shell.stagePane.focus();
      }
    }
  }

  async function refreshBackendState() {
    const payload = await runtimeBridge.getBackendState();
    lastBackendReady = Boolean(payload?.ready);
    setState((next) => {
      next.ui.backend = payload;
      return next;
    });
    if (lastBackendReady) {
      if (restorePending) { restorePending = false; reconnectJob(); }
      void refreshLocalMediaRegistry();
      void refreshArchiveLibrary();
    }
  }

  async function refreshLocalMediaRegistry() {
    if (typeof runtimeApi.getLocalMediaRegistry !== "function") {
      return;
    }
    const requestToken = ++registryRefreshToken;
    try {
      const payload = await runtimeApi.getLocalMediaRegistry();
      if (requestToken !== registryRefreshToken) {
        return;
      }
      const items = Array.isArray(payload?.items) ? payload.items : [];
      setState((next) => {
        next.source.registryItems = items;
        return next;
      });
    } catch (_) {
      if (requestToken !== registryRefreshToken) {
        return;
      }
    }
  }

  async function refreshArchiveLibrary() {
    if (typeof runtimeApi.getArchiveLibrary !== "function") {
      return;
    }
    const requestToken = ++archiveRefreshToken;
    setState((next) => {
      next.archive.status = "loading";
      next.archive.error = "";
      return next;
    });
    try {
      const payload = await runtimeApi.getArchiveLibrary();
      if (requestToken !== archiveRefreshToken) {
        return;
      }
      const items = Array.isArray(payload?.items) ? payload.items : [];
      setState((next) => {
        next.archive.items = items;
        next.archive.status = "ready";
        next.archive.error = "";
        if (!items.some((item) => item.sourceKey === next.archive.selectedSourceKey)) {
          next.archive.selectedSourceKey = "";
        }
        return next;
      });
    } catch (error) {
      if (requestToken !== archiveRefreshToken) {
        return;
      }
      setState((next) => {
        next.archive.status = "error";
        next.archive.error = describeError(error, store.getState().ui.locale || "en");
        next.archive.selectedSourceKey = "";
        return next;
      });
    }
  }

  function openArchive() {
    const state = store.getState();
    setState((next) => {
      next.archive.isOpen = true;
      return next;
    });
    if (state.ui.backend?.ready && (state.archive.status === "idle" || state.archive.status === "error")) {
      void refreshArchiveLibrary();
    }
    if (state.ui.backend?.ready) {
      void refreshCacheUsage();
    }
  }

  function setArchiveStorage(patch) {
    setState((next) => {
      next.archive.storage = { ...(next.archive.storage || {}), ...patch };
      return next;
    });
  }

  let cacheUsageToken = 0;
  async function refreshCacheUsage() {
    if (typeof runtimeApi.getCacheUsage !== "function") {
      return;
    }
    const requestToken = ++cacheUsageToken;
    setArchiveStorage({ status: "loading" });
    try {
      const usage = await runtimeApi.getCacheUsage();
      if (requestToken !== cacheUsageToken) return;
      setArchiveStorage({ status: "ready", totalHuman: usage.totalHuman, totalPaths: usage.totalPaths });
    } catch (_) {
      if (requestToken !== cacheUsageToken) return;
      setArchiveStorage({ status: "error" });
    }
  }

  async function clearAppCache() {
    const locale = store.getState().ui.locale || "en";
    if (typeof runtimeApi.clearCache !== "function") {
      return;
    }
    setArchiveStorage({ status: "clearing", error: "", result: "" });
    let result;
    try {
      result = await runtimeApi.clearCache();
    } catch (error) {
      setArchiveStorage({
        status: "ready",
        confirm: false,
        error: error?.status === 409 ? t("archive.storage.blocked", { locale }) : describeError(error, store.getState().ui.locale || "en"),
      });
      return;
    }
    stopPolling();
    stopSourcePreparePolling();
    const skipped = Array.isArray(result?.skippedPaths) ? result.skippedPaths.length : 0;
    const message = skipped
      ? t("archive.storage.partial", { locale, replacements: { size: result.reclaimedHuman, count: skipped } })
      : t("archive.storage.done", { locale, replacements: { size: result.reclaimedHuman } });
    // Everything the session pointed at (jobs, previews, prepared videos) lived in the cleared folder.
    setState((next) => {
      const fresh = createInitialSessionState();
      fresh.ui.locale = next.ui.locale;
      fresh.ui.backend = next.ui.backend;
      fresh.ui.inlineNotice = message;
      fresh.archive = {
        ...fresh.archive,
        isOpen: next.archive.isOpen,
        storage: { status: "ready", confirm: false, result: message, error: "", totalHuman: next.archive.storage?.totalHuman || "", totalPaths: next.archive.storage?.totalPaths || 0 },
      };
      return fresh;
    });
    lastStageMarkup = "";
    refreshCompletedLibraries();
    void refreshCacheUsage();
  }

  function closeArchive() {
    setState((next) => {
      next.archive.isOpen = false;
      next.archive.selectedSourceKey = "";
      return next;
    });
  }

  function getArchiveItem(sourceKey) {
    const key = String(sourceKey || "").trim() || store.getState().archive.selectedSourceKey;
    if (!key) {
      return null;
    }
    return store.getState().archive.items.find((item) => item.sourceKey === key) || null;
  }

  function refreshCompletedLibraries() {
    void refreshLocalMediaRegistry();
    void refreshArchiveLibrary();
  }

  async function loadSourceFromPath(filePath, sourceDetails = {}) {
    const targetPath = String(filePath || "").trim();
    if (!targetPath) {
      return;
    }
    resetCurrentSourceSession();
    setState((next) => {
      next.source.error = "";
      next.source.status = "loading";
      return next;
    });
    await sourceController.selectLocalFile(targetPath, sourceDetails);
    await loadSelectedPreviewCandidate();
  }

  async function loadSelectedPreviewCandidate() {
    const state = store.getState();
    if (state.ui.activeStep !== "roi" || !state.source.filePath || state.roi.previewImage) {
      return;
    }
    if (!getSelectedPreviewCandidate(state)) {
      return;
    }
    await loadPreview();
  }

  /** A restored review draft applies only to the job revision it was made on. */
  function restoredDraftFor(review, job, pages) {
    if (!pages.length || !Array.isArray(review.restoredSelectedPaths)) return null;
    const key = review.restoredDraftKey;
    if (key && (key.jobId !== String(job.job_id || "") || key.revision !== jobRevision(job.result || {}))) return null;
    return {
      selectedPaths: review.restoredSelectedPaths,
      systemOrder: Array.isArray(review.restoredSystemOrder) ? review.restoredSystemOrder : null,
      // "saved" needs the revision key: without it the draft may belong to another build
      applied: Boolean(key) && review.restoredApplied === true,
    };
  }

  function orderPagesBySystemIds(pages, systemOrder) {
    if (!Array.isArray(systemOrder) || !pages.some(page => page.kind === "system")) return pages;
    const rank = new Map(systemOrder.map((id, index) => [String(id), index]));
    const keyOf = page => page.systemId || page.capturePath;
    return [...pages].sort((a, b) => (rank.has(keyOf(a)) ? rank.get(keyOf(a)) : systemOrder.length + a.index)
      - (rank.has(keyOf(b)) ? rank.get(keyOf(b)) : systemOrder.length + b.index));
  }

  function applyJobSnapshot(job) {
    const locale = store.getState().ui.locale || "en";
    let pages = deriveCapturePages(job.result || {}, locale);
    setState((next) => {
      const displayMessage = formatExportJobMessage(job.message, {
        status: job.status,
        locale: next.ui.locale,
        errorCode: job.error_code,
      });
      next.exportConfig.jobId = job.job_id;
      next.exportConfig.runStatus = ["done", "error", "cancelled"].includes(job.status) ? job.status : "running";
      next.exportConfig.connectionState = "connected";
      next.exportConfig.progress = Number(job.progress || 0);
      next.exportConfig.currentStep = String(job.current_step || "");
      next.exportConfig.message = displayMessage;
      next.exportConfig.error = job.status === "error" ? displayMessage || t("export.failed", { locale: next.ui.locale }) : "";
      next.exportConfig.errorCode = job.status === "error" && job.error_code ? String(job.error_code) : "";
      next.exportConfig.outputDir = String(job.result?.output_dir || "");
      next.exportConfig.pdfPath = String(job.result?.pdf || "");
      const draft = restoredDraftFor(next.review, job, pages);
      // the order the capture built its files in (video order), before a restored draft rearranges it
      const capturedOrder = pages.map(page => page.id);
      if (draft) pages = orderPagesBySystemIds(pages, draft.systemOrder);
      next.review.pages = pages;
      next.review.jobRevision = jobRevision(job.result || {});
      next.review.reflow = deriveReflowInfo(job.result || {});
      const wasOriginal = Boolean(next.review.originalScreens?.active);
      next.review.originalScreens = deriveOriginalScreens(job.result || {}, next.roi?.appliedRect);
      // other rows now (clean systems <-> original screens): the review controller drops its history too
      if (wasOriginal !== next.review.originalScreens.active) { next.review.canUndo = false; next.review.canRedo = false; }
      // hypotheses belong to one delivered export: another job or a rebuild reloads them
      if (next.review.hypotheses?.jobId !== job.job_id || next.review.hypotheses?.revision !== next.review.jobRevision) {
        next.review.hypotheses = createReviewHypothesesState();
      }
      next.review.outputPages = deriveOutputPages(job.result || {});
      // no pages to show: back to the default view, so the next build opens on its pages
      if (!next.review.outputPages.length) next.review.pagePreview = null;
      const preferredPageIds = pages.filter((page) => !page.autoExcludeCandidate).map((page) => page.id);
      const savedSelection = next.review.originalScreens.active ? job.result?.original_screens?.selected
        : job.result?.review_export?.selected_captures?.length
          ? job.result.review_export.selected_captures : job.result?.review_export?.selected_pages;
      const restoredDraft = Boolean(draft);
      const savedPageIds = savedSelection?.length
        ? pages.filter(page => savedSelection.includes(page.capturePath)).map(page => page.id) : [];
      next.review.selectedPageIds = savedSelection?.length
        ? savedPageIds
        : pages.some(page => page.autoExcludeCandidate) ? preferredPageIds : pages.map((page) => page.id);
      // Files from the capture itself (no review rebuild yet): a clean chart built every system it
      // kept, in video order, which is the default selection. A layout conflict built no file.
      const firstCaptureFiles = !savedSelection?.length && !next.review.originalScreens.active
        && job.status === "done" && pages.some(page => page.kind === "system")
        && Boolean(job.result?.pdf || job.result?.images?.length)
        && String(job.result?.reflow_state || "") !== "layout_conflict";
      const firstCaptureIds = firstCaptureFiles ? [...next.review.selectedPageIds] : [];
      let draftMatchesSavedFiles = false;
      if (draft) {
        next.review.selectedPageIds = pages.filter(page => draft.selectedPaths.includes(page.capturePath)).map(page => page.id);
        // The draft is still what the saved files were built from only when the last session marked
        // it saved on this same job revision and every restored and saved capture maps to the same rows.
        draftMatchesSavedFiles = draft.applied
          && savedPageIds.length > 0
          && savedPageIds.length === savedSelection.length
          && draft.selectedPaths.length === next.review.selectedPageIds.length
          && savedPageIds.length === next.review.selectedPageIds.length
          && savedPageIds.every(id => next.review.selectedPageIds.includes(id));
        // or, before any rebuild, it is still the capture's own selection and order
        if (draft.applied && firstCaptureFiles) {
          draftMatchesSavedFiles = draft.selectedPaths.length === firstCaptureIds.length
            && next.review.selectedPageIds.length === firstCaptureIds.length
            && firstCaptureIds.every(id => next.review.selectedPageIds.includes(id))
            && pages.every((page, index) => page.id === capturedOrder[index]);
        }
        next.review.status = "idle";
      }
      if (pages.length) {
        // consumed (applied, or dropped because it belongs to another job revision)
        delete next.review.restoredSelectedPaths;
        delete next.review.restoredDraftKey;
        delete next.review.restoredSystemOrder;
        delete next.review.restoredApplied;
      }
      next.review.focusedPageId = pages.some(page => page.id === next.review.focusedPageId)
        ? next.review.focusedPageId : next.review.selectedPageIds[0] || pages[0]?.id || "";
      next.review.outputDir = String(job.result?.output_dir || "");
      next.review.pdfPath = String(job.result?.pdf || "");
      next.review.keptCount = Number(job.result?.review_export?.kept_count || pages.length || 0);
      next.review.status = restoredDraft ? (draftMatchesSavedFiles ? "applied" : "idle")
        : job.result?.review_export || next.review.originalScreens.active || firstCaptureFiles ? "applied" : "idle";
      next.review.error = "";
      // Recoverable failures retain the systems for review and rebuilding.
      if (isReviewableRun(next) && pages.length) {
        next.ui.activeStep = "review";
      }
      return next;
    });
  }

  function stopPolling() {
    if (activePoll) {
      clearTimeout(activePoll);
      activePoll = null;
    }
  }

  function stopSuggestionPolling() {
    if (activeSuggestionPoll) {
      clearTimeout(activeSuggestionPoll);
      activeSuggestionPoll = null;
    }
  }

  /**
   * Merge facts that arrive after a job is done (clean reflow "looks similar"
   * suggestions, a layout conflict found by a rebuild) into the review list
   * without touching the user's selection, order or pending edits.
   */
  function mergeJobFacts(job) {
    const locale = store.getState().ui.locale || "en";
    const fresh = deriveCapturePages(job.result || {}, locale);
    const byPath = new Map(fresh.map(page => [page.capturePath, page]));
    setState((next) => {
      if (next.exportConfig.jobId !== job.job_id) return next;
      next.review.reflow = deriveReflowInfo(job.result || {});
      if (jobRevision(job.result || {}) !== next.review.jobRevision) return next;
      next.review.pages = next.review.pages.map((page) => {
        const update = byPath.get(page.capturePath);
        if (!update) return page;
        return {
          ...page,
          similarTo: update.similarTo,
          suspicious: update.suspicious,
          warningReason: update.warningReason,
          diagnosticCodes: update.diagnosticCodes,
        };
      });
      return next;
    });
  }

  async function pollSuggestions(jobId, jobHandle, attempt = 0) {
    stopSuggestionPolling();
    try {
      const job = await runtimeApi.getJob(jobId);
      if (!runtimeGuards.isCurrentJob(jobHandle, jobId)) return;
      mergeJobFacts(job);
      if (job.result?.reflow?.suggestions_state === "pending" && attempt < 200) {
        activeSuggestionPoll = setTimeout(() => pollSuggestions(jobId, jobHandle, attempt + 1), 1500);
      }
    } catch (_) {
      if (runtimeGuards.isCurrentJob(jobHandle, jobId) && attempt < 200) {
        activeSuggestionPoll = setTimeout(() => pollSuggestions(jobId, jobHandle, attempt + 5), 4000);
      }
    }
  }

  function stopSourcePreparePolling() {
    if (activeSourcePreparePoll) {
      clearTimeout(activeSourcePreparePoll);
      activeSourcePreparePoll = null;
    }
  }

  // Restarting now would abandon a capture, a YouTube import or a review rebuild.
  function isWorkRunning(state = store.getState()) {
    return state.exportConfig.runStatus === "running"
      || state.source.prepareStatus === "loading"
      || ["running", "editing"].includes(state.review.status);
  }

  // Drafts that live only in this window: an unapplied score region, an open page crop, the file header form.
  function hasUnsavedEdits(state = store.getState()) {
    return hasDirtyRoiDraft(state) || Boolean(state.review.cropping) || Boolean(state.exportConfig.metadataModal?.isOpen);
  }

  function isUpdateInstalling() {
    return releaseUpdate?.status === "installing";
  }

  function currentFailureDetail(state = store.getState()) {
    return [state.source.error, state.roi.error, state.exportConfig.error, state.review.error].filter(Boolean).join("\n");
  }

  function setBugReport(patch) {
    bugReport = { ...bugReport, ...patch };
    render();
  }

  // Typing updates the draft without a render; this keeps a later render from resetting the caret.
  function syncBugReportDraft(field, value) {
    bugReport = { ...bugReport, draft: { ...bugReport.draft, [field]: value } };
    lastArchiveMarkup = renderBugReportModal(bugReport, store.getState().ui.locale || "en");
  }

  function replaceBugReportKeepingFocus(markup) {
    const active = globalThis.document?.activeElement;
    const inside = active && shell.modalLayer.contains?.(active) ? active : null;
    const field = inside?.dataset?.bugReportField || "";
    const action = inside?.dataset?.action || "";
    const selection = field && typeof inside.selectionStart === "number" ? [inside.selectionStart, inside.selectionEnd] : null;
    const scrollTop = shell.modalLayer.querySelector?.(".bug-report-body")?.scrollTop || 0;
    const logOpen = Boolean(shell.modalLayer.querySelector?.(".bug-report-diagnostics")?.open);
    shell.modalLayer.innerHTML = markup;
    const logDetails = shell.modalLayer.querySelector?.(".bug-report-diagnostics");
    if (logDetails) logDetails.open = logOpen;
    const body = shell.modalLayer.querySelector?.(".bug-report-body");
    if (body) body.scrollTop = scrollTop;
    if (!inside) return;
    const selector = field ? `[data-bug-report-field="${field}"]` : action ? `[data-action="${action}"]:not([disabled])` : "";
    const next = (selector && shell.modalLayer.querySelector?.(selector))
      || shell.modalLayer.querySelector?.("[data-bug-report-dialog]");
    next?.focus?.({ preventScroll: true });
    if (selection) next?.setSelectionRange?.(selection[0], selection[1]);
  }

  async function openBugReport() {
    if (bugReport.isOpen || bugReportPreparing) return;
    bugReportPreparing = true;
    bugReportRestoreFocusTarget = globalThis.document?.activeElement || null;
    // The screenshot is taken now, before the dialog covers the screen being reported.
    const prepared = await Promise.resolve(runtimeBridge.prepareBugReport?.(currentFailureDetail())).catch(() => null);
    bugReportPreparing = false;
    if (destroyed) return;
    setBugReport({
      isOpen: true,
      status: "editing",
      configured: Boolean(prepared?.configured),
      diagnostics: String(prepared?.diagnostics || ""),
      screenshotPreview: String(prepared?.screenshotPreview || ""),
      invalid: "",
      errorReason: "",
      notice: "",
    });
  }

  function closeBugReport() {
    if (!bugReport.isOpen || bugReport.status === "sending") return;
    // An unsent draft survives closing; a sent one starts over.
    const draft = bugReport.status === "sent" ? createBugReportDraft() : bugReport.draft;
    setBugReport({ isOpen: false, status: "editing", invalid: "", errorReason: "", notice: "", draft });
  }

  function focusBugReport(selector) {
    shell.modalLayer.querySelector?.(selector)?.focus?.();
  }

  function invalidBugReportField(draft) {
    if (!draft.description.trim()) return "description";
    const email = draft.email.trim();
    if (bugReport.configured && email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return "email";
    return "";
  }

  async function submitBugReport() {
    if (bugReport.status === "sending") return;
    const invalid = invalidBugReportField(bugReport.draft);
    if (invalid) {
      setBugReport({ invalid, status: "editing", errorReason: "" });
      focusBugReport(`[data-bug-report-field="${invalid}"]`);
      return;
    }
    setBugReport({ status: "sending", invalid: "", errorReason: "", notice: "" });
    const locale = store.getState().ui.locale || "en";
    const result = await Promise.resolve(runtimeBridge.sendBugReport?.({ ...bugReport.draft, locale }))
      .catch(() => ({ status: "error", reason: "network" }));
    if (destroyed || !bugReport.isOpen) return;
    if (result?.status === "sent") {
      setBugReport({ status: "sent" });
      focusBugReport('[data-action="close-bug-report"]:not(.archive-backdrop):not(.archive-close)');
    } else if (result?.status === "invalid") {
      setBugReport({ status: "editing", invalid: String(result.field || "description") });
      focusBugReport(`[data-bug-report-field="${bugReport.invalid}"]`);
    } else {
      setBugReport({ status: "error", errorReason: String(result?.reason || "network") });
      focusBugReport('[data-action="send-bug-report"]');
    }
  }

  async function openBugReportIssue() {
    const locale = store.getState().ui.locale || "en";
    if (!bugReport.draft.description.trim()) {
      setBugReport({ invalid: "description" });
      focusBugReport('[data-bug-report-field="description"]');
      return;
    }
    const { email: _email, ...draft } = bugReport.draft;
    const result = await Promise.resolve(runtimeBridge.openBugReportIssue?.(draft)).catch(() => null);
    if (destroyed) return;
    setBugReport({
      invalid: "",
      notice: !result?.opened ? t("support.actionFailed", { locale }) : result.copied ? t("bugReport.githubCopied", { locale }) : "",
    });
  }

  function renderReleaseUpdateGroup(locale, hasFailure) {
    const update = releaseUpdate || {};
    const replacements = { version: String(update.version || ""), progress: Number(update.progress) || 0 };
    const button = (action, key, tone = "secondary", disabled = false) =>
      `<button class="button button-${tone}" data-action="${action}"${disabled ? " disabled" : ""}>${escapeHtml(t(key, { locale }))}</button>`;
    let message = "";
    let actions = "";
    if (update.status === "available" && (!hasFailure || update.manual)) {
      const requiredOs = update.requiredOs;
      message = requiredOs
        ? t("update.requiresOs", { locale, replacements: { ...replacements, os: `${requiredOs.platform === "darwin" ? "macOS" : "Windows"} ${requiredOs.version}` } })
        : t("update.available", { locale, replacements });
      actions = (update.canInstall ? button("download-release-update", "update.install") : button("open-release-page", "update.open"))
        + button("dismiss-release-update", "update.dismiss", "ghost");
    } else if (update.status === "error" && update.error === "download") {
      message = t("update.downloadFailed", { locale });
      actions = button("download-release-update", "update.retry") + button("open-release-page", "update.open", "ghost");
    } else if (update.status === "downloading") {
      message = t("update.downloading", { locale, replacements });
    } else if (update.status === "ready") {
      const busy = isWorkRunning() || hasUnsavedEdits();
      message = update.error === "install"
        ? t("update.installFailed", { locale })
        : [t("update.ready", { locale, replacements }), busy || update.error === "busy" ? t("update.busy", { locale }) : ""].filter(Boolean).join(" ");
      actions = button("install-release-update", update.error === "install" ? "update.retry" : "update.restart", "secondary", busy)
        + (update.error === "install" ? button("open-release-page", "update.open", "ghost") : "");
    } else if (update.status === "installing") {
      message = t("update.installing", { locale });
    } else if (update.status === "manual") {
      message = t(update.reason === "swap-failed" ? "update.manualFailed" : "update.manual", { locale });
      actions = button("open-release-installer", "update.openInstaller");
    }
    return message ? `<div class="status-bar-group status-bar-recovery"><span>${escapeHtml(message)}</span>${actions}</div>` : "";
  }

  // Status and dock markup is replaced wholesale; put keyboard focus back on the same control.
  function replaceKeepingFocus(container, markup, fallback) {
    const active = globalThis.document?.activeElement;
    const focused = active && active !== container && container.contains?.(active) ? active : null;
    const action = focused?.dataset?.action || "";
    const locale = focused?.dataset?.locale || "";
    container.innerHTML = markup;
    if (!focused) return;
    const selector = `[data-action="${action}"]${locale ? `[data-locale="${locale}"]` : ""}:not([disabled])`;
    const next = (action && container.querySelector?.(selector)) || fallback?.();
    next?.focus?.();
  }

  function applyReleaseUpdate(update) {
    if (destroyed || !update || typeof update !== "object") return;
    releaseUpdate = update;
    render();
  }

  async function checkReleaseUpdateManually() {
    const locale = store.getState().ui.locale;
    // An update already found or in flight is the answer; checking again would only hide it.
    if (["available", "downloading", "ready", "installing", "manual"].includes(releaseUpdate.status)) {
      releaseUpdate = { ...releaseUpdate, manual: true };
      render();
      return;
    }
    const result = await runtimeBridge.checkReleaseUpdate?.({ manual: true });
    applyReleaseUpdate(result);
    if (!result || result.status === "unsupported") setInlineNotice(t("update.unsupported", { locale }));
    else if (result.status === "current") setInlineNotice(t("update.current", { locale, replacements: { version: result.currentVersion } }));
    else if (result.status === "error") setInlineNotice(t("update.checkFailed", { locale }));
  }

  function setInlineNotice(message) {
    setState((next) => {
      next.ui.inlineNotice = String(message || "");
      return next;
    });
  }

  function setActiveSourceDropZone(nextZone) {
    if (activeSourceDropZone === nextZone) {
      return;
    }
    activeSourceDropZone?.classList?.remove("is-drop-active");
    activeSourceDropZone = nextZone || null;
    activeSourceDropZone?.classList?.add("is-drop-active");
  }

  function clearActiveSourceDropZone() {
    setActiveSourceDropZone(null);
  }

  async function pollJob(jobId, jobHandle) {
    stopPolling();
    try {
      const job = await runtimeApi.getJob(jobId);
      if (!runtimeGuards.isCurrentJob(jobHandle, jobId)) {
        return;
      }
      pollFailures = 0;
      if (jobId === restoredJobId) restoredJobId = "";
      applyJobSnapshot(job);
      if (["done", "error", "cancelled"].includes(job.status)) {
        stopPolling();
        if (job.status === "error" && (isLayoutConflictPending(store.getState()) || isLedgerFailurePending(store.getState()))) {
          // no chart yet; suggestions and a rebuild started before a reload still arrive
          if (job.result?.reflow?.suggestions_state === "pending") {
            activeSuggestionPoll = setTimeout(() => pollSuggestions(jobId, jobHandle), 1500);
          }
          void resumeReviewExport(jobId);
        }
        if (job.status === "done") {
          refreshCompletedLibraries();
          // The chart is published first; "looks similar" suggestions arrive afterwards.
          if (job.result?.reflow?.suggestions_state === "pending") {
            activeSuggestionPoll = setTimeout(() => pollSuggestions(jobId, jobHandle), 1500);
          }
          // a PDF rebuild may still be running from before a reload: follow it
          if (["clean_reflow_v1", "original_screens_v1"].includes(job.result?.output_model)) void resumeReviewExport(jobId);
        }
        return;
      }
      activePoll = setTimeout(() => {
        pollJob(jobId, jobHandle);
      }, 1000);
    } catch (error) {
      if (!runtimeGuards.isCurrentJob(jobHandle, jobId)) {
        return;
      }
      if (error?.status === 404 && jobId === restoredJobId) {
        forgetMissingRestoredJob();
        return;
      }
      pollFailures += 1;
      const terminal = [401, 403, 404].includes(error?.status);
      setState((next) => {
        next.exportConfig.runStatus = terminal ? "error" : "running";
        next.exportConfig.connectionState = terminal || pollFailures >= 5 ? "paused" : "reconnecting";
        next.exportConfig.error = t("export.connectionLost", { locale: next.ui.locale });
        return next;
      });
      if (!terminal && pollFailures < 5) {
        activePoll = setTimeout(() => pollJob(jobId, jobHandle), Math.min(1000 * 2 ** (pollFailures - 1), 8000));
      }
    }
  }

  // The restored job is gone from the backend (folder deleted or moved), so retrying cannot help.
  // Drop only that job reference and its review draft; the source video and ROI stay.
  function forgetMissingRestoredJob() {
    restoredJobId = "";
    stopPolling();
    setState((next) => {
      next.exportConfig.jobId = "";
      next.exportConfig.runStatus = "idle";
      next.exportConfig.error = "";
      delete next.exportConfig.connectionState;
      delete next.review.restoredSelectedPaths;
      delete next.review.restoredDraftKey;
      delete next.review.restoredSystemOrder;
      delete next.review.restoredApplied;
      // The video and applied region are kept, so the user can make the files again.
      next.ui.activeStep = next.source.filePath && isRectValid(next.roi.appliedRect) ? "export" : "source";
      next.ui.inlineNotice = t("export.restoredJobMissing", { locale: next.ui.locale });
      return next;
    });
  }

  function reconnectJob() {
    const jobId = store.getState().exportConfig.jobId;
    if (!jobId) return;
    pollFailures = 0;
    activeJobHandle = runtimeGuards.attachJob(runtimeGuards.beginExportRun(), jobId);
    void pollJob(jobId, activeJobHandle);
  }

  async function cancelCurrentJob() {
    const state = store.getState();
    if (!state.exportConfig.jobId || !runtimeApi.cancelJob) return;
    try {
      await runtimeApi.cancelJob(state.exportConfig.jobId);
      if (store.getState().exportConfig.jobId === state.exportConfig.jobId) reconnectJob();
    } catch (error) {
      setInlineNotice(describeError(error, store.getState().ui.locale || "en"));
    }
  }

  async function pollSourcePrepareJob(jobId, prepareHandle, requestToken) {
    stopSourcePreparePolling();
    try {
      const snapshot = await runtimeApi.getPreviewSourceJob(jobId);
      if (!runtimeGuards.isCurrentSourcePrepareJob(prepareHandle, jobId)) {
        return;
      }
      sourceController.applyPrepareJobSnapshot(snapshot, requestToken);
      if (snapshot.status === "done") {
        stopSourcePreparePolling();
        try {
          const completed = await sourceController.completeYoutubePrepare(snapshot, requestToken);
          if (!completed) {
            return;
          }
          activeSourcePrepareHandle = null;
          runtimeGuards.bumpSourceSession();
          await loadSelectedPreviewCandidate();
          void refreshLocalMediaRegistry();
        } catch (error) {
          if (!runtimeGuards.isCurrentSourcePrepareJob(prepareHandle, jobId)) {
            return;
          }
          activeSourcePrepareHandle = null;
          runtimeGuards.invalidateSourcePrepare();
          sourceController.failYoutubePrepare(error, requestToken);
        }
        return;
      }
      if (snapshot.status === "error") {
        stopSourcePreparePolling();
        activeSourcePrepareHandle = null;
        runtimeGuards.invalidateSourcePrepare();
        return;
      }
      activeSourcePreparePoll = setTimeout(() => {
        pollSourcePrepareJob(jobId, prepareHandle, requestToken);
      }, 1000);
    } catch (error) {
      if (!runtimeGuards.isCurrentSourcePrepareJob(prepareHandle, jobId)) {
        return;
      }
      stopSourcePreparePolling();
      activeSourcePrepareHandle = null;
      runtimeGuards.invalidateSourcePrepare();
      sourceController.failYoutubePrepare(error, requestToken);
    }
  }

  async function prepareYoutubeSource() {
    const youtubeUrl = store.getState().source.youtubeUrl;
    resetCurrentSourceSession();
    const requestToken = sourceController.startYoutubePrepare(youtubeUrl);
    const prepareToken = runtimeGuards.beginSourcePrepare();

    try {
      const jobId = await runtimeApi.createPreviewSourceJob({ youtubeUrl });
      if (!runtimeGuards.isCurrentSourcePrepare(prepareToken)) {
        return;
      }
      activeSourcePrepareHandle = runtimeGuards.attachSourcePrepare(prepareToken, jobId);
      if (!activeSourcePrepareHandle) {
        return;
      }
      sourceController.applyPrepareJobStarted(jobId, requestToken);
      await pollSourcePrepareJob(jobId, activeSourcePrepareHandle, requestToken);
    } catch (error) {
      if (!runtimeGuards.isCurrentSourcePrepare(prepareToken)) {
        return;
      }
      activeSourcePrepareHandle = null;
      runtimeGuards.invalidateSourcePrepare();
      sourceController.failYoutubePrepare(error, requestToken);
    }
  }

  async function selectSourceFile() {
    activeSourceSelection += 1;
    const requestId = activeSourceSelection;
    setState((next) => {
      next.source.error = "";
      next.source.status = "loading";
      return next;
    });
    try {
      const filePath = await runtimeBridge.selectVideoFile();
      if (!filePath) {
        if (requestId !== activeSourceSelection) {
          return;
        }
        setState((next) => {
          next.source.status = "idle";
          return next;
        });
        return;
      }
      if (requestId !== activeSourceSelection) {
        return;
      }
      await loadSourceFromPath(filePath);
    } catch (error) {
      if (requestId !== activeSourceSelection) {
        return;
      }
      setState((next) => {
        next.source.status = "error";
        next.source.error = describeError(error, store.getState().ui.locale || "en");
        return next;
      });
    }
  }

  const handleDragEnter = (event) => {
    const dropZone = findSourceDropZone(event.target);
    if (!dropZone || store.getState().ui.activeStep !== "source" || !dataTransferHasFiles(event.dataTransfer)) {
      return;
    }
    setActiveSourceDropZone(dropZone);
  };

  const handleDragOver = (event) => {
    const dropZone = findSourceDropZone(event.target);
    if (!dropZone || store.getState().ui.activeStep !== "source" || !dataTransferHasFiles(event.dataTransfer)) {
      clearActiveSourceDropZone();
      return;
    }
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
    setActiveSourceDropZone(dropZone);
  };

  const handleDragLeave = (event) => {
    const dropZone = findSourceDropZone(event.target);
    if (!dropZone) {
      return;
    }
    const relatedZone = findSourceDropZone(event.relatedTarget);
    if (relatedZone === dropZone) {
      return;
    }
    clearActiveSourceDropZone();
  };

  const handleDrop = async (event) => {
    const dropZone = findSourceDropZone(event.target);
    clearActiveSourceDropZone();
    if (!dropZone || store.getState().ui.activeStep !== "source" || isUpdateInstalling()) {
      return;
    }
    if (!dataTransferHasFiles(event.dataTransfer)) {
      return;
    }

    event.preventDefault();
    const droppedPath = await getDroppedVideoPath(event.dataTransfer, runtimeBridge);
    if (!droppedPath) {
      setState((next) => {
        next.source.status = "error";
        next.source.error = t("source.dropInvalid", { locale: next.ui.locale || "en" });
        return next;
      });
      return;
    }

    activeSourceSelection += 1;
    try {
      await loadSourceFromPath(droppedPath);
    } catch (error) {
      setState((next) => {
        next.source.status = "error";
        next.source.error = describeError(error, store.getState().ui.locale || "en");
        return next;
      });
    }
  };

  async function loadPreview() {
    const state = store.getState();
    if (!state.source.filePath) {
      return;
    }
    const previewToken = runtimeGuards.beginPreviewRequest();
    setState((next) => {
      next.roi.status = "loading";
      next.roi.error = "";
      return next;
    });
    try {
      const preview = await runtimeApi.requestPreviewFrame({
        filePath: state.source.filePath,
        startSec: state.roi.frameTime || 0,
      });
      if (!runtimeGuards.isCurrentPreview(previewToken)) {
        releasePreviewImageUrl(preview.imagePath);
        return;
      }
      setState((next) => {
        next.roi.previewImage = preview.imagePath;
        next.roi.previewSourcePath = preview.sourcePath;
        next.roi.diagnostics = preview.diagnostics;
        next.roi.autoRoiStatus = "loading";
        next.roi.autoRoiEvidence = "";
        next.roi.autoRoiDiagnostics = {};
        next.roi.autoRoiUserEdited = false;
        next.roi.imageWidth = Number(next.source.metadata?.width || 0);
        next.roi.imageHeight = Number(next.source.metadata?.height || 0);
        next.roi.status = "ready";
        next.roi.error = "";
        return next;
      });
      try {
        const suggestion = await runtimeApi.requestAutoRoi({
          filePath: state.source.filePath,
          startSec: state.roi.frameTime || 0,
        });
        if (!runtimeGuards.isCurrentPreview(previewToken)) {
          return;
        }
        setState((next) => {
          const suggestedRect = suggestion.status === "suggested" && isRectValid(suggestion.roi)
            ? suggestion.roi
            : null;
          // Do not replace a box the user drew while background detection was
          // running. The detector only supplies a starting point.
          if (suggestedRect && !next.roi.autoRoiUserEdited) {
            next.roi.draftRect = suggestedRect;
          }
          next.roi.autoRoiStatus = suggestedRect ? "suggested" : "not_found";
          next.roi.autoRoiEvidence = suggestedRect ? suggestion.evidenceLevel : "low";
          next.roi.autoRoiDiagnostics = suggestion.diagnostics || {};
          return next;
        });
      } catch (_) {
        if (runtimeGuards.isCurrentPreview(previewToken)) {
          setState((next) => {
            next.roi.autoRoiStatus = "not_found";
            next.roi.autoRoiEvidence = "low";
            next.roi.autoRoiDiagnostics = {};
            return next;
          });
        }
      }
    } catch (error) {
      if (!runtimeGuards.isCurrentPreview(previewToken)) {
        return;
      }
      setState((next) => {
        next.roi.status = "error";
        next.roi.error = describeError(error, store.getState().ui.locale || "en");
        return next;
      });
    }
  }

  async function selectPreviewCandidate(candidateId) {
    const state = store.getState();
    const candidate = (state.roi.previewCandidates || []).find((item) => item.id === candidateId);
    if (!candidate) {
      return;
    }
    if (state.roi.selectedPreviewCandidateId === candidate.id && state.roi.previewImage) {
      return;
    }
    runtimeGuards.invalidatePreview();
    runtimeGuards.invalidateExport();
    stopPolling();
    activeJobHandle = null;
    setState((next) => {
      invalidatePreviewFlow(next, {
        frameTime: candidate.sec,
        frameTimeLabel: candidate.label,
        preserveCandidates: true,
        selectedPreviewCandidateId: candidate.id,
      });
      return next;
    });
    await loadPreview();
  }

  // Whole-video clipping check of the applied region. The result only shows a
  // warning and offers a larger draft; it never changes the draft or the
  // applied region by itself.
  async function checkAppliedRoi(rect) {
    const state = store.getState();
    if (!isRectValid(rect) || !state.source.filePath) return;
    const rectKey = JSON.stringify(rect);
    const sourcePath = state.source.filePath;
    setState((next) => {
      next.roi.clipCheck = { status: "loading", rectKey, suggestedRect: null };
      return next;
    });
    let status = "error";
    let suggestedRect = null;
    try {
      const health = await runtimeApi.requestPreviewRoiHealth({
        filePath: sourcePath,
        startSec: state.roi.frameTime || 0,
        roi: rect,
      });
      const envelope = health?.envelope || {};
      suggestedRect = envelope.clipped && isRectValid(envelope.suggestedRoi) ? envelope.suggestedRoi : null;
      status = envelope.clipped ? "clipped" : envelope.status === "found" ? "clear" : "error";
    } catch (_) {
      status = "error";
    }
    setState((next) => {
      // Ignore a result for a region or source that is no longer applied.
      if (next.source.filePath !== sourcePath || next.roi.clipCheck?.rectKey !== rectKey) return next;
      // A request made while the processor was not running (it is still starting
      // after a restart, or restarting) never reached it: that is not a failed
      // check. Go back to "not checked" so the check runs once it is ready.
      if (status === "error" && !next.ui.backend?.ready) {
        next.roi.clipCheck = { status: "idle", rectKey: "", suggestedRect: null, retry: true };
        return next;
      }
      next.roi.clipCheck = { status, rectKey, suggestedRect };
      return next;
    });
  }

  function maybeCheckAppliedRoi(state) {
    // Apply starts the check itself (and moves to the export step, which shows the
    // result); here only a region applied earlier and viewed on the ROI step is
    // checked, and only once the processor is ready: after a restart a restored
    // session renders before it is up, and a request sent then never reaches it.
    // A check cut off before the processor was up (Apply right after a restart) also
    // reruns on the export step, where its result is shown.
    const step = state.ui.activeStep;
    if (!(step === "roi" || (step === "export" && state.roi.clipCheck?.retry)) || !isRectValid(state.roi.appliedRect)) return;
    if (!state.ui.backend?.ready) return;
    const rectKey = JSON.stringify(state.roi.appliedRect);
    if (state.roi.clipCheck?.rectKey === rectKey) return;
    const rect = state.roi.appliedRect;
    // Start after the current render pass; the check sets its own state.
    Promise.resolve().then(() => {
      const latest = store.getState();
      if (latest.roi.clipCheck?.rectKey === rectKey || JSON.stringify(latest.roi.appliedRect) !== rectKey) return;
      if (!latest.ui.backend?.ready) return;
      void checkAppliedRoi(rect);
    });
  }

  // Section labels outside the applied score region: the result is only shown,
  // and a suggested label area is loaded as an editable draft by a user action.
  async function checkLabelRegion(rect) {
    const state = store.getState();
    if (!isRectValid(rect) || !state.source.filePath || typeof runtimeApi.requestLabelRegion !== "function") return;
    const rectKey = JSON.stringify(rect);
    const sourcePath = state.source.filePath;
    setState((next) => {
      next.roi.labelCheck = { status: "loading", rectKey, suggestedRect: null };
      return next;
    });
    let status = "error";
    let suggestedRect = null;
    try {
      const range = captureRange(state);
      const found = await runtimeApi.requestLabelRegion({ filePath: sourcePath, roi: rect, startSec: range.start, endSec: range.end });
      suggestedRect = found?.status === "suggested" && isRectValid(found.labelRoi) ? found.labelRoi : null;
      status = suggestedRect ? "suggested" : "not_found";
    } catch (_) {
      status = "error";
    }
    setState((next) => {
      if (next.source.filePath !== sourcePath || next.roi.labelCheck?.rectKey !== rectKey) return next;
      next.roi.labelCheck = { status, rectKey, suggestedRect };
      return next;
    });
  }

  function defaultLabelDraft(state) {
    const applied = state.roi.appliedRect;
    const width = Number(state.roi.imageWidth) || 1920;
    const height = Number(state.roi.imageHeight) || 1080;
    const top = isRectValid(applied) ? Math.min(...applied.map(point => Number(point[1]))) : height * 0.7;
    const y1 = Math.max(height * 0.08, top - height * 0.12);
    const y0 = Math.max(0, y1 - height * 0.1);
    return [[width * 0.03, y0], [width * 0.3, y0], [width * 0.3, y1], [width * 0.03, y1]].map(point => point.map(Math.round));
  }

  function editLabelArea({ useSuggestion = false } = {}) {
    const state = store.getState();
    const suggestion = state.roi.labelCheck?.status === "suggested" ? state.roi.labelCheck.suggestedRect : null;
    const draft = useSuggestion && isRectValid(suggestion) ? suggestion
      : state.roi.labelAppliedRect || (isRectValid(suggestion) ? suggestion : defaultLabelDraft(state));
    setState((next) => {
      next.roi.editTarget = "labels";
      next.roi.labelDraftRect = draft.map((point) => [Number(point[0]), Number(point[1])]);
      next.ui.activeStep = "roi";
      return next;
    });
  }

  function applyLabelArea() {
    const points = roiEditor?.applyDraft?.() || store.getState().roi.labelDraftRect;
    if (!isRectValid(points)) return;
    setState((next) => {
      next.roi.labelAppliedRect = points.map((point) => [Number(point[0]), Number(point[1])]);
      next.roi.labelDraftRect = null;
      next.roi.editTarget = "score";
      return next;
    });
  }

  function removeLabelArea() {
    setState((next) => {
      next.roi.labelAppliedRect = null;
      next.roi.labelDraftRect = null;
      next.roi.editTarget = "score";
      return next;
    });
  }

  function useSuggestedRoi() {
    const state = store.getState();
    const check = state.roi.clipCheck || {};
    if (check.status !== "clipped" || !isRectValid(check.suggestedRect)) return;
    if (check.rectKey !== JSON.stringify(state.roi.appliedRect)) return;
    const rect = check.suggestedRect.map((point) => [Number(point[0]), Number(point[1])]);
    setState((next) => {
      // A user action: load as an editable draft only, and keep a late
      // automatic suggestion from replacing it.
      next.roi.draftRect = rect;
      next.roi.autoRoiUserEdited = true;
      // Show the score draft, not a label area being edited.
      next.roi.editTarget = "score";
      next.roi.labelDraftRect = null;
      if (next.roi.status === "idle") next.roi.status = "ready";
      // From the export step, go back to the region step to see and apply the draft.
      next.ui.activeStep = "roi";
      return next;
    });
    roiEditor?.setDraft?.(rect);
    // The used button is now disabled; keep keyboard focus on the next step.
    shell.stagePane?.querySelector?.('[data-action="apply-roi"]:not([disabled])')?.focus?.();
  }

  function applyRoi() {
    const points = roiEditor?.applyDraft?.() || store.getState().roi.draftRect;
    if (!isRectValid(points)) {
      return;
    }
    stopPolling();
    activeJobHandle = null;
    runtimeGuards.invalidateExport();
    setState((next) => {
      invalidateExportReviewState(next);
      next.roi.appliedRect = points;
      // the box on screen is now the applied one (the editor rounds corners; a fractional
      // suggestion left in the draft would read as unapplied), and applying is the user's
      // decision: a late automatic suggestion must not replace it
      next.roi.draftRect = points;
      next.roi.autoRoiUserEdited = true;
      next.roi.appliedAutoFit = Boolean(next.roi.autoFit);
      next.exportConfig.layoutHint = inferLayoutHintFromRoi(points);
      next.ui.activeStep = "export";
      return next;
    });
    void checkAppliedRoi(points);
    void checkLabelRegion(points);
  }

  function buildJobPayload(state) {
    const roi = state.roi.appliedRect;
    const layoutHint = inferLayoutHintFromRoi(roi);
    const formats = Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [];
    const fallbackDisplayName = sourceDocumentDisplayName(state.source);
    const fallbackDocumentHeader = createDocumentHeaderState(state.source.filePath, new Date(), fallbackDisplayName);
    const documentHeader = normalizeDocumentHeader(state.exportConfig.documentHeader, fallbackDocumentHeader);
    const sourceIdentity = {
      kind: state.source.archiveSourceKind || "file",
      key: state.source.archiveSourceKey || state.source.filePath,
      display_name: fallbackDisplayName || fallbackDocumentHeader.title,
    };
    return {
      source_type: "file",
      file_path: state.source.filePath,
      source_identity: sourceIdentity,
      options: {
        extract: {
          fps: 1.0,
          capture_sensitivity: "medium",
          start_sec: captureRange(state).start,
          end_sec: captureRange(state).end,
        },
        detect: {
          roi,
          auto_fit: Boolean(state.roi.autoFit),
          layout_hint: layoutHint,
          // section-label area applied by the user (never the unapplied suggestion)
          ...(isRectValid(state.roi.labelAppliedRect) ? { label_roi: state.roi.labelAppliedRect } : {}),
        },
        rectify: {
          auto: true,
        },
        stitch: {
          enable: true,
          overlap_threshold: 0.2,
          layout_hint: layoutHint,
          dedupe_level: "normal",
        },
        upscale: {
          enable: false,
          scale: 2.0,
          gpu_only: true,
        },
        export: {
          formats: formats.slice(),
          include_raw_frames: false,
          page_fill_mode: state.exportConfig.pageFillMode || "performance",
          document_header: documentHeader,
        },
        // score layout: rearrange by measure (default) or keep the video's lines
        measure_reflow: state.exportConfig.measureReflow !== false,
      },
    };
  }

  function resetExportOutputs(next) {
    next.exportConfig.runStatus = "running";
    next.exportConfig.error = "";
    next.exportConfig.errorCode = "";
    next.exportConfig.progress = 0;
    next.exportConfig.message = t("export.starting", { locale: next.ui.locale });
    next.exportConfig.currentStep = "";
    next.exportConfig.outputDir = "";
    next.exportConfig.pdfPath = "";
    next.exportConfig.jobId = "";
    next.review.pages = [];
    next.review.selectedPageIds = [];
    next.review.focusedPageId = "";
    next.review.outputDir = "";
    next.review.pdfPath = "";
    next.review.keptCount = 0;
    next.review.error = "";
    next.review.status = "idle";
    next.review.reflow = null;
    return next;
  }

  function openExportMetadataModal() {
    const state = store.getState();
    const sourceDisplayName = sourceDocumentDisplayName(state.source);
    const fallbackDocumentHeader = createDocumentHeaderState(state.source.filePath, new Date(), sourceDisplayName);
    const confirmedHeader = normalizeDocumentHeader(state.exportConfig.documentHeader, fallbackDocumentHeader);
    setState((next) => {
      next.exportConfig.error = "";
      next.exportConfig.metadataModal = createExportMetadataModalState(
        next.source.filePath,
        new Date(),
        confirmedHeader,
        sourceDocumentDisplayName(next.source),
      );
      next.exportConfig.metadataModal.isOpen = true;
      return next;
    });
  }

  function closeExportMetadataModal(forceDiscard = false) {
    const state = store.getState();
    const modal = state.exportConfig.metadataModal;
    if (!modal?.isOpen) {
      return;
    }
    if (state.exportConfig.runStatus === "running") {
      return;
    }
    const liveDraft = captureLiveExportMetadataDraft(shell.stagePane, modal.draft);
    const liveDirty = isExportMetadataDirty(liveDraft, state.exportConfig.documentHeader);
    if (liveDirty && !forceDiscard) {
      setState((next) => {
        next.exportConfig.metadataModal.draft = liveDraft;
        next.exportConfig.metadataModal.dirty = true;
        next.exportConfig.metadataModal.showDiscardConfirm = true;
        return next;
      });
      return;
    }
    setState((next) => {
      next.exportConfig.metadataModal = createExportMetadataModalState(
        next.source.filePath,
        new Date(),
        next.exportConfig.documentHeader,
        sourceDocumentDisplayName(next.source),
      );
      return next;
    });
  }

  function syncExportMetadataDraftFromDom(field = "") {
    const state = store.getState();
    const modal = state.exportConfig.metadataModal;
    if (!modal?.isOpen || state.exportConfig.runStatus === "running") {
      return;
    }
    const liveDraft = captureLiveExportMetadataDraft(shell.stagePane, modal.draft);
    const onlyDraftChanged = !modal.validation?.title && !modal.validation?.bpm
      && !modal.showDiscardConfirm && !state.exportConfig.error;
    setState((next) => {
      const currentModal = next.exportConfig.metadataModal || createExportMetadataModalState(
        next.source.filePath,
        new Date(),
        createDocumentHeaderState(next.source.filePath, new Date(), sourceDocumentDisplayName(next.source)),
        sourceDocumentDisplayName(next.source),
      );
      currentModal.draft = liveDraft;
      currentModal.dirty = isExportMetadataDirty(liveDraft, next.exportConfig.documentHeader);
      currentModal.showDiscardConfirm = false;
      next.exportConfig.error = "";
      if (!field || field === "title") {
        currentModal.validation.title = "";
      }
      if (!field || field === "bpm") {
        currentModal.validation.bpm = "";
      }
      next.exportConfig.metadataModal = currentModal;
      // The native input already displays this value. Replacing the stage on
      // blur would remove the submit button between pointerdown and click.
      if (onlyDraftChanged) lastStageMarkup = stageMarkup(next);
      return next;
    });
  }

  function getExportStartBlockReason(state) {
    const locale = state.ui.locale || "en";
    const formats = Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [];
    if (!state.source.filePath) {
      return t("selector.blocking.sourceRequired", { locale });
    }
    if (!isRectValid(state.roi.appliedRect)) {
      return t("selector.blocking.roiRequired", { locale });
    }
    if (hasDirtyRoiDraft(state)) {
      return t("selector.blocking.roiDirty", { locale });
    }
    if (formats.length === 0) {
      return t("export.formatsRequiredError", { locale });
    }
    if (captureRange(state).error) return t(`export.range.error.${captureRange(state).error}`, { locale });
    return t("export.startBlocked", { locale });
  }

  async function startExportRun(state = store.getState()) {
    const formats = Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [];
    if (state.exportConfig.runStatus === "running") {
      return false;
    }
    if (!canRunExport(state)) {
      const blockReason = getExportStartBlockReason(state);
      setState((next) => {
        next.exportConfig.error = blockReason;
        return next;
      });
      return false;
    }
    const exportRun = runtimeGuards.beginExportRun();
    activeJobHandle = null;
    setState((next) => {
      return resetExportOutputs(next);
    });
    try {
      const jobId = await runtimeApi.createJob(buildJobPayload(state));
      const jobHandle = runtimeGuards.attachJob(exportRun, jobId);
      if (!jobHandle) {
        return false;
      }
      activeJobHandle = jobHandle;
      setState((next) => {
        next.exportConfig.jobId = jobId;
        return next;
      });
      void pollJob(jobId, jobHandle);
      return true;
    } catch (error) {
      if (!runtimeGuards.isCurrentExport(exportRun)) {
        return false;
      }
      setState((next) => {
        next.exportConfig.runStatus = "error";
        next.exportConfig.errorCode = "";
        next.exportConfig.currentStep = "";
        next.exportConfig.message = "";
        next.exportConfig.error = describeError(error, store.getState().ui.locale || "en");
        return next;
      });
      return false;
    }
  }

  async function confirmExportMetadata() {
    const state = store.getState();
    const modal = state.exportConfig.metadataModal;
    if (!modal?.isOpen || state.exportConfig.runStatus === "running") {
      return;
    }
    const sanitizedDraft = captureLiveExportMetadataDraft(shell.stagePane, modal.draft);
    const validation = validateExportMetadataDraft(sanitizedDraft, state.ui.locale || "en");
    if (validation.title || validation.bpm) {
      setState((next) => {
        next.exportConfig.error = "";
        next.exportConfig.metadataModal.draft = sanitizedDraft;
        next.exportConfig.metadataModal.validation = validation;
        next.exportConfig.metadataModal.showDiscardConfirm = false;
        return next;
      });
      return;
    }
    const sourceDisplayName = sourceDocumentDisplayName(state.source);
    const fallbackDocumentHeader = createDocumentHeaderState(state.source.filePath, new Date(), sourceDisplayName);
    const documentHeader = normalizeDocumentHeader(sanitizedDraft, fallbackDocumentHeader);
    setState((next) => {
      next.exportConfig.documentHeader = documentHeader;
      const currentModal = next.exportConfig.metadataModal || createExportMetadataModalState(
        next.source.filePath,
        new Date(),
        documentHeader,
        sourceDocumentDisplayName(next.source),
      );
      currentModal.isOpen = true;
      currentModal.draft = { ...documentHeader };
      currentModal.dirty = false;
      currentModal.validation = { title: "", bpm: "" };
      currentModal.showDiscardConfirm = false;
      next.exportConfig.metadataModal = currentModal;
      return next;
    });
    const started = await startExportRun(store.getState());
    if (!started) {
      if (!store.getState().exportConfig.error) {
        setState((next) => {
          next.exportConfig.error = t("export.startBlocked", { locale: next.ui.locale });
          return next;
        });
      }
      return;
    }
    setState((next) => {
      next.exportConfig.metadataModal = createExportMetadataModalState(
        next.source.filePath,
        new Date(),
        next.exportConfig.documentHeader,
        sourceDocumentDisplayName(next.source),
      );
      return next;
    });
  }

  async function runExport() {
    const state = store.getState();
    if (state.exportConfig.metadataModal?.isOpen) {
      return;
    }
    if (!canRunExport(state)) {
      await startExportRun(state);
      return;
    }
    if (isPdfSelected(Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [])) {
      openExportMetadataModal();
      return;
    }
    await startExportRun(state);
  }

  function reviewErrorMessage(error, locale) {
    const detail = errorDetailText(error);
    if (detail.startsWith("LAYOUT_CONFLICT:")) return t("review.layoutConflictError", { locale });
    if (error?.code === "LEDGER_VERIFICATION_FAILED" || detail.startsWith("LEDGER_VERIFICATION_FAILED:")) return t("review.ledgerVerificationFailed", { locale });
    if (detail.startsWith("LEGACY_JOB:")) return t("review.legacyJob", { locale });
    if (detail.startsWith("UNCUT_STRIP_UNAVAILABLE:")) return t("review.uncutStripUnavailable", { locale });
    if (detail.startsWith("EXPORT_INTERRUPTED:")) return t("review.exportInterrupted", { locale });
    if (detail.startsWith("SOURCE_VIDEO_MISSING:")) return t("review.original.sourceMissing", { locale });
    if (detail.startsWith("ORIGINAL_SCREENS_NOT_ONE_LINE:")) return t("review.original.notOneLine", { locale });
    // a join rebuild that could not run: the previous files are kept
    const seamCode = SEAM_REPAIR_CODES.find(code => error?.code === code || new RegExp(`^${code}\\b`).test(detail));
    if (seamCode) return t(`review.seamRepair.${seamCode}`, { locale });
    // a rebuild that may not be published (no valid plan, empty or unreadable files): previous files kept
    const invalid = EXPORT_INVALID_CODES.find(code => error?.code === code || detail.startsWith(`${code}:`));
    if (invalid) return t("review.exportInvalid", { locale, replacements: { reason: t(`export.invalid.${invalid}`, { locale }) } });
    return describeError(error, locale);
  }

  /** The background rebuild's latest snapshot, shown as progress in the review toolbar. */
  function trackExportTask(jobId, task, sourceSessionToken) {
    if (!task || !runtimeGuards.isCurrentSourceSession(sourceSessionToken)) return;
    setState((next) => {
      if (next.exportConfig.jobId !== jobId || next.review.status !== "running") return next;
      const previous = next.review.exportTask || {};
      next.review.exportTask = {
        jobId,
        taskId: task.taskId || previous.taskId || "",
        state: task.state || "queued",
        stage: task.stage || "queued",
        progress: Number(task.progress || 0),
        // a cancel asked in this window stays shown until the backend reports it
        cancelRequested: Boolean(task.cancelRequested || previous.cancelRequested),
      };
      return next;
    });
    // Cancel was pressed before the backend named the task: send it now
    const current = store.getState().review.exportTask;
    if (task.taskId && current?.cancelRequested && !task.cancelRequested && pendingExportCancel === jobId) {
      pendingExportCancel = "";
      void sendReviewExportCancel(jobId, task.taskId);
    }
  }

  async function sendReviewExportCancel(jobId, taskId) {
    try {
      await runtimeApi.cancelReviewExport(jobId, taskId);
    } catch (error) {
      setState((next) => {
        if (next.review.exportTask?.taskId === taskId) next.review.exportTask.cancelRequested = false;
        return next;
      });
      setInlineNotice(describeError(error, store.getState().ui.locale || "en"));
    }
  }

  /** The rebuild finished: load the job's new revision. */
  async function finishReviewExport(jobId, sourceSessionToken) {
    pendingExportCancel = "";
    const refreshed = await runtimeApi.getJob(jobId);
    if (!runtimeGuards.isCurrentSourceSession(sourceSessionToken)) {
      return;
    }
    if (activeJobHandle && !runtimeGuards.isCurrentJob(activeJobHandle, jobId)) {
      return;
    }
    applyJobSnapshot(refreshed);
    setState((next) => { next.review.exportTask = null; return next; });
    refreshCompletedLibraries();
    setInlineNotice(notice("review.applied", { locale: store.getState().ui.locale || "en" }));
    if (refreshed.result?.reflow?.suggestions_state === "pending" && activeJobHandle) {
      void pollSuggestions(jobId, activeJobHandle);
    }
  }

  /** The rebuild did not finish (cancelled, failed, refused, or its answer was lost). */
  async function failReviewExport(error, { jobId, previousRevision, previousStatus, sourceSessionToken }) {
    pendingExportCancel = "";
    if (!runtimeGuards.isCurrentSourceSession(sourceSessionToken) || error?.code === "EXPORT_POLL_STOPPED") {
      return;
    }
    const locale = store.getState().ui.locale || "en";
    if (error?.code === "EXPORT_IN_PROGRESS") {
      // a rebuild started earlier (another window, or before a reload) is still running: follow it
      setState((next) => { next.review.status = previousStatus; next.review.exportTask = null; return next; });
      setInlineNotice(t("review.exportInProgress", { locale }));
      void resumeReviewExport(jobId);
      return;
    }
    if (error?.code === "EXPORT_CANCELLED") {
      // the previous files and result are untouched; the selection stays as it was before the rebuild
      setState((next) => {
        next.review.status = previousStatus === "applied" ? "applied" : "idle";
        next.review.exportTask = null;
        next.review.error = "";
        return next;
      });
      setInlineNotice(t("review.rebuildCancelled", { locale }));
      return;
    }
    if (!error?.status && await recoverFinishedRebuild(jobId, previousRevision, sourceSessionToken)) {
      setState((next) => { next.review.exportTask = null; return next; });
      return;
    }
    setState((next) => {
      next.review.status = "error";
      next.review.exportTask = null;
      next.review.error = reviewErrorMessage(error, locale);
      return next;
    });
    if (String(error?.message || "").startsWith("LAYOUT_CONFLICT:")
      || error?.code === "LEDGER_VERIFICATION_FAILED"
      || errorDetailText(error).startsWith("LEDGER_VERIFICATION_FAILED:")) {
      // Refresh recoverable conflict/ledger facts without losing edits.
      try {
        const job = await runtimeApi.getJob(jobId);
        if (runtimeGuards.isCurrentSourceSession(sourceSessionToken)) mergeJobFacts(job);
      } catch (_) {
        // the error message above still explains the conflict
      }
    }
  }

  /**
   * Follow a rebuild that is already running on the backend (after a reload, or one started from
   * another window): show its progress, allow cancel, then load its result.
   */
  async function resumeReviewExport(jobId) {
    if (typeof runtimeApi.getReviewExportTask !== "function" || typeof runtimeApi.waitForReviewExport !== "function") return;
    const sourceSessionToken = runtimeGuards.captureSourceSession();
    let task;
    try {
      task = await runtimeApi.getReviewExportTask(jobId);
    } catch (_) {
      return;
    }
    const state = store.getState();
    if (!task || !["queued", "running"].includes(task.state) || !runtimeGuards.isCurrentSourceSession(sourceSessionToken)
      || state.exportConfig.jobId !== jobId || ["running", "editing"].includes(state.review.status)) {
      return;
    }
    const previousRevision = Number(state.review.jobRevision || 0);
    const previousStatus = state.review.status;
    setState((next) => {
      next.review.status = "running";
      next.review.error = "";
      return next;
    });
    trackExportTask(jobId, task, sourceSessionToken);
    try {
      await runtimeApi.waitForReviewExport(jobId, task, {
        onTask: (snapshot) => trackExportTask(jobId, snapshot, sourceSessionToken),
        shouldStop: () => destroyed || !runtimeGuards.isCurrentSourceSession(sourceSessionToken),
      });
      if (!runtimeGuards.isCurrentSourceSession(sourceSessionToken)) return;
      await finishReviewExport(jobId, sourceSessionToken);
    } catch (error) {
      await failReviewExport(error, { jobId, previousRevision, previousStatus, sourceSessionToken });
    }
  }

  async function cancelRunningReviewExport() {
    const state = store.getState();
    const task = state.review.exportTask;
    if (state.review.status !== "running" || !task || task.cancelRequested || typeof runtimeApi.cancelReviewExport !== "function") return;
    setState((next) => {
      if (next.review.exportTask) next.review.exportTask.cancelRequested = true;
      return next;
    });
    if (!task.taskId) {
      // the start request has not answered yet: cancel as soon as the task is known
      pendingExportCancel = task.jobId;
      return;
    }
    await sendReviewExportCancel(task.jobId, task.taskId);
  }

  /**
   * A rebuild whose answer never arrived (a timeout or a dropped connection, not an HTTP error)
   * may still have finished on the backend. When the job's revision moved past the one this
   * screen showed, the rebuild is taken as applied instead of reported as a failure.
   */
  async function recoverFinishedRebuild(jobId, previousRevision, sourceSessionToken) {
    try {
      const job = await runtimeApi.getJob(jobId);
      if (!runtimeGuards.isCurrentSourceSession(sourceSessionToken)) return true;
      if (job?.status !== "done" || jobRevision(job.result || {}) <= previousRevision) return false;
      applyJobSnapshot(job);
      refreshCompletedLibraries();
      setInlineNotice(notice("review.applied", { locale: store.getState().ui.locale || "en" }));
      return true;
    } catch (_) {
      return false;
    }
  }

  async function applyReviewSelection({ staffGapMm = null } = {}) {
    const state = store.getState();
    if (hasDirtyRoiDraft(state)) return;
    const formats = Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [];
    if (
      !state.exportConfig.jobId
      || !isReviewableRun(state)
      || ["running", "editing"].includes(state.review.status)
      || state.ui.savingPdfAs
    ) {
      return;
    }
    if (!formats.length) {
      setState((next) => {
        next.review.error = t("export.formatsRequiredError", { locale: next.ui.locale });
        return next;
      });
      return;
    }
    const sourceSessionToken = runtimeGuards.captureSourceSession();
    const selectedPages = state.review.pages.filter((page) => state.review.selectedPageIds.includes(page.id));
    if (!selectedPages.length) {
      return;
    }
    const usePageSelection = selectedPages.every((page) => page.selectionMode === "pages");
    const selected = selectedPages.map((page) => page.capturePath);
    if (state.review.originalScreens?.active) {
      // original screens: rebuild from the saved screens the user kept (no new capture)
      await runOriginalScreensExport({ keepCaptures: selected, formats });
      return;
    }
    // Clean reflow: the list order is the output order.
    const systemOrder = state.review.pages.some((page) => page.kind === "system")
      ? state.review.pages.map((page) => page.capturePath) : [];
    const previousRevision = Number(state.review.jobRevision || 0);
    const previousStatus = state.review.status;
    const jobId = state.exportConfig.jobId;
    // joins answered "a measure repeats or is missing": rebuilt with both views kept
    const rejectedSeamIds = pendingSeamRejections(state);
    setState((next) => {
      next.review.status = "running";
      next.review.error = "";
      next.review.exportTask = { jobId, taskId: "", state: "queued", stage: "queued", progress: 0, cancelRequested: false };
      return next;
    });
    try {
      // starts a background rebuild and polls it; the toolbar shows its progress and can cancel it
      await runtimeApi.reviewExport(jobId, {
        keepCaptures: usePageSelection ? [] : selected,
        keepImages: usePageSelection ? selected : [],
        formats,
        ...(systemOrder.length ? { systemOrder } : {}),
        // an explicit choice: a smaller staff size for this document only
        ...(Number.isFinite(staffGapMm) ? { staffGapMm, staffGapMmExplicit: true } : {}),
        // the score layout chosen now (each rebuild sends it, so an older job follows the toggle too)
        measureReflow: state.exportConfig.measureReflow !== false,
        ...(rejectedSeamIds ? { rejectedSeamIds, baseRevision: previousRevision } : {}),
      }, {
        onTask: (task) => trackExportTask(jobId, task, sourceSessionToken),
        shouldStop: () => destroyed || !runtimeGuards.isCurrentSourceSession(sourceSessionToken),
      });
      if (!runtimeGuards.isCurrentSourceSession(sourceSessionToken)) {
        return;
      }
      await finishReviewExport(jobId, sourceSessionToken);
    } catch (error) {
      await failReviewExport(error, { jobId, previousRevision, previousStatus, sourceSessionToken });
    }
  }

  /**
   * Rebuild the job as original screens (ORIGINAL_SCREENS_DESIGN.md): without ``keepCaptures`` the
   * backend captures the video again; with them it uses only those saved screens. Same background
   * task, progress, cancel and error handling as the clean rebuild; the previous files stay on failure.
   */
  async function runOriginalScreensExport({ keepCaptures = [], formats }) {
    const state = store.getState();
    if (!state.exportConfig.jobId || ["running", "editing"].includes(state.review.status) || state.ui.savingPdfAs) return;
    const sourceSessionToken = runtimeGuards.captureSourceSession();
    const previousRevision = Number(state.review.jobRevision || 0);
    const previousStatus = state.review.status;
    const jobId = state.exportConfig.jobId;
    setState((next) => {
      next.review.status = "running";
      next.review.error = "";
      next.review.exportTask = { jobId, taskId: "", state: "queued", stage: "queued", progress: 0, cancelRequested: false };
      return next;
    });
    try {
      await runtimeApi.reviewExport(jobId, { outputModel: "original_screens_v1", keepCaptures, formats }, {
        onTask: (task) => trackExportTask(jobId, task, sourceSessionToken),
        shouldStop: () => destroyed || !runtimeGuards.isCurrentSourceSession(sourceSessionToken),
      });
      if (!runtimeGuards.isCurrentSourceSession(sourceSessionToken)) return;
      await finishReviewExport(jobId, sourceSessionToken);
    } catch (error) {
      await failReviewExport(error, { jobId, previousRevision, previousStatus, sourceSessionToken });
    }
  }

  async function rebuildAsOriginalScreens() {
    const state = store.getState();
    if (!state.review.originalScreens?.available || !isReviewableRun(state)) return;
    const formats = Array.isArray(state.exportConfig.formats) ? state.exportConfig.formats : [];
    if (!formats.length) {
      setState((next) => {
        next.review.error = t("export.formatsRequiredError", { locale: next.ui.locale });
        return next;
      });
      return;
    }
    await runOriginalScreensExport({ formats });
  }

  async function handleOpenPath(targetPath, label) {
    const locale = store.getState().ui.locale;
    if (!targetPath) {
      setInlineNotice(notice("path.missing", { locale, replacements: { label } }));
      return;
    }
    try {
      const result = await runtimeBridge.openPath(targetPath);
      if (result) {
        setInlineNotice(notice("open.failed", { locale, replacements: { label, reason: result } }));
        return;
      }
      setInlineNotice(notice("open.success", { locale, replacements: { label } }));
    } catch (error) {
      setInlineNotice(notice("open.failed", {
        locale,
        replacements: { label, reason: describeError(error, store.getState().ui.locale || "en") },
      }));
    }
  }

  async function handleSavePdfAs() {
    const state = store.getState();
    if (!state.review.pdfPath || state.ui.savingPdfAs || ["running", "editing"].includes(state.review.status)
      || state.exportConfig.runStatus === "running") return;
    const token = runtimeGuards.captureSourceSession();
    const locale = state.ui.locale || "en";
    setState(next => { next.ui.savingPdfAs = true; return next; });
    try {
      const result = await runtimeBridge.savePdfAs({
        sourcePath: state.review.pdfPath,
        suggestedName: state.exportConfig.documentHeader?.title || state.source.displayName || "score",
        locale,
      });
      if (!runtimeGuards.isCurrentSourceSession(token) || result?.canceled) return;
      if (!result?.filePath) throw new Error(t("review.saveAsUnavailable", { locale }));
      setInlineNotice(t("review.saveAsSuccess", { locale, replacements: { path: result.filePath } }));
    } catch (error) {
      if (runtimeGuards.isCurrentSourceSession(token)) setInlineNotice(t("review.saveAsFailed", {
        locale, replacements: { reason: describeError(error, store.getState().ui.locale || "en") },
      }));
    } finally {
      setState(next => { next.ui.savingPdfAs = false; return next; });
    }
  }

  async function handleCopyText(text, label) {
    const locale = store.getState().ui.locale;
    if (!String(text || "").trim()) {
      setInlineNotice(notice("copy.missing", { locale, replacements: { label } }));
      return;
    }
    try {
      const copied = await runtimeBridge.copyText(text);
      setInlineNotice(copied
        ? notice("copy.success", { locale, replacements: { label } })
        : notice("copy.failed", { locale, replacements: { label } }));
    } catch (error) {
      setInlineNotice(notice("copy.error", {
        locale,
        replacements: { label, reason: describeError(error, store.getState().ui.locale || "en") },
      }));
    }
  }

  const handleClick = async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target || isUpdateInstalling()) {
      return;
    }
    const action = target.dataset.action;
    if (action === "open-bug-report") { await openBugReport(); return; }
    if (action === "close-bug-report") { closeBugReport(); return; }
    if (action === "send-bug-report") { await submitBugReport(); return; }
    if (action === "open-bug-report-issue") { await openBugReportIssue(); return; }
    if (action === "check-release-update") {
      if (target.getAttribute?.("aria-disabled") === "true") return;
      await checkReleaseUpdateManually().catch(() => setInlineNotice(t("update.checkFailed", { locale: store.getState().ui.locale })));
      return;
    }
    if (action === "download-release-update") {
      applyReleaseUpdate(await runtimeBridge.downloadReleaseUpdate?.().catch(() => null));
      return;
    }
    if (action === "install-release-update") {
      if (isWorkRunning()) return;
      applyReleaseUpdate(await runtimeBridge.installReleaseUpdate?.({ unsavedWork: hasUnsavedEdits() }).catch(() => null));
      return;
    }
    if (action === "open-release-installer") {
      const opened = await runtimeBridge.openReleaseInstaller?.().catch(() => false);
      if (!opened) setInlineNotice(t("support.actionFailed", { locale: store.getState().ui.locale }));
      return;
    }
    if (["copy-diagnostics", "open-support-issue", "open-release-page", "dismiss-release-update"].includes(action)) {
      try {
        if (action === "copy-diagnostics") {
          const state = store.getState();
          const copied = await runtimeBridge.copyDiagnostics?.(currentFailureDetail(state));
          setInlineNotice(t(copied ? "support.copied" : "support.copyFailed", { locale: state.ui.locale }));
        } else if (action === "open-support-issue") await runtimeBridge.openSupportIssue?.();
        else if (action === "open-release-page") await runtimeBridge.openReleasePage?.();
        else { await runtimeBridge.dismissReleaseUpdate?.(); releaseUpdate = { status: "idle" }; render(); }
      } catch (_) { setInlineNotice(t("support.actionFailed", { locale: store.getState().ui.locale })); }
      return;
    }
    if (action === "review-use-staff-size") {
      // the explicit user choice of a document staff size (never applied automatically)
      const size = Number(target.dataset.size);
      if (Number.isFinite(size) && size >= 1 && size <= 2.5) await applyReviewSelection({ staffGapMm: size });
      return;
    }
    // a folded part of a screen (reasons, more options): open or closed until toggled again
    if (action === "toggle-more") {
      const key = String(target.dataset.value || "");
      if (key) setState((next) => { next.ui.more = { ...(next.ui.more || {}), [key]: !next.ui.more?.[key] }; return next; });
      return;
    }
    if (action?.startsWith("review-")) { await reviewController.handleAction(action, target.dataset.value); return; }
    if (action === "cancel-job") { await cancelCurrentJob(); return; }
    if (action === "reconnect-job") { reconnectJob(); return; }
    if (action === "select-source-file") {
      await selectSourceFile();
      return;
    }
    if (action === "prepare-source-youtube") {
      await prepareYoutubeSource();
      return;
    }
    if (action === "load-registry-source") {
      try {
        await loadSourceFromPath(target.dataset.filePath, {
          sourceOrigin: target.dataset.sourceOrigin,
          youtubeUrl: target.dataset.youtubeUrl,
          displayName: target.dataset.displayName,
        });
      } catch (error) {
        setState((next) => {
          next.source.status = "error";
          next.source.error = describeError(error, store.getState().ui.locale || "en");
          return next;
        });
      }
      return;
    }
    if (action === "set-locale") {
      const locale = persistLocale(target.dataset.locale);
      setState((next) => {
        next.ui.locale = locale;
        // Review titles are baked when the job loads; redo them so the list follows the language.
        next.review.pages = next.review.pages.map((page) => ({ ...page, title: localizePageTitle(page, locale) }));
        if (next.source.prepareStatus === "error" && next.source.prepareErrorDetail) {
          next.source.error = youtubePrepareError(next.source.prepareErrorDetail, locale);
        }
        return next;
      });
      return;
    }
    if (action === "open-archive") {
      openArchive();
      return;
    }
    if (action === "restart-backend") {
      try {
        await runtimeBridge.restartBackend();
        setInlineNotice(t("status.restartTriggered", { locale: store.getState().ui.locale || "en" }));
      } catch (error) {
        setInlineNotice(describeError(error, store.getState().ui.locale || "en"));
      }
      return;
    }
    if (action === "run-guided-setup") {
      try {
        await runtimeBridge.runGuidedSetup();
        setInlineNotice(t("status.setupTriggered", { locale: store.getState().ui.locale || "en" }));
      } catch (error) {
        setInlineNotice(describeError(error, store.getState().ui.locale || "en"));
      }
      return;
    }
    if (action === "close-archive") {
      closeArchive();
      return;
    }
    if (action === "request-clear-cache") {
      setArchiveStorage({ confirm: true, error: "", result: "" });
      return;
    }
    if (action === "cancel-clear-cache") {
      setArchiveStorage({ confirm: false });
      return;
    }
    if (action === "confirm-clear-cache") {
      await clearAppCache();
      return;
    }
    if (action === "retry-archive") {
      void refreshArchiveLibrary();
      return;
    }
    if (action === "select-archive-item") {
      setState((next) => {
        next.archive.selectedSourceKey = String(target.dataset.sourceKey || "");
        return next;
      });
      return;
    }
    if (action === "back-archive-detail") {
      setState((next) => {
        next.archive.selectedSourceKey = "";
        return next;
      });
      return;
    }
    if (action === "open-step") {
      if (store.getState().exportConfig.metadataModal?.isOpen) {
        return;
      }
      const { step } = target.dataset;
      if (canOpenStep(store.getState(), step)) {
        setState((next) => {
          next.ui.activeStep = step;
          return next;
        });
      }
      return;
    }
    if (action === "load-preview-frame") {
      await loadPreview();
      return;
    }
    if (action === "select-preview-candidate") {
      await selectPreviewCandidate(target.dataset.candidateId);
      return;
    }
    if (action === "apply-roi") {
      applyRoi();
      return;
    }
    if (action === "use-suggested-roi") {
      useSuggestedRoi();
      return;
    }
    if (action === "use-suggested-label-roi") { editLabelArea({ useSuggestion: true }); return; }
    if (action === "edit-label-roi") { editLabelArea(); return; }
    if (action === "apply-label-roi") { applyLabelArea(); return; }
    if (action === "remove-label-roi") { removeLabelArea(); return; }
    if (action === "edit-score-roi") {
      setState((next) => { next.roi.editTarget = "score"; next.roi.labelDraftRect = null; return next; });
      return;
    }
    if (action === "recheck-roi") {
      const applied = store.getState().roi.appliedRect;
      if (isRectValid(applied)) void checkAppliedRoi(applied);
      return;
    }
    if (action === "run-export") {
      await runExport();
      return;
    }
    if (action === "confirm-export-metadata") {
      await confirmExportMetadata();
      return;
    }
    if (action === "close-export-metadata") {
      closeExportMetadataModal(false);
      return;
    }
    if (action === "discard-export-metadata") {
      closeExportMetadataModal(true);
      return;
    }
    if (action === "continue-export-metadata") {
      setState((next) => {
        if (next.exportConfig.metadataModal) {
          next.exportConfig.metadataModal.showDiscardConfirm = false;
        }
        return next;
      });
      return;
    }
    if (action === "focus-review-page") {
      const { pageId } = target.dataset;
      setState((next) => {
        next.review.focusedPageId = pageId;
        next.review.cropping = false;
        // picking a system shows that system, not the printed lines or pages
        if (next.review.lineCheck) next.review.lineCheck.open = false;
        next.review.pagePreview = false;
        return next;
      });
      return;
    }
    if (action === "apply-review") {
      await applyReviewSelection();
      return;
    }
    if (action === "cancel-review-export") {
      await cancelRunningReviewExport();
      return;
    }
    if (action === "rebuild-original-screens") {
      await rebuildAsOriginalScreens();
      return;
    }
    if (action === "open-original-screens-dir") {
      const locale = store.getState().ui.locale || "en";
      await handleOpenPath(store.getState().review.originalScreens?.screensDir, t("review.original.screensDir", { locale }));
      return;
    }
    if (action === "open-output-dir") {
      const locale = store.getState().ui.locale || "en";
      await handleOpenPath(store.getState().review.outputDir, t("label.outputDir", { locale }));
      return;
    }
    if (action === "open-output-pdf") {
      const locale = store.getState().ui.locale || "en";
      await handleOpenPath(store.getState().review.pdfPath, t("label.outputPdf", { locale }));
      return;
    }
    if (action === "save-output-pdf-as") {
      await handleSavePdfAs();
      return;
    }
    if (action === "copy-output-dir") {
      const locale = store.getState().ui.locale || "en";
      await handleCopyText(store.getState().review.outputDir, t("label.outputPath", { locale }));
      return;
    }
    if (action === "open-archive-pdf") {
      const locale = store.getState().ui.locale || "en";
      const item = getArchiveItem(target.dataset.sourceKey);
      await handleOpenPath(item?.pdfPath, t("archive.pathLabel.pdf", { locale }));
      return;
    }
    if (action === "open-archive-folder") {
      const locale = store.getState().ui.locale || "en";
      const item = getArchiveItem(target.dataset.sourceKey);
      await handleOpenPath(item?.outputDir, t("archive.pathLabel.folder", { locale }));
      return;
    }
    if (action === "reopen-archive-source") {
      try {
        await loadSourceFromPath(target.dataset.filePath, {
          sourceOrigin: target.dataset.sourceKind === "youtube" ? "prepared" : "job",
          youtubeUrl: target.dataset.youtubeUrl,
          displayName: target.dataset.displayName,
        });
        closeArchive();
      } catch (error) {
        setState((next) => {
          next.source.status = "error";
          next.source.error = describeError(error, store.getState().ui.locale || "en");
          return next;
        });
      }
      return;
    }
  };

  const handleInput = (event) => {
    const target = event.target;
    const bugReportField = target?.dataset?.bugReportField;
    if (bugReportField && bugReport.isOpen) {
      if (target.type === "checkbox") setBugReport({ draft: { ...bugReport.draft, [bugReportField]: Boolean(target.checked) } });
      else {
        // Clear a stale error in place; a render here would break an IME composition in progress.
        if (bugReport.invalid === bugReportField) {
          bugReport = { ...bugReport, invalid: "" };
          shell.modalLayer.querySelector?.(`#bugReportError-${bugReportField}`)?.remove?.();
          target.removeAttribute?.("aria-invalid");
          if (bugReportField === "email") target.setAttribute?.("aria-describedby", "bugReportEmailHint");
          else target.removeAttribute?.("aria-describedby");
        }
        syncBugReportDraft(bugReportField, String(target.value || ""));
      }
      return;
    }
    if (target.dataset.action === "capture-range") {
      const field = target.dataset.field;
      const state = store.getState();
      if (!["rangeStart", "rangeEnd"].includes(field) || state.exportConfig.runStatus === "running" || state.exportConfig.metadataModal?.isOpen) return;
      setState(next => { next.exportConfig[field] = String(target.value).slice(0, 24); return next; });
      return;
    }
    if (target.dataset.action === "toggle-roi-auto-fit") {
      setState(next => { next.roi.autoFit = Boolean(target.checked); return next; });
      return;
    }
    if (target.dataset.action === "youtube-url-input") {
      resetCurrentSourceSession();
      sourceController.setYoutubeUrl(String(target.value || ""));
      return;
    }
    if (target.id === "frameTimeSlider") {
      const value = Number(target.value || 0);
      const currentValue = store.getState().roi.frameTime;
      if (currentValue === value) {
        return;
      }
      runtimeGuards.invalidatePreview();
      runtimeGuards.invalidateExport();
      stopPolling();
      activeJobHandle = null;
      setState((next) => {
        invalidatePreviewFlow(next, {
          frameTime: value,
          frameTimeLabel: formatSecondsLabel(value),
          preserveCandidates: true,
        });
        next.roi.selectedPreviewCandidateId = "";
        return next;
      });
      return;
    }
    if (target.dataset.action === "toggle-measure-reflow") {
      const state = store.getState();
      if (state.exportConfig.runStatus === "running" || ["running", "editing"].includes(state.review.status)) {
        target.checked = state.exportConfig.measureReflow !== false;
        return;
      }
      setState((next) => {
        next.exportConfig.measureReflow = Boolean(target.checked);
        // saved files were made with the other layout: rebuilding is pending again
        if (next.review.status === "applied") next.review.status = "idle";
        return next;
      });
      return;
    }
    if (target.dataset.action === "toggle-format") {
      const format = target.dataset.format;
      stopPolling();
      activeJobHandle = null;
      runtimeGuards.invalidateExport();
      setState((next) => {
        const nextFormats = new Set(next.exportConfig.formats);
        if (target.checked) {
          nextFormats.add(format);
        } else {
          nextFormats.delete(format);
        }
        invalidateExportReviewState(next);
        next.exportConfig.formats = Array.from(nextFormats);
        next.ui.activeStep = "export";
        return next;
      });
      return;
    }
    if (target.dataset.action === "update-export-metadata") {
      const field = String(target.dataset.field || "");
      const sanitizedValue = sanitizeDocumentHeaderDraftField(field, target.value);
      if (target.value !== sanitizedValue) {
        target.value = sanitizedValue;
      }
      return;
    }
    if (target.dataset.action === "toggle-review-page") {
      const { pageId } = target.dataset;
      reviewController.toggle(pageId, target.checked);
      return;
    }
    if (target.dataset.action === "set-roi-bound") {
      const field = String(target.dataset.field || "");
      const value = Number(target.value);
      const state = store.getState();
      const baseBounds = rectToBounds(state.roi.draftRect || state.roi.appliedRect);
      const maxWidth = Number(state.roi.imageWidth || state.source.metadata?.width || 0);
      const maxHeight = Number(state.roi.imageHeight || state.source.metadata?.height || 0);
      if (!baseBounds || !maxWidth || !maxHeight || !Number.isFinite(value)) {
        return;
      }
      const nextBounds = { ...baseBounds, [field]: value };
      const nextRect = boundsToRect(nextBounds, maxWidth, maxHeight);
      if (rectMatches(nextRect, state.roi.draftRect)) {
        return;
      }
      setState((next) => {
        next.roi.draftRect = nextRect;
        if (next.roi.status === "idle") {
          next.roi.status = "ready";
        }
        return next;
      });
      roiEditor?.setDraft?.(nextRect);
    }
  };

  const handleCompositionEnd = (event) => {
    const target = event.target;
    if (target?.dataset?.action !== "update-export-metadata") {
      return;
    }
    const field = String(target.dataset.field || "");
    const sanitizedValue = sanitizeDocumentHeaderDraftField(field, target.value);
    if (target.value !== sanitizedValue) {
      target.value = sanitizedValue;
    }
  };

  const handleChange = (event) => {
    const target = event.target;
    if (target?.dataset?.action !== "update-export-metadata") {
      return;
    }
    const field = String(target.dataset.field || "");
    const sanitizedValue = sanitizeDocumentHeaderDraftField(field, target.value);
    if (target.value !== sanitizedValue) {
      target.value = sanitizedValue;
    }
    syncExportMetadataDraftFromDom(field);
  };

  const handleKeyDown = (event) => {
    if (isUpdateInstalling()) return;
    if (!bugReport.isOpen) reviewController.handleKey(event);
    if (event.key === "Tab" && store.getState().exportConfig.metadataModal?.isOpen) {
      const tabTargetIndex = exportMetadataTabTargetIndex(event.target);
      if (tabTargetIndex >= 0) {
        event.preventDefault?.();
        if (event.target?.dataset?.action === "update-export-metadata") {
          syncExportMetadataDraftFromDom(String(event.target.dataset.field || ""));
        }
        focusAdjacentExportMetadataTarget(shell.stagePane, event.target, Boolean(event.shiftKey));
        return;
      }
    }
    if (event.key === "Escape" && bugReport.isOpen) {
      event.preventDefault?.();
      closeBugReport();
      return;
    }
    if (event.key === "Escape" && store.getState().archive.isOpen) {
      event.preventDefault?.();
      closeArchive();
      return;
    }
    if (event.key === "Escape" && store.getState().exportConfig.metadataModal?.isOpen) {
      event.preventDefault?.();
      closeExportMetadataModal(false);
    }
  };

  root.addEventListener("click", handleClick);
  root.addEventListener("input", handleInput);
  root.addEventListener("compositionend", handleCompositionEnd);
  root.addEventListener("change", handleChange);
  root.addEventListener("keydown", handleKeyDown);
  root.addEventListener("dragenter", handleDragEnter);
  root.addEventListener("dragover", handleDragOver);
  root.addEventListener("dragleave", handleDragLeave);
  root.addEventListener("drop", handleDrop);
  // Image load does not bubble; listen in the capture phase to learn thumbnail aspect ratios.
  const handleImageLoad = event => syncThumbShape(event.target);
  root.addEventListener("load", handleImageLoad, true);

  const unsubscribeStore = store.subscribe(render);
  const unsubscribeBackend = runtimeBridge.onBackendState((payload) => {
    const becameReady = Boolean(payload?.ready) && !lastBackendReady;
    lastBackendReady = Boolean(payload?.ready);
    setState((next) => {
      next.ui.backend = payload;
      return next;
    });
    if (becameReady) {
      if (restorePending) { restorePending = false; reconnectJob(); }
      void refreshLocalMediaRegistry();
      void refreshArchiveLibrary();
    }
  });
  const unsubscribeSetupState = runtimeBridge.onSetupState((payload) => {
    const message = String(payload?.message || payload?.state || "").trim();
    if (message) {
      setInlineNotice(message);
    }
  });
  const unsubscribeSetupLog = runtimeBridge.onSetupLog((payload) => {
    const message = String(payload?.message || payload || "").trim();
    if (message) {
      setInlineNotice(message);
    }
  });

  refreshBackendState();
  render();
  const unsubscribeReleaseUpdate = runtimeBridge.onReleaseUpdateState?.(applyReleaseUpdate);
  Promise.resolve(runtimeBridge.checkReleaseUpdate?.({ manual: false })).then(applyReleaseUpdate).catch(() => {});

  return {
    debug: dependencies.exposeTestApi
      ? {
          buildJobPayload(state) {
            return buildJobPayload(state);
          },
          getState() {
            return store.getState();
          },
          setState(updater) {
            return setState(updater);
          },
        }
      : undefined,
    destroy() {
      destroyed = true;
      workspaceMotion.destroy();
      reviewController.destroy();
      stopPersistence();
      stopPolling();
      stopSuggestionPolling();
      stopSourcePreparePolling();
      releasePreviewImageUrl(store.getState().roi?.previewImage);
      destroyRoiEditor();
      unsubscribeStore?.();
      unsubscribeBackend?.();
      unsubscribeSetupState?.();
      unsubscribeSetupLog?.();
      unsubscribeReleaseUpdate?.();
      if (typeof root.removeEventListener === "function") {
        root.removeEventListener("click", handleClick);
        root.removeEventListener("input", handleInput);
        root.removeEventListener("compositionend", handleCompositionEnd);
        root.removeEventListener("change", handleChange);
        root.removeEventListener("keydown", handleKeyDown);
        root.removeEventListener("dragenter", handleDragEnter);
        root.removeEventListener("dragover", handleDragOver);
        root.removeEventListener("dragleave", handleDragLeave);
        root.removeEventListener("drop", handleDrop);
        root.removeEventListener("load", handleImageLoad, true);
      }
    },
  };
}
