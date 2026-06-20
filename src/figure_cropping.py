"""
figure_cropping.py — merging split detections, padding/snapping the crop boundary,
and writing the final per-figure PNGs.

Owns everything from "here are the labeled/unlabeled figure boxes for this sheet"
to "here are the saved crop files". Detection (figure_detection.py) and labeling
(figure_labeling.py) are separate concerns.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from cv_utils import box_gap, ink_mask, to_gray, union_box
from figure_labeling import ensure_qwen, infer_sheet_rotation, qwen_label, read_label
from figure_labeling import QWEN_PAD_BELOW_PX, QWEN_PAD_SIDE_PX

# ── Crop size gates ─────────────────────────────────────────────────────────────
MIN_CROP_PX  = 450     # discard FINAL (padded) crops smaller than this — filters bad thin split slices
NOISE_FLOOR_PX = 60    # raw YOLO boxes smaller than this are noise, not recoverable figures —
                        # filtered before padding so genuinely small figures still get a chance to
                        # clear MIN_CROP_PX once padded/snapped, instead of being dropped pre-pad

# Row/column is "whitespace" if fewer than this fraction of its pixels are ink.
# Used by the (retired) whitespace-sweep splitters' Otsu-based ink check elsewhere;
# kept here as the canonical "is this region basically blank" threshold for cropping.
WHITESPACE_INK_FRAC = 0.015

# ── Crop padding (relative to sheet size) ──────────────────────────────────────
# Pad is a fraction of the sheet's long edge, not a fixed pixel count, so framing
# is consistent across scan DPIs (180px on a 1200px sheet ≠ 180px on a 4000px one).
# Clamped to [_PAD_MIN_PX, _PAD_MAX_PX] so tiny/huge sheets stay sane.
CROP_PAD_FRAC = 0.045
_PAD_MIN_PX   = 120
_PAD_MAX_PX   = 260


def crop_pad_px(w: int, h: int) -> int:
    """Symmetric crop pad in px, scaled to the sheet's long edge and clamped."""
    return int(min(_PAD_MAX_PX, max(_PAD_MIN_PX, CROP_PAD_FRAC * max(w, h))))


# ── Merge parameters ──────────────────────────────────────────────────────────
# Same-label merge: if two YOLO boxes on one sheet get the same FIG. label their
# union bounding box is re-cropped as a single image (handles split rotor tips, etc.)
# Fu merge: unlabelled boxes whose vertical bands overlap AND whose horizontal gap
# is ≤ FU_MERGE_GAP_PX are merged the same way.
FU_MERGE_GAP_PX   = 200   # max horizontal gap (px) between two _Fu boxes to merge

# Two boxes getting the same OCR-read label doesn't always mean they're
# fragments of one figure — a neighboring figure's tail/caption can get
# misread as the same digit. Only treat same-label boxes as one figure if
# they're within this gap; further apart, keep them separate and flag the
# lower-confidence one instead of unioning across whatever sits between them.
SAME_LABEL_MERGE_GAP_PX = 300


def _review_hint_for_box(box: list[int]) -> str:
    """Hint only — flags boxes that look like multiple merged sub-figures
    (e.g. FIG.8A/8B/8C in one YOLO box) so a human reviewer can spot them
    fast. Never changes the crop, box, or label."""
    _wide_thresh = 1500
    x1, y1, x2, y2 = box
    box_w, box_h = x2 - x1, y2 - y1
    if (box_w >= _wide_thresh and box_w / max(box_h, 1) >= 1.8) or \
       (box_h >= _wide_thresh and box_h / max(box_w, 1) >= 1.8):
        return "possible_multi_fig"
    return ""


def _merge_labeled(labeled: list[dict]) -> list[dict]:
    """
    Group labeled crops by their figure label; merge each group into a single
    union-bbox entry. Keeps the highest-confidence box's metadata as representative.

    Same label alone isn't enough to merge — first cluster by proximity
    (SAME_LABEL_MERGE_GAP_PX) so legitimate split fragments (e.g. split rotor
    tips) still merge, but a same-label collision from an OCR misread on a
    far-away box (e.g. a neighboring figure's tail wing) doesn't get unioned
    in, which would silently swallow whatever sits between them. The cluster
    with the highest confidence keeps the label; any other same-label cluster
    is kept separate and flagged for review instead.
    """
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in labeled:
        groups[item["label"]].append(item)

    merged = []
    for lbl, items in groups.items():
        if len(items) == 1:
            merged.append(items[0])
            continue

        n = len(items)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        for i in range(n):
            for j in range(i + 1, n):
                if box_gap(items[i]["box"], items[j]["box"]) <= SAME_LABEL_MERGE_GAP_PX:
                    union(i, j)

        clusters: dict[int, list[dict]] = defaultdict(list)
        for i in range(n):
            clusters[find(i)].append(items[i])
        cluster_list = sorted(clusters.values(), key=lambda grp: max(x["conf"] for x in grp), reverse=True)

        for ci, grp in enumerate(cluster_list):
            best = max(grp, key=lambda x: x["conf"])
            ub = union_box([x["box"] for x in grp])
            is_primary = ci == 0
            merged.append({
                "box":   ub,
                "conf":  best["conf"],
                "label": lbl,
                "cap":   best.get("cap"),
                "label_rotation": best.get("label_rotation", 0),
                "method": best.get("method", "doclayout_easyocr"),
                "needs_review": not is_primary,
                "review_hint": _review_hint_for_box(ub) if is_primary else "duplicate_label_far_apart",
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
        prev_box  = union_box([x["box"] for x in current])
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
        ub = union_box([x["box"] for x in grp])
        merged.append({
            "box":   ub,
            "conf":  best["conf"],
            "label": None,
            "cap":   best.get("cap"),
            "label_rotation": 0,
            "method": best.get("method", "doclayout_easyocr"),
            "needs_review": True,
            "review_hint": _review_hint_for_box(ub),
            "qwen_status": best.get("qwen_status", "not_attempted"),
        })
    return merged


# ── Neighbor-aware padding ──────────────────────────────────────────────────────
# Allow padding to creep this fraction of the sheet's long edge past a neighbor's
# edge — recovers content from overlapping isometric figures (e.g. two views of the
# same aircraft sharing a sheet) without re-opening the FIG.10A/10B caption-bleed
# this clamp was added to prevent. Clamped so it stays a small nudge, not a bleed.
NEIGHBOR_OVERSHOOT_FRAC = 0.012
_OVERSHOOT_MIN_PX = 30
_OVERSHOOT_MAX_PX = 80


def _neighbor_overshoot_px(w: int, h: int) -> int:
    """Overshoot allowance in px, scaled to the sheet's long edge and clamped."""
    return int(min(_OVERSHOOT_MAX_PX, max(_OVERSHOOT_MIN_PX, NEIGHBOR_OVERSHOOT_FRAC * max(w, h))))


def _clamp_pad_against_neighbors(box: list[int], pad: int, other_boxes: list[list[int]],
                                  w: int, h: int, overshoot: int = 0) -> tuple[int, int, int, int]:
    """
    Expand `box` by `pad` on every side, but never cross into a neighboring
    figure box on the same sheet. Without this, the crop pad bleeds into
    the next figure's caption/leader-lines on densely-stacked multi-figure
    sheets (e.g. FIG. 10A's pad reaching down into FIG. 10B's "1002B" label).
    Only clamps in the direction the neighbor actually sits in (above/below for
    a horizontally-overlapping neighbor, left/right for a vertically-overlapping one).

    `overshoot` lets the pad creep slightly past the neighbor's edge instead of
    stopping dead on it — used as a second pass when content is still clipped
    after the strict clamp gave up.
    """
    x1, y1, x2, y2 = box
    nx1, ny1, nx2, ny2 = x1 - pad, y1 - pad, x2 + pad, y2 + pad
    for ox1, oy1, ox2, oy2 in other_boxes:
        h_overlap = min(x2, ox2) - max(x1, ox1)
        if h_overlap > 0:
            if oy2 <= y1:
                ny1 = max(ny1, oy2 - overshoot)
            if oy1 >= y2:
                ny2 = min(ny2, oy1 + overshoot)
        v_overlap = min(y2, oy2) - max(y1, oy1)
        if v_overlap > 0:
            if ox2 <= x1:
                nx1 = max(nx1, ox2 - overshoot)
            if ox1 >= x2:
                nx2 = min(nx2, ox1 + overshoot)
    return max(0, nx1), max(0, ny1), min(w, nx2), min(h, ny2)


def _crop_touches_border(crop: np.ndarray,
                          frac_thresh: float = 0.15, border_px: int = 2,
                          corner_frac_thresh: float = 0.04) -> bool:
    """
    True if drawing strokes run right up against any edge of the crop — a strong
    signal the YOLO box under-detected the figure's true extent and sliced through
    real content (e.g. a rotor disc or wingtip), rather than cleanly framing it
    with whitespace. Used to catch crops that would otherwise be silently
    auto-labelled despite being cut off.

    Ink is detected via Otsu (ink_mask), so faint line-art counts the same as
    dark ink. The four corners are checked separately with a much lower threshold:
    a diagonal stroke clipped at a corner (e.g. a wingtip on an isometric view)
    only ever touches a tiny sliver of a full edge — never enough to clear
    frac_thresh — but it's just as much a real clip as a flat edge cut. Corner
    patch size scales with the crop so sensitivity is the same at any DPI.
    """
    h, w = crop.shape[:2]
    if h <= border_px * 2 or w <= border_px * 2:
        return False
    ink = ink_mask(crop)
    edges = [ink[0:border_px, :], ink[-border_px:, :], ink[:, 0:border_px], ink[:, -border_px:]]
    if any(edge.mean() > frac_thresh for edge in edges):
        return True
    corner_px = max(20, min(h, w) // 40)   # relative — scale-invariant
    if h <= corner_px * 2 or w <= corner_px * 2:
        return False
    corners = [
        ink[0:corner_px, 0:corner_px], ink[0:corner_px, -corner_px:],
        ink[-corner_px:, 0:corner_px], ink[-corner_px:, -corner_px:],
    ]
    return any(corner.mean() > corner_frac_thresh for corner in corners)


# ── Connected-component crop snapping ───────────────────────────────────────────
# The fixed/relative pad alone is a guess at how far a figure's real extent
# reaches. Snapping the box to the connected ink components it already touches
# follows the drawing itself: a wingtip or rotor blade clipped by an under-tight
# YOLO box is part of the same connected stroke as content already inside the
# box, so it gets pulled in automatically — no edge/corner heuristics needed.
SNAP_MAX_GROWTH_FRAC = 0.06   # cap extra growth per side, as a fraction of the sheet's long edge
_SNAP_MAX_GROWTH_MIN_PX = 150
_SNAP_MAX_GROWTH_MAX_PX = 400


def _sheet_components(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Connected components of a full sheet's ink mask, computed once per sheet.
    Returns (labels, stats): labels is an (h, w) int32 array of component IDs
    (0 = background); stats[i] = [x, y, w, h, area] per cv2 convention, stats[0]
    is the background component and should be ignored by callers.
    """
    ink = ink_mask(gray).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    return labels, stats


def _snap_box_to_components(box: list[int], labels: np.ndarray, stats: np.ndarray,
                             w: int, h: int, search_pad: int, max_growth: int) -> list[int]:
    """
    Grow `box` to fully enclose every connected ink component already touching it
    (within `search_pad` of its edge) — recovers thin/diagonal strokes a tight YOLO
    box sliced through, because they belong to the same connected drawing as ink
    already inside the box.

    `max_growth` caps the expansion per side so a stray bridging stroke into an
    unrelated neighboring figure can't balloon the crop unboundedly; the caller
    still clamps the result against neighbor boxes afterward as a hard backstop.
    """
    x1, y1, x2, y2 = box
    sx1, sy1 = max(0, x1 - search_pad), max(0, y1 - search_pad)
    sx2, sy2 = min(w, x2 + search_pad), min(h, y2 + search_pad)
    if sx2 <= sx1 or sy2 <= sy1:
        return box

    region = labels[sy1:sy2, sx1:sx2]
    # Slice of the region that corresponds to the original (un-padded) box.
    ix1, iy1 = max(0, x1 - sx1), max(0, y1 - sy1)
    ix2, iy2 = min(region.shape[1], x2 - sx1), min(region.shape[0], y2 - sy1)
    if ix2 <= ix1 or iy2 <= iy1:
        return box
    touching_ids = set(np.unique(region[iy1:iy2, ix1:ix2])) - {0}
    if not touching_ids:
        return box

    nx1, ny1, nx2, ny2 = x1, y1, x2, y2
    for cid in touching_ids:
        cx, cy, cw, ch, _area = stats[cid]
        nx1, ny1 = min(nx1, cx), min(ny1, cy)
        nx2, ny2 = max(nx2, cx + cw), max(ny2, cy + ch)

    nx1 = max(0, max(nx1, x1 - max_growth))
    ny1 = max(0, max(ny1, y1 - max_growth))
    nx2 = min(w, min(nx2, x2 + max_growth))
    ny2 = min(h, min(ny2, y2 + max_growth))
    return [nx1, ny1, nx2, ny2]


def _clamp_grown_box_to_original_direction(orig_box: list[int], grown_box: list[int],
                                            other_boxes: list[list[int]]) -> list[int]:
    """
    Clamp a box that was grown from `orig_box` (e.g. by CC-snapping) so it never
    crosses into a neighbor that sat cleanly on one side of `orig_box`.

    `_clamp_pad_against_neighbors` decides which side a neighbor is on by checking
    the *current* box's position relative to it — which breaks once the box has
    already grown into the neighbor (a connected ink blob bridging two figures,
    e.g. a leader line nearly touching the next figure, pulls the whole neighboring
    figure's component in). This uses `orig_box` — which by construction doesn't yet
    overlap any neighbor — to fix the direction, then clamps `grown_box` to it.
    """
    ox1, oy1, ox2, oy2 = orig_box
    gx1, gy1, gx2, gy2 = grown_box
    for nx1, ny1, nx2, ny2 in other_boxes:
        h_overlap = min(ox2, nx2) - max(ox1, nx1)
        if h_overlap > 0:
            if ny2 <= oy1:        # neighbor sits above the original box
                gy1 = max(gy1, ny2)
            if ny1 >= oy2:        # neighbor sits below
                gy2 = min(gy2, ny1)
        v_overlap = min(oy2, ny2) - max(oy1, ny1)
        if v_overlap > 0:
            if nx2 <= ox1:        # neighbor sits to the left
                gx1 = max(gx1, nx2)
            if nx1 >= ox2:        # neighbor sits to the right
                gx2 = min(gx2, nx1)
    return [gx1, gy1, gx2, gy2]


def _expand_box_until_clear(img: np.ndarray, box: list[int], other_boxes: list[list[int]],
                             w: int, h: int, base_pad: int,
                             extra_step: int | None = None, max_extra: int = 3) -> tuple[int, int, int, int, np.ndarray]:
    """
    Grow the crop beyond the base pad when content still touches the crop edge —
    some figures (e.g. a rotated single-figure design-patent sheet drawn close to
    the page margins) extend further than the base pad recovers. Stops as soon as
    the crop clears the border, or stops growing because it hit a neighboring
    figure box or the page edge (still clamped via _clamp_pad_against_neighbors,
    so it never bleeds into the next figure).

    `extra_step` defaults to half the base pad, scaling the growth step to sheet
    size the same way the base pad itself is scaled (see crop_pad_px).
    """
    if extra_step is None:
        extra_step = max(60, base_pad // 2)
    pad = base_pad
    x1, y1, x2, y2 = _clamp_pad_against_neighbors(box, pad, other_boxes, w, h)
    crop = img[y1:y2, x1:x2]
    for _ in range(max_extra):
        if crop.size == 0 or not _crop_touches_border(crop):
            break
        pad += extra_step
        nx1, ny1, nx2, ny2 = _clamp_pad_against_neighbors(box, pad, other_boxes, w, h)
        if (nx1, ny1, nx2, ny2) == (x1, y1, x2, y2):
            break
        x1, y1, x2, y2 = nx1, ny1, nx2, ny2
        crop = img[y1:y2, x1:x2]

    # Strict clamp plateaued but content is still clipped (e.g. two overlapping
    # isometric figures sharing a sheet) — allow a small, fixed overshoot past
    # the neighbor's edge as a last resort rather than silently saving a cut crop.
    if crop.size == 0 or _crop_touches_border(crop):
        ox1, oy1, ox2, oy2 = _clamp_pad_against_neighbors(
            box, pad, other_boxes, w, h, overshoot=_neighbor_overshoot_px(w, h))
        if (ox1, oy1, ox2, oy2) != (x1, y1, x2, y2):
            x1, y1, x2, y2 = ox1, oy1, ox2, oy2
            crop = img[y1:y2, x1:x2]
    return x1, y1, x2, y2, crop


# ── Pass-3 review-flag predicates ───────────────────────────────────────────────
# Each of these inspects one saved crop/item and decides whether it needs human
# review. Kept as standalone predicates (rather than inline in crop_and_save) so
# the per-crop decision logic in the main loop reads as a short pipeline.

def _is_below_min_size(crop: np.ndarray) -> bool:
    return crop.shape[0] < MIN_CROP_PX or crop.shape[1] < MIN_CROP_PX


def _oversized_box_overlaps_other_figure(item: dict, to_save: list[dict], sheet_area: int) -> bool:
    """
    True if `item`'s raw box covers most of the sheet AND substantially contains a
    different, separately-labelled figure's box — meaning detection merged two
    distinct figures into one oversized crop (e.g. FIG. 4's box swallowing FIG. 3
    above it).
    """
    own_box  = item["box"]
    own_area = max(1, (own_box[2] - own_box[0]) * (own_box[3] - own_box[1]))
    if own_area < 0.85 * sheet_area:
        return False
    for other in to_save:
        if other is item:
            continue
        ob = other["box"]
        ob_area = max(1, (ob[2] - ob[0]) * (ob[3] - ob[1]))
        ix1, iy1 = max(own_box[0], ob[0]), max(own_box[1], ob[1])
        ix2, iy2 = min(own_box[2], ob[2]), min(own_box[3], ob[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter / ob_area >= 0.7:
            return True
    return False


def _ocr_pass1(item_box: list[int], captions: list[dict], img: np.ndarray, reader, engine,
                w: int, h: int) -> dict:
    """
    Run caption matching + the EasyOCR/Qwen label cascade for one raw figure box.
    Returns an annotated dict ready to feed into the labeled/unlabeled merge step.
    """
    from figure_labeling import match_caption
    x1, y1, x2, y2 = item_box
    cap = match_caption([x1, y1, x2, y2], captions)

    # Expand the OCR search region beyond the tight YOLO box — prevents
    # partial character reads when the label sits at the box edge.
    # YOLO clips "8" → OCR sees "0", "9" → "4", "I" → "|" etc.
    # This is separate from the saved-PNG crop pad (crop_pad_px).
    ocr_x1 = max(0, x1 - 80)
    ocr_y1 = max(0, y1 - 80)
    ocr_x2 = min(w, x2 + 80)
    ocr_y2 = min(h, y2 + 80)

    clean_lbl, needs_review, label_rotation = read_label(
        reader, img,
        cap["box"] if cap else None,
        fig_box=[ocr_x1, ocr_y1, ocr_x2, ocr_y2],
    )

    method = "doclayout_easyocr"
    qwen_status = "not_attempted"
    if needs_review and ensure_qwen(engine):
        # Pass A: padded figure box (catches labels just outside the detected region)
        qx1 = max(0, x1 - QWEN_PAD_SIDE_PX)
        qy1 = max(0, y1 - QWEN_PAD_SIDE_PX)
        qx2 = min(w, x2 + QWEN_PAD_SIDE_PX)
        qy2 = min(h, y2 + QWEN_PAD_BELOW_PX)
        qwen_lbl, qwen_status = qwen_label(img[qy1:qy2, qx1:qx2], engine[3], engine[4])
        if qwen_lbl:
            clean_lbl, needs_review = qwen_lbl, False
            method = "doclayout_qwen"
    elif needs_review:
        qwen_status = "unavailable"

    if needs_review and ensure_qwen(engine):
        # Pass B: bottom 20% of the full sheet — USPTO patents print "FIG. N" here,
        # often inside the YOLO box so Pass A's crop is swamped by callout numbers.
        strip_y1 = max(0, h - int(h * 0.20))
        qwen_lbl, qwen_status = qwen_label(img[strip_y1:h, 0:w], engine[3], engine[4])
        if qwen_lbl:
            clean_lbl, needs_review = qwen_lbl, False
            method = "doclayout_qwen_strip"

    return {
        "box":            [x1, y1, x2, y2],
        "conf":           None,   # filled in by caller from the source fig dict
        "label":          clean_lbl,
        "cap":            cap,
        "label_rotation": label_rotation,
        "method":         method,
        "needs_review":   needs_review,
        "review_hint":    _review_hint_for_box([x1, y1, x2, y2]),
        "qwen_status":    qwen_status,
    }


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
    CROP_PAD_PX = crop_pad_px(w, h)

    # ── Pass 1: OCR every detected figure box ────────────────────────────────
    annotated: list[dict] = []   # each item carries box + OCR result
    for fig in figures:
        x1, y1, x2, y2 = fig["box"]
        x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
        x2, y2 = max(x1 + 1, min(x2, w)), max(y1 + 1, min(y2, h))

        # Only drop genuinely degenerate detections here (noise, not real figures).
        # The real MIN_CROP_PX gate is applied after padding/CC-snapping in Pass 3 —
        # a legitimately small figure can clear it once padded, so filtering on the
        # raw YOLO box size here would drop recoverable figures with no record at all.
        if (y2 - y1) < NOISE_FLOOR_PX or (x2 - x1) < NOISE_FLOOR_PX:
            continue

        item = _ocr_pass1([x1, y1, x2, y2], captions, img, reader, engine, w, h)
        item["conf"] = fig["conf"]
        annotated.append(item)

    # ── Pass 2: merge split crops ─────────────────────────────────────────────
    labeled   = [a for a in annotated if not a["needs_review"]]
    unlabeled = [a for a in annotated if a["needs_review"]]

    merged_labeled   = _merge_labeled(labeled)
    merged_unlabeled = _merge_fu(unlabeled)

    # A sheet with only one caption can only contain one figure. If detection
    # still left multiple disjoint _Fu fragments (e.g. a wide multi-rotor eVTOL
    # drawing split into left/right clusters with a gap > FU_MERGE_GAP_PX),
    # _merge_fu's proximity threshold won't catch it — union them all into one
    # full-figure crop instead of emitting several meaningless partial ones.
    if len(captions) <= 1 and not merged_labeled and len(merged_unlabeled) > 1:
        ub = union_box([m["box"] for m in merged_unlabeled])
        best = max(merged_unlabeled, key=lambda x: x["conf"])
        merged_unlabeled = [{
            "box":           ub,
            "conf":          best["conf"],
            "label":         None,
            "cap":           best.get("cap"),
            "label_rotation": 0,
            "method":        best.get("method", "doclayout_easyocr"),
            "needs_review":  True,
            "review_hint":   "single_caption_sheet_merge",
            "qwen_status":   best.get("qwen_status", "not_attempted"),
        }]

    to_save = merged_labeled + merged_unlabeled

    # ── Pass 3: crop, rotate, save ────────────────────────────────────────────
    sheet_rot_cache: int | None = None

    sheet_area = w * h
    img_gray_full = to_gray(img)
    cc_labels, cc_stats = _sheet_components(img_gray_full)
    snap_max_growth = int(min(_SNAP_MAX_GROWTH_MAX_PX,
                               max(_SNAP_MAX_GROWTH_MIN_PX, SNAP_MAX_GROWTH_FRAC * max(w, h))))

    records: list[dict] = []
    for idx, item in enumerate(to_save):
        other_boxes = [other["box"] for j, other in enumerate(to_save) if j != idx]

        # Snap the raw YOLO box to the connected ink components it already
        # touches before padding — recovers a clipped wingtip/rotor/leader-line
        # that's part of the same drawing stroke, instead of guessing a pixel
        # pad. Hard-clamped against neighbor boxes immediately after so a
        # bridging stroke into another figure can't swallow it.
        snapped_box = _snap_box_to_components(
            item["box"], cc_labels, cc_stats, w, h,
            search_pad=CROP_PAD_PX, max_growth=snap_max_growth)
        snapped_box = _clamp_grown_box_to_original_direction(item["box"], snapped_box, other_boxes)

        # Expand by CROP_PAD_PX on all sides, but never cross into a
        # neighboring figure box on the same sheet (prevents bleed-through
        # into the next figure's caption/leader-lines). If content still
        # touches the crop edge after that, try growing further first instead
        # of immediately giving up and flagging it.
        x1, y1, x2, y2, crop = _expand_box_until_clear(img, snapped_box, other_boxes, w, h, CROP_PAD_PX)

        if crop.size == 0:   # degenerate box (e.g. fully clamped to zero width/height) — nothing to save
            continue

        label_rotation = item["label_rotation"]
        needs_review   = item["needs_review"]
        review_hint    = item.get("review_hint", "")

        # Still below the minimum even after padding/CC-snapping — almost certainly
        # a bad split slice, but flag it for human review rather than silently
        # dropping the figure with no trace in the output at all.
        if _is_below_min_size(crop):
            needs_review = True
            review_hint  = "below_min_size"

        if label_rotation != 0:
            crop = np.rot90(crop, k=label_rotation // 90)
        elif needs_review:
            if sheet_rot_cache is None:
                sheet_rot_cache = infer_sheet_rotation(reader, img)
            if sheet_rot_cache != 0:
                crop = np.rot90(crop, k=sheet_rot_cache // 90)

        # Drawing strokes still touching the crop edge after the grow attempt
        # mean YOLO under-detected the figure's true extent and the saved crop
        # slices through real content — flag for human review instead of
        # silently auto-labelling it.
        if not needs_review and _crop_touches_border(crop):
            needs_review = True
            review_hint  = "crop_touches_border"

        if not needs_review and _oversized_box_overlaps_other_figure(item, to_save, sheet_area):
            needs_review = True
            review_hint  = "oversized_box_overlaps_other_figure"

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
            "review_hint":  review_hint,
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
