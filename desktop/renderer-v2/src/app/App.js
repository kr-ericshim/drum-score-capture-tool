import { bridge, readVideoMetadata } from "./bridge.js";
import { createStore } from "./session/store.js";
import {
  createInitialSessionState,
  deriveCapturePages,
  formatSecondsLabel,
  getAccessibleSteps,
  getProcessRailItems,
  getTopBarSummary,
  inferLayoutHintFromRoi,
  isRectValid,
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
import { mountRoiEditor } from "../features/roi/roiEditor.js";
import { createJob, getJob, preparePreviewSource, requestPreviewFrame, reviewExport } from "../lib/api.js";
import { t } from "../lib/i18n.js";
import { baseName } from "../lib/paths.js";
import { persistLocale } from "../lib/i18n.js";
import { mergePrepareLogs, notice, youtubePrepareDetail, youtubePrepareError } from "../lib/messages.js";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
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

export function createApp(root, dependencies = {}) {
  const runtimeBridge = dependencies.bridge || bridge;
  const readMetadata = dependencies.readVideoMetadata || readVideoMetadata;
  const runtimeApi = dependencies.api || {
    createJob,
    getJob,
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
    api: runtimeApi,
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
  let activeSourceSelection = 0;
  let lastRenderedStep = "";
  let lastTopBarMarkup = "";
  let lastProcessRailMarkup = "";
  let lastContextLaneMarkup = "";
  let lastStageMarkup = "";
  let lastStatusMarkup = "";
  const runtimeGuards = createRuntimeGuards();

  function setState(updater) {
    store.setState(updater);
  }

  function resetDownstream(next) {
    next.roi = {
      frameTime: 0,
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
    };
    next.exportConfig = {
      formats: ["png", "pdf"],
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
    };
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
    if (state.ui.activeStep === "source") return renderSourceScreen(state);
    if (state.ui.activeStep === "roi") return renderRoiScreen(state);
    if (state.ui.activeStep === "export") return renderExportScreen(state);
    return renderReviewScreen(state);
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
    const stepLabel = t(`topbar.step.${state.ui.activeStep}`, { locale });
    const laneMarkup = renderContextLane(state);
    const topBarMarkup = renderTopBar(state, getTopBarSummary(state));
    const processRailMarkup = renderProcessRail(state, getProcessRailItems(state));
    const stageMarkupValue = stageMarkup(state);
    const statusMarkup = `
      <div class="status-bar-group">
        <span>${state.ui.backend?.ready ? t("status.engineReady", { locale }) : t("status.engineWaiting", { locale })}</span>
        <span>${state.source.displayName
          ? t("status.sourceLabel", { locale, replacements: { label: state.source.displayName } })
          : t("status.sourceIdle", { locale })}</span>
      </div>
      <div class="status-bar-group status-bar-group-notice">
        <span>${state.ui.inlineNotice || t("status.sessionStable", { locale })}</span>
      </div>
      <div class="status-bar-group">
        <span>${state.review.pages.length
          ? t("status.pagesCount", { locale, replacements: { count: state.review.pages.length } })
          : t("status.pagesEmpty", { locale })}</span>
        <span>${t("status.localTool", { locale })}</span>
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
      shell.stagePane.innerHTML = stageMarkupValue;
      lastStageMarkup = stageMarkupValue;
    }
    if (statusMarkup !== lastStatusMarkup) {
      shell.statusBar.innerHTML = statusMarkup;
      lastStatusMarkup = statusMarkup;
    }
    attachRoiEditor(state);
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
    setState((next) => {
      next.ui.backend = payload;
      return next;
    });
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

  function setInlineNotice(message) {
    setState((next) => {
      next.ui.inlineNotice = String(message || "");
      return next;
    });
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
      stopPolling();
      activeJobHandle = null;
      runtimeGuards.bumpSourceSession();
      await sourceController.selectLocalFile(filePath);
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
    return {
      source_type: "file",
      file_path: state.source.filePath,
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
          page_fill_mode: "performance",
        },
      },
    };
  }

  async function runExport() {
    const state = store.getState();
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
      if (!runtimeGuards.isCurrentJob(activeJobHandle, state.exportConfig.jobId)) {
        return;
      }
      applyJobSnapshot(refreshed);
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
      await sourceController.prepareYoutube(store.getState().source.youtubeUrl);
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
    if (action === "apply-roi") {
      applyRoi();
      return;
    }
    if (action === "run-export") {
      await runExport();
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
    }
  };

  const handleInput = (event) => {
    const target = event.target;
    if (target.dataset.action === "youtube-url-input") {
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
        });
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

  root.addEventListener("click", handleClick);
  root.addEventListener("input", handleInput);

  const unsubscribeStore = store.subscribe(render);
  const unsubscribeBackend = runtimeBridge.onBackendState((payload) => {
    setState((next) => {
      next.ui.backend = payload;
      return next;
    });
  });

  refreshBackendState();
  render();

  return {
    debug: dependencies.exposeTestApi
      ? {
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
      destroyRoiEditor();
      unsubscribeStore?.();
      unsubscribeBackend?.();
      if (typeof root.removeEventListener === "function") {
        root.removeEventListener("click", handleClick);
        root.removeEventListener("input", handleInput);
      }
    },
  };
}
