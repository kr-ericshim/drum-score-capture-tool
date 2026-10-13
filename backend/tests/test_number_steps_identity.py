"""Strict printed-number steps and raw identity's video/highlight exclusions."""

import copy
import json
import unittest
from unittest import mock

import cv2
import numpy as np

from app.pipeline import reflow_occurrences as ro
from app.pipeline import system_tracking as st
from reflow_fixture import STEP, build, frame, loader, strip


def add_number_residue(image, px, *, x=120, y=32):
    for dx, dy in ((0, 0), (5, 0), (0, 5), (5, 5), (2, 2), (3, 3))[:px]:
        image[y + dy, x + dx] = 0
    return image


class NumberStepTrackingTest(unittest.TestCase):
    def track(self, bars, transform=None):
        n = len(bars)
        frames = [(i * STEP, frame(strip(4, numbers=True, first_bar=bar), .35 + .5 * (i + .5) / n, seed=i))
                  for i, bar in enumerate(bars)]
        if transform is not None:
            frames = [(t, transform(i, im)) for i, (t, im) in enumerate(frames)]
        manifest, images = build(frames)
        tracking = st.build_episodes(manifest, loader(images))
        return tracking, manifest, images

    def test_stable_number_change_splits_and_places_both_without_repeat_hint(self):
        tracking, manifest, images = self.track([33] * 12 + [37] * 12)
        self.assertEqual(tracking["tracking_version"], "system_tracking-8")
        eps = tracking["episodes"]
        self.assertEqual(len(eps), 2, [(e["t_start"], e["t_end"], e["started_by"]) for e in eps])
        self.assertEqual([e["n_obs"] for e in eps], [12, 12])
        self.assertEqual(eps[0]["ended_by"], "number_step")
        self.assertEqual(eps[1]["started_by"], "number_step")
        self.assertTrue(all(e["confirmed"] and "content_family" not in e for e in eps))
        step, = tracking["number_steps"]
        self.assertEqual((step["t"], step["obs_id"]), (3.0, "obs-000012"))
        self.assertEqual(step["evidence"]["reason"], "measure_number_area_differs")
        json.dumps(tracking)  # comparator evidence contains only JSON-safe values
        occ = ro.build_occurrences(tracking, manifest, loader(images))
        self.assertEqual([s["episode_ids"] for s in occ["systems"]], [[e["id"]] for e in eps])
        self.assertTrue(all(s["included"] and "POSSIBLE_SAME_DISPLAY" not in s["issues"] for s in occ["systems"]))
        # Even a later continuity proposal cannot override the strict number gate.
        linked = copy.deepcopy(tracking)
        linked["episodes"][1]["continuity_links"] = [{"from": eps[0]["id"], "to": eps[1]["id"], "kind": "page_translation"}]
        out = ro.build_occurrences(linked, manifest, loader(images))
        self.assertEqual(len(out["systems"]), 2)
        self.assertTrue(any(v["verdict"] == "measure_number_area_differs" for v in out["identity_vetoes"]))

    def test_unchanged_number_does_not_scan_members_or_split(self):
        with mock.patch.object(ro, "measure_number_area_differs", wraps=ro.measure_number_area_differs) as compare:
            tracking, _manifest, _images = self.track([33] * 24)
        self.assertEqual(compare.call_count, 1)
        self.assertEqual(tracking["number_steps"], [])
        self.assertEqual(len(tracking["episodes"]), 1)
        self.assertEqual(tracking["number_steps_unresolved"], [])

    def test_few_pixel_number_residue_has_no_split_or_flag(self):
        for px in (4, 5, 6):
            for endpoint_only in (False, True):
                with self.subTest(px=px, endpoint_only=endpoint_only):
                    def residue(i, im):
                        changed = i == 23 if endpoint_only else i >= 12
                        return add_number_residue(im, px) if changed else im
                    tracking, manifest, images = self.track([33] * 24, residue)
                    windows = [ro._raw_window_of(ro._obs_index(manifest), loader(images), o["id"],
                                                o["system_regions"][0]["region_id"])
                               for o in (manifest["observations"][0], manifest["observations"][-1])]
                    self.assertEqual(ro.measure_number_area_differs(*windows)["px"], px)
                    self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [24])
                    self.assertEqual((tracking["number_steps"], tracking["number_steps_unresolved"]), ([], []))
                    self.assertFalse(any(e.get("number_step_unresolved") for e in tracking["episodes"]))
                    systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
                    self.assertFalse(any("NUMBER_STEP_UNRESOLVED" in s["issues"] for s in systems))

    def test_recursive_suffix_ignores_endpoint_and_interior_number_residue(self):
        for endpoint_agrees in (False, True):
            with self.subTest(endpoint_agrees=endpoint_agrees):
                def residue(i, im):
                    return add_number_residue(im, 6) if 24 <= i < (28 if endpoint_agrees else 36) else im
                tracking, _manifest, _images = self.track([33] * 12 + [37] * 24, residue)
                self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [12, 24])
                self.assertEqual(len(tracking["number_steps"]), 1)
                self.assertEqual(tracking["number_steps_unresolved"], [])
                self.assertFalse(any(e.get("number_step_unresolved") for e in tracking["episodes"]))

    def test_three_stable_number_states_split_in_order(self):
        tracking, manifest, images = self.track([33] * 12 + [37] * 12 + [41] * 12)
        self.assertEqual([e["observation_ids"] for e in tracking["episodes"]],
                         [[f"obs-{i:06d}" for i in range(a, a + 12)] for a in (0, 12, 24)])
        self.assertEqual([r["obs_id"] for r in tracking["number_steps"]], ["obs-000012", "obs-000024"])
        self.assertEqual(tracking["number_steps_unresolved"], [])
        systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
        self.assertEqual([s["episode_ids"] for s in systems], [[e["id"]] for e in tracking["episodes"]])
        self.assertTrue(all(s["included"] and "NUMBER_STEP_UNRESOLVED" not in s["issues"] for s in systems))

    def test_suffix_with_agreeing_endpoints_splits_every_stable_interior_state(self):
        tracking, manifest, images = self.track([33] * 12 + [37] * 12 + [41] * 12 + [37] * 12)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [12] * 4)
        self.assertEqual([r["obs_id"] for r in tracking["number_steps"]],
                         ["obs-000012", "obs-000024", "obs-000036"])
        self.assertEqual(tracking["number_steps_unresolved"], [])
        systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
        self.assertEqual(len(systems), 4)
        self.assertTrue(all(s["included"] and "NUMBER_STEP_UNRESOLVED" not in s["issues"] for s in systems))

    def test_unstable_interior_number_state_in_a_suffix_stays_flagged(self):
        tracking, manifest, images = self.track([33] * 12 + [37] * 12 + [41] * 2 + [37] * 12)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [12, 12, 14])
        self.assertEqual(len(tracking["number_steps_unresolved"]), 1)
        self.assertTrue(tracking["episodes"][-1]["number_step_unresolved"])
        systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
        self.assertIn("NUMBER_STEP_UNRESOLVED", systems[-1]["issues"])

    def test_two_or_three_observation_line_fades_do_not_flag_confirmed_displays(self):
        for n in (2, 3):
            for same_music in (False, True):
                with self.subTest(fade_observations=n, same_music=same_music):
                    a = frame(strip(4, numbers=True, first_bar=33), .5)
                    b = frame(strip(4 if same_music else 9, numbers=True, first_bar=37), .5)
                    fade = [np.rint((1 - v) * a + v * b).astype(np.uint8)
                            for v in np.linspace(.25, .75, n)]
                    frames = [a] * 12 + fade + [b] * 12
                    manifest, images = build([(i * STEP, im) for i, im in enumerate(frames)])
                    tracking = st.build_episodes(manifest, loader(images))
                    self.assertEqual(tracking["number_steps_unresolved"], [])
                    self.assertFalse(any(e.get("number_step_unresolved") for e in tracking["episodes"]))
                    retained = [oid for e in tracking["episodes"] for oid in e["observation_ids"]]
                    retained += [r["obs_id"] for r in tracking["transient_observations"]]
                    self.assertEqual(sorted(retained), [o["id"] for o in manifest["observations"]])
                    if not same_music:
                        ordinary = [e for e in tracking["episodes"] if not e.get("transient_display")]
                        self.assertEqual([e["n_obs"] for e in ordinary], [13, 1, 12])
                        self.assertFalse(ordinary[1]["confirmed"])
                    systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
                    self.assertFalse(any("NUMBER_STEP_UNRESOLVED" in s["issues"] for s in systems))

    def test_same_number_with_fade_or_one_pixel_jitter_has_no_step_or_flag(self):
        transforms = (lambda i, im: np.rint(im * (1 - .06 * i / 23)).astype(np.uint8),
                      lambda i, im: cv2.warpAffine(im, np.float32([[1, 0, i % 2], [0, 1, 0]]),
                                                 (im.shape[1], im.shape[0]), borderValue=(255, 255, 255)))
        for transform in transforms:
            with self.subTest(transform=transform):
                tracking, _manifest, _images = self.track([33] * 24, transform)
                self.assertEqual(len(tracking["episodes"]), 1)
                self.assertEqual(tracking["number_steps"], [])
                self.assertEqual(tracking["number_steps_unresolved"], [])
                self.assertFalse(any(e.get("number_step_unresolved") for e in tracking["episodes"]))

    def test_cursor_box_next_to_number_has_no_step_or_flag(self):
        def adjacent_box(i, im):
            im = im.copy()
            x = 110 + i % 20
            im[20:53, x:x + 30] = (255, 110, 40)
            return im
        tracking, _manifest, _images = self.track([33] * 24, adjacent_box)
        self.assertEqual(tracking["number_steps"], [])
        self.assertEqual(tracking["number_steps_unresolved"], [])
        self.assertFalse(any(e.get("number_step_unresolved") for e in tracking["episodes"]))

    def test_number_changed_briefly_in_middle_does_not_split(self):
        tracking, _manifest, _images = self.track([33] * 10 + [37] + [33] * 13)
        self.assertEqual(tracking["number_steps"], [])
        self.assertEqual(len(tracking["episodes"]), 1)

    def test_uncertain_member_blocks_a_cut_and_is_logged(self):
        manifest, images = build([(i * STEP, frame(strip(4, numbers=True), .5)) for i in range(12)])
        obs_by = ro._obs_index(manifest)
        members = [st._Member(o["id"], o["system_regions"][0]["region_id"], o["t_sec"], 70, 12, "active", None)
                   for o in manifest["observations"]]
        ep = st._Episode("slot-00", members, ended_by="end_of_source")
        def compare(a, b):
            i, j = a, b
            if i == 4 or j == 4:
                return {"reason": "number_area_uncertain"}
            return None if (i < 6) == (j < 6) else {"reason": "measure_number_area_differs"}
        log, messages, unresolved = [], [], []
        with mock.patch.object(ro, "_raw_window_of", side_effect=lambda _obs, _load, oid, _rid: int(oid[-6:])), \
                mock.patch.object(ro, "measure_number_area_differs", side_effect=lambda a, b, **_kw: compare(a, b)):
            parts = st._split_on_number_steps(ep, obs_by, loader(images), log, unresolved=unresolved, logger=messages.append)
        self.assertEqual(parts, [ep])
        self.assertEqual(log, [])
        self.assertTrue(any("no clean cut" in m for m in messages))
        self.assertTrue(ep.number_step_unresolved)
        self.assertEqual(unresolved[0]["evidence"]["reason"], "measure_number_area_differs")
        self.assertEqual(unresolved[0]["observation_ids"], [m.obs_id for m in members])
        # A differing endpoint pair does not prove either endpoint's own number
        # area is visible: their combined glyph footprint can be wider.
        def endpoint_uncertain(a, b):
            if a == b == 11:
                return {"reason": "number_area_uncertain"}
            return None if (a < 6) == (b < 6) else {"reason": "measure_number_area_differs"}
        with mock.patch.object(ro, "_raw_window_of", side_effect=lambda _obs, _load, oid, _rid: int(oid[-6:])), \
                mock.patch.object(ro, "measure_number_area_differs", side_effect=lambda a, b, **_kw: endpoint_uncertain(a, b)):
            # The suffix checks each member against its first. It need not compare
            # the last member against itself when its number agrees with that first.
            fresh = st._Episode("slot-00", members, ended_by="end_of_source")
            parts = st._split_on_number_steps(fresh, obs_by, loader(images), [], logger=messages.append)
        self.assertEqual([len(p.members) for p in parts], [6, 6])
        self.assertFalse(any(p.number_step_unresolved for p in parts))

    def test_uncertain_cut_is_recorded_and_system_is_flagged(self):
        def cover_cut(i, im):
            im = im.copy()
            if i == 12:
                im[18:54, 55:103] = (255, 110, 40)
            return im
        tracking, manifest, images = self.track([33] * 12 + [37] * 12, cover_cut)
        self.assertEqual(tracking["number_steps"], [])
        record, = tracking["number_steps_unresolved"]
        self.assertEqual(record["reason"], "cut_member_uncertain")
        self.assertEqual(record["obs_id"], "obs-000012")
        self.assertEqual(record["evidence"]["reason"], "measure_number_area_differs")
        self.assertTrue(any(e.get("number_step_unresolved") for e in tracking["episodes"]))
        systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
        self.assertTrue(any("NUMBER_STEP_UNRESOLVED" in s["issues"] for s in systems))
        json.dumps(tracking)


class RawWrittenIdentityTest(unittest.TestCase):
    def image(self):
        image = np.full((144, 400, 3), 255, np.uint8)
        for y in (48, 60, 72, 84, 96):
            cv2.line(image, (35, y), (390, y), (0, 0, 0), 1)
        cv2.ellipse(image, (170, 66), (6, 4), 0, 0, 360, (0, 0, 0), -1)
        cv2.line(image, (176, 39), (176, 66), (0, 0, 0), 1)
        cv2.ellipse(image, (320, 90), (6, 4), 0, 0, 360, (0, 0, 0), -1)
        cv2.line(image, (326, 64), (326, 90), (0, 0, 0), 1)
        return image

    def window(self, image):
        return image, (48, 48), 12.0, {"staff_y": [48, 60, 72, 84, 96], "staff_x": [35, 390]}

    def test_digit_scale_option_ignores_residue_but_default_still_vetoes(self):
        a = self.image()
        cv2.putText(a, "33", (35, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
        for px, sliver in ((4, False), (5, False), (6, False), (5, True)):
            with self.subTest(px=px, sliver=sliver):
                b = add_number_residue(a.copy(), px, x=73)
                if sliver:
                    b = a.copy()
                    for x, y in ((73, 29), (77, 29), (73, 33), (73, 37), (77, 37)):
                        b[y, x] = 0
                wa, wb = self.window(a), self.window(b)
                strict = ro.measure_number_area_differs(wa, wb)
                self.assertEqual((strict["reason"], strict["pieces"], strict["px"]),
                                 ("measure_number_area_differs", 1, px))
                self.assertIsNone(ro.measure_number_area_differs(wa, wb, require_digit_scale=True))
                self.assertIsNone(ro.measure_number_area_differs(wa, wb, require_uncovered_glyphs=True,
                                                               require_digit_scale=True))
                self.assertEqual(ro.measure_number_area_differs(wa, wb), strict)

    def test_digit_scale_requires_area_and_span_of_one_piece(self):
        gap = 22.38  # DEQ's recorded staff gap; its smallest real difference is 42 px, 11x16.
        top = round(st.WINDOW_ABOVE_GAPS * gap)
        ys = [round(top + i * gap) for i in range(5)]
        a = np.full((280, 420, 3), 255, np.uint8)
        for y in ys:
            cv2.line(a, (30, y), (390, y), (0, 0, 0), 1)
        a[29:45, 55] = 0  # a digit both views print: a number change needs a number on each side
        window = lambda im: (im, (top, top), gap, {"staff_y": ys, "staff_x": [30, 390]})
        digit = a.copy()
        digit[29:45, 30] = digit[29:45, 40] = 0
        digit[29, 31:40] = digit[44, 35] = 0
        compact = a.copy()
        compact[29:35, 30:37] = 0  # 42 px too, but neither dimension reaches half a gap.
        scattered = a.copy()
        for x in range(30, 181, 30):
            scattered[29:33, x:x + 3] = 0  # 72 px in total; each piece is only 12 px.
        for kind, b, px, pieces, passes in (("digit", digit, 42, 1, True),
                                          ("compact", compact, 42, 1, False),
                                          ("scattered", scattered, 72, 6, False)):
            with self.subTest(kind=kind):
                strict = ro.measure_number_area_differs(window(a), window(b))
                self.assertEqual((strict["px"], strict["pieces"]), (px, pieces))
                guarded = ro.measure_number_area_differs(window(a), window(b), require_digit_scale=True)
                self.assertEqual(guarded, strict if passes else None)
                if passes:
                    x0, y0, x1, y1 = guarded["box"]
                    self.assertEqual((x1 - x0, y1 - y0), (11, 16))
                    # only one view prints a number: no measure-number step (the join veto stays strict)
                    bare, one = a.copy(), b.copy()
                    bare[29:45, 55] = one[29:45, 55] = 255
                    self.assertIsNone(ro.measure_number_area_differs(window(bare), window(one), require_digit_scale=True))
                    self.assertIsNotNone(ro.measure_number_area_differs(window(bare), window(one)))

    def test_short_handover_stable_side_ignores_number_residue(self):
        a, b = self.image(), self.image()
        for im, number in ((a, "33"), (b, "37")):
            cv2.putText(im, number, (35, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
        windows = [self.window(a)] + [self.window(b)] * 5 \
                  + [self.window(add_number_residue(b.copy(), 6, x=73))] * 6
        members = [st._Member(f"obs-{i:06d}", f"r-{i}", i * STEP, 48, 12, "active", None)
                   for i in range(12)]
        ep = st._Episode("slot-00", members, started_by="content_change", ended_by="end_of_source")
        log, unresolved = [], []
        with mock.patch.object(ro, "_raw_window_of", side_effect=lambda _obs, _load, oid, _rid: windows[int(oid[-6:])]):
            parts = st._split_on_number_steps(ep, {}, None, log, unresolved=unresolved)
        self.assertEqual([len(p.members) for p in parts], [1, 11])
        self.assertEqual(parts[1].started_by, "view_transition")
        self.assertEqual((log, unresolved), ([], []))
        self.assertFalse(any(p.number_step_unresolved for p in parts))

    def test_thin_differing_ink_on_textured_video_strip_is_same(self):
        a = self.image()
        rng = np.random.default_rng(7)
        gray = rng.integers(215, 250, (18, 400), dtype=np.uint8)
        a[:18] = gray[..., None]
        b = a.copy()
        b[2:17, 230] = 0  # 1 px wide, 15 px long; larger than the unchanged ink threshold
        self.assertTrue(ro.same_written_display(self.window(a), self.window(b))[0])
        self.assertTrue(ro._same_whole_display(a, b, 12, ink_threshold=200, min_area_px=8, min_area_gaps=.06)[0])

    def test_light_translucent_boxes_of_multiple_hues_mask_tinted_stem(self):
        a = self.image()
        a[39:66, 176] = 195  # a thin gray stem crosses the ink threshold under tint
        for color in ((255, 205, 190), (195, 255, 210), (180, 195, 255)):
            b = a.copy()
            box = b[28:104, 155:185]
            box[:] = np.rint(.70 * box + .30 * np.array(color)).astype(np.uint8)
            hsv = cv2.cvtColor(b, cv2.COLOR_BGR2HSV)
            self.assertLess(int(hsv[30, 160, 1]), 80)  # missed by the old strong-color cut
            self.assertTrue(ro.same_written_display(self.window(a), self.window(b))[0], color)

    def test_real_added_notehead_on_paper_still_differs(self):
        a = self.image()
        b = a.copy()
        cv2.ellipse(b, (290, 78), (6, 4), 0, 0, 360, (0, 0, 0), -1)
        same, info = ro.same_written_display(self.window(a), self.window(b))
        self.assertFalse(same, info)
        self.assertFalse(ro._same_whole_display(a, b, 12)[0])
        colored = a.copy()
        cv2.ellipse(colored, (290, 78), (6, 4), 0, 0, 360, (180, 40, 40), -1)
        self.assertFalse(ro._same_whole_display(a, colored, 12)[0])

    def test_changed_measure_number_still_vetoes(self):
        a, b = self.image(), self.image()
        for image, text in ((a, "33"), (b, "37")):
            cv2.putText(image, text, (35, 28), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
        info = ro.measure_number_area_differs(self.window(a), self.window(b))
        self.assertEqual(info["reason"], "measure_number_area_differs", info)
        self.assertFalse(ro.same_written_display(self.window(a), self.window(b))[0])

    def test_overlay_coverage_is_judged_on_glyph_columns(self):
        a, same, changed = self.image(), self.image(), self.image()
        for image, number in ((a, "33"), (same, "33"), (changed, "37")):
            cv2.putText(image, number, (25, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
        # Search area x=0..131: 40 colored columns plus the existing 3-px
        # overlay margin mask >30%, while the digits at x=25..44 stay visible.
        for image in (same, changed):
            image[2:32, 90:130] = (255, 110, 40)
        self.assertIsNone(ro.measure_number_area_differs(self.window(a), self.window(same)))
        verdict = ro.measure_number_area_differs(self.window(a), self.window(changed))
        self.assertEqual(verdict["reason"], "measure_number_area_differs", verdict)
        covered = a.copy()
        box = covered[2:34, 18:60]
        box[:] = np.rint(.5 * box + .5 * np.array((255, 110, 40))).astype(np.uint8)
        verdict = ro.measure_number_area_differs(self.window(a), self.window(covered))
        self.assertEqual(verdict["reason"], "number_area_uncertain", verdict)
        self.assertEqual(verdict["why"], "overlay_covers_number_area", verdict)
        empty, empty_box = self.image(), self.image()
        empty_box[2:32, 90:130] = (255, 110, 40)
        verdict = ro.measure_number_area_differs(self.window(empty), self.window(empty_box))
        self.assertEqual(verdict["reason"], "number_area_uncertain", verdict)


class NumberStepFailureTest(unittest.TestCase):
    def episode(self):
        return st._Episode("slot-00", [st._Member(f"obs-{i:06d}", f"r-{i}", i * STEP,
                                                  70, 12, "active", None) for i in range(12)],
                           ended_by="end_of_source")

    def split(self, ep, compare, **kwargs):
        log, unresolved = [], []
        def digit_comparison(a, b, *, require_digit_scale):
            self.assertTrue(require_digit_scale)
            return compare(a, b)
        with mock.patch.object(ro, "_raw_window_of", side_effect=lambda _obs, _load, oid, _rid: int(oid[-6:])), \
                mock.patch.object(ro, "measure_number_area_differs", side_effect=digit_comparison):
            parts = st._split_on_number_steps(ep, {}, None, log, unresolved=unresolved, **kwargs)
        return parts, log, unresolved

    def test_certain_change_with_depth_limit_unstable_side_or_failed_comparison_is_flagged(self):
        def compare(a, b):
            return None if (a < 6) == (b < 6) else {"reason": "measure_number_area_differs"}
        for reason in ("depth_limit", "unstable_side", "comparison_failed", "no clean cut"):
            with self.subTest(reason=reason):
                ep = self.episode()
                kwargs = {"depth": st.NUMBER_STEP_MAX_DEPTH} if reason == "depth_limit" else {}
                if reason == "unstable_side":
                    ep.members = ep.members[:2] + ep.members[6:]
                def judged(a, b):
                    if reason == "comparison_failed" and b == 5:
                        raise ValueError("missing window")
                    if reason == "no clean cut" and b == 2:
                        return {"reason": "measure_number_area_differs"}
                    return compare(a, b)
                parts, log, unresolved = self.split(ep, judged, **kwargs)
                self.assertEqual(parts, [ep])
                self.assertEqual(log, [])
                self.assertTrue(ep.number_step_unresolved)
                self.assertEqual(unresolved[0]["reason"], reason)

    def test_uncertain_endpoints_do_not_scan_or_flag(self):
        calls = []
        def compare(a, b):
            calls.append((a, b))
            return {"reason": "number_area_uncertain"}
        ep = self.episode()
        parts, log, unresolved = self.split(ep, compare)
        self.assertEqual(parts, [ep])
        self.assertEqual(calls, [(0, 11)])
        self.assertEqual((log, unresolved), ([], []))
        self.assertFalse(ep.number_step_unresolved)

    def test_short_transition_episode_does_not_get_a_number_step_flag(self):
        for n in (2, 3):
            with self.subTest(observations=n):
                ep = self.episode()
                ep.members = ep.members[:n]
                ep.started_by = ep.ended_by = "content_change"
                parts, log, unresolved = self.split(ep, lambda a, b: {"reason": "measure_number_area_differs"})
                self.assertEqual(parts, [ep])
                self.assertEqual((log, unresolved), ([], []))
                self.assertFalse(ep.number_step_unresolved)

    def test_recursive_suffix_with_uncertain_interior_is_flagged(self):
        def compare(a, b):
            if b == 8:
                return {"reason": "number_area_uncertain"}
            return None if (a < 6) == (b < 6) else {"reason": "measure_number_area_differs"}
        parts, log, unresolved = self.split(self.episode(), compare)
        self.assertEqual([len(p.members) for p in parts], [6, 6])
        self.assertEqual(len(log), 1)
        self.assertFalse(parts[0].number_step_unresolved)
        self.assertTrue(parts[1].number_step_unresolved)
        self.assertEqual(unresolved[0]["obs_id"], "obs-000008")
        self.assertEqual(unresolved[0]["member_evidence"]["reason"], "number_area_uncertain")

    def test_flag_survives_playhead_split_and_occurrence_join(self):
        ep = self.episode()
        ep.number_step_unresolved = True
        for m, x in zip(ep.members, (.6, .7, .8, .1, .2, .3, .4, .5, .6, .7, .8, .9)):
            m.playhead_x = x
        parts = st._split_on_playhead_resets(ep)
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(p.number_step_unresolved for p in parts))
        records = [st._episode_record(f"e-{i}", p, 3) for i, p in enumerate(parts)]
        # Also cover a reset split where just one part is unresolved: a reset never joins (audit
        # F03), so each part keeps its own flag and the later part is a possible repeat (‡).
        records[0].pop("number_step_unresolved")
        out = ro.build_occurrences({"episodes": records}, {"observations": []}, lambda _o: None)
        self.assertEqual([s["episode_ids"] for s in out["systems"]], [["e-0"], ["e-1"]])
        self.assertNotIn("NUMBER_STEP_UNRESOLVED", out["systems"][0]["issues"])
        self.assertIn("NUMBER_STEP_UNRESOLVED", out["systems"][1]["issues"])
        self.assertIn("POSSIBLE_SAME_DISPLAY", out["systems"][1]["issues"])
        self.assertEqual(out["systems"][1]["possible_repeat_of"], out["systems"][0]["id"])


class PossibleRepeatNumberTest(unittest.TestCase):
    def pair(self, second_number):
        frames = [(i * STEP, frame(strip(4, numbers=True, first_bar=33 if i < 12 else second_number), .5))
                  for i in range(24)]
        manifest, images = build(frames)
        episodes = []
        for k, obs in enumerate((manifest["observations"][:12], manifest["observations"][12:])):
            members = [st._Member(o["id"], o["system_regions"][0]["region_id"], o["t_sec"],
                                  o["system_regions"][0]["staff_y"][0],
                                  o["system_regions"][0]["staff_gap_px"], "active", None) for o in obs]
            ep = st._Episode("slot-00", members, started_by="first_observation" if k == 0 else "content_step",
                             ended_by="content_step" if k == 0 else "end_of_source", family="F")
            episodes.append(st._episode_record(f"ep-{k}", ep, frames[-1][0]))
        return {"episodes": episodes}, manifest, images

    def test_different_numbers_clear_only_the_later_notice_without_changing_systems(self):
        tracking, manifest, images = self.pair(37)
        tracking["episodes"][1]["number_step_unresolved"] = True
        systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
        first, second = systems
        self.assertEqual([(s["id"], s["included"], s["episode_ids"]) for s in systems],
                         [("sys-001", True, ["ep-0"]), ("sys-002", True, ["ep-1"])])
        self.assertEqual([s["t_start"] for s in systems], [0, 3])
        self.assertNotIn("POSSIBLE_SAME_DISPLAY", second["issues"])
        self.assertNotIn("possible_repeat_of", second)
        self.assertIn("NUMBER_STEP_UNRESOLVED", second["issues"])
        self.assertEqual(second["possible_repeat_cleared"]["of"], first["id"])
        self.assertEqual(second["possible_repeat_cleared"]["evidence"]["reason"], "measure_number_area_differs")
        self.assertNotIn("possible_repeat_cleared", first)

    def test_number_residue_keeps_both_systems_and_the_repeat_notice(self):
        for px in (4, 5, 6):
            with self.subTest(px=px):
                tracking, manifest, images = self.pair(33)
                for i, im in enumerate(images.values()):
                    if i >= 12:
                        add_number_residue(im, px)
                systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
                self.assertEqual([s["episode_ids"] for s in systems], [["ep-0"], ["ep-1"]])
                self.assertTrue(all(s["included"] for s in systems))
                self.assertIn("POSSIBLE_SAME_DISPLAY", systems[1]["issues"])
                self.assertEqual(systems[1]["possible_repeat_of"], systems[0]["id"])
                self.assertNotIn("possible_repeat_cleared", systems[1])

    def test_uncertain_equal_or_absent_numbers_keep_the_notice(self):
        for kind in ("uncertain", "equal", "absent", "one_absent"):
            with self.subTest(kind=kind):
                tracking, manifest, images = self.pair(33 if kind != "uncertain" else 37)
                for i, image in enumerate(images.values()):
                    if kind == "uncertain" and i >= 12:
                        image[18:54, 55:103] = (255, 110, 40)
                    elif kind == "absent" or (kind == "one_absent" and i >= 12):
                        image[:48] = 255
                systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
                self.assertEqual(len(systems), 2)
                self.assertTrue(all(s["included"] for s in systems))
                self.assertIn("POSSIBLE_SAME_DISPLAY", systems[1]["issues"])
                self.assertEqual(systems[1]["possible_repeat_of"], systems[0]["id"])
                self.assertNotIn("possible_repeat_cleared", systems[1])

    def test_same_mixed_gray_number_under_pale_tint_keeps_the_notice(self):
        tracking, manifest, images = self.pair(33)
        for i, image in enumerate(images.values()):
            image[18:48, 55:103] = 255
            cv2.putText(image, "3", (60, 40), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 1)
            cv2.putText(image, "3", (75, 40), cv2.FONT_HERSHEY_SIMPLEX, .6, (195, 195, 195), 1)
            if i >= 12:
                box = image[12:54, 55:103]
                box[:] = np.rint(.70 * box + .30 * np.array((255, 220, 190))).astype(np.uint8)
        obs = manifest["observations"]
        wa = ro._raw_window_of(ro._obs_index(manifest), loader(images), obs[11]["id"], obs[11]["system_regions"][0]["region_id"])
        wb = ro._raw_window_of(ro._obs_index(manifest), loader(images), obs[12]["id"], obs[12]["system_regions"][0]["region_id"])
        raw = ro.measure_number_area_differs(wa, wb)
        self.assertEqual(raw["reason"], "measure_number_area_differs", raw)
        self.assertEqual(raw["number_present"], [True, True])
        guarded = ro.measure_number_area_differs(wa, wb, require_uncovered_glyphs=True)
        self.assertEqual(guarded["reason"], "number_area_uncertain", guarded)
        systems = ro.build_occurrences(tracking, manifest, loader(images))["systems"]
        self.assertEqual(len(systems), 2)
        self.assertIn("POSSIBLE_SAME_DISPLAY", systems[1]["issues"])
        self.assertEqual(systems[1]["possible_repeat_of"], systems[0]["id"])
        self.assertNotIn("possible_repeat_cleared", systems[1])


if __name__ == "__main__":
    unittest.main()
