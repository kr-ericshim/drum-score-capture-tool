from __future__ import annotations

import hashlib
import os
import platform
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.job_store import Job, JobStatus, JobStore
from app.schemas import (
    AudioSeparateRequest,
    AudioSeparateResponse,
    CaptureCropRequest,
    CaptureCropResponse,
    CacheClearResponse,
    CacheUsageResponse,
    JobCreate,
    JobCreateResponse,
    JobFileResponse,
    JobReviewExportRequest,
    JobReviewExportResponse,
    JobStatusResponse,
    PreviewFrameRequest,
    PreviewFrameResponse,
    PreviewSourceRequest,
    PreviewSourceResponse,
    RuntimeStatusResponse,
)
from app.pipeline.acceleration import get_runtime_acceleration, runtime_public_info
from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin
from app.pipeline.extract import extract_frames, extract_preview_frame, prepare_preview_source
from app.pipeline.detect import detect_sheet_regions
from app.pipeline.rectify import rectify_frames
from app.pipeline.stitch import stitch_pages
from app.pipeline.upscale import upscale_frames
from app.pipeline.audio_uvr import separate_audio_stem
from app.pipeline.torch_runtime import inspect_torch_runtime, select_torch_device
from app.pipeline.export import export_frames


app = FastAPI(title="Drum Sheet Capture API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


jobs_root = Path(os.getenv("DRUMSHEET_JOBS_DIR", Path(__file__).resolve().parents[1] / "jobs"))
jobs_root.mkdir(parents=True, exist_ok=True)
app.mount("/jobs-files", StaticFiles(directory=str(jobs_root), check_dir=False), name="jobs-files")
job_store = JobStore(jobs_root)
executor = ThreadPoolExecutor(max_workers=1)
AUDIO_SEPARATE_ALLOWED_EXTENSIONS = (".mp3", ".wav", ".mp4")
AUDIO_SEPARATE_ALLOWED_EXTENSION_SET = set(AUDIO_SEPARATE_ALLOWED_EXTENSIONS)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/runtime", response_model=RuntimeStatusResponse)
def runtime_status() -> RuntimeStatusResponse:
    ffmpeg_bin = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    accel = get_runtime_acceleration(ffmpeg_bin=ffmpeg_bin)
    payload = runtime_public_info(accel)
    torch_info = inspect_torch_runtime()
    payload.update(
        {
            "audio_gpu_mode": select_torch_device(torch_info),
            "audio_gpu_ready": bool(torch_info.get("gpu_ready", False)),
            "torch_version": str(torch_info.get("torch_version")) if torch_info.get("torch_version") else None,
            "torch_cuda_available": bool(torch_info.get("cuda_available", False)),
            "torch_cuda_version": str(torch_info.get("cuda_version")) if torch_info.get("cuda_version") else None,
            "torch_cuda_device_count": int(torch_info.get("cuda_device_count", 0) or 0),
            "torch_cuda_device_name": str(torch_info.get("cuda_device_name")) if torch_info.get("cuda_device_name") else None,
            "torch_mps_available": bool(torch_info.get("mps_available", False)),
            "torch_python": str(torch_info.get("python_executable")) if torch_info.get("python_executable") else None,
            "torch_gpu_reason": str(torch_info.get("gpu_reason", "unknown")),
        }
    )
    return RuntimeStatusResponse(**payload)


@app.post("/maintenance/clear-cache", response_model=CacheClearResponse)
def clear_cache() -> CacheClearResponse:
    active_jobs = job_store.active_job_ids()
    if active_jobs:
        raise HTTPException(status_code=409, detail="cache clear is blocked while jobs are running")

    reclaimed_bytes = 0
    cleared_paths = 0
    skipped_paths: List[str] = []

    for child in sorted(jobs_root.iterdir(), key=lambda item: item.name):
        try:
            reclaimed_bytes += _path_size_bytes(child)
            _remove_path(child)
            cleared_paths += 1
        except OSError as exc:
            skipped_paths.append(f"{child.name}: {exc}")

    cleared_jobs = job_store.clear_all()
    return CacheClearResponse(
        cleared_paths=cleared_paths,
        cleared_jobs=cleared_jobs,
        reclaimed_bytes=int(max(0, reclaimed_bytes)),
        reclaimed_human=_human_bytes(reclaimed_bytes),
        skipped_paths=skipped_paths,
    )


@app.get("/maintenance/cache-usage", response_model=CacheUsageResponse)
def cache_usage() -> CacheUsageResponse:
    total_paths, total_bytes = _cache_usage_summary()
    return CacheUsageResponse(
        total_paths=total_paths,
        total_bytes=int(max(0, total_bytes)),
        total_human=_human_bytes(total_bytes),
    )


@app.post("/preview/frame", response_model=PreviewFrameResponse)
def preview_frame(payload: PreviewFrameRequest) -> PreviewFrameResponse:
    try:
        if payload.source_type == "file":
            if not payload.file_path:
                raise HTTPException(status_code=400, detail="file_path is required when source_type is file")
            if not Path(payload.file_path).exists():
                raise HTTPException(status_code=400, detail="file_path does not exist")
        if payload.source_type == "youtube" and not payload.youtube_url:
            raise HTTPException(status_code=400, detail="youtube_url is required when source_type is youtube")

        preview_workspace = jobs_root / "_preview" / str(uuid.uuid4())
        preview_workspace.mkdir(parents=True, exist_ok=True)
        resolved_source_type = payload.source_type
        resolved_file_path = payload.file_path
        resolved_youtube_url = payload.youtube_url

        if payload.source_type == "youtube" and payload.youtube_url:
            cached_video, _ = _get_or_prepare_cached_youtube_video(payload.youtube_url, logger=lambda _: None)
            resolved_source_type = "file"
            resolved_file_path = str(cached_video)
            resolved_youtube_url = None

        image_path = extract_preview_frame(
            source_type=resolved_source_type,
            file_path=resolved_file_path,
            youtube_url=resolved_youtube_url,
            start_sec=payload.start_sec,
            workspace=preview_workspace,
            logger=lambda _: None,
        )
        image_url = None
        try:
            rel_path = image_path.relative_to(jobs_root)
            image_url = f"/jobs-files/{rel_path.as_posix()}"
        except ValueError:
            image_url = None
        return PreviewFrameResponse(image_path=str(image_path), image_url=image_url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"preview frame extraction failed: {exc}")


@app.post("/preview/source", response_model=PreviewSourceResponse)
def preview_source(payload: PreviewSourceRequest) -> PreviewSourceResponse:
    try:
        if payload.source_type == "file":
            if not payload.file_path:
                raise HTTPException(status_code=400, detail="file_path is required when source_type is file")
            source_path = Path(payload.file_path)
            if not source_path.exists():
                raise HTTPException(status_code=400, detail="file_path does not exist")
            return PreviewSourceResponse(video_path=str(source_path), video_url=None, from_cache=True)

        if payload.source_type == "youtube":
            if not payload.youtube_url:
                raise HTTPException(status_code=400, detail="youtube_url is required when source_type is youtube")
            video_path, from_cache = _get_or_prepare_cached_youtube_video(payload.youtube_url, logger=lambda _: None)
            video_url = _to_jobs_files_url(video_path)
            return PreviewSourceResponse(video_path=str(video_path), video_url=video_url, from_cache=from_cache)

        raise HTTPException(status_code=400, detail=f"unsupported source_type: {payload.source_type}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"preview source preparation failed: {exc}")


@app.post("/audio/separate", response_model=AudioSeparateResponse)
def audio_separate(payload: AudioSeparateRequest) -> AudioSeparateResponse:
    try:
        logs: list[str] = []

        def _audio_log(message: str) -> None:
            text = str(message or "").strip()
            if text:
                logs.append(text)

        if payload.source_type == "file":
            if not payload.file_path:
                raise HTTPException(status_code=400, detail="file_path is required when source_type is file")
            source_path = Path(payload.file_path)
            if not source_path.exists():
                raise HTTPException(status_code=400, detail="file_path does not exist")
            source_ext = source_path.suffix.lower()
            if source_ext not in AUDIO_SEPARATE_ALLOWED_EXTENSION_SET:
                allowed = ", ".join(ext.lstrip(".") for ext in AUDIO_SEPARATE_ALLOWED_EXTENSIONS)
                raise HTTPException(status_code=400, detail=f"audio separation supports only {allowed} for local files")
        if payload.source_type == "youtube" and not payload.youtube_url:
            raise HTTPException(status_code=400, detail="youtube_url is required when source_type is youtube")

        options = payload.options.model_copy(update={"enable": True})
        workspace = jobs_root / "_audio" / str(uuid.uuid4())
        workspace.mkdir(parents=True, exist_ok=True)
        _audio_log(f"audio separation request accepted: source_type={payload.source_type}")
        if payload.source_type == "youtube":
            source_video, from_cache = _get_or_prepare_cached_youtube_video(payload.youtube_url or "", logger=_audio_log)
            _audio_log("audio source cache hit: youtube preview cache reused" if from_cache else "audio source cache miss: youtube downloaded and cached")
        else:
            source_video = prepare_preview_source(
                source_type=payload.source_type,
                file_path=payload.file_path,
                youtube_url=payload.youtube_url,
                workspace=workspace / "source",
                logger=_audio_log,
            )
        _audio_log(f"audio source ready: {source_video}")
        source_video_url = _to_jobs_files_url(source_video)
        result = separate_audio_stem(
            source_video=source_video,
            options=options,
            workspace=workspace / "stem",
            logger=_audio_log,
        )
        stem_path = Path(result.get("audio_stem", ""))
        if not stem_path.exists():
            raise RuntimeError("audio stem output file is missing")
        audio_url = _to_jobs_files_url(stem_path)
        stem_paths: Dict[str, str] = {}
        stem_urls: Dict[str, str] = {}
        raw_stems = result.get("audio_stems")
        if isinstance(raw_stems, dict):
            for stem_name, stem_file in raw_stems.items():
                stem_value = str(stem_file)
                stem_paths[str(stem_name)] = stem_value
                try:
                    stem_url = _to_jobs_files_url(Path(stem_value))
                    if stem_url:
                        stem_urls[str(stem_name)] = stem_url
                except Exception:
                    continue
        return AudioSeparateResponse(
            audio_stem=str(stem_path),
            audio_url=audio_url,
            audio_stems=stem_paths,
            audio_stem_urls=stem_urls,
            source_video=str(source_video),
            source_video_url=source_video_url,
            audio_engine=str(result.get("audio_engine", options.engine)),
            audio_model=str(result.get("audio_model", options.model)),
            audio_device=str(result.get("audio_device", "unknown")),
            output_dir=str(stem_path.parent),
            log_tail=logs[-120:],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"audio separation failed: {exc}")


@app.post("/jobs", response_model=JobCreateResponse)
def create_job(payload: JobCreate) -> JobCreateResponse:
    if payload.source_type == "file":
        if not payload.file_path:
            raise HTTPException(status_code=400, detail="file_path is required when source_type is file")
        if not Path(payload.file_path).exists():
            raise HTTPException(status_code=400, detail="file_path does not exist")
    if payload.source_type == "youtube" and not payload.youtube_url:
        raise HTTPException(status_code=400, detail="youtube_url is required when source_type is youtube")

    job_id = str(uuid.uuid4())
    artifact_dir = jobs_root / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    job = Job(
        id=job_id,
        source_type=payload.source_type,
        file_path=payload.file_path,
        youtube_url=payload.youtube_url,
        options=payload.options.model_dump(),
        artifact_dir=str(artifact_dir),
    )
    job_store.create(job)
    executor.submit(_run_job, job_id, payload)
    return JobCreateResponse(job_id=job_id)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(**job.to_public_dict())


@app.get("/jobs/{job_id}/files", response_model=JobFileResponse)
def get_job_files(job_id: str) -> JobFileResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    result = job.result or {}
    images = [str(Path(p)) for p in result.get("images", [])]
    return JobFileResponse(
        images=images,
        pdf=str(result.get("pdf")) if result.get("pdf") else None,
    )


@app.post("/jobs/{job_id}/review-export", response_model=JobReviewExportResponse)
def review_export(job_id: str, payload: JobReviewExportRequest) -> JobReviewExportResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="job is still running")

    raw_inputs = payload.keep_captures if payload.keep_captures else payload.keep_images
    keep_raw = [str(path or "").strip() for path in raw_inputs]
    keep_raw = [path for path in keep_raw if path]
    if not keep_raw:
        raise HTTPException(status_code=400, detail="keep_captures must include at least one capture")

    artifact_root = Path(job.artifact_dir).resolve()
    resolved_paths: List[Path] = []
    seen: set[str] = set()
    for raw_path in keep_raw:
        resolved = _resolve_capture_path_for_job(job=job, raw_path=raw_path, must_exist=True)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        resolved_paths.append(resolved)

    if not resolved_paths:
        raise HTTPException(status_code=400, detail="no valid captures selected")

    configured_formats = ["png", "pdf"]
    if isinstance(job.options, dict):
        export_opts = job.options.get("export")
        if isinstance(export_opts, dict):
            candidate_formats = export_opts.get("formats")
            if isinstance(candidate_formats, list):
                configured_formats = [str(value) for value in candidate_formats if str(value).strip()]

    requested_formats = payload.formats if payload.formats is not None else configured_formats
    export_workspace = Path(job.artifact_dir) / "export"

    try:
        export_options = _build_export_options(formats=[str(value) for value in requested_formats])
        _clear_export_workspace(export_workspace)
        export_result = export_frames(
            frame_paths=resolved_paths,
            options=export_options,
            workspace=export_workspace,
            logger=lambda msg: _append(job_id, msg),
            source_frames=None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"review export failed: {exc}")

    result = dict(job.result or {})
    result["images"] = export_result.get("images", [])
    result["pdf"] = export_result.get("pdf")
    result["raw_frames"] = export_result.get("raw_frames", [])
    result["output_dir"] = str(export_workspace)
    result["review_candidates"] = [str(path) for path in resolved_paths]
    result["review_export"] = {
        "kept_count": len(resolved_paths),  # capture count
        "requested_count": len(keep_raw),
    }
    job_store.set_state(
        job_id,
        JobStatus.DONE,
        1.0,
        "done",
        "review export finished",
        result=result,
    )

    return JobReviewExportResponse(
        images=[str(path) for path in export_result.get("images", [])],
        pdf=str(export_result.get("pdf")) if export_result.get("pdf") else None,
        output_dir=str(export_workspace),
        kept_count=len(resolved_paths),
    )


@app.post("/jobs/{job_id}/capture-crop", response_model=CaptureCropResponse)
def crop_capture(job_id: str, payload: CaptureCropRequest) -> CaptureCropResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="job is still running")

    capture_path = _resolve_capture_path_for_job(job=job, raw_path=payload.capture_path, must_exist=True)
    if len(payload.roi) != 4:
        raise HTTPException(status_code=400, detail="roi must be 4 points: [[x,y], ...]")

    coords: List[tuple[float, float]] = []
    for point in payload.roi:
        if not isinstance(point, list) or len(point) != 2:
            raise HTTPException(status_code=400, detail="each roi point must be [x, y]")
        x = float(point[0])
        y = float(point[1])
        if not (x == x and y == y):  # NaN guard
            raise HTTPException(status_code=400, detail="roi includes invalid number")
        coords.append((x, y))

    image = cv2.imread(str(capture_path))
    if image is None:
        raise HTTPException(status_code=400, detail="capture file could not be read")

    h, w = image.shape[:2]
    xs = [max(0.0, min(float(w), point[0])) for point in coords]
    ys = [max(0.0, min(float(h), point[1])) for point in coords]
    x1 = int(round(min(xs)))
    y1 = int(round(min(ys)))
    x2 = int(round(max(xs)))
    y2 = int(round(max(ys)))

    min_size = 16
    if x2 - x1 < min_size or y2 - y1 < min_size:
        raise HTTPException(status_code=400, detail="roi is too small for capture crop")

    cropped = image[y1:y2, x1:x2].copy()
    if cropped.size == 0:
        raise HTTPException(status_code=400, detail="capture crop produced empty image")

    if not cv2.imwrite(str(capture_path), cropped):
        raise HTTPException(status_code=500, detail="failed to save cropped capture")

    result = dict(job.result or {})

    def _is_same_capture_path(raw_entry: object) -> bool:
        candidate_raw = str(raw_entry or "").strip()
        if not candidate_raw:
            return False
        try:
            candidate_resolved = _resolve_capture_path_for_job(job=job, raw_path=candidate_raw, must_exist=False)
        except HTTPException:
            return False
        return candidate_resolved == capture_path

    if isinstance(result.get("review_candidates"), list):
        result["review_candidates"] = [
            str(capture_path) if _is_same_capture_path(path) else str(path) for path in result["review_candidates"]
        ]
    if isinstance(result.get("upscaled_frames"), list):
        result["upscaled_frames"] = [
            str(capture_path) if _is_same_capture_path(path) else str(path) for path in result["upscaled_frames"]
        ]
    job_store.set_state(
        job_id,
        job.status,
        job.progress,
        job.current_step,
        "capture crop saved",
        result=result,
    )
    job_store.log(job_id, f"capture crop saved: {capture_path.name} ({x2 - x1}x{y2 - y1})")

    return CaptureCropResponse(
        capture_path=str(capture_path),
        width=int(x2 - x1),
        height=int(y2 - y1),
    )


def _run_job(job_id: str, payload: JobCreate) -> None:
    job = job_store.get(job_id)
    if not job:
        return

    artifact_dir = Path(job.artifact_dir)
    result: Dict[str, object] = {"output_dir": str(artifact_dir / "export")}
    job_store.log(job_id, "job started")
    job_store.set_state(job_id, JobStatus.RUNNING, 0.01, "initializing", "initializing pipeline")

    try:
        options = payload.options
        extract_opts = options.extract
        detect_opts = options.detect
        rectify_opts = options.rectify
        stitch_opts = options.stitch
        upscale_opts = options.upscale
        audio_opts = options.audio
        export_opts = options.export
        runtime_capture: Dict[str, str] = {}
        resolved_source_type = payload.source_type
        resolved_file_path = payload.file_path
        resolved_youtube_url = payload.youtube_url

        if payload.source_type == "youtube" and payload.youtube_url:
            cached_video, from_cache = _get_or_prepare_cached_youtube_video(payload.youtube_url, logger=lambda msg: _append(job_id, msg))
            _append(job_id, "job source cache hit: youtube preview cache reused" if from_cache else "job source cache miss: youtube downloaded and cached")
            resolved_source_type = "file"
            resolved_file_path = str(cached_video)
            resolved_youtube_url = None

        accel = get_runtime_acceleration(
            logger=lambda msg: _append(job_id, msg),
            ffmpeg_bin=resolve_ffmpeg_bin(strict=platform.system().lower() == "windows"),
        )

        if stitch_opts.layout_hint == "auto" and detect_opts.layout_hint != "auto":
            stitch_opts.layout_hint = detect_opts.layout_hint

        frames = extract_frames(
            source_type=resolved_source_type,
            file_path=resolved_file_path,
            youtube_url=resolved_youtube_url,
            options=extract_opts,
            workspace=artifact_dir,
            runtime_info=runtime_capture,
            logger=lambda msg: _append(job_id, msg),
        )
        result["extracted_frames"] = [str(frame_path) for frame_path in frames]
        result["runtime"] = runtime_public_info(accel, ffmpeg_mode=runtime_capture.get("ffmpeg_mode"))
        source_video_path = runtime_capture.get("source_video")
        src_w, src_h = _detect_source_resolution(source_video_path=source_video_path, extracted_frames=frames)
        if src_w > 0 and src_h > 0:
            result["source_resolution"] = {"width": int(src_w), "height": int(src_h)}
            job_store.log(job_id, f"source resolution: {src_w}x{src_h}")
        job_store.set_state(job_id, JobStatus.RUNNING, 0.2, "detecting", "frame extraction completed")

        if audio_opts.enable:
            job_store.set_state(job_id, JobStatus.RUNNING, 0.3, "separating_audio", "starting audio separation")
            source_video = runtime_capture.get("source_video")
            if not source_video:
                raise RuntimeError("source video path is unavailable for audio separation")
            audio_result = separate_audio_stem(
                source_video=Path(source_video),
                options=audio_opts,
                workspace=artifact_dir / "audio",
                logger=lambda msg: _append(job_id, msg),
            )
            result.update(audio_result)
            job_store.set_state(job_id, JobStatus.RUNNING, 0.38, "rectifying", "audio separation completed")

        if not frames:
            raise RuntimeError("No frames were extracted from source")

        detections = detect_sheet_regions(
            frame_paths=frames,
            options=detect_opts,
            workspace=artifact_dir / "detect",
            source_type=payload.source_type,
            logger=lambda msg: _append(job_id, msg),
        )
        result["detections"] = len(detections)
        if not detections:
            job_store.log(job_id, "no detection candidate found; using fallback rectification path")
        job_store.set_state(job_id, JobStatus.RUNNING, 0.45, "rectifying", "sheet detection completed")

        rectified_paths = rectify_frames(
            detections=detections,
            options=rectify_opts,
            workspace=artifact_dir / "rectified",
            logger=lambda msg: _append(job_id, msg),
        )
        result["rectified_frames"] = [str(path) for path in rectified_paths]
        job_store.set_state(job_id, JobStatus.RUNNING, 0.68, "stitching", "rectification completed")

        stitched_paths = stitch_pages(
            frame_paths=rectified_paths,
            options=stitch_opts,
            workspace=artifact_dir / "stitched",
            source_type=payload.source_type,
            logger=lambda msg: _append(job_id, msg),
        )
        result["stitched_frames"] = [str(path) for path in stitched_paths]
        job_store.set_state(job_id, JobStatus.RUNNING, 0.82, "upscaling", "stitching completed")

        upscaled_paths = upscale_frames(
            frame_paths=stitched_paths,
            options=upscale_opts,
            workspace=artifact_dir / "upscaled",
            acceleration=accel,
            logger=lambda msg: _append(job_id, msg),
        )
        result["upscaled_frames"] = [str(path) for path in upscaled_paths] if upscale_opts.enable else []
        result["review_candidates"] = [str(path) for path in upscaled_paths]
        upscale_message = "upscaling completed" if upscale_opts.enable else "upscaling skipped"
        job_store.set_state(job_id, JobStatus.RUNNING, 0.92, "exporting", upscale_message)

        export_result = export_frames(
            frame_paths=upscaled_paths,
            options=export_opts,
            workspace=artifact_dir / "export",
            logger=lambda msg: _append(job_id, msg),
            source_frames=frames,
        )
        result["images"] = export_result.get("images", [])
        result["pdf"] = export_result.get("pdf")
        result["raw_frames"] = export_result.get("raw_frames", [])
        result["output_dir"] = str(artifact_dir / "export")
        job_store.set_state(
            job_id,
            JobStatus.DONE,
            1.0,
            "done",
            "export finished",
            result=result,
        )
        job_store.log(job_id, "job finished")
    except Exception as exc:
        job_store.log(job_id, f"job failed: {exc}")
        job_store.set_state(
            job_id,
            JobStatus.ERROR,
            1.0,
            "failed",
            f"job failed: {exc}",
            result=result,
            error_code="PIPELINE_ERROR",
        )


def _append(job_id: str, message: str) -> None:
    job_store.log(job_id, message)


def _find_cached_video(workspace: Path) -> Path | None:
    candidates = sorted([p for p in workspace.glob("**/*") if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".avi"}])
    return candidates[0] if candidates else None


def _preview_source_cache_workspace(youtube_url: str) -> Path:
    cache_key = hashlib.sha1(youtube_url.encode("utf-8")).hexdigest()[:16]
    cache_dir = jobs_root / "_preview_source" / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_or_prepare_cached_youtube_video(youtube_url: str, *, logger) -> tuple[Path, bool]:
    url = str(youtube_url or "").strip()
    if not url:
        raise ValueError("youtube_url is required when source_type is youtube")

    cache_dir = _preview_source_cache_workspace(url)
    cached = _find_cached_video(cache_dir)
    if cached is not None:
        return cached, True

    video_path = prepare_preview_source(
        source_type="youtube",
        file_path=None,
        youtube_url=url,
        workspace=cache_dir,
        logger=logger,
    )
    return video_path, False


def _to_jobs_files_url(path: Path) -> str | None:
    try:
        rel_path = path.relative_to(jobs_root)
        return f"/jobs-files/{rel_path.as_posix()}"
    except ValueError:
        return None


def _resolve_client_file_path(raw: str) -> Path:
    value = str(raw or "").strip()
    if value.startswith("/jobs-files/"):
        rel = value[len("/jobs-files/") :].lstrip("/")
        return jobs_root / rel
    if value.startswith("jobs-files/"):
        rel = value[len("jobs-files/") :].lstrip("/")
        return jobs_root / rel
    return Path(value).expanduser()


def _resolve_capture_path_for_job(*, job: Job, raw_path: str, must_exist: bool) -> Path:
    candidate = _resolve_client_file_path(raw_path)
    resolved = candidate.resolve()

    artifact_root = Path(job.artifact_dir).resolve()
    try:
        resolved.relative_to(artifact_root)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"capture path must be inside this job directory: {raw_path}")

    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise HTTPException(status_code=400, detail=f"capture file not found: {raw_path}")
    if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail=f"unsupported capture format: {raw_path}")
    return resolved


def _build_export_options(*, formats: List[str]):
    from app.schemas import ExportOptions

    tokens = [str(value or "").strip().lower() for value in formats]
    normalized: List[str] = []
    for token in tokens:
        if token == "jpeg":
            token = "jpg"
        if token in {"png", "jpg", "pdf"} and token not in normalized:
            normalized.append(token)
    if not normalized:
        normalized = ["png", "pdf"]
    return ExportOptions(formats=normalized, include_raw_frames=False)


def _clear_export_workspace(workspace: Path) -> None:
    image_dir = workspace / "images"
    raw_dir = workspace / "raw_frames"
    for directory in (image_dir, raw_dir):
        if not directory.exists():
            continue
        for pattern in ("*.png", "*.jpg", "*.jpeg"):
            for file_path in directory.glob(pattern):
                try:
                    file_path.unlink()
                except OSError:
                    continue
    pdf_path = workspace / "sheet_export.pdf"
    if pdf_path.exists():
        try:
            pdf_path.unlink()
        except OSError:
            pass


def _detect_source_resolution(*, source_video_path: str | None, extracted_frames: List[Path]) -> tuple[int, int]:
    if source_video_path:
        width, height = _probe_video_resolution(Path(source_video_path))
        if width > 0 and height > 0:
            return width, height

    if extracted_frames:
        frame = cv2.imread(str(extracted_frames[0]))
        if frame is not None and frame.size > 0:
            h, w = frame.shape[:2]
            if w > 0 and h > 0:
                return int(w), int(h)

    return 0, 0


def _probe_video_resolution(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 0, 0
    try:
        width = int(round(float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)))
        height = int(round(float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)))
        if width > 0 and height > 0:
            return width, height
        return 0, 0
    finally:
        cap.release()


def _cache_usage_summary() -> tuple[int, int]:
    total_bytes = 0
    total_paths = 0
    for child in jobs_root.iterdir():
        total_paths += 1
        total_bytes += _path_size_bytes(child)
    return total_paths, int(max(0, total_bytes))


def _path_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0

    total = 0
    for root, _, files in os.walk(path, topdown=True):
        for file_name in files:
            file_path = Path(root) / file_name
            try:
                total += int(file_path.stat().st_size)
            except OSError:
                continue
    return int(max(0, total))


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink()


def _human_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(0, int(size)))
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.1f} {units[idx]}"
