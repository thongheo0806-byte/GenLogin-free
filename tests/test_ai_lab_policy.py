"""Policy-only AI research lab tests; no browser-use import or live model calls."""
import os
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from experiments.browser_use_lab.policy import (
    BROWSER_USE_VERSION, MODEL_BASE_URL, SENSITIVE_NAMES, validate_environment
)
from experiments.browser_use_lab.agent import run_demo


SAFE_ENV={
    "AUTUMN_AI_LAB_ISOLATED":"1",
    "BROWSER_USE_AUTO_LOGIN":"false",
    "ANONYMIZED_TELEMETRY":"false",
    "AUTUMN_LAB_MODEL":"qwen2.5:3b",
}


class BrowserUseLabPolicyTests(unittest.TestCase):
    def test_requires_proven_container_flag_and_explicit_local_model(self):
        with self.assertRaises(RuntimeError):
            validate_environment(SAFE_ENV,inside_container=False)
        with self.assertRaises(RuntimeError):
            validate_environment({},inside_container=True)
        cfg=validate_environment(SAFE_ENV,inside_container=True)
        self.assertEqual(cfg.model,"qwen2.5:3b")
        self.assertEqual(cfg.max_steps,6)
        self.assertLessEqual(cfg.timeout_seconds,90)
        self.assertIn("127.0.0.1",cfg.fixture_task("http://127.0.0.1:12345"))
        with self.assertRaises(ValueError):
            cfg.fixture_task("https://example.org")

    def test_prohibits_real_account_tokens_proxy_and_telemetry(self):
        for key in SENSITIVE_NAMES:
            with self.subTest(name=key):
                with self.assertRaises(RuntimeError):
                    validate_environment({**SAFE_ENV,key:"secret"},inside_container=True)
        for change in (
            {"AUTUMN_LAB_MODEL":"foo;curl attacker"},
            {"AUTUMN_LAB_MODEL":""},
            {"AUTUMN_LAB_MODEL":"../../secret model"},
            {"BROWSER_USE_AUTO_LOGIN":"true"},
            {"ANONYMIZED_TELEMETRY":"true"},
            {"HTTP_PROXY":"http://proxy.example:9000"}
        ):
            with self.subTest(change=change),self.assertRaises((ValueError,RuntimeError)):
                validate_environment({**SAFE_ENV,**change},inside_container=True)

    def test_fake_agent_only_sees_synthetic_local_fixture_and_ephemeral_workspace(self):
        config=validate_environment(SAFE_ENV,inside_container=True)
        seen={}
        class FakeBrowser:
            def __init__(self,*args,**kwargs):
                seen["browser"]=(args,kwargs)
        class FakeModel:
            def __init__(self,*args,**kwargs):
                seen["model"]=(args,kwargs)
        class FakeAgent:
            def __init__(self,task,**kwargs):
                seen["task"]=task
                seen["options"]=kwargs
                self.workspace=kwargs["workspace"]
                self.target=task.split("Open ",1)[1].split("/,",1)[0]
            def run_sync(self,**kwargs):
                seen["limits"]=kwargs
                address=seen["task"].split("Open ",1)[1].split(", click",1)[0]
                with urlopen(address,timeout=2) as resp:
                    html=resp.read().decode()
                assert "Verify local fixture" in html
                assert "TEST-OK" in html
                # Fake agent explicitly simulates the verification event.
                # A text-only reported success must no longer be sufficient.
                with urlopen(Request(address.rstrip("/") + "/verified",
                                     data=b"TEST-OK",method="POST",
                                     headers={"Content-Type":"text/plain"}),
                             timeout=2) as response:
                    assert response.status == 204
                class Result:
                    def final_result(self):
                        return "TEST-OK"
                return Result()
        self.assertTrue(run_demo(config,agent_type=FakeAgent,
                                  browser_type=FakeBrowser,llm_type=FakeModel))
        self.assertEqual(seen["browser"][0],("chromium",))
        self.assertEqual(seen["browser"][1]["allowed_domains"],["127.0.0.1"])
        self.assertEqual(seen["model"][1]["base_url"],MODEL_BASE_URL)
        self.assertFalse(seen["options"]["web_search"])
        self.assertFalse(seen["options"]["judge"])
        self.assertFalse(seen["options"]["use_vision"])
        self.assertFalse(Path(seen["options"]["workspace"]).exists(),
                         "No fake browser files should persist after lab run")
        self.assertEqual(seen["limits"]["max_steps"],6)
        self.assertEqual(seen["limits"]["timeout"],90)


if __name__=="__main__":
    unittest.main()
