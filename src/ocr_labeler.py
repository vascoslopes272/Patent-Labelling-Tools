"""
ocr_labeler.py — OCR figure labels from patent drawing images.

Runs pytesseract on the top and/or bottom crop regions of each image
to detect a figure token such as "FIG. 1" or "FIG. 3A".

Public API
----------
ocr_figure_label(img_path, cfg) → str | None
    Returns the normalised figure token (e.g. "FIG. 1") or None if not found.
"""

import re
from pathlib import Path

from PIL import Image


_FIG_PATTERN = re.compile(r"FIG\.?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)


def _crop_region(img: Image.Image, region: str, fraction: float = 0.22) -> Image.Image:
    """Return the top or bottom strip of img (default 22% of height)."""
    w, h = img.size
    strip = max(int(h * fraction), 40)   # at least 40px for legible OCR
    if region == "top":
        return img.crop((0, 0, w, strip))
    if region == "bottom":
        return img.crop((0, h - strip, w, h))
    return img


def _extract_token(text: str) -> str | None:
    """Return the first 'FIG. N[A]' token found in OCR text, or None."""
    m = _FIG_PATTERN.search(text)
    if m:
        return f"FIG. {m.group(1).upper()}"
    return None


def ocr_figure_label(img_path: Path, cfg: dict) -> str | None:
    """
    Run pytesseract on the label_crops regions of an image.

    Parameters
    ----------
    img_path : path to the image file
    cfg      : full config dict (reads cfg["ocr"]["label_crops"])

    Returns
    -------
    Detected figure token (e.g. "FIG. 3A") or None.
    """
    crops = cfg["ocr"].get("label_crops", ["bottom", "top"])
    try:
        img = Image.open(img_path).convert("L")   # greyscale → better OCR accuracy
    except Exception as exc:
        print(f"    OCR: cannot open {Path(img_path).name}: {exc}")
        return None

    import pytesseract  # lazy import — not needed until OCR is actually called

    for region in crops:
        snippet = _crop_region(img, region)
        text = pytesseract.image_to_string(snippet, config="--psm 6")
        token = _extract_token(text)
        if token:
            return token

    return None
