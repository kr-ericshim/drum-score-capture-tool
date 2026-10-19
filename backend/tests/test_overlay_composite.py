import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2

from app.pipeline.stitch import select_review_candidates
from app.schemas import StitchOptions
from drum_score_fixture import Degrade, Overlay, degrade, groove_notes, render, strip_spec


def _write_frames(root, images):
    paths = []
    for index, image in enumerate(images):
        path = root / f"sheet_{index:04d}.png"
        assert cv2.imwrite(str(path), image)
        paths.append(path)
    return paths


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
