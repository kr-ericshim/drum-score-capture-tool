"""Fix round 6: content families end at view transitions, and the round-5 paths that had no
test (tie rule, alternate tails, short families, mixed alternate numbering, start-edge runs)."""

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_pipeline as rp
from app.pipeline import reflow_strips as rs
from app.pipeline import system_detect as sd
from app.pipeline import system_tracking as st
from reflow_fixture import STEP, frame, page, show, strip
from test_minority_content import dark_pixels, displays, dot, pipeline, stroke, with_marks, write_video
from test_reflow_strips import full_frames, preview_frames, system_image


def top_mark(img):
    """A stroke above row 0 of a two-row page (row 0 staff at y 70..118)."""
    cv2.line(img, (700, 50), (760, 50), (0, 0, 0), 2)


def second(img):
    cv2.line(img, (300, 150), (340, 150), (0, 0, 0), 2)


def view_transition_frames():
    """A two-row page shown 8 s. Observations 8 and 9 show two other pages (a page curl /
    flip-through: both rows change for two observations), then the same page returns. Row 0
    gets a stroke for good from observation 20 (a content step after the transition)."""
    frames = show(page([4, 5]), 0.0, 8.0, system=0, seed=1)
    for k, other in ((8, page([6, 7])), (9, page([8, 9]))):
        frames[k] = (frames[k][0], frame(other, 0.3, seed=500 + k))
    return with_marks(frames, range(20, 32), top_mark)


def member(i, t):
    return st._Member(f"obs-{i:06d}", f"obs-{i:06d}-r0", t, 70.0, 12.0, "active", None)


def part(start, n, started_by, family="F", score=0):
    ep = st._Episode("slot-00", [member(start + k, (start + k) * STEP) for k in range(n)], started_by=started_by)
    ep.family, ep.family_score = family, score
    return ep


class FamilyAtViewTransitionTest(unittest.TestCase):
    """A content family is the states of one continuous display: a view transition ends the
    display, a playhead reset does not."""

    def test_rekey_starts_a_new_family_at_each_view_transition(self):
        parts = [part(0, 4, "first_observation"), part(6, 4, "view_transition", score=0),
                 part(10, 4, "content_step", score=1), part(14, 4, "playhead_reset", score=1),
                 part(20, 4, "view_transition", score=1), part(40, 4, "first_observation", family=None)]
        log = [{"slot_id": "slot-00", "obs_id": "obs-000010", "family": "F"}]
        st._rekey_families_at_view_transitions(parts, log)
        self.assertEqual([p.family for p in parts], [None, "F-v1", "F-v1", "F-v1", None, None])
        self.assertEqual([p.family_score for p in parts], [0, 0, 1, 1, 1, 0])  # scores are kept
        self.assertEqual(log[0]["family"], "F-v1")

    def test_content_step_after_a_view_transition_places_one_system_on_each_side(self):
        tracking, occ, recs, td = pipeline(view_transition_frames())
        self.addCleanup(td.cleanup)
        row0 = [e for e in tracking["episodes"] if e["slot_id"] == "slot-00"]
        self.assertEqual([e["started_by"] for e in row0], ["first_observation", "view_transition", "content_step"])
        # the part before the transition is its own display (no family); the two states after it are one family
        self.assertNotIn("content_family", row0[0])
        self.assertEqual(row0[1]["content_family"]["id"], row0[2]["content_family"]["id"])
        self.assertEqual(tracking["content_steps"][0]["family"], row0[2]["content_family"]["id"])
        systems = [s for s in occ["systems"] if s["slot_id"] == "slot-00"]
        placed = [s for s in systems if s["included"]]
        self.assertEqual(len(placed), 2)
        before, after = placed
        self.assertLess(before["t_end"], 8 * STEP)          # one placed before the transition ...
        self.assertGreaterEqual(after["t_start"], 10 * STEP)  # ... and one after it
        self.assertEqual(before["episode_ids"], [row0[0]["id"]])
        self.assertEqual(after["episode_ids"], [row0[2]["id"]])  # the state with the stroke
        alts = [s for s in systems if s.get("alternate_of")]
        self.assertEqual([(s["episode_ids"], s["alternate_of"]) for s in alts], [([row0[1]["id"]], after["id"])])
        # no episode is placed twice
        placed_eps = [e for s in occ["systems"] if s["included"] for e in s["episode_ids"]]
        self.assertEqual(len(placed_eps), len(set(placed_eps)))
        # the placed later state keeps its place in the page view (above row 1 of the same view)
        ids = [s["id"] for s in occ["systems"] if not s.get("alternate_of")]
        row1_after = next(s for s in occ["systems"] if s["slot_id"] == "slot-01" and s["t_start"] >= 2.0)
        self.assertLess(ids.index(after["id"]), ids.index(row1_after["id"]))

    def test_playhead_reset_inside_a_family_still_places_one_part(self):
        frames = with_marks(show(strip(5), 0.0, 4.0, seed=1) + show(strip(5), 4.0, 4.0, seed=2), range(24, 32), stroke)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        eps = tracking["episodes"]
        self.assertEqual([e["started_by"] for e in eps], ["first_observation", "playhead_reset", "content_step"])
        self.assertEqual(len({e["content_family"]["id"] for e in eps}), 1)  # the reset keeps the family
        self.assertEqual(sum(s["included"] for s in occ["systems"]), 1)
        placed = next(s for s in occ["systems"] if s["included"])
        self.assertEqual(placed["episode_ids"], [eps[2]["id"]])
        self.assertEqual([s["alternate_of"] for s in occ["systems"] if not s["included"]], [placed["id"]])


class Round5PathsTest(unittest.TestCase):
    def test_tie_places_the_later_state(self):
        # a mark removed for good at 2.5 s and another added for good at 5.5 s: the first and the
        # last state each show one step's ink (score 1 each); the later one is placed
        frames = with_marks(with_marks(show(strip(4), 0.0, 8.0, seed=1), range(0, 10), stroke), range(22, 32), second)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertEqual([e["content_family"]["score"] for e in tracking["episodes"]], [1, 0, 1])
        self.assertEqual([(s["id"], s["included"]) for s in occ["systems"]],
                         [("sys-001", True), ("sys-001-alt1", False), ("sys-001-alt2", False)])
        self.assertAlmostEqual(occ["systems"][0]["t_start"], 22 * STEP)
        self.assertEqual([s["t_start"] for s in occ["systems"][1:]], [0.0, 10 * STEP])

    def test_tie_rule_unit(self):
        def cand(root, t, score):
            return {"root": root, "t_start": t, "episodes": [{"content_family": {"id": "F", "score": score}}]}
        self.assertEqual(ro.content_step_alternates([cand("a", 0.0, 1), cand("b", 5.0, 1)], []), {"a": "b"})
        self.assertEqual(ro.content_step_alternates([cand("a", 0.0, 2), cand("b", 5.0, 1)], []), {"b": "a"})

    def test_content_step_alternate_keeps_its_preview_tail(self):
        cur, nxt = system_image(7), system_image(8)
        frames = with_marks(preview_frames(cur, nxt, n=32), range(16, 32), stroke) + full_frames(nxt, n=32, t0=8)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertEqual([(s["id"], s["included"]) for s in occ["systems"]],
                         [("sys-001", True), ("sys-001-alt1", False), ("sys-002", True)])
        placed, alt = recs[0], recs[1]
        self.assertTrue(placed["preview_tail"]["cut"])  # the placed state: verified against sys-002
        self.assertFalse(alt["preview_tail"]["cut"])
        self.assertEqual(alt["preview_tail"]["reason"], "alternate_keeps_the_tail")
        self.assertIn("PREVIEW_TAIL_UNVERIFIED", alt["issues"])
        self.assertNotIn("uncut", alt)
        self.assertGreater(alt["size"][0], placed["size"][0] + 200)  # the tail is on the alternate's strip

    def test_family_with_no_part_long_enough_stays_listed_short_displays(self):
        tracking, occ, recs, td = pipeline(with_marks(show(strip(4), 0.0, 2.0, seed=1), range(4, 8), stroke))
        self.addCleanup(td.cleanup)
        self.assertEqual(len(tracking["content_steps"]), 1)
        self.assertEqual(len({e["content_family"]["id"] for e in tracking["episodes"]}), 1)
        self.assertEqual([(s["id"], s["included"], s["issues"]) for s in occ["systems"]],
                         [("sys-001", False, ["SHORT_DISPLAY"]), ("sys-002", False, ["SHORT_DISPLAY"])])
        self.assertFalse(any(s.get("alternate_of") for s in occ["systems"]))
        self.assertEqual(occ["exclusions"]["content_step_alternates"], [])
        self.assertEqual(occ["exclusions"]["short_listed_excluded"], ["sys-001", "sys-002"])

    def test_short_run_at_the_start_of_a_later_display_keeps_uncertain_ink(self):
        # A hand-over does not prove the visible stroke is disposable.
        tracking, occ, recs, td = pipeline(with_marks(displays([4, 5]), {24, 25}, stroke))
        self.addCleanup(td.cleanup)
        self.assertEqual(tracking["content_steps"], [])
        self.assertEqual([s["included"] for s in occ["systems"]], [True, True])
        self.assertEqual(recs[0]["issues"], [])
        self.assertIn(rs.UNCERTAIN_MARK_KEPT, recs[1]["issues"])
        self.assertEqual(len(recs[1]["minority_content"]["events"]), 1)
        self.assertEqual(len(recs[1]["minority_content"]["alternates"]), 1)
        edge = recs[1]["minority_content"]["edge_transitions"]
        self.assertEqual(len(edge), 0)
        self.assertEqual(recs[0]["minority_content"]["edge_transitions"], [])


class MixedAlternateNumberingTest(unittest.TestCase):
    """One placed system with a content-step state and a minority moment: alt1 is the state,
    alt2 the moment, the same ids in the job record, occurrences.json and the strip files,
    listed after the system in number order."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        root = Path(cls.td.name)
        frames = with_marks(with_marks(show(strip(4), 0.0, 8.0, seed=1), range(16, 32), stroke), range(22, 27), dot)
        write_video(frames, root / "v.avi")
        cls.record = rp.analyse_source(video_path=root / "v.avi", roi=[[0, 0], [1400, 0], [1400, 190], [0, 190]],
                                       workspace=root / "reflow")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_ids_and_order(self):
        systems = self.record["systems"]
        self.assertEqual([(s["id"], s["included"], s.get("alternate_of")) for s in systems],
                         [("sys-001", True, None), ("sys-001-alt1", False, "sys-001"), ("sys-001-alt2", False, "sys-001")])
        main_s, state, moment = systems
        self.assertEqual(state.get("alternate_kind"), "content_step_state")
        self.assertIn(rp.MINORITY_ALTERNATE, moment["issues"])
        self.assertEqual(moment["alternate_kind"], "uncertain_mark_bundle")
        self.assertTrue(moment["review_bundle"]["evidence_patches"])
        self.assertLess(state["t_start"], main_s["t_start"])
        self.assertTrue(Path(state["strip_path"]).name == "strip_sys-001-alt1.png")
        self.assertTrue(Path(moment["strip_path"]).name == "strip_sys-001-alt2.png")
        self.assertTrue(all(Path(s["strip_path"]).is_file() for s in systems))
        ev = main_s["strip"]["minority_content"]["events"]
        self.assertEqual([e.get("alternate") for e in ev], ["alt2"])
        occ = json.loads((Path(self.record["workspace"]) / "occurrences.json").read_text())
        self.assertEqual([s["id"] for s in occ["systems"]], ["sys-001", "sys-001-alt1", "sys-001-alt2"])
        # the moment shows the dot, the placed strip leaves it out
        box = [598, 28, 603, 33]
        self.assertGreaterEqual(dark_pixels(cv2.imread(moment["strip_path"]), box, moment["strip"]), 8)
        self.assertEqual(dark_pixels(cv2.imread(main_s["strip_path"]), box, main_s["strip"]), 0)


class AlternateOrderUnitTest(unittest.TestCase):
    def test_runs_of_alternates_are_sorted_by_number(self):
        ids = [("sys-001", None), ("sys-001-alt3", "sys-001"), ("sys-001-alt1", "sys-001"), ("sys-001-alt2", "sys-001"),
               ("sys-002", None), ("sys-002-alt1", "sys-002")]
        systems = [{"id": i, **({"alternate_of": a} if a else {})} for i, a in ids]
        self.assertEqual([systems[k]["id"] for k in rp._alternates_in_number_order(systems)],
                         ["sys-001", "sys-001-alt1", "sys-001-alt2", "sys-001-alt3", "sys-002", "sys-002-alt1"])


class AnchorCacheTest(unittest.TestCase):
    def test_closed_episodes_release_their_anchor(self):
        released = []
        orig = st._Episode.release_anchor

        def spy(self):
            orig(self)
            released.append((self.anchor_band, dict(self.anchor_cache), self.ended_by))
        frames = show(strip(1), 0.0, 3.0, seed=1) + show(strip(2), 3.0, 3.0, seed=2)
        from reflow_fixture import build, loader
        manifest, images = build(frames)
        from unittest.mock import patch
        with patch.object(st._Episode, "release_anchor", spy):
            out = st.build_episodes(manifest, loader(images))
        self.assertEqual([r[2] for r in released], ["content_change", "end_of_source"])
        self.assertTrue(all(band is None and cache == {} for band, cache, _e in released))
        self.assertEqual(len(out["episodes"]), 2)


class PercentileTest(unittest.TestCase):
    def test_matches_numpy_and_falls_back_for_non_2d_input(self):
        rng = np.random.default_rng(3)
        g = rng.integers(0, 256, size=(37, 53), dtype=np.uint8)
        for q in (0, 12.5, 50, 75, 99.9, 100):
            self.assertEqual(sd.percentile_u8(g, q), float(np.percentile(g, q)))
        bgr = rng.integers(0, 256, size=(20, 30, 3), dtype=np.uint8)
        self.assertEqual(sd.percentile_u8(bgr, 50), float(np.percentile(bgr, 50)))
        flat = g.ravel()
        self.assertEqual(sd.percentile_u8(flat, 75), float(np.percentile(flat, 75)))


class RoleTieTest(unittest.TestCase):
    def test_a_role_tie_is_unknown_in_every_process(self):
        # Q8 ep-0006: one "preview" and one "unknown" member; set order used to decide it
        for roles in (["preview", "unknown"], ["unknown", "preview"], ["active", "unknown"]):
            ep = st._Episode("slot-00", [st._Member(f"obs-{k:06d}", f"obs-{k:06d}-r0", k * STEP, 70.0, 12.0, r, None)
                                         for k, r in enumerate(roles)])
            rec = st._episode_record("ep-0000", ep, 10.0)
            self.assertEqual(rec["role"], "unknown")
            self.assertEqual(list(rec["role_counts"]), sorted(set(roles)))


if __name__ == "__main__":
    unittest.main()
