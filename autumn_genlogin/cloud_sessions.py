"""Manual end-to-end-encrypted, revision-checked session archive handoff.

Transfers **existing .aglb backups only**, never an open browser directory.
The .aglb content is already encrypted and the TeamHub document is encrypted
again with a separate shared team passphrase. The hub never receives raw
cookies/session content, no restore is automatic, and every download must
be manually restored as a *new* local profile.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
from uuid import UUID, uuid4

from .profile_backup import MAGIC, HEADER_SIZE, TAG_SIZE

PART_SIZE = 256 * 1024
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_PARTS = 64
MANIFEST_FORMAT = "AutumnGenLogin/session-handoff-manifest-1"
CHUNK_FORMAT = "AutumnGenLogin/session-handoff-chunk-1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _file_size(source: Path) -> int:
    if source.is_symlink() or not source.is_file():
        raise ValueError("Select a regular encrypted .aglb backup file")
    size = source.stat().st_size
    if size < HEADER_SIZE + TAG_SIZE or size > MAX_ARCHIVE:
        raise ValueError("Session handoff supports encrypted backups up to 16 MiB")
    with source.open("rb") as fd:
        if fd.read(len(MAGIC)) != MAGIC:
            raise ValueError("Input must be an AutumnGenLogin encrypted .aglb backup")
    return size


def _id(value: str) -> str:
    result = str(UUID(value))
    if value != result:
        raise ValueError("Use the canonical lowercase session handoff ID")
    return result


def _name(ident: str, index: int | None = None) -> str:
    ident = _id(ident)
    if index is None:
        return "session-" + ident + "-manifest"
    if type(index) is not int or not 0 <= index < MAX_PARTS:
        raise ValueError("Invalid encrypted archive part index")
    return f"session-{ident}-{index:02d}"


def _chunk_doc(ident: str, index: int, data: bytes) -> dict:
    return {"format":CHUNK_FORMAT,"session_id":ident,"index":index,
            "data":base64.b64encode(data).decode("ascii")}


class CloudSessionHandoff:
    """Operate only on a CloudClient already logged into a trusted TeamHub."""

    def __init__(self, client):
        self.client = client

    def upload(self, team_id: str, source: Path, team_passphrase: str) -> str:
        source = Path(source)
        size = _file_size(source)
        raw = source.read_bytes()
        if len(raw) != size:
            raise ValueError("Backup changed during upload preparation")
        # Intentionally no identity, URL, username, cookies or OS path metadata.
        ident = str(uuid4())
        checksum = hashlib.sha256(raw).hexdigest()
        total = (len(raw) + PART_SIZE - 1) // PART_SIZE
        if total < 1 or total > MAX_PARTS:
            raise ValueError("Too many archive parts")
        # Creation of the manifest is the final publish point. Failed prior
        # chunk uploads leave unreachable encrypted orphan documents, not
        # a visible/valid archive. No automatic retry or replay.
        for index in range(total):
            piece = raw[index*PART_SIZE:(index+1)*PART_SIZE]
            revision = self.client.push(
                team_id, _name(ident,index), 0,
                _chunk_doc(ident,index,piece), team_passphrase
            )
            if revision != 1:
                raise ValueError("Unexpected part revision")
        manifest = {"format":MANIFEST_FORMAT,"session_id":ident,
                    "size":size,"parts":total,"sha256":checksum}
        revision = self.client.push(team_id,_name(ident),0,manifest,team_passphrase)
        if revision != 1:
            raise ValueError("Unexpected manifest revision")
        return ident

    def download(self, team_id: str, session_id: str,
                 target: Path, team_passphrase: str) -> int:
        ident=_id(session_id)
        target=Path(target).expanduser()
        if target.exists() or target.is_symlink():
            raise FileExistsError("Refusing to overwrite an existing encrypted backup")
        if not target.parent.is_dir():
            raise FileNotFoundError("Backup destination directory does not exist")
        revision,manifest=self.client.pull(team_id,_name(ident),team_passphrase)
        if revision != 1 or not isinstance(manifest,dict) or set(manifest) != {
            "format","session_id","size","parts","sha256"
        } or manifest["format"] != MANIFEST_FORMAT or manifest["session_id"] != ident:
            raise ValueError("Archive manifest is missing or invalid")
        size,parts,digest=manifest["size"],manifest["parts"],manifest["sha256"]
        if type(size) is not int or not HEADER_SIZE+TAG_SIZE <= size <= MAX_ARCHIVE:
            raise ValueError("Remote archive size is invalid")
        if type(parts) is not int or not 1 <= parts <= MAX_PARTS:
            raise ValueError("Remote archive part count is invalid")
        if (size+PART_SIZE-1)//PART_SIZE != parts:
            raise ValueError("Remote archive size does not match part count")
        if not isinstance(digest,str) or not _SHA.fullmatch(digest):
            raise ValueError("Remote archive digest is invalid")
        chunks=[]
        for index in range(parts):
            revision,doc=self.client.pull(team_id,_name(ident,index),team_passphrase)
            if revision != 1 or not isinstance(doc,dict) or set(doc) != {
                "format","session_id","index","data"
            } or doc["format"] != CHUNK_FORMAT or doc["session_id"] != ident or doc["index"] != index:
                raise ValueError("Encrypted session archive part is missing or invalid")
            data=doc["data"]
            if not isinstance(data,str) or len(data)>PART_SIZE*2:
                raise ValueError("Invalid session part encoding")
            try:
                raw=base64.b64decode(data,validate=True)
            except (ValueError,base64.binascii.Error) as exc:
                raise ValueError("Invalid encrypted session part data") from exc
            expected = PART_SIZE if index < parts-1 else size - PART_SIZE*(parts-1)
            if len(raw)!=expected:
                raise ValueError("Remote session part length mismatch")
            chunks.append(raw)
        result=b"".join(chunks)
        if len(result)!=size or hashlib.sha256(result).hexdigest()!=digest:
            raise ValueError("Remote encrypted archive integrity verification failed")
        if not result.startswith(MAGIC):
            raise ValueError("Remote object is not a valid encrypted backup container")
        # Store only still-encrypted .aglb bytes; never decrypt or auto-import.
        # 'xb' reserves a brand-new path, preventing accidental overwrite.
        try:
            with target.open("xb") as destination:
                destination.write(result)
                destination.flush()
                os.fsync(destination.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return len(result)
