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
NMS_IOU      = 0.30    # IoU threshold for suppressing duplicate/nested figure boxes
MIN_CROP_PX  = 300     # discard crops smaller than this in either dimension (filters bad thin split slices)
IMGSZ        = 1024    # DocStructBench model was trained at 1024

# A single figure box taller than this (px) AND containing clear horizontal whitespace
# is likely a wrapper around multiple sub-figures — split it vertically.
SPLIT_HEIGHT_PX  = 1400
SPLIT_GAP_PX     = 30   # minimum whitespace run (px) to treat as a split point

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

# DocStructBench class names we care about (matched by NAME, not index).
_FIGURE_CLASS = "figure"
_CAPTION_CLASS = "figure_caption"

# Robust to EasyOCR misreads of the separator character:
#   "FIG. 1A"  "Fig. 2a"  "FIG 3"  "Fig_4a"  "Fig: 1"  "Fia. 2"  "Fig1"
#   "FIGURE 1A" (spelled out — e.g. US2020148347) and plural "FIGS. 2"
# Accepts any 0-2 non-alphanumeric chars between FIG[URE](S) and the number.
_FIG_KEY_RE = re.compile(r"FI[GA](?:URE)?S?[^A-Za-z0-9]{0,2}([0-9]+[A-Za-z]?)", re.IGNORECASE)


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
    # Row is "white" if >95% of pixels are above threshold 230
    row_white = np.mean(crop > 230, axis=1) > 0.95

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

    # Split at the midpoint of the largest gap
    best = max(gaps, key=lambda g: g[1] - g[0])
    split_y = y1 + (best[0] + best[1]) // 2

    top = {"box": [x1, y1, x2, split_y], "conf": fig["conf"]}
    bot = {"box": [x1, split_y, x2, y2],  "conf": fig["conf"]}

    # Recurse in case each half is still too tall
    return _split_large_figure(top, img_gray) + _split_large_figure(bot, img_gray)


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

    results = model.predict(source=img_np, imgsz=IMGSZ, conf=YOLO_CONF,
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
                figures.append(rec)
            elif cls_name == _CAPTION_CLASS:
                captions.append(rec)

    figures = _nms_figures(figures)

    split_figures: list[dict] = []
    for fig in figures:
        split_figures.extend(_split_large_figure(fig, img_gray))

    return split_figures, captions


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


def _qwen_label(img_crop_bgr: np.ndarray, qwen_model, qwen_processor) -> str | None:
    """
    Ask Qwen2.5-VL for the figure label of a single already-cropped image.
    Returns a clean label like '3A' or None on failure.
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
    if raw.lower() == "none":
        return None
    m = _FIG_KEY_RE.search(raw)
    return m.group(1) if m else None


_QWEN_UNAVAILABLE = False   # set True after first failed load — suppresses repeated warnings

def _ensure_qwen(engine: list) -> bool:
    """
    Lazy-load Qwen into engine[3] / engine[4] on first call.
    Returns True if Qwen is available, False if import fails.
    engine is a mutable list [model, reader, device, qwen_model, qwen_processor].
    """
    global _QWEN_UNAVAILABLE
    if engine[3] is not None:
        return True
    if _QWEN_UNAVAILABLE:
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
    except Exception as e:
        print(f"    ⚠ Qwen fallback unavailable: {e}")
        _QWEN_UNAVAILABLE = True
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


def _union_box(boxes: list[list[int]]) -> list[int]:
    """Return the bounding box that contains all input xyxy boxes."""
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


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
            merged.append({
                "box":   _union_box([x["box"] for x in items]),
                "conf":  best["conf"],
                "label": lbl,
                "cap":   best.get("cap"),
                "label_rotation": best.get("label_rotation", 0),
                "method": best.get("method", "doclayout_easyocr"),
                "needs_review": False,
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
        merged.append({
            "box":   _union_box([x["box"] for x in grp]),
            "conf":  best["conf"],
            "label": None,
            "cap":   best.get("cap"),
            "label_rotation": 0,
            "method": best.get("method", "doclayout_easyocr"),
            "needs_review": True,
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
        if needs_review and _ensure_qwen(engine):
            qx1 = max(0, x1 - QWEN_PAD_SIDE_PX)
            qy1 = max(0, y1 - QWEN_PAD_SIDE_PX)
            qx2 = min(w, x2 + QWEN_PAD_SIDE_PX)
            qy2 = min(h, y2 + QWEN_PAD_BELOW_PX)
            qwen_lbl = _qwen_label(img[qy1:qy2, qx1:qx2], engine[3], engine[4])
            if qwen_lbl:
                clean_lbl, needs_review = qwen_lbl, False
                method = "doclayout_qwen"

        annotated.append({
            "box":            [x1, y1, x2, y2],
            "conf":           fig["conf"],
            "label":          clean_lbl,
            "cap":            cap,
            "label_rotation": label_rotation,
            "method":         method,
            "needs_review":   needs_review,
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
        x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
        x2, y2 = max(x1 + 1, min(x2, w)), max(y1 + 1, min(y2, h))

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
