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
    layout_hint: LayoutHint = "auto"

    @field_validator("roi")
    @classmethod
    def validate_roi(cls, value: List[List[float]]):
        if len(value) != 4:
            raise ValueError("roi must be 4 points: [[x,y], ...]")
        for point in value:
            if len(point) != 2:
                raise ValueError("each roi point must be [x, y]")
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

class JobOptions(BaseModel):
    extract: ExtractOptions = Field(default_factory=ExtractOptions)
    detect: DetectOptions = Field(default_factory=DetectOptions)
    rectify: RectifyOptions = Field(default_factory=RectifyOptions)
    stitch: StitchOptions = Field(default_factory=StitchOptions)
    upscale: UpscaleOptions = Field(default_factory=UpscaleOptions)
    export: ExportOptions = Field(default_factory=ExportOptions)


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


class JobReviewExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_captures: List[str] = Field(default_factory=list)
    keep_images: List[str] = Field(default_factory=list)
    formats: Optional[List[Literal["png", "jpg", "jpeg", "pdf"]]] = None

    @model_validator(mode="after")
    def validate_selection_mode(self):
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


class CacheClearResponse(BaseModel):
    cleared_paths: int = 0
    cleared_jobs: int = 0
    reclaimed_bytes: int = 0
    reclaimed_human: str = "0 B"
    skipped_paths: List[str] = Field(default_factory=list)


class CacheUsageResponse(BaseModel):
    total_paths: int = 0
    total_bytes: int = 0
    total_human: str = "0 B"
