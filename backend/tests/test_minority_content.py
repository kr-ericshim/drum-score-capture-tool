"""Audit round 4, blocker 1: content shown in a minority of a display's observations.

Astra's probe (build_episodes -> build_occurrences -> build_strip): 32 frames with a
radius-2 black dot in 8 consecutive frames gave one episode, one included strip, no
fragment, no dot pixel in the strip and no issue. Content may leave the composite only
when it is explained as an overlay (colored ink, the detected playhead, a cursor track);
any other neutral component shown by >= 2 consecutive observations is split into its
own display (a stable change at the start or end of a display) or flagged
MINORITY_CONTENT_DROPPED with an alternate strip that shows it.
"""

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app import main
from app.pipeline import minority_content as mc
from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_pipeline as rp
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as st
from drum_score_fixture import Overlay, render
from reflow_fixture import STEP, build, loader, show, strip

DOT = (600, 30)


def with_marks(frames, frame_range, draw):
    out = []
    for i, (t, img) in enumerate(frames):
        img = img.copy()
        if i in frame_range:
            draw(img)
        out.append((t, img))
    return out


def dot(img):
    cv2.circle(img, DOT, 2, (0, 0, 0), -1)


def stroke(img):
    cv2.line(img, (700, 150), (760, 150), (0, 0, 0), 2)


def pipeline(frames, out_dir=None):
    manifest, images = build(frames)
    load = loader(images)
    tracking = st.build_episodes(manifest, load)
    occ = ro.build_occurrences(tracking, manifest, load)
    td = None
    if out_dir is None:
        td = tempfile.TemporaryDirectory()
        out_dir = Path(td.name)
    recs = rs.build_strips(occ, manifest, load, Path(out_dir))
    return tracking, occ, recs, td


def dark_pixels(img, box_crop, rec):
    """Dark pixels of a strip image inside a crop-coordinate box."""
    x0, y0 = rec["box_crop"][0], rec["box_crop"][1]
    seg = img[max(0, box_crop[1] - y0 - 1):box_crop[3] - y0 + 1, max(0, box_crop[0] - x0 - 1):box_crop[2] - x0 + 1]
    return int((cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY) < 128).sum()) if seg.size else 0


def dark_playhead_frames(n=32, parked=1, width=5, gray=60):
    spec = strip(5)
    frames = []
    for i in range(n):
        img = render(spec)
        x = int(60 + (i // parked + 0.5) / (n // parked) * 1280)
        cv2.rectangle(img, (x - width // 2, 25), (x + width // 2, 165), (gray, gray, gray), -1)
        frames.append((i * STEP, img))
    return frames


class AstraProbeTest(unittest.TestCase):
    def test_dot_in_eight_of_32_frames_is_flagged_with_an_alternate_that_shows_it(self):
        frames = with_marks(show(strip(4), 0.0, 8.0, seed=1), range(12, 20), dot)
        self.assertEqual(len(frames), 32)
        manifest, images = build(frames)
        load = loader(images)
        tracking = st.build_episodes(manifest, load)
        occ = ro.build_occurrences(tracking, manifest, load)
        included = [s for s in occ["systems"] if s["included"]]
        self.assertEqual(len(included), 1)
        img, rec = rs.build_strip(included[0], manifest, load)
        box = [DOT[0] - 2, DOT[1] - 2, DOT[0] + 3, DOT[1] + 3]
        self.assertEqual(dark_pixels(img, box, rec), 0)  # the majority composite leaves the dot out ...
        self.assertIn(rs.MINORITY_ISSUE, rec["issues"])  # ... but never silently
        ev = rec["minority_content"]["events"]
        self.assertEqual(len(ev), 1)
        b = ev[0]["box_crop"]
        self.assertTrue(b[0] <= DOT[0] <= b[2] and b[1] <= DOT[1] <= b[3], b)
        t0, t1 = ev[0]["times"][0]
        self.assertGreaterEqual(t0, 12 * STEP - 1e-6)
        self.assertLessEqual(t1, 19 * STEP + 1e-6)
        alts = rec["minority_content"]["alternates"]
        self.assertEqual(len(alts), 1)
        alt_img = rec["_alternate_images"][0]
        self.assertGreaterEqual(dark_pixels(alt_img, box, {"box_crop": alts[0]["box_crop"]}), 8)
        self.assertTrue(set(alts[0]["obs_ids"]) <= {o["id"] for o in manifest["observations"][12:20]})

    def test_build_strips_writes_the_alternate(self):
        frames = with_marks(show(strip(4), 0.0, 8.0, seed=1), range(12, 20), dot)
        _tr, _occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        alt = recs[0]["minority_content"]["alternates"][0]
        self.assertTrue(Path(alt["path"]).is_file())
        self.assertNotIn("_alternate_images", recs[0])


class ExplainedOverlayTest(unittest.TestCase):
    def test_neutral_playhead_without_colored_recovery_evidence_keeps_review_bundle(self):
        tracking, occ, recs, td = pipeline(dark_playhead_frames())
        self.addCleanup(td.cleanup)
        self.assertEqual(len(tracking["episodes"]), 1)
        self.assertEqual(tracking["content_steps"], [])
        self.assertIn(rs.UNCERTAIN_MARK_KEPT,recs[0]["issues"])
        self.assertTrue(recs[0]["minority_content"]["events"])
        self.assertEqual(len(recs[0]["minority_content"]["alternates"]),1)
        img = cv2.imread(recs[0]["path"])
        clean = render(strip(5))
        x0, y0, x1, y1 = recs[0]["box_crop"]
        diff = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(int) - cv2.cvtColor(clean[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(int)
        self.assertEqual(int((diff < -60).sum()), 0)  # no playhead left in the strip

    def test_dark_stroke_without_colored_track_and_recovery_stays_uncertain(self):
        # Position-only dark strokes lack colored continuation/recovery evidence.
        tracking, occ, recs, td = pipeline(dark_playhead_frames(n=32, parked=2, width=2, gray=20))
        self.addCleanup(td.cleanup)
        self.assertEqual(len(tracking["episodes"]), 1, tracking["content_steps"])
        self.assertIn(rs.UNCERTAIN_MARK_KEPT, recs[0]["issues"])
        self.assertFalse(recs[0]["minority_content"]["cursor_track"]["track"])

    def test_colored_overlays_raise_no_flag(self):
        spec = strip(3)
        box_frames = [(i * STEP, render(spec, [Overlay("box", position=(i + 0.5) / 32, color=(230, 160, 60))])) for i in range(32)]
        for frames in (box_frames, show(strip(4), 0.0, 8.0, seed=1)):
            tracking, occ, recs, td = pipeline(frames)
            self.addCleanup(td.cleanup)
            self.assertEqual(len(tracking["episodes"]), 1)
            self.assertEqual([r["issues"] for r in recs], [[]])

    def test_a_single_differing_frame_keeps_an_uncertain_alternate(self):
        tracking, occ, recs, td = pipeline(with_marks(show(strip(4), 0.0, 8.0, seed=1), {14}, dot))
        self.addCleanup(td.cleanup)
        self.assertIn(rs.UNCERTAIN_MARK_KEPT, recs[0]["issues"])
        alt = recs[0]["minority_content"]["alternates"][0]
        self.assertGreater(dark_pixels(cv2.imread(alt["path"]), [598, 28, 603, 33], alt), 0)


class MinorityStrokeTest(unittest.TestCase):
    def test_stroke_shown_then_gone_is_flagged(self):
        tracking, occ, recs, td = pipeline(with_marks(show(strip(4), 0.0, 8.0, seed=1), range(10, 16), stroke))
        self.addCleanup(td.cleanup)
        self.assertEqual(len(tracking["episodes"]), 1)
        self.assertIn(rs.MINORITY_ISSUE, recs[0]["issues"])
        ev = recs[0]["minority_content"]["events"][0]
        self.assertLessEqual(ev["box_crop"][0], 700)
        self.assertGreaterEqual(ev["box_crop"][2], 760)
        alt = recs[0]["minority_content"]["alternates"][0]
        img = cv2.imread(alt["path"])
        self.assertGreater(dark_pixels(img, [700, 149, 761, 152], alt), 60)

    def test_stroke_added_for_good_splits_the_display(self):
        # A shared content family cannot prove these are the same written line.
        tracking, occ, recs, td = pipeline(with_marks(show(strip(4), 0.0, 8.0, seed=1), range(20, 32), stroke))
        self.addCleanup(td.cleanup)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [20, 12])
        self.assertEqual(tracking["episodes"][1]["started_by"], "content_step")
        self.assertEqual(tracking["content_steps"][0]["kind"], "added")
        self.assertEqual(tracking["content_steps"][0]["state_with_ink"], "later")
        self.assertEqual([(s["id"], s["included"]) for s in occ["systems"]], [("sys-001", True), ("sys-002", True)])
        earlier, later = occ["systems"]
        self.assertGreater(later["t_start"], earlier["t_start"])
        self.assertEqual(later["possible_repeat_of"], earlier["id"])
        self.assertEqual(later["issues"], ["POSSIBLE_SAME_DISPLAY"])
        self.assertTrue(all("alternate_of" not in s and "alternate_kind" not in s for s in occ["systems"]))
        self.assertEqual(occ["exclusions"]["short_listed_excluded"], [])
        self.assertEqual(occ["exclusions"]["content_step_alternates"], [])
        self.assertEqual([r["issues"] for r in recs], [[], []])
        self.assertEqual(dark_pixels(cv2.imread(recs[0]["path"]), [700, 149, 761, 152], recs[0]), 0)
        self.assertGreater(dark_pixels(cv2.imread(recs[1]["path"]), [700, 149, 761, 152], recs[1]), 60)

    def test_mark_removed_for_good_splits_the_display(self):
        tracking, occ, recs, td = pipeline(with_marks(show(strip(4), 0.0, 8.0, seed=1), range(0, 10), stroke))
        self.addCleanup(td.cleanup)
        self.assertEqual([e["n_obs"] for e in tracking["episodes"]], [10, 22])
        self.assertEqual(tracking["content_steps"][0]["state_with_ink"], "earlier")
        self.assertEqual([(s["id"], s["included"]) for s in occ["systems"]], [("sys-001", True), ("sys-002", True)])
        self.assertLess(occ["systems"][0]["t_start"], occ["systems"][1]["t_start"])
        self.assertEqual(occ["systems"][1]["possible_repeat_of"], "sys-001")
        self.assertGreater(dark_pixels(cv2.imread(recs[0]["path"]), [700, 149, 761, 152], recs[0]), 60)

    def test_short_mark_at_the_end_of_a_display_does_not_split_it(self):
        # two observations at the edge (0.25 s) are a hand-over, not a state: no content step
        frames = with_marks(show(strip(4), 0.0, 8.0, seed=1), range(30, 32), stroke)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertEqual(tracking["content_steps"], [])
        self.assertEqual([s["included"] for s in occ["systems"]], [True])


def speck(img):
    cv2.circle(img, DOT, 1, (0, 0, 0), -1)


def displays(seeds, seconds=6.0):
    frames = []
    for k, seed in enumerate(seeds):
        frames.extend(show(strip(seed), k * seconds, seconds, seed=seed))
    return frames


class Round5Test(unittest.TestCase):
    """Family parts stay visible; screen-position specks and hand-over runs stay uncertain."""

    def test_three_family_parts_are_all_placed_in_video_order(self):
        def second(img):
            cv2.line(img, (300, 150), (340, 150), (0, 0, 0), 2)
        frames = with_marks(with_marks(show(strip(4), 0.0, 8.0, seed=1), range(10, 32), stroke), range(21, 32), second)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertGreaterEqual(len(tracking["content_steps"]), 2)
        systems = occ["systems"]
        self.assertEqual([(s["id"], s["included"]) for s in systems],
                         [("sys-001", True), ("sys-002", True), ("sys-003", True)])
        self.assertEqual([s.get("possible_repeat_of") for s in systems], [None, "sys-001", "sys-002"])
        self.assertEqual([s["t_start"] for s in systems], sorted(s["t_start"] for s in systems))
        self.assertGreaterEqual(systems[-1]["t_start"], 21 * STEP - 1e-6)
        self.assertGreater(dark_pixels(cv2.imread(recs[-1]["path"]), [300, 149, 341, 152], recs[-1]), 30)
        self.assertGreater(dark_pixels(cv2.imread(recs[-1]["path"]), [700, 149, 761, 152], recs[-1]), 60)

    def test_recurrent_screen_position_is_suspicion_not_exclusion(self):
        frames = displays([4, 5, 6])
        frames = with_marks(frames, set(range(8, 14)) | set(range(32, 38)) | set(range(56, 62)), speck)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertEqual(tracking["content_steps"], [])
        self.assertEqual([s["included"] for s in occ["systems"]], [True, True, True])
        self.assertTrue(all(rs.UNCERTAIN_MARK_KEPT in r["issues"] for r in recs))
        self.assertEqual(sum(len(r["minority_content"].get("screen_fixed_suspicions", [])) for r in recs), 3)
        self.assertEqual(sum(len(r["minority_content"]["alternates"]) for r in recs), 3)

    def test_speck_in_two_displays_is_still_flagged(self):
        frames = with_marks(displays([4, 5, 6]), set(range(8, 14)) | set(range(32, 38)), speck)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertEqual([rs.MINORITY_ISSUE in r["issues"] for r in recs], [True, True, False])
        self.assertEqual([len(r["minority_content"]["alternates"]) for r in recs], [1, 1, 0])

    def test_short_run_at_a_hand_over_keeps_uncertain_ink(self):
        # Timing at a hand-over alone does not prove that the stroke is a transition.
        frames = with_marks(displays([4, 5]), {22, 23}, stroke)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertEqual(tracking["content_steps"], [])
        self.assertEqual([s["included"] for s in occ["systems"]], [True, True])
        self.assertIn(rs.UNCERTAIN_MARK_KEPT, recs[0]["issues"])
        self.assertEqual(len(recs[0]["minority_content"]["alternates"]), 1)
        self.assertEqual(recs[0]["minority_content"]["edge_transitions"], [])

    def test_short_run_at_the_end_of_the_source_is_flagged(self):
        frames = with_marks(displays([4, 5]), {46, 47}, stroke)
        tracking, occ, recs, td = pipeline(frames)
        self.addCleanup(td.cleanup)
        self.assertIn(rs.MINORITY_ISSUE, recs[1]["issues"])
        self.assertEqual(len(recs[1]["minority_content"]["alternates"]), 1)


class EventGroupingTest(unittest.TestCase):
    def test_runs_need_two_consecutive_members(self):
        m = np.zeros((40, 40), bool)
        m[10:13, 10:13] = True
        masks = {0: np.zeros_like(m), 1: m, 2: np.zeros_like(m), 3: m, 4: m}
        ev = mc.minority_events(masks, 12.0)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["runs"], [(3, 4)])

    def test_unexplained_ignores_overlay_columns(self):
        ref = np.zeros((30, 30), bool)
        mask = np.zeros_like(ref)
        mask[5:9, 5:9] = True
        cols = np.zeros(30, bool)
        cols[4:10] = True
        u, _shift = mc.unexplained(mask, ref, cols, 12.0)
        self.assertFalse(u.any())


class InkLikeTest(unittest.TestCase):
    def test_video_glint_through_a_band_is_background_and_a_dot_on_paper_is_not(self):
        norm = np.full((60, 120, 3), 250, np.uint8)
        rng = np.random.default_rng(1)
        norm[:, 60:] = rng.integers(150, 215, size=(60, 60, 1)).astype(np.uint8)  # video texture behind the band
        mask = np.zeros((60, 120), bool)
        mask[28:32, 20:24] = True   # a dot on paper
        mask[28:32, 88:92] = True   # a glint on video
        kept, dropped = mc.drop_on_video_background(mask, mc.background_texture(norm, 12.0))
        self.assertEqual(dropped, 1)
        self.assertTrue(kept[28:32, 20:24].all())
        self.assertFalse(kept[28:32, 88:92].any())

    def test_dense_notation_is_not_video_background(self):
        # the anti-aliased edges of a printed score do not read as video behind the band
        from app.pipeline import system_detect as sd
        _t, img = show(strip(4), 0.0, 1.0, seed=1)[0]
        norm = sd.normalize_polarity(img)[0]
        tex = mc.background_texture(norm, 12.0)
        ink = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY) < 110
        self.assertLess(float(tex[ink].max()), mc.VIDEO_BACKGROUND_MIN)

    def test_gray_lighter_than_the_ink_is_not_ink_like(self):
        clean = np.full((40, 80, 3), 255, np.uint8)
        clean[5:30, 5:8] = 5      # score ink (a stem)
        clean[10:14, 40:44] = 100  # translucent-band video, lighter than the ink
        clean[20:24, 60:64] = 20   # a dark dot
        n = mc.neutral_ink(clean)
        self.assertFalse(n[10:14, 40:44].any())
        self.assertTrue(n[20:24, 60:64].all())


def write_video(frames, path):
    h, w = frames[0][1].shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"FFV1"), 4, (w, h))
    for _t, img in frames:
        vw.write(img)
    vw.release()


class PipelineAlternateTest(unittest.TestCase):
    """The alternate is a listed, unchecked system right after its system (job record,
    occurrences.json, review diagnostics) and can be composed in its place."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        root = Path(cls.td.name)
        frames = with_marks(show(strip(4), 0.0, 8.0, seed=1), range(12, 20), dot)
        write_video(frames, root / "v.avi")
        cls.record = rp.analyse_source(video_path=root / "v.avi", roi=[[0, 0], [1400, 0], [1400, 190], [0, 190]],
                                       workspace=root / "reflow")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_alternate_is_listed_unchecked_after_its_system(self):
        systems = self.record["systems"]
        self.assertEqual([s["id"] for s in systems], ["sys-001", "sys-001-alt1"])
        main_s, alt = systems
        self.assertIn(rs.MINORITY_ISSUE, main_s["issues"])
        self.assertFalse(alt["included"])
        self.assertEqual(alt["alternate_of"], "sys-001")
        self.assertIn(rp.MINORITY_ALTERNATE, alt["issues"])
        self.assertTrue(Path(alt["strip_path"]).is_file())
        occ = json.loads((Path(self.record["workspace"]) / "occurrences.json").read_text())
        self.assertEqual([s["id"] for s in occ["systems"]], ["sys-001", "sys-001-alt1"])
        self.assertTrue(occ["systems"][1]["observations"])

    def test_review_diagnostics_name_the_alternate(self):
        fields = main._reflow_capture_fields(rp.public_record(self.record))
        main_s, alt = self.record["systems"]
        d_main = fields["capture_diagnostics"][main_s["strip_path"]]
        d_alt = fields["capture_diagnostics"][alt["strip_path"]]
        self.assertIn("MINORITY_CONTENT_DROPPED", d_main["diagnostic_codes"])
        self.assertTrue(any("잠깐만 보인" in r and "only for a moment" in r for r in d_main["warning_reasons"]))
        self.assertEqual(d_main["alternate_paths"], [alt["strip_path"]])
        self.assertEqual(d_main["minority_content"][0]["alternate"], "sys-001-alt1")
        self.assertEqual(d_alt["alternate_of"], "sys-001")
        self.assertIn("MINORITY_ALTERNATE", d_alt["diagnostic_codes"])
        self.assertEqual(fields["review_candidates"], [main_s["strip_path"], alt["strip_path"]])

    def test_the_alternate_can_be_composed_in_place_of_its_system(self):
        alt = self.record["systems"][1]
        plan, pages = rp.compose_systems([alt], all_systems=self.record["systems"], workspace=Path(self.record["workspace"]))
        self.assertEqual([pl["system_id"] for p in plan["pages"] for pl in p["placements"]], ["sys-001-alt1"])



class PipelineContentStepStateTest(unittest.TestCase):
    """Content-family parts remain ordinary systems, with a review warning and local PDF mark."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        root = Path(cls.td.name)
        write_video(with_marks(show(strip(4), 0.0, 8.0, seed=1), range(20, 32), stroke), root / "v.avi")
        cls.record = rp.analyse_source(video_path=root / "v.avi", roi=[[0, 0], [1400, 0], [1400, 190], [0, 190]],
                                       workspace=root / "reflow")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_both_parts_are_placed_with_family_diagnostics_and_review_reason(self):
        systems = self.record["systems"]
        self.assertEqual([(s["id"], s["included"]) for s in systems], [("sys-001", True), ("sys-002", True)])
        earlier, later = systems
        self.assertEqual(later["possible_repeat_of"], earlier["id"])
        self.assertEqual(earlier["content_family"]["id"], later["content_family"]["id"])
        self.assertTrue(all("alternate_of" not in s and "alternate_kind" not in s for s in systems))
        self.assertLess(earlier["t_start"], later["t_start"])
        fields = main._reflow_capture_fields(rp.public_record(self.record))
        diagnostic = fields["capture_diagnostics"][later["strip_path"]]
        self.assertIn("POSSIBLE_SAME_DISPLAY", diagnostic["diagnostic_codes"])
        self.assertEqual(diagnostic["warning_reasons"], [dict(main.REFLOW_ISSUE_REASONS)["POSSIBLE_SAME_DISPLAY"]])
        self.assertEqual(fields["review_candidates"], [earlier["strip_path"], later["strip_path"]])

    def test_the_other_state_can_be_placed_instead_or_with(self):
        earlier, later = self.record["systems"]
        ws = Path(self.record["workspace"])
        plan, _pages = rp.compose_systems([later], all_systems=self.record["systems"], workspace=ws)
        self.assertEqual([pl["system_id"] for p in plan["pages"] for pl in p["placements"]], ["sys-002"])
        self.assertFalse(any(p.get("markers") for p in plan["pages"]))
        plan, _pages = rp.compose_systems([earlier, later], all_systems=self.record["systems"], workspace=ws)
        self.assertEqual([pl["system_id"] for p in plan["pages"] for pl in p["placements"]], ["sys-001", "sys-002"])
        self.assertEqual([m["kind"] for p in plan["pages"] for m in p.get("markers", [])], ["possible_repeat"])


if __name__ == "__main__":
    unittest.main()
