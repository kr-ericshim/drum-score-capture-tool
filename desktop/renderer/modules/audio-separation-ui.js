import { el, fileUrl } from "./dom.js";
import { friendlyApiError, friendlyMessage } from "./messages.js";

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
const BEAT_TRACK_MODEL = "final0";
const BEAT_TRACK_GPU_ONLY = false;
const BEAT_TRACK_USE_DBN = true;
const METRONOME_SCHEDULER_INTERVAL_MS = 25;
const METRONOME_LOOKAHEAD_SEC = 0.25;
const METRONOME_LATE_TOLERANCE_SEC = 0.045;

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

export function createAudioSeparationUi({ apiBase }) {
  let outputDir = "";
  let latestStemEntries = [];
  let latestSourcePayload = null;
  let latestSeparationResult = null;
  let beatRequestId = 0;
  let markerSignature = "";
  const playback = {
    tracks: [],
    duration: 0,
    timerId: null,
    isPlaying: false,
  };
  const videoPlayback = {
    ready: false,
    activeSrc: "",
    isProgrammaticSeek: false,
  };
  const beatState = {
    beats: [],
    downbeats: [],
    bpm: null,
    model: "",
    device: "",
    beatTsv: "",
    status: "대기 중",
  };
  const metronome = {
    enabled: false,
    timerId: null,
    bpm: 120,
    detectedBpm: null,
    volume: 0.55,
    clickCount: 0,
    userAdjustedBpm: false,
    audioContext: null,
    nextBeatIndex: 0,
    nextManualBeatSec: 0,
    lastPlaybackTime: 0,
    downbeatCentis: new Set(),
    offsetMs: 0,
  };

  function setStatus(text) {
    const node = el("audioStatus");
    if (node) {
      node.textContent = text;
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
      appendLog(`[상세] ${friendlyMessage(text)}`);
    });
  }

  function describeProgressPhase(elapsedSec) {
    const sec = Number.isFinite(elapsedSec) ? Math.max(0, elapsedSec) : 0;
    if (sec < 8) {
      return "요청/의존성 확인";
    }
    if (sec < 20) {
      return "입력 오디오 추출";
    }
    return "Demucs 분리 실행";
  }

  function setVideoHint(text) {
    const node = el("audioVideoHint");
    if (node) {
      node.textContent = text;
    }
  }

  function setVideoPanelVisible(visible) {
    const panel = el("audioVideoPanel");
    if (panel) {
      panel.style.display = visible ? "block" : "none";
    }
  }

  function setVideoPrepareEnabled(enabled) {
    const button = el("audioPrepareVideo");
    if (button) {
      button.disabled = !enabled;
    }
  }

  function resolveMediaSrc(mediaUrl, mediaPath) {
    const url = String(mediaUrl || "").trim();
    if (url) {
      if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("file://")) {
        return url;
      }
      if (url.startsWith("/")) {
        return `${apiBase}${url}`;
      }
    }
    const path = String(mediaPath || "").trim();
    if (!path) {
      return "";
    }
    return fileUrl(path);
  }

  function resolveVideoCandidate(payload, result = null) {
    const sourceType = String(payload?.source_type || selectedAudioSourceType());
    const filePath = String(payload?.file_path || "").trim();
    const youtubeUrl = String(payload?.youtube_url || "").trim();
    const sourceVideoPath = String(result?.source_video || "").trim();
    const sourceVideoUrl = String(result?.source_video_url || "").trim();
    const candidatePath = sourceVideoPath || filePath;
    const hasVideo = sourceType === "youtube" || isVideoLikePath(candidatePath);
    return {
      sourceType,
      filePath,
      youtubeUrl,
      sourceVideoPath,
      sourceVideoUrl,
      hasVideo,
    };
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
      const error = await response.json().catch(() => ({ detail: "영상 준비 실패" }));
      throw new Error(friendlyApiError(normalizeApiDetail(error.detail || "영상 준비 실패")));
    }
    return response.json();
  }

  function setBeatStatus(text) {
    beatState.status = String(text || "대기 중");
    renderBeatMeta();
  }

  function setMetronomePanelVisible(visible) {
    const panel = el("metronomePanel");
    if (panel) {
      panel.style.display = visible ? "block" : "none";
    }
  }

  function setMetronomeButtonLabel() {
    const toggle = el("metronomeToggle");
    if (!toggle) {
      return;
    }
    toggle.textContent = metronome.enabled ? "메트로놈 끄기" : "메트로놈 켜기";
  }

  function setMetronomeControlsEnabled(enabled) {
    const toggle = el("metronomeToggle");
    const bpmInput = el("metronomeBpm");
    const volumeInput = el("metronomeVolume");
    const offsetInput = el("metronomeOffset");
    const useDetected = el("metronomeUseDetected");
    if (toggle) {
      toggle.disabled = !enabled;
    }
    if (bpmInput) {
      bpmInput.disabled = !enabled;
    }
    if (volumeInput) {
      volumeInput.disabled = !enabled;
    }
    if (offsetInput) {
      offsetInput.disabled = !enabled;
    }
    if (useDetected) {
      useDetected.disabled = !enabled || !Number.isFinite(Number(metronome.detectedBpm));
    }
  }

  function clampMetronomeBpm(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) {
      return metronome.bpm;
    }
    return Math.max(40, Math.min(260, Math.round(num)));
  }

  function setMetronomeBpm(value, { markUser = false, updateInput = true } = {}) {
    metronome.bpm = clampMetronomeBpm(value);
    if (markUser) {
      metronome.userAdjustedBpm = true;
    }
    if (updateInput) {
      const bpmInput = el("metronomeBpm");
      if (bpmInput) {
        bpmInput.value = String(metronome.bpm);
      }
    }
    renderBeatMeta();
  }

  function setMetronomeOffsetMs(value, { updateInput = true } = {}) {
    const num = Number(value);
    const resolved = Number.isFinite(num) ? Math.max(-220, Math.min(220, Math.round(num))) : 0;
    metronome.offsetMs = resolved;
    if (updateInput) {
      const offsetInput = el("metronomeOffset");
      if (offsetInput) {
        offsetInput.value = String(resolved);
      }
    }
    renderBeatMeta();
    if (metronome.enabled && playback.isPlaying) {
      startMetronomeTicker();
    }
  }

  function shouldUseDetectedBeatSchedule() {
    return !metronome.userAdjustedBpm && beatState.beats.length >= 2;
  }

  function metronomeOffsetSec() {
    return Number(metronome.offsetMs || 0) / 1000;
  }

  function isDownbeatTime(sec) {
    const key = Math.round(Number(sec) * 100);
    return metronome.downbeatCentis.has(key);
  }

  function resetDetectedBeatCursor(currentTime = 0) {
    const now = Number.isFinite(currentTime) ? Math.max(0, currentTime) : 0;
    const beats = Array.isArray(beatState.beats) ? beatState.beats : [];
    if (!beats.length) {
      metronome.nextBeatIndex = 0;
      metronome.lastPlaybackTime = now;
      return;
    }
    let idx = beats.findIndex((time) => Number(time) >= now - 0.02);
    if (idx < 0) {
      idx = beats.length;
    }
    metronome.nextBeatIndex = idx;
    metronome.lastPlaybackTime = now;
  }

  function resetManualBeatCursor(currentTime = 0) {
    const now = Number.isFinite(currentTime) ? Math.max(0, currentTime) : 0;
    metronome.nextManualBeatSec = now;
    metronome.clickCount = 0;
    metronome.lastPlaybackTime = now;
  }

  function applyDetectedBpm(nextBpm, { force = false } = {}) {
    const resolved = Number(nextBpm);
    if (!Number.isFinite(resolved) || resolved <= 0) {
      metronome.detectedBpm = null;
      setMetronomeControlsEnabled(latestStemEntries.length > 0);
      renderBeatMeta();
      return;
    }
    metronome.detectedBpm = Math.round(resolved);
    if (force || !metronome.userAdjustedBpm) {
      setMetronomeBpm(metronome.detectedBpm, { markUser: false, updateInput: true });
    } else {
      renderBeatMeta();
    }
    if (metronome.enabled && playback.isPlaying) {
      startMetronomeTicker();
    }
    setMetronomeControlsEnabled(latestStemEntries.length > 0);
  }

  function renderBeatMeta() {
    const node = el("metronomeMeta");
    if (!node) {
      return;
    }
    const lines = [];
    lines.push(`비트 분석 상태: ${beatState.status}`);
    lines.push(
      `감지 BPM: ${metronome.detectedBpm == null ? "분석 중/없음" : metronome.detectedBpm} · 현재 메트로놈 BPM: ${metronome.bpm}`,
    );
    lines.push(`동기 모드: ${shouldUseDetectedBeatSchedule() ? "감지 비트 추종(final0)" : "수동 BPM"} · 보정: ${metronome.offsetMs}ms`);
    lines.push(`메트로놈: ${metronome.enabled ? "ON" : "OFF"} · 클릭 볼륨: ${Math.round(metronome.volume * 100)}%`);
    lines.push(`비트 수: ${beatState.beats.length} / 다운비트 수: ${beatState.downbeats.length}`);
    lines.push(`모델/장치: ${beatState.model || "-"} / ${beatState.device || "-"}`);
    if (beatState.beatTsv) {
      lines.push(`비트 파일: ${beatState.beatTsv}`);
    }
    node.textContent = lines.join("\n");
  }

  function clearBeatMarkers() {
    const markerWrap = el("audioBeatMarkers");
    if (markerWrap) {
      markerWrap.replaceChildren();
    }
    markerSignature = "";
  }

  function clearBeatState() {
    beatRequestId += 1;
    beatState.beats = [];
    beatState.downbeats = [];
    beatState.bpm = null;
    beatState.model = "";
    beatState.device = "";
    beatState.beatTsv = "";
    beatState.status = "대기 중";
    metronome.detectedBpm = null;
    metronome.userAdjustedBpm = false;
    metronome.nextBeatIndex = 0;
    metronome.nextManualBeatSec = 0;
    metronome.lastPlaybackTime = 0;
    metronome.downbeatCentis = new Set();
    setMetronomeOffsetMs(0, { updateInput: true });
    setMetronomeBpm(120, { markUser: false, updateInput: true });
    clearBeatMarkers();
    renderBeatMeta();
    setMetronomeButtonLabel();
    setMetronomeControlsEnabled(latestStemEntries.length > 0);
  }

  function _sampleTimes(values, limit) {
    const list = Array.isArray(values) ? values : [];
    if (list.length <= limit) {
      return list;
    }
    const sampled = [];
    const step = Math.ceil(list.length / limit);
    for (let i = 0; i < list.length; i += step) {
      sampled.push(list[i]);
    }
    return sampled;
  }

  function renderBeatMarkers() {
    const markerWrap = el("audioBeatMarkers");
    if (!markerWrap) {
      return;
    }
    const duration = Number(playback.duration || 0);
    const signature = `${Math.round(duration * 100)}|${beatState.beats.length}|${beatState.downbeats.length}`;
    if (signature === markerSignature) {
      return;
    }
    markerSignature = signature;

    markerWrap.replaceChildren();
    if (duration <= 0 || (!beatState.beats.length && !beatState.downbeats.length)) {
      return;
    }

    const beatTimes = _sampleTimes(beatState.beats, 380);
    const downbeatTimes = _sampleTimes(beatState.downbeats, 220);
    const downbeatSet = new Set(downbeatTimes.map((v) => Math.round(Number(v) * 100)));

    const fragment = document.createDocumentFragment();
    beatTimes.forEach((time) => {
      const t = Number(time);
      if (!Number.isFinite(t) || t < 0 || t > duration) {
        return;
      }
      if (downbeatSet.has(Math.round(t * 100))) {
        return;
      }
      const marker = document.createElement("span");
      marker.className = "audio-beat-marker";
      marker.style.left = `${(t / duration) * 100}%`;
      fragment.append(marker);
    });
    downbeatTimes.forEach((time) => {
      const t = Number(time);
      if (!Number.isFinite(t) || t < 0 || t > duration) {
        return;
      }
      const marker = document.createElement("span");
      marker.className = "audio-beat-marker audio-beat-marker-downbeat";
      marker.style.left = `${(t / duration) * 100}%`;
      fragment.append(marker);
    });
    markerWrap.append(fragment);
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
    return labels[value] || name;
  }

  function resolveAudioSrc(audioUrl, audioPath) {
    return resolveMediaSrc(audioUrl, audioPath);
  }

  function setMixerControlsEnabled(enabled) {
    const playButton = el("audioPlayToggle");
    const stopButton = el("audioStop");
    const speed = el("audioSpeed");
    const seek = el("audioSeek");
    if (playButton) {
      playButton.disabled = !enabled;
    }
    if (stopButton) {
      stopButton.disabled = !enabled;
    }
    if (speed) {
      speed.disabled = !enabled;
    }
    if (seek) {
      seek.disabled = !enabled;
    }
  }

  function updatePlayButton() {
    const playButton = el("audioPlayToggle");
    if (!playButton) {
      return;
    }
    playButton.textContent = playback.isPlaying ? "일시정지" : "재생";
  }

  function formatTime(totalSec) {
    const sec = Number.isFinite(totalSec) ? Math.max(0, Math.floor(totalSec)) : 0;
    const minute = Math.floor(sec / 60);
    const remain = sec % 60;
    return `${String(minute).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
  }

  function syncTracks(force = false) {
    if (playback.tracks.length <= 1) {
      return;
    }
    const master = playback.tracks[0];
    const masterTime = Number(master.audio.currentTime || 0);
    const masterRate = Number(master.audio.playbackRate || 1);
    playback.tracks.slice(1).forEach((track) => {
      const drift = Math.abs((track.audio.currentTime || 0) - masterTime);
      if (force || drift > 0.08) {
        try {
          track.audio.currentTime = masterTime;
        } catch (_) {
          // no-op: some browser states can reject seeks temporarily.
        }
      }
      if (Math.abs((track.audio.playbackRate || 1) - masterRate) > 0.001) {
        track.audio.playbackRate = masterRate;
      }
    });
  }

  function getVideoNode() {
    return el("audioVideoPreview");
  }

  function seekVideoTo(nextTime, { force = false } = {}) {
    const video = getVideoNode();
    if (!video || !videoPlayback.ready) {
      return;
    }
    const safe = Number(nextTime);
    if (!Number.isFinite(safe) || safe < 0) {
      return;
    }
    const drift = Math.abs((video.currentTime || 0) - safe);
    if (!force && drift < 0.08) {
      return;
    }
    try {
      videoPlayback.isProgrammaticSeek = true;
      video.currentTime = safe;
    } catch (_) {
      // no-op
    } finally {
      setTimeout(() => {
        videoPlayback.isProgrammaticSeek = false;
      }, 0);
    }
  }

  function seekTracksTo(nextTime) {
    const safe = Number(nextTime);
    if (!Number.isFinite(safe) || safe < 0) {
      return;
    }
    playback.tracks.forEach((track) => {
      try {
        track.audio.currentTime = safe;
      } catch (_) {
        // no-op
      }
    });
    seekVideoTo(safe);
    if (shouldUseDetectedBeatSchedule()) {
      resetDetectedBeatCursor(safe);
    } else {
      resetManualBeatCursor(safe);
    }
  }

  function syncVideoToMaster(force = false) {
    const video = getVideoNode();
    const master = playback.tracks[0];
    if (!video || !videoPlayback.ready || !master) {
      return;
    }
    const masterTime = Number(master.audio.currentTime || 0);
    seekVideoTo(masterTime, { force });

    const masterRate = Number(master.audio.playbackRate || 1);
    if (Math.abs((video.playbackRate || 1) - masterRate) > 0.001) {
      video.playbackRate = masterRate;
    }
  }

  async function playVideoPreview() {
    const video = getVideoNode();
    if (!video || !videoPlayback.ready) {
      return;
    }
    syncVideoToMaster(true);
    try {
      await video.play();
    } catch (_) {
      // no-op: video autoplay may be blocked; audio playback can continue.
    }
  }

  function pauseVideoPreview() {
    const video = getVideoNode();
    if (!video) {
      return;
    }
    try {
      video.pause();
    } catch (_) {
      // no-op
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
    setVideoPrepareEnabled(Boolean(latestSourcePayload));
    setVideoHint("영상 입력(mp4/유튜브)일 때만 표시됩니다.");
  }

  async function loadVideoPreviewForSource(payload, result, { force = false } = {}) {
    latestSourcePayload = payload || latestSourcePayload;
    latestSeparationResult = result || latestSeparationResult;
    const source = resolveVideoCandidate(latestSourcePayload, latestSeparationResult);
    if (!source.hasVideo) {
      clearVideoPreview();
      appendLog("안내: 현재 입력은 오디오 파일이라 영상 미리보기를 생략합니다.");
      return false;
    }

    setVideoPanelVisible(true);
    setVideoPrepareEnabled(Boolean(latestSourcePayload));
    setVideoHint("영상 소스를 준비하고 있어요...");

    let videoPath = source.sourceVideoPath || source.filePath;
    let videoUrl = source.sourceVideoUrl;

    if (!videoUrl && source.sourceType === "youtube") {
      const prepared = await fetchPreparedVideoSource(source.sourceType, source.filePath, source.youtubeUrl);
      videoPath = String(prepared.video_path || "").trim() || videoPath;
      videoUrl = String(prepared.video_url || "").trim() || videoUrl;
      appendLog(prepared.from_cache ? "영상 미리보기: 캐시 영상 재사용" : "영상 미리보기: 유튜브 영상 준비 완료");
    }

    const nextSrc = resolveMediaSrc(videoUrl, videoPath);
    if (!nextSrc) {
      setVideoHint("영상 미리보기를 준비하지 못했어요.");
      return false;
    }

    const video = getVideoNode();
    if (!video) {
      return false;
    }

    const shouldReload = force || videoPlayback.activeSrc !== nextSrc;
    if (shouldReload) {
      try {
        video.pause();
      } catch (_) {
        // no-op
      }
      video.src = nextSrc;
      video.load();
      videoPlayback.activeSrc = nextSrc;
    }

    video.muted = true;
    videoPlayback.ready = true;
    syncVideoToMaster(true);
    setVideoHint("영상이 오디오와 동기화됩니다. 재생/정지/속도/탐색은 공용 컨트롤을 사용하세요.");
    return true;
  }

  async function retryVideoPreview() {
    if (!latestSourcePayload) {
      appendLog("안내: 먼저 음원 분리를 실행한 뒤 영상을 불러와 주세요.");
      return;
    }
    const button = el("audioPrepareVideo");
    try {
      if (button) {
        button.disabled = true;
      }
      await loadVideoPreviewForSource(latestSourcePayload, latestSeparationResult, { force: true });
    } catch (error) {
      appendLog(`영상 불러오기 오류: ${error.message}`);
      setVideoHint("영상 준비 실패. 버튼으로 다시 시도해 주세요.");
    } finally {
      if (button) {
        button.disabled = false;
      }
    }
  }

  function ensureMetronomeAudioContext() {
    if (metronome.audioContext && metronome.audioContext.state !== "closed") {
      return metronome.audioContext;
    }
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) {
      return null;
    }
    metronome.audioContext = new Ctx();
    return metronome.audioContext;
  }

  function playMetronomeClick(accent = false, whenSec = null) {
    const context = ensureMetronomeAudioContext();
    if (!context) {
      return;
    }
    if (context.state === "suspended") {
      context.resume().catch(() => {});
    }
    const now = context.currentTime;
    const when = Number.isFinite(whenSec) ? Math.max(now + 0.001, Number(whenSec)) : now;
    const osc = context.createOscillator();
    const gain = context.createGain();
    osc.type = "square";
    osc.frequency.setValueAtTime(accent ? 1550 : 1180, when);
    const level = Math.max(0, Math.min(1, Number(metronome.volume || 0.55)));
    gain.gain.setValueAtTime(0.0001, when);
    gain.gain.exponentialRampToValueAtTime(Math.max(0.02, level), when + 0.003);
    gain.gain.exponentialRampToValueAtTime(0.0001, when + 0.06);
    osc.connect(gain);
    gain.connect(context.destination);
    osc.start(when);
    osc.stop(when + 0.065);
  }

  function playbackSnapshot() {
    const master = playback.tracks[0];
    if (!master) {
      return null;
    }
    const mediaNow = Number(master.audio.currentTime || 0);
    if (!Number.isFinite(mediaNow)) {
      return null;
    }
    const playbackRate = Math.max(0.1, Number(master.audio.playbackRate || 1));
    return { mediaNow, playbackRate };
  }

  function stopMetronomeTicker() {
    if (metronome.timerId) {
      clearInterval(metronome.timerId);
      metronome.timerId = null;
    }
  }

  function scheduleDetectedBeats(snapshot, contextNow) {
    if (!shouldUseDetectedBeatSchedule()) {
      return;
    }
    const beats = beatState.beats;
    if (!Array.isArray(beats) || beats.length === 0) {
      return;
    }
    const lookaheadMedia = METRONOME_LOOKAHEAD_SEC * snapshot.playbackRate;
    const offsetSec = metronomeOffsetSec();
    let index = Math.max(0, Math.min(metronome.nextBeatIndex, beats.length));
    while (index < beats.length) {
      const beatSec = Number(beats[index]);
      if (!Number.isFinite(beatSec)) {
        index += 1;
        continue;
      }
      const targetSec = beatSec + offsetSec;
      const deltaMedia = targetSec - snapshot.mediaNow;
      if (deltaMedia > lookaheadMedia) {
        break;
      }
      if (deltaMedia < -METRONOME_LATE_TOLERANCE_SEC) {
        index += 1;
        continue;
      }
      const when = contextNow + deltaMedia / snapshot.playbackRate;
      playMetronomeClick(isDownbeatTime(beatSec), when);
      index += 1;
    }
    metronome.nextBeatIndex = index;
  }

  function scheduleManualBeats(snapshot, contextNow) {
    const intervalSec = 60 / Math.max(40, metronome.bpm);
    const lookaheadMedia = METRONOME_LOOKAHEAD_SEC * snapshot.playbackRate;
    const offsetSec = metronomeOffsetSec();

    if (!Number.isFinite(metronome.nextManualBeatSec)) {
      resetManualBeatCursor(snapshot.mediaNow);
    }

    while (metronome.nextManualBeatSec <= snapshot.mediaNow + lookaheadMedia) {
      const targetSec = metronome.nextManualBeatSec + offsetSec;
      const deltaMedia = targetSec - snapshot.mediaNow;
      if (deltaMedia >= -METRONOME_LATE_TOLERANCE_SEC) {
        const when = contextNow + deltaMedia / snapshot.playbackRate;
        playMetronomeClick(metronome.clickCount % 4 === 0, when);
      }
      metronome.clickCount += 1;
      metronome.nextManualBeatSec += intervalSec;
    }
  }

  function runMetronomeSchedulerTick() {
    if (!metronome.enabled || !playback.isPlaying) {
      return;
    }
    const snapshot = playbackSnapshot();
    if (!snapshot) {
      return;
    }
    const context = ensureMetronomeAudioContext();
    if (!context) {
      return;
    }
    if (context.state === "suspended") {
      context.resume().catch(() => {});
    }

    const prevTime = Number(metronome.lastPlaybackTime || 0);
    if (Number.isFinite(prevTime)) {
      const jumpedBackward = snapshot.mediaNow + 0.04 < prevTime;
      const jumpedForward = Math.abs(snapshot.mediaNow - prevTime) > 1.4;
      if (jumpedBackward || jumpedForward) {
        if (shouldUseDetectedBeatSchedule()) {
          resetDetectedBeatCursor(snapshot.mediaNow);
        } else {
          resetManualBeatCursor(snapshot.mediaNow);
        }
      }
    }

    if (shouldUseDetectedBeatSchedule()) {
      scheduleDetectedBeats(snapshot, context.currentTime);
    } else {
      scheduleManualBeats(snapshot, context.currentTime);
    }
    metronome.lastPlaybackTime = snapshot.mediaNow;
  }

  function startMetronomeTicker() {
    stopMetronomeTicker();
    if (!metronome.enabled || !playback.isPlaying) {
      return;
    }
    const snapshot = playbackSnapshot();
    if (!snapshot) {
      return;
    }
    if (shouldUseDetectedBeatSchedule()) {
      resetDetectedBeatCursor(snapshot.mediaNow);
    } else {
      resetManualBeatCursor(snapshot.mediaNow);
    }
    runMetronomeSchedulerTick();
    metronome.timerId = setInterval(runMetronomeSchedulerTick, METRONOME_SCHEDULER_INTERVAL_MS);
  }

  function toggleMetronome() {
    if (!latestStemEntries.length) {
      return;
    }
    metronome.enabled = !metronome.enabled;
    if (!metronome.enabled) {
      stopMetronomeTicker();
    } else if (playback.isPlaying) {
      const context = ensureMetronomeAudioContext();
      if (context && context.state === "suspended") {
        context.resume().catch(() => {});
      }
      metronome.clickCount = 0;
      startMetronomeTicker();
    } else {
      const context = ensureMetronomeAudioContext();
      if (context && context.state === "suspended") {
        context.resume().catch(() => {});
      }
    }
    setMetronomeButtonLabel();
    renderBeatMeta();
  }

  function updateTimeline() {
    const seek = el("audioSeek");
    const currentNode = el("audioCurrentTime");
    const durationNode = el("audioDuration");

    const master = playback.tracks[0];
    const masterTime = master ? Number(master.audio.currentTime || 0) : 0;
    const resolvedDuration = Number.isFinite(playback.duration) && playback.duration > 0
      ? playback.duration
      : Number(master?.audio?.duration || 0);
    playback.duration = resolvedDuration > 0 ? resolvedDuration : 0;

    if (seek) {
      if (playback.duration > 0) {
        const progress = Math.max(0, Math.min(1000, Math.round((masterTime / playback.duration) * 1000)));
        seek.value = String(progress);
      } else {
        seek.value = "0";
      }
    }
    if (currentNode) {
      currentNode.textContent = formatTime(masterTime);
    }
    if (durationNode) {
      durationNode.textContent = formatTime(playback.duration);
    }
    renderBeatMarkers();
  }

  function stopTimelineTicker() {
    if (playback.timerId) {
      clearInterval(playback.timerId);
      playback.timerId = null;
    }
  }

  function startTimelineTicker() {
    stopTimelineTicker();
    playback.timerId = setInterval(() => {
      updateTimeline();
      if (playback.isPlaying) {
        syncTracks(false);
        syncVideoToMaster(false);
      }
    }, 80);
  }

  function setPlaybackRate(rateValue) {
    const rate = Number(rateValue);
    const resolved = Number.isFinite(rate) && rate > 0 ? rate : 1;
    playback.tracks.forEach((track) => {
      track.audio.playbackRate = resolved;
    });
    const video = getVideoNode();
    if (video && videoPlayback.ready) {
      video.playbackRate = resolved;
    }
  }

  function pausePlayback() {
    playback.tracks.forEach((track) => {
      track.audio.pause();
    });
    stopMetronomeTicker();
    pauseVideoPreview();
    playback.isPlaying = false;
    updatePlayButton();
  }

  function stopPlayback({ resetPosition = true } = {}) {
    pausePlayback();
    if (resetPosition) {
      playback.tracks.forEach((track) => {
        try {
          track.audio.currentTime = 0;
        } catch (_) {
          // no-op
        }
      });
      seekVideoTo(0, { force: true });
      metronome.clickCount = 0;
      if (shouldUseDetectedBeatSchedule()) {
        resetDetectedBeatCursor(0);
      } else {
        resetManualBeatCursor(0);
      }
    }
    updateTimeline();
  }

  async function playPlayback() {
    if (!playback.tracks.length) {
      return;
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
    if (metronome.enabled) {
      const masterTime = Number(playback.tracks[0]?.audio?.currentTime || 0);
      if (shouldUseDetectedBeatSchedule()) {
        resetDetectedBeatCursor(masterTime);
      } else {
        resetManualBeatCursor(masterTime);
      }
      startMetronomeTicker();
    }
    startTimelineTicker();
  }

  function clearPlayback() {
    stopMetronomeTicker();
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
    latestStemEntries = [];
    setMetronomePanelVisible(false);
    setMetronomeControlsEnabled(false);
    clearBeatState();
  }

  function renderMixer(stemEntries) {
    clearPlayback();
    if (!Array.isArray(stemEntries) || stemEntries.length === 0) {
      return;
    }

    const mixerPanel = el("audioMixerPanel");
    const mixerList = el("audioStemMixer");
    if (!mixerPanel || !mixerList) {
      return;
    }

    mixerPanel.style.display = "block";
    const speedNode = el("audioSpeed");
    const initialRate = Number(speedNode?.value || 1) || 1;

    const ordered = stemEntries.slice().sort((a, b) => {
      const aKey = String(a.name || "").toLowerCase();
      const bKey = String(b.name || "").toLowerCase();
      if (aKey === "drums") return -1;
      if (bKey === "drums") return 1;
      return aKey.localeCompare(bKey);
    });

    const tracks = [];
    ordered.forEach((entry) => {
      const src = resolveAudioSrc(entry.url, entry.path);
      if (!src) {
        return;
      }
      const audio = new Audio(src);
      audio.preload = "metadata";
      audio.playbackRate = initialRate;
      const isDrum = String(entry.name || "").toLowerCase() === "drums";
      audio.volume = isDrum ? 1 : 0.8;
      audio.addEventListener("loadedmetadata", () => {
        playback.duration = Math.max(playback.duration, Number(audio.duration || 0));
        updateTimeline();
      });
      tracks.push({
        name: String(entry.name || "stem"),
        path: String(entry.path || ""),
        url: String(entry.url || ""),
        audio,
      });
    });

    if (!tracks.length) {
      return;
    }

    tracks[0].audio.addEventListener("ended", () => {
      stopPlayback({ resetPosition: true });
    });

    const fragment = document.createDocumentFragment();
    tracks.forEach((track) => {
      const row = document.createElement("div");
      row.className = "audio-stem-row";

      const nameNode = document.createElement("span");
      nameNode.className = "audio-stem-name";
      nameNode.textContent = stemLabel(track.name);

      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "0";
      slider.max = "1";
      slider.step = "0.01";
      slider.value = String(track.audio.volume);

      const valueNode = document.createElement("span");
      valueNode.className = "audio-stem-value";
      valueNode.textContent = `${Math.round(track.audio.volume * 100)}%`;

      slider.addEventListener("input", () => {
        const next = Number(slider.value || "1");
        const volume = Number.isFinite(next) ? Math.max(0, Math.min(1, next)) : 1;
        track.audio.volume = volume;
        valueNode.textContent = `${Math.round(volume * 100)}%`;
      });

      row.append(nameNode, slider, valueNode);
      fragment.append(row);
    });
    mixerList.replaceChildren(fragment);

    playback.tracks = tracks;
    latestStemEntries = tracks.map((track) => ({
      name: track.name,
      path: track.path,
      url: track.url,
    }));
    setMixerControlsEnabled(true);
    updatePlayButton();
    updateTimeline();
    startTimelineTicker();

    setMetronomePanelVisible(true);
    setMetronomeControlsEnabled(true);
    setMetronomeButtonLabel();
    setBeatStatus("분석 대기");
  }

  function clearResult() {
    const meta = el("audioResultMeta");
    if (meta) {
      meta.textContent = "";
    }
    outputDir = "";
    const openButton = el("audioOpenOutputDir");
    if (openButton) {
      openButton.disabled = true;
    }
    latestSeparationResult = null;
    clearPlayback();
  }

  function renderResult(data) {
    const meta = el("audioResultMeta");
    if (!meta) {
      return;
    }
    const lines = [];
    lines.push("작업 상태: 완료");
    if (data.audio_stem) {
      lines.push(`분리 음원: ${data.audio_stem}`);
      outputDir = data.output_dir || dirname(data.audio_stem);
    }
    const stemMap = data && typeof data.audio_stems === "object" && data.audio_stems ? data.audio_stems : {};
    const stemNames = Object.keys(stemMap);
    if (stemNames.length) {
      lines.push(`생성 stem: ${stemNames.join(", ")}`);
    }
    if (data.audio_model || data.audio_device) {
      lines.push(`모델/장치: ${data.audio_model || "-"} / ${data.audio_device || "-"}`);
    }
    lines.push(`엔진: ${data.audio_engine || "uvr_demucs"}`);
    meta.textContent = lines.join("\n");

    const openButton = el("audioOpenOutputDir");
    if (openButton) {
      openButton.disabled = !outputDir;
    }

    const stemUrls = data && typeof data.audio_stem_urls === "object" && data.audio_stem_urls ? data.audio_stem_urls : {};
    let entries = stemNames.map((stemName) => ({
      name: stemName,
      path: stemMap[stemName],
      url: stemUrls[stemName],
    }));
    if (!entries.length && data.audio_stem) {
      entries = [{
        name: "drums",
        path: data.audio_stem,
        url: data.audio_url || "",
      }];
    }
    renderMixer(entries);
  }

  function selectedStemForBeatTracking() {
    if (!latestStemEntries.length) {
      return null;
    }
    const drum = latestStemEntries.find((entry) => String(entry.name || "").toLowerCase() === "drums");
    if (drum) {
      return drum;
    }
    return latestStemEntries[0];
  }

  function buildBeatPayload() {
    const selected = selectedStemForBeatTracking();
    if (!selected || !selected.path) {
      throw new Error("비트 분석할 오디오를 찾지 못했어요. 먼저 음원 분리를 실행해 주세요.");
    }

    const sourceType = String(latestSourcePayload?.source_type || selectedAudioSourceType());
    const payload = {
      source_type: sourceType,
      audio_path: String(selected.path),
      options: {
        model: BEAT_TRACK_MODEL,
        gpu_only: BEAT_TRACK_GPU_ONLY,
        use_dbn: BEAT_TRACK_USE_DBN,
        float16: false,
        save_tsv: true,
      },
    };

    if (sourceType === "file") {
      const filePath = String(latestSourcePayload?.file_path || el("audioFilePath")?.value || "").trim();
      if (filePath) {
        payload.file_path = filePath;
      }
    } else {
      const url = String(latestSourcePayload?.youtube_url || el("audioYoutubeUrl")?.value || "").trim();
      if (url) {
        payload.youtube_url = url;
      }
    }
    return { payload, selected };
  }

  async function runBeatTracking() {
    const requestId = ++beatRequestId;
    try {
      setBeatStatus("자동 분석 중");
      appendLog("비트 분석 자동 시작");
      const { payload, selected } = buildBeatPayload();
      appendLog(`비트 분석 대상: ${stemLabel(selected.name)} (${selected.path})`);
      const response = await fetch(`${apiBase}/audio/beat-track`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "비트 분석 요청 실패" }));
        throw new Error(friendlyApiError(normalizeApiDetail(error.detail || "비트 분석 요청 실패")));
      }
      const data = await response.json();
      if (requestId !== beatRequestId) {
        return;
      }
      appendBackendLogs(data.log_tail);

      beatState.beats = Array.isArray(data.beats) ? data.beats.map((value) => Number(value)).filter((value) => Number.isFinite(value)) : [];
      beatState.downbeats = Array.isArray(data.downbeats) ? data.downbeats.map((value) => Number(value)).filter((value) => Number.isFinite(value)) : [];
      beatState.bpm = Number.isFinite(Number(data.bpm)) ? Number(data.bpm) : null;
      beatState.model = String(data.model || payload.options.model || "");
      beatState.device = String(data.device || "");
      beatState.beatTsv = String(data.beat_tsv || "");
      metronome.downbeatCentis = new Set(beatState.downbeats.map((value) => Math.round(Number(value) * 100)));
      applyDetectedBpm(beatState.bpm, { force: false });
      const currentTime = Number(playback.tracks[0]?.audio?.currentTime || 0);
      if (shouldUseDetectedBeatSchedule()) {
        resetDetectedBeatCursor(currentTime);
      } else {
        resetManualBeatCursor(currentTime);
      }
      markerSignature = "";
      renderBeatMeta();
      renderBeatMarkers();

      setBeatStatus("완료");
      appendLog(`비트 분석 완료: beats=${beatState.beats.length}, downbeats=${beatState.downbeats.length}, bpm=${beatState.bpm ?? "n/a"}`);
    } catch (error) {
      if (requestId !== beatRequestId) {
        return;
      }
      setBeatStatus("오류");
      appendLog(`비트 분석 오류: ${error.message}`);
    }
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

  async function runSeparation() {
    const runButton = el("audioRunSeparation");
    let progressTimer = null;
    let elapsed = 0;
    try {
      clearResult();
      if (runButton) {
        runButton.disabled = true;
      }
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
        setStatus(`분리 처리 중 · ${elapsed}s (${phase})`);
        if (elapsed > 0 && elapsed % 10 === 0) {
          appendLog(`진행 중: ${elapsed}s 경과 (${phase})`);
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
      if (latestStemEntries.length > 0) {
        runBeatTracking().catch((error) => {
          appendLog(`비트 분석 오류: ${error.message}`);
        });
      }
    } catch (error) {
      appendLog(`오류: ${error.message}`);
      setStatus("오류");
    } finally {
      if (progressTimer) {
        clearInterval(progressTimer);
      }
      if (runButton) {
        runButton.disabled = false;
      }
    }
  }

  function bindEvents() {
    document.querySelectorAll('input[name="audioSourceType"]').forEach((node) => {
      node.addEventListener("change", updateSourceRows);
    });

    const browse = el("audioBrowseFile");
    if (browse) {
      browse.addEventListener("click", async () => {
        const picker = window.drumSheetAPI.selectAudioSourceFile || window.drumSheetAPI.selectVideoFile;
        const path = typeof picker === "function" ? await picker() : "";
        if (path) {
          const fileNode = el("audioFilePath");
          if (fileNode) {
            fileNode.value = path;
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
        if (!outputDir) {
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
        if (shouldUseDetectedBeatSchedule()) {
          resetDetectedBeatCursor(nextTime);
        } else {
          resetManualBeatCursor(nextTime);
        }
        updateTimeline();
      });
      video.addEventListener("ended", () => {
        if (playback.isPlaying) {
          stopPlayback({ resetPosition: true });
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

    const speed = el("audioSpeed");
    if (speed) {
      speed.addEventListener("change", () => {
        setPlaybackRate(speed.value);
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

    const metronomeToggle = el("metronomeToggle");
    if (metronomeToggle) {
      metronomeToggle.addEventListener("click", () => {
        toggleMetronome();
      });
    }

    const metronomeBpm = el("metronomeBpm");
    if (metronomeBpm) {
      metronomeBpm.addEventListener("change", () => {
        setMetronomeBpm(metronomeBpm.value, { markUser: true, updateInput: true });
        if (metronome.enabled && playback.isPlaying) {
          startMetronomeTicker();
        }
      });
    }

    const metronomeVolume = el("metronomeVolume");
    if (metronomeVolume) {
      metronomeVolume.addEventListener("input", () => {
        const next = Number(metronomeVolume.value || "0.55");
        metronome.volume = Number.isFinite(next) ? Math.max(0, Math.min(1, next)) : 0.55;
      });
    }

    const metronomeOffset = el("metronomeOffset");
    if (metronomeOffset) {
      metronomeOffset.addEventListener("change", () => {
        setMetronomeOffsetMs(metronomeOffset.value, { updateInput: true });
      });
    }

    const useDetectedButton = el("metronomeUseDetected");
    if (useDetectedButton) {
      useDetectedButton.addEventListener("click", () => {
        if (!Number.isFinite(Number(metronome.detectedBpm))) {
          return;
        }
        setMetronomeBpm(metronome.detectedBpm, { markUser: false, updateInput: true });
        metronome.userAdjustedBpm = false;
        if (metronome.enabled && playback.isPlaying) {
          startMetronomeTicker();
        }
      });
    }

    updateSourceRows();
    setVideoPrepareEnabled(false);
    setVideoPanelVisible(false);
    setVideoHint("영상 입력(mp4/유튜브)일 때만 표시됩니다.");
    setMetronomePanelVisible(false);
    setMetronomeButtonLabel();
    setMetronomeControlsEnabled(false);
    setMixerControlsEnabled(false);
    setBeatStatus("대기 중");
    updatePlayButton();
    clearBeatState();
    updateTimeline();
  }

  bindEvents();
  return {
    updateSourceRows,
  };
}
