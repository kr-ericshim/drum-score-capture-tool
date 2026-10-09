"""Jump view: minority notation of a jump display is never dropped silently (Codex G3(a)).

A synthetic five-display jump-view video (the real observation helpers and tracker); a radius-2
dot drawn in 8 of the 32 observations of the first display is left out of that display's
median composite. The panorama strip must list it (``minority_content``), keep it as an
alternate strip and carry ``MINORITY_CONTENT_DROPPED``.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import reflow_jump as rj
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as stk
from reflow_fixture import STEP, build, loader
from test_reflow_jump import JUMP, VIEW_W, long_score, view

PER_DISPLAY = 32
DOT_OBS = range(12, 20)  # 8 consecutive observations in the middle of the first display


def frames_with_dot(score: np.ndarray, offsets: List[int], dot: Optional[Tuple[int, int]], *,
                    display: int = 0, obs: Sequence[int] = DOT_OBS) -> List[Tuple[float, np.ndarray]]:
    frames = []
    t = 0.0
    for k, off in enumerate(offsets):
        for i in range(PER_DISPLAY):
            img = view(score, off, cursor=(i + 0.5) / PER_DISPLAY, seed=k * 100 + i)
            if dot is not None and k == display and i in obs:
                cv2.circle(img, dot, 2, (20, 20, 20), -1)
            frames.append((t, img))
            t += STEP
    return frames


def blank_spot(img: np.ndarray, x_range: Tuple[int, int]) -> Tuple[int, int]:
    """A point inside the staff whose 11x7 neighbourhood is paper (no staff line, no note)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    rows = np.flatnonzero((gray < 128).mean(axis=1) > 0.5)  # staff lines
    for y in range(int(rows[0]) + 3, int(rows[-1]) - 3):
        for x in range(x_range[0], x_range[1], 4):
            if (gray[y - 3:y + 4, x - 5:x + 6] > 200).all():
                return x, y
    raise AssertionError("no blank spot")


class JumpMinorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.score = long_score(bars=12)
        cls.offsets = list(range(0, cls.score.shape[1] - VIEW_W + 1, JUMP))
        assert len(cls.offsets) == 5, cls.offsets
        cls.dot = blank_spot(cls.score[:, :VIEW_W], (150, 600))

    def run_case(self, dot: Optional[Tuple[int, int]], *, with_loader: bool = True, display: int = 0,
                 obs: Sequence[int] = DOT_OBS):
        manifest, images = build(frames_with_dot(self.score, self.offsets, dot, display=display, obs=obs))
        load = loader(images)
        tracking = stk.build_episodes(manifest, load)
        res = rj.analyse_jumps(tracking, manifest, load, keep_composites=True)
        self.assertEqual(len(res["runs"]), 1)
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        built = rj.build_jump_systems(res, tracking, manifest, Path(td.name), composites=res["_composites"],
                                      covered=res["_covered"], load=load if with_loader else None)
        return res, tracking, built

    def test_a_minority_dot_in_a_jump_display_is_kept_and_flagged(self) -> None:
        res, tracking, built = self.run_case(self.dot)
        first = res["runs"][0]["panorama_chains"][0]["displays"][0]
        # the median composite of the first display leaves the dot out (what the old code exported silently)
        x, y = self.dot
        comp = res["_composites"][first]
        self.assertFalse((cv2.cvtColor(comp, cv2.COLOR_BGR2GRAY)[y - 1:y + 2, x - 1:x + 2] < 100).any())
        flagged = [rec for _o, rec in built if rs.MINORITY_ISSUE in rec["issues"]]
        self.assertEqual(len(flagged), 1, [(r["system_id"], r["issues"]) for _o, r in built])
        rec = flagged[0]
        m = rec["minority_content"]
        self.assertTrue(m["checked"])
        self.assertEqual(len(m["events"]), 1, m["events"])
        ev = m["events"][0]
        self.assertEqual(ev["display"], first)
        bx0, by0, bx1, by1 = ev["box_crop"]
        self.assertTrue(bx0 <= x < bx1 and by0 <= y < by1, (ev["box_crop"], self.dot))
        # strip box: display crop + the display's panorama offset (first display, first chunk: 0)
        sx0, _sy0, sx1, _sy1 = ev["box_strip"]
        self.assertTrue(sx0 <= x < sx1, ev["box_strip"])
        self.assertEqual(len(ev["obs_ids"]), len(set(ev["obs_ids"])))
        self.assertGreaterEqual(len(ev["obs_ids"]), 2)
        # preserved: an alternate strip of the display's moment that shows the dot
        self.assertEqual(len(m["alternates"]), 1)
        alt = m["alternates"][0]
        self.assertEqual((alt["suffix"], alt["parent_id"], alt["display"]), ("alt1", rec["system_id"], first))
        self.assertEqual(ev["alternate"], "alt1")
        img = cv2.imread(alt["path"])
        self.assertIsNotNone(img)
        ax, ay = x - alt["box_crop"][0], y - alt["box_crop"][1]
        self.assertTrue((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[ay - 1:ay + 2, ax - 1:ax + 2] < 100).any())
        # the other strips: audited, nothing to report
        for _o, r in built:
            if r is not rec:
                self.assertTrue(r["minority_content"]["checked"])
                self.assertEqual(r["minority_content"]["events"], [])

    def test_a_clean_jump_video_has_no_minority_events(self) -> None:
        _res, _tracking, built = self.run_case(None)
        self.assertTrue(built)
        for _o, rec in built:
            self.assertTrue(rec["minority_content"]["checked"])
            self.assertEqual(rec["minority_content"]["events"], [], rec["system_id"])
            self.assertNotIn(rs.MINORITY_ISSUE, rec["issues"])
            self.assertNotIn(rj.JUMP_MINORITY_UNCHECKED, rec["issues"])

    def _edge_case(self, display: int, obs: Sequence[int]):
        res, tracking, built = self.run_case(self.dot, display=display, obs=obs)
        chain = res["runs"][0]["panorama_chains"][0]["displays"]
        self.assertEqual(len(chain), 5, chain)
        target = chain[display]
        flagged = [rec for _o, rec in built if rs.MINORITY_ISSUE in rec["issues"]]
        return target, tracking, built, flagged

    def _assert_flagged_at(self, target: str, flagged, obs_t) -> None:
        # Codex H2(a): a short run at the source start / end is content, not a hand-over
        self.assertEqual(len(flagged), 1, [r["system_id"] for r in flagged])
        m = flagged[0]["minority_content"]
        self.assertEqual(len(m["events"]), 1, m["events"])
        ev = m["events"][0]
        self.assertEqual(ev["display"], target)
        x, y = self.dot
        bx0, by0, bx1, by1 = ev["box_crop"]
        self.assertTrue(bx0 <= x < bx1 and by0 <= y < by1, (ev["box_crop"], self.dot))
        # A temporal cluster may also hold a passing cursor hypothesis. The
        # dot's real time range and original black pixels must still survive.
        self.assertIn(list(obs_t), ev["times"])
        self.assertEqual(len(m["alternates"]), 1)
        self.assertEqual(ev["alternate"], "alt1")
        rec = next(d for d in m["displays"] if d["display"] == target)
        self.assertEqual(rec["edge_transitions"], 0)
        bundle=m["alternates"][0]
        patches=[p for evidence in bundle.get("evidence_records",[bundle])
                 for p in evidence.get("evidence_patches",[])]
        witnesses=[p for p in patches if obs_t[0]-1e-6 <= p["t_sec"] <= obs_t[1]+1e-6]
        self.assertTrue(witnesses)
        kept=False
        for patch in witnesses:
            img=cv2.imread(patch["raw_path"])
            ax,ay=x-patch["box_crop"][0],y-patch["box_crop"][1]
            kept |= bool((cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)[ay-1:ay+2,ax-1:ax+2]<100).any())
        self.assertTrue(kept,"dot's original black pixels are absent from its timed evidence")

    def test_a_dot_in_the_first_two_source_observations_is_flagged(self) -> None:
        target, tracking, _built, flagged = self._edge_case(0, (0, 1))
        ep = next(e for e in tracking["episodes"] if e["id"] == target)
        self.assertEqual(ep["started_by"], "first_observation")
        self._assert_flagged_at(target, flagged, (0.0, STEP))
        rec = next(d for d in flagged[0]["minority_content"]["displays"] if d["display"] == target)
        self.assertTrue(rec["boundaries"]["first_display"])

    def test_a_dot_in_the_last_two_source_observations_is_flagged(self) -> None:
        target, tracking, _built, flagged = self._edge_case(4, (PER_DISPLAY - 2, PER_DISPLAY - 1))
        ep = next(e for e in tracking["episodes"] if e["id"] == target)
        self.assertEqual(ep["ended_by"], "end_of_source")
        t_last = (5 * PER_DISPLAY - 1) * STEP
        self._assert_flagged_at(target, flagged, (t_last - STEP, t_last))
        rec = next(d for d in flagged[0]["minority_content"]["displays"] if d["display"] == target)
        self.assertTrue(rec["boundaries"]["terminal_display"])
        self.assertFalse(rec["boundaries"]["first_display"])  # display 4 starts with a hand-over

    def test_a_short_run_at_an_established_hand_over_stays_on_record(self) -> None:
        # A hand-over timestamp is insufficient evidence to erase a visible dot.
        target, _tracking, built, flagged = self._edge_case(0, (PER_DISPLAY - 2, PER_DISPLAY - 1))
        self._assert_flagged_at(target, flagged, ((PER_DISPLAY - 2) * STEP, (PER_DISPLAY - 1) * STEP))
        recs = [d for _o, r in built for d in r["minority_content"]["displays"] if d["display"] == target]
        self.assertTrue(recs)
        self.assertEqual(recs[0]["edge_transitions"], 0)
        self.assertIsNotNone(recs[0]["boundaries"]["next"])
        self.assertTrue(recs[0]["boundaries"]["first_display"])

    def test_display_boundaries_need_the_paired_neighbour(self) -> None:
        eps = {"a": {"id": "a", "slot_id": "s", "t_start": 0.0, "t_end": 1.0, "started_by": "first_observation", "ended_by": "registration_change"},
               "b": {"id": "b", "slot_id": "s", "t_start": 1.25, "t_end": 2.0, "started_by": "registration_change", "ended_by": "slot_empty"},
               "c": {"id": "c", "slot_id": "s", "t_start": 3.0, "t_end": 4.0, "started_by": "slot_appeared", "ended_by": "content_change"},
               "x": {"id": "x", "slot_id": "t", "t_start": 4.25, "t_end": 5.0, "started_by": "content_change", "ended_by": "end_of_source"}}
        b = rj.display_boundaries
        self.assertEqual((b(eps["a"], eps)["first_display"], b(eps["a"], eps)["terminal_display"]), (True, False))
        self.assertEqual((b(eps["b"], eps)["previous"], b(eps["b"], eps)["next"]), ("a", "c"))
        # c ends with a content change, but no episode of its slot follows: not established
        self.assertEqual((b(eps["c"], eps)["first_display"], b(eps["c"], eps)["terminal_display"]), (False, True))
        # x: another slot's episode does not establish a hand-over
        self.assertEqual((b(eps["x"], eps)["first_display"], b(eps["x"], eps)["terminal_display"]), (True, True))

    def test_without_a_loader_every_strip_is_flagged_unchecked(self) -> None:
        _res, _tracking, built = self.run_case(self.dot, with_loader=False)
        for _o, rec in built:
            self.assertFalse(rec["minority_content"]["checked"])
            self.assertIn(rj.JUMP_MINORITY_UNCHECKED, rec["issues"])


if __name__ == "__main__":
    unittest.main()
