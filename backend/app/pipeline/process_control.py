"""Bounded subprocess output and cooperative cancellation for capture workers."""
from __future__ import annotations

import subprocess
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from queue import Empty, SimpleQueue
from threading import Event, Thread


class OperationCancelled(Exception):
    pass


_cancel_event: ContextVar[Event | None] = ContextVar("capture_cancel_event", default=None)


@contextmanager
def operation_scope(event: Event):
    token = _cancel_event.set(event)
    try:
        checkpoint()
        yield
    finally:
        _cancel_event.reset(token)


def checkpoint() -> None:
    event = _cancel_event.get()
    if event is not None and event.is_set():
        raise OperationCancelled("capture cancelled")


def run_capture_process(command, *, on_line=None, idle_timeout=120.0):
    """Consume both pipes immediately; keep only the last 64 KiB of stderr."""
    checkpoint()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines = SimpleQueue()
    errors = deque(maxlen=64)

    def read_stdout():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    def read_stderr():
        while chunk := process.stderr.read(1024):
            errors.append(chunk)

    readers = [Thread(target=read_stdout, daemon=True), Thread(target=read_stderr, daemon=True)]
    for reader in readers:
        reader.start()
    last_activity = time.monotonic()
    try:
        while True:
            checkpoint()
            try:
                line = lines.get(timeout=0.1)
            except Empty:
                if time.monotonic() - last_activity > idle_timeout:
                    raise TimeoutError("FFmpeg stopped reporting progress; retry or choose another video")
                continue
            if line is None:
                break
            last_activity = time.monotonic()
            if on_line:
                on_line(line)
        while process.poll() is None:
            checkpoint()
            if time.monotonic() - last_activity > idle_timeout:
                raise TimeoutError("FFmpeg did not finish after its output closed")
            time.sleep(0.05)
        checkpoint()
        returncode = process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for reader in readers:
            reader.join(timeout=2)
        process.stdout.close()
        process.stderr.close()
    return returncode, "".join(errors).strip()
