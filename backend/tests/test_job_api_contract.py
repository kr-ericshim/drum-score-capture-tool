import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException
from pydantic import ValidationError

from app import main
from app.job_store import Job, JobStatus, JobStore
from app.main import _run_job, crop_capture, review_export
from app.schemas import CaptureCropRequest, JobCreate, JobReviewExportRequest


def fake_reflow_job(*, job_id, job, payload, result, video_path, export_opts):
    """Stand-in for the reflow capture: finish the job with a one-page PDF."""
    export_dir = Path(job.artifact_dir) / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = export_dir / "sheet_export.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% reflow stand-in\n")
    main.job_store.set_state(job_id, JobStatus.DONE, 1.0, "done", "export finished",
                             result={**result, "images": [], "pdf": str(pdf_path)}, error_code=None)


class TestJobApiContract(unittest.TestCase):
    def test_direct_youtube_job_persists_source_identity_and_hydrates_libraries(self):
        class RecordingExecutor:
            def __init__(self):
                self.submitted = []

            def submit(self, fn, *args):
                self.submitted.append((fn, args))

        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)
            executor = RecordingExecutor()
            prepared_video = jobs_root / "_preview_source" / "yt-v3" / "abc123" / "downloads" / "lesson.mp4"
            prepared_video.parent.mkdir(parents=True, exist_ok=True)
            prepared_video.write_bytes(b"video")
            (prepared_video.parent / "source.json").write_text(
                '{"source_key":"https://www.youtube.com/watch?v=abc12345678","video_title":"URL Flow Lesson"}',
                encoding="utf-8",
            )

            payload = JobCreate(
                source_type="youtube",
                youtube_url="https://youtu.be/abc12345678",
                source_identity={
                    "kind": "youtube",
                    "key": "https://www.youtube.com/watch?v=abc12345678",
                    "display_name": "URL Flow Lesson",
                },
                options={
                    "detect": {
                        "roi": [[0, 0], [48, 0], [48, 24], [0, 24]],
                    },
                    "export": {
                        "formats": ["pdf"],
                    },
                },
            )

            with (
                patch.object(main, "jobs_root", jobs_root),
                patch.object(main, "job_store", store),
                patch.object(main, "executor", executor),
                patch.object(main, "_get_or_prepare_cached_youtube_video", return_value={
                    "video_path": prepared_video,
                    "from_cache": True,
                    "video_title": "URL Flow Lesson",
                    "source_key": "https://www.youtube.com/watch?v=abc12345678",
                }),
                patch.object(main, "_analyze_roi_health", return_value={"risk_level": "info", "diagnostics": []}),
                patch.object(main, "_execute_reflow_job", side_effect=fake_reflow_job),
                patch.object(main, "_probe_video_metadata", return_value=(1920, 1080, 252.0)),
                patch.object(main, "_probe_video_resolution", return_value=(1920, 1080)),
            ):
                response = main.create_job(payload)
                self.assertEqual(len(executor.submitted), 1)
                main._run_job(response.job_id, payload)

                job = store.get(response.job_id)
                self.assertIsNotNone(job)
                self.assertEqual(job.status, JobStatus.DONE)
                self.assertEqual(job.source_type, "youtube")
                self.assertEqual(job.youtube_url, "https://www.youtube.com/watch?v=abc12345678")
                self.assertEqual(job.result.get("source_video_path"), str(prepared_video))
                self.assertTrue(Path(job.result.get("pdf", "")).exists())

                job_json = jobs_root / response.job_id / "job.json"
                self.assertTrue(job_json.exists())
                self.assertIn("URL Flow Lesson", job_json.read_text(encoding="utf-8"))

                local = main.local_media_registry()
                archive = main.archive_library()

            local_match = next(
                item
                for item in local.items
                if item.youtube_url == "https://www.youtube.com/watch?v=abc12345678"
            )
            self.assertEqual(local_match.display_name, "URL Flow Lesson")
            self.assertTrue(local_match.has_score)
            self.assertEqual(local_match.youtube_url, "https://www.youtube.com/watch?v=abc12345678")
            archive_match = next(
                item
                for item in archive.items
                if item.source_key == "https://www.youtube.com/watch?v=abc12345678"
            )
            self.assertEqual(archive_match.source_kind, "youtube")
            self.assertEqual(archive_match.source_key, "https://www.youtube.com/watch?v=abc12345678")

    def test_run_job_keeps_roi_health_diagnostics_without_aborting_export(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-1"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            source_path = jobs_root / "source.mp4"
            source_path.write_bytes(b"video")

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(source_path),
                    youtube_url=None,
                    options={"export": {"formats": ["png"]}},
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
                    },
                },
            )

            roi_health = {
                "risk_level": "critical",
                "summary": "샘플 프레임 3개 기준으로 ROI를 점검했습니다.",
                "diagnostics": [
                    {
                        "level": "critical",
                        "code": "top_edge_busy",
                        "title": "상단 잘림 위험",
                        "detail": "샘플 프레임 3개에서 상단 경계가 악보 내용과 가깝습니다.",
                    },
                ],
                "sampled_frames": 3,
                "checked_seconds": [0.0, 0.8, 1.6],
                "metrics": {},
            }

            with (
                patch("app.main.job_store", store),
                patch("app.main.jobs_root", jobs_root),
                patch("app.main._analyze_roi_health", return_value=roi_health),
                patch("app.main._execute_reflow_job", side_effect=fake_reflow_job),
            ):
                _run_job("job-1", payload)

            job = store.get("job-1")
            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.DONE)
            self.assertEqual(job.result.get("roi_health"), roi_health)

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

    def test_review_export_request_accepts_document_header_with_capture_validation(self):
        for output in ({"keep_captures": ["/tmp/capture_0001.png"]}, {"output_model": "original_screens_v1"}):
            with self.subTest(output=output):
                request = JobReviewExportRequest.model_validate({**output, "document_header": {"title": " Override "}})
                self.assertEqual(request.document_header.title, "Override")
                for header in ({"title": " "}, {"title": "T", "bpm": True}, {"title": "T", "unknown": "x"}):
                    with self.subTest(header=header), self.assertRaises(ValidationError):
                        JobReviewExportRequest.model_validate({**output, "document_header": header})

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
