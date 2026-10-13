"""Audit F11 (2026-10-13): weak marks (a light 'pp', a ghost note, a thin gray line) lighter than
the ink cutoffs of the crop (``trim_blank_rows``) and the dark-plate cleanup (``FAINT_PAPER_DROP``)
must survive raw -> crop -> cleanup -> render, and the survival check must see them: a change that
erases a protected mark makes survival fail (``CONTENT_LOST_IN_FINISHING``)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_pipeline as rp
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as st
from test_reflow_visibility_marks import paper, system_case


def pp(level, org=(410, 125)):
    def draw(im):
        cv2.putText(im, "pp", org, cv2.FONT_HERSHEY_SIMPLEX, .55, (level,) * 3, 1, cv2.LINE_AA)
    x, y = org
    return draw, (x - 1, y - 10, x + 28, y + 5)


def ghost(level, center=(520, 68)):
    def draw(im):
        cv2.ellipse(im, center, (6, 4), -20, 0, 360, (level,) * 3, -1, cv2.LINE_AA)
    x, y = center
    return draw, (x - 8, y - 6, x + 9, y + 7)


def hline(level, y=20, x0=600, x1=660):
    def draw(im):
        im[y, x0:x1] = level
    return draw, (x0, y, x1, y + 1)


def vline(level, x=700, y0=106, y1=128):
    def draw(im):
        im[y0:y1, x] = level
    return draw, (x, y0, x + 1, y1)


def frames_with(draw, *, dark, n=8):
    images = []
    for _ in range(n):
        im = (255 - paper()) if dark else paper()
        draw(im)
        images.append(im)
    return images


def norm_gray(img, dark):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return (255 - g) if dark else g


def visible(gray, box, origin=(0, 0)):
    """Pixels of ``box`` (crop coordinates) at least 20 levels darker than paper (dark ink on light)."""
    x0, y0 = max(0, box[0] - origin[0]), max(0, box[1] - origin[1])
    x1, y1 = min(gray.shape[1], box[2] - origin[0]), min(gray.shape[0], box[3] - origin[1])
    if x1 <= x0 or y1 <= y0:
        return 0
    return int((gray[y0:y1, x0:x1] < 230).sum())


# (draw, box) for each mark kind; light-plate gray levels and dark-plate light levels
LIGHT = [pp(200), pp(170, (150, 28)), pp(215), ghost(190), ghost(205, (250, 80)), hline(205), vline(200)]
DARK = [pp(55), pp(80, (150, 28)), pp(45), ghost(60), ghost(45, (250, 80)), hline(50), vline(55)]


class WeakMarksSurvive(unittest.TestCase):
    def check(self, mark, dark):
        draw, box = mark
        images = frames_with(draw, dark=dark)
        raw = visible(norm_gray(images[0], dark), box)
        self.assertGreater(raw, 0)
        sys_, manifest, load = system_case(images)
        img, rec = rs.build_strip(sys_, manifest, load, chrome=False)
        got = visible(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), box, rec["box_crop"][:2])
        self.assertGreaterEqual(got, 0.6 * raw, (box, rec["box_crop"], got, raw))
        surv = rec["finishing"]["survival"]
        self.assertGreaterEqual(surv["weak_marks"]["found"], 1)
        self.assertGreaterEqual(surv["weak_marks"]["components"], 1)  # checked, not only kept
        self.assertEqual(surv["lost"], 0, surv)
        self.assertNotIn(rs.CONTENT_LOST_IN_FINISHING, rec["issues"])
        return img, rec

    def test_light_plate_weak_marks(self):
        for mark in LIGHT:
            with self.subTest(box=mark[1]):
                self.check(mark, dark=False)

    def test_dark_plate_weak_marks(self):
        for mark in DARK:
            with self.subTest(box=mark[1]):
                _img, rec = self.check(mark, dark=True)
                self.assertEqual(rec["finishing"]["dark_cleanup"]["plate"], "opaque")

    def test_tracker_path_keeps_both_audit_cases(self):
        for dark, level in ((False, 200), (True, 55)):
            draw, box = pp(level)
            images = frames_with(draw, dark=dark)
            _s, manifest, load = system_case(images)
            occ = ro.build_occurrences(st.build_episodes(manifest, load), manifest, load)
            included = [s for s in occ["systems"] if s["included"]]
            self.assertEqual(len(included), 1)
            img, rec = rs.build_strip(included[0], manifest, load, chrome=False)
            self.assertGreaterEqual(rec["box_crop"][3], box[3])
            self.assertGreater(visible(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), box, rec["box_crop"][:2]), 20)

    def test_weak_mark_reaches_the_page(self):
        img, rec = self.check(pp(200), dark=False)
        erased = img.copy()
        x0, y0 = rec["box_crop"][:2]
        b = pp(200)[1]
        erased[b[1] - y0:b[3] - y0, b[0] - x0:b[2] - x0] = 250
        pages = []
        for strip_img in (img, erased):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "strip.png"
                cv2.imwrite(str(path), strip_img)
                system = {"id": "sys-001", "included": True, "strip_path": str(path), "strip": dict(rec),
                          "layout": "bottom_bar", "issues": []}
                _plan, rendered = rp.compose_systems([system], header={"title": "T"}, all_systems=[system])
                pages.append(cv2.cvtColor(rendered[0], cv2.COLOR_BGR2GRAY).astype(np.int16))
        self.assertGreater(int((pages[1] - pages[0] >= 15).sum()), 10)  # the mark is printed, lighter than ink


class SurvivalCatchesErasure(unittest.TestCase):
    """Mutations that erase a protected weak mark must make the survival check fail."""

    def strip(self, mark, dark):
        draw, box = mark
        sys_, manifest, load = system_case(frames_with(draw, dark=dark))
        return rs.build_strip(sys_, manifest, load, chrome=False)

    def assert_lost(self, rec):
        self.assertGreaterEqual(rec["finishing"]["survival"]["lost"], 1)
        self.assertIn(rs.CONTENT_LOST_IN_FINISHING, rec["issues"])

    def test_cleanup_that_ignores_the_protection_is_caught(self):
        real = rs.dark_theme_cleanup

        def mutated(norm, **kw):
            kw["weak"] = None
            return real(norm, **kw)
        with patch.object(rs, "dark_theme_cleanup", side_effect=mutated):
            _img, rec = self.strip(pp(55), dark=True)
        self.assert_lost(rec)
        self.assertGreaterEqual(rec["finishing"]["survival"]["weak_marks"]["lost"], 1)

    def test_finishing_that_whitens_the_mark_is_caught(self):
        real = rs.flatten_paper_background
        b = pp(200)[1]

        def mutated(image):
            out = real(image)
            out = (image if out is None else out).copy()
            gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
            out[gray > 150] = 250  # a "cleanup" that whitens everything lighter than gray 150
            return out
        with patch.object(rs, "flatten_paper_background", side_effect=mutated):
            _img, rec = self.strip(pp(200), dark=False)
        self.assert_lost(rec)
        lost = rec["finishing"]["survival"]["weak_marks"]["lost_boxes_crop"]
        self.assertTrue(any(l[0] < b[2] and b[0] < l[2] and l[1] < b[3] and b[1] < l[3] for l in lost), lost)

    def test_crop_that_cuts_the_mark_is_caught(self):
        def ink_only(strip, *, keep, pad):  # the old trim: only ink darker than gray 200 holds rows
            gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
            rows = np.flatnonzero((gray < 200).any(axis=1))
            top, bot = int(rows[0]), int(rows[-1]) + 1
            return strip[top:bot].copy(), [top, strip.shape[0] - bot]
        with patch.object(rs, "trim_blank_rows", side_effect=ink_only):
            _img, rec = self.strip(pp(200), dark=False)
        self.assert_lost(rec)
        self.assertGreaterEqual(rec["finishing"]["survival"]["weak_marks"].get("cropped", 0), 1)


class JumpChunkKeepsWeakMarks(unittest.TestCase):
    """Review follow-up: the jump producer finished a panorama chunk without ``weak_out`` and
    trimmed it with the staff rows and the gray-200 cutoff, so a gray-200 'pp' below the staff
    passed the survival check (lost 0) and was then cut by the trim (79 -> 0 px)."""

    LINES, GAP = [50, 62, 74, 86, 98], 12.0

    def chunk(self, mark, dark):
        from app.pipeline import reflow_jump as rj
        draw, box = mark
        raw = (255 - paper()) if dark else paper()
        draw(raw)
        before = visible(norm_gray(raw, dark), box)
        self.assertGreater(before, 0)
        img, _inv, _flat, info, trimmed = rj.finish_panorama_chunk(raw, self.LINES, self.GAP)
        return img, info, trimmed, box, before

    def test_weak_mark_below_the_staff_stays_in_the_delivered_strip(self):
        for mark, dark in ((pp(200), False), (pp(55), True)):
            with self.subTest(dark=dark):
                img, info, trimmed, box, before = self.chunk(mark, dark)
                got = visible(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), box, (0, trimmed[0]))
                self.assertGreaterEqual(got, 0.6 * before, (got, before, trimmed))
                self.assertGreaterEqual(info["survival"]["weak_marks"]["found"], 1)
                self.assertEqual(info["survival"]["lost"], 0, info["survival"])
                self.assertNotIn(rs.CONTENT_LOST_IN_FINISHING, info["issues"])

    def test_crop_that_cuts_the_mark_is_caught_on_the_jump_path(self):
        def staff_only(strip, *, keep, pad):  # the old trim: the staff rows, nothing below
            top, bot = 25, 128
            return strip[top:bot].copy(), [top, strip.shape[0] - bot]
        with patch.object(rs, "trim_blank_rows", side_effect=staff_only):
            _img, info, _trimmed, _box, _before = self.chunk(pp(200), False)
        self.assertGreaterEqual(info["survival"]["weak_marks"].get("cropped", 0), 1)
        self.assertIn(rs.CONTENT_LOST_IN_FINISHING, info["issues"])


class NoWeakMarksNoChange(unittest.TestCase):
    def test_clean_paper_finds_no_weak_marks(self):
        for dark in (False, True):
            sys_, manifest, load = system_case(frames_with(lambda im: None, dark=dark))
            _img, rec = rs.build_strip(sys_, manifest, load, chrome=False)
            surv = rec["finishing"]["survival"]
            self.assertEqual(surv["weak_marks"]["found"], 0, dark)
            self.assertEqual(surv["lost"], 0)
            self.assertNotIn("weak_marks", rec["finishing"])

    def test_antialiased_rim_of_dark_ink_is_not_a_weak_mark(self):
        im = np.full((80, 200, 3), 250, np.uint8)
        cv2.putText(im, "pp", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, .8, (20, 20, 20), 2, cv2.LINE_AA)
        im = cv2.GaussianBlur(im, (0, 0), 1.0)
        mask, info = rs.weak_marks(im, members=[im] * 5, gap=12)
        self.assertEqual(info["components"], 0)

    def test_unstable_weak_mark_is_not_protected(self):
        base = np.full((80, 200, 3), 250, np.uint8)
        comp = base.copy()
        cv2.putText(comp, "pp", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, .8, (200, 200, 200), 1, cv2.LINE_AA)
        members = [comp.copy()] + [base.copy() for _ in range(4)]  # shown in one member of five
        _mask, info = rs.weak_marks(comp, members=members, gap=12)
        self.assertEqual(info["components"], 0)
        _mask, info = rs.weak_marks(comp, members=[comp.copy() for _ in range(5)], gap=12)
        self.assertGreaterEqual(info["components"], 1)


if __name__ == "__main__":
    unittest.main()
