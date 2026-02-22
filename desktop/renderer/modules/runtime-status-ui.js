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

function formatUpscaleEngine(runtime) {
  if (!runtime || runtime.upscale_available !== true) {
    return "사용 불가";
  }
  const hint = String(runtime.upscale_engine_hint || "").toLowerCase();
  if (hint === "hat") {
    return "HAT (Transformer SR)";
  }
  if (hint === "ffmpeg_scale_vt") {
    return "FFmpeg scale_vt (Metal)";
  }
  if (hint === "opencv_cuda") {
    return "OpenCV CUDA";
  }
  if (hint === "opencv_opencl") {
    return "OpenCV OpenCL";
  }
  return "업스케일 가능";
}

function formatEngineMini(runtime) {
  const ffmpeg = String(runtime?.ffmpeg_mode || "unknown").toUpperCase();
  const opencv = formatMode(runtime?.opencv_mode || "cpu");
  return `${ffmpeg} / ${opencv}`;
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
  const upscale = formatUpscaleEngine(runtime);
  if (overall === "gpu") {
    return `가속 가능한 단계는 GPU로 처리하고, 실패하면 자동으로 CPU로 전환합니다. (FFmpeg: ${ffmpeg}, OpenCV: ${opencv}, 업스케일: ${upscale})`;
  }
  return `현재 환경에서는 CPU로 처리 중입니다. GPU 가속 가능 환경이면 자동 전환됩니다. (FFmpeg: ${ffmpeg}, OpenCV: ${opencv}, 업스케일: ${upscale})`;
}

export function renderRuntimeStatus(runtime) {
  if (!runtime) {
    return;
  }
  const overallChip = el("runtimeOverallChip");
  const gpuMini = el("runtimeGpuMini");
  const engineMini = el("runtimeEngineMini");
  const title = el("runtimeMainTitle");
  const desc = el("runtimeMainDesc");
  const ffmpeg = el("runtimeFfmpeg");
  const opencv = el("runtimeOpencv");
  const upscale = el("runtimeUpscale");
  const gpu = el("runtimeGpu");
  const cpu = el("runtimeCpu");
  const order = el("runtimeOrder");

  const usesGpu = String(runtime.overall_mode || "").toLowerCase() === "gpu";
  if (overallChip) {
    overallChip.textContent = usesGpu ? "GPU 사용 중" : "CPU 사용 중";
    overallChip.classList.toggle("runtime-chip-gpu", usesGpu);
    overallChip.classList.toggle("runtime-chip-cpu", !usesGpu);
  }
  if (gpuMini) {
    gpuMini.textContent = runtime.gpu_name || runtime.cpu_name || "확인 불가";
  }
  if (engineMini) {
    engineMini.textContent = formatEngineMini(runtime);
  }
  if (title) {
    title.textContent = mainTitle(runtime);
  }
  if (desc) {
    desc.textContent = summaryText(runtime);
  }
  if (ffmpeg) {
    ffmpeg.textContent = formatMode(runtime.ffmpeg_mode);
  }
  if (opencv) {
    opencv.textContent = formatMode(runtime.opencv_mode);
  }
  if (upscale) {
    upscale.textContent = formatUpscaleEngine(runtime);
  }
  if (gpu) {
    gpu.textContent = runtime.gpu_name || "감지되지 않음";
  }
  if (cpu) {
    cpu.textContent = runtime.cpu_name || "알 수 없음";
  }
  if (order) {
    order.textContent = Array.isArray(runtime.ffmpeg_order) && runtime.ffmpeg_order.length > 0 ? runtime.ffmpeg_order.join(" -> ") : "cpu";
  }
}

export function renderRuntimeError() {
  const desc = el("runtimeMainDesc");
  if (desc) {
    desc.textContent = "런타임 정보를 읽지 못했습니다.";
  }
  const gpuMini = el("runtimeGpuMini");
  const engineMini = el("runtimeEngineMini");
  if (gpuMini) {
    gpuMini.textContent = "확인 실패";
  }
  if (engineMini) {
    engineMini.textContent = "확인 실패";
  }
}
