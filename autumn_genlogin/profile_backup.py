"""Opt-in encrypted local profile-session backup and safe restore.

A self-contained .aglb file contains AES-256-GCM encrypted TAR bytes.
Only encrypted bytes reach the exported backup file. Browser sessions are
sensitive, so plaintext metadata exports are deliberately not used here.
No OS vault passwords, local extension packages or API tokens are included.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import tarfile
from uuid import uuid4

from .locks import ProfileLease
from .models import Profile

# v1 is retained for legacy restore only. All new exports use v2.
MAGIC = b"AUTUMN-LOCAL-PROFILE-BACKUP-1\n"
MAGIC_V2 = b"AUTUMN-LOCAL-PROFILE-BACKUP-2\n"
SALT_SIZE, NONCE_SIZE, TAG_SIZE = 16, 12, 16
KDF_PARAMS_V2 = bytes((17, 8, 1))  # log2(N), r, p; scrypt N=131072
HEADER_SIZE = len(MAGIC) + SALT_SIZE + NONCE_SIZE
HEADER_SIZE_V2 = len(MAGIC_V2) + len(KDF_PARAMS_V2) + SALT_SIZE + NONCE_SIZE
FORMAT = "AutumnGenLogin/encrypted-profile-1"
MAX_FILES = 12000
MAX_FILE_SIZE = 256 * 1024 * 1024
MAX_TOTAL_SIZE = 1024 * 1024 * 1024
MAX_ENCRYPTED_SIZE = 1200 * 1024 * 1024
MAX_METADATA = 65536
CHUNK = 1024 * 1024
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                     *[f"LPT{i}" for i in range(1, 10)]}


def _passphrase(value: str) -> None:
    if not isinstance(value, str) or not 12 <= len(value) <= 1024:
        raise ValueError("Profile backup needs a passphrase of 12-1024 characters")


def _key(passphrase: str, salt: bytes, *, log_n: int = 14,
         r: int = 8, p: int = 1) -> bytes:
    # Never derive with unbounded attacker-controlled KDF parameters. Older
    # backups use v1/14; new ones pin v2/17 in an authenticated header.
    if (log_n, r, p) not in {(14, 8, 1), (17, 8, 1)}:
        raise ValueError("Unsupported backup key derivation parameters")
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt,
                          n=1 << log_n, r=r, p=p, dklen=32,
                          maxmem=256 * 1024 * 1024)


def _name(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or len(value) > 1024 or "\\" in value or "\x00" in value or ":" in value:
        raise ValueError("Unsafe archive path")
    if not value or value.startswith("/") or value.endswith("/") or "//" in value:
        raise ValueError("Unsafe archive path")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {".", ".."} or part.endswith((" ", ".")) or
                        any(ord(ch) < 32 for ch in part) or
                        part.split(".")[0].upper() in _WINDOWS_RESERVED for part in parts):
        raise ValueError("Unsafe archive path")
    if "/".join(parts) != value:
        raise ValueError("Noncanonical archive path")
    return parts


def _real_files(root: Path):
    if root.is_symlink() or _reparse(root):
        raise ValueError("Browser directory is a link or reparse point")
    if not root.exists():
        return []
    if not root.is_dir():
        raise ValueError("Browser data path is not a directory")
    result = []
    size = 0
    for item in root.rglob("*"):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or _reparse(item):
            raise ValueError("Linked browser data cannot be archived safely")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Non-regular browser data file")
        if info.st_size > MAX_FILE_SIZE:
            raise ValueError("Individual browser file exceeds backup limit")
        rel = item.relative_to(root).as_posix()
        _name("browser/" + rel)
        size += info.st_size
        if size > MAX_TOTAL_SIZE or len(result) >= MAX_FILES:
            raise ValueError("Browser profile exceeds bounded backup limits")
        result.append((item, rel, info.st_size))
    return sorted(result, key=lambda row: row[1])


def _reparse(path: Path) -> bool:
    value = getattr(path.lstat(), "st_file_attributes", 0) if path.exists() or path.is_symlink() else 0
    return bool(value & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


class _EncryptedWriter:
    def __init__(self, file, encryptor):
        self.file, self.encryptor = file, encryptor

    def write(self, chunk: bytes) -> int:
        self.file.write(self.encryptor.update(chunk))
        return len(chunk)

    def flush(self):
        self.file.flush()


class _DecryptedReader:
    def __init__(self, file, decryptor, remaining: int):
        self.file, self.decryptor, self.remaining = file, decryptor, remaining

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        if size is None or size < 0:
            size = CHUNK
        data = self.file.read(min(size, self.remaining))
        if not data:
            raise ValueError("Truncated encrypted backup")
        self.remaining -= len(data)
        return self.decryptor.update(data)

    def finish(self):
        while self.remaining:
            self.read(CHUNK)
        self.decryptor.finalize()  # authenticate the entire payload


def _decryptor(key: bytes, nonce: bytes, tag: bytes, *, aad: bytes | None = None):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    context = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    if aad is not None:
        context.authenticate_additional_data(aad)
    return context


def _encryption(key: bytes, nonce: bytes, *, aad: bytes | None = None):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    context = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    if aad is not None:
        context.authenticate_additional_data(aad)
    return context


def export_encrypted_profile(store, profile_id: str, target: Path, passphrase: str) -> int:
    """Export a stopped profile including its browser data, never a vault password.

    A successful export never writes plaintext profile files to a temporary
    archive. The destination must not already exist and cannot be inside
    AutumnGenLogin's local data directory.
    """
    _passphrase(passphrase)
    target = Path(target).expanduser().absolute()
    if target.is_relative_to(store.base):
        raise ValueError("Save encrypted backups outside the application data directory")
    if not target.parent.is_dir():
        raise FileNotFoundError("Backup destination directory does not exist")
    if target.exists():
        raise FileExistsError("Refusing to overwrite an existing backup")
    with ProfileLease(store.base, profile_id):
        profile = store.get(profile_id)
        files = _real_files(store.profile_path(profile.id))
        metadata = profile.public_dict()
        # Credentials remain in Windows Credential Manager, not in the archive.
        metadata.update(proxy_scheme="", proxy_host="", proxy_port=0, proxy_username="",
                        created_at="", updated_at="")
        manifest = json.dumps({"format": FORMAT, "profile": metadata},
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(manifest) > MAX_METADATA:
            raise ValueError("Profile metadata exceeds backup limit")
        salt, nonce = secrets.token_bytes(SALT_SIZE), secrets.token_bytes(NONCE_SIZE)
        # The v2 header records the KDF work factor and is authenticated
        # with AES-GCM AAD: it cannot be silently downgraded by an attacker.
        header = MAGIC_V2 + KDF_PARAMS_V2 + salt + nonce
        enc = _encryption(_key(passphrase, salt, log_n=17), nonce, aad=header)
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(header)
                sink = _EncryptedWriter(output, enc)
                with tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    header = tarfile.TarInfo("profile.json")
                    header.size, header.mode, header.mtime = len(manifest), 0o600, 0
                    archive.addfile(header, io.BytesIO(manifest))
                    for source, rel, expected_size in files:
                        if source.is_symlink() or _reparse(source) or source.stat().st_size != expected_size:
                            raise ValueError("Browser data changed while exporting")
                        member = tarfile.TarInfo("browser/" + rel)
                        member.size, member.mode, member.mtime = expected_size, 0o600, 0
                        with source.open("rb") as stream:
                            archive.addfile(member, stream)
                        if source.stat().st_size != expected_size:
                            raise ValueError("Browser data changed while exporting")
                output.write(enc.finalize())
                output.write(enc.tag)
                output.flush()
                os.fsync(output.fileno())
            if target.stat().st_size > MAX_ENCRYPTED_SIZE:
                raise ValueError("Encrypted backup exceeds size limit")
            return len(files)
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def _header(file, total: int):
    if total < HEADER_SIZE + TAG_SIZE or total > MAX_ENCRYPTED_SIZE:
        raise ValueError("Invalid encrypted profile backup size")
    magic = file.read(len(MAGIC))
    if magic == MAGIC:
        kdf = (14, 8, 1)
        header_size = HEADER_SIZE
    elif magic == MAGIC_V2:
        params = file.read(len(KDF_PARAMS_V2))
        if params != KDF_PARAMS_V2:
            raise ValueError("Unsupported encrypted backup KDF parameters")
        kdf = tuple(params)
        header_size = HEADER_SIZE_V2
    else:
        raise ValueError("Not an AutumnGenLogin encrypted profile backup")
    if total < header_size + TAG_SIZE:
        raise ValueError("Truncated encrypted profile backup")
    salt, nonce = file.read(SALT_SIZE), file.read(NONCE_SIZE)
    if len(salt) != SALT_SIZE or len(nonce) != NONCE_SIZE:
        raise ValueError("Truncated encrypted profile backup header")
    aad = magic + KDF_PARAMS_V2 + salt + nonce if magic == MAGIC_V2 else None
    file.seek(total - TAG_SIZE)
    tag = file.read(TAG_SIZE)
    if len(tag) != TAG_SIZE:
        raise ValueError("Truncated backup authentication tag")
    return salt, nonce, tag, total - header_size - TAG_SIZE, header_size, kdf, aad


def _read_manifest(raw: bytes):
    if len(raw) > MAX_METADATA:
        raise ValueError("Profile manifest exceeds size limit")
    try:
        manifest = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid backup manifest") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"format", "profile"} or manifest["format"] != FORMAT:
        raise ValueError("Unsupported backup manifest")
    profile = manifest["profile"]
    if not isinstance(profile, dict) or set(profile) != set(Profile().__dict__):
        raise ValueError("Invalid profile fields")
    for field, default in (("proxy_scheme", ""), ("proxy_host", ""),
                           ("proxy_port", 0), ("proxy_username", "")):
        if profile[field] != default:
            raise ValueError("Imported backups cannot contain proxy credentials")
    data = dict(profile)
    data.update(id=str(uuid4()), created_at="", updated_at="")
    result = Profile(**data)
    result.validate()
    return result


def restore_encrypted_profile(store, source: Path, passphrase: str) -> Profile:
    """Verify authentication, then extract strictly regular files into staging.

    No existing profile is overwritten. Any error removes staged browser data,
    leaving the SQLite catalog unchanged.
    """
    _passphrase(passphrase)
    source = Path(source).expanduser()
    stage = None
    final = None
    with source.open("rb") as file:
        total = os.fstat(file.fileno()).st_size
        salt, nonce, tag, encrypted_size, header_size, kdf, aad = _header(file, total)
        key = _key(passphrase, salt, log_n=kdf[0], r=kdf[1], p=kdf[2])
        # First pass authenticates *before* any profile directory is created.
        file.seek(header_size)
        checker = _DecryptedReader(file, _decryptor(key, nonce, tag, aad=aad), encrypted_size)
        try:
            checker.finish()
        except Exception as exc:
            raise ValueError("Wrong passphrase or corrupted encrypted backup") from exc
        file.seek(header_size)
        reader = _DecryptedReader(file, _decryptor(key, nonce, tag, aad=aad), encrypted_size)
        stage = store.browser_dir / (".import-" + str(uuid4()))
        profile = None
        visited = set()
        total_bytes = 0
        count = 0
        try:
            stage.mkdir(mode=0o700)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for member in archive:
                    parts = _name(member.name)
                    if not member.isfile():
                        raise ValueError("Archive contains a link, device or directory entry")
                    keyname = "/".join(parts).casefold()
                    if keyname in visited:
                        raise ValueError("Duplicate or case-colliding archive path")
                    visited.add(keyname)
                    if member.size < 0 or member.size > MAX_FILE_SIZE:
                        raise ValueError("Unsafe archive member size")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError("Missing archive file data")
                    if parts == ("profile.json",):
                        if profile is not None:
                            raise ValueError("Duplicate profile manifest")
                        profile = _read_manifest(stream.read(MAX_METADATA + 1))
                        continue
                    if parts[0] != "browser" or len(parts) < 2:
                        raise ValueError("Unexpected backup archive entry")
                    count += 1
                    total_bytes += member.size
                    if count > MAX_FILES or total_bytes > MAX_TOTAL_SIZE:
                        raise ValueError("Backup exceeds bounded restore limits")
                    dest = stage.joinpath(*parts[1:])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open("xb") as output:
                        remaining = member.size
                        while remaining:
                            block = stream.read(min(CHUNK, remaining))
                            if not block:
                                raise ValueError("Truncated browser data member")
                            output.write(block)
                            remaining -= len(block)
            reader.finish()  # validate again before any installation
            if profile is None:
                raise ValueError("Missing profile manifest")
            final = store.profile_path(profile.id)
            with ProfileLease(store.base, profile.id):
                if final.exists():
                    raise FileExistsError("Generated profile ID already exists")
                os.replace(stage, final)
                stage = None
                try:
                    store.save(profile)
                except BaseException:
                    shutil.rmtree(final)
                    raise
            return profile
        finally:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)
