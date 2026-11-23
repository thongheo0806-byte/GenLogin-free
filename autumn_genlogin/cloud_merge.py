"""Conservative, deterministic three-way reconciliation for encrypted team metadata.

No browser session, proxy, token or OS-vault password is allowed here.
Never use a two-way guess to overwrite an already published remote revision.
Merge returns structural conflict locations only, not field values.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from .graph import validate_graph
from .models import Profile, validated_steps

PROFILE_FORMAT = "AutumnGenLogin/profile-metadata-1"
WORKFLOW_FORMAT = "AutumnGenLogin/workflow-1"
PROFILE_FIELDS = frozenset({
    "id", "name", "group_name", "tags", "browser", "start_url",
    "locale", "timezone_id", "viewport_width", "viewport_height",
})


def _profiles(document: dict) -> dict[str, dict]:
    if (not isinstance(document, dict) or set(document) != {"format", "profiles"}
            or document["format"] != PROFILE_FORMAT
            or not isinstance(document["profiles"], list)
            or len(document["profiles"]) > 2000):
        raise ValueError("Invalid encrypted team profile metadata")
    result = {}
    for item in document["profiles"]:
        if not isinstance(item,dict) or set(item) != PROFILE_FIELDS:
            raise ValueError("Unexpected team metadata fields")
        try:
            ident = str(UUID(item["id"]))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Invalid team profile ID") from None
        if item["id"] != ident or ident in result:
            raise ValueError("Noncanonical or duplicate team profile ID")
        # Validate without reading or writing any local secret/profile data.
        Profile(**item).validate()
        result[ident]=deepcopy(item)
    return result


def _workflow(document: dict) -> dict:
    if (not isinstance(document,dict)
            or set(document) != {"format","workflow"}
            or document["format"] != WORKFLOW_FORMAT):
        raise ValueError("Invalid team workflow metadata")
    flow=document["workflow"]
    if isinstance(flow,list):
        validated_steps(flow)
    else:
        validate_graph(flow)
    return deepcopy(document)


def merge_cloud_documents(name: str, base: dict | None, local: dict,
                          remote: dict | None) -> tuple[dict | None, tuple[str,...]]:
    """Merge only diverging *allowed* metadata when a known baseline exists.

    No deletion is inferred from absence: cloud metadata is additive, and
    local profile removal must never be propagated implicitly. Conflicts
    include structural locations only; callers must not log field values.
    """
    if name not in {"profiles","workflows"}:
        raise ValueError("Unknown team document type")
    validate = _profiles if name=="profiles" else _workflow
    if name=="profiles":
        validate(local)
        if base is not None: validate(base)
        if remote is not None: validate(remote)
    else:
        validate(local)
        if base is not None: validate(base)
        if remote is not None: validate(remote)
    if remote == local:
        return deepcopy(local), ()
    if remote is None:
        if base is None:
            return deepcopy(local), ()
        return None, ("remote-document-removed",)
    if base is None:
        return None, ("no-shared-baseline",)
    if remote == base:
        return deepcopy(local), ()
    if local == base:
        return deepcopy(remote), ()
    if name=="workflows":
        return None, ("workflow-diverged",)

    baseline, ours, theirs = _profiles(base), _profiles(local), _profiles(remote)
    merged = {}
    conflicts=[]
    for ident in sorted(set(baseline) | set(ours) | set(theirs)):
        b, l, r = baseline.get(ident), ours.get(ident), theirs.get(ident)
        # Metadata sync does not delete profiles on a missing record.
        if l is None and r is None:
            # Never infer destructive deletion from two missing snapshots.
            # Preserve the previously known profile until an explicit
            # local delete/remote revoke workflow is implemented.
            if b is not None:
                merged[ident]=b
            continue
        if l is None:
            merged[ident]=r
            continue
        if r is None:
            merged[ident]=l
            continue
        if b is None:
            if l != r:
                conflicts.append(ident + ":new-record")
                continue
            merged[ident]=l
            continue
        row={"id":ident}
        for key in sorted(PROFILE_FIELDS - {"id"}):
            if l[key] == r[key]:
                row[key]=l[key]
            elif l[key] == b[key]:
                row[key]=r[key]
            elif r[key] == b[key]:
                row[key]=l[key]
            else:
                conflicts.append(ident + ":" + key)
        if len(row)==len(PROFILE_FIELDS):
            merged[ident]=row
    if conflicts:
        return None, tuple(conflicts)
    result={"format":PROFILE_FORMAT,"profiles":[merged[x] for x in sorted(merged)]}
    _profiles(result)  # merged row must still satisfy Profile constraints
    return result, ()
