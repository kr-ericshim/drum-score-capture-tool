"""Boundary classifier on real repeat signs (regression from a corpus video).

Fixtures: two column crops of cleaned strips from the corpus video gpYDVEsuXio (DRUMMATE, "Eye Of
Tiger"), run through the app pipeline with its auto-ROI (drum-score-corpus/reflow/e2e_rep1):

* ``start_repeat``: strip sys-045 columns 0-900: clef, a start repeat (thick, thin, two dots), two
  ordinary barlines.
* ``end_repeat``: strip sys-046 columns 1100-1878: an ordinary barline, a measure closed by an end
  repeat, then the start of the next system as shown by the video (its start repeat).

Each crop keeps its strip record (shifted to the crop) and the member observations' system regions,
so barline registration is the real one. A real repeat boundary must be LOCKED or UNKNOWN, or, when
SAFE, keep the dots with the correct side (start repeat with the right piece, end repeat with the left).
"""

import hashlib
import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_boundaries as rb

FIX = Path(__file__).resolve().parent / "fixtures"
SPEC = json.loads((FIX / "real_repeat_gpYDVEsuXio.json").read_text())


def load(name, record_patch=None, image=None):
    c = SPEC["crops"][name]
    img = cv2.imread(str(FIX / c["file"])) if image is None else image
    rec = dict(c["record"], **(record_patch or {}))
    return img, rec, rb.analyse_strip(img, rec, system_id=rec["system_id"], observations=c["observations"])


def repeat_side_violations(an, seams):
    """SAFE seams that split a repeat group or put its dots on the wrong side."""
    reach = rb.CONFIG["repeat_reach_gaps"] * an.gap
    bars = sorted(an.bars, key=lambda b: b["x0"])
    bad = []
    for s in seams:
        for i, b in enumerate(bars):
            x0, x1 = int(b["x0"]), int(b["x1"])
            start, end = b["dots"]["right"], b["dots"]["left"]
            if not (start or end):
                continue
            z0, z1 = x0 - (reach if end else 0), x1 + 1 + (reach if start else 0)
            if z0 < s < z1:
                bad.append((s, "inside", x0))
            nxt = bars[i + 1]["x0"] if i + 1 < len(bars) else an.staff["x"][1] + 1
            prv = bars[i - 1]["x1"] if i > 0 else an.staff["x"][0] - 1
            if start and z1 <= s < nxt:
                bad.append((s, "start_repeat_left_with_previous_measure", x0))
            if end and prv < s <= z0:
                bad.append((s, "end_repeat_moved_to_next_measure", x0))
    return bad


class RealRepeatSigns(unittest.TestCase):
    def test_fixtures_are_small_and_unchanged(self):
        for c in SPEC["crops"].values():
            p = FIX / c["file"]
            self.assertLess(p.stat().st_size, 200 * 1024)
            self.assertEqual(hashlib.sha256(cv2.imread(str(p)).tobytes()).hexdigest(), c["pixels_sha256"])

    def test_start_repeat_at_the_system_start(self):
        _img, _rec, an = load("start_repeat")
        groups = [b for b in an.bars if b["dots"]["right"] or b["dots"]["left"]]
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertTrue(g["dots"]["right"] and not g["dots"]["left"] and g["thick_stroke"], g)
        bnds = rb.strip_boundaries(an)
        at_repeat = [b for b in bnds if b["barline_box"][0] == g["x0"]]
        self.assertEqual(len(at_repeat), 1)
        self.assertEqual(at_repeat[0]["class"], rb.LOCKED, at_repeat[0]["reason_codes"])
        self.assertIn("REPEAT_BOUNDARY", at_repeat[0]["reason_codes"])
        self.assertLess(at_repeat[0]["seam_x"], g["x0"])  # the start repeat goes with the right piece
        # real positive controls: the two ordinary barlines after it are SAFE cuts
        safe = [b["seam_x"] for b in bnds if b["class"] == rb.SAFE]
        self.assertEqual(len(safe), 2, [(b["seam_x"], b["class"], b["reason_codes"]) for b in bnds])
        self.assertEqual(repeat_side_violations(an, safe), [])

    def test_end_repeat_at_the_system_end(self):
        img, rec, an = load("end_repeat")
        g = next(b for b in an.bars if b["dots"]["left"])
        self.assertFalse(g["dots"]["right"])
        bnds = rb.strip_boundaries(an)
        self.assertEqual(repeat_side_violations(an, [b["seam_x"] for b in bnds if b["class"] == rb.SAFE]), [])
        # every column seam across the repeat sign and its dots is rejected
        for x in range(int(g["x0"] - rb.CONFIG["repeat_reach_gaps"] * an.gap) + 1, int(g["x1"]) + 1):
            self.assertNotEqual(rb.classify_seam(an, x)["class"], rb.SAFE, x)

    def test_end_repeat_followed_by_start_repeat_is_locked(self):
        # read the staff across the gap to the next system's start (as a joined line would): the junction
        # end repeat | start repeat is a proposed internal boundary and must not be SAFE
        img, rec, _an = load("end_repeat")
        _img, _rec, an = load("end_repeat", {"staff_x_strip": [rec["staff_x_strip"][0], img.shape[1] - 3]})
        ends = [b for b in an.bars if b["dots"]["left"] and not b["dots"]["right"]]
        starts = [b for b in an.bars if b["dots"]["right"] and not b["dots"]["left"]]
        self.assertTrue(ends and starts, [(b["x0"], b["dots"]) for b in an.bars])
        props = [p for p in rb.propose(an) if p["bar"] in ends + starts]
        self.assertTrue(props)
        for p in props:
            res = rb.classify_seam(an, p["seam_x"])
            self.assertEqual(res["class"], rb.LOCKED, res["reasons"])
            self.assertIn("REPEAT_BOUNDARY", res["reasons"])
        safe = [b["seam_x"] for b in rb.strip_boundaries(an) if b["class"] == rb.SAFE]
        self.assertEqual(repeat_side_violations(an, safe), [])

    def test_real_start_repeat_with_fused_dots_is_not_safe_at_the_proposed_seam(self):
        base, rec, an0 = load("start_repeat")
        g0 = next(b for b in an0.bars if b["dots"]["right"])
        x1 = int(g0["x1"])
        for dark in (False, True):
            img = base.copy()
            # join each real dot to the thin stroke with a 2-px ink bridge (blur/compression fusion)
            l = an0.staff["lines"]
            for yc in ((l[1] + l[2]) / 2.0, (l[2] + l[3]) / 2.0):
                y = int(round(yc)) - 1
                img[y:y + 2, x1:x1 + 8] = 30
            if dark:
                img = 255 - img
            _i, _r, an = load("start_repeat", image=img)
            g = next(b for b in an.bars if b["x0"] == g0["x0"])
            self.assertFalse(g["dots"]["right"] or g["dots"]["left"], (dark, g["dots"]))  # dots no longer separate
            prop = next(p for p in rb.propose(an) if p["bar"] is g)
            self.assertGreater(prop["seam_x"], x1 + 8)  # the proposer puts the seam after the fused dots
            res = rb.classify_seam(an, prop["seam_x"])
            self.assertNotEqual(res["class"], rb.SAFE, (dark, res))
            self.assertIn("BARLINE_GROUP_ATTACHED_INK", res["reasons"], dark)


if __name__ == "__main__":
    unittest.main()
