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

YOLO_CONF = 0.40       # minimum detection confidence; below ~0.4 tends to be whole-page ghost boxes
MIN_CROP_PX = 150      # discard crops smaller than this in either dimension
IMGSZ = 1024           # DocStructBench model was trained at 1024

# DocStructBench class names we care about (matched by NAME, not index).
_FIGURE_CLASS = "figure"
_CAPTION_CLASS = "figure_caption"

_FIG_KEY_RE = re.compile(r"FIG(?:URE)?S?\.?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)


# ─── Engine ───────────────────────────────────────────────────────────────────

def build_engine(weights: str = DEFAULT_WEIGHTS, device: str = "cuda:0"):
    """
    Load DocLayout-YOLO + an EasyOCR reader once. Returns (model, reader, device).

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

    return model, reader, device


# ─── Detection ────────────────────────────────────────────────────────────────

def detect_regions(model, img_path: Path, device: str = "cuda:0") -> tuple[list[dict], list[dict]]:
    """
    Run DocLayout-YOLO on one sheet and split detections into figures and captions.

    Returns (figures, captions); each item is {"box": [x1, y1, x2, y2], "conf": float}
    in original-image pixel coordinates.
    """
    img_np = np.array(Image.open(img_path).convert("RGB"))
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
    """
    Try OCR at 0° first; if no FIG match, retry with rotation_info so EasyOCR
    also tests 90 / 180 / 270° — handles landscape captions on portrait sheets.
    Returns the matched label string or None.
    """
    for kwargs in [{"detail": 0}, {"detail": 0, "rotation_info": [90, 180, 270]}]:
        try:
            texts = reader.readtext(crop, **kwargs)
        except Exception:
            continue
        joined = " ".join(texts)
        m = _FIG_KEY_RE.search(joined)
        if m:
            return m.group(1)
    return None


def read_label(reader, img: np.ndarray, cap_box: list[int] | None,
               fig_box: list[int] | None = None) -> tuple[str | None, bool]:
    """
    OCR the caption region (with rotation fallback) and extract a clean figure label.

    If cap_box is None or yields no match, falls back to scanning the figure box itself
    for an embedded rotated label (e.g. 'Fig. 1' printed vertically inside the drawing).

    Returns (clean_label, needs_review). 'FIG. 2A' -> ('2A', False); unreadable -> (None, True).
    """
    h, w = img.shape[:2]

    def _read_region(box):
        x1, y1, x2, y2 = box
        pad = 4
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
        region = img[y1:y2, x1:x2]
        if region.size == 0:
            return None
        return _ocr_for_label(reader, region)

    # Pass 1: dedicated caption box
    if cap_box is not None:
        lbl = _read_region(cap_box)
        if lbl:
            return lbl, False

    # Pass 2: scan a small MARGIN around the figure box where rotated captions often sit
    # (patents sometimes print "Fig. N" beside the drawing, outside the detected region).
    # We expand by 15% on each side and restrict to outside the original fig_box so we
    # don't match reference numerals inside the drawing.
    if fig_box is not None:
        fx1, fy1, fx2, fy2 = fig_box
        fw, fh = fx2 - fx1, fy2 - fy1
        margin_x = max(10, int(fw * 0.15))
        margin_y = max(10, int(fh * 0.10))
        expanded = [max(0, fx1 - margin_x), max(0, fy1 - margin_y),
                    min(w, fx2 + margin_x), min(h, fy2 + margin_y)]
        lbl = _read_region(expanded)
        if lbl:
            return lbl, False

    return None, True


# ─── Cropping ─────────────────────────────────────────────────────────────────

def crop_and_save(img_path: Path, figures: list[dict], captions: list[dict],
                  reader, out_dir: Path) -> list[dict]:
    """
    For each detected figure: match a caption, OCR its label, crop the figure box
    (drawing only — no caption, best for the downstream DINOv2 dataset) from the
    original full-res image, and save with the project naming convention.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(str(img_path))
    if img is None:
        return []
    h, w = img.shape[:2]

    records: list[dict] = []
    for idx, fig in enumerate(figures):
        x1, y1, x2, y2 = fig["box"]
        x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
        x2, y2 = max(x1 + 1, min(x2, w)), max(y1 + 1, min(y2, h))

        crop = img[y1:y2, x1:x2]
        if crop.shape[0] < MIN_CROP_PX or crop.shape[1] < MIN_CROP_PX:
            continue

        cap = _match_caption(fig["box"], captions)
        clean_lbl, needs_review = read_label(reader, img,
                                             cap["box"] if cap else None,
                                             fig_box=fig["box"])

        suffix = f"_F{clean_lbl}" if not needs_review else "_Fu"
        out_path = out_dir / f"{img_path.stem}_crop_{idx}{suffix}.png"
        cv2.imwrite(str(out_path), crop)

        records.append({
            "original": img_path.name,
            "output": out_path.name,
            "label": clean_lbl,
            "box_px": [x1, y1, x2, y2],
            "method": "doclayout_easyocr",
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
    """Detect + crop one sheet. engine = (model, reader, device)."""
    model, reader, device = engine
    figures, captions = detect_regions(model, img_path, device=device)
    crops = crop_and_save(img_path, figures, captions, reader, out_dir)
    return {"image": img_path.name, "figures": figures, "captions": captions, "crops": crops}
