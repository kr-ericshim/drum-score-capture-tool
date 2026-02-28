import { el, parseJsonOrNull } from "./dom.js";
import { friendlyApiError } from "./messages.js";

export function sourceType() {
  const checked = document.querySelector('input[name="sourceType"]:checked');
  return checked ? checked.value : "file";
}

const DEFAULT_LAYOUT_HINT = "auto";
const LAYOUT_BOTTOM_BAR = "bottom_bar";
const LAYOUT_FULL_SCROLL = "full_scroll";

export function getFormats() {
  return Array.from(document.querySelectorAll(".format:checked")).map((node) => node.value);
}

function captureSensitivity() {
  const node = el("captureSensitivity");
  return node ? node.value : "medium";
}

function sensitivityConfig(level) {
  if (level === "low") {
    return { fps: 0.6, dedupe_level: "aggressive" };
  }
  if (level === "high") {
    return { fps: 1.8, dedupe_level: "sensitive" };
  }
  return { fps: 1.0, dedupe_level: "normal" };
}

function textValue(id, fallback = "") {
  const node = el(id);
  if (!node || typeof node.value !== "string") {
    return fallback;
  }
  return node.value;
}

function numberOrNull(id) {
  const raw = textValue(id, "").trim();
  if (!raw) {
    return null;
  }
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function numberOrDefault(id, fallback) {
  const value = numberOrNull(id);
  return value == null ? fallback : value;
}

function checkedValue(id, fallback = false) {
  const node = el(id);
  if (!node) {
    return fallback;
  }
  return Boolean(node.checked);
}

function parseManualRoi() {
  const parsed = parseJsonOrNull(textValue("roiInput", ""));
  if (!Array.isArray(parsed) || parsed.length !== 4) {
    return null;
  }
  const valid = parsed.every((point) => Array.isArray(point) && point.length === 2 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])));
  return valid ? parsed : null;
}

function inferLayoutHintFromRoi(roi, { sourceType: type, stitchEnabled }) {
  const fallback = type === "youtube" ? LAYOUT_BOTTOM_BAR : LAYOUT_FULL_SCROLL;
  if (!Array.isArray(roi) || roi.length !== 4) {
    return fallback;
  }

  const xs = roi.map((point) => Number(point[0]));
  const ys = roi.map((point) => Number(point[1]));
  const width = Math.max(...xs) - Math.min(...xs);
  const height = Math.max(...ys) - Math.min(...ys);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 2 || height <= 2) {
    return fallback;
  }

  const aspect = width / Math.max(1, height);
  if (aspect >= 2.25) {
    return LAYOUT_BOTTOM_BAR;
  }

  // Stitch on + non-strip ROI generally means full-score scroll/page style.
  if (stitchEnabled) {
    return LAYOUT_FULL_SCROLL;
  }
  return fallback;
}

export function buildPayload() {
  const type = sourceType();
  const sensitivity = captureSensitivity();
  const config = sensitivityConfig(sensitivity);
  const stitchEnabled = checkedValue("enableStitch", false);
  const parsedRoi = parseManualRoi();
  if (!parsedRoi) {
    throw new Error("악보 영역 좌표가 필요합니다. 3단계에서 미리보기 화면을 불러와 드래그로 지정해 주세요.");
  }
  const inferredLayoutHint = inferLayoutHintFromRoi(parsedRoi, {
    sourceType: type,
    stitchEnabled,
  });

  const body = {
    source_type: type,
    options: {
      extract: {
        fps: config.fps,
        capture_sensitivity: sensitivity,
        start_sec: numberOrNull("startSec"),
        end_sec: numberOrNull("endSec"),
      },
      detect: {
        roi: parsedRoi,
        layout_hint: inferredLayoutHint || DEFAULT_LAYOUT_HINT,
      },
      rectify: {
        auto: true,
      },
      stitch: {
        enable: stitchEnabled,
        overlap_threshold: numberOrDefault("overlapThreshold", 0.2),
        layout_hint: inferredLayoutHint || DEFAULT_LAYOUT_HINT,
        dedupe_level: config.dedupe_level,
      },
      upscale: {
        enable: checkedValue("enableUpscale", false),
        scale: numberOrDefault("upscaleFactor", 2.0),
        gpu_only: true,
      },
      audio: {
        enable: false,
        engine: "uvr_demucs",
        model: "htdemucs",
        stem: "drums",
        output_format: "wav",
        gpu_only: false,
      },
      export: {
        formats: getFormats(),
        include_raw_frames: false,
        page_fill_mode: "performance",
      },
    },
  };

  if (type === "file") {
    body.file_path = textValue("filePath", "").trim();
    if (!body.file_path) {
      throw new Error("로컬 파일을 선택해 주세요.");
    }
  } else {
    body.youtube_url = textValue("youtubeUrl", "").trim();
    if (!body.youtube_url) {
      throw new Error("유튜브 URL을 입력해 주세요.");
    }
  }

  const formats = getFormats();
  if (!formats.length) {
    throw new Error("최소 하나의 출력 형식을 선택해 주세요.");
  }
  body.options.export.formats = formats;

  return body;
}

export async function createJob(apiBase) {
  const payload = buildPayload();
  const response = await fetch(`${apiBase}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "요청 실패" }));
    throw new Error(friendlyApiError(error.detail || "요청 실패"));
  }
  const data = await response.json();
  return data.job_id;
}

export async function getJob(apiBase, jobId) {
  const response = await fetch(`${apiBase}/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error("작업 조회 실패");
  }
  return response.json();
}

export async function reviewExport(apiBase, jobId, { keepCaptures = [], formats = null } = {}) {
  const selected = Array.isArray(keepCaptures) ? keepCaptures.map((value) => String(value || "").trim()).filter(Boolean) : [];
  if (!selected.length) {
    throw new Error("검토 반영을 위해 포함할 캡쳐를 최소 1개 선택해 주세요.");
  }
  const body = {
    keep_captures: selected,
  };
  if (Array.isArray(formats) && formats.length > 0) {
    body.formats = formats;
  }

  const response = await fetch(`${apiBase}/jobs/${jobId}/review-export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "검토 반영 실패" }));
    throw new Error(friendlyApiError(error.detail || "검토 반영 실패"));
  }
  return response.json();
}

export async function cropCapture(apiBase, jobId, { capturePath = "", roi = [] } = {}) {
  const path = String(capturePath || "").trim();
  if (!path) {
    throw new Error("자르기 대상 캡쳐 경로가 비어 있어요.");
  }
  if (!Array.isArray(roi) || roi.length !== 4) {
    throw new Error("자르기 영역이 올바르지 않습니다. 다시 드래그해 주세요.");
  }

  const response = await fetch(`${apiBase}/jobs/${jobId}/capture-crop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      capture_path: path,
      roi,
    }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "캡쳐 자르기 실패" }));
    throw new Error(friendlyApiError(error.detail || "캡쳐 자르기 실패"));
  }
  return response.json();
}

export async function getRuntimeStatus(apiBase) {
  const response = await fetch(`${apiBase}/runtime`);
  if (!response.ok) {
    throw new Error("런타임 정보 조회 실패");
  }
  return response.json();
}

export async function clearCache(apiBase) {
  const response = await fetch(`${apiBase}/maintenance/clear-cache`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "캐시 정리 실패" }));
    throw new Error(friendlyApiError(error.detail || "캐시 정리 실패"));
  }
  return response.json();
}

export async function getCacheUsage(apiBase) {
  const response = await fetch(`${apiBase}/maintenance/cache-usage`);
  if (!response.ok) {
    throw new Error("캐시 용량 조회 실패");
  }
  return response.json();
}

function buildSourcePayload() {
  const type = sourceType();
  const payload = { source_type: type };

  if (type === "file") {
    payload.file_path = textValue("filePath", "").trim();
    if (!payload.file_path) {
      throw new Error("로컬 파일을 먼저 선택해 주세요.");
    }
  } else {
    payload.youtube_url = textValue("youtubeUrl", "").trim();
    if (!payload.youtube_url) {
      throw new Error("유튜브 주소를 먼저 입력해 주세요.");
    }
  }
  return payload;
}

export async function requestPreviewSource(apiBase) {
  const payload = buildSourcePayload();
  const response = await fetch(`${apiBase}/preview/source`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "영상 준비 실패" }));
    throw new Error(friendlyApiError(error.detail || "영상 준비 실패"));
  }
  return response.json();
}

function buildPreviewPayload(startSecOverride = null) {
  const type = sourceType();
  const override = Number(startSecOverride);
  const hasOverride = Number.isFinite(override) && override >= 0;
  const payload = {
    source_type: type,
    start_sec: hasOverride ? override : numberOrNull("startSec"),
  };

  if (type === "file") {
    payload.file_path = textValue("filePath", "").trim();
    if (!payload.file_path) {
      throw new Error("로컬 파일을 먼저 선택해 주세요.");
    }
  } else {
    payload.youtube_url = textValue("youtubeUrl", "").trim();
    if (!payload.youtube_url) {
      throw new Error("유튜브 주소를 먼저 입력해 주세요.");
    }
  }

  return payload;
}

export async function requestPreviewFrame(apiBase, { startSecOverride = null } = {}) {
  const payload = buildPreviewPayload(startSecOverride);
  const response = await fetch(`${apiBase}/preview/frame`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "미리보기 생성 실패" }));
    throw new Error(friendlyApiError(error.detail || "미리보기 생성 실패"));
  }
  const data = await response.json();
  if (data.image_url) {
    return data.image_url.startsWith("http") ? data.image_url : `${apiBase}${data.image_url}`;
  }
  return data.image_path;
}
