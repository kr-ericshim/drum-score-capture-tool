import { el } from "./dom.js";

function formatMode(mode) {
  if (!mode) {
    return "알 수 없음";
  }
  const value = String(mode).toLowerCase();
  if (value === "cpu") {
    return "CPU";
  }
  if (value === "cuda") {
    return "GPU (CUDA)";
  }
  if (value === "opencl") {
    return "GPU (OpenCL)";
  }
  return `GPU (${mode})`;
}

function mainTitle(runtime) {
  const overall = String(runtime.overall_mode || "").toLowerCase();
  if (overall === "gpu") {
    return `GPU 사용 중 - ${runtime.gpu_name || "장치명 확인 불가"}`;
  }
  return `CPU 사용 중 - ${runtime.cpu_name || "장치명 확인 불가"}`;
}

function summaryText(runtime) {
  const overall = String(runtime.overall_mode || "").toLowerCase();
  const ffmpeg = formatMode(runtime.ffmpeg_mode);
  const opencv = formatMode(runtime.opencv_mode);
  if (overall === "gpu") {
    return `가속 가능한 단계는 GPU로 처리하고, 실패하면 자동으로 CPU로 전환합니다. (FFmpeg: ${ffmpeg}, OpenCV: ${opencv})`;
  }
  return `현재 환경에서는 CPU로 처리 중입니다. GPU 가속 가능 환경이면 자동 전환됩니다. (FFmpeg: ${ffmpeg}, OpenCV: ${opencv})`;
}

export function renderRuntimeStatus(runtime) {
  if (!runtime) {
    return;
  }
  const overallChip = el("runtimeOverallChip");
  const title = el("runtimeMainTitle");
  const desc = el("runtimeMainDesc");
  const ffmpeg = el("runtimeFfmpeg");
  const opencv = el("runtimeOpencv");
  const gpu = el("runtimeGpu");
  const cpu = el("runtimeCpu");
  const order = el("runtimeOrder");
  if (!overallChip || !title || !desc || !ffmpeg || !opencv || !gpu || !cpu || !order) {
    return;
  }

  const usesGpu = String(runtime.overall_mode || "").toLowerCase() === "gpu";
  overallChip.textContent = usesGpu ? "GPU 사용 중" : "CPU 사용 중";
  overallChip.classList.toggle("runtime-chip-gpu", usesGpu);
  overallChip.classList.toggle("runtime-chip-cpu", !usesGpu);
  title.textContent = mainTitle(runtime);
  desc.textContent = summaryText(runtime);

  ffmpeg.textContent = formatMode(runtime.ffmpeg_mode);
  opencv.textContent = formatMode(runtime.opencv_mode);
  gpu.textContent = runtime.gpu_name || "감지되지 않음";
  cpu.textContent = runtime.cpu_name || "알 수 없음";
  order.textContent = Array.isArray(runtime.ffmpeg_order) && runtime.ffmpeg_order.length > 0 ? runtime.ffmpeg_order.join(" -> ") : "cpu";
}

export function renderRuntimeError() {
  const desc = el("runtimeMainDesc");
  if (desc) {
    desc.textContent = "런타임 정보를 읽지 못했습니다.";
  }
}
