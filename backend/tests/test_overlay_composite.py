import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

import cv2
import numpy as np

from app.pipeline.overlay_composite import compose_overlay_free_captures
from app.pipeline.process_control import OperationCancelled, operation_scope
from app.pipeline.stitch import select_review_candidates
from app.schemas import StitchOptions
from drum_score_fixture import Degrade, Overlay, PageSpec, degrade, groove_notes, render, strip_spec


def _write_frames(root, images):
    paths = []
    for index, image in enumerate(images):
        path = root / f"sheet_{index:04d}.png"
        assert cv2.imwrite(str(path), image)
        paths.append(path)
    return paths


def _bright_color_count(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return int(((hsv[..., 1] > 30) & (hsv[..., 2] > 150)).sum())


class TestOverlayComposite(unittest.TestCase):
    def compose(self, root, paths, *, layout="bottom_bar", report=None):
        return compose_overlay_free_captures(
            kept_paths=paths[:1],
            groups={str(paths[0]): [str(path) for path in paths]},
            layout_mode=layout,
            workspace=root / "clean",
            logger=lambda _msg: None,
            report=report,
        )

    def test_moving_highlights_preserve_clean_ink_after_video_degradation(self):
        for layout, spec in (("bottom_bar", strip_spec()), ("page_turn", PageSpec())):
            for kind in ("beat", "box"):
                with self.subTest(layout=layout, kind=kind), tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    score = groove_notes(spec, seed=5)
                    damage = Degrade(scale=0.75, blur=0.6, jpeg_quality=75)
                    clean = degrade(render(score), damage)
                    images = [
                        degrade(render(score, [Overlay(kind, x, color=(230, 175, 95))]), damage)
                        for x in (0.06, 0.18, 0.31, 0.43, 0.56, 0.68, 0.81, 0.93)
                    ]
                    paths = _write_frames(root, images)
                    original_bytes = [path.read_bytes() for path in paths]
                    result = self.compose(root, paths, layout=layout)
                    self.assertEqual(result, [root / "clean" / "sheet_0000_clean.png"])
                    composite = cv2.imread(str(result[0]))
                    before = _bright_color_count(images[0])
                    self.assertGreater(before, 1000)
                    self.assertLessEqual(_bright_color_count(composite), max(10, before * 0.005))
                    # Ink F1 against the identically degraded clean render tests
                    # staff and note preservation; color alone could hide erasure.
                    clean_ink = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY) < 160
                    composite_ink = cv2.cvtColor(composite, cv2.COLOR_BGR2GRAY) < 160
                    ink_f1 = 2 * np.count_nonzero(clean_ink & composite_ink) / (
                        np.count_nonzero(clean_ink) + np.count_nonzero(composite_ink)
                    )
                    self.assertGreater(ink_f1, 0.995)
                    error = np.abs(composite.astype(np.float32) - clean.astype(np.float32))
                    self.assertLess(float(error[clean_ink].mean()), 2.0)
                    self.assertEqual([path.read_bytes() for path in paths], original_bytes)

    def test_single_frame_returns_original_without_creating_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = _write_frames(root, [render(groove_notes(strip_spec()), [Overlay("beat", 0.1)])])
            self.assertEqual(self.compose(root, paths), paths)
            self.assertFalse((root / "clean").exists())

    def test_misaligned_wrong_shape_and_unreadable_members_are_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            score = groove_notes(strip_spec())
            images = [render(score, [Overlay("box", x)]) for x in (0.1, 0.4, 0.7)]
            images.extend([
                degrade(render(score), Degrade(jitter=(4, 3))),
                render(score)[:100],
            ])
            paths = _write_frames(root, images)
            paths.append(root / "missing.png")
            report = {}
            result = self.compose(root, paths, report=report)
            self.assertNotEqual(result, paths[:1])
            self.assertEqual(report[str(result[0])], [str(path) for path in paths[:3]])
            self.assertTrue(np.array_equal(cv2.imread(str(result[0])), render(score)))

    def test_only_misaligned_duplicate_returns_original(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            score = groove_notes(strip_spec())
            paths = _write_frames(root, [
                render(score, [Overlay("beat", 0.1)]),
                degrade(render(score, [Overlay("beat", 0.6)]), Degrade(jitter=(0, 3))),
            ])
            self.assertEqual(self.compose(root, paths), paths[:1])

    def test_full_scroll_returns_originals_in_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = _write_frames(root, [render(groove_notes(strip_spec()), [Overlay("box", x)]) for x in (0.1, 0.8)])
            result = compose_overlay_free_captures(
                kept_paths=paths, groups={str(paths[0]): [str(path) for path in paths]},
                layout_mode="full_scroll", workspace=root / "clean", logger=lambda _msg: None,
            )
            self.assertEqual(result, paths)
            self.assertFalse((root / "clean").exists())

    def test_no_overlays_and_dark_chroma_do_not_reencode(self):
        for dark_chroma in (False, True):
            with self.subTest(dark_chroma=dark_chroma), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                image = render(groove_notes(strip_spec()))
                if dark_chroma:
                    image[np.min(image, axis=2) < 100] = (65, 15, 15)
                paths = _write_frames(root, [image, image])
                self.assertEqual(self.compose(root, paths), paths[:1])
                self.assertFalse((root / "clean").exists())

    def test_fully_covered_columns_use_all_member_median_without_warnings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            score = groove_notes(strip_spec())
            images = [render(score, [Overlay("box", 0.1), Overlay("beat", x)]) for x in (0.4, 0.6, 0.8)]
            paths = _write_frames(root, images)
            with np.errstate(all="raise"), patch("warnings.warn", side_effect=AssertionError("unexpected NaN warning")):
                result = self.compose(root, paths)
            composite = cv2.imread(str(result[0]))
            fallback = np.median(np.stack(images), axis=0).astype(np.uint8)
            # This stationary box covers the first bar in every observation.
            self.assertTrue(np.array_equal(composite[:, 100:300], fallback[:, 100:300]))
            self.assertLess(_bright_color_count(composite), _bright_color_count(images[0]))

    def test_member_cap_is_evenly_sampled_and_reference_first(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            score = groove_notes(strip_spec(width=700, height=190))
            paths = _write_frames(root, [render(score, [Overlay("beat", x)]) for x in np.linspace(0.05, 0.95, 20)])
            report = {}
            result = self.compose(root, paths, report=report)
            members = report[str(result[0])]
            self.assertEqual(len(members), 15)
            self.assertEqual(len(set(members)), 15)
            self.assertEqual(members[0], str(paths[0]))
            self.assertIn(str(paths[1]), members)
            self.assertIn(str(paths[-1]), members)

    def test_long_held_page_decodes_at_most_the_member_cap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            score = groove_notes(strip_spec(width=700, height=190))
            paths = _write_frames(root, [render(score, [Overlay("beat", x)]) for x in np.linspace(0.05, 0.95, 60)])
            original_read = cv2.imread
            with patch("app.pipeline.overlay_composite.cv2.imread", side_effect=original_read) as reads:
                self.compose(root, paths)
            self.assertLessEqual(reads.call_count, 16)

    def test_one_pixel_jitter_is_rejected_instead_of_erasing_staff_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            score = groove_notes(strip_spec(), seed=5)
            base = [render(score, [Overlay("beat", x)]) for x in (0.1, 0.4, 0.7)]
            # Frames 1 and 2 are the same page knocked one pixel up and down.
            shifted = [base[0], np.roll(base[1], -1, axis=0), np.roll(base[2], 1, axis=0)]
            paths = _write_frames(root, shifted)
            report = {}
            result = self.compose(root, paths, report=report)
            self.assertEqual(result, paths[:1])
            self.assertEqual(report, {})

    def test_cancellation_is_checked_inside_member_loop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = _write_frames(root, [render(groove_notes(strip_spec()), [Overlay("beat", x)]) for x in (0.1, 0.8)])
            event = Event()
            original_read = cv2.imread

            def cancel_after_reference(*args, **kwargs):
                image = original_read(*args, **kwargs)
                event.set()
                return image

            with operation_scope(event), patch("app.pipeline.overlay_composite.cv2.imread", side_effect=cancel_after_reference):
                with self.assertRaises(OperationCancelled):
                    self.compose(root, paths)
            self.assertFalse((root / "clean").exists())


class TestObservationGroups(unittest.TestCase):
    def select(self, paths, layout="bottom_bar"):
        report = {}
        kept = select_review_candidates(
            frame_paths=paths, options=StitchOptions(layout_hint=layout), source_type="file",
            logger=lambda _msg: None, report=report,
        )
        return kept, report

    def test_clarity_replacement_moves_complete_group_to_new_kept_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            score = render(groove_notes(strip_spec()))
            paths = _write_frames(root, [score, score, score, score])
            # Isolate group bookkeeping from the clarity heuristic's thresholds.
            with patch("app.pipeline.stitch._should_replace_with_clearer_duplicate", side_effect=[False, True, False]):
                kept, report = self.select(paths)
            self.assertEqual(kept, [paths[2]])
            self.assertEqual(report["observation_groups"], {str(paths[2]): [str(paths[i]) for i in (2, 0, 1, 3)]})

    def test_committed_return_has_its_own_group_and_flickers_are_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = groove_notes(strip_spec(), seed=5)
            b = groove_notes(strip_spec(), seed=6)
            c = groove_notes(strip_spec(), seed=9)
            # A, B, one-frame A flicker, B, A persists, C, terminal B flicker.
            frames = [render(score, [Overlay("line", x)]) for score, x in (
                (a, 0.05), (a, 0.5), (b, 0.05), (b, 0.3), (a, 0.9), (b, 0.6),
                (a, 0.05), (a, 0.5), (c, 0.05), (c, 0.5), (b, 0.9),
            )]
            paths = _write_frames(root, [degrade(frame, Degrade(scale=0.75, blur=0.8, jpeg_quality=70)) for frame in frames])
            kept, report = self.select(paths)
            self.assertEqual(kept, [paths[i] for i in (0, 2, 6, 8)])
            self.assertEqual(report["observation_groups"], {
                str(paths[0]): [str(paths[i]) for i in (0, 1)],
                str(paths[2]): [str(paths[i]) for i in (2, 3, 5)],
                str(paths[6]): [str(paths[i]) for i in (6, 7)],
                str(paths[8]): [str(paths[i]) for i in (8, 9)],
            })
            self.assertEqual(report["similar_pairs"][0]["reason"], "recent_return")
            self.assertEqual(report["similar_pairs"][0]["candidate"], str(paths[6]))

    def test_recent_cache_drop_is_not_an_observation(self):
        with tempfile.TemporaryDirectory() as td:
            paths = _write_frames(Path(td), [render(groove_notes(strip_spec(), seed=i)) for i in (5, 6)])
            # Force the recent-cache path (rather than direct prev duplicate).
            with patch("app.pipeline.stitch._match_recent_frame", return_value=(paths[0], None)):
                kept, report = self.select(paths)
            self.assertEqual(kept, paths[:1])
            self.assertEqual(report["observation_groups"], {str(paths[0]): [str(paths[0])]})

    def test_empty_and_single_inputs_report_groups(self):
        kept, report = self.select([])
        self.assertEqual(kept, [])
        self.assertEqual(report, {"similar_pairs": [], "observation_groups": {}})
        with tempfile.TemporaryDirectory() as td:
            paths = _write_frames(Path(td), [render(groove_notes(strip_spec()))])
            kept, report = self.select(paths)
            self.assertEqual(kept, paths)
            self.assertEqual(report["observation_groups"], {str(paths[0]): [str(paths[0])]})


if __name__ == "__main__":
    unittest.main()
