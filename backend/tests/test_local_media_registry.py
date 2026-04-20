import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.job_store import Job, JobStatus, JobStore, SourcePrepareJob, SourcePrepareStore
from app.main import local_media_registry


class TestLocalMediaRegistry(unittest.TestCase):
    def test_local_media_registry_reads_done_jobs_and_prepare_cache(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            source_from_job = jobs_root / "_preview_source" / "yt-v3" / "abc123" / "downloads" / "job-source.mkv"
            source_from_job.parent.mkdir(parents=True, exist_ok=True)
            source_from_job.write_bytes(b"video")

            prepared_only_source = jobs_root / "_preview_source" / "yt-v3" / "def456" / "downloads" / "prepared-only.mkv"
            prepared_only_source.parent.mkdir(parents=True, exist_ok=True)
            prepared_only_source.write_bytes(b"video")

            export_dir = jobs_root / "job-1" / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = export_dir / "sheet_export.pdf"
            pdf_path.write_bytes(b"%PDF")

            job_store = JobStore(jobs_root)
            job_store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(source_from_job),
                    youtube_url=None,
                    options={},
                    artifact_dir=str(jobs_root / "job-1"),
                    source_identity={
                        "kind": "youtube",
                        "key": "https://www.youtube.com/watch?v=job-backed",
                        "display_name": "Blue in Green Drum Cover",
                    },
                    status=JobStatus.DONE,
                    message="export finished",
                    result={
                        "output_dir": str(export_dir),
                        "pdf": str(pdf_path),
                    },
                    created_at=10.0,
                    updated_at=20.0,
                )
            )

            prepare_store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
            prepare_store.create(
                SourcePrepareJob(
                    id="source-job-backed",
                    youtube_url="https://youtu.be/job-backed",
                    artifact_dir=str(prepare_store.root / "source-job-backed"),
                    status=JobStatus.DONE,
                    stage="done",
                    message="youtube source ready",
                    result={
                        "video_path": str(source_from_job),
                        "video_title": "Blue in Green Drum Cover",
                    },
                    created_at=5.0,
                    updated_at=30.0,
                )
            )
            prepare_store.create(
                SourcePrepareJob(
                    id="source-prepare-only",
                    youtube_url="https://youtu.be/prepare-only",
                    artifact_dir=str(prepare_store.root / "source-prepare-only"),
                    status=JobStatus.DONE,
                    stage="done",
                    message="youtube source ready",
                    result={
                        "video_path": str(prepared_only_source),
                        "video_title": "Take Five Drum Lesson",
                    },
                    created_at=6.0,
                    updated_at=15.0,
                )
            )

            with (
                patch("app.main.job_store", job_store),
                patch("app.main.source_prepare_store", prepare_store),
                patch(
                    "app.main._probe_video_metadata",
                    side_effect=[
                        (1920, 1080, 252.0),
                        (1280, 720, 61.0),
                    ],
                ),
            ):
                response = local_media_registry()

            self.assertEqual(len(response.items), 2)
            self.assertEqual(response.items[0].source_path, str(source_from_job.resolve()))
            self.assertEqual(response.items[0].pdf_path, str(pdf_path.resolve()))
            self.assertEqual(response.items[0].output_dir, str(export_dir.resolve()))
            self.assertTrue(response.items[0].has_score)
            self.assertEqual(response.items[0].source_origin, "job")
            self.assertEqual(response.items[0].display_name, "Blue in Green Drum Cover")
            self.assertEqual(response.items[0].resolution_label, "1920x1080")
            self.assertEqual(response.items[0].duration_label, "04:12")

            self.assertEqual(response.items[1].source_path, str(prepared_only_source.resolve()))
            self.assertIsNone(response.items[1].pdf_path)
            self.assertFalse(response.items[1].has_score)
            self.assertEqual(response.items[1].source_origin, "prepared")
            self.assertEqual(response.items[1].display_name, "Take Five Drum Lesson")
            self.assertEqual(response.items[1].resolution_label, "1280x720")
            self.assertEqual(response.items[1].duration_label, "01:01")

    def test_local_media_registry_upgrades_filename_only_job_name_from_prepare_title(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            shared_source = jobs_root / "_preview_source" / "yt-v3" / "abc123" / "downloads" / "abc123.mp4"
            shared_source.parent.mkdir(parents=True, exist_ok=True)
            shared_source.write_bytes(b"video")

            export_dir = jobs_root / "job-1" / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = export_dir / "sheet_export.pdf"
            pdf_path.write_bytes(b"%PDF")

            job_store = JobStore(jobs_root)
            job_store.create(
                Job(
                    id="job-1",
                    source_type="file",
                    file_path=str(shared_source),
                    youtube_url=None,
                    options={},
                    artifact_dir=str(jobs_root / "job-1"),
                    status=JobStatus.DONE,
                    message="export finished",
                    result={
                        "output_dir": str(export_dir),
                        "pdf": str(pdf_path),
                    },
                    created_at=10.0,
                    updated_at=20.0,
                )
            )

            prepare_store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
            prepare_store.create(
                SourcePrepareJob(
                    id="source-job-backed",
                    youtube_url="https://youtu.be/job-backed",
                    artifact_dir=str(prepare_store.root / "source-job-backed"),
                    status=JobStatus.DONE,
                    stage="done",
                    message="youtube source ready",
                    result={
                        "video_path": str(shared_source),
                        "video_title": "Autumn Leaves Drum Lesson",
                    },
                    created_at=5.0,
                    updated_at=30.0,
                )
            )

            with (
                patch("app.main.job_store", job_store),
                patch("app.main.source_prepare_store", prepare_store),
                patch("app.main._probe_video_metadata", return_value=(1920, 1080, 252.0)),
            ):
                response = local_media_registry()

            self.assertEqual(len(response.items), 1)
            self.assertEqual(response.items[0].display_name, "Autumn Leaves Drum Lesson")
            self.assertEqual(response.items[0].source_origin, "job")
            self.assertEqual(response.items[0].pdf_path, str(pdf_path.resolve()))

    def test_local_media_registry_includes_direct_youtube_done_jobs_without_file_path(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            cache_source = jobs_root / "_preview_source" / "yt-v3" / "abc123" / "downloads" / "direct-youtube.mp4"
            cache_source.parent.mkdir(parents=True, exist_ok=True)
            cache_source.write_bytes(b"video")
            (cache_source.parent / "source.json").write_text(
                '{"source_key":"https://www.youtube.com/watch?v=abc123","video_title":"Direct YouTube Lesson"}',
                encoding="utf-8",
            )

            export_dir = jobs_root / "job-youtube" / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = export_dir / "sheet_export.pdf"
            pdf_path.write_bytes(b"%PDF")

            job_store = JobStore(jobs_root)
            job_store.create(
                Job(
                    id="job-youtube",
                    source_type="youtube",
                    file_path=None,
                    youtube_url="https://youtu.be/abc123",
                    options={},
                    artifact_dir=str(jobs_root / "job-youtube"),
                    status=JobStatus.DONE,
                    result={
                        "source_video_path": str(cache_source),
                        "output_dir": str(export_dir),
                        "pdf": str(pdf_path),
                    },
                    updated_at=20.0,
                )
            )

            prepare_store = SourcePrepareStore(jobs_root / "_preview_source_jobs")

            with (
                patch("app.main.job_store", job_store),
                patch("app.main.source_prepare_store", prepare_store),
                patch("app.main._probe_video_metadata", return_value=(1920, 1080, 252.0)),
            ):
                response = local_media_registry()

            self.assertEqual(len(response.items), 1)
            self.assertEqual(response.items[0].source_path, str(cache_source.resolve()))
            self.assertEqual(response.items[0].display_name, "Direct YouTube Lesson")
            self.assertEqual(response.items[0].youtube_url, "https://www.youtube.com/watch?v=abc123")
            self.assertEqual(response.items[0].pdf_path, str(pdf_path.resolve()))


if __name__ == "__main__":
    unittest.main()
