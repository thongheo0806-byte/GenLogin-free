"""A marketing version string or synthetic test must NEVER unlock an EXE."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from autumn_genlogin.titan_evidence import (
    FORMAT, REQUIRED_CASES, audit_evidence, inspect_file
)


class TitanEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.empty={"format":FORMAT,"reference":None,"cases":[]}
        self.reference={
            "vendor":"GenLogin","product":"Titan Browser","release":"4.5.1",
            "edition":"synthetic review placeholder","platform":"Windows 11",
            "installer_sha256":"a"*64,"provenance":"vendor-official",
            "license_authorized":True,"observation_authorized":True,
            "baseline_date":"2026-11-21"
        }

    def test_no_reference_never_unlocks_release(self):
        report=audit_evidence(self.empty)
        self.assertEqual(report["state"],"blocked")
        self.assertFalse(report["can_claim_titan_parity"])
        self.assertFalse(report["can_build_exe"])
        self.assertEqual(report["matched_cases"],0)
        self.assertEqual(report["required_cases"],len(REQUIRED_CASES))
        self.assertGreater(len(report["outstanding"]),10)

    def test_only_self_reported_full_pass_still_requires_independent_review(self):
        doc=copy.deepcopy(self.empty)
        doc["reference"]=self.reference
        doc["cases"]=[{
            "id":name,
            "reference_status":"pass","autumn_status":"pass",
            "reference_artifact_sha256":"b"*64,
            "autumn_artifact_sha256":"c"*64
        } for name in REQUIRED_CASES]
        result=audit_evidence(doc)
        self.assertEqual(result["state"],"needs-independent-human-review")
        self.assertEqual(result["matched_cases"],len(REQUIRED_CASES))
        self.assertFalse(result["can_build_exe"])
        self.assertFalse(result["can_claim_titan_parity"])
        self.assertIn("External auditor",result["outstanding"][0])

    def test_missing_license_observations_and_failed_case_block(self):
        for bad in (
            {"license_authorized":False},
            {"observation_authorized":False},
            {"provenance":"third-party-unknown"},
            {"installer_sha256":""},
            {"baseline_date":"not a date"}
        ):
            with self.subTest(bad=bad):
                doc={**self.empty,"reference":{**self.reference,**bad}}
                self.assertEqual(audit_evidence(doc)["state"],"blocked")
        case={"id":REQUIRED_CASES[0],"reference_status":"pass","autumn_status":"fail",
              "reference_artifact_sha256":"a"*64,"autumn_artifact_sha256":"b"*64}
        doc={**self.empty,"reference":self.reference,"cases":[case]}
        self.assertEqual(audit_evidence(doc)["state"],"blocked")

    def test_rejects_unknown_evidence_fields_duplicate_or_fake_hash(self):
        invalids=[
            {**self.empty,"other":"include-secrets"},
            {**self.empty,"reference":{**self.reference,"extra":"x"}},
            {**self.empty,"reference":{**self.reference,"vendor":"OtherVendor"}},
            {**self.empty,"reference":{**self.reference,"release":"latest"}},
            {**self.empty,"cases":[{"id":"unknown"}]},
        ]
        for doc in invalids:
            with self.subTest(doc=doc),self.assertRaises(ValueError):
                audit_evidence(doc)
        good={"id":REQUIRED_CASES[0],"reference_status":"not-run",
              "autumn_status":"not-run",
              "reference_artifact_sha256":"","autumn_artifact_sha256":""}
        with self.assertRaises(ValueError):
            audit_evidence({**self.empty,"cases":[good,good]})
        with self.assertRaises(ValueError):
            audit_evidence({**self.empty,"cases":[{**good,"reference_artifact_sha256":"123"}]})

    def test_template_file_read_is_bounded_and_source_never_modified(self):
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/"evidence.json"
            path.write_text(json.dumps(self.empty),encoding="utf-8")
            self.assertFalse(inspect_file(path)["can_build_exe"])
            self.assertEqual(json.loads(path.read_text()),self.empty)
            path.write_bytes(b"?"*(128*1024+1))
            with self.assertRaises(ValueError):
                inspect_file(path)


if __name__=="__main__":
    unittest.main()
