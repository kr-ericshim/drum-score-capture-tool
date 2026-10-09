"""Sizing mode (docs/reflow/DECISIONS.md "Automatic staff size for dense charts", "Step 2A"): a size
the user chose is used as it is, also by the initial job and by later rebuilds; automatic sizing is
kept for a job created with the product default (the desktop app sends no size at job creation)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_pipeline as rp
from app.schemas import ExportOptions, JobCreate, JobOptions, JobReviewExportRequest

from test_reflow_measure import measure_strip


ROI = {"roi": [[0.0, 0.0], [100.0, 0.0], [100.0, 50.0], [0.0, 50.0]]}


def opts(**kw):
    return JobOptions(detect=ROI, **kw)


class JobOptionsModeTest(unittest.TestCase):
    def test_desktop_payload_without_a_size_is_automatic(self):
        self.assertFalse(opts().staff_gap_mm_explicit)
        self.assertFalse(JobOptions.model_validate({"detect": ROI, "measure_reflow": True}).staff_gap_mm_explicit)

    def test_the_product_default_is_automatic_and_another_size_is_explicit(self):
        self.assertFalse(opts(staff_gap_mm=1.5).staff_gap_mm_explicit)
        self.assertTrue(opts(staff_gap_mm=1.4).staff_gap_mm_explicit)
        self.assertTrue(opts(staff_gap_mm=1.8).staff_gap_mm_explicit)

    def test_an_explicit_flag_wins(self):
        self.assertTrue(opts(staff_gap_mm=1.5, staff_gap_mm_explicit=True).staff_gap_mm_explicit)
        self.assertFalse(opts(staff_gap_mm=1.4, staff_gap_mm_explicit=False).staff_gap_mm_explicit)

    def test_the_mode_survives_the_stored_job_options(self):
        for o in (opts(), opts(staff_gap_mm=1.4)):
            again = JobOptions.model_validate(o.model_dump())
            self.assertEqual(again.staff_gap_mm_explicit, o.staff_gap_mm_explicit)


def make_systems(folder: Path, n=2):
    folder.mkdir(parents=True, exist_ok=True)
    systems = []
    for i in range(n):
        img, rec = measure_strip()
        path = folder / f"strip_sys-00{i + 1}.png"
        cv2.imwrite(str(path), img)
        systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(path), "issues": [],
                        "t_start": float(i), "t_end": i + 0.9, "layout": "bottom_bar", "strip": dict(rec, system_id=f"sys-00{i + 1}")})
    return systems


class InitialJobModeTest(unittest.TestCase):
    """The initial job passes the sizing mode to composition and records it for rebuilds."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.video = self.root / "v.mp4"
        self.video.write_bytes(b"x")

    def tearDown(self):
        self.td.cleanup()

    def run_job(self, options):
        art = self.root / "job-m"
        systems = make_systems(art / "reflow" / "strips")
        record = {"systems": systems, "workspace": str(art / "reflow")}
        store = self.store = JobStore(self.root / "store")
        payload = JobCreate(source_type="file", file_path=str(self.video), options=options)
        job = Job(id="job-m", source_type="file", file_path=str(self.video), youtube_url=None,
                  options=payload.options.model_dump(), artifact_dir=str(art), status=JobStatus.RUNNING)
        store.create(job)
        calls = []
        real = rp.compose_systems

        def spy(*args, **kw):
            calls.append(kw)
            return real(*args, **kw)
        result = {}
        with patch.object(main, "job_store", store), patch.object(rp, "analyse_source", return_value=record), \
                patch.object(rp, "compose_systems", side_effect=spy), patch.object(main, "_finish_reflow_suggestions"):
            main._execute_reflow_job(job_id="job-m", job=store.get("job-m"), payload=payload, result=result,
                                     video_path=str(self.video), export_opts=ExportOptions(formats=["png"]))
        return calls[-1], store.get("job-m")

    def test_default_job_allows_the_automatic_search(self):
        kw, job = self.run_job(opts())
        self.assertTrue(kw["auto_staff_size"])
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertFalse(job.result["reflow"]["staff_gap_mm_explicit"])

    def test_explicit_job_size_is_used_as_it_is(self):
        kw, job = self.run_job(opts(staff_gap_mm=1.4))
        self.assertEqual((kw["staff_gap_mm"], kw["auto_staff_size"]), (1.4, False))
        self.assertTrue(job.result["reflow"]["staff_gap_mm_explicit"])
        self.assertEqual(job.result["measure_reflow"]["staff_size"]["staff_gap_mm"], 1.4)
        self.assertFalse(job.result["measure_reflow"]["staff_size"]["auto_reduced"])

    def test_explicit_size_that_does_not_fit_is_a_layout_conflict(self):
        # whole systems far too wide at 2.5 mm: a user-chosen size is never reduced
        kw, job = self.run_job(opts(staff_gap_mm=2.5, measure_reflow=False))
        self.assertFalse(kw["auto_staff_size"])
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, main.LAYOUT_CONFLICT_CODE)

    def test_rebuild_of_an_explicit_job_keeps_the_size_explicit(self):
        _kw, job = self.run_job(opts(staff_gap_mm=1.4))
        store = self.store
        calls = []
        real = rp.compose_systems

        def spy(*args, **kw):
            calls.append(kw)
            return real(*args, **kw)
        paths = [s["strip_path"] for s in job.result["reflow"]["systems"]]
        with patch.object(main, "job_store", store), patch.object(rp, "compose_systems", side_effect=spy):
            main.review_export("job-m", JobReviewExportRequest(keep_captures=paths, formats=["png"]))
            self.assertEqual((calls[-1]["staff_gap_mm"], calls[-1]["auto_staff_size"]), (1.4, False))
            # choosing the job's own (explicit) size again stays explicit
            main.review_export("job-m", JobReviewExportRequest(keep_captures=paths, formats=["png"], staff_gap_mm=1.4))
            self.assertEqual((calls[-1]["staff_gap_mm"], calls[-1]["auto_staff_size"]), (1.4, False))
        self.assertTrue(store.get("job-m").result["reflow"]["staff_gap_mm_explicit"])


if __name__ == "__main__":
    unittest.main()
