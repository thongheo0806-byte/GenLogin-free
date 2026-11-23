"""Static Docker Compose isolation contract.

This is not a substitute for runtime network/VM penetration testing. It is
designed to stop accidental reconfiguration that exposes host ports, secrets
or application profile mounts in the AI research experiment.
"""
from __future__ import annotations

import json
import sys


def check_contract(document: dict) -> None:
    if not isinstance(document, dict):
        raise ValueError("Compose file must resolve to a JSON object")
    services = document.get("services")
    networks = document.get("networks")
    if not isinstance(services, dict) or set(services) != {"agent", "ollama"}:
        raise ValueError("AI lab must have only its agent and Ollama model services")
    if not isinstance(networks, dict) or len(networks) != 1:
        raise ValueError("AI lab must use one dedicated isolated network")
    network_name, network = next(iter(networks.items()))
    if not isinstance(network, dict) or network.get("internal") is not True:
        raise ValueError("AI lab runtime network must be Docker internal-only")
    agent, model = services["agent"], services["ollama"]
    for name, service in services.items():
        if service.get("ports") or service.get("expose"):
            raise ValueError(name + " must not publish or expose network ports")
        if service.get("network_mode") or service.get("privileged"):
            raise ValueError(name + " must not bypass network or privilege separation")
        if service.get("read_only") is not True:
            raise ValueError(name + " root filesystem must be read-only")
        if "ALL" not in service.get("cap_drop", []):
            raise ValueError(name + " must drop Linux capabilities")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            raise ValueError(name + " must disable privilege escalation")
        names = service.get("networks", [])
        if isinstance(names, dict):
            names = list(names)
        if names != [network_name]:
            raise ValueError(name + " must use only private-lab network")
    if agent.get("volumes"):
        raise ValueError("AI agent may not access any host volumes")
    environment = agent.get("environment", {})
    if environment.get("ANONYMIZED_TELEMETRY") != "false":
        raise ValueError("AI telemetry must be disabled")
    if environment.get("BROWSER_USE_AUTO_LOGIN") != "false":
        raise ValueError("Cloud account auto-login must be disabled")
    if environment.get("AUTUMN_AI_LAB_ISOLATED") != "1":
        raise ValueError("AI lab must require operator opt-in")
    if not agent.get("user") or agent.get("user").startswith("0:"):
        raise ValueError("AI agent must not run as root")
    volumes = model.get("volumes", [])
    if (len(volumes) != 1 or not isinstance(volumes[0], dict)
            or volumes[0].get("read_only") is not True
            or volumes[0].get("target") != "/models"
            or volumes[0].get("type") != "bind"):
        raise ValueError("Model weights must be a single read-only /models bind mount")
    if model.get("environment", {}).get("OLLAMA_MODELS") != "/models":
        raise ValueError("Ollama must load offline model weights from /models")
    tmpfs = model.get("tmpfs", [])
    # Preserve a writable, ephemeral key/state directory while the root and
    # model weights remain read-only. No host mount may contain Ollama keys.
    if not any(
        isinstance(item, str) and item.startswith("/root/.ollama:rw,")
        for item in tmpfs
    ):
        raise ValueError("Ollama runtime state must use writable ephemeral tmpfs")
    health = model.get("healthcheck", {})
    if health.get("test") != ["CMD", "ollama", "list"]:
        raise ValueError("Ollama needs an explicit local readiness healthcheck")
    dependencies = agent.get("depends_on", {})
    if (not isinstance(dependencies, dict)
            or dependencies.get("ollama", {}).get("condition") != "service_healthy"):
        raise ValueError("Agent must wait for healthy offline model service")


if __name__ == "__main__":
    check_contract(json.load(sys.stdin))
    print("AI lab Compose static isolation contract: valid (not runtime verified)")
