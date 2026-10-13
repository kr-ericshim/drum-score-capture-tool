"""Regression tests for the 2026-10-13 lossless audit, group A (docs/reflow/audit_2026-10-13).

F01 one-observation screen listed, F04 cursor-less 33 -> 37 -> 33, F05 a short screen hidden
only by ONE neighbour, F07 the ‡ pair worked out after the selection, F09 removal step,
F03 a playhead reset never joins (‡ possible repeat instead), F06 the end tail is sampled.
"""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import cv2

from app.pipeline import reflow_occurrences as ro
from app.pipeline import system_tracking as st
from drum_score_fixture import render
from reflow_fixture import STEP, build, loader, show, strip


def static(specs):
    return [(i * STEP, render(spec)) for i, spec in enumerate(specs)]


def run(frames):
    manifest, images = build(frames)
    load = loader(images)
    tracking = st.build_episodes(manifest, load)
    return tracking, ro.build_occurrences(tracking, manifest, load)


class OneObservationScreenTest(unittest.TestCase):
    """F01: a fully different line seen in one observation is listed, never dropped."""

    def test_a_b_a_keeps_a_whole_and_lists_b(self):
        a, b = strip(4), strip(9)
        tracking, occ = run(static([a] * 12 + [b] + [a] * 12))
        ordinary = [e for e in tracking["episodes"] if not e.get("transient_display")]
        shown = [e for e in tracking["episodes"] if e.get("transient_display")]
        self.assertEqual([e["n_obs"] for e in ordinary], [24])  # A is not split: printed once
        self.assertEqual([e["observation_ids"] for e in shown], [["obs-000012"]])
        self.assertEqual(tracking["transient_displays"], [shown[0]["id"]])
        self.assertEqual([s["included"] for s in occ["systems"]], [True, False])
        self.assertIn("SHORT_DISPLAY", occ["systems"][1]["issues"])
        self.assertEqual(occ["systems"][1]["episode_ids"], [shown[0]["id"]])

    def test_a_b_c_lists_the_one_observation_b(self):
        tracking, occ = run(static([strip(4)] * 12 + [strip(9)] + [strip(7)] * 12))
        self.assertEqual([s["included"] for s in occ["systems"]], [True, False, True])

    def test_last_observation_alone_is_a_terminal_listed_display(self):
        a, b = strip(4), strip(9)
        tracking, occ = run(static([a] * 24 + [b]))
        last = [e for e in tracking["episodes"] if e.get("transient_display")]
        self.assertEqual(len(last), 1)
        self.assertEqual(last[0]["ended_by"], "end_of_source")
        self.assertEqual([s["included"] for s in occ["systems"]], [True, False])
        self.assertTrue(occ["systems"][1]["terminal_display"])

    def test_one_observation_subset_of_its_display_is_hidden(self):
        a = strip(4)
        frames = static([a] * 25)
        glitch = frames[12][1].copy()
        glitch[:, glitch.shape[1] // 2:] = 255  # half the line blanked for one frame
        frames[12] = (frames[12][0], glitch)
        tracking, occ = run(frames)
        self.assertEqual(len([e for e in tracking["episodes"] if e.get("transient_display")]), 1)
        self.assertEqual([s["included"] for s in occ["systems"]], [True])
        self.assertTrue(occ["fragments"][0]["hidden"])

    def test_jump_run_keeps_its_transient_display_listed(self):
        # review follow-up: A x12, B x1, A x12 with A shown by a jump-view run. B was excluded with
        # the run by slot/time alone and vanished (no system, no fragment); it is listed now.
        a, b = strip(4), strip(9)
        frames = static([a] * 12 + [b] + [a] * 12)
        manifest, images = build(frames)
        load = loader(images)
        tracking = st.build_episodes(manifest, load)
        run_eps = [e["id"] for e in tracking["episodes"] if not e.get("transient_display")]
        shown = [e["id"] for e in tracking["episodes"] if e.get("transient_display")]
        self.assertEqual(len(shown), 1)
        occ = ro.build_occurrences(tracking, manifest, load, exclude_episode_ids=run_eps)
        self.assertEqual([s["episode_ids"] for s in occ["systems"]], [shown])
        self.assertFalse(occ["systems"][0]["included"])
        self.assertIn("SHORT_DISPLAY", occ["systems"][0]["issues"])
        # the jump analysis itself still works on the ordinary displays
        self.assertEqual([e["id"] for e in st.without_transient_displays(tracking)["episodes"]], run_eps)


class ShortScreenOneNeighbourTest(unittest.TestCase):
    """F05: a short B whose halves are drawn by A and C is not hidden by their union."""

    def test_union_of_two_neighbours_does_not_hide(self):
        a, c = strip(4), strip(9)
        b = a.copy()
        b.notes = {k: list(v) for k, v in a.notes.items() if k[1] < 2}
        b.notes.update({k: list(v) for k, v in c.notes.items() if k[1] >= 2})
        _tracking, occ = run(static([a] * 12 + [b] * 4 + [c] * 12))
        self.assertEqual([s["included"] for s in occ["systems"]], [True, False, True])
        self.assertFalse(occ["fragments"][0]["hidden"])

    def test_short_screen_drawn_by_one_neighbour_is_still_hidden(self):
        a, c = strip(4), strip(9)
        b = a.copy()
        b.notes = {k: list(v) for k, v in a.notes.items() if k[1] < 2}  # A's first half only
        _tracking, occ = run(static([a] * 12 + [b] * 4 + [c] * 12))
        self.assertEqual([s["included"] for s in occ["systems"]], [True, True])
        self.assertTrue(occ["fragments"][0]["hidden"])
        self.assertEqual(occ["fragments"][0]["represented_by"], [occ["systems"][0]["id"]])


class MiddleNumberStepTest(unittest.TestCase):
    """F04: a cursor-less 33 -> 37 -> 33 is split, or flagged when the middle is too short."""

    def track(self, bars):
        manifest, images = build(static([strip(4, numbers=True, first_bar=n) for n in bars]))
        return st.build_episodes(manifest, loader(images))

    def test_stable_middle_number_splits_in_three(self):
        tracking = self.track([33] * 12 + [37] * 12 + [33] * 12)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [12, 12, 12])
        self.assertEqual(len(tracking["number_steps"]), 2)
        self.assertEqual(tracking["number_steps_unresolved"], [])

    def test_short_middle_number_is_flagged_not_split(self):
        tracking = self.track([33] * 12 + [37] * 2 + [33] * 12)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [26])
        self.assertTrue(tracking["episodes"][0]["number_step_unresolved"])
        self.assertEqual(tracking["number_steps_unresolved"][0]["reason"], "unstable_middle_run")

    def test_distinct_numbers_still_three_lines_and_same_number_one(self):
        self.assertEqual(len(self.track([13] * 12 + [17] * 12 + [13] * 12)["episodes"]), 3)
        same = self.track([33] * 30)
        self.assertEqual(len(same["episodes"]), 1)
        self.assertEqual(same["number_steps_unresolved"], [])


class RemovalStepTest(unittest.TestCase):
    """F09: a mark shown by the majority and gone at the end splits as a content step."""

    def test_mark_removed_for_the_last_twelve_observations_splits(self):
        frames = show(strip(4), 0, 8, seed=1)
        for i, (_t, im) in enumerate(frames):
            if i < 20:
                cv2.line(im, (700, 150), (760, 150), (0, 0, 0), 2)
        tracking, occ = run(frames)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [20, 12])
        self.assertEqual([(c["kind"], c["state_with_ink"]) for c in tracking["content_steps"]], [("removed", "earlier")])
        self.assertEqual([s["included"] for s in occ["systems"]], [True, True])
        self.assertIn("POSSIBLE_SAME_DISPLAY", occ["systems"][1]["issues"])

    def test_mark_added_for_the_last_twelve_observations_still_splits(self):
        frames = show(strip(4), 0, 8, seed=1)
        for i, (_t, im) in enumerate(frames):
            if i >= 20:
                cv2.line(im, (700, 150), (760, 150), (0, 0, 0), 2)
        tracking, _occ = run(frames)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [20, 12])
        self.assertEqual([c["kind"] for c in tracking["content_steps"]], ["added"])

    def test_unchanged_display_has_no_step(self):
        tracking, _occ = run(show(strip(4), 0, 8, seed=1))
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [32])
        self.assertEqual(tracking["content_steps"], [])


class PossibleRepeatAfterSelectionTest(unittest.TestCase):
    """F07: the ‡ pair is worked out on the composed selection."""

    @staticmethod
    def fam(sid, **kw):
        return {"id": sid, "content_family": {"id": "F", "score": 0}, "issues": [], **kw}

    def test_dropped_middle_part_pairs_the_printed_neighbours(self):
        a = self.fam("a")
        b = self.fam("b", issues=["POSSIBLE_SAME_DISPLAY"], possible_repeat_of="a")
        c = self.fam("c", issues=["POSSIBLE_SAME_DISPLAY"], possible_repeat_of="b")
        self.assertEqual(ro.possible_repeat_pairs([a, b, c]),
                         [{"system_id": "b", "of_system_id": "a"}, {"system_id": "c", "of_system_id": "b"}])
        self.assertEqual(ro.possible_repeat_pairs([a, c]), [{"system_id": "c", "of_system_id": "a"}])
        self.assertEqual(ro.possible_repeat_pairs([c]), [])

    def test_certainly_different_numbers_keep_a_pair_cleared(self):
        a = self.fam("a")
        b = self.fam("b", possible_repeat_cleared={"of": "a"})
        c = self.fam("c", issues=["POSSIBLE_SAME_DISPLAY"], possible_repeat_of="b", repeat_cleared_with=["a"])
        self.assertEqual(ro.possible_repeat_pairs([a, b]), [])
        self.assertEqual(ro.possible_repeat_pairs([a, c]), [])
        self.assertEqual(ro.possible_repeat_pairs([a, b, c]), [{"system_id": "c", "of_system_id": "b"}])

    def test_without_family_the_recorded_pair_is_kept(self):
        a = {"id": "a", "issues": []}
        b = {"id": "b", "issues": ["POSSIBLE_SAME_DISPLAY"], "possible_repeat_of": "a"}
        self.assertEqual(ro.possible_repeat_pairs([a, b]), [{"system_id": "b", "of_system_id": "a"}])
        self.assertEqual(ro.possible_repeat_pairs([b]), [])

    def test_composed_pdf_keeps_the_notice_when_the_middle_part_is_dropped(self):
        from test_reflow_measure import Doc, measure_strip
        from test_reflow_occurrences import EMPTY_MANIFEST, ep, never_load, tracking

        eps = [ep("a", "slot-00", 0, 4, started="first_observation", ended="content_step"),
               ep("b", "slot-00", 4.25, 4.75, started="content_step", ended="content_step"),
               ep("c", "slot-00", 5, 9, started="content_step", ended="end_of_source")]
        for e in eps:
            e["content_family"] = {"id": "F", "score": 0}
        occ = ro.build_occurrences(tracking(eps), EMPTY_MANIFEST, never_load)
        self.assertEqual([s["included"] for s in occ["systems"]], [True, False, True])
        with tempfile.TemporaryDirectory() as tmp:
            doc = Doc(Path(tmp))
            for o in occ["systems"]:
                s = doc.add(o["id"], *measure_strip())
                for k in ("included", "issues", "content_family", "possible_repeat_of", "repeat_cleared_with"):
                    if k in o:
                        s[k] = o[k]
            plan, _pages = doc.compose([s for s in doc.systems if s["included"]], measure_reflow=True)
            # the ‡ local notice is printed (audit F07: it disappeared when the middle part was dropped)
            self.assertTrue([m for p in plan["pages"] for m in p.get("markers", [])])


def ramp_1(i, n):
    return .3 + .6 * (i + .5) / n


def ramp_2(i, n):
    return .3 + .6 * (i + .2) / n


def two_cycles(a, b, *, first_number=None, second_number=None):
    """Two plays of a line: ``a`` then ``b``, the playhead restarting between them."""
    one, two = show(a, 0, 4, seed=1, phases=ramp_1), show(b, 4, 4, seed=2, phases=ramp_2)
    if first_number is not None:
        from test_reflow_split_join import numbered
        one, two = numbered(one, first_number), numbered(two, second_number)
    return one + two


def reset_split_occurrences(frames, cut=16):
    """Occurrences of the given frames split by the tracker at a playhead reset before ``cut``."""
    from test_reflow_split_join import tracking_from
    manifest, images = build(frames)
    return ro.build_occurrences(tracking_from(manifest, [cut], boundary="playhead_reset"), manifest, loader(images))


def one_note_less(spec):
    other = spec.copy()
    other.notes = {k: list(v) for k, v in spec.notes.items()}
    key = sorted(k for k, v in other.notes.items() if v)[3]
    other.notes[key] = other.notes[key][:-1]
    return other


class PlayheadResetNeverJoinsTest(unittest.TestCase):
    """F03: a reset alone never joins two displays; a possible repeat gets ‡, a certain
    difference is two lines without a notice, and no other join rule re-merges the split."""

    def test_two_cursor_cycles_of_one_groove_are_two_systems_with_a_notice(self):
        tracking, occ = run(two_cycles(strip(4), strip(4)))
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [16, 16])
        self.assertEqual([e["ended_by"] for e in tracking["episodes"]][:1], ["playhead_reset"])
        first, later = occ["systems"]
        self.assertTrue(first["included"] and later["included"])
        self.assertEqual(later["issues"], ["POSSIBLE_SAME_DISPLAY"])
        self.assertEqual(later["possible_repeat_of"], first["id"])
        self.assertEqual(later["possible_repeat_basis"], "playhead_reset")
        self.assertEqual(occ["joins"], [])
        self.assertEqual(ro.possible_repeat_pairs(occ["systems"]), [{"system_id": later["id"], "of_system_id": first["id"]}])
        # unticking either side prints it once, without a notice
        self.assertEqual(ro.possible_repeat_pairs([first]), [])
        self.assertEqual(ro.possible_repeat_pairs([later]), [])

    def test_cycles_differing_by_one_note_are_two_lines_without_a_notice(self):
        a = strip(4)
        occ = reset_split_occurrences(two_cycles(a, one_note_less(a)))
        self.assertEqual([s["episode_ids"] for s in occ["systems"]], [["ep-0000"], ["ep-0001"]])
        self.assertTrue(all(s["included"] for s in occ["systems"]))
        self.assertNotIn("POSSIBLE_SAME_DISPLAY", occ["systems"][1]["issues"])
        self.assertEqual(occ["joins"], [])
        self.assertEqual([(r["possible_repeat"], r["verdict"]) for r in occ["reset_splits"]], [(False, "veto")])
        self.assertEqual([v["path"] for v in occ["identity_vetoes"]], ["playhead_reset_same_display"])

    def test_difference_only_in_a_middle_member_is_not_merged(self):
        a = strip(4)
        frames = two_cycles(a, a)
        changed = show(one_note_less(a), 4, 4, seed=2, phases=ramp_2)
        for i in range(20, 28):  # middle of the second cycle; its first and last views equal the first cycle
            frames[i] = changed[i - 16]
        occ = reset_split_occurrences(frames)
        self.assertEqual([s["episode_ids"] for s in occ["systems"]], [["ep-0000"], ["ep-0001"]])
        self.assertTrue(all(s["included"] for s in occ["systems"]))
        self.assertNotIn("POSSIBLE_SAME_DISPLAY", occ["systems"][1]["issues"])
        self.assertEqual(occ["reset_splits"][0]["verdict"], "veto")
        self.assertEqual(occ["joins"], [])

    def test_same_cycles_split_by_the_tracker_keep_the_notice(self):
        a = strip(4)
        occ = reset_split_occurrences(two_cycles(a, a))
        self.assertEqual([s["episode_ids"] for s in occ["systems"]], [["ep-0000"], ["ep-0001"]])
        self.assertEqual(occ["systems"][1]["possible_repeat_of"], occ["systems"][0]["id"])
        self.assertEqual(occ["reset_splits"][0]["verdict"], "same")

    def test_steady_other_row_does_not_re_merge_a_reset_split(self):
        from test_reflow_split_join import IdentityVetoAllPathsTest, numbered, ramp, two_row_tracking
        (manifest, images), cut = IdentityVetoAllPathsTest._page(None, "13", "13")
        n = len(manifest["observations"])
        tracking = two_row_tracking(manifest, cut, boundary="playhead_reset", playhead=ramp(n, restart_at=[cut]))
        occ = ro.build_occurrences(tracking, manifest, loader(images))
        top = [s for s in occ["systems"] if set(s["episode_ids"]) & {"ep-0000", "ep-0001"}]
        self.assertEqual([s["episode_ids"] for s in top], [["ep-0000"], ["ep-0001"]], occ["joins"])
        self.assertTrue(all(s["included"] for s in top))
        self.assertEqual(top[1]["possible_repeat_of"], top[0]["id"])
        self.assertEqual(occ["joins"], [])
        blocked = [v for v in occ["identity_vetoes"] if v["path"] == "unchanged_page_view_same_row"]
        self.assertEqual([v["verdict"] for v in blocked], ["group_holds_identity_veto"])

    def test_distinct_measure_numbers_still_veto_without_a_notice(self):
        a = strip(4)
        occ = reset_split_occurrences(two_cycles(a, a, first_number="13", second_number="17"))
        self.assertEqual([s["episode_ids"] for s in occ["systems"]], [["ep-0000"], ["ep-0001"]])
        self.assertNotIn("POSSIBLE_SAME_DISPLAY", occ["systems"][1]["issues"])
        vetoes = [v for v in occ["identity_vetoes"] if v["path"] == "playhead_reset_same_display"]
        self.assertEqual(len(vetoes), 1)
        self.assertIn(vetoes[0]["verdict"], ("written_display_differs", "measure_number_area_differs"))

    def test_same_number_on_both_cycles_keeps_the_notice(self):
        a = strip(4)
        occ = reset_split_occurrences(two_cycles(a, a, first_number="13", second_number="13"))
        self.assertEqual(len(occ["systems"]), 2)
        self.assertEqual(occ["systems"][1]["possible_repeat_of"], occ["systems"][0]["id"])

    def test_family_part_keeps_a_reset_pair_outside_its_family(self):
        a = {"id": "a", "issues": []}
        b = {"id": "b", "issues": ["POSSIBLE_SAME_DISPLAY"], "possible_repeat_of": "a",
             "content_family": {"id": "F", "score": 0}}
        self.assertEqual(ro.possible_repeat_pairs([a, b]), [{"system_id": "b", "of_system_id": "a"}])


def three_cycles(first, second, third):
    """Three plays of a line, the playhead restarting between them."""
    return (show(first, 0, 4, seed=1, phases=ramp_1) + show(second, 4, 4, seed=2, phases=ramp_2)
            + show(third, 8, 4, seed=3, phases=ramp_1))


class ResetRepeatChainAfterSelectionTest(unittest.TestCase):
    """Review follow-up to F03/F07: three cursor cycles of one un-numbered groove give A, A' (‡ of
    A) and A'' (‡ of A'). Unticking A' must still print A'' with ‡ (paired with A); a certain
    difference in the chain keeps the pair out."""

    def test_unticking_the_middle_cycle_keeps_the_notice(self):
        a = strip(4)
        _tracking, occ = run(three_cycles(a, a, a))
        first, middle, last = occ["systems"]
        self.assertEqual(middle["possible_repeat_of"], first["id"])
        self.assertEqual(last["possible_repeat_of"], middle["id"])
        self.assertEqual(last["possible_repeat_chain"], [first["id"], middle["id"]])
        self.assertEqual(ro.possible_repeat_pairs([first, last]), [{"system_id": last["id"], "of_system_id": first["id"]}])
        self.assertEqual(ro.possible_repeat_pairs([middle, last]), [{"system_id": last["id"], "of_system_id": middle["id"]}])
        self.assertEqual(ro.possible_repeat_pairs([last]), [])

        from test_reflow_measure import Doc, measure_strip
        with tempfile.TemporaryDirectory() as tmp:
            doc = Doc(Path(tmp))
            for o in occ["systems"]:
                s = doc.add(o["id"], *measure_strip())
                for k in ("issues", "possible_repeat_of", "possible_repeat_basis", "possible_repeat_chain",
                          "repeat_cleared_with"):
                    if k in o:
                        s[k] = o[k]
            composed = [s for s in doc.systems if s["id"] != middle["id"]]  # the user unticks A'
            plan, _pages = doc.compose(composed, measure_reflow=True)
            markers = [m for p in plan["pages"] for m in p.get("markers", []) if m.get("kind") == "possible_repeat"]
            self.assertEqual([sid for m in markers for sid in m["system_ids"]], [last["id"]], markers)
            from app.main import _compose_header
            self.assertEqual(_compose_header({"title": "T"}, None, composed)["possible_repeats"],
                             [{"system_id": last["id"], "of_system_id": first["id"]}])

    def test_a_veto_in_the_chain_keeps_the_pair_out(self):
        a = strip(4)
        _tracking, occ = run(three_cycles(a, a, one_note_less(a)))
        first, middle, last = occ["systems"]
        self.assertEqual(middle["possible_repeat_of"], first["id"])
        self.assertNotIn("POSSIBLE_SAME_DISPLAY", last["issues"])
        self.assertNotIn("possible_repeat_chain", last)
        self.assertEqual(ro.possible_repeat_pairs([first, last]), [])
        self.assertEqual(ro.possible_repeat_pairs([first, middle, last]), [{"system_id": middle["id"], "of_system_id": first["id"]}])

    def test_numbers_cleared_further_back_keep_the_pair_out(self):
        a = {"id": "a", "issues": []}
        b = {"id": "b", "issues": ["POSSIBLE_SAME_DISPLAY"], "possible_repeat_of": "a", "possible_repeat_chain": ["a"]}
        c = {"id": "c", "issues": ["POSSIBLE_SAME_DISPLAY"], "possible_repeat_of": "b", "possible_repeat_chain": ["a", "b"],
             "repeat_cleared_with": ["a"]}
        self.assertEqual(ro.possible_repeat_pairs([a, c]), [])
        self.assertEqual(ro.possible_repeat_pairs([a, b, c]),
                         [{"system_id": "b", "of_system_id": "a"}, {"system_id": "c", "of_system_id": "b"}])

    def test_family_part_falls_back_to_its_reset_chain(self):
        a = {"id": "a", "issues": []}
        b = {"id": "b", "issues": [], "content_family": {"id": "F", "score": 0}}
        c = {"id": "c", "issues": ["POSSIBLE_SAME_DISPLAY"], "possible_repeat_of": "b", "possible_repeat_chain": ["a"],
             "content_family": {"id": "F", "score": 0}}
        self.assertEqual(ro.possible_repeat_pairs([a, c]), [{"system_id": "c", "of_system_id": "a"}])
        self.assertEqual(ro.possible_repeat_pairs([a, b, c]), [{"system_id": "c", "of_system_id": "b"}])


class EndTailTest(unittest.TestCase):
    """F06: the last frame is sampled once more, so a screen shown only after the last 0.5 s grid
    sample is observed; the grid itself and the decode-completeness check are unchanged."""

    ROI = [[0, 0], [1400, 0], [1400, 190], [0, 190]]

    def manifest(self, image_at, *, decodable, metadata):
        """A 30 fps capture decoding ``decodable`` frames of a container claiming ``metadata``.
        A seek reaches every frame the container claims (the stream itself continues)."""
        from unittest.mock import patch
        from app.pipeline import observations as ob

        class Capture:
            def __init__(self, *_a):
                self.i = -1
                self.limit = decodable

            def isOpened(self):
                return True

            def set(self, key, value):
                assert key == cv2.CAP_PROP_POS_MSEC
                self.limit = metadata
                self.i = math.ceil(value / 1000.0 * 30.0 - 1e-6) - 1

            def grab(self):
                self.i += 1
                return self.i < self.limit

            def retrieve(self):
                return True, image_at(self.i)

            def get(self, key):
                if key == cv2.CAP_PROP_FPS:
                    return 30.0
                if key == cv2.CAP_PROP_POS_MSEC:
                    return self.i / 30.0 * 1000.0
                return 0

            def release(self):
                pass

        info = ob.VideoInfo("memory", 30.0, metadata, 1400, 190, metadata / 30.0)
        with patch.object(ob, "probe_video", return_value=info), patch.object(ob.cv2, "VideoCapture", Capture), \
                patch.object(ob, "file_sha256", return_value="0" * 64):
            return ob.build_manifest(video_path=Path("/tmp/in_memory_not_a_video"), roi=self.ROI,
                                     store_frames=False, work_scale=1.0)

    def test_screen_after_the_last_grid_sample_is_a_terminal_listed_display(self):
        a, b = render(strip(1)), render(strip(2))
        image_at = lambda i: b if i >= 65 else a  # B from 2.167 s; the last grid sample is 2.0 s
        m = self.manifest(image_at, decodable=75, metadata=75)
        coarse = [o["t_sec"] for o in m["observations"] if o["sample_kind"] == "coarse"]
        self.assertEqual(coarse, [0.0, 0.5, 1.0, 1.5, 2.0, round(74 / 30, 6)])  # grid unchanged + last frame
        load = lambda o: image_at(int(round(o["t_sec"] * 30)))
        tracking = st.build_episodes(m, load)
        occ = ro.build_occurrences(tracking, m, load)
        self.assertEqual(len(occ["systems"]), 2)
        first, tail = occ["systems"]
        self.assertTrue(first["included"])
        self.assertTrue(tail["terminal_display"])
        self.assertIn("SHORT_DISPLAY", tail["issues"])  # listed in review, restorable
        self.assertTrue(all(load(m_obs) is b for m_obs in m["observations"] if m_obs["id"] in
                            {o["obs_id"] for o in tail["observations"]}))

    def test_no_duplicate_observation_at_one_pts(self):
        a = render(strip(1))
        for metadata in (61, 75):  # last frame on the grid (2.0 s) / between grid samples
            with self.subTest(metadata=metadata):
                m = self.manifest(lambda _i: a, decodable=metadata, metadata=metadata)
                ts = [o["t_sec"] for o in m["observations"]]
                self.assertEqual(len(ts), len(set(ts)))
                self.assertEqual(max(ts), round((metadata - 1) / 30, 6))
                self.assertEqual(sum(1 for t in ts if t > 2.0), 0 if metadata == 61 else 1)

    def test_overshooting_frame_count_gives_the_real_last_frame_without_failing(self):
        a = render(strip(1))
        m = self.manifest(lambda _i: a, decodable=70, metadata=75)  # the container claims 5 frames more
        last = m["observations"][-1]
        self.assertEqual(last["t_sec"], round(69 / 30, 6))
        self.assertIn(round(74 / 30, 6), last["requested_t"])
        self.assertEqual(m["sampling"]["sampled_until_sec"], round(70 / 30, 4))  # the decoder's real reach

    def test_decoder_stopping_early_still_fails(self):
        from app.pipeline import observations as ob
        a = render(strip(1))
        with self.assertRaises(ob.VideoDecodeIncompleteError) as ctx:
            self.manifest(lambda _i: a, decodable=45, metadata=180)
        self.assertEqual(ctx.exception.decoded_until, round(44 / 30, 6))

    def test_decoder_stopping_past_the_grid_tolerance_fails(self):
        # audit follow-up: 139 of 180 decodable frames (last at 4.6 s). Every unserved grid point
        # (5.5 s) is within 1 s of the last served sample, but the requested final frame is not.
        from app.pipeline import observations as ob
        a = render(strip(1))
        with self.assertRaises(ob.VideoDecodeIncompleteError) as ctx:
            self.manifest(lambda _i: a, decodable=139, metadata=180)
        self.assertEqual(ctx.exception.decoded_until, round(138 / 30, 6))


if __name__ == "__main__":
    unittest.main()
