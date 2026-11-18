"""OS-backed per-profile locks to prevent concurrent Chromium data-dir access.

One durable lock file per UUID. Lock files are intentionally never unlinked:
unlinking while a process holds a lock could create two independent locks.
"""
from __future__ import annotations

import os
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
