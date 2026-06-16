"""
segmenter.py — Split compound drawing pages into individual sub-figures.

Uses the pre-trained HR-Net model from:
    GoFigure-LANL/figure-segmentation (SDU@AAAI 2022)
    "Segmenting Technical Drawing Figures in US Patents"
    Hoque, Wei, Choudhury, Ajayi, Gryder, Wu, Oyen

The model takes a full drawing page (which may contain several sub-figures
arranged together) and produces a binary segmentation mask. Connected regions
in the mask are each cropped out as an individual sub-figure.

SETUP
-----
Download the pre-trained weights (run once):
    python scripts/download_weights.py

This places  models/model-hrnet-new1.h5  in the project root.

Public API
----------
load_segmenter(cfg)                                        → Keras model
segment_page(img_path, model, cfg)      → list[tuple[Path, tuple|None]]
segment_patent(patent_id, cfg, raw_dir, model)  → dict[str, list[tuple[Path, tuple|None]]]
"""

import json

import cv2
import numpy as np
from pathlib import Path
from PIL import Image

_MODEL_INPUT_SIZE = 128   # HR-Net was trained at 128×128


# ─── Model loading ────────────────────────────────────────────────────────────

def load_segmenter(cfg: dict):
    """
    Load the HR-Net Keras model from the weights file.

    Raises FileNotFoundError with download instructions if the weights are missing.
    Requires TensorFlow: pip install tensorflow
    """
    try:
        from tensorflow import keras
    except ImportError as e:
        raise ImportError(
            "TensorFlow is required for figure segmentation.\n"
            "Install it with:  pip install tensorflow"
        ) from e

    weights_path = Path(cfg["segmenter"]["model_path"])
    if not weights_path.is_absolute():
        # Resolve relative path from project root (parent of src/)
        weights_path = Path(__file__).resolve().parent.parent / weights_path

    if not weights_path.exists():
        raise FileNotFoundError(
            f"HR-Net weights not found at: {weights_path}\n"
            "Download them by running:  python scripts/download_weights.py\n"
            "Source: https://drive.google.com/drive/folders/12SRFMMXR0ZMKnRue7pBvC_rWjPey7MQh"
        )

    # compile=False skips optimizer reconstruction — we only need inference,
    # and the model was saved with Keras 2.2.4 whose Adam used `lr=` which
    # Keras 3.x no longer accepts.
    model = keras.models.load_model(str(weights_path), compile=False)
    print(f"HR-Net loaded from {weights_path.name}")
    return model


# ─── Segmentation ─────────────────────────────────────────────────────────────

def _predict_mask(model, img: Image.Image) -> np.ndarray:
    """
    Run HR-Net on one image and return a binary mask at the original resolution.

    The model runs at 128×128; the resulting mask is scaled back to the
    original image size using nearest-neighbour interpolation so bounding
    box coordinates map directly to original pixels.
    """
    orig_w, orig_h = img.size
    img_gray = img.convert("L").resize((_MODEL_INPUT_SIZE, _MODEL_INPUT_SIZE))
    arr = np.array(img_gray, dtype=np.float32) / 255.0
    arr = arr.reshape(1, _MODEL_INPUT_SIZE, _MODEL_INPUT_SIZE, 1)

    pred = model.predict(arr, verbose=0)
    mask_small = (pred[0, :, :, 0] > 0.5).astype(np.uint8) * 255

    mask_full = cv2.resize(mask_small, (orig_w, orig_h),
                           interpolation=cv2.INTER_NEAREST)
    return mask_full


def _mask_to_bboxes(mask: np.ndarray, min_size: int = 50) -> list[tuple]:
    """
    Extract (x1, y1, x2, y2) bounding boxes of individual sub-figures from mask.

    Post-processing mirrors the GoFigure testing script:
      1. Gaussian blur to reduce noise
      2. Binary-inverse Otsu threshold
      3. Morphological closing to connect nearby regions
      4. cv2.findContours to get individual regions
      5. Drop regions smaller than min_size in either dimension
    """
    blurred = cv2.GaussianBlur(mask, (5, 5), 0)
    _, thresh = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    kernel = np.ones((5, 5), np.uint8)
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    bboxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < min_size or h < min_size:
            continue
        bboxes.append((x, y, x + w, y + h))

    return bboxes


def segment_page(
    img_path: Path, model, cfg: dict
) -> list[tuple[Path, tuple | None]]:
    """
    Segment one full drawing page into individual sub-figure crops.

    Returns a list of (path, bbox) pairs where:
      - Single-figure page: [(img_path, None)]   — original file unchanged
      - Split page:  [(crop_s01, (x1,y1,x2,y2)), ...]  — bbox in original pixels

    The bbox coordinates allow callers to spatially match pre-OCR'd page labels
    to individual crops even when the label text was outside the crop area.
    """
    min_px = cfg.get("segmenter", {}).get("min_crop_pixels", 50)

    img = Image.open(img_path).convert("RGB")

    try:
        mask = _predict_mask(model, img)
        bboxes = _mask_to_bboxes(mask, min_size=min_px)
    except Exception as exc:
        print(f"    Segmentation failed for {img_path.name}: {exc} — keeping page as-is")
        return [(img_path, None)]

    if len(bboxes) <= 1:
        return [(img_path, None)]

    # Sort crops top-to-bottom (primary), left-to-right (secondary)
    bboxes_sorted = sorted(bboxes, key=lambda b: (b[1], b[0]))
    crops: list[tuple[Path, tuple]] = []

    for n, (x1, y1, x2, y2) in enumerate(bboxes_sorted, start=1):
        crop = img.crop((x1, y1, x2, y2))
        dest = img_path.parent / f"{img_path.stem}_s{n:02d}.png"
        crop.save(dest, "PNG")
        crops.append((dest, (x1, y1, x2, y2)))

    # Delete the original full page — it has been replaced by its sub-crops
    img_path.unlink()

    return crops


def segment_patent(
    patent_id: str,
    cfg: dict,
    raw_dir: Path,
    model,
) -> dict[str, list[tuple[Path, tuple | None]]]:
    """
    Run figure segmentation on all downloaded drawing pages for one patent.

    For each fig_XX.png that contains multiple sub-figures, splits it into
    fig_XX_s01.png, fig_XX_s02.png, etc. and deletes the original page.
    Single-figure pages are returned as-is (no new files written).

    Bounding boxes (in original page pixel coordinates) are saved to a sidecar
    JSON file so they survive across notebook re-runs (idempotent).

    Returns a dict mapping each original page stem to its (crop, bbox) list:
        { "fig_01": [(Path("fig_01.png"), None)],
          "fig_08": [(Path("fig_08_s01.png"), (x1,y1,x2,y2)),
                     (Path("fig_08_s02.png"), (x1,y1,x2,y2))], ... }

    bbox is None for single-figure pages (no crop was extracted).
    The dict is ordered by page number so iteration is in document order.
    """
    patent_dir   = raw_dir / patent_id
    seg_map_path = patent_dir / f"{patent_id}_seg_map.json"
    pages        = sorted(patent_dir.glob("fig_[0-9]*.png"))

    if not pages and not seg_map_path.exists():
        print(f"  No drawing pages found in {patent_dir}")
        return {}

    # ── Idempotency: load from sidecar JSON (written on first run) ─────────────
    if seg_map_path.exists():
        try:
            raw: dict = json.loads(seg_map_path.read_text())
            mapping: dict[str, list[tuple[Path, tuple | None]]] = {}
            for page_stem, crops_data in raw.items():
                entries = []
                for fname, bbox_list in crops_data.items():
                    fpath = patent_dir / fname
                    bbox  = tuple(bbox_list) if bbox_list else None
                    entries.append((fpath, bbox))
                mapping[page_stem] = entries
            total = sum(len(v) for v in mapping.values())
            print(f"  Already segmented — {total} figure files across {len(mapping)} pages")
            return mapping
        except Exception as exc:
            print(f"  Warning: could not read seg_map, re-segmenting ({exc})")

    # Legacy idempotency (split files exist but no sidecar) — no bbox data
    if any(patent_dir.glob("fig_*_s*.png")):
        mapping = {}
        for f in sorted(patent_dir.glob("fig_*.png")):
            page_stem = f.stem.rsplit("_s", 1)[0] if "_s" in f.stem else f.stem
            mapping.setdefault(page_stem, []).append((f, None))
        total = sum(len(v) for v in mapping.values())
        print(f"  Already segmented — {total} figure files across {len(mapping)} pages "
              f"(no bbox data — re-run for spatial matching)")
        return mapping

    # ── Fresh segmentation run ─────────────────────────────────────────────────
    mapping   = {}
    seg_data: dict[str, dict[str, list | None]] = {}
    n_split   = 0

    for page_path in pages:
        crops_with_bboxes = segment_page(page_path, model, cfg)
        mapping[page_path.stem] = crops_with_bboxes

        page_data: dict[str, list | None] = {}
        for crop_path, bbox in crops_with_bboxes:
            page_data[crop_path.name] = list(bbox) if bbox else None
        seg_data[page_path.stem] = page_data

        if len(crops_with_bboxes) > 1:
            n_split += 1
            print(f"    {page_path.name} → {len(crops_with_bboxes)} sub-figures")

    # Save sidecar for future idempotent runs
    seg_map_path.write_text(json.dumps(seg_data, indent=2))

    total = sum(len(v) for v in mapping.values())
    label = f"{n_split} page(s) split" if n_split else "no splits needed"
    print(f"  Segmentation: {len(pages)} pages → {total} figures ({label})")
    return mapping
