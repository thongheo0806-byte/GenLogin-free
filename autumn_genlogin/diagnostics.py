"""Read-only, offline health checks for browser profile storage.

No requests to third parties, fingerprint alterations or credentials are used.
The only metadata consumed is the local SQLite profile catalog.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import closing
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from .storage import Store


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # pass, warn, fail
    detail: str


def audit_store(store: Store) -> dict:
    checks: list[Check] = []

    def add(name: str, status: str, detail: str):
        checks.append(Check(name, status, detail))

    try:
        with closing(sqlite3.connect(store.db.as_uri() + "?mode=ro", uri=True)) as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
        add("database_integrity", "pass" if result == "ok" else "fail", "SQLite quick_check: " + str(result)[:120])
    except (OSError, sqlite3.Error) as exc:
        add("database_integrity", "fail", type(exc).__name__ + " while checking SQLite")

    try:
        with tempfile.TemporaryFile(dir=store.base) as f:
            f.write(b"ok")
            f.flush()
        add("storage_write", "pass", "Local data directory writable")
    except OSError as exc:
        add("storage_write", "fail", type(exc).__name__ + ": data directory not writable")

    try:
        free = shutil.disk_usage(store.base).free
        add("disk_space", "warn" if free < 250 * 1024 * 1024 else "pass",
            f"{free // (1024 * 1024)} MiB free on data volume")
    except OSError:
        add("disk_space", "warn", "Free disk space unavailable")

    try:
        profiles = store.all(readonly=True)
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        add("profile_catalog", "fail", type(exc).__name__ + ": cannot read profile catalog")
        profiles = []

    invalid = 0
    for profile in profiles:
        try:
            profile.validate()
        except (ValueError, TypeError):
            invalid += 1
    add("profile_validation", "fail" if invalid else "pass",
        f"{len(profiles)} profiles checked; {invalid} invalid")

    known = {profile.id for profile in profiles}
    orphans = 0
    try:
        for path in store.browser_dir.iterdir():
            if path.is_dir():
                try:
                    uuid = str(UUID(path.name))
                except ValueError:
                    continue
                if uuid not in known:
                    orphans += 1
    except OSError:
        add("orphaned_profile_data", "warn", "Browser directory inaccessible")
    else:
        add("orphaned_profile_data", "warn" if orphans else "pass",
            f"{orphans} unreferenced browser data directories; no files removed")

    # Incomplete cleanup from a successful logical deletion may leave quarantined
    # directories. Report them instead of silently erasing user data.
    staging = store.base / "delete-staging"
    try:
        leftovers = sum(1 for path in staging.iterdir() if path.is_dir()) if staging.exists() else 0
        add("pending_deletion_cleanup", "warn" if leftovers else "pass",
            f"{leftovers} staged data directories pending cleanup")
    except OSError:
        add("pending_deletion_cleanup", "warn", "Deletion staging directory inaccessible")

    add("privacy_scope", "pass", "Offline checks only; no credentials, browser cookies or browsing history read")
    return {
        "schema": "AutumnGenLogin/diagnostics/1",
        "checks": [asdict(check) for check in checks],
        "summary": {
            "passed": sum(c.status == "pass" for c in checks),
            "warnings": sum(c.status == "warn" for c in checks),
            "failed": sum(c.status == "fail" for c in checks),
        },
    }
