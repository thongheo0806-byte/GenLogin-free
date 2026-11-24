"""Reviewed, declarative local Miniapp catalog with optional pinned signatures.

Import never runs a workflow. An Ed25519 signature proves possession of a
manually trusted key, not the publisher's real-world identity or suitability
of a workflow. Unsigned imports remain visibly unverified legacy drafts.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .models import validated_steps
from .miniapp_signatures import (
    SIGNED_FORMAT, publisher_fingerprint, verify_signed_package,
)

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
    signature_status: str = "unsigned"
    publisher_fingerprint: str = ""


class MiniAppLibrary:
    def __init__(self,store):
        self.store=store
        with store.transaction() as conn:
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
            # Additive tables preserve older local catalog databases.
            conn.execute("""CREATE TABLE IF NOT EXISTS miniapp_publishers (
                fingerprint TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                public_key TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS miniapp_attestations (
                miniapp_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                public_key TEXT NOT NULL,
                signature TEXT NOT NULL,
                FOREIGN KEY(miniapp_id) REFERENCES miniapps(id) ON DELETE CASCADE
            )""")
            # Publisher identity survives uninstall, unlike per-package attestations.
            conn.execute("""CREATE TABLE IF NOT EXISTS miniapp_name_pins (
                name TEXT PRIMARY KEY, fingerprint TEXT NOT NULL
            )""")
            conn.execute(
                "INSERT OR IGNORE INTO miniapp_name_pins(name,fingerprint) "
                "SELECT m.name,a.fingerprint FROM miniapp_attestations a "
                "JOIN miniapps m ON m.id=a.miniapp_id ORDER BY m.name"
            )

    def trust_publisher(self, label: str, public_key: str) -> str:
        """User explicitly pins a 32-byte Ed25519 public key after review."""
        label=_field("publisher label",label,80)
        fingerprint=publisher_fingerprint(public_key)
        with self.store.write_transaction() as conn:
            row=conn.execute("SELECT public_key FROM miniapp_publishers WHERE fingerprint=?",
                             (fingerprint,)).fetchone()
            if row is not None and row["public_key"]!=public_key:
                raise ValueError("Publisher key fingerprint conflict")
            if row is None:
                if conn.execute("SELECT COUNT(*) FROM miniapp_publishers").fetchone()[0]>=100:
                    raise ValueError("Maximum 100 trusted Miniapp signing keys")
                conn.execute("INSERT INTO miniapp_publishers VALUES(?,?,?)",
                             (fingerprint,label,public_key))
        return fingerprint

    def list_publishers(self) -> list[dict]:
        with self.store.transaction() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT fingerprint,label,public_key FROM miniapp_publishers "
                "ORDER BY label,fingerprint")]

    def untrust_publisher(self, fingerprint: str) -> None:
        if not isinstance(fingerprint,str) or not _IDENT.fullmatch(fingerprint):
            raise ValueError("Invalid publisher fingerprint")
        with self.store.transaction() as conn:
            result=conn.execute(
                "DELETE FROM miniapp_publishers WHERE fingerprint=?",(fingerprint,))
            if result.rowcount!=1:
                raise KeyError("Trusted Miniapp publisher key not found")

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
        if isinstance(doc,dict) and doc.get("format")==SIGNED_FORMAT:
            return self.install_signed(doc)
        return self.install(doc)

    def install(self, manifest: object) -> MiniAppRecord:
        return self._install_checked(validate_miniapp(manifest))

    def install_signed(self, package: object) -> MiniAppRecord:
        manifest,fingerprint,public_key,signature=verify_signed_package(package)
        if len(json.dumps(package,ensure_ascii=False).encode("utf-8"))>MAX_PACKAGE_BYTES:
            raise ValueError("Signed Miniapp package exceeds 64 KiB")
        # Verifying a signature alone never implicitly trusts its key.
        return self._install_checked(manifest,(fingerprint,public_key,signature))

    def _install_checked(self, checked: dict, signer: tuple | None = None) -> MiniAppRecord:
        raw=json.dumps(checked,separators=(",",":"),sort_keys=True,ensure_ascii=False)
        if len(raw.encode("utf-8"))>MAX_PACKAGE_BYTES:
            raise ValueError("Miniapp manifest exceeds 64 KiB")
        ident=hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now=datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.store.write_transaction() as conn:
            existing_signature=None
            pin=conn.execute(
                "SELECT fingerprint FROM miniapp_name_pins WHERE name=?",
                (checked["name"],)).fetchone()
            if signer is None and pin is not None:
                # Existing identical signed package is an idempotent import.
                # No other unsigned version can borrow this publisher's name.
                signed_ident=conn.execute(
                    "SELECT 1 FROM miniapp_attestations WHERE miniapp_id=? "
                    "AND fingerprint=?", (ident,pin["fingerprint"])).fetchone()
                if signed_ident is None:
                    raise ValueError("Miniapp name is pinned to a signed publisher; unsigned updates are refused")
            if signer is not None:
                fingerprint,public_key,signature=signer
                if pin is not None and pin["fingerprint"]!=fingerprint:
                    raise ValueError("Miniapp name is already pinned to another publisher key")
                trusted=conn.execute(
                    "SELECT public_key FROM miniapp_publishers WHERE fingerprint=?",
                    (fingerprint,)).fetchone()
                if trusted is None or trusted["public_key"]!=public_key:
                    raise ValueError("Miniapp signing key is not explicitly trusted")
                prior=conn.execute(
                    "SELECT DISTINCT a.fingerprint FROM miniapp_attestations a "
                    "JOIN miniapps m ON m.id=a.miniapp_id WHERE m.name=?",
                    (checked["name"],)).fetchall()
                if any(row["fingerprint"]!=fingerprint for row in prior):
                    raise ValueError("Miniapp name is already pinned to another publisher key")
                existing_signature=conn.execute(
                    "SELECT fingerprint,public_key,signature FROM miniapp_attestations "
                    "WHERE miniapp_id=?",(ident,)).fetchone()
                if existing_signature is not None and (
                    dict(existing_signature) != {"fingerprint":fingerprint,
                                                 "public_key":public_key,
                                                 "signature":signature}
                ):
                    raise ValueError("Miniapp signature identity conflict")
            exists=conn.execute("SELECT id FROM miniapps WHERE name=? AND version=?",
                                (checked["name"],checked["version"])).fetchone()
            if exists:
                if exists["id"]!=ident:
                    raise ValueError("An incompatible miniapp already uses this name/version")
            elif conn.execute("SELECT COUNT(*) FROM miniapps").fetchone()[0]>=MAX_APPS:
                raise ValueError("Maximum 100 installed miniapp templates")
            else:
                conn.execute("INSERT INTO miniapps VALUES(?,?,?,?,?,?,?)",
                             (ident,checked["name"],checked["version"],
                              checked["category"],checked["description"],raw,now))
            if signer is not None and existing_signature is None:
                conn.execute("INSERT INTO miniapp_attestations VALUES(?,?,?,?)",
                             (ident,fingerprint,public_key,signature))
            if signer is not None and pin is None:
                conn.execute("INSERT INTO miniapp_name_pins(name,fingerprint) VALUES(?,?)",
                             (checked["name"],fingerprint))
        return self._record(ident)

    def _record(self, ident: str) -> MiniAppRecord:
        if not isinstance(ident,str) or not _IDENT.fullmatch(ident):
            raise ValueError("Invalid miniapp ID")
        with self.store.transaction() as conn:
            row=conn.execute("SELECT * FROM miniapps WHERE id=?",(ident,)).fetchone()
            if row is None:
                raise KeyError("Miniapp not found")
            manifest=validate_miniapp(json.loads(row["manifest"]))
            canonical=json.dumps(manifest,sort_keys=True,separators=(",",":"),ensure_ascii=False)
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest()!=ident:
                raise ValueError("Stored miniapp manifest integrity check failed")
            status="unsigned"
            fingerprint=""
            attestation=conn.execute(
                "SELECT fingerprint,public_key,signature FROM miniapp_attestations "
                "WHERE miniapp_id=?",(ident,)).fetchone()
            if attestation is not None:
                fingerprint=attestation["fingerprint"]
                candidate={"format":SIGNED_FORMAT,"manifest":manifest,
                           "public_key":attestation["public_key"],
                           "signature":attestation["signature"]}
                _,verified,_,_=verify_signed_package(candidate)
                if verified!=fingerprint:
                    raise ValueError("Miniapp signature trust metadata was changed")
                trusted=conn.execute(
                    "SELECT public_key FROM miniapp_publishers WHERE fingerprint=?",
                    (fingerprint,)).fetchone()
                status=("trusted" if trusted is not None
                        and trusted["public_key"]==attestation["public_key"]
                        else "untrusted")
            return MiniAppRecord(ident,manifest["name"],manifest["version"],
                                 manifest["category"],manifest["description"],
                                 len(manifest["workflow"]),scope_of(manifest),
                                 row["installed_at_utc"],status,fingerprint)

    def list(self) -> list[MiniAppRecord]:
        # A bad local row is visible as invalid, but cannot hide healthy apps.
        with self.store.transaction() as conn:
            rows=conn.execute(
                "SELECT id,installed_at_utc FROM miniapps ORDER BY name,version"
            ).fetchall()
        result=[]
        for row in rows:
            try:
                result.append(self._record(row["id"]))
            except (ValueError, TypeError, KeyError, UnicodeError):
                result.append(MiniAppRecord(
                    id=row["id"], name="[Invalid stored Miniapp]", version="?",
                    category="QA", description="Stored manifest or signature failed validation",
                    steps=0, origins=(), installed_at_utc=row["installed_at_utc"],
                    signature_status="invalid",
                ))
        return result

    def get(self, ident: str) -> dict:
        record=self._record(ident)
        # Even direct callers must not bypass local key revocation.
        # Unsigned legacy drafts still require separate human UI review.
        if record.signature_status=="untrusted":
            raise ValueError("Signed Miniapp key is no longer locally trusted")
        with self.store.transaction() as conn:
            row=conn.execute("SELECT manifest FROM miniapps WHERE id=?",(record.id,)).fetchone()
        return validate_miniapp(json.loads(row["manifest"]))

    def remove(self, ident: str) -> None:
        # Permit deliberate cleanup of corrupt entries without loading them.
        if not isinstance(ident,str) or not _IDENT.fullmatch(ident):
            raise ValueError("Invalid miniapp ID")
        with self.store.transaction() as conn:
            removed=conn.execute("DELETE FROM miniapps WHERE id=?",(ident,))
            if removed.rowcount!=1:
                raise KeyError("Miniapp not found")
