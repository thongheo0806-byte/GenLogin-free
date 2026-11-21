"""Static AI lab Docker policy rejection tests; no Docker needed in unit suite."""
from copy import deepcopy
import unittest

from experiments.browser_use_lab.check_compose import check_contract


def fixture():
    return {
        "networks":{"private-lab":{"internal":True}},
        "services":{
            "agent":{
                "networks":["private-lab"],"read_only":True,
                "cap_drop":["ALL"],"security_opt":["no-new-privileges:true"],
                "user":"10001:10001","volumes":[],
                "environment":{
                    "ANONYMIZED_TELEMETRY":"false",
                    "BROWSER_USE_AUTO_LOGIN":"false",
                    "AUTUMN_AI_LAB_ISOLATED":"1"
                }
            },
            "ollama":{
                "networks":["private-lab"],"read_only":True,
                "cap_drop":["ALL"],"security_opt":["no-new-privileges:true"],
                "volumes":[{"type":"bind","source":"/models",
                            "target":"/root/.ollama","read_only":True}]
            }
        },
    }


class AIComposePolicyTests(unittest.TestCase):
    def test_isolated_static_contract(self):
        check_contract(fixture())

    def test_refuse_privileged_network_exfil_and_host_app_mount(self):
        for bad in ("ports","expose","network_mode","privileged","volumes"):
            with self.subTest(bad=bad):
                config=fixture()
                if bad=="ports":config["services"]["agent"][bad]=["8000:8000"]
                elif bad=="expose":config["services"]["ollama"][bad]=[11434]
                elif bad=="network_mode":config["services"]["agent"][bad]="host"
                elif bad=="privileged":config["services"]["agent"][bad]=True
                else:config["services"]["agent"][bad]=["C:/Users/AppData:/data"]
                with self.assertRaises(ValueError):
                    check_contract(config)
        config=fixture()
        config["networks"]["private-lab"]["internal"]=False
        with self.assertRaises(ValueError):
            check_contract(config)
        config=fixture()
        config["services"]["ollama"]["volumes"][0]["read_only"]=False
        with self.assertRaises(ValueError):
            check_contract(config)

    def test_enforce_telemetry_off_rootless_and_capabilities_dropped(self):
        config=fixture()
        config["services"]["agent"]["environment"]["ANONYMIZED_TELEMETRY"]="true"
        with self.assertRaises(ValueError):
            check_contract(config)
        config=fixture()
        config["services"]["agent"]["user"]="0:0"
        with self.assertRaises(ValueError):
            check_contract(config)
        config=fixture()
        config["services"]["agent"]["cap_drop"]=[]
        with self.assertRaises(ValueError):
            check_contract(config)
        config=fixture()
        config["services"]["agent"]["security_opt"]=[]
        with self.assertRaises(ValueError):
            check_contract(config)


if __name__=="__main__":
    unittest.main()
