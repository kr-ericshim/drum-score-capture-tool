import { el, fileUrl, parseJsonOrNull } from "./modules/dom.js";
import { applyI18n, getLocale, initLocale, onLocaleChange, setLocale, t } from "./modules/i18n.js";
import {
  clearCache,
  createJob,
  cropCapture,
  getCacheUsage,
  getFormats,
  getJob,
  getRuntimeStatus,
  requestPreviewFrame,
  requestPreviewRoiHealth,
  requestPreviewSource,
  reviewExport,
  sourceType,
} from "./modules/job-api.js";
import { friendlyMessage, friendlyStatusText, friendlyStepName } from "./modules/messages.js";
import { createRoiController } from "./modules/roi-controller.js";
import { renderRuntimeError, renderRuntimeStatus } from "./modules/runtime-status-ui.js";
import { appendLog, clearResultMeta, renderResultMeta, setPipelineState, setProgress, setStatus } from "./modules/status-ui.js";
import { createVideoRangePicker } from "./modules/video-range-picker.js";

const API_BASE = window.drumSheetAPI?.apiBase || "http://127.0.0.1:8000";
const THEME_STORAGE_KEY = "drum-sheet-theme";
const THEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";
let activePoll = null;
let outputDir = "";
let outputPdf = "";
let activeCaptureJobId = "";
let currentPreviewImagePath = "";
let resultPageDiagnostics = [];
let resultFocusPending = false;
let currentPreviewFrame = {
  imagePath: "",
  sourcePath: "",
  previewSecond: null,
  diagnostics: [],
};
let currentRoiSnapshot = null;
let currentRoiHealth = {
  tone: "idle",
  summary: "",
};
let currentRoiHealthReport = {
  status: "idle",
  riskLevel: "info",
  summary: "",
  diagnostics: [],
  checkedSeconds: [],
  metrics: {},
  message: "",
};
let resultImagePaths = [];
let excludedResultIndices = new Set();
let reviewApplyRunning = false;
let captureCropState = {
  open: false,
  imagePath: "",
  imageIndex: -1,
  rect: null,
  naturalWidth: 0,
  naturalHeight: 0,
  canvasWidth: 0,
  canvasHeight: 0,
  dragStart: null,
  drawing: false,
  loaded: false,
  applyRunning: false,
};
const captureRenderVersion = new Map();
let latestRuntime = null;
let runState = "idle";
let currentPreset = "basic";
let manualOpenStep = null;
let lastSourceFingerprint = currentSourceFingerprint();
let lastSourceType = sourceType();
let previewRequestToken = 0;
let roiHealthRequestToken = 0;
let roiHealthDebounceTimer = null;
let runtimeRefreshInFlight = false;
let youtubePrepareState = {
  status: "idle",
  fingerprint: "",
  detail: "",
  fromCache: false,
  playable: "",
};
let youtubePrepareLogs = [];
let roiFrameRequestState = {
  status: "idle",
  detail: "",
};
let setupRunning = false;
let cacheClearRunning = false;
let cacheUsageText = "";
let cacheUsageLoading = false;
let lastCacheUsageFetchAt = 0;
let alwaysOnTopEnabled = false;
let supportSheetOpen = false;
let statusDrawerOpen = false;
let backendBridgeState = {
  ready: false,
  starting: true,
  running: false,
  error: "",
  setupRunning: false,
};
let themeMediaQuery = null;

const STEP_KEYS = ["source", "roi", "export"];
const STEP_DETAIL_IDS = {
  source: "stepSourceDetails",
  roi: "stepRoiDetails",
  export: "stepExportDetails",
};
const STEP_CARD_SUMMARY_IDS = {
  source: "stepSourceSummary",
  roi: "stepRoiSummary",
  export: "stepExportSummary",
};
const STEP_BAR_SUMMARY_IDS = {
  source: "stepBadgeSource",
  roi: "stepBadgeRoi",
  export: "stepBadgeExport",
};
const STEP_BAR_BUTTON_IDS = {
  source: "stepperSource",
  roi: "stepperRoi",
  export: "stepperExport",
};

function L(ko, en) {
  return getLocale() === "ko" ? ko : en;
}

function statusText(ko, en) {
  return L(ko, en);
}

function appendLocaleLog(ko, en) {
  appendLog(L(ko, en));
}

function appendLocaleError(message) {
  appendLog(`${L("오류", "Error")}: ${message}`);
}

function appendLocaleSetupLog(ko, en) {
  appendSetupLogLine(L(ko, en));
}

function appendLocaleSetupError(message) {
  appendSetupLogLine(`${L("오류", "Error")}: ${message}`);
}

function youtubePrepareStatusText(state = youtubePrepareState) {
  if (sourceType() !== "youtube") {
    return "";
  }
  switch (state.status) {
    case "preparing":
      return L(
        "유튜브 영상을 다운로드하고 있습니다. 첫 요청은 몇 초 이상 걸릴 수 있습니다.",
        "Downloading the YouTube video. The first request can take several seconds.",
      );
    case "ready":
      return state.fromCache
        ? L("캐시된 영상을 사용합니다. 바로 악보 화면을 열 수 있습니다.", "Using the cached video. You can open the score frame immediately.")
        : L("영상 준비 완료. 아래 플레이어에서 구간을 확인한 뒤 악보 화면을 열 수 있습니다.", "Video ready. Check the range below, then open the score frame.");
    case "error":
      return L(
        "유튜브 영상을 준비하지 못했습니다. 상세 원인은 아래 로그에서 확인할 수 있습니다.",
        "Could not prepare the YouTube video. Check the log below for details.",
      );
    default:
      return L("유튜브 주소를 붙여넣고 영상 준비를 누르면 다운로드 상태가 여기 표시됩니다.", "Paste a YouTube URL and press Prepare Video to see download status here.");
  }
}

function extractYoutubeLowResolution(detail = "", logs = youtubePrepareLogs) {
  const haystacks = [
    String(detail || ""),
    ...((Array.isArray(logs) ? logs : []).map((line) => String(line || ""))),
  ];
  for (const haystack of haystacks) {
    const match = haystack.match(/low resolution\s+(\d+)x(\d+)/i) || haystack.match(/resolved to\s+(\d+)x(\d+)/i);
    if (match) {
      return {
        width: Number(match[1]) || 0,
        height: Number(match[2]) || 0,
      };
    }
  }
  return null;
}

function isYoutubeQualityFailure(detail = "", logs = youtubePrepareLogs) {
  if (sourceType() !== "youtube" || youtubePrepareState.status !== "error") {
    return false;
  }
  return Boolean(extractYoutubeLowResolution(detail, logs));
}

function renderYoutubeQualityGate() {
  const gate = el("youtubeQualityGate");
  const body = el("youtubeQualityGateBody");
  if (!gate || !body) {
    return;
  }
  const lowResolution = extractYoutubeLowResolution(youtubePrepareState.detail, youtubePrepareLogs);
  const visible = isYoutubeQualityFailure(youtubePrepareState.detail, youtubePrepareLogs);
  gate.hidden = !visible;
  if (!visible) {
    return;
  }
  const resolution = lowResolution?.width > 0 && lowResolution?.height > 0
    ? `${lowResolution.width}x${lowResolution.height}`
    : "";
  body.textContent = resolution
    ? L(
        `현재 협상된 영상 해상도는 ${resolution}입니다. 이 해상도로는 악보 판독 정확도가 크게 떨어질 수 있으니, 다른 플랫폼 또는 직접 확보한 원본 영상 파일을 사용하는 편이 안전합니다.`,
        `The negotiated video resolution is ${resolution}. That is likely too soft for reliable score capture, so using the original file or a copy from another platform is safer.`,
      )
    : L(
        "현재 환경에서는 악보 판독에 충분한 해상도로 이 영상을 가져오지 못했습니다. 가능하면 다른 플랫폼 또는 직접 확보한 원본 영상 파일을 사용하세요.",
        "The current environment could not fetch this video at a resolution that is reliable enough for score capture. If possible, use the original video file or a copy obtained from another platform.",
      );
}

function roiFrameRequestStatusText(state = roiFrameRequestState) {
  const detail = compactErrorText(state.detail, "");
  switch (state.status) {
    case "loading":
      return L("악보 화면용 대표 프레임을 추출하고 있습니다.", "Extracting a representative frame for ROI setup.");
    case "ready":
      return L("프레임 준비 완료. 악보 전체가 들어오도록 드래그합니다.", "Frame ready. Drag to include the full score area.");
    case "error":
      return detail
        ? L(`프레임 준비 실패: ${detail}`, `Failed to prepare the frame: ${detail}`)
        : L("악보 화면을 열지 못했습니다. 다시 시도합니다.", "Could not open the score frame. Try again.");
    default:
      return "";
  }
}

function renderYoutubePrepareState() {
  const button = el("prepareYoutubeVideo");
  const statusNode = el("youtubePrepareStatus");
  const isYoutube = sourceType() === "youtube";
  if (button) {
    if (youtubePrepareState.status === "preparing") {
      button.textContent = L("준비 중...", "Preparing...");
    } else if (youtubePrepareState.status === "ready") {
      button.textContent = L("다시 준비", "Prepare Again");
    } else if (youtubePrepareState.status === "error") {
      button.textContent = L("다시 시도", "Try Again");
    } else {
      button.textContent = L("유튜브 영상 준비", "Prepare YouTube Video");
    }
  }
  if (!statusNode) {
    return;
  }
  statusNode.hidden = !isYoutube;
  statusNode.dataset.tone = youtubePrepareState.status === "preparing"
    ? "loading"
    : youtubePrepareState.status === "ready"
      ? "ready"
      : youtubePrepareState.status === "error"
        ? "error"
        : "idle";
  statusNode.textContent = youtubePrepareStatusText();
  renderYoutubeQualityGate();
  renderYoutubePrepareLogs();
}

function renderRoiFrameRequestState() {
  const button = el("loadPreviewForRoi");
  const statusNode = el("roiFrameRequestStatus");
  if (button) {
    button.textContent = roiFrameRequestState.status === "loading"
      ? L("불러오는 중...", "Loading...")
      : L("악보 화면 열기", "Open Score Frame");
  }
  if (!statusNode) {
    return;
  }
  const hasMessage = Boolean(roiFrameRequestStatusText());
  statusNode.hidden = !hasMessage;
  statusNode.dataset.tone = roiFrameRequestState.status === "loading"
    ? "loading"
    : roiFrameRequestState.status === "ready"
      ? "ready"
      : roiFrameRequestState.status === "error"
        ? "error"
        : "idle";
  statusNode.textContent = roiFrameRequestStatusText();
}

function resetYoutubePrepareState() {
  youtubePrepareState = {
    status: "idle",
    fingerprint: "",
    detail: "",
    fromCache: false,
    playable: "",
  };
  renderYoutubePrepareState();
}

function renderYoutubePrepareLogs() {
  const details = el("youtubePrepareLogDetails");
  const logNode = el("youtubePrepareLog");
  const isYoutube = sourceType() === "youtube";
  if (logNode) {
    logNode.textContent = youtubePrepareLogs.join("\n");
    logNode.scrollTop = logNode.scrollHeight;
  }
  if (!details) {
    return;
  }
  const hasLogs = youtubePrepareLogs.length > 0;
  details.hidden = !(isYoutube && hasLogs);
  if (!hasLogs) {
    details.open = false;
  } else if (youtubePrepareState.status === "preparing") {
    details.open = true;
  }
}

function resetYoutubePrepareLogs() {
  youtubePrepareLogs = [];
  renderYoutubePrepareLogs();
}

function appendYoutubePrepareLogLine(message) {
  const text = String(message || "").trim();
  if (!text) {
    return;
  }
  if (youtubePrepareLogs[youtubePrepareLogs.length - 1] === text) {
    return;
  }
  youtubePrepareLogs = [...youtubePrepareLogs, text].slice(-120);
  renderYoutubePrepareLogs();
}

function appendYoutubePrepareLogLines(lines = []) {
  lines.forEach((line) => appendYoutubePrepareLogLine(line));
}

function setYoutubePrepareState(next) {
  const previousStatus = youtubePrepareState.status;
  youtubePrepareState = {
    ...youtubePrepareState,
    ...next,
  };
  if (previousStatus === "preparing" && youtubePrepareState.status !== "preparing") {
    const details = el("youtubePrepareLogDetails");
    if (details) {
      details.open = false;
    }
  }
  renderYoutubePrepareState();
}

function setRoiFrameRequestState(next) {
  roiFrameRequestState = {
    ...roiFrameRequestState,
    ...next,
  };
  renderRoiFrameRequestState();
}

function defaultSetupLogText() {
  return t("support.setup.defaultLog");
}

function readStoredThemePreference() {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return stored === "light" || stored === "dark" ? stored : "";
}

function resolveSystemTheme() {
  return window.matchMedia && window.matchMedia(THEME_MEDIA_QUERY).matches ? "dark" : "light";
}

function currentTheme() {
  const value = String(document.documentElement.getAttribute("data-theme") || "").trim();
  return value === "dark" ? "dark" : "light";
}

function syncThemeToggleUi() {
  const button = el("themeToggle");
  if (!button) {
    return;
  }
  const theme = currentTheme();
  const nextLabel = theme === "dark" ? (getLocale() === "ko" ? "라이트 모드로 전환" : "Switch to light mode") : (getLocale() === "ko" ? "다크 모드로 전환" : "Switch to dark mode");
  const currentLabel = theme === "dark" ? (getLocale() === "ko" ? "현재 다크 모드" : "Dark mode active") : (getLocale() === "ko" ? "현재 라이트 모드" : "Light mode active");
  button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
  button.setAttribute("aria-label", `${currentLabel}, ${nextLabel}`);
  button.title = nextLabel;
}

function syncLocaleToggleUi() {
  const activeLocale = getLocale();
  ["ko", "en"].forEach((locale) => {
    const button = el(locale === "ko" ? "localeKo" : "localeEn");
    if (!button) {
      return;
    }
    const isActive = activeLocale === locale;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function cssToken(name, fallback = "") {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function applyTheme(theme, { persist = true } = {}) {
  const nextTheme = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", nextTheme);
  if (persist) {
    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
  }
  syncThemeToggleUi();
  renderRoiAssist(currentRoiSnapshot);
  if (captureCropState.open && captureCropState.loaded) {
    drawCaptureCropOverlay();
  }
}

function onThemeToggle() {
  const nextTheme = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(nextTheme, { persist: true });
}

function bindThemeToggle() {
  syncThemeToggleUi();
  const button = el("themeToggle");
  button?.addEventListener("click", onThemeToggle);

  if (!window.matchMedia) {
    return;
  }
  themeMediaQuery = window.matchMedia(THEME_MEDIA_QUERY);
  const handleMediaChange = () => {
    if (readStoredThemePreference()) {
      return;
    }
    applyTheme(resolveSystemTheme(), { persist: false });
  };
  if (typeof themeMediaQuery.addEventListener === "function") {
    themeMediaQuery.addEventListener("change", handleMediaChange);
  } else if (typeof themeMediaQuery.addListener === "function") {
    themeMediaQuery.addListener(handleMediaChange);
  }
}

function bindLocaleToggle() {
  syncLocaleToggleUi();
  el("localeKo")?.addEventListener("click", () => setLocale("ko"));
  el("localeEn")?.addEventListener("click", () => setLocale("en"));
}

const PRESET_CONFIG = {
  basic: {
    captureSensitivity: "medium",
    enableStitch: false,
    overlapThreshold: 0.2,
    enableUpscale: false,
    upscaleFactor: "2.0",
  },
  scroll: {
    captureSensitivity: "low",
    enableStitch: true,
    overlapThreshold: 0.26,
    enableUpscale: false,
    upscaleFactor: "2.0",
  },
  quality: {
    captureSensitivity: "high",
    enableStitch: false,
    overlapThreshold: 0.2,
    enableUpscale: true,
    upscaleFactor: "3.0",
  },
};

function presetHint(name) {
  if (name === "scroll") {
    return getLocale() === "ko"
      ? "스크롤 영상에서 줄이 이어지게 맞추는 모드입니다. 긴 스크롤 악보에 유리합니다."
      : "Best for scrolling videos where score lines should connect across a long page.";
  }
  if (name === "quality") {
    return getLocale() === "ko"
      ? "글자 선명도를 더 높이는 모드입니다. 처리 시간이 더 걸릴 수 있습니다."
      : "Prioritizes sharper text and notation, but processing may take longer.";
  }
  return getLocale() === "ko"
    ? "페이지 넘김을 줄이는 연주용 기본값입니다. 대부분 이 모드 그대로 쓰면 됩니다."
    : "Default mode tuned for practical use with fewer page turns. This fits most cases.";
}

function pathBaseName(rawPath) {
  const value = String(rawPath || "").trim();
  if (!value) {
    return "";
  }
  const normalized = value.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : value;
}

function truncateMiddle(text, maxLen = 60) {
  const value = String(text || "");
  if (!value || value.length <= maxLen) {
    return value;
  }
  const head = Math.ceil((maxLen - 1) / 2);
  const tail = Math.floor((maxLen - 1) / 2);
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

function bumpCaptureRenderVersion(pathValue) {
  const key = String(pathValue || "").trim();
  if (!key) {
    return;
  }
  const current = Number(captureRenderVersion.get(key) || 0);
  captureRenderVersion.set(key, current + 1);
}

function pathWithVersion(pathValue) {
  const key = String(pathValue || "").trim();
  if (!key) {
    return "";
  }
  if (key.startsWith("/jobs-files/")) {
    const version = Number(captureRenderVersion.get(key) || 0);
    if (version <= 0) {
      return `${API_BASE}${key}`;
    }
    return `${API_BASE}${key}?v=${version}`;
  }
  if (key.startsWith("jobs-files/")) {
    const normalized = `/${key}`;
    const version = Number(captureRenderVersion.get(key) || 0);
    if (version <= 0) {
      return `${API_BASE}${normalized}`;
    }
    return `${API_BASE}${normalized}?v=${version}`;
  }
  const base =
    key.startsWith("http://") || key.startsWith("https://") || key.startsWith("file://") ? key : fileUrl(key);
  const version = Number(captureRenderVersion.get(key) || 0);
  if (version <= 0) {
    return base;
  }
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}v=${version}`;
}

function formatPercent(value) {
  return `${Math.round(Math.max(0, value) * 100)}%`;
}

function roiElements() {
  return {
    frameMeta: el("roiFrameMeta"),
    cropCanvas: el("roiCropPreview"),
    cropSummary: el("roiCropSummary"),
    cropMetrics: el("roiCropMetrics"),
    zoomCanvas: el("roiZoomPreview"),
    zoomSummary: el("roiZoomSummary"),
    healthBadge: el("roiHealthBadge"),
    healthSummary: el("roiHealthSummary"),
    diagnosticsList: el("roiDiagnosticsList"),
    backendHint: el("roiBackendHint"),
    assistHint: el("roiAssistHint"),
  };
}

function prepareAssistCanvas(canvas) {
  if (!canvas) {
    return null;
  }
  const rect = canvas.getBoundingClientRect();
  const cssWidth = Math.max(160, Math.round(rect.width || 320));
  const cssHeight = Math.max(120, Math.round(rect.height || cssWidth * 0.625));
  const dpr = window.devicePixelRatio || 1;
  const pixelWidth = Math.max(1, Math.round(cssWidth * dpr));
  const pixelHeight = Math.max(1, Math.round(cssHeight * dpr));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return null;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  return { ctx, width: cssWidth, height: cssHeight };
}

function drawAssistPlaceholder(canvas, title, detail) {
  const prepared = prepareAssistCanvas(canvas);
  if (!prepared) {
    return;
  }
  const { ctx, width, height } = prepared;
  ctx.fillStyle = cssToken("--surface-faint", "#f5f9ff");
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = cssToken("--line-soft", "#d0dff0");
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
  ctx.fillStyle = cssToken("--ink", "#204063");
  ctx.font = '700 14px "Pretendard", "SUIT", "Noto Sans KR", sans-serif';
  ctx.fillText(title, 16, 26);
  ctx.fillStyle = cssToken("--ink-muted", "#56728f");
  ctx.font = '12px "Pretendard", "SUIT", "Noto Sans KR", sans-serif';
  wrapCanvasText(ctx, detail, 16, 50, width - 32, 18);
}

function wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight) {
  const words = String(text || "").split(" ");
  let line = "";
  let cursorY = y;
  words.forEach((word) => {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width > maxWidth && line) {
      ctx.fillText(line, x, cursorY);
      line = word;
      cursorY += lineHeight;
    } else {
      line = next;
    }
  });
  if (line) {
    ctx.fillText(line, x, cursorY);
  }
}

function drawImageIntoCanvas(canvas, image, crop, { overlayRect = null } = {}) {
  const prepared = prepareAssistCanvas(canvas);
  if (!prepared || !image) {
    return;
  }
  const { ctx, width, height } = prepared;
  ctx.fillStyle = cssToken("--surface", "#ffffff");
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(image, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, width, height);
  ctx.strokeStyle = cssToken("--line-soft", "#d0dff0");
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
  if (overlayRect) {
    ctx.strokeStyle = cssToken("--accent-2", "#11c3a0");
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.strokeRect(overlayRect.x, overlayRect.y, overlayRect.w, overlayRect.h);
  }
}

function renderRoiMetricPills(labels = []) {
  const { cropMetrics } = roiElements();
  if (!cropMetrics) {
    return;
  }
  cropMetrics.replaceChildren();
  labels.forEach((label) => {
    const pill = document.createElement("span");
    pill.className = "roi-metric-pill";
    pill.textContent = label;
    cropMetrics.append(pill);
  });
}

function clearScheduledRoiHealthCheck() {
  roiHealthRequestToken += 1;
  if (roiHealthDebounceTimer) {
    window.clearTimeout(roiHealthDebounceTimer);
    roiHealthDebounceTimer = null;
  }
}

function resetCurrentRoiHealthReport() {
  clearScheduledRoiHealthCheck();
  currentRoiHealthReport = {
    status: "idle",
    riskLevel: "info",
    summary: "",
    diagnostics: [],
    checkedSeconds: [],
    metrics: {},
    message: "",
  };
}

function localRoiMetrics(snapshot) {
  const rectWidth = snapshot.rect.x2 - snapshot.rect.x1;
  const rectHeight = snapshot.rect.y2 - snapshot.rect.y1;
  const widthRatio = rectWidth / Math.max(1, snapshot.canvasWidth);
  const heightRatio = rectHeight / Math.max(1, snapshot.canvasHeight);
  const topMarginRatio = snapshot.rect.y1 / Math.max(1, snapshot.canvasHeight);
  const bottomMarginRatio = (snapshot.canvasHeight - snapshot.rect.y2) / Math.max(1, snapshot.canvasHeight);
  const issues = [];

  if (widthRatio < 0.34) {
    issues.push(L("ROI가 너무 좁아서 좌우 악보 끝이 잘릴 수 있습니다.", "The ROI is too narrow, so the left and right score edges may be clipped."));
  }
  if (widthRatio > 0.96) {
    issues.push(L("ROI가 너무 넓어서 플레이어 UI나 빈 여백이 섞일 수 있습니다.", "The ROI is too wide and may include player UI or empty margins."));
  }
  if (heightRatio < 0.18) {
    issues.push(L("ROI 높이가 너무 얕아서 여러 줄 악보가 빠질 수 있습니다.", "The ROI height is too shallow, so some score rows may be missed."));
  }
  if (heightRatio > 0.88) {
    issues.push(L("ROI 높이가 너무 커서 불필요한 배경까지 많이 포함하고 있습니다.", "The ROI height is too large and includes too much background."));
  }
  if (topMarginRatio < 0.015 || bottomMarginRatio < 0.015) {
    issues.push(L("상단 또는 하단 경계가 너무 바짝 붙어 있어 잘림 위험이 있습니다.", "The top or bottom edge is too tight and may clip the score."));
  }
  if (topMarginRatio > 0.32) {
    issues.push(L("영역이 화면 아래쪽에 치우쳐 위쪽 보표 일부가 빠질 수 있습니다.", "The ROI is too low, so the upper staff may be missing."));
  }
  if (bottomMarginRatio > 0.32) {
    issues.push(L("영역이 화면 위쪽에 치우쳐 아래쪽 보표 일부가 빠질 수 있습니다.", "The ROI is too high, so the lower staff may be missing."));
  }

  return {
    rectWidth,
    rectHeight,
    widthRatio,
    heightRatio,
    topMarginRatio,
    bottomMarginRatio,
    issues,
  };
}

function roiMetricLabels(metrics, fallbackMetrics) {
  if (!metrics || typeof metrics !== "object") {
    return fallbackMetrics;
  }
  const widthRatio = Number(metrics.width_ratio);
  const heightRatio = Number(metrics.height_ratio);
  const topMarginRatio = Number(metrics.top_margin_ratio);
  const bottomMarginRatio = Number(metrics.bottom_margin_ratio);
  if (![widthRatio, heightRatio, topMarginRatio, bottomMarginRatio].every((value) => Number.isFinite(value))) {
    return fallbackMetrics;
  }
  return [
    L(`폭 ${formatPercent(widthRatio)}`, `Width ${formatPercent(widthRatio)}`),
    L(`높이 ${formatPercent(heightRatio)}`, `Height ${formatPercent(heightRatio)}`),
    L(`상단 여백 ${formatPercent(topMarginRatio)}`, `Top margin ${formatPercent(topMarginRatio)}`),
    L(`하단 여백 ${formatPercent(bottomMarginRatio)}`, `Bottom margin ${formatPercent(bottomMarginRatio)}`),
  ];
}

function roiBackendHint(report) {
  const checked = Array.isArray(report?.checkedSeconds) ? report.checkedSeconds.filter((value) => Number.isFinite(Number(value))) : [];
  if (!checked.length) {
    return L("샘플 프레임 기준으로 ROI 상태를 점검합니다.", "ROI is checked against sample frames.");
  }
  const label = checked.map((value) => formatSecToMmss(Number(value))).join(", ");
  return L(`샘플 프레임 ${label} 기준으로 ROI를 점검했습니다.`, `ROI checked using sample frames at ${label}.`);
}

async function requestRoiHealth(snapshot) {
  if (!backendBridgeState.ready || !snapshot?.imageReady || !Array.isArray(snapshot?.points) || snapshot.points.length !== 4) {
    resetCurrentRoiHealthReport();
    return;
  }

  clearScheduledRoiHealthCheck();
  const requestToken = roiHealthRequestToken;
  const sourceFingerprint = currentSourceFingerprint();
  const startSecOverride = currentPreviewFrame.previewSecond;
  currentRoiHealthReport = {
    ...currentRoiHealthReport,
    status: "loading",
    message: "",
  };
  renderRoiAssist(snapshot);

  roiHealthDebounceTimer = window.setTimeout(async () => {
    try {
      const response = await requestPreviewRoiHealth(API_BASE, {
        roi: snapshot.points,
        startSecOverride,
      });
      if (requestToken !== roiHealthRequestToken || sourceFingerprint !== currentSourceFingerprint()) {
        return;
      }
      currentRoiHealthReport = {
        status: "ready",
        riskLevel: String(response?.risk_level || "info"),
        summary: String(response?.summary || ""),
        diagnostics: Array.isArray(response?.diagnostics) ? response.diagnostics : [],
        checkedSeconds: Array.isArray(response?.checked_seconds) ? response.checked_seconds : [],
        metrics: response?.metrics && typeof response.metrics === "object" ? response.metrics : {},
        message: "",
      };
    } catch (error) {
      if (requestToken !== roiHealthRequestToken) {
        return;
      }
      currentRoiHealthReport = {
        ...currentRoiHealthReport,
        status: "error",
        message: compactErrorText(error?.message, L("ROI 점검 결과를 불러오지 못했습니다.", "Could not load ROI diagnostics.")),
      };
    } finally {
      if (requestToken === roiHealthRequestToken) {
        roiHealthDebounceTimer = null;
        renderRoiAssist(currentRoiSnapshot);
      }
    }
  }, 260);
}

function setRoiHealthVisual({ tone, badge, summary, items, backendHint }) {
  const { healthBadge, healthSummary, diagnosticsList, assistHint, frameMeta } = roiElements();
  currentRoiHealth = {
    tone: String(tone || "idle"),
    summary: String(summary || ""),
  };
  if (healthBadge) {
    healthBadge.textContent = badge;
    healthBadge.classList.remove("roi-health-idle", "roi-health-ready", "roi-health-warn");
    healthBadge.classList.add(tone === "ready" ? "roi-health-ready" : tone === "warn" ? "roi-health-warn" : "roi-health-idle");
  }
  if (healthSummary) {
    healthSummary.textContent = summary;
  }
  if (diagnosticsList) {
    diagnosticsList.replaceChildren();
    items.forEach((item) => {
      const node = document.createElement("li");
      node.className = `roi-diagnostic-item ${item.tone === "ready" ? "roi-diagnostic-ready" : item.tone === "warning" ? "roi-diagnostic-warning" : "roi-diagnostic-info"}`;
      node.textContent = item.text;
      diagnosticsList.append(node);
    });
  }
  const { backendHint: backendHintNode } = roiElements();
  if (backendHintNode) {
    backendHintNode.textContent = backendHint;
  }
  if (assistHint) {
    assistHint.textContent =
      tone === "ready"
        ? L("현재 ROI는 바로 실행 가능한 상태로 보입니다. 첫 결과 페이지에서 경계만 한 번 더 확인합니다.", "The current ROI looks ready to run. Check page edges once on the first result page.")
        : tone === "warn"
          ? L("잘림 또는 여백 문제 가능성이 있습니다. 확대 보기와 경고 항목을 먼저 확인합니다.", "There may be clipping or margin issues. Review the zoom preview and warnings first.")
          : L("프레임을 불러오면 선택 영역과 경계 여유를 함께 확인할 수 있습니다.", "Load a frame to review both the selected area and its boundary margins.");
  }
  if (frameMeta) {
    frameMeta.textContent = currentRoiSnapshot?.imageReady
      ? currentRoiSnapshot?.rect
        ? L(`${currentRoiSnapshot.canvasWidth} x ${currentRoiSnapshot.canvasHeight} · ROI 적용`, `${currentRoiSnapshot.canvasWidth} x ${currentRoiSnapshot.canvasHeight} · ROI applied`)
        : L(`${currentRoiSnapshot.canvasWidth} x ${currentRoiSnapshot.canvasHeight} 프레임`, `${currentRoiSnapshot.canvasWidth} x ${currentRoiSnapshot.canvasHeight} frame`)
      : L("프레임 준비 전", "Frame not ready");
  }
}

function buildRoiHealthState(snapshot) {
  if (!snapshot?.hasImage) {
    return {
      tone: "idle",
      badge: L("대기 중", "Idle"),
      summary: L("악보 화면을 먼저 열어야 ROI 진단을 시작할 수 있습니다.", "Open a score frame before starting ROI diagnostics."),
      items: [{ tone: "info", text: L("영상에서 악보가 가장 잘 보이는 시점을 연 뒤 ROI를 잡아주세요.", "Open a moment where the score is easy to read, then draw the ROI.") }],
      backendHint: L("현재 화면 기준으로 ROI 상태를 바로 안내합니다.", "Immediate ROI guidance is shown from the current frame."),
      cropSummary: L("프레임을 불러온 뒤 ROI를 지정하면 이 영역만 확대해서 보여줍니다.", "After loading a frame and setting ROI, this view zooms into the selected area."),
      zoomSummary: L("선택 영역 주변까지 같이 보여줘서 보표가 너무 바짝 붙지 않았는지 확인합니다.", "Shows the surrounding area so you can check whether the score is too close to the edge."),
      metrics: [t("roi.metric.widthEmpty"), t("roi.metric.heightEmpty"), t("roi.metric.topMarginEmpty"), t("roi.metric.bottomMarginEmpty")],
    };
  }

  if (!snapshot.imageReady) {
    return {
      tone: "idle",
      badge: L("불러오는 중", "Loading"),
      summary: L("프레임 이미지를 읽는 중입니다. 잠시만 기다려 주세요.", "Reading the frame image. Please wait a moment."),
      items: [{ tone: "info", text: L("프레임이 표시되면 악보 첫 줄부터 마지막 줄까지 감싸 주세요.", "When the frame appears, cover the score from the first visible line to the last.") }],
      backendHint: L("프레임 준비가 끝나면 즉시 진단이 표시됩니다.", "Diagnostics appear as soon as the frame is ready."),
      cropSummary: L("프레임을 읽는 중입니다.", "Loading frame."),
      zoomSummary: L("프레임이 로드되면 확대 보조가 표시됩니다.", "The zoom helper appears after the frame is loaded."),
      metrics: [t("roi.metric.widthEmpty"), t("roi.metric.heightEmpty"), t("roi.metric.topMarginEmpty"), t("roi.metric.bottomMarginEmpty")],
    };
  }

  if (!snapshot.rect) {
    return {
      tone: "idle",
      badge: L("ROI 필요", "ROI Needed"),
      summary: L("아직 악보 영역이 지정되지 않았습니다.", "The score area has not been set yet."),
      items: [
        { tone: "info", text: L("악보 첫 줄과 마지막 줄이 모두 들어오게 네모 박스를 그려 주세요.", "Draw a box that includes both the first and last visible score lines.") },
        { tone: "info", text: L("모서리 핸들 또는 방향키로 경계를 세밀하게 조정할 수 있습니다.", "Use corner handles or arrow keys for fine adjustments.") },
      ],
      backendHint: L("ROI를 지정하면 잘림과 여백 위험을 즉시 계산합니다.", "Clipping and margin risks are calculated as soon as ROI is set."),
      cropSummary: L("ROI를 지정하면 선택 영역만 따로 확대해서 보여줍니다.", "Once ROI is set, only the selected area is zoomed here."),
      zoomSummary: L("ROI를 지정하면 경계 주변 여유 공간을 함께 표시합니다.", "Once ROI is set, the surrounding margin is shown here too."),
      metrics: [t("roi.metric.widthEmpty"), t("roi.metric.heightEmpty"), t("roi.metric.topMarginEmpty"), t("roi.metric.bottomMarginEmpty")],
    };
  }

  const local = localRoiMetrics(snapshot);
  const fallbackMetrics = [
    L(`폭 ${formatPercent(local.widthRatio)}`, `Width ${formatPercent(local.widthRatio)}`),
    L(`높이 ${formatPercent(local.heightRatio)}`, `Height ${formatPercent(local.heightRatio)}`),
    L(`상단 여백 ${formatPercent(local.topMarginRatio)}`, `Top margin ${formatPercent(local.topMarginRatio)}`),
    L(`하단 여백 ${formatPercent(local.bottomMarginRatio)}`, `Bottom margin ${formatPercent(local.bottomMarginRatio)}`),
  ];

  if (currentRoiHealthReport.status === "ready") {
    const diagnostics = Array.isArray(currentRoiHealthReport.diagnostics) ? currentRoiHealthReport.diagnostics : [];
    const diagnosticItems = diagnostics
      .map((item) => ({
        tone: item?.level === "critical" || item?.level === "warning" ? "warning" : "info",
        text: [String(item?.title || "").trim(), String(item?.detail || "").trim()].filter(Boolean).join(": "),
      }))
      .filter((item) => item.text);
    const tone = currentRoiHealthReport.riskLevel === "info" ? "ready" : "warn";
    return {
      tone,
      badge: tone === "ready" ? L("실행 준비", "Ready") : L("조정 권장", "Adjust"),
      summary:
        currentRoiHealthReport.summary ||
        (tone === "ready" ? L("샘플 프레임 기준으로 현재 ROI는 안정적입니다.", "The current ROI looks stable across sampled frames.") : L("샘플 프레임 기준으로 조정이 필요한 지점이 있습니다.", "Sampled frames suggest the ROI should be adjusted.")),
      items: diagnosticItems.length
        ? diagnosticItems
        : [{ tone: "ready", text: L("샘플 프레임 기준으로 뚜렷한 잘림 위험이 보이지 않습니다.", "No obvious clipping risk was found in sampled frames.") }],
      backendHint: roiBackendHint(currentRoiHealthReport),
      cropSummary: L(`현재 선택 영역 ${local.rectWidth}px x ${local.rectHeight}px`, `Current selection ${local.rectWidth}px x ${local.rectHeight}px`),
      zoomSummary: L("ROI 바깥 여유 공간까지 함께 보여줍니다. 경계가 너무 바짝 붙지 않았는지 확인하세요.", "Shows the outer margin around the ROI. Check that the boundary is not too tight."),
      metrics: roiMetricLabels(currentRoiHealthReport.metrics, fallbackMetrics),
    };
  }

  if (currentRoiHealthReport.status === "loading") {
    return {
      tone: local.issues.length ? "warn" : "idle",
      badge: L("점검 중", "Checking"),
      summary: L("샘플 프레임으로 ROI 상태를 다시 점검하고 있습니다.", "Rechecking ROI status using sampled frames."),
      items: local.issues.length
        ? local.issues.map((text) => ({ tone: "warning", text }))
        : [{ tone: "info", text: L("샘플 프레임을 불러오는 중입니다. 잠시 후 경계 위험을 표시합니다.", "Loading sample frames. Boundary risk will appear shortly.") }],
      backendHint: L("샘플 프레임 점검 중입니다.", "Checking sampled frames."),
      cropSummary: L(`현재 선택 영역 ${local.rectWidth}px x ${local.rectHeight}px`, `Current selection ${local.rectWidth}px x ${local.rectHeight}px`),
      zoomSummary: L("ROI 바깥 여유 공간까지 함께 보여줍니다. 경계가 너무 바짝 붙지 않았는지 확인하세요.", "Shows the outer margin around the ROI. Check that the boundary is not too tight."),
      metrics: fallbackMetrics,
    };
  }

  if (currentRoiHealthReport.status === "error") {
    return {
      tone: local.issues.length ? "warn" : "idle",
      badge: L("재확인 필요", "Recheck"),
      summary: local.issues.length ? L(`현재 화면 기준으로 확인할 포인트가 ${local.issues.length}개 있습니다.`, `${local.issues.length} points need attention in the current frame.`) : L("샘플 프레임 점검에 실패해 현재 화면 기준 안내만 표시합니다.", "Sample-frame diagnostics failed, so only current-frame guidance is shown."),
      items: [
        ...local.issues.map((text) => ({ tone: "warning", text })),
        { tone: "info", text: L(`샘플 프레임 점검 실패: ${currentRoiHealthReport.message}`, `Sample-frame diagnostics failed: ${currentRoiHealthReport.message}`) },
      ],
      backendHint: L("샘플 프레임 점검을 완료하지 못했습니다.", "Could not complete sample-frame diagnostics."),
      cropSummary: L(`현재 선택 영역 ${local.rectWidth}px x ${local.rectHeight}px`, `Current selection ${local.rectWidth}px x ${local.rectHeight}px`),
      zoomSummary: L("ROI 바깥 여유 공간까지 함께 보여줍니다. 경계가 너무 바짝 붙지 않았는지 확인하세요.", "Shows the outer margin around the ROI. Check that the boundary is not too tight."),
      metrics: fallbackMetrics,
    };
  }

  const hasIssue = local.issues.length > 0;
  return {
    tone: hasIssue ? "warn" : "ready",
    badge: hasIssue ? L("조정 권장", "Adjust") : L("실행 준비", "Ready"),
    summary: hasIssue ? L(`현재 화면 기준으로 확인할 포인트가 ${local.issues.length}개 있습니다.`, `${local.issues.length} points need attention in the current frame.`) : L("현재 ROI는 무난해 보입니다. 샘플 프레임 점검을 기다립니다.", "The current ROI looks fine. Waiting for sample-frame diagnostics."),
    items: hasIssue
      ? local.issues.map((text) => ({ tone: "warning", text }))
      : [{ tone: "ready", text: L("현재 화면 기준으로는 즉시 눈에 띄는 잘림 위험이 보이지 않습니다.", "No obvious clipping risk is visible in the current frame.") }],
    backendHint: L("샘플 프레임 기준 ROI 점검을 준비합니다.", "Preparing ROI diagnostics using sample frames."),
    cropSummary: L(`현재 선택 영역 ${local.rectWidth}px x ${local.rectHeight}px`, `Current selection ${local.rectWidth}px x ${local.rectHeight}px`),
    zoomSummary: L("ROI 바깥 여유 공간까지 함께 보여줍니다. 경계가 너무 바짝 붙지 않았는지 확인하세요.", "Shows the outer margin around the ROI. Check that the boundary is not too tight."),
    metrics: fallbackMetrics,
  };
}

function renderRoiAssist(snapshot) {
  currentRoiSnapshot = snapshot;
  const ui = roiElements();
  const healthState = buildRoiHealthState(snapshot);
  setRoiHealthVisual(healthState);
  if (ui.cropSummary) {
    ui.cropSummary.textContent = healthState.cropSummary;
  }
  if (ui.zoomSummary) {
    ui.zoomSummary.textContent = healthState.zoomSummary;
  }
  renderRoiMetricPills(healthState.metrics);

  if (!snapshot?.hasImage || !snapshot.imageReady || !snapshot.imageElement) {
    drawAssistPlaceholder(ui.cropCanvas, L("선택 영역", "Selection"), healthState.cropSummary);
    drawAssistPlaceholder(ui.zoomCanvas, L("확대 보조", "Zoom Helper"), healthState.zoomSummary);
    refreshCaptureWorkflowUi();
    return;
  }

  if (!snapshot.rect) {
    drawAssistPlaceholder(ui.cropCanvas, L("선택 영역", "Selection"), L("ROI를 지정하면 이곳에 악보 부분만 크게 보입니다.", "After you set the ROI, the selected score area appears enlarged here."));
    drawAssistPlaceholder(ui.zoomCanvas, L("확대 보조", "Zoom Helper"), L("ROI를 지정하면 주변 여백까지 함께 확대해 보여줍니다.", "After you set the ROI, the surrounding margin appears enlarged here."));
    refreshCaptureWorkflowUi();
    return;
  }

  drawImageIntoCanvas(ui.cropCanvas, snapshot.imageElement, {
    sx: snapshot.rect.x1,
    sy: snapshot.rect.y1,
    sw: Math.max(1, snapshot.rect.x2 - snapshot.rect.x1),
    sh: Math.max(1, snapshot.rect.y2 - snapshot.rect.y1),
  });

  const rectWidth = snapshot.rect.x2 - snapshot.rect.x1;
  const rectHeight = snapshot.rect.y2 - snapshot.rect.y1;
  const padX = Math.max(16, Math.round(rectWidth * 0.18));
  const padY = Math.max(16, Math.round(rectHeight * 0.18));
  const sx = Math.max(0, snapshot.rect.x1 - padX);
  const sy = Math.max(0, snapshot.rect.y1 - padY);
  const ex = Math.min(snapshot.canvasWidth, snapshot.rect.x2 + padX);
  const ey = Math.min(snapshot.canvasHeight, snapshot.rect.y2 + padY);
  const sw = Math.max(1, ex - sx);
  const sh = Math.max(1, ey - sy);
  const zoomPrepared = prepareAssistCanvas(ui.zoomCanvas);
  if (zoomPrepared) {
    const overlayRect = {
      x: ((snapshot.rect.x1 - sx) / sw) * zoomPrepared.width,
      y: ((snapshot.rect.y1 - sy) / sh) * zoomPrepared.height,
      w: (rectWidth / sw) * zoomPrepared.width,
      h: (rectHeight / sh) * zoomPrepared.height,
    };
    drawImageIntoCanvas(
      ui.zoomCanvas,
      snapshot.imageElement,
      { sx, sy, sw, sh },
      { overlayRect },
    );
  }

  refreshCaptureWorkflowUi();
}

function toNumberOrNull(raw) {
  const text = String(raw ?? "").trim();
  if (text === "") {
    return null;
  }
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function formatSecToMmss(sec) {
  if (!Number.isFinite(sec) || sec == null || sec < 0) {
    return "-";
  }
  const safe = Math.max(0, Number(sec));
  const min = Math.floor(safe / 60);
  const rem = safe - min * 60;
  return `${String(min).padStart(2, "0")}:${rem.toFixed(1).padStart(4, "0")}`;
}

function nowTimeLabel() {
  const now = new Date();
  return now.toLocaleTimeString(getLocale() === "ko" ? "ko-KR" : "en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function appendSetupLogLine(text) {
  const logNode = el("setupLog");
  if (!logNode) {
    return;
  }
  const line = String(text || "").trim();
  if (!line) {
    return;
  }
  const merged = `${logNode.textContent}\n[${nowTimeLabel()}] ${line}`.trim();
  const maxLines = 140;
  const rows = merged.split("\n");
  logNode.textContent = rows.length > maxLines ? rows.slice(rows.length - maxLines).join("\n") : merged;
  logNode.scrollTop = logNode.scrollHeight;
}

function compactErrorText(raw, fallback = null) {
  const value = String(raw || "").trim();
  if (!value) {
    return fallback || L("오류 원인을 확인하지 못했습니다.", "Could not determine the cause of the error.");
  }
  return value.length > 180 ? `${value.slice(0, 177)}...` : value;
}

function renderBackendBridgeState() {
  const chip = el("backendBridgeChip");
  const text = el("backendBridgeText");
  const setupButton = el("runGuidedSetup");
  const restartButton = el("restartBackend");
  const clearCacheButton = el("clearCacheFiles");

  if (!chip || !text) {
    return;
  }

  chip.classList.remove("setup-chip-ok", "setup-chip-running", "setup-chip-warn", "setup-chip-error");

  if (setupRunning || backendBridgeState.setupRunning) {
    chip.classList.add("setup-chip-running");
    chip.textContent = getLocale() === "ko" ? "설치/복구 진행 중" : "Repair running";
    text.textContent = getLocale() === "ko" ? "자동 설치/복구가 진행 중입니다. 완료될 때까지 잠시만 기다려 주세요." : "Automatic setup/repair is running. Please wait until it finishes.";
  } else if (backendBridgeState.ready) {
    chip.classList.add("setup-chip-ok");
    chip.textContent = getLocale() === "ko" ? "엔진 연결 완료" : "Engine ready";
    text.textContent = getLocale() === "ko" ? "로컬 처리 엔진이 정상 연결되었습니다. 바로 작업을 시작할 수 있어요." : "The local processing engine is connected and ready.";
  } else if (backendBridgeState.starting) {
    chip.classList.add("setup-chip-running");
    chip.textContent = getLocale() === "ko" ? "엔진 시작 중" : "Starting engine";
    text.textContent = getLocale() === "ko" ? "로컬 처리 엔진을 시작하고 있습니다. 잠시 후 자동으로 연결됩니다." : "Starting the local engine. It should connect automatically shortly.";
  } else if (backendBridgeState.error) {
    chip.classList.add("setup-chip-error");
    chip.textContent = getLocale() === "ko" ? "엔진 연결 실패" : "Engine error";
    text.textContent = compactErrorText(
      backendBridgeState.error,
      getLocale() === "ko" ? "엔진 연결에 실패했습니다. 자동 설치/복구를 눌러 복구해 주세요." : "Failed to connect to the engine. Use auto setup/repair to recover.",
    );
  } else {
    chip.classList.add("setup-chip-warn");
    chip.textContent = getLocale() === "ko" ? "엔진 대기" : "Engine waiting";
    text.textContent = getLocale() === "ko" ? "로컬 처리 엔진이 아직 연결되지 않았습니다. 백엔드 다시 연결 또는 설치/복구를 눌러 주세요." : "The local engine is not connected yet. Try reconnecting the backend or running auto setup/repair.";
  }

  if (setupButton) {
    setupButton.disabled = setupRunning || backendBridgeState.setupRunning;
    setupButton.textContent =
      setupRunning || backendBridgeState.setupRunning
        ? (getLocale() === "ko" ? "설치/복구 진행 중..." : "Repair running...")
        : (getLocale() === "ko" ? "자동 설치/복구" : "Auto Setup/Repair");
  }
  if (restartButton) {
    restartButton.disabled = setupRunning || backendBridgeState.setupRunning || backendBridgeState.starting;
  }
  if (clearCacheButton) {
    const disabled =
      setupRunning ||
      backendBridgeState.setupRunning ||
      backendBridgeState.starting ||
      !backendBridgeState.ready ||
      runState === "running" ||
      reviewApplyRunning ||
      cacheClearRunning;
    clearCacheButton.disabled = disabled;
    if (cacheClearRunning) {
      clearCacheButton.textContent = getLocale() === "ko" ? "캐시 정리 중..." : "Clearing cache...";
    } else if (cacheUsageLoading && !cacheUsageText) {
      clearCacheButton.textContent = getLocale() === "ko" ? "캐시 용량 확인 중..." : "Checking cache size...";
    } else if (cacheUsageText) {
      clearCacheButton.textContent = getLocale() === "ko" ? `캐시 정리 (${cacheUsageText})` : `Clear Cache (${cacheUsageText})`;
    } else {
      clearCacheButton.textContent = getLocale() === "ko" ? "캐시 정리" : "Clear Cache";
    }
  }
}

function refreshAlwaysOnTopButton() {
  const button = el("toggleAlwaysOnTop");
  if (!button) {
    return;
  }
  button.textContent = alwaysOnTopEnabled
    ? (getLocale() === "ko" ? "창 고정: 켬" : "Pin Window: On")
    : (getLocale() === "ko" ? "창 고정: 끔" : "Pin Window: Off");
}

async function syncAlwaysOnTopState() {
  if (!window.drumSheetAPI || typeof window.drumSheetAPI.getAlwaysOnTop !== "function") {
    return;
  }
  try {
    alwaysOnTopEnabled = Boolean(await window.drumSheetAPI.getAlwaysOnTop());
  } catch (_) {
    alwaysOnTopEnabled = false;
  }
  refreshAlwaysOnTopButton();
}

async function onToggleAlwaysOnTop() {
  if (!window.drumSheetAPI || typeof window.drumSheetAPI.setAlwaysOnTop !== "function") {
    return;
  }
  try {
    alwaysOnTopEnabled = Boolean(await window.drumSheetAPI.setAlwaysOnTop(!alwaysOnTopEnabled));
    refreshAlwaysOnTopButton();
    appendLocaleLog(
      alwaysOnTopEnabled ? "연습 고정 켬: 창을 항상 위에 유지합니다." : "연습 고정 끔",
      alwaysOnTopEnabled ? "Pin window enabled: the app stays above other windows." : "Pin window disabled.",
    );
  } catch (_) {
    appendLocaleError(L("창 고정 상태를 바꾸지 못했습니다.", "Could not change the pin-window state."));
  }
}

async function refreshCacheUsage({ force = false } = {}) {
  if (!backendBridgeState.ready || cacheClearRunning) {
    return;
  }
  const now = Date.now();
  if (!force && now - lastCacheUsageFetchAt < 8000) {
    return;
  }
  lastCacheUsageFetchAt = now;
  try {
    cacheUsageLoading = true;
    renderBackendBridgeState();
    const usage = await getCacheUsage(API_BASE);
    const totalBytes = Number(usage?.total_bytes || 0);
    const totalHuman = String(usage?.total_human || "0 B");
    cacheUsageText = totalBytes > 0 ? L(`약 ${totalHuman}`, `about ${totalHuman}`) : L("약 0 B", "about 0 B");
  } catch (_) {
    cacheUsageText = "";
  } finally {
    cacheUsageLoading = false;
    renderBackendBridgeState();
  }
}

async function refreshBackendBridgeState() {
  if (!window.drumSheetAPI || typeof window.drumSheetAPI.getBackendState !== "function") {
    return;
  }
  try {
    const wasReady = backendBridgeState.ready;
    const state = await window.drumSheetAPI.getBackendState();
    backendBridgeState = {
      ready: Boolean(state?.ready),
      starting: Boolean(state?.starting),
      running: Boolean(state?.running),
      error: String(state?.error || ""),
      setupRunning: Boolean(state?.setupRunning),
    };
    renderBackendBridgeState();
    if (backendBridgeState.ready) {
      void refreshCacheUsage();
      if (!wasReady || !latestRuntime) {
        void refreshRuntimeStatus({ force: true, syncBackendStateOnFailure: false });
      }
    }
    refreshCaptureWorkflowUi();
  } catch (error) {
    appendLocaleSetupError(L(
      `엔진 상태 확인 실패 (${compactErrorText(error?.message)})`,
      `Failed to check engine status (${compactErrorText(error?.message)})`,
    ));
  }
}

async function onRunGuidedSetup() {
  if (!window.drumSheetAPI || typeof window.drumSheetAPI.runGuidedSetup !== "function") {
    appendLocaleSetupError(L(
      "현재 앱에서 자동 설치/복구 기능을 지원하지 않습니다.",
      "This app build does not support auto setup/repair.",
    ));
    return;
  }
  if (setupRunning) {
    return;
  }

  const proceed = window.confirm(
    L(
      "자동 설치/복구를 시작할까요?\n\n백엔드를 잠시 멈추고 Python/패키지/npm 상태를 자동으로 정리합니다.",
      "Start automatic setup/repair?\n\nThis temporarily stops the backend and repairs Python, packages, and npm state automatically.",
    ),
  );
  if (!proceed) {
    return;
  }

  try {
    setupRunning = true;
    renderBackendBridgeState();
    refreshCaptureWorkflowUi();
    appendLocaleSetupLog("자동 설치/복구 요청", "Auto setup/repair requested");
    const result = await window.drumSheetAPI.runGuidedSetup();
    if (result?.ok) {
      appendLocaleSetupLog("설치/복구 완료", "Setup/repair completed");
      appendLocaleLog("설치/복구 완료: 로컬 엔진이 다시 연결되었습니다.", "Setup/repair completed: the local engine reconnected.");
      await refreshRuntimeStatus();
    } else {
      const message = compactErrorText(result?.error, L("설치/복구 작업이 실패했습니다.", "Setup/repair failed."));
      appendLocaleSetupError(message);
      appendLocaleError(L(`설치/복구 실패 (${message})`, `Setup/repair failed (${message})`));
    }
  } catch (error) {
    const message = compactErrorText(error?.message, L("설치/복구 실행 실패", "Failed to run setup/repair."));
    appendLocaleSetupError(message);
    appendLocaleError(message);
  } finally {
    setupRunning = false;
    await refreshBackendBridgeState();
    refreshCaptureWorkflowUi();
  }
}

async function onRestartBackend() {
  if (!window.drumSheetAPI || typeof window.drumSheetAPI.restartBackend !== "function") {
    appendLocaleSetupError(L("백엔드 다시 연결 기능을 지원하지 않습니다.", "Reconnect-backend is not supported in this app build."));
    return;
  }

  try {
    appendLocaleSetupLog("백엔드 다시 연결 요청", "Reconnect backend requested");
    const result = await window.drumSheetAPI.restartBackend();
    if (result?.ok) {
      appendLocaleSetupLog("백엔드 연결 성공", "Backend reconnected");
      await refreshRuntimeStatus();
    } else {
      appendLocaleSetupError(compactErrorText(result?.error, L("백엔드 다시 연결 실패", "Failed to reconnect backend.")));
    }
  } catch (error) {
    appendLocaleSetupError(compactErrorText(error?.message, L("백엔드 다시 연결 실패", "Failed to reconnect backend.")));
  } finally {
    await refreshBackendBridgeState();
    refreshCaptureWorkflowUi();
  }
}

async function onClearCacheFiles() {
  if (cacheClearRunning) {
    return;
  }
  const usageHint = cacheUsageText ? `\n현재 임시 파일: ${cacheUsageText}` : "";
  const proceed = window.confirm(
    L(
      `캐시/결과 파일을 정리할까요?\n\n이전 악보 추출 결과와 중간 파일이 삭제됩니다.${usageHint}\n이 작업은 되돌릴 수 없습니다.`,
      `Clear cache and generated files?\n\nPrevious export results and temporary files will be deleted.${cacheUsageText ? `\nCurrent temporary files: ${cacheUsageText}` : ""}\nThis cannot be undone.`,
    ),
  );
  if (!proceed) {
    return;
  }

  try {
    cacheClearRunning = true;
    renderBackendBridgeState();
    appendLocaleSetupLog("캐시 정리 요청", "Cache clear requested");
    const result = await clearCache(API_BASE);
    const reclaimed = String(result?.reclaimed_human || "0 B");
    const clearedPaths = Number(result?.cleared_paths || 0);
    const skipped = Array.isArray(result?.skipped_paths) ? result.skipped_paths.length : 0;
    appendLocaleSetupLog(
      `캐시 정리 완료: 항목 ${clearedPaths}개, 확보 용량 ${reclaimed}${skipped > 0 ? `, 건너뜀 ${skipped}개` : ""}`,
      `Cache cleared: ${clearedPaths} items, reclaimed ${reclaimed}${skipped > 0 ? `, skipped ${skipped}` : ""}`,
    );
    appendLocaleLog(`캐시 정리 완료: ${reclaimed} 확보`, `Cache cleared: reclaimed ${reclaimed}`);
    setStatus(statusText("캐시 정리 완료", "Cache cleared"));
    cacheUsageText = L("약 0 B", "about 0 B");
    resetResultView();
  } catch (error) {
    appendLocaleSetupError(compactErrorText(error?.message, L("캐시 정리 실패", "Failed to clear cache.")));
    appendLocaleError(error.message);
    setStatus(statusText("캐시 정리 실패", "Cache clear failed"));
  } finally {
    cacheClearRunning = false;
    renderBackendBridgeState();
    void refreshCacheUsage({ force: true });
    refreshCaptureWorkflowUi();
  }
}

function getRangeValues() {
  return {
    start: toNumberOrNull(el("startSec")?.value),
    end: toNumberOrNull(el("endSec")?.value),
  };
}

function isSourceReady() {
  if (sourceType() === "file") {
    return Boolean(String(el("filePath")?.value || "").trim());
  }
  return Boolean(String(el("youtubeUrl")?.value || "").trim());
}

function currentSourceFingerprint() {
  const type = sourceType();
  const value = type === "file" ? String(el("filePath")?.value || "").trim() : String(el("youtubeUrl")?.value || "").trim();
  return `${type}:${value}`;
}

function isRangeValid() {
  const { start, end } = getRangeValues();
  if (start != null && end != null && end <= start) {
    return false;
  }
  return true;
}

function isRoiReady() {
  const parsed = parseJsonOrNull(String(el("roiInput")?.value || ""));
  if (!Array.isArray(parsed) || parsed.length !== 4) {
    return false;
  }
  return parsed.every((point) => Array.isArray(point) && point.length === 2 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])));
}

function isExportReady() {
  return getFormats().length > 0;
}

function sourceSummaryText() {
  if (sourceType() === "file") {
    const value = String(el("filePath")?.value || "").trim();
    return value
      ? (getLocale() === "ko" ? `선택됨: ${pathBaseName(value)}` : `Selected: ${pathBaseName(value)}`)
      : (getLocale() === "ko" ? "영상 파일을 골라주세요" : "Choose a video file");
  }
  const value = String(el("youtubeUrl")?.value || "").trim();
  return value ? (getLocale() === "ko" ? "URL 입력됨" : "URL entered") : (getLocale() === "ko" ? "유튜브 주소를 넣어주세요" : "Paste a YouTube URL");
}

function rangeSummaryText() {
  const { start, end } = getRangeValues();
  if (!isRangeValid()) {
    return getLocale() === "ko" ? "시작/끝 확인 필요" : "Check start/end";
  }
  if (start == null && end == null) {
    return getLocale() === "ko" ? "전체 구간 (권장)" : "Full range (recommended)";
  }
  const startText = start == null ? (getLocale() === "ko" ? "시작" : "Start") : formatSecToMmss(start);
  const endText = end == null ? (getLocale() === "ko" ? "끝" : "End") : formatSecToMmss(end);
  return `${startText}~${endText}`;
}

function roiSummaryText() {
  if (!isRoiReady()) {
    return getLocale() === "ko" ? "악보 영역 지정 필요" : "ROI needed";
  }
  if (currentRoiHealth.tone === "warn") {
    return getLocale() === "ko" ? "영역 지정됨 · 조정 권장" : "ROI set · adjust recommended";
  }
  if (currentRoiHealth.tone === "ready") {
    return getLocale() === "ko" ? "실행 전 점검 완료" : "Checked before run";
  }
  return getLocale() === "ko" ? "영역 지정 완료" : "ROI set";
}

function presetLabel(name = currentPreset) {
  if (name === "scroll") {
    return getLocale() === "ko" ? "스크롤 맞춤" : "Scroll";
  }
  if (name === "quality") {
    return getLocale() === "ko" ? "선명도 우선" : "Quality";
  }
  return getLocale() === "ko" ? "연주 기본" : "Basic";
}

function exportSummaryText() {
  const formats = getFormats();
  const label = formats.length ? formats.join("/").toUpperCase() : (getLocale() === "ko" ? "형식 미선택" : "No format");
  return `${label} · ${presetLabel(currentPreset)}`;
}

function stepLabel(key) {
  if (key === "roi") {
    return L("ROI 지정", "ROI");
  }
  if (key === "export") {
    return L("저장/내보내기", "Export");
  }
  return L("소스 선택", "Source");
}

function stepOrdinalLabel(key) {
  const order = STEP_KEYS.indexOf(key) + 1;
  return L(`${order}단계 · ${stepLabel(key)}`, `Step ${order} · ${stepLabel(key)}`);
}

function stepVisualState(key, progressStep, completion) {
  if (completion[key]) {
    return "done";
  }
  if (key === "roi" && progressStep === "roi" && currentPreviewFrame.imagePath) {
    return "active";
  }
  return "need";
}

function stepStateLabel({ key, progressStep, completion }) {
  const state = stepVisualState(key, progressStep, completion);
  if (state === "done") {
    return L("완료", "Done");
  }
  if (state === "active") {
    return L("진행 중", "In progress");
  }
  return L("확인 필요", "Needs attention");
}

function stepTone({ key, progressStep, completion }) {
  const state = stepVisualState(key, progressStep, completion);
  if (state === "done") {
    return "ready";
  }
  if (state === "active") {
    return "warn";
  }
  return "info";
}

function currentSourceDisplayText() {
  if (!isSourceReady()) {
    return L("선택되지 않음", "Not selected");
  }
  if (sourceType() === "youtube") {
    const url = String(el("youtubeUrl")?.value || "").trim();
    return truncateMiddle(url || L("유튜브 영상", "YouTube video"), 44);
  }
  return pathBaseName(String(el("filePath")?.value || "")) || L("로컬 파일", "Local file");
}

function countReviewCandidates() {
  return buildResultEntries().filter((entry) => entry.suspicious).length;
}

function contextSummaryModel(activeStep) {
  const reviewCount = countReviewCandidates();
  if (activeStep === "roi") {
    return {
      title: L("ROI 작업대", "ROI workspace"),
      copy: L(
        "대표 프레임에서 악보 전체가 들어오도록 ROI를 잡고, 오른쪽 요약으로 경계 위험을 확인합니다.",
        "Draw the ROI around the full score on the representative frame and confirm boundary risk in the summary.",
      ),
    };
  }
  if (activeStep === "export") {
    return {
      title: L("내보내기 준비", "Export setup"),
      copy: reviewCount > 0
        ? L("형식을 고른 뒤 실행합니다. 결과가 나오면 검토 필요 배지를 우선 확인합니다.", "Choose formats and run. After output appears, review the flagged pages first.")
        : L("형식과 프리셋을 확인한 뒤 바로 실행할 수 있습니다.", "Confirm formats and preset, then run immediately."),
    };
  }
  return {
    title: L("소스 준비", "Source setup"),
    copy: L(
      "파일을 선택하거나 YouTube 주소를 붙여넣고, 대표 프레임을 열어 다음 단계로 넘어갑니다.",
      "Choose a file or paste a YouTube URL, then open a representative frame for the next step.",
    ),
  };
}

function determineActiveStep() {
  if (!isSourceReady()) {
    return "source";
  }
  if (!isRangeValid()) {
    return "roi";
  }
  if (!isRoiReady()) {
    return "roi";
  }
  return "export";
}

function setStepText(key, text) {
  const cardSummary = el(STEP_CARD_SUMMARY_IDS[key]);
  const barSummary = el(STEP_BAR_SUMMARY_IDS[key]);
  if (cardSummary) {
    cardSummary.textContent = text;
  }
  if (barSummary) {
    barSummary.textContent = text;
  }
}

function setStepSummaryTone(key, tone = "need") {
  const cardSummary = el(STEP_CARD_SUMMARY_IDS[key]);
  if (!cardSummary) {
    return;
  }
  cardSummary.classList.remove("is-ready", "is-need", "is-alert");
  cardSummary.classList.add(`is-${tone}`);
}

function setStepVisual(key, { done, active }) {
  const button = el(STEP_BAR_BUTTON_IDS[key]);
  if (button) {
    button.classList.toggle("stepper-item-done", done);
    button.classList.toggle("stepper-item-active", active);
  }
}

function getOpenedStepFromDetails() {
  for (const key of STEP_KEYS) {
    const details = el(STEP_DETAIL_IDS[key]);
    if (details?.open) {
      return key;
    }
  }
  return null;
}

function openStep(key) {
  STEP_KEYS.forEach((candidate) => {
    const details = el(STEP_DETAIL_IDS[candidate]);
    if (!details) {
      return;
    }
    details.open = candidate === key;
  });
}

function scrollToElement(id, block = "center") {
  const node = el(id);
  node?.scrollIntoView({ behavior: "smooth", block });
}

function focusSourceEntry({ openPicker = false } = {}) {
  manualOpenStep = "source";
  refreshCaptureWorkflowUi();
  scrollToElement("stepSourceDetails");
  if (sourceType() === "file") {
    if (openPicker) {
      el("browseFile")?.click();
    } else {
      el("browseFile")?.focus();
    }
    return;
  }
  const youtubeInput = el("youtubeUrl");
  youtubeInput?.focus();
  youtubeInput?.select?.();
}

function guideToIncompleteStep() {
  if (!backendBridgeState.ready) {
    openSupportPanel();
    requestAnimationFrame(() => {
      el("runGuidedSetup")?.focus();
    });
    return;
  }
  if (!isSourceReady()) {
    focusSourceEntry({ openPicker: true });
    return;
  }
  if (!isRangeValid() || !isRoiReady()) {
    manualOpenStep = "roi";
    refreshCaptureWorkflowUi();
    scrollToElement(currentPreviewFrame.imagePath ? "roiEditorWrap" : "loadPreviewForRoi");
    if (!currentPreviewFrame.imagePath) {
      el("loadPreviewForRoi")?.focus();
    }
    return;
  }
  if (!isExportReady()) {
    manualOpenStep = "export";
    refreshCaptureWorkflowUi();
    scrollToElement("stepExportDetails");
  }
}

function updateCaptureEntryActions() {
  const copySourcePathButton = el("copySourcePath");
  if (copySourcePathButton) {
    copySourcePathButton.disabled = !isSourceReady();
  }
}

function updateCaptureLayoutState() {
  const hasSource = isSourceReady();
  const hasResult = Boolean(outputDir || outputPdf || resultImagePaths.length);
  const resultCard = document.querySelector(".result-card");
  const shell = el("appShell");
  const reviewCount = countReviewCandidates();

  document.body.classList.toggle("capture-has-source", hasSource);
  document.body.classList.toggle("capture-needs-setup", !backendBridgeState.ready);
  if (shell) {
    shell.dataset.hasResult = hasResult ? "true" : "false";
    shell.dataset.hasReview = reviewCount > 0 ? "true" : "false";
    shell.dataset.statusDrawerOpen = statusDrawerOpen ? "true" : "false";
    shell.dataset.supportOpen = supportSheetOpen ? "true" : "false";
  }
  if (resultCard) {
    resultCard.hidden = !hasResult;
  }
}

function renderHeaderState(progressStep, completion) {
  const sourceLabel = el("headerSourceLabel");
  const sourceValue = el("headerSourceValue");
  const stageLabel = el("headerStageLabel");
  const stageValue = el("headerStageValue");
  const stageChip = el("headerStageChip");
  const helpButton = el("openSupportPanel");

  if (sourceLabel) {
    sourceLabel.textContent = L("현재 소스", "Current source");
  }
  if (sourceValue) {
    sourceValue.textContent = currentSourceDisplayText();
  }
  if (stageLabel) {
    stageLabel.textContent = L("현재 단계", "Current step");
  }
  if (stageValue) {
    stageValue.textContent = stepOrdinalLabel(progressStep);
  }
  if (stageChip) {
    stageChip.textContent = stepStateLabel({ key: progressStep, progressStep, completion });
    stageChip.dataset.tone = stepTone({ key: progressStep, progressStep, completion });
  }
  if (helpButton) {
    helpButton.dataset.alert = !backendBridgeState.ready ? "true" : "false";
    helpButton.setAttribute("aria-expanded", supportSheetOpen ? "true" : "false");
  }
}

function renderStepRail(progressStep, activeStep, completion) {
  const reviewBadge = el("stepReviewBadge");
  const reviewCount = countReviewCandidates();
  if (reviewBadge) {
    reviewBadge.hidden = reviewCount <= 0;
    reviewBadge.textContent = reviewCount > 0
      ? L(`검토 필요 ${reviewCount}개`, `${reviewCount} review items`)
      : "";
  }

  STEP_KEYS.forEach((key) => {
    const button = el(STEP_BAR_BUTTON_IDS[key]);
    if (!button) {
      return;
    }
    button.dataset.state = stepVisualState(key, progressStep, completion);
    button.setAttribute("aria-current", key === activeStep ? "step" : "false");
  });
}

function renderInspectorState(activeStep, progressStep, completion) {
  const title = el("contextSummaryTitle");
  const copy = el("contextSummaryCopy");
  const stepLabelNode = el("contextStepLabel");
  const stepStatusNode = el("contextStepStatus");
  const nextLabelNode = el("contextNextLabel");
  const nextActionNode = el("contextNextAction");
  const reviewLabelNode = el("contextReviewLabel");
  const reviewStatusNode = el("contextReviewStatus");
  const summary = contextSummaryModel(activeStep);
  const reviewCount = countReviewCandidates();
  const runButton = el("runJob");

  if (title) {
    title.textContent = summary.title;
  }
  if (copy) {
    copy.textContent = summary.copy;
  }
  if (stepLabelNode) {
    stepLabelNode.textContent = L("현재 단계", "Current step");
  }
  if (stepStatusNode) {
    stepStatusNode.textContent = `${stepOrdinalLabel(progressStep)} · ${stepStateLabel({ key: progressStep, progressStep, completion })}`;
  }
  if (nextLabelNode) {
    nextLabelNode.textContent = L("다음 행동", "Next action");
  }
  if (nextActionNode) {
    nextActionNode.textContent = runButton?.textContent || L("입력 확인", "Check input");
  }
  if (reviewLabelNode) {
    reviewLabelNode.textContent = L("결과 검토", "Result review");
  }
  if (reviewStatusNode) {
    reviewStatusNode.textContent = reviewCount > 0
      ? L(`검토 필요 ${reviewCount}개`, `${reviewCount} items need review`)
      : hasResultOutput()
        ? L("검토 경고 없음", "No flagged pages")
        : L("아직 없음", "Not available yet");
  }
}

function renderStatusDrawerState() {
  const summary = el("statusDrawerSummary");
  const toggle = el("toggleStatusDrawer");
  if (summary) {
    summary.textContent = el("runCtaHint")?.textContent || L("1단계에서 영상을 선택합니다.", "Start by selecting a video in step 1.");
  }
  if (toggle) {
    toggle.textContent = statusDrawerOpen ? L("상태 접기", "Hide details") : L("상태 펼치기", "Show details");
    toggle.setAttribute("aria-expanded", statusDrawerOpen ? "true" : "false");
  }
}

function renderSupportSheetState() {
  const sheet = el("supportSheet");
  if (!sheet) {
    return;
  }
  sheet.hidden = !supportSheetOpen;
  sheet.setAttribute("aria-hidden", supportSheetOpen ? "false" : "true");
}

function hasResultOutput() {
  return Boolean(outputDir || outputPdf || resultImagePaths.length);
}

function renderWorkLayoutState(progressStep = determineActiveStep(), activeStep = manualOpenStep || progressStep, completion = {
  source: isSourceReady(),
  roi: isRoiReady(),
  export: isExportReady(),
}) {
  const shell = el("appShell");
  if (shell) {
    shell.dataset.activeStep = activeStep;
    shell.dataset.stepState = stepVisualState(progressStep, progressStep, completion);
  }
  updateCaptureLayoutState();
  renderHeaderState(progressStep, completion);
  renderStepRail(progressStep, activeStep, completion);
  renderInspectorState(activeStep, progressStep, completion);
  renderStatusDrawerState();
  renderSupportSheetState();
}

function resetRoiForSourceChange({ silent = true } = {}) {
  previewRequestToken += 1;
  resetCurrentRoiHealthReport();
  setRoiFrameRequestState({ status: "idle", detail: "" });
  const roiInput = el("roiInput");
  const hadRoi = Boolean(String(roiInput?.value || "").trim());
  currentPreviewFrame = {
    imagePath: "",
    sourcePath: "",
    previewSecond: null,
    diagnostics: [],
  };
  currentRoiSnapshot = null;
  roiController.clearPreview();
  if (roiInput) {
    roiInput.value = "";
    roiInput.dispatchEvent(new Event("input", { bubbles: true }));
  } else {
    renderRoiAssist(null);
    refreshCaptureWorkflowUi();
  }
  if (!silent && hadRoi) {
    appendLocaleLog("입력 소스가 바뀌어 이전 악보 영역을 초기화했습니다.", "The source changed, so the previous ROI was cleared.");
  }
}

function resetForSourceChange({ silent = true } = {}) {
  previewRequestToken += 1;
  if (activePoll) {
    clearInterval(activePoll);
    activePoll = null;
  }

  runState = "idle";
  resetYoutubePrepareState();
  resetYoutubePrepareLogs();
  resetRoiForSourceChange({ silent });
  videoRangePicker.clearMedia();
  videoRangePicker.clearRangeState();
  resetResultView();
  manualOpenStep = "source";
  setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
  if (!silent) {
    appendLocaleLog("새로운 소스로 전환되어 기존 결과와 미리보기 상태를 초기화했습니다.", "Switched to a new source, so previous results and preview state were reset.");
  }
  setStatus(statusText("대기 중", "Idle"));
}

function updateRangeHumanLabels() {
  const { start, end } = getRangeValues();
  const startHuman = el("startHuman");
  const endHuman = el("endHuman");
  if (startHuman) {
    startHuman.textContent = `mm:ss ${formatSecToMmss(start)}`;
  }
  if (endHuman) {
    endHuman.textContent = `mm:ss ${formatSecToMmss(end)}`;
  }
}

function updateRunCta() {
  const runButton = el("runJob");
  const cancelButton = el("cancelRun");
  const hint = el("runCtaHint");
  const stickyOpenOutput = el("stickyOpenOutput");

  if (stickyOpenOutput) {
    stickyOpenOutput.disabled = !outputDir;
  }

  if (!runButton || !cancelButton || !hint) {
    return;
  }

  const ready = isSourceReady() && isRangeValid() && isRoiReady() && isExportReady();

  if (!backendBridgeState.ready) {
    runButton.textContent =
      setupRunning || backendBridgeState.setupRunning
        ? (getLocale() === "ko" ? "설치/복구 진행 중..." : "Repair running...")
        : (getLocale() === "ko" ? "먼저 엔진 연결이 필요해요" : "Engine connection required");
    runButton.disabled = true;
    cancelButton.style.display = "none";
    const errorText = compactErrorText(backendBridgeState.error, "");
    hint.textContent = errorText
      ? (getLocale() === "ko" ? `엔진 연결 문제: ${errorText}` : `Engine connection issue: ${errorText}`)
      : (getLocale() === "ko" ? "상단의 자동 설치/복구 또는 엔진 다시 연결 버튼을 눌러주세요." : "Use Auto Setup/Repair or Reconnect Engine above.");
    return;
  }

  if (runState === "running") {
    runButton.textContent = getLocale() === "ko" ? "처리 중..." : "Processing...";
    runButton.disabled = true;
    cancelButton.style.display = "inline-flex";
    hint.textContent = getLocale() === "ko" ? "처리 중입니다. 필요하면 중단 버튼으로 진행 조회를 멈출 수 있어요." : "Processing. You can stop status polling if needed.";
    return;
  }

  cancelButton.style.display = "none";

  if (runState === "done" && outputDir) {
    runButton.textContent = getLocale() === "ko" ? "다시 실행" : "Run Again";
    runButton.disabled = !isSourceReady();
    hint.textContent = getLocale() === "ko" ? "완료되었습니다. 결과 폴더를 열거나 다시 실행할 수 있어요." : "Done. Open the output folder or run again.";
    return;
  }

  if (!isSourceReady()) {
    runButton.textContent = sourceType() === "youtube" ? (getLocale() === "ko" ? "유튜브 주소 입력으로 시작" : "Start with YouTube URL") : (getLocale() === "ko" ? "영상 선택" : "Select Video");
    runButton.disabled = false;
    hint.textContent = sourceType() === "youtube"
      ? (getLocale() === "ko" ? "유튜브 주소를 붙여넣으면 다음 단계로 바로 넘어갈 수 있어요." : "Paste a YouTube URL to move directly to the next step.")
      : (getLocale() === "ko" ? "가장 먼저 영상만 고르세요. 나머지 설정은 뒤에서 맞춰도 됩니다." : "Start by choosing a video. The rest can be adjusted later.");
    return;
  }

  if (!isRangeValid()) {
    runButton.textContent = getLocale() === "ko" ? "처리 범위 다시 확인" : "Review Range";
    runButton.disabled = false;
    hint.textContent = getLocale() === "ko" ? "처리 범위를 줄이는 경우에는 끝 시간이 시작 시간보다 커야 합니다." : "If you limit the range, the end time must be later than the start time.";
    return;
  }

  if (!isRoiReady()) {
    runButton.textContent = currentPreviewFrame.imagePath ? (getLocale() === "ko" ? "악보 영역 저장으로 이동" : "Apply ROI and Continue") : (getLocale() === "ko" ? "악보 화면 열기" : "Open Score Frame");
    runButton.disabled = false;
    hint.textContent = getLocale() === "ko" ? "2단계에서 프레임을 열고, 악보 부분을 네모로 한 번만 잡아 주세요." : "Open a frame in step 2 and draw a single box around the score.";
    return;
  }

  if (!isExportReady()) {
    runButton.textContent = getLocale() === "ko" ? "출력 형식 선택" : "Choose Export Format";
    runButton.disabled = false;
    hint.textContent = getLocale() === "ko" ? "PNG/JPG/PDF 중 최소 하나를 선택해 주세요." : "Choose at least one export format: PNG, JPG, or PDF.";
    return;
  }

  runButton.textContent = ready ? (getLocale() === "ko" ? "처리 시작" : "Start Processing") : (getLocale() === "ko" ? "입력 확인 중" : "Checking Input");
  runButton.disabled = !ready;
  hint.textContent = getLocale() === "ko" ? "준비 완료. 처리 시작을 누르면 바로 진행됩니다." : "Ready. Processing starts immediately when you click Start Processing.";
}

function refreshCaptureWorkflowUi() {
  updateRangeHumanLabels();
  updateCaptureEntryActions();

  const completion = {
    source: isSourceReady(),
    roi: isRoiReady(),
    export: isExportReady(),
  };

  setStepText("source", sourceSummaryText());
  setStepText("roi", roiSummaryText());
  setStepText("export", exportSummaryText());
  setStepSummaryTone("source", completion.source ? "ready" : "need");
  setStepSummaryTone("roi", completion.roi ? "ready" : "need");
  setStepSummaryTone("export", completion.export ? "ready" : "need");

  const progressStep = determineActiveStep();
  if (!manualOpenStep) {
    manualOpenStep = getOpenedStepFromDetails() || "source";
  }
  const activeStep = manualOpenStep;

  STEP_KEYS.forEach((key) => {
    const isDone = completion[key] && STEP_KEYS.indexOf(key) < STEP_KEYS.indexOf(progressStep);
    setStepVisual(key, { done: isDone, active: key === activeStep });
  });

  openStep(activeStep);
  updateRunCta();
  renderWorkLayoutState(progressStep, activeStep, completion);
}

function updateSourceRows() {
  const currentType = sourceType();
  const isFile = currentType === "file";
  const isYoutube = currentType === "youtube";
  const currentFingerprint = currentSourceFingerprint();
  if (currentFingerprint !== lastSourceFingerprint) {
    resetForSourceChange({ silent: true });
  } else if (currentType !== lastSourceType) {
    videoRangePicker.clearMedia();
    resetRoiForSourceChange({ silent: true });
  }
  lastSourceType = currentType;
  lastSourceFingerprint = currentFingerprint;
  const fileRow = el("fileRow");
  const youtubeRow = el("youtubeRow");
  if (fileRow) {
    fileRow.style.display = isFile ? "flex" : "none";
  }
  if (youtubeRow) {
    youtubeRow.style.display = isFile ? "none" : "flex";
  }
  const youtubeTools = el("youtubePrepareTools");
  if (youtubeTools) {
    youtubeTools.style.display = isYoutube ? "flex" : "none";
  }
  renderYoutubePrepareState();
  videoRangePicker.onSourceTypeChange();
  refreshCaptureWorkflowUi();
}

function updateManualTools() {
  const tools = el("manualRoiTools");
  if (tools) {
    tools.style.display = "flex";
  }
  refreshCaptureWorkflowUi();
}

function updateCaptureSensitivityHelp() {
  const select = el("captureSensitivity");
  const help = el("captureSensitivityHelp");
  if (!select || !help) {
    return;
  }

  const map = {
    low: getLocale() === "ko" ? "같은 장면이 반복 저장되는 것을 강하게 줄입니다. 대부분 이 옵션이 깔끔합니다." : "Strongly reduces repeated captures of the same scene. Cleanest in most cases.",
    medium: getLocale() === "ko" ? "균형형 옵션입니다. 처음 사용할 때 추천합니다." : "Balanced option. Recommended when you are using the app for the first time.",
    high: getLocale() === "ko" ? "미세한 변화까지 민감하게 잡습니다. 대신 비슷한 장면이 더 많이 저장될 수 있습니다." : "Captures even small changes, but may keep more near-duplicate scenes.",
  };
  help.textContent = map[select.value] || map.medium;
}

function updateUpscaleUi() {
  const toggle = el("enableUpscale");
  const factor = el("upscaleFactor");
  const hint = el("upscaleHint");
  if (!toggle || !factor || !hint) {
    return;
  }

  if (toggle.disabled) {
    factor.disabled = true;
    hint.textContent = getLocale() === "ko" ? "현재 환경에서 업스케일 엔진을 찾지 못해 사용할 수 없습니다." : "No usable upscaling engine was found in the current environment.";
    return;
  }

  const engineHint = String(latestRuntime?.upscale_engine_hint || "").toLowerCase();
  const engineName =
    engineHint === "hat"
      ? "HAT (Transformer SR)"
      : engineHint === "ffmpeg_scale_vt"
        ? "FFmpeg scale_vt (Metal)"
        : engineHint === "opencv_cuda"
          ? "OpenCV CUDA"
            : engineHint === "opencv_opencl"
              ? "OpenCV OpenCL"
            : (getLocale() === "ko" ? "업스케일 엔진" : "Upscaling engine");
  factor.disabled = !toggle.checked;
  hint.textContent = toggle.checked
    ? (getLocale() === "ko" ? `업스케일은 ${engineName}으로 처리합니다. 엔진 경로가 실패하면 작업이 중단됩니다.` : `Upscaling uses ${engineName}. If the engine path fails, the job stops.`)
    : (getLocale() === "ko" ? `업스케일을 끄면 원본 해상도로 저장합니다. (사용 가능 엔진: ${engineName})` : `If upscaling is off, pages are saved at original resolution. (Available engine: ${engineName})`);
}

function applyUpscaleAvailability(runtime) {
  const toggle = el("enableUpscale");
  if (!toggle) {
    return;
  }
  const canUseGpuUpscale = runtime?.upscale_available === true;
  if (!canUseGpuUpscale) {
    toggle.checked = false;
    toggle.disabled = true;
    updateUpscaleUi();
    return;
  }
  toggle.disabled = false;
  updateUpscaleUi();
}

function updatePresetButtons() {
  const ids = ["presetBasic", "presetScroll", "presetQuality"];
  ids.forEach((id) => {
    const node = el(id);
    if (!node) {
      return;
    }
    const isActive =
      (currentPreset === "basic" && id === "presetBasic") ||
      (currentPreset === "scroll" && id === "presetScroll") ||
      (currentPreset === "quality" && id === "presetQuality");
    node.classList.toggle("preset-btn-active", isActive);
  });
}

function applyCapturePreset(name, { withLog = true } = {}) {
  const preset = PRESET_CONFIG[name] || PRESET_CONFIG.basic;
  currentPreset = PRESET_CONFIG[name] ? name : "basic";

  const sensitivity = el("captureSensitivity");
  const enableStitch = el("enableStitch");
  const overlap = el("overlapThreshold");
  const enableUpscale = el("enableUpscale");
  const upscaleFactor = el("upscaleFactor");
  const presetHintNode = el("presetHint");

  if (sensitivity) {
    sensitivity.value = preset.captureSensitivity;
  }
  if (enableStitch) {
    enableStitch.checked = Boolean(preset.enableStitch);
  }
  if (overlap) {
    overlap.value = String(preset.overlapThreshold);
  }
  if (enableUpscale) {
    const allowUpscale = !enableUpscale.disabled;
    enableUpscale.checked = allowUpscale ? Boolean(preset.enableUpscale) : false;
  }
  if (upscaleFactor) {
    upscaleFactor.value = preset.upscaleFactor;
  }
  if (presetHintNode) {
    presetHintNode.textContent = presetHint(name);
  }

  updatePresetButtons();
  updateCaptureSensitivityHelp();
  updateUpscaleUi();
  refreshCaptureWorkflowUi();

  if (withLog) {
    appendLog(getLocale() === "ko" ? `프리셋 적용: ${presetLabel(currentPreset)}` : `Preset applied: ${presetLabel(currentPreset)}`);
  }
}

function setPathChip(pathValue) {
  const chip = el("resultPathChip");
  if (!chip) {
    return;
  }
  if (!pathValue) {
    chip.textContent = getLocale() === "ko" ? "출력 경로: -" : "Output Path: -";
    return;
  }
  chip.textContent = getLocale() === "ko" ? `출력 경로: ${truncateMiddle(String(pathValue), 78)}` : `Output Path: ${truncateMiddle(String(pathValue), 78)}`;
}

function clearResultThumbnails() {
  const grid = el("resultThumbGrid");
  if (grid) {
    grid.replaceChildren();
  }
  resultImagePaths = [];
  resultPageDiagnostics = [];
  captureRenderVersion.clear();
  excludedResultIndices.clear();
  syncResultReviewUi();
}

function pruneExcludedResultIndices() {
  const max = resultImagePaths.length;
  for (const index of Array.from(excludedResultIndices)) {
    if (!Number.isInteger(index) || index < 0 || index >= max) {
      excludedResultIndices.delete(index);
    }
  }
}

function buildResultEntries() {
  const entries = resultImagePaths.map((imagePath, idx) => {
    const diagnostic = resultPageDiagnostics[idx] || {};
    const reasons = Array.isArray(diagnostic?.warning_reasons) ? diagnostic.warning_reasons.filter(Boolean) : [];
    return {
      imagePath,
      idx,
      diagnostic,
      suspicious: Boolean(diagnostic?.suspicious),
      reasons,
      excluded: excludedResultIndices.has(idx),
    };
  });

  entries.sort((a, b) => {
    if (a.suspicious !== b.suspicious) {
      return a.suspicious ? -1 : 1;
    }
    return a.idx - b.idx;
  });
  return entries;
}

function includedResultImagePaths() {
  pruneExcludedResultIndices();
  return buildResultEntries()
    .filter((entry) => !entry.excluded)
    .map((entry) => entry.imagePath);
}

function firstIncludedImagePath() {
  const kept = includedResultImagePaths();
  return kept.length > 0 ? kept[0] : "";
}

function syncResultReviewUi() {
  const reviewBar = el("resultReviewBar");
  const summary = el("resultReviewSummary");
  const keepAllButton = el("resultKeepAll");
  const applyButton = el("resultApplyReview");
  const stepReviewBadge = el("stepReviewBadge");
  const resultReviewBadge = el("resultReviewBadge");

  const total = resultImagePaths.length;
  const entries = buildResultEntries();
  const kept = entries.filter((entry) => !entry.excluded).length;
  const excluded = Math.max(0, total - kept);
  const suspiciousTotal = entries.filter((entry) => entry.suspicious).length;
  const suspiciousKept = entries.filter((entry) => entry.suspicious && !entry.excluded).length;

  if (reviewBar) {
    reviewBar.style.display = total > 0 ? "flex" : "none";
  }
  if (stepReviewBadge) {
    stepReviewBadge.hidden = suspiciousTotal <= 0;
    stepReviewBadge.textContent = suspiciousTotal > 0
      ? (getLocale() === "ko" ? `검토 필요 ${suspiciousTotal}개` : `${suspiciousTotal} review items`)
      : "";
  }
  if (resultReviewBadge) {
    resultReviewBadge.hidden = suspiciousTotal <= 0;
    resultReviewBadge.textContent = suspiciousTotal > 0
      ? (getLocale() === "ko" ? "검토 필요" : "Needs Review")
      : "";
  }
  if (summary) {
    if (total <= 0) {
      summary.textContent = getLocale() === "ko" ? "캡처 결과가 생기면 검토가 필요한 페이지를 먼저 표시합니다." : "Pages that likely need review will be shown first after captures are generated.";
    } else if (excluded > 0) {
      summary.textContent = suspiciousTotal > 0
        ? (getLocale() === "ko"
            ? `검토 필요 ${suspiciousKept}/${suspiciousTotal}페이지를 포함한 상태입니다. 전체 캡처 ${total}개 중 ${excluded}개 제외 예정입니다.`
            : `Keeping ${suspiciousKept}/${suspiciousTotal} review-needed pages. ${excluded} of ${total} captures will be excluded.`)
        : (getLocale() === "ko"
            ? `전체 캡처 ${total}개 중 ${excluded}개 제외 예정입니다. 반영하면 남은 캡처만으로 다시 생성합니다.`
            : `${excluded} of ${total} captures will be excluded. Applying review regenerates pages from the remaining captures.`);
    } else {
      summary.textContent = suspiciousTotal > 0
        ? (getLocale() === "ko"
            ? `검토 필요 페이지 ${suspiciousTotal}개가 먼저 표시됩니다. 제외할 캡처가 있으면 체크를 해제합니다.`
            : `${suspiciousTotal} review-needed pages are shown first. Uncheck any captures you want to exclude.`)
        : (getLocale() === "ko"
            ? `전체 캡처 ${total}개가 포함 상태입니다. 문제 없어 보이면 바로 저장해도 됩니다.`
            : `All ${total} captures are currently included. Export directly if everything looks fine.`);
    }
  }
  if (keepAllButton) {
    keepAllButton.disabled = total <= 0 || reviewApplyRunning;
  }
  if (applyButton) {
    applyButton.disabled = reviewApplyRunning || !activeCaptureJobId || total <= 0 || kept <= 0 || excluded <= 0;
    applyButton.textContent = reviewApplyRunning ? (getLocale() === "ko" ? "반영 중..." : "Applying...") : (getLocale() === "ko" ? "선택 반영 후 페이지 다시 생성" : "Apply Selection and Regenerate");
  }
  renderWorkLayoutState();
}

function renderResultThumbnails(imagePaths = [], pageDiagnostics = []) {
  const grid = el("resultThumbGrid");
  if (!grid) {
    return;
  }
  grid.replaceChildren();
  resultImagePaths = Array.isArray(imagePaths) ? imagePaths.slice() : [];
  resultPageDiagnostics = Array.isArray(pageDiagnostics) ? pageDiagnostics.slice() : [];
  pruneExcludedResultIndices();
  if (resultImagePaths.length === 0) {
    syncResultReviewUi();
    return;
  }

  const entries = buildResultEntries();

  const fragment = document.createDocumentFragment();
  entries.forEach(({ imagePath, idx, diagnostic, suspicious, reasons, excluded }) => {
    const isExcluded = excluded;
    const card = document.createElement("article");
    card.className = isExcluded ? "result-thumb is-excluded" : "result-thumb";
    if (suspicious) {
      card.classList.add("is-suspicious");
    }

    const preview = document.createElement("img");
    preview.src = pathWithVersion(imagePath);
    preview.alt = `result page ${idx + 1}`;
    preview.addEventListener("click", () => {
      renderResultPreview(imagePath);
    });
    preview.addEventListener("dblclick", () => {
      window.drumSheetAPI.openPath(imagePath);
    });

    const meta = document.createElement("div");
    meta.className = "result-thumb-meta";

    const checkLabel = document.createElement("label");
    checkLabel.className = "result-thumb-check";
    const includeCheck = document.createElement("input");
    includeCheck.type = "checkbox";
    includeCheck.checked = !isExcluded;
    const checkText = document.createElement("span");
    checkText.textContent = getLocale() === "ko" ? `캡처 ${idx + 1}` : `Capture ${idx + 1}`;
    checkLabel.append(includeCheck, checkText);

    const state = document.createElement("span");
    state.className = "result-thumb-state";
    state.textContent = isExcluded ? (getLocale() === "ko" ? "제외 예정" : "Excluded") : suspicious ? (getLocale() === "ko" ? "검토 필요" : "Needs Review") : (getLocale() === "ko" ? "포함" : "Included");

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "secondary";
    openButton.textContent = getLocale() === "ko" ? "열기" : "Open";
    openButton.addEventListener("click", () => {
      window.drumSheetAPI.openPath(imagePath);
    });

    const recropButton = document.createElement("button");
    recropButton.type = "button";
    recropButton.className = "secondary";
    recropButton.textContent = getLocale() === "ko" ? "다시 자르기" : "Recrop";
    recropButton.addEventListener("click", () => {
      openCaptureCropModal(imagePath, idx);
    });

    includeCheck.addEventListener("change", () => {
      if (includeCheck.checked) {
        excludedResultIndices.delete(idx);
        card.classList.remove("is-excluded");
        state.textContent = suspicious ? (getLocale() === "ko" ? "검토 필요" : "Needs Review") : (getLocale() === "ko" ? "포함" : "Included");
      } else {
        excludedResultIndices.add(idx);
        card.classList.add("is-excluded");
        state.textContent = getLocale() === "ko" ? "제외 예정" : "Excluded";
        if (currentPreviewImagePath === imagePath) {
          renderResultPreview(firstIncludedImagePath());
        }
      }
      syncResultReviewUi();
    });

    const left = document.createElement("div");
    left.className = "result-thumb-left";
    left.append(checkLabel, state);

    if (suspicious) {
      const warning = document.createElement("p");
      warning.className = "result-thumb-warning";
      warning.textContent = reasons.length ? reasons[0] : (getLocale() === "ko" ? "페이지 경계가 빽빽해서 잘림 여부를 확인해 주세요." : "Page edges look tight. Check whether the content is clipped.");
      left.append(warning);
    }

    const badgeRow = document.createElement("div");
    badgeRow.className = "result-thumb-meta-badges";
    const indexBadge = document.createElement("span");
    indexBadge.className = "result-thumb-badge";
    indexBadge.textContent = getLocale() === "ko" ? `페이지 ${idx + 1}` : `Page ${idx + 1}`;
    badgeRow.append(indexBadge);
    if (suspicious) {
      const riskBadge = document.createElement("span");
      riskBadge.className = "result-thumb-badge result-thumb-badge-risk";
      riskBadge.textContent = getLocale() === "ko" ? "검토 권장" : "Review";
      badgeRow.append(riskBadge);
    }
    if (Number.isFinite(Number(diagnostic?.top_edge_density)) && Number(diagnostic.top_edge_density) > 0) {
      const topBadge = document.createElement("span");
      topBadge.className = "result-thumb-badge";
      topBadge.textContent = getLocale() === "ko" ? `상단 ${Math.round(Number(diagnostic.top_edge_density) * 100)}%` : `Top ${Math.round(Number(diagnostic.top_edge_density) * 100)}%`;
      badgeRow.append(topBadge);
    }
    if (Number.isFinite(Number(diagnostic?.bottom_edge_density)) && Number(diagnostic.bottom_edge_density) > 0) {
      const bottomBadge = document.createElement("span");
      bottomBadge.className = "result-thumb-badge";
      bottomBadge.textContent = getLocale() === "ko" ? `하단 ${Math.round(Number(diagnostic.bottom_edge_density) * 100)}%` : `Bottom ${Math.round(Number(diagnostic.bottom_edge_density) * 100)}%`;
      badgeRow.append(bottomBadge);
    }
    left.append(badgeRow);

    const actions = document.createElement("div");
    actions.className = "result-thumb-actions";
    actions.append(recropButton, openButton);

    meta.append(left, actions);
    card.append(preview, meta);
    fragment.append(card);
  });

  grid.append(fragment);
  syncResultReviewUi();
}

function clampNumber(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function getCaptureCropElements() {
  return {
    modal: el("captureCropModal"),
    image: el("captureCropImage"),
    canvas: el("captureCropCanvas"),
    close: el("captureCropClose"),
    reset: el("captureCropReset"),
    apply: el("captureCropApply"),
  };
}

function canvasPointFromEvent(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  const x = clampNumber(event.clientX - rect.left, 0, rect.width);
  const y = clampNumber(event.clientY - rect.top, 0, rect.height);
  return { x, y };
}

function normalizeRectFromPoints(start, end, width, height) {
  const x1 = clampNumber(Math.min(start.x, end.x), 0, width);
  const y1 = clampNumber(Math.min(start.y, end.y), 0, height);
  const x2 = clampNumber(Math.max(start.x, end.x), 0, width);
  const y2 = clampNumber(Math.max(start.y, end.y), 0, height);
  return {
    x: x1,
    y: y1,
    w: Math.max(0, x2 - x1),
    h: Math.max(0, y2 - y1),
  };
}

function drawCaptureCropOverlay() {
  const { canvas } = getCaptureCropElements();
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = currentTheme() === "dark" ? "rgba(4, 9, 16, 0.6)" : "rgba(9, 24, 41, 0.45)";
  ctx.fillRect(0, 0, width, height);

  const rect = captureCropState.rect;
  if (!rect || rect.w <= 0 || rect.h <= 0) {
    return;
  }

  ctx.clearRect(rect.x, rect.y, rect.w, rect.h);
  ctx.strokeStyle = cssToken("--accent-2", "#31d5c8");
  ctx.lineWidth = 2;
  ctx.setLineDash([]);
  ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, Math.max(0, rect.w - 1), Math.max(0, rect.h - 1));
}

function resetCaptureCropRectToFull() {
  if (!captureCropState.canvasWidth || !captureCropState.canvasHeight) {
    captureCropState.rect = null;
    drawCaptureCropOverlay();
    return;
  }
  captureCropState.rect = {
    x: 0,
    y: 0,
    w: captureCropState.canvasWidth,
    h: captureCropState.canvasHeight,
  };
  drawCaptureCropOverlay();
}

function resizeCaptureCropCanvas() {
  const { image, canvas } = getCaptureCropElements();
  if (!image || !canvas) {
    return;
  }
  const rect = image.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  if (width <= 1 || height <= 1) {
    return;
  }

  const prevRect = captureCropState.rect;
  const prevWidth = captureCropState.canvasWidth;
  const prevHeight = captureCropState.canvasHeight;

  canvas.width = width;
  canvas.height = height;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  captureCropState.canvasWidth = width;
  captureCropState.canvasHeight = height;

  if (prevRect && prevWidth > 0 && prevHeight > 0) {
    captureCropState.rect = {
      x: (prevRect.x / prevWidth) * width,
      y: (prevRect.y / prevHeight) * height,
      w: (prevRect.w / prevWidth) * width,
      h: (prevRect.h / prevHeight) * height,
    };
  } else {
    resetCaptureCropRectToFull();
    return;
  }

  drawCaptureCropOverlay();
}

function setCaptureCropApplyBusy(running) {
  const { apply, reset } = getCaptureCropElements();
  captureCropState.applyRunning = Boolean(running);
  if (apply) {
    apply.disabled = captureCropState.applyRunning || !captureCropState.loaded;
    apply.textContent = captureCropState.applyRunning ? L("저장 중...", "Saving...") : t("crop.apply");
  }
  if (reset) {
    reset.disabled = captureCropState.applyRunning || !captureCropState.loaded;
  }
}

function closeCaptureCropModal() {
  const { modal, image, canvas } = getCaptureCropElements();
  if (modal) {
    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
  }
  if (image) {
    image.removeAttribute("src");
  }
  if (canvas) {
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }
  captureCropState = {
    open: false,
    imagePath: "",
    imageIndex: -1,
    rect: null,
    naturalWidth: 0,
    naturalHeight: 0,
    canvasWidth: 0,
    canvasHeight: 0,
    dragStart: null,
    drawing: false,
    loaded: false,
    applyRunning: false,
  };
  setCaptureCropApplyBusy(false);
}

function openCaptureCropModal(imagePath, index) {
  const path = String(imagePath || "").trim();
  if (!path) {
    appendLocaleError(L("자를 캡처 경로를 찾지 못했습니다.", "Could not find the capture path to crop."));
    return;
  }
  const { modal, image } = getCaptureCropElements();
  if (!modal || !image) {
    appendLocaleError(L("캡처 편집 창을 열 수 없습니다.", "Could not open the capture editor."));
    return;
  }

  captureCropState = {
    open: true,
    imagePath: path,
    imageIndex: Number.isInteger(index) ? index : -1,
    rect: null,
    naturalWidth: 0,
    naturalHeight: 0,
    canvasWidth: 0,
    canvasHeight: 0,
    dragStart: null,
    drawing: false,
    loaded: false,
    applyRunning: false,
  };
  setCaptureCropApplyBusy(false);

  modal.style.display = "flex";
  modal.setAttribute("aria-hidden", "false");
  setStatus(statusText("캡처 다시 자르기: 영역을 드래그해 주세요", "Recrop capture: drag the area to keep"));

  image.onload = () => {
    if (!captureCropState.open) {
      return;
    }
    captureCropState.loaded = true;
    captureCropState.naturalWidth = image.naturalWidth || 0;
    captureCropState.naturalHeight = image.naturalHeight || 0;
    window.requestAnimationFrame(() => {
      resizeCaptureCropCanvas();
      setCaptureCropApplyBusy(false);
    });
  };
  image.onerror = () => {
    appendLocaleError(L("캡처 이미지를 불러오지 못했습니다.", "Could not load the capture image."));
    closeCaptureCropModal();
  };
  image.src = pathWithVersion(path);
}

function onCaptureCropPointerDown(event) {
  if (!captureCropState.open || !captureCropState.loaded || captureCropState.applyRunning) {
    return;
  }
  const { canvas } = getCaptureCropElements();
  if (!canvas) {
    return;
  }
  const point = canvasPointFromEvent(event, canvas);
  captureCropState.drawing = true;
  captureCropState.dragStart = point;
  captureCropState.rect = { x: point.x, y: point.y, w: 0, h: 0 };
  drawCaptureCropOverlay();
}

function onCaptureCropPointerMove(event) {
  if (!captureCropState.drawing || !captureCropState.dragStart) {
    return;
  }
  const { canvas } = getCaptureCropElements();
  if (!canvas) {
    return;
  }
  const point = canvasPointFromEvent(event, canvas);
  captureCropState.rect = normalizeRectFromPoints(captureCropState.dragStart, point, canvas.width, canvas.height);
  drawCaptureCropOverlay();
}

function onCaptureCropPointerUp() {
  if (!captureCropState.drawing) {
    return;
  }
  captureCropState.drawing = false;
  captureCropState.dragStart = null;
  if (!captureCropState.rect || captureCropState.rect.w < 3 || captureCropState.rect.h < 3) {
    resetCaptureCropRectToFull();
  } else {
    drawCaptureCropOverlay();
  }
}

function buildCropRoiFromState() {
  const rect = captureCropState.rect;
  if (!rect || rect.w <= 0 || rect.h <= 0) {
    return null;
  }
  if (
    captureCropState.canvasWidth <= 0 ||
    captureCropState.canvasHeight <= 0 ||
    captureCropState.naturalWidth <= 0 ||
    captureCropState.naturalHeight <= 0
  ) {
    return null;
  }
  const scaleX = captureCropState.naturalWidth / captureCropState.canvasWidth;
  const scaleY = captureCropState.naturalHeight / captureCropState.canvasHeight;
  const x1 = clampNumber(Math.round(rect.x * scaleX), 0, captureCropState.naturalWidth);
  const y1 = clampNumber(Math.round(rect.y * scaleY), 0, captureCropState.naturalHeight);
  const x2 = clampNumber(Math.round((rect.x + rect.w) * scaleX), 0, captureCropState.naturalWidth);
  const y2 = clampNumber(Math.round((rect.y + rect.h) * scaleY), 0, captureCropState.naturalHeight);
  if (x2 <= x1 || y2 <= y1) {
    return null;
  }
  return [
    [x1, y1],
    [x2, y1],
    [x2, y2],
    [x1, y2],
  ];
}

async function onApplyCaptureCrop() {
  if (captureCropState.applyRunning) {
    return;
  }
  if (!activeCaptureJobId) {
    appendLocaleError(L("현재 작업을 찾지 못해 캡처 자르기를 저장할 수 없습니다.", "Could not find the current job, so the recrop could not be saved."));
    return;
  }
  const roi = buildCropRoiFromState();
  if (!roi) {
    appendLocaleLog("안내: 먼저 캡처에서 남길 영역을 드래그해 주세요.", "Info: drag the area to keep before applying recrop.");
    return;
  }

  try {
    setCaptureCropApplyBusy(true);
    const targetPath = captureCropState.imagePath;
    const response = await cropCapture(API_BASE, activeCaptureJobId, {
      capturePath: targetPath,
      roi,
    });
    bumpCaptureRenderVersion(targetPath);
    renderResultThumbnails(resultImagePaths);
    if (currentPreviewImagePath === targetPath) {
      renderResultPreview(targetPath);
    }
    appendLocaleLog(
      `캡처 다시 자르기 저장: ${pathBaseName(response.capture_path)} (${response.width}x${response.height})`,
      `Recrop saved: ${pathBaseName(response.capture_path)} (${response.width}x${response.height})`,
    );
    setStatus(statusText("캡처 자르기 저장 완료", "Recrop saved"));
    closeCaptureCropModal();
  } catch (error) {
    appendLocaleError(error.message);
    setStatus(statusText("캡처 자르기 저장 실패", "Failed to save recrop"));
    setCaptureCropApplyBusy(false);
  }
}

async function copyTextToClipboard(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  try {
    if (window.drumSheetAPI && typeof window.drumSheetAPI.copyText === "function") {
      await window.drumSheetAPI.copyText(text);
      return true;
    }
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {
    return false;
  }
  return false;
}

const roiController = createRoiController({
  onPreviewLoadError: () => {
    appendLocaleError(L("미리보기 이미지를 불러오지 못했습니다. 시작 시간을 살짝 옮겨 다시 눌러 주세요.", "Could not load the preview image. Move the start time slightly and try again."));
    setStatus(statusText("영역 지정 화면 표시 실패", "Failed to show ROI screen"));
  },
  onPreviewReady: ({ width, height }) => {
    const frameMeta = el("roiFrameMeta");
    if (frameMeta && Number.isFinite(width) && Number.isFinite(height)) {
      frameMeta.textContent = L(`${width} x ${height} 프레임`, `${width} x ${height} frame`);
    }
  },
  onRoiChange: (snapshot) => {
    renderRoiAssist(snapshot);
    if (!snapshot?.hasImage || !snapshot?.imageReady || !snapshot?.rect || !Array.isArray(snapshot?.points)) {
      resetCurrentRoiHealthReport();
      renderRoiAssist(snapshot);
      return;
    }
    void requestRoiHealth(snapshot);
  },
});

const videoRangePicker = createVideoRangePicker({
  sourceType,
  onRangeChange: () => {
    refreshCaptureWorkflowUi();
  },
});

function resetResultView() {
  if (captureCropState.open) {
    closeCaptureCropModal();
  }
  roiController.clearPreview();
  clearResultMeta();
  clearResultThumbnails();
  outputDir = "";
  outputPdf = "";
  activeCaptureJobId = "";
  currentPreviewImagePath = "";
  reviewApplyRunning = false;
  resultFocusPending = false;

  const openOutputDir = el("openOutputDir");
  const stickyOpenOutput = el("stickyOpenOutput");
  const openPdf = el("openPdf");
  const copyOutputPath = el("copyOutputPath");
  if (openOutputDir) {
    openOutputDir.disabled = true;
  }
  if (stickyOpenOutput) {
    stickyOpenOutput.disabled = true;
  }
  if (openPdf) {
    openPdf.disabled = true;
  }
  if (copyOutputPath) {
    copyOutputPath.disabled = true;
  }

  setPathChip("");

  const previewImage = el("resultPreviewImage");
  if (previewImage) {
    previewImage.style.display = "none";
    previewImage.removeAttribute("src");
  }
  syncResultReviewUi();
}

function focusResultWorkspace({ review = false } = {}) {
  const target = review
    ? el("resultThumbGrid") || el("resultReviewBar") || document.querySelector(".result-card")
    : document.querySelector(".result-card");
  target?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderResultPreview(imagePath) {
  const previewImage = el("resultPreviewImage");
  if (!previewImage) {
    return;
  }
  const path = String(imagePath || "").trim();
  if (!path) {
    currentPreviewImagePath = "";
    previewImage.style.display = "none";
    previewImage.removeAttribute("src");
    return;
  }
  previewImage.src = pathWithVersion(path);
  previewImage.style.display = "block";
  currentPreviewImagePath = path;
}

function appendRecoveryHint(job) {
  const detail = String(job?.message || "").toLowerCase();
  if (!detail) {
    return;
  }
  if (detail.includes("sheet detection") || detail.includes("detect")) {
    appendLocaleLog("안내: 2단계에서 미리보기 화면을 다시 불러오고 악보 영역을 다시 드래그해 보세요.", "Info: reload the preview in step 2 and draw the score area again.");
    return;
  }
  if (detail.includes("ffmpeg")) {
    appendLocaleLog("안내: 영상 코덱 문제일 수 있습니다. 시작/끝 구간을 좁히거나 다른 파일로 시도해 보세요.", "Info: this may be a video codec issue. Narrow the range or try another file.");
    return;
  }
  if (detail.includes("youtube")) {
    appendLocaleLog("안내: 유튜브 준비 실패 시 로컬 파일로 먼저 테스트해 보세요.", "Info: if YouTube preparation fails, test with a local file first.");
  }
}

function renderResult(job) {
  const meta = renderResultMeta(job, friendlyStepName);
  outputDir = meta.outputDir || "";
  outputPdf = meta.pdfPath || "";
  activeCaptureJobId = String(job?.job_id || activeCaptureJobId || "");
  excludedResultIndices.clear();

  const openOutputDir = el("openOutputDir");
  const stickyOpenOutput = el("stickyOpenOutput");
  const openPdf = el("openPdf");
  const copyOutputPath = el("copyOutputPath");

  if (openOutputDir) {
    openOutputDir.disabled = !outputDir;
  }
  if (stickyOpenOutput) {
    stickyOpenOutput.disabled = !outputDir;
  }
  if (openPdf) {
    openPdf.disabled = !outputPdf;
  }
  if (copyOutputPath) {
    copyOutputPath.disabled = !outputDir;
  }

  setPathChip(outputDir);
  const reviewPaths = Array.isArray(meta.capturePaths) && meta.capturePaths.length ? meta.capturePaths : meta.imagePaths || [];
  renderResultThumbnails(reviewPaths, meta.pageDiagnostics);
  const previewPath = firstIncludedImagePath() || meta.firstImagePath;
  renderResultPreview(previewPath);

  if (job?.result?.runtime) {
    latestRuntime = job.result.runtime;
    renderRuntimeStatus(latestRuntime);
    applyUpscaleAvailability(latestRuntime);
  }

  refreshCaptureWorkflowUi();
  if (resultFocusPending && reviewPaths.length > 0) {
    resultFocusPending = false;
    window.setTimeout(() => {
      focusResultWorkspace({ review: countReviewCandidates() > 0 });
    }, 80);
  }
}

function onKeepAllResultPages() {
  if (reviewApplyRunning || !resultImagePaths.length) {
    return;
  }
  excludedResultIndices.clear();
  renderResultThumbnails(resultImagePaths);
  appendLocaleLog("결과 검토: 모든 캡처를 포함 상태로 되돌렸습니다.", "Review reset: all captures were restored to included.");
}

async function onApplyResultReview() {
  if (reviewApplyRunning) {
    return;
  }
  if (!activeCaptureJobId) {
    appendLocaleError(L("검토를 반영할 완료 작업을 찾지 못했습니다.", "Could not find a completed job to apply review changes."));
    return;
  }

  const keepImages = includedResultImagePaths();
  if (keepImages.length <= 0) {
    appendLocaleLog("안내: 최소 1개 캡처는 포함 상태로 남겨야 저장할 수 있습니다.", "Info: keep at least one capture included before applying review.");
    return;
  }
  if (keepImages.length === resultImagePaths.length) {
    appendLocaleLog("안내: 제외된 캡처가 없습니다. 체크 해제 후 다시 반영해 주세요.", "Info: no captures are excluded. Uncheck at least one and apply again.");
    return;
  }

  reviewApplyRunning = true;
  syncResultReviewUi();
  setStatus(statusText("검토 반영 중", "Applying review"));
  appendLocaleLog(
    `검토 반영 시작: 전체 캡처 ${resultImagePaths.length}개 중 ${keepImages.length}개 유지`,
    `Applying review: keeping ${keepImages.length} of ${resultImagePaths.length} captures`,
  );
  try {
    await reviewExport(API_BASE, activeCaptureJobId, {
      keepCaptures: keepImages,
      formats: getFormats(),
    });
    const refreshed = await getJob(API_BASE, activeCaptureJobId);
    renderResult(refreshed);
    appendLocaleLog("검토 반영 완료: 선택한 캡처로 페이지를 다시 생성했습니다.", "Review applied: pages were regenerated from the selected captures.");
    setStatus(statusText("검토 반영 완료", "Review applied"));
  } catch (error) {
    appendLocaleError(error.message);
    setStatus(statusText("검토 반영 실패", "Failed to apply review"));
  } finally {
    reviewApplyRunning = false;
    syncResultReviewUi();
    refreshCaptureWorkflowUi();
  }
}

async function poll(jobId) {
  const job = await getJob(API_BASE, jobId);
  setProgress(job.progress);
  setStatus(friendlyStatusText(job.current_step, job.message));
  setPipelineState({
    currentStep: job.current_step,
    progress: job.progress,
    status: job.status,
    isYoutubeSource: sourceType() === "youtube",
  });
  appendLog(`[${friendlyStepName(job.current_step)}] ${friendlyMessage(job.message)}`);

  if (job.status === "running" || job.status === "queued") {
    return;
  }

  clearInterval(activePoll);
  activePoll = null;

  if (job.status === "done") {
    runState = "done";
    setStatus(statusText("완료", "Done"));
    renderResult(job);
  } else {
    runState = "idle";
    setStatus(L(`오류 (${job.error_code || "알 수 없음"})`, `Error (${job.error_code || "Unknown"})`));
    if (job.result) {
      renderResult(job);
    }
    appendRecoveryHint(job);
  }

  refreshCaptureWorkflowUi();
}

async function onRun() {
  try {
    if (activePoll) {
      clearInterval(activePoll);
      activePoll = null;
    }

    if (!backendBridgeState.ready) {
      appendLocaleError(L("로컬 엔진이 연결되지 않았습니다. 상단 자동 설치/복구를 먼저 실행해 주세요.", "The local engine is not connected. Run Auto Setup/Repair first."));
      setStatus(statusText("엔진 연결 필요", "Engine connection required"));
      guideToIncompleteStep();
      refreshCaptureWorkflowUi();
      return;
    }

    if (!isSourceReady() || !isRangeValid() || !isRoiReady() || !isExportReady()) {
      guideToIncompleteStep();
      refreshCaptureWorkflowUi();
      return;
    }

    runState = "running";
    resetResultView();
    setProgress(0);
    setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
    setStatus(statusText("작업을 시작하고 있어요", "Starting job"));
    appendLocaleLog("작업 시작", "Job started");
    refreshCaptureWorkflowUi();

    const jobId = await createJob(API_BASE);
    activeCaptureJobId = String(jobId || "");
    resultFocusPending = true;
    setStatus(statusText("작업 대기 중", "Job queued"));
    activePoll = setInterval(() => {
      poll(jobId).catch((error) => {
        appendLocaleError(String(error.message));
        clearInterval(activePoll);
        activePoll = null;
        runState = "idle";
        setStatus(statusText("조회 실패", "Status polling failed"));
        setPipelineState({ currentStep: "exporting", progress: 1, status: "error", isYoutubeSource: sourceType() === "youtube" });
        refreshCaptureWorkflowUi();
      });
    }, 700);
  } catch (error) {
    appendLocaleError(error.message);
    runState = "idle";
    setStatus(statusText("요청 실패", "Request failed"));
    setPipelineState({ currentStep: "exporting", progress: 1, status: "error", isYoutubeSource: sourceType() === "youtube" });
    refreshCaptureWorkflowUi();
  }
}

function onCancelRun() {
  if (activePoll) {
    clearInterval(activePoll);
    activePoll = null;
  }
  runState = "idle";
  setStatus(statusText("진행 조회 중단", "Stopped polling"));
  appendLocaleLog(
    "사용자가 진행 조회를 중단했습니다. 백엔드 작업은 백그라운드에서 계속될 수 있습니다.",
    "Stopped polling. The backend job may still continue in the background.",
  );
  setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
  refreshCaptureWorkflowUi();
}

async function refreshRuntimeStatus({ force = false, syncBackendStateOnFailure = true } = {}) {
  if (runtimeRefreshInFlight) {
    return;
  }
  if (!force && latestRuntime && backendBridgeState.ready) {
    renderRuntimeStatus(latestRuntime);
    applyUpscaleAvailability(latestRuntime);
    return;
  }
  runtimeRefreshInFlight = true;
  try {
    latestRuntime = await getRuntimeStatus(API_BASE);
    renderRuntimeStatus(latestRuntime);
    applyUpscaleAvailability(latestRuntime);
    backendBridgeState = {
      ...backendBridgeState,
      ready: true,
      starting: false,
      running: true,
      error: "",
    };
    renderBackendBridgeState();
    void refreshCacheUsage();
  } catch (_) {
    renderRuntimeError();
    applyUpscaleAvailability(latestRuntime);
    if (syncBackendStateOnFailure) {
      await refreshBackendBridgeState();
    }
  } finally {
    runtimeRefreshInFlight = false;
  }
}

async function onLoadPreviewForRoi() {
  const button = el("loadPreviewForRoi");
  const requestToken = ++previewRequestToken;
  const sourceFingerprint = currentSourceFingerprint();
  try {
    if (button) {
      button.disabled = true;
    }
    const filePathNode = el("filePath");
    if (sourceType() === "file" && !filePathNode?.value) {
      const pickedPath = await window.drumSheetAPI.selectVideoFile();
      if (pickedPath) {
        if (filePathNode) {
          filePathNode.value = pickedPath;
        }
        videoRangePicker.loadLocalFile(pickedPath);
      }
    }
    setRoiFrameRequestState({ status: "loading", detail: "" });
    setStatus(statusText("악보 화면을 준비 중입니다", "Preparing score frame"));
    appendLocaleLog("악보 영역 지정 화면 요청", "Requested score-frame preview");
    roiController.clearPreview();
    if (sourceType() === "youtube") {
      await ensureYoutubePrepared({ reason: "frame" });
    }
    const previewStartSec = videoRangePicker.getPreviewSecond();
    if (previewStartSec != null) {
      appendLocaleLog(`영역 지정 시점: ${previewStartSec.toFixed(1)}초`, `Preview moment: ${previewStartSec.toFixed(1)}s`);
    }
    let previewFrame = null;
    let resolvedPreviewSecond = previewStartSec;
    try {
      previewFrame = await requestPreviewFrame(API_BASE, { startSecOverride: previewStartSec });
    } catch (firstError) {
      if (previewStartSec != null && previewStartSec > 0.25) {
        appendLocaleLog(
          "안내: 선택 시점 프레임 추출에 실패해 영상 시작 기준으로 한 번 더 시도합니다.",
          "Info: failed to extract the selected frame, so retrying from the start of the video.",
        );
        previewFrame = await requestPreviewFrame(API_BASE, { startSecOverride: 0 });
        resolvedPreviewSecond = 0;
      } else {
        throw firstError;
      }
    }
    if (requestToken !== previewRequestToken || sourceFingerprint !== currentSourceFingerprint()) {
      appendLocaleLog(
        "안내: 입력 값이 바뀌어 영역 지정 화면 요청이 취소되었습니다. 다시 눌러 주세요.",
        "Info: the input changed, so the preview request was canceled. Try again.",
      );
      setRoiFrameRequestState({ status: "idle", detail: "" });
      setStatus(statusText("입력 변경으로 요청 취소됨", "Request canceled because input changed"));
      return false;
    }
    manualOpenStep = "roi";
    updateManualTools();
    currentPreviewFrame = previewFrame || {
      imagePath: "",
      sourcePath: "",
      previewSecond: resolvedPreviewSecond,
      diagnostics: [],
    };
    currentPreviewFrame.previewSecond = resolvedPreviewSecond;
    resetCurrentRoiHealthReport();
    roiController.showPreviewWithRoi(currentPreviewFrame.imagePath);
    roiController.setRoiEditorVisibility(true);
    roiController.setRoiEditMode(true);
    setRoiFrameRequestState({ status: "ready", detail: "" });
    el("roiEditorWrap")?.scrollIntoView({ behavior: "smooth", block: "center" });
    setStatus(statusText("화면 준비 완료. 악보 부분을 드래그해 주세요", "Frame ready. Drag over the score area."));
    appendLocaleLog("영역 지정 화면 준비 완료", "Score-frame preview is ready");
    refreshCaptureWorkflowUi();
    return true;
  } catch (error) {
    if (requestToken !== previewRequestToken) {
      return false;
    }
    appendLocaleError(error.message);
    setRoiFrameRequestState({ status: "error", detail: error?.message || "" });
    setStatus(statusText("악보 화면을 불러오지 못했습니다", "Could not load the score frame"));
    return false;
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

async function onLockRoiFrame() {
  const reloaded = await onLoadPreviewForRoi();
  if (reloaded) {
    appendLocaleLog("현재 시점 프레임을 다시 불러왔습니다.", "Reloaded the frame at the current moment.");
    setStatus(statusText("현재 시점 프레임으로 갱신됨", "Updated with current frame"));
  }
  refreshCaptureWorkflowUi();
}

async function ensureYoutubePrepared({ reason = "manual" } = {}) {
  if (sourceType() !== "youtube") {
    return null;
  }

  const fingerprint = currentSourceFingerprint();
  const previousFingerprint = youtubePrepareState.fingerprint;
  if (
    youtubePrepareState.status === "ready" &&
    youtubePrepareState.fingerprint === fingerprint &&
    youtubePrepareState.playable &&
    videoRangePicker.hasMediaLoaded?.()
  ) {
    return {
      playable: youtubePrepareState.playable,
      fromCache: youtubePrepareState.fromCache,
      alreadyReady: true,
    };
  }

  setYoutubePrepareState({
    status: "preparing",
    fingerprint,
    detail: "",
    fromCache: false,
    playable: "",
  });
  if (previousFingerprint !== fingerprint || youtubePrepareLogs.length === 0) {
    resetYoutubePrepareLogs();
  }
  appendYoutubePrepareLogLine(
    reason === "manual"
      ? L("유튜브 준비 요청을 시작했습니다.", "Started YouTube preparation.")
      : L("프레임을 열기 전에 유튜브 준비를 시작합니다.", "Preparing the YouTube source before opening a frame."),
  );
  if (reason === "manual") {
    setStatus(statusText("유튜브 영상을 준비 중입니다", "Preparing YouTube video"));
    appendLocaleLog("유튜브 영상 준비 요청", "Requested YouTube video preparation");
  } else {
    appendLocaleLog(
      "악보 화면을 열기 전에 유튜브 영상을 먼저 준비합니다.",
      "Preparing the YouTube video before opening the score frame.",
    );
  }

  try {
    const prepared = await requestPreviewSource(API_BASE);
    appendYoutubePrepareLogLines(Array.isArray(prepared?.log_lines) ? prepared.log_lines : []);
    const playable = prepared.video_url || prepared.video_path;
    if (!playable) {
      throw new Error(L("재생 가능한 유튜브 영상을 준비하지 못했어요.", "Could not prepare a playable YouTube video."));
    }
    if (fingerprint !== currentSourceFingerprint()) {
      throw new Error(L("입력한 유튜브 주소가 바뀌었습니다. 다시 시도합니다.", "The YouTube URL changed. Try again."));
    }
    videoRangePicker.loadVideoSource(playable);
    setYoutubePrepareState({
      status: "ready",
      fingerprint,
      detail: "",
      fromCache: Boolean(prepared.from_cache),
      playable,
    });
    appendYoutubePrepareLogLine(
      prepared.from_cache
        ? L("캐시된 유튜브 영상을 사용할 수 있습니다.", "The cached YouTube video is ready to use.")
        : L("유튜브 다운로드가 완료되어 바로 재생할 수 있습니다.", "The YouTube download is complete and ready to play."),
    );
    return {
      playable,
      fromCache: Boolean(prepared.from_cache),
      alreadyReady: false,
    };
  } catch (error) {
    if (fingerprint === currentSourceFingerprint()) {
      setYoutubePrepareState({
        status: "error",
        fingerprint,
        detail: error?.message || "",
        fromCache: false,
        playable: "",
      });
      appendYoutubePrepareLogLine(L(`실패: ${error?.message || ""}`, `Failed: ${error?.message || ""}`));
    }
    throw error;
  }
}

function onApplyRoiSelection() {
  if (typeof roiController.applyCurrentRoi !== "function") {
    return;
  }
  const applied = roiController.applyCurrentRoi();
  if (!applied) {
    appendLocaleLog("안내: 먼저 악보 화면에서 영역을 드래그해 주세요.", "Info: drag the score area on the frame first.");
    setStatus(statusText("영역 지정 필요", "ROI required"));
    return;
  }
  const applyButton = el("applyRoi");
  if (applyButton) {
    const original = t("roi.apply");
    applyButton.textContent = L("영역 저장됨", "ROI Saved");
    applyButton.disabled = true;
    window.setTimeout(() => {
      applyButton.disabled = false;
      applyButton.textContent = original;
    }, 850);
  }
  manualOpenStep = "export";
  appendLocaleLog("영역 저장 완료: 이 범위로 캡처를 진행합니다.", "ROI saved: captures will use this area.");
  setStatus(statusText("영역 저장 완료", "ROI saved"));
  refreshCaptureWorkflowUi();
}

async function onPrepareYoutubeVideo() {
  const button = el("prepareYoutubeVideo");
  try {
    if (sourceType() !== "youtube") {
      return;
    }
    if (button) {
      button.disabled = true;
    }
    const prepared = await ensureYoutubePrepared({ reason: "manual" });
    setStatus(statusText("유튜브 영상 준비 완료", "YouTube video ready"));
    appendLocaleLog(
      prepared.alreadyReady
        ? "이미 준비된 유튜브 영상을 그대로 사용합니다."
        : prepared.fromCache
          ? "캐시된 유튜브 영상 사용"
          : "유튜브 영상 다운로드 완료",
      prepared.alreadyReady
        ? "Using the already prepared YouTube video."
        : prepared.fromCache
          ? "Using cached YouTube video"
          : "YouTube video downloaded",
    );
    refreshCaptureWorkflowUi();
  } catch (error) {
    appendLocaleError(error.message);
    setStatus(statusText("유튜브 영상 준비에 실패했습니다", "Failed to prepare YouTube video"));
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

function bindStepNavigation() {
  STEP_KEYS.forEach((key) => {
    const button = el(STEP_BAR_BUTTON_IDS[key]);
    if (!button) {
      return;
    }
    button.addEventListener("click", () => {
      manualOpenStep = key;
      refreshCaptureWorkflowUi();
      const details = el(STEP_DETAIL_IDS[key]);
      details?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

function bindPresetButtons() {
  const basic = el("presetBasic");
  const scroll = el("presetScroll");
  const quality = el("presetQuality");
  basic?.addEventListener("click", () => applyCapturePreset("basic"));
  scroll?.addEventListener("click", () => applyCapturePreset("scroll"));
  quality?.addEventListener("click", () => applyCapturePreset("quality"));
}

function openSupportPanel() {
  supportSheetOpen = true;
  renderSupportSheetState();
  renderWorkLayoutState();
}

function closeSupportPanel() {
  supportSheetOpen = false;
  renderSupportSheetState();
  renderWorkLayoutState();
}

function toggleStatusDrawer() {
  statusDrawerOpen = !statusDrawerOpen;
  renderWorkLayoutState();
}

document.querySelectorAll('input[name="sourceType"]').forEach((node) => {
  node.addEventListener("change", () => {
    manualOpenStep = "source";
    updateSourceRows();
  });
});

const roiInput = el("roiInput");
if (roiInput) {
  roiInput.addEventListener("input", () => {
    roiController.onRoiInputChange();
    refreshCaptureWorkflowUi();
  });
}

const browseFileButton = el("browseFile");
if (browseFileButton) {
  browseFileButton.addEventListener("click", async () => {
    const path = await window.drumSheetAPI.selectVideoFile();
    if (path) {
      const filePathNode = el("filePath");
      if (filePathNode) {
        filePathNode.value = path;
      }
      videoRangePicker.loadLocalFile(path);
      resetRoiForSourceChange({ silent: false });
      refreshCaptureWorkflowUi();
    }
  });
}

["heroStart", "quickstartStart"].forEach((id) => {
  const node = el(id);
  if (!node) {
    return;
  }
  node.addEventListener("click", () => {
    focusSourceEntry({ openPicker: true });
  });
});

const openSupportPanelButton = el("openSupportPanel");
if (openSupportPanelButton) {
  openSupportPanelButton.addEventListener("click", openSupportPanel);
}

["closeSupportPanel", "supportSheetBackdrop"].forEach((id) => {
  const node = el(id);
  if (!node) {
    return;
  }
  node.addEventListener("click", closeSupportPanel);
});

const toggleStatusDrawerButton = el("toggleStatusDrawer");
if (toggleStatusDrawerButton) {
  toggleStatusDrawerButton.addEventListener("click", toggleStatusDrawer);
}

const loadPreviewForRoiButton = el("loadPreviewForRoi");
if (loadPreviewForRoiButton) {
  loadPreviewForRoiButton.addEventListener("click", onLoadPreviewForRoi);
}

const applyRoiButton = el("applyRoi");
if (applyRoiButton) {
  applyRoiButton.addEventListener("click", onApplyRoiSelection);
}

const lockRoiFrameButton = el("lockRoiFrame");
if (lockRoiFrameButton) {
  lockRoiFrameButton.addEventListener("click", onLockRoiFrame);
}

const prepareYoutubeVideoButton = el("prepareYoutubeVideo");
if (prepareYoutubeVideoButton) {
  prepareYoutubeVideoButton.addEventListener("click", onPrepareYoutubeVideo);
}

const qualityGateOpenFileButton = el("qualityGateOpenFile");
if (qualityGateOpenFileButton) {
  qualityGateOpenFileButton.addEventListener("click", () => {
    const fileRadio = document.querySelector('input[name="sourceType"][value="file"]');
    if (fileRadio instanceof HTMLInputElement && !fileRadio.checked) {
      fileRadio.checked = true;
      fileRadio.dispatchEvent(new Event("change", { bubbles: true }));
    }
    el("browseFile")?.click();
  });
}

const qualityGateShowLogButton = el("qualityGateShowLog");
if (qualityGateShowLogButton) {
  qualityGateShowLogButton.addEventListener("click", () => {
    const details = el("youtubePrepareLogDetails");
    if (details) {
      details.hidden = false;
      details.open = true;
      details.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });
}

const copySourcePathButton = el("copySourcePath");
if (copySourcePathButton) {
  copySourcePathButton.addEventListener("click", async () => {
    const sourcePath = sourceType() === "file" ? String(el("filePath")?.value || "") : String(el("youtubeUrl")?.value || "");
    const ok = await copyTextToClipboard(sourcePath);
    ok
      ? appendLocaleLog("입력 경로를 복사했습니다.", "Copied the source path.")
      : appendLocaleError(L("입력 경로 복사 실패", "Failed to copy the source path."));
  });
}

const copyRoiCoordsButton = el("copyRoiCoords");
if (copyRoiCoordsButton) {
  copyRoiCoordsButton.addEventListener("click", async () => {
    const value = String(el("roiInput")?.value || "");
    const ok = await copyTextToClipboard(value);
    ok
      ? appendLocaleLog("ROI 좌표를 복사했습니다.", "Copied ROI coordinates.")
      : appendLocaleError(L("ROI 좌표 복사 실패", "Failed to copy ROI coordinates."));
  });
}

const captureSensitivityNode = el("captureSensitivity");
if (captureSensitivityNode) {
  captureSensitivityNode.addEventListener("change", () => {
    updateCaptureSensitivityHelp();
    appendLocaleLog("캡처 민감도 변경", "Capture sensitivity changed");
    refreshCaptureWorkflowUi();
  });
}

const enableUpscaleNode = el("enableUpscale");
if (enableUpscaleNode) {
  enableUpscaleNode.addEventListener("change", () => {
    updateUpscaleUi();
    appendLocaleLog(
      enableUpscaleNode.checked ? "GPU 업스케일 사용" : "GPU 업스케일 사용 안 함",
      enableUpscaleNode.checked ? "GPU upscaling enabled" : "GPU upscaling disabled",
    );
    refreshCaptureWorkflowUi();
  });
}

const startSecNode = el("startSec");
if (startSecNode) {
  startSecNode.addEventListener("input", () => {
    manualOpenStep = "roi";
    refreshCaptureWorkflowUi();
  });
}

const endSecNode = el("endSec");
if (endSecNode) {
  endSecNode.addEventListener("input", () => {
    manualOpenStep = "roi";
    refreshCaptureWorkflowUi();
  });
}

["videoSeek", "startSlider", "endSlider"].forEach((id) => {
  const node = el(id);
  if (!node) {
    return;
  }
  node.addEventListener("input", () => {
    manualOpenStep = "roi";
    refreshCaptureWorkflowUi();
  });
});

["setStartAtCurrent", "setEndAtCurrent", "clearRange"].forEach((id) => {
  const node = el(id);
  if (!node) {
    return;
  }
  node.addEventListener("click", () => {
    manualOpenStep = "roi";
    refreshCaptureWorkflowUi();
  });
});

const youtubeUrlNode = el("youtubeUrl");
if (youtubeUrlNode) {
  youtubeUrlNode.addEventListener("input", () => {
    if (sourceType() === "youtube") {
      resetRoiForSourceChange({ silent: true });
    }
    manualOpenStep = "source";
    refreshCaptureWorkflowUi();
  });
}

document.querySelectorAll(".format").forEach((node) => {
  node.addEventListener("change", () => {
    manualOpenStep = "export";
    refreshCaptureWorkflowUi();
  });
});

const openOutputDirButton = el("openOutputDir");
if (openOutputDirButton) {
  openOutputDirButton.addEventListener("click", () => {
    if (!outputDir) {
      return;
    }
    window.drumSheetAPI.openPath(outputDir);
  });
}

const stickyOpenOutputButton = el("stickyOpenOutput");
if (stickyOpenOutputButton) {
  stickyOpenOutputButton.addEventListener("click", () => {
    if (!outputDir) {
      return;
    }
    window.drumSheetAPI.openPath(outputDir);
  });
}

const openPdfButton = el("openPdf");
if (openPdfButton) {
  openPdfButton.addEventListener("click", () => {
    if (!outputPdf) {
      return;
    }
    window.drumSheetAPI.openPath(outputPdf);
  });
}

const copyOutputPathButton = el("copyOutputPath");
if (copyOutputPathButton) {
  copyOutputPathButton.addEventListener("click", async () => {
    if (!outputDir) {
      return;
    }
    const ok = await copyTextToClipboard(outputDir);
    ok
      ? appendLocaleLog("출력 경로를 복사했습니다.", "Copied the output path.")
      : appendLocaleError(L("출력 경로 복사 실패", "Failed to copy the output path."));
  });
}

const toggleAlwaysOnTopButton = el("toggleAlwaysOnTop");
if (toggleAlwaysOnTopButton) {
  toggleAlwaysOnTopButton.addEventListener("click", onToggleAlwaysOnTop);
}

const resultKeepAllButton = el("resultKeepAll");
if (resultKeepAllButton) {
  resultKeepAllButton.addEventListener("click", onKeepAllResultPages);
}

const resultApplyReviewButton = el("resultApplyReview");
if (resultApplyReviewButton) {
  resultApplyReviewButton.addEventListener("click", onApplyResultReview);
}

const captureCropModal = el("captureCropModal");
if (captureCropModal) {
  captureCropModal.addEventListener("click", (event) => {
    if (event.target === captureCropModal && !captureCropState.applyRunning) {
      closeCaptureCropModal();
    }
  });
}

const captureCropCloseButton = el("captureCropClose");
if (captureCropCloseButton) {
  captureCropCloseButton.addEventListener("click", () => {
    if (captureCropState.applyRunning) {
      return;
    }
    closeCaptureCropModal();
  });
}

const captureCropResetButton = el("captureCropReset");
if (captureCropResetButton) {
  captureCropResetButton.addEventListener("click", () => {
    if (captureCropState.applyRunning) {
      return;
    }
    resetCaptureCropRectToFull();
  });
}

const captureCropApplyButton = el("captureCropApply");
if (captureCropApplyButton) {
  captureCropApplyButton.addEventListener("click", onApplyCaptureCrop);
}

const captureCropCanvas = el("captureCropCanvas");
if (captureCropCanvas) {
  captureCropCanvas.addEventListener("pointerdown", (event) => {
    if (captureCropCanvas.setPointerCapture) {
      try {
        captureCropCanvas.setPointerCapture(event.pointerId);
      } catch (_) {}
    }
    onCaptureCropPointerDown(event);
  });
  captureCropCanvas.addEventListener("pointermove", onCaptureCropPointerMove);
  captureCropCanvas.addEventListener("pointerup", (event) => {
    if (captureCropCanvas.releasePointerCapture) {
      try {
        captureCropCanvas.releasePointerCapture(event.pointerId);
      } catch (_) {}
    }
    onCaptureCropPointerUp();
  });
  captureCropCanvas.addEventListener("pointercancel", onCaptureCropPointerUp);
  captureCropCanvas.addEventListener("pointerleave", () => {
    if (captureCropState.drawing) {
      onCaptureCropPointerUp();
    }
  });
}

window.addEventListener("resize", () => {
  if (!captureCropState.open || !captureCropState.loaded) {
    return;
  }
  resizeCaptureCropCanvas();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (captureCropState.open && !captureCropState.applyRunning) {
    event.preventDefault();
    closeCaptureCropModal();
    return;
  }
  if (supportSheetOpen) {
    event.preventDefault();
    closeSupportPanel();
  }
});

const runJobButton = el("runJob");
if (runJobButton) {
  runJobButton.addEventListener("click", onRun);
}

const cancelRunButton = el("cancelRun");
if (cancelRunButton) {
  cancelRunButton.addEventListener("click", onCancelRun);
}

const runGuidedSetupButton = el("runGuidedSetup");
if (runGuidedSetupButton) {
  runGuidedSetupButton.addEventListener("click", onRunGuidedSetup);
}

const restartBackendButton = el("restartBackend");
if (restartBackendButton) {
  restartBackendButton.addEventListener("click", onRestartBackend);
}

const clearSetupLogButton = el("clearSetupLog");
if (clearSetupLogButton) {
  clearSetupLogButton.addEventListener("click", () => {
    const logNode = el("setupLog");
    if (logNode) {
      logNode.textContent = getLocale() === "ko" ? "[안내] 로그를 지웠습니다." : "[Info] Log cleared.";
    }
  });
}

const clearCacheFilesButton = el("clearCacheFiles");
if (clearCacheFilesButton) {
  clearCacheFilesButton.addEventListener("click", onClearCacheFiles);
}

if (window.drumSheetAPI && typeof window.drumSheetAPI.onSetupLog === "function") {
  window.drumSheetAPI.onSetupLog((payload) => {
    const line = String(payload?.line || "").trim();
    if (!line) {
      return;
    }
    appendSetupLogLine(line);
  });
}

if (window.drumSheetAPI && typeof window.drumSheetAPI.onSetupState === "function") {
  window.drumSheetAPI.onSetupState((payload) => {
    setupRunning = Boolean(payload?.running);
    backendBridgeState = {
      ...backendBridgeState,
      setupRunning,
    };
    renderBackendBridgeState();
    refreshCaptureWorkflowUi();
  });
}

if (window.drumSheetAPI && typeof window.drumSheetAPI.onBackendState === "function") {
  window.drumSheetAPI.onBackendState((payload) => {
    const wasReady = backendBridgeState.ready;
    backendBridgeState = {
      ready: Boolean(payload?.ready),
      starting: Boolean(payload?.starting),
      running: Boolean(payload?.running),
      error: String(payload?.error || ""),
      setupRunning: Boolean(payload?.setupRunning),
    };
    renderBackendBridgeState();
    if (backendBridgeState.ready && (!wasReady || !latestRuntime)) {
      void refreshRuntimeStatus({ force: true, syncBackendStateOnFailure: false });
    }
    refreshCaptureWorkflowUi();
  });
}

function refreshLocalizedUi() {
  applyI18n(document);
  const setupLog = el("setupLog");
  if (setupLog) {
    const current = String(setupLog.textContent || "").trim();
    const knownDefaults = new Set([
      "",
      "[안내] 로그를 지웠습니다.",
      "[Info] Log cleared.",
      "support.setup.defaultLog",
      t("support.setup.defaultLog"),
    ]);
    if (knownDefaults.has(current) || current === "[안내] 문제가 발생하면 아래 로그에서 원인을 확인할 수 있습니다." || current === "[Info] If something goes wrong, inspect the log below.") {
      setupLog.textContent = defaultSetupLogText();
    }
  }
  syncThemeToggleUi();
  syncLocaleToggleUi();
  renderYoutubePrepareState();
  renderRoiFrameRequestState();
  refreshAlwaysOnTopButton();
  renderBackendBridgeState();
  updateCaptureSensitivityHelp();
  updateUpscaleUi();
  applyCapturePreset(currentPreset, { withLog: false });
  videoRangePicker.onSourceTypeChange?.();
  if (latestRuntime) {
    renderRuntimeStatus(latestRuntime);
  } else {
    renderRuntimeError();
  }
  renderRoiAssist(currentRoiSnapshot);
  if (resultImagePaths.length) {
    renderResultThumbnails(resultImagePaths, resultPageDiagnostics);
  } else {
    syncResultReviewUi();
  }
  refreshCaptureWorkflowUi();
}

initLocale();
bindStepNavigation();
bindPresetButtons();
bindThemeToggle();
bindLocaleToggle();
onLocaleChange(() => {
  refreshLocalizedUi();
});
updateSourceRows();
updateManualTools();
renderYoutubePrepareState();
renderRoiFrameRequestState();
renderRoiAssist(null);
updateCaptureSensitivityHelp();
updateUpscaleUi();
applyCapturePreset("basic", { withLog: false });
refreshRuntimeStatus();
refreshBackendBridgeState();
renderBackendBridgeState();
setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
syncResultReviewUi();
syncAlwaysOnTopState();

const filePathNode = el("filePath");
if (sourceType() === "file" && filePathNode?.value) {
  videoRangePicker.loadLocalFile(filePathNode.value);
}

refreshCaptureWorkflowUi();
