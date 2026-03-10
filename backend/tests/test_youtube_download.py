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
            with patch.object(extract, "YoutubeDL", FakeYoutubeDL):
                output = extract._download_youtube("https://example.com/watch?v=abc", Path(tmpdir), logger=lambda _: None)
                self.assertTrue(output.exists())
        self.assertEqual(FakeYoutubeDL.seen_opts[0]["format"], "bestvideo+bestaudio/best")
        self.assertNotIn("merge_output_format", FakeYoutubeDL.seen_opts[0])

    def test_download_falls_back_to_mp4_compatibility(self):
        FakeYoutubeDL.plans = [
            {"raise": RuntimeError("quality path failed")},
            {"ext": "mp4"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(extract, "YoutubeDL", FakeYoutubeDL):
                output = extract._download_youtube("https://example.com/watch?v=abc", Path(tmpdir), logger=lambda _: None)
                self.assertTrue(output.exists())
        self.assertEqual(FakeYoutubeDL.seen_opts[0]["format"], "bestvideo+bestaudio/best")
        self.assertEqual(
            FakeYoutubeDL.seen_opts[1]["format"],
            "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        )
        self.assertEqual(FakeYoutubeDL.seen_opts[1]["merge_output_format"], "mp4")
