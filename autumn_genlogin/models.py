"""Validated local profile settings. No anti-detection guarantees are made."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from ipaddress import ip_address
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlparse
from uuid import uuid4


@dataclass
class Profile:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "New profile"
    group_name: str = "Default"
    tags: str = ""
    browser: str = "chrome"  # chromium, chrome, msedge, firefox, webkit
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
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError("Profile name must be between 1 and 100 characters")
        if not isinstance(self.group_name, str) or not isinstance(self.tags, str) or len(self.group_name) > 100 or len(self.tags) > 500:
            raise ValueError("Group or tags are invalid")
        if self.browser not in {"chrome", "msedge", "chromium", "firefox", "webkit"}:
            raise ValueError("Unknown browser engine")
        valid_http_url(self.start_url)
        if not isinstance(self.locale, str) or not re.fullmatch(
            r"[a-z]{2,3}(?:-[a-z]{4})?(?:-[a-z]{2}|-[0-9]{3})?", self.locale, re.IGNORECASE
        ):
            raise ValueError("Locale must be a valid language/region tag (for example vi-VN)")
        # BCP-47 tags are case-insensitive; pass a canonical form to Chromium.
        locale_parts = self.locale.split("-")
        self.locale = "-".join([locale_parts[0].lower()] + [
            part.title() if len(part) == 4 else part.upper() if len(part) == 2 else part
            for part in locale_parts[1:]
        ])
        if not isinstance(self.timezone_id, str) or len(self.timezone_id) > 100:
            raise ValueError("Invalid timezone")
        try:
            ZoneInfo(self.timezone_id)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise ValueError("Unknown IANA timezone (install tzdata on Windows)") from exc
        if not isinstance(self.user_agent, str) or len(self.user_agent) > 1024:
            raise ValueError("Invalid user agent")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (self.viewport_width, self.viewport_height)) or not 320 <= self.viewport_width <= 7680 or not 240 <= self.viewport_height <= 4320:
            raise ValueError("Viewport is out of range")
        if self.proxy_scheme:
            if self.proxy_scheme not in {"http", "socks5"}:
                raise ValueError("Proxy scheme must be http or socks5")
            if not isinstance(self.proxy_host, str) or not self.proxy_host or any(c in self.proxy_host for c in " /\\@\n\r\t?#%[]"):
                raise ValueError("Invalid proxy host")
            try:
                ip_address(self.proxy_host)  # IPv4/IPv6 literal
            except ValueError:
                # Strict ASCII DNS labels, optionally with one final root dot.
                host = self.proxy_host.removesuffix(".")
                labels = host.split(".")
                if (len(host) > 253 or not host or all(c in "0123456789." for c in host)
                    or any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                           for label in labels)):
                    raise ValueError("Proxy host must be a valid DNS name or IPv4/IPv6 literal")
            if not isinstance(self.proxy_port, int) or isinstance(self.proxy_port, bool) or not 1 <= self.proxy_port <= 65535:
                raise ValueError("Proxy port out of range")
            if not isinstance(self.proxy_username, str):
                raise ValueError("Invalid proxy username")
            if self.proxy_scheme == "socks5" and self.proxy_username:
                raise ValueError("Chromium cannot authenticate SOCKS5 proxies with username/password")
        elif self.proxy_host or self.proxy_port or self.proxy_username:
            raise ValueError("Select a proxy type or clear all proxy settings")

    def public_dict(self) -> dict:
        """No proxy passwords or browsing-session data ever leave the local store."""
        return asdict(self)


def valid_http_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("URL must be a string")
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
        "goto": ("url",), "click": ("selector",), "click_image": ("template_id", "confidence"), "fill": ("selector", "text"),
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
        # Recorded DOM actions can target a precise tab slot and nested frame.
        # Legacy steps without this context still target the first tab.
        if "tab_index" in item or "tab_count" in item or "frames" in item:
            if "selector" not in kinds[action]:
                raise ValueError(f"Step {number}: tab/frame context requires a DOM selector")
            allowed.update({"tab_index", "tab_count"})
            if "frames" in item:
                allowed.add("frames")
        if set(item) != allowed:
            raise ValueError(f"Step {number}: unexpected or missing fields")
        for key in kinds[action]:
            value = item[key]
            if key in {"seconds", "confidence"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"Step {number}: {key} must be numeric")
                if key == "seconds" and not 0 <= value <= 30:
                    raise ValueError(f"Step {number}: wait must be 0-30 seconds")
                if key == "confidence" and not 0.90 <= value <= 1:
                    raise ValueError(f"Step {number}: image confidence must be 0.90-1.00")
            elif not isinstance(value, str) or (not value and key != "text") or len(value) > 4096:
                raise ValueError(f"Step {number}: invalid {key}")
        if "tab_index" in item:
            tab, count = item["tab_index"], item["tab_count"]
            if (type(tab) is not int or type(count) is not int
                    or not 1 <= count <= 12 or not 0 <= tab < count):
                raise ValueError(f"Step {number}: invalid tab position or count")
            frames = item.get("frames", [])
            if (not isinstance(frames, list) or len(frames) > 4
                    or any(not isinstance(sel, str) or not sel or len(sel) > 240
                           or any(ord(ch) < 32 or ord(ch) == 127 for ch in sel)
                           for sel in frames)):
                raise ValueError(f"Step {number}: invalid iframe selector path")
        if action == "goto":
            valid_http_url(item["url"])
        if action == "click_image" and not re.fullmatch(r"[0-9a-f]{64}", item["template_id"]):
            raise ValueError(f"Step {number}: invalid image template ID")
        if "selector" in item and any(c in item["selector"] for c in "\x00\r\n"):
            raise ValueError(f"Step {number}: invalid selector")
        steps.append(item.copy())
    return steps
