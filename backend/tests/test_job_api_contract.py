import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException
from pydantic import ValidationError

from app.job_store import Job, JobStatus, JobStore
from app.main import _run_job, crop_capture, review_export
from app.schemas import CaptureCropRequest, JobCreate, JobReviewExportRequest


class TestJobApiContract(unittest.TestCase):
    def test_run_job_uses_stored_export_options_for_document_header(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            source_path = jobs_root / "source.mp4"
            source_path.write_bytes(b"video")

            rectified = artifact_dir / "rectified" / "capture_0001.png"
            stitched = artifact_dir / "stitched" / "page_0001.png"
            stored_document_header = {
                "title": "Stored Title",
                "performer": "Stored Performer",
                "bpm": 108,
                "date": "2026-04-19",
                "memo": "stored memo",
            }

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(source_path),
                    youtube_url=None,
                    options={
                        "export": {
                            "formats": ["pdf"],
                            "page_fill_mode": "balanced",
                            "document_header": stored_document_header,
                        },
                    },
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.QUEUED,
                )
            )

            payload = JobCreate(
                source_type="file",
                file_path=str(source_path),
                options={
                    "detect": {
                        "roi": [[0, 0], [320, 0], [320, 180], [0, 180]],
                    },
                    "export": {
                        "formats": ["png"],
                        "page_fill_mode": "performance",
                        "document_header": {
                            "title": "Payload Title",
                            "performer": "Payload Performer",
                            "bpm": 72,
                            "date": "2020-01-01",
                            "memo": "payload memo",
                        },
                    },
                },
            )

            with (
                patch("app.main.job_store", store),
                patch("app.main.jobs_root", jobs_root),
                patch("app.main._enforce_roi_capture_gate", return_value={"summary": "ok"}),
                patch("app.main.get_runtime_acceleration", return_value={}),
                patch("app.main.runtime_public_info", return_value={}),
                patch("app.main._detect_source_resolution", return_value=(0, 0)),
                patch("app.main.extract_frames", return_value=[artifact_dir / "frames" / "frame_0001.png"]),
                patch("app.main.detect_sheet_regions", return_value=[{"id": "roi"}]),
                patch("app.main.rectify_frames", return_value=[rectified]),
                patch("app.main.select_review_candidates", return_value=[rectified], create=True),
                patch("app.main.stitch_pages", return_value=[stitched]),
                patch("app.main.upscale_frames", return_value=[stitched]),
                patch(
                    "app.main.export_frames",
                    return_value={
                        "images": [str(artifact_dir / "export" / "images" / "page_0001.png")],
                        "pdf": str(artifact_dir / "export" / "sheet_export.pdf"),
                        "raw_frames": [],
                        "page_diagnostics": [],
                    },
                ) as export_frames,
            ):
                _run_job("job-1", payload)

            export_options = export_frames.call_args.kwargs["options"]
            self.assertEqual(export_options.formats, ["pdf"])
            self.assertEqual(export_options.page_fill_mode, "balanced")
            self.assertEqual(export_options.document_header.model_dump(), stored_document_header)
            self.assertEqual(export_frames.call_args.kwargs["document_header"], stored_document_header)

    def test_review_export_rejects_capture_outside_current_review_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            export_dir = artifact_dir / "export" / "images"
            hidden_dir = artifact_dir / "debug"
            export_dir.mkdir(parents=True, exist_ok=True)
            hidden_dir.mkdir(parents=True, exist_ok=True)

            candidate_path = export_dir / "page_0001.png"
            hidden_path = hidden_dir / "shadow.png"
            candidate_path.write_bytes(b"candidate")
            hidden_path.write_bytes(b"hidden")

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["png", "pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "review_candidates": [str(candidate_path)],
                        "images": [str(candidate_path)],
                    },
                )
            )

            with (
                patch("app.main.job_store", store),
                patch("app.main.export_selected_pages") as export_selected_pages,
            ):
                with self.assertRaises(HTTPException) as error:
                    review_export(
                        "job-1",
                        JobReviewExportRequest(keep_captures=[str(hidden_path)], formats=["png"]),
                    )

            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(error.exception.detail, f"capture is not selectable for this job: {hidden_path}")
            export_selected_pages.assert_not_called()

    def test_review_export_rejects_error_job(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            review_dir = artifact_dir / "review"
            review_dir.mkdir(parents=True, exist_ok=True)
            candidate_path = review_dir / "capture_0001.png"
            candidate_path.write_bytes(b"candidate")

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["png", "pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.ERROR,
                    error_code="PIPELINE_ERROR",
                    result={"review_candidates": [str(candidate_path)]},
                )
            )

            with patch("app.main.job_store", store):
                with self.assertRaises(HTTPException) as error:
                    review_export(
                        "job-1",
                        JobReviewExportRequest(keep_captures=[str(candidate_path)], formats=["png"]),
                    )

            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(error.exception.detail, "job must be completed successfully before review export")

    def test_review_export_request_rejects_document_header_override_payload(self):
        with self.assertRaises(ValidationError):
            JobReviewExportRequest.model_validate(
                {
                    "keep_captures": ["/tmp/capture_0001.png"],
                    "document_header": {"title": "Override"},
                }
            )

    def test_capture_crop_rejects_capture_outside_current_review_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            review_dir = artifact_dir / "review"
            hidden_dir = artifact_dir / "debug"
            review_dir.mkdir(parents=True, exist_ok=True)
            hidden_dir.mkdir(parents=True, exist_ok=True)

            candidate_path = review_dir / "capture_0001.png"
            hidden_path = hidden_dir / "shadow.png"
            image = np.full((200, 300, 3), 255, dtype=np.uint8)
            cv2.imwrite(str(candidate_path), image)
            cv2.imwrite(str(hidden_path), image)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["png", "pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.DONE,
                    result={
                        "review_candidates": [str(candidate_path)],
                        "upscaled_frames": [str(candidate_path)],
                    },
                )
            )

            with patch("app.main.job_store", store):
                with self.assertRaises(HTTPException) as error:
                    crop_capture(
                        "job-1",
                        CaptureCropRequest(
                            capture_path=str(hidden_path),
                            roi=[[10, 10], [120, 10], [120, 120], [10, 120]],
                        ),
                    )

            self.assertEqual(error.exception.status_code, 400)
            self.assertEqual(error.exception.detail, f"capture is not selectable for this job: {hidden_path}")

    def test_capture_crop_rejects_error_job(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            review_dir = artifact_dir / "review"
            review_dir.mkdir(parents=True, exist_ok=True)

            candidate_path = review_dir / "capture_0001.png"
            image = np.full((200, 300, 3), 255, dtype=np.uint8)
            cv2.imwrite(str(candidate_path), image)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(jobs_root / "source.mp4"),
                    youtube_url=None,
                    options={"export": {"formats": ["png", "pdf"]}},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.ERROR,
                    error_code="PIPELINE_ERROR",
                    result={"review_candidates": [str(candidate_path)]},
                )
            )

            with patch("app.main.job_store", store):
                with self.assertRaises(HTTPException) as error:
                    crop_capture(
                        "job-1",
                        CaptureCropRequest(
                            capture_path=str(candidate_path),
                            roi=[[10, 10], [120, 10], [120, 120], [10, 120]],
                        ),
                    )

            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(error.exception.detail, "job must be completed successfully before capture crop")


if __name__ == "__main__":
    unittest.main()
