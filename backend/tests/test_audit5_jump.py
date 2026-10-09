"""Audit 5: recurring screen positions do not certify discarded jump notation."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import overlay_composite as oc
from app.pipeline import reflow_jump as rj
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as stk
from reflow_fixture import build, loader
from test_reflow_jump import JUMP, VIEW_W, long_score
from test_reflow_jump_minority import PER_DISPLAY, frames_with_dot


class Audit5JumpTests(unittest.TestCase):
    def small_case(self, *, icon=False, adjacent_dot=False, fixed=False):
        comps = {}
        for i, d in enumerate("abcd"):
            c = np.full((80, 200, 3), 250, np.uint8)
            # Different notation is required by the real screen chrome detector.
            cv2.rectangle(c, (5, 5 + 17*i), (15, 15 + 17*i), (20, 20, 20), -1)
            if icon:
                cv2.rectangle(c, (35, 20), (45, 40), (30, 80, 160), -1)
                if adjacent_dot:
                    cv2.circle(c, (47, 30), 2, (20, 20, 20), -1)
            elif d != "d":
                cv2.circle(c, (40, 30), 2, (20, 20, 20), -1)
            comps[d] = c
        pano = np.full((80, 500, 3), 250, np.uint8)
        info = {"offsets": [[0, 0], [100, 0], [200, 0], [300, 0]],
                "owners": [{"display": d, "pano_cols": cols} for d, cols in
                           zip(comps, [[0, 20], [20, 120], [120, 220], [220, 500]])]}
        eps = {d: {"id": d, "staff_gap_px": 10., "observation_ids": [f"o{d}"], "region_ids": ["r"]} for d in comps}
        obs = {f"o{d}": {"id": f"o{d}", "system_regions": []} for d in comps}
        cov = {d: np.zeros(200, bool) for d in comps}
        fixed_mask = np.ones((80, 200), bool) if fixed else None
        chrome, ci = oc.screen_fixed_chrome(list(comps.values()))
        led = rj.panorama_preservation(list(comps), info, pano, comps, cov, eps, obs, 0, rj.CONFIG,
                                       fixed=fixed_mask, chrome=chrome, chrome_info=ci)
        return led, chrome, ci

    def test_recurrence_is_only_suspicion_even_with_registration_fixed_mask(self):
        led, _mask, _ci = self.small_case(fixed=True)
        self.assertEqual(led["counts"]["screen_fixed"], 0)
        self.assertFalse(led["content_preserved"])
        self.assertEqual(len(led["screen_fixed_suspicions"]), 3)
        self.assertTrue(all(s["disposition"] == "review_bundle" for s in led["screen_fixed_suspicions"]))
        self.assertTrue(all(s in [dict(c, disposition="review_bundle") for c in led["conflicts"]]
                            for s in led["screen_fixed_suspicions"]))

    def test_positive_chrome_icon_is_explained_with_detector_evidence(self):
        led, mask, ci = self.small_case(icon=True)
        self.assertGreater(ci["displays"], 2)
        self.assertTrue(mask[30, 40])
        icons = [e for e in led["screen_fixed"] if e["box_crop"] == [35, 20, 46, 41]]
        self.assertEqual(len(icons), 3)  # fourth icon is in its own columns
        self.assertTrue(all(e["classification"] == "EXPLAINED_CHROME" for e in icons))
        self.assertTrue(all(e["evidence"]["method"] == "screen_fixed_chrome_appearance" for e in icons))
        self.assertFalse(any(c["box_crop"] == [35, 20, 46, 41] for c in led["conflicts"]))
        self.assertTrue(led["content_preserved"])

    def test_chrome_mask_dilation_does_not_explain_adjacent_neutral_notation(self):
        led, mask, _ci = self.small_case(icon=True, adjacent_dot=True)
        self.assertTrue(mask[30, 47])
        self.assertFalse(led["content_preserved"])
        self.assertTrue(any(c["box_crop"][0] <= 47 < c["box_crop"][2] for c in led["conflicts"]))

    def test_persistent_dot_in_first_four_displays_requires_review_and_raw_bundle(self):
        score = long_score(bars=12)
        offsets = list(range(0, score.shape[1]-VIEW_W+1, JUMP))
        self.assertEqual(len(offsets), 5)
        frames = frames_with_dot(score, offsets, None)
        for _t, frame in frames[:4*PER_DISPLAY]:
            cv2.circle(frame, (920, 43), 2, (20, 20, 20), -1)
        manifest, images = build(frames)
        load = loader(images)
        tracking = stk.build_episodes(manifest, load)
        jump = rj.analyse_jumps(tracking, manifest, load, keep_composites=True)
        self.assertEqual(len(jump["runs"]), 1)
        self.assertEqual(len(jump["runs"][0]["panorama_chains"][0]["displays"]), 5)
        with tempfile.TemporaryDirectory() as td:
            built = rj.build_jump_systems(jump, tracking, manifest, Path(td), composites=jump["_composites"],
                                          covered=jump["_covered"], load=load)
            records = [r for _s, r in built]
            p = records[0]["jump"]["preservation"]
            self.assertFalse(p["chain_content_preserved"])
            self.assertEqual((p["counts"]["screen_fixed"], p["counts"]["unmatched"]), (0, 4))
            self.assertEqual(len(p["screen_fixed_suspicions"]), 4)
            conflicts = [c for r in records for c in r["jump"]["preservation"]["conflicts"]]
            self.assertEqual(len(conflicts), 4)
            for r in records:
                if not r["jump"]["preservation"]["conflicts"]:
                    continue
                self.assertIn(rj.JUMP_OVERLAP_CONFLICT, r["issues"])
                self.assertNotIn(rs.MINORITY_ISSUE, r["issues"])
                bundles = r["minority_content"]["alternates"]
                self.assertEqual(len(bundles), 1)
                self.assertEqual(bundles[0]["kind"], "uncertain_mark_bundle")
                for evidence in bundles[0]["evidence_records"]:
                    if evidence.get("kind") != "overlap_conflict":
                        continue
                    patches = evidence["evidence_patches"]
                    self.assertEqual(len(patches), PER_DISPLAY+1)
                    self.assertEqual(len([p for p in patches if p["kind"] == "raw_observation"]), PER_DISPLAY)
                    self.assertEqual(len({p["obs_id"] for p in patches if "obs_id" in p}), PER_DISPLAY)
                    for patch in patches:
                        path = Path(patch["raw_path"])
                        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), patch["raw_png_sha256"])
                        image = cv2.imread(str(path))
                        x, y = 920-patch["box_crop"][0], 43-patch["box_crop"][1]
                        self.assertLess(int(image[y, x].max()), 100)
            exported = rj.exported_reference([s for s, _r in built], {r["system_id"]:r for r in records})
            cov = rj.account_coverage(tracking, manifest, jump, exported=exported)
            self.assertEqual(cov["status"], "incomplete")
            self.assertEqual(len([i for i in cov["intervals"] if i["evidence"].get("rule") ==
                                  "panorama_overlap_content_conflict"]), 4)


if __name__ == "__main__":
    unittest.main()
