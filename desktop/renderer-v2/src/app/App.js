import { bridge, readVideoMetadata } from "./bridge.js";
import { createStore } from "./session/store.js";
import {
  createDocumentHeaderState,
  createExportMetadataModalState,
  createInitialExportConfig,
  createInitialSessionState,
  deriveCapturePages,
  formatSecondsLabel,
  getAccessibleSteps,
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
import { canRunExport, createRuntimeGuards, invalidatePreviewFlow } from "./session/runtimeSafety.js";
import { canOpenStep } from "./routes.js";
import { mountShell } from "../ui/shell/AppShell.js";
import { renderTopBar } from "../ui/shell/TopBar.js";
import { renderProcessRail } from "../ui/shell/ProcessRail.js";
import { renderContextLane } from "../ui/shell/ContextLane.js";
import { renderSourceScreen } from "../features/source/SourceScreen.js";
import { createSourceController } from "../features/source/sourceController.js";
import { renderRoiScreen } from "../features/roi/RoiScreen.js";
import { renderExportScreen } from "../features/export/ExportScreen.js";
import { renderReviewScreen } from "../features/review/ReviewScreen.js";
import { renderArchiveModal } from "../features/archive/ArchiveModal.js";
import { mountRoiEditor } from "../features/roi/roiEditor.js";
import {
  createJob,
  createPreviewSourceJob,
  getArchiveLibrary,
  getJob,
  getLocalMediaRegistry,
  getPreviewSourceJob,
  preparePreviewSource,
  requestPreviewFrame,
  reviewExport,
} from "../lib/api.js";
import { escapeHtml } from "../lib/html.js";
import { t } from "../lib/i18n.js";
import { baseName } from "../lib/paths.js";
import { persistLocale } from "../lib/i18n.js";
import { mergePrepareLogs, notice, youtubePrepareDetail, youtubePrepareError } from "../lib/messages.js";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

const SOURCE_DROP_ZONE_SELECTOR = '[data-drop-zone="source-ingest"]';
const SUPPORTED_VIDEO_EXTENSIONS = new Set(["mp4", "mkv", "mov", "avi", "webm"]);

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
    const resolvedPath = runtimeBridge.getPathForFile ? await runtimeBridge.getPathForFile(file) : "";
    const filePath = String(resolvedPath || file?.path || "").trim();
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

function captureStageInputFocus() {
  const activeElement = globalThis?.document?.activeElement;
  if (activeElement?.dataset?.action !== "update-export-metadata" || !activeElement.dataset.field) {
    return null;
  }
  return {
    selector: `[data-action="update-export-metadata"][data-field="${activeElement.dataset.field}"]`,
    selectionStart: Number.isInteger(activeElement.selectionStart) ? activeElement.selectionStart : null,
    selectionEnd: Number.isInteger(activeElement.selectionEnd) ? activeElement.selectionEnd : null,
  };
}

function restoreStageInputFocus(stagePane, snapshot) {
  if (!stagePane || !snapshot?.selector) {
    return;
  }
  const nextField = stagePane.querySelector?.(snapshot.selector);
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

export function createApp(root, dependencies = {}) {
  const runtimeBridge = dependencies.bridge || bridge;
  const readMetadata = dependencies.readVideoMetadata || readVideoMetadata;
  const runtimeApi = dependencies.api
    ? {
      getArchiveLibrary: async () => ({ items: [] }),
      getLocalMediaRegistry: async () => ({ items: [] }),
      ...dependencies.api,
    }
    : {
      createJob,
      createPreviewSourceJob,
      getArchiveLibrary,
      getJob,
      getLocalMediaRegistry,
      getPreviewSourceJob,
      preparePreviewSource,
      requestPreviewFrame,
      reviewExport,
    };
  const mountShellImpl = dependencies.mountShell || mountShell;
  const mountRoiEditorImpl = dependencies.mountRoiEditor || mountRoiEditor;
  const store = createStore(createInitialSessionState());
  const shell = mountShellImpl(root);
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
  let roiEditor = null;
  let roiEditorKey = "";
  let roiEditorNodes = null;
  let activePoll = null;
  let activeJobHandle = null;
  let activeSourcePreparePoll = null;
  let activeSourcePrepareHandle = null;
  let activeSourceSelection = 0;
  let lastRenderedStep = "";
  let lastTopBarMarkup = "";
  let lastProcessRailMarkup = "";
  let lastContextLaneMarkup = "";
  let lastStageMarkup = "";
  let lastArchiveMarkup = "";
  let lastStatusMarkup = "";
  let lastBackendReady = false;
  let lastArchiveOpen = false;
  let archiveRestoreFocusTarget = null;
  let registryRefreshToken = 0;
  let archiveRefreshToken = 0;
  let activeSourceDropZone = null;
  const runtimeGuards = createRuntimeGuards();

  function setState(updater) {
    store.setState(updater);
  }

  function getSelectedPreviewCandidate(state = store.getState()) {
    const selectedId = String(state.roi.selectedPreviewCandidateId || "");
    if (!selectedId) {
      return null;
    }
    return (state.roi.previewCandidates || []).find((candidate) => candidate.id === selectedId) || null;
  }

  function resetDownstream(next) {
    next.roi = {
      frameTime: 0,
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
    };
    next.exportConfig = createInitialExportConfig(next.source.filePath);
    next.review = {
      pages: [],
      selectedPageIds: [],
      focusedPageId: "",
      status: "idle",
      error: "",
      keptCount: 0,
      outputDir: "",
      pdfPath: "",
    };
  }

  function stageMarkup(state) {
    let screenMarkup = "";
    if (state.ui.activeStep === "source") {
      screenMarkup = renderSourceScreen(state);
    } else if (state.ui.activeStep === "roi") {
      screenMarkup = renderRoiScreen(state);
    } else if (state.ui.activeStep === "export") {
      screenMarkup = renderExportScreen(state);
    } else {
      screenMarkup = renderReviewScreen(state);
    }
    return screenMarkup;
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
    const nextKey = `${state.roi.previewSourcePath || state.roi.previewImage}`;
    const nodesChanged = !roiEditorNodes
      || roiEditorNodes.image !== image
      || roiEditorNodes.canvas !== canvas
      || roiEditorNodes.input !== input;
    if (roiEditor && roiEditorKey === nextKey && !nodesChanged) {
      roiEditor.setDraft?.(state.roi.draftRect || state.roi.appliedRect || null);
      return;
    }
    destroyRoiEditor();
    roiEditor = mountRoiEditorImpl({
      image,
      canvas,
      input,
      initialPoints: state.roi.draftRect || state.roi.appliedRect,
      onDraftChange(points) {
        if (rectMatches(points, store.getState().roi.draftRect)) {
          return;
        }
        setState((next) => {
          next.roi.draftRect = points;
          return next;
        });
      },
    });
    roiEditorKey = nextKey;
    roiEditorNodes = { image, canvas, input };
  }

  function render() {
    const state = store.getState();
    const locale = state.ui.locale || "en";
    syncDocumentChrome(locale);
    const stepLabel = t(`topbar.step.${state.ui.activeStep}`, { locale });
    const topBarSummary = getTopBarSummary(state);
    const sourceStatusLabel = getSourcePrepareSummary(state, locale)
      || state.source.displayName
      || "";
    const laneMarkup = renderContextLane(state);
    const topBarMarkup = renderTopBar(state, topBarSummary);
    const processRailMarkup = renderProcessRail(state, getProcessRailItems(state));
    const stageMarkupValue = stageMarkup(state);
    const archiveMarkupValue = renderArchiveModal(state);
    const archiveMarkupChanged = archiveMarkupValue !== lastArchiveMarkup;
    const isArchiveOpen = Boolean(state.archive?.isOpen);
    const engineStatus = escapeHtml(state.ui.backend?.ready ? t("status.engineReady", { locale }) : t("status.engineWaiting", { locale }));
    const sourceStatus = escapeHtml(sourceStatusLabel
      ? t("status.sourceLabel", { locale, replacements: { label: sourceStatusLabel } })
      : t("status.sourceIdle", { locale }));
    const inlineNotice = escapeHtml(state.ui.inlineNotice || t("status.sessionStable", { locale }));
    const pagesStatus = escapeHtml(state.review.pages.length
      ? t("status.pagesCount", { locale, replacements: { count: state.review.pages.length } })
      : t("status.pagesEmpty", { locale }));
    const localToolStatus = escapeHtml(t("status.localTool", { locale }));
    const statusMarkup = `
      <div class="status-bar-group">
        <span>${engineStatus}</span>
        <span>${sourceStatus}</span>
      </div>
      <div class="status-bar-group status-bar-group-notice">
        <span>${inlineNotice}</span>
      </div>
      <div class="status-bar-group">
        <span>${pagesStatus}</span>
        <span>${localToolStatus}</span>
      </div>
    `;
    if (shell.appShell) {
      shell.appShell.dataset.step = state.ui.activeStep;
    }
    shell.processRail?.setAttribute?.("aria-label", t("app.aria.workflowSteps", { locale }));
    shell.contextLane?.setAttribute?.("aria-label", t("app.aria.inspectionDetails", { locale }));
    shell.stagePane?.setAttribute?.("aria-label", t("app.aria.stagePane", { locale, replacements: { step: stepLabel } }));
    if (topBarMarkup !== lastTopBarMarkup) {
      shell.topBar.innerHTML = topBarMarkup;
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
      shell.stagePane.innerHTML = stageMarkupValue;
      lastStageMarkup = stageMarkupValue;
      restoreStageInputFocus(shell.stagePane, focusSnapshot);
    }
    if (archiveMarkupChanged) {
      shell.modalLayer.innerHTML = archiveMarkupValue;
      lastArchiveMarkup = archiveMarkupValue;
    }
    syncArchiveShellState(isArchiveOpen);
    if (statusMarkup !== lastStatusMarkup) {
      shell.statusBar.innerHTML = statusMarkup;
      lastStatusMarkup = statusMarkup;
    }
    attachRoiEditor(state);
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
    if (state.ui.activeStep !== lastRenderedStep) {
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
        next.archive.error = String(error?.message || error);
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

  async function loadSourceFromPath(filePath) {
    const targetPath = String(filePath || "").trim();
    if (!targetPath) {
      return;
    }
    stopPolling();
    stopSourcePreparePolling();
    activeJobHandle = null;
    activeSourcePrepareHandle = null;
    runtimeGuards.bumpSourceSession();
    setState((next) => {
      next.source.error = "";
      next.source.status = "loading";
      return next;
    });
    await sourceController.selectLocalFile(targetPath);
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

  function applyJobSnapshot(job) {
    const locale = store.getState().ui.locale || "en";
    const pages = deriveCapturePages(job.result || {}, locale);
    setState((next) => {
      next.exportConfig.jobId = job.job_id;
      next.exportConfig.runStatus = job.status === "done" ? "done" : job.status === "error" ? "error" : "running";
      next.exportConfig.progress = Number(job.progress || 0);
      next.exportConfig.currentStep = String(job.current_step || "");
      next.exportConfig.message = String(job.message || "");
      next.exportConfig.error = job.status === "error" ? String(job.message || t("export.failed", { locale: next.ui.locale })) : "";
      next.exportConfig.outputDir = String(job.result?.output_dir || "");
      next.exportConfig.pdfPath = String(job.result?.pdf || "");
      next.review.pages = pages;
      next.review.selectedPageIds = pages.map((page) => page.id);
      next.review.focusedPageId = pages[0]?.id || "";
      next.review.outputDir = String(job.result?.output_dir || "");
      next.review.pdfPath = String(job.result?.pdf || "");
      next.review.keptCount = Number(job.result?.review_export?.kept_count || pages.length || 0);
      next.review.status = job.result?.review_export ? "applied" : "idle";
      next.review.error = "";
      if (job.status === "done" && pages.length) {
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

  function stopSourcePreparePolling() {
    if (activeSourcePreparePoll) {
      clearTimeout(activeSourcePreparePoll);
      activeSourcePreparePoll = null;
    }
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
      applyJobSnapshot(job);
      if (job.status === "done" || job.status === "error") {
        stopPolling();
        if (job.status === "done") {
          refreshCompletedLibraries();
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
      setState((next) => {
        next.exportConfig.runStatus = "error";
        next.exportConfig.error = String(error?.message || error);
        return next;
      });
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
        activeSourcePrepareHandle = null;
        runtimeGuards.bumpSourceSession();
        await sourceController.completeYoutubePrepare(snapshot, requestToken);
        await loadSelectedPreviewCandidate();
        void refreshLocalMediaRegistry();
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
    const requestToken = sourceController.startYoutubePrepare(youtubeUrl);
    stopSourcePreparePolling();
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
        next.source.error = String(error?.message || error);
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
    if (!dropZone || store.getState().ui.activeStep !== "source") {
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
        next.source.error = String(error?.message || error);
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
        return;
      }
      setState((next) => {
        next.roi.previewImage = preview.imagePath;
        next.roi.previewSourcePath = preview.sourcePath;
        next.roi.diagnostics = preview.diagnostics;
        next.roi.imageWidth = Number(next.source.metadata?.width || 0);
        next.roi.imageHeight = Number(next.source.metadata?.height || 0);
        next.roi.status = "ready";
        next.roi.error = "";
        return next;
      });
    } catch (error) {
      if (!runtimeGuards.isCurrentPreview(previewToken)) {
        return;
      }
      setState((next) => {
        next.roi.status = "error";
        next.roi.error = String(error?.message || error);
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

  function applyRoi() {
    const points = roiEditor?.applyDraft?.() || store.getState().roi.draftRect;
    if (!isRectValid(points)) {
      return;
    }
    setState((next) => {
      next.roi.appliedRect = points;
      next.exportConfig.layoutHint = inferLayoutHintFromRoi(points);
      next.ui.activeStep = "export";
      return next;
    });
  }

  function buildJobPayload(state) {
    const roi = state.roi.appliedRect;
    const layoutHint = inferLayoutHintFromRoi(roi);
    const fallbackDocumentHeader = createDocumentHeaderState(state.source.filePath);
    const documentHeader = normalizeDocumentHeader(state.exportConfig.documentHeader, fallbackDocumentHeader);
    const sourceIdentity = {
      kind: state.source.archiveSourceKind || "file",
      key: state.source.archiveSourceKey || state.source.filePath,
      display_name: state.source.archiveDisplayName || state.source.displayName || fallbackDocumentHeader.title,
    };
    return {
      source_type: "file",
      file_path: state.source.filePath,
      source_identity: sourceIdentity,
      options: {
        extract: {
          fps: 1.0,
          capture_sensitivity: "medium",
          start_sec: 0,
          end_sec: null,
        },
        detect: {
          roi,
          layout_hint: layoutHint,
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
          formats: state.exportConfig.formats.slice(),
          include_raw_frames: false,
          page_fill_mode: state.exportConfig.pageFillMode || "performance",
          document_header: documentHeader,
        },
      },
    };
  }

  function resetExportOutputs(next) {
    next.exportConfig.runStatus = "running";
    next.exportConfig.error = "";
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
    return next;
  }

  function openExportMetadataModal() {
    const state = store.getState();
    const fallbackDocumentHeader = createDocumentHeaderState(state.source.filePath);
    const confirmedHeader = normalizeDocumentHeader(state.exportConfig.documentHeader, fallbackDocumentHeader);
    setState((next) => {
      next.exportConfig.error = "";
      next.exportConfig.metadataModal = createExportMetadataModalState(
        next.source.filePath,
        new Date(),
        confirmedHeader,
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
    if (modal.dirty && !forceDiscard) {
      setState((next) => {
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
      );
      return next;
    });
  }

  function updateExportMetadata(field, value) {
    const state = store.getState();
    const modal = state.exportConfig.metadataModal;
    if (!modal?.isOpen || !field) {
      return;
    }
    const nextValue = sanitizeDocumentHeaderDraftField(field, value);
    setState((next) => {
      const currentModal = next.exportConfig.metadataModal || createExportMetadataModalState(next.source.filePath);
      const draft = {
        ...currentModal.draft,
        [field]: nextValue,
      };
      currentModal.draft = draft;
      currentModal.dirty = isExportMetadataDirty(draft, next.exportConfig.documentHeader);
      currentModal.showDiscardConfirm = false;
      if (field === "title") {
        currentModal.validation.title = "";
      }
      if (field === "bpm") {
        currentModal.validation.bpm = "";
      }
      next.exportConfig.metadataModal = currentModal;
      return next;
    });
  }

  async function startExportRun(state = store.getState()) {
    if (!canRunExport(state)) {
      if (state.source.filePath && isRectValid(state.roi.appliedRect) && state.exportConfig.formats.length === 0) {
        setState((next) => {
          next.exportConfig.error = t("export.formatsRequiredError", { locale: next.ui.locale });
          return next;
        });
      }
      return;
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
        return;
      }
      activeJobHandle = jobHandle;
      setState((next) => {
        next.exportConfig.jobId = jobId;
        return next;
      });
      await pollJob(jobId, jobHandle);
    } catch (error) {
      setState((next) => {
        next.exportConfig.runStatus = "error";
        next.exportConfig.error = String(error?.message || error);
        return next;
      });
    }
  }

  async function confirmExportMetadata() {
    const state = store.getState();
    const modal = state.exportConfig.metadataModal;
    if (!modal?.isOpen) {
      return;
    }
    const sanitizedDraft = {
      ...modal.draft,
      bpm: sanitizeDocumentHeaderDraftField("bpm", modal.draft?.bpm),
    };
    const validation = validateExportMetadataDraft(sanitizedDraft, state.ui.locale || "en");
    if (validation.title || validation.bpm) {
      setState((next) => {
        next.exportConfig.metadataModal.validation = validation;
        next.exportConfig.metadataModal.showDiscardConfirm = false;
        return next;
      });
      return;
    }
    const fallbackDocumentHeader = createDocumentHeaderState(state.source.filePath);
    const documentHeader = normalizeDocumentHeader(sanitizedDraft, fallbackDocumentHeader);
    setState((next) => {
      next.exportConfig.documentHeader = documentHeader;
      next.exportConfig.metadataModal = createExportMetadataModalState(
        next.source.filePath,
        new Date(),
        documentHeader,
      );
      return next;
    });
    await startExportRun(store.getState());
  }

  async function runExport() {
    const state = store.getState();
    if (!canRunExport(state)) {
      await startExportRun(state);
      return;
    }
    if (isPdfSelected(state.exportConfig.formats)) {
      openExportMetadataModal();
      return;
    }
    await startExportRun(state);
  }

  async function applyReviewSelection() {
    const state = store.getState();
    if (
      !state.exportConfig.jobId
      || state.exportConfig.runStatus !== "done"
      || state.review.status === "applied"
      || state.review.status === "running"
    ) {
      return;
    }
    const selected = state.review.pages
      .filter((page) => state.review.selectedPageIds.includes(page.id))
      .map((page) => page.capturePath);
    if (!selected.length) {
      return;
    }
    setState((next) => {
      next.review.status = "running";
      next.review.error = "";
      return next;
    });
    try {
      await runtimeApi.reviewExport(state.exportConfig.jobId, selected, state.exportConfig.formats);
      const refreshed = await runtimeApi.getJob(state.exportConfig.jobId);
      if (activeJobHandle && !runtimeGuards.isCurrentJob(activeJobHandle, state.exportConfig.jobId)) {
        return;
      }
      applyJobSnapshot(refreshed);
      refreshCompletedLibraries();
      setInlineNotice(notice("review.applied", { locale: store.getState().ui.locale || "en" }));
    } catch (error) {
      setState((next) => {
        next.review.status = "error";
        next.review.error = String(error?.message || error);
        return next;
      });
    }
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
        replacements: { label, reason: String(error?.message || error) },
      }));
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
        replacements: { label, reason: String(error?.message || error) },
      }));
    }
  }

  const handleClick = async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) {
      return;
    }
    const action = target.dataset.action;
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
        await loadSourceFromPath(target.dataset.filePath);
      } catch (error) {
        setState((next) => {
          next.source.status = "error";
          next.source.error = String(error?.message || error);
          return next;
        });
      }
      return;
    }
    if (action === "set-locale") {
      const locale = persistLocale(target.dataset.locale);
      setState((next) => {
        next.ui.locale = locale;
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
    if (action === "close-archive") {
      closeArchive();
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
        return next;
      });
      return;
    }
    if (action === "apply-review") {
      await applyReviewSelection();
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
    }
  };

  const handleInput = (event) => {
    const target = event.target;
    if (target.dataset.action === "youtube-url-input") {
      stopSourcePreparePolling();
      activeSourcePrepareHandle = null;
      runtimeGuards.invalidateSourcePrepare();
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
    if (target.dataset.action === "toggle-format") {
      const format = target.dataset.format;
      setState((next) => {
        const nextFormats = new Set(next.exportConfig.formats);
        if (target.checked) {
          nextFormats.add(format);
        } else {
          nextFormats.delete(format);
        }
        next.exportConfig.formats = Array.from(nextFormats);
        return next;
      });
      return;
    }
    if (target.dataset.action === "update-export-metadata") {
      updateExportMetadata(String(target.dataset.field || ""), target.value);
      return;
    }
    if (target.dataset.action === "toggle-review-page") {
      const { pageId } = target.dataset;
      setState((next) => {
        if (next.review.status === "applied") {
          return next;
        }
        const selected = new Set(next.review.selectedPageIds);
        if (target.checked) {
          selected.add(pageId);
        } else {
          selected.delete(pageId);
        }
        next.review.selectedPageIds = Array.from(selected);
        return next;
      });
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

  const handleKeyDown = (event) => {
    if (event.key === "Escape" && store.getState().archive.isOpen) {
      event.preventDefault?.();
      closeArchive();
    }
  };

  root.addEventListener("click", handleClick);
  root.addEventListener("input", handleInput);
  root.addEventListener("keydown", handleKeyDown);
  root.addEventListener("dragenter", handleDragEnter);
  root.addEventListener("dragover", handleDragOver);
  root.addEventListener("dragleave", handleDragLeave);
  root.addEventListener("drop", handleDrop);

  const unsubscribeStore = store.subscribe(render);
  const unsubscribeBackend = runtimeBridge.onBackendState((payload) => {
    const becameReady = Boolean(payload?.ready) && !lastBackendReady;
    lastBackendReady = Boolean(payload?.ready);
    setState((next) => {
      next.ui.backend = payload;
      return next;
    });
    if (becameReady) {
      void refreshLocalMediaRegistry();
      void refreshArchiveLibrary();
    }
  });

  refreshBackendState();
  render();

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
      stopPolling();
      stopSourcePreparePolling();
      destroyRoiEditor();
      unsubscribeStore?.();
      unsubscribeBackend?.();
      if (typeof root.removeEventListener === "function") {
        root.removeEventListener("click", handleClick);
        root.removeEventListener("input", handleInput);
        root.removeEventListener("keydown", handleKeyDown);
        root.removeEventListener("dragenter", handleDragEnter);
        root.removeEventListener("dragover", handleDragOver);
        root.removeEventListener("dragleave", handleDragLeave);
        root.removeEventListener("drop", handleDrop);
      }
    },
  };
}
