"""Screen-fixed chrome and 2-D overlay recovery (STRATEGY Step 2B, work package B2)."""

import unittest

import cv2
import numpy as np

from app.pipeline import overlay_composite as oc
from app.pipeline import reflow_strips as rs

GAP = 14
PINK = (220, 170, 230)    # BGR, a light frame band
CURSOR = (240, 210, 170)  # BGR, a pale translucent blue box


def staff(width=900, height=200, top=70, notes=(), paper=250):
    img = np.full((height, width, 3), paper, np.uint8)
    ys = [top + k * GAP for k in range(5)]
    for y in ys:
        cv2.line(img, (20, y), (width - 20, y), (20, 20, 20), 1)
    for x in notes:
        cv2.circle(img, (int(x), ys[2]), 5, (20, 20, 20), -1)
        cv2.line(img, (int(x) + 5, ys[2]), (int(x) + 5, ys[0] - 20), (20, 20, 20), 2)
    return img


def with_band(img, x0=600, rows=(0, 12)):
    out = img.copy()
    out[rows[0]:rows[1], x0:] = PINK
    return out


def with_cursor(img, x, w=40, y0=40, y1=170):
    out = img.astype(np.float32)
    out[y0:y1, x:x + w] = 0.55 * out[y0:y1, x:x + w] + 0.45 * np.array(CURSOR, np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


class OverlayMask2DTest(unittest.TestCase):
    def test_band_is_masked_as_rows_not_whole_columns(self):
        img = with_band(staff(notes=(650, 700)))
        mask = oc.overlay_mask_2d(img)
        self.assertTrue(mask[5, 700])
        self.assertFalse(mask[100:, 600:].any())  # the staff under the band's columns is not masked
        self.assertTrue(oc._overlay_columns(img)[700])  # the old column mask took the whole column

    def test_translucent_box_is_masked_as_a_box(self):
        img = with_cursor(staff(notes=(320,)), 300)
        mask = oc.overlay_mask_2d(img)
        self.assertTrue(mask[100, 320])  # the tinted note inside the box is covered too
        self.assertFalse(mask[100, 500])


class ScreenFixedChromeTest(unittest.TestCase):
    def test_static_band_is_chrome_and_the_cursor_is_not(self):
        displays = [with_cursor(with_band(staff(notes=[60 + 90 * j + 17 * k for j in range(9)])), 150 + 120 * k) for k in range(5)]
        mask, info = oc.screen_fixed_chrome(displays)
        self.assertEqual(info["displays"], 5)
        self.assertTrue(mask[5, 700])
        self.assertFalse(mask[100:, :].any())  # no cursor, no staff

    def test_one_display_shown_many_times_is_not_enough(self):
        same = [with_band(staff(notes=(100, 400)))] * 6
        mask, info = oc.screen_fixed_chrome(same)
        self.assertEqual(info["displays"], 1)
        self.assertFalse(mask.any())

    def test_an_object_that_moves_with_the_line_end_is_not_chrome(self):
        def icon_at(img, x):
            out = img.copy()
            out[30:46, x:x + 14] = (230, 160, 90)
            return out
        xs = [800, 800, 800, 800, 770, 770, 800, 800, 800, 800]
        displays = [icon_at(staff(notes=[60 + 70 * j + 7 * k for j in range(10)]), x) for k, x in enumerate(xs)]
        mask, info = oc.screen_fixed_chrome(displays)
        self.assertFalse(mask[30:46, 800:814].any(), info)


class ComposeTest(unittest.TestCase):
    def test_fade_member_is_never_the_reference_and_not_in_the_median(self):
        base = staff(notes=(200, 400, 600))
        faded = np.clip(base.astype(np.int16) - 120, 0, 255).astype(np.uint8)
        images = [faded] + [with_cursor(base, x) for x in (150, 350, 550, 750)]
        out, info = rs.compose_members(images, float(GAP))
        self.assertEqual(info["faded_members"], 1)
        self.assertNotEqual(info["reference_index"], 0)
        self.assertLess(float(np.abs(out.astype(int) - base.astype(int)).mean()), 1.0)

    def test_cursor_pixels_come_from_members_where_it_is_elsewhere(self):
        base = staff(notes=(200, 400, 600))
        images = [with_band(with_cursor(base, x)) for x in (150, 350, 550, 750)]
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        out, info = rs.compose_members(images, float(GAP), chrome=chrome)
        self.assertEqual(info["unrecovered_columns"], 0)  # the band is chrome, not an unrecovered overlay
        core = (slice(20, None), slice(None))
        self.assertLess(float(np.abs(out[core].astype(int) - base[core].astype(int)).max()), 3)

    def test_without_chrome_a_static_band_is_unrecovered(self):
        base = staff(notes=(200, 400))
        images = [with_band(with_cursor(base, x)) for x in (150, 350, 550)]
        _out, info = rs.compose_members(images, float(GAP))
        self.assertGreater(info["unrecovered_columns"], 0)
        self.assertLess(info["unrecovered_px"], 20 * 900)  # rows of the band, not whole columns


class SettleChromeTest(unittest.TestCase):
    def test_band_clear_of_notation_is_paper_filled(self):
        base = staff(notes=(650,))
        comp = with_band(base)
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        out, info = rs.settle_chrome(comp, [comp, comp], chrome, float(GAP))
        self.assertEqual(info["touched"], [])
        self.assertGreater(info["filled_px"], 0)
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        self.assertEqual(int((hsv[..., 1] > 30).sum()), 0)
        self.assertTrue((out[100:] == comp[100:]).all())  # nothing outside the chrome changes

    def test_band_touching_notation_is_kept_near_it_and_reported(self):
        base = staff(notes=(650,), top=30)  # the stem reaches into the band rows
        comp = with_band(base, rows=(0, 12))
        cv2.line(comp, (655, 4), (655, 30), (20, 20, 20), 2)
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        out, info = rs.settle_chrome(comp, [comp], chrome, float(GAP))
        self.assertEqual(len(info["touched"]), 1)
        x0, y0, x1, y1 = info["touched"][0]
        self.assertTrue(x0 <= 655 < x1 and y0 <= 4, info["touched"])
        self.assertTrue((out[0:14, 650:661] == comp[0:14, 650:661]).all())  # the stem and the band around it are kept
        self.assertTrue(info["_kept_mask"][4, 655])
        self.assertGreater(info["filled_px"], 0)  # band far from the stem: chrome only, paper-filled
        self.assertTrue((out[0:12, 800] == out[50, 5]).all())
        self.assertTrue((out[14:] == comp[14:]).all())

    def _band_with_mark(self, color):
        base = staff(notes=(650,))
        comps = []
        for k in range(3):
            c = with_band(base)
            c[3:9, 700:706] = color  # a persistent mark inside the band
            comps.append(c)
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        return comps, chrome

    def test_faint_gray_mark_inside_the_band_is_kept(self):
        comps, chrome = self._band_with_mark((150, 150, 150))
        out, info = rs.settle_chrome(comps[0], comps, chrome, float(GAP))
        self.assertEqual(len(info["touched"]), 1)
        self.assertTrue((out[3:9, 700:706] == 150).all())
        self.assertGreater(info["filled_px"], 0)

    def test_tinted_mark_inside_the_band_is_kept(self):
        comps, chrome = self._band_with_mark((60, 60, 200))
        out, info = rs.settle_chrome(comps[0], comps, chrome, float(GAP))
        self.assertEqual(len(info["touched"]), 1)
        self.assertTrue((out[3:9, 700:706] == (60, 60, 200)).all())

    def test_mark_in_one_member_only_blocks_the_fill_there(self):
        base = staff(notes=(650,))
        comp = with_band(base)
        marked = comp.copy()
        cv2.circle(marked, (720, 6), 2, (150, 150, 150), -1)
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        out, info = rs.settle_chrome(comp, [comp, marked, comp], chrome, float(GAP))
        self.assertEqual(len(info["touched"]), 1)
        self.assertTrue((out[6, 715:726] == comp[6, 715:726]).all())  # not paper-filled under the mark

    def test_antialiased_band_edge_is_chrome(self):
        base = staff(notes=(650,))
        comp = with_band(base)
        comp[12, 600:] = (235, 210, 240)  # half pink, half paper
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        _out, info = rs.settle_chrome(comp, [comp, comp], chrome, float(GAP))
        self.assertEqual(info["touched"], [])

    def _band_with_stroke(self, box, members=3, shown=(0, 1, 2)):
        base = staff(notes=(650,))
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        x0, y0, x1, y1 = box
        comps = []
        for k in range(members):
            c = with_band(base)
            if k in shown:
                c[y0:y1, x0:x1] = 20  # a gray-20 stroke one pixel thick
            comps.append(c)
        return comps, chrome

    def test_persistent_one_pixel_strokes_inside_the_band_are_kept(self):
        for box in ((700, 6, 706, 7), (700, 3, 701, 9)):  # 6x1 horizontal, 1x6 vertical
            comps, chrome = self._band_with_stroke(box)
            out, info = rs.settle_chrome(comps[0], comps, chrome, float(GAP))
            self.assertEqual(len(info["touched"]), 1, box)
            x0, y0, x1, y1 = box
            self.assertTrue((out[y0:y1, x0:x1] == 20).all(), box)
            self.assertTrue(info["_kept_mask"][y0:y1, x0:x1].all(), box)
            self.assertGreater(info["filled_px"], 0, box)  # the band away from the stroke is still filled

    def test_one_pixel_stroke_in_a_minority_of_members_is_residue(self):
        comps, chrome = self._band_with_stroke((700, 6, 706, 7), shown=(1,))
        out, info = rs.settle_chrome(comps[0], comps, chrome, float(GAP))
        self.assertEqual(info["touched"], [])
        self.assertFalse((out[6, 700:706] == 20).any())

    def test_one_pixel_stroke_shifted_by_a_pixel_is_still_persistent(self):
        base = staff(notes=(650,))
        chrome = np.zeros(base.shape[:2], bool)
        chrome[0:14, 598:] = True
        comps = []
        for dy in (0, 1, 0):
            c = with_band(base)
            c[6 + dy, 700:706] = 20
            comps.append(c)
        _out, info = rs.settle_chrome(comps[0], comps, chrome, float(GAP))
        self.assertEqual(len(info["touched"]), 1)

class ChromePipelineProbeTest(unittest.TestCase):
    """Codex audit F2 probes through build_episodes -> build_occurrences -> build_strip with the
    job's chrome detector: a static pink band over four displays; display 2 shows a radius-2 dot
    below the band in 8 of its 32 frames and a persistent gray-150 mark inside the band; display 3
    a persistent tinted mark inside the band."""

    DOT = (1000, 22)
    GRAY = (1100, 3, 1106, 9)
    TINT = (1200, 3, 1206, 9)

    @classmethod
    def setUpClass(cls):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from app.pipeline import reflow_occurrences as ro
        from app.pipeline import system_tracking as st
        from reflow_fixture import build, loader, show, strip

        frames = []
        for k, (bars, slots) in enumerate([(4, 8), (3, 8), (5, 8), (3, 6)]):
            for i, (t, img) in enumerate(show(strip(4, bars_per_system=bars, slots_per_bar=slots), k * 8.0, 8.0, seed=k + 1)):
                img = img.copy()
                img[0:12, 900:] = PINK
                if k == 1:
                    if 12 <= i < 20:
                        cv2.circle(img, cls.DOT, 2, (0, 0, 0), -1)
                    x0, y0, x1, y1 = cls.GRAY
                    img[y0:y1, x0:x1] = 150
                if k == 2:
                    x0, y0, x1, y1 = cls.TINT
                    img[y0:y1, x0:x1] = (60, 60, 200)
                frames.append((t, img))
        manifest, images = build(frames)
        load = loader(images)
        tracking = st.build_episodes(manifest, load)
        occ = ro.build_occurrences(tracking, manifest, load)
        chrome, cls.chrome_info = rs.job_screen_chrome(manifest, load)
        cls.chrome_found = chrome is not None
        cls.strips = []
        for system in occ["systems"]:
            if system["included"]:
                cls.strips.append(rs.build_strip(system, manifest, load, chrome=chrome if chrome is not None else False))

    @staticmethod
    def _dark(img, box_crop, rec, thr):
        x0, y0 = rec["box_crop"][0], rec["box_crop"][1]
        seg = img[max(0, box_crop[1] - y0):max(0, box_crop[3] - y0), max(0, box_crop[0] - x0):max(0, box_crop[2] - x0)]
        return int((cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY) < thr).sum()) if seg.size else 0

    def test_chrome_is_detected_and_four_displays_are_placed(self):
        self.assertTrue(self.chrome_found, self.chrome_info)
        self.assertEqual(len(self.strips), 4)

    def test_dot_below_a_static_band_is_minority_content(self):
        _img, rec = self.strips[1]
        self.assertIn(rs.MINORITY_ISSUE, rec["issues"])
        ev = rec["minority_content"]["events"]
        self.assertEqual(len(ev), 1)
        b = ev[0]["box_crop"]
        self.assertTrue(b[0] <= self.DOT[0] <= b[2] and b[1] <= self.DOT[1] <= b[3], b)
        alt = rec["minority_content"]["alternates"][0]
        box = [self.DOT[0] - 3, self.DOT[1] - 3, self.DOT[0] + 4, self.DOT[1] + 4]
        self.assertGreaterEqual(self._dark(rec["_alternate_images"][0], box, {"box_crop": alt["box_crop"]}, 128), 8)
        for k in (0, 2, 3):
            self.assertNotIn(rs.MINORITY_ISSUE, self.strips[k][1]["issues"])

    def test_gray_and_tinted_marks_inside_the_band_are_kept_and_flagged(self):
        for k, mark in ((1, self.GRAY), (2, self.TINT)):
            img, rec = self.strips[k]
            self.assertIn(rs.OVERLAY_COVERS_NOTATION, rec["issues"], k)
            self.assertLessEqual(rec["box_crop"][1], mark[1], k)  # the mark's rows are not trimmed away
            self.assertGreaterEqual(self._dark(img, mark, rec, 200), 30, k)
        for k in (0, 3):
            rec = self.strips[k][1]
            self.assertNotIn(rs.OVERLAY_COVERS_NOTATION, rec["issues"], k)
            self.assertGreater(rec["screen_chrome"]["filled_px"], 0, k)
            hsv = cv2.cvtColor(self.strips[k][0], cv2.COLOR_BGR2HSV)
            self.assertEqual(int(((hsv[..., 1] > 30) & (hsv[..., 2] > 150)).sum(axis=0).max()), 0, k)


class ThinStrokePipelineProbeTest(unittest.TestCase):
    """Codex finding G2: a persistent gray-20 stroke one pixel thick inside a static chrome band
    (display 1: 6x1 horizontal, display 2: 1x6 vertical) through build_episodes ->
    build_occurrences -> build_strip with the job's chrome detector is kept, its rows are not
    trimmed, and the strip is flagged OVERLAY_COVERS_NOTATION."""

    HSTROKE = (1100, 6, 1106, 7)
    VSTROKE = (1200, 3, 1201, 9)

    @classmethod
    def setUpClass(cls):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from app.pipeline import reflow_occurrences as ro
        from app.pipeline import system_tracking as st
        from reflow_fixture import build, loader, show, strip

        frames = []
        for k, (bars, slots) in enumerate([(4, 8), (3, 8), (5, 8), (3, 6)]):
            for _i, (t, img) in enumerate(show(strip(4, bars_per_system=bars, slots_per_bar=slots), k * 8.0, 8.0, seed=k + 1)):
                img = img.copy()
                img[0:12, 900:] = PINK
                mark = {1: cls.HSTROKE, 2: cls.VSTROKE}.get(k)
                if mark is not None:
                    x0, y0, x1, y1 = mark
                    img[y0:y1, x0:x1] = 20
                frames.append((t, img))
        manifest, images = build(frames)
        load = loader(images)
        tracking = st.build_episodes(manifest, load)
        occ = ro.build_occurrences(tracking, manifest, load)
        chrome, cls.chrome_info = rs.job_screen_chrome(manifest, load)
        cls.chrome_found = chrome is not None
        cls.strips = []
        for system in occ["systems"]:
            if system["included"]:
                cls.strips.append(rs.build_strip(system, manifest, load, chrome=chrome if chrome is not None else False))

    def test_thin_strokes_inside_the_band_are_kept_and_flagged(self):
        self.assertTrue(self.chrome_found, self.chrome_info)
        self.assertEqual(len(self.strips), 4)
        for k, mark in ((1, self.HSTROKE), (2, self.VSTROKE)):
            img, rec = self.strips[k]
            self.assertIn(rs.OVERLAY_COVERS_NOTATION, rec["issues"], k)
            self.assertLessEqual(rec["box_crop"][1], mark[1], k)  # the stroke's rows are not trimmed away
            self.assertGreaterEqual(ChromePipelineProbeTest._dark(img, mark, rec, 128), 5, k)
        for k in (0, 3):
            rec = self.strips[k][1]
            self.assertNotIn(rs.OVERLAY_COVERS_NOTATION, rec["issues"], k)
            self.assertGreater(rec["screen_chrome"]["filled_px"], 0, k)


class LostInkRestoreTest(unittest.TestCase):
    """Codex finding H3: the unregistered per-pixel median erases a thin stroke drawn one pixel
    apart in each member (+-1 px jitter); persistent ink missing from the composite is restored
    from one representative member and reported. Output pixels are tested, not metadata."""

    STROKE = (700, 760)  # x range of a gray-20 stroke one pixel thick, at row 120 + dy

    def _members(self, dys, band=False, cursor_xs=None):
        base = staff(notes=(300, 400))
        out = []
        for k, dy in enumerate(dys):
            c = with_band(base) if band else base.copy()
            if dy is not None:
                c[120 + dy if not band else 6 + dy, self.STROKE[0]:self.STROKE[1]] = 20
            if cursor_xs is not None:
                c = with_cursor(c, cursor_xs[k])
            out.append(c)
        return out

    def _stroke_px(self, img, row0, row1):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return int((g[row0:row1, self.STROKE[0]:self.STROKE[1]] < 128).sum())

    def test_three_way_jittered_stroke_survives_the_composite(self):
        members = self._members((-1, 0, 1))
        plain = np.rint(np.median(np.stack(members), axis=0)).astype(np.uint8)
        self.assertEqual(self._stroke_px(plain, 118, 123), 0)  # the bug: the median shows paper
        out, info = rs.compose_members(members, float(GAP))
        self.assertEqual(self._stroke_px(out, 118, 123), self.STROKE[1] - self.STROKE[0])  # one whole stroke, one row
        rows = np.flatnonzero((cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[118:123, self.STROKE[0]:self.STROKE[1]] < 128).any(axis=1))
        self.assertEqual(len(rows), 1)  # taken from one member, never a blend of rows
        self.assertEqual(info["ink_restored"]["components"], 1)
        self.assertEqual(info["ink_restored"]["px"], self.STROKE[1] - self.STROKE[0])
        x0, y0, x1, y1 = info["ink_restored"]["boxes"][0]
        self.assertEqual((x0, x1), self.STROKE)
        # nothing else changes: the staff and notes are the plain median
        mask = np.ones(out.shape[:2], bool)
        mask[118:123, self.STROKE[0]:self.STROKE[1]] = False
        self.assertTrue((out[mask] == plain[mask]).all())

    def test_stroke_in_a_minority_of_members_is_not_restored(self):
        members = self._members((0, None, None))
        out, info = rs.compose_members(members, float(GAP))
        self.assertEqual(self._stroke_px(out, 118, 123), 0)
        self.assertEqual(info["ink_restored"]["px"], 0)

    def test_registered_content_restores_nothing(self):
        out, info = rs.compose_members(self._members((0, 0, 0)), float(GAP))
        self.assertEqual(self._stroke_px(out, 118, 123), self.STROKE[1] - self.STROKE[0])
        self.assertEqual(info["ink_restored"]["px"], 0)

    def test_moving_cursor_is_not_restored(self):
        members = self._members((-1, 0, 1), cursor_xs=(200, 450, 600))
        out, info = rs.compose_members(members, float(GAP))
        self.assertEqual(self._stroke_px(out, 118, 123), self.STROKE[1] - self.STROKE[0])
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        self.assertEqual(int((hsv[..., 1] > 20).sum()), 0)  # no cursor tint anywhere
        self.assertEqual(info["ink_restored"]["components"], 1)

    def test_jittered_stroke_inside_a_chrome_band_survives_settle_chrome(self):
        members = self._members((-1, 0, 1), band=True)
        chrome = np.zeros(members[0].shape[:2], bool)
        chrome[0:12, 600:] = True
        comp, info = rs.compose_members(members, float(GAP), chrome=chrome)
        self.assertEqual(info["ink_restored"]["components"], 1)
        out, cinfo = rs.settle_chrome(comp, members, chrome, float(GAP))
        self.assertEqual(len(cinfo["touched"]), 1)
        self.assertEqual(self._stroke_px(out, 4, 9), self.STROKE[1] - self.STROKE[0])
        self.assertGreater(cinfo["filled_px"], 0)


class JitteredStrokePipelineProbeTest(unittest.TestCase):
    """Codex finding H3 probe: tracker -> occurrences -> build_strip, a gray-20 6x1 stroke inside a
    static chrome band drawn in every observation of display 1, cycling through rows 5, 6 and 7.
    The strip must contain the stroke's pixels (not only flag the chrome)."""

    STROKE_X = (1100, 1106)

    @classmethod
    def setUpClass(cls):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from app.pipeline import reflow_occurrences as ro
        from app.pipeline import system_tracking as st
        from reflow_fixture import build, loader, show, strip

        frames = []
        for k, (bars, slots) in enumerate([(4, 8), (3, 8), (5, 8), (3, 6)]):
            for i, (t, img) in enumerate(show(strip(4, bars_per_system=bars, slots_per_bar=slots), k * 8.0, 8.0, seed=k + 1)):
                img = img.copy()
                img[0:12, 900:] = PINK
                if k == 1:
                    img[5 + i % 3, cls.STROKE_X[0]:cls.STROKE_X[1]] = 20
                frames.append((t, img))
        manifest, images = build(frames)
        load = loader(images)
        tracking = st.build_episodes(manifest, load)
        occ = ro.build_occurrences(tracking, manifest, load)
        chrome, cls.chrome_info = rs.job_screen_chrome(manifest, load)
        cls.chrome_found = chrome is not None
        cls.strips = []
        for system in occ["systems"]:
            if system["included"]:
                cls.strips.append(rs.build_strip(system, manifest, load, chrome=chrome if chrome is not None else False))

    def test_jittered_stroke_pixels_survive_in_the_strip(self):
        self.assertTrue(self.chrome_found, self.chrome_info)
        self.assertEqual(len(self.strips), 4)
        img, rec = self.strips[1]
        box = (self.STROKE_X[0], 4, self.STROKE_X[1], 9)
        self.assertLessEqual(rec["box_crop"][1], 5)  # the stroke's rows are not trimmed away
        self.assertGreaterEqual(ChromePipelineProbeTest._dark(img, box, rec, 128), 5)
        self.assertIn(rs.OVERLAY_COVERS_NOTATION, rec["issues"])
        self.assertGreaterEqual(rec["ink_restored"]["components"], 1)
        self.assertTrue(rec["ink_restored"]["from_obs_ids"])
        for k in (0, 2, 3):
            rec = self.strips[k][1]
            self.assertEqual(rec["ink_restored"]["px"], 0, k)
            self.assertNotIn(rs.OVERLAY_COVERS_NOTATION, rec["issues"], k)

if __name__ == "__main__":
    unittest.main()
