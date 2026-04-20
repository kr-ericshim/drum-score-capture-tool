function resolveApiBase() {
  return String(window?.drumSheetAPI?.apiBase || "http://127.0.0.1:8000");
}

function resolveApiToken() {
  return String(window?.drumSheetAPI?.apiToken || "").trim();
}

function headers(extra = {}) {
  const merged = { ...extra };
  const token = resolveApiToken();
  if (token) {
    merged["X-DrumSheet-Token"] = token;
  }
  return merged;
}

function authorizedPath(pathname) {
  const url = new URL(String(pathname || ""), resolveApiBase());
  const token = resolveApiToken();
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}

async function readJson(response, fallbackMessage) {
  if (response.ok) {
    return response.json();
  }
  const error = await response.json().catch(() => ({ detail: fallbackMessage }));
  throw new Error(String(error?.detail || fallbackMessage));
}

export async function requestPreviewFrame({ filePath, startSec }) {
  const response = await fetch(`${resolveApiBase()}/preview/frame`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      source_type: "file",
      file_path: filePath,
      start_sec: Number.isFinite(startSec) ? startSec : null,
    }),
  });
  const data = await readJson(response, "미리보기를 불러오지 못했습니다.");
  return {
    imagePath: data.image_url ? authorizedPath(data.image_url) : data.image_path,
    sourcePath: data.image_path,
    diagnostics: Array.isArray(data.diagnostics) ? data.diagnostics : [],
  };
}

export async function requestPreviewRoiHealth({ sourceType = "file", filePath, youtubeUrl = "", startSec, roi }) {
  const response = await fetch(`${resolveApiBase()}/preview/roi-health`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      source_type: sourceType,
      file_path: filePath || null,
      youtube_url: youtubeUrl || null,
      start_sec: Number.isFinite(startSec) ? startSec : null,
      roi: Array.isArray(roi) ? roi : [],
    }),
  });
  const data = await readJson(response, "ROI 상태를 점검하지 못했습니다.");
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
  const response = await fetch(`${resolveApiBase()}/preview/source`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      source_type: sourceType,
      file_path: filePath || null,
      youtube_url: youtubeUrl || null,
    }),
  });
  const data = await readJson(response, "소스를 준비하지 못했습니다.");
  return {
    videoPath: data.video_path,
    videoUrl: data.video_url ? authorizedPath(data.video_url) : "",
    fromCache: Boolean(data.from_cache),
    logLines: Array.isArray(data.log_lines) ? data.log_lines : [],
  };
}

export async function createPreviewSourceJob({ youtubeUrl }) {
  const response = await fetch(`${resolveApiBase()}/preview/source-jobs`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      youtube_url: youtubeUrl || "",
    }),
  });
  const data = await readJson(response, "유튜브 준비 작업을 시작하지 못했습니다.");
  return String(data.job_id || "");
}

export async function getPreviewSourceJob(jobId) {
  const response = await fetch(`${resolveApiBase()}/preview/source-jobs/${jobId}`, {
    headers: headers(),
  });
  const data = await readJson(response, "유튜브 준비 상태를 불러오지 못했습니다.");
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
      videoUrl: result.video_url ? authorizedPath(result.video_url) : "",
      fromCache: Boolean(result.from_cache),
      videoTitle: String(result.video_title || ""),
      sourceKey: String(result.source_key || ""),
    },
  };
}

export async function getLocalMediaRegistry() {
  const response = await fetch(`${resolveApiBase()}/library/local-media`, {
    headers: headers(),
  });
  const data = await readJson(response, "로컬 미디어 목록을 불러오지 못했습니다.");
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
  const response = await fetch(`${resolveApiBase()}/library/archive`, {
    headers: headers(),
  });
  const data = await readJson(response, "보관함을 불러오지 못했습니다.");
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
  const response = await fetch(`${resolveApiBase()}/jobs`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await readJson(response, "작업 생성에 실패했습니다.");
  return data.job_id;
}

export async function getJob(jobId) {
  const response = await fetch(`${resolveApiBase()}/jobs/${jobId}`, {
    headers: headers(),
  });
  return readJson(response, "작업 조회에 실패했습니다.");
}

export async function reviewExport(jobId, { keepCaptures = [], keepImages = [], formats = [] } = {}) {
  const response = await fetch(`${resolveApiBase()}/jobs/${jobId}/review-export`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      keep_captures: keepCaptures,
      keep_images: keepImages,
      formats,
    }),
  });
  return readJson(response, "검토 반영에 실패했습니다.");
}
