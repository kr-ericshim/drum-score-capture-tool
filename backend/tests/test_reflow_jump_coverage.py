"""Jump view: every leftover interval accounted for (STRATEGY Step 2A).

Synthetic tracking/seam records (no video): views joined over no-shift seams, secondary runs,
the coverage statuses (non_score / redundant / recovered / unresolved), the whole-job
completeness gate and the refusal of a video with no jump view.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import cv2
import numpy as np

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline import reflow_jump as rj
from app.pipeline import reflow_pipeline
from app.schemas import JobCreate

GAP = 14.0
W, H = 1000, 200
STAFF = [60.0, 74.0, 88.0, 102.0, 116.0]


def ep(eid: str, t0: float, t1: float, *, layout: str = "horizontal_scroll", confirmed: bool = True, top: float = 60.0) -> Dict[str, Any]:
    return {"id": eid, "slot_id": "slot-00", "t_start": t0, "t_end": t1, "confirmed": confirmed, "layout": layout,
            "staff_top_y": top, "staff_gap_px": GAP, "observation_ids": [f"o-{eid}"], "region_ids": ["r0"]}


def seam(a: str, b: str, kind: str, *, dx: Optional[int] = None, transition: float = 0.13, reasons: Optional[List[str]] = None,
         resolved_dx: Optional[int] = None, skipped: Optional[List[str]] = None) -> Dict[str, Any]:
    verified = kind in ("jump", "no_shift", "small_shift")
    s = {"id": f"seam-{a}-{b}", "slot_id": "slot-00", "a": a, "b": b, "kind": kind, "verified": verified, "dx": dx, "dy": 0,
         "transition_sec": transition, "reasons": reasons or [], "skipped_episodes": skipped or [],
         "status": "verified" if verified else "unverified", "resolution": None, "residual": 1.0, "ratio": 9.0}
    if resolved_dx is not None:
        s.update(status="resolved", resolution={"status": "resolved", "dx": resolved_dx, "dy": 0})
    return s


def manifest_for(episodes: List[Dict[str, Any]], extra_obs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    obs = [{"id": f"o-{e['id']}", "t_sec": e["t_start"], "crop_size": [W, H],
            "system_regions": [{"region_id": "r0", "staff_y": STAFF, "row_band": [0, 30, W, 150], "bbox": [0, 30, W, 150]}]}
           for e in episodes]
    return {"observations": obs + list(extra_obs or [])}


def jump_record(tracking: Dict[str, Any], seams: List[Dict[str, Any]], **kw: Any) -> Dict[str, Any]:
    cls = rj.classify_runs(seams, tracking, cfg=rj.CONFIG)
    for r in cls["runs"]:
        r["panorama_chains"] = rj.panorama_chains(r, seams)
    return dict({"config": rj.CONFIG, "seams": seams, "runs": cls["runs"], "slots": [{"slot_id": "slot-00", "panel": {"right": 0}}]}, **kw)


def exported_all(tracking: Dict[str, Any], jump: Dict[str, Any], *, drop_pages: tuple = (), drop_chains: tuple = ()) -> Dict[str, Any]:
    """The exported reference when every run chain was built and every confirmed page display
    was included (full width), minus ``drop_pages`` / ``drop_chains`` (excluded, not exported)."""
    run_eps = {d for r in jump["runs"] for c in r["panorama_chains"] for d in c["displays"]}
    page = {e["id"]: [0, W] for e in tracking["episodes"] if e.get("layout") != "horizontal_scroll"
            and e.get("confirmed") and e["id"] not in run_eps and e["id"] not in drop_pages}
    chains = [[ri, ci] for ri, r in enumerate(jump["runs"]) for ci in range(len(r["panorama_chains"]))
              if (ri, ci) not in drop_chains]
    return {"systems": ["s"] * (len(page) + len(chains)), "page": page, "chains": chains}


def five_display_run(t0: float = 0.0) -> List[Dict[str, Any]]:
    """Five 2.5 s displays joined by verified jumps of 700 px."""
    return [ep(f"e{k}", t0 + 2.6 * k, t0 + 2.6 * k + 2.5) for k in range(5)]


def run_seams(eps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [seam(a["id"], b["id"], "jump", dx=700) for a, b in zip(eps, eps[1:])]


def paper(ink_cols: Optional[range] = None) -> np.ndarray:
    img = np.full((H, W, 3), 245, np.uint8)
    for y in STAFF:
        cv2.line(img, (0, int(y)), (W - 1, int(y)), (40, 40, 40), 1)
    if ink_cols is not None:
        for x in ink_cols:
            cv2.ellipse(img, (x, 81), (6, 4), -20, 0, 360, (20, 20, 20), -1)
    return img


class ViewAndRunTests(unittest.TestCase):
    def test_a_no_shift_seam_joins_one_view_and_keeps_the_run_whole(self) -> None:
        # the tracker split display e2 into e2/e2b (0.4 s + 2 s): one view, no break in the run
        eps = [ep("e0", 0.0, 2.5), ep("e1", 2.6, 5.1), ep("e2", 5.2, 5.6), ep("e2b", 5.7, 7.7), ep("e3", 7.8, 10.3),
               ep("e4", 10.4, 12.9)]
        ss = [seam("e0", "e1", "jump", dx=700), seam("e1", "e2", "jump", dx=700), seam("e2", "e2b", "no_shift", dx=0),
              seam("e2b", "e3", "jump", dx=700), seam("e3", "e4", "jump", dx=700)]
        tracking = {"episodes": eps, "layout_intervals": [{"start": 0.0, "end": 13.0, "kind": "horizontal_scroll", "supported": False}]}
        jump = jump_record(tracking, ss)
        self.assertEqual(len(jump["runs"]), 1)
        run = jump["runs"][0]
        self.assertEqual((run["start"], run["end"]), (0.0, 12.9))
        self.assertEqual(run["no_shift_seam_ids"], ["seam-e2-e2b"])
        chains = run["panorama_chains"]
        self.assertEqual([c["displays"] for c in chains], [["e0", "e1", "e2", "e2b", "e3", "e4"]])
        self.assertEqual(rj.seam_offset(ss[2]), (0, 0))

    def test_resolved_seams_extend_a_run_and_make_a_secondary_run_on_the_same_staff(self) -> None:
        eps = five_display_run() + [ep("x0", 14.0, 20.0, layout="bottom_bar")] + \
            [ep(f"s{k}", 21.0 + 2.6 * k, 23.5 + 2.6 * k) for k in range(4)] + \
            [ep(f"m{k}", 32.0 + 2.6 * k, 34.5 + 2.6 * k, top=46.0) for k in range(4)]
        ss = [seam("e0", "e1", "unverified", reasons=["ambiguous_offset"], resolved_dx=700)] + run_seams(eps[1:5])
        ss += [seam("e4", "x0", "unverified", reasons=["residual_high"], transition=2.0), seam("x0", "s0", "unverified", reasons=["residual_high"]),
               seam("s0", "s1", "unverified", reasons=["ambiguous_offset"], resolved_dx=700), seam("s1", "s2", "jump", dx=700),
               seam("s2", "s3", "unverified", reasons=["ambiguous_offset"], resolved_dx=700),
               seam("s3", "m0", "unverified", reasons=["row_change"]),
               seam("m0", "m1", "jump", dx=700), seam("m1", "m2", "jump", dx=700), seam("m2", "m3", "jump", dx=700)]
        # the e-run's 3 verified jumps (e1..e4) + a resolved seam in front: extended to e0
        tracking = {"episodes": eps, "layout_intervals": []}
        runs = rj.classify_runs(ss, tracking, cfg=rj.CONFIG)["runs"]
        self.assertEqual(runs[0]["start"], 0.0)
        self.assertFalse(runs[0]["secondary"])
        self.assertIn("seam-e0-e1", runs[0]["unverified_seam_ids"])
        # s0..s3: 3 known seams (2 resolved, 1 verified) on the run's staff rows: a secondary run
        self.assertTrue(runs[1]["secondary"])
        self.assertEqual((runs[1]["start"], runs[1]["end"]), (21.0, eps[9]["t_end"]))
        # m0..m3 have 3 verified jumps of their own: a primary run (other staff rows do not matter there)
        self.assertFalse(runs[2]["secondary"])
        self.assertEqual(len(runs), 3)

    def test_a_group_on_other_staff_rows_is_not_a_secondary_run(self) -> None:
        eps = five_display_run() + [ep(f"s{k}", 14.0 + 2.6 * k, 16.5 + 2.6 * k, top=46.0) for k in range(4)]
        ss = run_seams(eps[:5]) + [seam("e4", "s0", "unverified", reasons=["row_change"]),
                                    seam("s0", "s1", "unverified", reasons=["ambiguous_offset"], resolved_dx=700),
                                    seam("s1", "s2", "jump", dx=700),
                                    seam("s2", "s3", "unverified", reasons=["ambiguous_offset"], resolved_dx=700)]
        runs = rj.classify_runs(ss, {"episodes": eps, "layout_intervals": []}, cfg=rj.CONFIG)["runs"]
        self.assertEqual(len(runs), 1)


class CoverageTests(unittest.TestCase):
    def test_a_transition_between_output_displays_is_redundant_and_the_job_complete(self) -> None:
        eps = five_display_run()
        # after the run: transition frames (unconfirmed), then a page display, then the same view again
        eps += [ep("t0", 13.0, 13.3, confirmed=False), ep("p0", 13.4, 18.0, layout="bottom_bar"), ep("p0b", 18.1, 19.0)]
        ss = run_seams(eps[:5]) + [seam("e4", "p0", "unverified", reasons=["residual_high"], transition=0.9, skipped=["t0"]),
                                    seam("p0", "p0b", "no_shift", dx=0)]
        tracking = {"episodes": eps, "layout_intervals": [
            {"start": 0.0, "end": 13.3, "kind": "horizontal_scroll", "supported": False},
            {"start": 13.4, "end": 18.0, "kind": "bottom_bar", "supported": True},
            {"start": 18.1, "end": 19.0, "kind": "horizontal_scroll", "supported": False}]}
        # a same view is accounted for on its composite like any registered display
        composites = {e["id"]: paper(range(100, 900, 60)) for e in eps}
        jump = jump_record(tracking, ss, _composites=composites, _covered={k: np.zeros(W, bool) for k in composites})
        cov = reflow_pipeline.leftover_gate(tracking, manifest_for(eps), jump, exported=exported_all(tracking, jump))
        self.assertEqual(cov["status"], "complete", cov)
        self.assertEqual(cov["unresolved"], [])
        by_start = {iv["start"]: iv for iv in cov["intervals"]}
        self.assertEqual(by_start[12.9]["status"], "redundant")
        self.assertEqual(by_start[12.9]["evidence"]["displays"][0]["rule"], "transition_frames")
        self.assertEqual(by_start[18.1]["status"], "redundant")
        self.assertEqual(by_start[18.1]["evidence"]["displays"][0]["rule"], "same_view")

    def test_a_unique_unresolved_display_makes_the_result_incomplete_with_its_times(self) -> None:
        eps = five_display_run() + [ep("u0", 20.0, 26.0)]
        ss = run_seams(eps[:5]) + [seam("e4", "u0", "unverified", reasons=["residual_high"], transition=7.1)]
        tracking = {"episodes": eps, "layout_intervals": [
            {"start": 0.0, "end": 13.0, "kind": "horizontal_scroll", "supported": False},
            {"start": 19.5, "end": 26.0, "kind": "horizontal_scroll", "supported": False}]}
        jump = jump_record(tracking, ss)
        cov = reflow_pipeline.leftover_gate(tracking, manifest_for(eps), jump, exported=exported_all(tracking, jump))
        self.assertEqual(cov["status"], "incomplete")
        self.assertEqual(cov["unresolved"], [[20.0, 26.0]])  # the unresolved display, inside the interval
        iv = cov["intervals"][-1]
        self.assertEqual(iv["status"], "unresolved")
        self.assertEqual(iv["evidence"]["displays"][0]["rule"], "no_registered_link_to_output")

    def test_an_interval_without_score_rows_is_non_score(self) -> None:
        eps = five_display_run()
        tracking = {"episodes": eps, "layout_intervals": [
            {"start": 0.0, "end": 13.0, "kind": "horizontal_scroll", "supported": False},
            {"start": 14.0, "end": 16.0, "kind": "horizontal_scroll", "supported": False}]}
        jump = jump_record(tracking, run_seams(eps))
        blank = [{"id": f"b{k}", "t_sec": 14.0 + 0.5 * k, "crop_size": [W, H], "system_regions": []} for k in range(5)]
        cov = reflow_pipeline.leftover_gate(tracking, manifest_for(eps, blank), jump, exported=exported_all(tracking, jump))
        self.assertEqual(cov["status"], "complete")
        self.assertEqual(cov["intervals"][-1]["status"], "non_score")
        self.assertEqual(cov["intervals"][-1]["evidence"]["observations"], 5)

    def _registered_tail(self, tail: np.ndarray) -> Dict[str, Any]:
        """A display after the run, registered to the run's last display by a verified small
        shift of 100 px: its last 100 columns are shown by no output display."""
        eps = five_display_run() + [ep("z0", 13.0, 16.0)]
        ss = run_seams(eps[:5]) + [seam("e4", "z0", "small_shift", dx=100)]
        tracking = {"episodes": eps, "layout_intervals": [
            {"start": 0.0, "end": 16.0, "kind": "horizontal_scroll", "supported": False}]}
        composites = {e["id"]: paper(range(100, 900, 60)) for e in eps[:5]}
        composites["z0"] = tail
        jump = jump_record(tracking, ss, _composites=composites, _covered={k: np.zeros(W, bool) for k in composites})
        return rj.account_coverage(tracking, manifest_for(eps), jump, exported=exported_all(tracking, jump))

    def test_edge_notes_outside_the_output_keep_a_registered_display_unresolved(self) -> None:
        cov = self._registered_tail(paper(range(100, 1000, 60)))  # notes up to x=940: past the run's end
        self.assertEqual(cov["status"], "incomplete")
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual(d["rule"], "unique_columns_not_in_output")
        self.assertEqual(d["uncovered_columns"], [900, 1000])
        self.assertGreater(d["uncovered_ink_px"], 0)

    def test_a_registered_display_with_blank_uncovered_columns_is_redundant(self) -> None:
        cov = self._registered_tail(paper(range(100, 880, 60)))
        self.assertEqual(cov["status"], "complete", cov)
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual(d["rule"], "registered_to_exported_output")
        self.assertEqual(d["frames"][0]["x"], 2800 + 100)

    def test_a_small_dot_only_in_uncovered_columns_keeps_the_display_unresolved(self) -> None:
        # audit counterexample: a verified 100 px shift, a 13 px dot only in the last 100
        # columns; an aggregate ink allowance called it blank, per-component accounting must not
        tail = paper(range(100, 880, 60))
        cv2.circle(tail, (950, 81), 2, (20, 20, 20), -1)
        dot_px = int((tail[77:86, 900:, 0] < 100).sum())  # rows between two staff lines: the dot only
        self.assertTrue(0 < dot_px < 0.25 * GAP * GAP, dot_px)  # under the old aggregate allowance
        cov = self._registered_tail(tail)
        self.assertEqual(cov["status"], "incomplete", cov)
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual(d["rule"], "unique_columns_not_in_output")
        self.assertEqual(d["unexplained_components"], 1)
        x0, _y0, x1, _y1 = d["unexplained"][0]["bbox"]
        self.assertTrue(900 <= x0 and x1 <= 1000)

    def test_staff_fringe_remains_unresolved_but_one_pixel_speckle_is_explained(self) -> None:
        tail = paper(range(100, 880, 60))
        cv2.line(tail, (0, 63), (W - 1, 63), (40, 40, 40), 1)  # a doubled staff line: measured scaffold itself
        for x in range(0, W, 23):  # the partial edge row of the bottom line: 20 px dashes under it
            cv2.line(tail, (x, 117), (min(W - 1, x + 19), 117), (40, 40, 40), 1)
        tail[130, 960] = (20, 20, 20)  # one-pixel speckle
        cov = self._registered_tail(tail)
        self.assertEqual(cov["status"], "incomplete", cov)
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        # Proximity to measured staff is not evidence that the dashed fringe is scaffold.
        self.assertEqual(d["unexplained_components"], 5)
        self.assertTrue(all(c["bbox"][1:4:2] == [117, 118] for c in d["unexplained"]))
        self.assertGreaterEqual(d["explained_components"].get("speckle", 0), 1)
        # provenance: the measured line rows of every staff row
        self.assertEqual(len(d["staff_line_rows"]), 5)
        self.assertIn(63, d["staff_line_rows"][0])
        self.assertIn(60, d["staff_line_rows"][0])
        self.assertEqual(d["staff_line_rows"][4], [116])

    def test_an_isolated_stroke_near_a_staff_line_outside_the_output_is_unresolved(self) -> None:
        # Codex H2(b) counterexample: a 34x2 neutral stroke at x=930..963, y=119..120, three
        # pixels below the bottom staff line (y=116), wholly outside the exported columns
        tail = paper(range(100, 880, 60))
        tail[119:121, 930:964] = (40, 40, 40)
        ink, _removed = rj.coverage_ink(tail, GAP, STAFF, rj.CONFIG["ink_level"], rj.COVERAGE_CONFIG)
        self.assertEqual(int(ink[119:121, 930:964].sum()), 68)  # not scaffold
        cov = self._registered_tail(tail)
        self.assertEqual(cov["status"], "incomplete", cov)
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual(d["rule"], "unique_columns_not_in_output")
        self.assertEqual(d["unexplained_components"], 1, d)
        self.assertEqual(d["unexplained"][0]["bbox"], [930, 119, 964, 121])
        self.assertEqual(d["uncovered_ink_px"], 68)
        self.assertNotIn("staff_line_remnant", d["explained_components"])
        # the same stroke inside the staff-line band (2 px below the line, not touching it) is
        # not scaffold either: proximity is no evidence
        tail2 = paper(range(100, 880, 60))
        tail2[118:119, 930:964] = (40, 40, 40)
        cov2 = self._registered_tail(tail2)
        self.assertEqual(cov2["status"], "incomplete", cov2)
        self.assertEqual(cov2["intervals"][-1]["evidence"]["displays"][0]["unexplained"][0]["bbox"], [930, 118, 964, 119])

    def _excluded_page_case(self, *, drop_pages: tuple = (), drop_chains: tuple = (), h0: Optional[np.ndarray] = None,
                            page_span: Optional[List[int]] = None) -> Dict[str, Any]:
        """A run, then a confirmed 1.0 s page display p0, then a horizontal display h0 that is the
        same view as p0 (verified no-shift seam). ``page_span``: the columns p0's exported strip
        shows (default the full width)."""
        eps = five_display_run() + [ep("p0", 13.0, 14.0, layout="bottom_bar"), ep("h0", 14.1, 17.0)]
        ss = run_seams(eps[:5]) + [seam("e4", "p0", "unverified", reasons=["residual_high"], transition=0.1),
                                    seam("p0", "h0", "no_shift", dx=0)]
        tracking = {"episodes": eps, "layout_intervals": [
            {"start": 0.0, "end": 12.9, "kind": "horizontal_scroll", "supported": False},
            {"start": 13.0, "end": 14.0, "kind": "bottom_bar", "supported": True},
            {"start": 14.1, "end": 17.0, "kind": "horizontal_scroll", "supported": False}]}
        composites = {e["id"]: paper(range(100, 900, 60)) for e in eps}
        if h0 is not None:
            composites["h0"] = h0
        jump = jump_record(tracking, ss, _composites=composites, _covered={k: np.zeros(W, bool) for k in composites})
        exported = exported_all(tracking, jump, drop_pages=drop_pages, drop_chains=drop_chains)
        if page_span is not None and "p0" in exported["page"]:
            exported["page"]["p0"] = list(page_span)
        return reflow_pipeline.leftover_gate(tracking, manifest_for(eps), jump, exported=exported)

    def test_the_same_view_as_an_exported_page_display_is_redundant(self) -> None:
        cov = self._excluded_page_case()
        self.assertEqual(cov["status"], "complete", cov)
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual((d["rule"], d["as"], d["as_exported"]), ("same_view", "p0", True))

    def test_the_same_view_as_an_excluded_page_display_is_unresolved(self) -> None:
        # audit counterexample: p0 (1.0 s) is dropped by the occurrence gate, so neither p0 nor
        # h0 is in the chart: h0 must not be certified redundant through p0
        cov = self._excluded_page_case(drop_pages=("p0",))
        self.assertEqual(cov["status"], "incomplete", cov)
        self.assertEqual(cov["unresolved"], [[14.1, 17.0]])
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual(d["status"], "unresolved")
        self.assertEqual(cov["reference"]["page_displays"], 0)

    def test_the_same_view_outside_the_exported_crop_of_its_neighbour_is_unresolved(self) -> None:
        # Codex G3(c) counterexample: p0's strip exports x=52..1000; h0 (verified no-shift seam to
        # p0) shows a dot at x=30. The no-shift registration must not certify h0 by itself.
        h0 = paper(range(100, 900, 60))
        cv2.circle(h0, (30, 81), 2, (20, 20, 20), -1)
        cov = self._excluded_page_case(h0=h0, page_span=[52, 1000])
        self.assertEqual(cov["status"], "incomplete", cov)
        self.assertEqual(cov["unresolved"], [[14.1, 17.0]])
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual(d["rule"], "unique_columns_not_in_output")
        self.assertEqual(d["uncovered_columns"], [0, 52])
        self.assertEqual(d["unexplained_components"], 1)
        self.assertEqual(d["same_view"]["as"], "p0")
        # the same leftover columns blank: redundant (the exported span covers everything inked)
        cov2 = self._excluded_page_case(h0=paper(range(100, 900, 60)), page_span=[52, 1000])
        self.assertEqual(cov2["status"], "complete", cov2)
        self.assertEqual(cov2["intervals"][-1]["evidence"]["displays"][0]["rule"], "same_view")

    def test_the_same_view_through_a_non_output_display_checks_the_exported_span(self) -> None:
        # no-shift link h0 -> h1, h1 -> page p0 (exports x=52..1000): h0's dot at x=30 is still
        # outside every exported column, whatever h1's own status
        eps = five_display_run() + [ep("p0", 13.0, 14.0, layout="bottom_bar"), ep("h1", 14.1, 15.0), ep("h0", 15.1, 17.0)]
        ss = run_seams(eps[:5]) + [seam("e4", "p0", "unverified", reasons=["residual_high"], transition=0.1),
                                    seam("p0", "h1", "no_shift", dx=0), seam("h1", "h0", "no_shift", dx=0)]
        tracking = {"episodes": eps, "layout_intervals": [
            {"start": 0.0, "end": 12.9, "kind": "horizontal_scroll", "supported": False},
            {"start": 13.0, "end": 14.0, "kind": "bottom_bar", "supported": True},
            {"start": 14.1, "end": 17.0, "kind": "horizontal_scroll", "supported": False}]}
        composites = {e["id"]: paper(range(100, 900, 60)) for e in eps}
        cv2.circle(composites["h0"], (30, 81), 2, (20, 20, 20), -1)
        jump = jump_record(tracking, ss, _composites=composites, _covered={k: np.zeros(W, bool) for k in composites})
        exported = exported_all(tracking, jump)
        exported["page"]["p0"] = [52, 1000]
        cov = reflow_pipeline.leftover_gate(tracking, manifest_for(eps), jump, exported=exported)
        self.assertEqual(cov["status"], "incomplete", cov)
        by_ep = {d["episode"]: d for d in cov["intervals"][-1]["evidence"]["displays"]}
        self.assertEqual(by_ep["h1"]["status"], "redundant")
        self.assertEqual(by_ep["h0"]["status"], "unresolved")
        self.assertEqual(by_ep["h0"]["frames"][0]["via"], "p0")

    def test_a_dot_on_a_staff_row_outside_the_output_is_not_removed_with_the_staff(self) -> None:
        # Codex G3(b) counterexample: the 100 px tail-shift fixture, a radius-2 dot centred on the
        # top staff row (y=60) at x=950, wholly outside the exported columns
        tail = paper(range(100, 880, 60))
        cv2.circle(tail, (950, 60), 2, (20, 20, 20), -1)
        cov = self._registered_tail(tail)
        self.assertEqual(cov["status"], "incomplete", cov)
        d = cov["intervals"][-1]["evidence"]["displays"][0]
        self.assertEqual(d["rule"], "unique_columns_not_in_output")
        self.assertEqual(d["unexplained_components"], 1, d)
        x0, y0, x1, y1 = d["unexplained"][0]["bbox"]
        self.assertTrue(945 <= x0 and x1 <= 956 and y0 <= 60 < y1, d["unexplained"])
        # the staff lines themselves (scaffold) still explain nothing away: blank tail stays complete
        self.assertEqual(self._registered_tail(paper(range(100, 880, 60)))["status"], "complete")

    def test_coverage_ink_keeps_symbols_crossing_staff_lines_and_drops_the_lines(self) -> None:
        img = paper()
        cv2.line(img, (500, 50), (500, 120), (20, 20, 20), 1)  # a stem through all five lines
        cv2.circle(img, (700, 88), 2, (20, 20, 20), -1)  # a dot on the middle line
        ink, removed = rj.coverage_ink(img, GAP, STAFF, rj.CONFIG["ink_level"], rj.COVERAGE_CONFIG)
        self.assertGreater(removed, 4 * W)
        for y in STAFF:
            self.assertFalse(ink[int(y), 100:400].any())  # bare staff line: scaffold
            self.assertTrue(ink[int(y), 500])  # the stem's pixel on the line is kept
        self.assertTrue(ink[88, 700])
        self.assertTrue(ink[86:91, 700].all())

    def test_a_run_whose_strips_were_not_built_is_not_output(self) -> None:
        cov = self._excluded_page_case(drop_chains=((0, 0),))
        self.assertEqual(cov["status"], "incomplete", cov)
        self.assertEqual(cov["reference"]["runs_not_exported"], [0])
        first = cov["intervals"][0]
        self.assertEqual((first["start"], first["status"]), (0.0, "unresolved"))

    def test_exported_reference_counts_only_included_systems_with_written_strips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ok = Path(td) / "a.png"
            ok.write_bytes(b"x")
            systems = [
                {"id": "sys-001", "included": True, "layout": "bottom_bar", "episode_ids": ["p0"],
                 "observations": [{"obs_id": "o", "region_id": "r0", "episode_id": "p0"}]},
                {"id": "sys-002", "included": False, "layout": "bottom_bar", "episode_ids": ["p1"],
                 "observations": [{"obs_id": "o", "region_id": "r0", "episode_id": "p1"}]},
                {"id": "sys-003", "included": True, "layout": "bottom_bar", "episode_ids": ["p2"],
                 "observations": [{"obs_id": "o", "region_id": "r0", "episode_id": "p2"}]},
                {"id": "jmp-01-001", "included": True, "layout": "jump_view", "episode_ids": ["e0"],
                 "jump": {"run": 0, "chain": 1, "chunk": 0}},
            ]
            strips = {"sys-001": {"path": str(ok), "box_crop": [12, 30, 980, 150]},
                      "sys-002": {"path": str(ok), "box_crop": [0, 30, 1000, 150]},
                      "sys-003": {"path": str(Path(td) / "missing.png"), "box_crop": [0, 30, 1000, 150]},
                      "jmp-01-001": {"path": str(ok)}}
            ref = rj.exported_reference(systems, strips)
        self.assertEqual(ref["page"], {"p0": [12, 980]})
        self.assertEqual(ref["chains"], [[0, 1]])
        self.assertEqual(ref["systems"], ["sys-001", "jmp-01-001"])


class GateTests(unittest.TestCase):
    def test_all_horizontal_scroll_without_a_jump_view_is_refused(self) -> None:
        tracking = {"episodes": [], "layout_intervals": [{"start": 0.0, "end": 30.0, "kind": "horizontal_scroll", "supported": False}]}
        for jump in (None, {"runs": []}):
            with self.assertRaises(reflow_pipeline.UnsupportedLayoutError) as ctx:
                reflow_pipeline.leftover_gate(tracking, {"observations": []}, jump)
            self.assertEqual(ctx.exception.intervals[0]["end"], 30.0)

    def test_a_page_video_has_no_coverage_record(self) -> None:
        tracking = {"episodes": [], "layout_intervals": [{"start": 0.0, "end": 30.0, "kind": "page", "supported": True}]}
        self.assertIsNone(reflow_pipeline.leftover_gate(tracking, {"observations": []}, None))


def strip_image(label: str, width: int = 1700, gap: int = 16, top: int = 60, height: int = 220) -> np.ndarray:
    img = np.full((height, width, 3), 250, np.uint8)
    for k in range(5):
        y = top + k * gap
        cv2.line(img, (10, y), (width - 10, y), (0, 0, 0), 2)
    cv2.putText(img, label, (40, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    return img


class IncompleteJobTests(unittest.TestCase):
    """An unresolved interval: the recovered chart is exported, the result is marked incomplete."""

    def run_job(self, coverage: Optional[Dict[str, Any]]):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "v.mp4"
            video.write_bytes(b"0")
            store = JobStore(root)
            ws = root / "job-c" / "reflow"
            (ws / "strips").mkdir(parents=True)
            systems = []
            for i in range(2):
                p = ws / "strips" / f"strip_jmp-01-00{i + 1}.png"
                cv2.imwrite(str(p), strip_image(f"J{i + 1}"))
                systems.append({"id": f"jmp-01-00{i + 1}", "index": i + 1, "included": True, "strip_path": str(p),
                                "t_start": i * 5.0, "t_end": i * 5.0 + 4.0, "slot_id": "slot-00", "layout": "bottom_bar",
                                "episode_ids": [f"e{i}"], "first_display": i == 0, "terminal_display": False, "issues": [],
                                "strip": {"staff_gap_px": 16.0, "size": [1700, 220]}})
            record = {"version": "t", "output_model": "clean_reflow_v1", "workspace": str(ws), "systems": systems,
                      "fragments": [], "exclusions": {}, "continuity_suggestions": [], "duplicate_suggestions": [],
                      "_manifest": None, "_load": None}
            if coverage is not None:
                record["coverage"] = coverage
            payload = JobCreate(source_type="file", file_path=str(video),
                                options={"detect": {"roi": [[0, 0], [100, 0], [100, 50], [0, 50]]}, "export": {"formats": ["png"]}})
            store.create(Job(id="job-c", source_type="file", file_path=str(video), youtube_url=None,
                             options=payload.options.model_dump(), artifact_dir=str(root / "job-c"), status=JobStatus.QUEUED))
            with patch("app.main.job_store", store), \
                    patch("app.main._analyze_roi_health", return_value={"diagnostics": []}), \
                    patch("app.pipeline.reflow_pipeline.analyse_source", return_value=record), \
                    patch("app.pipeline.reflow_pipeline.duplicate_suggestions", return_value=[]):
                main._run_job("job-c", payload)
            return store.get("job-c")

    def test_unresolved_interval_exports_the_recovered_work_marked_incomplete(self) -> None:
        cov = {"status": "incomplete", "unresolved": [[133.0, 151.8]],
               "intervals": [{"start": 133.0, "end": 151.8, "kind": "horizontal_unclassified", "status": "unresolved", "evidence": {}}]}
        job = self.run_job(cov)
        self.assertEqual(job.result["reflow_state"], "incomplete")
        self.assertEqual(job.result["coverage"]["unresolved"], [[133.0, 151.8]])
        self.assertTrue(job.result["images"])
        self.assertEqual(job.result["reflow"]["coverage"]["status"], "incomplete")

    def test_complete_coverage_without_ledger_is_done_but_requires_review(self) -> None:
        job = self.run_job({"status": "complete", "unresolved": [], "intervals": []})
        self.assertEqual(job.result["reflow_state"], "review_required")
        self.assertTrue(job.result["review_required"])
        reasons = {reason["code"] if isinstance(reason, dict) else reason
                   for reason in job.result["review_reasons"]}
        self.assertIn("SOURCE_CLASS_UNKNOWN", reasons)  # B/C assess delivery without the raw ledger
        self.assertNotIn("LEDGER_UNASSESSED", reasons)
        self.assertEqual(job.result["reflow"]["ledger_summary"]["status"], "pass")
        self.assertEqual(job.result["coverage"]["status"], "complete")
        self.assertEqual(job.result["coverage"]["unresolved"], [])
        self.assertEqual(job.result["reflow"]["coverage"]["status"], "complete")
        self.assertTrue(job.result["images"])
        self.assertEqual(job.status, JobStatus.DONE)


if __name__ == "__main__":
    unittest.main()
