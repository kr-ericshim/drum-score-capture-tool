from __future__ import annotations

import platform
import sys
from typing import Dict, Optional


def inspect_torch_runtime() -> Dict[str, object]:
    info: Dict[str, object] = {
        "torch_available": False,
        "torch_import_error": None,
        "torch_version": None,
        "python_executable": (sys.executable or "").strip() or None,
        "platform": platform.platform(),
        "cuda_available": False,
        "cuda_version": None,
        "cuda_device_count": 0,
        "cuda_device_name": None,
        "mps_built": False,
        "mps_available": False,
        "recommended_device": "cpu",
        "gpu_ready": False,
        "gpu_reason": "torch_missing",
    }

    try:
        import torch  # type: ignore
    except Exception as exc:
        info["torch_import_error"] = str(exc)
        return info

    info["torch_available"] = True
    info["torch_version"] = str(getattr(torch, "__version__", "unknown"))
    info["cuda_version"] = _str_or_none(getattr(getattr(torch, "version", None), "cuda", None))

    cuda_available = False
    try:
        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False
    info["cuda_available"] = cuda_available

    cuda_device_count = 0
    try:
        cuda_device_count = int(torch.cuda.device_count())
    except Exception:
        cuda_device_count = 0
    info["cuda_device_count"] = max(0, cuda_device_count)

    if cuda_device_count > 0:
        try:
            info["cuda_device_name"] = _str_or_none(torch.cuda.get_device_name(0))
        except Exception:
            info["cuda_device_name"] = None

    mps_built = False
    mps_available = False
    try:
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is not None:
            try:
                mps_built = bool(mps_backend.is_built())
            except Exception:
                mps_built = False
            try:
                mps_available = bool(mps_backend.is_available())
            except Exception:
                mps_available = False
    except Exception:
        mps_built = False
        mps_available = False

    info["mps_built"] = mps_built
    info["mps_available"] = mps_available

    if cuda_available and cuda_device_count > 0:
        info["recommended_device"] = "cuda"
        info["gpu_ready"] = True
        info["gpu_reason"] = "cuda_ready"
        return info

    if mps_available:
        info["recommended_device"] = "mps"
        info["gpu_ready"] = True
        info["gpu_reason"] = "mps_ready"
        return info

    info["recommended_device"] = "cpu"
    info["gpu_ready"] = False
    info["gpu_reason"] = _gpu_unavailable_reason(info)
    return info


def select_torch_device(info: Optional[Dict[str, object]] = None) -> str:
    data = info if info is not None else inspect_torch_runtime()
    value = str(data.get("recommended_device") or "cpu").strip().lower()
    if value in {"cuda", "mps"}:
        return value
    return "cpu"


def torch_runtime_summary(info: Dict[str, object]) -> str:
    parts = [
        f"python={_str_or_dash(info.get('python_executable'))}",
        f"torch={_str_or_dash(info.get('torch_version'))}",
        f"cuda_ver={_str_or_dash(info.get('cuda_version'))}",
        f"cuda_available={bool(info.get('cuda_available', False))}",
        f"cuda_devices={int(info.get('cuda_device_count', 0) or 0)}",
        f"cuda_name={_str_or_dash(info.get('cuda_device_name'))}",
        f"mps_available={bool(info.get('mps_available', False))}",
        f"gpu_reason={_str_or_dash(info.get('gpu_reason'))}",
    ]
    return ", ".join(parts)


def torch_gpu_error_hint(info: Dict[str, object], *, task_name: str = "task") -> str:
    reason = str(info.get("gpu_reason", "gpu_unavailable"))
    system_name = platform.system().lower()
    if reason == "torch_missing":
        return f"{task_name} requires GPU, but torch is not installed in the backend environment."
    if reason == "cuda_build_missing":
        if "windows" in system_name:
            return (
                f"{task_name} requires CUDA torch, but the installed torch wheel is CPU-only. "
                "Install a CUDA build and matching torchaudio."
            )
        return f"{task_name} requires GPU, but MPS/CUDA torch is not available in this environment."
    if reason == "cuda_no_visible_device":
        return (
            f"{task_name} requires CUDA device access, but torch detects no visible CUDA devices. "
            "Check GPU driver/driver reboot and WSL/WSA restrictions."
        )
    if reason == "cuda_runtime_unavailable":
        return (
            f"{task_name} requires CUDA runtime, but CUDA cannot be initialized. "
            "Update NVIDIA driver and Python/CUDA compatible torch wheel."
        )
    if reason == "mps_unavailable":
        return (
            f"{task_name} requires MPS, but MPS is unavailable. "
            "Try torch built with MPS support or enable CUDA path where available."
        )
    return f"{task_name} requires GPU, but currently running on CPU."


def _gpu_unavailable_reason(info: Dict[str, object]) -> str:
    if not bool(info.get("torch_available")):
        return "torch_missing"

    cuda_version = _str_or_none(info.get("cuda_version"))
    cuda_available = bool(info.get("cuda_available", False))
    cuda_device_count = int(info.get("cuda_device_count", 0) or 0)
    mps_available = bool(info.get("mps_available", False))
    system_name = platform.system().lower()

    if "windows" in system_name and not cuda_version:
        return "cuda_build_missing"
    if cuda_available and cuda_device_count <= 0:
        return "cuda_no_visible_device"
    if not cuda_available and cuda_version:
        return "cuda_runtime_unavailable"
    if "darwin" in system_name and not mps_available:
        return "mps_unavailable"
    return "gpu_unavailable"


def _str_or_none(value: object) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _str_or_dash(value: object) -> str:
    text = _str_or_none(value)
    return text if text is not None else "-"
