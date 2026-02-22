import { el } from "./dom.js";

export function setStatus(text) {
  const node = el("status");
  if (node) {
    node.textContent = text;
  }
}

export function setProgress(ratio) {
  const pct = Math.max(0, Math.min(100, Math.round(ratio * 100)));
  const bar = el("progressBar");
  if (bar) {
    bar.style.width = `${pct}%`;
  }
}

export function appendLog(text) {
  const logs = el("logs");
  if (!logs) {
    return;
  }
  logs.textContent = `${logs.textContent}\n${text}`.trim();
  logs.scrollTop = logs.scrollHeight;
}

export function clearResultMeta() {
  const node = el("resultMeta");
  if (node) {
    node.textContent = "";
  }
}

const PIPELINE_IDS = ["pipeDownload", "pipeExtract", "pipeAudio", "pipeDetect", "pipeRectify", "pipeUpscale", "pipeExport"];

function resolvePipelineIndex(currentStep, progress, isYoutubeSource) {
  const step = String(currentStep || "").toLowerCase();
  const pct = Number.isFinite(progress) ? progress : 0;
  if (step === "done") {
    return PIPELINE_IDS.length - 1;
  }
  if (step === "initializing" || step === "queued") {
    return isYoutubeSource ? 0 : 1;
  }
  if (step === "detecting") {
    if (pct < 0.36) {
      return 1;
    }
    return 3;
  }
  if (step === "separating_audio") {
    return 2;
  }
  if (step === "rectifying" || step === "stitching" || step === "upscaling") {
    if (step === "rectifying") {
      return 3;
    }
    if (step === "stitching") {
      return 4;
    }
    return 5;
  }
  if (step === "exporting") {
    return 6;
  }
  return 0;
}

export function setPipelineState({ currentStep, progress = 0, status = "queued", isYoutubeSource = false }) {
  const activeIndex = resolvePipelineIndex(currentStep, progress, isYoutubeSource);
  const isDone = String(status || "").toLowerCase() === "done";
  const isError = String(status || "").toLowerCase() === "error";

  PIPELINE_IDS.forEach((id, idx) => {
    const node = el(id);
    if (!node) {
      return;
    }
    node.classList.remove("pipe-step-active", "pipe-step-done", "pipe-step-error");
    if (isDone || idx < activeIndex) {
      node.classList.add("pipe-step-done");
      return;
    }
    if (idx === activeIndex) {
      node.classList.add(isError ? "pipe-step-error" : "pipe-step-active");
    }
  });
}

export function renderResultMeta(job, friendlyStepName) {
  const meta = el("resultMeta");
  if (!meta) {
    return {
      outputDir: "",
      firstImagePath: "",
      hasResultImage: false,
      imagePaths: [],
      pdfPath: "",
    };
  }
  const files = job.result || {};
  const lines = [];

  lines.push(`작업 상태: ${friendlyStepName(job.status)}`);
  if (files.output_dir) {
    lines.push(`출력 폴더: ${files.output_dir}`);
  }
  if (files.pdf) {
    lines.push(`PDF 파일: ${files.pdf}`);
  }
  if (files.images?.length) {
    lines.push(`저장된 이미지: ${files.images.length}장`);
  }
  if (files.upscaled_frames?.length) {
    lines.push(`업스케일 처리: ${files.upscaled_frames.length}장`);
  }
  if (files.audio_stem) {
    lines.push(`드럼 분리 음원: ${files.audio_stem}`);
  }
  if (files.audio_model) {
    lines.push(`드럼 분리 모델: ${files.audio_model} (${files.audio_device || "unknown"})`);
  }
  if (files.runtime?.overall_mode) {
    const modeLabel = files.runtime.overall_mode === "gpu" ? "GPU" : "CPU";
    lines.push(`가속 모드: ${modeLabel} (FFmpeg: ${files.runtime.ffmpeg_mode}, OpenCV: ${files.runtime.opencv_mode})`);
    if (files.runtime.upscale_engine_hint) {
      const hint = String(files.runtime.upscale_engine_hint || "").toLowerCase();
      const hintLabel =
        hint === "hat"
          ? "HAT (Transformer SR)"
          : hint === "ffmpeg_scale_vt"
            ? "FFmpeg scale_vt (Metal)"
            : hint === "opencv_cuda"
              ? "OpenCV CUDA"
              : hint === "opencv_opencl"
                ? "OpenCV OpenCL"
                : files.runtime.upscale_engine_hint;
      lines.push(`업스케일 엔진: ${hintLabel}`);
    }
  }

  meta.textContent = lines.join("\n");
  return {
    outputDir: files.output_dir || "",
    firstImagePath: files.images?.[0] || "",
    hasResultImage: Boolean(files.images?.length),
    imagePaths: Array.isArray(files.images) ? files.images : [],
    pdfPath: files.pdf || "",
  };
}
