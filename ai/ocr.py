"""
OCR layer for ECHO (Tesseract via pytesseract).

pytesseract is only a Python wrapper: the Tesseract engine itself must be
installed separately. This module finds the engine, preprocesses the image,
runs OCR, and never raises into the web layer. Every call returns a dict with
``ok`` and either ``text`` or a friendly ``error``.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

log = logging.getLogger("echo.ocr")

try:
    import pytesseract
except ImportError:  # pragma: no cover - handled gracefully at runtime
    pytesseract = None

NOT_INSTALLED_MESSAGE = "Tesseract OCR is not installed or configured."

# Common install locations on Windows. TESSERACT_CMD (environment variable)
# always wins, so users with a custom location can point ECHO at it.
_WINDOWS_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
]

_status_cache: dict | None = None


def _locate_tesseract() -> str | None:
    env = os.environ.get("TESSERACT_CMD")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for candidate in _WINDOWS_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def ocr_status(refresh: bool = False) -> dict:
    """Return ``{"available": bool, "version": str|None, "path": str|None, "message": str}``."""
    global _status_cache
    if _status_cache is not None and not refresh:
        return _status_cache
    status = {"available": False, "version": None, "path": None, "message": NOT_INSTALLED_MESSAGE}
    if pytesseract is None:
        status["message"] = "The pytesseract package is not installed (pip install -r requirements.txt)."
    else:
        cmd = _locate_tesseract()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
            try:
                version = str(pytesseract.get_tesseract_version())
                status.update(available=True, version=version, path=cmd, message="Connected")
            except Exception as exc:  # engine present but not runnable
                log.warning("Tesseract found at %s but could not run: %s", cmd, exc)
    _status_cache = status
    return status


def preprocess(image: Image.Image) -> Image.Image:
    """Grayscale, fix orientation, upscale small images and boost contrast."""
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    gray = ImageOps.grayscale(image)
    width, height = gray.size
    if max(width, height) < 1400:  # Tesseract reads larger text more reliably
        scale = 1400 / max(width, height)
        gray = gray.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    return gray.filter(ImageFilter.SHARPEN)


def clean_text(text: str) -> str:
    """Normalise OCR output: unify dashes/quotes, drop junk, collapse blank lines."""
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\x0c", "")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip(" |_~`")
        if len(re.sub(r"[^A-Za-z0-9]", "", line)) >= 2:
            lines.append(line)
    return "\n".join(lines).strip()


def extract_text(image_path: str | Path) -> dict:
    """Run OCR on an image file. Returns ``{"ok", "text"}`` or ``{"ok": False, "error"}``."""
    status = ocr_status()
    if not status["available"]:
        return {"ok": False, "error": status["message"], "code": "ocr_unavailable"}
    try:
        with Image.open(image_path) as img:
            prepared = preprocess(img)
        # psm 6 = assume a uniform block of text; psm 3 (auto) as fallback.
        text = pytesseract.image_to_string(prepared, config="--oem 3 --psm 6")
        cleaned = clean_text(text)
        if len(cleaned) < 8:
            alt = clean_text(pytesseract.image_to_string(prepared, config="--oem 3 --psm 3"))
            if len(alt) > len(cleaned):
                cleaned = alt
        if not cleaned:
            return {"ok": False, "error": "ECHO couldn't read any text in this image. Try a sharper, well-lit photo.",
                    "code": "no_text"}
        return {"ok": True, "text": cleaned}
    except UnidentifiedImageError:
        return {"ok": False, "error": "This file doesn't look like a valid image.", "code": "bad_image"}
    except Exception as exc:
        log.error("OCR failed: %s", exc.__class__.__name__)
        return {"ok": False, "error": "Something went wrong while reading the image.", "code": "ocr_error"}
