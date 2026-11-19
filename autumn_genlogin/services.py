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
    snapshot = replace(previous) if previous else None
    stored = store.save(profile)
    try:
        if profile.proxy_scheme and new_password:
            set_secret(profile.id, new_password)
        elif not profile.proxy_scheme and previous is not None and previous.proxy_scheme:
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
