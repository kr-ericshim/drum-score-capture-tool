import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.pipeline import extract


class FakeYoutubeDL:
    plans = []
    seen_opts = []

    def __init__(self, opts):
        self.opts = dict(opts)
        self.plan = None

    def __enter__(self):
        type(self).seen_opts.append(self.opts)
        if not type(self).plans:
            raise AssertionError("missing FakeYoutubeDL plan")
        self.plan = type(self).plans.pop(0)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=True):
        if self.plan.get("raise"):
            raise self.plan["raise"]
        ext = self.plan.get("ext", "mp4")
        path = Path(self.opts["outtmpl"].replace("%(id)s", "sample").replace("%(ext)s", ext))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        return {"id": "sample", "ext": ext}

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", info["ext"])


class DownloadYoutubeTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.plans = []
        FakeYoutubeDL.seen_opts = []

    def test_download_prefers_quality_first(self):
        FakeYoutubeDL.plans = [{"ext": "webm"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(extract, "YoutubeDL", FakeYoutubeDL), patch.object(
                extract,
                "_probe_download_resolution",
                return_value=(1920, 1080),
            ):
                output = extract._download_youtube("https://example.com/watch?v=abc", Path(tmpdir), logger=lambda _: None)
                self.assertTrue(output.exists())
        self.assertEqual(FakeYoutubeDL.seen_opts[0]["format"], "bestvideo+bestaudio/best")
        self.assertNotIn("merge_output_format", FakeYoutubeDL.seen_opts[0])
        self.assertNotIn("extractor_args", FakeYoutubeDL.seen_opts[0])

    def test_download_passes_bundled_ffmpeg_to_ytdlp(self):
        FakeYoutubeDL.plans = [{"ext": "webm"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            ffmpeg_bin = Path(tmpdir) / "ffmpeg"
            ffmpeg_bin.write_bytes(b"fake-ffmpeg")
            with patch.object(extract, "YoutubeDL", FakeYoutubeDL), patch.object(
                extract,
                "resolve_ffmpeg_bin",
                return_value=str(ffmpeg_bin),
            ), patch.object(
                extract,
                "_probe_download_resolution",
                return_value=(1920, 1080),
            ), patch.object(extract, "ensure_runtime_bin_on_path") as ensure_path:
                output = extract._download_youtube("https://example.com/watch?v=abc", Path(tmpdir), logger=lambda _: None)
                self.assertTrue(output.exists())

        self.assertEqual(FakeYoutubeDL.seen_opts[0]["ffmpeg_location"], str(ffmpeg_bin))
        ensure_path.assert_called_once_with(ffmpeg_bin=str(ffmpeg_bin), logger=unittest.mock.ANY)

    def test_download_falls_back_to_mp4_compatibility(self):
        FakeYoutubeDL.plans = [
            {"raise": RuntimeError("quality path failed")},
            {"ext": "mp4"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(extract, "YoutubeDL", FakeYoutubeDL), patch.object(
                extract,
                "_probe_download_resolution",
                return_value=(1920, 1080),
            ):
                output = extract._download_youtube("https://example.com/watch?v=abc", Path(tmpdir), logger=lambda _: None)
                self.assertTrue(output.exists())
        self.assertEqual(FakeYoutubeDL.seen_opts[0]["format"], "bestvideo+bestaudio/best")
        self.assertEqual(
            FakeYoutubeDL.seen_opts[1]["format"],
            "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        )
        self.assertEqual(FakeYoutubeDL.seen_opts[1]["merge_output_format"], "mp4")

    def test_download_retries_when_first_result_is_low_resolution(self):
        FakeYoutubeDL.plans = [{"ext": "mp4"}, {"ext": "mp4"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(extract, "YoutubeDL", FakeYoutubeDL), patch.object(
                extract,
                "_probe_download_resolution",
                side_effect=[(640, 360), (1920, 1080)],
            ):
                output = extract._download_youtube("https://example.com/watch?v=abc", Path(tmpdir), logger=lambda _: None)
                self.assertTrue(output.exists())

        self.assertEqual(len(FakeYoutubeDL.seen_opts), 2)
        self.assertEqual(FakeYoutubeDL.seen_opts[0]["format"], "bestvideo+bestaudio/best")
        self.assertEqual(FakeYoutubeDL.seen_opts[1]["format"], "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best")
