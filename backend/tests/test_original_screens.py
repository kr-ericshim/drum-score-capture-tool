"""Original screens fallback (docs/reflow/ORIGINAL_SCREENS_DESIGN.md §7)."""

import copy
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
from app.pipeline import original_screens
from app.pipeline.export import export_composed_pages, pdf_page_count
from app.pipeline.process_control import report_progress
from app.schemas import JobReviewExportRequest
from drum_score_fixture import Degrade, Overlay, PageSpec, add_note, degrade, groove_notes, render, strip_spec


def _video(image):
    return degrade(image, Degrade(scale=0.75, blur=0.8, jpeg_quality=70, noise=2.0))


def _write(folder: Path, images):
    captured = []
    for k, img in enumerate(images):
        p = folder / f"crop_{k + 1:06d}.png"
        cv2.imwrite(str(p), img)
        captured.append({"path": p, "t": k * original_screens.INTERVAL_SEC})
    return captured


class SelectScreensTest(unittest.TestCase):
    """Tests 1 and 2: the existing comparator as the fallback uses it."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        self.page_a = groove_notes(PageSpec(), seed=3)
        self.page_b = groove_notes(PageSpec(), seed=11)

    def test_return_to_an_earlier_screen_that_stays_is_kept_in_order(self):
        a1 = _video(render(self.page_a, [Overlay("line", 0.2, system=1)]))
        a2 = _video(render(self.page_a, [Overlay("line", 0.55, system=1)]))  # playhead moved
        b1 = _video(render(self.page_b, [Overlay("line", 0.2, system=0)]))
        b2 = _video(render(self.page_b, [Overlay("line", 0.4, system=0)]))
        a3 = _video(render(self.page_a, [Overlay("line", 0.3, system=2)]))
        a4 = _video(render(self.page_a, [Overlay("line", 0.5, system=2)]))
        kept = original_screens.select_screens(_write(self.dir, [a1, a2, b1, b2, a3, a4]), logger=lambda _m: None)
        times = [c["t"] for c in kept]
        self.assertEqual(len(kept), 3)
        self.assertEqual(times, sorted(times))
        self.assertLess(times[0], 1.0)            # A
        self.assertTrue(1.0 <= times[1] < 2.0)    # B
        self.assertGreaterEqual(times[2], 2.0)    # A again

    def test_one_changed_note_is_a_new_screen(self):
        a = render(self.page_a)
        a_changed = render(add_note(self.page_a, 2, 1, 5, 1.5))
        kept = original_screens.select_screens(_write(self.dir, [_video(a), _video(a), _video(a_changed), _video(a_changed)]),
                                               logger=lambda _m: None)
        self.assertEqual(len(kept), 2)
        self.assertLess(kept[0]["t"], 1.0)
        self.assertGreaterEqual(kept[1]["t"], 1.0)


class ScreenRecordsTest(unittest.TestCase):
    """Test 3: only single-color screens are dropped; likely non-score screens become candidates."""

    def test_uniform_screens_drop_staff_only_stays_video_screen_is_a_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            h, w = 190, 1400
            black = np.zeros((h, w, 3), np.uint8)
            white = np.full((h, w, 3), 245, np.uint8)
            staff_only = render(strip_spec())  # five lines, no notes
            score = _video(render(groove_notes(strip_spec(), seed=5)))
            rng = np.random.default_rng(0)
            video = cv2.resize(rng.integers(0, 255, (h // 10, w // 10, 3), dtype=np.uint8), (w, h),
                               interpolation=cv2.INTER_NEAREST)
            self.assertTrue(original_screens.is_uniform(black))
            self.assertTrue(original_screens.is_uniform(white))
            self.assertFalse(original_screens.is_uniform(staff_only))
            captured = _write(Path(td), [black, score, staff_only, video, white])
            records, dropped = original_screens.screen_records(captured, logger=lambda _m: None)
        self.assertEqual(dropped, 2)
        self.assertEqual([r["t"] for r in records], [0.5, 1.0, 1.5])
        self.assertFalse(records[0]["candidate"])
        self.assertTrue(records[2]["candidate"])
        self.assertTrue(records[2]["reasons"])


def _write_video(path: Path, images, seconds_each=1.5, fps=10):
    h, w = images[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for image in images:
        for _ in range(int(seconds_each * fps)):
            writer.write(image)
    writer.release()


class OriginalScreensFlowTest(unittest.TestCase):
    """Test 4: build, rebuild from a selection, cancel, missing source, refused job, square ROI."""

    @classmethod
    def setUpClass(cls):
        cls.strips = [render(groove_notes(strip_spec(), seed=s)) for s in (3, 11)]

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.video = self.root / "source.mp4"
        _write_video(self.video, [np.zeros_like(self.strips[0])] + self.strips)
        self.store = JobStore(self.root / "jobs")
        self.tasks = xt.ExportTaskStore()
        for p in (patch.object(main, "job_store", self.store), patch.object(main, "export_task_store", self.tasks)):
            p.start()
            self.addCleanup(p.stop)
        self.wide_roi = [[0, 0], [1400, 0], [1400, 190], [0, 190]]  # aspect 7.4

    def tearDown(self):
        deadline = time.monotonic() + 30
        while self.tasks.active_count() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.td.cleanup()

    def _job(self, job_id, *, roi=None, refused=False):
        artifact = self.root / job_id
        artifact.mkdir(parents=True)
        options = {"detect": {"roi": roi or self.wide_roi}, "extract": {}, "export": {"formats": ["png", "pdf"]}}
        if refused:
            result = {"output_model": "clean_reflow_v1", "reflow_state": "unsupported_layout", "source_video_path": str(self.video),
                      "reflow": {"issues": [{"kind": "UNSUPPORTED_LAYOUT", "layout": "vertical_scroll", "interval": [0, 3]}]},
                      "images": [], "pdf": None}
            job = Job(id=job_id, source_type="file", file_path=str(self.video), youtube_url=None, options=options,
                      artifact_dir=str(artifact), status=JobStatus.ERROR, error_code="UNSUPPORTED_LAYOUT", result=result)
        else:
            page = np.full((3508, 2480, 3), 255, np.uint8)
            out = export_composed_pages(pages=[page], formats=["png", "pdf"], workspace=artifact / "export", logger=lambda _m: None)
            result = {"output_model": "clean_reflow_v1", "reflow_state": "done", "source_video_path": str(self.video),
                      "reflow": {"systems": [], "revision": 3, "header": {"title": "Test Song", "incomplete": {"unresolved": [[1, 2]]}}},
                      "images": out["images"], "pdf": out["pdf"]}
            job = Job(id=job_id, source_type="file", file_path=str(self.video), youtube_url=None, options=options,
                      artifact_dir=str(artifact), status=JobStatus.DONE, result=result)
        self.store.create(job)
        return artifact

    def _run(self, job_id, request):
        task = main.start_review_export(job_id, request)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            done = main.get_review_export(job_id, task.task_id)
            if done.state not in xt.ACTIVE_STATES:
                return task, done
            time.sleep(0.05)
        self.fail("export task did not finish")

    def test_build_then_rebuild_from_a_selection(self):
        artifact = self._job("job-done")
        clean_before = sorted(p.name for p in (artifact / "export").rglob("*"))
        task, done = self._run("job-done", JobReviewExportRequest(output_model="original_screens_v1"))
        self.assertEqual(task.revision, 4)
        self.assertEqual(done.state, "done", done.error)
        job = self.store.get("job-done")
        self.assertEqual((job.status, job.error_code), (JobStatus.DONE, None))
        self.assertEqual(job.result["output_model"], "original_screens_v1")
        self.assertEqual(job.result["reflow"]["revision"], 4)
        record = job.result["original_screens"]
        self.assertEqual(record["blank_dropped"], 1)  # the black opening
        screens = sorted((artifact / "original_screens" / "screens").glob("screen_*.png"))
        self.assertEqual(len(screens), 2)
        self.assertEqual([s["path"] for s in record["screens"]], [str(s) for s in screens])
        self.assertEqual(record["selected"], [str(s) for s in screens])
        pdf = Path(job.result["pdf"])
        self.assertEqual(pdf.parent, artifact / "original_screens")
        self.assertEqual(pdf_page_count(pdf), 1)
        self.assertEqual(sorted(p.name for p in (artifact / "export").rglob("*")), clean_before)
        self.assertFalse(list(artifact.glob("original_screens_work_*")) + list(artifact.glob("original_screens_staged_*")))

        with patch.object(original_screens, "capture_frames", side_effect=AssertionError("captured again")):
            _task, again = self._run("job-done", JobReviewExportRequest(output_model="original_screens_v1",
                                                                          keep_captures=[str(screens[1])]))
        self.assertEqual(again.state, "done", again.error)
        job = self.store.get("job-done")
        self.assertEqual(job.result["reflow"]["revision"], 5)
        self.assertEqual(job.result["original_screens"]["selected"], [str(screens[1])])
        self.assertEqual(len(job.result["original_screens"]["screens"]), 2)
        self.assertTrue(screens[0].is_file() and screens[1].is_file())

        with self.assertRaises(HTTPException) as ctx:
            main.start_review_export("job-done", JobReviewExportRequest(output_model="original_screens_v1",
                                                                         keep_captures=[str(self.root / "other.png")]))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_cancel_or_missing_source_keeps_the_previous_result(self):
        artifact = self._job("job-c")
        before = copy.deepcopy(self.store.get("job-c").result)
        started, release = threading.Event(), threading.Event()
        real = original_screens.select_screens

        def blocking(*args, **kwargs):
            report_progress("comparing", 0.0)
            started.set()
            release.wait(10)
            report_progress("comparing", 0.5)  # the cancel requested meanwhile stops here
            return real(*args, **kwargs)

        with patch.object(original_screens, "select_screens", side_effect=blocking):
            task = main.start_review_export("job-c", JobReviewExportRequest(output_model="original_screens_v1"))
            self.assertTrue(started.wait(60))
            main.cancel_review_export("job-c", task.task_id)
            release.set()
            deadline = time.monotonic() + 60
            while main.get_review_export("job-c", task.task_id).state in xt.ACTIVE_STATES and time.monotonic() < deadline:
                time.sleep(0.05)
        self.assertEqual(main.get_review_export("job-c", task.task_id).state, "cancelled")
        self.assertEqual(self.store.get("job-c").result, before)
        self.assertFalse(list(artifact.glob("original_screens*")))

        self.video.unlink()
        with self.assertRaises(HTTPException) as ctx:
            main.start_review_export("job-c", JobReviewExportRequest(output_model="original_screens_v1"))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("SOURCE_VIDEO_MISSING", ctx.exception.detail)
        self.assertEqual(self.store.get("job-c").result, before)

    def test_a_screen_that_cannot_be_saved_fails_the_build_and_keeps_the_previous_result(self):
        artifact = self._job("job-w")
        before = copy.deepcopy(self.store.get("job-w").result)
        real = cv2.imwrite
        calls = []

        def failing_second_write(path, image, *args):
            calls.append(path)
            return False if len(calls) == 2 else real(path, image, *args)

        with patch.object(original_screens.cv2, "imwrite", side_effect=failing_second_write):
            _task, done = self._run("job-w", JobReviewExportRequest(output_model="original_screens_v1"))
        self.assertEqual(done.state, "failed")
        self.assertIn("could not be saved", done.error)
        self.assertEqual(self.store.get("job-w").result, before)
        self.assertFalse(list(artifact.glob("original_screens*")))

    def test_a_failed_result_record_keeps_a_pending_layout_conflict_pending(self):
        artifact = self._job("job-p")
        job = self.store.get("job-p")
        result = copy.deepcopy(job.result)
        result.update(reflow_state="layout_conflict", images=[], pdf=None)
        self.store.set_state("job-p", JobStatus.ERROR, 1.0, "layout_conflict", "conflict", result=result,
                             error_code="LAYOUT_CONFLICT")
        self.assertTrue(main._layout_conflict_pending(self.store.get("job-p")))
        real = self.store.set_state

        def fail_done(job_id, status, *args, **kwargs):
            real(job_id, status, *args, **kwargs)
            if status == JobStatus.DONE:
                raise OSError("disk full")

        with patch.object(self.store, "set_state", side_effect=fail_done):
            _task, done = self._run("job-p", JobReviewExportRequest(output_model="original_screens_v1"))
        self.assertEqual(done.state, "failed")
        job = self.store.get("job-p")
        self.assertEqual((job.status, job.error_code), (JobStatus.ERROR, "LAYOUT_CONFLICT"))
        self.assertTrue(main._layout_conflict_pending(job))
        self.assertEqual(job.result, result)
        self.assertFalse((artifact / "original_screens").exists())

    def test_refused_job_and_square_roi_are_refused(self):
        self._job("job-refused", refused=True)
        self._job("job-square", roi=[[0, 0], [400, 0], [400, 190], [0, 190]])  # aspect 2.1
        for job_id, needle in (("job-refused", "finished clean chart"), ("job-square", "ORIGINAL_SCREENS_NOT_ONE_LINE")):
            with self.subTest(job_id=job_id), self.assertRaises(HTTPException) as ctx:
                main.start_review_export(job_id, JobReviewExportRequest(output_model="original_screens_v1"))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn(needle, ctx.exception.detail)

    def test_clean_only_fields_are_refused(self):
        for extra in ({"measure_reflow": True}, {"system_order": ["a"]}, {"keep_images": ["a"]}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                JobReviewExportRequest(output_model="original_screens_v1", **extra)


class LayoutTest(unittest.TestCase):
    def test_screens_fill_the_body_width_and_the_header_holds_only_document_fields(self):
        pages = original_screens.plan_pages([(1400, 190)] * 30, header_h=120)
        first = pages[0][0]
        self.assertEqual(first["w"], original_screens.BODY_W)
        self.assertGreater(first["y"], original_screens.rl.MARGIN_TOP + 120)
        self.assertEqual(pages[1][0]["y"], original_screens.rl.MARGIN_TOP)
        self.assertEqual(sum(len(p) for p in pages), 30)
        self.assertEqual(original_screens.document_header({"title": "T", "bpm": 120, "incomplete": {"x": 1}, "memo": ""}),
                         {"title": "T", "bpm": 120})


if __name__ == "__main__":
    unittest.main()
