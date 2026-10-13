"""Jump view: a panel label wider than the measured panel is not lost overlap content.

Sources such as a MuseScore continuous view draw a faded instrument name in the screen-fixed
panel; its last glyph can run a few pixels past the measured panel edge on every display.
``panorama_preservation`` exempts such a component only when it is faded AND starts within a
few staff gaps right of the panel edge AND at least ``label_mask_cover`` of its pixels are
faded near-panel ink in >= ``label_recur_min_others`` + 1 displays of the chain
(``panel_label_recurring``). Position alone or fadedness alone keeps it a conflict.
"""

from __future__ import annotations

import unittest
from typing import Callable, Dict

import cv2
import numpy as np

from app.pipeline import reflow_jump as rj

PANEL = 30
W = 200


def label_stroke(c: np.ndarray, tone: int) -> None:
    """A label stroke at crop x 39..44 (9 px right of the panel edge), rows 5..15."""
    cv2.rectangle(c, (39, 5), (44, 15), (tone, tone, tone), -1)


def ledger(marks: Dict[str, Callable[[np.ndarray], None]], n: int = 5):
    """``n`` displays (a, b, ...), offsets 100 px apart; display k owns panorama columns from
    100k+80. ``marks[d]`` draws into display d's composite; the panorama never draws anything
    left of crop x 70 (panel, label band), so those marks are unmatched overlap content."""
    names = [chr(ord("a") + k) for k in range(n)]
    comps = {}
    for d in names:
        c = np.full((60, W, 3), 250, np.uint8)
        for x in range(90, 170, 8):  # full-contrast score ink in the display's own columns
            cv2.line(c, (x, 20), (x, 40), (10, 10, 10), 2)
        if d in marks:
            marks[d](c)
        comps[d] = c
    pw = 100 * (n - 1) + W
    owners, offsets = [], []
    for k, d in enumerate(names):
        a = 0 if k == 0 else 100 * k + 80
        b = pw if k == n - 1 else 100 * (k + 1) + 80
        owners.append({"display": d, "pano_cols": [a, b]})
        offsets.append([100 * k, 0])
    pano = np.full((60, pw, 3), 250, np.uint8)
    for k, d in enumerate(names):
        a, b = owners[k]["pano_cols"]
        src = comps[d].copy()
        src[:, :70] = 250
        pano[:, a:b] = src[:, a - 100 * k:b - 100 * k]
    info = {"offsets": offsets, "owners": owners}
    eps = {d: {"id": d, "staff_gap_px": 10.0, "observation_ids": [f"o{d}"], "region_ids": ["r"]} for d in names}
    obs_by = {f"o{d}": {"id": f"o{d}", "system_regions": []} for d in names}
    cov = {d: np.zeros(W, bool) for d in names}
    return rj.panorama_preservation(names, info, pano, comps, cov, eps, obs_by, PANEL, rj.CONFIG)


def stroke(tone: int) -> Callable[[np.ndarray], None]:
    return lambda c: label_stroke(c, tone)


class PanelLabelRecurringTests(unittest.TestCase):
    def counts(self, led):
        return led["counts"]["unmatched"], led["counts"]["panel_label_recurring"]

    def test_a_faded_label_recurring_in_four_displays_is_panel_label_recurring(self) -> None:
        led = ledger({d: stroke(170) for d in "bcde"})
        self.assertEqual(self.counts(led), (0, 4), led["counts"])
        self.assertTrue(led["content_preserved"])
        self.assertEqual(len(led["panel_label_recurring"]), 4)
        rec = led["panel_label_recurring"][0]
        self.assertEqual(rec["classification"], "PANEL_LABEL_RECURRING")
        self.assertEqual(rec["box_crop"], [39, 5, 45, 16])
        self.assertGreaterEqual(rec["recurring_cover"], 0.8)
        self.assertEqual(led["version"], rj.PRESERVE_VERSION)

    def test_the_same_faded_glyph_in_one_display_stays_a_conflict(self) -> None:
        led = ledger({"c": stroke(170)})
        self.assertEqual(self.counts(led), (1, 0), led["counts"])
        self.assertFalse(led["content_preserved"])
        self.assertEqual(led["panel_label_recurring"], [])

    def test_a_faded_glyph_in_fewer_than_four_displays_stays_a_conflict(self) -> None:
        led = ledger({d: stroke(170) for d in "bcd"})
        self.assertEqual(self.counts(led), (3, 0), led["counts"])

    def test_a_dark_mark_recurring_at_the_same_place_stays_a_conflict(self) -> None:
        led = ledger({d: stroke(15) for d in "bcde"})
        self.assertEqual(self.counts(led), (4, 0), led["counts"])
        self.assertFalse(led["content_preserved"])

    def test_a_label_fragmented_differently_in_each_display_is_panel_label_recurring(self) -> None:
        rng = np.random.default_rng(7)

        def fragmented(seed_col: int, seed_row: int) -> Callable[[np.ndarray], None]:
            def draw(c: np.ndarray) -> None:
                cv2.rectangle(c, (39, 5), (52, 17), (170, 170, 170), -1)
                c[:, 39 + seed_col] = 250  # a 1-px gap column and row, different per display
                c[5 + seed_row, 39:53] = 250
            return draw

        marks = {d: fragmented(int(rng.integers(3, 11)), int(rng.integers(3, 10))) for d in "bcdef"}
        led = ledger(marks, n=6)
        self.assertEqual(led["counts"]["unmatched"], 0, (led["counts"], led["conflicts"]))
        per = {p["display"]: p["panel_label_recurring"] for p in led["displays"]}
        self.assertTrue(all(per[d] >= 1 for d in "bcdef"), per)

    def test_a_faded_blob_at_a_new_position_in_one_display_stays_a_conflict(self) -> None:
        def label_and_blob(c: np.ndarray) -> None:
            label_stroke(c, 170)
            cv2.circle(c, (58, 50), 4, (170, 170, 170), -1)  # starts in the band, runs past it

        marks = {d: stroke(170) for d in "bcde"}
        marks["c"] = label_and_blob
        led = ledger(marks)
        self.assertEqual(self.counts(led), (1, 4), led["counts"])
        self.assertEqual(led["conflicts"][0]["display"], "c")
        self.assertEqual(led["conflicts"][0]["box_crop"][0], 54)


if __name__ == "__main__":
    unittest.main()
