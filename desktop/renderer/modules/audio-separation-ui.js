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

export function createAudioSeparationUi({ apiBase }) {
  let outputDir = "";
  let latestStemEntries = [];
  let markerSignature = "";
  const playback = {
    tracks: [],
    duration: 0,
    timerId: null,
    isPlaying: false,
  };
  const beatState = {
    beats: [],
    downbeats: [],
    bpm: null,
    model: "",
    device: "",
    beatTsv: "",
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

  function setBeatStatus(text) {
    const node = el("beatTrackStatus");
    if (node) {
      node.textContent = text;
    }
  }

  function setBeatRunEnabled(enabled) {
    const runButton = el("beatTrackRun");
    if (runButton) {
      runButton.disabled = !enabled;
    }
  }

  function renderBeatMeta() {
    const node = el("beatTrackMeta");
    if (!node) {
      return;
    }
    if (!beatState.beats.length) {
      node.textContent = "아직 비트 분석 결과가 없습니다.";
      return;
    }
    const lines = [];
    lines.push(`비트 수: ${beatState.beats.length}  /  다운비트 수: ${beatState.downbeats.length}`);
    lines.push(`예상 BPM: ${beatState.bpm == null ? "계산 불가" : beatState.bpm}`);
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
    beatState.beats = [];
    beatState.downbeats = [];
    beatState.bpm = null;
    beatState.model = "";
    beatState.device = "";
    beatState.beatTsv = "";
    clearBeatMarkers();
    renderBeatMeta();
    setBeatStatus("대기 중");
    setBeatRunEnabled(latestStemEntries.length > 0);
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
    const url = String(audioUrl || "").trim();
    if (url) {
      if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("file://")) {
        return url;
      }
      if (url.startsWith("/")) {
        return `${apiBase}${url}`;
      }
    }

    const path = String(audioPath || "").trim();
    if (!path) {
      return "";
    }
    return fileUrl(path);
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
      }
    }, 180);
  }

  function setPlaybackRate(rateValue) {
    const rate = Number(rateValue);
    const resolved = Number.isFinite(rate) && rate > 0 ? rate : 1;
    playback.tracks.forEach((track) => {
      track.audio.playbackRate = resolved;
    });
  }

  function pausePlayback() {
    playback.tracks.forEach((track) => {
      track.audio.pause();
    });
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
    const beatPanel = el("beatTrackPanel");
    if (beatPanel) {
      beatPanel.style.display = "none";
    }
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

    const beatPanel = el("beatTrackPanel");
    if (beatPanel) {
      beatPanel.style.display = "block";
    }
    setBeatRunEnabled(true);
    setBeatStatus("대기 중");
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
    const preferDrum = Boolean(el("beatTrackUseDrum")?.checked);
    if (preferDrum) {
      const drum = latestStemEntries.find((entry) => String(entry.name || "").toLowerCase() === "drums");
      if (drum) {
        return drum;
      }
    }
    return latestStemEntries[0];
  }

  function buildBeatPayload() {
    const selected = selectedStemForBeatTracking();
    if (!selected || !selected.path) {
      throw new Error("비트 분석할 오디오를 찾지 못했어요. 먼저 음원 분리를 실행해 주세요.");
    }

    const sourceType = selectedAudioSourceType();
    const payload = {
      source_type: sourceType,
      audio_path: String(selected.path),
      options: {
        model: String(el("beatTrackModel")?.value || "small0"),
        gpu_only: Boolean(el("beatTrackGpuOnly")?.checked),
        use_dbn: false,
        float16: false,
        save_tsv: true,
      },
    };

    if (sourceType === "file") {
      const filePath = String(el("audioFilePath")?.value || "").trim();
      if (filePath) {
        payload.file_path = filePath;
      }
    } else {
      const url = String(el("audioYoutubeUrl")?.value || "").trim();
      if (url) {
        payload.youtube_url = url;
      }
    }
    return { payload, selected };
  }

  async function runBeatTracking() {
    const runButton = el("beatTrackRun");
    try {
      if (runButton) {
        runButton.disabled = true;
      }
      setBeatStatus("분석 요청 중");
      appendLog("비트 분석 시작");
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
      appendBackendLogs(data.log_tail);

      beatState.beats = Array.isArray(data.beats) ? data.beats.map((value) => Number(value)).filter((value) => Number.isFinite(value)) : [];
      beatState.downbeats = Array.isArray(data.downbeats) ? data.downbeats.map((value) => Number(value)).filter((value) => Number.isFinite(value)) : [];
      beatState.bpm = Number.isFinite(Number(data.bpm)) ? Number(data.bpm) : null;
      beatState.model = String(data.model || payload.options.model || "");
      beatState.device = String(data.device || "");
      beatState.beatTsv = String(data.beat_tsv || "");
      markerSignature = "";
      renderBeatMeta();
      renderBeatMarkers();

      setBeatStatus("완료");
      appendLog(`비트 분석 완료: beats=${beatState.beats.length}, downbeats=${beatState.downbeats.length}, bpm=${beatState.bpm ?? "n/a"}`);
    } catch (error) {
      setBeatStatus("오류");
      appendLog(`오류: ${error.message}`);
    } finally {
      if (runButton) {
        runButton.disabled = latestStemEntries.length === 0;
      }
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
      appendBackendLogs(data.log_tail);
      renderResult(data);
      setStatus("완료");
      const count = data?.audio_stems && typeof data.audio_stems === "object" ? Object.keys(data.audio_stems).length : 0;
      appendLog(count > 1 ? `완료: ${count}개 stem 생성` : `완료: ${data.audio_stem}`);
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
        playback.tracks.forEach((track) => {
          try {
            track.audio.currentTime = nextTime;
          } catch (_) {
            // no-op
          }
        });
        updateTimeline();
      });
    }

    const beatRun = el("beatTrackRun");
    if (beatRun) {
      beatRun.addEventListener("click", runBeatTracking);
    }

    updateSourceRows();
    setMixerControlsEnabled(false);
    setBeatRunEnabled(false);
    updatePlayButton();
    clearBeatState();
    updateTimeline();
  }

  bindEvents();
  return {
    updateSourceRows,
  };
}
