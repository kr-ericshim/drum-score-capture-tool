import sys
import threading
import unittest

from app.pipeline.process_control import OperationCancelled, operation_scope, run_capture_process


class CaptureBoundaryTests(unittest.TestCase):
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
