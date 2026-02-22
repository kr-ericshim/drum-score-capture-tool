from __future__ import annotations

import importlib.util
import subprocess
import time
import platform
from pathlib import Path
import re
import uuid
from typing import Callable, Dict, Optional

import numpy as np

from app.pipeline.ffmpeg_runtime import ensure_runtime_bin_on_path, resolve_ffmpeg_bin
from app.pipeline.torch_runtime import (
    inspect_torch_runtime,
    select_torch_device,
    torch_runtime_summary,
    torch_gpu_error_hint,
)
from app.schemas import BeatTrackOptions


def extract_audio_for_beat_input(*, source_video: Path, audio_output: Path) -> None:
    ffmpeg_bin = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    cmd = [
        ffmpeg_bin,
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
    requested_dbn = bool(options.use_dbn)
    dbn_enabled = requested_dbn
    if requested_dbn and importlib.util.find_spec("madmom") is None:
        dbn_enabled = False
        logger("beat tracking fallback: madmom is not installed, DBN disabled (continuing with non-DBN mode)")

    _ensure_beat_stack_installed(use_dbn=dbn_enabled, logger=logger)

    workspace.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    ensure_runtime_bin_on_path(ffmpeg_bin=ffmpeg_bin, logger=logger)
    prepared_audio = workspace / f"{_safe_audio_stem(audio_input)}_{uuid.uuid4().hex[:8]}_beat_input.wav"
    logger("beat tracking stage: prepare audio input")
    _normalize_audio_for_inference(source_audio=audio_input, audio_output=prepared_audio)
    logger(f"beat tracking input prepared: {prepared_audio}")

    torch_info = inspect_torch_runtime()
    device = select_torch_device(torch_info)
    logger(f"beat tracking torch runtime: {torch_runtime_summary(torch_info)}")
    if options.gpu_only and device == "cpu":
        raise RuntimeError(torch_gpu_error_hint(torch_info, task_name="Beat tracking"))
    logger(f"beat tracking model={options.model}, device={device}, dbn={dbn_enabled}, float16={options.float16}")

    logger("beat tracking stage: run model inference")
    infer_start = time.perf_counter()
    beats, downbeats = _run_beat_this(
        audio_path=prepared_audio,
        model=options.model,
        device=device,
        use_dbn=dbn_enabled,
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
        "dbn_used": dbn_enabled,
        "beat_tsv": str(beat_tsv) if beat_tsv else None,
    }


def _normalize_audio_for_inference(*, source_audio: Path, audio_output: Path) -> None:
    ffmpeg_bin = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    cmd = [
        ffmpeg_bin,
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


def _safe_audio_stem(path: Path) -> str:
    stem = path.stem.strip().replace(" ", "_") or "audio"
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("._-")
    return stem or "audio"


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
    except ModuleNotFoundError as exc:
        if exc.name == "soundfile":
            raise RuntimeError("soundfile is not installed. Install soundfile and retry.")
        raise RuntimeError(f"beat_this import failed: {exc}")
    except Exception as exc:
        raise RuntimeError(f"beat_this import failed: {exc}")

    try:
        tracker = File2Beats(checkpoint_path=model, device=device, float16=float16, dbn=use_dbn)
        beats, downbeats = tracker(str(audio_path))
    except ModuleNotFoundError as exc:
        if exc.name == "soundfile":
            raise RuntimeError("soundfile is not installed. Install soundfile and retry.")
        raise RuntimeError(f"beat tracking inference failed: {exc}")
    except Exception as exc:
        raise RuntimeError(f"beat tracking inference failed: {exc}")
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


def _ensure_beat_stack_installed(*, use_dbn: bool, logger: Callable[[str], None] | None = None) -> None:
    if importlib.util.find_spec("beat_this") is None:
        raise RuntimeError("beat_this is not installed. Install optional dependency and retry.")
    if importlib.util.find_spec("torchaudio") is None:
        raise RuntimeError("torchaudio is not installed. Install torch and torchaudio (or torchaudio wheel with CUDA support).")
    if importlib.util.find_spec("soxr") is None:
        raise RuntimeError("soxr is not installed. Install soxr and retry.")
    if importlib.util.find_spec("rotary_embedding_torch") is None:
        raise RuntimeError("rotary-embedding-torch is not installed. Install it and retry.")
    if importlib.util.find_spec("soundfile") is None:
        if logger is not None:
            logger("soundfile is not installed. beat tracking may still work via fallback, but installation is recommended.")
    if importlib.util.find_spec("torchcodec") is None:
        raise RuntimeError("torchcodec is not installed. Install torchcodec and retry.")
    if importlib.util.find_spec("torch") is None:
        raise RuntimeError("torch is not installed. Install torch and retry.")
    if use_dbn and importlib.util.find_spec("madmom") is None:
        raise RuntimeError("madmom is required when DBN mode is enabled.")
