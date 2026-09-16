const KEY = "drum-sheet-session-v1";

export function restoreSession(storage, initial) {
  try {
    const saved = JSON.parse(storage?.getItem(KEY) || "null");
    if (saved?.version !== 1 || typeof saved.source?.filePath !== "string" || !saved.source.filePath) return initial;
    initial.source = { ...initial.source, ...saved.source, status: "ready" };
    initial.roi = { ...initial.roi, ...saved.roi, draftRect: saved.roi?.appliedRect || null };
    initial.exportConfig = { ...initial.exportConfig, ...saved.exportConfig };
    initial.review.restoredSelectedPaths = saved.review?.selectedPaths ?? null;
    initial.ui.activeStep = initial.exportConfig.jobId ? "export" : "roi";
    return initial;
  } catch (_) {
    return initial;
  }
}

export function saveSession(storage, state) {
  try {
    const { source, roi, exportConfig } = state;
    if (!source.filePath) {
      storage?.removeItem(KEY);
      return;
    }
    storage?.setItem(KEY, JSON.stringify({
      version: 1,
      source: Object.fromEntries(["filePath", "sourceType", "displayName", "metadata", "youtubeUrl", "preparedFromYouTube", "archiveSourceKind", "archiveSourceKey", "archiveDisplayName"].map(key => [key, source[key]])),
      roi: { ...roi, previewImage: roi.previewSourcePath || "", draftRect: null, diagnostics: [], error: "" },
      exportConfig: Object.fromEntries(["formats", "pageFillMode", "layoutHint", "jobId", "runStatus", "documentHeader"].map(key => [key, exportConfig[key]])),
      review: { selectedPaths: state.review.pages.length
        ? state.review.pages.filter(page => state.review.selectedPageIds.includes(page.id)).map(page => page.capturePath)
        : state.review.restoredSelectedPaths ?? null },
    }));
  } catch (_) {
    // Storage failure must not prevent capture or destroy an in-memory draft.
  }
}
