"""
figure_detection.py — DocLayout-YOLO engine + per-sheet figure/caption detection.

Owns everything up to "here are the figure and caption boxes on this sheet": loading
the YOLO model, running it, and the post-processing (NMS, coplanar-fragment merge,
point-shooting compound-figure split) that turns raw YOLO output into clean figure
boxes. Labeling (OCR) and cropping (padding/snapping) are separate concerns — see
figure_labeling.py and figure_cropping.py.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from cv_utils import ink_mask, iou, union_box

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
IMGSZ        = 1024    # DocStructBench model was trained at 1024

# DocStructBench class names we care about (matched by NAME, not index).
_FIGURE_CLASS = "figure"
_CAPTION_CLASS = "figure_caption"


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


# ─── Post-processing helpers ──────────────────────────────────────────────────

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
            if iou(ca, ka) > iou_thresh:
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
                "box":  union_box([f["box"] for f in group]),
                "conf": max(f["conf"] for f in group),
            })

    return merged


def _point_shooting_split(
    fig: dict,
    img_gray: np.ndarray,
    n_shots: int | None = None,
    radius: int = 3,
    min_area_frac: float = 0.04,
    shots_per_px: float = 1 / 500,
) -> list[dict]:
    """
    Point-shooting compound-figure splitter — Hoque et al., SDU@AAAI 2022.

    Randomly places dots across the figure crop. Dots that land on or adjacent
    to ink (dark pixels) are retained; the rest are discarded. The retained dots
    are filled and dilated to merge marks from the same drawing into one blob.
    Contour bounding boxes of the resulting blobs become candidate sub-figure
    regions returned in full-image coordinates.

    More robust than whitespace sweeping because it finds sub-figures by where
    the ink IS, not by looking for clean whitespace gaps between figures — gaps
    interrupted by caption text or touching figure edges still split correctly.

    Returns [fig] unchanged when fewer than 2 valid sub-regions are found
    (i.e. the figure is already a single drawing — no split needed).
    """
    x1, y1, x2, y2 = fig["box"]
    crop = img_gray[y1:y2, x1:x2]
    ch, cw = crop.shape[:2]

    # Skip crops too small to contain multiple sub-figures
    if ch < 200 or cw < 200:
        return [fig]

    # Binarise via Otsu so faint line-art is found, not just dark ink. uint8 0/255.
    bw = ink_mask(crop).astype(np.uint8) * 255

    # Shoot count scales with crop area so large crops aren't under-sampled and
    # small ones aren't wastefully over-sampled (clamped to a sane range).
    if n_shots is None:
        n_shots = int(min(8000, max(1500, ch * cw * shots_per_px)))

    # Shoot random dots; retain those touching ink within radius
    mask = np.zeros((ch, cw), dtype=np.uint8)
    rng  = np.random.default_rng(seed=42)   # deterministic — same result every run
    ys   = rng.integers(0, ch, n_shots)
    xs   = rng.integers(0, cw, n_shots)

    for py, px in zip(ys, xs):
        y_lo = max(0, int(py) - radius)
        y_hi = min(ch, int(py) + radius + 1)
        x_lo = max(0, int(px) - radius)
        x_hi = min(cw, int(px) + radius + 1)
        if bw[y_lo:y_hi, x_lo:x_hi].any():
            cv2.circle(mask, (int(px), int(py)), radius, 255, -1)

    # Dilate to bridge nearby dots that belong to the same drawing.
    # Kernel ~3% of the smaller crop dimension; bridges intra-figure gaps
    # while leaving the whitespace band between two figures intact.
    dil_size = max(15, min(ch, cw) // 30)
    kernel   = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dil_size, dil_size))
    mask     = cv2.dilate(mask, kernel, iterations=2)

    # Find external contours of connected blobs
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return [fig]

    # Filter tiny blobs; convert surviving boxes to full-image coordinates
    min_area  = min_area_frac * ch * cw
    sub_boxes = []
    for cnt in contours:
        bx, by, bw_, bh_ = cv2.boundingRect(cnt)
        if bw_ * bh_ >= min_area:
            sub_boxes.append({
                "box":  [x1 + bx, y1 + by, x1 + bx + bw_, y1 + by + bh_],
                "conf": fig["conf"],
            })

    # Only return a split if we found at least 2 genuine sub-regions
    return sub_boxes if len(sub_boxes) >= 2 else [fig]


def detect_regions(model, img_path: Path, device: str = "cuda:0") -> tuple[list[dict], list[dict]]:
    """
    Run DocLayout-YOLO on one sheet and split detections into figures and captions.

    Returns (figures, captions); each item is {"box": [x1, y1, x2, y2], "conf": float}
    in original-image pixel coordinates.

    Post-processing:
    - NMS dedup: removes overlapping/nested boxes (lowered conf threshold picks up more)
    - Point-shooting split: wrapper boxes enclosing multiple sub-figures are split by ink density
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

    # Apply point-shooting split to every detected box (Hoque et al. 2022).
    # Unlike a whitespace-sweep approach, point-shooting finds sub-figures by
    # ink density — it works even when the gap between two sub-figures is
    # narrow, interrupted by caption text, or zero (touching). Applied per-box
    # so compound wrappers that YOLO missed are still caught when multiple
    # boxes are returned.
    split_results: list[dict] = []
    for _fig in figures:
        _sub = _point_shooting_split(_fig, img_gray)
        split_results.extend(_sub)
    figures = split_results

    # Re-merge any coplanar fragments introduced by the split, then re-apply
    # the minimum-area filter to drop slivers.
    if len(figures) > 1:
        figures = _merge_coplanar_fragments(figures)
        _max_area = max(
            (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1])
            for f in figures
        )
        figures = [
            f for f in figures
            if (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1])
            >= 0.12 * _max_area
        ]

    return figures, captions
