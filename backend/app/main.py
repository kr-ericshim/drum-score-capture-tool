from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.job_store import Job, JobStatus, JobStore
from app.schemas import (
    JobCreate,
    JobCreateResponse,
    JobFileResponse,
    JobStatusResponse,
    PreviewFrameRequest,
    PreviewFrameResponse,
    RuntimeStatusResponse,
)
from app.pipeline.acceleration import get_runtime_acceleration, runtime_public_info
from app.pipeline.extract import extract_frames, extract_preview_frame
from app.pipeline.detect import detect_sheet_regions
from app.pipeline.rectify import rectify_frames
from app.pipeline.stitch import stitch_pages
from app.pipeline.upscale import upscale_frames
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


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/runtime", response_model=RuntimeStatusResponse)
def runtime_status() -> RuntimeStatusResponse:
    accel = get_runtime_acceleration()
    payload = runtime_public_info(accel)
    return RuntimeStatusResponse(**payload)


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
        image_path = extract_preview_frame(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
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
        export_opts = options.export
        runtime_capture: Dict[str, str] = {}
        accel = get_runtime_acceleration(logger=lambda msg: _append(job_id, msg))

        if stitch_opts.layout_hint == "auto" and detect_opts.layout_hint != "auto":
            stitch_opts.layout_hint = detect_opts.layout_hint

        frames = extract_frames(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
            options=extract_opts,
            workspace=artifact_dir,
            runtime_info=runtime_capture,
            logger=lambda msg: _append(job_id, msg),
        )
        result["extracted_frames"] = [str(frame_path) for frame_path in frames]
        result["runtime"] = runtime_public_info(accel, ffmpeg_mode=runtime_capture.get("ffmpeg_mode"))
        job_store.set_state(job_id, JobStatus.RUNNING, 0.2, "detecting", "frame extraction completed")

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
