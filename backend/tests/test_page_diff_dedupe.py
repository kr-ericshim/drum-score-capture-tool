"""Regression tests for blob-level page comparison and temporal dedupe.

The synthetic frames come from drum_score_fixture: real drum notation
(5-line staves, x/oval heads, stems, bar lines, bar numbers) with playback
overlays, degraded like a captured video frame. The cases pin down the three
failure modes the old whole-image metrics had:

* a page that differs by only a few note heads was dropped as a duplicate,
* a moving playhead / highlight box was mistaken for a score change,
* an identical-looking next page (repeated groove) vanished silently.
"""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.page_diff import (
    VERDICT_AMBIGUOUS,
    VERDICT_DIFFERENT,
    VERDICT_SAME,
    compare_frames,
    estimate_staff_gap,
    playhead_jumped_back,
)
from app.pipeline.stitch import select_review_candidates, stitch_pages
from app.schemas import StitchOptions
from drum_score_fixture import (
    Degrade,
    Overlay,
    PageSpec,
    add_note,
    degrade,
    groove_notes,
    move_note,
    remove_slot,
    render,
    strip_spec,
)


LEVELS = ("sensitive", "normal", "aggressive")


def _video(image: np.ndarray, **overrides) -> np.ndarray:
    params = dict(scale=0.75, blur=0.8, jpeg_quality=70, noise=2.0)
    params.update(overrides)
    return degrade(image, Degrade(**params))


def _empty_hihat_slot(spec: PageSpec, system: int):
    for bar in range(spec.bars_per_system):
        for slot in range(spec.slots_per_bar):
            if -0.5 not in spec.notes.get((system, bar, slot), []):
                return system, bar, slot
    raise AssertionError("fixture has no free hi-hat slot")


class TestCompareFramesPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = groove_notes(PageSpec(), seed=3)
        cls.strip = groove_notes(strip_spec(), seed=5)

    def assertVerdict(self, a, b, expected, *, levels=LEVELS, degrade_b=None):
        for level in levels:
            verdict = compare_frames(_video(a), _video(b) if degrade_b is None else degrade_b, dedupe_level=level)
            allowed = expected if isinstance(expected, (set, tuple)) else {expected}
            self.assertIn(
                verdict.verdict,
                allowed,
                f"level={level}: got {verdict.verdict} ({verdict.reason}, blobs={verdict.significant_blobs}+{verdict.minor_blobs})",
            )

    def test_staff_gap_is_estimated_from_rendered_staves(self):
        gray = cv2.cvtColor(_video(render(self.page)), cv2.COLOR_BGR2GRAY)
        ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 9)
        self.assertAlmostEqual(estimate_staff_gap(ink), float(self.page.gap), delta=1.0)

    def test_identical_page_with_jitter_blur_and_tone_drift_is_same(self):
        drifted = degrade(
            render(self.page),
            Degrade(scale=0.75, blur=1.0, jpeg_quality=60, jitter=(3, -2), gain=0.92, bias=8, noise=3, seed=9),
        )
        self.assertVerdict(render(self.page), render(self.page), VERDICT_SAME, degrade_b=drifted)

    def test_heavily_degraded_identical_page_is_same(self):
        heavy = degrade(render(self.page), Degrade(scale=0.5, blur=1.5, jpeg_quality=40, noise=5, jitter=(5, 3), seed=2))
        verdict = compare_frames(_video(render(self.page), scale=0.5, blur=1.2, jpeg_quality=45, noise=4), heavy)
        self.assertEqual(verdict.verdict, VERDICT_SAME, verdict.reason)
        self.assertAlmostEqual(verdict.shift_x, 5.0, delta=1.0)
        self.assertAlmostEqual(verdict.shift_y, 3.0, delta=1.0)

    def test_small_rotation_from_roi_refit_is_same(self):
        image = render(self.page)
        matrix = cv2.getRotationMatrix2D((image.shape[1] / 2, image.shape[0] / 2), 0.4, 1.0)
        rotated = cv2.warpAffine(image, matrix, (image.shape[1], image.shape[0]), borderMode=cv2.BORDER_REPLICATE)
        self.assertVerdict(image, rotated, VERDICT_SAME, levels=("normal",))

    def test_single_added_snare_is_different(self):
        changed = add_note(self.page, 2, 1, 5, 1.5)
        self.assertVerdict(render(self.page), render(changed), VERDICT_DIFFERENT, levels=("sensitive", "normal"))
        verdict = compare_frames(_video(render(self.page)), _video(render(changed)))
        self.assertEqual((verdict.frame_width, verdict.frame_height), (self.page.width, self.page.height))
        self.assertEqual(len(verdict.change_boxes), 1)
        x, y, w, h = verdict.change_boxes[0]
        self.assertTrue(0 <= x < verdict.frame_width and 0 <= y < verdict.frame_height and w > 0 and h > 0)
        # Aggressive dedupe may downgrade one small head to "ambiguous" but must never say "same".
        self.assertVerdict(render(self.page), render(changed), {VERDICT_DIFFERENT, VERDICT_AMBIGUOUS}, levels=("aggressive",))

    def test_single_added_hihat_x_head_is_different(self):
        slot = _empty_hihat_slot(self.page, 1)
        self.assertVerdict(render(self.page), render(add_note(self.page, *slot, -0.5)), VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_single_removed_note_is_different(self):
        self.assertVerdict(render(self.page), render(remove_slot(self.page, 0, 0, 0)), VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_note_moved_to_another_drum_is_different(self):
        moved = move_note(self.page, 3, 2, 2, 1.5, 2.5)
        self.assertNotEqual(self.page.notes[(3, 2, 2)], moved.notes[(3, 2, 2)])
        self.assertVerdict(render(self.page), render(moved), VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_page_with_repeated_bars_still_detects_one_note(self):
        repeated = groove_notes(PageSpec(), seed=3, repeat_bar=True)
        self.assertVerdict(render(repeated), render(add_note(repeated, 2, 2, 3, 2.5)), VERDICT_DIFFERENT, levels=("normal",))

    def test_bar_numbers_only_change_is_not_same(self):
        next_page = self.page.copy()
        next_page.first_bar_number = 17
        self.assertVerdict(render(self.page), render(next_page), {VERDICT_DIFFERENT, VERDICT_AMBIGUOUS})

    def test_completely_different_page_is_different(self):
        self.assertVerdict(render(self.page), render(groove_notes(PageSpec(), seed=4)), VERDICT_DIFFERENT)

    def test_dense_six_system_page_detects_one_note(self):
        dense = groove_notes(PageSpec(width=1600, height=900, systems=6, gap=9), seed=11)
        self.assertVerdict(render(dense), render(dense), VERDICT_SAME)
        self.assertVerdict(render(dense), render(add_note(dense, 4, 2, 5, 1.5)), VERDICT_DIFFERENT, levels=("normal",))

    # --- playback overlays -------------------------------------------------

    def test_moving_colored_playhead_line_is_same(self):
        a = render(self.page, [Overlay("line", 0.2, system=1)])
        b = render(self.page, [Overlay("line", 0.55, system=1)])
        self.assertVerdict(a, b, VERDICT_SAME)
        verdict = compare_frames(_video(a), _video(b))
        self.assertIsNotNone(verdict.playhead_prev_x)
        self.assertIsNotNone(verdict.playhead_cur_x)
        self.assertLess(verdict.playhead_prev_x, verdict.playhead_cur_x)

    def test_moving_gray_playhead_line_is_same(self):
        a = render(self.page, [Overlay("line", 0.2, system=1, color=(90, 90, 90), thickness=4)])
        b = render(self.page, [Overlay("line", 0.5, system=1, color=(90, 90, 90), thickness=4)])
        self.assertVerdict(a, b, VERDICT_SAME, levels=("sensitive", "normal"))

    def test_moving_highlight_box_is_same(self):
        box = dict(color=(120, 220, 255))
        a = render(self.page, [Overlay("box", 0.1, system=1, **box)])
        b = render(self.page, [Overlay("box", 0.6, system=1, **box)])
        self.assertVerdict(a, b, VERDICT_SAME)

    def test_playhead_moved_and_one_note_changed_is_different(self):
        a = render(self.page, [Overlay("line", 0.2, system=1)])
        b = render(add_note(self.page, 2, 1, 5, 1.5), [Overlay("line", 0.55, system=1)])
        self.assertVerdict(a, b, VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_highlight_box_moved_and_one_note_changed_is_different(self):
        box = dict(color=(120, 220, 255))
        a = render(self.page, [Overlay("box", 0.1, system=1, **box)])
        b = render(add_note(self.page, 3, 1, 5, 1.5), [Overlay("box", 0.6, system=1, **box)])
        self.assertVerdict(a, b, VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_moving_pale_beat_highlight_with_recolored_notes_is_same(self):
        # Score-follow players tint the current beat with a pale translucent box
        # (saturation ~40, below the solid-overlay cut) and recolor the note
        # just played, which often sits beside the box rather than inside it.
        beat = dict(color=(150, 85, 40))
        a = render(self.page, [Overlay("beat", 0.3, system=1, **beat)])
        b = render(self.page, [Overlay("beat", 0.5, system=1, **beat)])
        self.assertVerdict(a, b, VERDICT_SAME)
        verdict = compare_frames(_video(a), _video(b))
        self.assertIsNotNone(verdict.playhead_prev_x)
        self.assertIsNotNone(verdict.playhead_cur_x)
        self.assertLess(verdict.playhead_prev_x, verdict.playhead_cur_x)

    def test_pale_beat_highlight_moved_and_one_note_changed_is_different(self):
        beat = dict(color=(150, 85, 40))
        a = render(self.page, [Overlay("beat", 0.3, system=1, **beat)])
        b = render(add_note(self.page, 3, 1, 5, 1.5), [Overlay("beat", 0.5, system=1, **beat)])
        self.assertVerdict(a, b, VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_cream_tinted_page_is_not_taken_for_a_highlight(self):
        def cream(image):
            tint = np.full_like(image, (200, 235, 250))
            return cv2.addWeighted(image, 0.75, tint, 0.25, 0)

        a = cream(render(self.page))
        b = cream(render(add_note(self.page, 2, 1, 5, 1.5)))
        self.assertVerdict(a, b, VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_identical_page_with_playhead_reset_is_ambiguous(self):
        a = render(self.page, [Overlay("line", 0.95, system=3)])
        b = render(self.page, [Overlay("line", 0.02, system=0)])
        for level in LEVELS:
            verdict = compare_frames(_video(a), _video(b), dedupe_level=level)
            self.assertEqual(verdict.verdict, VERDICT_AMBIGUOUS, level)
            self.assertEqual(verdict.reason, "playhead_reset")

    def test_playhead_jumped_back_helper(self):
        self.assertTrue(playhead_jumped_back(0.9, 0.05))
        self.assertFalse(playhead_jumped_back(0.2, 0.5))
        self.assertFalse(playhead_jumped_back(0.3, 0.2))
        self.assertFalse(playhead_jumped_back(None, 0.1))

    # --- strips (bottom-bar layout) ----------------------------------------

    def test_strip_single_note_is_different_and_progress_bar_is_same(self):
        self.assertVerdict(render(self.strip), render(self.strip), VERDICT_SAME)
        self.assertVerdict(render(self.strip), render(add_note(self.strip, 0, 1, 3, 1.5)), VERDICT_DIFFERENT, levels=("sensitive", "normal"))
        a = render(self.strip, [Overlay("progress", 0.2)])
        b = render(self.strip, [Overlay("progress", 0.5)])
        self.assertVerdict(a, b, VERDICT_SAME)

    def test_strip_playhead_moved_is_same_but_with_note_is_different(self):
        a = render(self.strip, [Overlay("line", 0.15)])
        self.assertVerdict(a, render(self.strip, [Overlay("line", 0.7)]), VERDICT_SAME)
        b = render(add_note(self.strip, 0, 1, 3, 1.5), [Overlay("line", 0.7)])
        self.assertVerdict(a, b, VERDICT_DIFFERENT, levels=("sensitive", "normal"))

    def test_blank_frames_are_same(self):
        a = np.full((300, 900, 3), 255, np.uint8)
        b = np.full((300, 900, 3), 250, np.uint8)
        self.assertEqual(compare_frames(a, b).verdict, VERDICT_SAME)

    def test_scrolled_copy_reports_shift_and_same_content(self):
        image = render(self.page)
        scrolled = _video(image, jitter=(0, 40))
        verdict = compare_frames(_video(image), scrolled)
        self.assertEqual(verdict.verdict, VERDICT_SAME)
        self.assertAlmostEqual(verdict.shift_y, 40.0, delta=1.5)


def _write_frames(directory: Path, frames, *, seed_offset: int = 0):
    paths = []
    for index, frame in enumerate(frames):
        path = directory / f"frame_{index:04d}.png"
        cv2.imwrite(str(path), degrade(frame, Degrade(scale=0.75, blur=0.8, jpeg_quality=70, noise=2.0, seed=seed_offset + index)))
        paths.append(path)
    return paths


def _select(paths, layout, level="normal"):
    report = {}
    logs = []
    kept = select_review_candidates(
        frame_paths=paths,
        options=StitchOptions(enable=True, layout_hint=layout, dedupe_level=level),
        source_type="file",
        logger=logs.append,
        report=report,
    )
    return [path.name for path in kept], report.get("similar_pairs", []), logs


class TestTemporalDedupeFlow(unittest.TestCase):
    def test_page_turn_keeps_note_change_and_flags_playhead_reset(self):
        page = groove_notes(PageSpec(), seed=3)
        page_b = add_note(page, 2, 1, 5, 1.5)
        page_c = groove_notes(PageSpec(), seed=4)
        frames = (
            [render(page, [Overlay("line", x, system=0)]) for x in (0.05, 0.3, 0.6, 0.9)]
            + [render(page_b, [Overlay("line", x, system=0)]) for x in (0.05, 0.5, 0.95)]
            + [render(page_c, [Overlay("line", x, system=2)]) for x in (0.1, 0.7)]
            # Identical next page: playhead restarts on the left.
            + [render(page_c, [Overlay("line", x, system=0)]) for x in (0.05, 0.7)]
        )
        with tempfile.TemporaryDirectory() as td:
            paths = _write_frames(Path(td), frames)
            kept, pairs, _logs = _select(paths, "page_turn")
            self.assertEqual(kept, ["frame_0000.png", "frame_0004.png", "frame_0007.png", "frame_0009.png"])
            self.assertEqual([(Path(p["candidate"]).name, p["reason"]) for p in pairs], [("frame_0009.png", "playhead_reset")])
            self.assertEqual(Path(pairs[0]["kept"]).name, "frame_0007.png")
            self.assertIn("verdict", pairs[0]["metrics"])
            self.assertEqual(len(pairs[0]["metrics"]["frame_size"]), 2)

            # Prepared (already reviewed) pages are not merged again.
            pages = stitch_pages(
                frame_paths=paths,
                options=StitchOptions(enable=True, layout_hint="page_turn"),
                workspace=Path(td) / "stitched",
                source_type="file",
                prepared_frames=[Path(td) / name for name in kept],
                logger=lambda *_: None,
            )
            self.assertEqual(len(pages), 4)

    def test_page_turn_compression_without_prepared_frames_keeps_note_change(self):
        page = groove_notes(PageSpec(), seed=3)
        page_b = add_note(page, 2, 1, 5, 1.5)
        frames = [render(page, [Overlay("line", x, system=0)]) for x in (0.1, 0.6)] + [
            render(page_b, [Overlay("line", x, system=0)]) for x in (0.1, 0.6)
        ]
        with tempfile.TemporaryDirectory() as td:
            paths = _write_frames(Path(td), frames)
            pages = stitch_pages(
                frame_paths=paths,
                options=StitchOptions(enable=True, layout_hint="page_turn"),
                workspace=Path(td) / "stitched",
                source_type="file",
                logger=lambda *_: None,
            )
            self.assertEqual(len(pages), 2)

    def test_bottom_bar_strip_sequence(self):
        strip = groove_notes(strip_spec(), seed=5)
        strip_b = add_note(strip, 0, 1, 3, 1.5)
        strip_c = groove_notes(strip_spec(), seed=6)
        frames = (
            [render(strip, [Overlay("line", x)]) for x in (0.05, 0.3, 0.6, 0.9)]
            + [render(strip_b, [Overlay("line", x)]) for x in (0.05, 0.5, 0.95)]
            + [render(strip_c, [Overlay("line", x)]) for x in (0.1, 0.7)]
            # Flicker back to an earlier strip: a real repeat of a kept page.
            + [render(strip_b, [Overlay("line", 0.5)])]
        )
        with tempfile.TemporaryDirectory() as td:
            paths = _write_frames(Path(td), frames)
            kept, pairs, _logs = _select(paths, "bottom_bar")
            self.assertEqual(kept, ["frame_0000.png", "frame_0004.png", "frame_0007.png"])
            self.assertEqual(pairs, [])

    def test_full_scroll_keeps_scrolled_frames_and_drops_static_repeats(self):
        tall = groove_notes(PageSpec(width=1200, height=1800, systems=8, gap=12), seed=8)
        image = render(tall)
        frames = [image[y : y + 700] for y in (0, 0, 0, 60, 120, 180, 180, 240)]
        with tempfile.TemporaryDirectory() as td:
            paths = _write_frames(Path(td), frames)
            kept, _pairs, _logs = _select(paths, "full_scroll")
            self.assertEqual(kept, ["frame_0000.png", "frame_0003.png", "frame_0004.png", "frame_0005.png", "frame_0007.png"])

    def test_fade_in_frame_is_replaced_by_clear_duplicate(self):
        faded = _make_plain_score_frame(ink=176, blur=True)
        clear = _make_plain_score_frame(ink=0, blur=False)
        with tempfile.TemporaryDirectory() as td:
            faded_path = Path(td) / "frame_000001.png"
            clear_path = Path(td) / "frame_000002.png"
            cv2.imwrite(str(faded_path), faded)
            cv2.imwrite(str(clear_path), clear)
            kept = select_review_candidates(
                frame_paths=[faded_path, clear_path],
                options=StitchOptions(enable=True, layout_hint="full_scroll", dedupe_level="normal"),
                source_type="file",
                logger=lambda *_: None,
            )
            self.assertEqual(kept, [clear_path])


def _make_plain_score_frame(*, ink: int, blur: bool) -> np.ndarray:
    image = np.full((240, 420, 3), 255, dtype=np.uint8)
    color = (ink, ink, ink)
    for system_top in (42, 122):
        for offset in (0, 9, 18, 27, 36):
            cv2.line(image, (34, system_top + offset), (386, system_top + offset), color, 2)
        cv2.circle(image, (104, system_top + 12), 8, color, -1)
        cv2.circle(image, (188, system_top + 25), 7, color, -1)
        cv2.circle(image, (280, system_top + 18), 7, color, -1)
        cv2.line(image, (112, system_top + 12), (112, system_top - 20), color, 2)
        cv2.line(image, (196, system_top + 25), (196, system_top - 8), color, 2)
        cv2.line(image, (288, system_top + 18), (288, system_top - 16), color, 2)

    if blur:
        image = cv2.GaussianBlur(image, (5, 5), 0)
    return image


if __name__ == "__main__":
    unittest.main()
