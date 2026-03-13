import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.job_store import Job, JobStatus, JobStore
from app.main import review_export
from app.schemas import JobReviewExportRequest


class TestReviewExport(unittest.TestCase):
    def test_review_export_passes_selected_captures_and_export_mode(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            export_dir = artifact_dir / "export" / "images"
            export_dir.mkdir(parents=True, exist_ok=True)

            page_one = export_dir / "page_0001.png"
            page_two = export_dir / "page_0002.png"
            page_one.write_bytes(b"page-1")
            page_two.write_bytes(b"page-2")

            store = JobStore(jobs_root)
            job = Job(
                id="job-1",
                source_type="file",
                file_path=str(jobs_root / "source.mp4"),
                youtube_url=None,
                options={"export": {"formats": ["png", "pdf"], "page_fill_mode": "balanced"}},
                artifact_dir=str(artifact_dir),
                status=JobStatus.DONE,
                result={
                    "images": [str(page_one), str(page_two)],
                    "review_candidates": [str(page_one), str(page_two)],
                    "page_diagnostics": [
                        {"page_index": 1, "suspicious": False},
                        {"page_index": 2, "suspicious": True},
                    ],
                },
            )
            store.create(job)

            with (
                patch("app.main.job_store", store),
                patch("app.main.export_selected_pages") as export_selected_pages,
                patch("app.main.export_frames") as export_frames,
            ):
                export_selected_pages.return_value = {
                    "images": [str(page_two)],
                    "pdf": str(artifact_dir / "export" / "sheet_export.pdf"),
                    "page_diagnostics": [{"page_index": 1, "suspicious": False}],
                }

                response = review_export(
                    "job-1",
                    JobReviewExportRequest(keep_captures=[str(page_two)], formats=["png"]),
                )

            export_frames.assert_not_called()
            export_selected_pages.assert_called_once()
            self.assertEqual(
                export_selected_pages.call_args.kwargs["page_paths"],
                [page_two.resolve()],
            )
            self.assertEqual(export_selected_pages.call_args.kwargs["page_fill_mode"], "balanced")
            self.assertEqual(response.images, [str(page_two)])
            self.assertEqual(response.kept_count, 1)
            refreshed = store.get("job-1")
            self.assertEqual(refreshed.result["review_candidates"], [str(page_two)])
            self.assertEqual(refreshed.result["images"], [str(page_two)])
            self.assertEqual(
                refreshed.result["page_diagnostics"],
                [{"page_index": 1, "suspicious": False}],
            )

    def test_review_export_uses_preview_images_for_review_candidates_when_pdf_only(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            export_dir = artifact_dir / "export" / "images"
            export_dir.mkdir(parents=True, exist_ok=True)

            page_one = export_dir / "page_0001.png"
            page_one.write_bytes(b"page-1")
            preview_one = artifact_dir / "export" / "preview" / "preview_0001.png"
            preview_one.parent.mkdir(parents=True, exist_ok=True)
            preview_one.write_bytes(b"preview-1")

            store = JobStore(jobs_root)
            job = Job(
                id="job-1",
                source_type="file",
                file_path=str(jobs_root / "source.mp4"),
                youtube_url=None,
                options={"export": {"formats": ["pdf"], "page_fill_mode": "performance"}},
                artifact_dir=str(artifact_dir),
                status=JobStatus.DONE,
                result={
                    "images": [str(page_one)],
                    "review_candidates": [str(page_one)],
                },
            )
            store.create(job)

            with (
                patch("app.main.job_store", store),
                patch("app.main.export_selected_pages") as export_selected_pages,
            ):
                export_selected_pages.return_value = {
                    "images": [],
                    "preview_images": [str(preview_one)],
                    "pdf": str(artifact_dir / "export" / "sheet_export.pdf"),
                    "page_diagnostics": [{"page_index": 1, "suspicious": False}],
                }

                response = review_export(
                    "job-1",
                    JobReviewExportRequest(keep_captures=[str(page_one)], formats=["pdf"]),
                )

            self.assertEqual(response.images, [])
            refreshed = store.get("job-1")
            self.assertEqual(refreshed.result["review_candidates"], [str(preview_one)])
            self.assertEqual(refreshed.result["images"], [])

    def test_review_export_rejects_reapplying_after_review_export(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            export_dir = artifact_dir / "export" / "preview"
            export_dir.mkdir(parents=True, exist_ok=True)

            preview_one = export_dir / "preview_0001.png"
            preview_one.write_bytes(b"preview-1")

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["pdf"], "page_fill_mode": "performance"}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "preview_images": [str(preview_one)],
                        "review_candidates": [str(preview_one)],
                        "review_export": {"kept_count": 1, "requested_count": 1},
                    },
                )
            )

            with patch("app.main.job_store", store):
                with self.assertRaises(HTTPException) as error:
                    review_export(
                        "job-1",
                        JobReviewExportRequest(keep_captures=[str(preview_one)], formats=["pdf"]),
                    )

            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(error.exception.detail, "review export is already applied")


if __name__ == "__main__":
    unittest.main()
