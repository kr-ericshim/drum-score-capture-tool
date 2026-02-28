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

const PIPELINE_IDS = ["pipeDownload", "pipeExtract", "pipeDetect", "pipeRectify", "pipeUpscale", "pipeExport"];

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
    return 2;
  }
  if (step === "separating_audio") {
    return 2;
  }
  if (step === "rectifying" || step === "stitching" || step === "upscaling") {
    if (step === "rectifying") {
      return 3;
    }
    if (step === "stitching") {
      return 3;
    }
    return 4;
  }
  if (step === "exporting") {
    return 5;
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
      capturePaths: [],
      pdfPath: "",
    };
  }
  const files = job.result || {};
  const lines = [];

  lines.push(`현재 상태: ${friendlyStepName(job.status)}`);
  if (files.output_dir) {
    lines.push(`저장 폴더: ${files.output_dir}`);
  }
  if (files.pdf) {
    lines.push(`PDF 파일: ${files.pdf}`);
  }
  if (files.images?.length) {
    const pageCount = Number(files.images.length || 0);
    lines.push(`완성 페이지: ${pageCount}장`);
    if (pageCount <= 2) {
      lines.push("연주 편의: 페이지 넘김이 적은 편입니다.");
    } else if (pageCount <= 4) {
      lines.push("연주 편의: 페이지 넘김이 보통입니다.");
    } else {
      lines.push("연주 편의: 페이지가 많아요. 필요하면 스크롤 맞춤 모드를 시도해 보세요.");
    }
  }
  if (files.review_export?.kept_count) {
    lines.push(`검토 반영: 캡쳐 ${files.review_export.kept_count}개 유지`);
  }
  if (files.source_resolution?.width && files.source_resolution?.height) {
    lines.push(`원본 영상 크기: ${files.source_resolution.width}x${files.source_resolution.height}`);
  }
  if (files.upscaled_frames?.length) {
    lines.push(`선명도 보정: ${files.upscaled_frames.length}장`);
  }
  if (files.runtime?.overall_mode) {
    const modeLabel = files.runtime.overall_mode === "gpu" ? "GPU" : "CPU";
    lines.push(`처리 장치: ${modeLabel}`);
  }

  meta.textContent = lines.join("\n");
  return {
    outputDir: files.output_dir || "",
    firstImagePath: files.images?.[0] || "",
    hasResultImage: Boolean(files.images?.length),
    imagePaths: Array.isArray(files.images) ? files.images : [],
    capturePaths: Array.isArray(files.review_candidates) && files.review_candidates.length
      ? files.review_candidates
      : Array.isArray(files.upscaled_frames) && files.upscaled_frames.length
        ? files.upscaled_frames
        : Array.isArray(files.stitched_frames)
          ? files.stitched_frames
          : [],
    pdfPath: files.pdf || "",
  };
}
