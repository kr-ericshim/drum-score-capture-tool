#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def resolve_command_path(command: str) -> str | None:
    value = str(command or "").strip()
    if not value:
        return None

    candidate = Path(value).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    if candidate.is_absolute():
        if candidate.suffix.lower() != ".exe":
            win_candidate = candidate.with_suffix(".exe")
            if win_candidate.is_file():
                return str(win_candidate.resolve())
        return None

    located = shutil.which(value)
    if located:
        return str(Path(located).resolve())
    return None


def command_version(command: str, args: tuple[str, ...] = ("-version",)) -> tuple[str, str] | tuple[None, None]:
    path = resolve_command_path(command)
    if not path:
        return None, None
    try:
        output = subprocess.check_output([path, *args], stderr=subprocess.STDOUT, text=True, timeout=5)
        first_line = output.strip().splitlines()[0] if output else "version output not found"
        return path, first_line
    except Exception as exc:
        return path, f"version check failed: {exc}"


def print_section(title: str) -> None:
    print(f"\n== {title} ==")


def print_item(name: str, value: str) -> None:
    print(f"- {name}: {value}")


def check_runtime() -> None:
    try:
        from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin
        from app.pipeline.acceleration import get_runtime_acceleration, runtime_public_info

        ffmpeg_bin = resolve_ffmpeg_bin()
        info = runtime_public_info(get_runtime_acceleration(ffmpeg_bin=ffmpeg_bin))
        print_item("overall_mode", str(info.get("overall_mode")))
        print_item("ffmpeg_mode", str(info.get("ffmpeg_mode")))
        print_item("opencv_mode", str(info.get("opencv_mode")))
        print_item("gpu_name", str(info.get("gpu_name")))
        print_item("cpu_name", str(info.get("cpu_name")))
        print_item("upscale_available", str(info.get("upscale_available")))
        print_item("upscale_engine_hint", str(info.get("upscale_engine_hint")))
    except Exception as exc:
        print_item("runtime", f"확인 실패: {exc}")


def main() -> int:
    print("Drum Score Capture Tool - 환경 점검")
    print_item("python", sys.version.split()[0])
    print_item("platform", platform.platform())
    print_item("backend_root", str(BACKEND_ROOT))

    print_section("명령어")
    from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin, resolve_ffprobe_bin

    ffmpeg_cmd = resolve_ffmpeg_bin()
    ffprobe_cmd = resolve_ffprobe_bin()
    ffmpeg_path, ffmpeg_ver = command_version(ffmpeg_cmd, ("-version",))
    ffprobe_path, ffprobe_ver = command_version(ffprobe_cmd, ("-version",))
    ytdlp_path, ytdlp_ver = command_version("yt-dlp", ("--version",))
    print_item("ffmpeg_resolved", ffmpeg_cmd)
    print_item("ffmpeg", f"{ffmpeg_path} | {ffmpeg_ver}" if ffmpeg_path else "없음")
    print_item("ffprobe_resolved", ffprobe_cmd)
    print_item("ffprobe", f"{ffprobe_path} | {ffprobe_ver}" if ffprobe_path else "없음")
    print_item("yt-dlp", f"{ytdlp_path} | {ytdlp_ver}" if ytdlp_path else "없음")

    print_section("필수 파이썬 모듈")
    required_modules = [
        "fastapi",
        "uvicorn",
        "numpy",
        "cv2",
        "PIL",
        "pydantic",
        "yt_dlp",
    ]
    for module in required_modules:
        print_item(module, "ok" if has_module(module) else "missing")

    print_section("앱 런타임 감지")
    check_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
