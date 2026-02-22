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


def command_version(command: str, args: tuple[str, ...] = ("-version",)) -> tuple[str, str] | tuple[None, None]:
    path = shutil.which(command)
    if not path:
        return None, None
    try:
        output = subprocess.check_output([command, *args], stderr=subprocess.STDOUT, text=True, timeout=5)
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
        from app.pipeline.acceleration import get_runtime_acceleration, runtime_public_info

        info = runtime_public_info(get_runtime_acceleration())
        print_item("overall_mode", str(info.get("overall_mode")))
        print_item("ffmpeg_mode", str(info.get("ffmpeg_mode")))
        print_item("opencv_mode", str(info.get("opencv_mode")))
        print_item("gpu_name", str(info.get("gpu_name")))
        print_item("cpu_name", str(info.get("cpu_name")))
        print_item("upscale_available", str(info.get("upscale_available")))
        print_item("upscale_engine_hint", str(info.get("upscale_engine_hint")))
    except Exception as exc:
        print_item("runtime", f"확인 실패: {exc}")


def check_torch() -> None:
    if not has_module("torch"):
        print_item("torch", "설치 안 됨")
        return
    try:
        import torch  # type: ignore

        print_item("torch", f"{torch.__version__}")
        print_item("torch.cuda.is_available", str(torch.cuda.is_available()))
        has_mps = hasattr(torch.backends, "mps")
        print_item("torch.mps.backend", str(has_mps))
        if has_mps:
            print_item("torch.mps.is_built", str(torch.backends.mps.is_built()))
            print_item("torch.mps.is_available", str(torch.backends.mps.is_available()))
    except Exception as exc:
        print_item("torch", f"확인 실패: {exc}")


def main() -> int:
    print("Drum Score Capture Tool - 환경 점검")
    print_item("python", sys.version.split()[0])
    print_item("platform", platform.platform())
    print_item("backend_root", str(BACKEND_ROOT))

    print_section("명령어")
    ffmpeg_path, ffmpeg_ver = command_version("ffmpeg", ("-version",))
    ytdlp_path, ytdlp_ver = command_version("yt-dlp", ("--version",))
    print_item("ffmpeg", f"{ffmpeg_path} | {ffmpeg_ver}" if ffmpeg_path else "없음")
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

    print_section("옵션 모듈 - 오디오 분리")
    uvr_modules = ["demucs", "torch", "torchaudio", "torchcodec"]
    for module in uvr_modules:
        print_item(module, "ok" if has_module(module) else "missing")

    print_section("옵션 모듈 - 비트 분석")
    beat_modules = ["beat_this", "soxr", "rotary_embedding_torch"]
    for module in beat_modules:
        print_item(module, "ok" if has_module(module) else "missing")

    print_section("Torch 장치")
    check_torch()

    print_section("앱 런타임 감지")
    check_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
