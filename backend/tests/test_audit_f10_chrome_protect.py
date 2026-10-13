"""Audit F10 (2026-10-13): a colored symbol at the same screen place on several score lines (a
section mark, a boxed rehearsal letter, a mark above or below the staff) is score content, not
screen chrome. It must survive into the final strip and page. A clear UI band away from the
notation is still removed, and a band touching notation never erases the notation."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import overlay_composite as oc
from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_pipeline as rp
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as st
from reflow_fixture import build, loader, show, strip
from test_overlay_chrome import PINK, staff

RED = (40, 40, 220)
BLUE = (220, 40, 40)
GRAY = (110, 110, 110)
LINES = [(4, 8), (3, 8), (5, 8)]  # (bars, slots per bar): three different score lines


def run(draw, *, seconds=2.0):
    """Three different score lines (reflow_fixture strips with a moving playhead), each shown for
    ``seconds``, with ``draw(img)`` applied to every frame. Returns the included strips
    [(image, record)], the job chrome info and one raw frame (crop 1400 x 190, staff rows 67-123)."""
    frames = []
    for k, (bars, slots) in enumerate(LINES):
        for t, img in show(strip(4, bars_per_system=bars, slots_per_bar=slots), k * seconds, seconds, seed=k + 1):
            img = img.copy()
            draw(img)
            frames.append((t, img))
    manifest, images = build(frames)
    load = loader(images)
    tracking = st.build_episodes(manifest, load)
    occ = ro.build_occurrences(tracking, manifest, load)
    _chrome, info = rs.job_screen_chrome(manifest, load)
    strips = [rs.build_strip(s, manifest, load) for s in occ["systems"] if s["included"]]
    return strips, info, frames[0][1]


def strip_patch(img, rec, box):
    """``box`` (crop coordinates, half-open) cut from a strip image; None when outside it."""
    x0, y0 = rec["box_crop"][:2]
    bx0, by0, bx1, by1 = box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0
    if bx0 < 0 or by0 < 0 or bx1 > img.shape[1] or by1 > img.shape[0]:
        return None
    return img[by0:by1, bx0:bx1]


def hue_px(patch, color):
    """Pixels of ``patch`` that are clearly ``color`` (its dominant channel well above the others)."""
    c = int(np.argmax(color))
    p = patch.astype(np.int16)
    others = [i for i in range(3) if i != c]
    return int(((p[..., c] - p[..., others].max(axis=-1)) > 80).sum())


def dark_px(patch, thr=170):
    return int((cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) < thr).sum())


def letter_a(color):
    def draw(im):
        cv2.putText(im, "A", (180, 175), cv2.FONT_HERSHEY_SIMPLEX, .9, color, 2, cv2.LINE_AA)
    return draw


A_BOX = (174, 150, 204, 180)  # below the staff (staff rows 67-123)


class ScreenFixedSymbolsSurvive(unittest.TestCase):
    def test_fixed_section_letter_below_the_staff_survives_in_every_strip(self):
        for color in (RED, BLUE, GRAY):
            with self.subTest(color=color):
                strips, info, raw = run(letter_a(color))
                self.assertEqual(len(strips), 3)
                raw_dark = dark_px(raw[A_BOX[1]:A_BOX[3], A_BOX[0]:A_BOX[2]])
                self.assertGreater(raw_dark, 60)
                for img, rec in strips:
                    patch = strip_patch(img, rec, A_BOX)
                    self.assertIsNotNone(patch, rec["box_crop"])  # the letter's rows are not cropped away
                    self.assertGreaterEqual(dark_px(patch), 0.8 * raw_dark, rec["box_crop"])
                    if color != GRAY:
                        self.assertGreater(hue_px(patch, color), 40)  # still the colored letter
                    self.assertNotIn(rs.OVERLAY_COVERS_NOTATION, rec["issues"])
                    self.assertEqual(rec.get("unrecovered_columns", 0), 0)
                if color != GRAY:
                    self.assertTrue(info.get("protected_objects"), info)  # it was a chrome candidate

    def test_boxed_rehearsal_letter_and_marks_above_and_below_survive(self):
        def draw(im):
            cv2.rectangle(im, (300, 2), (324, 20), RED, 2)  # a boxed rehearsal letter above the staff
            cv2.putText(im, "B", (305, 17), cv2.FONT_HERSHEY_SIMPLEX, .5, RED, 2, cv2.LINE_AA)
            cv2.putText(im, "f", (520, 18), cv2.FONT_HERSHEY_SIMPLEX, .6, BLUE, 2, cv2.LINE_AA)   # above the staff
            cv2.putText(im, "mp", (700, 160), cv2.FONT_HERSHEY_SIMPLEX, .6, BLUE, 2, cv2.LINE_AA)  # below the staff
        strips, info, raw = run(draw)
        self.assertEqual(len(strips), 3)
        marks = [((298, 0, 327, 23), RED), ((517, 2, 535, 22), BLUE), ((698, 145, 735, 165), BLUE)]
        for img, rec in strips:
            for box, color in marks:
                raw_hue = hue_px(raw[box[1]:box[3], box[0]:box[2]], color)
                self.assertGreater(raw_hue, 20)
                patch = strip_patch(img, rec, box)
                self.assertIsNotNone(patch, (box, rec["box_crop"]))
                self.assertGreaterEqual(hue_px(patch, color), 0.8 * raw_hue, box)

    def test_letter_reaches_the_page(self):
        strips, _info, _raw = run(letter_a(RED))
        img, rec = strips[0]
        erased = img.copy()
        x0, y0 = rec["box_crop"][:2]
        erased[A_BOX[1] - y0:A_BOX[3] - y0, A_BOX[0] - x0:A_BOX[2] - x0] = 250
        pages = []
        for strip_img in (img, erased):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "strip.png"
                cv2.imwrite(str(path), strip_img)
                system = {"id": "sys-001", "included": True, "strip_path": str(path), "strip": dict(rec),
                          "layout": "bottom_bar", "issues": []}
                _plan, rendered = rp.compose_systems([system], header={"title": "T"}, all_systems=[system])
                pages.append(rendered[0])
        page, page_erased = pages
        self.assertGreater(hue_px(page, RED), 40)  # the red letter is printed
        self.assertEqual(hue_px(page_erased, RED), 0)
        self.assertGreater(int((np.abs(page.astype(np.int16) - page_erased.astype(np.int16)).max(axis=-1) > 60).sum()), 40)


class ChromeControls(unittest.TestCase):
    def test_clear_ui_band_away_from_notation_is_still_removed(self):
        def draw(im):
            im[0:12, 900:] = PINK
            letter_a(RED)(im)
        strips, info, _raw = run(draw)
        self.assertEqual(len(strips), 3)
        for img, rec in strips:
            self.assertGreater(rec["screen_chrome"]["filled_px"], 0)
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            pink = (hsv[..., 1] > 30) & (hsv[..., 2] > 150) & (np.abs(img.astype(np.int16) - np.array(PINK)).max(axis=-1) < 25)
            self.assertEqual(int(pink.sum()), 0)  # no band left anywhere
            patch = strip_patch(img, rec, A_BOX)
            self.assertIsNotNone(patch)
            self.assertGreater(hue_px(patch, RED), 40)  # while the letter stays

    def test_band_touching_notation_does_not_erase_it(self):
        def draw(im):
            im[0:12, 900:] = PINK
            cv2.line(im, (1000, 4), (1000, 40), (20, 20, 20), 2)  # a stroke reaching into the band
        strips, _info, raw = run(draw)
        self.assertEqual(len(strips), 3)
        stem = (998, 4, 1003, 40)
        raw_dark = dark_px(raw[stem[1]:stem[3], stem[0]:stem[2]], 100)
        for img, rec in strips:
            patch = strip_patch(img, rec, stem)
            self.assertIsNotNone(patch, rec["box_crop"])
            self.assertGreaterEqual(dark_px(patch, 100), raw_dark)


class ProtectZoneUnit(unittest.TestCase):
    def test_symbol_outside_the_rows_or_larger_than_a_symbol_stays_chrome(self):
        reps = []
        for k in range(3):
            im = staff(notes=[60 + 70 * j + 23 * k * (j % 3) for j in range(10)])
            cv2.putText(im, "A", (180, 180), cv2.FONT_HERSHEY_SIMPLEX, .9, RED, 2, cv2.LINE_AA)
            reps.append(im)
        zone = np.zeros(reps[0].shape[:2], bool)
        zone[40:150] = True  # rows that do not reach the letter
        mask, info = oc.screen_fixed_chrome(reps, protect=zone, gap=14.0)
        self.assertTrue(mask[170, 190] or mask[165:182, 179:198].any())
        zone[:] = True
        mask, info = oc.screen_fixed_chrome(reps, protect=zone, gap=14.0)
        self.assertFalse(mask.any())
        self.assertEqual(len(info["protected_objects"]), 1)
        mask, info = oc.screen_fixed_chrome(reps, protect=zone, gap=3.0)  # 4 gaps = 12 px: the letter is larger
        self.assertTrue(mask.any())

    def test_symbol_fixed_on_most_of_many_displays_is_chrome(self):
        # an editor icon or logo at one place on every line of a long video (corpus SZwT): a section
        # mark changes with the section, so it cannot repeat on most of many different displays
        def reps(n):
            out = []
            for k in range(n):
                im = staff(notes=[60 + 70 * j + 11 * k * (j % 3) for j in range(10)])
                cv2.putText(im, "A", (180, 180), cv2.FONT_HERSHEY_SIMPLEX, .9, RED, 2, cv2.LINE_AA)
                out.append(im)
            return out
        many = reps(oc.LOGO_MIN_DISPLAYS)
        zone = np.ones(many[0].shape[:2], bool)
        mask, info = oc.screen_fixed_chrome(many, protect=zone, gap=14.0)
        self.assertEqual(info["displays"], oc.LOGO_MIN_DISPLAYS)
        self.assertEqual(info.get("protect_skipped"), "many_displays")
        self.assertTrue(mask[165:182, 179:198].any())
        few = reps(oc.LOGO_MIN_DISPLAYS - 1)
        mask, info = oc.screen_fixed_chrome(few, protect=zone, gap=14.0)
        self.assertEqual(info["displays"], oc.LOGO_MIN_DISPLAYS - 1)
        self.assertFalse(mask.any())
        self.assertEqual(len(info["protected_objects"]), 1)


if __name__ == "__main__":
    unittest.main()
