"""Output-line provenance, coordinate mapping and export hooks."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_reflow_review_export as fixtures
from app import main
from app.pipeline.reflow_line_review import build_line_review, load_line_review
from app.schemas import JobReviewExportRequest


def sample():
    units = [{"id": f"u{i}", "system_id": "jump", "box": [i * 100, 0, (i + 1) * 100, 50], "measure_count": 1}
             for i in range(4)]
    placements = [{"line_id": "l1", "x": 10, "y": 20, "w": 200, "h": 50, "scale": 1,
                   "unit_ids": ["u0", "u1"], "system_ids": ["jump"]},
                  {"line_id": "l2", "x": 10, "y": 80, "w": 200, "h": 50, "scale": 1,
                   "unit_ids": ["u2", "u3"], "system_ids": ["jump"]}]
    plan = {"page_px": [800, 1000], "pages": [{"placements": placements}], "measure_reflow": {"units": units}}
    systems = [{"id": "jump", "t_start": 0, "t_end": 30, "layout": "jump_view", "included": True,
                "strip": {"size": [400, 50], "jump": {
                    "owners": [{"display": "ep0", "strip_cols": [0, 150]}, {"display": "ep1", "strip_cols": [150, 250]},
                               {"display": "ep2", "strip_cols": [250, 400]}],
                    "stitch_cuts": [{"x": 150}, {"x": 250}]}}}]
    jump = {"seams": [{"id": "s01", "a": "ep0", "b": "ep1", "verified": True, "kind": "jump", "t_a": [0, 9], "t_b": [10, 19]},
                      {"id": "s12", "a": "ep1", "b": "ep2", "verified": False, "kind": "unverified",
                       "t_a": [10, 19], "t_b": [20, 30], "resolution": {"status": "resolved", "evidence": ["forward", "low_ink_window"]}}]}
    episodes = [{"id": f"ep{i}", "t_start": a, "t_end": b} for i, (a, b) in enumerate(((0, 9), (10, 19), (20, 30)))]
    return plan, systems, jump, episodes


class LineReviewTest(unittest.TestCase):
    def test_jump_owners_and_stitches_split_across_lines(self):
        plan, systems, jump, episodes = sample()
        before = copy.deepcopy((plan, systems, jump, episodes))
        lines = build_line_review(plan, systems, jump, episodes)
        self.assertEqual((plan, systems, jump, episodes), before)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["rect"], [10, 20, 200, 50])
        self.assertEqual(lines[0]["page_size"], [800, 1000])
        self.assertEqual([l["page"] for l in lines], [1, 1])
        self.assertEqual([l["measures"] for l in lines], [2, 2])
        self.assertEqual([s["display"] for s in lines[0]["sources"]], ["ep0", "ep1"])
        self.assertEqual([s["display"] for s in lines[1]["sources"]], ["ep1", "ep2"])
        self.assertEqual([(s["t_start"], s["t_end"]) for s in lines[1]["sources"]], [(10, 19), (20, 30)])
        self.assertEqual(lines[0]["seams"], [{"id": "s01", "status": "verified", "evidence": [], "low_ink": False, "x_frac": 0.75}])
        self.assertEqual(lines[1]["seams"], [{"id": "s12", "status": "resolved", "evidence": ["forward", "low_ink_window"],
                                             "low_ink": True, "x_frac": 0.25}])
        self.assertIsNone(lines[0]["attention"])
        self.assertEqual(lines[1]["attention"], "seam_inferred")
        self.assertEqual(lines, build_line_review(plan, systems, jump))  # Seam times work without tracking.

    def test_line_switch_and_unknown_measure_count(self):
        plan, systems, _jump, _episodes = sample()
        systems[0].update(layout="line_switch", t_start=12.5, t_end=18.25)
        systems[0]["strip"].pop("jump")
        plan["measure_reflow"]["units"][0]["measure_count"] = None
        plan["pages"] = [{"placements": [p]} for p in plan["pages"][0]["placements"]]
        lines = build_line_review(plan, systems)
        self.assertEqual([l["page"] for l in lines], [1, 2])
        self.assertEqual([l["measures"] for l in lines], [None, 2])
        for line in lines:
            self.assertEqual(line["sources"], [{"system_id": "jump", "display": None, "t_start": 12.5, "t_end": 18.25}])
            self.assertEqual(line["seams"], [])

    def test_missing_jump_record_falls_back_to_system_times(self):
        plan, systems, _jump, episodes = sample()
        lines = build_line_review(plan, systems, episodes=episodes)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(line["sources"], [{"system_id": "jump", "display": None, "t_start": 0, "t_end": 30}])
            self.assertEqual(line["seams"], [])
            self.assertIsNone(line["attention"])

    def test_unverified_attention_takes_priority_and_no_shift_is_verified(self):
        plan, systems, jump, episodes = sample()
        plan["pages"][0]["placements"] = [{"line_id": "all", "x": 0, "y": 0, "w": 400, "h": 50,
                                            "unit_ids": ["u0", "u1", "u2", "u3"], "system_ids": ["jump"]}]
        jump["seams"][0].update(verified=False, kind="unverified", resolution={"status": "resolved"})
        jump["seams"][1]["resolution"]["status"] = "unverified"
        line = build_line_review(plan, systems, jump, episodes)[0]
        self.assertEqual([s["status"] for s in line["seams"]], ["resolved", "unverified"])
        self.assertEqual(line["attention"], "seam_unverified")
        jump["seams"][1].update(verified=True, kind="no_shift")
        self.assertEqual(build_line_review(plan, systems, jump, episodes)[0]["seams"][1]["status"], "verified")

    def test_half_open_line_and_owner_boundaries(self):
        plan, systems, jump, episodes = sample()
        systems[0]["strip"]["jump"]["owners"][0]["strip_cols"][1] = 200
        systems[0]["strip"]["jump"]["owners"][1]["strip_cols"][0] = 200
        systems[0]["strip"]["jump"]["stitch_cuts"][0]["x"] = 200
        lines = build_line_review(plan, systems, jump, episodes)
        self.assertEqual([s["display"] for s in lines[0]["sources"]], ["ep0"])
        self.assertEqual(lines[0]["seams"], [])
        self.assertEqual([s["id"] for s in lines[1]["seams"]], ["s01", "s12"])
        self.assertEqual(lines[1]["seams"][0]["x_frac"], 0)

    def test_audit_mapping_accounts_for_crop_scale_prefix_and_insertions(self):
        plan, systems, jump, episodes = sample()
        # u1 is cropped at native x=100 and resampled 2x. The stitch at x=150 maps
        # to R=100.5; inserting 10 columns before it moves it to L=20+110.5.
        cols = list(range(100)) + [None] * 10 + list(range(100, 200))
        plan["measure_reflow"]["audit"] = {"placements": [{"line_id": "l1", "unit_id": "u1", "x_out": 20, "width_out": 210,
                                                           "scale": 2, "pre_crop": [100, 0], "source_col_index": cols,
                                                           "resample": {"source_size": [100, 50], "output_size": [200, 100]}}]}
        plan["pages"][0]["placements"][0].update(w=300, scale=1.5)
        line = build_line_review(plan, systems, jump, episodes)[0]
        self.assertAlmostEqual(line["seams"][0]["x_frac"], 130.5 * 1.5 / 300)
        # Removed source whitespace is located by interpolating its retained neighbours.
        record = plan["measure_reflow"]["audit"]["placements"][0]
        record.update(source_col_index=[98, 99, 102, 103], width_out=4)
        self.assertAlmostEqual(build_line_review(plan, systems, jump, episodes)[0]["seams"][0]["x_frac"], 21.5 * 1.5 / 300)

    def test_placed_excluded_and_alternate_systems_follow_the_plan(self):
        plan, systems, jump, episodes = sample()
        systems[0]["included"] = False
        self.assertEqual(len(build_line_review(plan, systems, jump, episodes)), 2)
        alternate = {"id": "alt", "included": False, "layout": "line_switch", "t_start": 50, "t_end": 60, "strip": {"alternate_of": "jump"}}
        systems.append(alternate)
        plan["measure_reflow"]["units"][0]["system_id"] = "alt"
        plan["pages"][0]["placements"][0]["system_ids"] = ["alt", "jump"]
        line = build_line_review(plan, systems, jump, episodes)[0]
        self.assertEqual(line["system_ids"], ["alt", "jump"])
        self.assertEqual(line["sources"][0], {"system_id": "alt", "display": None, "t_start": 50, "t_end": 60})
        self.assertAlmostEqual(line["seams"][0]["x_frac"], 0.75)  # preceding alternate contributes half the line width

    def test_whole_system_jump_mapping_and_label_offset(self):
        plan, systems, jump, episodes = sample()
        plan.pop("measure_reflow")
        plan["pages"][0]["placements"] = [{"system_id": "jump", "x": 0, "y": 0, "w": 420, "h": 70,
                                            "scale": 1, "strip_offset_px": [20, 20]}]
        line = build_line_review(plan, systems, jump, episodes)[0]
        self.assertEqual(line["line_id"], "jump")
        self.assertIsNone(line["measures"])
        self.assertEqual(len(line["sources"]), 3)
        self.assertAlmostEqual(line["seams"][0]["x_frac"], 170 / 420)

    def test_malformed_input_returns_empty_once_without_partial_lines(self):
        bad = []
        for mutation in (lambda p, s, j, e: p["pages"][0]["placements"][1].update(w="bad"),
                         lambda p, s, j, e: p["measure_reflow"]["units"][2].update(box=[200, 0, 100, 50]),
                         lambda p, s, j, e: j["seams"][1].update(resolution={"evidence": "bad"}),
                         lambda p, s, j, e: j["seams"].pop(),
                         lambda p, s, j, e: p.update(page_px=[float("nan"), 1000])):
            values = sample()
            mutation(*values)
            bad.append(values)
        bad.extend(((None, None, None, None), ({}, [], None, None), ([], [], None, None)))
        for values in bad:
            with self.subTest(values=str(values)[:80]), self.assertLogs("app.pipeline.reflow_line_review", level="WARNING") as logs:
                self.assertEqual(build_line_review(*values), [])
            self.assertEqual(len(logs.output), 1)

    def test_loader_reads_workspace_prefers_records_and_handles_failure(self):
        plan, systems, jump, episodes = sample()
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            (workspace / "jump.json").write_text(json.dumps(jump))
            (workspace / "tracking.json").write_text(json.dumps({"episodes": episodes}))
            reflow = {"systems": systems, "workspace": td, "episodes": 3}
            expected = build_line_review(plan, systems, jump, episodes)
            self.assertEqual(load_line_review(plan, reflow), expected)
            (workspace / "tracking.json").unlink()
            self.assertEqual(load_line_review(plan, reflow), expected)  # t_a/t_b fallback
            (workspace / "jump.json").write_text("broken json")
            reflow.update(jump=jump, episodes=episodes)
            self.assertEqual(load_line_review(plan, reflow), expected)
            reflow.pop("jump")
            messages = []
            self.assertEqual(load_line_review(plan, reflow, logger=messages.append), [])
            self.assertEqual(len(messages), 1)
            self.assertEqual(load_line_review(plan, reflow, logger=lambda _m: 1 / 0), [])
            # An excluded, unplaced jump system does not require workspace files.
            systems.append({"id": "other", "t_start": 100, "t_end": 110})
            plan["pages"][0]["placements"] = [{"system_id": "other", "x": 0, "y": 0, "w": 100, "h": 50}]
            self.assertEqual(load_line_review(plan, reflow)[0]["sources"][0]["t_start"], 100)


class LineReviewExportTest(unittest.TestCase):
    def test_review_export_stores_refreshes_and_echoes_lines_without_changing_files(self):
        fixture = fixtures.ReflowReviewExportTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        paths = [s["strip_path"] for s in fixture.systems]
        with patch("app.main.job_store", fixture.store):
            main.review_export("job-r", JobReviewExportRequest(keep_captures=paths, measure_reflow=True))
            result = fixture.store.get("job-r").result
            lines = result["reflow"]["line_review"]
            plan = result["reflow"]["page_plan"]
            self.assertTrue(lines)
            self.assertEqual(len(lines), sum(len(p["placements"]) for p in plan["pages"]))
            self.assertEqual(result["review_export"]["line_review"], lines)
            self.assertEqual(lines, build_line_review(plan, result["reflow"]["systems"]))
            before = fixtures.digest(fixture.artifact / "export")
            with patch("app.pipeline.reflow_line_review.load_line_review", return_value=[]):
                main.review_export("job-r", JobReviewExportRequest(keep_captures=paths, measure_reflow=True))
            without = fixture.store.get("job-r").result
            self.assertEqual(without["reflow"]["page_plan"], plan)
            after = fixtures.digest(fixture.artifact / "export")
            # Ledger sidecars bind to the export revision, which changes on every rebuild.
            delivered = lambda files: {k: v for k, v in files.items() if k == "plan.json" or k.startswith("images/") or k.endswith(".pdf")}
            self.assertEqual(delivered(after), delivered(before))
            self.assertEqual(without["review_export"]["line_review"], [])
            main.review_export("job-r", JobReviewExportRequest(keep_captures=[paths[2]], measure_reflow=False))
        refreshed = fixture.store.get("job-r").result
        self.assertEqual(refreshed["review_export"]["line_review"], refreshed["reflow"]["line_review"])
        self.assertEqual(refreshed["reflow"]["line_review"][0]["system_ids"], ["sys-003"])
        self.assertEqual(refreshed["reflow"]["line_review"][0]["sources"][0]["t_start"], 10)

    def test_job_export_adds_lines_before_suggestions_and_failure_is_nonfatal(self):
        fixture = fixtures.ReflowJobFlowTest()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        seen = []

        def suggest(*_args, **_kwargs):
            seen.extend(fixture.store.get("job-f").result["reflow"]["line_review"])
            return []

        job = fixture.run_job(fixture.record(), suggest)
        self.assertTrue(job.result["reflow"]["line_review"])
        self.assertEqual(seen, job.result["reflow"]["line_review"])
        # Bad optional metadata cannot turn a successful export into a failed job.
        record = fixture.record()
        record["systems"][0].pop("t_start")
        job = fixture.run_job(record, lambda *_a, **_k: [])
        self.assertEqual(job.status, fixtures.JobStatus.DONE)
        self.assertEqual(job.result["reflow"]["line_review"], [])
        self.assertEqual(sum("line_review unavailable:" in msg for msg in job.log), 1)


if __name__ == "__main__":
    unittest.main()
