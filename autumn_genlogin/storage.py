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
    def __init__(self, base: Path | None = None):
        self.base = (base or data_home()).resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.browser_dir = self.base / "browser-data"
        self.browser_dir.mkdir(exist_ok=True)
        self.shot_dir = self.base / "screenshots"
        self.shot_dir.mkdir(exist_ok=True)
        self.db = self.base / "profiles.sqlite3"
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, group_name TEXT NOT NULL,
                tags TEXT NOT NULL, browser TEXT NOT NULL, start_url TEXT NOT NULL,
                locale TEXT NOT NULL, timezone_id TEXT NOT NULL, user_agent TEXT NOT NULL,
                viewport_width INTEGER NOT NULL, viewport_height INTEGER NOT NULL,
                proxy_scheme TEXT NOT NULL, proxy_host TEXT NOT NULL, proxy_port INTEGER NOT NULL,
                proxy_username TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def all(self) -> list[Profile]:
        with self._connect() as c:
            return [Profile(**dict(row)) for row in c.execute("SELECT * FROM profiles ORDER BY updated_at DESC, name")]

    def get(self, profile_id: str) -> Profile:
        profile_id = str(UUID(profile_id))
        with self._connect() as c:
            row = c.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            raise KeyError("Profile not found")
        return Profile(**dict(row))

    def save(self, profile: Profile) -> Profile:
        profile.id = str(UUID(profile.id))
        profile.validate()
        now = _utc()
        with self._connect() as c:
            current = c.execute("SELECT created_at FROM profiles WHERE id = ?", (profile.id,)).fetchone()
            profile.created_at = current[0] if current else (profile.created_at or now)
            profile.updated_at = now
            d = profile.public_dict()
            cols = ", ".join(d)
            placeholders = ", ".join("?" for _ in d)
            assignments = ", ".join(f"{k}=excluded.{k}" for k in d if k != "id")
            c.execute(f"INSERT INTO profiles ({cols}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {assignments}", tuple(d.values()))
        return profile

    def clone(self, profile_id: str) -> Profile:
        source = self.get(profile_id)
        d = source.public_dict()
        d.update(id=str(uuid4()), name=source.name + " (copy)", created_at="", updated_at="")
        return self.save(Profile(**d))

    def profile_path(self, profile_id: str) -> Path:
        # UUID validation blocks path traversal, even for imported metadata.
        return self.browser_dir / str(UUID(profile_id))

    def delete(self, profile_id: str) -> None:
        profile_id = str(UUID(profile_id))
        self.get(profile_id)
        # Hold the OS lock while removing data. Cross-process browser access
        # must not race with deletion. Never remove the lock file itself.
        with ProfileLease(self.base, profile_id):
            for directory in (self.profile_path(profile_id), self.shot_dir / profile_id):
                if directory.exists():
                    shutil.rmtree(directory)
            with self._connect() as c:
                c.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))

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
        for p in profiles:
            self.save(p)
        return len(profiles)

    def backup_database(self, target: Path) -> None:
        with self._connect() as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
