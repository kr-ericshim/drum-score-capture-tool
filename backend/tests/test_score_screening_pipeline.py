import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.pipeline.export import export_selected_pages
from app.schemas import JobCreate


class TestScoreScreeningPipeline(unittest.TestCase):
    def run_screening(self, root, *, all_blank=False):
        artifact = root / "job"
        artifact.mkdir()
        source = root / "source.mp4"
        source.write_bytes(b"mock source")
        blank = np.full((240, 640, 3), 255, np.uint8)
        score = blank.copy()
        for y in range(80, 129, 12):
            cv2.line(score, (30, y), (610, y), (0, 0, 0), 1)
        for x in (140, 270, 390):
            cv2.circle(score, (x, 104), 5, (0, 0, 0), -1)
        paths = [artifact / "blank.png", artifact / "score.png"]
        for path, image in zip(paths, (blank, blank if all_blank else score)):
            cv2.imwrite(str(path), image)
        store = JobStore(root)
        store.create(Job(id="job", source_type="file", file_path=str(source), youtube_url=None,
                         options={}, artifact_dir=str(artifact), status=JobStatus.QUEUED))
        payload = JobCreate(source_type="file", file_path=str(source), options={
            "detect": {"roi": [[0, 0], [640, 0], [640, 240], [0, 240]]},
            "stitch": {"enable": False, "layout_hint": "bottom_bar"},
            "export": {"formats": ["png", "pdf"], "include_raw_frames": True},
        })
        with (
            patch.object(main, "job_store", store),
            patch.object(main, "_analyze_roi_health", return_value={}),
            patch.object(main, "get_runtime_acceleration", return_value={}),
            patch.object(main, "resolve_ffmpeg_bin", return_value="ffmpeg"),
            patch.object(main, "runtime_public_info", return_value={}),
            patch.object(main, "extract_frames", return_value=paths),
            patch.object(main, "detect_sheet_regions", return_value=[]),
            patch.object(main, "rectify_frames", return_value=paths),
            patch.object(main, "select_review_candidates", return_value=paths),
            patch.object(main, "stitch_pages", wraps=main.stitch_pages) as stitch,
        ):
            main._run_job("job", payload)
        job = store.get("job")
        self.assertEqual(job.status, JobStatus.DONE, job.message)
        return job.result, paths, stitch.call_args.kwargs["prepared_frames"]

    def test_initial_pdf_filters_non_score_and_preserves_review_originals(self):
        with tempfile.TemporaryDirectory() as td:
            result, paths, stitch_inputs = self.run_screening(Path(td))
            self.assertEqual(stitch_inputs, [paths[1]])
            self.assertEqual(result["review_candidates"], list(map(str, paths)))
            self.assertEqual(result["auto_excluded_captures"], [str(paths[0])])
            self.assertEqual(result["capture_classification_summary"], {"score": 1, "non_score": 1, "uncertain": 0})
            self.assertEqual(len(result["images"]), 1)
            self.assertTrue(Path(result["pdf"]).exists())
            self.assertTrue(all(path.exists() for path in paths))

    def test_all_excluded_finishes_with_recoverable_originals_and_no_misleading_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            result, paths, stitch_inputs = self.run_screening(Path(td), all_blank=True)
            self.assertEqual(stitch_inputs, [])
            self.assertEqual(result["images"], [])
            self.assertIsNone(result["pdf"])
            self.assertEqual(result["review_candidates"], list(map(str, paths)))
            self.assertEqual(result["auto_excluded_captures"], list(map(str, paths)))
            self.assertTrue(Path(result["output_dir"]).is_dir())
            self.assertEqual(len(result["raw_frames"]), 2)
            self.assertTrue(all(Path(path).exists() for path in result["raw_frames"]))
            # Explicit manual restoration still exports a rejected capture.
            restored = export_selected_pages(page_paths=[paths[0]], formats=["png"],
                                             workspace=Path(td) / "restored", logger=lambda _: None)
            self.assertEqual(len(restored["images"]), 1)


if __name__ == "__main__":
    unittest.main()
