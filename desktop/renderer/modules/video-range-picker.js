import { clamp, el, fileUrl } from "./dom.js";

function formatTime(sec) {
  const safe = Number.isFinite(sec) ? Math.max(0, sec) : 0;
  const min = Math.floor(safe / 60);
  const rem = safe - min * 60;
  return `${String(min).padStart(2, "0")}:${rem.toFixed(1).padStart(4, "0")}`;
}

function roundToTenth(value) {
  return Math.round(value * 10) / 10;
}

export function createVideoRangePicker({ sourceType }) {
  const container = el("localRangeHelper");
  const video = el("rangeVideo");
  const seekSlider = el("videoSeek");
  const startSlider = el("startSlider");
  const endSlider = el("endSlider");
  const currentLabel = el("videoCurrent");
  const durationLabel = el("videoDuration");
  const hintLabel = el("videoHelperHint");
  const startInput = el("startSec");
  const endInput = el("endSec");
  const setStartButton = el("setStartAtCurrent");
  const setEndButton = el("setEndAtCurrent");
  const clearRangeButton = el("clearRange");

  if (!container || !video || !seekSlider || !startSlider || !endSlider || !startInput || !endInput) {
    return {
      onSourceTypeChange: () => {},
      loadLocalFile: () => {},
    };
  }

  let hasMedia = false;
  let durationSec = 0;
  let startTouched = false;
  let endTouched = false;
  let syncing = false;

  function setHint(text) {
    if (hintLabel) {
      hintLabel.textContent = text;
    }
  }

  function setControlsDisabled(disabled) {
    video.controls = !disabled;
    seekSlider.disabled = disabled;
    startSlider.disabled = disabled;
    endSlider.disabled = disabled;
    if (setStartButton) {
      setStartButton.disabled = disabled;
    }
    if (setEndButton) {
      setEndButton.disabled = disabled;
    }
    if (clearRangeButton) {
      clearRangeButton.disabled = disabled;
    }
  }

  function updateTimeLabels(current) {
    currentLabel.textContent = formatTime(current);
    durationLabel.textContent = formatTime(durationSec);
  }

  function setSliderBounds() {
    const max = Math.max(0.1, durationSec);
    seekSlider.max = String(max);
    startSlider.max = String(max);
    endSlider.max = String(max);
  }

  function syncSeekFromVideo() {
    if (!hasMedia || syncing) {
      return;
    }
    seekSlider.value = String(clamp(video.currentTime || 0, 0, durationSec || 0));
    updateTimeLabels(video.currentTime || 0);
  }

  function applyStartValue(sec) {
    const safe = roundToTenth(clamp(sec, 0, durationSec || 0));
    startInput.value = String(safe);
    startSlider.value = String(safe);
    startTouched = true;
  }

  function applyEndValue(sec) {
    const safe = roundToTenth(clamp(sec, 0, durationSec || 0));
    endInput.value = String(safe);
    endSlider.value = String(safe);
    endTouched = true;
  }

  function ensureRangeOrder() {
    let start = parseFloat(startSlider.value || "0");
    let end = parseFloat(endSlider.value || "0");
    if (!Number.isFinite(start)) {
      start = 0;
    }
    if (!Number.isFinite(end)) {
      end = durationSec || 0;
    }
    if (start > end) {
      end = start;
      endSlider.value = String(end);
      if (endTouched) {
        endInput.value = String(roundToTenth(end));
      }
    }
  }

  function resetMediaState() {
    hasMedia = false;
    durationSec = 0;
    startTouched = false;
    endTouched = false;
    seekSlider.value = "0";
    seekSlider.max = "0";
    startSlider.value = "0";
    startSlider.max = "0";
    endSlider.value = "0";
    endSlider.max = "0";
    updateTimeLabels(0);
    setControlsDisabled(true);
  }

  function onSourceTypeChange() {
    const isFile = sourceType() === "file";
    container.style.display = isFile ? "block" : "none";
    if (!isFile) {
      video.pause();
      return;
    }
    if (!hasMedia) {
      setHint("로컬 파일을 선택하면 아래 플레이어에서 시작/끝 시간을 슬라이더로 쉽게 고를 수 있어요.");
    }
  }

  function loadLocalFile(filePath) {
    if (!filePath) {
      return;
    }
    onSourceTypeChange();
    resetMediaState();
    setHint("영상 메타데이터를 읽는 중...");
    video.src = fileUrl(filePath);
    video.load();
  }

  video.addEventListener("loadedmetadata", () => {
    if (!Number.isFinite(video.duration) || video.duration <= 0) {
      resetMediaState();
      setHint("영상 길이를 읽지 못했어요. 다른 파일로 시도해 주세요.");
      return;
    }
    hasMedia = true;
    durationSec = roundToTenth(video.duration);
    setSliderBounds();
    seekSlider.value = "0";
    startSlider.value = "0";
    endSlider.value = String(durationSec);
    updateTimeLabels(0);
    setControlsDisabled(false);
    setHint("플레이어를 재생하거나 슬라이더를 움직여 원하는 구간을 빠르게 설정하세요.");
  });

  video.addEventListener("timeupdate", () => {
    syncSeekFromVideo();
  });

  video.addEventListener("error", () => {
    resetMediaState();
    setHint("이 영상은 미리보기 재생이 어렵습니다. 시작/끝 시간을 직접 입력해 주세요.");
  });

  seekSlider.addEventListener("input", () => {
    if (!hasMedia) {
      return;
    }
    const sec = parseFloat(seekSlider.value || "0");
    if (!Number.isFinite(sec)) {
      return;
    }
    syncing = true;
    video.currentTime = clamp(sec, 0, durationSec);
    updateTimeLabels(sec);
    syncing = false;
  });

  startSlider.addEventListener("input", () => {
    if (!hasMedia) {
      return;
    }
    applyStartValue(parseFloat(startSlider.value || "0"));
    ensureRangeOrder();
  });

  endSlider.addEventListener("input", () => {
    if (!hasMedia) {
      return;
    }
    applyEndValue(parseFloat(endSlider.value || "0"));
    ensureRangeOrder();
  });

  startInput.addEventListener("input", () => {
    if (!hasMedia) {
      return;
    }
    const value = parseFloat(startInput.value || "0");
    if (!Number.isFinite(value)) {
      return;
    }
    applyStartValue(value);
    ensureRangeOrder();
  });

  endInput.addEventListener("input", () => {
    if (!hasMedia) {
      return;
    }
    const value = parseFloat(endInput.value || "0");
    if (!Number.isFinite(value)) {
      return;
    }
    applyEndValue(value);
    ensureRangeOrder();
  });

  if (setStartButton) {
    setStartButton.addEventListener("click", () => {
      if (!hasMedia) {
        return;
      }
      applyStartValue(video.currentTime || 0);
      ensureRangeOrder();
    });
  }

  if (setEndButton) {
    setEndButton.addEventListener("click", () => {
      if (!hasMedia) {
        return;
      }
      applyEndValue(video.currentTime || 0);
      ensureRangeOrder();
    });
  }

  if (clearRangeButton) {
    clearRangeButton.addEventListener("click", () => {
      startTouched = false;
      endTouched = false;
      startInput.value = "";
      endInput.value = "";
      if (hasMedia) {
        startSlider.value = "0";
        endSlider.value = String(durationSec);
      } else {
        startSlider.value = "0";
        endSlider.value = "0";
      }
    });
  }

  onSourceTypeChange();
  resetMediaState();
  return {
    onSourceTypeChange,
    loadLocalFile,
    getPreviewSecond: () => {
      if (!hasMedia) {
        return null;
      }
      return roundToTenth(clamp(video.currentTime || 0, 0, durationSec || 0));
    },
  };
}
