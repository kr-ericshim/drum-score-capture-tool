import { el, fileUrl, parseJsonOrNull } from "./modules/dom.js";
import {
  clearCache,
  createJob,
  cropCapture,
  getCacheUsage,
  getFormats,
  getJob,
  getRuntimeStatus,
  requestPreviewFrame,
  requestPreviewSource,
  reviewExport,
  sourceType,
} from "./modules/job-api.js";
import { createAudioSeparationUi } from "./modules/audio-separation-ui.js";
import { friendlyMessage, friendlyStatusText, friendlyStepName } from "./modules/messages.js";
import { createRoiController } from "./modules/roi-controller.js";
import { renderRuntimeError, renderRuntimeStatus } from "./modules/runtime-status-ui.js";
import { appendLog, clearResultMeta, renderResultMeta, setPipelineState, setProgress, setStatus } from "./modules/status-ui.js";
import { createVideoRangePicker } from "./modules/video-range-picker.js";

const API_BASE = window.drumSheetAPI.apiBase || "http://127.0.0.1:8000";
let activePoll = null;
let outputDir = "";
let outputPdf = "";
let activeCaptureJobId = "";
let currentPreviewImagePath = "";
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
let activeMode = "capture";
let runState = "idle";
let currentPreset = "basic";
let manualOpenStep = null;
let lastSourceFingerprint = currentSourceFingerprint();
let lastSourceType = sourceType();
let previewRequestToken = 0;
let setupRunning = false;
let cacheClearRunning = false;
let cacheUsageText = "";
let cacheUsageLoading = false;
let lastCacheUsageFetchAt = 0;
let alwaysOnTopEnabled = false;
let backendBridgeState = {
  ready: false,
  starting: true,
  running: false,
  error: "",
  setupRunning: false,
};

const STEP_KEYS = ["source", "range", "roi", "export"];
const STEP_DETAIL_IDS = {
  source: "stepSourceDetails",
  range: "stepRangeDetails",
  roi: "stepRoiDetails",
  export: "stepExportDetails",
};
const STEP_CARD_SUMMARY_IDS = {
  source: "stepSourceSummary",
  range: "stepRangeSummary",
  roi: "stepRoiSummary",
  export: "stepExportSummary",
};
const STEP_BAR_SUMMARY_IDS = {
  source: "stepBadgeSource",
  range: "stepBadgeRange",
  roi: "stepBadgeRoi",
  export: "stepBadgeExport",
};
const STEP_BAR_BUTTON_IDS = {
  source: "stepperSource",
  range: "stepperRange",
  roi: "stepperRoi",
  export: "stepperExport",
};

const PRESET_CONFIG = {
  basic: {
    hint: "페이지 넘김을 줄이는 연주용 기본값입니다. 대부분 이 모드 그대로 쓰면 됩니다.",
    captureSensitivity: "medium",
    enableStitch: false,
    overlapThreshold: 0.2,
    enableUpscale: false,
    upscaleFactor: "2.0",
  },
  scroll: {
    hint: "스크롤 영상에서 줄이 이어지게 맞추는 모드입니다. 긴 스크롤 악보에 유리합니다.",
    captureSensitivity: "low",
    enableStitch: true,
    overlapThreshold: 0.26,
    enableUpscale: false,
    upscaleFactor: "2.0",
  },
  quality: {
    hint: "글자 선명도를 더 높이는 모드입니다. 처리 시간이 더 걸릴 수 있습니다.",
    captureSensitivity: "high",
    enableStitch: false,
    overlapThreshold: 0.2,
    enableUpscale: true,
    upscaleFactor: "3.0",
  },
};

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
  return now.toLocaleTimeString("ko-KR", {
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

function compactErrorText(raw, fallback = "오류 원인을 확인하지 못했습니다.") {
  const value = String(raw || "").trim();
  if (!value) {
    return fallback;
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
    chip.textContent = "설치/복구 진행 중";
    text.textContent = "자동 설치/복구가 진행 중입니다. 완료될 때까지 잠시만 기다려 주세요.";
  } else if (backendBridgeState.ready) {
    chip.classList.add("setup-chip-ok");
    chip.textContent = "엔진 연결 완료";
    text.textContent = "로컬 처리 엔진이 정상 연결되었습니다. 바로 작업을 시작할 수 있어요.";
  } else if (backendBridgeState.starting) {
    chip.classList.add("setup-chip-running");
    chip.textContent = "엔진 시작 중";
    text.textContent = "로컬 처리 엔진을 시작하고 있습니다. 잠시 후 자동으로 연결됩니다.";
  } else if (backendBridgeState.error) {
    chip.classList.add("setup-chip-error");
    chip.textContent = "엔진 연결 실패";
    text.textContent = compactErrorText(backendBridgeState.error, "엔진 연결에 실패했습니다. 자동 설치/복구를 눌러 복구해 주세요.");
  } else {
    chip.classList.add("setup-chip-warn");
    chip.textContent = "엔진 대기";
    text.textContent = "로컬 처리 엔진이 아직 연결되지 않았습니다. 백엔드 다시 연결 또는 설치/복구를 눌러 주세요.";
  }

  if (setupButton) {
    setupButton.disabled = setupRunning || backendBridgeState.setupRunning;
    setupButton.textContent = setupRunning || backendBridgeState.setupRunning ? "설치/복구 진행 중..." : "자동 설치/복구";
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
      clearCacheButton.textContent = "캐시 정리 중...";
    } else if (cacheUsageLoading && !cacheUsageText) {
      clearCacheButton.textContent = "캐시 용량 확인 중...";
    } else if (cacheUsageText) {
      clearCacheButton.textContent = `캐시 정리 (${cacheUsageText})`;
    } else {
      clearCacheButton.textContent = "캐시 정리";
    }
  }
}

function refreshAlwaysOnTopButton() {
  const button = el("toggleAlwaysOnTop");
  if (!button) {
    return;
  }
  button.textContent = alwaysOnTopEnabled ? "연습 고정: 켬" : "연습 고정: 끔";
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
    appendLog(alwaysOnTopEnabled ? "연습 고정 켬: 창을 항상 위에 유지합니다." : "연습 고정 끔");
  } catch (_) {
    appendLog("오류: 창 고정 상태를 바꾸지 못했습니다.");
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
    cacheUsageText = totalBytes > 0 ? `약 ${totalHuman}` : "약 0 B";
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
    }
    refreshCaptureWorkflowUi();
  } catch (error) {
    appendSetupLogLine(`오류: 엔진 상태 확인 실패 (${compactErrorText(error?.message)})`);
  }
}

async function onRunGuidedSetup() {
  if (!window.drumSheetAPI || typeof window.drumSheetAPI.runGuidedSetup !== "function") {
    appendSetupLogLine("오류: 현재 앱에서 자동 설치/복구 기능을 지원하지 않습니다.");
    return;
  }
  if (setupRunning) {
    return;
  }

  const proceed = window.confirm(
    "자동 설치/복구를 시작할까요?\n\n백엔드를 잠시 멈추고 Python/패키지/npm 상태를 자동으로 정리합니다.",
  );
  if (!proceed) {
    return;
  }

  try {
    setupRunning = true;
    renderBackendBridgeState();
    refreshCaptureWorkflowUi();
    appendSetupLogLine("자동 설치/복구 요청");
    const result = await window.drumSheetAPI.runGuidedSetup();
    if (result?.ok) {
      appendSetupLogLine("설치/복구 완료");
      appendLog("설치/복구 완료: 로컬 엔진이 다시 연결되었습니다.");
      await refreshRuntimeStatus();
    } else {
      const message = compactErrorText(result?.error, "설치/복구 작업이 실패했습니다.");
      appendSetupLogLine(`오류: ${message}`);
      appendLog(`오류: 설치/복구 실패 (${message})`);
    }
  } catch (error) {
    const message = compactErrorText(error?.message, "설치/복구 실행 실패");
    appendSetupLogLine(`오류: ${message}`);
    appendLog(`오류: ${message}`);
  } finally {
    setupRunning = false;
    await refreshBackendBridgeState();
    refreshCaptureWorkflowUi();
  }
}

async function onRestartBackend() {
  if (!window.drumSheetAPI || typeof window.drumSheetAPI.restartBackend !== "function") {
    appendSetupLogLine("오류: 백엔드 다시 연결 기능을 지원하지 않습니다.");
    return;
  }

  try {
    appendSetupLogLine("백엔드 다시 연결 요청");
    const result = await window.drumSheetAPI.restartBackend();
    if (result?.ok) {
      appendSetupLogLine("백엔드 연결 성공");
      await refreshRuntimeStatus();
    } else {
      appendSetupLogLine(`오류: ${compactErrorText(result?.error, "백엔드 다시 연결 실패")}`);
    }
  } catch (error) {
    appendSetupLogLine(`오류: ${compactErrorText(error?.message, "백엔드 다시 연결 실패")}`);
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
    `캐시/결과 파일을 정리할까요?\n\n이전 악보 추출/음원 분리 결과와 중간 파일이 삭제됩니다.${usageHint}\n이 작업은 되돌릴 수 없습니다.`,
  );
  if (!proceed) {
    return;
  }

  try {
    cacheClearRunning = true;
    renderBackendBridgeState();
    appendSetupLogLine("캐시 정리 요청");
    const result = await clearCache(API_BASE);
    const reclaimed = String(result?.reclaimed_human || "0 B");
    const clearedPaths = Number(result?.cleared_paths || 0);
    const skipped = Array.isArray(result?.skipped_paths) ? result.skipped_paths.length : 0;
    appendSetupLogLine(`캐시 정리 완료: 항목 ${clearedPaths}개, 확보 용량 ${reclaimed}${skipped > 0 ? `, 건너뜀 ${skipped}개` : ""}`);
    appendLog(`캐시 정리 완료: ${reclaimed} 확보`);
    setStatus("캐시 정리 완료");
    cacheUsageText = "약 0 B";
    resetResultView();
  } catch (error) {
    appendSetupLogLine(`오류: ${compactErrorText(error?.message, "캐시 정리 실패")}`);
    appendLog(`오류: ${error.message}`);
    setStatus("캐시 정리 실패");
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
    return value ? `선택됨: ${pathBaseName(value)}` : "영상 파일을 골라주세요";
  }
  const value = String(el("youtubeUrl")?.value || "").trim();
  return value ? `URL 입력됨` : "유튜브 주소를 넣어주세요";
}

function rangeSummaryText() {
  const { start, end } = getRangeValues();
  if (!isRangeValid()) {
    return "시작/끝 확인 필요";
  }
  if (start == null && end == null) {
    return "전체 구간 (권장)";
  }
  const startText = start == null ? "시작" : formatSecToMmss(start);
  const endText = end == null ? "끝" : formatSecToMmss(end);
  return `${startText}~${endText}`;
}

function roiSummaryText() {
  return isRoiReady() ? "영역 지정 완료" : "악보 영역 지정 필요";
}

function presetLabel(name = currentPreset) {
  if (name === "scroll") {
    return "스크롤 맞춤";
  }
  if (name === "quality") {
    return "선명도 우선";
  }
  return "연주 기본";
}

function exportSummaryText() {
  const formats = getFormats();
  const label = formats.length ? formats.join("/").toUpperCase() : "형식 미선택";
  return `${label} · ${presetLabel(currentPreset)}`;
}

function determineActiveStep() {
  if (!isSourceReady()) {
    return "source";
  }
  if (!isRangeValid()) {
    return "range";
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

function resetRoiForSourceChange({ silent = true } = {}) {
  previewRequestToken += 1;
  const roiInput = el("roiInput");
  const hadRoi = Boolean(String(roiInput?.value || "").trim());
  roiController.clearPreview();
  if (roiInput) {
    roiInput.value = "";
    roiInput.dispatchEvent(new Event("input", { bubbles: true }));
  } else {
    refreshCaptureWorkflowUi();
  }
  if (!silent && hadRoi) {
    appendLog("입력 소스가 바뀌어 이전 악보 영역을 초기화했습니다.");
  }
}

function resetForSourceChange({ silent = true } = {}) {
  previewRequestToken += 1;
  if (activePoll) {
    clearInterval(activePoll);
    activePoll = null;
  }

  runState = "idle";
  resetRoiForSourceChange({ silent });
  videoRangePicker.clearMedia();
  videoRangePicker.clearRangeState();
  resetResultView();
  manualOpenStep = "source";
  setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
  if (!silent) {
    appendLog("새로운 소스로 전환되어 기존 결과와 미리보기 상태를 초기화했습니다.");
  }
  setStatus("대기 중");
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
    runButton.textContent = setupRunning || backendBridgeState.setupRunning ? "설치/복구 진행 중..." : "먼저 엔진 연결이 필요해요";
    runButton.disabled = true;
    cancelButton.style.display = "none";
    const errorText = compactErrorText(backendBridgeState.error, "");
    hint.textContent = errorText
      ? `엔진 연결 문제: ${errorText}`
      : "상단의 자동 설치/복구 또는 엔진 다시 연결 버튼을 눌러주세요.";
    return;
  }

  if (runState === "running") {
    runButton.textContent = "처리 중...";
    runButton.disabled = true;
    cancelButton.style.display = "inline-flex";
    hint.textContent = "처리 중입니다. 필요하면 중단 버튼으로 진행 조회를 멈출 수 있어요.";
    return;
  }

  cancelButton.style.display = "none";

  if (runState === "done" && outputDir) {
    runButton.textContent = "다시 실행";
    runButton.disabled = !isSourceReady();
    hint.textContent = "완료되었습니다. 결과 폴더를 열거나 다시 실행할 수 있어요.";
    return;
  }

  if (!isSourceReady()) {
    runButton.textContent = "1단계에서 영상을 선택해 주세요";
    runButton.disabled = true;
    hint.textContent = "로컬 파일이나 유튜브 URL 중 하나를 먼저 입력해 주세요.";
    return;
  }

  if (!isRangeValid()) {
    runButton.textContent = "시작/끝 시간을 확인해 주세요";
    runButton.disabled = true;
    hint.textContent = "끝 시간이 시작 시간보다 커야 합니다.";
    return;
  }

  if (!isRoiReady()) {
    runButton.textContent = "3단계에서 악보 영역을 잡아주세요";
    runButton.disabled = true;
    hint.textContent = "악보 화면 열기 버튼을 누른 뒤, 악보 부분을 마우스로 드래그해 주세요.";
    return;
  }

  if (!isExportReady()) {
    runButton.textContent = "출력 형식을 선택해 주세요";
    runButton.disabled = true;
    hint.textContent = "PNG/JPG/PDF 중 최소 하나를 선택해 주세요.";
    return;
  }

  runButton.textContent = ready ? "처리 시작" : "입력 확인 중";
  runButton.disabled = !ready;
  hint.textContent = "준비 완료. 처리 시작을 누르면 바로 진행됩니다.";
}

function refreshCaptureWorkflowUi() {
  updateRangeHumanLabels();

  const completion = {
    source: isSourceReady(),
    range: isRangeValid(),
    roi: isRoiReady(),
    export: isExportReady(),
  };

  setStepText("source", sourceSummaryText());
  setStepText("range", rangeSummaryText());
  setStepText("roi", roiSummaryText());
  setStepText("export", exportSummaryText());
  setStepSummaryTone("source", completion.source ? "ready" : "need");
  setStepSummaryTone("range", completion.range ? "ready" : "alert");
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
}

function setActiveMode(mode) {
  activeMode = mode === "audio" ? "audio" : "capture";
  const layout = document.querySelector(".layout");
  if (layout) {
    layout.classList.toggle("mode-audio", activeMode === "audio");
  }
  const captureTab = el("tabCapture");
  const audioTab = el("tabAudio");
  if (captureTab) {
    captureTab.classList.toggle("mode-tab-active", activeMode === "capture");
  }
  if (audioTab) {
    audioTab.classList.toggle("mode-tab-active", activeMode === "audio");
  }
  if (activeMode === "audio") {
    audioSeparationUi.updateSourceRows();
  } else {
    refreshCaptureWorkflowUi();
  }
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
    low: "같은 장면이 반복 저장되는 것을 강하게 줄입니다. 대부분 이 옵션이 깔끔합니다.",
    medium: "균형형 옵션입니다. 처음 사용할 때 추천합니다.",
    high: "미세한 변화까지 민감하게 잡습니다. 대신 비슷한 장면이 더 많이 저장될 수 있습니다.",
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
    hint.textContent = "현재 환경에서 업스케일 엔진을 찾지 못해 사용할 수 없습니다.";
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
            : "업스케일 엔진";
  factor.disabled = !toggle.checked;
  hint.textContent = toggle.checked
    ? `업스케일은 ${engineName}으로 처리합니다. 엔진 경로가 실패하면 작업이 중단됩니다.`
    : `업스케일을 끄면 원본 해상도로 저장합니다. (사용 가능 엔진: ${engineName})`;
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
  const presetHint = el("presetHint");

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
  if (presetHint) {
    presetHint.textContent = preset.hint;
  }

  updatePresetButtons();
  updateCaptureSensitivityHelp();
  updateUpscaleUi();
  refreshCaptureWorkflowUi();

  if (withLog) {
    appendLog(`프리셋 적용: ${presetLabel(currentPreset)}`);
  }
}

function setPathChip(pathValue) {
  const chip = el("resultPathChip");
  if (!chip) {
    return;
  }
  if (!pathValue) {
    chip.textContent = "출력 경로: -";
    return;
  }
  chip.textContent = `출력 경로: ${truncateMiddle(String(pathValue), 78)}`;
}

function clearResultThumbnails() {
  const grid = el("resultThumbGrid");
  if (grid) {
    grid.replaceChildren();
  }
  resultImagePaths = [];
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

function includedResultImagePaths() {
  pruneExcludedResultIndices();
  return resultImagePaths.filter((_, idx) => !excludedResultIndices.has(idx));
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

  const total = resultImagePaths.length;
  const kept = includedResultImagePaths().length;
  const excluded = Math.max(0, total - kept);

  if (reviewBar) {
    reviewBar.style.display = total > 0 ? "flex" : "none";
  }
  if (summary) {
    if (total <= 0) {
      summary.textContent = "캡쳐 결과를 검토해 제외할 항목을 선택해 주세요.";
    } else if (excluded > 0) {
      summary.textContent = `전체 캡쳐 ${total}개 중 ${excluded}개 제외 예정입니다. 반영 버튼으로 페이지를 다시 생성하세요.`;
    } else {
      summary.textContent = `전체 캡쳐 ${total}개 포함 상태입니다. 중복/오류 캡쳐가 있으면 체크를 해제해 주세요.`;
    }
  }
  if (keepAllButton) {
    keepAllButton.disabled = total <= 0 || reviewApplyRunning;
  }
  if (applyButton) {
    applyButton.disabled = reviewApplyRunning || !activeCaptureJobId || total <= 0 || kept <= 0 || excluded <= 0;
    applyButton.textContent = reviewApplyRunning ? "반영 중..." : "선택 반영 후 페이지 다시 생성";
  }
}

function renderResultThumbnails(imagePaths = []) {
  const grid = el("resultThumbGrid");
  if (!grid) {
    return;
  }
  grid.replaceChildren();
  resultImagePaths = Array.isArray(imagePaths) ? imagePaths.slice() : [];
  pruneExcludedResultIndices();
  if (resultImagePaths.length === 0) {
    syncResultReviewUi();
    return;
  }

  const fragment = document.createDocumentFragment();
  resultImagePaths.forEach((imagePath, idx) => {
    const isExcluded = excludedResultIndices.has(idx);
    const card = document.createElement("article");
    card.className = isExcluded ? "result-thumb is-excluded" : "result-thumb";

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
    checkText.textContent = `캡쳐 ${idx + 1}`;
    checkLabel.append(includeCheck, checkText);

    const state = document.createElement("span");
    state.className = "result-thumb-state";
    state.textContent = isExcluded ? "제외 예정" : "포함";

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "secondary";
    openButton.textContent = "열기";
    openButton.addEventListener("click", () => {
      window.drumSheetAPI.openPath(imagePath);
    });

    const recropButton = document.createElement("button");
    recropButton.type = "button";
    recropButton.className = "secondary";
    recropButton.textContent = "다시 자르기";
    recropButton.addEventListener("click", () => {
      openCaptureCropModal(imagePath, idx);
    });

    includeCheck.addEventListener("change", () => {
      if (includeCheck.checked) {
        excludedResultIndices.delete(idx);
        card.classList.remove("is-excluded");
        state.textContent = "포함";
      } else {
        excludedResultIndices.add(idx);
        card.classList.add("is-excluded");
        state.textContent = "제외 예정";
        if (currentPreviewImagePath === imagePath) {
          renderResultPreview(firstIncludedImagePath());
        }
      }
      syncResultReviewUi();
    });

    const left = document.createElement("div");
    left.className = "result-thumb-left";
    left.append(checkLabel, state);

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
  ctx.fillStyle = "rgba(9, 24, 41, 0.45)";
  ctx.fillRect(0, 0, width, height);

  const rect = captureCropState.rect;
  if (!rect || rect.w <= 0 || rect.h <= 0) {
    return;
  }

  ctx.clearRect(rect.x, rect.y, rect.w, rect.h);
  ctx.strokeStyle = "#31d5c8";
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
    apply.textContent = captureCropState.applyRunning ? "저장 중..." : "이 캡쳐에 반영";
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
    appendLog("오류: 자를 캡쳐 경로를 찾지 못했습니다.");
    return;
  }
  const { modal, image } = getCaptureCropElements();
  if (!modal || !image) {
    appendLog("오류: 캡쳐 편집 창을 열 수 없습니다.");
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
  setStatus("캡쳐 다시 자르기: 영역을 드래그해 주세요");

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
    appendLog("오류: 캡쳐 이미지를 불러오지 못했습니다.");
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
    appendLog("오류: 현재 작업을 찾지 못해 캡쳐 자르기를 저장할 수 없습니다.");
    return;
  }
  const roi = buildCropRoiFromState();
  if (!roi) {
    appendLog("안내: 먼저 캡쳐에서 남길 영역을 드래그해 주세요.");
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
    appendLog(`캡쳐 다시 자르기 저장: ${pathBaseName(response.capture_path)} (${response.width}x${response.height})`);
    setStatus("캡쳐 자르기 저장 완료");
    closeCaptureCropModal();
  } catch (error) {
    appendLog(`오류: ${error.message}`);
    setStatus("캡쳐 자르기 저장 실패");
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
    appendLog("오류: 미리보기 이미지를 불러오지 못했습니다. 시작 시간을 살짝 옮겨 다시 눌러 주세요.");
    setStatus("영역 지정 화면 표시 실패");
  },
});

const videoRangePicker = createVideoRangePicker({
  sourceType,
  onRangeChange: () => {
    refreshCaptureWorkflowUi();
  },
});

const audioSeparationUi = createAudioSeparationUi({ apiBase: API_BASE });

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
    appendLog("안내: 3단계에서 미리보기 화면을 다시 불러오고 악보 영역을 다시 드래그해 보세요.");
    return;
  }
  if (detail.includes("ffmpeg")) {
    appendLog("안내: 영상 코덱 문제일 수 있습니다. 시작/끝 구간을 좁히거나 다른 파일로 시도해 보세요.");
    return;
  }
  if (detail.includes("youtube")) {
    appendLog("안내: 유튜브 준비 실패 시 로컬 파일로 먼저 테스트해 보세요.");
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
  renderResultThumbnails(reviewPaths);
  const previewPath = firstIncludedImagePath() || meta.firstImagePath;
  renderResultPreview(previewPath);

  if (job?.result?.runtime) {
    latestRuntime = job.result.runtime;
    renderRuntimeStatus(latestRuntime);
    applyUpscaleAvailability(latestRuntime);
  }

  refreshCaptureWorkflowUi();
}

function onKeepAllResultPages() {
  if (reviewApplyRunning || !resultImagePaths.length) {
    return;
  }
  excludedResultIndices.clear();
  renderResultThumbnails(resultImagePaths);
  appendLog("결과 검토: 모든 캡쳐를 포함 상태로 되돌렸습니다.");
}

async function onApplyResultReview() {
  if (reviewApplyRunning) {
    return;
  }
  if (!activeCaptureJobId) {
    appendLog("오류: 검토 반영할 완료 작업을 찾지 못했습니다.");
    return;
  }

  const keepImages = includedResultImagePaths();
  if (keepImages.length <= 0) {
    appendLog("안내: 최소 1개 캡쳐는 포함 상태로 남겨야 저장할 수 있습니다.");
    return;
  }
  if (keepImages.length === resultImagePaths.length) {
    appendLog("안내: 제외된 캡쳐가 없습니다. 체크 해제 후 다시 반영해 주세요.");
    return;
  }

  reviewApplyRunning = true;
  syncResultReviewUi();
  setStatus("검토 반영 중");
  appendLog(`검토 반영 시작: 전체 캡쳐 ${resultImagePaths.length}개 중 ${keepImages.length}개 유지`);
  try {
    await reviewExport(API_BASE, activeCaptureJobId, {
      keepCaptures: keepImages,
      formats: getFormats(),
    });
    const refreshed = await getJob(API_BASE, activeCaptureJobId);
    renderResult(refreshed);
    appendLog("검토 반영 완료: 선택한 캡쳐로 페이지를 다시 생성했습니다.");
    setStatus("검토 반영 완료");
  } catch (error) {
    appendLog(`오류: ${error.message}`);
    setStatus("검토 반영 실패");
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
    setStatus("완료");
    renderResult(job);
  } else {
    runState = "idle";
    setStatus(`오류 (${job.error_code || "알 수 없음"})`);
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
      appendLog("오류: 로컬 엔진이 연결되지 않았습니다. 상단 자동 설치/복구를 먼저 실행해 주세요.");
      setStatus("엔진 연결 필요");
      refreshCaptureWorkflowUi();
      return;
    }

    if (!isSourceReady() || !isRangeValid() || !isRoiReady() || !isExportReady()) {
      refreshCaptureWorkflowUi();
      return;
    }

    runState = "running";
    resetResultView();
    setProgress(0);
    setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
    setStatus("작업을 시작하고 있어요");
    appendLog("작업 시작");
    refreshCaptureWorkflowUi();

    const jobId = await createJob(API_BASE);
    activeCaptureJobId = String(jobId || "");
    setStatus("작업 대기 중");
    activePoll = setInterval(() => {
      poll(jobId).catch((error) => {
        appendLog(`오류: ${String(error.message)}`);
        clearInterval(activePoll);
        activePoll = null;
        runState = "idle";
        setStatus("조회 실패");
        setPipelineState({ currentStep: "exporting", progress: 1, status: "error", isYoutubeSource: sourceType() === "youtube" });
        refreshCaptureWorkflowUi();
      });
    }, 700);
  } catch (error) {
    appendLog(`오류: ${error.message}`);
    runState = "idle";
    setStatus("요청 실패");
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
  setStatus("진행 조회 중단");
  appendLog("사용자가 진행 조회를 중단했습니다. 백엔드 작업은 백그라운드에서 계속될 수 있습니다.");
  setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
  refreshCaptureWorkflowUi();
}

async function refreshRuntimeStatus() {
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
    await refreshBackendBridgeState();
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
    setStatus("악보 화면을 준비 중입니다");
    appendLog("악보 영역 지정 화면 요청");
    roiController.clearPreview();
    const previewStartSec = videoRangePicker.getPreviewSecond();
    if (previewStartSec != null) {
      appendLog(`영역 지정 시점: ${previewStartSec.toFixed(1)}초`);
    }
    let previewImagePath = "";
    try {
      previewImagePath = await requestPreviewFrame(API_BASE, { startSecOverride: previewStartSec });
    } catch (firstError) {
      if (previewStartSec != null && previewStartSec > 0.25) {
        appendLog("안내: 선택 시점 프레임 추출에 실패해 영상 시작 기준으로 한 번 더 시도합니다.");
        previewImagePath = await requestPreviewFrame(API_BASE, { startSecOverride: 0 });
      } else {
        throw firstError;
      }
    }
    if (requestToken !== previewRequestToken || sourceFingerprint !== currentSourceFingerprint()) {
      appendLog("안내: 입력 값이 바뀌어 영역 지정 화면 요청이 취소되었습니다. 다시 눌러 주세요.");
      setStatus("입력 변경으로 요청 취소됨");
      return false;
    }
    manualOpenStep = "roi";
    updateManualTools();
    roiController.showPreviewWithRoi(previewImagePath);
    roiController.setRoiEditorVisibility(true);
    roiController.setRoiEditMode(true);
    el("roiEditorWrap")?.scrollIntoView({ behavior: "smooth", block: "center" });
    setStatus("화면 준비 완료. 악보 부분을 드래그해 주세요");
    appendLog("영역 지정 화면 준비 완료");
    refreshCaptureWorkflowUi();
    return true;
  } catch (error) {
    if (requestToken !== previewRequestToken) {
      return false;
    }
    appendLog(`오류: ${error.message}`);
    setStatus("악보 화면을 불러오지 못했습니다");
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
    appendLog("현재 시점 프레임을 다시 불러왔습니다.");
    setStatus("현재 시점 프레임으로 갱신됨");
  }
  refreshCaptureWorkflowUi();
}

function onApplyRoiSelection() {
  if (typeof roiController.applyCurrentRoi !== "function") {
    return;
  }
  const applied = roiController.applyCurrentRoi();
  if (!applied) {
    appendLog("안내: 먼저 악보 화면에서 영역을 드래그해 주세요.");
    setStatus("영역 지정 필요");
    return;
  }
  const applyButton = el("applyRoi");
  if (applyButton) {
    const original = "이 영역으로 진행";
    applyButton.textContent = "영역 저장됨";
    applyButton.disabled = true;
    window.setTimeout(() => {
      applyButton.disabled = false;
      applyButton.textContent = original;
    }, 850);
  }
  manualOpenStep = "export";
  appendLog("영역 저장 완료: 이 범위로 캡쳐를 진행합니다.");
  setStatus("영역 저장 완료");
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
    setStatus("유튜브 영상을 준비 중입니다");
    appendLog("유튜브 영상 준비 요청");
    const prepared = await requestPreviewSource(API_BASE);
    const playable = prepared.video_url ? `${API_BASE}${prepared.video_url}` : prepared.video_path;
    if (!playable) {
      throw new Error("재생 가능한 유튜브 영상을 준비하지 못했어요.");
    }
    videoRangePicker.loadVideoSource(playable);
    setStatus("유튜브 영상 준비 완료");
    appendLog(prepared.from_cache ? "캐시된 유튜브 영상 사용" : "유튜브 영상 다운로드 완료");
    refreshCaptureWorkflowUi();
  } catch (error) {
    appendLog(`오류: ${error.message}`);
    setStatus("유튜브 영상 준비에 실패했습니다");
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

const copySourcePathButton = el("copySourcePath");
if (copySourcePathButton) {
  copySourcePathButton.addEventListener("click", async () => {
    const sourcePath = sourceType() === "file" ? String(el("filePath")?.value || "") : String(el("youtubeUrl")?.value || "");
    const ok = await copyTextToClipboard(sourcePath);
    appendLog(ok ? "입력 경로를 복사했습니다." : "오류: 입력 경로 복사 실패");
  });
}

const copyRoiCoordsButton = el("copyRoiCoords");
if (copyRoiCoordsButton) {
  copyRoiCoordsButton.addEventListener("click", async () => {
    const value = String(el("roiInput")?.value || "");
    const ok = await copyTextToClipboard(value);
    appendLog(ok ? "ROI 좌표를 복사했습니다." : "오류: ROI 좌표 복사 실패");
  });
}

const captureSensitivityNode = el("captureSensitivity");
if (captureSensitivityNode) {
  captureSensitivityNode.addEventListener("change", () => {
    updateCaptureSensitivityHelp();
    appendLog("캡처 민감도 변경");
    refreshCaptureWorkflowUi();
  });
}

const enableUpscaleNode = el("enableUpscale");
if (enableUpscaleNode) {
  enableUpscaleNode.addEventListener("change", () => {
    updateUpscaleUi();
    appendLog(enableUpscaleNode.checked ? "GPU 업스케일 사용" : "GPU 업스케일 사용 안 함");
    refreshCaptureWorkflowUi();
  });
}

const startSecNode = el("startSec");
if (startSecNode) {
  startSecNode.addEventListener("input", () => {
    manualOpenStep = "range";
    refreshCaptureWorkflowUi();
  });
}

const endSecNode = el("endSec");
if (endSecNode) {
  endSecNode.addEventListener("input", () => {
    manualOpenStep = "range";
    refreshCaptureWorkflowUi();
  });
}

["videoSeek", "startSlider", "endSlider"].forEach((id) => {
  const node = el(id);
  if (!node) {
    return;
  }
  node.addEventListener("input", () => {
    manualOpenStep = "range";
    refreshCaptureWorkflowUi();
  });
});

["setStartAtCurrent", "setEndAtCurrent", "clearRange"].forEach((id) => {
  const node = el(id);
  if (!node) {
    return;
  }
  node.addEventListener("click", () => {
    manualOpenStep = "range";
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
    appendLog(ok ? "출력 경로를 복사했습니다." : "오류: 출력 경로 복사 실패");
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
  if (event.key !== "Escape" || !captureCropState.open || captureCropState.applyRunning) {
    return;
  }
  event.preventDefault();
  closeCaptureCropModal();
});

const runJobButton = el("runJob");
if (runJobButton) {
  runJobButton.addEventListener("click", onRun);
}

const cancelRunButton = el("cancelRun");
if (cancelRunButton) {
  cancelRunButton.addEventListener("click", onCancelRun);
}

const tabCapture = el("tabCapture");
if (tabCapture) {
  tabCapture.addEventListener("click", () => setActiveMode("capture"));
}

const tabAudio = el("tabAudio");
if (tabAudio) {
  tabAudio.addEventListener("click", () => setActiveMode("audio"));
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
      logNode.textContent = "[안내] 로그를 지웠습니다.";
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
    backendBridgeState = {
      ready: Boolean(payload?.ready),
      starting: Boolean(payload?.starting),
      running: Boolean(payload?.running),
      error: String(payload?.error || ""),
      setupRunning: Boolean(payload?.setupRunning),
    };
    renderBackendBridgeState();
    refreshCaptureWorkflowUi();
  });
}

bindStepNavigation();
bindPresetButtons();
updateSourceRows();
updateManualTools();
updateCaptureSensitivityHelp();
updateUpscaleUi();
applyCapturePreset("basic", { withLog: false });
refreshRuntimeStatus();
refreshBackendBridgeState();
renderBackendBridgeState();
setActiveMode("capture");
setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });
syncResultReviewUi();
syncAlwaysOnTopState();

const filePathNode = el("filePath");
if (sourceType() === "file" && filePathNode?.value) {
  videoRangePicker.loadLocalFile(filePathNode.value);
}

refreshCaptureWorkflowUi();
