import unittest

from app import main


class TestSourceValidation(unittest.TestCase):
    def test_accepts_supported_youtube_hosts(self):
        self.assertEqual(
            main._normalize_supported_youtube_url("https://www.youtube.com/watch?v=abc12345678"),
            "https://www.youtube.com/watch?v=abc12345678",
        )
        self.assertEqual(
            main._normalize_supported_youtube_url("https://youtu.be/abc12345678"),
            "https://youtu.be/abc12345678",
        )

    def test_rejects_non_http_or_unsupported_hosts(self):
        with self.assertRaises(ValueError):
            main._normalize_supported_youtube_url("file:///tmp/video.mp4")

        with self.assertRaises(ValueError):
            main._normalize_supported_youtube_url("https://example.com/video")


if __name__ == "__main__":
    unittest.main()
