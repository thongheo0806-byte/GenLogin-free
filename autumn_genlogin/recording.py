"""Consent-based DOM recording, redaction and explicit replay review.

OpenAdapt-inspired design principles, independently implemented:
observe only the chosen browser session, prefer structural DOM selectors,
discard typed values and secret-bearing option values, and require an
explicit human review before turning a demonstration into executable steps.
No desktop-wide input hooks, image streams, or cloud capture.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass

from .models import validated_steps

MAX_RECORDED_STEPS = 100
ALLOWED_RECORDED_ACTIONS = frozenset(
    {"click", "fill", "select_option", "check", "uncheck", "press"}
)
ALLOWED_RECORDED_KEYS = frozenset({"Enter", "Tab", "Escape"})


def sanitize_recorded_event(payload: object, *, allow_context: bool = False) -> dict | None:
    """Return a strict, value-free action, ignoring untrusted page extras.

    A website can invoke an exposed Playwright binding itself. Never allow
    such calls to smuggle navigation, screenshot, JS, arbitrary steps, or
    user-entered values into the recorded workflow.
    """
    if not isinstance(payload, dict):
        return None
    kind = payload.get("action")
    if kind not in ALLOWED_RECORDED_ACTIONS:
        return None
    selector = payload.get("selector")
    if not isinstance(selector, str) or not selector or len(selector) > 240:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in selector):
        return None
    if kind == "fill":
        step = {"action": "fill", "selector": selector, "text": ""}
    elif kind == "select_option":
        step = {"action": "select_option", "selector": selector, "value": "REVIEW_OPTION"}
    elif kind == "press":
        key = payload.get("key")
        if key not in ALLOWED_RECORDED_KEYS:
            return None
        step = {"action": "press", "selector": selector, "key": key}
    else:
        step = {"action": kind, "selector": selector}
    if allow_context and "tab_index" in payload:
        # Stored recorder context is derived from Playwright source objects;
        # page-supplied context fields are ALWAYS discarded by default.
        step["tab_index"] = payload["tab_index"]
        step["tab_count"] = payload.get("tab_count")
        if "tab_token" in payload:
            step["tab_token"] = payload["tab_token"]
        if "frames" in payload:
            step["frames"] = payload["frames"]
        if "frame_tokens" in payload:
            step["frame_tokens"] = payload["frame_tokens"]
    try:
        return validated_steps([step])[0]
    except (TypeError, ValueError):
        return None


def append_recorded_event(events: list[dict], payload: object, *,
                          context: dict | None = None) -> bool:
    if len(events) >= MAX_RECORDED_STEPS:
        return False
    # Never trust a page-provided tab/frame index. Only Playwright's binding
    # source may supply context, independently of the untrusted payload.
    item = sanitize_recorded_event(payload)
    if item is None:
        return False
    if context is not None:
        if not isinstance(context, dict):
            return False
        candidate = {**item, **context}
        item = sanitize_recorded_event(candidate, allow_context=True)
        if item is None:
            return False
    # Consecutive browser 'change' events often report the same field twice.
    # Clicks are never deduplicated: a repeated click can be meaningful.
    if item["action"] in {"fill", "select_option", "check", "uncheck"}:
        if events and events[-1] == item:
            return False
    events.append(item)
    return True


@dataclass(frozen=True)
class RecordingReview:
    steps: list[dict]
    redacted_fields: int
    navigation_boundaries: int
    ignored_tabs: int
    warnings: tuple[str, ...]

    def public_summary(self) -> dict:
        return {
            "step_count": len(self.steps),
            "redacted_fields": self.redacted_fields,
            "navigation_boundaries": self.navigation_boundaries,
            "ignored_tabs": self.ignored_tabs,
            "requires_review": True,
            "warnings": list(self.warnings),
        }


def review_recording(events: list[dict], *, navigation_boundaries: int = 0,
                     ignored_tabs: int = 0) -> RecordingReview:
    if not isinstance(events, list) or len(events) > MAX_RECORDED_STEPS:
        raise ValueError("Recording exceeds maximum 100 reviewed steps")
    if type(navigation_boundaries) is not int or navigation_boundaries < 0:
        raise ValueError("Invalid navigation boundary count")
    if type(ignored_tabs) is not int or not 0 <= ignored_tabs <= 1000:
        raise ValueError("Invalid ignored-tab count")
    # Re-scrub all events: no path through importing a recording may restore
    # typed input values sent by a malicious page or outdated recorder.
    cleaned = [sanitize_recorded_event(x, allow_context=True) for x in events]
    if any(x is None for x in cleaned):
        raise ValueError("Recorded event is not eligible for replay")
    redacted = sum(x["action"] in {"fill", "select_option"} for x in cleaned)
    warnings = ["Review every action and its target before replay; recording is not proof of success."]
    if redacted:
        warnings.append(
            f"{redacted} input/select actions have intentionally blank or placeholder values."
        )
    if navigation_boundaries:
        warnings.append(
            f"{navigation_boundaries} page load(s) observed: URLs were intentionally not captured; "
            "add explicit, reviewed navigation checks before replay."
        )
    if ignored_tabs:
        warnings.append(
            f"{ignored_tabs} browser tab(s) had unrecordable actions or closed during capture."
        )
    if any("tab_index" in x for x in cleaned):
        warnings.append(
            "Tab positions and tab counts must match the recording; mismatches fail closed. "
            "Legacy ordinal-only recordings are refused at runtime. "
            "Live identity tokens bind only to the same open browser session; "
            "a restarted session requires recording again."
        )
    if any(x.get("frames") for x in cleaned):
        warnings.append(
            "Iframe selector chains must match the current DOM; cross-origin/frame changes may "
            "prevent replay. Frame identity tokens also require the original live frames."
        )
    return RecordingReview(deepcopy(cleaned), redacted, navigation_boundaries,
                           ignored_tabs, tuple(warnings))
