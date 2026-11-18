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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from .storage import Store

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


class ExtensionLibrary:
    def __init__(self, store: Store):
        self.store = store
        self.directory = store.base / "extensions"
        self.directory.mkdir(parents=True, exist_ok=True)
        with store._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS extension_packages (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
                permissions TEXT NOT NULL, host_permissions TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS profile_extensions (
                profile_id TEXT NOT NULL, extension_id TEXT NOT NULL,
                PRIMARY KEY (profile_id, extension_id),
                FOREIGN KEY (profile_id) REFERENCES profiles(id),
                FOREIGN KEY (extension_id) REFERENCES extension_packages(id))""")

    def list(self) -> list[ExtensionRecord]:
        with self.store._connect() as conn:
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
                with self.store._connect() as conn:
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
        profile = self.store.get(profile_id)
        extension_id = str(UUID(extension_id))
        if profile.browser != "chromium":
            raise ValueError("Unpacked extensions require bundled Playwright Chromium (not Chrome/Edge)")
        self._get(extension_id)
        with self.store._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO profile_extensions VALUES (?,?)", (profile_id, extension_id))

    def detach(self, profile_id: str, extension_id: str) -> None:
        profile_id, extension_id = str(UUID(profile_id)), str(UUID(extension_id))
        with self.store._connect() as conn:
            conn.execute("DELETE FROM profile_extensions WHERE profile_id=? AND extension_id=?", (profile_id, extension_id))

    def attached_ids(self, profile_id: str) -> list[str]:
        profile_id = str(UUID(profile_id))
        with self.store._connect() as conn:
            return [r[0] for r in conn.execute("SELECT extension_id FROM profile_extensions WHERE profile_id=? ORDER BY extension_id", (profile_id,))]

    def _get(self, extension_id: str) -> ExtensionRecord:
        entries = [r for r in self.list() if r.id == extension_id]
        if not entries:
            raise KeyError("Extension not found")
        return entries[0]

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

    def remove(self, extension_id: str) -> None:
        extension_id = str(UUID(extension_id))
        self._get(extension_id)
        with self.store._connect() as conn:
            conn.execute("DELETE FROM profile_extensions WHERE extension_id=?", (extension_id,))
            conn.execute("DELETE FROM extension_packages WHERE id=?", (extension_id,))
        shutil.rmtree(self.directory / extension_id)
