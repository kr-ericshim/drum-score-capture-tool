#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
import tempfile
import wave
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
        from app.pipeline.torch_runtime import inspect_torch_runtime, select_torch_device, torch_runtime_summary

        ffmpeg_bin = resolve_ffmpeg_bin()
        info = runtime_public_info(get_runtime_acceleration(ffmpeg_bin=ffmpeg_bin))
        torch_info = inspect_torch_runtime()
        print_item("overall_mode", str(info.get("overall_mode")))
        print_item("ffmpeg_mode", str(info.get("ffmpeg_mode")))
        print_item("opencv_mode", str(info.get("opencv_mode")))
        print_item("gpu_name", str(info.get("gpu_name")))
        print_item("cpu_name", str(info.get("cpu_name")))
        print_item("upscale_available", str(info.get("upscale_available")))
        print_item("upscale_engine_hint", str(info.get("upscale_engine_hint")))
        print_item("audio_gpu_mode(torch)", select_torch_device(torch_info))
        print_item("audio_gpu_ready(torch)", str(bool(torch_info.get("gpu_ready", False))))
        print_item("audio_torch_summary", torch_runtime_summary(torch_info))
    except Exception as exc:
        print_item("runtime", f"확인 실패: {exc}")


def check_torch() -> None:
    if not has_module("torch"):
        print_item("torch", "설치 안 됨")
        return
    try:
        import torch  # type: ignore

        print_item("torch", f"{torch.__version__}")
        print_item("python.executable", sys.executable)
        print_item("torch.version.cuda", str(getattr(torch.version, "cuda", None)))
        print_item("torch.cuda.is_available", str(torch.cuda.is_available()))
        try:
            gpu_count = int(torch.cuda.device_count())
        except Exception:
            gpu_count = 0
        print_item("torch.cuda.device_count", str(gpu_count))
        if gpu_count > 0:
            try:
                print_item("torch.cuda.device_name[0]", str(torch.cuda.get_device_name(0)))
            except Exception as exc:
                print_item("torch.cuda.device_name[0]", f"확인 실패: {exc}")
        has_mps = hasattr(torch.backends, "mps")
        print_item("torch.mps.backend", str(has_mps))
        if has_mps:
            print_item("torch.mps.is_built", str(torch.backends.mps.is_built()))
            print_item("torch.mps.is_available", str(torch.backends.mps.is_available()))
    except Exception as exc:
        print_item("torch", f"확인 실패: {exc}")


def check_torchaudio_smoke() -> None:
    if not has_module("torchaudio"):
        print_item("torchaudio.load", "missing")
        return
    if not has_module("torch"):
        print_item("torchaudio.load", "torch missing")
        return
    if not has_module("numpy"):
        print_item("torchaudio.load", "numpy missing")
        return

    tmp_path: Path | None = None
    try:
        import numpy as np
        import torchaudio  # type: ignore
        sample_rate = 16000
        duration_sec = 1.0
        t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
        tone = (0.2 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            tmp_path = Path(temp_file.name)

        with wave.open(str(tmp_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(tone.tobytes())

        waveform, sr = torchaudio.load(str(tmp_path))
        if int(sr) != sample_rate or getattr(waveform, "numel", lambda: 0)() <= 0:
            print_item("torchaudio.load", f"failed: invalid output sr={sr}, samples={getattr(waveform, 'numel', lambda: 0)()}")
            return
        print_item("torchaudio.load", "ok")
    except Exception as exc:
        print_item("torchaudio.load", f"failed: {exc}")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


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

    print_section("옵션 모듈 - 오디오 분리")
    uvr_modules = ["demucs", "torch", "torchaudio", "torchcodec"]
    for module in uvr_modules:
        print_item(module, "ok" if has_module(module) else "missing")

    print_section("Torch 장치")
    check_torch()
    check_torchaudio_smoke()

    print_section("앱 런타임 감지")
    check_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
