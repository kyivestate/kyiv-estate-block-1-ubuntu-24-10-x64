from __future__ import annotations
import fcntl
import os

def acquire_process_lock(name: str) -> int:
    path = f"/tmp/kyiv_estate_{name}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError(f"{name} already running")
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd
