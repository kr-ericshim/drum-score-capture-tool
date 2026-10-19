import { errorDetailText } from "./i18n.js";
import { normalizeAssetPath } from "./paths.js";

function resolveApiBase() {
  return String(window?.drumSheetAPI?.apiBase || "http://127.0.0.1:8000");
}

function apiPath(pathname) {
  const url = new URL(String(pathname || ""), resolveApiBase());
  url.searchParams.delete("token");
  return url.toString();
}

function isJobsFilePath(pathname) {
  const url = new URL(String(pathname || ""), resolveApiBase());
  const base = new URL(resolveApiBase());
  return url.origin === base.origin && url.pathname.startsWith("/jobs-files/");
}

async function readProtectedJobAsset(pathname) {
  const bridgeReader = window?.drumSheetAPI?.readJobAsset;
  if (typeof bridgeReader === "function" && isJobsFilePath(pathname)) {
    return bridgeReader(pathname);
  }

  const response = await fetch(apiPath(pathname));
  if (!response.ok) {
    throw new Error("보호된 작업 파일을 불러오지 못했습니다. / Could not load the job file.");
  }
  return {
    bytes: await response.arrayBuffer(),
    contentType: String(response.headers.get("content-type") || ""),
  };
}

async function protectedImageUrl(pathname) {
  if (typeof Blob !== "function" || typeof globalThis.URL?.createObjectURL !== "function") {
    return apiPath(pathname);
  }
  const asset = await readProtectedJobAsset(pathname);
  const blob = new Blob([asset.bytes], asset.contentType ? { type: asset.contentType } : undefined);
  return globalThis.URL.createObjectURL(blob);
}

async function readJson(response, fallbackMessage) {
  if (response.ok) {
    return response.json();
  }
  const error = await response.json().catch(() => ({ detail: fallbackMessage }));
  throw Object.assign(new Error(errorDetailText(error?.detail) || fallbackMessage), { status: response.status });
}

async function requestApiJson(pathname, options = {}, fallbackMessage) {
  const bridgeRequest = window?.drumSheetAPI?.requestJson;
  if (typeof bridgeRequest === "function") {
    let result;
    try {
      result = await bridgeRequest(pathname, {
        method: options.method || "GET",
        body: options.body,
        ...(options.timeoutMs ? { timeoutMs: options.timeoutMs } : {}),
      });
    } catch (error) {
      // an error crossing the preload bridge may arrive as a plain object; keep its text readable
      throw error instanceof Error ? error : new Error(errorDetailText(error) || fallbackMessage);
    }
    if (result?.ok) {
      return result.data;
    }
    throw Object.assign(new Error(errorDetailText(result?.data?.detail) || fallbackMessage), { status: result?.status });
  }

  const response = await fetch(apiPath(pathname), {
    method: options.method || "GET",
    headers: options.headers,
    body: options.body,
  });
  return readJson(response, fallbackMessage);
}

export async function requestPreviewFrame({ filePath, startSec }) {
  const data = await requestApiJson("/preview/frame", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: "file",
      file_path: filePath,
      start_sec: Number.isFinite(startSec) ? startSec : null,
    }),
  }, "미리보기를 불러오지 못했습니다. / Could not load the preview.");
  return {
    imagePath: data.image_url ? await protectedImageUrl(data.image_url) : data.image_path,
    sourcePath: data.image_path,
    diagnostics: Array.isArray(data.diagnostics) ? data.diagnostics : [],
  };
}

export async function requestAutoRoi({ filePath, startSec }) {
  const data = await requestApiJson("/preview/auto-roi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: "file",
      file_path: filePath,
      youtube_url: null,
      start_sec: Number.isFinite(startSec) ? startSec : null,
    }),
  }, "악보 영역을 자동으로 찾지 못했습니다. / Could not find the score region automatically.");
  return {
    status: String(data.status || "not_found"),
    roi: Array.isArray(data.roi) ? data.roi : null,
    evidenceLevel: String(data.evidence_level || "low"),
    layoutHint: data.layout_hint ? String(data.layout_hint) : "",
    isDarkMode: Boolean(data.is_dark_mode),
    diagnostics: data.diagnostics && typeof data.diagnostics === "object" ? data.diagnostics : {},
  };
}

export async function requestLabelRegion({ filePath, roi, startSec = null, endSec = null }) {
  const data = await requestApiJson("/preview/label-region", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_path: filePath,
      roi,
      ...(Number.isFinite(startSec) ? { start_sec: startSec } : {}),
      ...(Number.isFinite(endSec) ? { end_sec: endSec } : {}),
    }),
  }, "구간 표시 영역을 확인하지 못했습니다. / Could not check the section-label area.");
  return {
    status: String(data?.status || "not_found"),
    labelRoi: Array.isArray(data?.label_roi) ? data.label_roi : null,
    evidence: data?.evidence && typeof data.evidence === "object" ? data.evidence : {},
  };
}

export async function requestPreviewRoiHealth({ sourceType = "file", filePath, youtubeUrl = "", startSec, roi }) {
  const data = await requestApiJson("/preview/roi-health", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: sourceType,
      file_path: filePath || null,
      youtube_url: youtubeUrl || null,
      start_sec: Number.isFinite(startSec) ? startSec : null,
      roi: Array.isArray(roi) ? roi : [],
    }),
  }, "악보 영역 상태를 점검하지 못했습니다. / Could not check the score region.");
  return {
    riskLevel: String(data.risk_level || "info"),
    summary: String(data.summary || ""),
    diagnostics: Array.isArray(data.diagnostics) ? data.diagnostics : [],
    sampledFrames: Number(data.sampled_frames || 0),
    checkedSeconds: Array.isArray(data.checked_seconds) ? data.checked_seconds : [],
    metrics: data.metrics && typeof data.metrics === "object" ? data.metrics : {},
    envelope: normalizeEnvelopeCheck(data.envelope),
  };
}

function normalizeEnvelopeCheck(envelope) {
  const value = envelope && typeof envelope === "object" ? envelope : {};
  return {
    status: String(value.status || "unavailable"),
    clipped: Boolean(value.clipped),
    suggestedRoi: Array.isArray(value.suggested_roi) ? value.suggested_roi : null,
    counts: value.counts && typeof value.counts === "object" ? value.counts : {},
    framesWithClipping: Array.isArray(value.frames_with_clipping) ? value.frames_with_clipping : [],
  };
}

export async function preparePreviewSource({ sourceType, filePath, youtubeUrl }) {
  const data = await requestApiJson("/preview/source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: sourceType,
      file_path: filePath || null,
      youtube_url: youtubeUrl || null,
    }),
  }, "소스를 준비하지 못했습니다. / Could not prepare the video.");
  return {
    videoPath: data.video_path,
    videoUrl: data.video_url ? apiPath(data.video_url) : "",
    fromCache: Boolean(data.from_cache),
    logLines: Array.isArray(data.log_lines) ? data.log_lines : [],
  };
}

export async function createPreviewSourceJob({ youtubeUrl }) {
  const data = await requestApiJson("/preview/source-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      youtube_url: youtubeUrl || "",
    }),
  }, "유튜브 준비 작업을 시작하지 못했습니다. / Could not start preparing the YouTube video.");
  return String(data.job_id || "");
}

export async function getPreviewSourceJob(jobId) {
  const data = await requestApiJson(`/preview/source-jobs/${jobId}`, {}, "유튜브 준비 상태를 불러오지 못했습니다. / Could not load the YouTube preparation status.");
  const result = data.result || {};
  return {
    jobId: String(data.job_id || jobId || ""),
    status: String(data.status || "queued"),
    stage: String(data.stage || ""),
    message: String(data.message || ""),
    progress: Number(data.progress || 0),
    progressMode: String(data.progress_mode || "indeterminate"),
    errorCode: data.error_code ? String(data.error_code) : "",
    logLines: Array.isArray(data.log_tail) ? data.log_tail : [],
    result: {
      videoPath: String(result.video_path || ""),
      videoUrl: result.video_url ? apiPath(result.video_url) : "",
      fromCache: Boolean(result.from_cache),
      videoTitle: String(result.video_title || ""),
      sourceKey: String(result.source_key || ""),
    },
  };
}

export async function getLocalMediaRegistry() {
  const data = await requestApiJson("/library/local-media", {}, "로컬 미디어 목록을 불러오지 못했습니다. / Could not load the recent videos.");
  return {
    items: Array.isArray(data.items)
      ? data.items.map((item) => ({
        filePath: String(item.source_path || ""),
        displayName: String(item.display_name || ""),
        directory: String(item.directory || ""),
        resolutionLabel: String(item.resolution_label || ""),
        durationLabel: String(item.duration_label || ""),
        width: Number(item.width || 0),
        height: Number(item.height || 0),
        durationSec: Number(item.duration_sec || 0),
        pdfPath: item.pdf_path ? String(item.pdf_path) : "",
        outputDir: item.output_dir ? String(item.output_dir) : "",
        hasScore: Boolean(item.has_score),
        sourceOrigin: String(item.source_origin || "job"),
        youtubeUrl: item.youtube_url ? String(item.youtube_url) : "",
        updatedAt: Number(item.updated_at || 0),
      }))
      : [],
  };
}

export async function getArchiveLibrary() {
  const data = await requestApiJson("/library/archive", {}, "보관함을 불러오지 못했습니다. / Could not load the archive.");
  return {
    items: Array.isArray(data.items)
      ? data.items.map((item) => ({
        sourceKey: String(item.source_key || ""),
        sourceKind: String(item.source_kind || "file"),
        displayName: String(item.display_name || ""),
        completedAt: Number(item.completed_at || 0),
        sourcePath: String(item.source_path || ""),
        pdfPath: String(item.pdf_path || ""),
        outputDir: item.output_dir ? String(item.output_dir) : "",
        youtubeUrl: item.youtube_url ? String(item.youtube_url) : "",
      }))
      : [],
  };
}

export async function createJob(payload) {
  const options = payload?.options;
  const body = options && Number.isFinite(options.staff_gap_mm) ? {
    ...payload, options: { ...options, staff_gap_mm_explicit: typeof options.staff_gap_mm_explicit === "boolean"
      ? options.staff_gap_mm_explicit : true },
  } : payload;
  const data = await requestApiJson("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, "작업 생성에 실패했습니다. / Could not create the job.");
  return data.job_id;
}

export async function getJob(jobId) {
  return requestApiJson(`/jobs/${jobId}`, {}, "작업 조회에 실패했습니다. / Could not read the job.");
}

export async function cancelJob(jobId) {
  return requestApiJson(`/jobs/${jobId}/cancel`, { method: "POST" }, "작업 취소에 실패했습니다. / Could not cancel the job.");
}

export async function cropCapture(jobId, capturePath, roi = []) {
  return requestApiJson(`/jobs/${jobId}/capture-crop`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ capture_path: capturePath, roi }),
  }, "캡처 자르기에 실패했습니다. / Could not crop the capture.");
}

const REVIEW_EXPORT_FAILED = "검토 반영에 실패했습니다. / Could not apply the review.";
const ACTIVE_EXPORT_STATES = new Set(["queued", "running"]);
/** Poll delays for a background review export: 500 ms, growing to 2 s. */
export const REVIEW_EXPORT_POLL_DELAYS_MS = [500, 500, 750, 1000, 1500, 2000];
const REVIEW_EXPORT_POLL_FAILURES = 5;

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** A background review export task as the backend reports it (POST/GET /jobs/{id}/review-export). */
export function normalizeReviewExportTask(data) {
  const value = data && typeof data === "object" ? data : {};
  return {
    taskId: String(value.task_id || ""),
    jobId: String(value.job_id || ""),
    revision: Number(value.revision || 0),
    state: String(value.state || ""),
    stage: String(value.stage || ""),
    progress: Math.max(0, Math.min(1, Number(value.progress || 0))),
    cancelRequested: Boolean(value.cancel_requested),
    result: value.result && typeof value.result === "object" ? value.result : null,
    errorCode: value.error_code ? String(value.error_code) : "",
    error: errorDetailText(value.error),
    errorStatus: Number(value.error_status || 0) || null,
  };
}

function exportTaskError(task) {
  if (task.state === "cancelled") {
    return Object.assign(new Error(task.error || "EXPORT_CANCELLED: the rebuild was cancelled"), { code: "EXPORT_CANCELLED", cancelled: true, task });
  }
  // the message keeps the backend's detail (e.g. "LAYOUT_CONFLICT: ...") so callers map it as before
  return Object.assign(new Error(task.error || task.errorCode || REVIEW_EXPORT_FAILED), {
    status: task.errorStatus || 500, code: task.errorCode || "EXPORT_FAILED", task,
  });
}

function reviewExportBody({ keepCaptures = [], keepImages = [], formats = [], systemOrder = [], staffGapMm = null, staffGapMmExplicit = null, measureReflow = null, rejectedSeamIds = null, baseRevision = null, outputModel = "", documentHeader = null } = {}) {
  // a new PDF title (and the rest of the document info) for this rebuild; omitted = the job's own
  const header = documentHeader ? { document_header: documentHeader } : {};
  if (outputModel === "original_screens_v1") {
    // Original screens: no selection captures from the video; a selection rebuilds from the saved
    // screens. Clean reflow fields (and empty selections) are never sent: the backend refuses them.
    return JSON.stringify({ output_model: outputModel, formats, ...(keepCaptures.length ? { keep_captures: keepCaptures } : {}), ...header });
  }
  return JSON.stringify({
    keep_captures: keepCaptures,
    keep_images: keepImages,
    formats,
    ...header,
    // Clean reflow jobs: every system in the arranged order (included and excluded).
    ...(systemOrder.length ? { system_order: systemOrder } : {}),
    // Clean reflow jobs: an explicit user choice of the document staff size (mm).
    ...(Number.isFinite(staffGapMm) ? { staff_gap_mm: staffGapMm } : {}),
    ...(typeof staffGapMmExplicit === "boolean" ? { staff_gap_mm_explicit: staffGapMmExplicit }
      : Number.isFinite(staffGapMm) ? { staff_gap_mm_explicit: true } : {}),
    // Clean reflow jobs: rearrange by measure (true) or keep whole lines (false); omitted = the job's option.
    ...(typeof measureReflow === "boolean" ? { measure_reflow: measureReflow } : {}),
    // Jump-view joins the user marked wrong (the full set; omitted = keep the last rebuild's), checked against the shown revision.
    ...(Array.isArray(rejectedSeamIds) ? { rejected_seam_ids: rejectedSeamIds, ...(Number.isFinite(baseRevision) ? { base_revision: baseRevision } : {}) } : {}),
  });
}

/**
 * Start a background review export. Answers at once with the task (202), or with the export itself
 * from a backend that still builds it inside the request (no task_id). A running export of the same
 * job is refused with an error whose code is EXPORT_IN_PROGRESS.
 */
export async function startReviewExport(jobId, options = {}) {
  try {
    return await requestApiJson(`/jobs/${jobId}/review-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: reviewExportBody(options),
    }, REVIEW_EXPORT_FAILED);
  } catch (error) {
    if (/^EXPORT_IN_PROGRESS\b/.test(String(error?.message || ""))) error.code = "EXPORT_IN_PROGRESS";
    throw error;
  }
}

/** The job's latest review export task, or null when it never had one. */
export async function getReviewExportTask(jobId, taskId = "") {
  const path = taskId ? `/jobs/${jobId}/review-export/${taskId}` : `/jobs/${jobId}/review-export`;
  try {
    return normalizeReviewExportTask(await requestApiJson(path, {}, REVIEW_EXPORT_FAILED));
  } catch (error) {
    if (error?.status === 404 && !taskId) return null;
    throw error;
  }
}

export async function cancelReviewExport(jobId, taskId) {
  return normalizeReviewExportTask(await requestApiJson(`/jobs/${jobId}/review-export/${taskId}/cancel`, { method: "POST" }, REVIEW_EXPORT_FAILED));
}

/**
 * Poll a review export task until it ends. Resolves with the export (images, pdf, output_dir,
 * kept_count, measure_reflow, revision); rejects with the backend's error (code, status) or with
 * code EXPORT_CANCELLED. ``onTask`` sees every snapshot; ``shouldStop`` ends the wait early
 * (code EXPORT_POLL_STOPPED). A few failed polls in a row are retried before giving up.
 */
export async function waitForReviewExport(jobId, task, { onTask = null, shouldStop = null, sleep = sleepMs, delays = REVIEW_EXPORT_POLL_DELAYS_MS } = {}) {
  let current = task;
  let polls = 0;
  let failures = 0;
  while (ACTIVE_EXPORT_STATES.has(current.state)) {
    await sleep(delays[Math.min(polls, delays.length - 1)]);
    polls += 1;
    if (typeof shouldStop === "function" && shouldStop()) {
      throw Object.assign(new Error("EXPORT_POLL_STOPPED"), { code: "EXPORT_POLL_STOPPED" });
    }
    try {
      current = await getReviewExportTask(jobId, current.taskId);
      failures = 0;
    } catch (error) {
      failures += 1;
      if (error?.status || failures >= REVIEW_EXPORT_POLL_FAILURES) throw error;
      continue;
    }
    if (typeof onTask === "function") onTask(current);
  }
  if (current.state === "done") return current.result || {};
  throw exportTaskError(current);
}

/** Start a review export and wait for it (see startReviewExport / waitForReviewExport). */
export async function reviewExport(jobId, options = {}, { onTask = null, shouldStop = null, sleep, delays } = {}) {
  const started = await startReviewExport(jobId, options);
  if (!started || typeof started !== "object" || !started.task_id) return started;  // the export itself
  const task = normalizeReviewExportTask(started);
  if (typeof onTask === "function") onTask(task);
  return waitForReviewExport(jobId, task, { onTask, shouldStop, ...(sleep ? { sleep } : {}), ...(delays ? { delays } : {}) });
}

const HYPOTHESIS_STATUSES = new Set(["fail", "review_required", "unresolved"]);
const count = value => Math.max(0, Number(value) || 0);
const finiteOrNull = value => (value === null || value === undefined || !Number.isFinite(Number(value)) ? null : Number(value));

/** One page of ledger hypotheses that did not end "pass" (LEDGER_2D_INTERFACE §10). */
export function normalizeReviewHypotheses(data = {}) {
  const counts = data?.counts && typeof data.counts === "object" ? data.counts : {};
  const excluded = counts.user_excluded && typeof counts.user_excluded === "object" ? counts.user_excluded : {};
  const items = Array.isArray(data?.hypotheses) ? data.hypotheses : [];
  return {
    status: String(data?.status || "unassessed"),
    exportRevision: finiteOrNull(data?.export_revision),
    counts: {
      hypotheses: count(counts.hypotheses), bundles: count(counts.bundles),
      boundariesSafe: count(counts.boundaries_safe), boundariesUnknown: count(counts.boundaries_unknown),
      pages: count(counts.pages), userExcludedItems: count(excluded.items),
      byCode: counts.by_code && typeof counts.by_code === "object" ? { ...counts.by_code } : {},
    },
    total: count(data?.total),
    offset: count(data?.offset),
    items: items.filter(item => item && typeof item === "object").map(item => ({
      id: String(item.id || ""),
      itemId: String(item.item_id || ""),
      displayId: String(item.display_id || ""),
      systemId: item.system_id ? String(item.system_id) : "",
      timestampSec: finiteOrNull(item.timestamp_sec),
      status: HYPOTHESIS_STATUSES.has(item.status) ? item.status : "review_required",
      code: String(item.code || ""),
      pageIndex: finiteOrNull(item.page_index),
      rawCrop: normalizeAssetPath(item.raw_crop || ""),
      primaryCrop: item.primary_crop ? normalizeAssetPath(item.primary_crop) : "",
    })),
  };
}

export async function getReviewHypotheses(jobId, { offset = 0, limit = 100, codes = null } = {}) {
  const query = new URLSearchParams({ offset: String(count(offset)), limit: String(count(limit) || 100) });
  if (Array.isArray(codes)) query.set("codes", codes.join(","));
  const data = await requestApiJson(`/jobs/${jobId}/review-hypotheses?${query}`, {}, "확인 항목을 불러오지 못했습니다. / Could not load the items to check.");
  return normalizeReviewHypotheses(data);
}

export async function getCacheUsage() {
  const data = await requestApiJson("/maintenance/cache-usage", {}, "저장 공간을 확인하지 못했습니다. / Could not check the storage usage.");
  return {
    totalPaths: Number(data.total_paths || 0),
    totalBytes: Number(data.total_bytes || 0),
    totalHuman: String(data.total_human || "0 B"),
  };
}

export async function clearCache() {
  const data = await requestApiJson("/maintenance/clear-cache", { method: "POST" }, "캐시를 비우지 못했습니다. / Could not clear the cache.");
  return {
    clearedPaths: Number(data.cleared_paths || 0),
    reclaimedBytes: Number(data.reclaimed_bytes || 0),
    reclaimedHuman: String(data.reclaimed_human || "0 B"),
    skippedPaths: Array.isArray(data.skipped_paths) ? data.skipped_paths.map(String) : [],
  };
}
