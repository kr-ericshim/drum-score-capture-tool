"""Tests for the ported staff/barline detector and system regions.

The golden regression runs only where the drum-score corpus exists
(~/Documents/drum-score-corpus/golden.json and the referenced captures).
"""

import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import system_detect as sd
from drum_score_fixture import groove_notes, render, strip_spec, PageSpec

CORPUS = Path.home() / "Documents/drum-score-corpus"
GOLDEN = CORPUS / "golden.json"


def _golden_available() -> bool:
    if not GOLDEN.exists():
        return False
    try:
        gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(gold) and all(Path(p).exists() for p in gold)


class SyntheticDetectionTest(unittest.TestCase):
    def test_strip_staff_and_barlines(self):
        spec = groove_notes(strip_spec(), seed=3)
        img = render(spec)
        res = sd.detect(img)
        self.assertFalse(res["inverted"])
        self.assertEqual(len(res["staves"]), 1)
        st = res["staves"][0]
        self.assertAlmostEqual(st["gap"], spec.gap, delta=1.0)
        # 5 bar lines are drawn (start, 3 inner, end); the first sits on the
        # staff start and is dropped like the clef bars in the original.
        centres = sd.barline_centres(st)
        bar_w = (spec.width - 2 * spec.margin_x) / spec.bars_per_system
        expected = [spec.margin_x + k * bar_w for k in range(1, spec.bars_per_system + 1)]
        for x in expected:
            self.assertTrue(any(abs(x - c) <= spec.gap / 2 for c in centres), (x, centres))

    def test_dark_theme_is_inverted(self):
        spec = groove_notes(strip_spec(), seed=4)
        img = 255 - render(spec)
        res = sd.detect(img)
        self.assertTrue(res["inverted"])
        self.assertEqual(len(res["staves"]), 1)

    def test_system_regions_page_rows_and_envelopes(self):
        spec = groove_notes(PageSpec(width=1400, height=900, systems=4, gap=12), seed=5)
        img = render(spec)
        out = sd.system_regions(img)
        regions = out["regions"]
        self.assertEqual(len(regions), 4)
        tops = [r["staff_y"][0] for r in regions]
        self.assertEqual(tops, sorted(tops))
        for r in regions:
            ex0, ey0, ex1, ey1 = r["envelope_bbox"]
            bx0, by0, bx1, by1 = r["bbox"]
            # envelope covers the staff and the stems/beams above it
            self.assertLessEqual(ey0, r["staff_y"][0] - 2 * spec.gap)
            self.assertGreaterEqual(ey1, r["staff_y"][4])
            self.assertGreaterEqual(ey0, by0)
            self.assertLessEqual(ey1, by1)
            self.assertEqual(r["issues"], [])
        # bands do not overlap
        for a, b in zip(regions, regions[1:]):
            self.assertLessEqual(a["bbox"][3], b["bbox"][1] + 1)

    def test_envelope_touching_crop_edge_is_flagged(self):
        spec = groove_notes(strip_spec(), seed=6)
        img = render(spec)
        top = sd.system_regions(img)["regions"][0]
        # crop so the stems/beam stubs above the staff touch the top border
        y_cut = int(top["staff_y"][0] - 1.5 * spec.gap)
        clipped = sd.system_regions(img[y_cut:])["regions"][0]
        self.assertIn("envelope_at_top_edge", clipped["issues"])
        self.assertNotIn("envelope_at_top_edge", top["issues"])

    @staticmethod
    def _staff_with_ghost_row(*, below: bool = False):
        """Thin full-width staff plus a dense beam / note-head row one gap off it."""
        w, h, gap, top = 1500, 260, 14, 120
        img = np.full((h, w, 3), 245, np.uint8)
        lines = [top + k * gap for k in range(5)]
        for y in lines:
            cv2.line(img, (20, y), (w - 20, y), (40, 40, 40), 1)
        for x in range(20, w - 20, 300):  # barlines
            cv2.line(img, (x, lines[0]), (x, lines[4]), (40, 40, 40), 2)
        ghost = lines[4] + gap if below else lines[0] - gap
        # beamed groups: thick bars ~130 px long with short breaks, plus note heads
        for gx in range(40, w - 160, 150):
            cv2.rectangle(img, (gx, ghost - 3), (gx + 125, ghost + 3), (30, 30, 30), -1)
            for k in range(4):
                cv2.ellipse(img, (gx + 8 + k * 36, ghost + (8 if not below else -8)), (6, 4), -20, 0, 360, (30, 30, 30), -1)
        return img, [float(y) for y in lines]

    def test_ghost_row_above_staff_does_not_shift_lines(self):
        img, lines = self._staff_with_ghost_row()
        ink = sd.ink_mask(sd.normalize_polarity(img)[0])
        rows = [y for y, _ in sd._line_rows(sd._horizontal_lines(ink), 0.2)]
        # the ghost row really is a detected line row one gap above the staff
        self.assertTrue(any(abs(y - (lines[0] - 14)) <= 3 for y in rows), rows)
        regions = sd.system_regions(img)["regions"]
        self.assertEqual(len(regions), 1)
        for a, b in zip(regions[0]["staff_y"], lines):
            self.assertAlmostEqual(a, b, delta=1.0)

    def test_ghost_row_below_staff_does_not_shift_lines(self):
        img, lines = self._staff_with_ghost_row(below=True)
        regions = sd.system_regions(img)["regions"]
        self.assertEqual(len(regions), 1)
        for a, b in zip(regions[0]["staff_y"], lines):
            self.assertAlmostEqual(a, b, delta=1.0)

    def test_score_against_golden_counts_extra_staves(self):
        gold = [{"top": 50.0, "gap": 10.0, "x": [0, 500], "bars": [100.0, 200.0]}]
        det = [
            {"lines": [50.5, 60, 70, 80, 90], "x": [0, 500], "bars": [[99, 101, 1], [199, 201, 1], [300, 301, 1]]},
            {"lines": [200, 210, 220, 230, 240], "x": [0, 500], "bars": []},
        ]
        s = sd.score_against_golden(gold, det)
        self.assertEqual((s["tp"], s["fp"], s["fn"], s["missing_staves"], s["extra_staves"]), (2, 1, 0, 0, 1))


@unittest.skipUnless(_golden_available(), "drum-score corpus golden set not available")
class GoldenRegressionTest(unittest.TestCase):
    def test_golden_set_reproduces_367(self):
        gold = json.loads(GOLDEN.read_text(encoding="utf-8"))
        tot = {"tp": 0, "fp": 0, "fn": 0, "missing_staves": 0, "extra_staves": 0}
        for cap, staves in gold.items():
            res = sd.detect(cv2.imread(cap))
            s = sd.score_against_golden(staves, res["staves"])
            for k in tot:
                tot[k] += s[k]
        self.assertEqual(len(gold), 67)
        self.assertEqual(tot["tp"], 367)
        self.assertEqual(tot["fp"], 0)
        self.assertEqual(tot["fn"], 0)
        self.assertEqual(tot["missing_staves"], 0)
        # golden.py does not look at unmatched detections; the port does.
        self.assertEqual(tot["extra_staves"], 0)


if __name__ == "__main__":
    unittest.main()
