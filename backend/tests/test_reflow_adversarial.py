"""Adversarial cases from docs/archive/reflow/DESIGN_astra.md section 6 for tracking + assembly,
plus regressions found on the calibration corpus."""

import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import observations as ob
from app.pipeline import score_assembly as sa
from app.pipeline import system_detect as sd
from app.pipeline import system_tracking as st
from drum_score_fixture import Overlay, groove_notes, render, strip_spec
from reflow_fixture import STEP, build, frame, loader, page, show, strip

CORPUS = Path.home() / "Documents/drum-score-corpus"


def run(frames, policy="evidence"):
    manifest, images = build(frames)
    load = loader(images)
    tracking = st.build_episodes(manifest, load)
    return sa.assemble_locations(tracking, manifest, load, policy=policy), tracking, manifest


class IdentifierTest(unittest.TestCase):
    def _region(self, img):
        return ob.analyse_crop(img)["regions"][0]

    def test_non_numeric_mark_is_not_an_identifier(self):
        spec = groove_notes(strip_spec(height=190), seed=3)
        img = render(spec)
        r = self._region(img)
        g, top, x0 = r["staff_gap_px"], r["staff_y"][0], r["staff_x"][0]
        marked = img.copy()
        # open-hat circle and accent above the first beat, a crash-like head on a ledger stub
        cv2.circle(marked, (int(x0 + 1.2 * g), int(top - 1.6 * g)), int(0.35 * g), (20, 20, 20), 2)
        cv2.line(marked, (int(x0 + 0.4 * g), int(top - 2.6 * g)), (int(x0 + 1.4 * g), int(top - 2.3 * g)), (20, 20, 20), 2)
        cv2.line(marked, (int(x0 + 1.4 * g), int(top - 2.3 * g)), (int(x0 + 0.4 * g), int(top - 2.0 * g)), (20, 20, 20), 2)
        self.assertIsNone(sa.number_patch(sd.normalize_polarity(marked)[0], r))
        # a boxed section letter is not a number either
        boxed = img.copy()
        cv2.rectangle(boxed, (int(x0), int(top - 2.6 * g)), (int(x0 + 1.6 * g), int(top - 0.8 * g)), (20, 20, 20), 2)
        cv2.putText(boxed, "A", (int(x0 + 0.3 * g), int(top - 1.0 * g)), cv2.FONT_HERSHEY_SIMPLEX, g / 22.0, (20, 20, 20), 2)
        self.assertIsNone(sa.number_patch(sd.normalize_polarity(boxed)[0], r))
        # a printed measure number is
        numbered = render(groove_notes(strip_spec(height=190, first_bar_number=17), seed=3))
        self.assertIsNotNone(sa.number_patch(sd.normalize_polarity(numbered)[0], self._region(numbered)))

    def test_identical_two_row_pages_without_identifiers_are_not_merged(self):
        # Regression for Q8XtphO6Xz0 L14/L30 (run 1: false identifier+context merge on a cymbal
        # head treated as a "number"). Identical two-row page views, no printed numbers.
        p1 = page([41, 42])
        p2 = page([43, 44])
        frames = show(p1, 0, 4, seed=1) + show(p2, 4, 4, seed=2) + show(p1, 8, 4, seed=3) + show(p2, 12, 4, seed=4)
        out, _, _ = run(frames, "evidence")
        self.assertEqual([m for m in out["merges"] if m["basis"] in ("identifier+context", "page_map_identity")], [])
        kinds = {e["kind"] for e in out["evidence"]}
        self.assertNotIn("identifier_patch_match", kinds)
        self.assertTrue(all(c["state"] == "unresolved" for c in out["identity_candidates"]))

    @unittest.skipUnless((CORPUS / "reflow/manifests/Q8XtphO6Xz0.json").exists() and (CORPUS / "reflow/gt/Q8XtphO6Xz0/gt.json").exists(),
                         "corpus Q8XtphO6Xz0 manifest not available")
    def test_corpus_q8_l14_l30_have_no_identifier(self):
        m = json.loads((CORPUS / "reflow/manifests/Q8XtphO6Xz0.json").read_text())
        gt = json.loads((CORPUS / "reflow/gt/Q8XtphO6Xz0/gt.json").read_text())
        by = {o["id"]: o for o in m["observations"]}
        for lid in ("L14", "L30"):
            ref = next(l for l in gt["locations"] if l["id"] == lid)["reference"]
            obs = by[ref["obs_id"]]
            img = ob.load_observation_image(CORPUS / "reflow/manifests/Q8XtphO6Xz0", obs, m)
            region = min(obs["system_regions"], key=lambda r: abs(r["staff_y"][0] - ref["staff_top_y_crop"]))
            self.assertIsNone(sa.number_patch(sd.normalize_polarity(img)[0], region), lid)


class SequenceAdversarialTest(unittest.TestCase):
    def test_repeat_older_than_eight_episodes_is_still_nominated(self):
        a = strip(100)
        frames = show(a, 0, 2, seed=0)
        t = 2.0
        for k in range(9):
            frames += show(strip(200 + k), t, 2, seed=k + 1)
            t += 2.0
        frames += show(a, t, 2, seed=50)
        out, tracking, _ = run(frames, "conservative")
        self.assertEqual(len(tracking["episodes"]), 11)
        first, last = tracking["episodes"][0]["id"], tracking["episodes"][-1]["id"]
        self.assertTrue(any({c["a"], c["b"]} == {first, last} and c["state"] == "unresolved" for c in out["identity_candidates"]))

    def test_in_row_preview_segment_is_one_region_and_one_episode(self):
        cur = render(groove_notes(strip_spec(width=1150, height=190, margin_x=40), seed=7))
        nxt = render(groove_notes(strip_spec(width=1150, height=190, margin_x=40), seed=8))
        def with_preview(main, preview, phase):
            img = np.full((190, 1400, 3), 255, np.uint8)
            img[:, :1150] = main
            img[:, 1180:1400] = preview[:, 40:260]  # first bar of the next system beside the current one
            cv2.line(img, (int(40 + phase * 1070), 20), (int(40 + phase * 1070), 170), (220, 120, 40), 3)
            return img
        frames = [(i * STEP, with_preview(cur, nxt, (i + 0.5) / 12)) for i in range(12)]
        manifest, images = build(frames)
        regs = [o["system_regions"] for o in manifest["observations"]]
        self.assertTrue(all(len(r) == 1 for r in regs))
        self.assertTrue(all(len(r[0]["segments"]) == 2 for r in regs), [r[0]["segments"] for r in regs])
        tracking = st.build_episodes(manifest, loader(images))
        self.assertEqual(len(tracking["episodes"]), 1)

    def test_short_terminal_display_is_kept_and_flagged(self):
        a, b = strip(1), strip(2)
        frames = show(a, 0, 3, seed=1) + show(b, 3, 0.5, seed=2)
        out, tracking, _ = run(frames, "conservative")
        last = tracking["episodes"][-1]
        self.assertIn(st.SHORT_EPISODE, last["flags"])
        self.assertIn(st.TERMINAL, last["flags"])
        loc = next(l for l in out["locations"] if last["id"] in l["episode_ids"])
        self.assertFalse(loc["included"])
        self.assertIn("NON_SCORE_UNCERTAIN", loc["issues"])
        self.assertIn(loc["id"], out["excluded_location_ids"])
        self.assertNotEqual(out["completion"], "resolved")

    def test_numbering_restart_does_not_merge_different_systems(self):
        s1 = strip(1, first_bar=1, numbers=True)
        s2 = strip(2, first_bar=1, numbers=True)  # numbering restarts, different content
        frames = show(s1, 0, 3, seed=1) + show(s2, 3, 3, seed=2)
        out, _, _ = run(frames, "evidence")
        self.assertEqual(out["merges"], [])
        self.assertEqual(len(out["locations"]), 2)

    def test_dark_playhead_over_barlines_does_not_split(self):
        a = strip(5)
        frames = []
        for i in range(16):
            img = render(a)
            x = int(60 + (i + 0.5) / 16 * 1280)
            cv2.rectangle(img, (x - 2, 25), (x + 2, 165), (60, 60, 60), -1)  # dark gray playhead bar, crosses barlines
            frames.append((i * STEP, img))
        manifest, images = build(frames)
        tracking = st.build_episodes(manifest, loader(images))
        self.assertEqual(len(tracking["episodes"]), 1, [(e["t_start"], e["ended_by"]) for e in tracking["episodes"]])


class EnvelopeTest(unittest.TestCase):
    def test_attached_envelope_includes_near_marks_excludes_far_ink(self):
        spec = groove_notes(strip_spec(height=260), seed=4)
        img = render(spec)
        r0 = ob.analyse_crop(img)["regions"][0]
        g, top = r0["staff_gap_px"], r0["staff_y"][0]
        near = img.copy()
        cv2.circle(near, (700, int(top - 2.2 * g - 0.5 * g)), int(0.3 * g), (20, 20, 20), 2)  # just above a beam stub
        far = img.copy()
        cv2.putText(far, "TITLE", (300, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1)  # far above the notation
        e_base = r0["envelope_bbox"]
        e_near = ob.analyse_crop(near)["regions"][0]["envelope_bbox"]
        e_far = ob.analyse_crop(far)["regions"][0]["envelope_bbox"]
        self.assertLess(e_near[1], e_base[1])
        self.assertEqual(e_far[1], e_base[1])
        self.assertGreater(e_base[1], r0["row_band"][1])


if __name__ == "__main__":
    unittest.main()
