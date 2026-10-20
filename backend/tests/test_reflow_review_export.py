"""Clean reflow job path and review export (output_model clean_reflow_v1)."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_pipeline
from app.pipeline.export import export_composed_pages
from app.pipeline.process_control import OperationCancelled
from app.pipeline.reflow_verify_page import decode_lossless_pdf
from app.schemas import JobCreate, JobReviewExportRequest


def strip_image(label, width=1700, gap=16, top=60, height=220):
    img = np.full((height, width, 3), 250, np.uint8)
    for k in range(5):
        y = top + k * gap
        cv2.line(img, (10, y), (width - 10, y), (0, 0, 0), 2)
    cv2.putText(img, label, (40, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    return img


def digest(folder: Path):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


class ReflowReviewExportTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.artifact = self.root / "job-r"
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
        self.store.create(Job(id="job-r", source_type="file", file_path=str(self.root / "v.mp4"), youtube_url=None,
                              options={"export": {"formats": ["png", "pdf"]}}, artifact_dir=str(self.artifact),
                              status=JobStatus.DONE, result=result))

    def tearDown(self):
        self.td.cleanup()

    def test_order_and_selection_are_composed_and_stored(self):
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store):
            resp = main.review_export("job-r", JobReviewExportRequest(keep_captures=[paths[2], paths[0]],
                                                                       system_order=[paths[2], paths[1], paths[0]], formats=["png", "jpg", "pdf"]))
        self.assertEqual(resp.kept_count, 2)
        job = self.store.get("job-r")
        reflow = job.result["reflow"]
        self.assertEqual([s["id"] for s in reflow["systems"]], ["sys-003", "sys-002", "sys-001"])
        self.assertEqual([s["included"] for s in reflow["systems"]], [True, False, True])
        placed = [pl["system_id"] for p in reflow["page_plan"]["pages"] for pl in p["placements"]]
        self.assertEqual(placed, ["sys-003", "sys-001"])
        self.assertEqual(job.result["review_candidates"], [paths[2], paths[1], paths[0]])
        self.assertEqual(job.result["review_export"]["selected_captures"], [paths[2], paths[0]])
        self.assertEqual(reflow["revision"], 2)
        self.assertTrue(Path(job.result["pdf"]).is_file())
        self.assertEqual(len([p for p in job.result["images"] if p.endswith(".jpg")]), 1)

    def test_export_leaves_the_previous_record_unchanged(self):
        # the candidate shares the strip records with the job's record; nothing writes into them
        previous = self.store.get("job-r").result
        content_before = copy.deepcopy(previous)
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store):
            main.review_export("job-r", JobReviewExportRequest(keep_captures=[paths[1]], system_order=[paths[1], paths[0], paths[2]],
                                                               document_header={"title": "Other"}))
        self.assertEqual(previous, content_before)
        self.assertEqual(self.store.get("job-r").result["reflow"]["revision"], 2)

    def test_failed_export_keeps_previous_files_and_result(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        result_before = self.store.get("job-r").result
        options_before = copy.deepcopy(self.store.get("job-r").options)
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store), \
                patch("app.pipeline.export.export_composed_pages", side_effect=RuntimeError("disk full")):
            with self.assertRaises(HTTPException) as ctx:
                main.review_export("job-r", JobReviewExportRequest(keep_captures=[paths[0]],
                                                                   document_header={"title": "New title"}))
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(digest(export_dir), before)
        self.assertEqual(self.store.get("job-r").result, result_before)
        self.assertEqual(self.store.get("job-r").options, options_before)
        self.assertEqual(JobStore(self.root).get("job-r").options, options_before)
        self.assertEqual([p.name for p in self.artifact.iterdir() if p.name.startswith("export_staged_")], [])
        self.assertEqual([p.name for p in self.artifact.iterdir() if "_backup_" in p.name], [])

    def test_document_header_updates_pdf_result_and_survives_restart_and_rebuild(self):
        header = {"title": "수정한 제목 / Corrected title", "performer": "Drummer", "bpm": 120,
                  "date": "2026-10-16", "memo": "Review"}
        path = self.systems[0]["strip_path"]
        _, expected_pages = reflow_pipeline.compose_systems(self.systems[:1], header=header, all_systems=self.systems)
        expected_header = cv2.cvtColor(expected_pages[0], cv2.COLOR_BGR2GRAY)[:300]
        with patch("app.main.job_store", self.store):
            response = main.review_export("job-r", JobReviewExportRequest(keep_captures=[path], document_header=header))
        job = self.store.get("job-r")
        self.assertEqual(job.result["reflow"]["header"], header)
        self.assertEqual(job.result["reflow"]["page_plan"]["header"]["title"], header["title"])
        self.assertEqual(job.options["export"], {"formats": ["png", "pdf"], "document_header": header})
        np.testing.assert_array_equal(decode_lossless_pdf(response.pdf, profile="lossless")[0][:300], expected_header)
        self.assertEqual(Path(response.pdf).name, "sheet_export.pdf")

        restarted = JobStore(self.root)
        self.assertEqual(restarted.get("job-r").options["export"]["document_header"], header)
        with patch("app.main.job_store", restarted):
            response = main.review_export("job-r", JobReviewExportRequest(keep_captures=[path]))
        self.assertEqual(restarted.get("job-r").result["reflow"]["header"], header)
        np.testing.assert_array_equal(decode_lossless_pdf(response.pdf, profile="lossless")[0][:300], expected_header)

    def test_cancelled_header_rebuild_keeps_options_and_files(self):
        before = copy.deepcopy(self.store.get("job-r").options)
        files_before = digest(self.artifact / "export")
        with patch("app.main.job_store", self.store), patch("app.main.checkpoint", side_effect=OperationCancelled):
            with self.assertRaises(OperationCancelled):
                main.review_export("job-r", JobReviewExportRequest(keep_captures=[self.systems[0]["strip_path"]],
                                                                   document_header={"title": "Cancelled title"}))
        self.assertEqual(self.store.get("job-r").options, before)
        self.assertEqual(JobStore(self.root).get("job-r").options, before)
        self.assertEqual(digest(self.artifact / "export"), files_before)

    # --- staged commit failures: the previous chart's bytes must stay retrievable ---

    def _fail_replace(self, *, staged=False, backup=False, job_json=False):
        """Patch Path.replace (the rename the commit and the job store use) to fail for
        the named sources; everything else is a real rename. ``job_json`` fails the job
        store's writes only after the new export was installed (post-commit failure)."""
        real = Path.replace
        installed = {"done": False}

        def fake(src, dst):
            src, dst = Path(src), Path(dst)
            if staged and src.name.startswith("export_staged_"):
                raise OSError("simulated: cannot install the new export")
            if backup and "_backup_" in src.name:
                raise OSError("simulated: cannot move the backup back")
            if job_json and installed["done"] and dst.name == "job.json":
                raise OSError("simulated: cannot record the job result")
            out = real(src, dst)
            if src.name.startswith("export_staged_"):
                installed["done"] = True
            return out
        return patch.object(Path, "replace", autospec=True, side_effect=fake)

    def _export(self, paths, **kwargs):
        return main.review_export("job-r", JobReviewExportRequest(keep_captures=[paths[1]], formats=["png", "pdf"], **kwargs))

    def _leftovers(self):
        return sorted(p.name for p in self.artifact.iterdir() if p.name != "export" and p.name.startswith("export"))

    def test_install_failure_with_rollback_keeps_previous_export(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        result_before = self.store.get("job-r").result
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store), self._fail_replace(staged=True):
            with self.assertRaises(HTTPException) as ctx:
                self._export(paths)
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(digest(export_dir), before)
        self.assertEqual(self.store.get("job-r").result, result_before)
        self.assertEqual(self._leftovers(), [])

    def test_install_and_rollback_failure_keeps_the_backup_and_reports_it(self):
        # Before the fix the backup (the only copy of the previous chart) was deleted in `finally`.
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        result_before = self.store.get("job-r").result
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store), self._fail_replace(staged=True, backup=True):
            with self.assertRaises(HTTPException) as ctx:
                self._export(paths)
        self.assertEqual(ctx.exception.status_code, 500)
        backups = [p for p in self.artifact.iterdir() if "_backup_" in p.name]
        self.assertEqual(len(backups), 1)
        self.assertEqual(digest(backups[0]), before)
        self.assertIn(str(backups[0]), ctx.exception.detail)
        self.assertEqual(self.store.get("job-r").result, result_before)

    def test_post_commit_metadata_failure_restores_previous_export(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        result_before = self.store.get("job-r").result
        content_before = copy.deepcopy(result_before)
        options_before = copy.deepcopy(self.store.get("job-r").options)
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store), self._fail_replace(job_json=True):
            with self.assertRaises(HTTPException) as ctx:
                self._export(paths, document_header={"title": "Uncommitted title"})
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(digest(export_dir), before)
        self.assertEqual(self.store.get("job-r").result, result_before)
        # the restored record is the previous one, unchanged in content (it is not copied first)
        self.assertEqual(self.store.get("job-r").result, content_before)
        self.assertEqual(self.store.get("job-r").options, options_before)
        self.assertEqual(JobStore(self.root).get("job-r").options, options_before)
        self.assertEqual(self._leftovers(), [])

    def test_post_commit_failure_and_failed_restore_keep_the_backup(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store), self._fail_replace(job_json=True, backup=True):
            with self.assertRaises(HTTPException) as ctx:
                self._export(paths)
        self.assertEqual(ctx.exception.status_code, 500)
        backups = [p for p in self.artifact.iterdir() if "_backup_" in p.name]
        self.assertEqual(len(backups), 1)
        self.assertEqual(digest(backups[0]), before)
        self.assertIn(str(backups[0]), ctx.exception.detail)

    def test_successful_export_removes_the_backup(self):
        paths = [s["strip_path"] for s in self.systems]
        with patch("app.main.job_store", self.store):
            self._export(paths)
        self.assertEqual(self._leftovers(), [])
        self.assertEqual(len(self.store.get("job-r").result["images"]), 1)

    def test_unknown_system_is_rejected(self):
        with patch("app.main.job_store", self.store):
            with self.assertRaises(HTTPException) as ctx:
                main.review_export("job-r", JobReviewExportRequest(keep_captures=[str(self.root / "other.png")]))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_duplicate_suggestions_become_similar_pairs(self):
        reflow = {"systems": self.systems, "duplicate_suggestions": [{"system_id": "sys-003", "of_system_id": "sys-001", "basis": "x"}]}
        fields = main._reflow_capture_fields(reflow)
        self.assertEqual(fields["similar_capture_pairs"][0]["reason"], "looks_similar")  # appearance only, not "duplicate"
        self.assertEqual(fields["similar_capture_pairs"][0]["candidate"], self.systems[2]["strip_path"])
        self.assertEqual(fields["similar_capture_pairs"][0]["kept"], self.systems[0]["strip_path"])


class DependencyRevalidationTest(unittest.TestCase):
    """Audit round 2, P1: preview destinations and section-label owners are re-validated on
    every review export (exclude, reorder, re-include)."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.artifact = self.root / "job-d"
        strips = self.artifact / "reflow" / "strips"
        (strips / "uncut").mkdir(parents=True)
        labels = self.artifact / "reflow" / "labels"
        labels.mkdir(parents=True)
        self.systems = []
        for i in range(4):
            sid = f"sys-00{i + 1}"
            p = strips / f"strip_{sid}.png"
            cv2.imwrite(str(p), strip_image(f"S{i + 1}", width=1500))
            rec = {"id": sid, "index": i + 1, "included": True, "strip_path": str(p), "issues": [],
                   "t_start": i * 5.0, "t_end": i * 5.0 + 4.0, "strip": {"staff_gap_px": 16.0, "size": [1500, 220]}}
            self.systems.append(rec)
        # sys-001's preview tail was cut: its destination is sys-002
        up = strips / "uncut" / "strip_sys-001.png"
        cv2.imwrite(str(up), strip_image("S1 + TAIL", width=1700))
        self.systems[0]["strip"]["preview_tail"] = {"cut": True, "verified": True, "destination_system_id": "sys-002"}
        self.systems[0]["strip"]["uncut"] = {"path": str(up), "box_crop": [0, 0, 1700, 220], "size": [1700, 220]}
        # "Verse" starts at sys-003 and continues on sys-004 (each keeps its own source patch)
        for sid, extra in (("sys-003", {"placed": True}), ("sys-004", {"placed": False, "repeats_system_id": "sys-003"})):
            lp = labels / f"label_{sid}.png"
            patch_img = np.full((30, 120, 3), 255, np.uint8)
            cv2.putText(patch_img, "Verse", (5, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
            cv2.imwrite(str(lp), patch_img)
            next(x for x in self.systems if x["id"] == sid)["label"] = {"path": str(lp), "x_in_strip": 40, **extra}
        included = list(self.systems)
        plan, pages = reflow_pipeline.compose_systems(included, header={"title": "T"}, all_systems=self.systems)
        out = export_composed_pages(pages=pages, formats=["png"], workspace=self.artifact / "export", logger=lambda _m: None)
        reflow = {"systems": self.systems, "page_plan": plan, "header": {"title": "T"}, "revision": 1, "duplicate_suggestions": [],
                  "dependencies": plan["dependencies"]}
        result = {"output_model": "clean_reflow_v1", "reflow_state": "done", "reflow": reflow, "images": out["images"], "pdf": None,
                  **main._reflow_capture_fields(reflow)}
        self.store = JobStore(self.root)
        self.store.create(Job(id="job-d", source_type="file", file_path=str(self.root / "v.mp4"), youtube_url=None,
                              options={"export": {"formats": ["png"]}}, artifact_dir=str(self.artifact),
                              status=JobStatus.DONE, result=result))
        self.paths = {s["id"]: s["strip_path"] for s in self.systems}

    def tearDown(self):
        self.td.cleanup()

    def export(self, keep, order=None):
        with patch("app.main.job_store", self.store):
            main.review_export("job-d", JobReviewExportRequest(keep_captures=[self.paths[k] for k in keep],
                                                               system_order=[self.paths[k] for k in (order or [])], formats=["png"]))
        job = self.store.get("job-d")
        plan = job.result["reflow"]["page_plan"]
        return job, {pl["system_id"]: pl for p in plan["pages"] for pl in p["placements"]}, plan["dependencies"]

    def test_default_order_keeps_the_cut_and_the_section_start_label(self):
        job, pls, deps = self.export(["sys-001", "sys-002", "sys-003", "sys-004"])
        self.assertEqual(pls["sys-001"]["strip_variant"], "strip")
        self.assertEqual(deps, {"preview_tails_restored": [], "labels_moved": [], "labels_unplaced": []})
        self.assertIn("label_box_px", pls["sys-003"])
        self.assertNotIn("label_box_px", pls["sys-004"])

    def test_excluded_destination_restores_the_tail_and_reinclude_cuts_it_again(self):
        job, pls, deps = self.export(["sys-001", "sys-003", "sys-004"])
        self.assertEqual(pls["sys-001"]["strip_variant"], "uncut")
        self.assertAlmostEqual(pls["sys-001"]["w"] / pls["sys-001"]["scale"], 1700, delta=2)  # the tail is on the page with its strip
        self.assertEqual(deps["preview_tails_restored"][0]["reason"], "destination_not_placed")
        diag = job.result["capture_diagnostics"][self.paths["sys-001"]]
        self.assertIn("PREVIEW_TAIL_RESTORED", diag["diagnostic_codes"])
        job, pls, deps = self.export(["sys-001", "sys-002", "sys-003", "sys-004"])
        self.assertEqual(pls["sys-001"]["strip_variant"], "strip")
        self.assertEqual(deps["preview_tails_restored"], [])

    def test_destination_moved_away_restores_the_tail(self):
        order = ["sys-002", "sys-001", "sys-003", "sys-004"]
        job, pls, deps = self.export(order, order)
        self.assertEqual(pls["sys-001"]["strip_variant"], "uncut")
        self.assertEqual(deps["preview_tails_restored"][0]["reason"], "destination_not_next")
        self.assertEqual(deps["preview_tails_restored"][0]["next_system_id"], "sys-003")

    def test_excluded_section_start_moves_its_label_to_the_next_system_of_the_section(self):
        job, pls, deps = self.export(["sys-001", "sys-002", "sys-004"])
        self.assertIn("label_box_px", pls["sys-004"])
        self.assertEqual(pls["sys-004"]["label_section"], "sys-003")
        self.assertEqual(deps["labels_moved"], [{"section": "sys-003", "placed_on": "sys-004", "reason": "section_start_excluded"}])
        # re-included: back on its own start, once
        job, pls, deps = self.export(["sys-001", "sys-002", "sys-003", "sys-004"])
        self.assertIn("label_box_px", pls["sys-003"])
        self.assertNotIn("label_box_px", pls["sys-004"])
        self.assertEqual(deps["labels_moved"], [])

    def test_reordered_section_puts_the_label_above_its_first_placed_system(self):
        order = ["sys-001", "sys-002", "sys-004", "sys-003"]
        job, pls, deps = self.export(order, order)
        self.assertIn("label_box_px", pls["sys-004"])
        self.assertNotIn("label_box_px", pls["sys-003"])
        self.assertEqual(deps["labels_moved"][0]["reason"], "order_changed")

    def test_section_without_any_placed_system_is_reported(self):
        job, pls, deps = self.export(["sys-001", "sys-002"])
        self.assertEqual(deps["labels_unplaced"], [{"section": "sys-003", "systems": ["sys-003", "sys-004"],
                                                    "reason": "no_placed_system_of_this_section"}])
        for sid in ("sys-003", "sys-004"):
            self.assertIn("SECTION_LABEL_NOT_PLACED", job.result["capture_diagnostics"][self.paths[sid]]["diagnostic_codes"])


class SuggestionBudgetTest(unittest.TestCase):
    """Audit round 2, P2: strip loading ignored a cancel (20/20 strips read when already
    cancelled), and the label check had no deadline: with a simulated clock it ran from a
    1 s budget to 120 s and still published its result."""

    def test_strip_loading_stops_when_already_cancelled(self):
        from app.pipeline import reflow_occurrences as ro
        systems = [{"id": f"sys-{i:03d}", "order_t": i * 5.0, "staff_top_y_crop": 50.0, "staff_gap_px": 14.0} for i in range(20)]
        strip_of = {s["id"]: f"/nonexistent/{s['id']}.png" for s in systems}
        reads = []
        with patch.object(ro.cv2, "imread", side_effect=lambda p, *a: reads.append(p)):
            out = ro.suggest_similar_strips(systems, strip_of, should_stop=lambda: True)
        self.assertEqual(out, [])
        self.assertEqual(reads, [])

    def test_label_check_stops_at_the_deadline_between_frames_and_is_not_published(self):
        from app.pipeline import notation_envelope as ne
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            video = td / "v.avi"
            vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 5, (160, 120))
            for k in range(5 * 30):
                vw.write(np.full((120, 160, 3), (k * 3) % 255, np.uint8))
            vw.release()
            clock = {"t": 1000.0}
            real_cap = cv2.VideoCapture
            reads = {"n": 0}

            class SlowCapture:  # each decoded frame costs 3 simulated seconds
                def __init__(self, *a):
                    self._c = real_cap(*a)

                def read(self):
                    reads["n"] += 1
                    clock["t"] += 3.0
                    return self._c.read()

                def __getattr__(self, name):
                    return getattr(self._c, name)

            class FakeTime:
                def __getattr__(self, name):
                    import time as real_time
                    return getattr(real_time, name)

                def monotonic(self):
                    return clock["t"]

            store = JobStore(td)
            reflow = {"systems": [], "labels": {"status": "not_checked"}, "duplicate_suggestions": [], "suggestions_state": "pending"}
            store.create(Job(id="job-b", source_type="file", file_path=str(video), youtube_url=None, options={},
                             artifact_dir=str(td / "job-b"), status=JobStatus.DONE, result={"reflow": reflow}))
            record = {"workspace": str(td / "job-b" / "reflow"), "labels": {"status": "not_checked"}, "source_path": str(video),
                      "source_range": [0.0, None], "applied_roi": [[0, 60], [160, 60], [160, 120], [0, 120]],
                      "continuity_suggestions": []}
            with patch("app.main.job_store", store), patch.object(main, "time", FakeTime()), \
                    patch.object(ne.cv2, "VideoCapture", SlowCapture), \
                    patch("app.pipeline.reflow_pipeline.duplicate_suggestions", return_value=[]):
                main._finish_reflow_suggestions("job-b", record, time_budget_sec=1.0)
            out = store.get("job-b").result["reflow"]
        self.assertLessEqual(reads["n"], 1)  # stopped before the second frame (80 frames requested)
        self.assertLess(clock["t"] - 1000.0, 10.0)
        self.assertEqual(out["suggestions_state"], "partial")
        self.assertEqual(out["suggestions_incomplete"], ["label_check"])
        self.assertEqual(out["labels"]["status"], "not_checked")  # no finding published after the budget
        self.assertEqual(out["labels"]["check"], "incomplete")


class CleanOnlyOutputTest(unittest.TestCase):
    """The raw-stitch (legacy) output cannot be selected over the public API."""

    def test_schema_rejects_legacy_output_model(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            JobCreate(source_type="file", file_path="v.mp4",
                      options={"output_model": "legacy_pages", "detect": {"roi": [[0, 0], [10, 0], [10, 10], [0, 10]]}})
        ok = JobCreate(source_type="file", file_path="v.mp4", options={"detect": {"roi": [[0, 0], [10, 0], [10, 10], [0, 10]]}})
        self.assertEqual(ok.options.output_model, "clean_reflow_v1")

    def test_http_job_creation_submits_the_reflow_path(self):
        submitted = []

        class Exec:
            def submit(self, fn, *args, **kwargs):
                submitted.append((fn, args, kwargs))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "v.mp4"
            video.write_bytes(b"0")
            store = JobStore(root)
            payload = JobCreate(source_type="file", file_path=str(video), options={"detect": {"roi": [[0, 0], [10, 0], [10, 10], [0, 10]]}})
            with patch("app.main.job_store", store), patch("app.main.jobs_root", root), patch("app.main.executor", Exec()):
                main.create_job(payload)
        self.assertEqual(len(submitted), 1)
        fn, args, kwargs = submitted[0]
        self.assertIs(fn, main._run_job)
        self.assertEqual(kwargs, {})

    def test_review_export_of_a_pre_reflow_job_is_refused_not_rebuilt_raw(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cap = root / "job-l" / "review" / "capture_0001.png"
            cap.parent.mkdir(parents=True)
            cv2.imwrite(str(cap), strip_image("L"))
            store = JobStore(root)
            store.create(Job(id="job-l", source_type="file", file_path=str(root / "v.mp4"), youtube_url=None,
                             options={"export": {"formats": ["png"]}}, artifact_dir=str(root / "job-l"), status=JobStatus.DONE,
                             result={"review_candidates": [str(cap)], "images": [str(cap)]}))
            with patch("app.main.job_store", store):
                with self.assertRaises(HTTPException) as ctx:
                    main.review_export("job-l", JobReviewExportRequest(keep_captures=[str(cap)], formats=["png"]))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertTrue(ctx.exception.detail.startswith("LEGACY_JOB:"))


class ReflowJobPathTest(unittest.TestCase):
    def _run(self, side_effect):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "v.mp4"
            video.write_bytes(b"0")
            store = JobStore(root)
            payload = JobCreate(source_type="file", file_path=str(video),
                                options={"detect": {"roi": [[0, 0], [100, 0], [100, 50], [0, 50]]}})
            store.create(Job(id="job-j", source_type="file", file_path=str(video), youtube_url=None,
                             options=payload.options.model_dump(), artifact_dir=str(root / "job-j"), status=JobStatus.QUEUED))
            (root / "job-j").mkdir(exist_ok=True)
            with patch("app.main.job_store", store), \
                    patch("app.main._analyze_roi_health", return_value={"diagnostics": []}), \
                    patch("app.pipeline.reflow_pipeline.analyse_source", side_effect=side_effect):
                main._execute_job("job-j", payload)
            return store.get("job-j")

    def test_default_job_uses_reflow_and_reports_unsupported_layout(self):
        job = self._run(reflow_pipeline.UnsupportedLayoutError([{"start": 3.0, "end": 90.0, "kind": "horizontal_scroll"}]))
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "UNSUPPORTED_LAYOUT")
        self.assertEqual(job.result["reflow_state"], "unsupported_layout")
        self.assertEqual(job.result["output_model"], "clean_reflow_v1")
        self.assertEqual(job.result["images"], [])

    def test_no_systems_is_an_explicit_error(self):
        job = self._run(reflow_pipeline.NoSystemsError("none"))
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "NO_SCORE_SYSTEMS")

    def test_incomplete_decode_is_an_explicit_error(self):
        from app.pipeline.observations import VideoDecodeIncompleteError
        job = self._run(VideoDecodeIncompleteError(1.0, 6.0))
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "VIDEO_DECODE_INCOMPLETE")
        self.assertEqual(job.result["reflow_state"], "decode_incomplete")
        self.assertIsNone(job.result["pdf"])


if __name__ == "__main__":
    unittest.main()


class ReflowJobFlowTest(unittest.TestCase):
    """Job completion order, similar-system suggestions after DONE, and layout conflicts."""

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

    def record(self, widths=(1700, 1700)):
        systems = []
        for i, w in enumerate(widths):
            p = self.ws / "strips" / f"strip_sys-00{i + 1}.png"
            cv2.imwrite(str(p), strip_image(f"S{i + 1}", width=w))
            systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(p), "t_start": i * 5.0,
                            "t_end": i * 5.0 + 4.0, "slot_id": "slot-00", "layout": "bottom_bar", "episode_ids": [f"e{i}"],
                            "first_display": i == 0, "terminal_display": i == len(widths) - 1, "issues": [],
                            "strip": {"staff_gap_px": 16.0, "size": [w, 220]}})
        return {"version": "t", "output_model": "clean_reflow_v1", "workspace": str(self.ws), "systems": systems,
                "fragments": [], "exclusions": {}, "continuity_suggestions": [], "duplicate_suggestions": [],
                "_manifest": None, "_load": None}

    def run_job(self, record, suggest, **options):
        payload = JobCreate(source_type="file", file_path=str(self.video),
                            options={"detect": {"roi": [[0, 0], [100, 0], [100, 50], [0, 50]]}, "export": {"formats": ["png"]},
                                     **options})
        self.store.create(Job(id="job-f", source_type="file", file_path=str(self.video), youtube_url=None,
                              options=payload.options.model_dump(), artifact_dir=str(self.root / "job-f"), status=JobStatus.QUEUED))
        with patch("app.main.job_store", self.store), \
                patch("app.main._analyze_roi_health", return_value={"diagnostics": []}), \
                patch("app.pipeline.reflow_pipeline.analyse_source", return_value=record), \
                patch("app.pipeline.reflow_pipeline.duplicate_suggestions", side_effect=suggest):
            main._run_job("job-f", payload)
        return self.store.get("job-f")

    def test_job_is_done_with_files_before_suggestions_run(self):
        seen = {}

        def suggest(record, logger=None, should_stop=None):
            job = self.store.get("job-f")
            seen["status"] = job.status
            seen["images"] = list(job.result.get("images", []))
            seen["state"] = job.result["reflow"]["suggestions_state"]
            return [{"system_id": "sys-002", "of_system_id": "sys-001", "basis": "full_window_appearance", "reason": "looks_similar"}]

        job = self.run_job(self.record(), suggest)
        self.assertEqual(seen["status"], JobStatus.DONE)  # published first
        self.assertTrue(seen["images"])
        self.assertEqual(seen["state"], "pending")
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertEqual(job.result["reflow"]["suggestions_state"], "done")
        self.assertEqual(job.result["similar_capture_pairs"][0]["reason"], "looks_similar")
        # a suggestion is never applied: both systems stay included and placed
        # (measure reflow is on by default: a line placement lists the systems it holds)
        placed = [sid for p in job.result["reflow"]["page_plan"]["pages"] for pl in p["placements"]
                  for sid in (pl.get("system_ids") or [pl["system_id"]])]
        self.assertEqual(placed, ["sys-001", "sys-002"])

    def test_suggestions_stop_at_the_time_budget_and_on_cancel(self):
        def slow(record, logger=None, should_stop=None):
            import time as _t
            t0 = _t.monotonic()
            while not should_stop():
                if _t.monotonic() - t0 > 5:
                    raise AssertionError("not bounded")
                _t.sleep(0.01)
            return []

        with patch.object(main, "SUGGESTION_TIME_BUDGET_SEC", 0.2):
            job = self.run_job(self.record(), slow)
        self.assertEqual(job.result["reflow"]["suggestions_state"], "partial")

    def test_cancel_stops_pending_suggestions(self):
        def cancelled(record, logger=None, should_stop=None):
            main.cancel_pending_suggestions("job-f")
            self.assertTrue(should_stop())
            return []

        job = self.run_job(self.record(), cancelled)
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertEqual(job.result["reflow"]["suggestions_state"], "cancelled")

    def test_strip_wider_than_the_page_is_a_conflict_until_the_user_chooses(self):
        # 2600 px at a 16 px gap fits the line only at about 1.1 mm, below the automatic floor (1.2 mm):
        # a visible conflict, never "done" without files (STRATEGY Step 2A)
        job = self.run_job(self.record(widths=(1700, 2600)), lambda *a, **k: [])
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "LAYOUT_CONFLICT")
        self.assertEqual(job.result["reflow_state"], "layout_conflict")
        self.assertEqual(job.result["reflow"]["page_plan"]["staff_size"]["reason"], "BELOW_AUTO_MINIMUM")
        self.assertEqual(job.result["images"], [])
        conflict = job.result["reflow"]["layout_conflict"]
        self.assertEqual([c["system_id"] for c in conflict["conflicts"]], ["sys-002"])
        offered = conflict["largest_fitting_staff_gap_mm"]
        self.assertTrue(1.0 <= offered < 1.5)
        diag = job.result["capture_diagnostics"][job.result["review_candidates"][1]]
        self.assertIn("LAYOUT_CONFLICT", diag["diagnostic_codes"])
        paths = job.result["review_candidates"]
        with patch("app.main.job_store", self.store):
            # rebuilding without a choice is refused (409) and changes no files
            with self.assertRaises(HTTPException) as ctx:
                main.review_export("job-f", JobReviewExportRequest(keep_captures=paths))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertTrue(ctx.exception.detail.startswith("LAYOUT_CONFLICT:"))
            # excluding the system resolves it at 1.5 mm
            main.review_export("job-f", JobReviewExportRequest(keep_captures=[paths[0]]))
            self.assertAlmostEqual(self.store.get("job-f").result["reflow"]["page_plan"]["staff_gap_mm"], 1.5, places=3)
            # or the explicit choice of the offered smaller size for this document
            main.review_export("job-f", JobReviewExportRequest(keep_captures=paths, staff_gap_mm=offered))
        result = self.store.get("job-f").result
        self.assertEqual(result["reflow_state"], "review_required")
        self.assertTrue(result["review_required"])  # layout resolved; raw-to-PDF ledger remains unassessed
        self.assertAlmostEqual(result["reflow"]["page_plan"]["staff_gap_mm"], offered, places=4)
        self.assertEqual(result["reflow"]["staff_gap_mm"], offered)
        self.assertNotIn("layout_conflict", result["reflow"])
        self.assertTrue(result["images"])

    def test_strip_fitting_at_a_smaller_size_is_done_at_that_size_and_disclosed(self):
        # 2300 px at a 16 px gap fits the line up to about 1.25 mm: whole systems at 1.25 mm (>= 1.2 mm)
        job = self.run_job(self.record(widths=(1700, 2300)), lambda *a, **k: [], measure_reflow=False)
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertIsNone(job.error_code)
        self.assertEqual(job.result["reflow_state"], "review_required")
        self.assertTrue(job.result["review_required"])  # files finished; preservation has no producer obligations
        self.assertTrue(job.result["images"])
        plan = job.result["reflow"]["page_plan"]
        self.assertAlmostEqual(plan["staff_gap_mm"], 1.25, places=3)
        size = job.result["measure_reflow"]["staff_size"]
        self.assertEqual(size, {"staff_gap_mm": 1.25, "staff_gap_mm_requested": 1.5, "auto_reduced": True,
                                "reason": "WHOLE_SYSTEMS_DO_NOT_FIT"})
        self.assertTrue(job.result["reflow"]["export_verification"]["verified"])
        # an explicit size chosen in review is used as it is: 1.5 mm again is a conflict, 1.3 mm is kept
        paths = job.result["review_candidates"]
        with patch("app.main.job_store", self.store):
            with self.assertRaises(HTTPException) as ctx:
                main.review_export("job-f", JobReviewExportRequest(keep_captures=paths, staff_gap_mm=1.4))
            self.assertTrue(ctx.exception.detail.startswith("LAYOUT_CONFLICT:"))
            self.assertEqual(self.store.get("job-f").status, JobStatus.DONE)  # previous files stay published
            main.review_export("job-f", JobReviewExportRequest(keep_captures=paths, staff_gap_mm=1.25))
        result = self.store.get("job-f").result
        self.assertAlmostEqual(result["reflow"]["page_plan"]["staff_gap_mm"], 1.25, places=3)
        self.assertTrue(result["reflow"]["staff_gap_mm_explicit"])

    def test_an_export_without_pages_is_never_done(self):
        def empty_export(*, pages, formats, workspace, logger, **kw):
            Path(workspace).mkdir(parents=True, exist_ok=True)
            return {"images": [], "pdf": None, "preview_images": [], "page_count": 0, "formats": ["png", "pdf"]}

        with patch("app.pipeline.export.export_composed_pages", side_effect=empty_export):
            job = self.run_job(self.record(), lambda *a, **k: [])
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "EMPTY_EXPORT")
        self.assertEqual(job.result["reflow_state"], "export_invalid")
        self.assertEqual(job.result["images"], [])
        self.assertIsNone(job.result["pdf"])
        self.assertEqual(job.result["reflow"]["export_verification"]["error_code"], "EMPTY_EXPORT")
        self.assertTrue(job.result["reflow"]["page_plan"]["pages"])  # diagnostics kept
        self.assertFalse((self.root / "job-f" / "export").exists())

    def test_review_export_with_a_mismatched_page_count_keeps_the_previous_files(self):
        job = self.run_job(self.record(), lambda *a, **k: [])
        self.assertEqual(job.status, JobStatus.DONE)
        export_dir = self.root / "job-f" / "export"
        before = digest(export_dir)
        paths = job.result["review_candidates"]

        def short_export(*, pages, formats, workspace, logger, **kw):
            # one PNG page fewer than planned
            res = export_composed_pages(pages=pages, formats=["png"], workspace=workspace, logger=logger)
            return dict(res, images=res["images"][:-1])

        with patch("app.main.job_store", self.store), \
                patch("app.pipeline.export.export_composed_pages", side_effect=short_export):
            with self.assertRaises(HTTPException) as ctx:
                main.review_export("job-f", JobReviewExportRequest(keep_captures=paths))
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertTrue(ctx.exception.detail.startswith("PAGE_COUNT_MISMATCH:"), ctx.exception.detail)
        self.assertEqual(digest(export_dir), before)
        self.assertEqual(self.store.get("job-f").status, JobStatus.DONE)

    def test_unavailable_uncut_strip_ends_the_job_with_uncut_strip_unavailable(self):
        # round 6 (f): sys-001's preview tail was cut toward sys-002, which is not placed, so the
        # uncut strip is needed; it is missing and cannot be rebuilt (no stored observations)
        record = self.record()
        s1, s2 = record["systems"]
        s1["strip"]["preview_tail"] = {"cut": True, "verified": True, "destination_system_id": "sys-002"}
        s1["strip"]["uncut"] = {"path": str(self.ws / "strips" / "uncut" / "strip_sys-001.png"),
                                "box_crop": [0, 0, 1900, 220], "size": [1900, 220]}
        s2["included"] = False
        export_dir = self.root / "job-f" / "export"
        export_dir.mkdir(parents=True)
        (export_dir / "page_001.png").write_bytes(b"previous page")
        before_export, before_ws = digest(export_dir), digest(self.ws)
        calls = []
        job = self.run_job(record, lambda *a, **k: calls.append(1) or [])
        self.assertEqual(job.status, JobStatus.ERROR)
        self.assertEqual(job.error_code, "UNCUT_STRIP_UNAVAILABLE")
        self.assertTrue(job.message.startswith("UNCUT_STRIP_UNAVAILABLE:"), job.message)
        self.assertEqual(job.result["reflow_state"], "dependency_unavailable")
        self.assertEqual(job.result["images"], [])
        self.assertIsNone(job.result["pdf"])
        self.assertNotIn("page_plan", job.result["reflow"])
        self.assertEqual(calls, [])  # no suggestions for a job that made no chart
        # nothing written: the previous export and the strips stay as they were
        self.assertEqual(digest(export_dir), before_export)
        self.assertEqual(digest(self.ws), before_ws)
        self.assertEqual([p.name for p in (self.root / "job-f").iterdir() if p.name.startswith("export_staged_")], [])


class UncutStripFailClosedTest(DependencyRevalidationTest):
    """Audit round 4, blocker 2: a missing or unreadable uncut strip was recorded as
    ``uncut_strip_missing`` and the page was still made from the CUT strip, its destination
    absent. Now it is regenerated and verified, or the export stops with an explicit
    409 ``UNCUT_STRIP_UNAVAILABLE`` and the previous export stays as it was."""

    def _fails_closed(self):
        export_dir = self.artifact / "export"
        before = digest(export_dir)
        result_before = self.store.get("job-d").result
        with patch("app.main.job_store", self.store):
            with self.assertRaises(HTTPException) as ctx:
                main.review_export("job-d", JobReviewExportRequest(keep_captures=[self.paths[k] for k in ("sys-001", "sys-003", "sys-004")],
                                                                   formats=["png"]))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue(ctx.exception.detail.startswith("UNCUT_STRIP_UNAVAILABLE:"), ctx.exception.detail)
        self.assertIn("원본 줄 이미지", ctx.exception.detail)
        self.assertIn("could not be rebuilt", ctx.exception.detail)
        self.assertIn("sys-001", ctx.exception.detail)
        self.assertEqual(digest(export_dir), before)
        self.assertEqual(self.store.get("job-d").result, result_before)
        self.assertEqual([p.name for p in self.artifact.iterdir() if p.name.startswith("export_staged_")], [])

    def test_missing_uncut_strip_stops_the_export(self):
        Path(self.systems[0]["strip"]["uncut"]["path"]).unlink()
        self._fails_closed()

    def test_unreadable_uncut_strip_stops_the_export(self):
        Path(self.systems[0]["strip"]["uncut"]["path"]).write_bytes(b"not an image")
        self._fails_closed()

    def test_wrong_size_uncut_strip_stops_the_export(self):
        # round 6 (g): decodable but not the recorded size, and nothing to rebuild it from
        cv2.imwrite(self.systems[0]["strip"]["uncut"]["path"], strip_image("S1 + TAIL", width=1500))
        self._fails_closed()

    def test_compose_never_places_the_cut_strip_without_its_destination(self):
        Path(self.systems[0]["strip"]["uncut"]["path"]).unlink()
        with self.assertRaises(reflow_pipeline.DependencyUnavailableError) as ctx:
            reflow_pipeline.compose_systems([self.systems[0], self.systems[2]], all_systems=self.systems)
        self.assertEqual(ctx.exception.system_id, "sys-001")
        self.assertEqual(ctx.exception.code, "UNCUT_STRIP_UNAVAILABLE")

    def test_missing_uncut_is_not_needed_while_the_destination_follows(self):
        Path(self.systems[0]["strip"]["uncut"]["path"]).unlink()
        job, pls, deps = self.export(["sys-001", "sys-002", "sys-003", "sys-004"])
        self.assertEqual(pls["sys-001"]["strip_variant"], "strip")


class UncutStripRegenerationTest(unittest.TestCase):
    """A real job workspace (analyse_source on a lossless synthetic video): the uncut strip of
    a cut preview tail is rebuilt from the stored observations and verified by its pixel hash."""

    @classmethod
    def setUpClass(cls):
        from test_reflow_strips import full_frames, preview_frames, system_image
        cls.td = tempfile.TemporaryDirectory()
        root = Path(cls.td.name)
        cur, nxt, oth = system_image(7), system_image(8), system_image(9)
        frames = preview_frames(cur, nxt, n=32) + full_frames(nxt, n=32, t0=8) + full_frames(oth, n=32, t0=16)
        cls.video = root / "v.avi"
        vw = cv2.VideoWriter(str(cls.video), cv2.VideoWriter_fourcc(*"FFV1"), 4, (1400, 190))
        for _t, img in frames:
            vw.write(img)
        vw.release()
        cls.template = root / "template"
        cls.record = reflow_pipeline.analyse_source(video_path=cls.video, roi=[[0, 0], [1400, 0], [1400, 190], [0, 190]],
                                                    workspace=cls.template / "reflow")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def setUp(self):
        import json
        import shutil
        self.inner = tempfile.TemporaryDirectory()
        self.root = Path(self.inner.name)
        self.artifact = self.root / "job-g"
        shutil.copytree(self.template, self.artifact)
        # the job's record, with paths moved into this job's folder
        # JSON text holds paths with escaped separators (backslashes on Windows)
        text = json.dumps(reflow_pipeline.public_record(self.record)).replace(
            json.dumps(str(self.template))[1:-1], json.dumps(str(self.artifact))[1:-1])
        reflow = json.loads(text)
        self.systems = reflow["systems"]
        self.assertTrue(self.systems[0]["strip"]["preview_tail"]["cut"])
        self.uncut = Path(self.systems[0]["strip"]["uncut"]["path"])
        self.original = cv2.imread(str(self.uncut))
        plan, pages = reflow_pipeline.compose_systems(self.systems, header={"title": "T"}, all_systems=self.systems,
                                                      workspace=self.artifact / "reflow")
        out = export_composed_pages(pages=pages, formats=["png"], workspace=self.artifact / "export", logger=lambda _m: None)
        reflow.update(page_plan=plan, header={"title": "T"}, revision=1, duplicate_suggestions=[], dependencies=plan["dependencies"])
        result = {"output_model": "clean_reflow_v1", "reflow_state": "done", "reflow": reflow, "images": out["images"], "pdf": None,
                  **main._reflow_capture_fields(reflow)}
        self.store = JobStore(self.root)
        self.store.create(Job(id="job-g", source_type="file", file_path=str(self.video), youtube_url=None,
                              options={"export": {"formats": ["png"]}}, artifact_dir=str(self.artifact),
                              status=JobStatus.DONE, result=result))

    def tearDown(self):
        self.inner.cleanup()

    def _export_without_destination(self):
        paths = {s["id"]: s["strip_path"] for s in self.systems}
        with patch("app.main.job_store", self.store):
            main.review_export("job-g", JobReviewExportRequest(keep_captures=[paths["sys-001"], paths["sys-003"]], formats=["png"]))
        job = self.store.get("job-g")
        plan = job.result["reflow"]["page_plan"]
        return {pl["system_id"]: pl for p in plan["pages"] for pl in p["placements"]}, plan["dependencies"]

    def test_missing_uncut_strip_is_regenerated_and_verified(self):
        self.uncut.unlink()
        pls, deps = self._export_without_destination()
        self.assertEqual(pls["sys-001"]["strip_variant"], "uncut")
        restored = deps["preview_tails_restored"][0]
        self.assertEqual(restored["regenerated"], {"was": "uncut_strip_missing", "verified_by": "pixel_hash"})
        self.assertTrue(np.array_equal(cv2.imread(str(self.uncut)), self.original))

    def test_damaged_uncut_strip_is_regenerated(self):
        cv2.imwrite(str(self.uncut), 255 - self.original)  # decodable, right size, wrong pixels
        pls, deps = self._export_without_destination()
        self.assertEqual(deps["preview_tails_restored"][0]["regenerated"]["was"], "uncut_strip_damaged")
        self.assertTrue(np.array_equal(cv2.imread(str(self.uncut)), self.original))

    def test_wrong_size_uncut_strip_is_regenerated(self):
        # round 6 (g): a decodable file of another size is rebuilt and verified
        cv2.imwrite(str(self.uncut), self.original[:, :-12])
        pls, deps = self._export_without_destination()
        self.assertEqual(pls["sys-001"]["strip_variant"], "uncut")
        self.assertEqual(deps["preview_tails_restored"][0]["regenerated"], {"was": "uncut_strip_size_differs", "verified_by": "pixel_hash"})
        self.assertTrue(np.array_equal(cv2.imread(str(self.uncut)), self.original))

    def test_regeneration_decodes_the_source_again_after_frames_were_pruned(self):
        reflow_pipeline.prune_frames({"workspace": str(self.artifact / "reflow")})
        self.uncut.write_bytes(b"broken")
        pls, deps = self._export_without_destination()
        self.assertEqual(pls["sys-001"]["strip_variant"], "uncut")
        self.assertTrue(np.array_equal(cv2.imread(str(self.uncut)), self.original))

    def test_unverifiable_regeneration_fails_closed_and_keeps_the_export(self):
        import json
        # the stored observations no longer reproduce the recorded pixels
        occ_path = self.artifact / "reflow" / "occurrences.json"
        occ = json.loads(occ_path.read_text(encoding="utf-8"))
        occ["systems"][0]["observations"] = occ["systems"][2]["observations"]  # another system's observations
        occ_path.write_text(json.dumps(occ), encoding="utf-8")
        self.uncut.unlink()
        before = digest(self.artifact / "export")
        result_before = self.store.get("job-g").result
        with self.assertRaises(HTTPException) as ctx:
            self._export_without_destination()
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertRegex(ctx.exception.detail, r"regenerated_(pixels|size)_differ")
        self.assertFalse(self.uncut.exists())  # nothing unverified is written
        self.assertEqual(digest(self.artifact / "export"), before)
        self.assertEqual(self.store.get("job-g").result, result_before)
