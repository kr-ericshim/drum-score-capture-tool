from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional
import platform

from yt_dlp import YoutubeDL

from app.pipeline.acceleration import get_runtime_acceleration
from app.pipeline.ffmpeg_runtime import ensure_runtime_bin_on_path, resolve_ffmpeg_bin, resolve_ffprobe_bin
from app.schemas import ExtractOptions

YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "yt-v3"
YOUTUBE_LOW_QUALITY_HEIGHT_THRESHOLD = 360


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
    ffmpeg_bin = resolve_ffmpeg_bin(strict=False)
    ffmpeg_location = ""
    if ffmpeg_bin:
        ffmpeg_candidate = Path(ffmpeg_bin).expanduser()
        if ffmpeg_candidate.is_file():
            ensure_runtime_bin_on_path(ffmpeg_bin=str(ffmpeg_candidate), logger=logger)
            ffmpeg_location = str(ffmpeg_candidate)

    base_opts = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": False,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 2,
        "logger": _YtDlpLogBridge(logger),
    }
    if ffmpeg_location:
        base_opts["ffmpeg_location"] = ffmpeg_location

    attempts = [
        (
            "default-best",
            {
                "format": "bestvideo+bestaudio/best",
            },
        ),
        (
            "default-mp4",
            {
                "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            },
        ),
    ]
    errors: List[str] = []
    for name, extra_opts in attempts:
        ydl_opts = {**base_opts, **extra_opts}
        try:
            _clear_download_artifacts(download_dir)
            logger(f"youtube download strategy={name}")
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                download_path = _resolve_download_path(download_dir=download_dir, ydl=ydl, info=info)
                if not download_path.exists():
                    raise RuntimeError(f"failed to download youtube source from {url}")
            selected_width, selected_height = _selected_format_resolution(info)
            probe_width, probe_height = _probe_download_resolution(download_path)
            width = probe_width or selected_width
            height = probe_height or selected_height
            logger(
                f"youtube download selected={_selected_format_summary(info)} actual={width}x{height} strategy={name}"
            )
            if _is_low_quality_video(width=width, height=height):
                logger(
                    f"youtube download rejected: {download_path.name} resolved to {width}x{height}; retrying next strategy"
                )
                errors.append(f"{name}: low resolution {width}x{height}")
                _clear_download_artifacts(download_dir)
                continue
            logger(f"youtube download saved: {download_path}")
            return download_path
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger(f"youtube download strategy failed: {name}: {exc}")
    raise RuntimeError(f"failed to download youtube source from {url}: {' | '.join(errors)}")


class _YtDlpLogBridge:
    def __init__(self, logger) -> None:
        self._logger = logger

    def debug(self, msg) -> None:
        self._emit(msg)

    def warning(self, msg) -> None:
        self._emit(msg)

    def error(self, msg) -> None:
        self._emit(msg)

    def _emit(self, msg) -> None:
        text = str(msg or "").strip()
        if not text:
            return
        if text.startswith("[debug]"):
            return
        self._logger(f"yt-dlp: {text}")


def _clear_download_artifacts(download_dir: Path) -> None:
    for file_path in download_dir.glob("*"):
        if not file_path.is_file():
            continue
        try:
            file_path.unlink()
        except OSError:
            continue


def _resolve_download_path(*, download_dir: Path, ydl: YoutubeDL, info: Dict[str, object]) -> Path:
    prepared = Path(ydl.prepare_filename(info))
    if prepared.exists():
        return prepared

    video_id = str(info.get("id") or "").strip()
    candidates: List[Path] = []
    if video_id:
        candidates.extend(sorted(download_dir.glob(f"{video_id}.*"), key=_download_sort_key, reverse=True))
    if not candidates:
        candidates.extend(sorted([p for p in download_dir.iterdir() if p.is_file()], key=_download_sort_key, reverse=True))
    return candidates[0] if candidates else prepared


def _download_sort_key(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _selected_format_summary(info: Dict[str, object]) -> str:
    requested = info.get("requested_formats")
    if isinstance(requested, list) and requested:
        format_ids = [
            str(fmt.get("format_id") or "?")
            for fmt in requested
            if isinstance(fmt, dict)
        ]
        ext = str(info.get("ext") or "").strip()
        width, height = _selected_format_resolution(info)
        detail = f"{'+'.join(format_ids)} {width}x{height}".strip()
        return f"{detail} {ext}".strip()

    format_id = str(info.get("format_id") or "unknown").strip()
    ext = str(info.get("ext") or "").strip()
    width, height = _selected_format_resolution(info)
    detail = f"{format_id} {width}x{height}".strip()
    return f"{detail} {ext}".strip()


def _selected_format_resolution(info: Dict[str, object]) -> tuple[int, int]:
    requested = info.get("requested_formats")
    if isinstance(requested, list) and requested:
        widths = [int(fmt.get("width") or 0) for fmt in requested if isinstance(fmt, dict)]
        heights = [int(fmt.get("height") or 0) for fmt in requested if isinstance(fmt, dict)]
        return (max(widths or [0]), max(heights or [0]))
    return (int(info.get("width") or 0), int(info.get("height") or 0))


def _probe_download_resolution(path: Path) -> tuple[int, int]:
    try:
        ffprobe = resolve_ffprobe_bin(strict=False)
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except (OSError, RuntimeError, ValueError):
        return (0, 0)

    if completed.returncode != 0:
        return (0, 0)

    raw = str(completed.stdout or "").strip().splitlines()
    if not raw:
        return (0, 0)
    parts = [segment.strip() for segment in raw[0].split("x", maxsplit=1)]
    if len(parts) != 2:
        return (0, 0)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (0, 0)


def _is_low_quality_video(*, width: int, height: int) -> bool:
    if height > 0:
        return height <= YOUTUBE_LOW_QUALITY_HEIGHT_THRESHOLD
    if width > 0:
        return width <= 640
    return False


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
    # Single-frame preview extraction is more fragile on Windows than the main
    # capture path. Favor CPU decode here to avoid driver/hwaccel-specific
    # failures when opening the ROI setup screen.
    if platform.system().lower() == "windows":
        hwaccel_flag_sets = [[]]
    else:
        accel = get_runtime_acceleration(logger=logger, ffmpeg_bin=ffmpeg)
        hwaccel_flag_sets = accel.ffmpeg_hwaccel_flags or [[]]
    seek_candidates = _preview_seek_candidates(sec)
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

    # Some packaged Windows builds can decode the video overall but fail on direct
    # single-frame seeks near the beginning. Fall back to ffmpeg's thumbnail scan
    # so ROI setup still opens with a representative frame.
    logger("running ffmpeg preview thumbnail fallback")
    thumbnail_start = max(0.0, sec)
    thumbnail_window = 12.0
    thumb_cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(thumbnail_start),
        "-i",
        str(source_video),
        "-t",
        str(thumbnail_window),
        "-vf",
        "thumbnail=90",
        "-frames:v",
        "1",
        str(out_path),
    ]
    thumb_result = subprocess.run(thumb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if thumb_result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
        return

    thumb_stderr = thumb_result.stderr.strip() if thumb_result.stderr else "unknown ffmpeg error"
    attempt_errors.append(f"thumbnail fallback: {thumb_stderr}")
    if out_path.exists():
        try:
            out_path.unlink()
        except OSError:
            pass

    joined = " | ".join(attempt_errors[-3:])
    raise RuntimeError(f"ffmpeg preview failed after retries: {joined}")


def _preview_seek_candidates(sec: float) -> List[float]:
    base = max(0.0, float(sec or 0.0))
    raw_candidates = [
        base,
        base + 0.8,
        base + 1.8,
        base + 3.5,
        base + 6.0,
    ]
    if base >= 1.5:
        raw_candidates.extend([max(0.0, base - 1.0), max(0.0, base - 3.0)])

    ordered: List[float] = []
    seen: set[float] = set()
    for candidate in raw_candidates:
        normalized = round(max(0.0, candidate), 2)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


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
