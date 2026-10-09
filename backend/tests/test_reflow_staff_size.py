"""Automatic staff size for dense charts (docs/reflow/DECISIONS.md): measure lines may use a smaller
staff size, never below 1.2 mm, when dense measures leave lines short; the largest size on a 0.05 mm
grid that fills every line, else the size with the fewest short lines (the larger on a tie). Charts
already full at the chosen size are unchanged, and a size the user chose in review is used as it is."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_measure as rmeas
from app.pipeline import reflow_pipeline as rp
from app.pipeline.export import export_composed_pages
from app.schemas import JobReviewExportRequest

from test_reflow_measure import measure_strip


def fake_plan(short_ids, *, n_lines=4):
    """(built, lines_plan) with ``n_lines`` one-atom lines; ``short_ids`` are short."""
    atoms = [{"id": f"a{i}", "break_before": "system_start" if i == 0 else "safe_cut", "join_legal": False} for i in range(n_lines)]
    lines = [{"id": f"line-{i + 1:03d}", "start": i, "end": i + 1} for i in range(n_lines)]
    ragged = [{"line_id": lid, "reason": "LOCKED_SPAN"} for lid in short_ids]
    return {"atoms": atoms}, {"lines": lines, "ragged_exceptions": ragged}


class CandidateGridTest(unittest.TestCase):
    def test_grid_is_0_05_mm_down_to_the_floor(self):
        self.assertEqual(rmeas.staff_size_candidates(1.5), [1.45, 1.4, 1.35, 1.3, 1.25, 1.2])
        self.assertEqual(rmeas.staff_size_candidates(1.3), [1.25, 1.2])
        self.assertEqual(rmeas.staff_size_candidates(1.2), [])
        self.assertEqual(rmeas.staff_size_candidates(1.0), [])
        self.assertEqual(rmeas.staff_size_candidates(1.53), [1.5, 1.45, 1.4, 1.35, 1.3, 1.25, 1.2])
        self.assertTrue(all(mm >= rmeas.AUTO_MIN_STAFF_GAP_MM for mm in rmeas.staff_size_candidates(2.5)))


class ChooseStaffSizeTest(unittest.TestCase):
    def choose(self, shorts, short_requested):
        calls = []

        def short_at(mm):
            calls.append(mm)
            return shorts.get(mm)
        chosen, tried = rmeas.choose_staff_size(1.5, short_at, short_requested)
        return chosen, calls, tried

    def test_largest_size_that_fills_every_line(self):
        chosen, calls, _ = self.choose({1.45: 5, 1.4: 2, 1.35: 0, 1.3: 0, 1.25: 0, 1.2: 0}, 9)
        self.assertEqual(chosen, 1.35)
        self.assertEqual(calls, [1.45, 1.4, 1.35])  # stops at the first full size

    def test_never_below_the_floor(self):
        chosen, calls, _ = self.choose({1.45: 8, 1.4: 7, 1.35: 6, 1.3: 5, 1.25: 4, 1.2: 3, 1.15: 0, 1.1: 0}, 9)
        self.assertEqual(chosen, 1.2)
        self.assertEqual(min(calls), 1.2)

    def test_fewest_short_lines_and_the_larger_on_a_tie(self):
        chosen, _, tried = self.choose({1.45: 3, 1.4: 1, 1.35: 2, 1.3: 1, 1.25: 1, 1.2: 1}, 4)
        self.assertEqual(chosen, 1.4)
        self.assertEqual(tried[0], {"staff_gap_mm": 1.5, "short_lines": 4})

    def test_requested_size_wins_a_tie(self):
        chosen, _, _ = self.choose({1.45: 2, 1.4: 3, 1.35: 2, 1.3: 2, 1.25: 2, 1.2: 2}, 2)
        self.assertEqual(chosen, 1.5)

    def test_a_size_without_a_plan_is_skipped(self):
        chosen, _, tried = self.choose({1.45: None, 1.4: 0}, 3)
        self.assertEqual(chosen, 1.4)
        self.assertIsNone(tried[1]["short_lines"])


class ComposeSearchTest(unittest.TestCase):
    """compose(): plans only at the candidate sizes, renders once."""

    def run_compose(self, plans, *, requested=1.5, auto=True):
        planned, rendered = [], []

        def plan_at(decided, mm, **kw):
            planned.append(mm)
            if plans.get(mm) is None:
                raise rmeas.MeasurePlanUnavailable("NO_FEASIBLE_LINE_BREAKS")
            return plans[mm]

        def render(built, lines_plan, *, header, staff_gap_mm, content_w):
            rendered.append(staff_gap_mm)
            return {"staff_gap_mm": staff_gap_mm, "staff_gap_mm_requested": staff_gap_mm, "measure_reflow": {}}, ["page"]

        with patch.object(rmeas, "_plan_at", side_effect=plan_at), patch.object(rmeas, "_render", side_effect=render):
            plan, _pages = rmeas.compose([], header=None, staff_gap_mm=requested, context=None, auto_staff_size=auto)
        return plan, planned, rendered

    def test_full_chart_is_planned_and_rendered_once_at_the_chosen_size(self):
        plan, planned, rendered = self.run_compose({1.5: fake_plan([])})
        self.assertEqual((planned, rendered), ([1.5], [1.5]))
        self.assertEqual(plan["staff_size"]["reason"], "LINES_FULL")
        self.assertFalse(plan["staff_size"]["auto_reduced"])
        self.assertEqual(plan["staff_gap_mm"], 1.5)

    def test_dense_chart_is_reduced_and_rendered_once(self):
        plans = {1.5: fake_plan(["line-001", "line-002"]), 1.45: fake_plan(["line-001"]), 1.4: fake_plan([]),
                 1.35: fake_plan([])}
        plan, planned, rendered = self.run_compose(plans)
        self.assertEqual(planned, [1.5, 1.45, 1.4])
        self.assertEqual(rendered, [1.4])
        size = plan["staff_size"]
        self.assertEqual((size["staff_gap_mm"], size["staff_gap_mm_requested"], size["auto_reduced"], size["reason"]),
                         (1.4, 1.5, True, "DENSE_LINES_NOT_FULL"))
        self.assertEqual(plan["staff_gap_mm_requested"], 1.5)
        self.assertEqual(plan["measure_reflow"]["staff_size"], size)

    def test_floor_when_no_size_fills_every_line(self):
        plans = {mm: fake_plan(["line-001", "line-002"]) for mm in (1.5, 1.45, 1.4, 1.35, 1.3, 1.25)}
        plans[1.2] = fake_plan(["line-001"])
        plan, planned, rendered = self.run_compose(plans)
        self.assertEqual(planned[-1], 1.2)
        self.assertEqual(rendered, [1.2])
        self.assertEqual(plan["staff_size"]["short_lines"], 1)

    def test_no_smaller_size_helps(self):
        plans = {mm: fake_plan(["line-001", "line-002"]) for mm in (1.5, 1.45, 1.4, 1.35, 1.3, 1.25, 1.2)}
        plan, _planned, rendered = self.run_compose(plans)
        self.assertEqual(rendered, [1.5])
        self.assertEqual(plan["staff_size"]["reason"], "NO_SMALLER_SIZE_HELPS")

    def test_one_short_line_never_shrinks_the_chart(self):
        # Q8: one unavoidable short line (an opening multi-measure rest) in 33 lines
        plans = {1.5: fake_plan(["line-001"], n_lines=33), 1.2: fake_plan([], n_lines=25)}
        plan, planned, rendered = self.run_compose(plans)
        self.assertEqual((planned, rendered), ([1.5], [1.5]))
        self.assertEqual(plan["staff_size"]["reason"], "FEW_SHORT_LINES")
        plans = {1.5: fake_plan(["line-001", "line-002"], n_lines=60), 1.45: fake_plan([], n_lines=58)}
        plan, planned, _ = self.run_compose(plans)
        self.assertEqual((planned, plan["staff_size"]["reason"]), ([1.5], "FEW_SHORT_LINES"))

    def test_off_and_at_the_floor(self):
        plan, planned, _ = self.run_compose({1.5: fake_plan(["line-001"]), 1.4: fake_plan([])}, auto=False)
        self.assertEqual((planned, plan["staff_size"]["reason"]), ([1.5], "AUTO_OFF"))
        plan, planned, _ = self.run_compose({1.2: fake_plan(["line-001", "line-002"])}, requested=1.2)
        self.assertEqual((planned, plan["staff_size"]["reason"]), ([1.2], "AT_MINIMUM"))


class FullChartUnchangedTest(unittest.TestCase):
    def test_pages_are_identical_with_and_without_the_search(self):
        with tempfile.TemporaryDirectory() as td:
            systems = []
            for i in range(3):
                img, rec = measure_strip()
                path = Path(td) / f"strip_sys-00{i + 1}.png"
                cv2.imwrite(str(path), img)
                systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(path), "issues": [],
                                "t_start": float(i), "t_end": i + 0.9, "layout": "bottom_bar", "strip": dict(rec, system_id=f"sys-00{i + 1}")})
            plan_a, pages_a = rp.compose_systems(systems, header={"title": "T"}, measure_reflow=True, measure_context={})
            plan_b, pages_b = rp.compose_systems(systems, header={"title": "T"}, measure_reflow=True, measure_context={},
                                                 auto_staff_size=True)
        self.assertEqual(plan_b["measure_reflow"]["status"], "measure_lines")
        self.assertEqual(plan_b["staff_size"]["reason"], "LINES_FULL")
        self.assertEqual(len(pages_a), len(pages_b))
        for a, b in zip(pages_a, pages_b):
            self.assertTrue(np.array_equal(a, b))


class ReviewExportStaffSizeTest(unittest.TestCase):
    """The review export searches only while the document keeps the job's size."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        art = self.root / "job-s"
        strips = art / "reflow" / "strips"
        strips.mkdir(parents=True)
        systems = []
        for i in range(2):
            img, rec = measure_strip()
            path = strips / f"strip_sys-00{i + 1}.png"
            cv2.imwrite(str(path), img)
            systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(path), "issues": [],
                            "t_start": float(i), "t_end": i + 0.9, "layout": "bottom_bar", "strip": dict(rec, system_id=f"sys-00{i + 1}")})
        plan, pages = rp.compose_systems(systems, header={"title": "T"})
        out = export_composed_pages(pages=pages, formats=["png"], workspace=art / "export", logger=lambda _m: None)
        reflow = {"systems": systems, "page_plan": plan, "header": {"title": "T"}, "revision": 1, "duplicate_suggestions": [],
                  "workspace": str(art / "reflow"), "staff_gap_mm": 1.5}
        result = {"output_model": "clean_reflow_v1", "reflow_state": "done", "reflow": reflow, "images": out["images"], "pdf": None,
                  **main._reflow_capture_fields(reflow)}
        self.store = JobStore(self.root)
        self.store.create(Job(id="job-s", source_type="file", file_path=str(self.root / "v.mp4"), youtube_url=None,
                              options={"measure_reflow": True, "staff_gap_mm": 1.5, "export": {"formats": ["png"]}},
                              artifact_dir=str(art), status=JobStatus.DONE, result=result))
        self.paths = [s["strip_path"] for s in systems]

    def tearDown(self):
        self.td.cleanup()

    def export(self, **kwargs):
        calls = []
        real = rp.compose_systems

        def spy(*args, **kw):
            calls.append(kw)
            return real(*args, **kw)
        with patch.object(main, "job_store", self.store), patch.object(rp, "compose_systems", side_effect=spy):
            main.review_export("job-s", JobReviewExportRequest(keep_captures=self.paths, formats=["png"], **kwargs))
        return calls[-1], self.store.get("job-s").result

    def test_default_size_allows_the_search_and_records_the_size_used(self):
        kw, result = self.export()
        self.assertTrue(kw["auto_staff_size"])
        self.assertEqual(kw["staff_gap_mm"], 1.5)
        self.assertFalse(result["reflow"]["staff_gap_mm_explicit"])
        self.assertEqual(result["measure_reflow"]["staff_size"],
                         {"staff_gap_mm": 1.5, "staff_gap_mm_requested": 1.5, "auto_reduced": False, "reason": "LINES_FULL"})

    def test_explicit_size_is_used_as_it_is_and_kept_for_rebuilds(self):
        kw, result = self.export(staff_gap_mm=1.3)
        self.assertFalse(kw["auto_staff_size"])
        self.assertEqual(kw["staff_gap_mm"], 1.3)
        self.assertTrue(result["reflow"]["staff_gap_mm_explicit"])
        kw, result = self.export()  # a later rebuild keeps the user's size, still without the search
        self.assertEqual((kw["staff_gap_mm"], kw["auto_staff_size"]), (1.3, False))
        # "back to 1.5 mm" (the job's size) allows the search again
        kw, result = self.export(staff_gap_mm=1.5)
        self.assertTrue(kw["auto_staff_size"])
        self.assertFalse(result["reflow"]["staff_gap_mm_explicit"])

    def test_document_saved_before_the_flag_with_a_smaller_size_counts_as_explicit(self):
        job = self.store.get("job-s")
        job.result["reflow"]["staff_gap_mm"] = 1.3
        job.result["reflow"]["staff_gap_mm_default"] = 1.5
        kw, _ = self.export()
        self.assertEqual((kw["staff_gap_mm"], kw["auto_staff_size"]), (1.3, False))


if __name__ == "__main__":
    unittest.main()
