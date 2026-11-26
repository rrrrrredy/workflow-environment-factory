"""Run and reap a command tree while retaining a bounded tail of each output stream."""

import os
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

if os.name == "nt":
    from . import windows_job

_LIMIT = 1_000_000


def _read_output(fd: int) -> bytes | None:
    if os.name == "nt":
        available = windows_job.available(fd)
        if available is None:
            return None
        if not available:
            return b""
        return os.read(fd, min(available, 65536)) or None
    try:
        return os.read(fd, 65536) or None
    except BlockingIOError:
        return b""


def run_command(
    argv: list[str],
    cwd: Path,
    timeout: float,
    *,
    env: dict[str, str] | None = None,
    on_started: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    job = windows_job.create_job() if os.name == "nt" else None
    process = None
    stopped = False

    def stop_tree():
        nonlocal job, stopped
        if stopped:
            return
        if job is not None:
            windows_job.close_job(job)
            job = None
        elif process is not None and os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        stopped = True

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=os.name == "posix",
            creationflags=(subprocess.CREATE_NO_WINDOW | 4) if os.name == "nt" else 0,
        )
        if job is not None:
            windows_job.attach_and_resume(job, process)
        if on_started:
            on_started()
        tails = [bytearray(), bytearray()]
        descriptors = {i: stream.fileno() for i, stream in enumerate((process.stdout, process.stderr))}
        if os.name == "posix":
            for fd in descriptors.values():
                os.set_blocking(fd, False)
        deadline = time.monotonic() + timeout
        timed_out = False
        while True:
            now = time.monotonic()
            if not stopped and (process.poll() is not None or now >= deadline):
                timed_out = process.returncode is None
                stop_tree()
                deadline = now + 1
            progress = False
            for index, fd in list(descriptors.items()):
                chunk = _read_output(fd)
                if chunk is None:
                    del descriptors[index]
                elif chunk:
                    tails[index].extend(chunk)
                    del tails[index][:-_LIMIT]
                    progress = True
            if stopped and (not descriptors or now >= deadline):
                break
            if not progress:
                time.sleep(0.005)
        stdout, stderr = (tail.decode("utf-8", "replace") for tail in tails)
        if timed_out:
            raise subprocess.TimeoutExpired(argv, timeout, stdout, stderr)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    finally:
        try:
            stop_tree()
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=2)
                finally:
                    process.stdout.close()
                    process.stderr.close()
                    if os.name == "nt":
                        process._handle.Close()
