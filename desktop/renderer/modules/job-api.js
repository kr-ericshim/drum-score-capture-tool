import { el, parseJsonOrNull } from "./dom.js";
import { friendlyApiError } from "./messages.js";

export function sourceType() {
  const checked = document.querySelector('input[name="sourceType"]:checked');
  return checked ? checked.value : "file";
}

export function detectMode() {
  const checked = document.querySelector('input[name="detectMode"]:checked');
  return checked ? checked.value : "auto";
}

export function layoutHint() {
  const node = el("layoutHint");
  return node ? node.value : "auto";
}

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

export function buildPayload() {
  const type = sourceType();
  const sensitivity = captureSensitivity();
  const config = sensitivityConfig(sensitivity);
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
        mode: detectMode(),
        roi: null,
        layout_hint: layoutHint(),
      },
      rectify: {
        auto: true,
      },
      stitch: {
        enable: checkedValue("enableStitch", false),
        overlap_threshold: numberOrDefault("overlapThreshold", 0.2),
        layout_hint: layoutHint(),
        dedupe_level: config.dedupe_level,
      },
      upscale: {
        enable: checkedValue("enableUpscale", false),
        scale: numberOrDefault("upscaleFactor", 2.0),
        gpu_only: true,
      },
      export: {
        formats: getFormats(),
        include_raw_frames: false,
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

  if (detectMode() === "manual") {
    const parsed = parseJsonOrNull(textValue("roiInput", ""));
    if (!parsed) {
      throw new Error("직접 영역 지정을 켠 경우, 좌표를 입력해 주세요. 예: [[0,0],[100,0],[100,100],[0,100]]");
    }
    body.options.detect.roi = parsed;
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

export async function getRuntimeStatus(apiBase) {
  const response = await fetch(`${apiBase}/runtime`);
  if (!response.ok) {
    throw new Error("런타임 정보 조회 실패");
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
