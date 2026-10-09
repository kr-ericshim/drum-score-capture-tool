"""Step 2B (audit AUDIT_2B_identity_overlay.md): one written line on screen once is placed once.

A. page_diff: staff-line rendering drift (a line removed in one frame and left as dashes in
   the other) is not content; a real small mark off the staff line still counts.
B. reflow_occurrences: consecutive displays of one slot split at ``content_change`` are one
   display when the split is short, the playhead goes on and the written display is the same
   (joined before the short-display cut). Only positive evidence of one written occurrence
   joins: a changed measure number or any notation one side does not draw keeps two
   occurrences (audit F1, no content family); a pure playback-cursor difference at the
   playhead readings may join; a playhead that goes back keeps them apart.
C. GT-free self-checks: ``adjacent_duplicate``, ``score_time_uncovered``, ``revisit_count``.
"""

import copy
import unittest
from unittest import mock
import weakref
from typing import Any, Dict, List, Optional, Sequence

import cv2
import numpy as np

from app.pipeline import page_diff as pd
from app.pipeline import reflow_occurrences as ro
from drum_score_fixture import Degrade, Overlay, add_note, degrade, render, system_top
from reflow_fixture import STEP, build, loader, page, show, strip


# --------------------------------------------------------------------------- #
# A. page_diff
# --------------------------------------------------------------------------- #


def _free_spot(img: np.ndarray, y: int, r: int = 5) -> int:
    """An x where a (2r+1)^2 window around (x, y) holds no ink (a dot there touches nothing)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for x in range(600, img.shape[1] - 100):
        if int(g[y - r:y + r + 1, x - r:x + r + 1].min()) > 200:
            return x
    raise AssertionError("no free spot")


def _staff_rows(spec) -> List[int]:
    top = int(system_top(spec, 0))
    return [top + k * spec.gap for k in range(5)]


def _dash_top_line(img: np.ndarray, y: int, *, period: int = 100, on: int = 30, phase: int = 0) -> np.ndarray:
    """The top staff line left as short dashes (the rest of it lightened to paper)."""
    out = img.copy()
    row = out[y - 1:y + 2]
    for x in range(0, out.shape[1]):
        if (x + phase) % period >= on:
            row[:, x] = np.maximum(row[:, x], 235)
    return out


class StaffLineDriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = strip(3)
        cls.img = render(cls.spec)
        cls.rows = _staff_rows(cls.spec)

    def test_staff_line_rows_are_found_per_band(self):
        g = cv2.cvtColor(self.img, cv2.COLOR_BGR2GRAY)
        rows = pd.staff_line_rows(pd._ink_mask(g), gap=float(self.spec.gap))
        for y in self.rows:
            self.assertTrue(rows[y], y)
        self.assertFalse(rows[self.rows[0] + self.spec.gap // 2])

    def test_top_line_left_as_drifting_dashes_is_same(self):
        a = _dash_top_line(self.img, self.rows[0], phase=0)
        b = _dash_top_line(self.img, self.rows[0], phase=25)
        for level in ("normal", "sensitive"):
            v = pd.compare_frames(a, b, dedupe_level=level)
            self.assertEqual(v.verdict, pd.VERDICT_SAME, (level, v.to_dict()))
        v = pd.compare_frames(self.img, a)
        self.assertEqual(v.verdict, pd.VERDICT_SAME, v.to_dict())

    def _dot_with_and_without_drift(self, y: int, radius: int, level: str):
        x = _free_spot(self.img, y)
        plain = self.img.copy()
        cv2.circle(plain, (x, y), radius, (0, 0, 0), -1)
        a = _dash_top_line(self.img, self.rows[0], phase=0)
        b = _dash_top_line(plain, self.rows[0], phase=25)
        return x, pd.compare_frames(self.img, plain, dedupe_level=level), pd.compare_frames(a, b, dedupe_level=level)

    def test_small_dot_off_the_staff_line_still_counts_with_drift(self):
        # a radius-2 dot is a "small change" at the sensitive level and a radius-3 one at the
        # normal level, with or without the drifting line next to it
        y = self.rows[1] + self.spec.gap // 2  # in a space, off the lines
        for radius, level in ((2, "sensitive"), (3, "normal")):
            x, plain, drift = self._dot_with_and_without_drift(y, radius, level)
            self.assertNotEqual(plain.verdict, pd.VERDICT_SAME, (radius, level))
            self.assertEqual((drift.verdict, drift.significant_blobs + drift.minor_blobs),
                             (plain.verdict, plain.significant_blobs + plain.minor_blobs), (radius, level, drift.to_dict()))
            self.assertTrue(any(bx - 2 <= x <= bx + bw + 2 and by - 2 <= y <= by + bh + 2 for bx, by, bw, bh in drift.change_boxes), drift.change_boxes)

    def test_dot_above_the_staff_with_drift_still_counts(self):
        y = self.rows[0] - 2 * self.spec.gap
        _x, plain, drift = self._dot_with_and_without_drift(y, 3, "normal")
        self.assertNotEqual(drift.verdict, pd.VERDICT_SAME, drift.to_dict())
        self.assertEqual(drift.verdict, plain.verdict)

    def test_added_note_with_drift_is_different(self):
        changed = render(add_note(self.spec, 0, 2, 3, 1.5))
        a = _dash_top_line(self.img, self.rows[0], phase=0)
        b = _dash_top_line(changed, self.rows[0], phase=25)
        v = pd.compare_frames(a, b)
        self.assertEqual(v.verdict, pd.VERDICT_DIFFERENT, v.to_dict())


# --------------------------------------------------------------------------- #
# B/C. occurrence-level join and self-checks
# --------------------------------------------------------------------------- #


def tracking_from(manifest: Dict[str, Any], cuts: Sequence[int], *, boundary: str = "content_change",
                  playhead: Optional[List[Optional[float]]] = None) -> Dict[str, Any]:
    """Display episodes of the one slot of ``manifest``, split before the observation indexes
    in ``cuts`` (what the tracker does on a false content change). ``playhead``: one reading per
    observation (None = no reading); default: the observations' own detected playhead."""
    obs = manifest["observations"]
    bounds = [0] + list(cuts) + [len(obs)]
    eps = []
    for k, (i0, i1) in enumerate(zip(bounds, bounds[1:])):
        part = obs[i0:i1]
        regs = [o["system_regions"][0] for o in part]
        xs = [playhead[i] if playhead is not None else r.get("playhead_x") for i, r in zip(range(i0, i1), regs)]
        eps.append({
            "id": f"ep-{k:04d}", "slot_id": regs[0]["slot_id"] or "slot-00", "t_start": part[0]["t_sec"], "t_end": part[-1]["t_sec"],
            "n_obs": len(part), "observation_ids": [o["id"] for o in part], "region_ids": [r["region_id"] for r in regs],
            "staff_top_y": float(regs[0]["staff_y"][0]), "staff_gap_px": float(regs[0]["staff_gap_px"]), "role": "active",
            "started_by": "first_observation" if k == 0 else boundary,
            "ended_by": "end_of_source" if i1 == len(obs) else boundary,
            "motion": {"playhead_track": [[o["t_sec"], x] for o, x in zip(part, xs) if x is not None]},
            "continuity_links": [], "layout": "bottom_bar",
        })
    return {"episodes": eps, "layout_intervals": []}


def ramp(n: int, *, restart_at: Sequence[int] = ()) -> List[float]:
    """Playhead readings moving left to right, restarting from the left at ``restart_at``."""
    out, start = [], 0
    marks = list(restart_at) + [n]
    for m in marks:
        k = m - start
        out += [round(0.05 + 0.9 * (i + 0.5) / max(1, k), 4) for i in range(k)]
        start = m
    return out


def numbered(frames, text: str, *, thickness: int = 2, ink: int = 0, scale: float = 0.6):
    """Frames with a measure number above the start of the staff."""
    out = []
    for t, img in frames:
        img = img.copy()
        cv2.putText(img, text, (60, 50), cv2.FONT_HERSHEY_SIMPLEX, scale, (ink, ink, ink), thickness, cv2.LINE_AA)
        out.append((t, img))
    return out


def run(frames, cuts, **kw):
    manifest, images = build(frames)
    tracking = tracking_from(manifest, cuts, **kw)
    return ro.build_occurrences(tracking, manifest, loader(images)), manifest


class SplitJoinTest(unittest.TestCase):
    def test_long_whole_span_scan_retains_only_endpoint_windows(self):
        # Reuse one decoded frame so this measures raw-window retention, independently
        # of the image loader's own bounded decoded-frame cache.
        image = render(strip(4, numbers=True))
        manifest, _images = build([(0.0, image)])
        template = manifest["observations"][0]
        manifest["observations"] = []
        for i in range(256):
            obs = copy.deepcopy(template)
            obs["id"], obs["t_sec"] = f"obs-{i:06d}", i * STEP
            obs["system_regions"][0]["region_id"] = f"{obs['id']}-r0"
            manifest["observations"].append(obs)
        tracking = tracking_from(manifest, [128], playhead=ramp(256))
        windows, peak = [], 0
        raw_window_of = ro._raw_window_of

        def counted_window(*args):
            nonlocal peak
            result = raw_window_of(*args)
            windows.append(weakref.ref(result[0]))
            peak = max(peak, sum(w() is not None for w in windows))
            return result

        with mock.patch.object(ro, "_raw_window_of", side_effect=counted_window):
            occ = ro.build_occurrences(tracking, manifest, lambda _o: image)
        self.assertEqual([s["episode_ids"] for s in occ["systems"] if s["included"]],
                         [["ep-0000", "ep-0001"]])
        self.assertGreaterEqual(len(windows), 256)  # all members were actually examined
        self.assertLessEqual(peak, 6, f"retained {peak} raw windows for 256 members")

    def test_late_boundary_observations_of_next_display_do_not_join(self):
        # Same groove, different printed measures. The tracker has already admitted
        # two frames of 81 into the episode for 77, so boundary-only identity agrees.
        a = numbered(show(strip(4), 0.0, 4.0, seed=51), "77")
        b = numbered(show(strip(4), 4.0, 4.0, seed=52), "81")
        frames = a + b
        cut = len(a) + 2
        for readings in (ramp(len(frames), restart_at=[len(a)]),
                         [None] * len(frames), ramp(len(frames))):
            with self.subTest(motion=readings[:2]):
                occ, _m = run(frames, [cut], playhead=readings)
                placed = [s for s in occ["systems"] if s["included"]]
                self.assertEqual([s["episode_ids"] for s in placed], [["ep-0000"], ["ep-0001"]])
                self.assertEqual(occ["joins"], [])
                self.assertFalse(any(s.get("alternate_of") for s in placed))
                checks = occ["self_checks"]["split_joins"]["kept_apart"]
                self.assertEqual(len(checks), 1)
                self.assertIn(checks[0]["kept_apart"],
                              ("playhead_went_back", "written_display_differs", "measure_number_area_differs"))

    def test_middle_member_difference_in_either_episode_keeps_split(self):
        # Matching endpoints do not establish sameness over either episode's span.
        frames = numbered(show(strip(4), 0.0, 8.0, seed=53), "81")
        changed = numbered(show(strip(4), 0.0, 8.0, seed=53), "77")
        cut = len(frames) // 2
        for index in (cut // 2, cut + cut // 2):
            with self.subTest(changed_member=index):
                mixed = list(frames)
                mixed[index] = changed[index]
                occ, _m = run(mixed, [cut], playhead=ramp(len(frames)))
                self.assertEqual(occ["joins"], [])
                self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 2)

    def test_false_split_with_staff_drift_and_continuing_playhead_still_joins(self):
        spec = strip(4, numbers=True)
        frames = show(spec, 0.0, 6.0, seed=54)
        cut = len(frames) // 2
        top = _staff_rows(spec)[0]
        manifest, images = build(frames)
        tracking = tracking_from(manifest, [cut], playhead=ramp(len(frames)))
        # Keep the detected staff geometry fixed while its rendering drifts.
        for i, o in enumerate(manifest["observations"]):
            images[o["id"]] = _dash_top_line(images[o["id"]], top, phase=0 if i < cut else 25)
        occ = ro.build_occurrences(tracking, manifest, loader(images))
        self.assertEqual([s["episode_ids"] for s in occ["systems"] if s["included"]],
                         [["ep-0000", "ep-0001"]])
        self.assertEqual(len(occ["joins"]), 1)
        self.assertFalse(occ["joins"][0]["joined_without_motion_evidence"])

    def test_false_split_with_continuing_playhead_is_one_display(self):
        frames = show(strip(4, numbers=True), 0.0, 6.0, seed=1)
        occ, _m = run(frames, [14], playhead=ramp(len(frames)))
        placed = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(placed), 1, [(s["id"], s["episode_ids"]) for s in occ["systems"]])
        self.assertEqual(placed[0]["episode_ids"], ["ep-0000", "ep-0001"])
        j = [x for x in occ["joins"] if x["basis"] == "content_change_same_written_display"]
        self.assertEqual(len(j), 1)
        self.assertFalse(j[0]["joined_without_motion_evidence"])
        self.assertEqual(occ["self_checks"]["adjacent_duplicate"], 0)
        self.assertEqual(occ["exclusions"]["self_checks"]["adjacent_duplicate"], 0)

    def test_short_parts_are_joined_before_the_short_display_cut(self):
        # 1.0 + 1.25 + 0.75 s: each part alone is a short display; together one placed line
        frames = show(strip(4, numbers=True), 0.0, 3.0, seed=2)
        occ, _m = run(frames, [4, 9], playhead=ramp(len(frames)))
        placed = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(placed), 1)
        self.assertEqual(len(placed[0]["episode_ids"]), 3)
        self.assertEqual(occ["self_checks"]["score_time_uncovered_sec"], 0.0)

    def test_without_the_join_the_short_parts_are_uncovered_score_time(self):
        # the playhead restarts at each cut: no evidence of one display, the parts stay apart
        frames = show(strip(4, numbers=True), 0.0, 3.0, seed=2)
        occ, _m = run(frames, [4, 9], playhead=ramp(len(frames), restart_at=[4, 9]))
        self.assertFalse([x for x in occ["joins"] if x["basis"] == "content_change_same_written_display"])
        sc = occ["self_checks"]
        self.assertGreater(sc["score_time_uncovered_sec"], 2.5)
        self.assertEqual(len(sc["score_time_uncovered"]), 1)
        self.assertEqual(sorted(sc["score_time_uncovered"][0]["episode_ids"]), ["ep-0000", "ep-0001", "ep-0002"])
        self.assertTrue(all(k["kept_apart"] == "playhead_went_back" for k in sc["split_joins"]["kept_apart"]))

    def test_playhead_going_back_keeps_two_displays_and_reports_the_return(self):
        frames = show(strip(4, numbers=True), 0.0, 8.0, seed=3)
        occ, _m = run(frames, [16], playhead=ramp(len(frames), restart_at=[16]))
        placed = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(placed), 2)
        sc = occ["self_checks"]
        self.assertEqual(sc["adjacent_duplicate"], 0)
        self.assertEqual(len(sc["adjacent_same_after_leaving"]), 1)

    def test_without_playhead_readings_join_on_pixel_sameness_and_record_it(self):
        frames = show(strip(4, numbers=True), 0.0, 6.0, seed=4)
        occ, _m = run(frames, [12], playhead=[None] * len(frames))
        placed = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(placed), 1)
        j = [x for x in occ["joins"] if x["basis"] == "content_change_same_written_display"]
        self.assertTrue(j and j[0]["joined_without_motion_evidence"])

    def test_different_measure_numbers_without_playhead_stay_apart(self):
        # the same groove written twice; only the (dark) measure number differs
        a = numbered(show(strip(4), 0.0, 4.0, seed=5), "13")
        b = numbered(show(strip(4), 4.0, 4.0, seed=6), "17")
        occ, _m = run(a + b, [len(a)], playhead=[None] * (len(a) + len(b)))
        self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 2)
        same = numbered(show(strip(4), 4.0, 4.0, seed=6), "13")
        occ, _m = run(a + same, [len(a)], playhead=[None] * (len(a) + len(same)))
        self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 1)

    def test_another_line_with_continuing_playhead_is_not_joined_or_familied(self):
        a = show(strip(4, numbers=True, first_bar=1), 0.0, 4.0, seed=7)
        b = show(strip(9, numbers=True, first_bar=5), 4.0, 4.0, seed=8)
        occ, _m = run(a + b, [len(a)], playhead=ramp(len(a) + len(b)))
        placed = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(placed), 2)
        self.assertFalse(any(s.get("alternate_of") for s in occ["systems"]))

    def test_one_added_note_with_continuing_playhead_stays_two_occurrences(self):
        # F1: a notation component one side does not draw is no evidence of one written
        # occurrence; both displays are placed, none hidden as an alternate, no family
        spec = strip(4, numbers=True)
        a = show(spec, 0.0, 4.0, seed=9)
        b = show(add_note(spec, 0, 2, 3, 1.5), 4.0, 4.0, seed=10)
        occ, _m = run(a + b, [len(a)], playhead=ramp(len(a) + len(b)))
        placed = [s for s in occ["systems"] if s["included"]]
        self.assertEqual([s["episode_ids"] for s in placed], [["ep-0000"], ["ep-0001"]],
                         [(s["id"], s["included"], s.get("alternate_of")) for s in occ["systems"]])
        self.assertFalse(any(s.get("alternate_of") for s in occ["systems"]))
        sj = occ["self_checks"]["split_joins"]
        self.assertEqual(sj["families"], [])
        self.assertEqual(sj["joined"], [])
        self.assertEqual([k["kept_apart"] for k in sj["kept_apart"]], ["written_display_differs"])

    def test_numbered_lines_13_and_17_with_continuing_playhead_stay_apart(self):
        # F1 (audit): the same groove written twice, numbered 13 and 17, split at content_change
        # with a playhead that goes on: two written lines, both placed
        for kw in ({}, {"thickness": 1, "ink": 90, "scale": 0.5}):
            a = numbered(show(strip(4), 0.0, 4.0, seed=17), "13", **kw)
            b = numbered(show(strip(4), 4.0, 4.0, seed=18), "17", **kw)
            occ, _m = run(a + b, [len(a)], playhead=ramp(len(a) + len(b)))
            placed = [s for s in occ["systems"] if s["included"]]
            self.assertEqual(len(placed), 2, (kw, [(s["id"], s["included"], s.get("alternate_of")) for s in occ["systems"]]))
            self.assertFalse(any(s.get("alternate_of") for s in occ["systems"]))
            sj = occ["self_checks"]["split_joins"]
            self.assertEqual((sj["joined"], sj["families"]), ([], []))
            self.assertEqual(len(sj["kept_apart"]), 1)
            # the same number on both sides: one display
            same = numbered(show(strip(4), 4.0, 4.0, seed=18), "13", **kw)
            occ, _m = run(a + same, [len(a)], playhead=ramp(len(a) + len(same)))
            self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 1, kw)

    def test_gray_numbered_lines_13_and_17_stay_apart(self):
        # audit G1: a gray measure number (ink 120-180) is whitened by clean_content; the join
        # decision compares raw polarity-normalized pixels, so 13 and 17 stay two placed lines
        for ink in (120, 150, 180):
            kw = {"thickness": 1, "ink": ink, "scale": 0.5}
            a = numbered(show(strip(4), 0.0, 4.0, seed=17), "13", **kw)
            b = numbered(show(strip(4), 4.0, 4.0, seed=18), "17", **kw)
            occ, _m = run(a + b, [len(a)], playhead=ramp(len(a) + len(b)))
            placed = [s for s in occ["systems"] if s["included"]]
            self.assertEqual([s["episode_ids"] for s in placed], [["ep-0000"], ["ep-0001"]],
                             (ink, occ["self_checks"]["split_joins"]))
            self.assertFalse(any(s.get("alternate_of") for s in occ["systems"]))
            sj = occ["self_checks"]["split_joins"]
            self.assertEqual(sj["joined"], [], ink)
            self.assertEqual([k["kept_apart"] for k in sj["kept_apart"]], ["written_display_differs"], (ink, sj["kept_apart"]))
            # the same gray number on both sides is still one display
            same = numbered(show(strip(4), 4.0, 4.0, seed=18), "13", **kw)
            occ, _m = run(a + same, [len(a)], playhead=ramp(len(a) + len(same)))
            self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 1, (ink, occ["self_checks"]["split_joins"]))

    def test_gray_number_area_veto_on_raw_windows(self):
        # the number area alone (whole-display check bypassed) tells a gray 13 from a gray 18
        for ink in (120, 150, 180):
            kw = {"thickness": 1, "ink": ink, "scale": 0.5}
            manifest, images = build(numbered(show(strip(4), 0.0, 1.0, seed=19), "13", **kw)
                                     + numbered(show(strip(4), 1.0, 1.0, seed=20), "18", **kw)
                                     + numbered(show(strip(4), 2.0, 1.0, seed=21), "13", **kw))
            obs = ro._obs_index(manifest)
            w = [ro._raw_window_of(obs, loader(images), o["id"], o["system_regions"][0]["region_id"])
                 for o in (manifest["observations"][0], manifest["observations"][4], manifest["observations"][8])]
            diff = ro.measure_number_area_differs(w[0], w[1])
            self.assertIsNotNone(diff, ink)
            self.assertEqual(diff["reason"], "measure_number_area_differs", (ink, diff))
            self.assertIsNone(ro.measure_number_area_differs(w[0], w[2]), ink)

    def test_number_area_without_light_paper_is_uncertain_not_joined(self):
        # a background showing through behind the number (gray ~150 paper): no confident verdict
        manifest, images = build(numbered(show(strip(4), 0.0, 1.0, seed=22), "13", thickness=1, ink=60, scale=0.5))
        obs = ro._obs_index(manifest)
        o = manifest["observations"][0]
        wt = ro._raw_window_of(obs, loader(images), o["id"], o["system_regions"][0]["region_id"])
        dim = (wt[0].astype(np.int32) * 150 // 255).astype(np.uint8)
        res = ro.measure_number_area_differs((dim,) + tuple(wt[1:]), (dim.copy(),) + tuple(wt[1:]))
        self.assertIsNotNone(res)
        self.assertEqual(res["reason"], "number_area_uncertain", res)

    def test_measure_number_area_veto_catches_a_digit_below_the_whole_display_threshold(self):
        manifest, images = build(numbered(show(strip(4), 0.0, 1.0, seed=19), "13", thickness=1, ink=90, scale=0.5)
                                 + numbered(show(strip(4), 1.0, 1.0, seed=20), "18", thickness=1, ink=90, scale=0.5)
                                 + numbered(show(strip(4), 2.0, 1.0, seed=21), "13", thickness=1, ink=90, scale=0.5))
        obs = ro._obs_index(manifest)
        w = [ro._raw_window_of(obs, loader(images), o["id"], o["system_regions"][0]["region_id"])
             for o in (manifest["observations"][0], manifest["observations"][4], manifest["observations"][8])]
        self.assertIsNotNone(ro.measure_number_area_differs(w[0], w[1]))
        self.assertIsNone(ro.measure_number_area_differs(w[0], w[2]))

    def test_dark_cursor_only_difference_with_continuing_playhead_is_one_display(self):
        # a black (uncolored) playback cursor moving along: the only difference is at the
        # playhead readings, so the false split is joined
        spec = strip(4, numbers=True)
        n = 16
        frames = []
        for i in range(n):
            ph = 0.1 + 0.8 * (i + 0.5) / n
            img = render(spec, [Overlay("line", position=ph, color=(20, 20, 20), thickness=2)])
            frames.append((i * STEP, degrade(img, Degrade(blur=0.6, jpeg_quality=90, noise=1.0, seed=2000 + i))))
        manifest, images = build(frames)
        readings = []
        for i, o in enumerate(manifest["observations"]):
            r = o["system_regions"][0]
            x = spec.margin_x + (0.1 + 0.8 * (i + 0.5) / n) * (spec.width - 2 * spec.margin_x)
            readings.append(round((x - r["bbox"][0]) / (r["bbox"][2] - r["bbox"][0]), 4))
        tracking = tracking_from(manifest, [8], playhead=readings)
        occ = ro.build_occurrences(tracking, manifest, loader(images))
        placed = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(placed), 1, occ["self_checks"]["split_joins"])
        j = occ["self_checks"]["split_joins"]["joined"]
        self.assertEqual(len(j), 1)
        self.assertTrue(j[0].get("differs_only_by_cursor"), j)
        # The indexed member lookup preserves the old timestamp tolerance and uses
        # each member's own cursor reading, even when stored times differ slightly.
        jittered = tracking_from(manifest, [8], playhead=readings)
        for episode in jittered["episodes"]:
            episode["motion"]["playhead_track"] = [[t + 0.00005, x]
                for t, x in episode["motion"]["playhead_track"]]
        occ = ro.build_occurrences(jittered, manifest, loader(images))
        self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 1)
        # A reading near the boundary but outside the member timestamp tolerance
        # is endpoint evidence only. It cannot explain the reference frame's cursor
        # during the whole-span scan when that frame has no actual reading.
        missing_reference = tracking_from(manifest, [8], playhead=readings)
        b_track = missing_reference["episodes"][1]["motion"]["playhead_track"]
        b_track[0][0] += 0.01
        occ = ro.build_occurrences(missing_reference, manifest, loader(images))
        self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 2)
        # the same cursor with a playhead reading elsewhere is no evidence: kept apart
        far = [round(min(0.98, x + 0.3), 4) if k >= 8 else x for k, x in enumerate(readings)]
        occ = ro.build_occurrences(tracking_from(manifest, [8], playhead=far), manifest, loader(images))
        self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 2)

    def test_revisit_after_another_line_is_counted(self):
        s1, s2 = strip(4, numbers=True, first_bar=1), strip(9, numbers=True, first_bar=5)
        frames = show(s1, 0.0, 4.0, seed=11) + show(s2, 4.0, 4.0, seed=12) + show(s1, 8.0, 4.0, seed=13)
        n = len(frames) // 3
        occ, _m = run(frames, [n, 2 * n], boundary="registration_change", playhead=ramp(len(frames), restart_at=[n, 2 * n]))
        sc = occ["self_checks"]
        self.assertEqual(len([s for s in occ["systems"] if s["included"]]), 3)
        self.assertEqual(sc["revisit_count"], 1)
        self.assertEqual(sc["revisits"][0], {"system_id": "sys-003", "of_system_id": "sys-001"})
        self.assertEqual(sc["adjacent_duplicate"], 0)
        self.assertEqual(sc["score_time_uncovered_sec"], 0.0)

    def test_same_groove_with_thin_light_measure_numbers_is_not_a_revisit(self):
        # corpus case: identical chorus grooves at m.61 and m.97, thin gray digits
        s2 = strip(9)
        frames = numbered(show(strip(4), 0.0, 4.0, seed=14), "61", thickness=1, ink=90, scale=0.5) + \
            show(s2, 4.0, 4.0, seed=15) + numbered(show(strip(4), 8.0, 4.0, seed=16), "97", thickness=1, ink=90, scale=0.5)
        n = len(frames) // 3
        occ, _m = run(frames, [n, 2 * n], boundary="registration_change", playhead=ramp(len(frames), restart_at=[n, 2 * n]))
        self.assertEqual(occ["self_checks"]["revisit_count"], 0, occ["self_checks"]["revisits"])
        same = numbered(show(strip(4), 8.0, 4.0, seed=16), "61", thickness=1, ink=90, scale=0.5)
        occ, _m = run(frames[:2 * n] + same, [n, 2 * n], boundary="registration_change",
                      playhead=ramp(len(frames), restart_at=[n, 2 * n]))
        self.assertEqual(occ["self_checks"]["revisit_count"], 1)



# --------------------------------------------------------------------------- #
# D. every join path honours the raw identity veto (Codex H1)
# --------------------------------------------------------------------------- #


def two_row_tracking(manifest: Dict[str, Any], cut: int, *, boundary: str,
                     playhead: Optional[List[Optional[float]]] = None) -> Dict[str, Any]:
    """Top row (slot of region 0) split before observation ``cut``; the bottom row (region 1)
    one steady display over the whole page view."""
    obs = manifest["observations"]
    eps = []

    def ep(k, part, ri, started, ended, xs):
        regs = [o["system_regions"][ri] for o in part]
        return {"id": f"ep-{k:04d}", "slot_id": regs[0]["slot_id"], "t_start": part[0]["t_sec"], "t_end": part[-1]["t_sec"],
                "n_obs": len(part), "observation_ids": [o["id"] for o in part], "region_ids": [r["region_id"] for r in regs],
                "staff_top_y": float(regs[0]["staff_y"][0]), "staff_gap_px": float(regs[0]["staff_gap_px"]), "role": "active",
                "started_by": started, "ended_by": ended,
                "motion": {"playhead_track": [[o["t_sec"], x] for o, x in zip(part, xs) if x is not None]},
                "continuity_links": [], "layout": "page"}

    xs = playhead if playhead is not None else [None] * len(obs)
    eps.append(ep(0, obs[:cut], 0, "first_observation", boundary, xs[:cut]))
    eps.append(ep(1, obs[cut:], 0, boundary, "end_of_source", xs[cut:]))
    eps.append(ep(2, obs, 1, "first_observation", "end_of_source", [None] * len(obs)))
    return {"episodes": eps, "layout_intervals": []}


class IdentityVetoAllPathsTest(unittest.TestCase):
    """A two-row page whose bottom row stays steady while the identical top groove changes its
    gray measure number 13 -> 17: two written occurrences, whichever join rule is tried."""

    def _page(self, top_a: str, top_b: str, ink: int = 150):
        kw = {"thickness": 1, "ink": ink, "scale": 0.5}
        spec = page([4, 9])
        frames = show(spec, 0.0, 8.0, seed=31)  # one page view, the playback line moving on
        half = len(frames) // 2
        return build(numbered(frames[:half], top_a, **kw) + numbered(frames[half:], top_b, **kw)), half

    def _top_systems(self, occ):
        return [s["episode_ids"] for s in occ["systems"] if s["included"] and set(s["episode_ids"]) & {"ep-0000", "ep-0001"}]

    def test_late_boundary_with_uncertain_first_member_and_steady_peer_keeps_split(self):
        # Review reproduction: the last two old-episode members already show 81;
        # its first member has paper 210, while later members clearly show 77.
        # The steady bottom row must not undo the whole-span rejection.
        (manifest, images), half = self._page("77", "81")
        first = manifest["observations"][0]
        images[first["id"]] = (images[first["id"]].astype(np.uint16) * 210 // 255).astype(np.uint8)
        cut = half + 2
        tracking = two_row_tracking(manifest, cut, boundary="content_change")
        occ = ro.build_occurrences(tracking, manifest, loader(images))
        self.assertEqual(self._top_systems(occ), [["ep-0000"], ["ep-0001"]], occ["joins"])
        self.assertEqual(occ["joins"], [])
        vetoes = [v for v in occ["identity_vetoes"] if v["path"] == "content_change_same_written_display"]
        self.assertEqual(len(vetoes), 1)
        self.assertIn(vetoes[0]["verdict"], ("written_display_differs", "measure_number_area_differs"))
        self.assertEqual(vetoes[0]["observations"][0], manifest["observations"][1]["id"])
        self.assertTrue(any(v["verdict"] == "group_holds_identity_veto" for v in occ["identity_vetoes"]))

    def test_uncertain_span_is_binding_even_without_a_definite_difference(self):
        (manifest, images), cut = self._page("81", "81")
        first = manifest["observations"][0]
        images[first["id"]] = (images[first["id"]].astype(np.uint16) * 210 // 255).astype(np.uint8)
        occ = ro.build_occurrences(two_row_tracking(manifest, cut, boundary="content_change"),
                                   manifest, loader(images))
        self.assertEqual(self._top_systems(occ), [["ep-0000"], ["ep-0001"]], occ["joins"])
        self.assertEqual(occ["joins"], [])
        self.assertEqual([v["verdict"] for v in occ["identity_vetoes"]],
                         ["identity_uncertain", "group_holds_identity_veto"])

    def test_steady_row_rule_checks_the_whole_span_without_the_false_split_rule(self):
        (manifest, images), half = self._page("77", "81")
        occ = ro.build_occurrences(two_row_tracking(manifest, half + 2, boundary="registration_change"),
                                   manifest, loader(images))
        self.assertEqual(self._top_systems(occ), [["ep-0000"], ["ep-0001"]], occ["joins"])
        self.assertEqual(occ["joins"], [])
        self.assertTrue(any(v["path"] == "unchanged_page_view_same_row" for v in occ["identity_vetoes"]))

    def test_steady_row_join_respects_the_measure_number_veto(self):
        for boundary, playhead in (("content_change", None), ("content_change", "ramp"), ("registration_change", None)):
            (manifest, images), cut = self._page("13", "17")
            n = len(manifest["observations"])
            ph = ramp(n) if playhead == "ramp" else None
            occ = ro.build_occurrences(two_row_tracking(manifest, cut, boundary=boundary, playhead=ph), manifest, loader(images))
            self.assertEqual(self._top_systems(occ), [["ep-0000"], ["ep-0001"]], (boundary, playhead, occ["joins"]))
            self.assertFalse([j for j in occ["joins"] if {j["a"], j["b"]} == {"ep-0000", "ep-0001"}], boundary)
            vetoes = [v for v in occ["identity_vetoes"] if {v["a"], v["b"]} == {"ep-0000", "ep-0001"}]
            self.assertTrue(vetoes, (boundary, occ["identity_vetoes"]))
            self.assertIn(vetoes[0]["verdict"], ("written_display_differs", "measure_number_area_differs"), vetoes)

    def test_playhead_reset_join_respects_the_measure_number_veto(self):
        (manifest, images), cut = self._page("13", "17")
        n = len(manifest["observations"])
        tracking = two_row_tracking(manifest, cut, boundary="playhead_reset", playhead=ramp(n, restart_at=[cut]))
        occ = ro.build_occurrences(tracking, manifest, loader(images))
        self.assertEqual(self._top_systems(occ), [["ep-0000"], ["ep-0001"]], occ["joins"])
        self.assertTrue([v for v in occ["identity_vetoes"] if v["path"] == "playhead_reset_same_display"], occ["identity_vetoes"])

    def test_same_number_on_a_steady_page_is_still_one_display(self):
        (manifest, images), cut = self._page("13", "13")
        occ = ro.build_occurrences(two_row_tracking(manifest, cut, boundary="registration_change"), manifest, loader(images))
        self.assertEqual(self._top_systems(occ), [["ep-0000", "ep-0001"]], (occ["joins"], occ["identity_vetoes"]))
        self.assertEqual([j["basis"] for j in occ["joins"]], ["unchanged_page_view_same_row"])

    def test_a_vetoed_pair_is_not_joined_through_a_third_display(self):
        uf = ro._UF(["x", "y", "z"])
        guard = ro._VetoGuard(uf)
        guard.veto("x", "z")
        self.assertTrue(guard.join("x", "y"))
        self.assertFalse(guard.join("y", "z"))
        self.assertNotEqual(uf.find("x"), uf.find("z"))


if __name__ == "__main__":
    unittest.main()
