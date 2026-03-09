from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
RUNTIME_DIR = BACKEND_DIR / "runtime"
BUILD_DIR = ROOT / ".tmp" / "pyinstaller-build"
SPEC_DIR = BUILD_DIR / "spec"
WORK_DIR = BUILD_DIR / "work"


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
        "--additional-hooks-dir",
        str(BACKEND_DIR / "pyinstaller_hooks"),
    ]

    print("[build_frozen_backend] running:", " ".join(command))
    subprocess.run(command, check=True, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
