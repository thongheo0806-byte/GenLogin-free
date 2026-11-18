"""Validated local profile settings. No anti-detection guarantees are made."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse
from uuid import uuid4


@dataclass
class Profile:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "New profile"
    group_name: str = "Default"
    tags: str = ""
    browser: str = "chrome"  # chrome, msedge, chromium
    start_url: str = "https://example.com"
    locale: str = "en-US"
    timezone_id: str = "UTC"
    user_agent: str = ""
    viewport_width: int = 1280
    viewport_height: int = 800
    proxy_scheme: str = ""  # http, socks5; empty disables proxy
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_username: str = ""
    created_at: str = ""
    updated_at: str = ""

    def validate(self) -> None:
        if not self.name.strip() or len(self.name) > 100:
            raise ValueError("Profile name must be between 1 and 100 characters")
        if len(self.group_name) > 100 or len(self.tags) > 500:
            raise ValueError("Group or tags are too long")
        if self.browser not in {"chrome", "msedge", "chromium"}:
            raise ValueError("Unknown browser engine")
        valid_http_url(self.start_url)
        if not self.locale or len(self.locale) > 35 or not self.timezone_id or len(self.timezone_id) > 100:
            raise ValueError("Invalid locale/timezone")
        if self.user_agent and len(self.user_agent) > 1024:
            raise ValueError("User agent too long")
        if not 320 <= int(self.viewport_width) <= 7680 or not 240 <= int(self.viewport_height) <= 4320:
            raise ValueError("Viewport is out of range")
        if self.proxy_scheme:
            if self.proxy_scheme not in {"http", "socks5"}:
                raise ValueError("Proxy scheme must be http or socks5")
            if not self.proxy_host or any(c in self.proxy_host for c in " /\\@\n\r\t"):
                raise ValueError("Invalid proxy host")
            if not 1 <= int(self.proxy_port) <= 65535:
                raise ValueError("Proxy port out of range")
        elif self.proxy_host or self.proxy_port or self.proxy_username:
            raise ValueError("Select a proxy type or clear all proxy settings")

    def public_dict(self) -> dict:
        """No proxy passwords or browsing-session data ever leave the local store."""
        return asdict(self)


def valid_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Only http(s) URLs without embedded credentials are accepted")
    if len(value) > 4096 or any(c in value for c in "\r\n\x00"):
        raise ValueError("Invalid URL")
    return value


def validated_steps(source: object) -> list[dict]:
    """Strict, code-free automation schema; no arbitrary JS/shell execution."""
    if not isinstance(source, list) or not 1 <= len(source) <= 100:
        raise ValueError("Workflow must be a list of 1-100 steps")
    kinds = {
        "goto": ("url",), "click": ("selector",), "fill": ("selector", "text"),
        "wait": ("seconds",), "wait_for": ("selector",),
        "screenshot": (), "extract_text": ("selector",),
        "press": ("selector", "key"), "check": ("selector",),
        "uncheck": ("selector",), "select_option": ("selector", "value"),
        "scroll_into_view": ("selector",),
    }
    steps = []
    for number, item in enumerate(source, 1):
        if not isinstance(item, dict) or item.get("action") not in kinds:
            raise ValueError(f"Step {number}: unknown action")
        action = item["action"]
        allowed = {"action", *kinds[action]}
        if set(item) != allowed:
            raise ValueError(f"Step {number}: unexpected or missing fields")
        for key in kinds[action]:
            value = item[key]
            if key == "seconds":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 30:
                    raise ValueError(f"Step {number}: wait must be 0-30 seconds")
            elif not isinstance(value, str) or not value or len(value) > 4096:
                raise ValueError(f"Step {number}: invalid {key}")
        if action == "goto":
            valid_http_url(item["url"])
        if "selector" in item and any(c in item["selector"] for c in "\x00\r\n"):
            raise ValueError(f"Step {number}: invalid selector")
        steps.append(item.copy())
    return steps
