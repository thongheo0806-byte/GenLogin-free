"""OS-backed per-profile locks to prevent concurrent Chromium data-dir access.

One durable lock file per UUID. Lock files are intentionally never unlinked:
unlinking while a process holds a lock could create two independent locks.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from uuid import UUID


class ProfileBusyError(RuntimeError):
    """Another application instance is already using this profile."""


class ProfileLease:
    def __init__(self, home: Path, profile_id: str):
        self.path = Path(home) / "locks" / (str(UUID(profile_id)) + ".lock")
        self._file = None

    def __enter__(self) -> "ProfileLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                file.seek(0, os.SEEK_END)
                if file.tell() == 0:
                    file.write(b"\0")
                    file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            file.close()
            raise ProfileBusyError("Profile is already open in another process") from exc
        except BaseException:
            file.close()
            raise
        self._file = file
        return self

    def __exit__(self, exc_type, exc, tb):
        file = self._file
        self._file = None
        if file is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
            finally:
                file.close()


class AsyncProfileLease:
    """Own a ProfileLease entirely on one background thread.

    The thread performs both OS lock/unlock, including Windows msvcrt byte
    locking, and holds the lease until the parent signals release. A cancelled
    async acquire still signals release, even if the worker finishes acquiring
    after the cancellation. The shared Playwright event loop never touches
    blocking filesystem lock operations.
    """

    def __init__(self, home: Path, profile_id: str):
        import concurrent.futures
        import threading
        self.home, self.profile_id = Path(home), str(UUID(profile_id))
        self._ready = concurrent.futures.Future()
        self._done = concurrent.futures.Future()
        self._release = threading.Event()
        self._thread = None
        self._start_lock = threading.Lock()

    def _work(self):
        try:
            with ProfileLease(self.home, self.profile_id):
                if not self._ready.done():
                    self._ready.set_result(None)
                self._release.wait()
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            self._done.set_exception(exc)
        else:
            self._done.set_result(None)

    async def acquire(self):
        import asyncio
        with self._start_lock:
            if self._thread is not None:
                raise RuntimeError("Profile lease already started")
            self._thread = threading.Thread(
                target=self._work, daemon=True,
                name="autumn-profile-lock-" + self.profile_id[:8],
            )
            self._thread.start()
        try:
            await asyncio.wrap_future(self._ready)
        except BaseException:
            # A cancellation cannot abandon the worker holding a lock after
            # a delayed acquire. Let _work release from its owning thread.
            self._release.set()
            raise
        return self

    async def release(self):
        import asyncio
        self._release.set()
        thread = self._thread
        if thread is None:
            return
        # Await the worker's termination off-loop; this also reports a
        # Windows unlock exception instead of silently losing the lock.
        await asyncio.to_thread(thread.join)
        await asyncio.wrap_future(self._done)
