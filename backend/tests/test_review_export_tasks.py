"""Background review export tasks (STRATEGY Step 1c): start, poll, cancel, one per job, restart."""

import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from app import export_tasks as xt
from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_pipeline
from app.pipeline.export import export_composed_pages
from app.pipeline.process_control import report_progress
from app.schemas import CaptureCropRequest, JobReviewExportRequest


def strip_image(label, width=1700, gap=16, top=60, height=220):
    img = np.full((height, width, 3), 250, np.uint8)
    for k in range(5):
        y = top + k * gap
        cv2.line(img, (10, y), (width - 10, y), (0, 0, 0), 2)
    cv2.putText(img, label, (40, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    return img


def digest(folder: Path):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


class ReviewExportTaskTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.artifact = self.root / "job-t"
        strips = self.artifact / "reflow" / "strips"
        strips.mkdir(parents=True)
        self.systems = []
        for i in range(3):
            p = strips / f"strip_sys-00{i + 1}.png"
            cv2.imwrite(str(p), strip_image(f"S{i + 1}"))
            self.systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(p), "issues": [],
                                 "t_start": i * 5.0, "t_end": i * 5.0 + 4.0,
                                 "strip": {"staff_gap_px": 16.0, "size": [1700, 220]}})
        plan, pages = reflow_pipeline.compose_systems(self.systems, header={"title": "T"})
        out = export_composed_pages(pages=pages, formats=["png", "pdf"], workspace=self.artifact / "export", logger=lambda _m: None)
        reflow = {"systems": self.systems, "page_plan": plan, "header": {"title": "T"}, "revision": 1, "duplicate_suggestions": []}
        result = {"output_model": "clean_reflow_v1", "reflow_state": "done", "reflow": reflow, "images": out["images"], "pdf": out["pdf"],
                  **main._reflow_capture_fields(reflow)}
        self.store = JobStore(self.root)
        self.store.create(Job(id="job-t", source_type="file", file_path=str(self.root / "v.mp4"), youtube_url=None,
                              options={"export": {"formats": ["png", "pdf"]}}, artifact_dir=str(self.artifact),
                              status=JobStatus.DONE, result=result))
        self.tasks = xt.ExportTaskStore()
        self.paths = [s["strip_path"] for s in self.systems]
        for p in (patch.object(main, "job_store", self.store), patch.object(main, "export_task_store", self.tasks)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        # let a task still running finish before the folder goes away
        deadline = time.monotonic() + 30
        while self.tasks.active_count() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.td.cleanup()

    def _request(self, **kw):
        return JobReviewExportRequest(keep_captures=kw.pop("keep", [self.paths[1], self.paths[0]]),
                                      formats=kw.pop("formats", ["png", "pdf"]), **kw)

    def _wait(self, task_id, timeout=60.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = main.get_review_export("job-t", task_id)
            if task.state not in xt.ACTIVE_STATES:
                return task
            time.sleep(0.02)
        self.fail("export task did not finish")

    def _blocking_compose(self):
        """compose_systems that reports planning, then waits for ``release`` before going on."""
        started, release = threading.Event(), threading.Event()
        real = reflow_pipeline.compose_systems

        def compose(*args, **kwargs):
            report_progress("planning", 0.5)
            started.set()
            release.wait(10)
            report_progress("sizing", 0.0)  # a cancel requested meanwhile stops here
            return real(*args, **kwargs)
        return compose, started, release

    def test_start_answers_at_once_then_polling_reports_progress_and_the_result(self):
        stages = []
        real_progress = self.tasks.progress

        def record(job_id, task_id, stage, fraction):
            stages.append(stage)
            real_progress(job_id, task_id, stage, fraction)

        with patch.object(self.tasks, "progress", side_effect=record):
            started = main.start_review_export("job-t", self._request(system_order=list(self.paths)))
            self.assertEqual(started.job_id, "job-t")
            self.assertEqual(started.revision, 2)
            self.assertIn(started.state, ("queued", "running"))
            done = self._wait(started.task_id)
        self.assertEqual(done.state, "done")
        self.assertEqual(done.stage, "done")
        self.assertEqual(done.progress, 1.0)
        self.assertIsNone(done.error_code)
        self.assertEqual(done.result.kept_count, 2)
        self.assertEqual(done.result.revision, 2)
        self.assertTrue(Path(done.result.pdf).is_file())
        # the stages a whole-system compose passes through, in order
        self.assertEqual([s for i, s in enumerate(stages) if i == 0 or stages[i - 1] != s], ["planning", "rendering", "writing"])
        job = self.store.get("job-t")
        self.assertEqual(job.result["reflow"]["revision"], 2)
        self.assertEqual(job.status, JobStatus.DONE)
        latest = main.get_latest_review_export("job-t")
        self.assertEqual((latest.task_id, latest.state), (started.task_id, "done"))
        saved = json.loads((self.artifact / xt.TASK_FILE).read_text())
        self.assertEqual(saved["state"], "done")
        self.assertEqual(saved["result"]["revision"], 2)

    def test_cancel_stops_the_export_and_keeps_the_previous_files_and_result(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        result_before = json.loads(json.dumps(self.store.get("job-t").result))
        compose, started, release = self._blocking_compose()
        with patch.object(reflow_pipeline, "compose_systems", side_effect=compose):
            task = main.start_review_export("job-t", self._request())
            self.assertTrue(started.wait(10))
            running = main.get_review_export("job-t", task.task_id)
            self.assertEqual((running.state, running.stage), ("running", "planning"))
            self.assertGreater(running.progress, 0.0)
            asked = main.cancel_review_export("job-t", task.task_id)
            self.assertTrue(asked.cancel_requested)
            self.assertEqual(asked.state, "running")  # it stops at its next stage boundary
            release.set()
            final = self._wait(task.task_id)
        self.assertEqual(final.state, "cancelled")
        self.assertEqual(final.error_code, "EXPORT_CANCELLED")
        self.assertIsNone(final.result)
        self.assertEqual(digest(export_dir), before)
        self.assertEqual(self.store.get("job-t").result, result_before)
        self.assertEqual(sorted(p.name for p in self.artifact.iterdir() if p.name.startswith("export_")), [])
        # cancelling a finished task changes nothing
        again = main.cancel_review_export("job-t", task.task_id)
        self.assertEqual(again.state, "cancelled")

    def test_cancel_during_writing_discards_the_staged_pages(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        real = export_composed_pages
        holder = {}

        def write_then_cancel(**kwargs):
            out = real(**kwargs)
            self.tasks.request_cancel("job-t", holder["task"])
            return out
        with patch("app.pipeline.export.export_composed_pages", side_effect=write_then_cancel):
            # the worker cannot run before the task id is known: hold the review lock meanwhile
            with main.maintenance_lock:
                lock = main.review_locks.setdefault("job-t", main.RLock())
            with lock:
                task = main.start_review_export("job-t", self._request())
                holder["task"] = task.task_id
            final = self._wait(task.task_id)
        self.assertEqual(final.state, "cancelled")
        self.assertEqual(digest(export_dir), before)
        self.assertEqual([p.name for p in self.artifact.iterdir() if p.name.startswith("export_staged_")], [])

    def test_a_second_request_while_one_runs_is_refused_and_crops_wait_for_it(self):
        compose, started, release = self._blocking_compose()
        with patch.object(reflow_pipeline, "compose_systems", side_effect=compose):
            first = main.start_review_export("job-t", self._request())
            self.assertTrue(started.wait(10))
            with self.assertRaises(HTTPException) as busy:
                main.start_review_export("job-t", self._request(keep=[self.paths[0]]))
            self.assertEqual(busy.exception.status_code, 409)
            self.assertTrue(busy.exception.detail.startswith("EXPORT_IN_PROGRESS:"))
            self.assertIn(first.task_id, busy.exception.detail)
            with self.assertRaises(HTTPException) as crop:
                main.crop_capture("job-t", CaptureCropRequest(capture_path=self.paths[0], roi=[]))
            self.assertEqual(crop.exception.status_code, 409)
            self.assertEqual(main.app_activity().active_exports, 1)
            with self.assertRaises(HTTPException):
                main.acquire_update_lock()
            self.assertFalse(main.update_install_locked)
            release.set()
            self.assertEqual(self._wait(first.task_id).state, "done")
        self.assertEqual(main.app_activity().active_exports, 0)
        # the next export is accepted once the first one ended
        second = main.start_review_export("job-t", self._request(keep=[self.paths[0]]))
        self.assertNotEqual(second.task_id, first.task_id)
        self.assertEqual(second.revision, 3)
        self.assertEqual(self._wait(second.task_id).state, "done")

    def test_failures_keep_their_codes_and_the_previous_export(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        result_before = json.loads(json.dumps(self.store.get("job-t").result))
        with patch.object(reflow_pipeline, "compose_systems",
                          side_effect=reflow_pipeline.DependencyUnavailableError("sys-002", "missing")):
            failed = self._wait(main.start_review_export("job-t", self._request()).task_id)
        self.assertEqual((failed.state, failed.error_code, failed.error_status), ("failed", "UNCUT_STRIP_UNAVAILABLE", 409))
        self.assertTrue(failed.error.startswith("UNCUT_STRIP_UNAVAILABLE:"))
        with patch("app.pipeline.export.export_composed_pages", side_effect=RuntimeError("disk full")):
            failed = self._wait(main.start_review_export("job-t", self._request()).task_id)
        self.assertEqual((failed.state, failed.error_code, failed.error_status), ("failed", "EXPORT_FAILED", 500))
        self.assertIn("disk full", failed.error)
        self.assertEqual(digest(export_dir), before)
        self.assertEqual(self.store.get("job-t").result, result_before)

    def test_request_errors_answer_at_once_without_a_task(self):
        with self.assertRaises(HTTPException) as bad:
            main.start_review_export("job-t", self._request(keep=[str(self.root / "other.png")]))
        self.assertEqual(bad.exception.status_code, 400)
        with self.assertRaises(HTTPException) as missing:
            main.start_review_export("job-x", self._request())
        self.assertEqual(missing.exception.status_code, 404)
        legacy = dict(self.store.get("job-t").result, output_model="raw_stitch")
        self.store.set_state("job-t", JobStatus.DONE, result=legacy)
        with self.assertRaises(HTTPException) as old:
            main.start_review_export("job-t", self._request())
        self.assertEqual(old.exception.status_code, 409)
        self.assertTrue(old.exception.detail.startswith("LEGACY_JOB:"))
        with self.assertRaises(HTTPException) as none:
            main.get_latest_review_export("job-t")
        self.assertEqual(none.exception.status_code, 404)
        self.assertEqual(self.tasks.active_count(), 0)

    def test_an_export_left_running_by_a_stopped_backend_reads_as_interrupted(self):
        compose, started, release = self._blocking_compose()
        with patch.object(reflow_pipeline, "compose_systems", side_effect=compose):
            task = main.start_review_export("job-t", self._request())
            self.assertTrue(started.wait(10))
            on_disk = json.loads((self.artifact / xt.TASK_FILE).read_text())
            self.assertEqual(on_disk["state"], "running")
            # a new backend process: same files, no live task
            restarted = xt.ExportTaskStore()
            with patch.object(main, "export_task_store", restarted):
                seen = main.get_review_export("job-t", task.task_id)
                self.assertEqual((seen.state, seen.error_code, seen.stage), ("failed", "EXPORT_INTERRUPTED", "interrupted"))
                self.assertTrue(seen.error.startswith("EXPORT_INTERRUPTED:"))
                self.assertEqual(main.app_activity().active_exports, 0)
            self.assertEqual(json.loads((self.artifact / xt.TASK_FILE).read_text())["state"], "failed")
            self.tasks.request_cancel("job-t", task.task_id)
            release.set()
            self.assertEqual(self._wait(task.task_id).state, "cancelled")

    def test_a_queued_task_cancelled_before_it_starts_never_runs(self):
        with patch.object(main, "_review_export_reflow") as compose:
            # hold the single export worker so the task stays queued
            gate = threading.Event()
            main.export_executor.submit(gate.wait, 10)
            try:
                task = main.start_review_export("job-t", self._request())
                self.assertEqual(task.state, "queued")
                cancelled = main.cancel_review_export("job-t", task.task_id)
                self.assertEqual((cancelled.state, cancelled.error_code), ("cancelled", "EXPORT_CANCELLED"))
            finally:
                gate.set()
            # the worker runs in order: once this returns, the queued task has been taken up
            main.export_executor.submit(lambda: None).result(10)
        self.assertEqual(main.get_review_export("job-t", task.task_id).state, "cancelled")
        compose.assert_not_called()


class StageProgressTest(unittest.TestCase):
    def test_stage_ranges_rise_through_the_stages(self):
        values = [xt.stage_progress(s, f) for s, f in (("planning", 0), ("planning", 1), ("sizing", 0.5), ("rendering", 0),
                                                        ("writing", 0), ("writing", 1), ("done", None))]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 1.0)

    def test_error_codes_come_from_the_detail_prefix(self):
        self.assertEqual(xt.error_code_for(409, "LAYOUT_CONFLICT: sys-001 do not fit"), "LAYOUT_CONFLICT")
        self.assertEqual(xt.error_code_for(409, "LEGACY_JOB: made before"), "LEGACY_JOB")
        self.assertEqual(xt.error_code_for(400, "unknown system: x"), "INVALID_REQUEST")
        self.assertEqual(xt.error_code_for(500, "review export failed: disk full"), "EXPORT_FAILED")


if __name__ == "__main__":
    unittest.main()
