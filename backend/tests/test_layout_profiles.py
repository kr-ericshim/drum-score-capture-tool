import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.job_store import JobStore
from app.pipeline.layout_profiles import (
    LAYOUT_BOTTOM_BAR,
    LAYOUT_FULL_SCROLL,
    LAYOUT_PAGE_TURN,
    infer_layout_hint_from_roi,
    resolve_layout_hint,
)
from app.schemas import JobCreate


class TestLayoutProfiles(unittest.TestCase):
    def test_infer_layout_hint_from_roi_detects_bottom_bar(self):
        hint = infer_layout_hint_from_roi([[0, 0], [300, 0], [300, 60], [0, 60]], source_type="file")
        self.assertEqual(hint, LAYOUT_BOTTOM_BAR)

    def test_infer_layout_hint_from_roi_detects_page_turn(self):
        hint = infer_layout_hint_from_roi([[0, 0], [160, 0], [160, 200], [0, 200]], source_type="file")
        self.assertEqual(hint, LAYOUT_PAGE_TURN)

    def test_resolve_layout_hint_prefers_explicit_value(self):
        hint = resolve_layout_hint(
            "full_scroll",
            source_type="youtube",
            roi=[[0, 0], [300, 0], [300, 60], [0, 60]],
        )
        self.assertEqual(hint, LAYOUT_FULL_SCROLL)

    def test_create_job_persists_inferred_auto_layout_hints(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            source_path = Path(td) / "source.mp4"
            source_path.write_bytes(b"video")

            payload = JobCreate(
                source_type="file",
                file_path=str(source_path),
                options={
                    "detect": {
                        "roi": [[0, 0], [160, 0], [160, 200], [0, 200]],
                        "layout_hint": "auto",
                    },
                    "stitch": {
                        "enable": True,
                        "layout_hint": "auto",
                    },
                },
            )

            submitted = []

            class _Executor:
                def submit(self, fn, *args):
                    submitted.append((fn, args))

            with (
                patch.object(main, "jobs_root", jobs_root),
                patch.object(main, "job_store", JobStore(jobs_root)),
                patch.object(main, "executor", _Executor()),
                patch.object(main, "_enforce_roi_capture_gate", return_value={"summary": "ok"}),
            ):
                response = main.create_job(payload)
                job = main.job_store.get(response.job_id)

            self.assertIsNotNone(job)
            self.assertEqual(job.options["detect"]["layout_hint"], LAYOUT_PAGE_TURN)
            self.assertEqual(job.options["stitch"]["layout_hint"], LAYOUT_PAGE_TURN)
            self.assertEqual(len(submitted), 1)


if __name__ == "__main__":
    unittest.main()
