"""Strip-cleaning speed-ups keep every minority finding.

The minority check predicts a member's registration against the composite from the strip
registration (only when unambiguous) and computes overlay masks only where they are read.
Each case runs build_strip twice - with the prediction and with every member registered
exactly (as before) - and requires the same finding from both.
"""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline import reflow_strips as rs
from test_reflow_visibility_marks import paper, system_case

_REAL_PHASE = cv2.phaseCorrelate


def _run(images, *, exact):
    calls = []

    def phase(*args, **kwargs):
        calls.append(1)
        return _REAL_PHASE(*args, **kwargs)

    system, manifest, load = system_case(images)
    with patch.object(rs.cv2, "phaseCorrelate", side_effect=phase):
        if exact:
            with patch.object(rs, "PREDICT_MIN_RESPONSE", 2.0):  # no prediction: every member registered
                strip, rec = rs.build_strip(system, manifest, load, chrome=False)
        else:
            strip, rec = rs.build_strip(system, manifest, load, chrome=False)
    return strip, rec, len(calls)


def _summary(rec):
    mc = rec["minority_content"]
    events = [(e["box_crop"], e["members"], e["seen"], e["eligible"], e["classification"],
               e.get("disposition"), e.get("eligibility")) for e in mc["events"]]
    explained = [(e["box_crop"], e["members"], e["classification"]) for e in mc.get("explained_events", [])]
    rejected = [(r["obs_id"], r["classification"]) for r in mc.get("rejected_observations", [])]
    return events, explained, rejected, mc["checked_members"], mc["skipped_members"], rec["issues"]


def _covers(event, x, y):
    x0, y0, x1, y1 = event["box_crop"]
    return x0 <= x < x1 and y0 <= y < y1


class PredictedRegistrationKeepsFindingsTest(unittest.TestCase):
    def both(self, images):
        strip_p, rec_p, calls_p = _run(images, exact=False)
        strip_e, rec_e, calls_e = _run(images, exact=True)
        self.assertEqual(_summary(rec_p), _summary(rec_e))
        self.assertTrue(np.array_equal(strip_p, strip_e))
        return rec_p, strip_p, calls_p, calls_e

    def test_small_mark_in_exactly_one_member(self):
        images = [paper() for _ in range(12)]
        images[5][110:122, 420] = 0
        rec, _strip, calls_p, calls_e = self.both(images)
        self.assertLess(calls_p, calls_e)  # the prediction was used for some members
        events = [e for e in rec["minority_content"]["events"] if _covers(e, 420, 110)]
        self.assertTrue(events)
        self.assertEqual(events[0]["seen"], 1)
        self.assertEqual(events[0]["eligible"], 12)

    def test_dot_missing_from_composite_beside_other_ink(self):
        images = [paper() for _ in range(12)]
        for im in images:  # notation around the dot: a notehead and its stem
            cv2.circle(im, (410, 80), 5, (0, 0, 0), -1)
            cv2.line(im, (415, 80), (415, 40), (0, 0, 0), 1)
        images[7][78:81, 424:427] = 0  # a staccato-like dot in one member only
        rec, _strip, calls_p, calls_e = self.both(images)
        self.assertLess(calls_p, calls_e)
        self.assertTrue(any(_covers(e, 425, 79) and e["members"] == [7]
                            for e in rec["minority_content"]["events"]))

    def test_mark_at_the_crop_boundary(self):
        images = [paper() for _ in range(12)]
        images[4][0:6, 600] = 0  # touches the top edge of the strip crop (and of the frame)
        rec, _strip, calls_p, calls_e = self.both(images)
        self.assertLess(calls_p, calls_e)
        # the event starts on the crop's first row (a single-row display keeps the full height)
        self.assertTrue(any(_covers(e, 600, 0) and e["box_crop"][1] == 0 for e in rec["minority_content"]["events"]))

    def test_ink_revealed_when_a_cursor_moves(self):
        # A colored playhead parked over a printed dot in every member but one; the member
        # that reveals the dot is not among the composite's sampled members.
        n = 40
        images = []
        for i in range(n):
            im = paper()
            im[110:113, 430:433] = 0
            x = 600 if i == 1 else 428 + (i % 3)
            im[15:135, x:x + 8] = (200, 60, 200)
            images.append(im)
        rec, strip, calls_p, calls_e = self.both(images)
        self.assertLess(calls_p, calls_e)
        found = any(_covers(e, 431, 111) for e in rec["minority_content"]["events"])
        drawn = bool((strip[111 - rec["box_crop"][1], 431 - rec["box_crop"][0]] < 100).all())
        self.assertTrue(found or drawn)

    def test_misregistered_member_is_still_registered_exactly_and_rejected(self):
        images = [paper() for _ in range(12)]
        images[5] = np.roll(images[5], 3, axis=1)
        images[5][110:122, 420] = 0
        rec, _strip, _p, _e = self.both(images)
        rejected = rec["minority_content"]["rejected_observations"]
        self.assertEqual([r["classification"] for r in rejected], ["INELIGIBLE_REGISTRATION"])
        self.assertTrue(any("INELIGIBLE_REGISTRATION" in e.get("eligibility", [])
                            for e in rec["minority_content"]["events"]))


class LazyOverlayMaskTest(unittest.TestCase):
    def count_overlays(self, images):
        calls = []
        real = rs._overlay_mask2d

        def overlay(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        system, manifest, load = system_case(images)
        with patch.object(rs, "_overlay_mask2d", side_effect=overlay):
            _strip, rec = rs.build_strip(system, manifest, load, chrome=False)
        return len(calls), rec

    def test_clean_members_need_no_overlay_mask_beyond_the_composite(self):
        calls, rec = self.count_overlays([paper() for _ in range(40)])
        self.assertEqual(rec["minority_content"]["events"], [])
        self.assertEqual(calls, rec["members_offered"])  # only the composite's own members

    def test_an_event_still_counts_every_eligible_member(self):
        images = [paper() for _ in range(40)]
        images[1][110:122, 420] = 0
        calls, rec = self.count_overlays(images)
        events = [e for e in rec["minority_content"]["events"] if _covers(e, 420, 110)]
        self.assertTrue(events)
        self.assertEqual(events[0]["eligible"], 40)
        self.assertEqual(calls, 40)


class SharedTransitionReferenceTest(unittest.TestCase):
    def test_prepared_reference_gives_the_same_evidence(self):
        from app.pipeline import minority_content as mc
        ref = cv2.cvtColor(paper(), cv2.COLOR_BGR2GRAY)
        warped = cv2.warpAffine(ref, np.array([[1, 0, 0], [.04, 1, -16]], np.float32), (800, 160), borderValue=255)
        mark = ref.copy(); mark[110:122, 420] = 0
        shadow = ref.copy()
        yy, xx = np.indices(ref.shape)
        shadow[(xx + 2 * yy > 500) & (shadow > 200)] = 170
        prepared = mc.transition_reference(ref, 12)
        for gray in (warped, mark, shadow, ref):
            self.assertEqual(mc.transition_evidence(gray, ref, 12, prepared=prepared),
                             mc.transition_evidence(gray, ref, 12))
        self.assertIsNotNone(mc.transition_evidence(warped, ref, 12, prepared=prepared))
        self.assertIsNone(mc.transition_evidence(mark, ref, 12, prepared=prepared))


if __name__ == "__main__":
    unittest.main()
