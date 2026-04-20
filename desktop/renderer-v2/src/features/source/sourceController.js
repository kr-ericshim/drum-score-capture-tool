import { buildRepresentativeFrameCandidates } from "../../app/session/selectors.js";

export function createSourceController({
  store,
  readMetadata,
  formatSecondsLabel,
  resetDownstream,
  baseName,
  messages,
}) {
  let sourceRequestToken = 0;

  function withoutExtension(value = "") {
    return String(value || "").replace(/\.[^.]+$/, "");
  }

  function clearArchiveIdentity(next) {
    next.source.archiveSourceKind = "";
    next.source.archiveSourceKey = "";
    next.source.archiveDisplayName = "";
    next.source.displayName = "";
  }

  function bumpSourceToken() {
    sourceRequestToken += 1;
    return sourceRequestToken;
  }

  function isCurrentToken(requestToken) {
    return requestToken === sourceRequestToken;
  }

  function clearPrepareState(next) {
    next.source.prepareStatus = "idle";
    next.source.prepareJobId = "";
    next.source.prepareStage = "";
    next.source.prepareProgress = 0;
    next.source.prepareProgressMode = "indeterminate";
    next.source.prepareMessage = "";
    next.source.prepareFromCache = false;
    next.source.prepareLogs = [];
    next.source.prepareErrorDetail = "";
    next.source.error = "";
  }

  function resolveLocalSourceIdentity(filePath, sourceDetails = {}) {
    const sourceOrigin = String(sourceDetails.sourceOrigin || "").trim();
    const youtubeUrl = String(sourceDetails.youtubeUrl || "").trim();
    const reopenedDisplayName = String(sourceDetails.displayName || "").trim();
    const preparedFromYouTube = sourceOrigin === "prepared" && Boolean(youtubeUrl);
    const fileLabel = baseName(filePath);
    const displayName = reopenedDisplayName || fileLabel;

    return {
      sourceType: preparedFromYouTube ? "youtube" : "file",
      youtubeUrl: preparedFromYouTube ? youtubeUrl : "",
      archiveSourceKind: preparedFromYouTube ? "youtube" : "file",
      archiveSourceKey: preparedFromYouTube ? youtubeUrl : filePath,
      archiveDisplayName: preparedFromYouTube ? displayName : withoutExtension(fileLabel),
      displayName,
      preparedFromYouTube,
      preparedVideoPath: preparedFromYouTube ? filePath : "",
    };
  }

  function clearResolvedSourceState(next, { sourceType = next.source.sourceType || "file", youtubeUrl = next.source.youtubeUrl || "" } = {}) {
    next.source.sourceType = sourceType;
    next.source.filePath = "";
    next.source.displayName = "";
    next.source.metadata = null;
    next.source.status = "idle";
    next.source.youtubeUrl = youtubeUrl;
    next.source.preparedFromYouTube = false;
    next.source.preparedVideoPath = "";
    clearArchiveIdentity(next);
    clearPrepareState(next);
    resetDownstream(next);
    next.ui.activeStep = "source";
  }

  function seedRepresentativeFrames(next, metadata) {
    const candidates = buildRepresentativeFrameCandidates(metadata?.durationSec);
    const defaultCandidate = candidates[1] || candidates[0] || null;
    next.roi.previewCandidates = candidates;
    next.roi.selectedPreviewCandidateId = defaultCandidate?.id || "";
    next.roi.frameTime = defaultCandidate?.sec ?? 0;
    next.roi.frameTimeLabel = defaultCandidate?.label || formatSecondsLabel(0);
  }

  function startYoutubePrepare(youtubeUrl) {
    const requestToken = bumpSourceToken();
    store.setState((next) => {
      clearResolvedSourceState(next, {
        sourceType: "youtube",
        youtubeUrl,
      });
      next.source.status = "loading";
      next.source.prepareStatus = "loading";
      next.source.prepareJobId = "";
      next.source.prepareStage = "queued";
      next.source.prepareProgress = 0;
      next.source.prepareProgressMode = "indeterminate";
      next.source.prepareMessage = "";
      next.source.prepareFromCache = false;
      next.source.prepareLogs = [];
      return next;
    });
    return requestToken;
  }

  function applyPrepareJobStarted(jobId, requestToken) {
    if (!isCurrentToken(requestToken)) {
      return false;
    }
    store.setState((next) => {
      next.source.prepareJobId = jobId;
      next.source.prepareStatus = "loading";
      next.source.prepareStage = next.source.prepareStage || "queued";
      return next;
    });
    return true;
  }

  function applyPrepareJobSnapshot(snapshot, requestToken) {
    if (!isCurrentToken(requestToken)) {
      return false;
    }
    const status = String(snapshot?.status || "queued");
    const progressMode = String(snapshot?.progressMode || "indeterminate");
    const detail = messages.youtubePrepareDetail
      ? messages.youtubePrepareDetail(snapshot?.message || "")
      : String(snapshot?.message || "").trim();

    store.setState((next) => {
      next.source.prepareJobId = String(snapshot?.jobId || next.source.prepareJobId || "");
      next.source.prepareStatus = status === "error" ? "error" : status === "done" ? "ready" : "loading";
      next.source.prepareStage = String(snapshot?.stage || next.source.prepareStage || "");
      next.source.prepareProgress = Number(snapshot?.progress || 0);
      next.source.prepareProgressMode = progressMode;
      next.source.prepareMessage = String(snapshot?.message || "");
      next.source.prepareLogs = Array.isArray(snapshot?.logLines) ? snapshot.logLines : [];
      next.source.prepareFromCache = Boolean(snapshot?.result?.fromCache);
      if (status === "error") {
        next.source.prepareErrorDetail = detail;
        next.source.error = messages.youtubePrepareError(detail, next.ui.locale);
      } else {
        next.source.prepareErrorDetail = "";
        next.source.error = "";
      }
      return next;
    });
    return true;
  }

  async function completeYoutubePrepare(snapshot, requestToken) {
    if (!isCurrentToken(requestToken)) {
      return false;
    }
    const preparedPath = String(snapshot?.result?.videoPath || "").trim();
    if (!preparedPath) {
      throw new Error("prepared youtube video path is missing");
    }
    const metadata = await readMetadata(preparedPath);
    if (!isCurrentToken(requestToken)) {
      return false;
    }

    store.setState((next) => {
      const archiveSourceKey = String(snapshot?.result?.sourceKey || next.source.youtubeUrl || "");
      const archiveDisplayName = String(snapshot?.result?.videoTitle || "").trim() || baseName(preparedPath);
      next.source.filePath = preparedPath;
      next.source.archiveSourceKind = "youtube";
      next.source.archiveSourceKey = archiveSourceKey;
      next.source.archiveDisplayName = archiveDisplayName;
      next.source.displayName = archiveDisplayName;
      next.source.metadata = metadata;
      next.source.status = "ready";
      next.source.preparedFromYouTube = true;
      next.source.preparedVideoPath = preparedPath;
      next.source.prepareStatus = "ready";
      next.source.prepareJobId = String(snapshot?.jobId || "");
      next.source.prepareStage = String(snapshot?.stage || "done");
      next.source.prepareProgress = Number(snapshot?.progress || 1);
      next.source.prepareProgressMode = String(snapshot?.progressMode || "determinate");
      next.source.prepareMessage = String(snapshot?.message || "");
      next.source.prepareLogs = Array.isArray(snapshot?.logLines) ? snapshot.logLines : [];
      next.source.prepareFromCache = Boolean(snapshot?.result?.fromCache);
      next.source.prepareErrorDetail = "";
      next.source.error = "";
      resetDownstream(next);
      seedRepresentativeFrames(next, metadata);
      next.ui.activeStep = "roi";
      return next;
    });
    return true;
  }

  function failYoutubePrepare(errorOrDetail, requestToken) {
    if (!isCurrentToken(requestToken)) {
      return false;
    }
    const detail = messages.youtubePrepareDetail ? messages.youtubePrepareDetail(errorOrDetail) : String(errorOrDetail || "").trim();
    store.setState((next) => {
      next.source.prepareStatus = "error";
      next.source.prepareStage = next.source.prepareStage || "failed";
      next.source.prepareMessage = detail;
      next.source.prepareErrorDetail = detail;
      next.source.error = messages.youtubePrepareError(detail, next.ui.locale);
      next.source.prepareLogs = messages.mergePrepareLogs(next.source.prepareLogs, errorOrDetail);
      return next;
    });
    return true;
  }

  async function selectLocalFile(filePath, sourceDetails = {}) {
    const sourceIdentity = resolveLocalSourceIdentity(filePath, sourceDetails);
    const requestToken = bumpSourceToken();
    store.setState((next) => {
      clearResolvedSourceState(next, {
        sourceType: sourceIdentity.sourceType,
        youtubeUrl: sourceIdentity.youtubeUrl,
      });
      next.source.status = "loading";
      return next;
    });
    const metadata = await readMetadata(filePath);
    if (!isCurrentToken(requestToken)) {
      return;
    }
    store.setState((next) => {
      next.source.sourceType = sourceIdentity.sourceType;
      next.source.filePath = filePath;
      next.source.archiveSourceKind = sourceIdentity.archiveSourceKind;
      next.source.archiveSourceKey = sourceIdentity.archiveSourceKey;
      next.source.archiveDisplayName = sourceIdentity.archiveDisplayName;
      next.source.displayName = sourceIdentity.displayName;
      next.source.metadata = metadata;
      next.source.status = "ready";
      next.source.youtubeUrl = sourceIdentity.youtubeUrl;
      next.source.preparedFromYouTube = sourceIdentity.preparedFromYouTube;
      next.source.preparedVideoPath = sourceIdentity.preparedVideoPath;
      clearPrepareState(next);
      resetDownstream(next);
      seedRepresentativeFrames(next, metadata);
      next.ui.activeStep = "roi";
      return next;
    });
  }

  function setSourceType(sourceType) {
    bumpSourceToken();
    store.setState((next) => {
      if (sourceType === "file") {
        clearResolvedSourceState(next, {
          sourceType,
          youtubeUrl: "",
        });
      } else {
        next.source.sourceType = sourceType;
      }
      return next;
    });
  }

  function setYoutubeUrl(youtubeUrl) {
    bumpSourceToken();
    store.setState((next) => {
      clearResolvedSourceState(next, {
        sourceType: "youtube",
        youtubeUrl,
      });
      return next;
    });
  }

  return {
    startYoutubePrepare,
    applyPrepareJobStarted,
    applyPrepareJobSnapshot,
    completeYoutubePrepare,
    failYoutubePrepare,
    selectLocalFile,
    setSourceType,
    setYoutubeUrl,
  };
}
