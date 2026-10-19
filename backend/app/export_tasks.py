"""Background review exports ("PDF 다시 만들기"): one task per job at a time.

A task is kept in memory while this process runs it and is mirrored to
``<job artifact dir>/review_export_task.json`` (the latest task of the job). A file
that says queued/running but has no live task in this process was left by a backend
that stopped mid-export: it is reported as failed (EXPORT_INTERRUPTED), never as running.
The export itself is transactional (staged folder, then install), so an interrupted,
cancelled or failed task leaves the previous export and result as they were.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Any, Dict, Optional

TASK_FILE = "review_export_task.json"

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
ACTIVE_STATES = (QUEUED, RUNNING)

# progress ranges of the stages a background export reports (process_control.report_progress)
STAGE_RANGES = {
    "queued": (0.0, 0.0),
    "recovering": (0.01, 0.06),
    "rebuilding": (0.06, 0.15),
    "planning": (0.02, 0.30),
    "capturing": (0.02, 0.50),  # original screens: frames from the source video
    "comparing": (0.50, 0.60),  # original screens: dropping repeated screens
    "sizing": (0.30, 0.60),
    "rendering": (0.60, 0.80),
    "writing": (0.80, 0.99),
    "done": (1.0, 1.0),
}

EXPORT_IN_PROGRESS = "EXPORT_IN_PROGRESS"
EXPORT_INTERRUPTED = "EXPORT_INTERRUPTED"
EXPORT_CANCELLED = "EXPORT_CANCELLED"
EXPORT_FAILED = "EXPORT_FAILED"
INVALID_REQUEST = "INVALID_REQUEST"

INTERRUPTED_DETAIL = (
    "EXPORT_INTERRUPTED: 처리기가 다시 시작되어 PDF 다시 만들기가 끝나지 않았습니다. 이전 파일은 그대로 있습니다. "
    "/ The processor restarted before the rebuild finished. The previous files are kept."
)


def stage_progress(stage: str, fraction: Optional[float]) -> float:
    low, high = STAGE_RANGES.get(stage, (0.0, 0.0))
    f = 0.0 if fraction is None else max(0.0, min(1.0, float(fraction)))
    return round(low + (high - low) * f, 4)


def error_code_for(status_code: int, detail: str) -> str:
    """The code a failed task reports: the detail's own prefix (UNCUT_STRIP_UNAVAILABLE,
    LAYOUT_CONFLICT, LEGACY_JOB, ...) when it has one, else a code for the status."""
    head = str(detail or "").split(":", 1)[0].strip()
    if head and head.replace("_", "").isalnum() and head.upper() == head and "_" in head:
        return head
    return INVALID_REQUEST if 400 <= int(status_code or 500) < 500 else EXPORT_FAILED


@dataclass
class ExportTask:
    id: str
    job_id: str
    revision: int  # the job's revision this export produces when it finishes
    state: str = QUEUED
    stage: str = "queued"
    progress: float = 0.0
    message: str = ""
    result: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error: Optional[str] = None
    error_status: Optional[int] = None
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    updated_at: float = field(default_factory=time.time)

    def public(self) -> Dict[str, Any]:
        out = asdict(self)
        out["task_id"] = out.pop("id")
        return out

    @classmethod
    def from_record(cls, payload: Dict[str, Any]) -> "ExportTask":
        if not isinstance(payload, dict):
            raise ValueError("export task record is not an object")
        known = {k: payload[k] for k in cls.__dataclass_fields__ if k in payload}
        known.setdefault("id", payload.get("task_id") or "")
        return cls(**known)


class ExportBusy(Exception):
    def __init__(self, task: ExportTask):
        super().__init__(task.id)
        self.task = task


class ExportTaskStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._live: Dict[str, ExportTask] = {}  # job id -> task run by this process
        self._dirs: Dict[str, Path] = {}
        self._cancel: Dict[str, Event] = {}  # task id -> cancel event

    # -- queries ---------------------------------------------------------------------------
    def latest(self, job_id: str, artifact_dir: str | Path) -> Optional[ExportTask]:
        with self._lock:
            live = self._live.get(job_id)
            if live is not None:
                return ExportTask(**asdict(live))
            path = Path(artifact_dir) / TASK_FILE
            try:
                task = ExportTask.from_record(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                return None
            if task.state in ACTIVE_STATES:
                # left by a backend that stopped mid-export
                now = time.time()
                task.state, task.stage = FAILED, "interrupted"
                task.error_code, task.error, task.error_status = EXPORT_INTERRUPTED, INTERRUPTED_DETAIL, 500
                task.message = "interrupted"
                task.finished_at = task.updated_at = now
                try:
                    self._write(path, task)
                except OSError:
                    pass  # reported as interrupted either way
            return task

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._live.values() if t.state in ACTIVE_STATES)

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            task = self._live.get(job_id)
            return bool(task and task.state in ACTIVE_STATES)

    def cancel_event(self, task_id: str) -> Event:
        with self._lock:
            return self._cancel.setdefault(task_id, Event())

    # -- changes ---------------------------------------------------------------------------
    def begin(self, job_id: str, artifact_dir: str | Path, revision: int) -> ExportTask:
        """Register a queued task, or raise ExportBusy with the job's running one."""
        with self._lock:
            live = self._live.get(job_id)
            if live is not None and live.state in ACTIVE_STATES:
                raise ExportBusy(ExportTask(**asdict(live)))
            task = ExportTask(id=uuid.uuid4().hex[:12], job_id=job_id, revision=int(revision), message="queued")
            self._live[job_id] = task
            self._dirs[job_id] = Path(artifact_dir)
            self._cancel[task.id] = Event()
            self._persist_locked(task)
            return ExportTask(**asdict(task))

    def update(self, job_id: str, task_id: str, **changes: Any) -> Optional[ExportTask]:
        with self._lock:
            task = self._live.get(job_id)
            if task is None or task.id != task_id:
                return None
            if task.state not in ACTIVE_STATES and changes.get("state") in ACTIVE_STATES:
                return ExportTask(**asdict(task))  # a finished task never goes back to running
            for key, value in changes.items():
                setattr(task, key, value)
            now = time.time()
            task.updated_at = now
            if task.state == RUNNING and task.started_at is None:
                task.started_at = now
            if task.state not in ACTIVE_STATES:
                task.finished_at = task.finished_at or now
                self._cancel.pop(task.id, None)
            self._persist_locked(task)
            return ExportTask(**asdict(task))

    def progress(self, job_id: str, task_id: str, stage: str, fraction: Optional[float]) -> None:
        with self._lock:
            task = self._live.get(job_id)
            if task is None or task.id != task_id or task.state not in ACTIVE_STATES:
                return
            value = stage_progress(stage, fraction)
            changed = stage != task.stage or abs(value - task.progress) >= 0.01
            task.stage = stage
            task.progress = max(task.progress, value)
            task.state = RUNNING
            task.updated_at = time.time()
            if changed:
                self._persist_locked(task)

    def request_cancel(self, job_id: str, task_id: str) -> Optional[ExportTask]:
        """Ask the task to stop. A queued task is cancelled at once; a running one stops at its next
        stage boundary, and one already writing its files may still finish (cancel_requested stays set)."""
        with self._lock:
            task = self._live.get(job_id)
            if task is None or task.id != task_id:
                return None
            if task.state in ACTIVE_STATES:
                task.cancel_requested = True
                self._cancel.setdefault(task.id, Event()).set()
                now = time.time()
                if task.state == QUEUED:
                    task.state, task.stage, task.message = CANCELLED, "cancelled", "cancelled"
                    task.error_code = EXPORT_CANCELLED
                    task.finished_at = now
                else:
                    task.message = "cancelling"
                task.updated_at = now
                self._persist_locked(task)
            return ExportTask(**asdict(task))

    # -- persistence -----------------------------------------------------------------------
    def _persist_locked(self, task: ExportTask) -> None:
        folder = self._dirs.get(task.job_id)
        if folder is None:
            return
        try:
            self._write(folder / TASK_FILE, task)
        except OSError:
            pass  # the in-memory task stays authoritative while this process runs

    @staticmethod
    def _write(path: Path, task: ExportTask) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps(asdict(task), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
