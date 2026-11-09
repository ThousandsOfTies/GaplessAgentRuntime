"""Bounded UTF-8 process transport with operation-owned process cleanup."""

import os
import signal
import subprocess
import threading
import time

from scripts.gar_lib.core.errors import GarDomainError


def _windows_job():
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("times", ctypes.c_int64 * 2),
            ("flags", wintypes.DWORD),
            ("working", ctypes.c_size_t * 2),
            ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6), ("memory", ctypes.c_size_t * 4)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())

    def attach(process):
        if not kernel.AssignProcessToJobObject(job, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        nt = ctypes.WinDLL("ntdll")
        nt.NtResumeProcess.argtypes = [wintypes.HANDLE]
        if nt.NtResumeProcess(int(process._handle)) != 0:
            raise OSError("Cannot resume operation")

    return attach, lambda: kernel.CloseHandle(job)


def run_bounded(command, *, cwd, env, timeout, limit=1048576):
    process = None
    close_job = None
    readers = []
    overflow = threading.Event()
    buffers = [bytearray(), bytearray()]

    def read(stream, buffer):
        while chunk := stream.read(8192):
            if len(buffer) + len(chunk) > limit:
                overflow.set()
                return
            buffer.extend(chunk)

    try:
        options = {"start_new_session": True}
        if os.name == "nt":
            attach, close_job = _windows_job()
            options = {"creationflags": 4}  # CREATE_SUSPENDED: assign job before any child can spawn.
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
        if os.name == "nt":
            attach(process)
        for stream, buffer in zip((process.stdout, process.stderr), buffers, strict=False):
            thread = threading.Thread(target=read, args=(stream, buffer), daemon=True)
            thread.start()
            readers.append(thread)
        deadline = time.monotonic() + timeout
        while process.poll() is None or any(thread.is_alive() for thread in readers):
            if overflow.is_set():
                raise GarDomainError("Product操作の出力が上限を超えました")
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("Product operation", timeout)
            time.sleep(0.01)
        if overflow.is_set():
            raise GarDomainError("Product操作の出力が上限を超えました")
        try:
            output = buffers[0].decode("utf-8", errors="strict").replace("\r\n", "\n")
        except UnicodeError as error:
            raise GarDomainError("Product操作の出力がUTF-8ではありません") from error
        return subprocess.CompletedProcess(command, process.returncode, output, "")
    finally:
        if close_job is not None:
            close_job()
        if process is not None:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait()
            for thread in readers:
                thread.join(timeout=2)
            process.stdout.close()
            process.stderr.close()
