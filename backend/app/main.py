from __future__ import annotations

import hashlib
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
    AudioBeatTrackRequest,
    AudioBeatTrackResponse,
    AudioSeparateRequest,
    AudioSeparateResponse,
    JobCreate,
    JobCreateResponse,
    JobFileResponse,
    JobStatusResponse,
    PreviewFrameRequest,
    PreviewFrameResponse,
    PreviewSourceRequest,
    PreviewSourceResponse,
    RuntimeStatusResponse,
)
from app.pipeline.acceleration import get_runtime_acceleration, runtime_public_info
from app.pipeline.extract import extract_frames, extract_preview_frame, prepare_preview_source
from app.pipeline.detect import detect_sheet_regions
from app.pipeline.rectify import rectify_frames
from app.pipeline.stitch import stitch_pages
from app.pipeline.upscale import upscale_frames
from app.pipeline.audio_beat import extract_audio_for_beat_input, track_beats_for_audio
from app.pipeline.audio_uvr import separate_audio_stem
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
            cache_key = hashlib.sha1(payload.youtube_url.encode("utf-8")).hexdigest()[:16]
            cache_dir = jobs_root / "_preview_source" / cache_key
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached = _find_cached_video(cache_dir)
            if cached is not None:
                video_url = _to_jobs_files_url(cached)
                return PreviewSourceResponse(video_path=str(cached), video_url=video_url, from_cache=True)

            video_path = prepare_preview_source(
                source_type=payload.source_type,
                file_path=payload.file_path,
                youtube_url=payload.youtube_url,
                workspace=cache_dir,
                logger=lambda _: None,
            )
            video_url = _to_jobs_files_url(video_path)
            return PreviewSourceResponse(video_path=str(video_path), video_url=video_url, from_cache=False)

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


@app.post("/audio/beat-track", response_model=AudioBeatTrackResponse)
def audio_beat_track(payload: AudioBeatTrackRequest) -> AudioBeatTrackResponse:
    try:
        logs: list[str] = []

        def _beat_log(message: str) -> None:
            text = str(message or "").strip()
            if text:
                logs.append(text)

        workspace = jobs_root / "_beat" / str(uuid.uuid4())
        workspace.mkdir(parents=True, exist_ok=True)

        options = payload.options
        resolved_audio_path: Path
        if payload.audio_path:
            resolved_audio_path = Path(payload.audio_path)
            if not resolved_audio_path.exists():
                raise HTTPException(status_code=400, detail="audio_path does not exist")
            _beat_log(f"beat tracking input selected: {resolved_audio_path}")
        else:
            if payload.source_type == "file":
                if not payload.file_path:
                    raise HTTPException(status_code=400, detail="file_path is required when source_type is file")
                source_path = Path(payload.file_path)
                if not source_path.exists():
                    raise HTTPException(status_code=400, detail="file_path does not exist")
            if payload.source_type == "youtube" and not payload.youtube_url:
                raise HTTPException(status_code=400, detail="youtube_url is required when source_type is youtube")

            source_video = prepare_preview_source(
                source_type=payload.source_type,
                file_path=payload.file_path,
                youtube_url=payload.youtube_url,
                workspace=workspace / "source",
                logger=_beat_log,
            )
            resolved_audio_path = workspace / "input" / "source_audio.wav"
            resolved_audio_path.parent.mkdir(parents=True, exist_ok=True)
            extract_audio_for_beat_input(source_video=source_video, audio_output=resolved_audio_path)
            _beat_log(f"beat tracking source audio extracted: {resolved_audio_path}")

        result = track_beats_for_audio(
            audio_input=resolved_audio_path,
            options=options,
            workspace=workspace / "result",
            logger=_beat_log,
        )

        beat_tsv = result.get("beat_tsv")
        beat_tsv_url = _to_jobs_files_url(Path(str(beat_tsv))) if beat_tsv else None
        return AudioBeatTrackResponse(
            audio_path=str(result.get("audio_path", resolved_audio_path)),
            beats=[float(v) for v in result.get("beats", [])],
            downbeats=[float(v) for v in result.get("downbeats", [])],
            beat_count=int(result.get("beat_count", 0)),
            downbeat_count=int(result.get("downbeat_count", 0)),
            bpm=float(result["bpm"]) if result.get("bpm") is not None else None,
            model=str(result.get("model", options.model)),
            device=str(result.get("device", "unknown")),
            beat_tsv=str(beat_tsv) if beat_tsv else None,
            beat_tsv_url=beat_tsv_url,
            log_tail=logs[-120:],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"beat tracking failed: {exc}")


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
        audio_opts = options.audio
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
            job_store.set_state(job_id, JobStatus.RUNNING, 0.38, "detecting", "audio separation completed")

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


def _find_cached_video(workspace: Path) -> Path | None:
    candidates = sorted([p for p in workspace.glob("**/*") if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".avi"}])
    return candidates[0] if candidates else None


def _to_jobs_files_url(path: Path) -> str | None:
    try:
        rel_path = path.relative_to(jobs_root)
        return f"/jobs-files/{rel_path.as_posix()}"
    except ValueError:
        return None
