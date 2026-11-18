"""Proxy passwords go to the OS credential vault, never SQLite or exports."""
from __future__ import annotations

SERVICE = "AutumnGenLogin/proxy"


def _backend():
    try:
        import keyring
        backend = keyring.get_keyring()
        if getattr(backend, "priority", 0) <= 0:
            raise RuntimeError("No secure OS credential store is available")
        return keyring
    except ImportError as exc:
        raise RuntimeError("Install keyring for secure password storage") from exc


def get_password(profile_id: str) -> str:
    return _backend().get_password(SERVICE, profile_id) or ""


def set_password(profile_id: str, password: str) -> None:
    keyring = _backend()
    if password:
        keyring.set_password(SERVICE, profile_id, password)
    else:
        try:
            keyring.delete_password(SERVICE, profile_id)
        except keyring.errors.PasswordDeleteError:
            pass


def delete_password(profile_id: str) -> None:
    set_password(profile_id, "")
