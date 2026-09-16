import sys
import tempfile
import threading
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.pipeline.rectify import rectify_frames
from app.pipeline.process_control import OperationCancelled, operation_scope, run_capture_process
from app.schemas import RectifyOptions


class CaptureBoundaryTests(unittest.TestCase):
    def test_expanded_legacy_roi_cannot_capture_outside_the_visible_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = np.full((180, 320, 3), (0, 0, 255), dtype=np.uint8)
            source[100:160, 20:300] = (240, 240, 240)
            cv2.line(source, (20, 110), (299, 110), (0, 0, 0), 1)
            frame = root / "frame.png"
            cv2.imwrite(str(frame), source)
            paths = rectify_frames(detections=[{"frame_path": str(frame),
                "roi": [[20, 100], [300, 100], [300, 160], [20, 160]],
                "safe_roi": [[16, 92], [304, 92], [304, 168], [16, 168]]}],
                options=RectifyOptions(auto=False), workspace=root / "out", logger=lambda _: None)
            actual = cv2.imread(str(paths[0]))
            np.testing.assert_array_equal(actual, source[100:160, 20:300])

    def test_missing_region_fails_instead_of_exporting_full_frame(self):
        with tempfile.TemporaryDirectory() as td:
            frame = Path(td) / "frame.png"
            cv2.imwrite(str(frame), np.zeros((40, 60, 3), dtype=np.uint8))
            with self.assertRaises(ValueError):
                rectify_frames(detections=[{"frame_path": str(frame)}], options=RectifyOptions(), workspace=Path(td) / "out", logger=lambda _: None)

    def test_error_pipe_larger_than_os_buffer_finishes_without_deadlock(self):
        lines = []
        code, stderr = run_capture_process([sys.executable, "-c", "import os; os.write(2, b'x'*1048576); print('progress=end')"], on_line=lines.append, idle_timeout=3)
        self.assertEqual(code, 0)
        self.assertIn("progress=end\n", lines)
        self.assertLessEqual(len(stderr), 65536)

    def test_cancelling_terminates_a_silent_process(self):
        event = threading.Event()
        timer = threading.Timer(0.15, event.set)
        timer.start()
        try:
            with self.assertRaises(OperationCancelled), operation_scope(event):
                run_capture_process([sys.executable, "-c", "import time; time.sleep(20)"], idle_timeout=3)
        finally:
            timer.cancel()

    def test_stalled_process_has_a_bounded_wait(self):
        with self.assertRaises(TimeoutError):
            run_capture_process([sys.executable, "-c", "import time; time.sleep(20)"], idle_timeout=0.15)
