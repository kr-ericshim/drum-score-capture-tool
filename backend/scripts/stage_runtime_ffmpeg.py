from __future__ import annotations

import os
import shutil
import stat
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
        raise RuntimeError(
            f"{command} was not found on PATH. Install ffmpeg on the build machine before packaging."
        )
    return resolved


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
