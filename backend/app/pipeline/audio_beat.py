from __future__ import annotations

import importlib.util
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from app.schemas import BeatTrackOptions


def extract_audio_for_beat_input(*, source_video: Path, audio_output: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_video),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(audio_output),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not audio_output.exists() or audio_output.stat().st_size <= 0:
        stderr = result.stderr.strip() if result.stderr else "unknown ffmpeg error"
        raise RuntimeError(f"Failed to extract audio track: {stderr}")


def track_beats_for_audio(
    *,
    audio_input: Path,
    options: BeatTrackOptions,
    workspace: Path,
    logger,
) -> Dict[str, object]:
    _ensure_beat_stack_installed(use_dbn=options.use_dbn)

    workspace.mkdir(parents=True, exist_ok=True)
    prepared_audio = workspace / "beat_input.wav"
    logger("beat tracking stage: prepare audio input")
    _normalize_audio_for_inference(source_audio=audio_input, audio_output=prepared_audio)
    logger(f"beat tracking input prepared: {prepared_audio}")

    device = _resolve_beat_device()
    if options.gpu_only and device == "cpu":
        raise RuntimeError("Beat tracking requires GPU, but CUDA/MPS is not available.")
    logger(f"beat tracking model={options.model}, device={device}, dbn={options.use_dbn}, float16={options.float16}")

    logger("beat tracking stage: run model inference")
    infer_start = time.perf_counter()
    beats, downbeats = _run_beat_this(
        audio_path=prepared_audio,
        model=options.model,
        device=device,
        use_dbn=options.use_dbn,
        float16=options.float16,
    )
    infer_elapsed = time.perf_counter() - infer_start
    logger(f"beat tracking inference completed in {infer_elapsed:.2f}s")

    beat_list = _to_float_list(beats)
    downbeat_list = _to_float_list(downbeats)
    bpm = _estimate_bpm(beat_list)
    logger(f"beat tracking result: beats={len(beat_list)}, downbeats={len(downbeat_list)}, bpm={bpm if bpm is not None else 'n/a'}")

    beat_tsv: Optional[Path] = None
    if options.save_tsv:
        beat_tsv = workspace / "beats.tsv"
        _save_beat_tsv(beat_list=beat_list, downbeat_list=downbeat_list, output_path=beat_tsv)
        logger(f"beat tracking tsv saved: {beat_tsv}")

    return {
        "audio_path": str(prepared_audio),
        "beats": beat_list,
        "downbeats": downbeat_list,
        "beat_count": len(beat_list),
        "downbeat_count": len(downbeat_list),
        "bpm": bpm,
        "model": options.model,
        "device": device,
        "beat_tsv": str(beat_tsv) if beat_tsv else None,
    }


def _normalize_audio_for_inference(*, source_audio: Path, audio_output: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_audio),
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(audio_output),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not audio_output.exists() or audio_output.stat().st_size <= 0:
        stderr = result.stderr.strip() if result.stderr else "unknown ffmpeg error"
        raise RuntimeError(f"Failed to prepare audio for beat tracking: {stderr}")


def _run_beat_this(
    *,
    audio_path: Path,
    model: str,
    device: str,
    use_dbn: bool,
    float16: bool,
) -> tuple[np.ndarray, np.ndarray]:
    try:
        from beat_this.inference import File2Beats  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"beat_this import failed: {exc}")

    tracker = File2Beats(checkpoint_path=model, device=device, float16=float16, dbn=use_dbn)
    beats, downbeats = tracker(str(audio_path))
    return np.asarray(beats, dtype=np.float64), np.asarray(downbeats, dtype=np.float64)


def _save_beat_tsv(*, beat_list: list[float], downbeat_list: list[float], output_path: Path) -> None:
    try:
        from beat_this.utils import save_beat_tsv  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"beat_this utility import failed: {exc}")
    beats = np.asarray(beat_list, dtype=np.float64)
    downbeats = np.asarray(downbeat_list, dtype=np.float64)
    save_beat_tsv(beats, downbeats, str(output_path))


def _to_float_list(values) -> list[float]:
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return []
    return [float(v) for v in arr.tolist()]


def _estimate_bpm(beats: list[float]) -> Optional[float]:
    if len(beats) < 2:
        return None
    values = np.asarray(beats, dtype=np.float64)
    intervals = np.diff(values)
    intervals = intervals[(intervals > 0.18) & (intervals < 2.5)]
    if intervals.size == 0:
        return None
    bpm = 60.0 / float(np.median(intervals))
    if not np.isfinite(bpm):
        return None
    return round(float(bpm), 2)


def _resolve_beat_device() -> str:
    try:
        import torch  # type: ignore
    except Exception:
        return "cpu"

    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass

    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass

    return "cpu"


def _ensure_beat_stack_installed(*, use_dbn: bool) -> None:
    if importlib.util.find_spec("beat_this") is None:
        raise RuntimeError("beat_this is not installed. Install optional dependency and retry.")
    if importlib.util.find_spec("soxr") is None:
        raise RuntimeError("soxr is not installed. Install soxr and retry.")
    if importlib.util.find_spec("rotary_embedding_torch") is None:
        raise RuntimeError("rotary-embedding-torch is not installed. Install it and retry.")
    if importlib.util.find_spec("torch") is None:
        raise RuntimeError("torch is not installed. Install torch and retry.")
    if use_dbn and importlib.util.find_spec("madmom") is None:
        raise RuntimeError("madmom is required when DBN mode is enabled.")
