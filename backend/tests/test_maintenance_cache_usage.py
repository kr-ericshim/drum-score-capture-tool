import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class TestMaintenanceCacheUsage(unittest.TestCase):
    def test_cache_usage_counts_top_level_paths_and_recursive_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            root_file = jobs_root / "root-note.txt"
            root_file.write_bytes(b"abc")

            export_dir = jobs_root / "job-1" / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / "page-1.png").write_bytes(b"12345")
            (export_dir / "page-2.png").write_bytes(b"6789")

            cache_dir = jobs_root / "_preview_source" / "yt-v3" / "abc123" / "downloads"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "source.mp4").write_bytes(b"video")
            (cache_dir / "source.json").write_bytes(b"{}")

            (jobs_root / "empty-job").mkdir()

            with patch.object(main, "jobs_root", jobs_root):
                response = main.cache_usage()

            self.assertEqual(response.total_paths, 4)
            self.assertEqual(response.total_bytes, 3 + 5 + 4 + 5 + 2)
            self.assertEqual(response.total_human, "19 B")

    def test_cache_usage_ignores_files_removed_during_scan(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            stable_dir = jobs_root / "stable-job"
            stable_dir.mkdir()
            (stable_dir / "artifact.txt").write_bytes(b"stable")

            disappearing_file = jobs_root / "removed-before-size.txt"
            disappearing_file.write_bytes(b"stale")

            original_path_size = main._path_size_bytes

            def remove_before_sizing(path: Path) -> int:
                if path == disappearing_file:
                    disappearing_file.unlink()
                return original_path_size(path)

            with patch.object(main, "jobs_root", jobs_root), patch.object(
                main,
                "_path_size_bytes",
                side_effect=remove_before_sizing,
            ):
                response = main.cache_usage()

            self.assertEqual(response.total_paths, 2)
            self.assertEqual(response.total_bytes, len(b"stable"))
            self.assertEqual(response.total_human, "6 B")

    def test_cache_usage_summarizes_large_nested_job_tree(self):
        with tempfile.TemporaryDirectory() as td:
            jobs_root = Path(td) / "jobs"
            jobs_root.mkdir(parents=True, exist_ok=True)

            expected_bytes = 0
            for job_index in range(20):
                job_root = jobs_root / f"job-{job_index:02d}"
                for section in ("frames", "rectified", "export"):
                    section_root = job_root / section
                    section_root.mkdir(parents=True, exist_ok=True)
                    for file_index in range(5):
                        payload = bytes([job_index, file_index]) * (file_index + 1)
                        expected_bytes += len(payload)
                        (section_root / f"artifact-{file_index}.bin").write_bytes(payload)

            with patch.object(main, "jobs_root", jobs_root):
                response = main.cache_usage()

            self.assertEqual(response.total_paths, 20)
            self.assertEqual(response.total_bytes, expected_bytes)


if __name__ == "__main__":
    unittest.main()
