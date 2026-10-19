"""Tests for the full notation envelope and the ROI clipping check.

Synthetic frames: a score panel rendered by drum_score_fixture is pasted into
a busy "video" frame. The panel carries an open hi-hat circle high above the
staff, a boxed section label and a lyric line well below the staff, i.e. the
content the old fixed 4.5-gap ROI cut off.
"""

import unittest

import cv2
import numpy as np

from app.pipeline import notation_envelope as ne
from app.pipeline.auto_roi_detector import apply_notation_envelope
from app.pipeline.roi_health import add_envelope_clipping
from drum_score_fixture import groove_notes, render, strip_spec, system_top, PageSpec

W, H = 1280, 800
PANEL_Y0, PANEL_Y1 = 470, 740
GAP = 14


def _video_background(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]
    base = np.stack([(60 + 0.08 * xx) % 255, (90 + 0.1 * yy) % 255, (120 + 0.05 * (xx + yy)) % 255], axis=2).astype(np.uint8)
    for _ in range(40):
        x0, y0 = int(rng.integers(0, W - 60)), int(rng.integers(0, H - 60))
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.rectangle(base, (x0, y0), (x0 + int(rng.integers(20, 200)), y0 + int(rng.integers(20, 160))), color, -1)
    # dark and bright details right above the panel (a drum kit edge)
    cv2.ellipse(base, (400, PANEL_Y0 - 30), (160, 40), 0, 0, 360, (25, 25, 25), -1)
    cv2.ellipse(base, (900, PANEL_Y0 - 20), (120, 30), 0, 0, 360, (235, 235, 235), 3)
    return base


def score_panel(seed: int = 3, *, circle: bool = True, lyrics: bool = True, label: bool = True) -> tuple:
    """(panel image, geometry dict) for a strip with marks around the staff."""
    spec = groove_notes(strip_spec(width=W, height=PANEL_Y1 - PANEL_Y0, gap=GAP, margin_x=70, show_bar_numbers=False), seed=seed)
    img = render(spec)
    top = system_top(spec, 0)
    bot = top + 4 * GAP
    geo = {"staff_top": top + PANEL_Y0, "staff_bot": bot + PANEL_Y0}
    ink = (20, 20, 20)
    if circle:
        cy = top - int(4.6 * GAP)
        cv2.circle(img, (700, cy), 5, ink, 2)
        geo["circle"] = [695 - 1, cy - 6 + PANEL_Y0, 706, cy + 7 + PANEL_Y0]
    if label:
        cv2.rectangle(img, (20, top - int(3.2 * GAP)), (44, top - int(1.6 * GAP)), ink, 2)
        cv2.putText(img, "A", (25, top - int(1.9 * GAP)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ink, 1, cv2.LINE_AA)
    if lyrics:
        base_y = bot + int(4.6 * GAP)
        cv2.putText(img, "la la love song", (200, base_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, ink, 1, cv2.LINE_AA)
        geo["lyrics_bottom"] = base_y + 3 + PANEL_Y0
        geo["lyrics_top"] = base_y - 13 + PANEL_Y0
    return img, geo


def make_frame(seed: int = 3, *, dark: bool = False, **kw) -> tuple:
    frame = _video_background(seed)
    panel, geo = score_panel(seed, **kw)
    if dark:
        panel = 255 - panel
    frame[PANEL_Y0:PANEL_Y1] = panel
    return frame, geo


def legacy_roi(geo) -> list:
    """The old suggestion: staff +-4.5 gaps."""
    return ne.bbox_to_roi([60, geo["staff_top"] - 4.5 * GAP, W - 60, geo["staff_bot"] + 4.5 * GAP])


class SamplingTest(unittest.TestCase):
    def test_twelve_evenly_spaced_times(self):
        times = ne.sample_times(120.0)
        self.assertEqual(len(times), 12)
        self.assertAlmostEqual(times[0], 5.0)
        self.assertAlmostEqual(times[-1], 115.0)
        self.assertTrue(all(b - a == 10.0 for a, b in zip(times, times[1:])))

    def test_degenerate_duration(self):
        self.assertEqual(ne.sample_times(0.0), [0.0])


class StaffDetectionTest(unittest.TestCase):
    def test_finds_panel_staff_in_busy_frame(self):
        frame, geo = make_frame()
        staves = ne.detect_staves(frame)
        self.assertEqual(len(staves), 1, staves)
        self.assertEqual(staves[0]["polarity"], "dark_on_light")
        self.assertAlmostEqual(staves[0]["lines"][0], geo["staff_top"], delta=2)
        self.assertAlmostEqual(staves[0]["gap"], GAP, delta=1)

    def test_dark_polarity_panel(self):
        frame, geo = make_frame(dark=True)
        staves = ne.detect_staves(frame)
        self.assertEqual(len(staves), 1, staves)
        self.assertEqual(staves[0]["polarity"], "light_on_dark")
        self.assertAlmostEqual(staves[0]["lines"][0], geo["staff_top"], delta=2)


class EnvelopeTest(unittest.TestCase):
    def _check_cover(self, env, geo):
        x0, y0, x1, y1 = env
        self.assertLessEqual(y0, geo["circle"][1], "open-hat circle above the staff")
        self.assertGreaterEqual(y1, geo["lyrics_bottom"] - 1, "lyrics below the staff")
        self.assertLessEqual(x0, 21, "boxed label left of the staff")
        # Bounded by the panel: no video content taken in.
        self.assertGreaterEqual(y0, PANEL_Y0)
        self.assertLessEqual(y1, PANEL_Y1)

    def test_frame_envelope_covers_marks_text_and_lyrics(self):
        frame, geo = make_frame()
        fr = ne.frame_envelope(frame)
        self.assertEqual(len(fr["rows"]), 1)
        row = fr["rows"][0]
        self._check_cover(row["envelope_bbox"], geo)
        self.assertEqual(row["panel"][1], PANEL_Y0)
        self.assertTrue(row["panel_bounded"]["top"])

    def test_dark_polarity_envelope(self):
        frame, geo = make_frame(dark=True)
        row = ne.frame_envelope(frame)["rows"][0]
        self._check_cover(row["envelope_bbox"], geo)

    def test_source_envelope_padding_and_non_score_frames(self):
        frames = [(float(t), make_frame(seed=s)[0]) for t, s in ((1, 3), (2, 4), (3, 5))]
        _, geo = make_frame(seed=3)
        frames.insert(0, (0.0, _video_background(9)))  # intro card without a staff
        env = ne.analyze_samples(frames)
        self.assertEqual(env["status"], "found")
        self.assertEqual(env["skipped_times"], [0.0])
        self.assertEqual(env["score_times"], [1.0, 2.0, 3.0])
        sx0, sy0, sx1, sy1 = env["suggested_bbox"]
        ex0, ey0, ex1, ey1 = env["envelope_bbox"]
        # The panel top is within 3 gaps of the padded envelope: the rest of
        # the panel is taken in, never the video above it.
        self.assertEqual(sy0, PANEL_Y0)
        self.assertIn("snapped_to_panel", env["flags"])
        self.assertGreaterEqual(ey0 - sy0, 0.75 * env["gap"] - 1.0)
        self.assertGreaterEqual(sy1 - ey1, 0.75 * env["gap"] - 1.0)
        self.assertLessEqual(sy1, PANEL_Y1)
        self.assertEqual(ne.public(env).keys() & {"_rows"}, set())

    def test_padding_is_three_quarter_gap_when_the_paper_continues(self):
        frames = []
        for t, seed in ((1.0, 3), (2.0, 4)):
            frame, geo = make_frame(seed=seed)
            frame[60:PANEL_Y0] = 255  # paper continues far above the score
            frame[PANEL_Y1:] = 255
            frames.append((t, frame))
        env = ne.analyze_samples(frames)
        sx0, sy0, sx1, sy1 = env["suggested_bbox"]
        ex0, ey0, ex1, ey1 = env["envelope_bbox"]
        self.assertAlmostEqual(ey0 - sy0, 0.75 * env["gap"], delta=1.0)
        self.assertAlmostEqual(sx1 - ex1, 0.5 * env["gap"], delta=1.0)
        self.assertAlmostEqual(sy1 - ey1, 0.75 * env["gap"], delta=1.0)

    def test_stray_staff_with_other_gap_is_ignored(self):
        frame, _ = make_frame()
        # A small "next line" preview box elsewhere with a much smaller staff.
        small = render(groove_notes(PageSpec(width=420, height=120, systems=1, gap=7, margin_x=20), seed=2))
        frame[60:180, 800:1220] = small
        env = ne.analyze_samples([(0.0, frame), (1.0, make_frame(seed=4)[0])])
        self.assertEqual(env["status"], "found")
        self.assertGreaterEqual(env["envelope_bbox"][1], PANEL_Y0)

    def test_no_staff(self):
        env = ne.analyze_samples([(0.0, _video_background(1)), (1.0, _video_background(2))])
        self.assertEqual(env["status"], "no_staff")
        self.assertIsNone(env["suggested_bbox"])

    def test_full_page_paper_reaches_frame_edges(self):
        spec = groove_notes(PageSpec(width=1200, height=800, systems=4, gap=12), seed=5)
        page = render(spec)
        cv2.putText(page, "Song Title", (450, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2, cv2.LINE_AA)
        env = ne.analyze_samples([(0.0, page)])
        self.assertEqual(env["status"], "found")
        self.assertLessEqual(env["envelope_bbox"][1], 12, "title above the first system")
        self.assertEqual(len(env["frames"][0]["rows"]), 4)


class ClippingTest(unittest.TestCase):
    def setUp(self):
        self.frame, self.geo = make_frame()
        self.env = ne.analyze_samples([(4.0, self.frame), (8.0, make_frame(seed=4)[0])])

    def test_legacy_roi_clips_circle_and_lyrics(self):
        clip = ne.check_roi_clipping(self.env, legacy_roi(self.geo))
        self.assertTrue(clip["clipped"])
        self.assertEqual(clip["code"], ne.ENVELOPE_CLIPPED)
        self.assertGreater(clip["counts"]["top"], 0)
        self.assertGreater(clip["counts"]["bottom"], 0)
        top_hits = [loc for loc in clip["locations"] if loc["edge"] == "top" and loc["t_sec"] == 4.0]
        self.assertTrue(any(abs(loc["bbox"][0] - self.geo["circle"][0]) <= 3 for loc in top_hits), top_hits)
        sx0, sy0, sx1, sy1 = ne.roi_to_bbox(clip["suggested_roi"])
        self.assertLessEqual(sy0, self.geo["circle"][1])
        self.assertGreaterEqual(sy1, self.geo["lyrics_bottom"])

    def test_single_small_circle_is_enough(self):
        frame, geo = make_frame(lyrics=False, label=False)
        env = ne.analyze_samples([(0.0, frame)])
        # ROI that covers everything except the open-hat circle.
        roi = ne.bbox_to_roi([0, geo["circle"][3] + 2, W, PANEL_Y1])
        clip = ne.check_roi_clipping(env, roi)
        self.assertTrue(clip["clipped"])
        self.assertEqual(clip["counts"]["bottom"], 0)
        self.assertGreaterEqual(clip["counts"]["top"], 1)
        self.assertGreaterEqual(clip["cut_counts"]["top"], 1)
        self.assertTrue(all(loc["cut"] for loc in clip["locations"] if loc["edge"] == "top"))

    def test_near_edge_without_cut_is_reported_as_near(self):
        frame, geo = make_frame(lyrics=False, label=False)
        env = ne.analyze_samples([(0.0, frame)])
        # Top edge 1 px above the circle: inside the ROI but within 0.25 gap.
        roi = ne.bbox_to_roi([0, geo["circle"][1] - 1, W, PANEL_Y1])
        clip = ne.check_roi_clipping(env, roi)
        self.assertTrue(clip["clipped"])
        self.assertGreaterEqual(clip["counts"]["top"], 1)
        self.assertEqual(clip["cut_counts"]["top"], 0)

    def test_suggested_roi_is_clean(self):
        clip = ne.check_roi_clipping(self.env, ne.bbox_to_roi(self.env["suggested_bbox"]))
        self.assertFalse(clip["clipped"], clip["locations"])

    def test_edge_on_panel_border_is_not_reported(self):
        # Notation that the video itself cuts at the panel edge cannot be
        # recovered by moving the ROI into the video.
        roi = ne.bbox_to_roi([0, PANEL_Y0, W, PANEL_Y1])
        clip = ne.check_roi_clipping(self.env, roi)
        self.assertFalse(clip["clipped"], clip["locations"])

    def test_staff_outside_roi(self):
        roi = ne.bbox_to_roi([0, 100, W, 400])
        clip = ne.check_roi_clipping(self.env, roi)
        self.assertTrue(clip["clipped"])
        self.assertGreater(clip["counts"]["staff_outside"], 0)


class IntegrationTest(unittest.TestCase):
    def test_auto_roi_uses_envelope_and_keeps_fallback(self):
        frame, geo = make_frame()
        env = ne.analyze_samples([(1.0, frame), (2.0, make_frame(seed=4)[0])])
        legacy = {"status": "suggested", "roi": legacy_roi(geo), "evidence_level": "high", "is_dark_mode": False,
                  "diagnostics": {"supporting_frames": 3}}
        out = apply_notation_envelope(legacy, env)
        self.assertEqual(out["status"], "suggested")
        self.assertEqual(out["diagnostics"]["method"], "notation_envelope")
        self.assertEqual(out["diagnostics"]["envelope"]["sampled_times"], [1.0, 2.0])
        self.assertTrue(out["diagnostics"]["envelope"]["rows"])
        x0, y0, x1, y1 = ne.roi_to_bbox(out["roi"])
        self.assertLessEqual(y0, geo["circle"][1])
        self.assertGreaterEqual(y1, geo["lyrics_bottom"])

        none = ne.analyze_samples([(0.0, _video_background(1))])
        kept = apply_notation_envelope(legacy, none)
        self.assertEqual(kept["roi"], legacy["roi"])
        self.assertEqual(kept["diagnostics"]["method"], "fixed_padding")
        self.assertIn("no_staff", kept["diagnostics"]["reason"])

    def test_health_warning_does_not_block_capture(self):
        frame, geo = make_frame()
        env = ne.analyze_samples([(1.0, frame)])
        base = {"risk_level": "info", "summary": "", "diagnostics": [{"level": "info", "code": "roi_healthy", "title": "", "detail": ""}],
                "sampled_frames": 3, "metrics": {}}
        out = add_envelope_clipping(base, env, legacy_roi(geo))
        self.assertEqual(out["risk_level"], "warning")
        codes = [d["code"] for d in out["diagnostics"]]
        self.assertEqual(codes, ["envelope_clipped"])
        self.assertTrue(out["envelope"]["clipped"])
        self.assertIsNotNone(out["envelope"]["suggested_roi"])
        self.assertNotEqual(out["risk_level"], "critical")

        clean = add_envelope_clipping(base, env, ne.bbox_to_roi(env["suggested_bbox"]))
        self.assertEqual(clean["risk_level"], "info")
        self.assertFalse(clean["envelope"]["clipped"])


if __name__ == "__main__":
    unittest.main()
