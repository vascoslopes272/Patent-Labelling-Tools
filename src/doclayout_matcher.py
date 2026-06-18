"""
doclayout_matcher.py — Hypothesis 2: DocLayout-YOLO + EasyOCR figure extraction.

Free, local alternative to the Claude API route. DocLayout-YOLO (a document-layout
detector) natively finds the `figure` regions on each patent drawing sheet — the exact
task the Qwen2.5-VL model failed at — and the `figure_caption` regions. EasyOCR then
reads each caption to recover the `FIG. N` label for naming.

Raw files are never modified; crops are written to the chosen output directory using the
project naming convention: ``_F<label>`` when a label is read, ``_Fu`` otherwise.

Reuses the proven YOLOv10 call pattern from
``Patent_Images_Extractor_&_FT_2.0/My_DataSet_Pipeline/src/extractor.py`` and the label
regex / naming convention from ``figure_matcher.py`` / ``claude_extractor.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# ─── Configuration ────────────────────────────────────────────────────────────

# Existing weights from the sibling pipeline — no download needed.
DEFAULT_WEIGHTS = (
    "/home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent_Images_Extractor_&_FT_2.0/"
    "My_DataSet_Pipeline/models/doclayout_yolo_docstructbench_imgsz1024.pt"
)

YOLO_CONF    = 0.25    # lowered from 0.40 — recovers sub-figures detected at 0.25–0.39
CAPTION_CONF = 0.15    # figure_caption only — more captions survive to OCR Pass 1
                        # (figure boxes still filtered at YOLO_CONF, see detect_regions)
NMS_IOU      = 0.30    # IoU threshold for suppressing duplicate/nested figure boxes
MIN_CROP_PX  = 450     # discard crops smaller than this in either dimension (filters bad thin split slices)
IMGSZ        = 1024    # DocStructBench model was trained at 1024
CROP_PAD_PX_FIXED = 60  # fixed padding (px) around each YOLO box — enough to capture
                         # the "FIG. X" caption just outside the box without bleeding
                         # into adjacent figures on high-res sheets (replaces % padding)

# A single figure box taller than this (px) AND containing clear horizontal whitespace
# is likely a wrapper around multiple sub-figures — split it vertically.
SPLIT_HEIGHT_PX  = 1500  # only attempt split on very tall wrapper boxes
SPLIT_GAP_PX     = 120  # gap must be large enough to distinguish two-figure separation
                          # from internal whitespace within a single figure

SPLIT_WIDTH_PX     = 1500
SPLIT_GAP_PX_VERT  = 120

# Context padding around the figure box for the Qwen fallback. The caption ("FIG. n")
# is usually printed OUTSIDE the YOLO figure box — without this margin Qwen never sees it.
# 350px below matches the EasyOCR Pass-4 caption strip; smaller side/top pads catch
# rotated labels printed beside or above the drawing.
QWEN_PAD_BELOW_PX = 350
QWEN_PAD_SIDE_PX  = 150

# ── Merge parameters ──────────────────────────────────────────────────────────
# Same-label merge: if two YOLO boxes on one sheet get the same FIG. label their
# union bounding box is re-cropped as a single image (handles split rotor tips, etc.)
# Fu merge: unlabelled boxes whose vertical bands overlap AND whose horizontal gap
# is ≤ FU_MERGE_GAP_PX are merged the same way.
FU_MERGE_GAP_PX   = 200   # max horizontal gap (px) between two _Fu boxes to merge

# Vertical-strip merge: YOLO sometimes slices one figure into thin horizontal bands
# that all share the same x-span. Merge vertically-adjacent boxes whose x-spans
# overlap by ≥ VMERGE_X_OVERLAP_FRAC of the smaller box's width AND whose vertical
# gap is ≤ VMERGE_GAP_PX. Done before OCR so the full figure is cropped at once.
VMERGE_X_OVERLAP_FRAC = 0.80   # 80% x-overlap → treat as same column
VMERGE_GAP_PX         = 20     # max vertical gap (px) between two stacked boxes

# DocStructBench class names we care about (matched by NAME, not index).
_FIGURE_CLASS = "figure"
_CAPTION_CLASS = "figure_caption"

# Robust to EasyOCR misreads of the separator character:
#   "FIG. 1A"  "Fig. 2a"  "FIG 3"  "Fig_4a"  "Fig: 1"  "Fia. 2"  "Fig1"
#   "FIGURE 1A" (spelled out — e.g. US2020148347) and plural "FIGS. 2"
# Accepts any 0-2 non-alphanumeric chars between FIG[URE](S) and the number.
_FIG_KEY_RE = re.compile(r"FI[GA](?:URE)?S?[^A-Za-z0-9]{0,2}([0-9]+[A-Za-z]?)", re.IGNORECASE)

# Figure numbers above this are almost certainly component callouts (e.g. "203g")
# misread as figure labels — patents rarely have more than 50 sheets.
_MAX_FIG_NUMBER = 99

def _valid_fig_label(label: str) -> bool:
    """Return False if the numeric part of a label looks like a component callout."""
    m = re.match(r"^([0-9]+)", label)
    return bool(m) and int(m.group(1)) <= _MAX_FIG_NUMBER


# ─── Engine ───────────────────────────────────────────────────────────────────

def build_engine(weights: str = DEFAULT_WEIGHTS, device: str = "cuda:0"):
    """
    Load DocLayout-YOLO + EasyOCR once. Returns (model, reader, device, None, None).
    The last two slots are reserved for the lazy-loaded Qwen fallback (model, processor).

    Falls back to CPU if CUDA is unavailable. The EasyOCR reader downloads its
    detection/recognition models on first construction (~100 MB, one-time).
    """
    import torch
    from doclayout_yolo import YOLOv10
    import easyocr

    if device.startswith("cuda") and not torch.cuda.is_available():
        device = "cpu"

    model = YOLOv10(weights)
    model.to(device)

    reader = easyocr.Reader(["en"], gpu=device.startswith("cuda"))

    # Return a mutable list — Qwen slots (index 3, 4) are populated lazily on first OCR miss
    return [model, reader, device, None, None]


# ─── Detection ────────────────────────────────────────────────────────────────

def _iou(a: list[int], b: list[int]) -> float:
    """Intersection-over-union for two xyxy boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _union_box(boxes: list[list[int]]) -> list[int]:
    """Return the bounding box that contains all input xyxy boxes."""
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _nms_figures(figures: list[dict], iou_thresh: float = NMS_IOU) -> list[dict]:
    """
    Suppress duplicate/nested figure boxes by IoU.
    Keeps the higher-confidence box when two overlap above the threshold.
    Also removes boxes that are almost entirely contained within a larger box
    (the 'wrapper' suppression that previously merged sub-figures into one crop).
    """
    figures = sorted(figures, key=lambda f: f["conf"], reverse=True)
    kept = []
    for cand in figures:
        ca = cand["box"]
        discard = False
        for k in kept:
            ka = k["box"]
            if _iou(ca, ka) > iou_thresh:
                discard = True
                break
            # also suppress if cand is almost fully inside an already-kept box
            inter_x = max(0, min(ca[2], ka[2]) - max(ca[0], ka[0]))
            inter_y = max(0, min(ca[3], ka[3]) - max(ca[1], ka[1]))
            inter   = inter_x * inter_y
            area_c  = max(1, (ca[2] - ca[0]) * (ca[3] - ca[1]))
            if inter / area_c > 0.85:
                discard = True
                break
        if not discard:
            kept.append(cand)
    return kept


def _merge_coplanar_fragments(figures: list[dict], y_overlap_frac: float = 0.70) -> list[dict]:
    """
    Merge boxes that are side-by-side fragments of the same figure.
    YOLO sometimes slices one figure into narrow vertical columns with the same
    y-range — merge any group of boxes whose y-ranges overlap by ≥ y_overlap_frac
    of the smaller box's height into one wide union box.
    """
    if not figures:
        return figures

    merged = []
    used = [False] * len(figures)

    for i, fig in enumerate(figures):
        if used[i]:
            continue
        group = [fig]
        used[i] = True
        y1i, y2i = fig["box"][1], fig["box"][3]
        hi = y2i - y1i

        for j, other in enumerate(figures):
            if used[j]:
                continue
            y1j, y2j = other["box"][1], other["box"][3]
            hj = y2j - y1j
            # y-overlap between the two boxes
            overlap = max(0, min(y2i, y2j) - max(y1i, y1j))
            if overlap / max(1, min(hi, hj)) >= y_overlap_frac:
                group.append(other)
                used[j] = True

        if len(group) == 1:
            merged.append(fig)
        else:
            merged.append({
                "box":  _union_box([f["box"] for f in group]),
                "conf": max(f["conf"] for f in group),
            })

    return merged


def _merge_vertical_strips(figures: list[dict]) -> list[dict]:
    """
    Merge vertically-adjacent figure boxes that share the same x-span (same column).
    YOLO sometimes slices a single drawing into thin horizontal bands — this re-joins them.

    Algorithm: sort top-to-bottom; greedily extend a group while the next box
    shares ≥ VMERGE_X_OVERLAP_FRAC x-overlap with the group union AND the vertical
    gap is ≤ VMERGE_GAP_PX. Each finished group becomes one union-bbox figure.
    """
    if not figures:
        return figures

    # Sort top-to-bottom by y1
    sorted_figs = sorted(figures, key=lambda f: f["box"][1])

    groups: list[list[dict]] = []
    current = [sorted_figs[0]]

    for fig in sorted_figs[1:]:
        # Union box of current group
        gx1 = min(f["box"][0] for f in current)
        gx2 = max(f["box"][2] for f in current)
        gy2 = max(f["box"][3] for f in current)

        fx1, fy1, fx2, fy2 = fig["box"]

        # x-overlap fraction relative to the smaller width
        x_overlap = max(0, min(gx2, fx2) - max(gx1, fx1))
        smaller_w = min(gx2 - gx1, fx2 - fx1)
        x_frac = x_overlap / smaller_w if smaller_w > 0 else 0

        v_gap = fy1 - gy2   # positive = gap, negative = overlap

        if x_frac >= VMERGE_X_OVERLAP_FRAC and v_gap <= VMERGE_GAP_PX:
            current.append(fig)
        else:
            groups.append(current)
            current = [fig]
    groups.append(current)

    merged = []
    for grp in groups:
        merged.append({
            "box":  _union_box([f["box"] for f in grp]),
            "conf": max(f["conf"] for f in grp),
        })
    return merged


def _split_large_figure(fig: dict, img_gray: np.ndarray) -> list[dict]:
    """
    If a figure box is suspiciously tall (YOLO wrapped multiple sub-figures into one),
    find horizontal whitespace rows inside the crop and split at the largest gap.
    Returns a list of sub-figure dicts (may be just [fig] if no good split point found).
    """
    x1, y1, x2, y2 = fig["box"]
    h = y2 - y1
    if h < SPLIT_HEIGHT_PX:
        return [fig]

    crop = img_gray[y1:y2, x1:x2]
    # Row is a "gap" if fewer than 1.5% of pixels are genuinely black (< 80).
    # Using a strict darkness threshold separates real whitespace/caption-text gaps
    # from drawing content, even in light design-patent drawings with thin lines.
    row_white = np.mean(crop < 80, axis=1) < 0.015

    # Find runs of consecutive white rows
    gaps: list[tuple[int, int]] = []  # (start_row, end_row) relative to crop
    in_gap, gap_start = False, 0
    for r, white in enumerate(row_white):
        if white and not in_gap:
            in_gap, gap_start = True, r
        elif not white and in_gap:
            run = r - gap_start
            if run >= SPLIT_GAP_PX:
                gaps.append((gap_start, r))
            in_gap = False
    if in_gap and (len(row_white) - gap_start) >= SPLIT_GAP_PX:
        gaps.append((gap_start, len(row_white)))

    if not gaps:
        return [fig]

    # Split once at the midpoint of the largest gap — no recursion
    best = max(gaps, key=lambda g: g[1] - g[0])
    split_y = y1 + (best[0] + best[1]) // 2

    top = {"box": [x1, y1, x2, split_y], "conf": fig["conf"]}
    bot = {"box": [x1, split_y, x2, y2],  "conf": fig["conf"]}
    return [top, bot]


def _split_wide_figure(fig: dict, img_gray: np.ndarray) -> list[dict]:
    """
    If a figure box is suspiciously wide (YOLO wrapped multiple side-by-side
    sub-figures into one — e.g. FIG. 8A/8B/8C on a landscape sheet), find vertical
    whitespace columns inside the crop and split at the widest gap.
    Returns a list of sub-figure dicts (may be just [fig] if no good split point found).
    """
    x1, y1, x2, y2 = fig["box"]
    w = x2 - x1
    if w < SPLIT_WIDTH_PX:
        return [fig]

    crop = img_gray[y1:y2, x1:x2]
    # Column is a "gap" if fewer than 1.5% of pixels are genuinely black (< 80)
    col_white = np.mean(crop < 80, axis=0) < 0.015

    # Find runs of consecutive white columns
    gaps: list[tuple[int, int]] = []  # (start_col, end_col) relative to crop
    in_gap, gap_start = False, 0
    for c, white in enumerate(col_white):
        if white and not in_gap:
            in_gap, gap_start = True, c
        elif not white and in_gap:
            run = c - gap_start
            if run >= SPLIT_GAP_PX_VERT:
                gaps.append((gap_start, c))
            in_gap = False
    if in_gap and (len(col_white) - gap_start) >= SPLIT_GAP_PX_VERT:
        gaps.append((gap_start, len(col_white)))

    if not gaps:
        return [fig]

    # Split once at the midpoint of the largest gap — no recursion
    best = max(gaps, key=lambda g: g[1] - g[0])
    split_x = x1 + (best[0] + best[1]) // 2

    left  = {"box": [x1, y1, split_x, y2], "conf": fig["conf"]}
    right = {"box": [split_x, y1, x2, y2], "conf": fig["conf"]}
    return [left, right]


def detect_regions(model, img_path: Path, device: str = "cuda:0") -> tuple[list[dict], list[dict]]:
    """
    Run DocLayout-YOLO on one sheet and split detections into figures and captions.

    Returns (figures, captions); each item is {"box": [x1, y1, x2, y2], "conf": float}
    in original-image pixel coordinates.

    Post-processing:
    - NMS dedup: removes overlapping/nested boxes (lowered conf threshold picks up more)
    - Large-crop split: wrapper boxes enclosing multiple sub-figures are split at whitespace
    """
    img_pil  = Image.open(img_path).convert("RGB")
    img_np   = np.array(img_pil)
    img_gray = np.array(img_pil.convert("L"))

    # Run at the lower CAPTION_CONF threshold so more figure_caption boxes survive,
    # then filter figure boxes back up to YOLO_CONF manually (captions get the break,
    # figures keep the stricter threshold that was already tuned).
    results = model.predict(source=img_np, imgsz=IMGSZ, conf=CAPTION_CONF,
                            device=device, verbose=False)

    figures: list[dict] = []
    captions: list[dict] = []
    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            cls_name = model.names[int(box.cls[0])].lower()
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            conf = float(box.conf[0])
            rec = {"box": [x1, y1, x2, y2], "conf": conf}
            if cls_name == _FIGURE_CLASS:
                if conf >= YOLO_CONF:
                    figures.append(rec)
            elif cls_name == _CAPTION_CLASS:
                captions.append(rec)

    # NMS: remove duplicate/nested figure boxes
    figures = _nms_figures(figures)

    # Merge side-by-side column fragments of the same figure into one wide box
    figures = _merge_coplanar_fragments(figures)

    # Filter out boxes that are tiny relative to the largest box on the sheet —
    # small detections are annotation artifacts, not real figures
    if len(figures) > 1:
        max_area = max((f["box"][2]-f["box"][0]) * (f["box"][3]-f["box"][1]) for f in figures)
        figures  = [f for f in figures
                    if (f["box"][2]-f["box"][0]) * (f["box"][3]-f["box"][1]) >= 0.12 * max_area]

    # Only split if YOLO returned exactly one box (a wrapper around multiple sub-figures).
    # When YOLO already found 2+ individual boxes, trust them — splitting further creates noise.
    if len(figures) == 1:
        fig = figures[0]
        h_box = fig["box"][3] - fig["box"][1]
        w_box = fig["box"][2] - fig["box"][0]

        halves = _split_large_figure(fig, img_gray)
        if len(halves) == 2:
            h0 = halves[0]["box"][3] - halves[0]["box"][1]
            h1 = halves[1]["box"][3] - halves[1]["box"][1]
            # Reject split if one half is less than 20% of the other — it's a sliver
            if min(h0, h1) >= 0.20 * max(h0, h1):
                figures = halves

        if len(figures) == 1:
            halves = _split_wide_figure(fig, img_gray)
            if len(halves) == 2:
                w0 = halves[0]["box"][2] - halves[0]["box"][0]
                w1 = halves[1]["box"][2] - halves[1]["box"][0]
                if min(w0, w1) >= 0.20 * max(w0, w1):
                    figures = halves

        # After split: merge any coplanar fragments and re-apply area filter
        if len(figures) > 1:
            figures = _merge_coplanar_fragments(figures)
            max_area = max((f["box"][2]-f["box"][0])*(f["box"][3]-f["box"][1]) for f in figures)
            figures  = [f for f in figures
                        if (f["box"][2]-f["box"][0])*(f["box"][3]-f["box"][1]) >= 0.12 * max_area]

    return figures, captions


# ─── Caption matching + OCR ───────────────────────────────────────────────────

def _x_overlap(a: list[int], b: list[int]) -> int:
    """Horizontal overlap in pixels between two xyxy boxes."""
    return max(0, min(a[2], b[2]) - max(a[0], b[0]))


def _match_caption(fig_box: list[int], captions: list[dict]) -> dict | None:
    """
    Pick the caption belonging to a figure: prefer one that overlaps horizontally and
    sits just below the figure (patents print 'FIG. N' under the drawing). Fall back to
    the nearest caption by center distance.
    """
    fx1, fy1, fx2, fy2 = fig_box
    fcx = (fx1 + fx2) / 2

    below = []
    for cap in captions:
        cx1, cy1, cx2, cy2 = cap["box"]
        if _x_overlap(fig_box, cap["box"]) > 0 and cy1 >= fy1:
            # vertical gap from figure bottom to caption top (allow slight overlap)
            gap = cy1 - fy2
            if gap >= -0.15 * (fy2 - fy1):
                below.append((gap, cap))
    if below:
        below.sort(key=lambda t: t[0])
        return below[0][1]

    if captions:
        def _dist(cap):
            cx1, cy1, cx2, cy2 = cap["box"]
            return abs((cx1 + cx2) / 2 - fcx) + abs((cy1 + cy2) / 2 - (fy1 + fy2) / 2)
        return min(captions, key=_dist)
    return None


def _ocr_for_label(reader, crop: np.ndarray) -> str | None:
    """Try OCR at each cardinal rotation; return label or None."""
    lbl, _ = _ocr_for_label_and_rotation(reader, crop)
    return lbl


def _ocr_for_label_and_rotation(reader, crop: np.ndarray) -> tuple[str | None, int]:
    """
    Try OCR at 0°, then 90°, 180°, 270° explicitly.
    Returns (label, rotation_degrees) where rotation_degrees is the angle that
    needed to be applied to the crop to make the label readable upright.

    Trying each angle independently (rather than passing rotation_info) lets us
    know *which* angle worked, so the caller can apply the same rotation to the
    saved crop — making the output image always upright.
    """
    for degrees in [0, 180, 90, 270]:   # 180° first after 0° — most common flip
        rotated = np.rot90(crop, k=degrees // 90)
        try:
            texts = reader.readtext(rotated, detail=0)
        except Exception:
            continue
        joined = " ".join(texts)
        m = _FIG_KEY_RE.search(joined)
        if m:
            return m.group(1), degrees
    return None, 0


def read_label(reader, img: np.ndarray, cap_box: list[int] | None,
               fig_box: list[int] | None = None) -> tuple[str | None, bool, int]:
    """
    OCR the caption region (with rotation fallback) and extract a clean figure label.

    Returns (clean_label, needs_review, rotation_degrees).
    rotation_degrees is the angle that needed to be applied to the REGION crop to
    make the label readable — the caller applies the same rotation to the figure crop
    so the saved image is always upright. 0 means no rotation needed (or unknown).
    """
    h, w = img.shape[:2]

    def _read_region(box) -> tuple[str | None, int]:
        x1, y1, x2, y2 = box
        pad = 4
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
        region = img[y1:y2, x1:x2]
        if region.size == 0:
            return None, 0
        return _ocr_for_label_and_rotation(reader, region)

    # Pass 1: dedicated caption box
    if cap_box is not None:
        lbl, rot = _read_region(cap_box)
        if lbl:
            return lbl, False, rot

    if fig_box is not None:
        fx1, fy1, fx2, fy2 = fig_box
        fw, fh = fx2 - fx1, fy2 - fy1

        # Pass 2: top-left corner (top 25% × left 45%)
        lbl, rot = _read_region([fx1, fy1, fx1 + int(fw * 0.45), fy1 + int(fh * 0.25)])
        if lbl:
            return lbl, False, rot

        # Pass 3: top-right corner
        lbl, rot = _read_region([fx2 - int(fw * 0.45), fy1, fx2, fy1 + int(fh * 0.25)])
        if lbl:
            return lbl, False, rot

        # Pass 4: 350px strip below the figure box
        lbl, rot = _read_region([fx1, fy2, fx2, min(h, fy2 + 350)])
        if lbl:
            return lbl, False, rot

        # Pass 4b: bottom 15% center of figure box
        lbl, rot = _read_region([fx1 + int(fw * 0.1), fy2 - int(fh * 0.15),
                                  fx2 - int(fw * 0.1), fy2])
        if lbl:
            return lbl, False, rot

        # Pass 5: side margins + above
        margin_x     = max(10, int(fw * 0.15))
        margin_above = max(10, int(fh * 0.08))
        for region_box in [
            [max(0, fx1 - margin_x), fy1, fx1, fy2],
            [fx2, fy1, min(w, fx2 + margin_x), fy2],
            [fx1, max(0, fy1 - margin_above), fx2, fy1],
        ]:
            lbl, rot = _read_region(region_box)
            if lbl:
                return lbl, False, rot

        # Pass 6: bottom strip of the entire sheet — catches labels printed at the very
        # bottom page margin, outside all figure boxes (common on rotated/flipped sheets).
        sheet_bottom_box = [0, max(0, h - 350), w, h]
        lbl, rot = _read_region(sheet_bottom_box)
        if lbl:
            return lbl, False, rot

        # Pass 7: bottom corners of the figure box (labels often tucked into corners
        # of rotated sheets where top-corner passes miss them).
        lbl, rot = _read_region([fx1, fy2 - int(fh * 0.25), fx1 + int(fw * 0.45), fy2])
        if lbl:
            return lbl, False, rot
        lbl, rot = _read_region([fx2 - int(fw * 0.45), fy2 - int(fh * 0.25), fx2, fy2])
        if lbl:
            return lbl, False, rot

        # Pass 8: whole figure box at all 4 rotations — last resort; slow but recovers
        # sheets where the label is embedded inside the drawing area.
        lbl, rot = _ocr_for_label_and_rotation(reader, img[fy1:fy2, fx1:fx2])
        if lbl:
            return lbl, False, rot

    return None, True, 0


# ─── Cropping ─────────────────────────────────────────────────────────────────

def _auto_rotate(crop_bgr: np.ndarray) -> np.ndarray:
    """
    Detect and correct image rotation using the dominant text/line angle via Hough
    transform on a binarised version of the crop.  Only corrects multiples of 90°
    (portrait vs landscape) — fine-angle skew correction is left to the OCR engine.

    Strategy: compute the fraction of non-white pixels in each of the four cardinal
    orientations; if the image is wider than tall in one rotation but taller in the
    original, it was likely scanned sideways.  Simpler heuristic: if the crop is
    significantly taller than wide (portrait), check whether rotating 90° yields a
    landscape aspect closer to the norm for patent sub-figures and whether the
    binarised row-projection variance (text lines produce high variance) increases.
    """
    h, w = crop_bgr.shape[:2]
    if h == 0 or w == 0:
        return crop_bgr

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    def _row_var(img_bw: np.ndarray) -> float:
        return float(np.var(np.sum(img_bw, axis=1)))

    best_angle = 0
    best_var   = _row_var(bw)

    for angle in [90, 180, 270]:
        rotated_bw = np.rot90(bw, k=angle // 90)
        v = _row_var(rotated_bw)
        if v > best_var * 1.15:   # need at least 15% improvement to commit
            best_var   = v
            best_angle = angle

    if best_angle == 0:
        return crop_bgr
    return np.rot90(crop_bgr, k=best_angle // 90)


def _qwen_label(img_crop_bgr: np.ndarray, qwen_model, qwen_processor) -> tuple[str | None, str]:
    """
    Ask Qwen2.5-VL for the figure label of a single already-cropped image.
    Returns (label, status). label is a clean string like '3A', or None on failure/no-label.
    status is one of: "ok" (model answered, label may still be None), "oom", "error".
    """
    import torch
    from PIL import Image as PilImage
    from qwen_vl_utils import process_vision_info

    prompt = (
        "This is a cropped patent drawing. "
        "What is the figure label printed on it (e.g. 'FIG. 1', 'FIG. 2A', 'Fig. 3')? "
        "Reply with ONLY the label, nothing else. If there is no label, reply 'none'."
    )
    pil_img = PilImage.fromarray(cv2.cvtColor(img_crop_bgr, cv2.COLOR_BGR2RGB))
    messages = [{"role": "user", "content": [
        {"type": "image", "image": pil_img},
        {"type": "text",  "text": prompt},
    ]}]
    try:
        text = qwen_processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = qwen_processor(
            text=[text], images=image_inputs, videos=video_inputs,
            padding=True, return_tensors="pt"
        ).to("cuda")
        with torch.no_grad():
            gen_ids = qwen_model.generate(**inputs, max_new_tokens=32)
            trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, gen_ids)]
            raw = qwen_processor.batch_decode(trimmed, skip_special_tokens=True,
                                               clean_up_tokenization_spaces=False)[0].strip()
    except torch.cuda.OutOfMemoryError as e:
        print(f"    ⚠ Qwen OOM on this crop: {e}")
        torch.cuda.empty_cache()
        return None, "oom"
    except Exception as e:
        print(f"    ⚠ Qwen inference error on this crop: {e}")
        return None, "error"

    if raw.lower() == "none":
        return None, "ok"
    m = _FIG_KEY_RE.search(raw)
    return (m.group(1) if m else None), "ok"


_QWEN_LOAD_FAILED = False   # set True only after a non-transient (import/missing-dep) failure

def _ensure_qwen(engine: list) -> bool:
    """
    Lazy-load Qwen into engine[3] / engine[4] on first call.
    Returns True if Qwen is available, False otherwise.
    engine is a mutable list [model, reader, device, qwen_model, qwen_processor].

    Only ImportError/ModuleNotFoundError (missing dependency) permanently disables
    Qwen for the rest of the run. Transient errors (e.g. CUDA OOM during load) are
    retried on every call — VRAM pressure can change patent-to-patent as YOLO/EasyOCR
    allocations are freed, so a failure here doesn't mean it'll fail next time.
    """
    global _QWEN_LOAD_FAILED
    if engine[3] is not None:
        return True
    if _QWEN_LOAD_FAILED:
        return False
    try:
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        import figure_matcher as fm
        from config_loader import load_config
        cfg = load_config()
        qwen_model, qwen_proc = fm.build_engine(cfg)
        engine[3] = qwen_model
        engine[4] = qwen_proc
        return True
    except (ImportError, ModuleNotFoundError) as e:
        print(f"    ⚠ Qwen fallback unavailable (missing dependency): {e}")
        _QWEN_LOAD_FAILED = True
        return False
    except Exception as e:
        import torch, gc
        print(f"    ⚠ Qwen load failed, will retry next call: {e}")
        gc.collect()
        torch.cuda.empty_cache()
        return False


def _infer_sheet_rotation(reader, img: np.ndarray) -> int:
    """
    When no FIG label is found, infer the correct upright rotation from all readable
    text on the sheet.  Tries 0°, 90°, 180°, 270°; picks the rotation that produces
    the most total readable characters (longest joined OCR output).

    Uses a small downscale (max 600px on the long edge) so the full-sheet scan stays fast.
    Returns the rotation angle (0 / 90 / 180 / 270) to apply to bring the sheet upright.
    Returns 0 if no rotation clearly wins (i.e. difference is small).
    """
    h, w = img.shape[:2]
    scale = min(1.0, 600 / max(h, w, 1))
    small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))

    scores: dict[int, int] = {}
    for degrees in [0, 90, 180, 270]:
        rotated = np.rot90(small, k=degrees // 90)
        try:
            texts = reader.readtext(rotated, detail=0)
        except Exception:
            scores[degrees] = 0
            continue
        scores[degrees] = sum(len(t) for t in texts)

    best_angle = max(scores, key=scores.__getitem__)
    # Only commit if the best rotation gives clearly more text than upright (0°)
    if best_angle != 0 and scores[best_angle] > scores.get(0, 0) * 1.2:
        return best_angle
    return 0



def _review_hint_for_box(box: list[int]) -> str:
    """Hint only — flags boxes that look like multiple merged sub-figures
    (e.g. FIG.8A/8B/8C in one YOLO box) so a human reviewer can spot them
    fast. Never changes the crop, box, or label."""
    x1, y1, x2, y2 = box
    box_w, box_h = x2 - x1, y2 - y1
    if (box_w >= SPLIT_WIDTH_PX and box_w / max(box_h, 1) >= 1.8) or \
       (box_h >= SPLIT_HEIGHT_PX and box_h / max(box_w, 1) >= 1.8):
        return "possible_multi_fig"
    return ""


def _merge_labeled(labeled: list[dict]) -> list[dict]:
    """
    Group labeled crops by their figure label; merge each group into a single
    union-bbox entry. Keeps the highest-confidence box's metadata as representative.
    """
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in labeled:
        groups[item["label"]].append(item)

    merged = []
    for lbl, items in groups.items():
        if len(items) == 1:
            merged.append(items[0])
        else:
            best = max(items, key=lambda x: x["conf"])
            union_box = _union_box([x["box"] for x in items])
            merged.append({
                "box":   union_box,
                "conf":  best["conf"],
                "label": lbl,
                "cap":   best.get("cap"),
                "label_rotation": best.get("label_rotation", 0),
                "method": best.get("method", "doclayout_easyocr"),
                "needs_review": False,
                "review_hint": _review_hint_for_box(union_box),
                "qwen_status": best.get("qwen_status", "not_attempted"),
            })
    return merged


def _merge_fu(unlabeled: list[dict]) -> list[dict]:
    """
    Merge unlabelled (_Fu) boxes that sit in the same horizontal band and are
    close enough horizontally (gap ≤ FU_MERGE_GAP_PX). Uses a simple greedy
    sweep: sort boxes left-to-right; extend the current group while the next box
    overlaps vertically and is within the gap threshold.
    """
    if not unlabeled:
        return []

    # Sort by left edge
    items = sorted(unlabeled, key=lambda x: x["box"][0])
    groups: list[list[dict]] = []
    current = [items[0]]

    for item in items[1:]:
        prev_box  = _union_box([x["box"] for x in current])
        curr_box  = item["box"]

        # Vertical overlap check (y-bands must intersect)
        v_overlap = min(prev_box[3], curr_box[3]) - max(prev_box[1], curr_box[1])
        # Horizontal gap between the right edge of current group and left edge of next
        h_gap = curr_box[0] - prev_box[2]

        if v_overlap > 0 and h_gap <= FU_MERGE_GAP_PX:
            current.append(item)
        else:
            groups.append(current)
            current = [item]
    groups.append(current)

    merged = []
    for grp in groups:
        best = max(grp, key=lambda x: x["conf"])
        union_box = _union_box([x["box"] for x in grp])
        merged.append({
            "box":   union_box,
            "conf":  best["conf"],
            "label": None,
            "cap":   best.get("cap"),
            "label_rotation": 0,
            "method": best.get("method", "doclayout_easyocr"),
            "needs_review": True,
            "review_hint": _review_hint_for_box(union_box),
            "qwen_status": best.get("qwen_status", "not_attempted"),
        })
    return merged


def crop_and_save(img_path: Path, figures: list[dict], captions: list[dict],
                  engine, out_dir: Path) -> list[dict]:
    """
    For each detected figure: match a caption, OCR its label, auto-rotate the crop
    to upright orientation, and save with the project naming convention.

    If all EasyOCR passes fail, falls back to Qwen2.5-VL (loaded lazily).
    engine is the mutable list returned by build_engine().
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _, reader, _, _, _ = engine
    img = cv2.imread(str(img_path))
    if img is None:
        return []
    h, w = img.shape[:2]
    CROP_PAD_PX = CROP_PAD_PX_FIXED

    # ── Pass 1: OCR every detected figure box ────────────────────────────────
    annotated: list[dict] = []   # each item carries box + OCR result
    for fig in figures:
        x1, y1, x2, y2 = fig["box"]
        x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
        x2, y2 = max(x1 + 1, min(x2, w)), max(y1 + 1, min(y2, h))

        if (y2 - y1) < MIN_CROP_PX or (x2 - x1) < MIN_CROP_PX:
            continue

        cap = _match_caption([x1, y1, x2, y2], captions)
        clean_lbl, needs_review, label_rotation = read_label(
            reader, img,
            cap["box"] if cap else None,
            fig_box=[x1, y1, x2, y2],
        )

        method = "doclayout_easyocr"
        qwen_status = "not_attempted"
        if needs_review and _ensure_qwen(engine):
            # Pass A: padded figure box (catches labels just outside the detected region)
            qx1 = max(0, x1 - QWEN_PAD_SIDE_PX)
            qy1 = max(0, y1 - QWEN_PAD_SIDE_PX)
            qx2 = min(w, x2 + QWEN_PAD_SIDE_PX)
            qy2 = min(h, y2 + QWEN_PAD_BELOW_PX)
            qwen_lbl, qwen_status = _qwen_label(img[qy1:qy2, qx1:qx2], engine[3], engine[4])
            if qwen_lbl:
                clean_lbl, needs_review = qwen_lbl, False
                method = "doclayout_qwen"
        elif needs_review:
            qwen_status = "unavailable"

        if needs_review and _ensure_qwen(engine):
            # Pass B: bottom 20% of the full sheet — USPTO patents print "FIG. N" here,
            # often inside the YOLO box so Pass A's crop is swamped by callout numbers.
            strip_y1 = max(0, h - int(h * 0.20))
            qwen_lbl, qwen_status = _qwen_label(img[strip_y1:h, 0:w], engine[3], engine[4])
            if qwen_lbl:
                clean_lbl, needs_review = qwen_lbl, False
                method = "doclayout_qwen_strip"

        annotated.append({
            "box":            [x1, y1, x2, y2],
            "conf":           fig["conf"],
            "label":          clean_lbl,
            "cap":            cap,
            "label_rotation": label_rotation,
            "method":         method,
            "needs_review":   needs_review,
            "review_hint":    _review_hint_for_box([x1, y1, x2, y2]),
            "qwen_status":    qwen_status,
        })

    # ── Pass 2: merge split crops ─────────────────────────────────────────────
    labeled   = [a for a in annotated if not a["needs_review"]]
    unlabeled = [a for a in annotated if a["needs_review"]]

    merged_labeled   = _merge_labeled(labeled)
    merged_unlabeled = _merge_fu(unlabeled)
    to_save = merged_labeled + merged_unlabeled

    # ── Pass 3: crop, rotate, save ────────────────────────────────────────────
    _sheet_rot_cache: int | None = None

    records: list[dict] = []
    for idx, item in enumerate(to_save):
        x1, y1, x2, y2 = item["box"]
        # Expand box by CROP_PAD_PX on all sides, clamped to image bounds
        x1 = max(0, x1 - CROP_PAD_PX)
        y1 = max(0, y1 - CROP_PAD_PX)
        x2 = min(w, x2 + CROP_PAD_PX)
        y2 = min(h, y2 + CROP_PAD_PX)

        crop = img[y1:y2, x1:x2]
        if crop.shape[0] < MIN_CROP_PX or crop.shape[1] < MIN_CROP_PX:
            continue

        label_rotation = item["label_rotation"]
        needs_review   = item["needs_review"]

        if label_rotation != 0:
            crop = np.rot90(crop, k=label_rotation // 90)
        elif needs_review:
            if _sheet_rot_cache is None:
                _sheet_rot_cache = _infer_sheet_rotation(reader, img)
            if _sheet_rot_cache != 0:
                crop = np.rot90(crop, k=_sheet_rot_cache // 90)

        clean_lbl = item["label"]
        suffix    = f"_F{clean_lbl}" if not needs_review else "_Fu"
        out_path  = out_dir / f"{img_path.stem}_crop_{idx}{suffix}.png"
        cv2.imwrite(str(out_path), crop)

        records.append({
            "original":     img_path.name,
            "output":       out_path.name,
            "label":        clean_lbl,
            "box_px":       [x1, y1, x2, y2],
            "method":       item["method"],
            "needs_review": needs_review,
            "review_hint":  item.get("review_hint", ""),
            "qwen_status":  item.get("qwen_status", "not_attempted"),
        })
    return records


def draw_regions(img_path: Path, figures: list[dict], captions: list[dict]) -> np.ndarray:
    """Return an RGB copy with figure boxes (green) and caption boxes (blue) drawn."""
    img = cv2.imread(str(img_path))
    for fig in figures:
        x1, y1, x2, y2 = fig["box"]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 0), 4)
        cv2.putText(img, f"figure {fig['conf']:.2f}", (x1, max(0, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 200, 0), 3)
    for cap in captions:
        x1, y1, x2, y2 = cap["box"]
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 0, 0), 3)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


# ─── Orchestration ────────────────────────────────────────────────────────────

def process_image(engine, img_path: Path, out_dir: Path) -> dict:
    """
    Detect + crop one sheet.
    engine is the mutable list [model, reader, device, qwen_model, qwen_processor]
    returned by build_engine(). Qwen slots are populated lazily on first OCR miss.
    """
    model, reader, device = engine[0], engine[1], engine[2]
    figures, captions = detect_regions(model, img_path, device=device)
    crops = crop_and_save(img_path, figures, captions, engine, out_dir)
    return {"image": img_path.name, "figures": figures, "captions": captions, "crops": crops}


def _worker_process(
    subset: list[str],
    device: str,
    weights: str,
    raw_dir: str,
    matched_dir: str,
    triage_dir: str,
    result_queue,
):
    """
    Runs in a separate process — builds its own engine on `device`, processes
    its subset of patents, puts (rows, triage_skipped, logs) into result_queue.
    Must be a module-level function so multiprocessing can pickle it.
    """
    import json, re, shutil, torch
    from pathlib import Path

    engine = build_engine(weights, device=device)
    raw_dir     = Path(raw_dir)
    matched_dir = Path(matched_dir)
    triage_dir  = Path(triage_dir)

    _CLEAN_RE   = re.compile(r"[^A-Za-z0-9]")
    _NUM_SUFFIX = re.compile(r"_\d+$")
    _DL_SUFFIX  = re.compile(r"PAFP$|PAF$", re.IGNORECASE)
    _KIND_CODES = ["A1","A2","A3","B1","B2","C1","U1"]
    _NON_SHEET  = re.compile(r"manifest|thumbnail|cover|abstract|front.?page", re.IGNORECASE)
    _SHEET_RE   = re.compile(r"""
        (?:
            _[Dd]\d{3,}|PAFP_img\d|PAF_img\d|_img[af]?\d|fig_\d|record__fig_\d|
            ^img[af]?\d|^pat\d|^FT_\d|^HDA\d|^\d+\.|^srep\d|sN_img\d
        )""", re.VERBOSE | re.IGNORECASE)

    def _c(pid):
        p = _NUM_SUFFIX.sub("", pid)
        c = _CLEAN_RE.sub("", p).upper()
        c = _DL_SUFFIX.sub("", c)
        for sfx in _KIND_CODES:
            if c.endswith(sfx): return c[:-len(sfx)]
        return c

    def _is_sheet(f):
        if f.suffix.lower() != ".png": return False
        if _NON_SHEET.search(f.name): return False
        return bool(_SHEET_RE.search(f.name))

    def _excluded(pid):
        p = triage_dir / f"{pid}.json"
        if not p.exists(): return set()
        try:
            data = json.loads(p.read_text())
            return {fig["file"] for fig in data.get("figures", [])
                    if fig.get("keep") is False and fig.get("locked") is True}
        except Exception:
            return set()

    folder_map = {_c(p.name): p for p in raw_dir.iterdir() if p.is_dir()}

    rows: list[dict] = []
    triage_skipped_total = 0
    logs: list[str] = []

    for excel_id in subset:
        folder = folder_map.get(_c(excel_id))
        if folder is None:
            logs.append(f"  ⚠  [{device}] No raw folder for {excel_id} — skipping")
            continue

        out_dir = matched_dir / folder.name
        out_dir.mkdir(parents=True, exist_ok=True)

        files     = sorted(folder.iterdir())
        img_files = [f for f in files if _is_sheet(f)]
        fat_files = [f for f in files if re.search(r"_FAT\d", f.name)]
        excl      = _excluded(folder.name)

        if excl:
            skipped = sum(1 for f in img_files + fat_files if f.name in excl)
            triage_skipped_total += skipped
            img_files = [f for f in img_files if f.name not in excl]
            fat_files = [f for f in fat_files if f.name not in excl]

        for f in fat_files:
            out_path = out_dir / f"{f.stem}_Fu.png"
            shutil.copy2(f, out_path)
            rows.append({"patent_id": excel_id, "original": f.name, "output": out_path.name,
                         "label": None, "method": "fat_copy", "needs_review": True, "review_hint": "",
                         "qwen_status": "not_attempted"})

        for img_path in img_files:
            try:
                res = process_image(engine, img_path, out_dir)
                for c in res["crops"]:
                    rows.append({"patent_id": excel_id, "original": c["original"],
                                 "output": c["output"], "label": c["label"],
                                 "method": c["method"], "needs_review": c["needs_review"],
                                 "review_hint": c.get("review_hint", ""),
                                 "qwen_status": c.get("qwen_status", "not_attempted")})
            except Exception as e:
                logs.append(f"    ❌ [{device}] {img_path.name}: {e}")

        torch.cuda.empty_cache()
        total    = sum(1 for r in rows if r["patent_id"] == excel_id)
        labelled = sum(1 for r in rows if r["patent_id"] == excel_id and not r["needs_review"])
        logs.append(f"  ✓ [{device}] {excel_id}  sheets={len(img_files)}  crops={total}  labelled={labelled}")

    result_queue.put((rows, triage_skipped_total, logs))


def process_patents_parallel(
    patent_rows,
    folder_map,
    matched_dir: Path,
    triage_dir: Path,
    engines,
    is_sheet_fn,
    triage_excluded_fn,
    cfg: dict,
    weights: str = DEFAULT_WEIGHTS,
    gpu_ids: list[str] | None = None,
) -> tuple[list[dict], int]:
    """
    Process patents across one or more GPUs using subprocess.Popen + CUDA_VISIBLE_DEVICES.
    Each worker is a fresh Python process that sees only its assigned GPU as cuda:0,
    so there is no CUDA re-init conflict and no GIL contention.
    Results are exchanged via temp JSON files.

    gpu_ids: explicit list of physical GPU indices to use, e.g. ["0"] or ["0", "1"].
    If None, defaults to one worker per visible GPU (or a single worker on GPU 0
    if only one GPU is visible) — the old behaviour.
    """
    import json, os, subprocess, sys, tempfile, torch
    from pathlib import Path as _Path

    ids = [str(r).strip() for r in patent_rows]

    if gpu_ids is None:
        n_gpu = torch.cuda.device_count()
        gpu_ids = [str(i) for i in range(n_gpu)] if n_gpu >= 1 else ["0"]

    n_workers = len(gpu_ids)
    chunk = max(1, -(-len(ids) // n_workers))  # ceil division
    splits = [ids[i:i + chunk] for i in range(0, len(ids), chunk)] or [[]]
    while len(splits) < n_workers:
        splits.append([])

    worker_script = str(_Path(__file__).parent / "gpu_worker.py")
    python_exe    = sys.executable

    tmp_dir = _Path(tempfile.mkdtemp(prefix="dm_parallel_"))
    procs   = []
    result_paths = []

    for i in range(n_workers):
        args_path   = tmp_dir / f"args_{i}.json"
        result_path = tmp_dir / f"result_{i}.json"
        result_paths.append(result_path)

        args_path.write_text(json.dumps({
            "patent_ids": splits[i],
            "weights":    weights,
            "raw_dir":    str(cfg["paths"]["raw_images"]),
            "matched_dir": str(matched_dir),
            "triage_dir":  str(triage_dir),
        }))

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids[i]

        p = subprocess.Popen(
            [python_exe, worker_script, str(args_path), str(result_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        procs.append(p)
        print(f"[GPU {gpu_ids[i]}] worker started (PID {p.pid})")

    # Stream output from both processes as they run
    import threading
    def _stream(proc, label):
        for line in proc.stdout:
            print(f"[GPU {label}] {line}", end="", flush=True)

    threads = [threading.Thread(target=_stream, args=(procs[i], gpu_ids[i]), daemon=True)
               for i in range(n_workers)]
    for t in threads: t.start()
    for p in procs:   p.wait()
    for t in threads: t.join()

    # Collect results
    all_rows: list[dict] = []
    triage_skipped_total = 0
    for rp in result_paths:
        if not rp.exists():
            print(f"⚠  Result file missing: {rp} — worker may have crashed")
            continue
        data = json.loads(rp.read_text())
        all_rows.extend(data["rows"])
        triage_skipped_total += data["triage_skipped_total"]

    # Cleanup temp dir
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return all_rows, triage_skipped_total


def _core(pid: str) -> str:
    """Normalise a patent ID to its bare alphanumeric core (duplicate of notebook helper)."""
    import re as _re
    _CLEAN_RE   = _re.compile(r"[^A-Za-z0-9]")
    _NUM_SUFFIX = _re.compile(r"_\d+$")
    _DL_SUFFIX  = _re.compile(r"PAFP$|PAF$", _re.IGNORECASE)
    _KIND_CODES = ["A1","A2","A3","B1","B2","C1","U1"]
    p = _NUM_SUFFIX.sub("", pid)
    c = _CLEAN_RE.sub("", p).upper()
    c = _DL_SUFFIX.sub("", c)
    for sfx in _KIND_CODES:
        if c.endswith(sfx):
            return c[:-len(sfx)]
    return c
