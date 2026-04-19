import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.job_store import Job, JobStatus, JobStore
from app.main import review_export
from app.schemas import JobReviewExportRequest


class TestReviewExport(unittest.TestCase):
    def test_review_export_reuses_stored_document_header(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            export_dir = artifact_dir / "export" / "images"
            export_dir.mkdir(parents=True, exist_ok=True)

            page_one = export_dir / "page_0001.png"
            page_one.write_bytes(b"page-1")
            stored_document_header = {
                "title": "Stored Title",
                "performer": "Stored Performer",
                "bpm": 92,
                "date": "2026-04-19",
                "memo": "stored memo",
            }

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={
                        "export": {
                            "formats": ["png", "pdf"],
                            "page_fill_mode": "performance",
                            "document_header": stored_document_header,
                        },
                    },
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={"images": [str(page_one)]},
                )
            )

            with (
                patch("app.main.job_store", store),
                patch("app.main.stitch_pages") as stitch_pages,
                patch("app.main.export_selected_pages") as export_selected_pages,
            ):
                export_selected_pages.return_value = {
                    "images": [str(page_one)],
                    "pdf": str(artifact_dir / "export" / "sheet_export.pdf"),
                    "page_diagnostics": [{"page_index": 1, "suspicious": False}],
                }

                review_export(
                    "job-1",
                    JobReviewExportRequest(keep_images=[str(page_one)], formats=["png", "pdf"]),
                )

            stitch_pages.assert_not_called()
            self.assertEqual(export_selected_pages.call_args.kwargs["document_header"], stored_document_header)

    def test_review_export_capture_mode_restitches_selected_captures_in_canonical_order(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            capture_dir = artifact_dir / "review"
            capture_dir.mkdir(parents=True, exist_ok=True)

            capture_one = capture_dir / "capture_0001.png"
            capture_two = capture_dir / "capture_0002.png"
            capture_one.write_bytes(b"capture-1")
            capture_two.write_bytes(b"capture-2")
            stitched_page = artifact_dir / "stitched" / "page_0000.png"

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
                    "review_candidates": [str(capture_two), str(capture_one)],
                    "page_diagnostics": [
                        {"page_index": 1, "suspicious": False},
                        {"page_index": 2, "suspicious": True},
                    ],
                },
            )
            store.create(job)

            with (
                patch("app.main.job_store", store),
                patch("app.main.stitch_pages", return_value=[stitched_page]) as stitch_pages,
                patch("app.main.export_selected_pages") as export_selected_pages,
            ):
                def _mock_export_selected_pages(**kwargs):
                    workspace = kwargs["workspace"]
                    return {
                        "images": [str(workspace / "images" / "page_0001.png")],
                        "pdf": str(workspace / "sheet_export.pdf"),
                        "page_diagnostics": [{"page_index": 1, "suspicious": False}],
                    }

                export_selected_pages.side_effect = _mock_export_selected_pages

                response = review_export(
                    "job-1",
                    JobReviewExportRequest(keep_captures=[str(capture_one), str(capture_two)], formats=["png"]),
                )

            stitch_pages.assert_called_once()
            export_selected_pages.assert_called_once()
            self.assertEqual(
                stitch_pages.call_args.kwargs["frame_paths"],
                [capture_two.resolve(), capture_one.resolve()],
            )
            self.assertEqual(stitch_pages.call_args.kwargs["prepared_frames"], [capture_two.resolve(), capture_one.resolve()])
            self.assertEqual(export_selected_pages.call_args.kwargs["page_paths"], [stitched_page])
            self.assertEqual(export_selected_pages.call_args.kwargs["page_fill_mode"], "balanced")
            self.assertEqual(response.images, [str(artifact_dir / "export" / "images" / "page_0001.png")])
            self.assertEqual(response.kept_count, 2)
            refreshed = store.get("job-1")
            self.assertEqual(refreshed.result["review_candidates"], [str(capture_two.resolve()), str(capture_one.resolve())])
            self.assertEqual(refreshed.result["images"], [str(artifact_dir / "export" / "images" / "page_0001.png")])
            self.assertEqual(
                refreshed.result["page_diagnostics"],
                [{"page_index": 1, "suspicious": False}],
            )
            self.assertEqual(refreshed.result["review_export"]["selection_mode"], "captures")

    def test_review_export_page_mode_uses_images_without_review_candidates(self):
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
                options={"export": {"formats": ["png", "pdf"], "page_fill_mode": "performance"}},
                artifact_dir=str(artifact_dir),
                status=JobStatus.DONE,
                result={
                    "images": [str(page_one), str(page_two)],
                    "review_candidates": [str(artifact_dir / "review" / "capture_0009.png")],
                },
            )
            store.create(job)

            with (
                patch("app.main.job_store", store),
                patch("app.main.stitch_pages") as stitch_pages,
                patch("app.main.export_selected_pages") as export_selected_pages,
            ):
                export_selected_pages.return_value = {
                    "images": [str(page_two)],
                    "pdf": str(artifact_dir / "export" / "sheet_export.pdf"),
                    "page_diagnostics": [{"page_index": 1, "suspicious": False}],
                }

                response = review_export(
                    "job-1",
                    JobReviewExportRequest(keep_images=[str(page_two)], formats=["png"]),
                )

            stitch_pages.assert_not_called()
            export_selected_pages.assert_called_once()
            self.assertEqual(export_selected_pages.call_args.kwargs["page_paths"], [page_two.resolve()])
            self.assertEqual(response.images, [str(page_two)])
            refreshed = store.get("job-1")
            self.assertEqual(refreshed.result["images"], [str(page_two)])
            self.assertEqual(refreshed.result["review_export"]["selection_mode"], "pages")
            self.assertEqual(refreshed.result["review_export"]["selected_pages"], [str(page_two.resolve())])

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

    def test_review_export_failure_preserves_existing_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            export_dir = artifact_dir / "export" / "images"
            review_dir = artifact_dir / "review"
            export_dir.mkdir(parents=True, exist_ok=True)
            review_dir.mkdir(parents=True, exist_ok=True)

            existing_page = export_dir / "page_0001.png"
            existing_pdf = artifact_dir / "export" / "sheet_export.pdf"
            selected_capture = review_dir / "capture_0001.png"
            existing_page.write_bytes(b"existing-page")
            existing_pdf.write_bytes(b"existing-pdf")
            selected_capture.write_bytes(b"capture")

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["png", "pdf"], "page_fill_mode": "performance"}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "images": [str(existing_page)],
                        "pdf": str(existing_pdf),
                        "review_candidates": [str(selected_capture)],
                    },
                )
            )

            with (
                patch("app.main.job_store", store),
                patch("app.main.stitch_pages", return_value=[selected_capture.resolve()]),
                patch("app.main.export_selected_pages", side_effect=RuntimeError("boom")),
            ):
                with self.assertRaises(HTTPException) as error:
                    review_export(
                        "job-1",
                        JobReviewExportRequest(keep_captures=[str(selected_capture)], formats=["png", "pdf"]),
                    )

            self.assertEqual(error.exception.status_code, 500)
            self.assertTrue(existing_page.exists())
            self.assertTrue(existing_pdf.exists())


if __name__ == "__main__":
    unittest.main()
