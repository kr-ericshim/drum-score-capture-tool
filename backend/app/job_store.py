from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    id: str
    source_type: str
    file_path: Optional[str]
    youtube_url: Optional[str]
    options: Dict
    artifact_dir: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    current_step: str = "queued"
    message: str = ""
    result: Dict = field(default_factory=dict)
    error_code: Optional[str] = None
    log: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

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


class JobStore:
    def __init__(self, root: Path):
        self._jobs: Dict[str, Job] = {}
        self._lock = Lock()
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def create(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def log(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.log.append(message)
            job.updated_at = time.time()

    def set_state(
        self,
        job_id: str,
        status: JobStatus,
        progress: Optional[float] = None,
        current_step: Optional[str] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error_code: Optional[str] = None,
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
            if error_code is not None:
                job.error_code = error_code
            job.updated_at = time.time()

    @property
    def root(self) -> Path:
        return self._root
