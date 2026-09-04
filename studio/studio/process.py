"""
Tiny cross-platform process-liveness helper.

"""
from __future__ import annotations

import os
import sys


def pid_alive(pid: int | None) -> bool:
    """Return True if a process with this PID currently exists."""
    if not pid or pid <= 0:
        return False

    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    return _pid_alive_unix(pid)


def _pid_alive_unix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # We don't own it but it exists.
        return True
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code),
            )
            if not ok:
                return False
            # 259 == STILL_ACTIVE
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False
