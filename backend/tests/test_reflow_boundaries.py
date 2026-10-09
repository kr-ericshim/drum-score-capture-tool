"""Measure-boundary classifier (reflow_boundaries): negative and positive controls.

Synthetic strips are drawn with anti-aliased strokes; barlines are registered against
three independently degraded renders of the same strip (the member observations).
"""

import unittest
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.pipeline import reflow_boundaries as rb
from app.pipeline import system_detect as sd

G = 16  # staff gap px
TOP = 92
MEASURE_W = 300
PREFIX_W = 110
INK = (25, 25, 25)


def bar_x(k: int) -> int:
    """x of barline k (k = 1..3 internal, 4 = final)."""
    return PREFIX_W + k * MEASURE_W


def _lines() -> List[int]:
    return [TOP + i * G for i in range(5)]


def make_strip(*, tie_at: Optional[int] = None, lyric_across: Optional[int] = None, lyrics: bool = False,
               repeat_at: Optional[int] = None, dot_at: Optional[Tuple[int, int]] = None, broken_tie_at: Optional[int] = None,
               blur: float = 0.0, faint_dot_at: Optional[Tuple[int, int]] = None, slur_above_at: Optional[int] = None,
               volta_end_at: Optional[int] = None, seed: int = 0) -> Tuple[np.ndarray, Dict[str, Any]]:
    w = PREFIX_W + 4 * MEASURE_W + 30
    h = 250
    img = np.full((h, w, 3), 252, np.uint8)
    ls = _lines()
    x_start, x_end = 20, bar_x(4)
    for y in ls:
        cv2.line(img, (x_start, y), (x_end, y), INK, 1, cv2.LINE_AA)
    # percussion clef: two short thick bars over the middle lines
    for cx in (34, 44):
        cv2.rectangle(img, (cx, ls[1]), (cx + 4, ls[3]), INK, -1)
    for k in range(1, 5):
        x = bar_x(k)
        cv2.rectangle(img, (x, ls[0]), (x + 1, ls[4]), INK, -1)
    for m in range(4):
        x0 = PREFIX_W + m * MEASURE_W
        xs = [x0 + 60, x0 + 120, x0 + 180, x0 + 240]
        for i, x in enumerate(xs):
            y = ls[2] + G // 2 if i % 2 == 0 else ls[1] + G // 2
            cv2.ellipse(img, (x, y), (7, 5), -20, 0, 360, INK, -1, cv2.LINE_AA)
            cv2.line(img, (x + 7, y), (x + 7, ls[0] - 2 * G), INK, 1, cv2.LINE_AA)
        for a, b in ((xs[0], xs[1]), (xs[2], xs[3])):
            cv2.rectangle(img, (a + 7, ls[0] - 2 * G), (b + 7, ls[0] - 2 * G + 3), INK, -1)
        if lyrics:
            cv2.putText(img, "la la", (x0 + 70, ls[4] + 3 * G), cv2.FONT_HERSHEY_SIMPLEX, 0.6, INK, 1, cv2.LINE_AA)
    if tie_at is not None:
        x = bar_x(tie_at)
        cv2.ellipse(img, (x, ls[4] + G), (75, 14), 0, 0, 180, INK, 2, cv2.LINE_AA)
    if broken_tie_at is not None:
        x = bar_x(broken_tie_at)
        cv2.ellipse(img, (x, ls[4] + G), (75, 14), 0, 0, 180, INK, 2, cv2.LINE_AA)
        seam = _proposed_seam_x(broken_tie_at)
        img[ls[4] + G - 2: h, seam - 1:seam + 2] = 252  # a 3-px gap in the stroke right at the seam
    if slur_above_at is not None:
        x = bar_x(slur_above_at)
        cv2.ellipse(img, (x, ls[0] - 3 * G), (90, 12), 0, 180, 360, INK, 1, cv2.LINE_AA)
    if lyric_across is not None:
        x = bar_x(lyric_across)
        cv2.putText(img, "together", (x - 40, ls[4] + 5 * G), cv2.FONT_HERSHEY_SIMPLEX, 0.6, INK, 1, cv2.LINE_AA)
    if repeat_at is not None:
        x = bar_x(repeat_at)
        cv2.rectangle(img, (x - 8, ls[0]), (x - 4, ls[4]), INK, -1)  # thin stroke + thick stroke = end repeat
        for yc in ((ls[1] + ls[2]) // 2, (ls[2] + ls[3]) // 2):
            cv2.circle(img, (x - 16, yc), 2, INK, -1, cv2.LINE_AA)
    if volta_end_at is not None:
        x = _proposed_seam_x(volta_end_at)
        cv2.line(img, (x - 200, ls[0] - 4 * G), (x - 5, ls[0] - 4 * G), INK, 1, cv2.LINE_AA)
    if dot_at is not None:
        img[dot_at[1], dot_at[0]] = INK
    if faint_dot_at is not None:
        img[faint_dot_at[1], faint_dot_at[0]] = (190, 190, 190)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    record = {"system_id": "sys-t", "staff_y_strip": [float(y) for y in ls], "staff_gap_px": float(G),
              "staff_x_strip": [x_start, x_end], "box_crop": [0, 0, w, h], "size": [w, h], "layout": "bottom_bar",
              "member_obs_ids": ["o1", "o2", "o3"], "issues": [], "envelope_flags": []}
    return img, record


def darken(img: np.ndarray, *, seed: int = 0, paper: int = 28, ink: int = 228, jpeg: int = 70) -> np.ndarray:
    """Dark-theme version of a light strip: light ink on a dark, slightly textured paper, JPEG-compressed."""
    rng = np.random.default_rng(seed)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    alpha = np.clip((252 - gray) / (252 - 25), 0, 1)
    h, w = gray.shape
    yy, xx = np.mgrid[0:h, 0:w]
    bg = paper + 8 * np.sin(xx / 97.0) * np.cos(yy / 41.0) + rng.normal(0, 3, (h, w))
    out = cv2.cvtColor(np.clip(bg * (1 - alpha) + ink * alpha, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def barline_fringe(img: np.ndarray) -> np.ndarray:
    """Anti-aliased fringe columns on both sides of every barline (as video scaling leaves them)."""
    ls = _lines()
    for k in (1, 2, 3, 4):
        x = bar_x(k)
        img[ls[0]:ls[4] + 1, x - 1] = (190, 190, 190)
        img[ls[0]:ls[4] + 1, x + 2] = (215, 215, 215)
    return img


def start_repeat(img: np.ndarray, k: int) -> np.ndarray:
    """Thick stroke, the barline (thin) and two dots on its right: a start repeat at barline k."""
    ls = _lines()
    x = bar_x(k)
    cv2.rectangle(img, (x - 6, ls[0]), (x - 3, ls[4]), INK, -1)
    for yc in ((ls[1] + ls[2]) // 2, (ls[2] + ls[3]) // 2):
        cv2.circle(img, (x + 8, yc), 2, INK, -1, cv2.LINE_AA)
    return img


def fused_start_repeat(img: np.ndarray, k: int) -> np.ndarray:
    """A start repeat at barline k whose dots are fused with the strokes: thick stroke, the barline (thin),
    and two dots about 0.6 gap to its right joined to it by ink (blur/compression in a video frame), so the
    strokes, the staff-line stubs between them and the dots are one component and no dot is a separate one."""
    ls = _lines()
    x = bar_x(k)
    cv2.rectangle(img, (x - 8, ls[0]), (x - 3, ls[4]), INK, -1)  # 6 px: a verified thick stroke
    for yc in ((ls[1] + ls[2]) // 2, (ls[2] + ls[3]) // 2):
        cv2.circle(img, (x + 10, yc), 3, INK, -1, cv2.LINE_AA)
        cv2.rectangle(img, (x + 1, yc - 1), (x + 9, yc + 1), INK, -1)
    return img


def _proposed_seam_x(k: int) -> int:
    """Middle of the corridor right of barline k (barline 2 px, first note head starts ~53 px after it)."""
    return bar_x(k) + 2 + 25


def observations_of(img: np.ndarray, n: int = 3, seed: int = 0) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        noisy = np.clip(img.astype(np.float32) + rng.normal(0, 2.0, img.shape), 0, 255).astype(np.uint8)
        noisy = cv2.GaussianBlur(noisy, (0, 0), 0.5)
        det = sd.detect(noisy)
        if not det["staves"]:
            continue
        st = max(det["staves"], key=lambda s: s["x"][1] - s["x"][0])
        out.append({"region_id": f"o{i + 1}-r0", "staff_gap_px": st["gap"], "staff_x": st["x"], "bars": st["bars"]})
    return out


def analyse(img, record, obs="auto"):
    if obs == "auto":
        obs = observations_of(img)
    return rb.analyse_strip(img, record, system_id=record["system_id"], observations=obs)


def boundary_at(boundaries, k):
    x = bar_x(k)
    return next(b for b in boundaries if b["barline_box"][0] - 2 <= x <= b["barline_box"][2] + 2)


class PositiveControls(unittest.TestCase):
    def test_clean_barline_seams_are_safe(self):
        img, rec = make_strip()
        an = analyse(img, rec)
        bnds = rb.strip_boundaries(an)
        self.assertEqual(len(bnds), 3, [b["barline_box"] for b in bnds])
        for b in bnds:
            self.assertEqual(b["class"], rb.SAFE, b["reason_codes"])
            self.assertEqual(b["barline_owner"], "left")
            self.assertGreater(b["seam_x"], b["barline_box"][2])

    def test_lyrics_inside_measures_do_not_block(self):
        img, rec = make_strip(lyrics=True)
        bnds = rb.strip_boundaries(analyse(img, rec))
        self.assertEqual([b["class"] for b in bnds], [rb.SAFE] * 3, [b["reason_codes"] for b in bnds])

    def test_only_the_crossed_boundary_changes(self):
        img, rec = make_strip(tie_at=2)
        bnds = rb.strip_boundaries(analyse(img, rec))
        self.assertEqual(boundary_at(bnds, 1)["class"], rb.SAFE)
        self.assertEqual(boundary_at(bnds, 3)["class"], rb.SAFE)
        self.assertEqual(boundary_at(bnds, 2)["class"], rb.LOCKED)


class NegativeControls(unittest.TestCase):
    """Injected cuts that must never be accepted (class != SAFE)."""

    def assertRejected(self, res, *, want=None):
        self.assertNotEqual(res["class"], rb.SAFE, res)
        if want is not None:
            self.assertEqual(res["class"], want, res["reasons"])

    def test_tie_crossing_the_seam_is_locked(self):
        img, rec = make_strip(tie_at=2)
        an = analyse(img, rec)
        res = rb.classify_seam(an, _proposed_seam_x(2))
        self.assertRejected(res, want=rb.LOCKED)
        self.assertTrue(any("CROSSES" in r for r in res["reasons"]))

    def test_slur_above_the_staff_is_locked(self):
        img, rec = make_strip(slur_above_at=1)
        res = rb.classify_seam(analyse(img, rec), _proposed_seam_x(1))
        self.assertRejected(res, want=rb.LOCKED)

    def test_slur_through_the_barline_is_locked(self):
        img, rec = make_strip()
        ls = _lines()
        cv2.ellipse(img, (bar_x(2), ls[3]), (80, 2 * G + 6), 0, 180, 360, INK, 2, cv2.LINE_AA)
        res = rb.classify_seam(analyse(img, rec, obs=observations_of(make_strip()[0])), _proposed_seam_x(2))
        self.assertRejected(res, want=rb.LOCKED)

    def test_broken_tie_at_the_seam_is_rejected(self):
        img, rec = make_strip(broken_tie_at=2)
        res = rb.classify_seam(analyse(img, rec), _proposed_seam_x(2))
        self.assertRejected(res)
        self.assertIn("POSSIBLE_BROKEN_STROKE", res["reasons"])

    def test_blurred_tie_is_rejected(self):
        img, rec = make_strip(tie_at=3, blur=1.2)
        sharp, _rec = make_strip(tie_at=3)
        res = rb.classify_seam(analyse(img, rec, obs=observations_of(sharp)), _proposed_seam_x(3))
        self.assertRejected(res, want=rb.LOCKED)

    def test_lyric_word_across_the_seam_is_locked(self):
        img, rec = make_strip(lyric_across=1)
        res = rb.classify_seam(analyse(img, rec), _proposed_seam_x(1))
        self.assertRejected(res, want=rb.LOCKED)

    def test_lyric_group_close_to_the_seam_is_locked(self):
        img, rec = make_strip()
        ls = _lines()
        s = _proposed_seam_x(2)
        cv2.putText(img, "ab", (s - 30, ls[4] + 4 * G), cv2.FONT_HERSHEY_SIMPLEX, 0.6, INK, 1, cv2.LINE_AA)
        cv2.putText(img, "cd", (s + 4, ls[4] + 4 * G), cv2.FONT_HERSHEY_SIMPLEX, 0.6, INK, 1, cv2.LINE_AA)
        res = rb.classify_seam(analyse(img, rec), s)
        self.assertRejected(res, want=rb.LOCKED)
        self.assertIn("TEXT_GROUP_CROSSES", res["reasons"])

    def test_repeat_sign_boundary_is_locked(self):
        img, rec = make_strip(repeat_at=2)
        an = analyse(img, rec)
        bnd = boundary_at(rb.strip_boundaries(an), 2)
        self.assertEqual(bnd["class"], rb.LOCKED, bnd["reason_codes"])
        self.assertIn("REPEAT_BOUNDARY", bnd["reason_codes"])

    def test_cut_between_repeat_dots_and_strokes_is_locked(self):
        img, rec = make_strip(repeat_at=2)
        an = analyse(img, rec)
        for x in (bar_x(2) - 11, bar_x(2) - 6, bar_x(2) - 2):  # dots|thin, thin|thick, thick|thin
            res = rb.classify_seam(an, x)
            self.assertRejected(res, want=rb.LOCKED)

    def test_one_pixel_dot_at_the_seam_is_rejected(self):
        s = _proposed_seam_x(1)
        for y in (TOP + 4 * G + 30, TOP - 40, TOP + 2 * G + 4):
            img, rec = make_strip(dot_at=(s, y))
            res = rb.classify_seam(analyse(img, rec), s)
            self.assertRejected(res)

    def test_faint_one_pixel_dot_is_rejected(self):
        s = _proposed_seam_x(3)
        img, rec = make_strip(faint_dot_at=(s - 1, TOP + 4 * G + 40))
        self.assertRejected(rb.classify_seam(analyse(img, rec), s))

    def test_line_endpoint_near_the_seam_is_rejected(self):
        img, rec = make_strip(volta_end_at=2)
        res = rb.classify_seam(analyse(img, rec), _proposed_seam_x(2))
        self.assertRejected(res, want=rb.UNKNOWN)
        self.assertIn("LINE_ENDPOINT_NEAR_SEAM", res["reasons"])

    def test_seam_inside_a_measure_is_not_safe(self):
        img, rec = make_strip()
        an = analyse(img, rec)
        x = bar_x(1) + 150 + 20  # blank column between two notes of measure 2
        res = rb.classify_seam(an, x)
        self.assertRejected(res)
        self.assertIn("NO_ADJACENT_BARLINE", res["reasons"])

    def test_seam_through_a_barline_is_locked(self):
        img, rec = make_strip()
        res = rb.classify_seam(analyse(img, rec), bar_x(2) + 1)
        self.assertRejected(res, want=rb.LOCKED)

    def test_seam_left_of_a_plain_barline_is_not_safe(self):
        img, rec = make_strip()
        res = rb.classify_seam(analyse(img, rec), bar_x(2) - 20)
        self.assertRejected(res)

    def test_without_observations_nothing_is_safe(self):
        img, rec = make_strip()
        bnds = rb.strip_boundaries(analyse(img, rec, obs=None))
        self.assertTrue(bnds)
        self.assertTrue(all(b["class"] == rb.UNKNOWN and "NO_OBSERVATIONS" in b["reason_codes"] for b in bnds))

    def test_two_observations_are_insufficient(self):
        img, rec = make_strip()
        bnds = rb.strip_boundaries(analyse(img, rec, obs=observations_of(img, n=2)))
        self.assertTrue(all(b["class"] == rb.UNKNOWN for b in bnds))

    def test_unregistered_barline_is_not_safe(self):
        img, rec = make_strip()
        obs = observations_of(img)
        for o in obs:
            o["bars"] = [b for b in o["bars"] if abs((b[0] + b[1]) / 2 - bar_x(2)) > 8]
        bnd = boundary_at(rb.strip_boundaries(analyse(img, rec, obs=obs)), 2)
        self.assertEqual(bnd["class"], rb.UNKNOWN)
        self.assertIn("INSUFFICIENT_OBSERVATIONS", bnd["reason_codes"])

    def test_minority_content_near_the_seam_is_not_safe(self):
        img, rec = make_strip()
        s = _proposed_seam_x(1)
        rec["minority_content"] = {"events": [{"box_strip": [s + 5, 10, s + 9, 14]}]}
        res = rb.classify_seam(analyse(img, rec), s)
        self.assertEqual(res["class"], rb.UNKNOWN)
        self.assertIn("UNRESOLVED_MINORITY_CONTENT", res["reasons"])

    def test_low_resolution_is_unknown(self):
        img, rec = make_strip()
        small = cv2.resize(img, (img.shape[1] // 3, img.shape[0] // 3), interpolation=cv2.INTER_AREA)
        rec2 = dict(rec, staff_y_strip=[y / 3 for y in rec["staff_y_strip"]], staff_gap_px=G / 3,
                    staff_x_strip=[rec["staff_x_strip"][0] // 3, rec["staff_x_strip"][1] // 3], box_crop=[0, 0, small.shape[1], small.shape[0]])
        for b in rb.strip_boundaries(analyse(small, rec2)):
            self.assertNotEqual(b["class"], rb.SAFE)

    def test_user_lock_is_locked(self):
        img, rec = make_strip()
        an = analyse(img, rec)
        first = rb.strip_boundaries(an)[0]
        lock = {"id": "lock-1", "type": "boundary_lock", "targets": [first["id"]], "active": True}
        again = rb.strip_boundaries(an, locks=[lock])[0]
        self.assertEqual(again["class"], rb.LOCKED)
        self.assertIn("USER_LOCK", again["reason_codes"])

    def test_unresolved_preview_tail_region_is_unknown(self):
        img, rec = make_strip()
        rec["preview_tail"] = {"cut": False, "cut_x": bar_x(3) - 40, "verified": False}
        bnd = boundary_at(rb.strip_boundaries(analyse(img, rec)), 3)
        self.assertIn("UNRESOLVED_PREVIEW_TAIL", bnd["reason_codes"])
        self.assertNotEqual(bnd["class"], rb.SAFE)


class Records(unittest.TestCase):
    def test_boundary_record_fields_and_stable_ids(self):
        img, rec = make_strip()
        an = analyse(img, rec)
        a = rb.strip_boundaries(an)
        b = rb.strip_boundaries(analyse(img, rec))
        self.assertEqual([x["id"] for x in a], [x["id"] for x in b])
        for x in a:
            for k in ("id", "seam_x", "seam_x_crop", "barline_box", "stroke_boxes", "class", "reason_codes", "evidence"):
                self.assertIn(k, x)
            self.assertEqual(x["evidence"]["config_hash"], rb.config_hash())
            self.assertIn("protected", x["evidence"]["masks"])

    def test_cut_preview_tail_seam_is_locked_and_owned_by_destination(self):
        rec = {"preview_tail": {"cut": True, "cut_x": 1700, "verified": True, "destination_system_id": "sys-009"},
               "uncut": {"box_crop": [20, 0, 1920, 200], "size": [1900, 200]}}
        b = rb.preview_tail_boundary("sys-008", rec, 1900)
        self.assertEqual(b["class"], rb.LOCKED)
        self.assertEqual(b["owned_by"], "sys-009")
        self.assertEqual(b["seam_x"], 1680)
        self.assertIn("PREVIEW_TAIL_SEAM", b["reason_codes"])
        self.assertIsNone(rb.preview_tail_boundary("sys-008", {"preview_tail": {"cut": False}}))

    def test_scaffold_excludes_crossing_objects(self):
        img, rec = make_strip()
        an = analyse(img, rec)
        ls = _lines()
        # a clean staff-line column inside a corridor is scaffold
        s = _proposed_seam_x(1)
        self.assertTrue(an.scaffold[ls[2] - 1:ls[2] + 2, s].any())
        self.assertFalse(an.nonstaff[:, s].any())
        # the barline column is not scaffold
        self.assertFalse(an.scaffold[ls[2], bar_x(1)])


class RepeatDotsAndDarkTheme(unittest.TestCase):
    """Milestone-2 tuning: repeat dots are whole small components in both middle spaces; dark themes."""

    def test_barline_fringe_on_a_dark_theme_is_not_a_repeat(self):
        # milestone-1 regression: a window-cropped anti-aliased barline fringe read as repeat dots
        img, rec = make_strip(lyrics=True)
        img = darken(barline_fringe(img))
        an = analyse(img, rec)
        self.assertTrue(all(not b["dots"]["left"] and not b["dots"]["right"] for b in an.bars))
        self.assertEqual([b["class"] for b in rb.strip_boundaries(an)], [rb.SAFE] * 3)

    def test_note_head_after_a_barline_is_not_a_repeat_dot(self):
        img, rec = make_strip()
        ls = _lines()
        x, y = bar_x(2) + 22, ls[1] + G // 2
        cv2.ellipse(img, (x, y), (7, 5), -20, 0, 360, INK, -1, cv2.LINE_AA)
        cv2.line(img, (x + 7, y), (x + 7, ls[0] - 2 * G), INK, 1, cv2.LINE_AA)
        bnd = boundary_at(rb.strip_boundaries(analyse(img, rec)), 2)
        self.assertNotIn("REPEAT_BOUNDARY", bnd["reason_codes"])
        self.assertNotIn("POSSIBLE_REPEAT_DOT", bnd["reason_codes"])

    def test_one_dot_after_a_barline_is_unknown(self):
        img, rec = make_strip()
        ls = _lines()
        cv2.circle(img, (bar_x(2) + 8, (ls[1] + ls[2]) // 2), 2, INK, -1, cv2.LINE_AA)
        an = analyse(img, rec, obs=observations_of(make_strip()[0]))
        for seam in (bar_x(2) + 5, bar_x(2) + 14):
            res = rb.classify_seam(an, seam)
            self.assertNotEqual(res["class"], rb.SAFE, res)
        bnd = boundary_at(rb.strip_boundaries(an), 2)
        self.assertNotEqual(bnd["class"], rb.SAFE)

    def test_start_repeat_is_locked_and_never_split(self):
        img, rec = make_strip()
        img = start_repeat(img, 2)
        an = analyse(img, rec)
        b2 = next(b for b in an.bars if b["x0"] - 8 <= bar_x(2) <= b["x1"] + 8)
        self.assertTrue(b2["dots"]["right"])
        bnd = boundary_at(rb.strip_boundaries(an), 2)
        self.assertEqual(bnd["class"], rb.LOCKED, bnd["reason_codes"])
        for x in (bar_x(2) + 4, bar_x(2) + 13, bar_x(2) - 2):  # strokes|dots, dots|notes, thick|thin
            self.assertNotEqual(rb.classify_seam(an, x)["class"], rb.SAFE, x)

    def _fused_case(self, dark: bool):
        img, rec = make_strip()
        img = fused_start_repeat(img, 2)
        obs = observations_of(img)
        if dark:
            img = darken(barline_fringe(img))
        an = analyse(img, rec, obs=obs)
        b2 = next(b for b in an.bars if b["x0"] - 8 <= bar_x(2) <= b["x1"] + 8)
        # the fused dots are not separate components: the dot finder cannot see them
        self.assertFalse(b2["dots"]["right"] or b2["dots"]["left"], b2)
        prop = next(p for p in rb.propose(an) if p["bar"] is b2)
        return an, prop

    def test_fused_start_repeat_at_the_proposed_seam_is_not_safe(self):
        for dark in (False, True):
            an, prop = self._fused_case(dark)
            # the proposer takes the fused dots for the group's fringe and puts the seam after them
            self.assertGreater(prop["seam_x"], bar_x(2) + 13, (dark, prop["corridor"]))
            res = rb.classify_seam(an, prop["seam_x"])
            self.assertNotEqual(res["class"], rb.SAFE, (dark, res))
            self.assertIn("BARLINE_GROUP_ATTACHED_INK", res["reasons"], dark)
            bnd = boundary_at(rb.strip_boundaries(an), 2)
            self.assertNotEqual(bnd["class"], rb.SAFE, (dark, bnd["reason_codes"]))
            # the other (plain) barlines of the strip stay SAFE: the veto is local to the group
            if not dark:
                self.assertEqual(boundary_at(rb.strip_boundaries(an), 1)["class"], rb.SAFE)

    def test_plain_barline_has_no_attached_ink(self):
        img, rec = make_strip(lyrics=True)
        an = analyse(img, rec)
        for b in an.bars:
            self.assertEqual(rb._attached_ink(an, b), [], b)

    def test_dark_theme_negatives_are_rejected(self):
        for kw, seam in ((dict(tie_at=2), _proposed_seam_x(2)), (dict(lyric_across=2), _proposed_seam_x(2)),
                         (dict(repeat_at=2), _proposed_seam_x(2)), (dict(repeat_at=2), bar_x(2) - 11),
                         (dict(slur_above_at=2), _proposed_seam_x(2))):
            img, rec = make_strip(**kw)
            dark = darken(barline_fringe(img))
            res = rb.classify_seam(analyse(dark, rec, obs=observations_of(img)), seam)
            self.assertNotEqual(res["class"], rb.SAFE, (kw, res))


class ClippedContent(unittest.TestCase):
    def _clipped(self, x0: int, x1: int):
        img, rec = make_strip()
        h = img.shape[0]
        cv2.rectangle(img, (x0, h - 6), (x1, h - 1), INK, -1)  # a glyph cut by the strip's bottom edge
        return analyse(img, rec)

    def test_clipped_glyph_at_the_seam_is_unknown(self):
        s = _proposed_seam_x(2)
        res = rb.classify_seam(self._clipped(s + 4, s + 12), s)
        self.assertNotEqual(res["class"], rb.SAFE)
        self.assertIn("CONTENT_AT_STRIP_EDGE", res["reasons"])

    def test_clipped_glyph_a_gap_away_does_not_veto(self):
        s = _proposed_seam_x(2)
        res = rb.classify_seam(self._clipped(s + G + 2, s + G + 12), s)
        self.assertNotIn("CONTENT_AT_STRIP_EDGE", res["reasons"])

    def test_clipped_long_component_vetoes_the_neighbourhood(self):
        s = _proposed_seam_x(2)
        res = rb.classify_seam(self._clipped(s + G + 2, s + G + 2 + 3 * G), s)
        self.assertIn("CONTENT_AT_STRIP_EDGE", res["reasons"])


if __name__ == "__main__":
    unittest.main()
