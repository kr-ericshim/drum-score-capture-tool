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

  function clearArchiveIdentity(next) {
    next.source.archiveSourceKind = "";
    next.source.archiveSourceKey = "";
    next.source.archiveDisplayName = "";
    next.source.displayName = "";
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
      next.source.sourceType = "youtube";
      next.source.youtubeUrl = youtubeUrl;
      clearArchiveIdentity(next);
      next.source.prepareStatus = "loading";
      next.source.prepareJobId = "";
      next.source.prepareStage = "queued";
      next.source.prepareProgress = 0;
      next.source.prepareProgressMode = "indeterminate";
      next.source.prepareMessage = "";
      next.source.prepareFromCache = false;
      next.source.prepareLogs = [];
      next.source.prepareErrorDetail = "";
      next.source.error = "";
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

  async function selectLocalFile(filePath) {
    const requestToken = bumpSourceToken();
    const metadata = await readMetadata(filePath);
    if (!isCurrentToken(requestToken)) {
      return;
    }
    store.setState((next) => {
      next.source.sourceType = "file";
      next.source.filePath = filePath;
      clearArchiveIdentity(next);
      next.source.displayName = baseName(filePath);
      next.source.metadata = metadata;
      next.source.status = "ready";
      next.source.preparedFromYouTube = false;
      next.source.preparedVideoPath = "";
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
      next.source.sourceType = sourceType;
      if (sourceType === "file") {
        next.source.preparedFromYouTube = false;
        next.source.preparedVideoPath = "";
        clearArchiveIdentity(next);
        clearPrepareState(next);
      }
      return next;
    });
  }

  function setYoutubeUrl(youtubeUrl) {
    bumpSourceToken();
    store.setState((next) => {
      next.source.sourceType = "youtube";
      next.source.youtubeUrl = youtubeUrl;
      next.source.preparedFromYouTube = false;
      next.source.preparedVideoPath = "";
      clearArchiveIdentity(next);
      clearPrepareState(next);
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
