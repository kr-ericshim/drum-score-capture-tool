"""Jump view: a complete column owner map does not certify content preservation (Codex J1).

A synthetic five-display jump-view video (real observation helpers and tracker). A radius-3
neutral dot is drawn in EVERY observation of display 0 inside its overlap with display 1, at a
column display 1 owns in the panorama. The display's median composite draws it (no minority
event), the seams register, the owner map is complete - and the panorama, built from display 1
there, lacks it. The preservation ledger must find it, keep display 0 as an alternate, flag the
strip ``JUMP_OVERLAP_CONTENT_CONFLICT`` and keep coverage from reporting complete.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_jump as rj
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as stk
from reflow_fixture import build, loader
from test_reflow_jump import JUMP, VIEW_W, long_score
from test_reflow_jump_minority import PER_DISPLAY, blank_spot, frames_with_dot


def dark(img: np.ndarray, box, thr: int = 100) -> int:
    x0, y0, x1, y1 = box
    return int((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[y0:y1, x0:x1] < thr).sum())


class JumpPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.score = long_score(bars=12)
        cls.offsets = list(range(0, cls.score.shape[1] - VIEW_W + 1, JUMP))
        assert len(cls.offsets) == 5, cls.offsets
        # inside display 0's overlap with display 1 (crop x 700..1000), right of the usual cut
        cls.dot = blank_spot(cls.score[:, :VIEW_W], (900, 960))

    def run_case(self, dot, radius: int = 3):
        frames = frames_with_dot(self.score, self.offsets, None)
        if dot is not None:
            for i in range(PER_DISPLAY):  # every observation of display 0
                cv2.circle(frames[i][1], dot, radius, (20, 20, 20), -1)
        manifest, images = build(frames)
        load = loader(images)
        tracking = stk.build_episodes(manifest, load)
        res = rj.analyse_jumps(tracking, manifest, load, keep_composites=True)
        self.assertEqual(len(res["runs"]), 1)
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        built = rj.build_jump_systems(res, tracking, manifest, Path(td.name), composites=res["_composites"],
                                      covered=res["_covered"], load=load)
        systems = [o for o, _r in built]
        by_id = {r["system_id"]: r for _o, r in built}
        cov = rj.account_coverage(tracking, manifest, res, exported=rj.exported_reference(systems, by_id))
        return res, tracking, built, cov

    def test_a_persistent_overlap_dot_the_panorama_discards_is_kept_and_flagged(self) -> None:
        res, tracking, built, cov = self.run_case(self.dot)
        chain = res["runs"][0]["panorama_chains"][0]["displays"]
        self.assertEqual(len(chain), 5, chain)
        d0 = chain[0]
        x, y = self.dot
        box = (x - 4, y - 4, x + 5, y + 5)
        # the setting of the finding: the composite draws the dot, display 1 owns its columns
        self.assertGreater(dark(res["_composites"][d0], box), 15)
        seams = [s for s in res["seams"] if s["a"] in chain]
        self.assertTrue(all(rj.seam_offset(s) == (JUMP, 0) for s in seams), [rj.seam_offset(s) for s in seams])
        first = next(r for _o, r in built if r["jump"]["chunk"] == 0)
        owner = next(o for o in first["jump"]["owners"] if o["strip_cols"][0] <= x < o["strip_cols"][1])
        self.assertNotEqual(owner["display"], d0, "dot column not owned by display 1: the case does not apply")
        flagged = [r for _o, r in built if rj.JUMP_OVERLAP_CONFLICT in r["issues"]]
        self.assertEqual(len(flagged), 1, [(r["system_id"], r["issues"]) for _o, r in built])
        rec = flagged[0]
        p = rec["jump"]["preservation"]
        self.assertFalse(p["chain_content_preserved"])
        self.assertEqual(p["counts"]["unmatched"], 1, p)
        self.assertEqual(len(p["conflicts"]), 1)
        c = p["conflicts"][0]
        self.assertEqual(c["display"], d0)
        bx0, by0, bx1, by1 = c["box_crop"]
        self.assertTrue(bx0 <= x < bx1 and by0 <= y < by1, (c["box_crop"], self.dot))
        # the main strip indeed lacks the dot (the panorama is not changed) ...
        img = cv2.imread(rec["path"])
        ev = next(e for e in rec["minority_content"]["events"] if e.get("kind") == "overlap_conflict")
        sx, sy = x + ev["box_strip"][0] - ev["box_crop"][0], y + ev["box_strip"][1] - ev["box_crop"][1]
        self.assertEqual(dark(img, (sx - 2, sy - 1, sx + 3, sy + 3)), 0)  # the dot's core (a staff line may touch its rim)
        # ... and an alternate of display 0's composite shows it
        bundles = rec["minority_content"]["alternates"]
        self.assertEqual(len(bundles),1)
        self.assertEqual(bundles[0]["kind"],"uncertain_mark_bundle")
        alts = [a for a in bundles[0]["evidence_records"] if a.get("kind") == "overlap_conflict"]
        self.assertEqual(len(alts), 1)
        alt = alts[0]
        self.assertEqual((alt["display"], alt["parent_id"]), (d0, rec["system_id"]))
        aimg = cv2.imread(alt["path"])
        ax, ay = x - alt["box_crop"][0], y - alt["box_crop"][1]
        self.assertGreater(dark(aimg, (ax - 4, ay - 4, ax + 5, ay + 5)), 15)
        self.assertEqual(c["alternate"], alt["suffix"])
        # no minority event of the classic kind: the dot is in every observation
        self.assertNotIn(rs.MINORITY_ISSUE, rec["issues"])
        # coverage does not certify it
        self.assertEqual(cov["status"], "incomplete")
        iv = [i for i in cov["intervals"] if i["evidence"].get("rule") == "panorama_overlap_content_conflict"]
        self.assertEqual(len(iv), 1)
        self.assertEqual(iv[0]["evidence"]["display"], d0)
        ep0 = next(e for e in tracking["episodes"] if e["id"] == d0)
        self.assertEqual(iv[0]["unresolved_span"], [round(ep0["t_start"], 3), round(ep0["t_end"], 3)])

    def test_a_clean_jump_video_preserves_every_component(self) -> None:
        _res, _tracking, built, cov = self.run_case(None)
        self.assertTrue(built)
        for _o, rec in built:
            p = rec["jump"]["preservation"]
            self.assertTrue(p["chain_content_preserved"], p)
            self.assertEqual(p["counts"]["unmatched"], 0)
            self.assertGreater(p["counts"]["matched"], 0)  # overlap content was actually looked up
            self.assertNotIn(rj.JUMP_OVERLAP_CONFLICT, rec["issues"])
        self.assertFalse([i for i in cov["intervals"] if i["evidence"].get("rule") == "panorama_overlap_content_conflict"])

    def test_the_ledger_matches_content_shifted_by_one_pixel(self) -> None:
        # registration slack: a component one pixel off in the panorama is the same content
        comp = np.full((60, 200, 3), 250, np.uint8)
        cv2.circle(comp, (150, 30), 3, (20, 20, 20), -1)
        pano = np.full((60, 300, 3), 250, np.uint8)
        cv2.circle(pano, (151, 31), 3, (20, 20, 20), -1)
        comps = {"a": comp, "b": np.full((60, 200, 3), 250, np.uint8)}
        info = {"offsets": [[0, 0], [100, 0]], "owners": [{"display": "a", "pano_cols": [0, 120]}, {"display": "b", "pano_cols": [120, 300]}]}
        eps = {d: {"id": d, "staff_gap_px": 10.0, "observation_ids": [f"o{d}"], "region_ids": ["r"]} for d in comps}
        obs_by = {f"o{d}": {"id": f"o{d}", "system_regions": []} for d in comps}
        cov = {d: np.zeros(200, bool) for d in comps}
        led = rj.panorama_preservation(["a", "b"], info, pano, comps, cov, eps, obs_by, 0, rj.CONFIG)
        self.assertEqual((led["counts"]["matched"], led["counts"]["unmatched"]), (1, 0), led)
        pano2 = np.full((60, 300, 3), 250, np.uint8)
        led2 = rj.panorama_preservation(["a", "b"], info, pano2, comps, cov, eps, obs_by, 0, rj.CONFIG)
        self.assertEqual(led2["counts"]["unmatched"], 1, led2)

    def test_a_recurrent_screen_position_alone_does_not_explain_a_missing_speck(self) -> None:
        # Repetition at a crop position is suspicion, not positive screen-chrome evidence.
        comps = {}
        for d in "abcd":
            c = np.full((60, 200, 3), 250, np.uint8)
            if d != "d":
                cv2.circle(c, (40, 30), 2, (20, 20, 20), -1)
            comps[d] = c
        pano = np.full((60, 500, 3), 250, np.uint8)
        info = {"offsets": [[0, 0], [100, 0], [200, 0], [300, 0]],
                "owners": [{"display": "a", "pano_cols": [0, 20]}, {"display": "b", "pano_cols": [20, 120]},
                           {"display": "c", "pano_cols": [120, 220]}, {"display": "d", "pano_cols": [220, 500]}]}
        eps = {d: {"id": d, "staff_gap_px": 10.0, "observation_ids": [f"o{d}"], "region_ids": ["r"]} for d in comps}
        obs_by = {f"o{d}": {"id": f"o{d}", "system_regions": []} for d in comps}
        cov = {d: np.zeros(200, bool) for d in comps}
        led = rj.panorama_preservation(list(comps), info, pano, comps, cov, eps, obs_by, 0, rj.CONFIG)
        self.assertEqual((led["counts"]["unmatched"], led["counts"]["screen_fixed"]), (3, 0), led["counts"])
        self.assertFalse(led["content_preserved"])
        # in two displays only: content (two conflicts)
        comps["c"] = np.full((60, 200, 3), 250, np.uint8)
        led = rj.panorama_preservation(list(comps), info, pano, comps, cov, eps, obs_by, 0, rj.CONFIG)
        self.assertEqual((led["counts"]["unmatched"], led["counts"]["screen_fixed"]), (2, 0), led["counts"])

    def test_faded_ink_cut_by_a_later_display_panel_edge_is_panel_overflow(self) -> None:
        # a measure-number label of the panel runs past the measured panel (x < 30): faded ink
        # starting at the panel edge of a later display is chrome; dark ink there stays a conflict
        def case(tone: int):
            a = np.full((60, 200, 3), 250, np.uint8)
            b = np.full((60, 200, 3), 250, np.uint8)
            for c in (a, b):  # full-contrast score ink in each display's own columns (its reference)
                for x in range(90, 170, 8):
                    cv2.line(c, (x, 20), (x, 40), (10, 10, 10), 2)
            cv2.rectangle(b, (20, 5), (35, 15), (tone, tone, tone), -1)  # cut at x = 30 by the panel
            pano = np.full((60, 400, 3), 250, np.uint8)
            pano[:, 0:180] = a[:, 0:180]
            pano[:, 180:300] = b[:, 80:200]
            comps = {"a": a, "b": b}
            info = {"offsets": [[0, 0], [100, 0]], "owners": [{"display": "a", "pano_cols": [0, 180]},
                                                              {"display": "b", "pano_cols": [180, 300]}]}
            eps = {d: {"id": d, "staff_gap_px": 10.0, "observation_ids": [f"o{d}"], "region_ids": ["r"]} for d in comps}
            obs_by = {f"o{d}": {"id": f"o{d}", "system_regions": []} for d in comps}
            cov = {d: np.zeros(200, bool) for d in comps}
            return rj.panorama_preservation(["a", "b"], info, pano, comps, cov, eps, obs_by, 30, rj.CONFIG)["counts"]
        faded = case(170)
        self.assertEqual((faded["unmatched"], faded["panel_overflow"]), (0, 1), faded)
        dark_ = case(15)
        self.assertEqual((dark_["unmatched"], dark_["panel_overflow"]), (1, 0), dark_)


if __name__ == "__main__":
    unittest.main()
