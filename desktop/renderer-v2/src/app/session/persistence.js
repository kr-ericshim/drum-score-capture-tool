const KEY = "drum-sheet-session-v1";

export function restoreSession(storage, initial) {
  try {
    const saved = JSON.parse(storage?.getItem(KEY) || "null");
    if (saved?.version !== 1 || typeof saved.source?.filePath !== "string" || !saved.source.filePath) return initial;
    initial.source = { ...initial.source, ...saved.source, status: "ready" };
    initial.roi = { ...initial.roi, ...saved.roi, draftRect: saved.roi?.appliedRect || null };
    initial.exportConfig = { ...initial.exportConfig, ...saved.exportConfig };
    // score layout choice: only an explicit "off" turns measure reflow off
    initial.exportConfig.measureReflow = saved.exportConfig?.measureReflow !== false;
    initial.review.restoredSelectedPaths = saved.review?.selectedPaths ?? null;
    // An unsaved review draft (selection and, for clean reflow jobs, the system order)
    // belongs to one job revision; it is restored only onto that revision.
    initial.review.restoredDraftKey = saved.review?.jobId
      ? { jobId: String(saved.review.jobId), revision: Number(saved.review.revision ?? -1) }
      : null;
    initial.review.restoredSystemOrder = Array.isArray(saved.review?.systemOrder) ? saved.review.systemOrder.map(String) : null;
    // whether the saved files were built from exactly this draft (selection, order, crops, layout)
    initial.review.restoredApplied = saved.review?.applied === true;
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
      roi: {
        ...roi,
        previewImage: roi.previewSourcePath || "",
        draftRect: null,
        diagnostics: [],
        autoRoiStatus: "idle",
        autoRoiEvidence: "",
        autoRoiDiagnostics: {},
        autoRoiUserEdited: false,
        clipCheck: { status: "idle", rectKey: "", suggestedRect: null },
        labelCheck: { status: "idle", rectKey: "", suggestedRect: null },
        labelDraftRect: null,
        editTarget: "score",
        error: "",
      },
      exportConfig: Object.fromEntries(["rangeStart", "rangeEnd", "formats", "pageFillMode", "layoutHint", "measureReflow", "jobId", "runStatus", "documentHeader"].map(key => [key, exportConfig[key]])),
      review: reviewDraft(state),
    }));
  } catch (_) {
    // Storage failure must not prevent capture or destroy an in-memory draft.
  }
}

function reviewDraft(state) {
  const review = state.review;
  if (!review.pages.length) {
    // nothing loaded yet: keep a restored draft as it was
    return {
      jobId: review.restoredDraftKey?.jobId || "",
      revision: review.restoredDraftKey?.revision ?? null,
      selectedPaths: review.restoredSelectedPaths ?? null,
      systemOrder: review.restoredSystemOrder ?? null,
      applied: review.restoredApplied === true,
    };
  }
  const systems = review.pages.some(page => page.kind === "system");
  return {
    jobId: state.exportConfig.jobId || "",
    revision: Number.isFinite(review.jobRevision) ? review.jobRevision : null,
    selectedPaths: review.pages.filter(page => review.selectedPageIds.includes(page.id)).map(page => page.capturePath),
    // stable system ids (video order names) in the arranged order
    systemOrder: systems ? review.pages.map(page => page.systemId || page.capturePath) : null,
    applied: review.status === "applied",
  };
}
