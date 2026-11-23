"""Opt-in local MV3 extension library for Playwright's bundled Chromium.

Only unpacked developer extensions (folder/ZIP) are supported. There is no
Chrome Web Store downloader, automatic extension updates or browser patching.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import zipfile
from contextlib import ExitStack
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from .storage import Store
from .locks import ProfileLease

MAX_FILES = 800
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_SINGLE_FILE = 8 * 1024 * 1024


@dataclass(frozen=True)
class ExtensionRecord:
    id: str
    name: str
    version: str
    permissions: tuple[str, ...]
    host_permissions: tuple[str, ...]


def _manifest(root: Path) -> dict:
    file = root / "manifest.json"
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 256 * 1024:
        raise ValueError("Extension must contain a regular manifest.json up to 256 KB")
    try:
        manifest = json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid extension manifest.json") from exc
    if not isinstance(manifest, dict) or manifest.get("manifest_version") != 3:
        raise ValueError("Only Chrome Manifest V3 developer extensions are supported")
    for key in ("name", "version"):
        if not isinstance(manifest.get(key), str) or not 1 <= len(manifest[key]) <= 140:
            raise ValueError(f"Invalid extension {key}")
    for key in ("permissions", "host_permissions"):
        values = manifest.get(key, [])
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(x, str) or len(x) > 400 for x in values):
            raise ValueError(f"Invalid extension {key}")
    return manifest


def _relative_path(value: str) -> Path:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError("Unsafe extension path")
    posix = PurePosixPath(value)
    if posix.is_absolute() or any(part in {".", ".."} for part in value.split("/")) or len(value) > 250 or ":" in value:
        raise ValueError("Unsafe extension path")
    return Path(*posix.parts)


def _check_staged(root: Path) -> dict:
    total, count = 0, 0
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError("Symbolic links are not allowed in extensions")
        if item.is_file():
            count += 1
            size = item.stat().st_size
            total += size
            if count > MAX_FILES or size > MAX_SINGLE_FILE or total > MAX_TOTAL_BYTES:
                raise ValueError("Extension exceeds safety size limits")
        elif not item.is_dir():
            raise ValueError("Unsupported filesystem entry in extension")
    return _manifest(root)


@dataclass(frozen=True)
class ExtensionUpgrade:
    id: str
    old_id: str
    new_id: str
    profile_ids: tuple[str, ...]
    status: str
    created_utc: str


class ExtensionLibrary:
    def __init__(self, store: Store):
        self.store = store
        self.directory = store.base / "extensions"
        self.directory.mkdir(parents=True, exist_ok=True)
        with store.transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS extension_packages (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
                permissions TEXT NOT NULL, host_permissions TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS profile_extensions (
                profile_id TEXT NOT NULL, extension_id TEXT NOT NULL,
                PRIMARY KEY (profile_id, extension_id),
                FOREIGN KEY (profile_id) REFERENCES profiles(id),
                FOREIGN KEY (extension_id) REFERENCES extension_packages(id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS extension_upgrades (
                id TEXT PRIMARY KEY,
                old_id TEXT NOT NULL,
                new_id TEXT NOT NULL,
                attached_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_utc TEXT NOT NULL
            )""")

    def list(self) -> list[ExtensionRecord]:
        with self.store.transaction() as conn:
            rows = conn.execute("SELECT * FROM extension_packages ORDER BY name, id").fetchall()
        return [ExtensionRecord(row["id"], row["name"], row["version"],
                                tuple(json.loads(row["permissions"])), tuple(json.loads(row["host_permissions"]))) for row in rows]

    def _install(self, root: Path, *, archive: bool) -> ExtensionRecord:
        extension_id = str(uuid4())
        target = self.directory / extension_id
        with tempfile.TemporaryDirectory(prefix="ext-stage-", dir=self.directory) as staging:
            staged = Path(staging) / "unpacked"
            staged.mkdir()
            if archive:
                with zipfile.ZipFile(root) as zipped:
                    infos = zipped.infolist()
                    if len(infos) > MAX_FILES + 100:
                        raise ValueError("Too many archive entries")
                    total = 0
                    for info in infos:
                        rel = _relative_path(info.filename.rstrip("/"))
                        if info.is_dir():
                            (staged / rel).mkdir(parents=True, exist_ok=True)
                            continue
                        mode = (info.external_attr >> 16) & 0xFFFF
                        if stat.S_ISLNK(mode):
                            raise ValueError("Archive symlinks are not allowed")
                        if info.file_size > MAX_SINGLE_FILE:
                            raise ValueError("Archive file is too large")
                        total += info.file_size
                        if total > MAX_TOTAL_BYTES:
                            raise ValueError("Archive exceeds limit")
                        dest = staged / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zipped.open(info) as src, dest.open("xb") as out:
                            shutil.copyfileobj(src, out, length=1024 * 1024)
            else:
                _check_staged(root)
                shutil.copytree(root, staged, dirs_exist_ok=True, symlinks=False)
            manifest = _check_staged(staged)
            record = ExtensionRecord(extension_id, manifest["name"], manifest["version"],
                                     tuple(manifest.get("permissions", [])), tuple(manifest.get("host_permissions", [])))
            os.replace(staged, target)
            try:
                with self.store.transaction() as conn:
                    conn.execute("INSERT INTO extension_packages VALUES (?,?,?,?,?)",
                                 (record.id, record.name, record.version, json.dumps(record.permissions), json.dumps(record.host_permissions)))
            except BaseException:
                shutil.rmtree(target, ignore_errors=True)
                raise
        return record

    def install_folder(self, source: Path) -> ExtensionRecord:
        if not source.is_dir() or source.is_symlink():
            raise ValueError("Choose a real directory containing manifest.json")
        return self._install(source, archive=False)

    def install_zip(self, source: Path) -> ExtensionRecord:
        if source.suffix.lower() != ".zip" or not zipfile.is_zipfile(source):
            raise ValueError("Choose a ZIP archive containing manifest.json at its root")
        return self._install(source, archive=True)

    def attach(self, profile_id: str, extension_id: str) -> None:
        profile_id = str(UUID(profile_id))
        profile = self.store.get(profile_id)
        extension_id = str(UUID(extension_id))
        if profile.browser != "chromium":
            raise ValueError("Unpacked extensions require bundled Playwright Chromium (not Chrome/Edge)")
        self._get(extension_id)
        with self.store.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO profile_extensions VALUES (?,?)", (profile_id, extension_id))

    def detach(self, profile_id: str, extension_id: str) -> None:
        profile_id, extension_id = str(UUID(profile_id)), str(UUID(extension_id))
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM profile_extensions WHERE profile_id=? AND extension_id=?", (profile_id, extension_id))

    def attached_ids(self, profile_id: str) -> list[str]:
        profile_id = str(UUID(profile_id))
        with self.store.transaction() as conn:
            return [r[0] for r in conn.execute("SELECT extension_id FROM profile_extensions WHERE profile_id=? ORDER BY extension_id", (profile_id,))]

    def _get(self, extension_id: str) -> ExtensionRecord:
        with self.store.transaction() as conn:
            row = conn.execute("SELECT * FROM extension_packages WHERE id=?", (str(UUID(extension_id)),)).fetchone()
        if row is None:
            raise KeyError("Extension not found")
        return ExtensionRecord(row["id"], row["name"], row["version"],
                               tuple(json.loads(row["permissions"])), tuple(json.loads(row["host_permissions"])))

    def paths_for(self, profile_id: str) -> list[Path]:
        profile = self.store.get(profile_id)
        ids = self.attached_ids(profile_id)
        if ids and profile.browser != "chromium":
            raise ValueError("Installed extensions require bundled Chromium")
        paths = []
        for extension_id in ids:
            self._get(extension_id)
            path = self.directory / extension_id
            _check_staged(path)
            paths.append(path.resolve(strict=True))
        return paths

    def list_upgrades(self) -> list[ExtensionUpgrade]:
        with self.store.transaction() as conn:
            rows = conn.execute("SELECT * FROM extension_upgrades ORDER BY rowid DESC").fetchall()
        return [ExtensionUpgrade(row["id"], row["old_id"], row["new_id"],
                                 tuple(json.loads(row["attached_json"])),
                                 row["status"], row["created_utc"]) for row in rows]

    def prepare_update(self, old_id: str, source: Path, *, archive: bool) -> ExtensionRecord:
        """Import a *new, inactive* package so the GUI can preview scope changes.

        A different name may be unrelated code. Only explicit user confirmation
        may subsequently migrate profile associations to the new package.
        """
        old = self._get(old_id)
        candidate = self.install_zip(source) if archive else self.install_folder(source)
        if candidate.name != old.name or candidate.version == old.version:
            self.remove(candidate.id)
            raise ValueError("Updated extension must keep its name and change its version")
        return candidate

    def apply_update(self, old_id: str, new_id: str) -> ExtensionUpgrade:
        """Atomically migrate attachments, preserving previous package for rollback.

        Every affected profile receives a cross-process lease. Never mutate
        extension files while any associated browser process is using them.
        """
        old, new = self._get(old_id), self._get(new_id)
        if old.id == new.id or old.name != new.name or old.version == new.version:
            raise ValueError("Incompatible extension update")
        with self.store.transaction() as conn:
            ids = [r[0] for r in conn.execute(
                "SELECT profile_id FROM profile_extensions WHERE extension_id=? ORDER BY profile_id",
                (old.id,))]
        upgrade_id = str(uuid4())
        with ExitStack() as leases:
            for pid in ids:
                leases.enter_context(ProfileLease(self.store.base, pid))
            with self.store.transaction() as conn:
                conn.execute("BEGIN IMMEDIATE")
                found = [r[0] for r in conn.execute(
                    "SELECT profile_id FROM profile_extensions WHERE extension_id=? ORDER BY profile_id",
                    (old.id,))]
                if found != ids:
                    raise RuntimeError("Extension attachments changed during update; retry")
                collisions = conn.execute(
                    "SELECT profile_id FROM profile_extensions WHERE extension_id=? "
                    "AND profile_id IN (SELECT profile_id FROM profile_extensions WHERE extension_id=?)",
                    (new.id, old.id)).fetchall()
                if collisions:
                    raise ValueError("New package is already attached to an affected profile")
                for pid in ids:
                    conn.execute("INSERT INTO profile_extensions VALUES (?,?)", (pid, new.id))
                    conn.execute("DELETE FROM profile_extensions WHERE profile_id=? AND extension_id=?",
                                 (pid,old.id))
                conn.execute("INSERT INTO extension_upgrades VALUES (?,?,?,?,?,?)",
                             (upgrade_id,old.id,new.id,json.dumps(ids),"applied",
                              datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return ExtensionUpgrade(upgrade_id,old.id,new.id,tuple(ids),"applied",
                                datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def rollback_update(self, upgrade_id: str) -> ExtensionUpgrade:
        upgrade_id = str(UUID(upgrade_id))
        with self.store.transaction() as conn:
            row = conn.execute("SELECT * FROM extension_upgrades WHERE id=?",(upgrade_id,)).fetchone()
        if row is None:
            raise KeyError("Extension update not found")
        if row["status"] != "applied":
            raise ValueError("This extension update is no longer active")
        ids = json.loads(row["attached_json"])
        old_id, new_id = row["old_id"], row["new_id"]
        self._get(old_id)
        self._get(new_id)
        with ExitStack() as leases:
            for pid in sorted(ids):
                leases.enter_context(ProfileLease(self.store.base, pid))
            with self.store.transaction() as conn:
                conn.execute("BEGIN IMMEDIATE")
                fresh = conn.execute("SELECT status FROM extension_upgrades WHERE id=?",
                                     (upgrade_id,)).fetchone()
                if fresh is None or fresh["status"] != "applied":
                    raise ValueError("Update already rolled back")
                for pid in ids:
                    links = {r[0] for r in conn.execute(
                        "SELECT extension_id FROM profile_extensions WHERE profile_id=?",(pid,))}
                    if new_id not in links or old_id in links:
                        raise RuntimeError("Profile extension associations changed; manual review required")
                for pid in ids:
                    conn.execute("INSERT INTO profile_extensions VALUES (?,?)",(pid,old_id))
                    conn.execute("DELETE FROM profile_extensions WHERE profile_id=? AND extension_id=?",
                                 (pid,new_id))
                conn.execute("UPDATE extension_upgrades SET status='rolled_back' WHERE id=?",
                             (upgrade_id,))
        return ExtensionUpgrade(upgrade_id,old_id,new_id,tuple(ids),"rolled_back",
                                row["created_utc"])

    def remove(self, extension_id: str) -> None:
        extension_id = str(UUID(extension_id))
        self._get(extension_id)
        with self.store.transaction() as conn:
            pending = conn.execute(
                "SELECT 1 FROM extension_upgrades WHERE status='applied' "
                "AND (old_id=? OR new_id=?) LIMIT 1",
                (extension_id,extension_id)).fetchone()
            if pending:
                raise ValueError("Rollback is still available; roll back or keep this package")
            conn.execute("DELETE FROM profile_extensions WHERE extension_id=?", (extension_id,))
            conn.execute("DELETE FROM extension_packages WHERE id=?", (extension_id,))
        shutil.rmtree(self.directory / extension_id)
