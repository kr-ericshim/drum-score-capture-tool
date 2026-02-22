from __future__ import annotations

from pathlib import Path
from typing import List

import cv2

from app.pipeline.acceleration import RuntimeAcceleration
from app.schemas import UpscaleOptions


def upscale_frames(
    *,
    frame_paths: List[Path],
    options: UpscaleOptions,
    workspace: Path,
    acceleration: RuntimeAcceleration,
    logger,
) -> List[Path]:
    if not frame_paths:
        return []

    if not options.enable:
        logger("upscale disabled, using original resolution")
        return frame_paths

    mode = acceleration.opencv_mode
    if mode not in {"cuda", "opencl"}:
        raise RuntimeError("GPU-only upscaling requires OpenCV GPU mode (cuda/opencl).")

    workspace.mkdir(parents=True, exist_ok=True)
    scale = float(options.scale)
    logger("upscale enabled (gpu-only)")
    logger(f"upscale factor: {scale:.1f}x")

    out_paths: List[Path] = []
    use_opencl_fallback = mode == "cuda" and acceleration.opencl_available
    for idx, frame_path in enumerate(frame_paths):
        image = cv2.imread(str(frame_path))
        if image is None:
            continue

        target_w = max(2, int(round(image.shape[1] * scale)))
        target_h = max(2, int(round(image.shape[0] * scale)))
        upscaled = _upscale_image(
            image=image,
            target_size=(target_w, target_h),
            preferred_mode=mode,
            allow_opencl_fallback=use_opencl_fallback,
        )
        if upscaled is None:
            raise RuntimeError("GPU upscaling failed while resizing output pages.")

        out_path = workspace / f"upscaled_{idx:05d}.png"
        if cv2.imwrite(str(out_path), upscaled):
            out_paths.append(out_path)

    if not out_paths:
        raise RuntimeError("upscaling produced no output pages")

    logger(f"upscaled pages: {len(out_paths)}")
    return out_paths


def _upscale_image(
    *,
    image,
    target_size,
    preferred_mode: str,
    allow_opencl_fallback: bool,
):
    if preferred_mode == "cuda":
        resized = _resize_with_cuda(image, target_size)
        if resized is not None:
            return resized
        if allow_opencl_fallback:
            return _resize_with_opencl(image, target_size)
        return None

    if preferred_mode == "opencl":
        return _resize_with_opencl(image, target_size)

    return None


def _resize_with_cuda(image, target_size):
    if not hasattr(cv2, "cuda"):
        return None
    try:
        gpu = cv2.cuda_GpuMat()
        gpu.upload(image)
        resized_gpu = cv2.cuda.resize(gpu, target_size, interpolation=cv2.INTER_CUBIC)
        return resized_gpu.download()
    except Exception:
        return None


def _resize_with_opencl(image, target_size):
    try:
        cv2.ocl.setUseOpenCL(True)
        umat = cv2.UMat(image)
        resized = cv2.resize(umat, target_size, interpolation=cv2.INTER_CUBIC)
        if isinstance(resized, cv2.UMat):
            return resized.get()
        return resized
    except Exception:
        return None
