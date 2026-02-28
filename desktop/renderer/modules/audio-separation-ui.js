import { el, fileUrl } from "./dom.js";
import { friendlyApiError } from "./messages.js";

function selectedAudioSourceType() {
  const checked = document.querySelector('input[name="audioSourceType"]:checked');
  return checked ? checked.value : "file";
}

function dirname(path) {
  const value = String(path || "").trim();
  if (!value) {
    return "";
  }
  const normalized = value.replace(/\\/g, "/");
  const idx = normalized.lastIndexOf("/");
  if (idx <= 0) {
    return "";
  }
  return normalized.slice(0, idx);
}

function normalizeApiDetail(detail) {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object" && typeof item.msg === "string") {
          return item.msg;
        }
        return String(item);
      })
      .join(" / ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.detail === "string") {
      return detail.detail;
    }
    if (typeof detail.message === "string") {
      return detail.message;
    }
  }
  return String(detail || "");
}

const VIDEO_EXTENSIONS = new Set([".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"]);
const PRACTICE_BPM_MIN = 40;
const PRACTICE_BPM_MAX = 260;
const PRACTICE_RATE_MIN = 0.5;
const PRACTICE_RATE_MAX = 1.25;

const AUDIO_PHASE_IDS = ["audioPhasePrepare", "audioPhaseExtract", "audioPhaseSeparate"];
const AUDIO_PHASE_STAGES = {
  prepare: { active: "audioPhasePrepare", done: [] },
  extract: { active: "audioPhaseExtract", done: ["audioPhasePrepare"] },
  separate: { active: "audioPhaseSeparate", done: ["audioPhasePrepare", "audioPhaseExtract"] },
  done: { active: "audioPhaseSeparate", done: ["audioPhasePrepare", "audioPhaseExtract", "audioPhaseSeparate"] },
};

function fileExtension(rawPath) {
  const normalized = String(rawPath || "").trim().replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  const idx = normalized.lastIndexOf(".");
  if (idx < 0) {
    return "";
  }
  return normalized.slice(idx).toLowerCase();
}

function isVideoLikePath(rawPath) {
  return VIDEO_EXTENSIONS.has(fileExtension(rawPath));
}

function stemLabel(name) {
  const value = String(name || "").toLowerCase();
  const labels = {
    drums: "드럼",
    bass: "베이스",
    vocals: "보컬",
    other: "기타 파트",
    guitar: "기타",
    piano: "피아노",
  };
  return labels[value] || String(name || "파트");
}

function stemCode(name) {
  const value = String(name || "").toLowerCase();
  const codes = {
    drums: "DR",
    bass: "BS",
    vocals: "VC",
    other: "OT",
    guitar: "GT",
    piano: "PN",
  };
  return codes[value] || String(name || "ST").slice(0, 2).toUpperCase();
}

function stemClassName(name) {
  const value = String(name || "stem").toLowerCase();
  const safe = value.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return safe || "stem";
}

function formatTime(totalSec) {
  const sec = Number.isFinite(totalSec) ? Math.max(0, Math.floor(totalSec)) : 0;
  const minute = Math.floor(sec / 60);
  const second = sec % 60;
  return `${String(minute).padStart(2, "0")}:${String(second).padStart(2, "0")}`;
}

export function createAudioSeparationUi({ apiBase }) {
  let outputDir = "";
  let latestStemEntries = [];
  let latestSourcePayload = null;
  let latestSeparationResult = null;
  let runBusy = false;
  let phaseStage = "prepare";

  const playback = {
    tracks: [],
    duration: 0,
    timerId: null,
    isPlaying: false,
    completed: false,
  };

  const videoPlayback = {
    ready: false,
    activeSrc: "",
    isProgrammaticSeek: false,
  };

  const practiceSpeed = {
    sourceBpm: 120,
    targetBpm: 120,
    userAdjusted: false,
  };

  function isSourceReady() {
    const type = selectedAudioSourceType();
    if (type === "file") {
      return Boolean(String(el("audioFilePath")?.value || "").trim());
    }
    return Boolean(String(el("audioYoutubeUrl")?.value || "").trim());
  }

  function refreshRunButtonState() {
    const runButton = el("audioRunSeparation");
    if (!runButton) {
      return;
    }
    if (runBusy) {
      runButton.disabled = true;
      runButton.classList.add("is-running");
      runButton.textContent = "분리 처리 중...";
      return;
    }
    const ready = isSourceReady();
    runButton.classList.remove("is-running");
    runButton.textContent = ready ? "드럼 음원 분리 시작" : "입력 소스 먼저 선택";
    runButton.disabled = !ready;
  }

  function statusToneAndGuide(text) {
    const value = String(text || "").toLowerCase();
    if (value.includes("오류")) {
      return {
        tone: "error",
        guide: "문제가 발생했습니다. 상세 로그를 열어 원인과 해결 방법을 확인해 주세요.",
      };
    }
    if (value.includes("완료")) {
      return {
        tone: "done",
        guide: "분리가 끝났습니다. 아래 재생/믹서에서 바로 확인할 수 있어요.",
      };
    }
    if (/처리 중|요청|준비|전송/.test(value)) {
      return {
        tone: "running",
        guide: "작업 중입니다. 긴 곡/정밀 모델은 시간이 더 걸릴 수 있습니다.",
      };
    }
    return {
      tone: "idle",
      guide: "입력 소스를 선택한 뒤 실행 버튼을 누르면 분리가 시작됩니다.",
    };
  }

  function setStatus(text) {
    const resolved = String(text || "대기 중");
    const status = statusToneAndGuide(resolved);
    const node = el("audioStatus");
    if (node) {
      node.textContent = resolved;
      node.classList.remove("audio-status-idle", "audio-status-running", "audio-status-done", "audio-status-error");
      node.classList.add(`audio-status-${status.tone}`);
    }
    const guide = el("audioStatusGuide");
    if (guide) {
      guide.textContent = status.guide;
    }
  }

  function setPhaseStage(stage) {
    const normalized = Object.prototype.hasOwnProperty.call(AUDIO_PHASE_STAGES, stage) ? stage : "prepare";
    const config = AUDIO_PHASE_STAGES[normalized];
    phaseStage = normalized;
    AUDIO_PHASE_IDS.forEach((id) => {
      const node = el(id);
      if (!node) {
        return;
      }
      node.classList.remove("audio-phase-step-active", "audio-phase-step-done", "audio-phase-step-error");
      if (config.done.includes(id)) {
        node.classList.add("audio-phase-step-done");
      }
      if (id === config.active) {
        node.classList.add("audio-phase-step-active");
      }
    });
  }

  function markPhaseError() {
    const config = AUDIO_PHASE_STAGES[phaseStage] || AUDIO_PHASE_STAGES.prepare;
    const activeNode = el(config.active);
    if (activeNode) {
      activeNode.classList.add("audio-phase-step-error");
    }
  }

  function appendLog(text) {
    const node = el("audioLogs");
    if (!node) {
      return;
    }
    node.textContent = `${node.textContent}\n${text}`.trim();
    node.scrollTop = node.scrollHeight;
  }

  function appendBackendLogs(logs) {
    if (!Array.isArray(logs) || logs.length === 0) {
      return;
    }
    logs.forEach((line) => {
      const text = String(line || "").trim();
      if (!text) {
        return;
      }
      appendLog(text);
    });
  }

  function resolveMediaSrc(mediaUrl, mediaPath) {
    const rawUrl = String(mediaUrl || "").trim();
    if (rawUrl) {
      if (rawUrl.startsWith("http://") || rawUrl.startsWith("https://")) {
        return rawUrl;
      }
      if (rawUrl.startsWith("/")) {
        return `${apiBase}${rawUrl}`;
      }
      return rawUrl;
    }

    const rawPath = String(mediaPath || "").trim();
    if (!rawPath) {
      return "";
    }
    if (rawPath.startsWith("http://") || rawPath.startsWith("https://")) {
      return rawPath;
    }
    if (rawPath.startsWith("/jobs-files/")) {
      return `${apiBase}${rawPath}`;
    }
    if (rawPath.startsWith("jobs-files/")) {
      return `${apiBase}/${rawPath}`;
    }
    if (rawPath.startsWith("/")) {
      return fileUrl(rawPath);
    }
    return rawPath;
  }

  function resolveAudioSrc(audioUrl, audioPath) {
    return resolveMediaSrc(audioUrl, audioPath);
  }

  function getVideoNode() {
    return el("audioVideoPreview");
  }

  function setVideoHint(text) {
    const node = el("audioVideoHint");
    if (node) {
      node.textContent = String(text || "");
    }
  }

  function setVideoPanelVisible(visible) {
    const panel = el("audioVideoPanel");
    if (panel) {
      panel.style.display = visible ? "" : "none";
    }
  }

  function setVideoPrepareEnabled(enabled) {
    const button = el("audioPrepareVideo");
    if (button) {
      button.disabled = !enabled;
    }
  }

  function clearVideoPreview() {
    const video = getVideoNode();
    if (video) {
      try {
        video.pause();
        video.removeAttribute("src");
        video.load();
      } catch (_) {
        // no-op
      }
    }
    videoPlayback.ready = false;
    videoPlayback.activeSrc = "";
    setVideoPanelVisible(false);
    setVideoPrepareEnabled(false);
    setVideoHint("영상 입력(mp4/유튜브)일 때만 표시됩니다.");
  }

  function seekVideoTo(seconds, { force = false } = {}) {
    const video = getVideoNode();
    if (!video || !videoPlayback.ready || (!force && !playback.tracks.length)) {
      return;
    }
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) {
      return;
    }
    videoPlayback.isProgrammaticSeek = true;
    try {
      video.currentTime = value;
    } catch (_) {
      // no-op
    }
    setTimeout(() => {
      videoPlayback.isProgrammaticSeek = false;
    }, 0);
  }

  function syncVideoToMaster(force = false) {
    if (!videoPlayback.ready || !playback.tracks.length) {
      return;
    }
    const video = getVideoNode();
    const master = playback.tracks[0];
    if (!video || !master) {
      return;
    }
    const audioNow = Number(master.audio.currentTime || 0);
    if (!Number.isFinite(audioNow)) {
      return;
    }
    const drift = Math.abs(Number(video.currentTime || 0) - audioNow);
    if (force || drift > 0.18) {
      seekVideoTo(audioNow, { force: true });
    }
    const rate = Number(master.audio.playbackRate || 1);
    if (Number.isFinite(rate) && rate > 0 && Math.abs(Number(video.playbackRate || 1) - rate) > 0.01) {
      video.playbackRate = rate;
    }
  }

  function pauseVideoPreview() {
    const video = getVideoNode();
    if (!video || !videoPlayback.ready) {
      return;
    }
    try {
      video.pause();
    } catch (_) {
      // no-op
    }
  }

  async function playVideoPreview() {
    const video = getVideoNode();
    if (!video || !videoPlayback.ready || !playback.tracks.length) {
      return;
    }
    syncVideoToMaster(true);
    try {
      await video.play();
    } catch (_) {
      // no-op
    }
  }

  async function fetchPreparedVideoSource(sourceType, filePath, youtubeUrl) {
    const payload = { source_type: sourceType };
    if (sourceType === "file") {
      payload.file_path = filePath;
    } else {
      payload.youtube_url = youtubeUrl;
    }

    const response = await fetch(`${apiBase}/preview/source`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "영상 소스 준비 실패" }));
      throw new Error(friendlyApiError(normalizeApiDetail(error.detail || "영상 소스 준비 실패")));
    }
    return response.json();
  }

  async function loadVideoPreviewForSource(payload, result, { force = false } = {}) {
    const sourceType = String(payload?.source_type || selectedAudioSourceType());
    const filePath = String(payload?.file_path || "").trim();
    const youtubeUrl = String(payload?.youtube_url || "").trim();
    const video = getVideoNode();
    if (!video) {
      return;
    }

    let src = "";

    const resultVideoUrl = String(result?.source_video_url || "").trim();
    const resultVideoPath = String(result?.source_video || "").trim();
    if (resultVideoUrl || resultVideoPath) {
      src = resolveMediaSrc(resultVideoUrl, resultVideoPath);
    }

    if (!src && sourceType === "file" && isVideoLikePath(filePath)) {
      src = resolveMediaSrc("", filePath);
    }

    if (!src && (sourceType === "youtube" || filePath)) {
      const prepared = await fetchPreparedVideoSource(sourceType, filePath, youtubeUrl);
      src = resolveMediaSrc(prepared?.video_url, prepared?.video_path);
    }

    if (!src || !isVideoLikePath(src)) {
      clearVideoPreview();
      return;
    }

    if (!force && src === videoPlayback.activeSrc) {
      setVideoPanelVisible(true);
      setVideoPrepareEnabled(true);
      setVideoHint("분리된 오디오와 동기 재생 중입니다.");
      syncVideoToMaster(true);
      return;
    }

    videoPlayback.ready = false;
    videoPlayback.activeSrc = src;
    setVideoPanelVisible(true);
    setVideoPrepareEnabled(true);
    setVideoHint("영상 로딩 중...");

    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch (_) {
      // no-op
    }

    video.src = src;
    video.load();
  }

  async function retryVideoPreview() {
    if (!latestSourcePayload && !latestSeparationResult) {
      setVideoHint("먼저 음원 분리를 실행해 주세요.");
      return;
    }
    try {
      await loadVideoPreviewForSource(
        latestSourcePayload || { source_type: selectedAudioSourceType() },
        latestSeparationResult || {},
        { force: true },
      );
    } catch (error) {
      setVideoHint(`영상 준비 실패: ${error.message}`);
      appendLog(`영상 준비 실패: ${error.message}`);
    }
  }

  function clampPracticeBpm(value, fallback = 120) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      return Math.max(PRACTICE_BPM_MIN, Math.min(PRACTICE_BPM_MAX, Math.round(Number(fallback) || 120)));
    }
    return Math.max(PRACTICE_BPM_MIN, Math.min(PRACTICE_BPM_MAX, Math.round(parsed)));
  }

  function clampPracticeRate(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return 1;
    }
    return Math.max(PRACTICE_RATE_MIN, Math.min(PRACTICE_RATE_MAX, parsed));
  }

  function derivePracticePlaybackRate() {
    const source = clampPracticeBpm(practiceSpeed.sourceBpm, 120);
    const target = clampPracticeBpm(practiceSpeed.targetBpm, source);
    if (!Number.isFinite(source) || source <= 0) {
      return 1;
    }
    return clampPracticeRate(target / source);
  }

  function renderPracticeSpeedUi() {
    const sourceNode = el("audioSourceBpm");
    const targetNode = el("audioPracticeBpm");
    const sliderNode = el("audioPracticeBpmSlider");
    const ratioNode = el("audioSpeedRatio");

    const source = clampPracticeBpm(practiceSpeed.sourceBpm, 120);
    const target = clampPracticeBpm(practiceSpeed.targetBpm, source);
    practiceSpeed.sourceBpm = source;
    practiceSpeed.targetBpm = target;

    if (sourceNode) {
      sourceNode.value = String(source);
    }
    if (targetNode) {
      targetNode.value = String(target);
    }
    if (sliderNode) {
      sliderNode.value = String(target);
    }
    if (ratioNode) {
      ratioNode.textContent = `${derivePracticePlaybackRate().toFixed(2)}x`;
    }
  }

  function setPracticeControlsEnabled(enabled) {
    const sourceNode = el("audioSourceBpm");
    const targetNode = el("audioPracticeBpm");
    const sliderNode = el("audioPracticeBpmSlider");
    if (sourceNode) {
      sourceNode.disabled = !enabled;
    }
    if (targetNode) {
      targetNode.disabled = !enabled;
    }
    if (sliderNode) {
      sliderNode.disabled = !enabled;
    }
  }

  function setPracticeSourceBpm(value, { keepRelative = false } = {}) {
    const prevSource = clampPracticeBpm(practiceSpeed.sourceBpm, 120);
    const prevTarget = clampPracticeBpm(practiceSpeed.targetBpm, prevSource);
    const nextSource = clampPracticeBpm(value, prevSource);
    practiceSpeed.sourceBpm = nextSource;

    if (!practiceSpeed.userAdjusted) {
      practiceSpeed.targetBpm = nextSource;
    } else if (keepRelative && prevSource > 0) {
      const ratio = prevTarget / prevSource;
      practiceSpeed.targetBpm = clampPracticeBpm(Math.round(nextSource * ratio), nextSource);
    } else {
      practiceSpeed.targetBpm = clampPracticeBpm(practiceSpeed.targetBpm, nextSource);
    }
    renderPracticeSpeedUi();
  }

  function setPracticeTargetBpm(value, { markUser = true } = {}) {
    practiceSpeed.targetBpm = clampPracticeBpm(value, practiceSpeed.sourceBpm);
    if (markUser) {
      practiceSpeed.userAdjusted = true;
    }
    renderPracticeSpeedUi();
  }

  function setPlaybackRate(rateValue) {
    const resolved = clampPracticeRate(rateValue);
    playback.tracks.forEach((track) => {
      track.audio.playbackRate = resolved;
    });
    const video = getVideoNode();
    if (video && videoPlayback.ready) {
      video.playbackRate = resolved;
    }
    renderPracticeSpeedUi();
  }

  function applyPracticeSpeedToPlayback() {
    const rate = derivePracticePlaybackRate();
    setPlaybackRate(rate);
  }

  function setMixerControlsEnabled(enabled) {
    const playButton = el("audioPlayToggle");
    const stopButton = el("audioStop");
    const seek = el("audioSeek");

    if (playButton) {
      playButton.disabled = !enabled;
    }
    if (stopButton) {
      stopButton.disabled = !enabled;
    }
    if (seek) {
      seek.disabled = !enabled;
    }
    document.querySelectorAll(".audio-stem-mute").forEach((button) => {
      button.disabled = !enabled;
    });
    setPracticeControlsEnabled(enabled);
  }

  function updatePlayButton() {
    const playButton = el("audioPlayToggle");
    if (!playButton) {
      return;
    }
    playButton.textContent = playback.isPlaying ? "일시정지" : "재생";
  }

  function getTimelineState() {
    const master = playback.tracks[0];
    const rawCurrent = master ? Number(master.audio.currentTime || 0) : 0;
    const fallbackDuration = master ? Number(master.audio.duration || 0) : 0;
    const resolvedDuration = Number.isFinite(playback.duration) && playback.duration > 0
      ? playback.duration
      : fallbackDuration;
    const duration = resolvedDuration > 0 ? resolvedDuration : 0;
    const ended = Boolean(master?.audio?.ended) || (duration > 0 && rawCurrent >= duration - 0.05);
    const current = duration > 0
      ? Math.max(0, Math.min(duration, Number.isFinite(rawCurrent) ? rawCurrent : 0))
      : Math.max(0, Number.isFinite(rawCurrent) ? rawCurrent : 0);
    return { current, duration, ended };
  }

  function updateTimeline() {
    const seek = el("audioSeek");
    const currentNode = el("audioCurrentTime");
    const durationNode = el("audioDuration");
    const timeline = getTimelineState();
    const forceCompleted = !playback.isPlaying && playback.completed && timeline.duration > 0;
    const displayCurrent = (forceCompleted || (!playback.isPlaying && timeline.ended && timeline.duration > 0))
      ? timeline.duration
      : timeline.current;
    playback.duration = timeline.duration;

    if (seek) {
      if (timeline.duration > 0) {
        const progressBase = (forceCompleted || (!playback.isPlaying && timeline.ended))
          ? 1
          : (displayCurrent / timeline.duration);
        const progress = Math.max(0, Math.min(1000, Math.round(progressBase * 1000)));
        seek.value = String(progress);
        seek.style.setProperty("--seek-progress", `${(progress / 10).toFixed(2)}%`);
      } else {
        seek.value = "0";
        seek.style.setProperty("--seek-progress", "0%");
      }
    }
    if (currentNode) {
      currentNode.textContent = formatTime(displayCurrent);
    }
    if (durationNode) {
      durationNode.textContent = formatTime(timeline.duration);
    }
  }

  function stopTimelineTicker() {
    if (playback.timerId) {
      clearInterval(playback.timerId);
      playback.timerId = null;
    }
  }

  function hasPlaybackReachedEnd() {
    return getTimelineState().ended;
  }

  function syncTracks(force = false) {
    const master = playback.tracks[0];
    if (!master) {
      return;
    }
    const baseTime = Number(master.audio.currentTime || 0);
    const baseRate = Number(master.audio.playbackRate || 1);
    if (!Number.isFinite(baseTime)) {
      return;
    }
    playback.tracks.forEach((track, index) => {
      if (index === 0) {
        return;
      }
      if (!Number.isFinite(track.audio.currentTime)) {
        return;
      }
      const drift = Math.abs(track.audio.currentTime - baseTime);
      if (force || drift > 0.06) {
        try {
          track.audio.currentTime = baseTime;
        } catch (_) {
          // no-op
        }
      }
      if (Math.abs(Number(track.audio.playbackRate || 1) - baseRate) > 0.01) {
        track.audio.playbackRate = baseRate;
      }
      if (playback.isPlaying && track.audio.paused) {
        track.audio.play().catch(() => {});
      }
    });
  }

  function seekTracksTo(timeSec) {
    const safe = Number(timeSec);
    if (!Number.isFinite(safe) || safe < 0) {
      return;
    }
    playback.completed = false;
    playback.tracks.forEach((track) => {
      try {
        track.audio.currentTime = safe;
      } catch (_) {
        // no-op
      }
    });
    seekVideoTo(safe, { force: true });
  }

  function startTimelineTicker() {
    stopTimelineTicker();
    playback.timerId = setInterval(() => {
      if (playback.isPlaying && hasPlaybackReachedEnd()) {
        stopPlayback({ resetPosition: false });
        return;
      }
      updateTimeline();
      if (playback.isPlaying) {
        syncTracks(false);
        syncVideoToMaster(false);
      }
    }, 80);
  }

  function pausePlayback() {
    playback.tracks.forEach((track) => {
      track.audio.pause();
    });
    pauseVideoPreview();
    playback.isPlaying = false;
    updatePlayButton();
    updateTimeline();
  }

  function stopPlayback({ resetPosition = true } = {}) {
    pausePlayback();
    if (resetPosition) {
      playback.completed = false;
      playback.tracks.forEach((track) => {
        try {
          track.audio.currentTime = 0;
        } catch (_) {
          // no-op
        }
      });
      seekVideoTo(0, { force: true });
      const seek = el("audioSeek");
      const currentNode = el("audioCurrentTime");
      if (seek) {
        seek.value = "0";
      }
      if (currentNode) {
        currentNode.textContent = "00:00";
      }
    } else {
      playback.completed = getTimelineState().ended;
    }
    updateTimeline();
  }

  async function playPlayback() {
    if (!playback.tracks.length) {
      return;
    }
    if (playback.completed || hasPlaybackReachedEnd()) {
      seekTracksTo(0);
      playback.completed = false;
    }
    syncTracks(true);
    const results = await Promise.allSettled(playback.tracks.map((track) => track.audio.play()));
    const success = results.some((result) => result.status === "fulfilled");
    if (!success) {
      appendLog("오류: 오디오 재생을 시작하지 못했어요.");
      playback.isPlaying = false;
      updatePlayButton();
      return;
    }
    playback.isPlaying = true;
    updatePlayButton();
    await playVideoPreview();
    startTimelineTicker();
  }

  function clearPlayback() {
    stopTimelineTicker();
    playback.tracks.forEach((track) => {
      try {
        track.audio.pause();
        track.audio.removeAttribute("src");
        track.audio.load();
      } catch (_) {
        // no-op
      }
    });
    playback.tracks = [];
    playback.duration = 0;
    playback.isPlaying = false;
    playback.completed = false;
    clearVideoPreview();
    updatePlayButton();
    updateTimeline();
    setMixerControlsEnabled(false);

    const mixerPanel = el("audioMixerPanel");
    if (mixerPanel) {
      mixerPanel.style.display = "none";
    }
    const mixerList = el("audioStemMixer");
    if (mixerList) {
      mixerList.replaceChildren();
    }
  }

  async function renderMixer(stemEntries) {
    const mixerPanel = el("audioMixerPanel");
    const mixerList = el("audioStemMixer");
    if (!mixerPanel || !mixerList) {
      return;
    }
    clearPlayback();

    if (!Array.isArray(stemEntries) || stemEntries.length === 0) {
      return;
    }

    mixerPanel.style.display = "block";
    const initialRate = derivePracticePlaybackRate();
    const ordered = stemEntries.slice().sort((a, b) => {
      const aKey = String(a.name || "").toLowerCase();
      const bKey = String(b.name || "").toLowerCase();
      if (aKey === "drums") {
        return -1;
      }
      if (bKey === "drums") {
        return 1;
      }
      return aKey.localeCompare(bKey);
    });

    const tracks = [];
    const loadPromises = ordered.map((entry) => {
      const src = resolveAudioSrc(entry.url, entry.path);
      if (!src) {
        return Promise.reject(new Error(`오디오 경로를 확인할 수 없어요: ${entry.name}`));
      }
      const audio = new Audio();
      audio.preload = "auto";
      audio.src = src;
      audio.loop = false;
      audio.volume = 0.8;
      audio.playbackRate = initialRate;
      tracks.push({
        name: entry.name,
        path: entry.path,
        url: entry.url,
        audio,
      });
      return new Promise((resolve, reject) => {
        const onReady = () => {
          cleanup();
          resolve();
        };
        const onError = () => {
          cleanup();
          reject(new Error(`오디오 로드 실패: ${entry.name}`));
        };
        const cleanup = () => {
          audio.removeEventListener("loadedmetadata", onReady);
          audio.removeEventListener("error", onError);
        };
        audio.addEventListener("loadedmetadata", onReady, { once: true });
        audio.addEventListener("error", onError, { once: true });
        audio.load();
      });
    });

    try {
      await Promise.all(loadPromises);
    } catch (error) {
      appendLog(`오류: ${error.message}`);
      return;
    }

    playback.tracks = tracks;
    playback.duration = Number(tracks[0]?.audio?.duration || 0);
    playback.completed = false;

    tracks[0].audio.addEventListener("ended", () => {
      stopPlayback({ resetPosition: false });
    });

    const fragment = document.createDocumentFragment();
    tracks.forEach((track) => {
      const row = document.createElement("div");
      row.className = `audio-stem-row audio-stem-row--${stemClassName(track.name)}`;

      const left = document.createElement("div");
      left.className = "audio-stem-left";

      const badge = document.createElement("span");
      badge.className = "audio-stem-badge";
      badge.textContent = stemCode(track.name);

      const nameNode = document.createElement("span");
      nameNode.className = "audio-stem-name";
      nameNode.textContent = stemLabel(track.name);
      left.append(badge, nameNode);

      const sliderWrap = document.createElement("div");
      sliderWrap.className = "audio-stem-slider-wrap";

      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "0";
      slider.max = "1";
      slider.step = "0.01";
      slider.value = String(track.audio.volume);
      sliderWrap.append(slider);

      const actions = document.createElement("div");
      actions.className = "audio-stem-actions";

      const valueNode = document.createElement("span");
      valueNode.className = "audio-stem-value";

      const muteButton = document.createElement("button");
      muteButton.type = "button";
      muteButton.className = "secondary audio-stem-mute";

      const syncTrackUi = () => {
        const muted = Boolean(track.audio.muted);
        row.classList.toggle("is-muted", muted);
        muteButton.textContent = muted ? "해제" : "음소거";
        valueNode.textContent = muted ? "MUTE" : `${Math.round(track.audio.volume * 100)}%`;
      };

      slider.addEventListener("input", () => {
        const next = Number(slider.value || "1");
        const volume = Number.isFinite(next) ? Math.max(0, Math.min(1, next)) : 1;
        track.audio.volume = volume;
        if (track.audio.muted && volume > 0) {
          track.audio.muted = false;
        }
        syncTrackUi();
      });

      muteButton.addEventListener("click", () => {
        track.audio.muted = !track.audio.muted;
        syncTrackUi();
      });

      actions.append(valueNode, muteButton);
      syncTrackUi();
      row.append(left, sliderWrap, actions);
      fragment.append(row);
    });

    mixerList.replaceChildren(fragment);
    latestStemEntries = tracks.map((track) => ({
      name: track.name,
      path: track.path,
      url: track.url,
    }));
    setMixerControlsEnabled(true);
    applyPracticeSpeedToPlayback();
    updatePlayButton();
    updateTimeline();
    startTimelineTicker();
  }

  function clearResult() {
    outputDir = "";
    latestStemEntries = [];
    latestSeparationResult = null;
    clearPlayback();
    const meta = el("audioResultMeta");
    if (meta) {
      meta.textContent = "";
    }
    const openButton = el("audioOpenOutputDir");
    if (openButton) {
      openButton.disabled = true;
    }
  }

  function renderResult(data) {
    outputDir = String(data?.output_dir || "");
    const meta = el("audioResultMeta");
    if (meta) {
      const lines = [];
      lines.push(`출력 폴더: ${outputDir || "-"}`);
      const stemMap = data && typeof data.audio_stems === "object" && data.audio_stems ? data.audio_stems : {};
      const stemNames = Object.keys(stemMap);
      if (stemNames.length) {
        lines.push(`생성 stem: ${stemNames.join(", ")}`);
      }
      if (data?.audio_model || data?.audio_device) {
        lines.push(`모델/장치: ${data.audio_model || "-"} / ${data.audio_device || "-"}`);
      }
      lines.push(`엔진: ${data?.audio_engine || "uvr_demucs"}`);
      meta.textContent = lines.join("\n");
    }

    const openButton = el("audioOpenOutputDir");
    if (openButton) {
      openButton.disabled = !outputDir;
    }

    const stemMap = data && typeof data.audio_stems === "object" && data.audio_stems ? data.audio_stems : {};
    const stemUrls = data && typeof data.audio_stem_urls === "object" && data.audio_stem_urls ? data.audio_stem_urls : {};
    let entries = Object.keys(stemMap).map((stemName) => ({
      name: stemName,
      path: stemMap[stemName],
      url: stemUrls[stemName],
    }));

    if (!entries.length && data?.audio_stem) {
      entries = [{
        name: "drums",
        path: data.audio_stem,
        url: data.audio_url || "",
      }];
    }
    renderMixer(entries);
  }

  function updateSourceRows() {
    const type = selectedAudioSourceType();
    const fileRow = el("audioFileRow");
    const youtubeRow = el("audioYoutubeRow");
    if (fileRow) {
      fileRow.style.display = type === "file" ? "flex" : "none";
    }
    if (youtubeRow) {
      youtubeRow.style.display = type === "youtube" ? "flex" : "none";
    }
    const sourceHint = el("audioSourceHint");
    if (sourceHint) {
      sourceHint.textContent = type === "youtube"
        ? "유튜브 URL은 먼저 로컬 파일로 준비됩니다. 네트워크 환경에 따라 첫 실행이 오래 걸릴 수 있어요."
        : "mp3/wav/mp4 파일을 바로 분리합니다. 영상(mp4)을 넣으면 아래 믹서에서 동기 재생도 가능합니다.";
    }
    refreshRunButtonState();
  }

  function buildPayload() {
    const type = selectedAudioSourceType();
    const payload = {
      source_type: type,
      options: {
        enable: true,
        engine: "uvr_demucs",
        model: el("audioModel")?.value || "htdemucs",
        stem: "drums",
        output_format: el("audioOutputFormat")?.value === "mp3" ? "mp3" : "wav",
        gpu_only: el("audioGpuOnly") ? Boolean(el("audioGpuOnly").checked) : false,
      },
    };

    if (type === "file") {
      const filePath = String(el("audioFilePath")?.value || "").trim();
      if (!filePath) {
        throw new Error("로컬 파일을 선택해 주세요.");
      }
      payload.file_path = filePath;
    } else {
      const url = String(el("audioYoutubeUrl")?.value || "").trim();
      if (!url) {
        throw new Error("유튜브 URL을 입력해 주세요.");
      }
      payload.youtube_url = url;
    }
    return payload;
  }

  function describeProgressPhase(elapsedSec) {
    const t = Number(elapsedSec) || 0;
    if (t < 4) {
      return { stage: "prepare", label: "요청 준비" };
    }
    if (t < 9) {
      return { stage: "extract", label: "오디오 추출" };
    }
    return { stage: "separate", label: "Stem 분리" };
  }

  async function runSeparation() {
    let progressTimer = null;
    let elapsed = 0;
    try {
      clearResult();
      const logsNode = el("audioLogs");
      if (logsNode) {
        logsNode.textContent = "";
      }
      setPhaseStage("prepare");
      runBusy = true;
      refreshRunButtonState();
      setStatus("분리 요청 준비");
      appendLog("드럼 음원 분리 시작");

      const payload = buildPayload();
      latestSourcePayload = payload;

      appendLog(`입력 소스: ${payload.source_type === "youtube" ? "유튜브" : "로컬 파일"}`);
      appendLog(`요청 옵션: 모델=${payload.options.model}, 포맷=${payload.options.output_format}, GPU전용=${payload.options.gpu_only ? "on" : "off"}`);
      setStatus("분리 요청 전송 중");

      progressTimer = setInterval(() => {
        elapsed += 1;
        const phase = describeProgressPhase(elapsed);
        setPhaseStage(phase.stage);
        setStatus(`분리 처리 중 · ${elapsed}s (${phase.label})`);
        if (elapsed > 0 && elapsed % 10 === 0) {
          appendLog(`진행 중: ${elapsed}s 경과 (${phase.label})`);
        }
      }, 1000);

      const response = await fetch(`${apiBase}/audio/separate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "오디오 분리 요청 실패" }));
        throw new Error(friendlyApiError(normalizeApiDetail(error.detail || "오디오 분리 요청 실패")));
      }

      const data = await response.json();
      latestSeparationResult = data;
      setPhaseStage("separate");
      appendBackendLogs(data.log_tail);
      renderResult(data);
      try {
        await loadVideoPreviewForSource(payload, data, { force: true });
      } catch (videoError) {
        appendLog(`영상 미리보기 준비 실패: ${videoError.message}`);
        setVideoHint("영상 준비 실패. '영상 다시 불러오기' 버튼으로 재시도해 주세요.");
      }
      setStatus("완료");
      const count = data?.audio_stems && typeof data.audio_stems === "object" ? Object.keys(data.audio_stems).length : 0;
      appendLog(count > 1 ? `완료: ${count}개 stem 생성` : `완료: ${data.audio_stem}`);
      setPhaseStage("done");
    } catch (error) {
      appendLog(`오류: ${error.message}`);
      setStatus("오류");
      markPhaseError();
    } finally {
      if (progressTimer) {
        clearInterval(progressTimer);
      }
      runBusy = false;
      refreshRunButtonState();
    }
  }

  function bindEvents() {
    document.querySelectorAll('input[name="audioSourceType"]').forEach((node) => {
      node.addEventListener("change", () => {
        updateSourceRows();
      });
    });

    const filePathNode = el("audioFilePath");
    if (filePathNode) {
      filePathNode.addEventListener("input", refreshRunButtonState);
    }
    const youtubeNode = el("audioYoutubeUrl");
    if (youtubeNode) {
      youtubeNode.addEventListener("input", refreshRunButtonState);
    }

    const browse = el("audioBrowseFile");
    if (browse) {
      browse.addEventListener("click", async () => {
        const picker = window.drumSheetAPI.selectAudioSourceFile || window.drumSheetAPI.selectVideoFile;
        const path = typeof picker === "function" ? await picker() : "";
        if (path) {
          const fileNode = el("audioFilePath");
          if (fileNode) {
            fileNode.value = path;
            fileNode.dispatchEvent(new Event("input", { bubbles: true }));
          }
        }
      });
    }

    const run = el("audioRunSeparation");
    if (run) {
      run.addEventListener("click", runSeparation);
    }

    const open = el("audioOpenOutputDir");
    if (open) {
      open.addEventListener("click", () => {
        if (!outputDir || !window.drumSheetAPI || typeof window.drumSheetAPI.openPath !== "function") {
          return;
        }
        window.drumSheetAPI.openPath(outputDir);
      });
    }

    const prepareVideo = el("audioPrepareVideo");
    if (prepareVideo) {
      prepareVideo.addEventListener("click", () => {
        retryVideoPreview();
      });
    }

    const video = getVideoNode();
    if (video) {
      video.addEventListener("loadedmetadata", () => {
        if (!videoPlayback.activeSrc) {
          return;
        }
        videoPlayback.ready = true;
        syncVideoToMaster(true);
        setVideoHint("분리된 오디오와 동기 재생 중입니다.");
      });
      video.addEventListener("error", () => {
        videoPlayback.ready = false;
        setVideoHint("영상을 재생하지 못했어요. '영상 다시 불러오기'를 눌러 재시도해 주세요.");
      });
      video.addEventListener("seeking", () => {
        if (videoPlayback.isProgrammaticSeek || !playback.tracks.length) {
          return;
        }
        const nextTime = Number(video.currentTime || 0);
        if (!Number.isFinite(nextTime)) {
          return;
        }
        playback.tracks.forEach((track) => {
          try {
            track.audio.currentTime = nextTime;
          } catch (_) {
            // no-op
          }
        });
        updateTimeline();
      });
      video.addEventListener("ended", () => {
        if (playback.isPlaying) {
          stopPlayback({ resetPosition: false });
        }
      });
    }

    const playToggle = el("audioPlayToggle");
    if (playToggle) {
      playToggle.addEventListener("click", async () => {
        if (playback.isPlaying) {
          pausePlayback();
          return;
        }
        await playPlayback();
      });
    }

    const stop = el("audioStop");
    if (stop) {
      stop.addEventListener("click", () => {
        stopPlayback({ resetPosition: true });
      });
    }

    const sourceBpm = el("audioSourceBpm");
    if (sourceBpm) {
      sourceBpm.addEventListener("change", () => {
        setPracticeSourceBpm(sourceBpm.value, { keepRelative: true });
        applyPracticeSpeedToPlayback();
      });
    }

    const practiceBpm = el("audioPracticeBpm");
    if (practiceBpm) {
      practiceBpm.addEventListener("change", () => {
        setPracticeTargetBpm(practiceBpm.value, { markUser: true });
        applyPracticeSpeedToPlayback();
      });
    }

    const practiceBpmSlider = el("audioPracticeBpmSlider");
    if (practiceBpmSlider) {
      practiceBpmSlider.addEventListener("input", () => {
        setPracticeTargetBpm(practiceBpmSlider.value, { markUser: true });
        applyPracticeSpeedToPlayback();
      });
    }

    const seek = el("audioSeek");
    if (seek) {
      seek.addEventListener("input", () => {
        if (!playback.tracks.length || playback.duration <= 0) {
          return;
        }
        const ratio = Number(seek.value || "0") / 1000;
        const nextTime = Math.max(0, Math.min(playback.duration, ratio * playback.duration));
        seekTracksTo(nextTime);
        updateTimeline();
      });
    }

    updateSourceRows();
    setPhaseStage("prepare");
    setStatus("대기 중");
    setVideoPrepareEnabled(false);
    setVideoPanelVisible(false);
    setVideoHint("영상 입력(mp4/유튜브)일 때만 표시됩니다.");
    setMixerControlsEnabled(false);
    updatePlayButton();
    updateTimeline();
    renderPracticeSpeedUi();
    refreshRunButtonState();

    const meta = el("audioResultMeta");
    if (meta && !String(meta.textContent || "").trim()) {
      meta.textContent = "분리 결과가 아직 없습니다. 실행하면 stem 정보와 저장 경로가 여기에 표시됩니다.";
    }
  }

  bindEvents();
  return {
    updateSourceRows,
  };
}
