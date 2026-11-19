"""Non-UI profile operations, keeping database and vault updates ordered.

Credentials never enter SQLite, export files, logging or exception messages.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

from .models import Profile
from .storage import Store


def save_profile_with_credentials(store: Store, profile: Profile,
                                  previous: Profile | None,
                                  new_password: str,
                                  *, set_secret: Callable[[str, str], None],
                                  delete_secret: Callable[[str], None]) -> Profile:
    """Persist validated metadata first; roll back it if OS vault write fails.

    Note: vault / SQLite are different stores, so this is compensating
    transaction logic rather than an impossible cross-system ACID transaction.
    """
    profile.validate()
    if new_password and (not profile.proxy_scheme or not profile.proxy_username):
        raise ValueError("A proxy username is required to save a proxy password")
    snapshot = replace(previous) if previous else None
    stored = store.save(profile)
    try:
        if profile.proxy_scheme and profile.proxy_username and new_password:
            set_secret(profile.id, new_password)
        elif previous is not None and (
            previous.proxy_username != profile.proxy_username
            or (previous.proxy_scheme and not profile.proxy_scheme)
        ):
            # The secret belongs to a particular proxy identity. Never reuse
            # a password from a former username when a new username is entered.
            delete_secret(profile.id)
    except Exception:
        try:
            if snapshot is not None:
                store.save(snapshot)
            else:
                store.delete(profile.id)
        except Exception as restore_error:
            raise RuntimeError("Credential update failed AND metadata recovery failed; run Diagnostics") from restore_error
        raise
    return stored


def delete_profile_with_credentials(store: Store, profile_id: str, *,
                                    delete_secret: Callable[[str], None],
                                    clear_run: Callable[[str], None] | None = None) -> tuple[list[str], str | None]:
    """Delete data transactionally, then revoke vault secret and in-memory results.

    The database+filesystem cannot be made atomic with the OS credential vault.
    Return an explicit warning if credential cleanup fails AFTER deletion.
    """
    leftovers = store.delete(profile_id)  # raises before touching the OS vault on failure
    if clear_run is not None:
        clear_run(profile_id)
    try:
        delete_secret(profile_id)
    except Exception:
        return leftovers, "Profile removed, but credential vault cleanup failed. Inspect your OS credential manager."
    return leftovers, None
