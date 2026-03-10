from __future__ import annotations

import io
import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET_DIR = ROOT / "backend" / "bin"


def _copy_binary(source: str, destination_name: str) -> Path:
    source_path = Path(source).resolve()
    destination = TARGET_DIR / destination_name
    if destination.exists():
        destination.chmod(destination.stat().st_mode | stat.S_IWUSR)
        destination.unlink()
    shutil.copy2(source_path, destination)
    mode = destination.stat().st_mode
    destination.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return destination


def _resolve_command(command: str) -> str:
    resolved = shutil.which(command)
    if not resolved:
        _download_runtime_binaries()
        resolved = shutil.which(command)
        if not resolved:
            bundled = TARGET_DIR / command
            if bundled.exists():
                return str(bundled.resolve())
        if not resolved:
            raise RuntimeError(
                f"{command} was not found on PATH and automatic download failed."
            )
    return resolved


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url) as response:
        return response.read()


def _write_from_zip_bytes(payload: bytes, suffix: str, member_suffix: str, output_name: str) -> Path:
    with tempfile.TemporaryDirectory() as td:
        archive_path = Path(td) / suffix
        archive_path.write_bytes(payload)
        with zipfile.ZipFile(archive_path) as zf:
            members = [name for name in zf.namelist() if name.lower().endswith(member_suffix.lower())]
            if not members:
                raise RuntimeError(f"archive does not contain {member_suffix}")
            member = members[0]
            extracted_path = Path(td) / output_name
            extracted_path.write_bytes(zf.read(member))
            return _copy_binary(str(extracted_path), output_name)


def _download_runtime_binaries() -> None:
    system = os.uname().sysname.lower() if hasattr(os, "uname") else ("windows" if os.name == "nt" else "")
    if "darwin" in system:
        _download_macos_arm64_binaries()
        return
    if os.name == "nt" or "windows" in system:
        _download_windows_x64_binaries()
        return
    raise RuntimeError("automatic ffmpeg download is only configured for macOS and Windows packaging")


def _download_macos_arm64_binaries() -> None:
    ffmpeg_zip = _download("https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip")
    ffprobe_zip = _download("https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffprobe.zip")
    _write_from_zip_bytes(ffmpeg_zip, "ffmpeg.zip", "ffmpeg", "ffmpeg")
    _write_from_zip_bytes(ffprobe_zip, "ffprobe.zip", "ffprobe", "ffprobe")


def _download_windows_x64_binaries() -> None:
    payload = _download("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
    with tempfile.TemporaryDirectory() as td:
        archive_path = Path(td) / "ffmpeg-release-essentials.zip"
        archive_path.write_bytes(payload)
        with zipfile.ZipFile(archive_path) as zf:
            ffmpeg_members = [name for name in zf.namelist() if name.lower().endswith("/bin/ffmpeg.exe")]
            ffprobe_members = [name for name in zf.namelist() if name.lower().endswith("/bin/ffprobe.exe")]
            if not ffmpeg_members or not ffprobe_members:
                raise RuntimeError("windows ffmpeg archive does not contain ffmpeg.exe/ffprobe.exe")
            ffmpeg_path = Path(td) / "ffmpeg.exe"
            ffprobe_path = Path(td) / "ffprobe.exe"
            ffmpeg_path.write_bytes(zf.read(ffmpeg_members[0]))
            ffprobe_path.write_bytes(zf.read(ffprobe_members[0]))
            _copy_binary(str(ffmpeg_path), "ffmpeg.exe")
            _copy_binary(str(ffprobe_path), "ffprobe.exe")


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"

    ffmpeg_path = _resolve_command(ffmpeg_name)
    ffprobe_path = _resolve_command(ffprobe_name)

    copied_ffmpeg = _copy_binary(ffmpeg_path, ffmpeg_name)
    copied_ffprobe = _copy_binary(ffprobe_path, ffprobe_name)

    print(f"[stage-runtime-ffmpeg] ffmpeg -> {copied_ffmpeg}")
    print(f"[stage-runtime-ffmpeg] ffprobe -> {copied_ffprobe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
