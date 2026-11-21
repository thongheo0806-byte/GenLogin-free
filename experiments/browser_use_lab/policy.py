"""Preflight policy for a self-contained AI agent proof of concept.

Validation alone is not a sandbox. A container runtime with an *internal*
network, no application-data mounts and a local-only model is required.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

BROWSER_USE_VERSION = "1.0.7"
MODEL_BASE_URL = "http://ollama:11434/v1"
MODEL_RE = re.compile(r"[A-Za-z0-9_.:/-]{1,96}\Z")
SENSITIVE_NAMES = frozenset({
    "BROWSER_USE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "POLLINATIONS_API_KEY",
    "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "GH_TOKEN", "AUTUMN_GENLOGIN_HOME",
    "AUTUMN_API_TOKEN", "PROXY_PASSWORD",
})


@dataclass(frozen=True)
class LabConfig:
    model: str
    max_steps: int = 6
    timeout_seconds: int = 90

    def fixture_task(self, origin: str) -> str:
        if not origin.startswith("http://127.0.0.1:"):
            raise ValueError("AI lab task must use its own loopback fixture")
        return (
            f"Open {origin}/, click the button labeled 'Verify local fixture' "
            "and report exactly the resulting message TEST-OK. "
            "This is a synthetic offline test. Do not access any other site, "
            "file or browser profile. Do not submit credentials."
        )


def validate_environment(env: Mapping[str, str], *, inside_container: bool) -> LabConfig:
    if not inside_container:
        raise RuntimeError("AI lab refuses host execution: use its isolated Docker service")
    if env.get("AUTUMN_AI_LAB_ISOLATED") != "1":
        raise RuntimeError("AI lab requires explicit isolation approval")
    if any(env.get(key) for key in SENSITIVE_NAMES):
        raise RuntimeError("AI lab must not inherit application credentials or profile paths")
    if env.get("ANONYMIZED_TELEMETRY", "").lower() != "false":
        raise RuntimeError("Disable browser-use telemetry in the isolated lab")
    if env.get("BROWSER_USE_AUTO_LOGIN", "").lower() != "false":
        raise RuntimeError("Disable interactive/cloud login in the isolated lab")
    if any(env.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")):
        raise RuntimeError("AI lab must not use inherited network proxies")
    model = env.get("AUTUMN_LAB_MODEL", "")
    if not isinstance(model, str) or not MODEL_RE.fullmatch(model) or model.startswith("-"):
        raise ValueError("Explicitly specify a local Ollama model without spaces or commands")
    return LabConfig(model=model)
