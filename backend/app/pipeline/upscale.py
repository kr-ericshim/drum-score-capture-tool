from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import yaml

from app.pipeline.acceleration import RuntimeAcceleration
from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin
from app.pipeline.hat_runtime import HatRuntime, get_hat_runtime
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

    scale = float(options.scale)
    logger("upscale enabled (gpu-only)")
    logger(f"upscale factor: {scale:.1f}x")
    logger("upscale quality profile: document_text")
    if _should_apply_sharpening():
        logger("upscale post-process: unsharp enabled")

    workspace.mkdir(parents=True, exist_ok=True)
    attempt_errors: List[str] = []
    engine_pref = _upscale_engine_pref()
    logger(f"upscale engine preference: {engine_pref}")

    for engine in _upscale_engine_order(engine_pref):
        if engine == "hat":
            hat_runtime = get_hat_runtime()
            if not hat_runtime.enabled:
                continue
            if not hat_runtime.available:
                attempt_errors.append(f"hat_unavailable({hat_runtime.reason})")
                continue
            if options.gpu_only and hat_runtime.run_device == "cpu" and not hat_runtime.allow_cpu:
                attempt_errors.append("hat_cpu_disallowed")
                continue
            try:
                logger("upscale engine: hat")
                logger(f"hat runtime device: {hat_runtime.run_device}")
                if hat_runtime.run_device == "cpu" and hat_runtime.allow_cpu:
                    logger("hat cpu override enabled")
                return _upscale_with_hat(
                    frame_paths=frame_paths,
                    scale=scale,
                    workspace=workspace,
                    hat_runtime=hat_runtime,
                )
            except Exception as exc:
                attempt_errors.append(f"hat: {exc}")
            continue

        if engine == "opencv":
            mode = acceleration.opencv_mode
            if mode not in {"cuda", "opencl"}:
                continue
            try:
                logger(f"upscale engine: opencv_{mode}")
                return _upscale_with_opencv_gpu(
                    frame_paths=frame_paths,
                    scale=scale,
                    workspace=workspace,
                    preferred_mode=mode,
                    allow_opencl_fallback=(mode == "cuda" and acceleration.opencl_available),
                )
            except Exception as exc:
                attempt_errors.append(f"opencv_{mode}: {exc}")
            continue

        if engine == "ffmpeg":
            if not acceleration.ffmpeg_scale_vt_available:
                continue
            try:
                logger("upscale engine: ffmpeg_scale_vt")
                return _upscale_with_ffmpeg_scale_vt(
                    frame_paths=frame_paths,
                    scale=scale,
                    workspace=workspace,
                )
            except Exception as exc:
                attempt_errors.append(f"ffmpeg_scale_vt: {exc}")
            continue

    if attempt_errors:
        joined = " | ".join(attempt_errors[-4:])
        raise RuntimeError(f"GPU-only upscaling failed: {joined}")
    raise RuntimeError("GPU-only upscaling requires HAT or OpenCV GPU mode (cuda/opencl) or ffmpeg scale_vt.")


def _upscale_with_hat(
    *,
    frame_paths: List[Path],
    scale: float,
    workspace: Path,
    hat_runtime: HatRuntime,
) -> List[Path]:
    if hat_runtime.repo_path is None or hat_runtime.option_template_path is None or hat_runtime.weights_path is None:
        raise RuntimeError("HAT runtime is incomplete")

    run_id = uuid.uuid4().hex[:10]
    run_name = f"drumsheet_hat_{run_id}"
    hat_results_dir = hat_runtime.repo_path / "results" / run_name
    run_workspace = Path(tempfile.mkdtemp(prefix="hat_", dir=str(workspace)))
    input_dir = run_workspace / "input_dir"
    input_dir.mkdir(parents=True, exist_ok=True)

    staged: List[Tuple[int, str, int, int]] = []
    try:
        for idx, frame_path in enumerate(frame_paths):
            image = cv2.imread(str(frame_path))
            if image is None:
                continue
            name = f"in_{idx:05d}.png"
            target_w = max(2, int(round(image.shape[1] * scale)))
            target_h = max(2, int(round(image.shape[0] * scale)))
            staged_path = input_dir / name
            if not cv2.imwrite(str(staged_path), image):
                continue
            staged.append((idx, staged_path.stem, target_w, target_h))

        if not staged:
            raise RuntimeError("HAT received no readable input frames")

        options = _build_hat_options(
            option_template_path=hat_runtime.option_template_path,
            input_dir=input_dir,
            run_name=run_name,
            weights_path=hat_runtime.weights_path,
            run_device=hat_runtime.run_device,
            tile_size=hat_runtime.tile_size,
            tile_pad=hat_runtime.tile_pad,
        )
        opt_path = run_workspace / "hat_job.yml"
        with open(opt_path, "w", encoding="utf-8") as fp:
            yaml.safe_dump(options, fp, sort_keys=False)

        cmd = [hat_runtime.python_bin, "hat/test.py", "-opt", str(opt_path)]
        result = subprocess.run(
            cmd,
            cwd=str(hat_runtime.repo_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            stderr = _tail_text(result.stderr, limit=900)
            raise RuntimeError(f"HAT inference failed: {stderr}")

        output_dir = hat_results_dir / "visualization" / "custom"
        if not output_dir.exists():
            raise RuntimeError("HAT output directory is missing")

        out_paths: List[Path] = []
        for idx, stem, target_w, target_h in staged:
            out_src = _find_hat_output(output_dir=output_dir, stem=stem)
            if out_src is None:
                continue
            out_img = cv2.imread(str(out_src))
            if out_img is None:
                continue

            if out_img.shape[1] != target_w or out_img.shape[0] != target_h:
                interp = cv2.INTER_AREA if (out_img.shape[1] > target_w or out_img.shape[0] > target_h) else cv2.INTER_LANCZOS4
                out_img = cv2.resize(out_img, (target_w, target_h), interpolation=interp)
            if _should_apply_sharpening():
                out_img = _enhance_document_upscale(out_img)

            out_path = workspace / f"upscaled_{idx:05d}.png"
            if cv2.imwrite(str(out_path), out_img):
                out_paths.append(out_path)

        if not out_paths:
            raise RuntimeError("HAT produced no output pages")
        return out_paths
    finally:
        shutil.rmtree(run_workspace, ignore_errors=True)
        shutil.rmtree(hat_results_dir, ignore_errors=True)


def _build_hat_options(
    *,
    option_template_path: Path,
    input_dir: Path,
    run_name: str,
    weights_path: Path,
    run_device: str,
    tile_size: int,
    tile_pad: int,
) -> Dict[str, object]:
    with open(option_template_path, "r", encoding="utf-8") as fp:
        options = yaml.safe_load(fp) or {}
    if not isinstance(options, dict):
        raise RuntimeError("invalid HAT option template")

    options["name"] = run_name
    options["num_gpu"] = 1 if run_device == "cuda" else 0
    if run_device == "mps":
        options["device"] = "mps"

    tile = options.get("tile")
    if not isinstance(tile, dict):
        tile = {}
    tile["tile_size"] = int(tile_size)
    tile["tile_pad"] = int(tile_pad)
    options["tile"] = tile

    options["datasets"] = {
        "test_1": {
            "name": "custom",
            "type": "SingleImageDataset",
            "dataroot_lq": str(input_dir),
            "io_backend": {"type": "disk"},
        }
    }

    path = options.get("path")
    if not isinstance(path, dict):
        path = {}
    path["pretrain_network_g"] = str(weights_path)
    options["path"] = path

    val = options.get("val")
    if not isinstance(val, dict):
        val = {}
    val["save_img"] = True
    val["suffix"] = None
    # In inference-only mode we do not have GT images; disable metric blocks.
    val.pop("metrics", None)
    options["val"] = val

    return options


def _find_hat_output(*, output_dir: Path, stem: str) -> Optional[Path]:
    candidates = sorted([p for p in output_dir.glob(f"{stem}*") if p.is_file()])
    for path in candidates:
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            return path
    return candidates[0] if candidates else None


def _upscale_with_opencv_gpu(
    *,
    frame_paths: List[Path],
    scale: float,
    workspace: Path,
    preferred_mode: str,
    allow_opencl_fallback: bool,
) -> List[Path]:
    out_paths: List[Path] = []
    for idx, frame_path in enumerate(frame_paths):
        image = cv2.imread(str(frame_path))
        if image is None:
            continue

        target_w = max(2, int(round(image.shape[1] * scale)))
        target_h = max(2, int(round(image.shape[0] * scale)))
        upscaled = _upscale_image(
            image=image,
            target_size=(target_w, target_h),
            preferred_mode=preferred_mode,
            allow_opencl_fallback=allow_opencl_fallback,
        )
        if upscaled is None:
            raise RuntimeError("GPU upscaling failed while resizing output pages.")
        if _should_apply_sharpening():
            upscaled = _enhance_document_upscale(upscaled)

        out_path = workspace / f"upscaled_{idx:05d}.png"
        if cv2.imwrite(str(out_path), upscaled):
            out_paths.append(out_path)

    if not out_paths:
        raise RuntimeError("upscaling produced no output pages")
    return out_paths


def _upscale_with_ffmpeg_scale_vt(
    *,
    frame_paths: List[Path],
    scale: float,
    workspace: Path,
) -> List[Path]:
    ffmpeg_bin = resolve_ffmpeg_bin()
    out_paths: List[Path] = []
    for idx, frame_path in enumerate(frame_paths):
        image = cv2.imread(str(frame_path))
        if image is None:
            continue
        target_w = max(2, int(round(image.shape[1] * scale)))
        target_h = max(2, int(round(image.shape[0] * scale)))
        out_path = workspace / f"upscaled_{idx:05d}.png"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-init_hw_device",
            "videotoolbox=vt",
            "-filter_hw_device",
            "vt",
            "-i",
            str(frame_path),
            "-vf",
            f"format=nv12,hwupload,scale_vt=w={target_w}:h={target_h},hwdownload,format=nv12",
            "-frames:v",
            "1",
            str(out_path),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size <= 0:
            stderr = result.stderr.strip() if result.stderr else "unknown ffmpeg error"
            raise RuntimeError(f"scale_vt failed at frame {idx}: {stderr}")
        if _should_apply_sharpening():
            out_img = cv2.imread(str(out_path))
            if out_img is not None:
                refined = _enhance_document_upscale(out_img)
                cv2.imwrite(str(out_path), refined)
        out_paths.append(out_path)

    if not out_paths:
        raise RuntimeError("upscaling produced no output pages")
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
        # Lanczos keeps thin stave lines and symbols more legible than cubic.
        resized = cv2.resize(umat, target_size, interpolation=cv2.INTER_LANCZOS4)
        if isinstance(resized, cv2.UMat):
            return resized.get()
        return resized
    except Exception:
        return None


def _enhance_document_upscale(image):
    if image is None:
        return image
    if min(image.shape[:2]) < 80:
        return image
    try:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        # Conservative unsharp mask to recover edge clarity without aggressive halos.
        blurred = cv2.GaussianBlur(l_channel, (0, 0), 0.8)
        sharpened_l = cv2.addWeighted(l_channel, 1.45, blurred, -0.45, 0)
        merged = cv2.merge((sharpened_l, a_channel, b_channel))
        return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    except Exception:
        return image


def _upscale_engine_pref() -> str:
    value = os.getenv("DRUMSHEET_UPSCALE_ENGINE", "auto").strip().lower()
    if value in {"hat", "opencv", "ffmpeg"}:
        return value
    return "auto"


def _upscale_engine_order(pref: str) -> List[str]:
    if pref == "hat":
        return ["hat", "opencv", "ffmpeg"]
    if pref == "opencv":
        return ["opencv", "hat", "ffmpeg"]
    if pref == "ffmpeg":
        return ["ffmpeg", "opencv", "hat"]
    return ["hat", "opencv", "ffmpeg"]


def _tail_text(text: str, *, limit: int) -> str:
    value = (text or "").strip()
    if not value:
        return "unknown error"
    if len(value) <= limit:
        return value
    return value[-limit:]


def _should_apply_sharpening() -> bool:
    raw = os.getenv("DRUMSHEET_UPSCALE_SHARPEN", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}
