"""Synthetic Compose hardening regressions; no Docker/model is started."""
from __future__ import annotations

import copy
import unittest

from experiments.browser_use_lab.check_compose import check_contract


def fixture():
    base = {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "networks": ["private-lab"],
    }
    return {
        "services": {
            "agent": {
                **base,
                "user": "10001:10001",
                "environment": {
                    "ANONYMIZED_TELEMETRY": "false",
                    "BROWSER_USE_AUTO_LOGIN": "false",
                    "AUTUMN_AI_LAB_ISOLATED": "1",
                },
                "depends_on": {"ollama": {"condition": "service_healthy"}},
            },
            "ollama": {
                **base,
                "environment": {"OLLAMA_MODELS": "/models"},
                "volumes": [
                    {"type": "bind", "source": "/synthetic-models",
                     "target": "/models", "read_only": True}
                ],
                "tmpfs": ["/tmp:rw,nosuid,nodev,size=256m",
                          "/root/.ollama:rw,nosuid,nodev,size=32m"],
                "healthcheck": {"test": ["CMD", "ollama", "list"]},
            },
        },
        "networks": {"private-lab": {"internal": True}},
    }


class LabComposeContractTests(unittest.TestCase):
    def test_valid_isolated_offline_model_mount(self):
        self.assertIsNone(check_contract(fixture()))

    def test_refuses_read_only_home_without_ephemeral_key_state(self):
        doc=fixture()
        doc["services"]["ollama"]["tmpfs"] = ["/tmp:rw,nosuid,nodev,size=256m"]
        with self.assertRaisesRegex(ValueError, "ephemeral tmpfs"):
            check_contract(doc)

    def test_refuses_host_model_credentials_and_writable_weights(self):
        for change in (
            {"target": "/root/.ollama"},
            {"read_only": False},
            {"target": "/tmp"},
        ):
            with self.subTest(change=change):
                doc=copy.deepcopy(fixture())
                doc["services"]["ollama"]["volumes"][0].update(change)
                with self.assertRaisesRegex(ValueError, "read-only /models"):
                    check_contract(doc)

    def test_refuses_missing_model_readiness_gate(self):
        for field in ("healthcheck", "depends_on"):
            with self.subTest(field=field):
                doc=copy.deepcopy(fixture())
                doc["services"]["ollama" if field=="healthcheck" else "agent"].pop(field)
                with self.assertRaises(ValueError):
                    check_contract(doc)

    def test_refuses_models_outside_the_read_only_bind(self):
        doc=fixture()
        doc["services"]["ollama"]["environment"]["OLLAMA_MODELS"]="/root/.ollama"
        with self.assertRaisesRegex(ValueError,"offline model weights"):
            check_contract(doc)


if __name__=="__main__":
    unittest.main()
