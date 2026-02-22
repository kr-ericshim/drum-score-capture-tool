import { el, fileUrl } from "./modules/dom.js";
import { createJob, detectMode, getJob, getRuntimeStatus, requestPreviewFrame, sourceType } from "./modules/job-api.js";
import { friendlyLayoutLabel, selectedLayoutHint, updateLayoutHintUi } from "./modules/layout-presets.js";
import { friendlyMessage, friendlyStatusText, friendlyStepName } from "./modules/messages.js";
import { createRoiController } from "./modules/roi-controller.js";
import { renderRuntimeError, renderRuntimeStatus } from "./modules/runtime-status-ui.js";
import { appendLog, clearResultMeta, renderResultMeta, setProgress, setStatus } from "./modules/status-ui.js";
import { createVideoRangePicker } from "./modules/video-range-picker.js";

const API_BASE = window.drumSheetAPI.apiBase || "http://127.0.0.1:8000";
let activePoll = null;
let outputDir = "";
let latestRuntime = null;

const roiController = createRoiController({
  detectMode,
  onPreviewLoadError: () => {
    appendLog("오류: 미리보기 이미지를 불러오지 못했습니다.");
    setStatus("영역 지정 화면 표시 실패");
  },
});
const videoRangePicker = createVideoRangePicker({ sourceType });

function updateSourceRows() {
  const isFile = sourceType() === "file";
  el("fileRow").style.display = isFile ? "flex" : "none";
  el("youtubeRow").style.display = isFile ? "none" : "flex";
  videoRangePicker.onSourceTypeChange();
}

function updateManualTools() {
  const tools = el("manualRoiTools");
  if (tools) {
    tools.style.display = detectMode() === "manual" ? "flex" : "none";
  }
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
    hint.textContent = "현재 OpenCV GPU 가속(CUDA/OpenCL)을 찾지 못해 업스케일을 사용할 수 없습니다.";
    return;
  }

  factor.disabled = !toggle.checked;
  hint.textContent = toggle.checked
    ? "업스케일은 GPU로만 처리합니다. GPU 가속이 불가능하면 작업이 중단됩니다."
    : "업스케일을 끄면 원본 해상도로 바로 저장합니다.";
}

function applyUpscaleAvailability(runtime) {
  const toggle = el("enableUpscale");
  if (!toggle) {
    return;
  }
  const mode = String(runtime?.opencv_mode || "").toLowerCase();
  const canUseGpuUpscale = mode === "cuda" || mode === "opencl";
  if (!canUseGpuUpscale) {
    toggle.checked = false;
    toggle.disabled = true;
    updateUpscaleUi();
    return;
  }
  toggle.disabled = false;
  updateUpscaleUi();
}

function resetResultView() {
  roiController.clearPreview();
  clearResultMeta();
  outputDir = "";
  el("openOutputDir").disabled = true;
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

function renderResult(job) {
  const meta = renderResultMeta(job, friendlyStepName);
  outputDir = meta.outputDir || "";
  el("openOutputDir").disabled = !outputDir;

  if (job?.result?.runtime) {
    latestRuntime = job.result.runtime;
    renderRuntimeStatus(latestRuntime);
    applyUpscaleAvailability(latestRuntime);
  }

  renderResultPreview(meta.firstImagePath);

  const canEditRoi = detectMode() === "manual" && meta.hasResultImage;
  if (canEditRoi && meta.firstImagePath) {
    roiController.showPreviewWithRoi(meta.firstImagePath);
  }
  roiController.setRoiEditorVisibility(canEditRoi);
  roiController.setRoiEditMode(canEditRoi);
}

async function poll(jobId) {
  const job = await getJob(API_BASE, jobId);
  setProgress(job.progress);
  setStatus(friendlyStatusText(job.current_step, job.message));
  appendLog(`[${friendlyStepName(job.current_step)}] ${friendlyMessage(job.message)}`);

  if (job.status === "running" || job.status === "queued") {
    return;
  }

  clearInterval(activePoll);
  activePoll = null;

  if (job.status === "done") {
    setStatus("완료");
    renderResult(job);
  } else {
    setStatus(`오류 (${job.error_code || "알 수 없음"})`);
    if (job.result) {
      renderResult(job);
    }
  }
  el("runJob").disabled = false;
}

async function onRun() {
  try {
    if (activePoll) {
      clearInterval(activePoll);
      activePoll = null;
    }
    resetResultView();
    setProgress(0);
    setStatus("작업을 시작하고 있어요");
    appendLog("작업 시작");
    appendLog(`영상 형태: ${friendlyLayoutLabel(selectedLayoutHint())}`);
    el("runJob").disabled = true;

    const jobId = await createJob(API_BASE);
    setStatus("작업 대기 중");
    activePoll = setInterval(() => {
      poll(jobId).catch((error) => {
        appendLog(`오류: ${String(error.message)}`);
        clearInterval(activePoll);
        activePoll = null;
        setStatus("조회 실패");
        el("runJob").disabled = false;
      });
    }, 700);
  } catch (error) {
    appendLog(`오류: ${error.message}`);
    setStatus("요청 실패");
    el("runJob").disabled = false;
  }
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
  try {
    button.disabled = true;
    if (sourceType() === "file" && !el("filePath").value) {
      const pickedPath = await window.drumSheetAPI.selectVideoFile();
      if (pickedPath) {
        el("filePath").value = pickedPath;
        videoRangePicker.loadLocalFile(pickedPath);
      }
    }
    setStatus("영역 지정용 화면을 불러오는 중");
    appendLog("영역 지정 화면 요청");
    const previewStartSec = sourceType() === "file" ? videoRangePicker.getPreviewSecond() : null;
    if (previewStartSec != null) {
      appendLog(`영역 지정 시점: ${previewStartSec.toFixed(1)}초`);
    }
    const previewImagePath = await requestPreviewFrame(API_BASE, { startSecOverride: previewStartSec });
    el("detectManual").checked = true;
    updateManualTools();
    roiController.showPreviewWithRoi(previewImagePath);
    roiController.setRoiEditorVisibility(true);
    roiController.setRoiEditMode(true);
    el("roiEditorWrap")?.scrollIntoView({ behavior: "smooth", block: "center" });
    setStatus("화면 준비 완료. 악보 부분을 드래그해 주세요");
    appendLog("영역 지정 화면 준비 완료");
  } catch (error) {
    appendLog(`오류: ${error.message}`);
    setStatus("영역 지정 화면 불러오기 실패");
  } finally {
    button.disabled = false;
  }
}

document.querySelectorAll('input[name="sourceType"]').forEach((node) => {
  node.addEventListener("change", updateSourceRows);
});

document.querySelectorAll('input[name="detectMode"]').forEach((node) => {
  node.addEventListener("change", () => {
    updateManualTools();
    roiController.onDetectModeChange();
  });
});

el("roiInput").addEventListener("input", () => {
  roiController.onRoiInputChange();
});

el("browseFile").addEventListener("click", async () => {
  const path = await window.drumSheetAPI.selectVideoFile();
  if (path) {
    el("filePath").value = path;
    videoRangePicker.loadLocalFile(path);
  }
});

el("loadPreviewForRoi").addEventListener("click", onLoadPreviewForRoi);

const layoutHintNode = el("layoutHint");
if (layoutHintNode) {
  layoutHintNode.addEventListener("change", () => {
    updateLayoutHintUi({ applyDefaults: true });
    appendLog("영상 형태 변경: 추천 옵션을 적용했어요");
  });
}

const captureSensitivityNode = el("captureSensitivity");
if (captureSensitivityNode) {
  captureSensitivityNode.addEventListener("change", () => {
    updateCaptureSensitivityHelp();
    appendLog("캡처 민감도 변경");
  });
}

const enableUpscaleNode = el("enableUpscale");
if (enableUpscaleNode) {
  enableUpscaleNode.addEventListener("change", () => {
    updateUpscaleUi();
    appendLog(enableUpscaleNode.checked ? "GPU 업스케일 사용" : "GPU 업스케일 사용 안 함");
  });
}

el("openOutputDir").addEventListener("click", () => {
  if (!outputDir) {
    return;
  }
  window.drumSheetAPI.openPath(outputDir);
});

el("runJob").addEventListener("click", onRun);

updateSourceRows();
updateManualTools();
updateLayoutHintUi({ applyDefaults: false });
updateCaptureSensitivityHelp();
updateUpscaleUi();
refreshRuntimeStatus();
if (sourceType() === "file" && el("filePath").value) {
  videoRangePicker.loadLocalFile(el("filePath").value);
}
