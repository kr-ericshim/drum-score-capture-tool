"""Audit J2: dark-paper finishing must not erase persistent gray notation.

Codex probe: an opaque dark-paper score with gray-120 'pp' below the staff, 20 observations,
tracker -> occurrences -> build_strip: the text was in every observation but the strip held
zero of its pixels, issues=[] (after inversion it is gray 135, lighter than the fixed
DARK_INK_MAX=110 cutoff, and was whitened as video bleed). Background suppression now rests
on instability across the members and contrast against the local plate, not on a gray level;
what cannot be separated is kept and flagged, and every notation component is checked to
survive finishing.
"""

import unittest

import cv2
import numpy as np

from app.pipeline import observations as ob
from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as st
from reflow_fixture import build, loader, show, strip

GRAY_TEXT = 120


def pp_position(img):
    r = ob.analyse_crop(img)["regions"][0]
    return 300, int(r["staff_y"][4] + 3.2 * r["staff_gap_px"])


def draw_pp(img, pos, gray=GRAY_TEXT):
    cv2.putText(img, "pp", pos, cv2.FONT_HERSHEY_SIMPLEX | cv2.FONT_ITALIC, 0.8, (gray, gray, gray), 2, cv2.LINE_AA)


def pp_pixels(img, rec, pos):
    x0, y0 = rec["box_crop"][:2]
    seg = img[max(0, pos[1] - 22 - y0):pos[1] + 6 - y0, max(0, pos[0] - 2 - x0):pos[0] + 40 - x0]
    return int((cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY) < 200).sum()) if seg.size else 0


def dark_paper_frames(n_seconds=5.0, blob=False):
    frames = show(strip(4), 0.0, n_seconds, seed=1)
    pos = pp_position(frames[0][1])
    out = []
    for i, (t, img) in enumerate(frames):
        d = 255 - img  # opaque dark paper, light ink
        if blob:
            # video behind a translucent plate: a soft gray blob that moves between observations
            layer = np.zeros(d.shape[:2], np.float32)
            cv2.circle(layer, (700 + 37 * i, 160), 14, 1.0, -1)
            layer = cv2.GaussianBlur(layer, (0, 0), 3)
            d = np.maximum(d, (layer[..., None] * 110).astype(np.uint8))
        draw_pp(d, pos)
        out.append((t, d))
    return out, pos


def strip_of(frames):
    manifest, images = build(frames)
    load = loader(images)
    tracking = st.build_episodes(manifest, load)
    occ = ro.build_occurrences(tracking, manifest, load)
    included = [s for s in occ["systems"] if s["included"]]
    return included, manifest, load


class PersistentGrayDynamicsTest(unittest.TestCase):
    def test_gray_pp_on_dark_paper_survives_the_strip(self):
        frames, pos = dark_paper_frames()
        self.assertEqual(len(frames), 20)
        included, manifest, load = strip_of(frames)
        self.assertEqual(len(included), 1)
        img, rec = rs.build_strip(included[0], manifest, load)
        self.assertTrue(rec["inverted"])
        self.assertGreater(pp_pixels(img, rec, pos), 150)
        dc = rec["finishing"]["dark_cleanup"]
        self.assertGreaterEqual(dc["kept"], 1)
        self.assertEqual(rec["finishing"]["survival"]["lost"], 0)
        self.assertNotIn(rs.CONTENT_LOST_IN_FINISHING, rec["issues"])
        # kept as clearly separated, persistent notation: no uncertainty flag
        self.assertNotIn(rs.LOW_CONTRAST_KEPT, rec["issues"])

    def test_moving_video_bleed_is_whitened_and_pp_kept(self):
        frames, pos = dark_paper_frames(blob=True)
        included, manifest, load = strip_of(frames)
        img, rec = rs.build_strip(included[0], manifest, load)
        self.assertGreater(pp_pixels(img, rec, pos), 150)
        # no blob residue anywhere along its path, away from the staff and the text
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        x0, y0 = rec["box_crop"][:2]
        band = gray[max(0, 150 - y0):min(gray.shape[0], 175 - y0), 690 - x0:1400 - x0]
        self.assertEqual(int((band < 200).sum()), 0)


class DimmedNotationOnTranslucentPlateTest(unittest.TestCase):
    def test_staff_lighter_than_the_video_cutoff_is_kept_and_flagged(self):
        # a dimmed display on a translucent plate: all notation at gray 120, video half-tone
        # showing through on the right; the level cutoff would erase the staff itself
        frames = []
        for t, img in show(strip(4), 0.0, 3.0, seed=1):
            d = ((255 - img).astype(np.float32) * (120 / 255.0)).astype(np.uint8)
            shade = np.tile(np.linspace(0, 70, 500, dtype=np.float32), (d.shape[0], 1)).astype(np.uint8)
            d[:, 900:] = np.maximum(d[:, 900:], shade[..., None])
            frames.append((t, d))
        included, manifest, load = strip_of(frames)
        self.assertTrue(included)
        img, rec = rs.build_strip(included[0], manifest, load)
        dc = rec["finishing"]["dark_cleanup"]
        self.assertEqual(dc["plate"], "opaque")  # forced: the staff did not survive the translucent cleanup
        self.assertTrue(dc["forced_opaque"])
        self.assertIn(rs.LOW_CONTRAST_KEPT, rec["issues"])
        self.assertTrue(rec["finishing"]["survival"]["staff"])
        y0 = rec["box_crop"][1]
        sy = int(round(rec["staff_y_strip"][2]))
        row = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[sy - 1:sy + 2, 100:800].min(axis=0)
        self.assertGreater(float((row < 200).mean()), 0.8)


class CleanupUnitTest(unittest.TestCase):
    def setUp(self):
        self.plate = np.full((80, 200, 3), 30, np.uint8)  # dark paper
        self.text_at = (40, 50)

    def members(self, n=7, moving=False):
        out = []
        for i in range(n):
            m = self.plate.copy()
            draw_pp(m, self.text_at)
            if moving:
                cv2.rectangle(m, (120 + 8 * i, 20), (126 + 8 * i, 60), (120, 120, 120), -1)
            out.append(m)
        return out

    def test_persistent_gray_text_is_kept_and_unstable_mark_whitened(self):
        mem = self.members(moving=True)
        comp = np.rint(np.median(np.stack(mem), axis=0)).astype(np.uint8)
        # the composite still shows one member's mark (as if the median could not clear it)
        cv2.rectangle(comp, (144, 20), (150, 60), (120, 120, 120), -1)
        norm = 255 - comp
        out, info = rs.dark_theme_cleanup(norm, members=mem, gap=12)
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        self.assertGreater(int((g[30:56, 38:80] < 200).sum()), 100)  # the 'pp'
        self.assertEqual(int((g[20:61, 144:151] < 250).sum()), 0)    # the moving mark
        self.assertGreaterEqual(info["whitened_unstable"], 1)
        self.assertEqual(info["kept_flagged"], 0)

    def test_without_member_evidence_faint_content_is_kept_and_flagged(self):
        comp = self.members(1)[0]
        out, info = rs.dark_theme_cleanup(255 - comp, members=None, gap=12)
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        self.assertGreater(int((g[30:56, 38:80] < 200).sum()), 100)
        self.assertGreaterEqual(info["kept_flagged"], 1)
        _img, _inv, _flat, finfo = rs.finish_strip(comp)
        self.assertIn(rs.LOW_CONTRAST_KEPT, finfo["issues"])

    def test_low_contrast_plate_tone_is_whitened(self):
        comp = self.plate.copy()
        comp[10:70, 100:190] = 75  # a broad, soft plate variation (video behind the plate)
        mem = [comp.copy() for _ in range(5)]
        out, info = rs.dark_theme_cleanup(255 - comp, members=mem, gap=12)
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        self.assertEqual(int((g[12:68, 102:188] < 250).sum()), 0)
        self.assertEqual(info["kept"] + info["kept_flagged"], 0)

    def test_translucent_plate_keeps_whitening_static_video(self):
        # video behind a translucent plate: soft half-tone shading over much of the strip and a
        # static, sharp gray stand - as persistent and separated as gray text, so it is whitened
        comp = self.plate.copy()
        shade = np.tile(np.linspace(30, 80, 100, dtype=np.float32), (80, 1))
        comp[:, 100:] = np.maximum(comp[:, 100:], shade.astype(np.uint8)[..., None])
        cv2.rectangle(comp, (40, 5), (45, 70), (125, 125, 125), -1)
        mem = [comp.copy() for _ in range(5)]
        out, info = rs.dark_theme_cleanup(255 - comp, members=mem, gap=12)
        self.assertEqual(info["plate"], "translucent")
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        self.assertEqual(int((g[5:71, 40:46] < 250).sum()), 0)
        self.assertEqual(info["kept"] + info["kept_flagged"], 0)
        self.assertGreaterEqual(info["translucent_glyphlike"], 1)  # counted for review, not silently

    def test_survival_check_reports_a_component_erased_by_finishing(self):
        before = np.full((60, 120, 3), 255, np.uint8)
        draw_pp(before, (20, 40), gray=135)
        notation = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY) < 195
        ok = rs.finishing_survival(before, before.copy(), notation)
        self.assertGreaterEqual(ok["components"], 1)
        self.assertEqual(ok["lost"], 0)
        lost = rs.finishing_survival(before, np.full_like(before, 255), notation)
        self.assertEqual(lost["lost"], lost["components"])
        self.assertTrue(lost["lost_boxes"])


if __name__ == "__main__":
    unittest.main()
