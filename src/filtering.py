"""
filtering.py — filter out bad, blank, or duplicate drawings (Stage 03, stub).

Removes images that are blank, too small, or near-duplicate perceptual hashes
before feeding them to DINOv2, keeping only clean, informative figures.

Public API (to be implemented)
-------------------------------
is_blank(img, threshold)        → bool
is_too_small(img, min_px)       → bool
hash_image(img)                 → str   (perceptual hash for dedup)
filter_patent(patent_id, cfg)   → list[Path]   (paths that pass all filters)
"""

from pathlib import Path
from PIL import Image


def is_blank(img: Image.Image, threshold: float = 0.98) -> bool:
    """
    Return True if the image is nearly uniform (blank page / solid fill).

    TODO: convert to greyscale, compute pixel variance; if variance < threshold
          (after normalisation) classify as blank.
    """
    raise NotImplementedError("Stage 03: is_blank not yet implemented")


def is_too_small(img: Image.Image, min_px: int = 50) -> bool:
    """
    Return True if either dimension is smaller than min_px.

    TODO: return min(img.size) < min_px
    """
    raise NotImplementedError("Stage 03: is_too_small not yet implemented")


def hash_image(img: Image.Image) -> str:
    """
    Return a perceptual hash string for near-duplicate detection.

    TODO: implement using imagehash.dhash(img) or similar.
    """
    raise NotImplementedError("Stage 03: hash_image not yet implemented")


def filter_patent(patent_id: str, cfg: dict) -> list[Path]:
    """
    Apply all filters to the processed images for one patent.

    Reads from cfg["paths"]["processed"] / patent_id.
    Returns the list of image Paths that pass all filters (blank / size / dedup).

    TODO: iterate images, call is_blank + is_too_small + hash_image,
          return survivors sorted by filename.
    """
    raise NotImplementedError("Stage 03: filter_patent not yet implemented")
