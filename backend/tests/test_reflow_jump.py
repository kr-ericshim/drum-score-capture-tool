"""Jump-view seam registration (reflow_jump, JUMP_PLAN milestone 1).

A synthetic continuous drum score is windowed the way a jump-view video shows
it: a static display for a few seconds, then the view jumps right and the next
display overlaps the previous one. Manifests and episodes come from the real
observation helpers and tracker (reflow_fixture.build, system_tracking).
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.pipeline import reflow_jump as rj
from app.pipeline import system_tracking as stk
from drum_score_fixture import Degrade, degrade, groove_notes, render, strip_spec
from reflow_fixture import STEP, build, loader, strip

VIEW_W = 1000
JUMP = 700
DWELL = 2.5


def long_score(bars: int = 14, *, seed: int = 5, repeat: bool = False) -> np.ndarray:
    """One long system. Each bar gets its own figure (a real chart varies from bar to
    bar); ``repeat`` repeats the first bar's figure in every bar (periodic content)."""
    spec = strip_spec(width=bars * 320 + 120, bars_per_system=bars, show_bar_numbers=False)
    if repeat:
        return render(groove_notes(spec, seed=seed, repeat_bar=True))
    rng = random.Random(seed)
    lines_pool = [-1.0, -0.5, 0.5, 1.5, 2.5, 3.5, 4.0]
    for bar in range(bars):
        for slot in range(spec.slots_per_bar):
            if rng.random() < 0.8:
                spec.notes[(0, bar, slot)] = sorted(rng.sample(lines_pool, rng.choice([1, 1, 2, 3])))
    return render(spec)


def view(score: np.ndarray, off: int, *, cursor: Optional[float], panel: int = 0, label: str = "", seed: int = 0) -> np.ndarray:
    img = score[:, off: off + VIEW_W].copy()
    if cursor is not None:  # a colored playback line
        x = int(cursor * (VIEW_W - 1))
        cv2.line(img, (x, 10), (x, img.shape[0] - 10), (40, 120, 230), 3)
    if panel:
        # translucent panel at the left edge with a fixed clef and a measure label
        img[:, :panel] = (0.35 * img[:, :panel] + 0.65 * 245).astype(np.uint8)
        cv2.rectangle(img, (14, 70), (18, 112), (60, 60, 60), -1)
        cv2.rectangle(img, (24, 70), (28, 112), (60, 60, 60), -1)
        cv2.putText(img, label, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1, cv2.LINE_AA)
    return degrade(img, Degrade(blur=0.6, jpeg_quality=90, noise=1.0, seed=seed))


def jump_frames(score: np.ndarray, offsets: List[int], *, panel: int = 0, eased: bool = False) -> List[Tuple[float, np.ndarray]]:
    frames: List[Tuple[float, np.ndarray]] = []
    t = 0.0
    n = int(round(DWELL / STEP))
    for k, off in enumerate(offsets):
        if eased and k > 0:
            # a 2-frame eased jump: one sample caught half-way
            mid = (offsets[k - 1] + off) // 2
            frames.append((t, view(score, mid, cursor=None, panel=panel, label=f"#{k}", seed=900 + k)))
            t += STEP
        for i in range(n):
            frames.append((t, view(score, off, cursor=(i + 0.5) / n, panel=panel, label=f"#{k + 1}", seed=k * 100 + i)))
            t += STEP
    return frames


def analyse(frames, **kw):
    manifest, images = build(frames)
    load = loader(images)
    tracking = stk.build_episodes(manifest, load)
    return rj.analyse_jumps(tracking, manifest, load, **kw), tracking


class JumpViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.score = long_score()
        w = cls.score.shape[1]
        cls.offsets = list(range(0, w - VIEW_W + 1, JUMP))

    def assert_jump_run(self, res, *, n_displays: int) -> None:
        seams = res["seams"]
        self.assertEqual(len(seams), n_displays - 1, [s["id"] for s in seams])
        for s in seams:
            self.assertTrue(s["verified"], s)
            self.assertEqual(s["kind"], "jump", s)
            self.assertLessEqual(abs(s["dx"] - JUMP), 1, s)
        self.assertEqual(len(res["runs"]), 1)
        run = res["runs"][0]
        self.assertEqual(run["kind"], "jump_view")
        self.assertEqual(run["verified_seams"], n_displays - 1)
        self.assertEqual([len(c) for c in run["chains"]], [n_displays])
        self.assertTrue(any(iv["kind"] == "jump_view" for iv in res["intervals"]))

    def test_jumps_with_a_colored_cursor_register_exactly(self) -> None:
        res, _t = analyse(jump_frames(self.score, self.offsets))
        self.assertTrue(res["gate"]["attempt"], res["gate"])
        self.assertEqual(res["slots"][0]["panel"]["right"], 0, res["slots"][0]["panel"])
        self.assert_jump_run(res, n_displays=len(self.offsets))

    def test_translucent_left_panel_is_detected_and_excluded(self) -> None:
        res, _t = analyse(jump_frames(self.score, self.offsets, panel=60))
        panel = res["slots"][0]["panel"]
        self.assertGreaterEqual(panel["right"], 28, panel)  # at least the fixed clef bars
        self.assertLessEqual(panel["right"], 60 + 30, panel)
        self.assert_jump_run(res, n_displays=len(self.offsets))
        for s in res["seams"]:
            self.assertGreaterEqual(s["overlap_px"], VIEW_W - JUMP - panel["right"] - 2)

    def test_eased_two_frame_jump_skips_the_mid_jump_frame(self) -> None:
        res, tracking = analyse(jump_frames(self.score, self.offsets, eased=True))
        self.assert_jump_run(res, n_displays=len(self.offsets))
        confirmed = [e for e in tracking["episodes"] if e["confirmed"]]
        self.assertEqual(len(confirmed), len(self.offsets))

    def test_periodic_content_leaves_the_seam_unverified(self) -> None:
        score = long_score(repeat=True)
        res, _t = analyse(jump_frames(score, self.offsets))
        self.assertTrue(res["seams"])
        for s in res["seams"]:
            self.assertFalse(s["verified"], s)
            self.assertIn("ambiguous_offset", s["reasons"])
            self.assertEqual(s["kind"], "unverified")
        self.assertEqual(res["runs"], [])
        self.assertFalse(any(iv["kind"] == "jump_view" for iv in res["intervals"]))

    def test_smooth_scroll_is_not_jump_view(self) -> None:
        w = self.score.shape[1]
        frames = []
        for i, off in enumerate(range(0, w - VIEW_W, 45)):
            frames.append((i * STEP, view(self.score, off, cursor=0.3, seed=i)))
        res, tracking = analyse(frames)
        self.assertEqual(res["runs"], [])
        self.assertFalse(any(iv["kind"] == "jump_view" for iv in res["intervals"]))
        if any(iv.get("kind") == "horizontal_scroll" for iv in tracking.get("layout_intervals", [])):
            self.assertTrue(any(iv["kind"] == "smooth_scroll" for iv in res["intervals"]), res["intervals"])

    def test_page_switch_video_is_untouched(self) -> None:
        frames: List[Tuple[float, np.ndarray]] = []
        t = 0.0
        for k, seed in enumerate((11, 12, 13, 14)):
            spec = strip(seed)
            for i in range(10):
                img = render(spec)
                frames.append((t, degrade(img, Degrade(blur=0.6, jpeg_quality=90, noise=1.0, seed=k * 50 + i))))
                t += STEP
        res, tracking = analyse(frames)
        self.assertFalse(any(iv.get("kind") == "horizontal_scroll" for iv in tracking.get("layout_intervals", [])))
        self.assertFalse(res["gate"]["attempt"], res["gate"])
        self.assertEqual(res["seams"], [])
        self.assertEqual(res["runs"], [])
        self.assertTrue(all(iv["kind"] == "not_horizontal" for iv in res["intervals"]), res["intervals"])

    def test_result_is_written_as_json_with_the_frozen_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "reflow" / "jump.json"
            res, _t = analyse(jump_frames(self.score, self.offsets[:4]), out_path=out)
            data = json.loads(out.read_text())
        self.assertEqual(data["config_hash"], rj.config_hash())
        self.assertEqual(data["config"], rj.CONFIG)
        self.assertEqual(data["version"], rj.JUMP_VERSION)
        self.assertEqual(data["summary"]["seams"], len(res["seams"]))
        self.assertFalse(any(k.startswith("_") for k in data))


class RegistrationUnitTests(unittest.TestCase):
    def _display(self, img: np.ndarray, gap: float = 14.0):
        return {"gap": gap, "rows": (0, img.shape[0]), "width": img.shape[1], "features": rj.features(img, gap),
                "covered": np.zeros(img.shape[1], dtype=bool)}

    def test_register_pair_finds_the_offset_and_rejects_blank_overlap(self) -> None:
        score = long_score()
        a = self._display(score[:, 0:VIEW_W])
        b = self._display(score[:, 650:650 + VIEW_W])
        reg = rj.register_pair(a, b, 0, rj.CONFIG)
        self.assertEqual(reg["dx"], 650)
        ok, reasons = rj.verify_seam(reg, 14.0, rj.CONFIG)
        self.assertTrue(ok, (reg, reasons))
        blank = np.full_like(score[:, :VIEW_W], 255)
        reg2 = rj.register_pair(self._display(blank), self._display(blank), 0, rj.CONFIG)
        ok2, reasons2 = rj.verify_seam(reg2, 14.0, rj.CONFIG)
        self.assertFalse(ok2)
        self.assertIn("no_candidate", reasons2)

    def test_config_hash_is_stable(self) -> None:
        self.assertEqual(rj.config_hash(), rj.config_hash(dict(rj.CONFIG)))
        changed = dict(rj.CONFIG, resid_max=rj.CONFIG["resid_max"] + 1)
        self.assertNotEqual(rj.config_hash(), rj.config_hash(changed))


def partly_periodic_score(bars: int = 24, periodic: Tuple[int, int] = (9, 15), seed: int = 5) -> np.ndarray:
    """Bars vary from bar to bar except a run of identical bars (a repeated groove)."""
    spec = strip_spec(width=bars * 320 + 120, bars_per_system=bars, show_bar_numbers=False)
    rng = random.Random(seed)
    lines_pool = [-1.0, -0.5, 0.5, 1.5, 2.5, 3.5, 4.0]
    figure = None
    for bar in range(bars):
        if periodic[0] <= bar < periodic[1] and figure is not None:
            for slot, notes in figure.items():
                spec.notes[(0, bar, slot)] = list(notes)
            continue
        cur = {}
        for slot in range(spec.slots_per_bar):
            if rng.random() < 0.8:
                cur[slot] = sorted(rng.sample(lines_pool, rng.choice([1, 1, 2, 3])))
                spec.notes[(0, bar, slot)] = cur[slot]
        if bar == periodic[0]:
            figure = cur
    return render(spec)


class SeamResolutionTests(unittest.TestCase):
    """Milestone 2: ambiguous seams on a repeated groove, resolved from the slot's own jumps."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.score = partly_periodic_score()
        w = cls.score.shape[1]
        cls.offsets = list(range(0, w - VIEW_W + 1, JUMP))
        cls.res, cls.tracking = analyse(jump_frames(cls.score, cls.offsets), keep_composites=True)

    def test_ambiguous_seams_resolve_to_the_typical_jump(self) -> None:
        seams = self.res["seams"]
        self.assertEqual(len(seams), len(self.offsets) - 1)
        amb = [s for s in seams if not s["verified"]]
        self.assertTrue(amb, "the periodic bars should leave some seams ambiguous")
        for s in amb:
            self.assertIn("ambiguous_offset", s["reasons"])
            self.assertEqual(s["status"], "resolved", s.get("resolution"))
            res = s["resolution"]
            self.assertLessEqual(abs(res["dx"] - JUMP), 1, res)
            self.assertIn("typical_jump", res["evidence"])
        ev = self.res["slots"][0]["evidence"]
        self.assertTrue(ev["typical"]["usable"], ev)
        self.assertLessEqual(abs(ev["typical"]["median_dx"] - JUMP), 1)
        run = self.res["runs"][0]
        self.assertEqual(len(run["panorama_chains"]), 1, run["panorama_chains"])
        self.assertEqual(run["panorama_chains"][0]["displays"], [e["id"] for e in self.tracking["episodes"] if e["confirmed"]])

    def test_panorama_has_every_column_once_and_matches_the_score(self) -> None:
        run = self.res["runs"][0]
        chain = run["panorama_chains"][0]["displays"]
        seam_of = {(s["a"], s["b"]): s for s in self.res["seams"]}
        pano, info = rj.build_panorama(chain, seam_of, self.res["_composites"], self.res["_covered"], 0, 14.0, rj.CONFIG)
        self.assertTrue(info["owner_map_complete"])
        self.assertEqual(pano.shape[1], self.offsets[-1] + VIEW_W)
        spans = [o["pano_cols"] for o in info["owners"]]
        self.assertEqual(spans[0][0], 0)
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            self.assertEqual(a1, b0)
        # the stitched strip shows the score (registration exact, cursor removed by the composite)
        # (each display is a degraded video frame: compare against one display's own difference)
        ref = cv2.cvtColor(self.score[:, :pano.shape[1]], cv2.COLOR_BGR2GRAY).astype(np.int16)
        got = cv2.cvtColor(pano, cv2.COLOR_BGR2GRAY).astype(np.int16)
        first = cv2.cvtColor(self.res["_composites"][chain[0]], cv2.COLOR_BGR2GRAY).astype(np.int16)
        base = float(np.abs(ref[:, :VIEW_W] - first).mean())
        self.assertLess(float(np.abs(ref - got).mean()), 1.25 * base + 1.0)
        cols = np.abs(ref - got).mean(axis=0)
        self.assertLess(float(np.percentile(cols, 99.5)), 4 * float(np.percentile(np.abs(ref[:, :VIEW_W] - first).mean(axis=0), 99.5)) + 5)

    def test_jump_systems_are_strips_with_a_jump_section(self) -> None:
        manifest, _images = build(jump_frames(self.score, self.offsets))
        with tempfile.TemporaryDirectory() as td:
            built = rj.build_jump_systems(self.res, self.tracking, manifest, Path(td), composites=self.res["_composites"],
                                          covered=self.res["_covered"])
            self.assertTrue(built)
            for occ, rec in built:
                self.assertEqual(occ["layout"], "jump_view")
                self.assertTrue(Path(rec["path"]).is_file())
                for k in ("box_crop", "staff_y_strip", "staff_x_strip", "member_obs_ids", "uncut_pixels_sha256", "jump"):
                    self.assertIn(k, rec)
                self.assertNotIn(rj.JUMP_SEAM_UNVERIFIED, rec["issues"])
                self.assertTrue(rec["jump"]["members"])

    def test_without_enough_verified_jumps_nothing_is_resolved(self) -> None:
        ev = rj.slot_evidence([], 1000, rj.CONFIG)
        self.assertFalse(ev["typical"]["usable"])
        seam = {"reasons": ["ambiguous_offset"], "candidates": [[700, 0.5, 0, 300], [380, 0.4, 0, 620]], "a": "a", "b": "b"}
        d = {"gap": 14.0, "width": 1000}
        out = rj.resolve_seam(seam, d, d, 0, ev, rj.CONFIG, last_display=False)
        self.assertEqual(out["status"], "unverified")
        self.assertEqual(out["reason"], "no_unique_offset")
        out2 = rj.resolve_seam(dict(seam, reasons=["residual_high"]), d, d, 0, ev, rj.CONFIG, last_display=False)
        self.assertEqual(out2["reason"], "not_only_ambiguous")
        out3 = rj.resolve_seam(seam, d, d, 0, ev, rj.CONFIG, last_display=True)
        self.assertEqual(out3["reason"], "final_display")

    def test_a_contradicting_cursor_prior_keeps_the_seam_unverified(self) -> None:
        ev = {"tol_px": 30.0, "typical": {"usable": True, "median_dx": 700.0},
              "prior": {"usable": True, "tol_px": 100.0}}
        seam = {"reasons": ["ambiguous_offset"], "candidates": [[700, 0.5, 0, 300], [380, 0.4, 0, 620]], "prior_fit_dx": 380.0}
        d = {"gap": 14.0, "width": 1000}
        from unittest import mock
        with mock.patch.object(rj, "window_candidates", return_value=[]):
            out = rj.resolve_seam(seam, d, d, 0, ev, rj.CONFIG, last_display=False)
            out2 = rj.resolve_seam(seam, d, d, 0, ev, rj.CONFIG, last_display=False, numbers=lambda dx: dx == 380)
            ev_np = dict(ev, prior={"usable": False})
            out3 = rj.resolve_seam(seam, d, d, 0, ev_np, rj.CONFIG, last_display=False, numbers=lambda dx: dx == 380)
        self.assertEqual(out["status"], "unverified")
        self.assertEqual(out["reason"], "cursor_prior_contradicts")
        self.assertEqual(out2["status"], "unverified")
        # measure numbers that reject the only offset the jump size allows: a contradiction
        self.assertEqual(out3["reason"], "measure_numbers_contradict")


class UnverifiedSeamTests(unittest.TestCase):
    def test_an_unverified_seam_splits_the_chain_and_flags_both_sides(self) -> None:
        score = long_score()
        offsets = list(range(0, score.shape[1] - VIEW_W + 1, JUMP))
        res, tracking = analyse(jump_frames(score, offsets), keep_composites=True)
        run = res["runs"][0]
        mid = res["seams"][len(res["seams"]) // 2]
        mid.update(verified=False, kind="unverified", reasons=["ambiguous_offset"], status="unverified", resolution=None)
        chains = rj.panorama_chains(run, res["seams"])
        self.assertEqual(len(chains), 2)
        self.assertEqual(chains[0]["break_after"], mid["id"])
        self.assertEqual(chains[1]["break_before"], mid["id"])
        self.assertEqual(sum(len(c["displays"]) for c in chains), len(offsets))
        run["panorama_chains"] = chains
        manifest, _images = build(jump_frames(score, offsets))
        with tempfile.TemporaryDirectory() as td:
            built = rj.build_jump_systems(res, tracking, manifest, Path(td), composites=res["_composites"], covered=res["_covered"])
        flagged = [rec["system_id"] for _o, rec in built if rj.JUMP_SEAM_UNVERIFIED in rec["issues"]]
        self.assertEqual(len(flagged), 2, [(r["system_id"], r["issues"]) for _o, r in built])
        # both sides keep the displays at the seam: display a ends the first chain, display b starts the next
        owners = [o["display"] for _o, rec in built for o in rec["jump"]["owners"]]
        self.assertIn(mid["a"], owners)
        self.assertIn(mid["b"], owners)

    def test_smooth_scroll_left_over_stays_unsupported(self) -> None:
        tracking = {"episodes": [], "layout_intervals": [{"start": 0.0, "end": 30.0, "kind": "horizontal_scroll", "supported": False}]}
        jump = {"config": rj.CONFIG, "runs": []}
        self.assertEqual(len(rj.remaining_unsupported(tracking, jump)), 1)


class MemberRegionShiftTests(unittest.TestCase):
    def test_jump_members_are_shifted_by_their_display_offset(self) -> None:
        from app.pipeline import reflow_boundaries as rb
        obs_by = {"o1": {"id": "o1", "system_regions": [{"region_id": "r1", "bars": [[100, 102, 1]], "staff_x": [10, 900],
                                                          "staff_gap_px": 14.0}]}}
        rec = {"member_obs_ids": ["o1"], "jump": {"members": [{"obs_id": "o1", "region_id": "r1", "offset_x": 500}]}}
        regs = rb.member_regions(rec, None, obs_by)
        self.assertEqual(regs[0]["bars"][0][:2], [600, 602])
        self.assertEqual(regs[0]["staff_x"], [510, 1400])
        self.assertEqual(obs_by["o1"]["system_regions"][0]["bars"][0][:2], [100, 102])


class OversizeSplitTests(unittest.TestCase):
    def test_crossed_barlines_are_never_cut_in_an_oversize_span(self) -> None:
        # STRATEGY Step 2A: the jump-only OVERSIZE_SPAN forced cut is reverted; only SAFE boundaries are cuts
        from app.pipeline import reflow_units as ru
        bounds = [
            {"id": "b1", "kind": "barline", "seam_x": 900, "class": "LOCKED", "reason_codes": ["TIE_SLUR_OR_LINE_CROSSES"]},
            {"id": "b2", "kind": "barline", "seam_x": 1800, "class": "UNKNOWN", "reason_codes": ["BARLINE_REGISTRATION_DISAGREES"]},
            {"id": "b3", "kind": "barline", "seam_x": 2700, "class": "SAFE", "reason_codes": []},
        ]
        self.assertFalse(hasattr(ru, "oversize_splits"))
        self.assertEqual([ru._is_cut(b) for b in bounds], [False, False, True])
        bounds[0]["forced_cut"] = {"reason": "OVERSIZE_SPAN"}  # a record from before the revert
        self.assertFalse(ru._is_cut(bounds[0]))


if __name__ == "__main__":
    unittest.main()
