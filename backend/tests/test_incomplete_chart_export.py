"""STRATEGY Step 2A: an incomplete chart is marked on paper, and ended jobs drop heavy temp data.

* coverage ``incomplete`` -> page-1 notice under the title naming every unresolved interval, plus a
  one-row boxed marker between the systems placed before and after an interval whose position in
  the output order is known (main._compose_header, reflow_render.layout_markers, reflow_layout markers);
* a complete chart composes exactly as before;
* a job that ends in error, refusal or cancel keeps JSON/logs, ROI-health samples and
  its strips but loses frames and other image/array caches (main.prune_job_workspace)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_layout as rl
from app.pipeline import reflow_pipeline
from app.pipeline import reflow_render as rr
from app.pipeline.export import export_composed_pages, verify_composed_export
from app.pipeline.process_control import OperationCancelled
from app.schemas import JobReviewExportRequest


def strip_image(label, width=1700, gap=16, top=60, height=220):
    img = np.full((height, width, 3), 250, np.uint8)
    for k in range(5):
        y = top + k * gap
        cv2.line(img, (10, y), (width - 10, y), (0, 0, 0), 2)
    cv2.putText(img, label, (40, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    return img


def make_systems(folder: Path, times):
    folder.mkdir(parents=True, exist_ok=True)
    systems = []
    for i, (a, b) in enumerate(times):
        p = folder / f"strip_sys-00{i + 1}.png"
        cv2.imwrite(str(p), strip_image(f"S{i + 1}"))
        systems.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(p), "issues": [],
                        "t_start": a, "t_end": b, "strip": {"staff_gap_px": 16.0, "size": [1700, 220]}})
    return systems


def incomplete(*spans):
    return {"status": "incomplete", "unresolved": [list(s) for s in spans],
            "intervals": [{"start": a, "end": b, "status": "unresolved", "unresolved_span": [a, b]} for a, b in spans]}


def placements(plan):
    return [pl for p in plan["pages"] for pl in p["placements"]]


def markers(plan):
    return [(p["index"], mk) for p in plan["pages"] for mk in p.get("markers", [])]


class ComposeHeaderTest(unittest.TestCase):
    def setUp(self):
        self.systems = [{"id": "a", "t_start": 0.0, "t_end": 4.0}, {"id": "b", "t_start": 5.0, "t_end": 9.0},
                        {"id": "c", "t_start": 20.0, "t_end": 24.0}]

    def test_complete_coverage_keeps_the_header_object(self):
        header = {"title": "T"}
        self.assertIs(main._compose_header(header, None, self.systems), header)
        self.assertIs(main._compose_header(header, {"status": "complete", "unresolved": []}, self.systems), header)

    def test_clean_split_gives_the_systems_before(self):
        header = {"title": "T"}
        out = main._compose_header(header, incomplete((10.2, 18.7)), self.systems)
        self.assertNotIn("incomplete", header)  # the stored header is not changed
        self.assertEqual(out["incomplete"]["markers"], [{"start": 10.2, "end": 18.7, "before_ids": ["a", "b"]}])
        out = main._compose_header(header, incomplete((25.0, 30.0)), self.systems)
        self.assertEqual(out["incomplete"]["markers"][0]["before_ids"], ["a", "b", "c"])
        out = main._compose_header(header, incomplete((0.0, 0.0)), [dict(s, t_start=s["t_start"] + 1) for s in self.systems])
        self.assertEqual(out["incomplete"]["markers"][0]["before_ids"], [])

    def test_overlapping_or_reordered_systems_leave_the_position_unknown(self):
        overlap = [dict(self.systems[0]), dict(self.systems[1], t_end=15.0), dict(self.systems[2])]
        out = main._compose_header({}, incomplete((10.0, 18.0)), overlap)
        self.assertIsNone(out["incomplete"]["markers"][0]["before_ids"])
        reordered = [self.systems[2], self.systems[0], self.systems[1]]
        out = main._compose_header({}, incomplete((10.0, 18.0)), reordered)
        self.assertIsNone(out["incomplete"]["markers"][0]["before_ids"])
        out = main._compose_header({}, incomplete((10.0, 18.0)), [{"id": "x"}])
        self.assertIsNone(out["incomplete"]["markers"][0]["before_ids"])


class NoticeTextTest(unittest.TestCase):
    def test_korean_default_and_english_when_known(self):
        h = {"title": "T", "incomplete": {"unresolved": [[70.4, 95.2], [3601.0, 3605.5]]}}
        self.assertEqual(rr.incomplete_notice_text(h), "미완성 악보: 영상 01:10–01:36, 1:00:01–1:00:06 구간을 복구하지 못했습니다.")
        self.assertEqual(rr.marker_text(h, 70.4, 95.2), "[누락 구간 01:10–01:36]")
        h["incomplete"]["locale"] = "en"
        self.assertEqual(rr.incomplete_notice_text(h), "Incomplete chart: video 01:10–01:36, 1:00:01–1:00:06 could not be recovered.")
        self.assertEqual(rr.marker_text(h, 70.4, 95.2), "[Missing 01:10–01:36]")
        self.assertIsNone(rr.incomplete_notice_text({"title": "T"}))
        self.assertIsNone(rr.incomplete_notice_text({"title": "T", "incomplete": {"unresolved": []}}))

    def test_line_markers_only_at_a_clean_break(self):
        h = {"incomplete": {"unresolved": [[10, 18]], "markers": [{"start": 10, "end": 18, "before_ids": ["a", "b"]}]}}
        mk, rec = rr.layout_markers(h, [("L1", ["a"]), ("L2", ["b"]), ("L3", ["c"])])
        self.assertEqual([m["after"] for m in mk], ["L2"])
        self.assertEqual(rec[0]["position"], "placed")
        # a line that joins b and c: the interval falls inside a line -> notice only
        mk, rec = rr.layout_markers(h, [("L1", ["a"]), ("L2", ["b", "c"])])
        self.assertEqual(mk, [])
        self.assertEqual(rec[0]["position"], "inside_line")
        h["incomplete"]["markers"][0]["before_ids"] = None
        mk, rec = rr.layout_markers(h, [("L1", ["a"]), ("L2", ["b"])])
        self.assertEqual((mk, rec[0]["position"]), ([], "unknown"))


class LayoutMarkerTest(unittest.TestCase):
    def test_complete_plan_is_unchanged(self):
        units = [{"id": f"s{i}", "width": 1500, "height": 900, "staff_gap_px": 16.0} for i in range(7)]
        self.assertEqual(rl.plan_pages(units, header_height_px=120), rl.plan_pages(units, header_height_px=120, markers=()))

    def test_trailing_marker_never_sits_alone_on_a_page(self):
        g = 1.5 * rl.MM
        content_h = rl.PAGE_H - rl.MARGIN_TOP - rl.MARGIN_BOTTOM
        h = (content_h - 2 * int(rl.MIN_SEP_GAPS * g + 1)) // 3  # three units fill page 1
        units = [{"id": f"s{i}", "width": 1500, "height": h, "staff_gap_px": g} for i in range(3)]
        mk = [{"id": "missing-1", "after": "s2", "h": rr.MARKER_H, "text": "[x]"}]
        plan = rl.plan_pages(units, markers=mk)
        self.assertTrue(plan["validation"]["valid"], plan["validation"])
        self.assertTrue(all(p["placements"] for p in plan["pages"]))
        (page, m), = markers(plan)
        last = plan["pages"][page - 1]["placements"][-1]
        self.assertEqual(last["system_id"], "s2")
        self.assertGreaterEqual(m["y"], last["y"] + last["h"])
        self.assertLessEqual(m["y"] + m["h"], rl.PAGE_H - rl.MARGIN_BOTTOM)
        # a leading marker keeps with the first unit
        plan = rl.plan_pages(units, markers=[dict(mk[0], after=None)])
        (page, m), = markers(plan)
        self.assertEqual(page, 1)
        self.assertLessEqual(m["y"] + m["h"], plan["pages"][0]["placements"][0]["y"])


class ComposedChartTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.systems = make_systems(self.root / "strips", [(0, 4), (5, 9), (20, 24), (25, 29)])

    def tearDown(self):
        self.td.cleanup()

    def test_complete_chart_renders_exactly_as_before(self):
        header = {"title": "T"}
        plan0, pages0 = reflow_pipeline.compose_systems(self.systems, header=header)
        plan1, pages1 = reflow_pipeline.compose_systems(self.systems, header=main._compose_header(header, {"status": "complete"}, self.systems))
        self.assertEqual(json.dumps(plan0, sort_keys=True), json.dumps(plan1, sort_keys=True))
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(pages0, pages1)))
        self.assertNotIn("incomplete", plan0)
        self.assertFalse(any("markers" in p for p in plan0["pages"]))

    def test_incomplete_chart_has_a_notice_and_a_marker_between_its_neighbours(self):
        header = {"title": "T"}
        base, _ = reflow_pipeline.compose_systems(self.systems, header=header)
        h = main._compose_header(header, incomplete((10.0, 18.6)), self.systems)
        plan, pages = reflow_pipeline.compose_systems(self.systems, header=h)
        self.assertTrue(plan["validation"]["valid"])
        self.assertEqual(plan["header"]["notice"], "미완성 악보: 영상 00:10–00:19 구간을 복구하지 못했습니다.")
        self.assertGreater(plan["header_band_px"], base["header_band_px"])  # the notice has its own room
        pls = {pl["system_id"]: pl for pl in placements(plan)}
        (page, m), = markers(plan)
        self.assertEqual(page, 1)
        self.assertEqual(m["text"], "[누락 구간 00:10–00:19]")
        self.assertGreaterEqual(m["y"], pls["sys-002"]["y"] + pls["sys-002"]["h"])
        self.assertLessEqual(m["y"] + m["h"], pls["sys-003"]["y"])
        self.assertEqual(plan["incomplete"]["markers"][0]["page"], 1)
        # the marker is drawn (a dark border in its box) and the placements are unchanged in content
        self.assertLess(int(pages[0][m["y"]:m["y"] + 4, m["x"]:m["x"] + m["w"]].min()), 100)
        self.assertEqual([p["system_id"] for p in placements(plan)], [p["system_id"] for p in placements(base)])
        # the notice band is inked under the title, above the first system
        band = pages[0][rl.MARGIN_TOP:pls["sys-001"]["y"]]
        self.assertGreater(int((band < 128).sum()), 1000)

    def test_unknown_position_gives_the_notice_only(self):
        sys = [dict(s) for s in self.systems]
        sys[1]["t_end"] = 15.0  # overlaps the interval
        plan, _ = reflow_pipeline.compose_systems(sys, header=main._compose_header({"title": "T"}, incomplete((10.0, 18.0)), sys))
        self.assertIn("notice", plan["header"])
        self.assertEqual(markers(plan), [])
        self.assertEqual(plan["incomplete"]["markers"][0]["position"], "unknown")

    def test_incomplete_export_verifies(self):
        h = main._compose_header({"title": "T"}, incomplete((10.0, 18.0), (30.0, 40.0)), self.systems)
        plan, pages = reflow_pipeline.compose_systems(self.systems, header=h)
        self.assertEqual(len(markers(plan)), 2)
        out = export_composed_pages(pages=pages, formats=["png", "pdf"], workspace=self.root / "export", logger=lambda _m: None)
        self.assertTrue(verify_composed_export(out, plan=plan, pages=pages)["verified"])


class MeasureLinesIncompleteTest(unittest.TestCase):
    def test_marker_at_a_line_break_in_measure_mode(self):
        from test_reflow_staff_size import measure_strip
        with tempfile.TemporaryDirectory() as td:
            ms = []
            for i in range(4):
                img, rec = measure_strip()
                p = Path(td) / f"m{i}.png"
                cv2.imwrite(str(p), img)
                ms.append({"id": f"sys-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(p), "issues": [],
                           "t_start": float(i * 10), "t_end": i * 10 + 4.0, "layout": "bottom_bar",
                           "strip": dict(rec, system_id=f"sys-00{i + 1}")})
            base, _ = reflow_pipeline.compose_systems(ms, header={"title": "T"}, measure_reflow=True, measure_context={})
            h = main._compose_header({"title": "T"}, incomplete((5.0, 9.0)), ms)
            plan, _ = reflow_pipeline.compose_systems(ms, header=h, measure_reflow=True, measure_context={})
        self.assertEqual(plan["measure_reflow"]["status"], "measure_lines")
        self.assertTrue(plan["validation"]["valid"])
        rec = plan["incomplete"]["markers"][0]
        line_sys = {pl["line_id"]: pl["system_ids"] for pl in placements(plan)}
        if rec["position"] == "placed":
            self.assertEqual(line_sys[rec["after"]][-1], "sys-001")
        else:
            self.assertEqual(rec["position"], "inside_line")
        self.assertEqual([pl["line_id"] for pl in placements(plan)], [pl["line_id"] for pl in placements(base)])


class ReviewExportIncompleteTest(unittest.TestCase):
    def test_review_export_keeps_the_marking(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "job-i"
            systems = make_systems(artifact / "reflow" / "strips", [(0, 4), (5, 9), (20, 24)])
            plan, pages = reflow_pipeline.compose_systems(systems, header={"title": "T"})
            out = export_composed_pages(pages=pages, formats=["png", "pdf"], workspace=artifact / "export", logger=lambda _m: None)
            reflow = {"systems": systems, "page_plan": plan, "header": {"title": "T"}, "revision": 1, "duplicate_suggestions": []}
            result = {"output_model": "clean_reflow_v1", "reflow_state": "incomplete", "reflow": reflow, "images": out["images"],
                      "pdf": out["pdf"], "coverage": incomplete((10.0, 18.0)), **main._reflow_capture_fields(reflow)}
            store = JobStore(root)
            store.create(Job(id="job-i", source_type="file", file_path=str(root / "v.mp4"), youtube_url=None,
                             options={"export": {"formats": ["png", "pdf"]}}, artifact_dir=str(artifact),
                             status=JobStatus.DONE, result=result))
            paths = [s["strip_path"] for s in systems]
            with patch("app.main.job_store", store):
                main.review_export("job-i", JobReviewExportRequest(keep_captures=paths))
            job = store.get("job-i")
            new_plan = job.result["reflow"]["page_plan"]
            self.assertEqual(job.result["reflow_state"], "incomplete")
            self.assertIn("미완성 악보", new_plan["header"]["notice"])
            self.assertEqual([mk["text"] for _p, mk in markers(new_plan)], ["[누락 구간 00:10–00:18]"])
            self.assertEqual(job.result["reflow"]["header"], {"title": "T"})  # stored header unchanged


def write_bytes(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * n)


def fake_workspace(artifact: Path) -> None:
    """The folder a reflow job leaves: decoded frames (heavy), manifest/tracking JSON, strips,
    ROI-health samples, an interrupted staged export, a cached array."""
    for i in range(40):
        write_bytes(artifact / "reflow" / "manifest" / "frames" / f"obs_{i:04d}.png", 250_000)
    write_bytes(artifact / "reflow" / "manifest.json", 20_000)
    write_bytes(artifact / "reflow" / "tracking.json", 5_000)
    write_bytes(artifact / "reflow" / "cache" / "panorama.npy", 2_000_000)
    for i in range(3):
        write_bytes(artifact / "reflow" / "strips" / f"strip_sys-00{i + 1}.png", 300_000)
    write_bytes(artifact / "reflow" / "labels" / "label_sys-001.png", 20_000)
    write_bytes(artifact / "roi-health" / "sample_0" / "frame.png", 400_000)
    write_bytes(artifact / "export_staged_abc" / "page_0001.png", 900_000)


def folder_mb(path: Path) -> float:
    """Folder size without the job record (it grows with the job's log)."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and f.name != "job.json") / 1e6


class EndedJobCleanupTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.store = JobStore(self.root)
        self.sizes = {}

    def tearDown(self):
        self.td.cleanup()

    def run_job(self, name, outcome):
        artifact = self.root / name
        fake_workspace(artifact)
        self.store.create(Job(id=name, source_type="file", file_path=str(self.root / "v.mp4"), youtube_url=None,
                              options={}, artifact_dir=str(artifact), status=JobStatus.QUEUED, result={}))
        before = folder_mb(artifact)

        def fake_execute(job_id, payload):
            if outcome == "cancel":
                raise OperationCancelled()
            if outcome == "done":
                main.job_store.set_state(job_id, JobStatus.DONE, 1.0, "done", "export finished", result={"reflow_state": "done"},
                                         error_code=None)
            elif outcome == "layout_conflict":
                main.job_store.set_state(job_id, JobStatus.ERROR, 1.0, "layout_conflict", "x",
                                         result={"reflow_state": "layout_conflict", "reflow": {"systems": []}},
                                         error_code=main.LAYOUT_CONFLICT_CODE)
            else:
                main.job_store.set_state(job_id, JobStatus.ERROR, 1.0, "unsupported_layout", "x",
                                         result={"reflow_state": "unsupported_layout"}, error_code="UNSUPPORTED_LAYOUT")

        with patch("app.main.job_store", self.store), patch("app.main._execute_job", side_effect=fake_execute):
            main._run_job(name, None)  # payload unused by the patched _execute_job
        after = folder_mb(artifact)
        self.sizes[name] = (round(before, 2), round(after, 2))
        return artifact, before, after

    def test_success_failure_and_cancel_sizes(self):
        art, before, after = self.run_job("done", "done")
        self.assertEqual(self.store.get("done").status, JobStatus.DONE)
        self.assertAlmostEqual(before, after, places=6)  # a done job is not touched here
        self.assertNotIn("workspace_cleanup", self.store.get("done").result)

        art, before, after = self.run_job("failed", "unsupported")
        job = self.store.get("failed")
        self.assertEqual((job.status, job.error_code), (JobStatus.ERROR, "UNSUPPORTED_LAYOUT"))
        self.assertLess(after, 2.0)
        self.assertFalse((art / "reflow" / "manifest" / "frames").exists())
        self.assertEqual(len(list((art / "reflow" / "strips").glob("*.png"))), 3)  # listed by the result, kept
        self.assertFalse((art / "export_staged_abc").exists())
        self.assertFalse((art / "reflow" / "cache" / "panorama.npy").exists())
        for kept in ("reflow/manifest.json", "reflow/tracking.json", "roi-health/sample_0/frame.png", "job.json"):
            self.assertTrue((art / kept).is_file(), kept)
        self.assertEqual(job.result["reflow_state"], "unsupported_layout")
        self.assertGreater(job.result["workspace_cleanup"]["bytes_before"], job.result["workspace_cleanup"]["bytes_after"])

        art, before, after = self.run_job("cancelled", "cancel")
        self.assertEqual(self.store.get("cancelled").status, JobStatus.CANCELLED)
        self.assertLess(after, 2.0)
        self.assertFalse((art / "reflow" / "manifest" / "frames").exists())
        self.assertTrue((art / "reflow" / "manifest.json").is_file())

        art, before, after = self.run_job("conflict", "layout_conflict")
        job = self.store.get("conflict")
        self.assertTrue(main._layout_conflict_pending(job))  # still reviewable
        self.assertFalse((art / "reflow" / "manifest" / "frames").exists())
        self.assertEqual(len(list((art / "reflow" / "strips").glob("*.png"))), 3)
        self.assertTrue((art / "reflow" / "labels" / "label_sys-001.png").is_file())
        self.assertLess(after, 2.0)
        print(f"\n[workspace sizes MB before -> after] {self.sizes}")


if __name__ == "__main__":
    unittest.main()
