from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import cv2
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.job_store import Job, JobStatus, JobStore, ProgressMode, SourcePrepareJob, SourcePrepareStore
from app.schemas import (
    ArchiveLibraryItem,
    ArchiveLibraryResponse,
    CaptureCropRequest,
    CaptureCropResponse,
    CacheClearResponse,
    CacheUsageResponse,
    ExportOptions,
    JobCreate,
    JobCreateResponse,
    JobFileResponse,
    JobReviewExportRequest,
    JobReviewExportResponse,
    JobStatusResponse,
    LocalMediaRegistryItem,
    LocalMediaRegistryResponse,
    PreviewFrameRequest,
    PreviewFrameResponse,
    PreviewRoiHealthRequest,
    PreviewRoiHealthResponse,
    PreviewSourceRequest,
    PreviewSourceResponse,
    PreviewSourceJobCreateRequest,
    PreviewSourceJobCreateResponse,
    PreviewSourceJobStatusResponse,
    RuntimeStatusResponse,
)
from app.pipeline.acceleration import get_runtime_acceleration, runtime_public_info
from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin, resolve_ffprobe_bin
from app.pipeline.extract import (
    YOUTUBE_DOWNLOAD_STRATEGY_VERSION,
    extract_frames,
    extract_preview_frame,
    prepare_preview_source,
)
from app.pipeline.layout_profiles import infer_layout_hint_from_roi
from app.pipeline.roi_health import analyze_roi_health_for_source
from app.pipeline.detect import detect_sheet_regions
from app.pipeline.rectify import rectify_frames
from app.pipeline.stitch import select_review_candidates, stitch_pages
from app.pipeline.upscale import upscale_frames
from app.pipeline.export import export_frames, export_selected_pages


PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION
DRUMSHEET_SESSION_TOKEN = str(os.getenv("DRUMSHEET_SESSION_TOKEN") or "").strip()
TOKEN_HEADER_NAME = "x-drumsheet-token"
SUPPORTED_YOUTUBE_HOSTS = {
    "www.youtube.com",
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


app = FastAPI(title="Drum Sheet Capture API", version="0.1.27")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-DrumSheet-Token"],
)


jobs_root = Path(os.getenv("DRUMSHEET_JOBS_DIR", Path(__file__).resolve().parents[1] / "jobs"))
jobs_root.mkdir(parents=True, exist_ok=True)
job_store = JobStore(jobs_root)
executor = ThreadPoolExecutor(max_workers=1)
source_prepare_store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
source_prepare_executor = ThreadPoolExecutor(max_workers=1)


def _runtime_metadata() -> Dict[str, str]:
    return {
        "app_version": str(app.version),
        "preview_cache_namespace": PREVIEW_SOURCE_CACHE_NAMESPACE,
        "youtube_download_strategy": YOUTUBE_DOWNLOAD_STRATEGY_VERSION,
    }


def _requires_session_token(path: str) -> bool:
    normalized = str(path or "").strip() or "/"
    return normalized != "/health"


def _has_valid_session_token(headers, expected_token: str, query_params=None) -> bool:
    expected = str(expected_token or "").strip()
    if not expected:
        return True

    if headers is not None:
        header_value = str(headers.get(TOKEN_HEADER_NAME, "") or headers.get("X-DrumSheet-Token", "") or "").strip()
        if header_value == expected:
            return True

    if query_params is not None:
        query_value = str(query_params.get("token") or "").strip()
        if query_value == expected:
            return True
    return False


def _normalize_supported_youtube_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("youtube_url is required when source_type is youtube")

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("youtube_url must use http or https")
    host = (parsed.hostname or "").lower()
    if host not in SUPPORTED_YOUTUBE_HOSTS:
        raise ValueError("youtube_url must point to a supported YouTube host")
    return value


def _normalize_existing_file_path(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("file_path is required when source_type is file")
    path = Path(value).expanduser()
    if not path.exists():
        raise ValueError("file_path does not exist")
    if not path.is_file():
        raise ValueError("file_path must be a file")
    return str(path.resolve())


def _normalize_source_inputs(*, source_type: str, file_path: str | None, youtube_url: str | None) -> tuple[str | None, str | None]:
    if source_type == "file":
        return _normalize_existing_file_path(file_path or ""), None
    if source_type == "youtube":
        return None, _normalize_supported_youtube_url(youtube_url or "")
    raise ValueError(f"unsupported source_type: {source_type}")


def _resolve_jobs_file_path(file_path: str) -> Path:
    candidate = (jobs_root / str(file_path or "").lstrip("/")).resolve()
    try:
        candidate.relative_to(jobs_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="job file path must stay inside jobs root")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="job file not found")
    return candidate


@app.middleware("http")
async def enforce_session_token(request: Request, call_next):
    if request.method != "OPTIONS" and _requires_session_token(request.url.path):
        if not _has_valid_session_token(request.headers, DRUMSHEET_SESSION_TOKEN, request.query_params):
            return JSONResponse(status_code=401, content={"detail": "missing or invalid session token"})
    return await call_next(request)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", **_runtime_metadata()}


@app.get("/runtime", response_model=RuntimeStatusResponse)
def runtime_status() -> RuntimeStatusResponse:
    ffmpeg_bin = resolve_ffmpeg_bin(strict=platform.system().lower() == "windows")
    accel = get_runtime_acceleration(ffmpeg_bin=ffmpeg_bin)
    payload = {**runtime_public_info(accel), **_runtime_metadata()}
    return RuntimeStatusResponse(**payload)


@app.get("/jobs-files/{file_path:path}")
def read_job_file(file_path: str) -> FileResponse:
    return FileResponse(_resolve_jobs_file_path(file_path))


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


@app.get("/library/local-media", response_model=LocalMediaRegistryResponse)
def local_media_registry() -> LocalMediaRegistryResponse:
    items_by_source: Dict[str, Dict[str, Any]] = {}

    def register_entry(entry: Dict[str, Any]) -> None:
        source_path = str(entry.get("source_path") or "").strip()
        if not source_path:
            return
        if source_path in items_by_source:
            existing = items_by_source[source_path]
            basename = Path(source_path).name
            existing_display_name = str(existing.get("display_name") or "").strip()
            incoming_display_name = str(entry.get("display_name") or "").strip()
            existing["updated_at"] = max(float(existing.get("updated_at") or 0), float(entry.get("updated_at") or 0))
            if incoming_display_name and incoming_display_name != basename and (
                not existing_display_name or existing_display_name == basename
            ):
                existing["display_name"] = incoming_display_name
            if not existing.get("pdf_path") and entry.get("pdf_path"):
                existing["pdf_path"] = entry.get("pdf_path")
                existing["output_dir"] = entry.get("output_dir")
                existing["has_score"] = True
            return
        source = Path(source_path)
        width, height, duration_sec = _probe_video_metadata(source)
        items_by_source[source_path] = {
            **entry,
            "directory": str(source.parent),
            "width": int(width),
            "height": int(height),
            "duration_sec": float(duration_sec),
            "resolution_label": f"{width}x{height}" if width > 0 and height > 0 else "",
            "duration_label": _format_duration_label(duration_sec) if duration_sec > 0 else "",
            "has_score": bool(entry.get("pdf_path")),
        }

    completed_jobs: List[Dict[str, Any]] = []
    for metadata_path in sorted(job_store.root.glob("*/job.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            job = Job.from_record(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if job.status != JobStatus.DONE:
            continue
        source_path = _existing_file_path(job.file_path)
        if source_path is None:
            continue
        result = dict(job.result or {})
        pdf_path = _existing_file_path(result.get("pdf"))
        output_dir = _existing_dir_path(result.get("output_dir"))
        completed_jobs.append(
            {
                "source_path": str(source_path),
                "display_name": str((job.source_identity or {}).get("display_name") or "").strip() or source_path.name,
                "pdf_path": str(pdf_path) if pdf_path else None,
                "output_dir": str(output_dir) if output_dir else None,
                "source_origin": "job",
                "youtube_url": job.youtube_url,
                "updated_at": float(job.updated_at),
            }
        )

    completed_jobs.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    for entry in completed_jobs:
        register_entry(entry)

    prepared_sources: List[Dict[str, Any]] = []
    for metadata_path in sorted(source_prepare_store.root.glob("*/job.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            job = SourcePrepareJob.from_record(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if job.status != JobStatus.DONE:
            continue
        source_path = _existing_file_path(dict(job.result or {}).get("video_path"))
        if source_path is None:
            continue
        prepared_sources.append(
            {
                "source_path": str(source_path),
                "display_name": str(dict(job.result or {}).get("video_title") or "").strip() or source_path.name,
                "pdf_path": None,
                "output_dir": None,
                "source_origin": "prepared",
                "youtube_url": job.youtube_url,
                "updated_at": float(job.updated_at),
            }
        )

    prepared_sources.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    for entry in prepared_sources:
        register_entry(entry)

    items = [
        LocalMediaRegistryItem(**payload)
        for payload in sorted(items_by_source.values(), key=lambda item: float(item.get("updated_at") or 0), reverse=True)[:50]
    ]
    return LocalMediaRegistryResponse(items=items)


@app.get("/library/archive", response_model=ArchiveLibraryResponse)
def archive_library() -> ArchiveLibraryResponse:
    latest_by_source: Dict[str, ArchiveLibraryItem] = {}

    for metadata_path in sorted(job_store.root.glob("*/job.json")):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            job = Job.from_record(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue

        if job.status != JobStatus.DONE:
            continue

        source_identity = dict(job.source_identity or {})
        source_key = _resolve_archive_source_key(job=job, source_identity=source_identity)
        if not source_key:
            continue

        result = dict(job.result or {})
        pdf_path = _existing_file_path(result.get("pdf"))
        if pdf_path is None:
            continue

        output_dir = _existing_dir_path(result.get("output_dir"))
        display_name = str(source_identity.get("display_name") or "").strip()
        if not display_name:
            file_path = str(job.file_path or "").strip()
            youtube_url = str(job.youtube_url or "").strip()
            if file_path:
                display_name = Path(file_path).name
            elif youtube_url:
                display_name = youtube_url
            else:
                display_name = pdf_path.stem

        source_kind = str(source_identity.get("kind") or job.source_type or "file").strip().lower()
        if source_kind not in {"file", "youtube"}:
            source_kind = "file"

        completed_at = _archive_effective_timestamp(job=job, result=result)
        candidate = ArchiveLibraryItem(
            source_key=source_key,
            source_kind=source_kind,
            display_name=display_name,
            completed_at=completed_at,
            pdf_path=str(pdf_path),
            output_dir=str(output_dir) if output_dir else None,
        )
        existing = latest_by_source.get(source_key)
        if existing is None or candidate.completed_at > existing.completed_at:
            latest_by_source[source_key] = candidate

    items = sorted(latest_by_source.values(), key=lambda item: item.completed_at, reverse=True)
    return ArchiveLibraryResponse(items=items)


@app.post("/preview/frame", response_model=PreviewFrameResponse)
def preview_frame(payload: PreviewFrameRequest) -> PreviewFrameResponse:
    try:
        normalized_file_path, normalized_youtube_url = _normalize_source_inputs(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
        )

        preview_workspace = jobs_root / "_preview" / str(uuid.uuid4())
        preview_workspace.mkdir(parents=True, exist_ok=True)
        resolved_source_type = payload.source_type
        resolved_file_path = normalized_file_path
        resolved_youtube_url = normalized_youtube_url

        if payload.source_type == "youtube" and normalized_youtube_url:
            prepared = _get_or_prepare_cached_youtube_video(normalized_youtube_url, logger=lambda _: None)
            resolved_source_type = "file"
            resolved_file_path = str(prepared["video_path"])
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[preview/frame] failed for {payload.source_type}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"preview frame extraction failed: {exc}")


@app.post("/preview/roi-health", response_model=PreviewRoiHealthResponse)
def preview_roi_health(payload: PreviewRoiHealthRequest) -> PreviewRoiHealthResponse:
    try:
        normalized_file_path, normalized_youtube_url = _normalize_source_inputs(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
        )

        preview_workspace = jobs_root / "_preview_health" / str(uuid.uuid4())
        preview_workspace.mkdir(parents=True, exist_ok=True)
        resolved_source_type = payload.source_type
        resolved_file_path = normalized_file_path
        resolved_youtube_url = normalized_youtube_url

        if payload.source_type == "youtube" and normalized_youtube_url:
            prepared = _get_or_prepare_cached_youtube_video(normalized_youtube_url, logger=lambda _: None)
            resolved_source_type = "file"
            resolved_file_path = str(prepared["video_path"])
            resolved_youtube_url = None

        analysis = analyze_roi_health_for_source(
            source_type=resolved_source_type,
            file_path=resolved_file_path,
            youtube_url=resolved_youtube_url,
            start_sec=payload.start_sec,
            roi=payload.roi,
            workspace=preview_workspace,
            logger=lambda _: None,
        )
        return PreviewRoiHealthResponse(
            risk_level=str(analysis.get("risk_level") or "info"),
            summary=str(analysis.get("summary") or ""),
            diagnostics=list(analysis.get("diagnostics") or []),
            sampled_frames=int(analysis.get("sampled_frames") or 0),
            checked_seconds=[float(value) for value in analysis.get("checked_seconds", [])],
            metrics=dict(analysis.get("metrics") or {}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"preview roi health failed: {exc}")


@app.post("/preview/source", response_model=PreviewSourceResponse)
def preview_source(payload: PreviewSourceRequest) -> PreviewSourceResponse:
    try:
        if payload.source_type == "file":
            source_path = Path(_normalize_existing_file_path(payload.file_path or ""))
            return PreviewSourceResponse(video_path=str(source_path), video_url=None, from_cache=True)

        if payload.source_type == "youtube":
            normalized_youtube_url = _normalize_supported_youtube_url(payload.youtube_url or "")
            log_lines: List[str] = []
            prepared = _get_or_prepare_cached_youtube_video(
                normalized_youtube_url,
                logger=lambda line: log_lines.append(str(line or "").strip()),
            )
            video_url = _to_jobs_files_url(prepared["video_path"])
            return PreviewSourceResponse(
                video_path=str(prepared["video_path"]),
                video_url=video_url,
                from_cache=bool(prepared["from_cache"]),
                log_lines=[line for line in log_lines if line],
            )

        raise HTTPException(status_code=400, detail=f"unsupported source_type: {payload.source_type}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[preview/source] failed for {payload.source_type}: {exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"preview source preparation failed: {exc}")


@app.post("/preview/source-jobs", response_model=PreviewSourceJobCreateResponse)
def create_preview_source_job(payload: PreviewSourceJobCreateRequest) -> PreviewSourceJobCreateResponse:
    try:
        normalized_youtube_url = _normalize_supported_youtube_url(payload.youtube_url or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = f"source-{uuid.uuid4().hex[:12]}"
    artifact_dir = source_prepare_store.root / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_prepare_store.create(
        SourcePrepareJob(
            id=job_id,
            youtube_url=normalized_youtube_url,
            artifact_dir=str(artifact_dir),
        )
    )
    source_prepare_executor.submit(_run_source_prepare_job, job_id)
    return PreviewSourceJobCreateResponse(job_id=job_id)


@app.get("/preview/source-jobs/{job_id}", response_model=PreviewSourceJobStatusResponse)
def get_preview_source_job(job_id: str) -> PreviewSourceJobStatusResponse:
    job = source_prepare_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"preview source job not found: {job_id}")
    return PreviewSourceJobStatusResponse(**job.to_public_dict())


@app.post("/jobs", response_model=JobCreateResponse)
def create_job(payload: JobCreate) -> JobCreateResponse:
    try:
        normalized_file_path, normalized_youtube_url = _normalize_source_inputs(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _apply_auto_layout_hints(payload)

    job_id = str(uuid.uuid4())
    artifact_dir = jobs_root / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    job = Job(
        id=job_id,
        source_type=payload.source_type,
        file_path=normalized_file_path,
        youtube_url=normalized_youtube_url,
        options=payload.options.model_dump(),
        artifact_dir=str(artifact_dir),
        source_identity=payload.source_identity.model_dump() if payload.source_identity else {},
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


def _resolve_job_export_options(job: Job, fallback: Optional[ExportOptions] = None) -> ExportOptions:
    if isinstance(job.options, dict):
        export_opts = job.options.get("export")
        if isinstance(export_opts, dict):
            try:
                return ExportOptions.model_validate(export_opts)
            except Exception:
                pass
    if fallback is not None:
        return fallback
    return ExportOptions()


@app.post("/jobs/{job_id}/review-export", response_model=JobReviewExportResponse)
def review_export(job_id: str, payload: JobReviewExportRequest) -> JobReviewExportResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != JobStatus.DONE:
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise HTTPException(status_code=409, detail="job is still running")
        raise HTTPException(status_code=409, detail="job must be completed successfully before review export")
    if isinstance(job.result, dict) and job.result.get("review_export"):
        raise HTTPException(status_code=409, detail="review export is already applied")

    has_capture_selection = bool(payload.keep_captures)
    has_page_selection = bool(payload.keep_images)
    if has_capture_selection and has_page_selection:
        raise HTTPException(status_code=400, detail="keep_captures and keep_images cannot be used together")
    if not has_capture_selection and not has_page_selection:
        raise HTTPException(status_code=400, detail="keep_captures must include at least one capture")

    selection_mode = "captures" if has_capture_selection else "pages"
    raw_inputs = payload.keep_captures if has_capture_selection else payload.keep_images
    keep_raw = [str(path or "").strip() for path in raw_inputs]
    keep_raw = [path for path in keep_raw if path]
    if not keep_raw:
        raise HTTPException(status_code=400, detail="keep_captures must include at least one capture")

    selectable_paths = _resolve_selectable_capture_paths_for_job_ordered(
        job=job,
        preferred_keys=("review_candidates",) if selection_mode == "captures" else ("images",),
    )
    resolved_paths = _resolve_selected_capture_paths_for_job(
        job=job,
        raw_paths=keep_raw,
        selectable_paths=selectable_paths,
    )
    if not resolved_paths:
        raise HTTPException(status_code=400, detail="no valid captures selected")

    export_config = _resolve_job_export_options(job)
    configured_formats = list(export_config.formats)
    configured_page_fill_mode = export_config.page_fill_mode
    configured_document_header = export_config.document_header.model_dump() if export_config.document_header else None
    stitch_options_payload: Optional[dict[str, object]] = None
    if isinstance(job.options, dict):
        stitch_opts = job.options.get("stitch")
        if isinstance(stitch_opts, dict):
            stitch_options_payload = stitch_opts

    requested_formats = payload.formats if payload.formats is not None else configured_formats
    export_workspace = Path(job.artifact_dir) / "export"
    staged_export_workspace = _create_staged_export_workspace(target_workspace=export_workspace)

    try:
        page_paths = resolved_paths
        if selection_mode == "captures":
            stitch_opts = _build_stitch_options(stitch_options_payload)
            page_paths = stitch_pages(
                frame_paths=resolved_paths,
                options=stitch_opts,
                workspace=staged_export_workspace / "stitched",
                source_type=job.source_type,
                prepared_frames=resolved_paths,
                logger=lambda msg: _append(job_id, msg),
            )
            if not page_paths:
                raise RuntimeError("no pages available after stitching selected captures")
        export_result = export_selected_pages(
            page_paths=page_paths,
            formats=[str(value) for value in requested_formats],
            page_fill_mode=configured_page_fill_mode,
            document_header=configured_document_header,
            workspace=staged_export_workspace,
            logger=lambda msg: _append(job_id, msg),
        )
        _commit_staged_export_workspace(
            staged_workspace=staged_export_workspace,
            target_workspace=export_workspace,
        )
        export_result = _rewrite_export_result_paths(
            export_result=export_result,
            staged_workspace=staged_export_workspace,
            target_workspace=export_workspace,
        )
    except Exception as exc:
        shutil.rmtree(staged_export_workspace, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"review export failed: {exc}")

    result = dict(job.result or {})
    result["images"] = export_result.get("images", [])
    result["pdf"] = export_result.get("pdf")
    result["raw_frames"] = export_result.get("raw_frames", [])
    result["page_diagnostics"] = export_result.get("page_diagnostics", [])
    result["output_dir"] = str(export_workspace)
    result["preview_images"] = [str(path) for path in export_result.get("preview_images", [])]
    if selection_mode == "captures":
        result["review_candidates"] = [str(path) for path in resolved_paths]
    result["review_export"] = {
        "kept_count": len(resolved_paths),
        "requested_count": len(keep_raw),
        "selection_mode": selection_mode,
        "selected_captures": [str(path) for path in resolved_paths] if selection_mode == "captures" else [],
        "selected_pages": [str(path) for path in resolved_paths] if selection_mode == "pages" else [],
    }
    job_store.set_state(
        job_id,
        JobStatus.DONE,
        1.0,
        "done",
        "review export finished",
        result=result,
        error_code=None,
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
    if job.status != JobStatus.DONE:
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise HTTPException(status_code=409, detail="job is still running")
        raise HTTPException(status_code=409, detail="job must be completed successfully before capture crop")

    capture_path = _resolve_capture_path_for_job(job=job, raw_path=payload.capture_path, must_exist=True)
    result = dict(job.result or {})
    selectable_paths = _resolve_selectable_capture_paths_for_job(
        job=job,
        preferred_keys=("review_candidates", "upscaled_frames", "images"),
    )
    if selectable_paths and capture_path not in selectable_paths:
        raise HTTPException(status_code=400, detail=f"capture is not selectable for this job: {payload.capture_path}")

    if result.get("review_export"):
        raise HTTPException(status_code=409, detail="capture crop is unavailable after review export")

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
        error_code=None,
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
        _apply_auto_layout_hints(payload)
        options = payload.options
        extract_opts = options.extract
        detect_opts = options.detect
        rectify_opts = options.rectify
        stitch_opts = options.stitch
        upscale_opts = options.upscale
        export_opts = _resolve_job_export_options(job, fallback=options.export)
        runtime_capture: Dict[str, str] = {}
        resolved_source_type = payload.source_type
        normalized_file_path, normalized_youtube_url = _normalize_source_inputs(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
        )
        resolved_file_path = normalized_file_path
        resolved_youtube_url = normalized_youtube_url

        if payload.source_type == "youtube" and normalized_youtube_url:
            prepared = _get_or_prepare_cached_youtube_video(
                normalized_youtube_url,
                logger=lambda msg: _append(job_id, msg),
            )
            _append(
                job_id,
                "job source cache hit: youtube preview cache reused"
                if prepared["from_cache"]
                else "job source cache miss: youtube downloaded and cached",
            )
            resolved_source_type = "file"
            resolved_file_path = str(prepared["video_path"])
            resolved_youtube_url = None

        accel = get_runtime_acceleration(
            logger=lambda msg: _append(job_id, msg),
            ffmpeg_bin=resolve_ffmpeg_bin(strict=platform.system().lower() == "windows"),
        )

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

        review_candidate_paths = select_review_candidates(
            frame_paths=rectified_paths,
            options=stitch_opts,
            source_type=payload.source_type,
            logger=lambda msg: _append(job_id, msg),
        )

        stitched_paths = stitch_pages(
            frame_paths=rectified_paths,
            options=stitch_opts,
            workspace=artifact_dir / "stitched",
            source_type=payload.source_type,
            prepared_frames=review_candidate_paths,
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
        review_candidate_paths = review_candidate_paths or upscaled_paths or stitched_paths
        result["review_candidates"] = [str(path) for path in review_candidate_paths]
        upscale_message = "upscaling completed" if upscale_opts.enable else "upscaling skipped"
        job_store.set_state(job_id, JobStatus.RUNNING, 0.92, "exporting", upscale_message)

        configured_document_header = export_opts.document_header.model_dump() if export_opts.document_header else None
        export_result = export_frames(
            frame_paths=upscaled_paths,
            options=export_opts,
            document_header=configured_document_header,
            workspace=artifact_dir / "export",
            logger=lambda msg: _append(job_id, msg),
            source_frames=frames,
        )
        result["images"] = export_result.get("images", [])
        result["pdf"] = export_result.get("pdf")
        result["raw_frames"] = export_result.get("raw_frames", [])
        result["page_diagnostics"] = export_result.get("page_diagnostics", [])
        result["output_dir"] = str(artifact_dir / "export")
        job_store.set_state(
            job_id,
            JobStatus.DONE,
            1.0,
            "done",
            "export finished",
            result=result,
            error_code=None,
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


def _run_source_prepare_job(job_id: str) -> None:
    job = source_prepare_store.get(job_id)
    if not job:
        return

    source_prepare_store.log(job_id, "source prepare job started")
    source_prepare_store.set_state(
        job_id,
        JobStatus.RUNNING,
        stage="cache_lookup",
        progress=0.0,
        progress_mode=ProgressMode.INDETERMINATE,
        message="checking youtube cache",
        error_code=None,
    )

    try:
        prepared = _get_or_prepare_cached_youtube_video(
            job.youtube_url,
            logger=lambda msg: _append_source_prepare(job_id, msg),
            progress_callback=lambda update: _apply_source_prepare_progress(job_id, update),
        )
        source_prepare_store.set_state(
            job_id,
            JobStatus.RUNNING,
            stage="validate",
            progress=0.98,
            progress_mode=ProgressMode.INDETERMINATE,
            message="validating final source",
        )
        result = {
            "video_path": str(prepared["video_path"]),
            "video_url": _to_jobs_files_url(prepared["video_path"]),
            "from_cache": bool(prepared["from_cache"]),
            "video_title": str(prepared.get("video_title") or ""),
            "source_key": str(prepared.get("source_key") or job.youtube_url),
        }
        source_prepare_store.set_state(
            job_id,
            JobStatus.DONE,
            stage="done",
            progress=1.0,
            progress_mode=ProgressMode.DETERMINATE,
            message="youtube source ready",
            result=result,
            error_code=None,
        )
        source_prepare_store.log(job_id, "source prepare job finished")
    except Exception as exc:
        detail = str(exc)
        source_prepare_store.log(job_id, f"source prepare failed: {detail}")
        source_prepare_store.set_state(
            job_id,
            JobStatus.ERROR,
            stage="failed",
            progress=1.0,
            progress_mode=ProgressMode.INDETERMINATE,
            message=detail,
            error_code=_source_prepare_error_code(detail),
        )


def _append(job_id: str, message: str) -> None:
    job_store.log(job_id, message)


def _append_source_prepare(job_id: str, message: str) -> None:
    source_prepare_store.log(job_id, message)


def _apply_source_prepare_progress(job_id: str, update: Dict[str, Any]) -> None:
    if not update:
        return
    progress_mode = _coerce_prepare_progress_mode(update.get("progress_mode"))
    progress_value = update.get("progress")
    try:
        progress = float(progress_value) if progress_value is not None else None
    except (TypeError, ValueError):
        progress = None
    source_prepare_store.set_state(
        job_id,
        JobStatus.RUNNING,
        stage=str(update.get("stage") or "download"),
        progress=progress,
        progress_mode=progress_mode,
        message=str(update.get("message") or ""),
    )


def _coerce_prepare_progress_mode(value: object) -> ProgressMode:
    raw = str(value or ProgressMode.INDETERMINATE.value).strip().lower()
    if raw == ProgressMode.DETERMINATE.value:
        return ProgressMode.DETERMINATE
    return ProgressMode.INDETERMINATE


def _source_prepare_error_code(detail: str) -> str:
    text = str(detail or "").lower()
    if "low resolution" in text or "resolved to" in text:
        return "LOW_RESOLUTION"
    if "youtube_url" in text:
        return "INVALID_YOUTUBE_URL"
    return "SOURCE_PREPARE_ERROR"


def _find_cached_video(workspace: Path) -> Path | None:
    candidates = sorted([p for p in workspace.glob("**/*") if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".avi"}])
    if not candidates:
        return None
    candidates.sort(key=_cached_video_rank, reverse=True)
    return candidates[0]


def _preview_source_cache_workspace(youtube_url: str) -> Path:
    cache_key = hashlib.sha1(youtube_url.encode("utf-8")).hexdigest()[:16]
    cache_dir = jobs_root / "_preview_source" / PREVIEW_SOURCE_CACHE_NAMESPACE / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _read_cached_youtube_metadata(video_path: Path) -> Dict[str, str]:
    metadata_path = video_path.parent / "source.json"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "source_key": str(payload.get("source_key") or "").strip(),
        "video_title": str(payload.get("video_title") or "").strip(),
    }


def _get_or_prepare_cached_youtube_video(youtube_url: str, *, logger, progress_callback=None) -> Dict[str, object]:
    url = str(youtube_url or "").strip()
    if not url:
        raise ValueError("youtube_url is required when source_type is youtube")

    if progress_callback:
        progress_callback(
            {
                "stage": "cache_lookup",
                "progress": 0.0,
                "progress_mode": "indeterminate",
                "message": "checking youtube cache",
            }
        )

    cache_dir = _preview_source_cache_workspace(url)
    cached = _find_cached_video(cache_dir)
    if cached is not None:
        width, height = _probe_video_resolution(cached)
        if _is_invalid_cached_video(width=width, height=height):
            logger(f"youtube cache rejected: {cached.name} resolved to {width}x{height}; invalid cache, redownloading")
            try:
                cached.unlink()
            except OSError:
                pass
        elif _is_low_quality_cached_video(width=width, height=height):
            logger(f"youtube cache rejected: {cached.name} resolved to {width}x{height}; redownloading")
            try:
                cached.unlink()
            except OSError:
                pass
        else:
            logger(f"youtube cache hit: {cached.name} {width}x{height}")
            if progress_callback:
                progress_callback(
                    {
                        "stage": "validate",
                        "progress_mode": "indeterminate",
                        "message": "using cached youtube video",
                    }
                )
            cached_meta = _read_cached_youtube_metadata(cached)
            return {
                "video_path": cached,
                "from_cache": True,
                "video_title": cached_meta.get("video_title", ""),
                "source_key": cached_meta.get("source_key", "") or url,
            }

    logger("youtube cache miss: downloading source")
    video_path = prepare_preview_source(
        source_type="youtube",
        file_path=None,
        youtube_url=url,
        workspace=cache_dir,
        logger=logger,
        progress_callback=progress_callback,
    )
    metadata = _read_cached_youtube_metadata(video_path)
    return {
        "video_path": video_path,
        "from_cache": False,
        "video_title": metadata.get("video_title", ""),
        "source_key": metadata.get("source_key", "") or url,
    }


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


def _resolve_selectable_capture_paths_for_job_ordered(*, job: Job, preferred_keys: tuple[str, ...]) -> List[Path]:
    result = job.result if isinstance(job.result, dict) else {}
    for key in preferred_keys:
        raw_values = result.get(key)
        if not isinstance(raw_values, list):
            continue
        resolved_values: List[Path] = []
        seen: set[Path] = set()
        for raw_value in raw_values:
            candidate_raw = str(raw_value or "").strip()
            if not candidate_raw:
                continue
            try:
                resolved = _resolve_capture_path_for_job(job=job, raw_path=candidate_raw, must_exist=False)
            except HTTPException:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            resolved_values.append(resolved)
        if resolved_values:
            return resolved_values
    return []


def _resolve_selectable_capture_paths_for_job(*, job: Job, preferred_keys: tuple[str, ...]) -> set[Path]:
    return set(_resolve_selectable_capture_paths_for_job_ordered(job=job, preferred_keys=preferred_keys))


def _resolve_selected_capture_paths_for_job(
    *,
    job: Job,
    raw_paths: List[str],
    selectable_paths: List[Path],
) -> List[Path]:
    selectable_set = set(selectable_paths)
    requested_order: List[Path] = []
    selected_set: set[Path] = set()
    for raw_path in raw_paths:
        resolved = _resolve_capture_path_for_job(job=job, raw_path=raw_path, must_exist=True)
        if selectable_set and resolved not in selectable_set:
            raise HTTPException(status_code=400, detail=f"capture is not selectable for this job: {raw_path}")
        if resolved in selected_set:
            continue
        selected_set.add(resolved)
        requested_order.append(resolved)

    if selectable_paths:
        ordered = [path for path in selectable_paths if path in selected_set]
        if ordered:
            return ordered
    return requested_order


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


def _apply_auto_layout_hints(payload: JobCreate) -> None:
    detect_opts = payload.options.detect
    stitch_opts = payload.options.stitch
    inferred_hint = infer_layout_hint_from_roi(detect_opts.roi, source_type=payload.source_type)

    if detect_opts.layout_hint == "auto":
        detect_opts.layout_hint = inferred_hint
    if stitch_opts.layout_hint == "auto":
        stitch_opts.layout_hint = detect_opts.layout_hint if detect_opts.layout_hint != "auto" else inferred_hint


def _build_stitch_options(raw_options: Optional[dict[str, object]]):
    from app.schemas import StitchOptions

    payload = raw_options if isinstance(raw_options, dict) else {}
    return StitchOptions(**payload)


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


def _create_staged_export_workspace(*, target_workspace: Path) -> Path:
    parent = target_workspace.parent
    parent.mkdir(parents=True, exist_ok=True)
    staged_root = Path(tempfile.mkdtemp(prefix=f"{target_workspace.name}_staged_", dir=str(parent)))
    shutil.rmtree(staged_root, ignore_errors=True)
    staged_root.mkdir(parents=True, exist_ok=True)
    return staged_root


def _commit_staged_export_workspace(*, staged_workspace: Path, target_workspace: Path) -> None:
    backup_workspace = target_workspace.with_name(f"{target_workspace.name}_backup_{uuid.uuid4().hex[:8]}")
    try:
        if target_workspace.exists():
            target_workspace.replace(backup_workspace)
        staged_workspace.replace(target_workspace)
    except Exception:
        if backup_workspace.exists() and not target_workspace.exists():
            backup_workspace.replace(target_workspace)
        raise
    finally:
        shutil.rmtree(backup_workspace, ignore_errors=True)


def _rewrite_export_result_paths(
    *,
    export_result: Dict[str, object],
    staged_workspace: Path,
    target_workspace: Path,
) -> Dict[str, object]:
    rewritten = dict(export_result or {})
    for key in ("images", "preview_images", "raw_frames"):
        raw_values = rewritten.get(key)
        if not isinstance(raw_values, list):
            continue
        rewritten[key] = [
            str(_rewrite_export_result_path(value, staged_workspace=staged_workspace, target_workspace=target_workspace))
            for value in raw_values
        ]
    pdf_value = rewritten.get("pdf")
    if pdf_value:
        rewritten["pdf"] = str(
            _rewrite_export_result_path(pdf_value, staged_workspace=staged_workspace, target_workspace=target_workspace)
        )
    return rewritten


def _rewrite_export_result_path(raw_value: object, *, staged_workspace: Path, target_workspace: Path) -> Path:
    candidate = Path(str(raw_value))
    try:
        rel = candidate.relative_to(staged_workspace)
    except ValueError:
        return candidate
    return target_workspace / rel


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
    width, height = _probe_video_resolution_with_ffprobe(path)
    if width > 0 and height > 0:
        return width, height
    return _probe_video_resolution_with_opencv(path)


def _probe_video_metadata(path: Path) -> tuple[int, int, float]:
    width, height = _probe_video_resolution(path)
    duration_sec = _probe_video_duration(path)
    return width, height, duration_sec


def _cached_video_rank(path: Path) -> tuple[int, int, int]:
    width, height = _probe_video_resolution(path)
    try:
        stat = path.stat()
        mtime_ns = int(stat.st_mtime_ns)
    except OSError:
        mtime_ns = 0
    return (int(height), int(width), mtime_ns)


def _is_low_quality_cached_video(*, width: int, height: int) -> bool:
    if height > 0:
        return height <= 360
    if width > 0:
        return width <= 640
    return False


def _is_invalid_cached_video(*, width: int, height: int) -> bool:
    return width <= 0 or height <= 0


def _probe_video_resolution_with_ffprobe(path: Path) -> tuple[int, int]:
    try:
        ffprobe = resolve_ffprobe_bin(strict=False)
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except (OSError, RuntimeError, ValueError):
        return 0, 0

    if completed.returncode != 0 or not completed.stdout:
        return 0, 0

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return 0, 0

    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        return 0, 0

    stream = streams[0] if isinstance(streams[0], dict) else {}
    width = int(round(float(stream.get("width") or 0)))
    height = int(round(float(stream.get("height") or 0)))
    if width > 0 and height > 0:
        return width, height
    return 0, 0


def _probe_video_resolution_with_opencv(path: Path) -> tuple[int, int]:
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


def _probe_video_duration(path: Path) -> float:
    if not path.exists():
        return 0.0
    duration = _probe_video_duration_with_ffprobe(path)
    if duration > 0:
        return duration
    return _probe_video_duration_with_opencv(path)


def _probe_video_duration_with_ffprobe(path: Path) -> float:
    try:
        ffprobe = resolve_ffprobe_bin(strict=False)
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except (OSError, RuntimeError, ValueError):
        return 0.0

    if completed.returncode != 0 or not completed.stdout:
        return 0.0

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return 0.0

    info = payload.get("format")
    if not isinstance(info, dict):
        return 0.0

    try:
        duration = float(info.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0
    return duration if duration > 0 else 0.0


def _probe_video_duration_with_opencv(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 0.0
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps > 0 and frame_count > 0:
            return frame_count / fps
        return 0.0
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


def _existing_file_path(raw_path: object) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.exists() or not path.is_file():
        return None
    return path.resolve()


def _existing_dir_path(raw_path: object) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.exists() or not path.is_dir():
        return None
    return path.resolve()


def _resolve_archive_source_key(*, job: Job, source_identity: Dict[str, Any]) -> str:
    source_key = str(source_identity.get("key") or "").strip()
    if source_key:
        return source_key

    if str(job.source_type or "").strip().lower() == "youtube":
        return str(job.youtube_url or "").strip()

    return str(job.file_path or "").strip()


def _archive_effective_timestamp(*, job: Job, result: Dict[str, Any]) -> float:
    completed_at = float(job.completed_at) if job.completed_at is not None else 0.0
    updated_at = float(job.updated_at or 0.0)
    if result.get("review_export"):
        return max(completed_at, updated_at)
    if completed_at > 0:
        return completed_at
    return updated_at


def _format_duration_label(seconds: float) -> str:
    safe = int(max(0, round(float(seconds or 0))))
    minutes, remain = divmod(safe, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{remain:02}"
    return f"{minutes:02}:{remain:02}"
