from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LayoutHint = Literal["auto", "bottom_bar", "full_scroll", "page_turn"]
CaptureSensitivity = Literal["low", "medium", "high"]
DedupeLevel = Literal["aggressive", "normal", "sensitive"]
PageFillMode = Literal["balanced", "performance"]


class ExtractOptions(BaseModel):
    fps: Optional[float] = Field(default=None, gt=0)
    capture_sensitivity: CaptureSensitivity = "medium"
    start_sec: Optional[float] = Field(default=None, ge=0)
    end_sec: Optional[float] = Field(default=None, ge=0)

    @field_validator("end_sec")
    @classmethod
    def validate_window(cls, value: Optional[float], info):
        start_sec = info.data.get("start_sec")
        if value is not None and start_sec is not None and value <= start_sec:
            raise ValueError("end_sec must be greater than start_sec")
        return value


class DetectOptions(BaseModel):
    roi: List[List[float]]
    auto_fit: bool = False
    layout_hint: LayoutHint = "auto"
    # Clean reflow: an optional second region (source pixels) where section labels are
    # drawn outside the score region (e.g. over the video). Applied by the user only;
    # small label patches are taken from it and placed above their system.
    label_roi: Optional[List[List[float]]] = None

    @field_validator("roi")
    @classmethod
    def validate_roi(cls, value: List[List[float]]):
        if len(value) != 4:
            raise ValueError("roi must be 4 points: [[x,y], ...]")
        for point in value:
            if len(point) != 2:
                raise ValueError("each roi point must be [x, y]")
        return value

    @field_validator("label_roi")
    @classmethod
    def validate_label_roi(cls, value: Optional[List[List[float]]]):
        if value is None:
            return value
        if len(value) != 4 or any(len(point) != 2 for point in value):
            raise ValueError("label_roi must be 4 points: [[x,y], ...]")
        return value


class RectifyOptions(BaseModel):
    auto: bool = True
    manual_points: Optional[List[List[float]]] = None

    @field_validator("manual_points")
    @classmethod
    def validate_manual_points(cls, value: Optional[List[List[float]]]):
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError("manual_points must be 4 points: [[x,y], ...]")
        for point in value:
            if len(point) != 2:
                raise ValueError("each manual_point must be [x, y]")
        return value


class StitchOptions(BaseModel):
    enable: bool = False
    remove_overlays: bool = True
    flatten_background: bool = True
    overlap_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    layout_hint: LayoutHint = "auto"
    dedupe_level: DedupeLevel = "normal"


class UpscaleOptions(BaseModel):
    enable: bool = False
    scale: float = Field(default=2.0, ge=1.0, le=4.0)
    gpu_only: bool = True

    @model_validator(mode="after")
    def validate_scale(self):
        if self.enable and self.scale <= 1.0:
            raise ValueError("scale must be greater than 1.0 when upscale is enabled")
        return self


class ExportOptions(BaseModel):
    class DocumentHeaderOptions(BaseModel):
        model_config = ConfigDict(extra="forbid")

        title: str
        performer: str = ""
        bpm: Optional[int] = None
        date: str = ""
        memo: str = ""

        @field_validator("title", mode="before")
        @classmethod
        def validate_title(cls, value: object) -> str:
            title = str(value or "").strip()
            if not title:
                raise ValueError("document_header.title is required")
            return title

        @field_validator("performer", "date", "memo", mode="before")
        @classmethod
        def normalize_optional_text(cls, value: object) -> str:
            return str(value or "").strip()

        @field_validator("bpm", mode="before")
        @classmethod
        def validate_bpm(cls, value: object) -> Optional[int]:
            if value in (None, ""):
                return None
            if isinstance(value, bool):
                raise ValueError("document_header.bpm must be an integer")
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                if not value.is_integer():
                    raise ValueError("document_header.bpm must be an integer")
                return int(value)
            text = str(value).strip()
            if not text:
                return None
            if not re.fullmatch(r"[+-]?\d+", text):
                raise ValueError("document_header.bpm must be an integer")
            return int(text)

    formats: List[Literal["png", "jpg", "jpeg", "pdf"]] = Field(default_factory=lambda: ["png", "pdf"])
    output_dir: Optional[str] = None
    include_raw_frames: bool = False
    page_fill_mode: PageFillMode = "performance"
    document_header: Optional[DocumentHeaderOptions] = None

# Product default document staff gap (mm); see JobOptions.staff_gap_mm_explicit.
PRODUCT_STAFF_GAP_MM = 1.5


class JobOptions(BaseModel):
    # Raw source obligations for the offline developer verifier; app B/C stay enabled.
    dev_ledger: bool = False
    extract: ExtractOptions = Field(default_factory=ExtractOptions)
    detect: DetectOptions = Field(default_factory=DetectOptions)
    rectify: RectifyOptions = Field(default_factory=RectifyOptions)
    stitch: StitchOptions = Field(default_factory=StitchOptions)
    upscale: UpscaleOptions = Field(default_factory=UpscaleOptions)
    export: ExportOptions = Field(default_factory=ExportOptions)
    # The app's only final output is the clean reflow chart (docs/reflow/DECISIONS.md).
    # No other value is accepted; the pre-reflow raw-stitch path is not selectable.
    output_model: Literal["clean_reflow_v1"] = "clean_reflow_v1"
    # Clean reflow: document staff gap in millimetres (A4, 300 dpi).
    staff_gap_mm: float = Field(default=PRODUCT_STAFF_GAP_MM, ge=1.0, le=2.5)
    # Sizing mode (docs/reflow/DECISIONS.md "Automatic staff size for dense charts"): True means the
    # user chose ``staff_gap_mm`` and it is used as it is (no automatic reduction; a layout that does
    # not fit is a LAYOUT_CONFLICT); False allows the automatic search. Omitted: explicit only when
    # the request sets ``staff_gap_mm`` to a value other than the product default (1.5 mm). The
    # desktop app sends no size at job creation, so its jobs keep automatic sizing.
    staff_gap_mm_explicit: Optional[bool] = None
    # Measure-level reflow (split systems only at SAFE measure boundaries, justified lines).
    # On by default for new jobs (measure reflow MVP, docs/reflow/DECISIONS.md). A job record
    # saved before this option existed has no field and keeps whole systems (read as False).
    measure_reflow: bool = True

    @model_validator(mode="after")
    def resolve_staff_gap_mode(self):
        if self.staff_gap_mm_explicit is None:
            self.staff_gap_mm_explicit = ("staff_gap_mm" in self.model_fields_set
                                          and abs(float(self.staff_gap_mm) - PRODUCT_STAFF_GAP_MM) > 1e-6)
        return self


class SourceIdentity(BaseModel):
    kind: Literal["file", "youtube"]
    key: str
    display_name: str


class JobCreate(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    source_identity: Optional[SourceIdentity] = None
    options: JobOptions = Field(default_factory=JobOptions)


class JobCreateResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: float
    current_step: str
    message: str
    result: Dict[str, Any]
    error_code: Optional[str] = None
    log_tail: List[str]


class JobFileResponse(BaseModel):
    images: List[str]
    pdf: Optional[str]


class ReviewExcludedCounts(BaseModel):
    displays: int = 0
    items: int = 0


class ReviewHypothesisCounts(BaseModel):
    hypotheses: int = 0
    bundles: int = 0
    boundaries_safe: int = 0
    boundaries_unknown: int = 0
    pages: int = 0
    by_code: Dict[str, int] = Field(default_factory=dict)
    user_excluded: ReviewExcludedCounts = Field(default_factory=ReviewExcludedCounts)


class ReviewHypothesis(BaseModel):
    id: str
    item_id: str
    display_id: str
    occurrence_id: Optional[str] = None
    system_id: Optional[str] = None
    timestamp_sec: Optional[float] = None
    status: Literal["review_required", "unresolved", "fail"]
    code: str
    page_index: Optional[int] = None
    raw_crop: str
    primary_crop: Optional[str] = None
    crop_scale: float


class JobReviewHypothesesResponse(BaseModel):
    job_id: str
    status: Literal["pass", "review_required", "fail", "unassessed"] = "unassessed"
    export_revision: Optional[int] = None
    counts: ReviewHypothesisCounts = Field(default_factory=ReviewHypothesisCounts)
    total: int = 0
    offset: int = 0
    limit: int = 100
    hypotheses: List[ReviewHypothesis] = Field(default_factory=list)
    truncated: bool = False


class JobReviewExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_captures: List[str] = Field(default_factory=list)
    keep_images: List[str] = Field(default_factory=list)
    formats: Optional[List[Literal["png", "jpg", "jpeg", "pdf"]]] = None
    document_header: Optional[ExportOptions.DocumentHeaderOptions] = None
    # Clean reflow jobs: every system strip path in the order the user arranged
    # them (included and excluded). keep_captures are composed in this order.
    system_order: List[str] = Field(default_factory=list)
    # Clean reflow jobs: an explicit user choice of the document staff size in mm
    # (e.g. a smaller size allowed for this document to resolve a layout conflict).
    # Omitted: the document's current size. A size other than the job's is used as it is;
    # with the job's size, old requests without a mode may use a smaller size for a dense
    # chart. Modern clients send staff_gap_mm_explicit with every size choice (also 1.5 mm).
    staff_gap_mm: Optional[float] = Field(default=None, ge=1.0, le=2.5)
    # Explicit mode wins even at the product default; None keeps old-client inference.
    staff_gap_mm_explicit: Optional[bool] = None
    # Clean reflow jobs: rearrange by measure for this export (True) or keep whole
    # systems (False). Omitted: the job's own option (False for jobs saved before it existed).
    measure_reflow: Optional[bool] = None
    # Full desired override set. None keeps the committed set; [] clears it.
    rejected_seam_ids: Optional[List[str]] = None
    base_revision: Optional[int] = Field(default=None, ge=0)
    # Original screens fallback (docs/reflow/ORIGINAL_SCREENS_DESIGN.md): rebuild the job as whole
    # screens. Without keep_captures it captures from the source video; with keep_captures it
    # rebuilds from the saved screens with exactly those. Omitted: the clean reflow export above.
    output_model: Optional[Literal["original_screens_v1"]] = None

    @model_validator(mode="after")
    def validate_selection_mode(self):
        if self.output_model == "original_screens_v1":
            clean_only = [name for name in ("system_order", "staff_gap_mm", "staff_gap_mm_explicit", "measure_reflow",
                                            "rejected_seam_ids", "keep_images") if name in self.model_fields_set]
            if clean_only:
                raise ValueError(f"original_screens_v1 does not take clean reflow fields: {', '.join(clean_only)}")
            return self
        if self.keep_captures and self.keep_images:
            raise ValueError("keep_captures and keep_images cannot be used together")
        if not self.keep_captures and not self.keep_images:
            raise ValueError("keep_captures must include at least one capture")
        return self


class JobReviewExportResponse(BaseModel):
    images: List[str] = Field(default_factory=list)
    pdf: Optional[str] = None
    output_dir: str
    kept_count: int = 0
    # Clean reflow jobs: which layout produced this export ({requested, applied, status, reason}).
    measure_reflow: Optional[Dict[str, Any]] = None
    # Clean reflow jobs: the document revision this export produced.
    revision: Optional[int] = None
    review_required: bool = False
    review_reasons: List[Any] = Field(default_factory=list)


class ReviewExportTaskResponse(BaseModel):
    """A background review export (POST /jobs/{id}/review-export answers 202 with this).

    ``state``: queued | running | done | failed | cancelled. ``stage``: queued, planning, sizing,
    rendering, writing, done (or cancelled / interrupted). ``result`` is set when done (the payload
    the synchronous export used to return); ``error_code`` / ``error`` / ``error_status`` when it
    failed (UNCUT_STRIP_UNAVAILABLE, LAYOUT_CONFLICT, LEGACY_JOB, INVALID_REQUEST, EXPORT_FAILED,
    EXPORT_INTERRUPTED) or was cancelled (EXPORT_CANCELLED)."""

    task_id: str
    job_id: str
    revision: int
    state: str
    stage: str
    progress: float = 0.0
    message: str = ""
    result: Optional[JobReviewExportResponse] = None
    error_code: Optional[str] = None
    error: Optional[str] = None
    error_status: Optional[int] = None
    cancel_requested: bool = False
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    updated_at: float


class CaptureCropRequest(BaseModel):
    capture_path: str
    roi: List[List[float]] = Field(default_factory=list)


class CaptureCropResponse(BaseModel):
    capture_path: str
    width: int
    height: int


class PreviewFrameRequest(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    start_sec: Optional[float] = Field(default=None, ge=0)


class PreviewDiagnostic(BaseModel):
    level: Literal["info", "warning", "critical"] = "info"
    code: str = ""
    title: str = ""
    detail: str = ""


class PreviewFrameResponse(BaseModel):
    image_path: str
    image_url: Optional[str] = None
    diagnostics: List[PreviewDiagnostic] = Field(default_factory=list)


class PreviewAutoRoiRequest(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    start_sec: Optional[float] = Field(default=None, ge=0)


class PreviewAutoRoiResponse(BaseModel):
    status: Literal["suggested", "not_found"]
    roi: Optional[List[List[float]]] = None
    evidence_level: Literal["high", "medium", "low"] = "low"
    layout_hint: Optional[Literal["bottom_bar", "full_scroll", "page_turn"]] = None
    is_dark_mode: bool = False
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class PreviewLabelRegionRequest(BaseModel):
    """Suggest a section-label region outside the applied score region (an editable draft)."""
    file_path: str
    roi: List[List[float]]
    start_sec: Optional[float] = Field(default=None, ge=0)
    end_sec: Optional[float] = Field(default=None, ge=0)

    @field_validator("roi")
    @classmethod
    def validate_roi(cls, value: List[List[float]]):
        if len(value) != 4 or any(len(point) != 2 for point in value):
            raise ValueError("roi must be 4 points: [[x,y], ...]")
        return value


class PreviewLabelRegionResponse(BaseModel):
    status: Literal["suggested", "not_found"]
    label_roi: Optional[List[List[float]]] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class PreviewRoiHealthRequest(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    start_sec: Optional[float] = Field(default=None, ge=0)
    roi: List[List[float]] = Field(default_factory=list)

    @field_validator("roi")
    @classmethod
    def validate_roi(cls, value: List[List[float]]):
        if len(value) != 4:
            raise ValueError("roi must be 4 points: [[x,y], ...]")
        for point in value:
            if len(point) != 2:
                raise ValueError("each roi point must be [x, y]")
        return value


class PreviewRoiHealthResponse(BaseModel):
    risk_level: Literal["info", "warning", "critical"] = "info"
    summary: str = ""
    diagnostics: List[PreviewDiagnostic] = Field(default_factory=list)
    sampled_frames: int = 0
    checked_seconds: List[float] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    # Whole-source notation clipping check (ENVELOPE_CLIPPED); see
    # app/pipeline/notation_envelope.py.
    envelope: Dict[str, Any] = Field(default_factory=dict)


class PreviewSourceRequest(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None


class PreviewSourceResponse(BaseModel):
    video_path: str
    video_url: Optional[str] = None
    from_cache: bool = False
    log_lines: List[str] = Field(default_factory=list)


class PreviewSourceJobCreateRequest(BaseModel):
    youtube_url: str


class PreviewSourceJobCreateResponse(BaseModel):
    job_id: str


class PreviewSourceJobStatusResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    message: str
    progress: float
    progress_mode: Literal["determinate", "indeterminate"] = "indeterminate"
    result: Dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None
    log_tail: List[str] = Field(default_factory=list)


class LocalMediaRegistryItem(BaseModel):
    source_path: str
    display_name: str
    directory: str
    resolution_label: str = ""
    duration_label: str = ""
    width: int = 0
    height: int = 0
    duration_sec: float = 0.0
    pdf_path: Optional[str] = None
    output_dir: Optional[str] = None
    has_score: bool = False
    source_origin: Literal["job", "prepared"] = "job"
    youtube_url: Optional[str] = None
    updated_at: float = 0.0


class LocalMediaRegistryResponse(BaseModel):
    items: List[LocalMediaRegistryItem] = Field(default_factory=list)


class ArchiveLibraryItem(BaseModel):
    source_key: str
    source_kind: Literal["file", "youtube"]
    display_name: str
    completed_at: float = 0.0
    source_path: str = ""
    pdf_path: str
    output_dir: Optional[str] = None
    youtube_url: Optional[str] = None


class ArchiveLibraryResponse(BaseModel):
    items: List[ArchiveLibraryItem] = Field(default_factory=list)


class RuntimeStatusResponse(BaseModel):
    overall_mode: Literal["gpu", "cpu"]
    ffmpeg_mode: str
    opencv_mode: str
    ffmpeg_order: List[str]
    gpu_name: Optional[str]
    cpu_name: str
    upscale_available: bool = False
    upscale_engine_hint: str = "none"
    hat_available: bool = False
    hat_device: str = "none"
    app_version: str
    preview_cache_namespace: str
    youtube_download_strategy: str
    youtube_downloader_version: str = ""


class CacheClearResponse(BaseModel):
    cleared_paths: int = 0
    cleared_jobs: int = 0
    reclaimed_bytes: int = 0
    reclaimed_human: str = "0 B"
    skipped_paths: List[str] = Field(default_factory=list)


class AppActivityResponse(BaseModel):
    active_jobs: int = 0
    active_source_jobs: int = 0
    inflight_requests: int = 0
    # background review exports (PDF rebuilds) queued or running
    active_exports: int = 0


class CacheUsageResponse(BaseModel):
    total_paths: int = 0
    total_bytes: int = 0
    total_human: str = "0 B"
