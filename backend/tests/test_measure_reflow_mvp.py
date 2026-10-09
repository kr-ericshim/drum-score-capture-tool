"""Measure reflow MVP wiring (docs/reflow/DECISIONS.md "Measure reflow MVP"): on by default for
new jobs, off for job records saved before the option existed, switchable per review export,
the producing mode recorded in the result, planner failures reported as whole-system fallbacks."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_measure as rmeas
from app.pipeline import reflow_pipeline as rp
from app.pipeline.export import export_composed_pages
from app.schemas import JobCreate, JobOptions, JobReviewExportRequest

from test_reflow_measure import measure_strip
from test_reflow_review_export import strip_image

ROI = [[0, 0], [100, 0], [100, 50], [0, 50]]


class DefaultOptionTest(unittest.TestCase):
    def test_new_jobs_default_to_measure_reflow_and_store_it(self):
        self.assertTrue(JobOptions.model_fields["measure_reflow"].default)
        payload = JobCreate(source_type="file", file_path="/v.mp4", options={"detect": {"roi": ROI}})
        self.assertTrue(payload.options.measure_reflow)
        # the stored job record carries the option explicitly
        self.assertIs(payload.options.model_dump()["measure_reflow"], True)
        off = JobCreate(source_type="file", file_path="/v.mp4", options={"detect": {"roi": ROI}, "measure_reflow": False})
        self.assertIs(off.options.model_dump()["measure_reflow"], False)

    def test_a_job_saved_without_the_field_reads_as_off(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            art = root / "old-job"
            art.mkdir()
            record = Job(id="old-job", source_type="file", file_path=str(root / "v.mp4"), youtube_url=None,
                         options={"detect": {"roi": ROI}, "export": {"formats": ["png"]}, "staff_gap_mm": 1.5},
                         artifact_dir=str(art), status=JobStatus.DONE).to_record()
            self.assertNotIn("measure_reflow", record["options"])
            (art / "job.json").write_text(json.dumps(record))
            job = JobStore(root).get("old-job")  # loaded the way the app loads it after a restart
            self.assertFalse(main._job_measure_reflow(job))
            job.options = dict(job.options, measure_reflow=True)
            self.assertTrue(main._job_measure_reflow(job))

    def test_review_export_request_field(self):
        paths = ["/a.png"]
        self.assertIsNone(JobReviewExportRequest(keep_captures=paths).measure_reflow)
        self.assertFalse(JobReviewExportRequest(keep_captures=paths, measure_reflow=False).measure_reflow)
        self.assertTrue(JobReviewExportRequest(keep_captures=paths, measure_reflow=True).measure_reflow)


class ReviewExportModeTest(unittest.TestCase):
    """Per-export override, the recorded mode, and the fallback record."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def job(self, options):
        art = self.root / "job-m"
        strips = art / "reflow" / "strips"
        strips.mkdir(parents=True)
        systems = []
        for i in range(3):
            img, rec = measure_strip()
            path = strips / f"strip_sys-00{i + 1}.png"
            cv2.imwrite(str(path), img)
            systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(path), "issues": [],
                            "t_start": float(i), "t_end": i + 0.9, "layout": "bottom_bar", "strip": dict(rec, system_id=f"sys-00{i + 1}")})
        plan, pages = rp.compose_systems(systems, header={"title": "T"})
        out = export_composed_pages(pages=pages, formats=["png"], workspace=art / "export", logger=lambda _m: None)
        reflow = {"systems": systems, "page_plan": plan, "header": {"title": "T"}, "revision": 1, "duplicate_suggestions": [],
                  "workspace": str(art / "reflow")}
        result = {"output_model": "clean_reflow_v1", "reflow_state": "done", "reflow": reflow, "images": out["images"], "pdf": None,
                  **main._reflow_capture_fields(reflow)}
        store = JobStore(self.root)
        store.create(Job(id="job-m", source_type="file", file_path=str(self.root / "v.mp4"), youtube_url=None,
                         options=dict(options, export={"formats": ["png"]}), artifact_dir=str(art), status=JobStatus.DONE, result=result))
        return store, [s["strip_path"] for s in systems]

    def export(self, store, paths, **kwargs):
        with patch.object(main, "job_store", store):
            response = main.review_export("job-m", JobReviewExportRequest(keep_captures=paths, formats=["png"], **kwargs))
        return response, store.get("job-m").result

    def test_old_job_without_the_field_keeps_whole_systems(self):
        store, paths = self.job({})
        response, result = self.export(store, paths)
        self.assertNotIn("measure_reflow", result["reflow"]["page_plan"])
        self.assertEqual(result["measure_reflow"], {"requested": False, "applied": False, "status": "off", "reason": None})
        self.assertEqual(response.measure_reflow["status"], "off")
        self.assertEqual(result["review_export"]["measure_reflow"]["status"], "off")

    def test_job_option_is_used_when_the_export_does_not_choose(self):
        store, paths = self.job({"measure_reflow": True})
        response, result = self.export(store, paths)
        self.assertEqual(result["reflow"]["page_plan"]["measure_reflow"]["status"], "measure_lines")
        self.assertEqual(result["measure_reflow"], {"requested": True, "applied": True, "status": "measure_lines", "reason": None,
                                                    "staff_size": {"staff_gap_mm": 1.5, "staff_gap_mm_requested": 1.5,
                                                                   "auto_reduced": False, "reason": "LINES_FULL"}})
        self.assertEqual(response.measure_reflow, result["measure_reflow"])

    def test_export_can_turn_it_off_and_on_again(self):
        store, paths = self.job({"measure_reflow": True})
        _, off = self.export(store, paths, measure_reflow=False)
        self.assertNotIn("measure_reflow", off["reflow"]["page_plan"])
        self.assertEqual(off["measure_reflow"]["status"], "off")
        self.assertEqual(off["review_export"]["measure_reflow"]["status"], "off")
        placed = [pl["system_id"] for p in off["reflow"]["page_plan"]["pages"] for pl in p["placements"]]
        self.assertEqual(placed, ["sys-001", "sys-002", "sys-003"])
        _, on = self.export(store, paths, measure_reflow=True)
        self.assertEqual(on["measure_reflow"]["status"], "measure_lines")
        self.assertEqual(on["review_export"]["revision"], off["review_export"]["revision"] + 1)
        # the job's own option is not changed by an export choice
        self.assertTrue(store.get("job-m").options["measure_reflow"])

    def test_old_job_can_opt_in_per_export(self):
        store, paths = self.job({})
        _, result = self.export(store, paths, measure_reflow=True)
        self.assertEqual(result["measure_reflow"]["status"], "measure_lines")
        self.assertNotIn("measure_reflow", store.get("job-m").options)

    def test_planner_failure_falls_back_and_is_reported(self):
        store, paths = self.job({"measure_reflow": True})
        with patch.object(rmeas, "compose", side_effect=rmeas.MeasurePlanUnavailable("NO_STAFF_GAP", {"system_id": "sys-001"})):
            response, result = self.export(store, paths)
        self.assertEqual(result["reflow"]["page_plan"]["measure_reflow"]["status"], "fallback_whole_systems")
        self.assertEqual(result["measure_reflow"], {"requested": True, "applied": False, "status": "fallback_whole_systems",
                                                    "reason": "NO_STAFF_GAP"})
        self.assertEqual(response.measure_reflow["reason"], "NO_STAFF_GAP")
        self.assertTrue(result["images"])  # whole systems were still exported
        self.assertTrue(any("measure reflow fell back to whole systems: NO_STAFF_GAP" in line for line in store.get("job-m").log))

    def test_unexpected_planner_error_has_a_short_reason_code(self):
        store, paths = self.job({"measure_reflow": True})
        with patch.object(rmeas, "compose", side_effect=ValueError("boom")):
            _, result = self.export(store, paths)
        self.assertEqual(result["measure_reflow"]["status"], "fallback_whole_systems")
        self.assertEqual(result["measure_reflow"]["reason"], "MEASURE_PLAN_ERROR")


class JobComposeModeTest(unittest.TestCase):
    """The job's own compose records which layout produced its files."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.video = self.root / "v.mp4"
        self.video.write_bytes(b"0")
        self.store = JobStore(self.root)
        self.ws = self.root / "job-f" / "reflow"
        (self.ws / "strips").mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def record(self):
        systems = []
        for i in range(2):
            p = self.ws / "strips" / f"strip_sys-00{i + 1}.png"
            cv2.imwrite(str(p), strip_image(f"S{i + 1}", width=1700))
            systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(p), "t_start": i * 5.0,
                            "t_end": i * 5.0 + 4.0, "slot_id": "slot-00", "layout": "bottom_bar", "episode_ids": [f"e{i}"],
                            "first_display": i == 0, "terminal_display": i == 1, "issues": [],
                            "strip": {"staff_gap_px": 16.0, "size": [1700, 220]}})
        return {"version": "t", "output_model": "clean_reflow_v1", "workspace": str(self.ws), "systems": systems,
                "fragments": [], "exclusions": {}, "continuity_suggestions": [], "duplicate_suggestions": [],
                "_manifest": None, "_load": None}

    def run_job(self, **options):
        payload = JobCreate(source_type="file", file_path=str(self.video),
                            options={"detect": {"roi": ROI}, "export": {"formats": ["png"]}, **options})
        self.store.create(Job(id="job-f", source_type="file", file_path=str(self.video), youtube_url=None,
                              options=payload.options.model_dump(), artifact_dir=str(self.root / "job-f"), status=JobStatus.QUEUED))
        with patch("app.main.job_store", self.store), \
                patch("app.main._analyze_roi_health", return_value={"diagnostics": []}), \
                patch("app.pipeline.reflow_pipeline.analyse_source", return_value=self.record()), \
                patch("app.pipeline.reflow_pipeline.duplicate_suggestions", return_value=[]):
            main._run_job("job-f", payload)
        return self.store.get("job-f")

    def test_default_job_is_rearranged_by_measure(self):
        job = self.run_job()
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertTrue(job.options["measure_reflow"])
        self.assertEqual(job.result["measure_reflow"]["status"], "measure_lines")
        self.assertTrue(job.result["measure_reflow"]["applied"])

    def test_job_with_the_option_off_keeps_whole_systems(self):
        job = self.run_job(measure_reflow=False)
        self.assertEqual(job.result["measure_reflow"]["status"], "off")
        self.assertNotIn("measure_reflow", job.result["reflow"]["page_plan"])

    def test_job_planner_failure_is_recorded(self):
        with patch.object(rmeas, "compose", side_effect=rmeas.MeasurePlanUnavailable("STRIP_UNREADABLE")):
            job = self.run_job()
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertEqual(job.result["measure_reflow"]["status"], "fallback_whole_systems")
        self.assertEqual(job.result["measure_reflow"]["reason"], "STRIP_UNREADABLE")
        self.assertTrue(job.result["images"])


class RuntimeSourcesTest(unittest.TestCase):
    """The classifier and line planner the app runs come from the code, never corpus files."""

    def test_measure_modules_read_no_corpus_files(self):
        root = Path(main.__file__).resolve().parent / "pipeline"
        for name in ("reflow_boundaries", "reflow_units", "reflow_lines", "reflow_measure", "reflow_accounting", "reflow_pipeline"):
            text = (root / f"{name}.py").read_text(encoding="utf-8")
            for needle in ("drum-score-corpus", "freeze_v1", "predictions", "labels_claude", "expanduser", "Path.home"):
                self.assertNotIn(needle, text, f"{name}.py mentions {needle}")
        # the only files the measure path reads are the job workspace's own manifest and occurrences
        reads = re.findall(r'"([a-z_]+\.json)"', (root / "reflow_measure.py").read_text(encoding="utf-8"))
        self.assertLessEqual(set(reads), {"manifest.json", "occurrences.json"})


if __name__ == "__main__":
    unittest.main()
