from __future__ import annotations

import os
import platform
import subprocess
import threading
import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Literal, Optional

import cv2
import numpy as np


OpencvMode = Literal["cuda", "opencl", "cpu"]


@dataclass(frozen=True)
class RuntimeAcceleration:
    opencv_mode: OpencvMode
    cuda_device_count: int
    opencl_available: bool
    opencl_enabled: bool
    ffmpeg_hwaccel_flags: List[List[str]]
    ffmpeg_mode_order: List[str]
    cpu_name: str
    gpu_name: Optional[str]


_ACCELERATION_CACHE: Optional[RuntimeAcceleration] = None
_ACCELERATION_LOGGED = False
_LOCK = threading.Lock()


def get_runtime_acceleration(
    *,
    logger: Optional[Callable[[str], None]] = None,
    ffmpeg_bin: str = "ffmpeg",
) -> RuntimeAcceleration:
    global _ACCELERATION_CACHE, _ACCELERATION_LOGGED
    with _LOCK:
        if _ACCELERATION_CACHE is None:
            _ACCELERATION_CACHE = _detect_runtime_acceleration(ffmpeg_bin=ffmpeg_bin)
            _ACCELERATION_LOGGED = False
        accel = _ACCELERATION_CACHE

        if logger is not None and not _ACCELERATION_LOGGED:
            _log_runtime_acceleration(accel, logger)
            _ACCELERATION_LOGGED = True
        return accel


def _detect_runtime_acceleration(*, ffmpeg_bin: str) -> RuntimeAcceleration:
    cuda_device_count = _get_cuda_device_count()
    opencl_available = bool(cv2.ocl.haveOpenCL())
    opencl_enabled = bool(cv2.ocl.useOpenCL())
    opencv_mode = _select_opencv_mode(
        cuda_device_count=cuda_device_count,
        opencl_available=opencl_available,
    )
    if opencv_mode == "opencl":
        try:
            cv2.ocl.setUseOpenCL(True)
        except Exception:
            pass
        opencl_enabled = bool(cv2.ocl.useOpenCL())
    else:
        try:
            cv2.ocl.setUseOpenCL(False)
        except Exception:
            pass
        opencl_enabled = bool(cv2.ocl.useOpenCL())

    ffmpeg_hwaccel_flags = _resolve_ffmpeg_hwaccel_flags(ffmpeg_bin=ffmpeg_bin)
    ffmpeg_mode_order = [_flags_to_name(flags) for flags in ffmpeg_hwaccel_flags]
    cpu_name = _detect_cpu_name()
    gpu_name = _detect_gpu_name(cuda_device_count=cuda_device_count)
    if platform.system().lower() == "darwin":
        if cpu_name.lower() in {"arm", "arm64", "x86_64", "unknown cpu"} and gpu_name and gpu_name.lower().startswith("apple "):
            cpu_name = gpu_name
    return RuntimeAcceleration(
        opencv_mode=opencv_mode,
        cuda_device_count=cuda_device_count,
        opencl_available=opencl_available,
        opencl_enabled=opencl_enabled,
        ffmpeg_hwaccel_flags=ffmpeg_hwaccel_flags,
        ffmpeg_mode_order=ffmpeg_mode_order,
        cpu_name=cpu_name,
        gpu_name=gpu_name,
    )


def _log_runtime_acceleration(accel: RuntimeAcceleration, logger: Callable[[str], None]) -> None:
    logger(
        "runtime acceleration: "
        f"opencv={accel.opencv_mode} "
        f"(cuda_devices={accel.cuda_device_count}, opencl_available={accel.opencl_available}, opencl_enabled={accel.opencl_enabled}) "
        f"ffmpeg_hwaccel={'/'.join(accel.ffmpeg_mode_order)} "
        f"gpu_name={accel.gpu_name or 'unavailable'} "
        f"cpu_name={accel.cpu_name}"
    )


def runtime_public_info(accel: RuntimeAcceleration, *, ffmpeg_mode: Optional[str] = None) -> Dict[str, object]:
    active_ffmpeg_mode = ffmpeg_mode or _first_non_cpu(accel.ffmpeg_mode_order) or "cpu"
    uses_gpu = active_ffmpeg_mode != "cpu" or accel.opencv_mode in {"cuda", "opencl"}
    return {
        "overall_mode": "gpu" if uses_gpu else "cpu",
        "ffmpeg_mode": active_ffmpeg_mode,
        "opencv_mode": accel.opencv_mode,
        "ffmpeg_order": accel.ffmpeg_mode_order,
        "gpu_name": accel.gpu_name,
        "cpu_name": accel.cpu_name,
    }


def _first_non_cpu(names: List[str]) -> Optional[str]:
    for name in names:
        if name != "cpu":
            return name
    return None


def _flags_to_name(flags: List[str]) -> str:
    if not flags:
        return "cpu"
    if "-hwaccel" in flags:
        try:
            idx = flags.index("-hwaccel")
            return flags[idx + 1]
        except Exception:
            return "gpu"
    return "gpu"


def _select_opencv_mode(*, cuda_device_count: int, opencl_available: bool) -> OpencvMode:
    pref = os.getenv("DRUMSHEET_OPENCV_ACCEL", "auto").strip().lower()
    if pref in {"none", "off"}:
        pref = "cpu"

    def cuda_ready() -> bool:
        return cuda_device_count > 0 and _probe_cuda_pipeline()

    def opencl_ready() -> bool:
        if not opencl_available:
            return False
        try:
            cv2.ocl.setUseOpenCL(True)
            return bool(cv2.ocl.useOpenCL())
        except Exception:
            return False

    if pref == "cpu":
        return "cpu"
    if pref == "cuda":
        if cuda_ready():
            return "cuda"
        if opencl_ready():
            return "opencl"
        return "cpu"
    if pref == "opencl":
        if opencl_ready():
            return "opencl"
        if cuda_ready():
            return "cuda"
        return "cpu"

    if cuda_ready():
        return "cuda"
    if opencl_ready():
        return "opencl"
    return "cpu"


def _probe_cuda_pipeline() -> bool:
    if not hasattr(cv2, "cuda"):
        return False
    try:
        sample = np.zeros((64, 64, 3), dtype=np.uint8)
        gpu = cv2.cuda_GpuMat()
        gpu.upload(sample)
        gray_gpu = cv2.cuda.cvtColor(gpu, cv2.COLOR_BGR2GRAY)
        blur = cv2.cuda.createGaussianFilter(cv2.CV_8UC1, cv2.CV_8UC1, (5, 5), 0)
        blurred_gpu = blur.apply(gray_gpu)
        canny = cv2.cuda.createCannyEdgeDetector(40, 140)
        edges = canny.detect(blurred_gpu)
        _ = edges.download()
        return True
    except Exception:
        return False


def _get_cuda_device_count() -> int:
    if not hasattr(cv2, "cuda"):
        return 0
    try:
        return int(cv2.cuda.getCudaEnabledDeviceCount())
    except Exception:
        return 0


def _resolve_ffmpeg_hwaccel_flags(*, ffmpeg_bin: str) -> List[List[str]]:
    pref = os.getenv("DRUMSHEET_HWACCEL", "auto").strip().lower()
    if pref in {"none", "off", "cpu"}:
        return [[]]

    available = _ffmpeg_hwaccels(ffmpeg_bin)
    if pref and pref != "auto":
        requested = [item.strip() for item in pref.split(",") if item.strip()]
    else:
        requested = _platform_hwaccel_preference()

    flags: List[List[str]] = []
    for name in requested:
        if available and name not in available:
            continue
        values = _hwaccel_flags_for(name)
        if values:
            flags.append(values)

    if not flags and pref not in {"", "auto"}:
        for name in requested:
            values = _hwaccel_flags_for(name)
            if values:
                flags.append(values)

    flags.append([])
    dedup: List[List[str]] = []
    seen = set()
    for item in flags:
        key = tuple(item)
        if key in seen:
            continue
        dedup.append(item)
        seen.add(key)
    return dedup


def _platform_hwaccel_preference() -> List[str]:
    system_name = platform.system().lower()
    if "darwin" in system_name:
        return ["videotoolbox", "cuda"]
    if "windows" in system_name:
        return ["cuda", "d3d11va", "dxva2", "qsv"]
    if "linux" in system_name:
        return ["cuda", "vaapi", "qsv", "vdpau"]
    return ["cuda"]


def _hwaccel_flags_for(name: str) -> List[str]:
    key = name.strip().lower()
    if not key:
        return []
    if key == "cuda":
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    return ["-hwaccel", key]


def _ffmpeg_hwaccels(ffmpeg_bin: str) -> List[str]:
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-hwaccels"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    names: List[str] = []
    for raw in result.stdout.splitlines():
        line = raw.strip().lower()
        if not line or "hardware acceleration methods" in line:
            continue
        names.append(line)
    return names


def _detect_cpu_name() -> str:
    system_name = platform.system().lower()
    if "darwin" in system_name:
        name = _run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"])
        if name:
            return name
        chip = _run_cmd(["sysctl", "-n", "hw.model"])
        if chip:
            return chip
    if "linux" in system_name:
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    if "windows" in system_name:
        name = _run_cmd(["wmic", "cpu", "get", "Name"])
        parsed = _first_non_header_line(name, header_contains="name")
        if parsed:
            return parsed
    return platform.processor() or platform.machine() or "Unknown CPU"


def _detect_gpu_name(*, cuda_device_count: int) -> Optional[str]:
    if cuda_device_count > 0:
        name = _run_cmd(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            timeout_sec=2.5,
        )
        if name:
            first = name.splitlines()[0].strip()
            if first:
                return first

    system_name = platform.system().lower()
    if "darwin" in system_name:
        raw = _run_cmd(["system_profiler", "SPDisplaysDataType", "-json"], timeout_sec=6.0)
        if raw:
            try:
                data = json.loads(raw)
                items = data.get("SPDisplaysDataType") or []
                for item in items:
                    candidate = (item.get("sppci_model") or item.get("spdisplays_model") or "").strip()
                    if candidate:
                        return candidate
            except Exception:
                pass
        return "Apple GPU"

    if "windows" in system_name:
        raw = _run_cmd(["wmic", "path", "win32_VideoController", "get", "Name"], timeout_sec=3.0)
        parsed = _first_non_header_line(raw, header_contains="name")
        if parsed:
            return parsed
        return None

    if "linux" in system_name:
        raw = _run_cmd(["lspci"], timeout_sec=2.5)
        if raw:
            for line in raw.splitlines():
                low = line.lower()
                if "vga compatible controller" in low or "3d controller" in low or "display controller" in low:
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
                    return line.strip()
    return None


def _run_cmd(cmd: List[str], *, timeout_sec: float = 2.0) -> str:
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _first_non_header_line(raw: str, *, header_contains: str) -> Optional[str]:
    if not raw:
        return None
    for line in raw.splitlines():
        value = line.strip()
        if not value:
            continue
        if header_contains in value.lower():
            continue
        return value
    return None
