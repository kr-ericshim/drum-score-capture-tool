"""Clean system strips (reflow_strips)."""

import unittest

import cv2
import numpy as np

from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as st
from drum_score_fixture import Overlay, groove_notes, render, strip_spec
from reflow_fixture import STEP, build, loader, show, strip


def staff_row(width=1800, gap=14, top=60, height=200, preview_at=None):
    img = np.full((height, width, 3), 255, np.uint8)
    ys = [top + k * gap for k in range(5)]
    segments = [(20, width - 20)] if preview_at is None else [(20, preview_at), (preview_at + 10, width - 20)]
    for x0, x1 in segments:
        for y in ys:
            cv2.line(img, (x0, y), (x1, y), (0, 0, 0), 1)
    for x in range(300, (preview_at or width) - 50, 350):
        cv2.line(img, (x, ys[0]), (x, ys[4]), (0, 0, 0), 2)
    if preview_at is not None:
        cv2.line(img, (preview_at - 3, ys[0]), (preview_at - 3, ys[4]), (0, 0, 0), 4)  # final barline
        c = preview_at + 16  # percussion clef: two short thick bars over the middle lines
        cv2.rectangle(img, (c, ys[1]), (c + 3, ys[3]), (0, 0, 0), -1)
        cv2.rectangle(img, (c + 8, ys[1]), (c + 11, ys[3]), (0, 0, 0), -1)
    region = {"staff_y": [float(y) for y in ys], "staff_gap_px": float(gap), "staff_x": [20, width - 20]}
    return img, region


class PreviewTailTest(unittest.TestCase):
    def test_next_system_start_is_found(self):
        img, region = staff_row(preview_at=1500)
        tail = rs.find_preview_tail(img, region)
        self.assertIsNotNone(tail)
        self.assertGreaterEqual(tail["cut_x"], 1495)
        self.assertLessEqual(tail["cut_x"], 1505)

    def test_continuous_staff_is_never_cut(self):
        img, region = staff_row()
        self.assertIsNone(rs.find_preview_tail(img, region))

    def test_break_without_clef_is_not_a_preview(self):
        img, region = staff_row(preview_at=1500)
        img[:, 1514:1530] = 255  # remove the clef bars
        for y in region["staff_y"]:
            cv2.line(img, (1510, int(y)), (1780, int(y)), (0, 0, 0), 1)
        self.assertIsNone(rs.find_preview_tail(img, region))


class StaffBreakTest(unittest.TestCase):
    def test_gap_in_one_staff_line_is_not_a_break(self):
        # Audit probe: removing only line 1 at x=70..79 returned [(70, 80)] (the
        # per-line masks were ANDed, so a gap in one line looked like a break in all five).
        img, region = staff_row()
        y0 = int(region["staff_y"][0])
        img[y0 - 1:y0 + 2, 70:80] = 255
        ink = rs.sd.ink_mask(img)
        self.assertEqual(rs.staff_breaks(ink, region["staff_y"], 20, 1780), [])

    def test_gap_in_all_five_lines_is_a_break(self):
        img, region = staff_row()
        img[:, 70:80] = 255
        ink = rs.sd.ink_mask(img)
        self.assertEqual(rs.staff_breaks(ink, region["staff_y"], 20, 1780), [(70, 80)])


def system_image(seed):
    """A rendered single system (staff x 40..1110) with a percussion clef at its start."""
    img = render(groove_notes(strip_spec(width=1150, height=190, margin_x=40), seed=seed))
    img[:, 41:60] = 255
    for y in (67, 81, 95, 109, 123):
        cv2.line(img, (40, y), (60, y), (0, 0, 0), 1)
    cv2.rectangle(img, (44, 81), (47, 109), (0, 0, 0), -1)
    cv2.rectangle(img, (52, 81), (55, 109), (0, 0, 0), -1)
    return img


def preview_frames(cur, nxt, n=12, t0=0.0):
    def with_preview(phase):
        img = np.full((190, 1400, 3), 255, np.uint8)
        img[:, :1150] = cur
        img[:, 1180:1400] = nxt[:, 40:260]  # first bar of the next system beside the current one
        cv2.line(img, (int(40 + phase * 1070), 20), (int(40 + phase * 1070), 170), (220, 120, 40), 3)
        return img
    return [(t0 + i * STEP, with_preview((i + 0.5) / n)) for i in range(n)]


def full_frames(sys_img, n=12, t0=0.0):
    out = []
    for i in range(n):
        img = np.full((190, 1400, 3), 255, np.uint8)
        img[:, :1150] = sys_img
        x = int(40 + (i + 0.5) / n * 1070)
        cv2.line(img, (x, 20), (x, 170), (220, 120, 40), 3)
        out.append((t0 + i * STEP, img))
    return out


class PreviewDestinationTest(unittest.TestCase):
    """A preview tail is cut only when the next occurrence is verified to start with it."""

    def _systems(self, frames, split):
        manifest, images = build(frames)
        obs = manifest["observations"]
        mk = lambda sid, os_: {"id": sid, "observations": [{"obs_id": o["id"], "region_id": o["system_regions"][0]["region_id"]} for o in os_]}
        return manifest, loader(images), [mk("sys-001", obs[:split]), mk("sys-002", obs[split:])]

    def test_tail_shown_at_next_start_is_cut_with_destination_mapping(self):
        cur, nxt = system_image(7), system_image(8)
        manifest, load, systems = self._systems(preview_frames(cur, nxt) + full_frames(nxt, t0=3.0), 12)
        _img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        tail = rec["preview_tail"]
        self.assertIsNotNone(tail)
        self.assertTrue(tail["verified"], tail)
        self.assertTrue(tail["cut"])
        self.assertEqual(tail["destination_system_id"], "sys-002")
        self.assertLessEqual(abs(tail["destination_crop_x0"] - 40), 3)  # tail x 1180 -> next system x 40
        self.assertLessEqual(rec["box_crop"][2], 1180)
        self.assertEqual(rec["issues"], [])

    def test_tail_not_found_at_next_start_is_kept_and_flagged(self):
        cur, nxt, other = system_image(7), system_image(8), system_image(9)
        manifest, load, systems = self._systems(preview_frames(cur, nxt) + full_frames(other, t0=3.0), 12)
        _img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        tail = rec["preview_tail"]
        self.assertIsNotNone(tail)
        self.assertFalse(tail["verified"], tail)
        self.assertFalse(tail["cut"])
        self.assertGreaterEqual(rec["box_crop"][2], 1390)  # nothing removed
        self.assertEqual(rec["issues"], ["PREVIEW_TAIL_UNVERIFIED"])

    def test_tail_without_a_following_system_is_kept_and_flagged(self):
        cur, nxt = system_image(7), system_image(8)
        manifest, load, systems = self._systems(preview_frames(cur, nxt), 12)
        _img, rec = rs.build_strip(systems[0], manifest, load, next_systems=[])
        self.assertFalse(rec["preview_tail"]["cut"])
        self.assertEqual(rec["issues"], ["PREVIEW_TAIL_UNVERIFIED"])


class PreviewCutRemovesOnlyVerifiedPixelsTest(unittest.TestCase):
    """Audit round 2, P0: the destination check covered only top-3..bottom+3 gaps of the tail,
    but the cut removed the strip's full height (a unique "A" above that band was cut with
    coverage 1.0), and a destination with included:false still permitted the cut."""

    def _systems(self, frames, split, dest_included=True):
        manifest, images = build(frames)
        obs = manifest["observations"]
        mk = lambda sid, os_, inc: {"id": sid, "included": inc,
                                    "observations": [{"obs_id": o["id"], "region_id": o["system_regions"][0]["region_id"]} for o in os_]}
        return manifest, loader(images), [mk("sys-001", obs[:split], True), mk("sys-002", obs[split:], dest_included)]

    @staticmethod
    def _with_a(frames, x):
        out = []
        for t, im in frames:
            im = im.copy()
            cv2.putText(im, "A", (x, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)  # above the checked band (y < 25)
            out.append((t, im))
        return out

    def test_unique_mark_above_the_band_keeps_the_tail(self):
        cur, nxt = system_image(7), system_image(8)
        manifest, load, systems = self._systems(self._with_a(preview_frames(cur, nxt), 1250) + full_frames(nxt, t0=3.0), 12)
        img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        tail = rec["preview_tail"]
        self.assertFalse(tail["cut"], tail)
        self.assertEqual(rec["issues"], ["PREVIEW_TAIL_UNVERIFIED"])
        self.assertGreaterEqual(rec["box_crop"][2], 1390)  # nothing removed
        removed = tail["checks"][0]["removed_pixels"]
        self.assertEqual(removed["reason"], "removed_ink_not_at_destination")
        bx = removed["component_box_crop"]
        self.assertTrue(bx[0] <= 1255 <= bx[2] and bx[3] <= 25, bx)  # the "A" itself
        self.assertNotIn("uncut", rec)

    def test_the_same_mark_at_the_destination_start_allows_the_cut(self):
        cur, nxt = system_image(7), system_image(8)
        # tail x 1250 -> destination x 1250 - 1180 + 40 = 110
        frames = self._with_a(preview_frames(cur, nxt), 1250) + self._with_a(full_frames(nxt, t0=3.0), 110)
        manifest, load, systems = self._systems(frames, 12)
        img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        tail = rec["preview_tail"]
        self.assertTrue(tail["cut"], tail)
        rb = tail["removed_box_crop"]
        self.assertEqual((rb[1], rb[3]), (0, 190))  # every row of the strip box was verified
        removed = tail["checks"][0]["removed_pixels"]
        self.assertTrue(removed["verified"])
        self.assertLessEqual(removed["dest_ink_box_crop"][1], 18)  # the "A" was among the verified pixels

    @staticmethod
    def _with_dot(frames, x, y, size):
        out = []
        for t, im in frames:
            im = im.copy()
            im[y:y + size, x:x + size] = 0
            out.append((t, im))
        return out

    def test_a_speck_in_the_tail_does_not_keep_the_tail(self):
        # bF69 sys-010: one 1-px speck the destination does not draw kept a whole verified tail,
        # so the next system's first bar was printed twice
        cur, nxt = system_image(7), system_image(8)
        manifest, load, systems = self._systems(self._with_dot(preview_frames(cur, nxt), 1250, 15, 1) + full_frames(nxt, t0=3.0), 12)
        _img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        tail = rec["preview_tail"]
        self.assertTrue(tail["cut"], tail)
        self.assertNotIn("PREVIEW_TAIL_UNVERIFIED", rec["issues"])

    def test_a_dot_sized_mark_in_the_tail_still_keeps_the_tail(self):
        cur, nxt = system_image(7), system_image(8)
        manifest, load, systems = self._systems(self._with_dot(preview_frames(cur, nxt), 1250, 12, 4) + full_frames(nxt, t0=3.0), 12)
        _img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        tail = rec["preview_tail"]
        self.assertFalse(tail["cut"], tail)
        self.assertEqual(tail["checks"][0]["removed_pixels"]["reason"], "removed_ink_not_at_destination")
        self.assertEqual(rec["issues"], ["PREVIEW_TAIL_UNVERIFIED"])

    def test_excluded_destination_does_not_permit_a_cut(self):
        cur, nxt = system_image(7), system_image(8)
        manifest, load, systems = self._systems(preview_frames(cur, nxt) + full_frames(nxt, t0=3.0), 12, dest_included=False)
        _img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        self.assertFalse(rec["preview_tail"]["cut"])
        self.assertEqual(rec["preview_tail"]["reason"], "no_next_included_system")
        self.assertEqual(rec["issues"], ["PREVIEW_TAIL_UNVERIFIED"])

    def test_cut_is_made_in_an_empty_column_not_through_the_last_flag(self):
        # system_image(7)'s last eighth flag reaches x=1118, past the staff end (1110) where
        # the staff break starts; the old cut at the break start sliced it.
        cur, nxt = system_image(7), system_image(8)
        manifest, load, systems = self._systems(preview_frames(cur, nxt) + full_frames(nxt, t0=3.0), 12)
        img, rec = rs.build_strip(systems[0], manifest, load, next_systems=systems[1:])
        tail = rec["preview_tail"]
        self.assertTrue(tail["cut"], tail)
        ink_cols = np.flatnonzero((cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY) < 128).any(axis=0))
        self.assertGreater(rec["box_crop"][2], int(ink_cols.max()))  # every column of the current system kept
        self.assertLess(rec["box_crop"][2], 1180)
        self.assertEqual(rec["uncut"]["box_crop"][2], 1400)

    def test_cut_is_undone_when_the_destination_strip_does_not_hold_the_tail(self):
        recs = [{"system_id": "sys-001", "box_crop": [0, 0, 1149, 190], "size": [1149, 190], "staff_y_strip": [60.0] * 5, "issues": [],
                 "preview_tail": {"cut": True, "verified": True, "destination_system_id": "sys-002", "dest_ink_box_crop": [38, 5, 258, 128]},
                 "uncut": {"box_crop": [0, 0, 1400, 190], "size": [1400, 190], "staff_y_strip": [60.0] * 5}},
                {"system_id": "sys-002", "box_crop": [30, 20, 1120, 180], "issues": [], "preview_tail": None}]
        restored = rs.check_destination_strips(recs)
        self.assertEqual([r["system_id"] for r in restored], ["sys-001"])
        self.assertEqual(recs[0]["box_crop"], [0, 0, 1400, 190])
        self.assertFalse(recs[0]["preview_tail"]["cut"])
        self.assertIn("PREVIEW_TAIL_UNVERIFIED", recs[0]["issues"])


class ComposeMembersTest(unittest.TestCase):
    def test_moving_colored_playhead_is_removed(self):
        spec = strip(3)
        images = [render(spec, [Overlay("box", position=p, color=(230, 160, 60))]) for p in np.linspace(0.1, 0.9, 7)]
        clean = render(spec, [])
        out, info = rs.compose_members(images, 12.0)
        self.assertEqual(info["unrecovered_columns"], 0)
        self.assertGreaterEqual(info["members_used"], 5)
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        self.assertLess(int(((hsv[..., 1] > 60) & (hsv[..., 2] > 120)).sum()), 50)
        self.assertLess(float(np.abs(out.astype(int) - clean.astype(int)).mean()), 3.0)

    def test_single_member_reports_covered_columns(self):
        spec = strip(3)
        img = render(spec, [Overlay("box", position=0.5, color=(230, 160, 60))])
        _out, info = rs.compose_members([img], 12.0)
        self.assertGreater(info["unrecovered_columns"], 0)


class BuildStripTest(unittest.TestCase):
    def test_strip_keeps_marks_above_and_text_below(self):
        spec = strip(4, numbers=True)
        frames = show(spec, 0.0, 3.0, seed=1)
        # add a text line below and a mark above the staff in every frame (score text must be kept)
        marked = []
        for t, img in frames:
            img = img.copy()
            cv2.putText(img, "la la la", (300, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
            cv2.circle(img, (900, 22), 5, (0, 0, 0), 2)
            marked.append((t, img))
        manifest, images = build(marked)
        load = loader(images)
        occ = ro.build_occurrences(st.build_episodes(manifest, load), manifest, load)
        system = [s for s in occ["systems"] if s["included"]][0]
        img, rec = rs.build_strip(system, manifest, load)
        x0, y0, x1, y1 = rec["box_crop"]
        self.assertLessEqual(y0, 22 - 5)
        self.assertGreaterEqual(y1, 175)
        self.assertEqual(img.shape[:2], (y1 - y0, x1 - x0))
        self.assertIsNone(rec["preview_tail"])


if __name__ == "__main__":
    unittest.main()
