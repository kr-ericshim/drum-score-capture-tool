from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

_ERROR_CODE_UNSET = object()


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class ProgressMode(str, Enum):
    DETERMINATE = "determinate"
    INDETERMINATE = "indeterminate"


@dataclass
class Job:
    id: str
    source_type: str
    file_path: Optional[str]
    youtube_url: Optional[str]
    options: Dict
    artifact_dir: str
    source_identity: Dict = field(default_factory=dict)
    completed_at: Optional[float] = None
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    current_step: str = "queued"
    message: str = ""
    result: Dict = field(default_factory=dict)
    error_code: Optional[str] = None
    log: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_record(self) -> Dict:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "file_path": self.file_path,
            "youtube_url": self.youtube_url,
            "options": self.options,
            "artifact_dir": self.artifact_dir,
            "source_identity": dict(self.source_identity),
            "completed_at": self.completed_at,
            "status": self.status.value,
            "progress": self.progress,
            "current_step": self.current_step,
            "message": self.message,
            "result": self.result,
            "error_code": self.error_code,
            "log": list(self.log),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, payload: Dict) -> "Job":
        return cls(
            id=str(payload.get("id") or ""),
            source_type=str(payload.get("source_type") or "file"),
            file_path=payload.get("file_path"),
            youtube_url=payload.get("youtube_url"),
            options=dict(payload.get("options") or {}),
            artifact_dir=str(payload.get("artifact_dir") or ""),
            source_identity=dict(payload.get("source_identity") or {}),
            completed_at=(
                None
                if payload.get("completed_at") in (None, "")
                else float(payload.get("completed_at"))
            ),
            status=JobStatus(str(payload.get("status") or JobStatus.QUEUED.value)),
            progress=float(payload.get("progress") or 0.0),
            current_step=str(payload.get("current_step") or "queued"),
            message=str(payload.get("message") or ""),
            result=dict(payload.get("result") or {}),
            error_code=str(payload.get("error_code") or "") or None,
            log=[str(line) for line in payload.get("log", [])],
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
        )

    def to_public_dict(self) -> Dict:
        return {
            "job_id": self.id,
            "status": self.status.value,
            "progress": self.progress,
            "current_step": self.current_step,
            "message": self.message,
            "result": self.result,
            "error_code": self.error_code,
            "log_tail": self.log[-20:],
        }


@dataclass
class SourcePrepareJob:
    id: str
    youtube_url: str
    artifact_dir: str
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    message: str = ""
    progress: float = 0.0
    progress_mode: ProgressMode = ProgressMode.INDETERMINATE
    result: Dict = field(default_factory=dict)
    error_code: Optional[str] = None
    log: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_record(self) -> Dict:
        return {
            "id": self.id,
            "youtube_url": self.youtube_url,
            "artifact_dir": self.artifact_dir,
            "status": self.status.value,
            "stage": self.stage,
            "message": self.message,
            "progress": self.progress,
            "progress_mode": self.progress_mode.value,
            "result": self.result,
            "error_code": self.error_code,
            "log": list(self.log),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, payload: Dict) -> "SourcePrepareJob":
        return cls(
            id=str(payload.get("id") or ""),
            youtube_url=str(payload.get("youtube_url") or ""),
            artifact_dir=str(payload.get("artifact_dir") or ""),
            status=JobStatus(str(payload.get("status") or JobStatus.QUEUED.value)),
            stage=str(payload.get("stage") or "queued"),
            message=str(payload.get("message") or ""),
            progress=float(payload.get("progress") or 0.0),
            progress_mode=ProgressMode(str(payload.get("progress_mode") or ProgressMode.INDETERMINATE.value)),
            result=dict(payload.get("result") or {}),
            error_code=str(payload.get("error_code") or "") or None,
            log=[str(line) for line in payload.get("log", [])],
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
        )

    def to_public_dict(self) -> Dict:
        return {
            "job_id": self.id,
            "status": self.status.value,
            "stage": self.stage,
            "message": self.message,
            "progress": self.progress,
            "progress_mode": self.progress_mode.value,
            "result": self.result,
            "error_code": self.error_code,
            "log_tail": self.log[-40:],
        }


class JobStore:
    def __init__(self, root: Path):
        self._jobs: Dict[str, Job] = {}
        self._lock = Lock()
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._load_existing_jobs()

    def create(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._persist_job_locked(job)

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def active_job_ids(self) -> List[str]:
        with self._lock:
            return [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            ]

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._jobs)
            self._jobs.clear()
            return count

    def log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.log.append(message)
            job.updated_at = time.time()
            self._persist_job_locked(job)

    def set_state(
        self,
        job_id: str,
        status: JobStatus,
        progress: Optional[float] = None,
        current_step: Optional[str] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error_code: Optional[str] | object = _ERROR_CODE_UNSET,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            if progress is not None:
                job.progress = max(0.0, min(1.0, progress))
            if current_step is not None:
                job.current_step = current_step
            if message is not None:
                job.message = message
            if result is not None:
                job.result = result
            if error_code is not _ERROR_CODE_UNSET:
                job.error_code = error_code
            if status == JobStatus.DONE and job.completed_at is None:
                job.completed_at = time.time()
            job.updated_at = time.time()
            self._persist_job_locked(job)

    @property
    def root(self) -> Path:
        return self._root

    def _job_metadata_path(self, artifact_dir: str) -> Path:
        return Path(artifact_dir) / "job.json"

    def _persist_job_locked(self, job: Job) -> None:
        artifact_dir = Path(job.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self._job_metadata_path(job.artifact_dir)
        payload = json.dumps(job.to_record(), ensure_ascii=True, indent=2)
        tmp_path = metadata_path.with_name(f"{metadata_path.name}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(metadata_path)

    def _load_existing_jobs(self) -> None:
        for metadata_path in sorted(self._root.glob("*/job.json")):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                job = Job.from_record(payload)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                job = self._recover_corrupt_job(metadata_path)

            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                job.status = JobStatus.ERROR
                job.current_step = "failed"
                job.message = "job recovered after restart; rerun the capture"
                job.error_code = "RECOVERED_AFTER_RESTART"
                job.log.append("job recovered after restart")
                job.updated_at = time.time()

            self._jobs[job.id] = job
            try:
                self._persist_job_locked(job)
            except OSError:
                continue

    def _recover_corrupt_job(self, metadata_path: Path) -> Job:
        backup_path = metadata_path.with_name("job.corrupt.json")
        if backup_path.exists():
            backup_path.unlink()
        metadata_path.replace(backup_path)
        now = time.time()
        return Job(
            id=metadata_path.parent.name,
            source_type="file",
            file_path=None,
            youtube_url=None,
            options={},
            artifact_dir=str(metadata_path.parent),
            status=JobStatus.ERROR,
            progress=0.0,
            current_step="failed",
            message="job metadata was corrupt after restart; rerun the capture",
            error_code="RECOVERED_CORRUPT_METADATA",
            log=["job metadata was corrupt after restart"],
            created_at=now,
            updated_at=now,
        )


class SourcePrepareStore:
    def __init__(self, root: Path):
        self._jobs: Dict[str, SourcePrepareJob] = {}
        self._lock = Lock()
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._load_existing_jobs()

    def create(self, job: SourcePrepareJob) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._persist_job_locked(job)

    def get(self, job_id: str) -> Optional[SourcePrepareJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.log.append(message)
            job.updated_at = time.time()
            self._persist_job_locked(job)

    def set_state(
        self,
        job_id: str,
        status: JobStatus,
        *,
        stage: Optional[str] = None,
        progress: Optional[float] = None,
        progress_mode: Optional[ProgressMode] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error_code: Optional[str] | object = _ERROR_CODE_UNSET,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            if stage is not None:
                job.stage = stage
            if progress is not None:
                job.progress = max(0.0, min(1.0, float(progress)))
            if progress_mode is not None:
                job.progress_mode = progress_mode
            if message is not None:
                job.message = message
            if result is not None:
                job.result = result
            if error_code is not _ERROR_CODE_UNSET:
                job.error_code = error_code
            job.updated_at = time.time()
            self._persist_job_locked(job)

    @property
    def root(self) -> Path:
        return self._root

    def _job_metadata_path(self, artifact_dir: str) -> Path:
        return Path(artifact_dir) / "job.json"

    def _persist_job_locked(self, job: SourcePrepareJob) -> None:
        artifact_dir = Path(job.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self._job_metadata_path(job.artifact_dir)
        payload = json.dumps(job.to_record(), ensure_ascii=True, indent=2)
        tmp_path = metadata_path.with_name(f"{metadata_path.name}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(metadata_path)

    def _load_existing_jobs(self) -> None:
        for metadata_path in sorted(self._root.glob("*/job.json")):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                job = SourcePrepareJob.from_record(payload)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                job = self._recover_corrupt_job(metadata_path)

            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                job.status = JobStatus.ERROR
                job.stage = "failed"
                job.message = "source prepare recovered after restart; retry the YouTube source"
                job.error_code = "RECOVERED_AFTER_RESTART"
                job.log.append("source prepare recovered after restart")
                job.updated_at = time.time()

            self._jobs[job.id] = job
            try:
                self._persist_job_locked(job)
            except OSError:
                continue

    def _recover_corrupt_job(self, metadata_path: Path) -> SourcePrepareJob:
        backup_path = metadata_path.with_name("job.corrupt.json")
        if backup_path.exists():
            backup_path.unlink()
        metadata_path.replace(backup_path)
        now = time.time()
        return SourcePrepareJob(
            id=metadata_path.parent.name,
            youtube_url="",
            artifact_dir=str(metadata_path.parent),
            status=JobStatus.ERROR,
            stage="failed",
            message="source prepare metadata was corrupt after restart; retry the YouTube source",
            error_code="RECOVERED_CORRUPT_METADATA",
            log=["source prepare metadata was corrupt after restart"],
            created_at=now,
            updated_at=now,
        )
