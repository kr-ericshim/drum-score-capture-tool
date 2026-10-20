import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from app.parent_watch import EXIT_WITH_PARENT_ENV, start_parent_watch

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _child_env(**extra):
    env = {**os.environ, "PYTHONPATH": str(BACKEND_DIR)}
    env.pop(EXIT_WITH_PARENT_ENV, None)
    env.update(extra)
    return env


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestParentWatch(unittest.TestCase):
    def test_disabled_without_the_env_flag(self):
        self.assertFalse(start_parent_watch({}))

    def test_exits_with_its_children_when_stdin_closes(self):
        script = textwrap.dedent("""
            import subprocess, sys, time
            from app.parent_watch import start_parent_watch
            assert start_parent_watch()
            if sys.platform != "win32":  # Windows keeps the pipe on fd 0
                # a child reading stdin to EOF must not wait on the parent's pipe
                child = subprocess.run([sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"],
                                       capture_output=True, text=True, timeout=10)
                print("child-stdin", child.stdout.strip(), flush=True)
            worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            print("worker", worker.pid, flush=True)
            time.sleep(60)
        """)
        proc = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, env=_child_env(**{EXIT_WITH_PARENT_ENV: "1"}))
        worker_pid = None
        try:
            if sys.platform != "win32":
                self.assertEqual(proc.stdout.readline().strip(), "child-stdin 0")
            worker_pid = int(proc.stdout.readline().split()[1])
            self.assertIsNone(proc.poll())
            proc.stdin.close()
            proc.wait(timeout=10)
            deadline = time.monotonic() + 10
            while _alive(worker_pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(_alive(worker_pid), "the backend's child kept running")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            if worker_pid and _alive(worker_pid):
                os.kill(worker_pid, signal.SIGTERM)


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@unittest.skipIf(sys.platform == "win32", "SIGTERM delivery is POSIX-only")
class TestBackendShutdown(unittest.TestCase):
    def test_sigterm_does_not_wait_for_a_long_request(self):
        port = _free_port()
        script = textwrap.dedent("""
            import time
            import run
            @run.fastapi_app.get("/health/slow-test")
            def slow():
                time.sleep(120)
                return {}
            run.main()
        """)
        with tempfile.TemporaryDirectory() as jobs_dir:
            proc = subprocess.Popen([sys.executable, "-c", script], cwd=str(BACKEND_DIR),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    env=_child_env(DRUMSHEET_PORT=str(port), DRUMSHEET_JOBS_DIR=jobs_dir))
            try:
                deadline = time.monotonic() + 60
                while True:
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read()
                        break
                    except OSError:
                        if time.monotonic() > deadline or proc.poll() is not None:
                            self.fail("backend did not start")
                        time.sleep(0.2)
                threading.Thread(target=lambda: _ignore_errors(
                    lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/health/slow-test", timeout=60).read()),
                    daemon=True).start()
                time.sleep(1.0)
                started = time.monotonic()
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=20)
                self.assertLess(time.monotonic() - started, 15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


def _ignore_errors(fn):
    try:
        fn()
    except Exception:
        pass


if __name__ == "__main__":
    unittest.main()
