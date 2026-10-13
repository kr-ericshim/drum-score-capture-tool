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

function fileTitleFromName(fileName = "") {
  const baseName = String(fileName || "").trim();
  if (!baseName) {
    return "";
  }
  if (baseName.startsWith(".") && !baseName.slice(1).includes(".")) {
    return baseName;
  }
  return baseName.replace(/\.[^.]+$/, "");
}

function fileTitleFromPath(filePath = "") {
  return fileTitleFromName(fileBaseName(filePath));
}

function padDatePart(value) {
  return String(value).padStart(2, "0");
}

function formatDocumentDate(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return formatDocumentDate(new Date());
  }
  return `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}`;
}

function hasOwnValue(target, key) {
  return Boolean(target) && Object.prototype.hasOwnProperty.call(target, key);
}

function normalizeUnicodeText(value) {
  return String(value ?? "").normalize("NFC");
}

function normalizeOptionalText(value) {
  return normalizeUnicodeText(value).trim();
}

function cleanDocumentTitle(value) {
  let title = normalizeOptionalText(value);
  if (!title) {
    return "";
  }
  title = title
    .replace(/^\s*\[[^\]]+\]\s*/u, "")
    .replace(/\s*[|｜]\s*[^|｜]+$/u, "")
    .replace(/\s*[（(][^()（）]*(?:★|☆)[^()（）]*[)）]\s*/gu, " ")
    .replace(/\b(?:score\s*book|sheet\s*lessons?|tutorial|drum\s*cover)\b/giu, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
  return title || normalizeOptionalText(value);
}

function compareableHeaderValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return normalizeUnicodeText(value);
}

function normalizeBpmValue(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const text = String(value).trim();
  if (!text) {
    return null;
  }
  const parsed = Number.parseInt(text, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export function createDocumentHeaderState(sourceFilePath = "", today = new Date(), sourceDisplayName = "") {
  const displayTitle = cleanDocumentTitle(sourceDisplayName);
  return {
    title: displayTitle || fileTitleFromPath(sourceFilePath),
    performer: "",
    bpm: null,
    date: formatDocumentDate(today),
    memo: "",
  };
}

export function normalizeDocumentHeader(documentHeader = {}, fallbackHeader = createDocumentHeaderState()) {
  const fallback = {
    title: normalizeOptionalText(fallbackHeader.title),
    performer: normalizeOptionalText(fallbackHeader.performer),
    bpm: normalizeBpmValue(fallbackHeader.bpm),
    date: normalizeOptionalText(fallbackHeader.date),
    memo: normalizeOptionalText(fallbackHeader.memo),
  };
  const normalizedTitle = hasOwnValue(documentHeader, "title")
    ? normalizeOptionalText(documentHeader.title)
    : fallback.title;

  return {
    title: normalizedTitle || fallback.title,
    performer: hasOwnValue(documentHeader, "performer")
      ? normalizeOptionalText(documentHeader.performer)
      : fallback.performer,
    bpm: hasOwnValue(documentHeader, "bpm")
      ? normalizeBpmValue(documentHeader.bpm)
      : fallback.bpm,
    date: hasOwnValue(documentHeader, "date")
      ? normalizeOptionalText(documentHeader.date)
      : fallback.date,
    memo: hasOwnValue(documentHeader, "memo")
      ? normalizeOptionalText(documentHeader.memo)
      : fallback.memo,
  };
}

export function sanitizeDocumentHeaderDraftField(field, value) {
  if (field === "bpm") {
    return String(value ?? "").replace(/\D/g, "");
  }
  return normalizeUnicodeText(value);
}

export function isPdfSelected(formats = []) {
  return Array.isArray(formats) && formats.includes("pdf");
}

export function isExportMetadataDirty(draft = {}, confirmed = {}) {
  return compareableHeaderValue(draft.title) !== compareableHeaderValue(confirmed.title)
    || compareableHeaderValue(draft.performer) !== compareableHeaderValue(confirmed.performer)
    || compareableHeaderValue(draft.bpm) !== compareableHeaderValue(confirmed.bpm)
    || compareableHeaderValue(draft.date) !== compareableHeaderValue(confirmed.date)
    || compareableHeaderValue(draft.memo) !== compareableHeaderValue(confirmed.memo);
}

export function validateExportMetadataDraft(draft = {}, locale = "en") {
  const title = normalizeOptionalText(draft.title);
  const bpm = compareableHeaderValue(draft.bpm).trim();
  return {
    title: title ? "" : t("export.metadata.validation.titleRequired", { locale }),
    bpm: !bpm || /^\d+$/.test(bpm) ? "" : t("export.metadata.validation.bpmDigits", { locale }),
  };
}

export function createExportMetadataModalState(
  sourceFilePath = "",
  today = new Date(),
  documentHeader = createDocumentHeaderState(sourceFilePath, today),
  sourceDisplayName = "",
) {
  const fallbackHeader = createDocumentHeaderState(sourceFilePath, today, sourceDisplayName);
  const confirmed = normalizeDocumentHeader(documentHeader, fallbackHeader);
  return {
    isOpen: false,
    draft: {
      ...confirmed,
    },
    dirty: false,
    validation: {
      title: "",
      bpm: "",
    },
    showDiscardConfirm: false,
  };
}

export function createInitialExportConfig(sourceFilePath = "", today = new Date(), sourceDisplayName = "") {
  const documentHeader = createDocumentHeaderState(sourceFilePath, today, sourceDisplayName);
  return {
    formats: DEFAULT_FORMATS.slice(),
    rangeStart: "",
    rangeEnd: "",
    outputDir: "",
    pageFillMode: "performance",
    layoutHint: "auto",
    // Score layout: rearrange by measure (on by default) or keep the video's lines.
    measureReflow: true,
    jobId: "",
    runStatus: "idle",
    progress: 0,
    currentStep: "",
    message: "",
    pdfPath: "",
    error: "",
    // the job's error code (e.g. LAYOUT_CONFLICT, which review export can still resolve)
    errorCode: "",
    documentHeader,
    metadataModal: createExportMetadataModalState(sourceFilePath, today, documentHeader, sourceDisplayName),
  };
}

function normalizedPrepareProgress(value) {
  const progress = Number(value || 0);
  if (!Number.isFinite(progress)) {
    return 0;
  }
  return Math.max(0, Math.min(1, progress));
}

function preparePercentLabel(progress) {
  return `${Math.round(normalizedPrepareProgress(progress) * 100)}%`;
}

function roundToHalfSecond(value) {
  return Math.round(Number(value || 0) * 2) / 2;
}

function clampFrameSecond(value, durationSec) {
  if (!Number.isFinite(durationSec) || durationSec <= 0) {
    return roundToHalfSecond(value);
  }
  return Math.max(0, Math.min(roundToHalfSecond(value), roundToHalfSecond(durationSec)));
}

export function buildRepresentativeFrameCandidates(durationSec) {
  const duration = Number(durationSec || 0);
  const defaultCandidates = [0, 5, 10];
  const rawTimes = Number.isFinite(duration) && duration > 0
    ? duration <= 12
      ? [0, duration * 0.45, Math.max(duration * 0.85, duration - 0.5)]
      : [duration * 0.2, duration * 0.33, duration * 0.5]
    : defaultCandidates;
  const maxDuration = Number.isFinite(duration) && duration > 0 ? duration : null;
  const normalizedTimes = [];
  rawTimes.forEach((value, index) => {
    let nextValue = clampFrameSecond(value, maxDuration);
    if (index > 0 && nextValue <= normalizedTimes[index - 1]) {
      nextValue = clampFrameSecond(normalizedTimes[index - 1] + 0.5, maxDuration);
    }
    normalizedTimes.push(nextValue);
  });

  return normalizedTimes.map((sec, index) => ({
    id: `preview-candidate-${index + 1}`,
    sec,
    label: formatSecondsLabel(sec),
    tone: index === 1 ? "recommended" : "alternate",
  }));
}

function isPrepareActive(source = {}) {
  return source.prepareStatus === "loading";
}

export function getSourcePrepareSummary(state, locale = state?.ui?.locale || "en") {
  const source = state?.source || {};
  if (!isPrepareActive(source)) {
    return "";
  }
  const stage = String(source.prepareStage || "queued");
  const stageLabel = t(`source.prepareStage.${stage}`, { locale });
  if (source.prepareProgressMode === "determinate") {
    return t("source.prepareStageProgress", {
      locale,
      replacements: {
        stage: stageLabel,
        percent: preparePercentLabel(source.prepareProgress),
      },
    });
  }
  return stageLabel;
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
      archiveSourceKind: "",
      archiveSourceKey: "",
      archiveDisplayName: "",
      metadata: null,
      status: "idle",
      error: "",
      youtubeUrl: "",
      preparedFromYouTube: false,
      prepareStatus: "idle",
      prepareJobId: "",
      prepareStage: "",
      prepareProgress: 0,
      prepareProgressMode: "indeterminate",
      prepareMessage: "",
      prepareFromCache: false,
      prepareLogs: [],
      preparedVideoPath: "",
      prepareErrorDetail: "",
      registryItems: [],
    },
    roi: {
      frameTime: null,
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
      // Whole-video check of the applied region (backend ENVELOPE_CLIPPED).
      // status: idle | loading | clipped | clear | error; rectKey ties the
      // result to the applied rect it was computed for.
      clipCheck: { status: "idle", rectKey: "", suggestedRect: null },
      draftRect: null,
      appliedRect: null,
      // Optional section-label area outside the score region (clean reflow). The
      // backend suggestion is only loaded as a draft; the user applies it.
      labelCheck: { status: "idle", rectKey: "", suggestedRect: null },
      labelDraftRect: null,
      labelAppliedRect: null,
      editTarget: "score",
      imageWidth: 0,
      imageHeight: 0,
      status: "idle",
      error: "",
    },
    exportConfig: createInitialExportConfig(),
    review: {
      pages: [],
      selectedPageIds: [],
      focusedPageId: "",
      status: "idle",
      error: "",
      keptCount: 0,
      outputDir: "",
      pdfPath: "",
      compare: false,
      // Clean reflow jobs: composed A4 previews of the last build, and whether the
      // viewer shows them instead of the focused system.
      outputPages: [],
      pagePreview: false,
      // Clean reflow job facts the review screen reports (deriveReflowInfo).
      reflow: null,
      // Original screens fallback: { active, screensDir, available } (deriveOriginalScreens).
      originalScreens: { active: false, screensDir: "", available: false },
      // A running background rebuild: { jobId, taskId, state, stage, progress, cancelRequested }.
      exportTask: null,
      // Ledger hypotheses of the last delivered export that need a look (LEDGER_2D_INTERFACE §10).
      hypotheses: createReviewHypothesesState(),
    },
    archive: {
      isOpen: false,
      status: "idle",
      items: [],
      error: "",
      selectedSourceKey: "",
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
  const aspect = width / height;
  if (aspect >= 2.25) {
    return "bottom_bar";
  }
  if (aspect <= 1.05) {
    return "page_turn";
  }
  return "full_scroll";
}

function hasPendingRoiDraft(state) {
  if (!isRectValid(state?.roi?.draftRect)) {
    return false;
  }
  if (!isRectValid(state?.roi?.appliedRect)) {
    return true;
  }
  return JSON.stringify(state.roi.draftRect) !== JSON.stringify(state.roi.appliedRect);
}

export function getStepState(state, step) {
  const locale = state.ui.locale || "en";
  const sourceReady = Boolean(state.source.filePath);
  const roiDirty = hasPendingRoiDraft(state);
  const roiReady = sourceReady && Number.isFinite(state.roi.frameTime) && isRectValid(state.roi.appliedRect) && !roiDirty;
  const exportReady = Boolean(state.exportConfig.jobId) && state.exportConfig.runStatus === "done" && state.review.pages.length > 0;
  const reviewReady = isReviewableRun(state) && state.review.pages.length > 0;

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
        blockingReason: !sourceReady
          ? t("selector.blocking.sourceRequired", { locale })
          : roiDirty
            ? t("selector.blocking.roiDirty", { locale })
            : "",
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
        // a pending layout conflict opens review but has no chart yet
        complete: reviewReady && state.exportConfig.runStatus === "done",
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

/**
 * A clean reflow job stopped at a layout conflict (status error, error code LAYOUT_CONFLICT,
 * reflow state "layout_conflict"): no chart files yet, but review export may still resolve it by
 * leaving a system out or choosing a staff size (STRATEGY Step 2A).
 */
export function isLayoutConflictPending(state) {
  return state?.exportConfig?.runStatus === "error"
    && String(state.exportConfig.errorCode || "") === "LAYOUT_CONFLICT"
    && state?.review?.reflow?.state === "layout_conflict";
}

export function isLedgerFailurePending(state) {
  return state?.exportConfig?.runStatus === "error"
    && String(state.exportConfig.errorCode || "") === "LEDGER_VERIFICATION_FAILED"
    && state?.review?.reflow?.state === "ledger_failed";
}

/** The current job can be reviewed and exported again: done, layout conflict, or ledger failure. */
export function isReviewableRun(state) {
  return state?.exportConfig?.runStatus === "done" || isLayoutConflictPending(state) || isLedgerFailurePending(state);
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
        : isPdfSelected(state.exportConfig.formats)
          ? t("selector.primary.runExportPdf", { locale })
          : t("selector.primary.runExportDirect", { locale }),
      disabled: !getStepState(state, "export").enabled || state.exportConfig.runStatus === "running" || !hasFormats,
    };
  }
  if (activeStep === "review") {
    const hasFormats = Array.isArray(state.exportConfig.formats) && state.exportConfig.formats.length > 0;
    const reviewLocked = !state.exportConfig.jobId
      || !isReviewableRun(state)
      || state.review.status === "running"
      || state.review.status === "applied"
      || !hasFormats
      || hasPendingRoiDraft(state);
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

function pathKey(value) {
  return String(value || "").trim().replace(/\\/g, "/");
}

function pathBaseName(value) {
  const key = pathKey(value);
  return key.slice(key.lastIndexOf("/") + 1);
}

function normalizeChangeBoxes(metrics = {}) {
  const size = Array.isArray(metrics?.frame_size) ? metrics.frame_size : [];
  const width = Number(size[0] || 0);
  const height = Number(size[1] || 0);
  const boxes = Array.isArray(metrics?.change_boxes) ? metrics.change_boxes : [];
  if (!(width > 0) || !(height > 0)) {
    return [];
  }
  return boxes
    .filter((box) => Array.isArray(box) && box.length === 4)
    .map(([x, y, w, h]) => ({
      left: Math.max(0, Math.min(1, Number(x) / width)),
      top: Math.max(0, Math.min(1, Number(y) / height)),
      width: Math.max(0, Math.min(1, Number(w) / width)),
      height: Math.max(0, Math.min(1, Number(h) / height)),
    }))
    .filter((box) => box.width > 0 && box.height > 0);
}

/**
 * Pairs the backend kept although the candidate looks almost identical to the
 * previous kept frame (few note heads changed, or the playhead jumped back).
 * Returns a map keyed by the candidate capture path.
 */
function buildSimilarPairIndex(result = {}) {
  const pairs = Array.isArray(result.similar_capture_pairs) ? result.similar_capture_pairs : [];
  const byPath = new Map();
  const byName = new Map();
  for (const pair of pairs) {
    const candidate = pathKey(pair?.candidate);
    if (!candidate) continue;
    const size = Array.isArray(pair?.metrics?.frame_size) ? pair.metrics.frame_size : [];
    const frameAspect = Number(size[0]) > 0 && Number(size[1]) > 0 ? Number(size[0]) / Number(size[1]) : 0;
    const entry = {
      referencePath: pathKey(pair?.kept),
      reason: String(pair?.reason || pair?.metrics?.reason || "").trim() || "small_change",
      changeBoxes: normalizeChangeBoxes(pair?.metrics),
      frameAspect,
      metrics: pair?.metrics || {},
    };
    byPath.set(candidate, entry);
    byName.set(pathBaseName(candidate), entry);
  }
  return {
    lookup(capturePath) {
      return byPath.get(pathKey(capturePath)) || byName.get(pathBaseName(capturePath)) || null;
    },
  };
}

function systemNumber(systemId, fallback) {
  const id = String(systemId || "");
  const alternate = id.match(/(\d+)-alt\d+$/);
  if (alternate) return Number(alternate[1]);
  const match = id.match(/(\d+)$/);
  return match ? Number(match[1]) : fallback;
}

/** "other moment" number of a minority-content alternate (``sys-005-alt2`` -> 2), else 0. */
function alternateNumber(systemId) {
  const match = String(systemId || "").match(/-alt(\d+)$/);
  return match ? Number(match[1]) : 0;
}

function formatClockLabel(value) {
  const sec = Math.max(0, Math.floor(Number(value) || 0));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

/** The review screen's hypothesis view: closed and not loaded. */
export function createReviewHypothesesState() {
  return { open: false, jobId: "", revision: -1, status: "idle", items: [], counts: null, total: 0, ledgerStatus: "", error: "" };
}

// Review codes shown to users. A code is added only after a spot check finds its items real and
// actionable; every other code stays in the developer report (export/review_hypotheses.json).
export const APP_REVIEW_CODES = Object.freeze([]);

// The small ledger summary a reflow job result carries (counts only, no crops). The toolbar count
// covers only the codes the app shows.
export function deriveLedgerSummary(summary, shownCodes = APP_REVIEW_CODES) {
  if (!summary || typeof summary !== "object") return null;
  const byCode = summary.issue_counts && typeof summary.issue_counts === "object" ? summary.issue_counts : {};
  const shown = shownCodes.reduce((total, code) => total + Math.max(0, Number(byCode[code]) || 0), 0);
  return { status: String(summary.status || ""), reviewHypotheses: shown };
}

/** Output models whose A4 pages the review screen previews (clean chart, original screens). */
const PAGED_OUTPUT_MODELS = new Set(["clean_reflow_v1", "original_screens_v1"]);

export function deriveOutputPages(result = {}) {
  if (!PAGED_OUTPUT_MODELS.has(result.output_model)) return [];
  const previews = Array.isArray(result.preview_images) ? result.preview_images : [];
  // a rebuild rewrites the same file names: the revision keeps the browser from showing the old pages
  const revision = Number(result.reflow?.revision ?? result.revision);
  const version = Number.isFinite(revision) && revision > 0 ? `?r=${revision}` : "";
  return previews.map((path, index) => ({ index: index + 1, path: `${normalizeAssetPath(path)}${version}` }));
}

function finiteOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/**
 * Clean reflow facts for the review screen: excluded/hidden short displays,
 * "looks similar" suggestion state, a layout conflict and the document staff size.
 * Returns null for jobs that are not clean reflow jobs.
 */
export function deriveReflowInfo(result = {}) {
  if (result.output_model !== "clean_reflow_v1") return null;
  const reflow = result.reflow && typeof result.reflow === "object" ? result.reflow : {};
  const systems = Array.isArray(reflow.systems) ? reflow.systems : [];
  const exclusions = reflow.exclusions && typeof reflow.exclusions === "object" ? reflow.exclusions : {};
  const conflict = reflow.layout_conflict && typeof reflow.layout_conflict === "object" ? reflow.layout_conflict : null;
  const conflictIds = conflict && Array.isArray(conflict.conflicts) ? conflict.conflicts.map(item => String(item?.system_id || "")) : [];
  const staffGapMm = finiteOrNull(reflow.staff_gap_mm);
  const defaultMm = finiteOrNull(reflow.staff_gap_mm_default) ?? 1.5;
  const labels = reflow.labels && typeof reflow.labels === "object" ? reflow.labels : {};
  return {
    revision: Number(reflow.revision || 0),
    state: String(result.reflow_state || ""),
    suggestionsState: String(reflow.suggestions_state || "done"),
    listedShort: Array.isArray(exclusions.short_listed_excluded) ? exclusions.short_listed_excluded.length : 0,
    // systems whose strip leaves out marks shown only for a moment (an "other moment" alternate shows them)
    minorityLines: systems.filter(system => Array.isArray(system?.issues) && system.issues.includes("MINORITY_CONTENT_DROPPED")).length,
    hiddenShort: Number(exclusions.hidden || 0),
    conflict: conflict ? {
      systemNumbers: conflictIds.map((id, index) => systemNumber(id, index + 1)),
      requestedMm: finiteOrNull(conflict.requested_staff_gap_mm),
      offeredMm: finiteOrNull(conflict.largest_fitting_staff_gap_mm),
      // why the automatic size did not resolve it (plan.staff_size.reason): BELOW_AUTO_MINIMUM,
      // NO_FITTING_SIZE, AUTO_OFF (a size the user chose), or "" when not recorded
      ...conflictSizeFacts(reflow.page_plan),
    } : null,
    // no chart files yet: the job stopped at this conflict and waits for review export
    conflictPending: String(result.reflow_state || "") === "layout_conflict",
    // a jump-view interval stayed unresolved: the chart is labelled incomplete with its time ranges
    ...deriveCoverage(result),
    ...deriveReviewRequired(result, reflow, systems),
    staffGapMm,
    defaultStaffGapMm: defaultMm,
    smallerStaff: staffGapMm !== null && staffGapMm < defaultMm - 1e-6,
    // the delivered-file check: status and how many hypotheses need a look (null before it ran)
    ledger: deriveLedgerSummary(reflow.ledger_summary),
    labelsOutsideRoi: String(labels.status || "") === "LABELS_OUTSIDE_ROI",
    labelsPlaced: Number(labels.placed || 0),
    systemCount: systems.length,
    // which layout produced the current files (null for files made before it was recorded)
    measureReflow: deriveMeasureReflow(result.measure_reflow),
    // a dense chart laid out by measure at a smaller staff size than chosen (null otherwise)
    autoStaff: deriveAutoStaff(result.measure_reflow),
    // one entry per printed line: where it sits on its page, which part of the video it came
    // from and the view-jump seams inside it (reflow.line_review; empty for older jobs)
    lines: deriveLineReview(reflow.line_review),
    // seams the user marked wrong, kept unverified by the last rebuild (reflow.rejected_seam_ids)
    rejectedSeamIds: Array.isArray(reflow.rejected_seam_ids) ? reflow.rejected_seam_ids.map(String).filter(Boolean) : [],
    sourceVideoPath: String(result.source_video_path || ""),
  };
}

const LINE_SEAM_STATUSES = new Set(["verified", "resolved", "unverified"]);

/** Printed lines for the line-by-line check; malformed entries are dropped. */
export function deriveLineReview(raw) {
  if (!Array.isArray(raw)) return [];
  const finite = value => (Number.isFinite(Number(value)) ? Number(value) : null);
  return raw.flatMap((line, index) => {
    const rect = Array.isArray(line?.rect) ? line.rect.map(Number) : [];
    const size = Array.isArray(line?.page_size) ? line.page_size.map(Number) : [];
    const page = Math.trunc(Number(line?.page));
    if (rect.length !== 4 || size.length !== 2 || !rect.every(Number.isFinite) || !(size[0] > 0 && size[1] > 0)
      || !(rect[2] > 0 && rect[3] > 0) || !(page >= 1)) return [];
    const sources = (Array.isArray(line.sources) ? line.sources : [])
      .map(source => ({ systemId: String(source?.system_id || ""), display: source?.display ? String(source.display) : "",
        tStart: finite(source?.t_start), tEnd: finite(source?.t_end) }))
      .filter(source => source.tStart !== null && source.tEnd !== null && source.tEnd >= source.tStart);
    const seams = (Array.isArray(line.seams) ? line.seams : [])
      .filter(seam => LINE_SEAM_STATUSES.has(String(seam?.status)))
      .map(seam => ({ id: String(seam.id || ""), status: String(seam.status), lowInk: Boolean(seam.low_ink),
        xFrac: Math.min(1, Math.max(0, finite(seam.x_frac) ?? 0)),
        // the user said this join was wrong and a rebuild kept both views
        userRejected: seam.user_rejected === true,
        // a rejected seam now ends one printed line ("end") and starts the next ("start")
        boundary: ["start", "end"].includes(seam.boundary) ? seam.boundary : "" }));
    const attention = ["seam_inferred", "seam_unverified"].includes(line.attention) ? line.attention : "";
    return [{ id: String(line.line_id || `line-${index + 1}`), page, rect, pageSize: size,
      measures: finite(line.measures), sources, seams, attention }];
  });
}

function deriveReviewRequired(result, reflow, systems) {
  const flags = ["SOURCE_CLIPPED", "UNCERTAIN_MARK_KEPT", "TRANSLUCENT_PLATE_GRAY"];
  const codes = systems.filter(system => system?.included !== false)
    .flatMap(system => (Array.isArray(system?.issues) ? system.issues : []).filter(code => flags.includes(code)));
  const raw = [...(Array.isArray(result.review_reasons) ? result.review_reasons : []),
    ...(Array.isArray(reflow.review_reasons) ? reflow.review_reasons : []), ...codes];
  const reasons = raw.map(reason => typeof reason === "string" ? { code: reason, text: reason }
    : { code: String(reason?.code || reason?.kind || reason?.reason || ""), text: String(reason?.text || reason?.message || reason?.detail || "") });
  const seen = new Set();
  return {
    reviewRequired: Boolean(result.review_required || reflow.review_required || ["review_required", "ledger_failed"].includes(result.reflow_state) || codes.length),
    reviewReasons: reasons.filter(reason => {
      const key = reason.code ? `code:${reason.code}` : reason.text ? `text:${reason.text}` : "";
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    }),
  };
}

function conflictSizeFacts(plan) {
  const size = plan && typeof plan === "object" && plan.staff_size && typeof plan.staff_size === "object" ? plan.staff_size : {};
  return {
    sizeReason: String(size.reason || "").slice(0, 64),
    autoMinMm: finiteOrNull(size.auto_min_staff_gap_mm) ?? 1.2,
  };
}

/** Unresolved ranges of an incomplete jump-view chart (result.coverage, or result.reflow.coverage). */
function deriveCoverage(result = {}) {
  const coverage = result.coverage && typeof result.coverage === "object" ? result.coverage
    : result.reflow?.coverage && typeof result.reflow.coverage === "object" ? result.reflow.coverage : null;
  const incomplete = String(result.reflow_state || "") === "incomplete" || coverage?.status === "incomplete";
  if (!incomplete) return { incomplete: false, unresolvedRanges: [] };
  const spans = Array.isArray(coverage?.unresolved) ? coverage.unresolved : [];
  const unresolvedRanges = spans.map((span) => {
    const start = finiteOrNull(Array.isArray(span) ? span[0] : span?.start);
    const end = finiteOrNull(Array.isArray(span) ? span[1] : span?.end);
    if (start === null || end === null) return null;
    return { start, end, label: `${formatClockLabel(start)}–${formatClockLabel(Math.ceil(end))}` };
  }).filter(Boolean);
  return { incomplete: true, unresolvedRanges };
}

/** plan.staff_size reasons for a score wider than the page (whole systems, or measure units without a safe cut). */
const WIDE_STAFF_REASONS = new Set(["WHOLE_SYSTEMS_DO_NOT_FIT", "UNITS_DO_NOT_FIT"]);

// A smaller staff size the planner chose by itself: a dense chart laid out by measure, or a score
// wider than the page (whole systems, or measure units without a safe cut).
function deriveAutoStaff(record) {
  const size = record && typeof record === "object" ? record.staff_size : null;
  if (!size || typeof size !== "object" || size.auto_reduced !== true) return null;
  const reason = String(size.reason || "");
  // any other automatic reduction of a measure layout is the dense-chart search (DENSE_LINES_NOT_FULL)
  const kind = WIDE_STAFF_REASONS.has(reason) ? "wide" : record.status === "measure_lines" ? "dense" : "";
  if (!kind) return null;
  const usedMm = finiteOrNull(size.staff_gap_mm);
  const requestedMm = finiteOrNull(size.staff_gap_mm_requested);
  if (usedMm === null || (requestedMm !== null && usedMm >= requestedMm - 1e-6)) return null;
  return { usedMm, requestedMm, reason, kind };
}

function deriveMeasureReflow(record) {
  if (!record || typeof record !== "object") return null;
  const status = String(record.status || "");
  if (!["measure_lines", "fallback_whole_systems", "off"].includes(status)) return null;
  return {
    status,
    applied: status === "measure_lines",
    fellBack: status === "fallback_whole_systems",
    reason: status === "fallback_whole_systems" ? String(record.reason || "").slice(0, 64) : "",
  };
}

/** Review revision a saved draft belongs to (reflow revision, else review-export revision). */
export function jobRevision(result = {}) {
  if (PAGED_OUTPUT_MODELS.has(result.output_model)) return Number(result.reflow?.revision || 0);
  return Number(result.review_export?.revision || 0);
}

/** Title for a reflow system at its current list position. */
export function systemTitle(index, locale = "en") {
  return t("selector.systemTitle", { locale, replacements: { index } });
}

export function needsAttention(page) {
  return Boolean(page?.suspicious || page?.autoExcludeCandidate || page?.similarTo);
}

/** At least this many short transition displays are shown as one collapsed group. */
export const FRAGMENT_GROUP_MIN = 2;

/**
 * The review list as shown: the filtered systems, with short transition displays
 * (clean reflow ``SHORT_DISPLAY``: page curls, fades, brief flashes) gathered into one
 * collapsible group when there are several. ``navigable`` is what ← → walk through:
 * the visible rows in screen order (group rows only while the group is open).
 */
export function reviewListPages(review = {}) {
  const pages = Array.isArray(review.pages) ? review.pages : [];
  const filtered = review.filter === "suspicious" ? pages.filter(needsAttention) : pages;
  const fragmentList = filtered.filter(page => page.transitionFragment);
  const alternateList = filtered.filter(page => page.minorityAlternate);
  const grouped = fragmentList.length >= FRAGMENT_GROUP_MIN;
  const alternatesGrouped = alternateList.length >= FRAGMENT_GROUP_MIN;
  const fragments = grouped ? fragmentList : [];
  const alternates = alternatesGrouped ? alternateList : [];
  const main = filtered.filter(page => !(grouped && page.transitionFragment) && !(alternatesGrouped && page.minorityAlternate));
  const expanded = grouped && Boolean(review.fragmentsExpanded);
  const alternatesExpanded = alternatesGrouped && Boolean(review.alternatesExpanded);
  return {
    main, fragments, grouped, expanded,
    // "other moments" of systems whose strip leaves out marks shown only briefly
    alternates, alternatesGrouped, alternatesExpanded,
    navigable: [...main, ...(alternatesExpanded ? alternates : []), ...(expanded ? fragments : [])],
  };
}

/**
 * Display title of a review page, from fields kept on the page so a locale switch can redo it.
 * A system keeps its name (video order number) when the list is rearranged.
 */
export function localizePageTitle(page = {}, locale = "en") {
  const index = Number(page.index) || 0;
  if (page.kind === "screen") return t("selector.screenTitle", { locale, replacements: { index } });
  if (page.kind !== "system") return t("selector.pageTitle", { locale, replacements: { index } });
  const titleNumber = systemNumber(page.systemId, index);
  const otherMoment = alternateNumber(page.systemId);
  return otherMoment
    ? t("selector.alternateTitle", { locale, replacements: { index: titleNumber, moment: otherMoment } })
    : t("selector.systemTitle", { locale, replacements: { index: titleNumber } });
}

/** The original-screens fallback works only for one-line videos (ORIGINAL_SCREENS_DESIGN.md §2). */
export const ORIGINAL_SCREENS_MIN_ASPECT = 2.25;

/** Width / height of the box around an ROI's points (0 when unknown). */
export function roiAspect(points) {
  if (!Array.isArray(points) || points.length !== 4) return 0;
  const xs = points.map(point => Number(point?.[0])), ys = points.map(point => Number(point?.[1]));
  if (![...xs, ...ys].every(Number.isFinite)) return 0;
  const height = Math.max(...ys) - Math.min(...ys);
  return height > 0 ? (Math.max(...xs) - Math.min(...xs)) / height : 0;
}

/**
 * Original screens facts for the review screen: ``active`` when the job's files are the original
 * screens (with the folder of the captured screens), ``available`` when a clean chart may be rebuilt
 * as original screens (a one-line video: the applied ROI is at least 2.25 times wider than tall).
 */
export function deriveOriginalScreens(result = {}, fallbackRoi = null) {
  const active = result.output_model === "original_screens_v1";
  const record = result.original_screens && typeof result.original_screens === "object" ? result.original_screens : {};
  const roi = Array.isArray(result.reflow?.applied_roi) ? result.reflow.applied_roi : fallbackRoi;
  return {
    active,
    screensDir: active ? String(record.screens_dir || "") : "",
    available: result.output_model === "clean_reflow_v1" && roiAspect(roi) >= ORIGINAL_SCREENS_MIN_ASPECT,
  };
}

/** Review rows of an original-screens result: every saved screen in time order, candidates flagged. */
function deriveOriginalScreenPages(result, locale) {
  const screens = Array.isArray(result.original_screens?.screens) ? result.original_screens.screens : [];
  return screens.filter(screen => screen && screen.path).map((screen, index) => {
    const reasons = Array.isArray(screen.reasons) ? screen.reasons.map(value => String(value || "").trim()).filter(Boolean) : [];
    const candidate = screen.candidate === true;
    const seconds = Number(screen.t);
    return {
      id: `${index + 1}`,
      index: index + 1,
      kind: "screen",
      systemId: "",
      timeLabel: Number.isFinite(seconds) ? formatClockLabel(seconds) : "",
      title: localizePageTitle({ kind: "screen", index: index + 1 }, locale),
      capturePath: String(screen.path),
      previewPath: normalizeAssetPath(String(screen.path)),
      cropRect: null,
      outputPreviewPath: normalizeAssetPath(String(screen.path)),
      previewKind: "capture",
      selectionMode: "captures",
      exportLocked: false,
      suspicious: candidate,
      warningReason: reasons[0] || "",
      diagnosticCodes: [],
      recommendedAction: candidate ? "exclude" : "keep",
      autoExcludeCandidate: candidate,
      transitionFragment: false,
      minorityAlternate: false,
      diagnostics: {},
      similarTo: null,
    };
  });
}

export function deriveCapturePages(result = {}, locale = "en") {
  if (result.output_model === "original_screens_v1") return deriveOriginalScreenPages(result, locale);
  const pageDiagnostics = Array.isArray(result.page_diagnostics) ? result.page_diagnostics : [];
  const similarPairs = buildSimilarPairIndex(result);
  const droppedPages = Array.isArray(result.dropped_pages) ? result.dropped_pages : [];
  const previewImages = Array.isArray(result.preview_images) ? result.preview_images : [];
  const reviewCandidates = Array.isArray(result.review_candidates) ? result.review_candidates : [];
  const finalImages = Array.isArray(result.images) ? result.images : [];
  const reviewSelectionMode = String(result.review_export?.selection_mode || "");
  // Clean reflow jobs: review items are the cleaned system strips in their current order.
  const isReflow = result.output_model === "clean_reflow_v1";
  let capturePaths = finalImages;
  let previewKind = "output";
  let selectionMode = "pages";
  if (Array.isArray(result.original_images) && result.original_images.length) {
    capturePaths = result.original_images;
  } else if (reviewSelectionMode === "pages" && finalImages.length) {
    capturePaths = finalImages;
    previewKind = "output";
    selectionMode = "pages";
  } else if (isReflow && reviewCandidates.length) {
    capturePaths = reviewCandidates;
    previewKind = "capture";
    selectionMode = "captures";
  } else if (reviewCandidates.length) {
    capturePaths = reviewCandidates;
    previewKind = "capture";
    selectionMode = "captures";
  } else if (Array.isArray(result.upscaled_frames) && result.upscaled_frames.length) {
    capturePaths = result.upscaled_frames;
    previewKind = "capture";
    selectionMode = "captures";
  } else if (Array.isArray(result.stitched_frames) && result.stitched_frames.length) {
    capturePaths = result.stitched_frames;
    previewKind = "capture";
    selectionMode = "captures";
  } else if (previewImages.length) {
    capturePaths = previewImages;
  }
  let alignedDiagnostics = pageDiagnostics.length === capturePaths.length ? pageDiagnostics : [];
  if (!alignedDiagnostics.length && droppedPages.length > 0) {
    const combinedDiagnostics = [...pageDiagnostics, ...droppedPages].sort((a, b) => {
      const aIndex = Number(a?.page_index || a?.pageIndex || 0);
      const bIndex = Number(b?.page_index || b?.pageIndex || 0);
      return aIndex - bIndex;
    });
    if (combinedDiagnostics.length === capturePaths.length) {
      alignedDiagnostics = combinedDiagnostics;
    }
  }

  const pages = capturePaths.map((capturePath, index) => {
    const diagnostic = result.capture_diagnostics?.[capturePath] || alignedDiagnostics[index] || {};
    const diagnosticCodes = Array.isArray(diagnostic?.diagnostic_codes)
      ? diagnostic.diagnostic_codes.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    const warningReasons = Array.isArray(diagnostic?.warning_reasons)
      ? diagnostic.warning_reasons.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    const warningReason = warningReasons[0]
      || String(diagnostic?.warning_reason || diagnostic?.warningReason || "").trim();
    const recommendedAction = String(diagnostic?.recommended_action || diagnostic?.recommendedAction || "").trim();
    const autoExcludeCandidate = recommendedAction === "exclude"
      || diagnosticCodes.includes("mostly_blank_page")
      || diagnosticCodes.includes("video_frame_content");
    const outputPreviewPath = isReflow ? capturePath : (previewImages[index] || finalImages[index] || capturePath);
    const startSec = Number(diagnostic?.t_start);
    return {
      id: `${index + 1}`,
      index: index + 1,
      kind: isReflow ? "system" : "capture",
      systemId: isReflow ? String(diagnostic?.system_id || "") : "",
      timeLabel: isReflow && Number.isFinite(startSec) ? formatClockLabel(startSec) : "",
      title: localizePageTitle({ kind: isReflow ? "system" : "capture", index: index + 1, systemId: diagnostic?.system_id }, locale),
      capturePath,
      previewPath: normalizeAssetPath(result.capture_edits?.[capturePath]?.image_path || capturePath),
      cropRect: result.capture_edits?.[capturePath]?.roi || null,
      outputPreviewPath: normalizeAssetPath(outputPreviewPath),
      previewKind,
      selectionMode,
      exportLocked: false,
      suspicious: Boolean(diagnostic?.suspicious),
      warningReason,
      diagnosticCodes,
      recommendedAction,
      autoExcludeCandidate,
      // a short display (flicker, page curl, brief flash) listed unchecked so it can be restored
      transitionFragment: isReflow && diagnosticCodes.includes("SHORT_DISPLAY"),
      // another moment of a system, showing marks its strip leaves out (listed unchecked)
      minorityAlternate: isReflow && diagnosticCodes.includes("MINORITY_ALTERNATE"),
      diagnostics: diagnostic,
      similarTo: null,
    };
  });

  for (const page of pages) {
    const pair = similarPairs.lookup(page.capturePath);
    if (!pair) continue;
    const reference = pages.find((other) => other !== page && (
      pathKey(other.capturePath) === pair.referencePath || pathBaseName(other.capturePath) === pathBaseName(pair.referencePath)
    ));
    page.similarTo = {
      referenceId: reference?.id || "",
      referenceIndex: reference?.index || 0,
      referencePath: pair.referencePath,
      // Reflow suggestions are appearance only ("looks similar"); older results said "repeat".
      reason: isReflow && ["repeat", "looks_similar"].includes(pair.reason) ? "looks_similar" : pair.reason,
      changeBoxes: pair.changeBoxes,
      changeCount: pair.changeBoxes.length,
      frameAspect: pair.frameAspect,
    };
  }
  return pages;
}

export function getTopBarSummary(state) {
  const locale = state.ui.locale || "en";
  const preparingLabel = getSourcePrepareSummary(state, locale);
  const sourceLabel = preparingLabel || state.source.displayName || fileBaseName(state.source.filePath) || t("selector.sourceFallback", { locale });
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
    const preparingLabel = getSourcePrepareSummary(state, locale);
    let summary = t("selector.summary.idle", { locale });
    if (step === "source" && preparingLabel) {
      summary = preparingLabel;
    } else if (step === "source" && state.source.displayName) {
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
          ? t(state.review.reflow?.reviewRequired ? "selector.summary.reviewRequired" : "selector.summary.exportDone", { locale })
          : stepState.enabled
            ? t("selector.summary.exportReady", { locale })
            : t("selector.summary.exportBlocked", { locale });
    } else if (step === "review") {
      summary = isLayoutConflictPending(state) && stepState.enabled
        ? t("selector.summary.reviewConflict", { locale })
        : isLedgerFailurePending(state) && stepState.enabled
          ? t("selector.summary.reviewLedgerFailed", { locale })
        : stepState.complete && state.review.reflow?.incomplete
          ? t("selector.summary.reviewIncomplete", { locale })
          : stepState.complete && state.review.reflow?.reviewRequired
            ? t("selector.summary.reviewRequired", { locale })
          : stepState.complete
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
