from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time
import platform
from pathlib import Path
from typing import Dict

from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin, resolve_ffprobe_bin
from app.pipeline.torch_runtime import (
    inspect_torch_runtime,
    select_torch_device,
    torch_runtime_summary,
    torch_gpu_error_hint,
)
from app.schemas import AudioSeparationOptions


def separate_audio_stem(
    *,
    source_video: Path,
    options: AudioSeparationOptions,
    workspace: Path,
    logger,
) -> Dict[str, object]:
    if not options.enable:
        return {}

    start_time = time.perf_counter()
    logger("audio separation stage: verify dependencies")
    _ensure_audio_stack_installed()
    logger("audio separation dependencies: demucs/torch/torchcodec ready")

    workspace.mkdir(parents=True, exist_ok=True)
    logger(f"audio separation workspace: {workspace}")
    ffmpeg_bin = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    ffprobe_bin = resolve_ffprobe_bin()
    logger(f"audio separation binaries: ffmpeg={ffmpeg_bin}, ffprobe={ffprobe_bin}")
    audio_input = workspace / "source_audio.wav"
    logger("audio separation stage: extract audio track (ffmpeg)")
    extract_started = time.perf_counter()
    _extract_audio_track(source_video=source_video, audio_output=audio_input, ffmpeg_bin=ffmpeg_bin)
    extract_elapsed = time.perf_counter() - extract_started
    file_size_mb = float(audio_input.stat().st_size) / (1024.0 * 1024.0) if audio_input.exists() else 0.0
    duration_sec = _probe_duration_seconds(audio_input, ffprobe_bin=ffprobe_bin)
    if duration_sec is not None:
        logger(f"audio extraction finished: duration={duration_sec:.1f}s, size={file_size_mb:.1f}MB, elapsed={extract_elapsed:.1f}s")
    else:
        logger(f"audio extraction finished: size={file_size_mb:.1f}MB, elapsed={extract_elapsed:.1f}s")
    logger("audio separation input prepared")

    torch_info = inspect_torch_runtime()
    device = select_torch_device(torch_info)
    logger(f"audio separation torch runtime: {torch_runtime_summary(torch_info)}")
    if options.gpu_only and device == "cpu":
        raise RuntimeError(torch_gpu_error_hint(torch_info, task_name="Audio separation"))

    logger(f"audio separation engine={options.engine}, model={options.model}, stem={options.stem}, device={device}")
    demucs_output_root = workspace / "demucs_output"
    demucs_output_root.mkdir(parents=True, exist_ok=True)

    logger("audio separation stage: run demucs inference (this may take a while)")
    demucs_started = time.perf_counter()
    _run_demucs(
        source_audio=audio_input,
        output_root=demucs_output_root,
        model=options.model,
        device=device,
        logger=logger,
    )
    logger(f"demucs inference finished in {time.perf_counter() - demucs_started:.1f}s")

    logger("audio separation stage: collect separated stems")
    stem_sources = _collect_stem_files(
        output_root=demucs_output_root,
        model=options.model,
        track_name=audio_input.stem,
    )
    if not stem_sources:
        raise RuntimeError("Separated stems were not generated.")
    logger(f"audio stems detected: {', '.join(sorted(stem_sources.keys()))}")

    logger("audio separation stage: export stem files")
    exported_stems: Dict[str, str] = {}
    for stem_name, stem_src in stem_sources.items():
        stem_out = workspace / f"{stem_name}.{options.output_format}"
        if options.output_format == "wav":
            shutil.copy2(stem_src, stem_out)
        else:
            _transcode_audio(src=stem_src, dst=stem_out, fmt=options.output_format, ffmpeg_bin=ffmpeg_bin)
        exported_stems[stem_name] = str(stem_out)
        stem_size_mb = float(stem_out.stat().st_size) / (1024.0 * 1024.0) if stem_out.exists() else 0.0
        logger(f"audio stem saved: {stem_name} -> {stem_out.name} ({stem_size_mb:.1f}MB)")

    primary_stem = exported_stems.get(options.stem) or next(iter(exported_stems.values()))
    logger(f"audio primary stem selected: {Path(primary_stem).name}")
    logger(f"audio separation total elapsed: {time.perf_counter() - start_time:.1f}s")
    logger(f"audio stems exported: {', '.join(sorted(exported_stems.keys()))}")
    return {
        "audio_stem": str(primary_stem),
        "audio_stems": exported_stems,
        "audio_engine": options.engine,
        "audio_model": options.model,
        "audio_device": device,
    }


def _extract_audio_track(*, source_video: Path, audio_output: Path, ffmpeg_bin: str) -> None:
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


def _run_demucs(
    *,
    source_audio: Path,
    output_root: Path,
    model: str,
    device: str,
    logger,
) -> None:
    python_bin = _resolve_python_bin()
    cmd = [
        python_bin,
        "-m",
        "demucs.separate",
        "-n",
        model,
        "--device",
        device,
        "-o",
        str(output_root),
        str(source_audio),
    ]
    logger(f"demucs process started: model={model}, device={device}")
    result = _run_process_with_live_logs(cmd, logger=logger)
    if result["returncode"] == 0:
        logger("demucs process completed")
        return

    combined = result["combined"].strip()
    if "No module named demucs" in combined:
        raise RuntimeError("demucs is not installed. Install optional dependency and retry.")
    if "No module named torchcodec" in combined or "TorchCodec is required for save_with_torchcodec" in combined:
        raise RuntimeError("torchcodec is not installed. Install torchcodec and retry: pip install torchcodec")
    raise RuntimeError(f"Demucs separation failed: {_trim_error_log(combined) or 'unknown error'}")


def _collect_stem_files(*, output_root: Path, model: str, track_name: str) -> Dict[str, Path]:
    track_dir = output_root / model / track_name
    if track_dir.exists():
        candidates = sorted(track_dir.glob("*.wav"))
    else:
        candidates = sorted(output_root.glob("**/*.wav"))

    stems: Dict[str, Path] = {}
    for path in candidates:
        stem_name = path.stem.strip().lower()
        if not stem_name:
            continue
        stems[stem_name] = path
    return stems


def _transcode_audio(*, src: Path, dst: Path, fmt: str, ffmpeg_bin: str) -> None:
    if fmt == "wav":
        shutil.copy2(src, dst)
        return
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(dst),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not dst.exists() or dst.stat().st_size <= 0:
        stderr = result.stderr.strip() if result.stderr else "unknown ffmpeg error"
        raise RuntimeError(f"Failed to convert separated stem to {fmt}: {stderr}")


def _resolve_python_bin() -> str:
    override = os.getenv("DRUMSHEET_AUDIO_PYTHON_BIN", "").strip()
    if override:
        return override
    value = (sys.executable or "").strip()
    if value:
        # Keep the original executable path (often .venv/bin/python symlink).
        # Resolving symlinks can drop virtualenv context and lose installed modules.
        return value
    return "python3"


def _ensure_audio_stack_installed() -> None:
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError("demucs is not installed. Install optional dependency and retry: pip install -r requirements-uvr.txt")
    if importlib.util.find_spec("torch") is None:
        raise RuntimeError("torch is not installed. Install torch for demucs and retry.")
    if importlib.util.find_spec("torchcodec") is None:
        raise RuntimeError("torchcodec is not installed. Install torchcodec and retry: pip install torchcodec")


def _trim_error_log(text: str, *, max_lines: int = 40, max_chars: int = 4000) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    lines = value.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    compact = "\n".join(lines).strip()
    if len(compact) > max_chars:
        compact = compact[-max_chars:]
    return compact


def _probe_duration_seconds(path: Path, *, ffprobe_bin: str) -> float | None:
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        value = float((result.stdout or "").strip())
        if value > 0:
            return value
    except Exception:
        return None
    return None


def _run_process_with_live_logs(cmd: list[str], *, logger) -> Dict[str, object]:
    lines: list[str] = []
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    emitted_progress = 0
    if proc.stdout is not None:
        for raw in proc.stdout:
            line = _normalize_cli_line(raw)
            if not line:
                continue
            lines.append(line)
            lower = line.lower()
            is_progress = "%" in line and "|" in line
            if is_progress:
                emitted_progress += 1
                if "100%" in line or emitted_progress % 8 == 0:
                    logger(f"demucs: {line}")
                continue
            if any(token in lower for token in ("model", "load", "saving", "saved", "writing", "separat", "device", "error", "warning")):
                logger(f"demucs: {line}")
    returncode = proc.wait()
    return {
        "returncode": int(returncode),
        "combined": "\n".join(lines[-220:]),
    }


def _normalize_cli_line(raw: str) -> str:
    line = str(raw or "").replace("\r", " ").strip()
    if not line:
        return ""
    if len(line) > 320:
        return line[:320]
    return line
