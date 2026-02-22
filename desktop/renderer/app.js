import { el, fileUrl, parseJsonOrNull } from "./modules/dom.js";
import { createJob, getFormats, getJob, getRuntimeStatus, requestPreviewFrame, requestPreviewSource, sourceType } from "./modules/job-api.js";
import { createAudioSeparationUi } from "./modules/audio-separation-ui.js";
import { friendlyLayoutLabel, selectedLayoutHint, updateLayoutHintUi } from "./modules/layout-presets.js";
import { friendlyMessage, friendlyStatusText, friendlyStepName } from "./modules/messages.js";
import { createRoiController } from "./modules/roi-controller.js";
import { renderRuntimeError, renderRuntimeStatus } from "./modules/runtime-status-ui.js";
import { appendLog, clearResultMeta, renderResultMeta, setPipelineState, setProgress, setStatus } from "./modules/status-ui.js";
import { createVideoRangePicker } from "./modules/video-range-picker.js";

const API_BASE = window.drumSheetAPI.apiBase || "http://127.0.0.1:8000";
let activePoll = null;
let outputDir = "";
let outputPdf = "";
let latestRuntime = null;
let activeMode = "capture";
let runState = "idle";
let currentPreset = "basic";
let manualOpenStep = null;
let lastSourceFingerprint = currentSourceFingerprint();
let lastSourceType = sourceType();
let previewRequestToken = 0;

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
    hint: "대부분 영상은 기본(추천)으로 충분합니다. 결과가 아쉬울 때만 다른 프리셋을 선택하세요.",
    layoutHint: "auto",
    captureSensitivity: "medium",
    enableStitch: false,
    overlapThreshold: 0.2,
    enableUpscale: false,
    upscaleFactor: "2.0",
  },
  scroll: {
    hint: "스크롤 악보가 위/아래로 흐르는 영상에 맞춘 프리셋입니다. 스티칭과 중복 억제를 강화합니다.",
    layoutHint: "full_scroll",
    captureSensitivity: "medium",
    enableStitch: true,
    overlapThreshold: 0.24,
    enableUpscale: false,
    upscaleFactor: "2.0",
  },
  quality: {
    hint: "출력 선명도를 우선합니다. 처리 시간과 리소스 사용량이 증가합니다.",
    layoutHint: "auto",
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

function toNumberOrNull(raw) {
  const value = Number(String(raw || "").trim());
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
    return value ? `파일: ${pathBaseName(value)}` : "파일 선택 대기";
  }
  const value = String(el("youtubeUrl")?.value || "").trim();
  return value ? `URL: ${truncateMiddle(value, 42)}` : "URL 입력 대기";
}

function rangeSummaryText() {
  const { start, end } = getRangeValues();
  if (!isRangeValid()) {
    return "구간 값 오류";
  }
  if (start == null && end == null) {
    return "전체 구간";
  }
  const startText = start == null ? "시작" : formatSecToMmss(start);
  const endText = end == null ? "끝" : formatSecToMmss(end);
  return `${startText}~${endText}`;
}

function roiSummaryText() {
  return isRoiReady() ? "영역 지정 완료" : "영역 지정 필요";
}

function presetLabel(name = currentPreset) {
  if (name === "scroll") {
    return "스크롤 최적화";
  }
  if (name === "quality") {
    return "고해상도";
  }
  return "기본";
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
    runButton.textContent = "파일/URL을 선택해 주세요";
    runButton.disabled = true;
    hint.textContent = "먼저 입력 소스를 선택해 주세요.";
    return;
  }

  if (!isRangeValid()) {
    runButton.textContent = "구간 값을 확인해 주세요";
    runButton.disabled = true;
    hint.textContent = "끝 시간이 시작 시간보다 커야 합니다.";
    return;
  }

  if (!isRoiReady()) {
    runButton.textContent = "악보 영역을 지정해 주세요";
    runButton.disabled = true;
    hint.textContent = "3단계에서 미리보기 화면을 불러와 드래그로 악보 영역을 지정해 주세요.";
    return;
  }

  if (!isExportReady()) {
    runButton.textContent = "출력 형식을 선택해 주세요";
    runButton.disabled = true;
    hint.textContent = "PNG/JPG/PDF 중 최소 하나를 선택해 주세요.";
    return;
  }

  runButton.textContent = ready ? "처리 시작" : "처리 준비 중";
  runButton.disabled = !ready;
  hint.textContent = "준비 완료. 처리 시작을 누르면 바로 작업합니다.";
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
    low: "중복 캡처를 가장 강하게 줄입니다. 처리 속도는 빠르고 결과 장수는 적습니다.",
    medium: "대부분 영상에 권장됩니다.",
    high: "미세 변화까지 최대한 반영합니다. 대신 중복 캡처가 늘 수 있습니다.",
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
  const layoutHintNode = el("layoutHint");
  const enableStitch = el("enableStitch");
  const overlap = el("overlapThreshold");
  const enableUpscale = el("enableUpscale");
  const upscaleFactor = el("upscaleFactor");
  const presetHint = el("presetHint");

  if (sensitivity) {
    sensitivity.value = preset.captureSensitivity;
  }
  if (layoutHintNode) {
    layoutHintNode.value = preset.layoutHint;
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
  updateLayoutHintUi({ applyDefaults: false });
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
}

function renderResultThumbnails(imagePaths = []) {
  const grid = el("resultThumbGrid");
  if (!grid) {
    return;
  }
  grid.replaceChildren();
  if (!Array.isArray(imagePaths) || imagePaths.length === 0) {
    return;
  }

  const fragment = document.createDocumentFragment();
  imagePaths.slice(0, 60).forEach((imagePath, idx) => {
    const card = document.createElement("article");
    card.className = "result-thumb";

    const preview = document.createElement("img");
    preview.src = imagePath.startsWith("file://") ? imagePath : fileUrl(imagePath);
    preview.alt = `result page ${idx + 1}`;
    preview.addEventListener("click", () => {
      window.drumSheetAPI.openPath(imagePath);
    });

    const meta = document.createElement("div");
    meta.className = "result-thumb-meta";

    const label = document.createElement("span");
    label.textContent = `페이지 ${idx + 1}`;

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "secondary";
    openButton.textContent = "열기";
    openButton.addEventListener("click", () => {
      window.drumSheetAPI.openPath(imagePath);
    });

    meta.append(label, openButton);
    card.append(preview, meta);
    fragment.append(card);
  });

  grid.append(fragment);
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
    appendLog("오류: 미리보기 이미지를 불러오지 못했습니다.");
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
  roiController.clearPreview();
  clearResultMeta();
  clearResultThumbnails();
  outputDir = "";
  outputPdf = "";

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
}

function renderResultPreview(imagePath) {
  const previewImage = el("resultPreviewImage");
  if (!previewImage) {
    return;
  }
  const path = String(imagePath || "").trim();
  if (!path) {
    previewImage.style.display = "none";
    previewImage.removeAttribute("src");
    return;
  }
  const src = path.startsWith("http://") || path.startsWith("https://") || path.startsWith("file://") ? path : fileUrl(path);
  previewImage.src = src;
  previewImage.style.display = "block";
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
  renderResultThumbnails(meta.imagePaths || []);
  renderResultPreview(meta.firstImagePath);

  if (job?.result?.runtime) {
    latestRuntime = job.result.runtime;
    renderRuntimeStatus(latestRuntime);
    applyUpscaleAvailability(latestRuntime);
  }

  const canEditRoi = meta.hasResultImage;
  if (canEditRoi && meta.firstImagePath) {
    roiController.showPreviewWithRoi(meta.firstImagePath);
  }
  roiController.setRoiEditorVisibility(canEditRoi);
  roiController.setRoiEditMode(canEditRoi);

  refreshCaptureWorkflowUi();
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
    appendLog(`영상 형태: ${friendlyLayoutLabel(selectedLayoutHint())}`);
    refreshCaptureWorkflowUi();

    const jobId = await createJob(API_BASE);
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
  } catch (_) {
    renderRuntimeError();
    applyUpscaleAvailability(latestRuntime);
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
    setStatus("영역 지정용 화면을 불러오는 중");
    appendLog("영역 지정 화면 요청");
    roiController.clearPreview();
    const previewStartSec = videoRangePicker.getPreviewSecond();
    if (previewStartSec != null) {
      appendLog(`영역 지정 시점: ${previewStartSec.toFixed(1)}초`);
    }
    const previewImagePath = await requestPreviewFrame(API_BASE, { startSecOverride: previewStartSec });
    if (requestToken !== previewRequestToken || sourceFingerprint !== currentSourceFingerprint()) {
      return;
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
  } catch (error) {
    if (requestToken !== previewRequestToken) {
      return;
    }
    appendLog(`오류: ${error.message}`);
    setStatus("영역 지정 화면 불러오기 실패");
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

async function onLockRoiFrame() {
  await onLoadPreviewForRoi();
  if (typeof roiController.applyCurrentRoi === "function") {
    const applied = roiController.applyCurrentRoi();
    if (applied) {
      appendLog("현재 프레임 기준 ROI를 고정했습니다.");
    }
  }
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
    setStatus("유튜브 영상 준비 중");
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
    setStatus("유튜브 영상 준비 실패");
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

const layoutHintNode = el("layoutHint");
if (layoutHintNode) {
  layoutHintNode.addEventListener("change", () => {
    updateLayoutHintUi({ applyDefaults: true });
    manualOpenStep = "roi";
    appendLog("영상 형태 변경: 추천 옵션을 적용했어요");
    refreshCaptureWorkflowUi();
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

bindStepNavigation();
bindPresetButtons();
updateSourceRows();
updateManualTools();
updateLayoutHintUi({ applyDefaults: false });
updateCaptureSensitivityHelp();
updateUpscaleUi();
applyCapturePreset("basic", { withLog: false });
refreshRuntimeStatus();
setActiveMode("capture");
setPipelineState({ currentStep: "queued", progress: 0, status: "queued", isYoutubeSource: sourceType() === "youtube" });

const filePathNode = el("filePath");
if (sourceType() === "file" && filePathNode?.value) {
  videoRangePicker.loadLocalFile(filePathNode.value);
}

refreshCaptureWorkflowUi();
