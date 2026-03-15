export function createSourceController({
  store,
  api,
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

  async function prepareYoutube(youtubeUrl) {
    const requestToken = bumpSourceToken();
    store.setState((next) => {
      next.source.sourceType = "youtube";
      next.source.youtubeUrl = youtubeUrl;
      next.source.prepareStatus = "loading";
      next.source.error = "";
      next.source.prepareErrorDetail = "";
      return next;
    });

    try {
      const prepared = await api.preparePreviewSource({
        sourceType: "youtube",
        youtubeUrl,
      });
      if (requestToken !== sourceRequestToken) {
        return;
      }
      const metadata = await readMetadata(prepared.videoPath);
      if (requestToken !== sourceRequestToken) {
        return;
      }

      store.setState((next) => {
        next.source.filePath = prepared.videoPath;
        next.source.displayName = baseName(prepared.videoPath);
        next.source.metadata = metadata;
        next.source.status = "ready";
        next.source.preparedFromYouTube = true;
        next.source.preparedVideoPath = prepared.videoPath;
        next.source.prepareStatus = "ready";
        next.source.prepareLogs = prepared.logLines;
        next.source.prepareErrorDetail = "";
        resetDownstream(next);
        next.roi.frameTime = metadata?.durationSec ? Math.min(5, Math.floor(metadata.durationSec / 3)) : 0;
        next.roi.frameTimeLabel = formatSecondsLabel(next.roi.frameTime);
        next.ui.activeStep = "roi";
        return next;
      });
    } catch (error) {
      if (requestToken !== sourceRequestToken) {
        return;
      }
      const detail = messages.youtubePrepareDetail ? messages.youtubePrepareDetail(error) : String(error?.message || error || "").trim();
      store.setState((next) => {
        next.source.prepareStatus = "error";
        next.source.prepareErrorDetail = detail;
        next.source.error = messages.youtubePrepareError(detail, next.ui.locale);
        next.source.prepareLogs = messages.mergePrepareLogs(next.source.prepareLogs, error);
        return next;
      });
    }
  }

  async function selectLocalFile(filePath) {
    const requestToken = bumpSourceToken();
    const metadata = await readMetadata(filePath);
    if (requestToken !== sourceRequestToken) {
      return;
    }
    store.setState((next) => {
      next.source.sourceType = "file";
      next.source.filePath = filePath;
      next.source.displayName = baseName(filePath);
      next.source.metadata = metadata;
      next.source.status = "ready";
      next.source.error = "";
      next.source.preparedFromYouTube = false;
      next.source.preparedVideoPath = "";
      next.source.prepareStatus = "idle";
      next.source.prepareLogs = [];
      next.source.prepareErrorDetail = "";
      resetDownstream(next);
      next.roi.frameTime = metadata?.durationSec ? Math.min(5, Math.floor(metadata.durationSec / 3)) : 0;
      next.roi.frameTimeLabel = formatSecondsLabel(next.roi.frameTime);
      next.ui.activeStep = "roi";
      return next;
    });
  }

  function setSourceType(sourceType) {
    bumpSourceToken();
    store.setState((next) => {
      next.source.sourceType = sourceType;
      if (sourceType === "file") {
        next.source.prepareStatus = "idle";
        next.source.error = "";
        next.source.prepareLogs = [];
        next.source.prepareErrorDetail = "";
        next.source.preparedFromYouTube = false;
        next.source.preparedVideoPath = "";
      }
      return next;
    });
  }

  function setYoutubeUrl(youtubeUrl) {
    bumpSourceToken();
    store.setState((next) => {
      next.source.sourceType = "youtube";
      next.source.youtubeUrl = youtubeUrl;
      next.source.prepareStatus = "idle";
      next.source.error = "";
      next.source.prepareLogs = [];
      next.source.prepareErrorDetail = "";
      next.source.preparedFromYouTube = false;
      next.source.preparedVideoPath = "";
      return next;
    });
  }

  return {
    prepareYoutube,
    selectLocalFile,
    setSourceType,
    setYoutubeUrl,
  };
}
