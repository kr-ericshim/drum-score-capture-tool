import { el } from "./dom.js";

export function setStatus(text) {
  el("status").textContent = text;
}

export function setProgress(ratio) {
  const pct = Math.max(0, Math.min(100, Math.round(ratio * 100)));
  el("progressBar").style.width = `${pct}%`;
}

export function appendLog(text) {
  const logs = el("logs");
  logs.textContent = `${logs.textContent}\n${text}`.trim();
  logs.scrollTop = logs.scrollHeight;
}

export function clearResultMeta() {
  el("resultMeta").textContent = "";
}

export function renderResultMeta(job, friendlyStepName) {
  const meta = el("resultMeta");
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
  if (files.runtime?.overall_mode) {
    const modeLabel = files.runtime.overall_mode === "gpu" ? "GPU" : "CPU";
    lines.push(`가속 모드: ${modeLabel} (FFmpeg: ${files.runtime.ffmpeg_mode}, OpenCV: ${files.runtime.opencv_mode})`);
  }

  meta.textContent = lines.join("\n");
  return {
    outputDir: files.output_dir || "",
    firstImagePath: files.images?.[0] || "",
    hasResultImage: Boolean(files.images?.length),
  };
}
