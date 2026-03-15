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

export async function reviewExport(jobId, keepCaptures, formats) {
  const response = await fetch(`${resolveApiBase()}/jobs/${jobId}/review-export`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      keep_captures: keepCaptures,
      formats,
    }),
  });
  return readJson(response, "검토 반영에 실패했습니다.");
}
