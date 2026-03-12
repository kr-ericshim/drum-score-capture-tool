import { el } from "./dom.js";
import { getLocale } from "./i18n.js";

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
      pageDiagnostics: [],
      pdfPath: "",
    };
  }
  const files = job.result || {};
  const lines = [];

  lines.push(getLocale() === "ko" ? `현재 상태: ${friendlyStepName(job.status)}` : `Status: ${friendlyStepName(job.status)}`);
  if (files.output_dir) {
    lines.push(getLocale() === "ko" ? `저장 폴더: ${files.output_dir}` : `Output folder: ${files.output_dir}`);
  }
  if (files.pdf) {
    lines.push(getLocale() === "ko" ? `PDF 파일: ${files.pdf}` : `PDF file: ${files.pdf}`);
  }
  if (files.images?.length) {
    const pageCount = Number(files.images.length || 0);
    lines.push(getLocale() === "ko" ? `생성 페이지: ${pageCount}장` : `Pages generated: ${pageCount}`);
    if (pageCount <= 2) {
      lines.push(getLocale() === "ko" ? "페이지 구성: 페이지 수가 적습니다." : "Page layout: low page count.");
    } else if (pageCount <= 4) {
      lines.push(getLocale() === "ko" ? "페이지 구성: 페이지 수가 보통입니다." : "Page layout: moderate page count.");
    } else {
      lines.push(
        getLocale() === "ko"
          ? "페이지 구성: 페이지 수가 많습니다. 필요 시 스크롤 맞춤 모드를 사용합니다."
          : "Page layout: high page count. Use the scroll preset when needed.",
      );
    }
  }
  if (files.review_export?.kept_count) {
    lines.push(getLocale() === "ko" ? `검토 반영: 페이지 ${files.review_export.kept_count}장 유지` : `Review applied: kept ${files.review_export.kept_count} pages`);
  }
  if (files.source_resolution?.width && files.source_resolution?.height) {
    lines.push(getLocale() === "ko" ? `원본 영상 크기: ${files.source_resolution.width}x${files.source_resolution.height}` : `Source resolution: ${files.source_resolution.width}x${files.source_resolution.height}`);
  }
  if (files.upscaled_frames?.length) {
    lines.push(getLocale() === "ko" ? `선명도 보정: ${files.upscaled_frames.length}개` : `Clarity enhanced: ${files.upscaled_frames.length}`);
  }
  if (files.runtime?.overall_mode) {
    const modeLabel = files.runtime.overall_mode === "gpu" ? "GPU" : "CPU";
    lines.push(getLocale() === "ko" ? `처리 장치: ${modeLabel}` : `Processing device: ${modeLabel}`);
  }

  meta.textContent = lines.join("\n");
  return {
    outputDir: files.output_dir || "",
    firstImagePath: files.images?.[0] || "",
    hasResultImage: Boolean(files.images?.length),
    imagePaths: Array.isArray(files.images) ? files.images : [],
    capturePaths: Array.isArray(files.images) ? files.images : [],
    pageDiagnostics: Array.isArray(files.page_diagnostics) ? files.page_diagnostics : [],
    pdfPath: files.pdf || "",
  };
}
