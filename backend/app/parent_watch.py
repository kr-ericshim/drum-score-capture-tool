"""End the backend when the desktop app that started it is gone.

The desktop app sets ``DRUMSHEET_EXIT_WITH_PARENT=1`` and keeps the write end of this process's
stdin open without writing to it. When the app exits for any reason (quit, crash, force quit),
the OS closes that end and the read here returns EOF. The backend then ends itself and the
ffmpeg (or other) children it started, even if no signal reached it or a request is still running.
"""

import os
import signal
import subprocess
import sys
import threading

EXIT_WITH_PARENT_ENV = "DRUMSHEET_EXIT_WITH_PARENT"


def _end_process_tree() -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(os.getpid())], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        elif os.getpgid(0) == os.getpid():  # never signal a group this process did not create
            os.killpg(0, signal.SIGKILL)
    except Exception:
        pass
    os._exit(0)


def _exit_when_closed(fd: int) -> None:
    try:
        while os.read(fd, 4096):
            pass
    except OSError:
        pass
    _end_process_tree()


def start_parent_watch(environ=os.environ) -> bool:
    if environ.get(EXIT_WITH_PARENT_ENV) != "1":
        return False
    if sys.platform == "win32":
        # fd 0 stays as it is: replacing it would leave the Win32 standard input handle that
        # subprocess hands to children pointing at a closed handle.
        watch_fd = 0
    else:
        # Own process group, so the exit can take every child with it.
        try:
            os.setpgid(0, 0)
        except OSError:
            pass
        # Read the pipe through a private, non-inheritable copy and give fd 0 /dev/null again,
        # so ffmpeg and other children keep the empty stdin they had before.
        watch_fd = os.dup(0)
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        os.close(devnull)
    threading.Thread(target=_exit_when_closed, args=(watch_fd,), name="parent-watch", daemon=True).start()
    return True
