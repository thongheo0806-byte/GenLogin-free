"""Local, opt-in OpenCV image template matching for browser screenshots.

Templates are explicit user-owned PNG assets stored by SHA-256 under the app
home, not arbitrary script paths in workflow JSON. Matching only inspects
in-memory Playwright viewport screenshots and never calls a network service.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

MAX_TEMPLATE_BYTES = 256 * 1024
MAX_TEMPLATES = 200
MAX_SCREEN_PIXELS = 3840 * 2160
MIN_DIM, MAX_DIM = 16, 256
TEMPLATE_ID = re.compile(r"[0-9a-f]{64}\Z")


def _cv():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Image click requires: python -m pip install -r requirements-vision.txt") from exc
    return cv2, np


def _decode(raw: bytes, *, template: bool):
    cv2, np = _cv()
    if not isinstance(raw, bytes) or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Image must be a PNG file")
    if template and len(raw) > MAX_TEMPLATE_BYTES:
        raise ValueError("Template PNG exceeds 256 KiB")
    # cv2's PNG decoder reads from memory, not a user-controlled image path.
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or len(img.shape) != 2:
        raise ValueError("Unable to decode PNG")
    height, width = img.shape
    if template:
        if not (MIN_DIM <= height <= MAX_DIM and MIN_DIM <= width <= MAX_DIM):
            raise ValueError("Template dimensions must be between 16 and 256 pixels")
        if float(img.std()) < 12.0:
            raise ValueError("Low-detail template would produce unreliable clicks")
    elif height * width > MAX_SCREEN_PIXELS:
        raise ValueError("Viewport screenshot exceeds the 3840x2160 match limit")
    return img


class ImageTemplateLibrary:
    def __init__(self, store):
        self.directory = store.base / "image-templates"
        self.directory.mkdir(parents=True, exist_ok=True)

    def import_png(self, source: Path) -> str:
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError("Select a regular, non-linked PNG file")
        if source.stat().st_size > MAX_TEMPLATE_BYTES:
            raise ValueError("Template PNG exceeds 256 KiB")
        raw = source.read_bytes()
        _decode(raw, template=True)
        ident = hashlib.sha256(raw).hexdigest()
        target = self.directory / (ident + ".png")
        if not target.exists() and len(list(self.directory.glob("*.png"))) >= MAX_TEMPLATES:
            raise ValueError("Maximum 200 saved image templates")
        try:
            with target.open("xb") as dest:
                dest.write(raw)
        except FileExistsError:
            if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != ident:
                raise ValueError("Existing template file failed integrity check")
        return ident

    def read(self, template_id: str) -> bytes:
        if not isinstance(template_id, str) or not TEMPLATE_ID.fullmatch(template_id):
            raise ValueError("Invalid image template ID")
        target = self.directory / (template_id + ".png")
        if target.is_symlink() or not target.is_file():
            raise ValueError("Image template not found")
        if target.stat().st_size > MAX_TEMPLATE_BYTES:
            raise ValueError("Template exceeds maximum size")
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != template_id:
            raise ValueError("Image template was modified after import")
        _decode(data, template=True)
        return data


def find_image_center(screenshot_png: bytes, template_png: bytes,
                      confidence: float = 0.94) -> tuple[float, float]:
    """Return CSS viewport coordinates only for a sufficiently unique match.

    Screenshot must use Playwright's scale='css' to avoid device-pixel-ratio
    errors. Ambiguous/repeated templates fail closed instead of clicking.
    """
    if isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not 0.90 <= confidence <= 1:
        raise ValueError("Confidence must be between 0.90 and 1.00")
    cv2, np = _cv()
    template = _decode(template_png, template=True)
    screenshot = _decode(screenshot_png, template=False)
    th, tw = template.shape
    sh, sw = screenshot.shape
    if th > sh or tw > sw:
        raise ValueError("Template is larger than browser viewport")
    # Disable excess OpenCV worker threads to avoid resource contention when
    # multiple browser profiles perform image matching concurrently.
    cv2.setNumThreads(1)
    matches = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
    _min, best, _minloc, location = cv2.minMaxLoc(matches)
    if not np.isfinite(best) or best < confidence:
        raise ValueError("No sufficiently confident image match in viewport")
    # Discard the same physical target's overlapping nearby matches.
    # A second far-away high-confidence location is an ambiguous click.
    others = matches.copy()
    x, y = location
    ex, ey = max(1, tw // 2), max(1, th // 2)
    others[max(0,y-ey):min(others.shape[0],y+ey+1),
           max(0,x-ex):min(others.shape[1],x+ex+1)] = -1
    if others.size and float(others.max()) >= confidence:
        raise ValueError("Multiple matching images found; crop a more distinctive template")
    return (x + tw / 2, y + th / 2)
