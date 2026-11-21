"""Reviewed, declarative local miniapp catalog. Never executes imported code.

Miniapps are small reusable JSON workflow *drafts* with an immutable SHA-256
ID. Importing is not running. A GUI preview and explicit user confirmation
are required before a workflow is loaded into the existing validated editor.
No remote marketplace, arbitrary Python/JS, external package installs or
automatic credential copying.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .models import validated_steps

FORMAT = "AutumnGenLogin/miniapp-1"
MAX_PACKAGE_BYTES = 65536
MAX_APPS = 100
MAX_STEPS = 50
_ALLOWED_CATEGORIES = frozenset({"QA","Productivity","Research","Utilities"})
_VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z")
_IDENT = re.compile(r"[0-9a-f]{64}\Z")


def _field(name: str, value: object, max_length: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= max_length:
        raise ValueError("Invalid miniapp " + name)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Miniapp text fields may not contain control characters")
    return value.strip()


def validate_miniapp(source: object) -> dict:
    if not isinstance(source, dict) or set(source) != {
        "format","name","version","description","category","workflow"
    }:
        raise ValueError("Miniapp must have the exact reviewed manifest fields")
    if source["format"] != FORMAT:
        raise ValueError("Unsupported miniapp format")
    name = _field("name",source["name"],80)
    version = source["version"]
    if not isinstance(version,str) or not _VERSION.fullmatch(version):
        raise ValueError("Miniapp version must be MAJOR.MINOR.PATCH")
    category = source["category"]
    if not isinstance(category,str) or category not in _ALLOWED_CATEGORIES:
        raise ValueError("Unknown miniapp category")
    desc = _field("description",source["description"],300)
    actions = validated_steps(source["workflow"])
    if len(actions) > MAX_STEPS:
        raise ValueError("Miniapp workflows have a 50-step maximum")
    for step in actions:
        if step["action"] == "fill" and step["text"] != "":
            raise ValueError("Miniapps cannot pre-fill private or user-supplied text")
        if step["action"] == "select_option" and step["value"] != "REVIEW_OPTION":
            raise ValueError("Miniapps must leave select values as REVIEW_OPTION")
        if step["action"] == "goto":
            parsed = urlsplit(step["url"])
            if parsed.query or parsed.fragment:
                raise ValueError("Miniapp navigation cannot include URL query or fragments")
            if parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port is not None):
                raise ValueError("Miniapp navigation must use HTTPS or literal loopback HTTP")
    return {"format":FORMAT,"name":name,"version":version,
            "description":desc,"category":category,"workflow":deepcopy(actions)}


def scope_of(manifest: dict) -> tuple[str,...]:
    urls=set()
    for action in manifest["workflow"]:
        if action["action"] == "goto":
            value=urlsplit(action["url"])
            urls.add(value.scheme+"://"+value.netloc)
    return tuple(sorted(urls))


@dataclass(frozen=True)
class MiniAppRecord:
    id: str
    name: str
    version: str
    category: str
    description: str
    steps: int
    origins: tuple[str,...]
    installed_at_utc: str


class MiniAppLibrary:
    def __init__(self,store):
        self.store=store
        with store._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS miniapps (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                manifest TEXT NOT NULL,
                installed_at_utc TEXT NOT NULL,
                UNIQUE(name,version)
            )""")

    def install_json(self, source: Path) -> MiniAppRecord:
        source=Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError("Choose an ordinary JSON miniapp file")
        if source.stat().st_size > MAX_PACKAGE_BYTES:
            raise ValueError("Miniapp package exceeds 64 KiB")
        try:
            doc=json.loads(source.read_text(encoding="utf-8"))
        except (UnicodeError,ValueError) as exc:
            raise ValueError("Invalid UTF-8 JSON miniapp") from exc
        return self.install(doc)

    def install(self, manifest: object) -> MiniAppRecord:
        checked=validate_miniapp(manifest)
        raw=json.dumps(checked,separators=(",",":"),sort_keys=True,ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_PACKAGE_BYTES:
            raise ValueError("Miniapp manifest exceeds 64 KiB")
        ident=hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now=datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists=conn.execute("SELECT id FROM miniapps WHERE name=? AND version=?",
                                (checked["name"],checked["version"])).fetchone()
            if exists:
                if exists["id"] != ident:
                    raise ValueError("An incompatible miniapp already uses this name/version")
            elif conn.execute("SELECT COUNT(*) FROM miniapps").fetchone()[0] >= MAX_APPS:
                raise ValueError("Maximum 100 installed miniapp templates")
            else:
                conn.execute("INSERT INTO miniapps VALUES(?,?,?,?,?,?,?)",
                             (ident,checked["name"],checked["version"],
                              checked["category"],checked["description"],raw,now))
        return self._record(ident)

    def _record(self, ident: str) -> MiniAppRecord:
        if not isinstance(ident,str) or not _IDENT.fullmatch(ident):
            raise ValueError("Invalid miniapp ID")
        with self.store._connect() as conn:
            row=conn.execute("SELECT * FROM miniapps WHERE id=?",(ident,)).fetchone()
        if row is None:
            raise KeyError("Miniapp not found")
        manifest=validate_miniapp(json.loads(row["manifest"]))
        canonical=json.dumps(manifest,sort_keys=True,separators=(",",":"),ensure_ascii=False)
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != ident:
            raise ValueError("Stored miniapp manifest integrity check failed")
        return MiniAppRecord(ident,manifest["name"],manifest["version"],
                             manifest["category"],manifest["description"],
                             len(manifest["workflow"]),scope_of(manifest),
                             row["installed_at_utc"])

    def list(self) -> list[MiniAppRecord]:
        with self.store._connect() as conn:
            ids=[r[0] for r in conn.execute(
                "SELECT id FROM miniapps ORDER BY name,version")]
        return [self._record(ident) for ident in ids]

    def get(self, ident: str) -> dict:
        record=self._record(ident)
        with self.store._connect() as conn:
            row=conn.execute("SELECT manifest FROM miniapps WHERE id=?",(record.id,)).fetchone()
        return validate_miniapp(json.loads(row["manifest"]))

    def remove(self, ident: str) -> None:
        self._record(ident)
        with self.store._connect() as conn:
            conn.execute("DELETE FROM miniapps WHERE id=?",(ident,))
