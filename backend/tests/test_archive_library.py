import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.job_store import Job, JobStatus, JobStore, SourcePrepareJob, SourcePrepareStore
from app.schemas import JobCreate


class TestArchiveLibrary(unittest.TestCase):
    def _import_main_with_stubbed_cv(self):
        acceleration = types.ModuleType("app.pipeline.acceleration")
        acceleration.get_runtime_acceleration = lambda *args, **kwargs: {}
        acceleration.runtime_public_info = lambda *args, **kwargs: {}

        extract = types.ModuleType("app.pipeline.extract")
        extract.YOUTUBE_DOWNLOAD_STRATEGY_VERSION = "test"
        extract.extract_frames = lambda *args, **kwargs: []
        extract.extract_preview_frame = lambda *args, **kwargs: None
        extract.prepare_preview_source = lambda *args, **kwargs: None

        detect = types.ModuleType("app.pipeline.detect")
        detect.detect_sheet_regions = lambda *args, **kwargs: []

        layout_profiles = types.ModuleType("app.pipeline.layout_profiles")
        layout_profiles.infer_layout_hint_from_roi = lambda *args, **kwargs: "full_scroll"

        roi_health = types.ModuleType("app.pipeline.roi_health")
        roi_health.analyze_roi_health_for_source = lambda *args, **kwargs: {}

        rectify = types.ModuleType("app.pipeline.rectify")
        rectify.rectify_frames = lambda *args, **kwargs: []

        stitch = types.ModuleType("app.pipeline.stitch")
        stitch.select_review_candidates = lambda *args, **kwargs: []
        stitch.stitch_pages = lambda *args, **kwargs: []

        upscale = types.ModuleType("app.pipeline.upscale")
        upscale.upscale_frames = lambda *args, **kwargs: []

        export = types.ModuleType("app.pipeline.export")
        export.export_frames = lambda *args, **kwargs: {}
        export.export_selected_pages = lambda *args, **kwargs: {}

        stubbed_modules = {
            "cv2": types.ModuleType("cv2"),
            "app.pipeline.acceleration": acceleration,
            "app.pipeline.extract": extract,
            "app.pipeline.detect": detect,
            "app.pipeline.layout_profiles": layout_profiles,
            "app.pipeline.roi_health": roi_health,
            "app.pipeline.rectify": rectify,
            "app.pipeline.stitch": stitch,
            "app.pipeline.upscale": upscale,
            "app.pipeline.export": export,
        }
        previous_main = sys.modules.pop("app.main", None)
        try:
            with patch.dict(sys.modules, stubbed_modules):
                return importlib.import_module("app.main")
        finally:
            sys.modules.pop("app.main", None)
            if previous_main is not None:
                sys.modules["app.main"] = previous_main

    def test_job_store_round_trip_preserves_source_identity_and_completed_at(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            store = JobStore(jobs_root)
            job = Job(
                id="job-1",
                source_type="file",
                file_path="/tmp/source.mp4",
                youtube_url=None,
                options={},
                artifact_dir=str(jobs_root / "job-1"),
                source_identity={
                    "kind": "youtube",
                    "key": "https://www.youtube.com/watch?v=abc123",
                    "display_name": "Blue in Green Drum Cover",
                },
                completed_at=1713526200.0,
            )

            store.create(job)
            reloaded = JobStore(jobs_root)
            loaded = reloaded.get("job-1")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.source_identity["kind"], "youtube")
            self.assertEqual(
                loaded.source_identity["display_name"],
                "Blue in Green Drum Cover",
            )
            self.assertEqual(loaded.completed_at, 1713526200.0)

    def test_create_job_persists_source_identity_from_live_jobs_path(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            source_path = Path(td) / "source.mp4"
            source_path.write_bytes(b"video")

            payload = JobCreate(
                source_type="file",
                file_path=str(source_path),
                source_identity={
                    "kind": "youtube",
                    "key": "https://youtu.be/abc12345678?si=demo",
                    "display_name": "Blue in Green Drum Cover",
                },
                options={
                    "detect": {
                        "roi": [[0, 0], [320, 0], [320, 180], [0, 180]],
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
            ):
                response = main.create_job(payload)

            reloaded = JobStore(jobs_root)
            loaded = reloaded.get(response.job_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(
                loaded.source_identity,
                {
                    "kind": "youtube",
                    "key": "https://www.youtube.com/watch?v=abc12345678",
                    "display_name": "Blue in Green Drum Cover",
                },
            )
            self.assertEqual(len(submitted), 1)

    def test_set_state_stamps_completed_at_when_job_becomes_done(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-2"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-2",
                    source_type="file",
                    file_path="/tmp/source.mp4",
                    youtube_url=None,
                    options={},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.RUNNING,
                )
            )

            with patch("app.job_store.time.time", return_value=1713526200.0):
                store.set_state("job-2", JobStatus.DONE)

            loaded = store.get("job-2")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.completed_at, 1713526200.0)

    def test_set_state_done_does_not_overwrite_existing_completed_at(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td)
            artifact_dir = jobs_root / "job-3"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store = JobStore(jobs_root)
            store.create(
                Job(
                    id="job-3",
                    source_type="file",
                    file_path="/tmp/source.mp4",
                    youtube_url=None,
                    options={},
                    artifact_dir=str(artifact_dir),
                    status=JobStatus.RUNNING,
                    completed_at=1713526200.0,
                )
            )

            with patch("app.job_store.time.time", return_value=1813526200.0):
                store.set_state("job-3", JobStatus.DONE)

            loaded = store.get("job-3")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.completed_at, 1713526200.0)

    def test_archive_prepare_snapshot_exposes_video_title_and_source_key(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = SourcePrepareStore(jobs_root / "_preview_source_jobs")
            artifact_dir = store.root / "source-1"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            store.create(
                SourcePrepareJob(
                    id="source-1",
                    youtube_url="https://youtu.be/abc12345678?si=demo",
                    artifact_dir=str(artifact_dir),
                )
            )

            with (
                patch.object(main, "source_prepare_store", store),
                patch.object(
                    main,
                    "_get_or_prepare_cached_youtube_video",
                    return_value={
                        "video_path": Path("/tmp/cache/abc123.mp4"),
                        "from_cache": True,
                        "video_title": "Take Five Drum Lesson",
                        "source_key": "https://youtu.be/abc12345678?si=demo",
                    },
                ),
                patch.object(main, "_to_jobs_files_url", return_value="/jobs-files/_preview/youtube.mp4"),
            ):
                main._run_source_prepare_job("source-1")

            job = store.get("source-1")
            self.assertIsNotNone(job)
            self.assertEqual(job.status, JobStatus.DONE)
            result = job.result or {}
            self.assertEqual(result["video_title"], "Take Five Drum Lesson")
            self.assertEqual(result["source_key"], "https://www.youtube.com/watch?v=abc12345678")

    def _create_done_job(
        self,
        store: JobStore,
        jobs_root: Path,
        *,
        job_id: str,
        source_type: str = "file",
        source_kind: str | None = None,
        source_key: str | None = None,
        display_name: str = "",
        file_path: str | None = "/tmp/nonexistent-source.mp4",
        youtube_url: str | None = None,
        completed_at: float | None = None,
        updated_at: float | None = None,
        pdf_relative_path: str | None = None,
        create_pdf: bool = True,
        output_dir_relative_path: str | None = None,
        review_export_applied: bool = False,
        include_source_identity: bool = True,
    ) -> dict:
        pdf_path = None
        if pdf_relative_path is not None:
            pdf_path = jobs_root / pdf_relative_path
            if create_pdf:
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(b"%PDF-1.4\n% archive test pdf\n")

        output_dir = None
        if output_dir_relative_path is not None:
            output_dir = jobs_root / output_dir_relative_path
            output_dir.mkdir(parents=True, exist_ok=True)

        resolved_source_kind = source_kind or source_type
        source_identity = {}
        if include_source_identity:
            source_identity["kind"] = resolved_source_kind
            if source_key is not None:
                source_identity["key"] = source_key
            if display_name:
                source_identity["display_name"] = display_name

        result = {
            "pdf": str(pdf_path) if pdf_path is not None else None,
            "output_dir": str(output_dir) if output_dir is not None else None,
        }
        if review_export_applied:
            result["review_export"] = {
                "kept_count": 1,
                "requested_count": 1,
                "selection_mode": "pages",
                "selected_captures": [],
                "selected_pages": [],
            }

        artifact_dir = jobs_root / job_id
        store.create(
            Job(
                id=job_id,
                source_type=source_type,
                file_path=file_path,
                youtube_url=youtube_url,
                options={},
                artifact_dir=str(artifact_dir),
                source_identity=source_identity,
                completed_at=completed_at,
                updated_at=updated_at if updated_at is not None else float(completed_at or 0.0),
                status=JobStatus.DONE,
                result=result,
            )
        )

        return {
            "pdf_path": str(pdf_path.resolve()) if pdf_path is not None and create_pdf else (str(pdf_path) if pdf_path is not None else None),
            "output_dir": str(output_dir.resolve()) if output_dir is not None else None,
        }

    def test_archive_library_groups_by_source_key_and_keeps_latest_pdf(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)

            older = self._create_done_job(
                store,
                jobs_root,
                job_id="job-older",
                source_key="file:/scores/blue.mp4",
                display_name="Blue Session",
                completed_at=100.0,
                pdf_relative_path="exports/job-older/sheet_export.pdf",
                output_dir_relative_path="exports/job-older",
            )
            newer = self._create_done_job(
                store,
                jobs_root,
                job_id="job-newer",
                source_key="file:/scores/blue.mp4",
                display_name="Blue Session Latest",
                completed_at=200.0,
                pdf_relative_path="exports/job-newer/sheet_export.pdf",
                output_dir_relative_path="exports/job-newer",
            )
            self._create_done_job(
                store,
                jobs_root,
                job_id="job-other",
                source_key="file:/scores/green.mp4",
                display_name="Green Session",
                completed_at=150.0,
                pdf_relative_path="exports/job-other/sheet_export.pdf",
                output_dir_relative_path="exports/job-other",
            )
            self._create_done_job(
                store,
                jobs_root,
                job_id="job-no-key",
                source_type="file",
                source_key=None,
                display_name="Missing Source Key",
                file_path=None,
                include_source_identity=False,
                completed_at=300.0,
                pdf_relative_path="exports/job-no-key/sheet_export.pdf",
                output_dir_relative_path="exports/job-no-key",
            )

            with patch.object(main, "job_store", store):
                response = main.archive_library()

            self.assertEqual(len(response.items), 2)
            self.assertEqual([item.source_key for item in response.items], ["file:/scores/blue.mp4", "file:/scores/green.mp4"])
            self.assertEqual(response.items[0].pdf_path, newer["pdf_path"])
            self.assertEqual(response.items[0].output_dir, newer["output_dir"])
            self.assertEqual(response.items[0].display_name, "Blue Session Latest")
            self.assertEqual(response.items[0].completed_at, 200.0)
            self.assertNotEqual(response.items[0].pdf_path, older["pdf_path"])

    def test_archive_library_skips_missing_or_nonexistent_pdf_rows(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)

            older_valid = self._create_done_job(
                store,
                jobs_root,
                job_id="job-valid",
                source_key="file:/scores/blue.mp4",
                display_name="Blue Session",
                completed_at=100.0,
                pdf_relative_path="exports/job-valid/sheet_export.pdf",
                output_dir_relative_path="exports/job-valid",
            )
            self._create_done_job(
                store,
                jobs_root,
                job_id="job-missing-pdf",
                source_key="file:/scores/blue.mp4",
                display_name="Blue Session Missing PDF",
                completed_at=300.0,
                pdf_relative_path="exports/job-missing-pdf/sheet_export.pdf",
                create_pdf=False,
                output_dir_relative_path="exports/job-missing-pdf",
            )
            self._create_done_job(
                store,
                jobs_root,
                job_id="job-no-pdf",
                source_key="file:/scores/red.mp4",
                display_name="Red Session",
                completed_at=250.0,
                pdf_relative_path=None,
                output_dir_relative_path="exports/job-no-pdf",
            )

            with patch.object(main, "job_store", store):
                response = main.archive_library()

            self.assertEqual(len(response.items), 1)
            self.assertEqual(response.items[0].source_key, "file:/scores/blue.mp4")
            self.assertEqual(response.items[0].pdf_path, older_valid["pdf_path"])
            self.assertEqual(response.items[0].completed_at, 100.0)

    def test_archive_library_uses_file_path_fallback_when_source_identity_is_missing(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)

            source_file = Path(td) / "recordings" / "fallback-source.mp4"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_bytes(b"video")
            created = self._create_done_job(
                store,
                jobs_root,
                job_id="job-fallback-file",
                source_type="file",
                file_path=str(source_file.resolve()),
                include_source_identity=False,
                completed_at=120.0,
                pdf_relative_path="exports/job-fallback-file/sheet_export.pdf",
                output_dir_relative_path="exports/job-fallback-file",
            )

            with patch.object(main, "job_store", store):
                response = main.archive_library()

            self.assertEqual(len(response.items), 1)
            item = response.items[0]
            self.assertEqual(item.source_key, str(source_file.resolve()))
            self.assertEqual(item.source_kind, "file")
            self.assertEqual(item.display_name, "fallback-source.mp4")
            self.assertEqual(item.pdf_path, created["pdf_path"])
            self.assertEqual(item.output_dir, created["output_dir"])

    def test_archive_library_returns_latest_review_export_pdf_when_present(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)

            initial_final = self._create_done_job(
                store,
                jobs_root,
                job_id="job-final",
                source_kind="youtube",
                source_key="https://www.youtube.com/watch?v=abc123",
                display_name="Take Five Drum Lesson",
                completed_at=180.0,
                pdf_relative_path="exports/job-final/sheet_export.pdf",
                output_dir_relative_path="exports/job-final",
            )
            review_export = self._create_done_job(
                store,
                jobs_root,
                job_id="job-review-export",
                source_kind="youtube",
                source_key="https://www.youtube.com/watch?v=abc123",
                display_name="Take Five Drum Lesson",
                completed_at=240.0,
                pdf_relative_path="exports/job-review-export/review_export.pdf",
                output_dir_relative_path="exports/job-review-export",
            )

            with patch.object(main, "job_store", store):
                response = main.archive_library()

            self.assertEqual(len(response.items), 1)
            item = response.items[0]
            self.assertEqual(item.source_key, "https://www.youtube.com/watch?v=abc123")
            self.assertEqual(item.source_kind, "youtube")
            self.assertEqual(item.display_name, "Take Five Drum Lesson")
            self.assertEqual(item.completed_at, 240.0)
            self.assertEqual(item.pdf_path, review_export["pdf_path"])
            self.assertEqual(item.output_dir, review_export["output_dir"])
            self.assertNotEqual(item.pdf_path, initial_final["pdf_path"])

    def test_archive_library_groups_equivalent_youtube_urls_under_one_canonical_key(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)

            self._create_done_job(
                store,
                jobs_root,
                job_id="job-short-url",
                source_kind="youtube",
                source_type="youtube",
                source_key="https://youtu.be/abc12345678?si=short",
                display_name="Take Five Drum Lesson",
                file_path=None,
                youtube_url="https://youtu.be/abc12345678?si=short",
                completed_at=180.0,
                pdf_relative_path="exports/job-short-url/sheet_export.pdf",
                output_dir_relative_path="exports/job-short-url",
            )
            latest = self._create_done_job(
                store,
                jobs_root,
                job_id="job-watch-url",
                source_kind="youtube",
                source_type="youtube",
                source_key="https://www.youtube.com/watch?v=abc12345678&t=43",
                display_name="Take Five Drum Lesson Latest",
                file_path=None,
                youtube_url="https://www.youtube.com/watch?v=abc12345678&t=43",
                completed_at=260.0,
                pdf_relative_path="exports/job-watch-url/review_export.pdf",
                output_dir_relative_path="exports/job-watch-url",
            )

            with patch.object(main, "job_store", store):
                response = main.archive_library()

            self.assertEqual(len(response.items), 1)
            item = response.items[0]
            self.assertEqual(item.source_key, "https://www.youtube.com/watch?v=abc12345678")
            self.assertEqual(item.pdf_path, latest["pdf_path"])
            self.assertEqual(item.output_dir, latest["output_dir"])
            self.assertEqual(item.display_name, "Take Five Drum Lesson Latest")
            self.assertEqual(item.completed_at, 260.0)

    def test_archive_library_restores_direct_youtube_source_path_and_title_from_cache(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)

            cache_source = jobs_root / "_preview_source" / "test" / "abc123" / "downloads" / "direct-youtube.mp4"
            cache_source.parent.mkdir(parents=True, exist_ok=True)
            cache_source.write_bytes(b"video")
            (cache_source.parent / "source.json").write_text(
                '{"source_key":"https://www.youtube.com/watch?v=abc123","video_title":"Direct YouTube Lesson"}',
                encoding="utf-8",
            )

            export_dir = jobs_root / "job-youtube" / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = export_dir / "sheet_export.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n% archive test pdf\n")

            store.create(
                Job(
                    id="job-youtube",
                    source_type="youtube",
                    file_path=None,
                    youtube_url="https://youtu.be/abc123",
                    options={},
                    artifact_dir=str(jobs_root / "job-youtube"),
                    completed_at=1713526200.0,
                    updated_at=1713526201.0,
                    status=JobStatus.DONE,
                    result={
                        "source_video_path": str(cache_source),
                        "pdf": str(pdf_path),
                        "output_dir": str(export_dir),
                    },
                )
            )

            with (
                patch.object(main, "jobs_root", jobs_root),
                patch.object(main, "job_store", store),
            ):
                response = main.archive_library()

            self.assertEqual(len(response.items), 1)
            item = response.items[0]
            self.assertEqual(item.source_key, "https://www.youtube.com/watch?v=abc123")
            self.assertEqual(item.source_kind, "youtube")
            self.assertEqual(item.display_name, "Direct YouTube Lesson")
            self.assertEqual(item.source_path, str(cache_source.resolve()))
            self.assertEqual(item.youtube_url, "https://www.youtube.com/watch?v=abc123")

    def test_archive_library_prefers_review_export_when_updated_after_newer_raw_export(self):
        main = self._import_main_with_stubbed_cv()
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)
            store = JobStore(jobs_root)

            review_export = self._create_done_job(
                store,
                jobs_root,
                job_id="job-reviewed",
                source_kind="youtube",
                source_type="youtube",
                source_key="https://www.youtube.com/watch?v=abc123",
                display_name="Take Five Drum Lesson",
                file_path=None,
                youtube_url="https://www.youtube.com/watch?v=abc123",
                completed_at=180.0,
                updated_at=260.0,
                pdf_relative_path="exports/job-reviewed/review_export.pdf",
                output_dir_relative_path="exports/job-reviewed",
                review_export_applied=True,
            )
            newer_raw = self._create_done_job(
                store,
                jobs_root,
                job_id="job-newer-raw",
                source_kind="youtube",
                source_type="youtube",
                source_key="https://www.youtube.com/watch?v=abc123",
                display_name="Take Five Drum Lesson Raw",
                file_path=None,
                youtube_url="https://www.youtube.com/watch?v=abc123",
                completed_at=220.0,
                updated_at=220.0,
                pdf_relative_path="exports/job-newer-raw/sheet_export.pdf",
                output_dir_relative_path="exports/job-newer-raw",
            )

            with patch.object(main, "job_store", store):
                response = main.archive_library()

            self.assertEqual(len(response.items), 1)
            item = response.items[0]
            self.assertEqual(item.pdf_path, review_export["pdf_path"])
            self.assertEqual(item.output_dir, review_export["output_dir"])
            self.assertEqual(item.completed_at, 260.0)
            self.assertNotEqual(item.pdf_path, newer_raw["pdf_path"])


if __name__ == "__main__":
    unittest.main()
