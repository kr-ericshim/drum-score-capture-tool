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
    throw new Error("보호된 작업 파일을 불러오지 못했습니다.");
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
  throw new Error(String(error?.detail || fallbackMessage));
}

async function requestApiJson(pathname, options = {}, fallbackMessage) {
  const bridgeRequest = window?.drumSheetAPI?.requestJson;
  if (typeof bridgeRequest === "function") {
    const result = await bridgeRequest(pathname, {
      method: options.method || "GET",
      body: options.body,
    });
    if (result?.ok) {
      return result.data;
    }
    throw new Error(String(result?.data?.detail || fallbackMessage));
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
  }, "미리보기를 불러오지 못했습니다.");
  return {
    imagePath: data.image_url ? await protectedImageUrl(data.image_url) : data.image_path,
    sourcePath: data.image_path,
    diagnostics: Array.isArray(data.diagnostics) ? data.diagnostics : [],
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
  }, "악보 영역 상태를 점검하지 못했습니다.");
  return {
    riskLevel: String(data.risk_level || "info"),
    summary: String(data.summary || ""),
    diagnostics: Array.isArray(data.diagnostics) ? data.diagnostics : [],
    sampledFrames: Number(data.sampled_frames || 0),
    checkedSeconds: Array.isArray(data.checked_seconds) ? data.checked_seconds : [],
    metrics: data.metrics && typeof data.metrics === "object" ? data.metrics : {},
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
  }, "소스를 준비하지 못했습니다.");
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
  }, "유튜브 준비 작업을 시작하지 못했습니다.");
  return String(data.job_id || "");
}

export async function getPreviewSourceJob(jobId) {
  const data = await requestApiJson(`/preview/source-jobs/${jobId}`, {}, "유튜브 준비 상태를 불러오지 못했습니다.");
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
  const data = await requestApiJson("/library/local-media", {}, "로컬 미디어 목록을 불러오지 못했습니다.");
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
  const data = await requestApiJson("/library/archive", {}, "보관함을 불러오지 못했습니다.");
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
  const data = await requestApiJson("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, "작업 생성에 실패했습니다.");
  return data.job_id;
}

export async function getJob(jobId) {
  return requestApiJson(`/jobs/${jobId}`, {}, "작업 조회에 실패했습니다.");
}

export async function reviewExport(jobId, { keepCaptures = [], keepImages = [], formats = [] } = {}) {
  return requestApiJson(`/jobs/${jobId}/review-export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      keep_captures: keepCaptures,
      keep_images: keepImages,
      formats,
    }),
  }, "검토 반영에 실패했습니다.");
}
