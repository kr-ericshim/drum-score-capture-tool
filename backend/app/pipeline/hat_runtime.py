from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class HatRuntime:
    enabled: bool
    available: bool
    reason: str
    repo_path: Optional[Path]
    option_template_path: Optional[Path]
    weights_path: Optional[Path]
    torch_device: str
    run_device: str
    allow_cpu: bool
    tile_size: int
    tile_pad: int
    python_bin: str


_HAT_CACHE: Optional[HatRuntime] = None
_LOCK = threading.Lock()


def get_hat_runtime(*, force_refresh: bool = False) -> HatRuntime:
    global _HAT_CACHE
    with _LOCK:
        if force_refresh or _HAT_CACHE is None:
            _HAT_CACHE = _detect_hat_runtime()
        return _HAT_CACHE


def _detect_hat_runtime() -> HatRuntime:
    engine_pref = _upscale_engine_pref()
    enabled = _env_bool("DRUMSHEET_HAT_ENABLE", default=False) or engine_pref == "hat"
    allow_cpu = _env_bool("DRUMSHEET_HAT_ALLOW_CPU", default=False)
    tile_size = _env_int("DRUMSHEET_HAT_TILE_SIZE", default=512, minimum=64)
    tile_pad = _env_int("DRUMSHEET_HAT_TILE_PAD", default=32, minimum=0)
    python_bin = (os.getenv("DRUMSHEET_HAT_PYTHON_BIN", "").strip() or sys.executable or "python3").strip()

    if not enabled:
        return HatRuntime(
            enabled=False,
            available=False,
            reason="disabled",
            repo_path=None,
            option_template_path=None,
            weights_path=None,
            torch_device="none",
            run_device="none",
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    repo_raw = os.getenv("DRUMSHEET_HAT_REPO", "").strip()
    weights_raw = os.getenv("DRUMSHEET_HAT_WEIGHTS", "").strip()
    template_raw = os.getenv("DRUMSHEET_HAT_OPT_TEMPLATE", "options/test/HAT_SRx4_ImageNet-LR.yml").strip()

    if not repo_raw:
        return HatRuntime(
            enabled=True,
            available=False,
            reason="missing_repo",
            repo_path=None,
            option_template_path=None,
            weights_path=None,
            torch_device="none",
            run_device="none",
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    repo_path = Path(repo_raw).expanduser()
    if not repo_path.exists():
        return HatRuntime(
            enabled=True,
            available=False,
            reason="repo_not_found",
            repo_path=repo_path,
            option_template_path=None,
            weights_path=None,
            torch_device="none",
            run_device="none",
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    test_script = repo_path / "hat" / "test.py"
    if not test_script.exists():
        return HatRuntime(
            enabled=True,
            available=False,
            reason="missing_hat_test_py",
            repo_path=repo_path,
            option_template_path=None,
            weights_path=None,
            torch_device="none",
            run_device="none",
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    if not weights_raw:
        return HatRuntime(
            enabled=True,
            available=False,
            reason="missing_weights",
            repo_path=repo_path,
            option_template_path=None,
            weights_path=None,
            torch_device="none",
            run_device="none",
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    weights_path = Path(weights_raw).expanduser()
    if not weights_path.exists():
        return HatRuntime(
            enabled=True,
            available=False,
            reason="weights_not_found",
            repo_path=repo_path,
            option_template_path=None,
            weights_path=weights_path,
            torch_device="none",
            run_device="none",
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    template_path = Path(template_raw).expanduser()
    if not template_path.is_absolute():
        template_path = repo_path / template_path
    if not template_path.exists():
        return HatRuntime(
            enabled=True,
            available=False,
            reason="option_template_not_found",
            repo_path=repo_path,
            option_template_path=template_path,
            weights_path=weights_path,
            torch_device="none",
            run_device="none",
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    torch_device = _detect_torch_device()
    if torch_device in {"cuda", "mps"}:
        run_device = torch_device
    else:
        run_device = "cpu"

    if torch_device == "none":
        return HatRuntime(
            enabled=True,
            available=False,
            reason="torch_missing",
            repo_path=repo_path,
            option_template_path=template_path,
            weights_path=weights_path,
            torch_device=torch_device,
            run_device=run_device,
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    if run_device == "cpu" and not allow_cpu:
        return HatRuntime(
            enabled=True,
            available=False,
            reason="cpu_only_disallowed",
            repo_path=repo_path,
            option_template_path=template_path,
            weights_path=weights_path,
            torch_device=torch_device,
            run_device=run_device,
            allow_cpu=allow_cpu,
            tile_size=tile_size,
            tile_pad=tile_pad,
            python_bin=python_bin,
        )

    return HatRuntime(
        enabled=True,
        available=True,
        reason="ok",
        repo_path=repo_path,
        option_template_path=template_path,
        weights_path=weights_path,
        torch_device=torch_device,
        run_device=run_device,
        allow_cpu=allow_cpu,
        tile_size=tile_size,
        tile_pad=tile_pad,
        python_bin=python_bin,
    )


def _detect_torch_device() -> str:
    try:
        import torch  # type: ignore
    except Exception:
        return "none"

    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass

    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass

    return "cpu"


def _upscale_engine_pref() -> str:
    value = os.getenv("DRUMSHEET_UPSCALE_ENGINE", "auto").strip().lower()
    if value in {"hat", "opencv", "ffmpeg"}:
        return value
    return "auto"


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, *, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
        if value < minimum:
            return default
        return value
    except Exception:
        return default
