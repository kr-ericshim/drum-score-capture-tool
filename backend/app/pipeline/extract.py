from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional
import platform

from yt_dlp import YoutubeDL

from app.pipeline.acceleration import get_runtime_acceleration
from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin
from app.schemas import ExtractOptions


def prepare_preview_source(
    *,
    source_type: str,
    file_path: Optional[str],
    youtube_url: Optional[str],
    workspace: Path,
    logger,
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    return _resolve_source_video(
        source_type=source_type,
        file_path=file_path,
        youtube_url=youtube_url,
        workspace=workspace,
        logger=logger,
    )


def extract_frames(
    *,
    source_type: str,
    file_path: Optional[str],
    youtube_url: Optional[str],
    options: ExtractOptions,
    workspace: Path,
    runtime_info: Optional[Dict[str, str]] = None,
    logger,
) -> List[Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    logger("starting frame extraction")
    fps = _resolve_capture_fps(options)
    logger(f"capture sensitivity={options.capture_sensitivity}, sampling fps={fps:.2f}")

    source_video = _resolve_source_video(
        source_type=source_type,
        file_path=file_path,
        youtube_url=youtube_url,
        workspace=workspace,
        logger=logger,
    )
    if runtime_info is not None:
        runtime_info["source_video"] = str(source_video)

    frames_dir = workspace / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    return _extract_with_ffmpeg(
        source_video=source_video,
        out_dir=frames_dir,
        fps=fps,
        start_sec=options.start_sec,
        end_sec=options.end_sec,
        runtime_info=runtime_info,
        logger=logger,
    )


def extract_preview_frame(
    *,
    source_type: str,
    file_path: Optional[str],
    youtube_url: Optional[str],
    start_sec: Optional[float],
    workspace: Path,
    logger,
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    source_video = _resolve_source_video(
        source_type=source_type,
        file_path=file_path,
        youtube_url=youtube_url,
        workspace=workspace,
        logger=logger,
    )
    preview_dir = workspace / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    out_path = preview_dir / "preview_frame.png"
    _extract_single_frame_with_ffmpeg(
        source_video=source_video,
        out_path=out_path,
        sec=start_sec or 0.0,
        logger=logger,
    )
    return out_path


def _resolve_source_video(
    *,
    source_type: str,
    file_path: Optional[str],
    youtube_url: Optional[str],
    workspace: Path,
    logger,
) -> Path:
    if source_type == "file":
        if not file_path:
            raise ValueError("file_path required for file source")
        source_video = Path(file_path)
        if not source_video.exists():
            raise FileNotFoundError(f"input video does not exist: {source_video}")
        return source_video

    if source_type == "youtube":
        if not youtube_url:
            raise ValueError("youtube_url required for youtube source")
        return _download_youtube(youtube_url, workspace=workspace, logger=logger)

    raise ValueError(f"unsupported source_type={source_type}")


def _download_youtube(url: str, workspace: Path, logger) -> Path:
    download_dir = workspace / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(download_dir / "%(id)s.%(ext)s")
    logger(f"downloading youtube source: {url}")
    ydl_opts = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo+bestaudio/best",
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        download_path = Path(path)
        if not download_path.exists():
            raise RuntimeError(f"failed to download youtube source from {url}")
    logger(f"youtube download saved: {download_path}")
    return download_path


def _extract_with_ffmpeg(
    *,
    source_video: Path,
    out_dir: Path,
    fps: float,
    start_sec: Optional[float],
    end_sec: Optional[float],
    runtime_info: Optional[Dict[str, str]],
    logger,
) -> List[Path]:
    ffmpeg = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    accel = get_runtime_acceleration(logger=logger, ffmpeg_bin=ffmpeg)
    hwaccel_flag_sets = accel.ffmpeg_hwaccel_flags or [[]]
    out_pattern = out_dir / "frame_%06d.png"
    attempt_errors: List[str] = []

    for hw_flags in hwaccel_flag_sets:
        _clear_extracted_frames(out_dir)
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *hw_flags,
            "-i",
            str(source_video),
        ]
        if start_sec is not None:
            cmd += ["-ss", str(start_sec)]
        if end_sec is not None:
            cmd += ["-to", str(end_sec)]
        cmd += ["-vf", f"fps={fps}", str(out_pattern)]

        mode = _hwaccel_mode_name(hw_flags)
        logger(f"running ffmpeg extract ({mode})")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        frames = sorted(out_dir.glob("frame_*.png"))
        if result.returncode == 0 and frames:
            logger(f"extracted {len(frames)} frames")
            if runtime_info is not None:
                runtime_info["ffmpeg_mode"] = mode
            return frames

        stderr = result.stderr.strip() if result.stderr else "unknown ffmpeg error"
        attempt_errors.append(f"{mode}: {stderr}")

    joined = " | ".join(attempt_errors[-3:]) if attempt_errors else "no ffmpeg attempts"
    raise RuntimeError(f"ffmpeg failed after gpu/cpu fallback: {joined}")


def _extract_single_frame_with_ffmpeg(
    *,
    source_video: Path,
    out_path: Path,
    sec: float,
    logger,
) -> None:
    ffmpeg = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    accel = get_runtime_acceleration(logger=logger, ffmpeg_bin=ffmpeg)
    hwaccel_flag_sets = accel.ffmpeg_hwaccel_flags or [[]]
    seek_candidates = [max(0.0, sec), max(0.0, sec + 0.8), max(0.0, sec + 1.8)]
    attempt_errors: List[str] = []

    logger("running ffmpeg preview extraction")
    for hw_flags in hwaccel_flag_sets:
        mode = _hwaccel_mode_name(hw_flags)
        for seek_sec in seek_candidates:
            for seek_before_input in (True, False):
                cmd = [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    *hw_flags,
                ]
                if seek_before_input:
                    cmd += ["-ss", str(seek_sec), "-i", str(source_video)]
                else:
                    cmd += ["-i", str(source_video), "-ss", str(seek_sec)]
                cmd += ["-frames:v", "1", str(out_path)]

                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                    return

                stderr = result.stderr.strip() if result.stderr else "unknown ffmpeg error"
                attempt_errors.append(f"{mode} seek={seek_sec:.2f}, preseek={seek_before_input}: {stderr}")
                if out_path.exists():
                    try:
                        out_path.unlink()
                    except OSError:
                        pass

    joined = " | ".join(attempt_errors[-3:])
    raise RuntimeError(f"ffmpeg preview failed after retries: {joined}")


def _clear_extracted_frames(out_dir: Path) -> None:
    for item in out_dir.glob("frame_*.png"):
        try:
            item.unlink()
        except OSError:
            continue


def _hwaccel_mode_name(flags: List[str]) -> str:
    if not flags:
        return "cpu"
    if "-hwaccel" in flags:
        try:
            idx = flags.index("-hwaccel")
            return flags[idx + 1]
        except Exception:
            return "gpu"
    return "gpu"


def _resolve_capture_fps(options: ExtractOptions) -> float:
    if options.fps is not None and options.fps > 0:
        return float(options.fps)

    by_sensitivity = {
        "low": 0.6,
        "medium": 1.0,
        "high": 1.8,
    }
    return float(by_sensitivity.get(options.capture_sensitivity, 1.0))
