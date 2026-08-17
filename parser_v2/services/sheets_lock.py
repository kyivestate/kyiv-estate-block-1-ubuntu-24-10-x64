"""Process-safe exclusive lock for every Google Sheets write."""
from __future__ import annotations
import fcntl, json, os, time

LOCK_FILE = "/tmp/kyiv_estate_sheets_writer.lock"

class SheetsLock:
    """Exclusive writer lock released by the operating system if a process dies.

    Most best-effort writers keep the historical non-blocking behaviour.  Core
    Active-sheet mirrors can opt into a bounded wait so a coincident Telegraph
    or archive write cannot silently postpone a complete reconciliation.
    """
    def __init__(self, script_name: str, wait_seconds: float = 0, poll_seconds: float = 1):
        self.script_name, self._fd = script_name, None
        self.wait_seconds = max(0.0, float(wait_seconds))
        self.poll_seconds = max(0.1, float(poll_seconds))
    def __enter__(self):
        self._fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    owner = os.read(self._fd, 4096).decode("utf-8", "replace").strip()
                    os.close(self._fd); self._fd = None
                    raise RuntimeError(f"Sheets writer already running: {owner or 'unknown'}")
                time.sleep(min(self.poll_seconds, max(0.1, deadline - time.monotonic())))
        os.ftruncate(self._fd, 0)
        os.write(self._fd, json.dumps({"pid": os.getpid(), "script": self.script_name, "started": time.time()}).encode())
        os.fsync(self._fd)
        return self
    def __exit__(self, *_args):
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd); self._fd = None
