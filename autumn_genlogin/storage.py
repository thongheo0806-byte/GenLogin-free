"""SQLite metadata and isolated user-data directory management."""
from __future__ import annotations

import json
from contextlib import contextmanager, closing
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from .models import Profile
from .locks import ProfileLease


def data_home() -> Path:
    custom = os.environ.get("AUTUMN_GENLOGIN_HOME")
    if custom:
        return Path(custom).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AutumnGenLogin"
    return Path.home() / ".autumn-genlogin"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, base: Path | None = None, *, initialize: bool = True):
        self.base = (base or data_home()).resolve()
        self.browser_dir = self.base / "browser-data"
        self.shot_dir = self.base / "screenshots"
        self.db = self.base / "profiles.sqlite3"
        # Diagnostics must be able to inspect a corrupt catalog without trying
        # to initialize it (and must not create missing directories).
        if not initialize:
            return
        self.base.mkdir(parents=True, exist_ok=True)
        self.browser_dir.mkdir(exist_ok=True)
        self.shot_dir.mkdir(exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database was created by a newer AutumnGenLogin version")
            conn.execute("""CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, group_name TEXT NOT NULL,
                tags TEXT NOT NULL, browser TEXT NOT NULL, start_url TEXT NOT NULL,
                locale TEXT NOT NULL, timezone_id TEXT NOT NULL, user_agent TEXT NOT NULL,
                viewport_width INTEGER NOT NULL, viewport_height INTEGER NOT NULL,
                proxy_scheme TEXT NOT NULL, proxy_host TEXT NOT NULL, proxy_port INTEGER NOT NULL,
                proxy_username TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            if version == 0:
                conn.execute("PRAGMA user_version=1")

    @contextmanager
    def _connect(self, *, readonly: bool = False):
        conn = (sqlite3.connect(self.db.as_uri() + "?mode=ro", uri=True, timeout=10)
                if readonly else sqlite3.connect(self.db, timeout=10))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def all(self, *, readonly: bool = False) -> list[Profile]:
        with self._connect(readonly=readonly) as c:
            return [Profile(**dict(row)) for row in c.execute("SELECT * FROM profiles ORDER BY updated_at DESC, name")]

    def get(self, profile_id: str) -> Profile:
        profile_id = str(UUID(profile_id))
        with self._connect() as c:
            row = c.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            raise KeyError("Profile not found")
        return Profile(**dict(row))

    def _save_with_connection(self, conn: sqlite3.Connection, profile: Profile) -> Profile:
        profile.id = str(UUID(profile.id))
        profile.validate()
        now = _utc()
        current = conn.execute("SELECT created_at FROM profiles WHERE id = ?", (profile.id,)).fetchone()
        profile.created_at = current[0] if current else (profile.created_at or now)
        profile.updated_at = now
        d = profile.public_dict()
        cols = ", ".join(d)
        placeholders = ", ".join("?" for _ in d)
        assignments = ", ".join(f"{k}=excluded.{k}" for k in d if k != "id")
        conn.execute(f"INSERT INTO profiles ({cols}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {assignments}", tuple(d.values()))
        return profile

    def save(self, profile: Profile) -> Profile:
        with self._connect() as c:
            return self._save_with_connection(c, profile)

    def clone(self, profile_id: str) -> Profile:
        source = self.get(profile_id)
        d = source.public_dict()
        d.update(id=str(uuid4()), name=source.name + " (copy)", created_at="", updated_at="")
        return self.save(Profile(**d))

    def profile_path(self, profile_id: str) -> Path:
        # UUID validation blocks path traversal, even for imported metadata.
        return self.browser_dir / str(UUID(profile_id))

    def delete(self, profile_id: str) -> list[str]:
        """Delete metadata transactionally with browser-data moves.

        Quarantine folders with same-volume atomic renames before committing DB.
        If the DB fails, restore folders and leave credentials untouched (callers
        must clear the vault secret only *after* this function succeeds).
        Cleanup failures after commit are surfaced as orphan warnings; they never
        revive a deleted profile or leak the vault password.
        """
        profile_id = str(UUID(profile_id))
        self.get(profile_id)
        staged: list[tuple[Path, Path]] = []
        with ProfileLease(self.base, profile_id):
            self.get(profile_id)  # prevent stale pre-lock assumptions
            stage = self.base / "delete-staging"
            for directory in (self.profile_path(profile_id), self.shot_dir / profile_id):
                if not directory.exists():
                    continue
                try:
                    stage.mkdir(exist_ok=True)
                    target = stage / f"{uuid4()}-{directory.name}"
                    os.replace(directory, target)
                    staged.append((directory, target))
                except BaseException:
                    for original, moved in reversed(staged):
                        os.replace(moved, original)
                    raise
            try:
                with self._connect() as c:
                    exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_extensions'").fetchone()
                    if exists:
                        c.execute("DELETE FROM profile_extensions WHERE profile_id = ?", (profile_id,))
                    result = c.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
                    if result.rowcount != 1:
                        raise KeyError("Profile not found")
            except BaseException:
                for original, moved in reversed(staged):
                    os.replace(moved, original)
                raise
        leftovers = []
        for _original, moved in staged:
            try:
                shutil.rmtree(moved)
            except OSError:
                leftovers.append(str(moved))
        return leftovers

    def export_metadata(self, target: Path) -> int:
        profiles = [p.public_dict() for p in self.all()]
        # Deliberately excludes proxy passwords, cookies, history, browser databases.
        target.write_text(json.dumps({"format": "AutumnGenLogin/1", "profiles": profiles}, indent=2, ensure_ascii=False), encoding="utf-8")
        return len(profiles)

    def import_metadata(self, source: Path) -> int:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != "AutumnGenLogin/1" or not isinstance(payload.get("profiles"), list):
            raise ValueError("Invalid metadata export")
        if len(payload["profiles"]) > 2000:
            raise ValueError("Import too large")
        profiles = []
        for d in payload["profiles"]:
            if not isinstance(d, dict):
                raise ValueError("Invalid profile")
            p = Profile(**d)
            p.id = str(uuid4())  # Never overwrite an existing profile from import.
            p.created_at = p.updated_at = ""
            p.validate()
            profiles.append(p)
        with self._connect() as conn:
            for p in profiles:
                self._save_with_connection(conn, p)
        return len(profiles)

    def backup_database(self, target: Path) -> None:
        with self._connect() as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
