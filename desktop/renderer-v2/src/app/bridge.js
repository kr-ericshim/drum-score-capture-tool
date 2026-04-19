import { fileUrl } from "../lib/paths.js";

export const bridge = {
  selectVideoFile() {
    return window?.drumSheetAPI?.selectVideoFile?.() || Promise.resolve("");
  },
  getPathForFile(file) {
    return window?.drumSheetAPI?.getPathForFile?.(file) || "";
  },
  openPath(targetPath) {
    return window?.drumSheetAPI?.openPath?.(targetPath);
  },
  copyText(text) {
    return window?.drumSheetAPI?.copyText?.(text) || Promise.resolve(false);
  },
  getBackendState() {
    return window?.drumSheetAPI?.getBackendState?.() || Promise.resolve({
      ready: false,
      starting: false,
      running: false,
      error: "",
    });
  },
  onBackendState(handler) {
    if (typeof window?.drumSheetAPI?.onBackendState === "function") {
      return window.drumSheetAPI.onBackendState(handler);
    }
    return () => {};
  },
};

export async function readVideoMetadata(filePath) {
  const target = String(filePath || "").trim();
  if (!target) {
    return null;
  }
  const video = document.createElement("video");
  video.preload = "metadata";
  video.src = fileUrl(target);
  video.muted = true;

  return new Promise((resolve, reject) => {
    const cleanup = () => {
      video.pause();
      video.removeAttribute("src");
      video.load();
    };

    video.onloadedmetadata = () => {
      const durationSec = Number(video.duration || 0);
      const width = Number(video.videoWidth || 0);
      const height = Number(video.videoHeight || 0);
      cleanup();
      resolve({
        durationSec,
        durationLabel: formatDuration(durationSec),
        resolutionLabel: width && height ? `${width}x${height}` : "",
        width,
        height,
      });
    };
    video.onerror = () => {
      cleanup();
      reject(new Error("영상 메타데이터를 읽지 못했습니다."));
    };
  });
}

function formatDuration(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(safe / 60);
  const remain = Math.floor(safe % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}
