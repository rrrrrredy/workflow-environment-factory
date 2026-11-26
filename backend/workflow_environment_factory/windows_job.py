"""Win32 Job ownership for a subprocess started with CREATE_SUSPENDED."""

import ctypes as c
from ctypes import wintypes as w
from msvcrt import get_osfhandle

kernel = c.WinDLL("kernel32", use_last_error=True)


def _api(name, returns, *args):
    fn = getattr(kernel, name)
    fn.restype, fn.argtypes = returns, args
    return fn


class BasicLimits(c.Structure):
    _fields_ = [
        ("process_time", c.c_int64),
        ("job_time", c.c_int64),
        ("flags", w.DWORD),
        ("min_ws", c.c_size_t),
        ("max_ws", c.c_size_t),
        ("active", w.DWORD),
        ("affinity", c.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class ExtendedLimits(c.Structure):
    _fields_ = [("basic", BasicLimits), ("io_counters", c.c_uint64 * 6), ("memory_limits", c.c_size_t * 4)]


class ThreadEntry(c.Structure):
    _fields_ = [(name, w.DWORD) for name in ("size", "usage", "tid", "pid", "priority", "delta", "flags")]


_create = _api("CreateJobObjectW", w.HANDLE, w.LPVOID, w.LPCWSTR)
_set = _api("SetInformationJobObject", w.BOOL, w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
_assign = _api("AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)
_snapshot = _api("CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
_first = _api("Thread32First", w.BOOL, w.HANDLE, c.POINTER(ThreadEntry))
_next = _api("Thread32Next", w.BOOL, w.HANDLE, c.POINTER(ThreadEntry))
_open_thread = _api("OpenThread", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
_resume = _api("ResumeThread", w.DWORD, w.HANDLE)
_close = _api("CloseHandle", w.BOOL, w.HANDLE)
_peek = _api("PeekNamedPipe", w.BOOL, w.HANDLE, w.LPVOID, w.DWORD, w.LPVOID, c.POINTER(w.DWORD), w.LPVOID)


def create_job():
    job = _create(None, None)
    if not job:
        raise c.WinError(c.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _set(job, 9, c.byref(limits), c.sizeof(limits)):
        error = c.WinError(c.get_last_error())
        _close(job)
        raise error
    return job


def attach_and_resume(job, process):
    if not _assign(job, int(process._handle)):
        raise c.WinError(c.get_last_error())
    # Popen closes the primary thread handle. The suspended child has precisely one thread.
    snapshot = _snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == w.HANDLE(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        entry = ThreadEntry()
        entry.size = c.sizeof(entry)
        ok = _first(snapshot, c.byref(entry))
        while ok:
            if entry.pid == process.pid:
                thread = _open_thread(2, False, entry.tid)  # THREAD_SUSPEND_RESUME
                if not thread:
                    raise c.WinError(c.get_last_error())
                try:
                    if _resume(thread) == 0xFFFFFFFF:
                        raise c.WinError(c.get_last_error())
                    return
                finally:
                    _close(thread)
            ok = _next(snapshot, c.byref(entry))
        raise OSError("suspended process primary thread could not be found")
    finally:
        _close(snapshot)


def close_job(job):
    if not _close(job):
        raise c.WinError(c.get_last_error())


def available(fd):
    size = w.DWORD()
    if not _peek(get_osfhandle(fd), None, 0, None, c.byref(size), None):
        error = c.get_last_error()
        if error in {109, 232, 233}:  # Broken, closing, or disconnected pipe.
            return None
        raise c.WinError(error)
    return size.value
