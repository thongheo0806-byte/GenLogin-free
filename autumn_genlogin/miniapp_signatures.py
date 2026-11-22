"""Local-only Ed25519 signatures for declarative Miniapp JSON packages.

A valid signature proves possession of the pinned private key, NOT a public
publisher's real-world identity. Trust must be granted separately, using an
out-of-band verified fingerprint. No marketplace or remote code execution.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

SIGNED_FORMAT = "AutumnGenLogin/signed-miniapp-1"
DOMAIN = b"AutumnGenLogin/miniapp-signature-v1\x00"


def canonical_bytes(manifest: object) -> bytes:
    from .miniapps import validate_miniapp
    checked = validate_miniapp(manifest)
    return json.dumps(checked,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False).encode("utf-8")


def decode_b64(value: object, expected: int) -> bytes:
    if not isinstance(value,str) or len(value) > 200 or not value.isascii():
        raise ValueError("Invalid public-key or signature encoding")
    try:
        raw=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error) as exc:
        raise ValueError("Invalid public-key or signature encoding") from exc
    if len(raw)!=expected or base64.b64encode(raw).decode("ascii")!=value:
        raise ValueError("Invalid public-key or signature length")
    return raw


def publisher_fingerprint(public_key_b64: str) -> str:
    raw=decode_b64(public_key_b64,32)
    Ed25519PublicKey.from_public_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def verify_signed_package(package: object) -> tuple[dict,str,str,str]:
    if not isinstance(package,dict) or set(package)!={
        "format","manifest","public_key","signature"
    } or package.get("format")!=SIGNED_FORMAT:
        raise ValueError("Unsupported signed Miniapp envelope")
    from .miniapps import validate_miniapp
    manifest=validate_miniapp(package["manifest"])
    public_key=package["public_key"]
    signature=package["signature"]
    pub=decode_b64(public_key,32)
    sig=decode_b64(signature,64)
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(
            sig,DOMAIN+canonical_bytes(manifest))
    except (InvalidSignature,ValueError) as exc:
        raise ValueError("Miniapp Ed25519 signature is invalid") from exc
    return manifest,hashlib.sha256(pub).hexdigest(),public_key,signature


def sign_package(manifest: object, private_key: Ed25519PrivateKey) -> dict:
    if not isinstance(private_key,Ed25519PrivateKey):
        raise ValueError("Signing requires an Ed25519 private key")
    from .miniapps import validate_miniapp
    checked=validate_miniapp(manifest)
    public_key=private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature=private_key.sign(DOMAIN+canonical_bytes(checked))
    return {
        "format":SIGNED_FORMAT,
        "manifest":checked,
        "public_key":base64.b64encode(public_key).decode("ascii"),
        "signature":base64.b64encode(signature).decode("ascii")
    }


def _load_pem_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink() or not path.is_file() or path.stat().st_size>8192:
        raise ValueError("Key must be an ordinary private PEM file <=8 KiB")
    key=serialization.load_pem_private_key(path.read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):
        raise ValueError("Publisher signing key must use Ed25519")
    return key


def main() -> int:
    """Local signer or public-key exporter. Private PEM is never printed."""
    if len(sys.argv)==3 and sys.argv[1]=="public":
        try:
            key=_load_pem_key(Path(sys.argv[2]))
            public=key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            b64=base64.b64encode(public).decode("ascii")
            print("Public Ed25519 key (base64): "+b64)
            print("SHA-256 fingerprint: "+hashlib.sha256(public).hexdigest())
            return 0
        except (OSError,ValueError,TypeError):
            print("Public-key export failed; check the local PEM type and permissions.")
            return 1
    if len(sys.argv)!=5 or sys.argv[1]!="sign":
        print("Usage: python -m autumn_genlogin.miniapp_signatures "
              "public private_key.pem\n"
              "or: python -m autumn_genlogin.miniapp_signatures "
              "sign manifest.json private_key.pem signed.json")
        return 2
    _,_,source_name,key_name,dest_name=sys.argv
    source,key,dest=Path(source_name),Path(key_name),Path(dest_name)
    try:
        if (source.is_symlink() or not source.is_file()
                or source.stat().st_size>65536):
            raise ValueError("Manifest must be an ordinary JSON file <=64 KiB")
        manifest=json.loads(source.read_text(encoding="utf-8"))
        private=_load_pem_key(key)
        signed=sign_package(manifest,private)
        output=json.dumps(signed,ensure_ascii=False,indent=2)+"\n"
        if len(output.encode("utf-8"))>65536:
            raise ValueError("Signed Miniapp package exceeds 64 KiB")
        with dest.open("x",encoding="utf-8") as fd:
            fd.write(output)
    except (OSError,UnicodeError,ValueError,TypeError):
        # Never print input file text, key bytes or secrets.
        print("Signing failed; check JSON, key format, size and output path.")
        return 1
    print("Signed Miniapp written; verify publisher key fingerprint out of band.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
