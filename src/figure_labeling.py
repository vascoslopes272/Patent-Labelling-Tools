"""
figure_labeling.py — recovering the "FIG. N" label for a detected figure box.

Owns the caption-matching + OCR cascade (EasyOCR, with a lazy Qwen2.5-VL fallback
for sheets EasyOCR can't read), plus the rotation helpers used to make sure a
labeled crop is saved upright. Detection (figure_detection.py) and cropping
(figure_cropping.py) are separate concerns.
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from cv_utils import ink_mask, x_overlap

# Context padding around the figure box for the Qwen fallback. The caption ("FIG. n")
# is usually printed OUTSIDE the YOLO figure box — without this margin Qwen never sees it.
# 350px below matches the EasyOCR below-strip pass; smaller side/top pads catch
# rotated labels printed beside or above the drawing.
QWEN_PAD_BELOW_PX = 350
QWEN_PAD_SIDE_PX  = 150

# Robust to EasyOCR misreads of the separator character:
#   "FIG. 1A"  "Fig. 2a"  "FIG 3"  "Fig_4a"  "Fig: 1"  "Fia. 2"  "Fig1"
#   "FIGURE 1A" (spelled out — e.g. US2020148347) and plural "FIGS. 2"
# Accepts any 0-2 non-alphanumeric chars between FIG[URE](S) and the number.
FIG_KEY_RE = re.compile(r"FI[GA](?:URE)?S?[^A-Za-z0-9]{0,2}([0-9]+[A-Za-z]?)", re.IGNORECASE)

# Figure numbers above this are almost certainly component callouts (e.g. "203g")
# misread as figure labels — patents rarely have more than 50 sheets.
MAX_FIG_NUMBER = 99


def valid_fig_label(label: str) -> bool:
    """Return False if the numeric part of a label looks like a component callout."""
    m = re.match(r"^([0-9]+)", label)
    return bool(m) and int(m.group(1)) <= MAX_FIG_NUMBER


# ─── Caption matching ──────────────────────────────────────────────────────────

def match_caption(fig_box: list[int], captions: list[dict]) -> dict | None:
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
        if x_overlap(fig_box, cap["box"]) > 0 and cy1 >= fy1:
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


# ─── OCR ────────────────────────────────────────────────────────────────────────

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
        m = FIG_KEY_RE.search(joined)
        if m:
            return m.group(1), degrees
    return None, 0


def _figure_box_passes(fig_box: list[int], w: int, h: int) -> list[list[int]]:
    """
    Candidate sub-regions of `fig_box` to OCR for a label, in priority order — a
    label can sit in any of several places relative to the drawing depending on
    how the sheet was laid out (corner, below, margin, or tucked into a bottom
    corner on a rotated sheet). Kept as data (rather than one block of copy-pasted
    OCR calls) so passes are easy to inspect, add, or reorder.

    The sheet-bottom-strip pass is gated on the figure actually sitting near the
    page bottom: on a multi-figure sheet (e.g. two stacked isometric views), a
    full-width bottom strip would just as readily catch a DIFFERENT figure's
    caption and mislabel this one — restricting it to this figure's own x-span
    and to figures near the bottom avoids that cross-talk.
    """
    fx1, fy1, fx2, fy2 = fig_box
    fw, fh = fx2 - fx1, fy2 - fy1
    margin_x     = max(10, int(fw * 0.15))
    margin_above = max(10, int(fh * 0.08))

    passes = [
        [fx1, fy1, fx1 + int(fw * 0.45), fy1 + int(fh * 0.25)],            # top-left corner
        [fx2 - int(fw * 0.45), fy1, fx2, fy1 + int(fh * 0.25)],            # top-right corner
        [fx1, fy2, fx2, min(h, fy2 + 350)],                                # strip below the box
        [fx1 + int(fw * 0.1), fy2 - int(fh * 0.15), fx2 - int(fw * 0.1), fy2],  # bottom-center
        [max(0, fx1 - margin_x), fy1, fx1, fy2],                           # left margin
        [fx2, fy1, min(w, fx2 + margin_x), fy2],                           # right margin
        [fx1, max(0, fy1 - margin_above), fx2, fy1],                       # above the box
    ]
    if fy2 >= h - 400:
        passes.append([fx1, max(0, h - 350), fx2, h])                      # sheet-bottom strip
    passes.append([fx1, fy2 - int(fh * 0.25), fx1 + int(fw * 0.45), fy2])  # bottom-left corner
    passes.append([fx2 - int(fw * 0.45), fy2 - int(fh * 0.25), fx2, fy2])  # bottom-right corner
    return passes


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

    # Dedicated caption box first — most reliable when DocLayout-YOLO found one.
    if cap_box is not None:
        lbl, rot = _read_region(cap_box)
        if lbl:
            return lbl, False, rot

    if fig_box is not None:
        for box in _figure_box_passes(fig_box, w, h):
            lbl, rot = _read_region(box)
            if lbl:
                return lbl, False, rot

        # Last resort: whole figure box at all 4 rotations — slow but recovers
        # sheets where the label is embedded inside the drawing area.
        fx1, fy1, fx2, fy2 = fig_box
        lbl, rot = _ocr_for_label_and_rotation(reader, img[fy1:fy2, fx1:fx2])
        if lbl:
            return lbl, False, rot

    return None, True, 0


# ─── Rotation ───────────────────────────────────────────────────────────────────

def auto_rotate(crop_bgr: np.ndarray) -> np.ndarray:
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

    bw = ink_mask(crop_bgr).astype(np.uint8)

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


def infer_sheet_rotation(reader, img: np.ndarray) -> int:
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


# ─── Qwen2.5-VL fallback ────────────────────────────────────────────────────────

def qwen_label(img_crop_bgr: np.ndarray, qwen_model, qwen_processor) -> tuple[str | None, str]:
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
    m = FIG_KEY_RE.search(raw)
    return (m.group(1) if m else None), "ok"


_QWEN_LOAD_FAILED = False   # set True only after a non-transient (import/missing-dep) failure

def ensure_qwen(engine: list) -> bool:
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
