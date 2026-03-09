from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
RUNTIME_DIR = BACKEND_DIR / "runtime"
BUILD_DIR = ROOT / ".tmp" / "pyinstaller-build"
SPEC_DIR = BUILD_DIR / "spec"
WORK_DIR = BUILD_DIR / "work"


def build_pyinstaller_resource_flags() -> list[str]:
    hiddenimports = set()
    datas = []
    binaries = []

    for package in (
        "yt_dlp",
        "yt_dlp.extractor",
        "yt_dlp.downloader",
        "yt_dlp.networking",
        "yt_dlp.postprocessor",
        "curl_cffi",
        "requests",
        "urllib3",
        "websockets",
        "mutagen",
    ):
        try:
            hiddenimports.update(collect_submodules(package))
        except Exception:
            continue

    for package in ("yt_dlp", "curl_cffi", "certifi"):
        try:
            datas.extend(collect_data_files(package))
        except Exception:
            continue
        try:
            datas.extend(copy_metadata(package))
        except Exception:
            continue

    for package in ("curl_cffi",):
        try:
            binaries.extend(collect_dynamic_libs(package))
        except Exception:
            continue

    flags: list[str] = []
    for module_name in sorted(hiddenimports):
        flags.extend(["--hidden-import", module_name])
    for src, dest in sorted(set(datas)):
        flags.extend(["--add-data", f"{src}:{dest}"])
    for src, dest in sorted(set(binaries)):
        flags.extend(["--add-binary", f"{src}:{dest}"])
    return flags


def main() -> int:
    if RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(BACKEND_DIR / "run.py"),
        "--name",
        "drumsheet-backend",
        "--onedir",
        "--clean",
        "--distpath",
        str(RUNTIME_DIR),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
        "--paths",
        str(BACKEND_DIR),
        *build_pyinstaller_resource_flags(),
    ]

    print("[build_frozen_backend] running:", " ".join(command))
    subprocess.run(command, check=True, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
