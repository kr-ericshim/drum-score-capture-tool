import { el } from "./dom.js";

function formatMode(mode) {
  if (!mode) {
    return "확인 중";
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

function formatAudioGpu(runtime) {
  const mode = String(runtime?.audio_gpu_mode || "cpu").toLowerCase();
  if (mode === "cuda") {
    const name = runtime?.torch_cuda_device_name || runtime?.gpu_name || "CUDA GPU";
    return `GPU (CUDA) - ${name}`;
  }
  if (mode === "mps") {
    return "GPU (MPS)";
  }
  return "CPU (torch GPU 미사용)";
}

function formatEngineMini(runtime) {
  const ffmpegMode = String(runtime?.ffmpeg_mode || "").toLowerCase();
  const ffmpeg = ffmpegMode ? ffmpegMode.toUpperCase() : "확인 중";
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
    const audioGpuReady = Boolean(runtime.audio_gpu_ready);
    if (!audioGpuReady) {
      return `영상/이미지 처리는 GPU를 우선 사용합니다. 오디오 분리는 환경에 따라 CPU로 전환될 수 있어요. (영상: ${ffmpeg}, 이미지: ${opencv}, 선명도: ${upscale})`;
    }
    return `가능한 단계는 GPU로 처리하고, 안 되면 자동으로 CPU로 전환합니다. (영상: ${ffmpeg}, 이미지: ${opencv}, 선명도: ${upscale})`;
  }
  return `현재는 CPU 중심으로 처리합니다. GPU 환경이 준비되면 자동으로 가속을 사용합니다. (영상: ${ffmpeg}, 이미지: ${opencv}, 선명도: ${upscale})`;
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
  const audioGpu = el("runtimeAudioGpu");
  const upscale = el("runtimeUpscale");
  const gpu = el("runtimeGpu");
  const cpu = el("runtimeCpu");
  const torch = el("runtimeTorch");
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
  if (audioGpu) {
    audioGpu.textContent = formatAudioGpu(runtime);
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
  if (torch) {
    const version = runtime.torch_version || "미설치";
    const cudaVer = runtime.torch_cuda_version || "-";
    const reason = runtime.torch_gpu_reason || "unknown";
    const count = Number.isFinite(Number(runtime.torch_cuda_device_count)) ? Number(runtime.torch_cuda_device_count) : 0;
    torch.textContent = `${version} (CUDA=${cudaVer}, dev=${count}, reason=${reason})`;
  }
  if (order) {
    order.textContent = Array.isArray(runtime.ffmpeg_order) && runtime.ffmpeg_order.length > 0 ? runtime.ffmpeg_order.join(" -> ") : "cpu";
  }
}

export function renderRuntimeError() {
  const desc = el("runtimeMainDesc");
  if (desc) {
    desc.textContent = "엔진 정보를 아직 읽는 중입니다. 잠시 후 다시 확인됩니다.";
  }
  const gpuMini = el("runtimeGpuMini");
  const engineMini = el("runtimeEngineMini");
  if (gpuMini) {
    gpuMini.textContent = "연결 대기";
  }
  if (engineMini) {
    engineMini.textContent = "연결 대기";
  }
  const audioGpu = el("runtimeAudioGpu");
  const torch = el("runtimeTorch");
  if (audioGpu) {
    audioGpu.textContent = "연결 대기";
  }
  if (torch) {
    torch.textContent = "연결 대기";
  }
}
