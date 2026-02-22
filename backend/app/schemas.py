from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


LayoutHint = Literal["auto", "bottom_bar", "full_scroll", "page_turn"]
CaptureSensitivity = Literal["low", "medium", "high"]
DedupeLevel = Literal["aggressive", "normal", "sensitive"]


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
    mode: Literal["auto", "manual"] = "auto"
    roi: Optional[List[List[float]]] = None
    layout_hint: LayoutHint = "auto"
    prefer_bottom: Optional[bool] = None

    @field_validator("roi")
    @classmethod
    def validate_roi(cls, value: Optional[List[List[float]]]):
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError("roi must be 4 points: [[x,y], ...]")
        for point in value:
            if len(point) != 2:
                raise ValueError("each roi point must be [x, y]")
        return value

    @model_validator(mode="after")
    def validate_manual_roi(self):
        if self.mode == "manual" and not self.roi:
            raise ValueError("roi is required when detect mode is manual")
        return self


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
    formats: List[Literal["png", "jpg", "jpeg", "pdf"]] = Field(default_factory=lambda: ["png", "pdf"])
    output_dir: Optional[str] = None
    include_raw_frames: bool = False


class AudioSeparationOptions(BaseModel):
    enable: bool = False
    engine: Literal["uvr_demucs"] = "uvr_demucs"
    model: str = "htdemucs"
    stem: Literal["drums"] = "drums"
    output_format: Literal["wav", "mp3"] = "wav"
    gpu_only: bool = False


class JobOptions(BaseModel):
    extract: ExtractOptions = Field(default_factory=ExtractOptions)
    detect: DetectOptions = Field(default_factory=DetectOptions)
    rectify: RectifyOptions = Field(default_factory=RectifyOptions)
    stitch: StitchOptions = Field(default_factory=StitchOptions)
    upscale: UpscaleOptions = Field(default_factory=UpscaleOptions)
    audio: AudioSeparationOptions = Field(default_factory=AudioSeparationOptions)
    export: ExportOptions = Field(default_factory=ExportOptions)


class JobCreate(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
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


class PreviewFrameRequest(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    start_sec: Optional[float] = Field(default=None, ge=0)


class PreviewFrameResponse(BaseModel):
    image_path: str
    image_url: Optional[str] = None


class PreviewSourceRequest(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None


class PreviewSourceResponse(BaseModel):
    video_path: str
    video_url: Optional[str] = None
    from_cache: bool = False


class AudioSeparateRequest(BaseModel):
    source_type: Literal["file", "youtube"]
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    options: AudioSeparationOptions = Field(default_factory=lambda: AudioSeparationOptions(enable=True))


class AudioSeparateResponse(BaseModel):
    audio_stem: str
    audio_url: Optional[str] = None
    audio_stems: Dict[str, str] = Field(default_factory=dict)
    audio_stem_urls: Dict[str, str] = Field(default_factory=dict)
    audio_engine: str
    audio_model: str
    audio_device: str
    output_dir: str
    log_tail: List[str] = Field(default_factory=list)


class BeatTrackOptions(BaseModel):
    model: str = "small0"
    gpu_only: bool = False
    use_dbn: bool = False
    float16: bool = False
    save_tsv: bool = True


class AudioBeatTrackRequest(BaseModel):
    source_type: Literal["file", "youtube"] = "file"
    file_path: Optional[str] = None
    youtube_url: Optional[str] = None
    audio_path: Optional[str] = None
    options: BeatTrackOptions = Field(default_factory=BeatTrackOptions)

    @model_validator(mode="after")
    def validate_source(self):
        if self.audio_path:
            return self
        if self.source_type == "file" and not self.file_path:
            raise ValueError("file_path is required when source_type is file")
        if self.source_type == "youtube" and not self.youtube_url:
            raise ValueError("youtube_url is required when source_type is youtube")
        return self


class AudioBeatTrackResponse(BaseModel):
    audio_path: str
    beats: List[float] = Field(default_factory=list)
    downbeats: List[float] = Field(default_factory=list)
    beat_count: int = 0
    downbeat_count: int = 0
    bpm: Optional[float] = None
    model: str
    device: str
    beat_tsv: Optional[str] = None
    beat_tsv_url: Optional[str] = None
    log_tail: List[str] = Field(default_factory=list)


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
