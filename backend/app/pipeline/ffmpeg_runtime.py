from __future__ import annotations

import os
import platform
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Callable


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def resolve_ffmpeg_bin(*, strict: bool = False) -> str:
    return _resolve_tool_bin("ffmpeg", "DRUMSHEET_FFMPEG_BIN", strict=strict)


def resolve_ffprobe_bin(*, strict: bool = False) -> str:
    override = _resolve_env_override("ffprobe", "DRUMSHEET_FFPROBE_BIN")
    if override:
        return override

    ffmpeg_bin = resolve_ffmpeg_bin(strict=strict)
    sibling = _resolve_sibling_binary(ffmpeg_bin, "ffprobe")
    if sibling:
        return sibling

    return _resolve_tool_bin("ffprobe", "", strict=strict)


def ensure_runtime_bin_on_path(
    *,
    ffmpeg_bin: str,
    logger: Callable[[str], None] | None = None,
) -> str | None:
    """Ensure ffmpeg directory is on PATH for the current process."""
    if not ffmpeg_bin:
        return None

    try:
        bin_dir = Path(ffmpeg_bin).resolve().parent
    except Exception:
        return None

    if not bin_dir.is_dir():
        return None

    normalized = str(bin_dir.resolve())
    system_name = platform.system().lower()
    sep = ";" if "windows" in system_name else ":"

    current_path = os.environ.get("PATH", "")
    path_parts = [item for item in current_path.split(sep) if item]
    normalized_set = {item.lower() for item in path_parts}
    if system_name == "windows" and normalized.lower() not in normalized_set:
        os.environ["PATH"] = f"{normalized}{sep}{current_path}" if current_path else normalized
        if logger:
            logger(f"runtime PATH updated for Windows DLL search: {normalized}")
    elif system_name != "windows" and normalized not in path_parts:
        os.environ["PATH"] = f"{normalized}{sep}{current_path}" if current_path else normalized
        if logger:
            logger(f"runtime PATH updated: {normalized}")

    if "windows" in system_name:
        add_dll_directory = getattr(os, "add_dll_directory", None)
        if callable(add_dll_directory):
            try:
                add_dll_directory(normalized)
                if logger:
                    logger(f"runtime add_dll_directory configured: {normalized}")
            except OSError:
                pass

    return normalized


@lru_cache(maxsize=None)
def _resolve_tool_bin(tool_name: str, env_key: str, *, strict: bool = False) -> str:
    if env_key:
        override = _resolve_env_override(tool_name, env_key)
        if override:
            override_path = Path(override).expanduser()
            if strict and _looks_like_path(str(override_path)) and not _candidate_is_executable(override_path):
                raise RuntimeError(
                    f"{tool_name} override path not found or not executable: {override_path}. "
                    f"Set DRUMSHEET_{tool_name.upper()}_BIN to a valid absolute path."
                )
            return override

    for candidate in _bundled_candidates(tool_name):
        if candidate.is_file():
            return str(candidate.resolve())

    for command in _command_candidates(tool_name):
        located = shutil.which(command)
        if located:
            return str(Path(located).resolve())

    if strict:
        commands = _command_candidates(tool_name)
        raise RuntimeError(
            f"{tool_name} was not found. Checked candidate paths and PATH commands: {', '.join(commands)}. "
            "Set DRUMSHEET_FFMPEG_BIN / DRUMSHEET_FFPROBE_BIN to an absolute executable path and restart."
        )
    return _command_candidates(tool_name)[0]


def _candidate_is_executable(candidate: Path) -> bool:
    if not candidate.is_file():
        return False
    return True


def _resolve_env_override(tool_name: str, env_key: str) -> str:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return ""

    if _looks_like_path(raw):
        env_path = Path(raw).expanduser()
        path_candidates = [env_path] if env_path.is_absolute() else [BACKEND_ROOT / env_path, Path.cwd() / env_path]
        for candidate in path_candidates:
            normalized = _normalize_candidate_path(candidate, tool_name)
            if normalized is not None:
                return str(normalized.resolve())
        return str((path_candidates[0]).resolve())

    located = shutil.which(raw)
    if located:
        return str(Path(located).resolve())
    return raw


def _resolve_sibling_binary(command: str, tool_name: str) -> str:
    if not command:
        return ""
    if not _looks_like_path(command):
        return ""

    command_path = Path(command).expanduser()
    if not command_path.is_absolute():
        command_path = (BACKEND_ROOT / command_path).resolve()
    parent = command_path.parent

    for candidate in (
        parent / _binary_filename(tool_name),
        parent / tool_name,
        parent / f"{tool_name}.exe",
        parent.parent / _binary_filename(tool_name),
    ):
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def _bundled_candidates(tool_name: str) -> list[Path]:
    filename = _binary_filename(tool_name)
    rel_paths = [
        Path("bin") / filename,
        Path("bin") / tool_name / filename,
        Path("bin") / "ffmpeg" / filename,
        Path("ffmpeg") / filename,
        Path("ffmpeg") / "bin" / filename,
        Path("tools") / "ffmpeg" / filename,
        Path("tools") / "ffmpeg" / "bin" / filename,
        Path("third_party") / "ffmpeg" / filename,
        Path("third_party") / "ffmpeg" / "bin" / filename,
        Path("vendor") / "ffmpeg" / filename,
        Path("vendor") / "ffmpeg" / "bin" / filename,
    ]
    candidates: list[Path] = []
    seen: set[str] = set()
    for rel in rel_paths:
        path = (BACKEND_ROOT / rel).resolve()
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(path)
    return candidates


def _normalize_candidate_path(path: Path, tool_name: str) -> Path | None:
    if path.is_dir():
        path = path / _binary_filename(tool_name)
    if path.is_file():
        return path

    if platform.system().lower() == "windows" and path.suffix.lower() != ".exe":
        win_path = path.with_suffix(".exe")
        if win_path.is_file():
            return win_path
    return None


def _binary_filename(tool_name: str) -> str:
    if platform.system().lower() == "windows":
        return f"{tool_name}.exe"
    return tool_name


def _command_candidates(tool_name: str) -> list[str]:
    if platform.system().lower() == "windows":
        return [f"{tool_name}.exe", tool_name]
    return [tool_name]


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    return any(sep in value for sep in ("/", "\\")) or value.startswith(".")
