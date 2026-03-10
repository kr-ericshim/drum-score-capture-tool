import { el } from "./dom.js";
import { getLocale } from "./i18n.js";

function formatMode(mode) {
  if (!mode) {
    return getLocale() === "ko" ? "확인 중" : "Checking";
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
    return getLocale() === "ko" ? "사용 불가" : "Unavailable";
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
  return getLocale() === "ko" ? "업스케일 가능" : "Available";
}

function formatVersionValue(version) {
  const value = String(version || "").trim();
  return value || (getLocale() === "ko" ? "확인 중" : "Checking");
}

function formatVersionMismatch(version, otherVersion) {
  const current = String(version || "").trim();
  const other = String(otherVersion || "").trim();
  if (!current) {
    return formatVersionValue(current);
  }
  if (other && current !== other) {
    return getLocale() === "ko"
      ? `${current} (불일치: ${other})`
      : `${current} (mismatch: ${other})`;
  }
  return current;
}

function formatEngineMini(runtime) {
  const ffmpegMode = String(runtime?.ffmpeg_mode || "").toLowerCase();
  const ffmpeg = ffmpegMode ? ffmpegMode.toUpperCase() : (getLocale() === "ko" ? "확인 중" : "Checking");
  const opencv = formatMode(runtime?.opencv_mode || "cpu");
  return `${ffmpeg} / ${opencv}`;
}

function mainTitle(runtime) {
  const overall = String(runtime.overall_mode || "").toLowerCase();
  if (overall === "gpu") {
    return getLocale() === "ko" ? `GPU 사용 중 - ${runtime.gpu_name || "장치 정보 없음"}` : `Using GPU - ${runtime.gpu_name || "No device info"}`;
  }
  return getLocale() === "ko" ? `CPU 사용 중 - ${runtime.cpu_name || "장치 정보 없음"}` : `Using CPU - ${runtime.cpu_name || "No device info"}`;
}

function summaryText(runtime) {
  const overall = String(runtime.overall_mode || "").toLowerCase();
  const ffmpeg = formatMode(runtime.ffmpeg_mode);
  const opencv = formatMode(runtime.opencv_mode);
  const upscale = formatUpscaleEngine(runtime);
  if (overall === "gpu") {
    return getLocale() === "ko"
      ? `가능한 단계는 GPU를 우선 사용합니다. 필요 시 CPU로 자동 전환합니다. (영상: ${ffmpeg}, 이미지: ${opencv}, 선명도: ${upscale})`
      : `GPU is used whenever possible and falls back to CPU when needed. (Video: ${ffmpeg}, Image: ${opencv}, Clarity: ${upscale})`;
  }
  return getLocale() === "ko"
    ? `현재는 CPU 중심으로 처리합니다. GPU 환경이 준비되면 자동으로 가속을 사용합니다. (영상: ${ffmpeg}, 이미지: ${opencv}, 선명도: ${upscale})`
    : `Currently running in CPU-first mode. GPU acceleration will be used automatically when available. (Video: ${ffmpeg}, Image: ${opencv}, Clarity: ${upscale})`;
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
  const desktopVersion = el("runtimeDesktopVersion");
  const backendVersion = el("runtimeBackendVersion");
  const cacheNamespace = el("runtimeCacheNamespace");
  const ffmpeg = el("runtimeFfmpeg");
  const opencv = el("runtimeOpencv");
  const upscale = el("runtimeUpscale");
  const gpu = el("runtimeGpu");
  const cpu = el("runtimeCpu");
  const order = el("runtimeOrder");
  const desktopAppVersion = String(window.drumSheetAPI?.desktopVersion || "").trim();
  const backendAppVersion = String(runtime.app_version || "").trim();

  const usesGpu = String(runtime.overall_mode || "").toLowerCase() === "gpu";
  if (overallChip) {
    overallChip.textContent = usesGpu ? (getLocale() === "ko" ? "GPU 사용 중" : "Using GPU") : (getLocale() === "ko" ? "CPU 사용 중" : "Using CPU");
    overallChip.classList.toggle("runtime-chip-gpu", usesGpu);
    overallChip.classList.toggle("runtime-chip-cpu", !usesGpu);
  }
  if (gpuMini) {
    gpuMini.textContent = runtime.gpu_name || runtime.cpu_name || (getLocale() === "ko" ? "확인 불가" : "Unavailable");
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
  if (desktopVersion) {
    desktopVersion.textContent = formatVersionMismatch(desktopAppVersion, backendAppVersion);
  }
  if (backendVersion) {
    backendVersion.textContent = formatVersionMismatch(backendAppVersion, desktopAppVersion);
  }
  if (cacheNamespace) {
    cacheNamespace.textContent = formatVersionValue(runtime.preview_cache_namespace);
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
    gpu.textContent = runtime.gpu_name || (getLocale() === "ko" ? "사용 안 함" : "Not used");
  }
  if (cpu) {
    cpu.textContent = runtime.cpu_name || (getLocale() === "ko" ? "정보 없음" : "No info");
  }
  if (order) {
    order.textContent = Array.isArray(runtime.ffmpeg_order) && runtime.ffmpeg_order.length > 0 ? runtime.ffmpeg_order.join(" -> ") : "cpu";
  }
}

export function renderRuntimeError() {
  const desc = el("runtimeMainDesc");
  if (desc) {
    desc.textContent = getLocale() === "ko" ? "엔진 정보를 불러오는 중입니다. 잠시 후 다시 확인합니다." : "Loading engine information. Check again shortly.";
  }
  const desktopVersion = el("runtimeDesktopVersion");
  const backendVersion = el("runtimeBackendVersion");
  const cacheNamespace = el("runtimeCacheNamespace");
  const gpuMini = el("runtimeGpuMini");
  const engineMini = el("runtimeEngineMini");
  if (desktopVersion) {
    desktopVersion.textContent = formatVersionValue(window.drumSheetAPI?.desktopVersion || "");
  }
  if (backendVersion) {
    backendVersion.textContent = getLocale() === "ko" ? "연결 대기" : "Waiting";
  }
  if (cacheNamespace) {
    cacheNamespace.textContent = getLocale() === "ko" ? "연결 대기" : "Waiting";
  }
  if (gpuMini) {
    gpuMini.textContent = getLocale() === "ko" ? "연결 대기" : "Waiting";
  }
  if (engineMini) {
    engineMini.textContent = getLocale() === "ko" ? "연결 대기" : "Waiting";
  }
}
