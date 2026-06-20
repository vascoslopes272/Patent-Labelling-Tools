"""
cv_utils.py — small, dependency-free geometry and binarization primitives shared
across the figure_detection / figure_labeling / figure_cropping pipeline.

Kept separate so there's exactly one ink/background separator and one set of
box-geometry helpers in the codebase, instead of each pipeline stage reimplementing
its own threshold or overlap check.
"""

from __future__ import annotations

import cv2
import numpy as np

# ─── Binarization ───────────────────────────────────────────────────────────
# One ink/background separator used everywhere. Otsu picks the threshold per image,
# so it stays correct on faint/anti-aliased line-art where a fixed `< 80` cutoff
# misses light-gray strokes and finds whitespace gaps straight through real drawing.


def to_gray(img: np.ndarray) -> np.ndarray:
    """Grayscale view of a BGR or already-gray array (no copy when already gray)."""
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def ink_mask(img: np.ndarray) -> np.ndarray:
    """
    Boolean mask, True where there is ink (a drawing stroke / text), via Otsu.
    Replaces the scattered ``gray < 80`` / fixed-threshold binarizations so light
    line-art is handled consistently. Returns all-False for an empty/degenerate crop.
    """
    gray = to_gray(img)
    if gray.size == 0 or gray.shape[0] < 2 or gray.shape[1] < 2:
        return np.zeros(gray.shape, dtype=bool)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return bw.astype(bool)


# ─── Box geometry ───────────────────────────────────────────────────────────

def iou(a: list[int], b: list[int]) -> float:
    """Intersection-over-union for two xyxy boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def union_box(boxes: list[list[int]]) -> list[int]:
    """Return the bounding box that contains all input xyxy boxes."""
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def x_overlap(a: list[int], b: list[int]) -> int:
    """Horizontal overlap in pixels between two xyxy boxes."""
    return max(0, min(a[2], b[2]) - max(a[0], b[0]))


def box_gap(a: list[int], b: list[int]) -> int:
    """Max of the horizontal and vertical gap (px) between two xyxy boxes; 0 if they overlap/touch."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    dx = max(0, max(ax1, bx1) - min(ax2, bx2))
    dy = max(0, max(ay1, by1) - min(ay2, by2))
    return max(dx, dy)
