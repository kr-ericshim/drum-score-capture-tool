import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from app.schemas import PreviewAutoRoiRequest


class PreviewAutoRoiApiTests(unittest.TestCase):
    def test_endpoint_returns_suggestion_and_infers_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            suggestion = {
                "status": "suggested",
                "roi": [[10.0, 400.0], [950.0, 400.0], [950.0, 520.0], [10.0, 520.0]],
                "evidence_level": "high",
                "is_dark_mode": False,
                "diagnostics": {"supporting_frames": 3},
            }

            with patch.object(main, "jobs_root", root / "jobs"), patch.object(
                main,
                "estimate_auto_roi_for_source",
                return_value=suggestion,
            ):
                response = main.preview_auto_roi(
                    PreviewAutoRoiRequest(source_type="file", file_path=str(source), start_sec=12.0)
                )

            self.assertEqual(response.status, "suggested")
            self.assertEqual(response.evidence_level, "high")
            self.assertEqual(response.layout_hint, "bottom_bar")
            self.assertEqual(response.diagnostics["supporting_frames"], 3)


if __name__ == "__main__":
    unittest.main()
