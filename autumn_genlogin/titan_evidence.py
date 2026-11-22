"""Non-invasive GenLogin/Titan evidence intake and release-HOLD readiness audit.

This NEVER launches, patches, reverse engineers or copies proprietary binaries.
It cannot establish browser engine equivalence from marketing claims, a
download URL, a user agent, or this program's own synthetic tests. An external,
legally authorized Windows comparison and independent human review remain
mandatory before any EXE release decision.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

FORMAT = "AutumnGenLogin/titan-evidence-1"
REQUIRED_CASES = (
    "profile_lifecycle",
    "session_persistence",
    "network_proxy_consistency",
    "browser_locale_timezone",
    "extension_behavior",
    "workflow_recorder",
    "scheduler_recovery",
    "gui_accessibility",
    "cloud_profile_transfer",
    "rendering_consistency",
    "long_run_reliability",
    "license_distribution",
)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RELEASE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z")
_STATUS = {"pass","fail","not-run"}


def _sha(value: object) -> bool:
    return isinstance(value,str) and bool(_SHA.fullmatch(value))


def _validate_reference(reference: object) -> tuple[bool,tuple[str,...]]:
    if reference is None:
        return False, ("Pinned, authorized GenLogin/Titan baseline missing",)
    expected = {"vendor","product","release","edition","platform",
                "installer_sha256","provenance","license_authorized",
                "observation_authorized","baseline_date"}
    if not isinstance(reference,dict) or set(reference) != expected:
        raise ValueError("Reference attestation contains unexpected or missing fields")
    missing=[]
    if reference["vendor"] != "GenLogin" or reference["product"] != "Titan Browser":
        raise ValueError("Only an explicitly identified GenLogin/Titan reference is accepted")
    if not isinstance(reference["release"],str) or not _RELEASE.fullmatch(reference["release"]):
        raise ValueError("Reference release must be pinned as X.Y.Z")
    if not isinstance(reference["edition"],str) or not 1 <= len(reference["edition"]) <= 100:
        raise ValueError("Reference edition must be identified")
    if reference["platform"] not in {"Windows 10","Windows 11"}:
        raise ValueError("Reference must be a named Windows 10/11 environment")
    if not _sha(reference["installer_sha256"]):
        missing.append("Verified local installer SHA-256 missing")
    if reference["provenance"] != "vendor-official":
        missing.append("Official installer provenance not attested")
    if reference["license_authorized"] is not True:
        missing.append("Legal authorization for the installed reference missing")
    if reference["observation_authorized"] is not True:
        missing.append("Written or documented authorization for the observation plan missing")
    try:
        date.fromisoformat(reference["baseline_date"])
    except (TypeError, ValueError):
        missing.append("Baseline inspection date missing or invalid")
    return not missing,tuple(missing)


def _validate_case(record: object) -> tuple[str,str]:
    if not isinstance(record,dict) or set(record) != {
        "id","reference_status","autumn_status",
        "reference_artifact_sha256","autumn_artifact_sha256"
    }:
        raise ValueError("Test-case evidence contains unapproved fields")
    name=record["id"]
    if name not in REQUIRED_CASES:
        raise ValueError("Unrecognized reference comparison case")
    ref,local=record["reference_status"],record["autumn_status"]
    if not isinstance(ref,str) or ref not in _STATUS or not isinstance(local,str) or local not in _STATUS:
        raise ValueError("Case status must be pass, fail or not-run")
    for state,key in ((ref,"reference_artifact_sha256"),(local,"autumn_artifact_sha256")):
        digest=record[key]
        if not (digest == "" if state == "not-run" else _sha(digest)):
            raise ValueError("Case evidence artifact SHA-256 is invalid or missing")
    return name,("matched" if ref==local=="pass" else "mismatch" if "fail" in {ref,local}
                 else "missing")


def audit_evidence(document: object) -> dict:
    """Summarize *candidate* evidence, never issue a parity certificate."""
    if not isinstance(document,dict) or set(document) != {"format","reference","cases"} or document["format"] != FORMAT:
        raise ValueError("Invalid evidence intake document format")
    reference_ok,baseline_missing=_validate_reference(document["reference"])
    cases=document["cases"]
    if not isinstance(cases,list) or len(cases)>len(REQUIRED_CASES):
        raise ValueError("Evidence case list must be bounded")
    observed={}
    for record in cases:
        name,status=_validate_case(record)
        if name in observed:
            raise ValueError("Duplicate comparison case ID")
        observed[name]=status
    incomplete=[name for name in REQUIRED_CASES if observed.get(name)!="matched"]
    missing=list(baseline_missing)
    if not reference_ok:
        missing.append("Independent baseline verification not accepted")
    missing.extend(f"Case incomplete: {name}" for name in incomplete)
    # Even when every field is self-asserted and marked pass, independent
    # signed witness reports, product legal review and external release gates
    # are NOT something a local JSON parser can attest to.
    return {
        "state":"blocked" if missing else "needs-independent-human-review",
        "can_build_exe":False,
        "can_claim_titan_parity":False,
        "reference_declared":document["reference"] is not None,
        "case_count":len(observed),
        "matched_cases":sum(x=="matched" for x in observed.values()),
        "required_cases":len(REQUIRED_CASES),
        "outstanding":missing or [
            "External auditor must verify binary provenance, lawful reference observations, "
            "artifact authenticity, reproducibility and ALL release gates"
        ],
    }


def inspect_file(path: Path) -> dict:
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>128*1024:
        raise ValueError("Evidence file must be a regular JSON document under 128 KiB")
    return audit_evidence(json.loads(path.read_text(encoding="utf-8")))


def main() -> int:
    if len(sys.argv)!=2:
        print("Usage: python -m autumn_genlogin.titan_evidence <reference-evidence.json>")
        return 2
    try:
        result=inspect_file(Path(sys.argv[1]))
    except Exception as exc:
        # Never echo untrusted evidence file contents or confidential paths.
        print(json.dumps({"state":"invalid","error_type":type(exc).__name__,
                          "can_build_exe":False,"can_claim_titan_parity":False}))
        return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    # Any evidence, even complete self-reported cases, cannot unlock EXE.
    return 1
if __name__=="__main__":
    raise SystemExit(main())
