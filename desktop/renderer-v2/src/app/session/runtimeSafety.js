import { isRectValid } from "./selectors.js";

export function createRuntimeGuards() {
  let sourceSession = 0;
  let sourcePrepareVersion = 0;
  let previewVersion = 0;
  let exportVersion = 0;
  let activeJob = null;
  let activeSourcePrepare = null;

  return {
    bumpSourceSession() {
      sourceSession += 1;
      sourcePrepareVersion += 1;
      previewVersion += 1;
      exportVersion += 1;
      activeJob = null;
      activeSourcePrepare = null;
      return sourceSession;
    },
    invalidateSourcePrepare() {
      sourcePrepareVersion += 1;
      activeSourcePrepare = null;
      return sourcePrepareVersion;
    },
    invalidatePreview() {
      previewVersion += 1;
      return previewVersion;
    },
    invalidateExport() {
      exportVersion += 1;
      activeJob = null;
      return exportVersion;
    },
    beginPreviewRequest() {
      previewVersion += 1;
      return { sourceSession, previewVersion };
    },
    beginSourcePrepare() {
      sourcePrepareVersion += 1;
      activeSourcePrepare = null;
      return { sourceSession, sourcePrepareVersion };
    },
    attachSourcePrepare(token, jobId) {
      const handle = { ...token, jobId };
      if (!this.isCurrentSourcePrepare(handle)) {
        return null;
      }
      activeSourcePrepare = handle;
      return handle;
    },
    isCurrentSourcePrepare(token) {
      return Boolean(token) && token.sourceSession === sourceSession && token.sourcePrepareVersion === sourcePrepareVersion;
    },
    isCurrentSourcePrepareJob(handle, jobId = handle?.jobId) {
      return Boolean(handle)
        && Boolean(activeSourcePrepare)
        && activeSourcePrepare.jobId === handle.jobId
        && activeSourcePrepare.jobId === jobId
        && this.isCurrentSourcePrepare(handle);
    },
    isCurrentPreview(token) {
      return Boolean(token) && token.sourceSession === sourceSession && token.previewVersion === previewVersion;
    },
    beginExportRun() {
      exportVersion += 1;
      activeJob = null;
      return { sourceSession, exportVersion };
    },
    attachJob(token, jobId) {
      const handle = { ...token, jobId };
      if (!this.isCurrentExport(handle)) {
        return null;
      }
      activeJob = handle;
      return handle;
    },
    isCurrentExport(token) {
      return Boolean(token) && token.sourceSession === sourceSession && token.exportVersion === exportVersion;
    },
    isCurrentJob(handle, jobId = handle?.jobId) {
      return Boolean(handle)
        && Boolean(activeJob)
        && activeJob.jobId === handle.jobId
        && activeJob.jobId === jobId
        && this.isCurrentExport(handle);
    },
  };
}

export function invalidatePreviewFlow(state, {
  frameTime,
  frameTimeLabel,
  preserveCandidates = false,
  selectedPreviewCandidateId = "",
}) {
  const previewCandidates = preserveCandidates ? (state.roi.previewCandidates || []).slice() : [];
  state.roi.frameTime = frameTime;
  state.roi.frameTimeLabel = frameTimeLabel;
  state.roi.previewCandidates = previewCandidates;
  state.roi.selectedPreviewCandidateId = preserveCandidates ? String(selectedPreviewCandidateId || "") : "";
  state.roi.previewImage = "";
  state.roi.previewSourcePath = "";
  state.roi.diagnostics = [];
  state.roi.draftRect = null;
  state.roi.appliedRect = null;
  state.roi.imageWidth = 0;
  state.roi.imageHeight = 0;
  state.roi.status = "idle";
  state.roi.error = "";

  state.exportConfig.jobId = "";
  state.exportConfig.runStatus = "idle";
  state.exportConfig.progress = 0;
  state.exportConfig.currentStep = "";
  state.exportConfig.message = "";
  state.exportConfig.outputDir = "";
  state.exportConfig.pdfPath = "";
  state.exportConfig.error = "";

  state.review.pages = [];
  state.review.selectedPageIds = [];
  state.review.focusedPageId = "";
  state.review.status = "idle";
  state.review.error = "";
  state.review.keptCount = 0;
  state.review.outputDir = "";
  state.review.pdfPath = "";
}

export function canRunExport(state) {
  return Boolean(state?.source?.filePath)
    && isRectValid(state?.roi?.appliedRect)
    && Array.isArray(state?.exportConfig?.formats)
    && state.exportConfig.formats.length > 0;
}
