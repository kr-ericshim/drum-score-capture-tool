from __future__ import annotations

import hashlib
import copy
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, RLock
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

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
    AppActivityResponse,
    ExportOptions,
    JobCreate,
    JobCreateResponse,
    JobFileResponse,
    JobReviewExportRequest,
    JobReviewExportResponse,
    JobReviewHypothesesResponse,
    JobStatusResponse,
    LocalMediaRegistryItem,
    LocalMediaRegistryResponse,
    PreviewAutoRoiRequest,
    PreviewAutoRoiResponse,
    PreviewFrameRequest,
    PreviewFrameResponse,
    PreviewLabelRegionRequest,
    PreviewLabelRegionResponse,
    PreviewRoiHealthRequest,
    PreviewRoiHealthResponse,
    PreviewSourceRequest,
    PreviewSourceResponse,
    PreviewSourceJobCreateRequest,
    PreviewSourceJobCreateResponse,
    PreviewSourceJobStatusResponse,
    ReviewExportTaskResponse,
    RuntimeStatusResponse,
)
from app import export_tasks as xt
from app.pipeline.acceleration import get_runtime_acceleration, runtime_public_info
from app.pipeline.ffmpeg_runtime import resolve_ffmpeg_bin, resolve_ffprobe_bin
from app.pipeline.extract import (
    YOUTUBE_DOWNLOAD_STRATEGY_VERSION,
    extract_frames,
    extract_preview_frame,
    prepare_preview_source,
)
from app.pipeline.layout_profiles import infer_layout_hint_from_roi, resolve_layout_hint
from app.pipeline.auto_roi_detector import estimate_auto_roi_for_source
from app.pipeline.roi_health import analyze_roi_health_for_source
try:
    from app.pipeline.roi_health import should_block_roi_capture
except ImportError:
    def should_block_roi_capture(analysis: Dict[str, object]) -> bool:
        return str(analysis.get("risk_level") or "info").strip().lower() == "critical"
from app.pipeline.detect import detect_sheet_regions
from app.pipeline.rectify import rectify_frames
from app.pipeline.overlay_composite import compose_overlay_free_captures
from app.pipeline.paper_tone import flatten_capture_backgrounds
from app.pipeline.stitch import select_review_candidates, stitch_pages
from app.pipeline.upscale import upscale_frames
from app.pipeline.export import export_frames, export_selected_pages
from app.pipeline.process_control import OperationCancelled, checkpoint, operation_scope, progress_scope, report_progress
from yt_dlp.version import __version__ as YTDLP_VERSION


# The app's only final output (docs/reflow/DECISIONS.md). Reflow modules are imported
# lazily inside the functions that use them.
REFLOW_OUTPUT_MODEL = "clean_reflow_v1"
PREVIEW_SOURCE_CACHE_NAMESPACE = YOUTUBE_DOWNLOAD_STRATEGY_VERSION
PREVIEW_FRAME_WORKSPACE_KEEP = 2
PREVIEW_FRAME_WORKSPACE_TTL_SECONDS = 30 * 60
DRUMSHEET_SESSION_TOKEN = str(os.getenv("DRUMSHEET_SESSION_TOKEN") or "").strip()
TOKEN_HEADER_NAME = "x-drumsheet-token"
SUPPORTED_YOUTUBE_HOSTS = {
    "www.youtube.com",
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


app = FastAPI(title="Drum Sheet Capture API", version="0.2.1")

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
maintenance_lock = RLock()
# Review exports (PDF rebuilds) run as background tasks, one per job at a time (export_tasks.py).
export_task_store = xt.ExportTaskStore()
export_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="review-export")
# Synchronous work such as page crops runs inside the request itself.
inflight_lock = RLock()
inflight_requests = 0
update_install_locked = False
capture_controls: Dict[str, Event] = {}
review_locks: Dict[str, RLock] = {}


def _runtime_metadata() -> Dict[str, str]:
    return {
        "app_version": str(app.version),
        "preview_cache_namespace": PREVIEW_SOURCE_CACHE_NAMESPACE,
        "youtube_download_strategy": YOUTUBE_DOWNLOAD_STRATEGY_VERSION,
        "youtube_downloader_version": YTDLP_VERSION,
    }


def _requires_session_token(path: str) -> bool:
    normalized = str(path or "").strip() or "/"
    return normalized != "/health"


def _has_valid_session_token(headers, expected_token: str) -> bool:
    expected = str(expected_token or "").strip()
    if not expected:
        return True

    if headers is not None:
        header_value = str(headers.get(TOKEN_HEADER_NAME, "") or headers.get("X-DrumSheet-Token", "") or "").strip()
        if header_value == expected:
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
    video_id = _extract_supported_youtube_video_id(parsed)
    return f"https://www.youtube.com/watch?v={video_id}"


def _extract_supported_youtube_video_id(parsed) -> str:
    host = (parsed.hostname or "").lower()
    path_parts = [unquote(part).strip() for part in parsed.path.split("/") if str(part or "").strip()]

    video_id = ""
    if host == "youtu.be":
        video_id = path_parts[0] if path_parts else ""
    elif path_parts:
        head = path_parts[0].lower()
        if head in {"embed", "shorts", "live", "v"} and len(path_parts) >= 2:
            video_id = path_parts[1]

    if not video_id:
        video_id = next((entry.strip() for entry in parse_qs(parsed.query).get("v", []) if entry.strip()), "")

    if not video_id:
        raise ValueError("youtube_url must include a video id")

    return video_id


def _best_effort_normalize_youtube_key(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    try:
        return _normalize_supported_youtube_url(value)
    except ValueError:
        return value


def _normalize_source_identity_payload(source_identity: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(source_identity or {})
    kind = str(normalized.get("kind") or "").strip().lower()
    key = str(normalized.get("key") or "").strip()
    if kind == "youtube" and key:
        normalized["key"] = _best_effort_normalize_youtube_key(key)
    return normalized


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


def _analyze_roi_health(
    *,
    source_type: str,
    file_path: str | None,
    youtube_url: str | None,
    start_sec: float | None,
    roi: List[List[float]],
    workspace: Path,
    logger,
) -> Dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    resolved_source_type = source_type
    resolved_file_path = file_path
    resolved_youtube_url = youtube_url

    if source_type == "youtube" and youtube_url:
        prepared = _coerce_prepared_youtube_source(
            _get_or_prepare_cached_youtube_video(youtube_url, logger=logger),
            fallback_url=youtube_url,
        )
        resolved_source_type = "file"
        resolved_file_path = str(prepared["video_path"])
        resolved_youtube_url = None

    return analyze_roi_health_for_source(
        source_type=resolved_source_type,
        file_path=resolved_file_path,
        youtube_url=resolved_youtube_url,
        start_sec=start_sec,
        roi=roi,
        workspace=workspace,
        logger=logger,
    )


def _enforce_roi_capture_gate(
    *,
    source_type: str,
    file_path: str | None,
    youtube_url: str | None,
    start_sec: float | None,
    roi: List[List[float]],
    workspace: Path,
    logger,
) -> Dict[str, object]:
    analysis = _analyze_roi_health(
        source_type=source_type,
        file_path=file_path,
        youtube_url=youtube_url,
        start_sec=start_sec,
        roi=roi,
        workspace=workspace,
        logger=logger,
    )
    if should_block_roi_capture(analysis):
        raise RuntimeError(f"ROI is unsafe for capture: {analysis.get('summary') or 'critical ROI diagnostics'}")
    return analysis


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
        if not _has_valid_session_token(request.headers, DRUMSHEET_SESSION_TOKEN):
            return JSONResponse(status_code=401, content={"detail": "missing or invalid session token"})
    return await call_next(request)


@app.middleware("http")
async def count_inflight_mutations(request: Request, call_next):
    global inflight_requests
    if request.method != "POST":
        return await call_next(request)
    if request.url.path in {"/maintenance/update-lock", "/maintenance/update-unlock"}:
        return await call_next(request)
    with inflight_lock:
        if update_install_locked:
            return JSONResponse(status_code=409, content={"detail": "an update is being installed"})
        inflight_requests += 1
    try:
        return await call_next(request)
    finally:
        with inflight_lock:
            inflight_requests -= 1


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
    with maintenance_lock:
        active_jobs = job_store.active_job_ids()
        active_prepare_jobs = source_prepare_store.active_job_ids()
        if active_jobs or active_prepare_jobs or export_task_store.active_count():
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

        cleared_jobs = job_store.clear_all() + source_prepare_store.clear_all()
    return CacheClearResponse(
        cleared_paths=cleared_paths,
        cleared_jobs=cleared_jobs,
        reclaimed_bytes=int(max(0, reclaimed_bytes)),
        reclaimed_human=_human_bytes(reclaimed_bytes),
        skipped_paths=skipped_paths,
    )


@app.get("/maintenance/activity", response_model=AppActivityResponse)
def app_activity() -> AppActivityResponse:
    # The desktop shell asks before stopping the backend to install an update.
    with inflight_lock:
        requests = inflight_requests
    return AppActivityResponse(
        active_jobs=len(job_store.active_job_ids()),
        active_source_jobs=len(source_prepare_store.active_job_ids()),
        inflight_requests=max(0, requests),
        active_exports=export_task_store.active_count(),
    )


@app.post("/maintenance/update-lock")
def acquire_update_lock() -> Dict[str, bool]:
    global update_install_locked
    # Request admission and the idle check use the same lock. A POST either
    # counts as active work or sees this gate closed; it cannot slip between them.
    with inflight_lock:
        if (inflight_requests or job_store.active_job_ids() or source_prepare_store.active_job_ids()
                or export_task_store.active_count()):
            raise HTTPException(status_code=409, detail="work is still running")
        update_install_locked = True
    return {"locked": True}


@app.post("/maintenance/update-unlock")
def release_update_lock() -> Dict[str, bool]:
    global update_install_locked
    with inflight_lock:
        update_install_locked = False
    return {"locked": False}


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
        source_identity = dict(job.source_identity or {})
        cached_youtube_entry = _resolve_cached_youtube_source_entry(
            youtube_url=str(job.youtube_url or ""),
            source_key=str(source_identity.get("key") or ""),
        )
        source_path = _existing_file_path(job.file_path)
        if source_path is None:
            source_path = _existing_file_path(dict(job.result or {}).get("source_video_path"))
        if source_path is None:
            source_path = _existing_file_path(cached_youtube_entry.get("source_path"))
        if source_path is None:
            continue
        source_metadata = _read_cached_youtube_metadata(source_path)
        result = dict(job.result or {})
        pdf_path = _existing_file_path(result.get("pdf"))
        output_dir = _existing_dir_path(result.get("output_dir"))
        completed_jobs.append(
            {
                "source_path": str(source_path),
                "display_name": (
                    str(source_identity.get("display_name") or "").strip()
                    or str(cached_youtube_entry.get("video_title") or "").strip()
                    or str(source_metadata.get("video_title") or "").strip()
                    or source_path.name
                ),
                "pdf_path": str(pdf_path) if pdf_path else None,
                "output_dir": str(output_dir) if output_dir else None,
                "source_origin": "job",
                "youtube_url": (
                    str(cached_youtube_entry.get("youtube_url") or "").strip()
                    or str(source_metadata.get("source_key") or "").strip()
                    or str(job.youtube_url or "").strip()
                    or None
                ),
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
        cached_youtube_entry = _resolve_cached_youtube_source_entry(
            youtube_url=str(job.youtube_url or ""),
            source_key=str(source_identity.get("key") or ""),
        )
        source_key = _resolve_archive_source_key(job=job, source_identity=source_identity)
        if not source_key:
            source_key = str(cached_youtube_entry.get("source_key") or "").strip()
        if not source_key:
            continue

        result = dict(job.result or {})
        pdf_path = _existing_file_path(result.get("pdf"))
        if pdf_path is None:
            continue

        output_dir = _existing_dir_path(result.get("output_dir"))
        source_path = _existing_file_path(job.file_path)
        if source_path is None:
            source_path = _existing_file_path(result.get("source_video_path"))
        if source_path is None:
            source_path = _existing_file_path(cached_youtube_entry.get("source_path"))
        source_metadata = _read_cached_youtube_metadata(source_path) if source_path else {}
        display_name = str(source_identity.get("display_name") or "").strip()
        if not display_name:
            display_name = str(cached_youtube_entry.get("video_title") or "").strip()
        if not display_name:
            display_name = str(source_metadata.get("video_title") or "").strip()
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
            source_path=str(source_path) if source_path else "",
            pdf_path=str(pdf_path),
            output_dir=str(output_dir) if output_dir else None,
            youtube_url=(
                str(cached_youtube_entry.get("youtube_url") or "").strip()
                or str(source_metadata.get("source_key") or "").strip()
                or str(job.youtube_url or "").strip()
                or None
            ),
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

        preview_root = jobs_root / "_preview"
        _prune_preview_workspaces(
            preview_root,
            keep=PREVIEW_FRAME_WORKSPACE_KEEP,
            max_age_seconds=PREVIEW_FRAME_WORKSPACE_TTL_SECONDS,
        )
        preview_workspace = preview_root / str(uuid.uuid4())
        preview_workspace.mkdir(parents=True, exist_ok=True)
        resolved_source_type = payload.source_type
        resolved_file_path = normalized_file_path
        resolved_youtube_url = normalized_youtube_url

        if payload.source_type == "youtube" and normalized_youtube_url:
            prepared = _coerce_prepared_youtube_source(
                _get_or_prepare_cached_youtube_video(normalized_youtube_url, logger=lambda _: None),
                fallback_url=normalized_youtube_url,
            )
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


@app.post("/preview/auto-roi", response_model=PreviewAutoRoiResponse)
def preview_auto_roi(payload: PreviewAutoRoiRequest) -> PreviewAutoRoiResponse:
    preview_workspace: Path | None = None
    try:
        normalized_file_path, normalized_youtube_url = _normalize_source_inputs(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
        )
        preview_root = jobs_root / "_preview_auto_roi"
        _prune_preview_workspaces(preview_root, keep=0)
        preview_workspace = preview_root / str(uuid.uuid4())
        preview_workspace.mkdir(parents=True, exist_ok=True)

        resolved_source_type = payload.source_type
        resolved_file_path = normalized_file_path
        resolved_youtube_url = normalized_youtube_url
        if payload.source_type == "youtube" and normalized_youtube_url:
            prepared = _coerce_prepared_youtube_source(
                _get_or_prepare_cached_youtube_video(normalized_youtube_url, logger=lambda _: None),
                fallback_url=normalized_youtube_url,
            )
            resolved_source_type = "file"
            resolved_file_path = str(prepared["video_path"])
            resolved_youtube_url = None

        result = estimate_auto_roi_for_source(
            source_type=resolved_source_type,
            file_path=resolved_file_path,
            youtube_url=resolved_youtube_url,
            start_sec=payload.start_sec,
            workspace=preview_workspace,
            logger=lambda _: None,
        )
        roi = result.get("roi")
        layout_hint = infer_layout_hint_from_roi(roi, source_type=payload.source_type) if roi else None
        return PreviewAutoRoiResponse(
            status=str(result.get("status") or "not_found"),
            roi=roi,
            evidence_level=str(result.get("evidence_level") or "low"),
            layout_hint=layout_hint,
            is_dark_mode=bool(result.get("is_dark_mode")),
            diagnostics=dict(result.get("diagnostics") or {}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"preview auto ROI failed: {exc}")
    finally:
        if preview_workspace is not None:
            shutil.rmtree(preview_workspace, ignore_errors=True)


@app.post("/preview/roi-health", response_model=PreviewRoiHealthResponse)
def preview_roi_health(payload: PreviewRoiHealthRequest) -> PreviewRoiHealthResponse:
    preview_workspace: Path | None = None
    try:
        normalized_file_path, normalized_youtube_url = _normalize_source_inputs(
            source_type=payload.source_type,
            file_path=payload.file_path,
            youtube_url=payload.youtube_url,
        )

        preview_root = jobs_root / "_preview_health"
        _prune_preview_workspaces(preview_root, keep=0)
        preview_workspace = preview_root / str(uuid.uuid4())
        preview_workspace.mkdir(parents=True, exist_ok=True)
        analysis = _analyze_roi_health(
            source_type=payload.source_type,
            file_path=normalized_file_path,
            youtube_url=normalized_youtube_url,
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
            envelope=dict(analysis.get("envelope") or {}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"preview roi health failed: {exc}")
    finally:
        if preview_workspace is not None:
            shutil.rmtree(preview_workspace, ignore_errors=True)


@app.post("/preview/label-region", response_model=PreviewLabelRegionResponse)
def preview_label_region(payload: PreviewLabelRegionRequest) -> PreviewLabelRegionResponse:
    """Section labels drawn outside the score region: an editable draft region, never applied."""
    from app.pipeline import reflow_labels

    try:
        path = _normalize_existing_file_path(payload.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        found = reflow_labels.suggest_for_video(Path(path), payload.roi, start_sec=payload.start_sec or 0.0, end_sec=payload.end_sec)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"label region check failed: {exc}")
    return PreviewLabelRegionResponse(status="suggested" if found.get("status") == "suggested" else "not_found",
                                      label_roi=found.get("label_roi"), evidence=dict(found.get("evidence") or {}),
                                      reason=str(found.get("reason") or ""))


@app.post("/preview/source", response_model=PreviewSourceResponse)
def preview_source(payload: PreviewSourceRequest) -> PreviewSourceResponse:
    try:
        if payload.source_type == "file":
            source_path = Path(_normalize_existing_file_path(payload.file_path or ""))
            return PreviewSourceResponse(video_path=str(source_path), video_url=None, from_cache=True)

        if payload.source_type == "youtube":
            normalized_youtube_url = _normalize_supported_youtube_url(payload.youtube_url or "")
            log_lines: List[str] = []
            prepared = _coerce_prepared_youtube_source(
                _get_or_prepare_cached_youtube_video(
                    normalized_youtube_url,
                    logger=lambda line: log_lines.append(str(line or "").strip()),
                ),
                fallback_url=normalized_youtube_url,
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

    with maintenance_lock:
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
    detect_opts = payload.options.detect

    normalized_source_identity = _normalize_source_identity_payload(
        payload.source_identity.model_dump() if payload.source_identity else {}
    )

    with maintenance_lock:
        job_id = str(uuid.uuid4())
        artifact_dir = (jobs_root / job_id).resolve()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        job = Job(
            id=job_id,
            source_type=payload.source_type,
            file_path=normalized_file_path,
            youtube_url=normalized_youtube_url,
            options=payload.options.model_dump(),
            artifact_dir=str(artifact_dir),
            source_identity=normalized_source_identity,
        )
        job_store.create(job)
        capture_controls[job_id] = Event()
        cancel_pending_suggestions()
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


@app.get("/jobs/{job_id}/review-hypotheses", response_model=JobReviewHypothesesResponse)
def get_review_hypotheses(job_id: str, offset: int = 0, limit: int = 100, codes: Optional[str] = None) -> JobReviewHypothesesResponse:
    with maintenance_lock:
        lock = review_locks.setdefault(job_id, RLock())
    with lock:
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        result = job.result if isinstance(job.result, dict) else {}
        output = result.get("output_dir")
        if not output and result.get("pdf"):
            output = str(Path(result["pdf"]).parent)
        export = Path(output or Path(job.artifact_dir)/"export").resolve()
        path = export/"review_hypotheses.json"
        limit = min(500, max(1, limit))
        if not path.is_file() or not (export/"ledger_report.json").is_file():
            return JobReviewHypothesesResponse(job_id=job_id, offset=0, limit=limit)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            hypotheses = payload.get("hypotheses", []) if isinstance(payload, dict) else None
        except (OSError, ValueError):
            hypotheses = None
        if not isinstance(hypotheses, list):
            # a damaged review file must not turn the finished export into an error
            return JobReviewHypothesesResponse(job_id=job_id, offset=0, limit=limit)
        if codes is not None:
            # the app asks only for the codes it shows; the full list stays for developer tools
            wanted = {c for c in codes.split(",") if c}
            hypotheses = [h for h in hypotheses if isinstance(h, dict) and h.get("code") in wanted]
        offset = min(len(hypotheses), max(0, offset))
        entries = []
        for entry in hypotheses[offset:offset+limit]:
            entry = dict(entry)
            for key in ("raw_crop", "primary_crop"):
                if entry.get(key):
                    # Also accept earlier staged absolute paths: crop files always
                    # belong to this promoted export's review_hypotheses directory.
                    entry[key] = str(export/"review_hypotheses"/Path(entry[key]).name)
            entries.append(entry)
        return JobReviewHypothesesResponse(job_id=job_id, status=payload.get("status", "unassessed"),
            export_revision=payload.get("export_revision"), counts=payload.get("counts", {}),
            total=len(hypotheses), offset=offset, limit=limit, hypotheses=entries, truncated=bool(payload.get("truncated")))


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


def _normalize_requested_export_formats(formats: List[str]) -> List[str]:
    normalized: List[str] = []
    for raw in formats:
        token = str(raw or "").strip().lower()
        if token == "jpeg":
            token = "jpg"
        if token in {"png", "jpg", "pdf"} and token not in normalized:
            normalized.append(token)
    return normalized


def review_export(job_id: str, payload: JobReviewExportRequest) -> JobReviewExportResponse:
    """The review export run to completion in the caller's thread (tests and tools).
    Over HTTP the same export runs as a background task: ``start_review_export``."""
    with maintenance_lock:
        lock = review_locks.setdefault(job_id, RLock())
    with lock:
        return _review_export(job_id, payload)


def _review_export(job_id: str, payload: JobReviewExportRequest) -> JobReviewExportResponse:
    job = _require_reflow_export_job(job_id)
    return _review_export_reflow(job, job_id, payload)


def _require_reflow_export_job(job_id: str) -> Job:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != JobStatus.DONE and not (_layout_conflict_pending(job) or _ledger_failure_pending(job)):
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise HTTPException(status_code=409, detail="job is still running")
        raise HTTPException(status_code=409, detail="job must be completed successfully before review export")
    if (job.result or {}).get("output_model") != REFLOW_OUTPUT_MODEL:
        # The clean reflow chart is the only final output (docs/reflow/DECISIONS.md). A job
        # made before it keeps its saved files, but is never rebuilt with the raw-stitch path.
        raise HTTPException(status_code=409, detail=LEGACY_JOB_DETAIL)
    return job


EXPORT_IN_PROGRESS_DETAIL = (
    "EXPORT_IN_PROGRESS: 이 악보의 PDF를 이미 다시 만들고 있습니다. 끝나거나 취소한 뒤 다시 시도하세요. "
    "/ This score's PDF is already being rebuilt. Try again after it finishes or is cancelled."
)


def _task_response(task: "xt.ExportTask") -> ReviewExportTaskResponse:
    return ReviewExportTaskResponse(**task.public())


@app.post("/jobs/{job_id}/review-export", response_model=ReviewExportTaskResponse, status_code=202)
def start_review_export(job_id: str, payload: JobReviewExportRequest) -> ReviewExportTaskResponse:
    """Start a background compose for the job's next revision and answer at once (202).

    The request is checked first (unknown job, a job still running, LEGACY_JOB, the selection and
    formats answer as before). Only one export per job runs at a time: another request meanwhile
    is refused with 409 EXPORT_IN_PROGRESS (the running task is not superseded; poll it or cancel
    it). Poll GET /jobs/{id}/review-export/{task_id}; cancel with POST .../{task_id}/cancel."""
    job = _require_reflow_export_job(job_id)
    _reflow_export_inputs(job, payload)  # selection and format errors answer now, not as a failed task
    revision = int(((job.result or {}).get("reflow") or {}).get("revision", 1)) + 1
    try:
        task = export_task_store.begin(job_id, job.artifact_dir, revision)
    except xt.ExportBusy as busy:
        raise HTTPException(status_code=409, detail=f"{EXPORT_IN_PROGRESS_DETAIL} [task {busy.task.id}]")
    try:
        _append(job_id, f"review export queued (task {task.id}, revision {revision})")
    except Exception:
        pass
    export_executor.submit(_run_review_export_task, job_id, task.id, payload)
    return _task_response(task)


@app.get("/jobs/{job_id}/review-export", response_model=ReviewExportTaskResponse)
def get_latest_review_export(job_id: str) -> ReviewExportTaskResponse:
    """The job's latest review export task (running or finished); 404 when it never had one."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    task = export_task_store.latest(job_id, job.artifact_dir)
    if task is None:
        raise HTTPException(status_code=404, detail="EXPORT_TASK_NOT_FOUND: no review export for this job")
    return _task_response(task)


@app.get("/jobs/{job_id}/review-export/{task_id}", response_model=ReviewExportTaskResponse)
def get_review_export(job_id: str, task_id: str) -> ReviewExportTaskResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    task = export_task_store.latest(job_id, job.artifact_dir)
    if task is None or task.id != task_id:
        raise HTTPException(status_code=404, detail="EXPORT_TASK_NOT_FOUND: no such review export (only the latest is kept)")
    return _task_response(task)


@app.post("/jobs/{job_id}/review-export/{task_id}/cancel", response_model=ReviewExportTaskResponse)
def cancel_review_export(job_id: str, task_id: str) -> ReviewExportTaskResponse:
    """Stop a queued or running export. The previous export and result stay as they were. An export
    already installing its files finishes (``cancel_requested`` stays true); a finished one is returned as it is."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    task = export_task_store.request_cancel(job_id, task_id)
    if task is None:
        task = export_task_store.latest(job_id, job.artifact_dir)
        if task is None or task.id != task_id:
            raise HTTPException(status_code=404, detail="EXPORT_TASK_NOT_FOUND: no such review export")
    elif task.state == xt.CANCELLED:
        try:
            _append(job_id, f"review export cancelled before it started (task {task_id})")
        except Exception:
            pass
    return _task_response(task)


def _run_review_export_task(job_id: str, task_id: str, payload: JobReviewExportRequest) -> None:
    """The background part of start_review_export: the same transactional export as the
    synchronous path, under the job's review lock, with progress and cancellation."""
    cancel = export_task_store.cancel_event(task_id)
    if cancel.is_set():
        export_task_store.update(job_id, task_id, state=xt.CANCELLED, stage="cancelled", message="cancelled",
                                 error_code=xt.EXPORT_CANCELLED)
        return
    on_progress = lambda stage, fraction: export_task_store.progress(job_id, task_id, stage, fraction)  # noqa: E731
    try:
        with maintenance_lock:
            lock = review_locks.setdefault(job_id, RLock())
        with lock, operation_scope(cancel), progress_scope(on_progress):
            export_task_store.update(job_id, task_id, state=xt.RUNNING, stage="planning", message="planning",
                                     progress=xt.stage_progress("planning", 0.0))
            job = _require_reflow_export_job(job_id)  # read again: suggestions or a crop may have changed it
            response = _review_export_reflow(job, job_id, payload)
    except OperationCancelled:
        export_task_store.update(job_id, task_id, state=xt.CANCELLED, stage="cancelled", message="cancelled",
                                 error_code=xt.EXPORT_CANCELLED)
        try:
            _append(job_id, f"review export cancelled (task {task_id}); the previous export is kept")
        except Exception:
            pass
        return
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
        export_task_store.update(job_id, task_id, state=xt.FAILED, message="failed", error=detail,
                                 error_status=int(exc.status_code), error_code=xt.error_code_for(exc.status_code, detail))
        return
    except Exception as exc:  # pragma: no cover - _review_export_reflow turns failures into HTTPException
        detail = f"review export failed: {exc}"
        export_task_store.update(job_id, task_id, state=xt.FAILED, message="failed", error=detail, error_status=500,
                                 error_code=xt.EXPORT_FAILED)
        return
    done = dict(state=xt.DONE, stage="done", progress=1.0, message="done", result=response.model_dump())
    if response.revision:
        done["revision"] = int(response.revision)
    export_task_store.update(job_id, task_id, **done)


UNCUT_STRIP_UNAVAILABLE_DETAIL = (
    "UNCUT_STRIP_UNAVAILABLE: 다음 줄이 바로 뒤에 오지 않아 오른쪽 끝을 되살려야 하는데, 원본 줄 이미지를 찾거나 다시 만들 수 없습니다. "
    "이전 내보내기는 그대로 둡니다. / The right end of a line has to be restored because the next line no longer follows it, "
    "but its full image is missing and could not be rebuilt. The previous export is kept."
)


LEGACY_JOB_DETAIL = (
    "LEGACY_JOB: this capture was made before clean charts. Its saved files are kept as they are; "
    "capture the video again to make a clean chart."
)


def legacy_review_export(job_id: str, payload: JobReviewExportRequest) -> JobReviewExportResponse:
    """The pre-reflow capture/stitch review export. Not reachable over HTTP; kept
    callable for its regression tests."""
    with maintenance_lock:
        lock = review_locks.setdefault(job_id, RLock())
    with lock:
        job = job_store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status != JobStatus.DONE:
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                raise HTTPException(status_code=409, detail="job is still running")
            raise HTTPException(status_code=409, detail="job must be completed successfully before review export")
        return _review_export_legacy(job, job_id, payload)


def _review_export_legacy(job: Job, job_id: str, payload: JobReviewExportRequest) -> JobReviewExportResponse:
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
        preferred_keys=("review_candidates",) if selection_mode == "captures" else ("original_images", "images"),
    )
    resolved_paths = _resolve_selected_capture_paths_for_job(
        job=job,
        raw_paths=keep_raw,
        selectable_paths=selectable_paths,
    )
    if not resolved_paths:
        raise HTTPException(status_code=400, detail="no valid captures selected")

    # Legacy page-only jobs store images inside the replaceable export folder.
    # Preserve the complete set once, including pages excluded in this revision.
    if selection_mode == "pages" and not job.result.get("original_images"):
        originals_dir = Path(job.artifact_dir) / "original-pages"
        originals_dir.mkdir(exist_ok=True)
        preserved = {}
        for index, source in enumerate(selectable_paths):
            target = (originals_dir / f"page_{index + 1:04d}{source.suffix}").resolve()
            shutil.copy2(source, target)
            preserved[source] = target
        resolved_paths = [preserved[path] for path in resolved_paths]
        saved_result = dict(job.result)
        saved_result["original_images"] = [str(path) for path in preserved.values()]
        job_store.set_state(job_id, job.status, result=saved_result)

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
    normalized_requested_formats = _normalize_requested_export_formats(requested_formats)
    if not normalized_requested_formats:
        raise HTTPException(status_code=400, detail="formats must include at least one export format")
    export_workspace = Path(job.artifact_dir) / "export"
    staged_export_workspace = _create_staged_export_workspace(target_workspace=export_workspace)

    try:
        edits = job.result.get("capture_edits", {})
        page_paths = [Path(edits.get(str(path), {}).get("image_path", str(path))) for path in resolved_paths]
        if selection_mode == "captures":
            stitch_opts = _build_stitch_options(stitch_options_payload)
            page_paths = stitch_pages(
                frame_paths=page_paths,
                options=stitch_opts,
                workspace=staged_export_workspace / "stitched",
                source_type=job.source_type,
                prepared_frames=page_paths,
                logger=lambda msg: _append(job_id, msg),
            )
            if not page_paths:
                raise RuntimeError("no pages available after stitching selected captures")
        export_result = export_selected_pages(
            page_paths=page_paths,
            formats=normalized_requested_formats,
            page_fill_mode=configured_page_fill_mode,
            document_header=configured_document_header,
            workspace=staged_export_workspace,
            logger=lambda msg: _append(job_id, msg),
        )
        commit = _install_staged_export_workspace(
            staged_workspace=staged_export_workspace,
            target_workspace=export_workspace,
        )
    except Exception as exc:
        shutil.rmtree(staged_export_workspace, ignore_errors=True)
        raise HTTPException(status_code=500, detail=_export_failure_detail(exc))
    previous_result = dict(job.result or {})
    try:
        export_result = _rewrite_export_result_paths(
            export_result=export_result,
            staged_workspace=staged_export_workspace,
            target_workspace=export_workspace,
        )

        result = dict(job.result or {})
        result["images"] = export_result.get("images", [])
        result["pdf"] = export_result.get("pdf")
        result["raw_frames"] = export_result.get("raw_frames", [])
        result["page_diagnostics"] = export_result.get("page_diagnostics", [])
        result["dropped_pages"] = export_result.get("dropped_pages", [])
        result["output_dir"] = str(export_workspace)
        result["preview_images"] = [str(path) for path in export_result.get("preview_images", [])]
        if selection_mode == "captures":
            # Keep every candidate, including excluded ones, with canonical paths.
            result["review_candidates"] = [str(path) for path in selectable_paths]
        result["review_export"] = {
            "revision": int(result.get("review_export", {}).get("revision", 0)) + 1,
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
    except Exception as exc:
        _revert_after_metadata_failure(job_id, commit, previous_result, exc)
    commit.finalize()

    return JobReviewExportResponse(
        images=[str(path) for path in export_result.get("images", [])],
        pdf=str(export_result.get("pdf")) if export_result.get("pdf") else None,
        output_dir=str(export_workspace),
        kept_count=len(resolved_paths),
    )


@app.post("/jobs/{job_id}/capture-crop", response_model=CaptureCropResponse)
def crop_capture(job_id: str, payload: CaptureCropRequest) -> CaptureCropResponse:
    if export_task_store.is_active(job_id):
        # the export holds this job's review lock; answer now instead of waiting behind it
        raise HTTPException(status_code=409, detail=EXPORT_IN_PROGRESS_DETAIL)
    with maintenance_lock:
        lock = review_locks.setdefault(job_id, RLock())
    with lock:
        return _crop_capture(job_id, payload)


def _crop_capture(job_id: str, payload: CaptureCropRequest) -> CaptureCropResponse:
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

    if Path(job.artifact_dir, "export").resolve() in capture_path.parents:
        raise HTTPException(status_code=409, detail="edit the original capture, not an exported preview")

    if not payload.roi:
        image = cv2.imread(str(capture_path))
        if image is None:
            raise HTTPException(status_code=400, detail="capture file could not be read")
        edits = dict(result.get("capture_edits", {}))
        edits.pop(str(capture_path), None)
        result["capture_edits"] = edits
        job_store.set_state(job_id, job.status, result=result)
        return CaptureCropResponse(capture_path=str(capture_path), width=image.shape[1], height=image.shape[0])

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

    edit_dir = Path(job.artifact_dir) / "capture-edits"
    edit_dir.mkdir(exist_ok=True)
    edited_path = edit_dir / f"{uuid.uuid4().hex}.png"
    if not cv2.imwrite(str(edited_path), cropped):
        raise HTTPException(status_code=500, detail="failed to save cropped capture")

    edits = dict(result.get("capture_edits", {}))
    edits[str(capture_path)] = {"image_path": str(edited_path), "roi": payload.roi}
    result["capture_edits"] = edits

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
        capture_path=str(edited_path),
        width=int(x2 - x1),
        height=int(y2 - y1),
    )


@app.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
def cancel_job(job_id: str) -> JobStatusResponse:
    with maintenance_lock:
        job = job_store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            control = capture_controls.get(job_id)
            if control is None:
                raise HTTPException(status_code=409, detail="worker is no longer available; reload the job")
            control.set()
            job_store.set_state(job_id, job.status, current_step="cancelling", message="cancelling capture")
        elif job.status == JobStatus.DONE or _layout_conflict_pending(job):
            # the chart is done (or waits for review); this only stops pending similar-system suggestions
            cancel_pending_suggestions(job_id)
        return JobStatusResponse(**job.to_public_dict())


def _run_job(job_id: str, payload: JobCreate, *, legacy_pipeline: bool = False) -> None:
    """Run a capture job. ``legacy_pipeline`` (the pre-reflow raw-stitch path) is not
    reachable over HTTP; it stays callable for its regression tests only."""
    with maintenance_lock:
        control = capture_controls.setdefault(job_id, Event())
    try:
        with operation_scope(control):
            _execute_job(job_id, payload, legacy_pipeline=legacy_pipeline)
    except OperationCancelled:
        job_store.set_state(job_id, JobStatus.CANCELLED, current_step="cancelled", message="capture cancelled", error_code=None)
    finally:
        with maintenance_lock:
            capture_controls.pop(job_id, None)
        try:
            _cleanup_ended_job_workspace(job_id)
        except Exception as exc:  # pragma: no cover - cleanup never changes the job's outcome
            try:
                _append(job_id, f"workspace cleanup skipped: {exc}")
            except Exception:
                pass


# Heavy intermediates (decoded frames, image/array caches) that a failed, refused or cancelled job
# no longer needs: they can be decoded again from the source. JSON records and logs stay.
HEAVY_WORKSPACE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".npy", ".npz",
                            ".mp4", ".mkv", ".webm", ".mov", ".avi", ".raw", ".bin", ".tmp"}
# Result strips, label patches and repair revisions (including unpublished candidates)
# remain available in every prune mode, including after a failed review export.
REVIEW_WORKSPACE_DIRS = (("reflow", "strips"), ("reflow", "labels"), ("reflow_revisions",))
# small diagnostics shown with a failed job (ROI health samples), kept in every case
KEPT_DIAGNOSTIC_DIRS = (("roi-health",),)


def _dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def prune_job_workspace(artifact_dir: Path, *, keep_review: bool, keep_ledger: bool = False) -> Dict[str, Any]:
    """Delete heavy intermediates from an ended (error, refused or cancelled) job's folder.

    Removed: staged export folders left by an interrupted export (``export_staged_*``) and every
    file with a HEAVY_WORKSPACE_SUFFIXES suffix outside ``export/`` and the kept diagnostics, e.g.
    ``reflow/manifest/frames``. The strips and label patches (REVIEW_WORKSPACE_DIRS) stay, so a
    LAYOUT_CONFLICT job (``keep_review``, recorded) remains reviewable and a fail-closed job keeps its
    strips unchanged. Published repair revisions and unpublished candidates stay as well.
    JSON, logs and the job record stay. Returns the sizes."""
    artifact_dir = Path(artifact_dir).resolve()
    before = _dir_size(artifact_dir) if artifact_dir.is_dir() else 0
    removed = 0
    if artifact_dir.is_dir():
        for child in artifact_dir.iterdir():
            if child.is_dir() and child.name.startswith("export_staged_"):
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        keep_dirs = ([artifact_dir.joinpath(*parts) for parts in KEPT_DIAGNOSTIC_DIRS + REVIEW_WORKSPACE_DIRS]
                     + [artifact_dir / "export"])
        if keep_ledger:
            keep_dirs.extend(artifact_dir.rglob("ledger_evidence"))
            for ledger_path in artifact_dir.rglob("ledger_base.json"):
                try:
                    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                    keep_dirs.extend(Path(o["frame_path"]).resolve() for o in ledger.get("observations",[]) if o.get("frame_path"))
                except (OSError,ValueError,TypeError,KeyError):
                    # An unreadable inventory cannot identify which frames are disposable.
                    keep_dirs.append(ledger_path.parent/"manifest")

        for f in sorted(artifact_dir.rglob("*")):
            if not f.is_file() or f.is_symlink() or f.suffix.lower() not in HEAVY_WORKSPACE_SUFFIXES:
                continue
            if any(k == f or k in f.parents for k in keep_dirs):
                continue
            try:
                f.unlink()
                removed += 1
            except OSError:
                continue
        # folders emptied above (e.g. reflow/manifest/frames)
        for d in sorted((x for x in artifact_dir.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True):
            if any(k == d or k in d.parents for k in keep_dirs):
                continue
            try:
                d.rmdir()
            except OSError:
                pass
    after = _dir_size(artifact_dir) if artifact_dir.is_dir() else 0
    return {"bytes_before": before, "bytes_after": after, "removed": removed, "kept_for_review": bool(keep_review)}


def _cleanup_ended_job_workspace(job_id: str) -> Optional[Dict[str, Any]]:
    """After a job ends in error, refusal or cancel, drop its heavy intermediates (prune_job_workspace).
    A done job is left alone (its frames are pruned after the suggestions step)."""
    job = job_store.get(job_id)
    if not job or job.status not in {JobStatus.ERROR, JobStatus.CANCELLED}:
        return None
    with maintenance_lock:
        lock = review_locks.setdefault(job_id, RLock())
    with lock:
        # A review export can finish after the initial check while cleanup waits.
        job = job_store.get(job_id)
        if not job or job.status not in {JobStatus.ERROR, JobStatus.CANCELLED}:
            return None
        reflow = (job.result or {}).get("reflow") or {}
        keep_ledger = job.error_code == "LEDGER_VERIFICATION_FAILED" or reflow.get("state") == "ledger_failed" or reflow.get("ledger_summary",{}).get("status") == "fail"
        report = prune_job_workspace(Path(job.artifact_dir), keep_review=_layout_conflict_pending(job), keep_ledger=keep_ledger)
        if report["removed"]:
            _append(job_id, f"workspace pruned after {job.status.value}: {report['bytes_before'] / 1e6:.1f} MB -> "
                            f"{report['bytes_after'] / 1e6:.1f} MB ({report['removed']} items)")
        result = dict(job.result or {})
        result["workspace_cleanup"] = report
        job_store.set_state(job_id, job.status, result=result)
        return report


def _execute_job(job_id: str, payload: JobCreate, *, legacy_pipeline: bool = False) -> None:
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
            prepared = _coerce_prepared_youtube_source(
                _get_or_prepare_cached_youtube_video(normalized_youtube_url, logger=lambda msg: _append(job_id, msg)),
                fallback_url=normalized_youtube_url,
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
        if resolved_file_path:
            result["source_video_path"] = str(resolved_file_path)

        result["roi_health"] = _analyze_roi_health(
            source_type=resolved_source_type,
            file_path=resolved_file_path,
            youtube_url=resolved_youtube_url,
            start_sec=extract_opts.start_sec,
            roi=detect_opts.roi,
            workspace=artifact_dir / "roi-health",
            logger=lambda msg: _append(job_id, msg),
        )
        roi_health = result["roi_health"] if isinstance(result["roi_health"], dict) else {}
        for diagnostic in roi_health.get("diagnostics", []):
            level = str(diagnostic.get("level") or "info").strip().lower() or "info"
            title = str(diagnostic.get("title") or diagnostic.get("code") or "roi-diagnostic").strip()
            detail = str(diagnostic.get("detail") or "").strip()
            if detail:
                _append(job_id, f"roi health [{level}] {title}: {detail}")
            else:
                _append(job_id, f"roi health [{level}] {title}")

        if not legacy_pipeline:
            _execute_reflow_job(
                job_id=job_id,
                job=job,
                payload=payload,
                result=result,
                video_path=resolved_file_path,
                export_opts=export_opts,
            )
            return

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
            progress_callback=lambda update: _apply_export_extract_progress(job_id, update),
        )
        checkpoint()
        result["extracted_frames"] = [str(frame_path) for frame_path in frames]
        result["runtime"] = runtime_public_info(accel, ffmpeg_mode=runtime_capture.get("ffmpeg_mode"))
        source_video_path = runtime_capture.get("source_video")
        if source_video_path:
            result["source_video_path"] = str(source_video_path)
        src_w, src_h = _detect_source_resolution(source_video_path=source_video_path, extracted_frames=frames)
        if src_w > 0 and src_h > 0:
            result["source_resolution"] = {"width": int(src_w), "height": int(src_h)}
            job_store.log(job_id, f"source resolution: {src_w}x{src_h}")
        job_store.set_state(job_id, JobStatus.RUNNING, 0.2, "detecting", "frame extraction completed")

        if not frames:
            raise RuntimeError("No frames were extracted from source")

        checkpoint()
        detections = detect_sheet_regions(
            frame_paths=frames,
            options=detect_opts,
            workspace=artifact_dir / "detect",
            source_type=payload.source_type,
            logger=lambda msg: _append(job_id, msg),
        )
        result["detections"] = len(detections)
        result["region_adjustments"] = [
            {"frame_index": item.get("frame_index"), "roi": item.get("roi"), **item.get("auto_fit", {})}
            for item in detections if item.get("auto_fit", {}).get("status") == "adjusted"
        ]
        if not detections:
            job_store.log(job_id, "no detection candidate found; using fallback rectification path")
        job_store.set_state(job_id, JobStatus.RUNNING, 0.45, "rectifying", "sheet detection completed")

        checkpoint()
        rectified_paths = rectify_frames(
            detections=detections,
            options=rectify_opts,
            workspace=artifact_dir / "rectified",
            logger=lambda msg: _append(job_id, msg),
        )
        result["rectified_frames"] = [str(path) for path in rectified_paths]
        job_store.set_state(job_id, JobStatus.RUNNING, 0.68, "stitching", "rectification completed")

        checkpoint()
        dedupe_report: dict = {}
        review_candidate_paths = select_review_candidates(
            frame_paths=rectified_paths,
            options=stitch_opts,
            source_type=payload.source_type,
            logger=lambda msg: _append(job_id, msg),
            report=dedupe_report,
        )
        original_candidate_paths = review_candidate_paths
        overlay_composites: Dict[str, List[str]] = {}
        if stitch_opts.remove_overlays:
            review_candidate_paths = compose_overlay_free_captures(
                kept_paths=review_candidate_paths,
                groups=dedupe_report.get("observation_groups", {}),
                layout_mode=resolve_layout_hint(stitch_opts.layout_hint, source_type=payload.source_type),
                workspace=artifact_dir / "clean",
                logger=lambda msg: _append(job_id, msg),
                report=overlay_composites,
            )
        result["overlay_composites"] = overlay_composites
        if stitch_opts.flatten_background:
            review_candidate_paths = flatten_capture_backgrounds(
                paths=review_candidate_paths,
                workspace=artifact_dir / "clean",
                logger=lambda msg: _append(job_id, msg),
            )
        composed_path_map = {
            str(original): str(composed)
            for original, composed in zip(original_candidate_paths, review_candidate_paths)
        }
        # Cleaned capture -> the rectified capture it replaced, so originals stay
        # traceable (and restorable) whichever cleanup step produced the file.
        result["clean_capture_sources"] = {
            composed: original for original, composed in composed_path_map.items() if composed != original
        }
        # Frames kept although they look almost identical to the previous kept
        # frame (few note heads changed, or the playhead jumped back): the review
        # screen can present these pairs instead of the pipeline guessing.
        result["similar_capture_pairs"] = [
            {
                **pair,
                "kept": composed_path_map.get(pair["kept"], pair["kept"]),
                "candidate": composed_path_map.get(pair["candidate"], pair["candidate"]),
            }
            for pair in dedupe_report.get("similar_pairs", [])
        ]

        from app.pipeline.export import diagnose_capture_sequence
        result["capture_diagnostics"] = diagnose_capture_sequence(review_candidate_paths)
        excluded_paths = {
            path for path in review_candidate_paths
            if result["capture_diagnostics"].get(str(path), {}).get("recommended_action") == "exclude"
        }
        accepted_paths = [path for path in review_candidate_paths if path not in excluded_paths]
        result["auto_excluded_captures"] = [str(path) for path in review_candidate_paths if path in excluded_paths]
        result["capture_classification_summary"] = {
            label: sum(item["score_classification"] == label for item in result["capture_diagnostics"].values())
            for label in ("score", "non_score", "uncertain")
        }
        job_store.log(
            job_id, f"score screening: {len(accepted_paths)} retained, "
            f"{len(excluded_paths)} excluded; originals available for review",
        )

        checkpoint()
        stitched_paths = stitch_pages(
            frame_paths=rectified_paths,
            options=stitch_opts,
            workspace=artifact_dir / "stitched",
            source_type=payload.source_type,
            prepared_frames=accepted_paths,
            logger=lambda msg: _append(job_id, msg),
        )
        result["stitched_frames"] = [str(path) for path in stitched_paths]
        job_store.set_state(job_id, JobStatus.RUNNING, 0.82, "upscaling", "stitching completed")

        checkpoint()
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
        checkpoint()
        if upscaled_paths:
            export_result = export_frames(
                frame_paths=upscaled_paths,
                options=export_opts,
                document_header=configured_document_header,
                workspace=artifact_dir / "export",
                logger=lambda msg: _append(job_id, msg),
                source_frames=frames,
            )
        elif accepted_paths:
            raise RuntimeError("retained captures produced no pages for export")
        else:
            export_result = {"images": [], "pdf": None, "raw_frames": [], "page_diagnostics": [], "dropped_pages": []}
            (artifact_dir / "export").mkdir(parents=True, exist_ok=True)
            if export_opts.include_raw_frames:
                raw_dir = artifact_dir / "export" / "raw_frames"
                raw_dir.mkdir(parents=True, exist_ok=True)
                for index, source_path in enumerate(frames):
                    checkpoint()
                    target = raw_dir / f"raw_{index:05d}.png"
                    shutil.copy2(source_path, target)
                    export_result["raw_frames"].append(str(target))
            job_store.log(job_id, "all captures excluded by score screening; review originals to restore captures")
        checkpoint()
        result["images"] = export_result.get("images", [])
        result["pdf"] = export_result.get("pdf")
        result["raw_frames"] = export_result.get("raw_frames", [])
        result["page_diagnostics"] = export_result.get("page_diagnostics", [])
        result["dropped_pages"] = export_result.get("dropped_pages", [])
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
    except OperationCancelled:
        raise
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


REFLOW_PROGRESS = {
    "sampling": (0.05, 0.45),
    "tracking": (0.46, 0.55),
    "assembling": (0.56, 0.6),
    "cleaning": (0.6, 0.85),
}


def _printable_title(text: str) -> str:
    """Drop emoji and pictographs (no glyph in the score fonts) from a video title."""
    import unicodedata

    kept = []
    for ch in str(text or ""):
        cp = ord(ch)
        if unicodedata.category(ch) in ("So", "Cs", "Co", "Cn") or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D or cp >= 0x1F000:
            continue
        kept.append(ch)
    return " ".join("".join(kept).split())


def _default_reflow_header(job: Job, payload: JobCreate, export_opts: ExportOptions) -> Dict[str, Any]:
    """Editable header: the user's document header, else the video title as the title."""
    if export_opts.document_header is not None:
        return export_opts.document_header.model_dump()
    identity = job.source_identity if isinstance(job.source_identity, dict) else {}
    title = _printable_title(identity.get("display_name") or "")
    if not title and payload.file_path:
        title = _printable_title(Path(str(payload.file_path)).stem)
    return {"title": title} if title else {}


REFLOW_ISSUE_REASONS = (
    # the review shows the first matching reason, so the order is by notation impact: a possibly
    # repeated, missing or reordered measure first, then an action the user must take, then what a
    # line is (another moment, a brief display), and cosmetic or source notes last
    ("JUMP_SEAM_UNVERIFIED", "화면이 넘어간 지점을 확인하지 못해 양쪽을 모두 남겼습니다. 마디가 겹치거나 이어지지 않을 수 있습니다 / The view jump here could not be verified, so both sides are kept; a measure may repeat or a join may be missing"),
    ("CONTENT_LOST_IN_FINISHING", "정리 과정에서 표시 일부가 사라졌어요. 확인이 필요해요 / Some marks were lost during cleanup. Please check"),
    ("JUMP_OVERLAP_CONTENT_CONFLICT", "겹치는 화면끼리 내용이 달라 다른 버전을 함께 보관했어요 / Overlapping views disagree; the other version is kept as an alternate"),
    ("LAYOUT_CONFLICT", "페이지보다 커서 지금 크기로는 배치할 수 없습니다 / Does not fit the page at this staff size"),
    ("REPLAY_CANDIDATE", "앞에서 이미 나온 줄과 똑같습니다. D.S./반복으로 다시 연주하는 부분이면 체크를 해제해 빼세요 / Identical to lines shown earlier; if it is a D.S./repeat replay, untick it to leave it out"),
    ("LINE_BELOW_MIN_SIZE", "이 줄은 인쇄하기에 작게 축소되었습니다(오선 간격 {mm} mm) / This line is printed below the readable size (staff gap {mm} mm)"),
    ("FORCED_LINE_BREAK", "줄이 너무 길어 마디선에서 나눴습니다. 마디선을 지나던 선(크레셴도 등)이 다음 줄로 이어집니다 / This line was too long, so it was split at a barline; a line crossing it continues on the next line"),
    ("LEDGER_VERIFICATION_FAILED", "PDF 보존 검증에 실패했어요. 선택을 확인하고 다시 만들어 주세요 / PDF preservation verification failed. Check the selection and rebuild"),
    ("LEDGER_REVIEW_REQUIRED", "원본 표시가 PDF에 보존되었는지 확인이 필요해요 / Source-to-PDF preservation needs review"),
    ("LEDGER_UNASSESSED", "원본 표시와 PDF의 보존 검증 자료가 없어 확인이 필요해요 / Source-to-PDF evidence is missing. Please review"),
    ("DELIVERED_PDF_UNASSESSED", "PDF가 없어 최종 PDF 보존 검증을 하지 못했어요 / No PDF was produced; delivered PDF preservation is unassessed"),
    ("OVERLAY_COVERS_NOTATION", "화면 표시가 음표에 닿아 그대로 두었어요. 확인이 필요해요 / Screen overlay touches notation; kept as is. Please check"),
    ("OVERLAY_UNRECOVERED", "화면 표시에 가려진 악보를 복구하지 못했어요. 원본을 확인해 주세요 / Notation obscured by a screen overlay could not be recovered. Please review the source"),
    ("PREVIEW_TAIL_UNVERIFIED", "오른쪽 끝에 다음 줄의 시작이 함께 보일 수 있습니다 / The right end may also show the start of the next line"),
    ("SECTION_LABEL_NOT_PLACED", "이 구간 표시가 실린 줄이 모두 빠져 표시가 출력되지 않았습니다 / Every line of this section is excluded, so its label is not printed"),
    ("MINORITY_CONTENT_DROPPED", "잠깐만 보인 표시가 이 줄에서 빠졌습니다. 바로 뒤 '다른 순간'에 있습니다 / Marks shown only for a moment are left out here; see the other moment that follows"),
    ("CONTENT_STEP_STATE", "같은 줄의 다른 상태입니다. 표시가 조금 다릅니다 / Another state of the line above; a few marks differ"),
    ("MINORITY_ALTERNATE", "같은 줄의 다른 순간입니다. 앞 줄에서 빠진 표시가 보입니다 / Another moment of the line above, with the marks it leaves out"),
    ("SHORT_DISPLAY", "짧게 스친 화면입니다 / Shown only briefly"),
    ("REPLAY_COLLAPSED", "앞에서 이미 나온 줄을 다시 연주한 부분이라 빼 두었습니다(D.S./반복). 필요하면 다시 넣을 수 있습니다 / A replay of lines already shown earlier (D.S./repeat), left out; you can add it back"),
    ("PREVIEW_TAIL_RESTORED", "다음 줄이 바로 뒤에 오지 않아 오른쪽 끝의 미리보기를 남겼습니다 / The next line no longer follows, so the preview at the right end is kept"),
    ("SOURCE_CLIPPED", "원본 영상에서 가장자리가 잘려, 보이는 부분만 담았어요 / Cut off at the edge of the source video; only the visible part is kept"),
    ("UNCERTAIN_MARK_KEPT", "잠깐만 보인 흐린 표시를 지우지 않고 남겼어요. 확인이 필요해요 / A faint mark seen only briefly was kept. Please check"),
    ("TRANSLUCENT_PLATE_GRAY", "반투명 배경 위 회색 표시는 배경과 구분이 어려워요. 확인이 필요해요 / Gray marks on a see-through background are hard to tell from it. Please check"),
    ("LOW_CONTRAST_CONTENT_KEPT", "흐린 표시를 배경과 구분하지 못해 그대로 두었어요. 확인이 필요해요 / Faint marks could not be told apart from the background; kept as is. Please check"),
    ("LABELS_OUTSIDE_ROI", "악보 영역 밖의 구간 표시가 빠졌을 수 있습니다 / A section label outside the score region may be missing"),
)


def _reason_rank(code: str) -> int:
    """Position of ``code`` in REFLOW_ISSUE_REASONS (by notation impact); other codes after them."""
    return next((i for i, (c, _t) in enumerate(REFLOW_ISSUE_REASONS) if c == code), len(REFLOW_ISSUE_REASONS))


def _reflow_capture_fields(reflow: Dict[str, Any]) -> Dict[str, Any]:
    """Result fields the review screen reads (strip paths stand in for captures)."""
    systems = reflow.get("systems", [])
    size_codes = {c for s in systems for c in s.get("issues", [])
                  if c in ("FORCED_LINE_BREAK", "LINE_BELOW_MIN_SIZE")}
    reason_text = dict(REFLOW_ISSUE_REASONS)
    small_gaps = [s["effective_staff_gap_mm"] for s in systems
                  if "LINE_BELOW_MIN_SIZE" in s.get("issues", []) and s.get("effective_staff_gap_mm") is not None]
    if small_gaps:
        reason_text["LINE_BELOW_MIN_SIZE"] = reason_text["LINE_BELOW_MIN_SIZE"].replace("{mm}", f"{min(small_gaps):.3f}")
    path_of = {s["id"]: s["strip_path"] for s in systems}
    conflict_ids = {c.get("system_id") for c in (reflow.get("layout_conflict") or {}).get("conflicts", [])}
    deps = reflow.get("dependencies") or {}
    unplaced_label_ids = {sid for u in deps.get("labels_unplaced", []) for sid in u.get("systems", [])}
    restored_ids = {r.get("system_id") for r in deps.get("preview_tails_restored", []) if not r.get("error")}
    diagnostics: Dict[str, Dict[str, Any]] = {}
    for s in systems:
        codes = list(s.get("issues", []))
        if s["id"] in conflict_ids and "LAYOUT_CONFLICT" not in codes:
            codes.insert(0, "LAYOUT_CONFLICT")
        if s["id"] in unplaced_label_ids:
            codes.append("SECTION_LABEL_NOT_PLACED")
        if s["id"] in restored_ids:
            codes.append("PREVIEW_TAIL_RESTORED")
        reasons = [text for code, text in REFLOW_ISSUE_REASONS if code in codes
                   # a content-step state is listed like an "other moment" but is described as another state
                   and not (code == "MINORITY_ALTERNATE" and "CONTENT_STEP_STATE" in codes)]
        if "LINE_BELOW_MIN_SIZE" in codes:
            mm = s.get("effective_staff_gap_mm")
            reasons = [t.replace("{mm}", f"{mm:.3f}" if mm is not None else "?") for t in reasons]
        minority = (s.get("strip") or {}).get("minority_content") or {}
        extra: Dict[str, Any] = {}
        if s.get("alternate_of"):
            extra["alternate_of"] = s["alternate_of"]
            extra["alternate_of_path"] = path_of.get(s["alternate_of"])
        if minority.get("events"):
            # what the main strip leaves out: boxes (strip pixels), times and the alternate that shows it
            # alternates are numbered per placed system (an alternate's own alternates included)
            parent = s.get("alternate_of") or s["id"]
            extra["minority_content"] = [{"box_strip": e.get("box_strip"), "times": e.get("times"),
                                          "alternate": f"{parent}-{e['alternate']}" if e.get("alternate") else None}
                                         for e in minority["events"]]
            extra["alternate_paths"] = [path_of[f"{a.get('parent_id', parent)}-{a['suffix']}"] for a in minority.get("alternates", [])
                                        if f"{a.get('parent_id', parent)}-{a['suffix']}" in path_of]
        diagnostics[s["strip_path"]] = {
            **extra,
            **({"source_clipped": s["source_clipped"]} if s.get("source_clipped") else {}),
            "suspicious": bool(codes),
            "diagnostic_codes": codes,
            "warning_reasons": reasons,
            "recommended_action": "exclude" if not s.get("included", True) else "keep",
            "score_classification": "score",
            "system_id": s["id"],
            "t_start": s.get("t_start"),
            "t_end": s.get("t_end"),
        }
    pairs = []
    for d in reflow.get("duplicate_suggestions", []):
        if d.get("system_id") in path_of and d.get("of_system_id") in path_of:
            # Appearance only: "looks similar", never an established duplicate.
            pairs.append({"kept": path_of[d["of_system_id"]], "candidate": path_of[d["system_id"]], "reason": "looks_similar",
                          "metrics": {"reason": "looks_similar", "basis": d.get("basis")}})
    return {
        "review_candidates": [s["strip_path"] for s in systems],
        "auto_excluded_captures": [s["strip_path"] for s in systems if not s.get("included", True)],
        "capture_diagnostics": diagnostics,
        "similar_capture_pairs": pairs,
        "review_required": bool(reflow.get("review_required") or size_codes),
        # The renderer accepts {code, text}; include bilingual fallback copy for
        # new ledger reasons without requiring a renderer release in lockstep.
        "review_reasons": [{"code": reason, "text": reason_text[reason]}
                           if reason in ("LEDGER_UNASSESSED", "LEDGER_REVIEW_REQUIRED", "LEDGER_VERIFICATION_FAILED",
                                         "DELIVERED_PDF_UNASSESSED", "OVERLAY_UNRECOVERED", "OVERLAY_COVERS_NOTATION",
                                         "FORCED_LINE_BREAK", "LINE_BELOW_MIN_SIZE", "JUMP_SEAM_UNVERIFIED")
                           else reason for reason in sorted(dict.fromkeys((reflow.get("review_reasons") or []) + sorted(size_codes)),
                                                            key=_reason_rank)],
    }


def _log_dependencies(job_id: str, deps: Dict[str, Any]) -> None:
    for r in deps.get("preview_tails_restored", []):
        _append(job_id, f"preview tail of {r['system_id']} kept on its strip ({r['reason']}; next {r.get('next_system_id')})"
                        + (f" - uncut strip regenerated ({r['regenerated']})" if r.get("regenerated") else ""))
    for m in deps.get("labels_moved", []):
        _append(job_id, f"section label of {m['section']} placed above {m['placed_on']} ({m['reason']})")
    for u in deps.get("labels_unplaced", []):
        _append(job_id, f"section label of {u['section']} not placed: no placed system of its section ({', '.join(u['systems'])})")


def _job_measure_reflow(job: Job) -> bool:
    """The job's own measure-reflow option. A job saved before the option existed has no
    field and keeps whole systems (its old behaviour); new jobs store it explicitly."""
    options = job.options if isinstance(job.options, dict) else {}
    return bool(options.get("measure_reflow", False))


def _measure_reflow_summary(requested: bool, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Which layout produced the files: ``status`` is ``measure_lines`` (rearranged by
    measure), ``fallback_whole_systems`` (asked for, but the planner failed: ``reason`` is
    its short code) or ``off`` (whole systems by choice)."""
    record = plan.get("measure_reflow") if isinstance(plan, dict) else None
    record = record if isinstance(record, dict) else {}
    size = plan.get("staff_size") if isinstance(plan, dict) and isinstance(plan.get("staff_size"), dict) else None
    # the staff size actually used (smaller than the chosen one for a dense chart, or for whole
    # systems that do not fit the page at the chosen size: reason WHOLE_SYSTEMS_DO_NOT_FIT)
    sized = {"staff_size": {k: size.get(k) for k in ("staff_gap_mm", "staff_gap_mm_requested", "auto_reduced", "reason")}} if size else {}
    status = str(record.get("status") or "")
    if requested and status == "measure_lines":
        return {"requested": True, "applied": True, "status": "measure_lines", "reason": None, **sized}
    # whole systems: the size is listed when it was reduced (the details stay in the page plan)
    sized = sized if size and size.get("auto_reduced") else {}
    if not requested:
        return {"requested": False, "applied": False, "status": "off", "reason": None, **sized}
    return {"requested": True, "applied": False, "status": "fallback_whole_systems",
            "reason": str(record.get("reason") or "MEASURE_PLAN_UNAVAILABLE"), **sized}


def _log_measure_reflow(job_id: str, summary: Dict[str, Any]) -> None:
    if summary.get("status") == "fallback_whole_systems":
        _append(job_id, f"measure reflow fell back to whole systems: {summary.get('reason')}")
    size = summary.get("staff_size") or {}
    if size.get("auto_reduced"):
        _append(job_id, f"staff size reduced to {size.get('staff_gap_mm')} mm from {size.get('staff_gap_mm_requested')} mm "
                        f"({size.get('reason')})")


LAYOUT_CONFLICT_CODE = "LAYOUT_CONFLICT"


def _layout_conflict_pending(job: Job) -> bool:
    """A reflow job stopped at a layout conflict: no chart files (status ERROR, error code
    LAYOUT_CONFLICT), but its systems are kept for review, where the user excludes a system or
    chooses a staff size and exports again."""
    result = job.result if isinstance(job.result, dict) else {}
    return (job.status == JobStatus.ERROR and job.error_code == LAYOUT_CONFLICT_CODE
            and result.get("reflow_state") == "layout_conflict" and isinstance(result.get("reflow"), dict))


def _ledger_failure_pending(job: Job) -> bool:
    result = job.result if isinstance(job.result, dict) else {}
    return (job.status == JobStatus.ERROR and job.error_code == "LEDGER_VERIFICATION_FAILED"
            and isinstance(result.get("reflow"), dict))


def _verify_reflow_ledger(reflow: Dict[str, Any], export_result: Dict[str, Any], staged: Path, sink: Optional[dict] = None) -> dict:
    from app.pipeline import reflow_pipeline
    from app.pipeline.export import ExportVerificationError

    report = reflow_pipeline.verify_light_deliverable(reflow, export_result, staged, sink=sink or {})
    if report["status"] == "fail":
        raise ExportVerificationError("LEDGER_VERIFICATION_FAILED",
                                      "check_pdf_contract: " + dict(REFLOW_ISSUE_REASONS)["LEDGER_VERIFICATION_FAILED"],
                                      {"check": "check_pdf_contract", "ledger_verification": reflow["ledger_verification"]})
    return report["artifact_digests"]


def _install_verified_reflow_export(staged: Path, target: Path, binding: dict) -> "_ExportCommit":
    from app.pipeline import reflow_pipeline
    reflow_pipeline.check_export_binding(staged, binding, check="STAGED_ARTIFACT_DIGEST")
    commit = _install_staged_export_workspace(staged_workspace=staged, target_workspace=target)
    try:
        reflow_pipeline.check_export_binding(target, binding, check="INSTALLED_ARTIFACT_DIGEST")
    except Exception:
        commit.revert()
        raise
    return commit


def _layout_conflict_record(plan: Dict[str, Any]) -> Dict[str, Any]:
    conflicts = plan.get("conflicts", [])
    sizes = [c.get("largest_fitting_staff_gap_mm") for c in conflicts]
    offered = min(sizes) if sizes and all(v is not None for v in sizes) else None
    return {
        "requested_staff_gap_mm": plan.get("staff_gap_mm_requested"),
        "conflicts": conflicts,
        # the largest staff size at which every conflicting system fits (None: only excluding helps)
        "largest_fitting_staff_gap_mm": offered,
        "errors": (plan.get("validation") or {}).get("errors", []),
    }


def _layout_conflict_detail(record: Dict[str, Any]) -> str:
    ids = ", ".join(c["system_id"] for c in record["conflicts"]) or "-"
    offer = record.get("largest_fitting_staff_gap_mm")
    tail = f"; largest staff size that fits: {offer:.2f} mm" if offer else "; exclude the system to continue"
    return f"LAYOUT_CONFLICT: {ids} do not fit the page at {record['requested_staff_gap_mm']} mm{tail}"


def _revert_after_metadata_failure(job_id: str, commit: "_ExportCommit", previous_result: Dict[str, Any], exc: Exception,
                                   previous_status: JobStatus = JobStatus.DONE) -> None:
    """The new export is installed but its result could not be recorded: put the
    previous export back (or keep its backup and say where) and raise HTTP 500."""
    try:
        commit.revert()
        detail = f"review export failed while recording the result ({exc}); the previous export was restored"
    except ExportCommitError as revert_exc:
        detail = f"review export failed while recording the result ({exc}); {revert_exc}"
    try:
        # the in-memory record is updated before it is persisted; point it back at the previous result
        job_store.set_state(job_id, previous_status, result=previous_result)
    except Exception:
        pass
    try:
        _append(job_id, detail)
    except Exception:
        pass
    raise HTTPException(status_code=500, detail=detail)


def _finished_reflow_state(result: Dict[str, Any]) -> str:
    """State of a reflow export that produced its files: "incomplete" when a jump-view interval
    stayed unresolved, otherwise "review_required" for flagged source/content uncertainty or
    "done". JobStatus.DONE describes a finished export, not a claim of clean-complete content."""
    coverage = result.get("coverage") or (result.get("reflow") or {}).get("coverage") or {}
    if coverage.get("status") == "incomplete":
        return "incomplete"
    return "review_required" if result.get("review_required") or (result.get("reflow") or {}).get("review_required") else "done"


def _log_coverage(job_id: str, coverage: Dict[str, Any]) -> None:
    for iv in coverage.get("intervals", []):
        _append(job_id, f"coverage {iv['start']:.1f}-{iv['end']:.1f}s ({iv.get('kind')}): {iv['status']}")
    if coverage.get("status") == "incomplete":
        spans = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in coverage.get("unresolved", []))
        _append(job_id, f"result incomplete: unresolved intervals {spans}")


MISSING_MARKER_TOLERANCE_SEC = 0.25


def _compose_header(header: Dict[str, Any], coverage: Optional[Dict[str, Any]],
                    composed: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The header given to compose: ``header`` as it is for a complete chart; for an incomplete one
    (coverage status ``incomplete``) a copy with ``incomplete`` = the unresolved [start, end]
    intervals and, per interval, the composed systems placed before it (``before_ids``) when the
    output order splits cleanly there: every system before ends by the interval's start and every
    system after starts from its end (MISSING_MARKER_TOLERANCE_SEC). Otherwise ``before_ids`` is
    None and the interval is named on page 1 only (reflow_render.layout_markers). The stored
    document header is never changed. Source-clipped systems are passed separately as
    ``source_clipped`` so their local marks/summary never manufacture missing intervals."""
    out = dict(header or {})
    clipped = [{"system_id": s["id"], **(s.get("source_clipped") or {})} for s in composed
               if "SOURCE_CLIPPED" in (s.get("issues") or []) or s.get("source_clipped")]
    if clipped:
        out["source_clipped"] = clipped
    if not isinstance(coverage, dict) or coverage.get("status") != "incomplete" or not coverage.get("unresolved"):
        return out if clipped else header
    tol = MISSING_MARKER_TOLERANCE_SEC
    markers = []
    for start, end in coverage["unresolved"]:
        start, end = float(start), float(end)
        before_ids: Optional[List[str]] = None
        try:
            side = ["before" if float(s["t_end"]) <= start + tol else "after" if float(s["t_start"]) >= end - tol else "both"
                    for s in composed]
        except (KeyError, TypeError, ValueError):
            side = ["both"]
        if "both" not in side:
            k = side.count("before")
            if all(x == "before" for x in side[:k]):
                before_ids = [s["id"] for s in composed[:k]]
        markers.append({"start": start, "end": end, "before_ids": before_ids})
    out["incomplete"] = {"unresolved": [[float(a), float(b)] for a, b in coverage["unresolved"]], "markers": markers}
    return out


def _execute_reflow_job(
    *,
    job_id: str,
    job: Job,
    payload: JobCreate,
    result: Dict[str, object],
    video_path: Optional[str],
    export_opts: ExportOptions,
) -> None:
    """Clean reflow chart (output_model clean_reflow_v1) for a new capture job."""
    from app.pipeline import reflow_layout
    from app.pipeline import reflow_pipeline
    from app.pipeline.export import ExportVerificationError, export_composed_pages, verify_composed_export
    from app.pipeline.reflow_line_review import load_line_review

    artifact_dir = Path(job.artifact_dir)
    options = payload.options
    if not video_path or not Path(video_path).is_file():
        raise RuntimeError("clean reflow needs a local video file")
    result["output_model"] = REFLOW_OUTPUT_MODEL

    def progress(stage: str, fraction: float) -> None:
        lo, hi = REFLOW_PROGRESS.get(stage, (0.5, 0.5))
        job_store.set_state(job_id, JobStatus.RUNNING, lo + (hi - lo) * max(0.0, min(1.0, fraction)), stage, f"{stage}")

    try:
        record = reflow_pipeline.analyse_source(
            video_path=Path(video_path),
            roi=options.detect.roi,
            workspace=artifact_dir / "reflow",
            start_sec=options.extract.start_sec,
            end_sec=options.extract.end_sec,
            label_roi=options.detect.label_roi,
            ledger=options.dev_ledger,
            logger=lambda msg: _append(job_id, msg),
            progress=progress,
            checkpoint=checkpoint,
        )
    except reflow_pipeline.UnsupportedLayoutError as exc:
        result["reflow_state"] = "unsupported_layout"
        result["reflow"] = {"issues": [{"kind": "UNSUPPORTED_LAYOUT", "layout": iv.get("kind"), "interval": [iv["start"], iv["end"]]}
                                       for iv in exc.intervals]}
        result["images"], result["pdf"] = [], None
        job_store.log(job_id, f"job stopped: {exc}")
        job_store.set_state(job_id, JobStatus.ERROR, 1.0, "unsupported_layout", str(exc), result=result,
                            error_code="UNSUPPORTED_LAYOUT")
        return
    except reflow_pipeline.NoSystemsError as exc:
        result["reflow_state"] = "no_systems"
        result["images"], result["pdf"] = [], None
        job_store.set_state(job_id, JobStatus.ERROR, 1.0, "no_systems", str(exc), result=result, error_code="NO_SCORE_SYSTEMS")
        return
    except reflow_pipeline.UnsupportedSourceError as exc:
        # source-class gate: notation over live imagery is refused with its evidence, not processed
        result["reflow_state"] = "unsupported_source"
        result["source_class"] = reflow_pipeline.json_safe(exc.source_class)
        result["images"], result["pdf"] = [], None
        job_store.log(job_id, f"job stopped: {exc}")
        job_store.set_state(job_id, JobStatus.ERROR, 1.0, "unsupported_source", str(exc), result=result,
                            error_code=reflow_pipeline.UnsupportedSourceError.code)
        return
    result["source_class"] = reflow_pipeline.json_safe(record.get("source_class"))
    if record.get("coverage") is not None:
        # jump view: every leftover interval accounted for; an unresolved one marks the result incomplete
        result["coverage"] = reflow_pipeline.json_safe(record["coverage"])
        _log_coverage(job_id, result["coverage"])

    checkpoint()
    header = _default_reflow_header(job, payload, export_opts)
    included = [s for s in record["systems"] if s["included"]]
    job_store.set_state(job_id, JobStatus.RUNNING, 0.88, "composing", "composing A4 pages")
    reflow = reflow_pipeline.public_record(record)
    reflow["header"] = header
    reflow["revision"] = 1
    reflow["staff_gap_mm"] = options.staff_gap_mm
    # sizing mode: a size the user chose is used as it is (a misfit is a layout conflict), else automatic
    staff_gap_explicit = bool(options.staff_gap_mm_explicit)
    reflow["staff_gap_mm_default"] = options.staff_gap_mm
    reflow["staff_gap_mm_explicit"] = staff_gap_explicit
    reflow["duplicate_suggestions"] = []
    reflow["suggestions_state"] = "pending"
    ledger_sink = {"job_id": job_id, "export_revision": 1}
    try:
        plan, pages = reflow_pipeline.compose_systems(included, header=_compose_header(header, result.get("coverage"), included),
                                                      staff_gap_mm=options.staff_gap_mm,
                                                      all_systems=record["systems"], workspace=Path(record["workspace"]),
                                                      measure_reflow=bool(options.measure_reflow),
                                                      auto_staff_size=not staff_gap_explicit, ledger_sink=ledger_sink)
    except reflow_pipeline.DependencyUnavailableError as exc:
        # fail closed: no chart from a cut strip whose destination is not the next placed system
        result["reflow"] = reflow
        result["reflow_state"] = "dependency_unavailable"
        result["images"], result["pdf"] = [], None
        job_store.log(job_id, f"job stopped: {exc}")
        job_store.set_state(job_id, JobStatus.ERROR, 1.0, "dependency_unavailable", UNCUT_STRIP_UNAVAILABLE_DETAIL,
                            result=result, error_code=reflow_pipeline.DependencyUnavailableError.code)
        return
    except reflow_layout.LayoutConflictError as exc:
        # Whole systems that do not fit even at the automatic floor (1.2 mm), or at a size the user
        # chose: the user excludes the system or chooses a smaller staff size for this document in
        # review. No final files until then, and the job is not "done" (STRATEGY Step 2A): status
        # ERROR with error code LAYOUT_CONFLICT; review export stays allowed for it.
        conflict_plan = reflow_pipeline.json_safe(exc.plan)
        conflict = _layout_conflict_record(conflict_plan)
        reflow["page_plan"] = conflict_plan
        reflow["layout_conflict"] = conflict
        result["measure_reflow"] = _measure_reflow_summary(bool(options.measure_reflow), conflict_plan)
        _log_measure_reflow(job_id, result["measure_reflow"])
        result.update(_reflow_capture_fields(reflow))
        result["reflow"] = reflow
        result["reflow_state"] = "layout_conflict"
        result["images"], result["pdf"], result["preview_images"] = [], None, []
        result["raw_frames"], result["page_diagnostics"], result["dropped_pages"] = [], [], []
        result["output_dir"] = str(artifact_dir / "export")
        detail = _layout_conflict_detail(conflict)
        job_store.log(job_id, detail)
        job_store.set_state(job_id, JobStatus.ERROR, 1.0, "layout_conflict", detail, result=result,
                            error_code=LAYOUT_CONFLICT_CODE)
        _finish_reflow_suggestions(job_id, record)
        return
    export_workspace = artifact_dir / "export"
    staged = _create_staged_export_workspace(target_workspace=export_workspace)
    job_store.set_state(job_id, JobStatus.RUNNING, 0.92, "exporting", "writing files")
    try:
        export_result = export_composed_pages(pages=pages, formats=list(export_opts.formats), workspace=staged,
                                              logger=lambda msg: _append(job_id, msg))
        # "done" only with a valid placement plan and readable files whose page count matches it
        verified = verify_composed_export(export_result, plan=plan, pages=pages)
        binding = _verify_reflow_ledger(reflow, export_result, staged, ledger_sink)
        checkpoint()
        commit = _install_verified_reflow_export(staged, export_workspace, binding)
    except ExportVerificationError as exc:
        shutil.rmtree(staged, ignore_errors=True)
        if exc.code == "LEDGER_VERIFICATION_FAILED" and reflow.get("ledger_summary", {}).get("status") != "fail":
            check = str(exc.facts.get("check") or "ARTIFACT_DIGEST")
            reflow["ledger_summary"]["status"] = "fail"
            reflow["ledger_summary"]["issue_counts"][check] = 1
            reflow["ledger_verification"].update(status="fail", assessment="fail")
            reflow["review_required"] = True
            reflow["review_reasons"] = sorted(set(reflow.get("review_reasons", []) + ["LEDGER_VERIFICATION_FAILED"]))
        reflow["page_plan"] = plan
        reflow["export_verification"] = {"error_code": exc.code, "detail": exc.detail, **reflow_pipeline.json_safe(exc.facts)}
        result["measure_reflow"] = _measure_reflow_summary(bool(options.measure_reflow), plan)
        result.update(_reflow_capture_fields(reflow))
        result["reflow"] = reflow
        result["reflow_state"] = "ledger_failed" if exc.code == "LEDGER_VERIFICATION_FAILED" else "export_invalid"
        result["images"], result["pdf"], result["preview_images"] = [], None, []
        job_store.log(job_id, f"job stopped: {exc}")
        job_store.set_state(job_id, JobStatus.ERROR, 1.0, "export_invalid", str(exc), result=result, error_code=exc.code)
        return
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    export_result = _rewrite_export_result_paths(export_result=export_result, staged_workspace=staged,
                                                 target_workspace=export_workspace)
    reflow["page_plan"] = plan
    reflow["line_review"] = load_line_review(plan, reflow, logger=lambda msg: _append(job_id, msg))
    reflow["export_verification"] = reflow_pipeline.json_safe(verified)
    reflow["dependencies"] = plan.get("dependencies", {})
    _log_dependencies(job_id, reflow["dependencies"])
    result["measure_reflow"] = _measure_reflow_summary(bool(options.measure_reflow), plan)
    _log_measure_reflow(job_id, result["measure_reflow"])
    result.update(_reflow_capture_fields(reflow))
    result["reflow"] = reflow
    result["reflow_state"] = _finished_reflow_state(result)
    result["images"] = export_result.get("images", [])
    result["pdf"] = export_result.get("pdf")
    result["preview_images"] = export_result.get("preview_images", [])
    result["raw_frames"] = []
    result["page_diagnostics"] = []
    result["dropped_pages"] = []
    result["output_dir"] = str(export_workspace)
    # The chart is published (DONE) first; likely-repeat suggestions follow in a
    # bounded, cancellable step that only adds "looks similar" notes to the job.
    try:
        job_store.set_state(job_id, JobStatus.DONE, 1.0, "done", "export finished", result=result, error_code=None)
    except Exception:
        commit.revert()
        raise
    commit.finalize()
    job_store.log(job_id, f"job finished: {len(included)} systems on {len(pages)} pages")
    _finish_reflow_suggestions(job_id, record)


SUGGESTION_TIME_BUDGET_SEC = 90.0
suggestion_controls: Dict[str, Event] = {}


def cancel_pending_suggestions(job_id: Optional[str] = None) -> None:
    with maintenance_lock:
        for jid, event in list(suggestion_controls.items()):
            if job_id is None or jid == job_id:
                event.set()


def _finish_reflow_suggestions(job_id: str, record: Dict[str, Any], *, time_budget_sec: Optional[float] = None) -> None:
    """Likely-repeat suggestions after the job is DONE: bounded by a time budget,
    cancellable (a new job or a cancel request stops it), never blocking and never
    applied. The result is merged into the job's latest record."""
    from app.pipeline import reflow_pipeline

    cancel = Event()
    with maintenance_lock:
        suggestion_controls[job_id] = cancel
    budget = SUGGESTION_TIME_BUDGET_SEC if time_budget_sec is None else time_budget_sec
    deadline = time.monotonic() + budget
    # checked between items by every step (strip loading, frame decoding, label samples)
    should_stop = lambda: cancel.is_set() or time.monotonic() > deadline  # noqa: E731
    state = "done"
    incomplete: List[str] = []
    suggestions: List[Dict[str, Any]] = []
    labels = None
    try:
        try:
            suggestions = reflow_pipeline.duplicate_suggestions(record, logger=lambda msg: _append(job_id, msg), should_stop=should_stop)
            if should_stop():
                incomplete.append("similar_suggestions")
        except Exception as exc:  # suggestions are optional; the chart is already done
            state = "failed"
            _append(job_id, f"similar-system suggestions skipped: {exc}")
        if (record.get("labels") or {}).get("status") == "not_checked":
            if should_stop():
                labels = dict(record.get("labels") or {}, check="incomplete")
                incomplete.append("label_check")
            else:
                try:
                    # section labels drawn outside the applied score region (report only; never applied)
                    labels = reflow_pipeline.check_labels_outside(record, should_stop=should_stop)
                    if labels.get("check") == "incomplete" or should_stop():
                        # a result reached after the budget or a cancel is not published as a finding
                        labels = dict(record.get("labels") or {}, check="incomplete")
                        incomplete.append("label_check")
                except Exception as exc:  # pragma: no cover - defensive
                    _append(job_id, f"label check skipped: {exc}")
        if state != "failed" and incomplete:
            state = "cancelled" if cancel.is_set() else "partial"
    finally:
        with maintenance_lock:
            suggestion_controls.pop(job_id, None)
        reflow_pipeline.prune_frames(record)
    with maintenance_lock:
        lock = review_locks.setdefault(job_id, RLock())
    with lock:
        job = job_store.get(job_id)
        if not job or not isinstance(job.result, dict) or not isinstance(job.result.get("reflow"), dict):
            return
        result = dict(job.result)
        reflow = dict(result["reflow"])
        reflow["duplicate_suggestions"] = reflow_pipeline.json_safe(suggestions)
        reflow["suggestions_state"] = state
        reflow["suggestions_incomplete"] = incomplete  # steps stopped by the time budget or a cancel
        if labels is not None:
            reflow["labels"] = reflow_pipeline.json_safe(labels)
        reflow["frames_pruned"] = bool(record.get("frames_pruned"))
        if record.get("overlay_evidence_path"):
            reflow["overlay_evidence_path"] = record["overlay_evidence_path"]
        result["reflow"] = reflow
        result["similar_capture_pairs"] = _reflow_capture_fields(reflow)["similar_capture_pairs"]
        job_store.set_state(job_id, job.status, result=result)
    _append(job_id, f"similar-system suggestions: {len(suggestions)} ({state})")


def _reflow_export_inputs(job: Job, payload: JobReviewExportRequest) -> Dict[str, Any]:
    """Check the request against the job (selection, order, formats) and resolve what to compose.
    Raises HTTPException 400 for a selection or format the job cannot export."""
    result = copy.deepcopy(job.result or {})
    reflow = result.get("reflow") or {}
    if payload.base_revision is not None and payload.base_revision != int(reflow.get("revision", 1)):
        raise HTTPException(status_code=409, detail=f"STALE_REVISION: expected revision {int(reflow.get('revision', 1))}, received {payload.base_revision}")
    systems = [dict(s) for s in reflow.get("systems", [])]
    by_path = {str(Path(s["strip_path"]).resolve()): s for s in systems}

    def lookup(raw: str) -> Optional[Dict[str, Any]]:
        try:
            return by_path.get(str(Path(str(raw)).resolve()))
        except Exception:
            return None

    if payload.keep_images:
        raise HTTPException(status_code=400, detail="clean reflow jobs select systems with keep_captures")
    keep = []
    for raw in payload.keep_captures:
        s = lookup(raw)
        if s is None:
            raise HTTPException(status_code=400, detail=f"unknown system: {raw}")
        if s not in keep:
            keep.append(s)
    if not keep:
        raise HTTPException(status_code=400, detail="no valid systems selected")
    order = []
    for raw in payload.system_order:
        s = lookup(raw)
        if s is not None and s not in order:
            order.append(s)
    if order:
        order += [s for s in systems if s not in order]
    else:
        order = list(systems)
    # Selected systems follow the arranged order; keep_captures order is used when no arrangement is given.
    keep_ids = {s["id"] for s in keep}
    composed = [s for s in order if s["id"] in keep_ids] if payload.system_order else keep

    export_config = _resolve_job_export_options(job)
    requested = payload.formats if payload.formats is not None else list(export_config.formats)
    formats = _normalize_requested_export_formats(requested)
    if not formats:
        raise HTTPException(status_code=400, detail="formats must include at least one export format")
    from app.pipeline.reflow_seam_reject import SeamRepairError, validate_request
    reflow.setdefault("workspace", str(Path(job.artifact_dir) / "reflow"))
    try:
        repair = validate_request(reflow, systems, composed, payload)
    except SeamRepairError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"result": result, "reflow": reflow, "systems": systems, "order": order, "keep_ids": keep_ids,
            "composed": composed, "formats": formats, "export_config": export_config, "repair": repair}


def _review_export_reflow(job: Job, job_id: str, payload: JobReviewExportRequest) -> JobReviewExportResponse:
    """Revalidate under the export lock, prepare an unpublished candidate, then commit."""
    from app.pipeline import reflow_pipeline
    from app.pipeline.observations import SeamRepairSourceUnavailable
    from app.pipeline.reflow_seam_reject import SeamRepairError
    inputs = _reflow_export_inputs(job, payload)
    repair = inputs["repair"]
    revision_dir = None
    published = False
    try:
        if repair["changed"]:
            revision_dir = Path(job.artifact_dir) / "reflow_revisions" / f"revision-{int(inputs['reflow'].get('revision', 1))+1}-{uuid.uuid4().hex[:12]}"
            reflow, order, composed = reflow_pipeline.rebuild_jump_runs(
                inputs["reflow"], repair, inputs["order"], inputs["composed"], revision_dir,
                checkpoint=checkpoint, progress=report_progress, logger=lambda msg: _append(job_id, msg))
            inputs.update(reflow=reflow, systems=order, order=order, composed=composed,
                          keep_ids={s["id"] for s in composed})
            inputs["result"]["reflow"] = reflow
            if "coverage" in reflow:
                inputs["result"]["coverage"] = reflow["coverage"]
        inputs["reflow"]["rejected_seam_ids"] = repair["desired"]
        response = _compose_review_export_reflow(job, job_id, payload, inputs)
        published = True
        return response
    except SeamRepairSourceUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SeamRepairError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    finally:
        if revision_dir is not None and not published:
            shutil.rmtree(revision_dir, ignore_errors=True)


def _compose_review_export_reflow(job: Job, job_id: str, payload: JobReviewExportRequest,
                                inputs: Dict[str, Any]) -> JobReviewExportResponse:
    """Re-compose the clean reflow chart from the user's system order and selection.

    Transactional: the pages are written to a staged folder and installed only when complete; a
    failure or a cancel (process_control.OperationCancelled, raised at a stage boundary before the
    install) leaves the previous export files and the job's result as they were."""
    from app.pipeline import reflow_layout
    from app.pipeline import reflow_pipeline
    from app.pipeline.export import ExportVerificationError, export_composed_pages, verify_composed_export
    from app.pipeline.reflow_line_review import load_line_review

    result, reflow, systems = inputs["result"], inputs["reflow"], inputs["systems"]
    order, keep_ids, composed, formats = inputs["order"], inputs["keep_ids"], inputs["composed"], inputs["formats"]
    export_config = inputs["export_config"]
    previous_result = copy.deepcopy(job.result or {})
    header = reflow.get("header") or {}
    if export_config.document_header is not None:
        header = export_config.document_header.model_dump()
    default_gap = float((job.options or {}).get("staff_gap_mm") or 1.5) if isinstance(job.options, dict) else 1.5
    # An explicit user choice (a smaller size allowed for this document) is kept for later rebuilds.
    staff_gap_mm = float(payload.staff_gap_mm) if payload.staff_gap_mm is not None else float(reflow.get("staff_gap_mm") or default_gap)
    # Modern clients send the mode explicitly, including a locked 1.5 mm or automatic False.
    # Old clients without it retain the previous inference: a different size is explicit,
    # while the job's size allows automatic sizing unless the job itself locked that size.
    job_gap_explicit = bool((job.options or {}).get("staff_gap_mm_explicit")) if isinstance(job.options, dict) else False
    if payload.staff_gap_mm_explicit is not None:
        staff_gap_explicit = payload.staff_gap_mm_explicit
    elif payload.staff_gap_mm is not None:
        staff_gap_explicit = job_gap_explicit or abs(float(payload.staff_gap_mm) - default_gap) > 1e-6
    else:
        staff_gap_explicit = bool(reflow.get("staff_gap_mm_explicit",
                                             job_gap_explicit or abs(staff_gap_mm - default_gap) > 1e-6))
    export_workspace = Path(job.artifact_dir) / "export"
    user_excluded = {s["id"] for s in systems if s["id"] not in keep_ids and s.get("auto_included", s.get("included", True))}
    user_excluded.update(set(reflow.get("user_excluded_system_ids", [])) - keep_ids)
    ledger_sink = {"excluded_system_ids": sorted(user_excluded), "job_id": job_id,
                   "export_revision": int(reflow.get("revision", 1))+1}
    try:
        # the export's own choice, else the job's option; dependencies are re-validated on every compose
        measure_reflow = bool(payload.measure_reflow) if payload.measure_reflow is not None else _job_measure_reflow(job)
        coverage = result.get("coverage") or reflow.get("coverage")
        pdf_coverage = reflow.get("seam_repair_pdf_coverage") if reflow.get("rejected_seam_ids") else coverage
        plan, pages = reflow_pipeline.compose_systems(composed, header=_compose_header(header, pdf_coverage, composed),
                                                      staff_gap_mm=staff_gap_mm, all_systems=systems,
                                                      workspace=Path(reflow.get("workspace") or Path(job.artifact_dir) / "reflow"),
                                                      measure_reflow=measure_reflow, auto_staff_size=not staff_gap_explicit, ledger_sink=ledger_sink)
    except reflow_pipeline.DependencyUnavailableError as exc:
        # fail closed: the previous export files and result stay as they are
        try:
            _append(job_id, f"review export stopped: {exc}")
        except Exception:
            pass
        raise HTTPException(status_code=409, detail=f"{UNCUT_STRIP_UNAVAILABLE_DETAIL} [{exc.system_id}: {exc.reason}]")
    except reflow_layout.LayoutConflictError as exc:
        conflict = _layout_conflict_record(reflow_pipeline.json_safe(exc.plan))
        conflict["selected_system_ids"] = [s["id"] for s in composed]
        # metadata only: the previous export files and order stay as they are
        if inputs["repair"]["changed"]:
            raise HTTPException(status_code=409, detail=_layout_conflict_detail(conflict))
        noted = dict(reflow)
        noted["layout_conflict"] = conflict
        noted_result = dict(result)
        noted_result["reflow"] = noted
        noted_result["capture_diagnostics"] = _reflow_capture_fields(noted)["capture_diagnostics"]
        # the job keeps its state: done with its previous files, or still a pending layout conflict
        job_store.set_state(job_id, job.status, result=noted_result)
        raise HTTPException(status_code=409, detail=_layout_conflict_detail(conflict))
    except reflow_pipeline.NoSystemsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OperationCancelled:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"review export failed: {exc}")
    measure_summary = _measure_reflow_summary(measure_reflow, plan)
    report_progress("writing", 0.0)
    staged = _create_staged_export_workspace(target_workspace=export_workspace)
    try:
        export_result = export_composed_pages(pages=pages, formats=formats, workspace=staged,
                                              logger=lambda msg: _append(job_id, msg))
        # published only with a valid placement plan and files whose page count matches it
        verified = verify_composed_export(export_result, plan=plan, pages=pages)
        reflow.setdefault("workspace", str(Path(job.artifact_dir) / "reflow"))
        binding = _verify_reflow_ledger(reflow, export_result, staged, ledger_sink)
        # last cancel point: after this the new export is installed and recorded
        checkpoint()
        commit = _install_verified_reflow_export(staged, export_workspace, binding)
    except OperationCancelled:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    except ExportVerificationError as exc:
        # the previous export files and result stay as they are; the task reports exc.code
        shutil.rmtree(staged, ignore_errors=True)
        try:
            _append(job_id, f"review export stopped: {exc}")
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        shutil.rmtree(staged, ignore_errors=True)
        detail = _export_failure_detail(exc)
        try:
            _append(job_id, detail)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=detail)

    try:
        export_result = _rewrite_export_result_paths(export_result=export_result, staged_workspace=staged,
                                                     target_workspace=export_workspace)
        for s in order:
            s["included"] = s["id"] in keep_ids
        reflow["systems"] = order
        reflow["user_excluded_system_ids"] = sorted(user_excluded)
        reflow["page_plan"] = plan
        reflow["line_review"] = load_line_review(plan, reflow, logger=lambda msg: _append(job_id, msg))
        reflow["export_verification"] = reflow_pipeline.json_safe(verified)
        reflow.pop("layout_conflict", None)
        reflow["dependencies"] = plan.get("dependencies", {})
        _log_dependencies(job_id, reflow["dependencies"])
        reflow["header"] = header
        reflow["staff_gap_mm"] = staff_gap_mm
        reflow["staff_gap_mm_default"] = default_gap
        reflow["staff_gap_mm_explicit"] = staff_gap_explicit
        reflow.pop("layout_conflict", None)
        reflow["revision"] = int(reflow.get("revision", 1)) + 1
        result["measure_reflow"] = measure_summary
        result.update(_reflow_capture_fields(reflow))
        result["auto_excluded_captures"] = []
        result["reflow"] = reflow
        result["reflow_state"] = _finished_reflow_state(result)
        result["images"] = export_result.get("images", [])
        result["pdf"] = export_result.get("pdf")
        result["preview_images"] = export_result.get("preview_images", [])
        result["output_dir"] = str(export_workspace)
        selected_paths = [s["strip_path"] for s in composed]
        result["review_export"] = {
            "revision": int(result.get("review_export", {}).get("revision", 0)) + 1,
            "kept_count": len(composed),
            "requested_count": len(payload.keep_captures),
            "selection_mode": "captures",
            "selected_captures": selected_paths,
            "selected_pages": [],
            "system_order": [s["strip_path"] for s in order],
            "measure_reflow": measure_summary,
            "line_review": reflow["line_review"],
        }
        job_store.set_state(job_id, JobStatus.DONE, 1.0, "done", "review export finished", result=result, error_code=None)
    except Exception as exc:
        _revert_after_metadata_failure(job_id, commit, previous_result, exc, previous_status=job.status)
    commit.finalize()
    try:
        _log_measure_reflow(job_id, measure_summary)
    except Exception:
        pass
    return JobReviewExportResponse(
        images=[str(p) for p in export_result.get("images", [])],
        pdf=str(export_result.get("pdf")) if export_result.get("pdf") else None,
        output_dir=str(export_workspace),
        kept_count=len(composed),
        measure_reflow=measure_summary,
        revision=int(reflow.get("revision") or 0) or None,
        review_required=bool(result.get("review_required")),
        review_reasons=list(result.get("review_reasons") or []),
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
        prepared = _coerce_prepared_youtube_source(
            _get_or_prepare_cached_youtube_video(
                job.youtube_url,
                logger=lambda msg: _append_source_prepare(job_id, msg),
                progress_callback=lambda update: _apply_source_prepare_progress(job_id, update),
            ),
            fallback_url=job.youtube_url,
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
            "source_key": str(prepared.get("source_key") or ""),
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


def _apply_export_extract_progress(job_id: str, update: Dict[str, Any]) -> None:
    if not update:
        return
    progress_value = update.get("progress")
    try:
        sub_progress = float(progress_value) if progress_value is not None else None
    except (TypeError, ValueError):
        sub_progress = None

    progress = None
    if sub_progress is not None:
        progress = 0.02 + max(0.0, min(sub_progress, 1.0)) * 0.18
    stage = str(update.get("stage") or "extracting").strip() or "extracting"
    message = str(update.get("message") or "frame extraction in progress").strip()
    job_store.set_state(
        job_id,
        JobStatus.RUNNING,
        progress,
        stage,
        message,
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


def _preview_source_cache_workspace(youtube_url: str, *, create: bool = True) -> Path:
    normalized_url = _best_effort_normalize_youtube_key(youtube_url)
    cache_key = hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()[:16]
    cache_dir = jobs_root / "_preview_source" / PREVIEW_SOURCE_CACHE_NAMESPACE / cache_key
    if create:
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
        "source_key": _best_effort_normalize_youtube_key(payload.get("source_key") or ""),
        "video_title": str(payload.get("video_title") or "").strip(),
    }


def _coerce_prepared_youtube_source(prepared: object, *, fallback_url: str) -> Dict[str, object]:
    default_source_key = _best_effort_normalize_youtube_key(fallback_url)
    if isinstance(prepared, dict):
        video_value = prepared.get("video_path")
        video_path = Path(str(video_value or "")).expanduser()
        if not str(video_path).strip():
            raise ValueError("prepared youtube video path is missing")
        return {
            "video_path": video_path,
            "from_cache": bool(prepared.get("from_cache")),
            "video_title": str(prepared.get("video_title") or "").strip(),
            "source_key": _best_effort_normalize_youtube_key(prepared.get("source_key") or default_source_key),
        }

    try:
        video_path, from_cache = prepared
    except (TypeError, ValueError):
        raise TypeError("prepared youtube source must be a mapping or (video_path, from_cache) tuple")

    resolved_path = Path(video_path).expanduser()
    metadata = _read_cached_youtube_metadata(resolved_path)
    return {
        "video_path": resolved_path,
        "from_cache": bool(from_cache),
        "video_title": metadata.get("video_title", ""),
        "source_key": _best_effort_normalize_youtube_key(metadata.get("source_key", "") or default_source_key),
    }


def _preview_cleanup_now() -> float:
    return time.time()


def _prune_preview_workspaces(
    root: Path,
    *,
    keep: int = 2,
    max_age_seconds: float | None = None,
) -> None:
    if keep < 0 or not root.exists():
        return
    try:
        paths = [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return

    candidates: List[tuple[Path, float]] = []
    for path in paths:
        try:
            candidates.append((path, path.stat().st_mtime))
        except OSError:
            continue

    candidates.sort(key=lambda item: item[1], reverse=True)
    cutoff = None
    if max_age_seconds is not None and max_age_seconds >= 0:
        cutoff = _preview_cleanup_now() - max_age_seconds

    for index, (stale, mtime) in enumerate(candidates):
        if index < keep and (cutoff is None or mtime >= cutoff):
            continue
        try:
            _remove_path(stale)
        except OSError:
            continue


def _resolve_cached_youtube_source_entry(*, youtube_url: str, source_key: str = "") -> Dict[str, object]:
    normalized_key = _best_effort_normalize_youtube_key(source_key or youtube_url)
    if not normalized_key:
        return {}
    cache_dir = _preview_source_cache_workspace(normalized_key, create=False)
    cached_video = _find_cached_video(cache_dir)
    if cached_video is None:
        return {
            "source_key": normalized_key,
            "youtube_url": normalized_key,
        }
    metadata = _read_cached_youtube_metadata(cached_video)
    resolved_source_key = _best_effort_normalize_youtube_key(metadata.get("source_key") or normalized_key)
    return {
        "source_path": str(cached_video.resolve()),
        "source_key": resolved_source_key,
        "youtube_url": resolved_source_key,
        "video_title": str(metadata.get("video_title") or "").strip(),
    }


def _safe_source_prepare_progress(progress_callback, update, *, logger=None) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(dict(update or {}))
    except Exception as exc:
        if logger is not None:
            logger(f"source prepare progress callback failed: {exc}")


def _get_or_prepare_cached_youtube_video(youtube_url: str, *, logger, progress_callback=None) -> tuple[Path, bool]:
    url = _best_effort_normalize_youtube_key(youtube_url)
    if not url:
        raise ValueError("youtube_url is required when source_type is youtube")

    _safe_source_prepare_progress(
        progress_callback,
        {
            "stage": "cache_lookup",
            "progress": 0.0,
            "progress_mode": "indeterminate",
            "message": "checking youtube cache",
        },
        logger=logger,
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
            _safe_source_prepare_progress(
                progress_callback,
                {
                    "stage": "validate",
                    "progress_mode": "indeterminate",
                    "message": "using cached youtube video",
                },
                logger=logger,
            )
            return cached, True

    logger("youtube cache miss: downloading source")
    video_path = prepare_preview_source(
        source_type="youtube",
        file_path=None,
        youtube_url=url,
        workspace=cache_dir,
        logger=logger,
        progress_callback=progress_callback,
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


class ExportCommitError(RuntimeError):
    """Installing a new export failed and the previous export could not be put back
    in place automatically. ``backup_path`` holds the previous export's files."""

    def __init__(self, message: str, *, backup_path: Optional[Path] = None):
        super().__init__(message)
        self.backup_path = backup_path


def _fs_replace(src: Path, dst: Path) -> None:
    """Atomic rename used by the export commit (a seam for fault-injection tests)."""
    Path(src).replace(dst)


class _ExportCommit:
    """A staged export installed at ``target``; the previous export stays in
    ``backup`` until the caller has recorded the new result (``finalize``) or
    puts the previous export back (``revert``)."""

    def __init__(self, target: Path, backup: Optional[Path]):
        self.target = target
        self.backup = backup

    def finalize(self) -> None:
        if self.backup is not None:
            shutil.rmtree(self.backup, ignore_errors=True)
            self.backup = None

    def revert(self) -> None:
        """Post-commit failure (the new result could not be recorded): move the new
        export aside and restore the previous one. Raises ExportCommitError, keeping
        the backup, when that is not possible."""
        failed = self.target.with_name(f"{self.target.name}_failed_{uuid.uuid4().hex[:8]}")
        try:
            if self.target.exists():
                _fs_replace(self.target, failed)
            if self.backup is not None:
                _fs_replace(self.backup, self.target)
                self.backup = None
        except Exception as exc:
            raise ExportCommitError(
                f"could not restore the previous export; its files are kept at {self.backup}", backup_path=self.backup,
            ) from exc
        shutil.rmtree(failed, ignore_errors=True)


def _install_staged_export_workspace(*, staged_workspace: Path, target_workspace: Path) -> _ExportCommit:
    """Move ``staged_workspace`` into place. The previous export is renamed to a
    backup first and is deleted only by ``_ExportCommit.finalize`` after the
    caller recorded the new result. If installing fails the previous export is
    moved back; if that also fails, the backup is kept and ExportCommitError
    names it (the previous chart is never deleted on a failure path)."""
    backup_workspace = target_workspace.with_name(f"{target_workspace.name}_backup_{uuid.uuid4().hex[:8]}")
    moved = False
    try:
        if target_workspace.exists():
            _fs_replace(target_workspace, backup_workspace)
            moved = True
        _fs_replace(staged_workspace, target_workspace)
    except Exception as exc:
        if moved:
            try:
                if target_workspace.exists():
                    # a partial install: keep it aside, never on top of the previous export
                    _fs_replace(target_workspace, target_workspace.with_name(f"{target_workspace.name}_failed_{uuid.uuid4().hex[:8]}"))
                _fs_replace(backup_workspace, target_workspace)
            except Exception as rollback_exc:
                raise ExportCommitError(
                    f"export install failed ({exc}) and the previous export could not be restored "
                    f"({rollback_exc}); its files are kept at {backup_workspace}",
                    backup_path=backup_workspace,
                ) from exc
        raise
    return _ExportCommit(target_workspace, backup_workspace if moved else None)


def _export_failure_detail(exc: Exception) -> str:
    if isinstance(exc, ExportCommitError) and exc.backup_path is not None:
        return f"review export failed: {exc} (previous export kept at {exc.backup_path})"
    return f"review export failed: {exc}"


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
    source_kind = str(source_identity.get("kind") or job.source_type or "").strip().lower()
    source_key = str(source_identity.get("key") or "").strip()
    if source_kind == "youtube":
        if source_key:
            return _best_effort_normalize_youtube_key(source_key)
        return _best_effort_normalize_youtube_key(job.youtube_url or "")

    if source_key:
        return source_key

    if str(job.source_type or "").strip().lower() == "youtube":
        return _best_effort_normalize_youtube_key(job.youtube_url or "")

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
