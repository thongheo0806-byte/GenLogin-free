"""Single declaration of the supported code-free automation actions.

This registry describes the workflow/editor/recorder contract, not permission
to execute any action on arbitrary pages. Runtime scope, recorder redaction,
user consent and the isolated AI lab's narrower allowlist remain independent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable
from urllib.parse import urlparse


def valid_http_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("URL must be a string")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Only http(s) URLs without embedded credentials are accepted")
    if len(value) > 4096 or any(c in value for c in "\r\n\x00"):
        raise ValueError("Invalid URL")
    return value


def _validate_navigation(item: dict, number: int) -> None:
    valid_http_url(item["url"])


def _validate_template(item: dict, number: int) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", item["template_id"]):
        raise ValueError(f"Step {number}: invalid image template ID")


@dataclass(frozen=True)
class Action:
    fields: tuple[str, ...]
    recordable: bool = False
    validators: tuple[Callable[[dict, int], None], ...] = ()


# Preserve existing editor order as well as the exact field sets.
ACTIONS = MappingProxyType({
    "goto": Action(("url",), validators=(_validate_navigation,)),
    "click": Action(("selector",), recordable=True),
    "click_image": Action(("template_id", "confidence"), validators=(_validate_template,)),
    "fill": Action(("selector", "text"), recordable=True),
    "wait": Action(("seconds",)),
    "wait_for": Action(("selector",)),
    "screenshot": Action(()),
    "extract_text": Action(("selector",)),
    "press": Action(("selector", "key"), recordable=True),
    "check": Action(("selector",), recordable=True),
    "uncheck": Action(("selector",), recordable=True),
    "select_option": Action(("selector", "value"), recordable=True),
    "scroll_into_view": Action(("selector",)),
})

NUMERIC_FIELDS = frozenset({"seconds", "confidence"})
