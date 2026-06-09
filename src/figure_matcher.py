"""
figure_matcher.py — EasyOCR-based figure labelling for PatSeer drawing sheets.

Supported file types (as produced by patseer_downloader.py):
  img  — PatSeer pre-crops; may still contain sub-figures; splitting applied
  D    — full drawing sheets; splitting applied
  FAT  — composite sheets; always split, always _Fu

Processing order per patent: img* → D* → FAT* (each group sorted numerically).
Raw files are never modified; all crops are written to matched/<patent_id>/.

Public API
----------
build_easyocr_reader(gpu)                                       → easyocr.Reader
process_patent(patent_id, raw_dir, matched_dir,
               description_text, cfg, reader)                   → dict
process_all_patents(df, cfg, reader)                            → pd.DataFrame
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import easyocr
import numpy as np
import pandas as pd


# ─── Internal helpers ─────────────────────────────────────────────────────────

_FIG_KEY_RE = re.compile(r"FIG(?:URE)?S?\.?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)


def _white_row_mask(gray: np.ndarray, threshold: float = 0.95) -> np.ndarray:
    return (gray >= 250).mean(axis=1) >= threshold


def _white_col_mask(gray: np.ndarray, threshold: float = 0.95) -> np.ndarray:
    return (gray >= 250).mean(axis=0) >= threshold


def _find_band_boundaries(
    white_mask: np.ndarray, min_thickness: int
) -> list[tuple[int, int]]:
    bands: list[tuple[int, int]] = []
    in_band = False
    run_start = 0
    for i, val in enumerate(white_mask):
        if val and not in_band:
            in_band = True
            run_start = i
        elif not val and in_band:
            if i - run_start >= min_thickness:
                bands.append((run_start, i - 1))
            in_band = False
    if in_band and len(white_mask) - run_start >= min_thickness:
        bands.append((run_start, len(white_mask) - 1))
    return bands


def _file_sort_key(name: str) -> int:
    m = re.search(r"_(?:img|D|FAT)(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def _patent_core(patent_id: str) -> str:
    """Strip country/kind codes; pad compact 6-digit US serial to 7."""
    m = re.match(r"^[A-Z]{2,}(\d+)", patent_id, re.IGNORECASE)
    if not m:
        return patent_id
    num = m.group(1)
    m2 = re.match(r"^((?:19|20)\d{2})(\d{6})$", num)
    if m2:
        num = m2.group(1) + "0" + m2.group(2)
    return num


def _build_folder_map(raw_dir: Path) -> dict[str, Path]:
    return {_patent_core(d.name): d for d in raw_dir.iterdir() if d.is_dir()}


def _split_with_bboxes(
    img_path: Path,
) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
    """
    Split image at whitespace bands (>95% white pixels, min 15 px thick).
    Returns (crop_array, (x1, y1, x2, y2)) pairs in original pixel coordinates,
    sorted top-to-bottom then left-to-right.
    Falls back to the full image as a single crop when no bands are found.
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
    h, w = gray.shape

    h_bands = _find_band_boundaries(_white_row_mask(gray), min_thickness=15)
    if h_bands:
        result: list[tuple[np.ndarray, tuple[int, int, int, int]]] = []
        prev = 0
        for bs, be in h_bands:
            sub = img[prev:bs, :]
            if sub.size > 0:
                result.append((sub, (0, prev, w - 1, bs - 1)))
            prev = be + 1
        tail = img[prev:, :]
        if tail.size > 0:
            result.append((tail, (0, prev, w - 1, h - 1)))
        if result:
            return result

    v_bands = _find_band_boundaries(_white_col_mask(gray), min_thickness=15)
    if v_bands:
        result = []
        prev = 0
        for bs, be in v_bands:
            sub = img[:, prev:bs]
            if sub.size > 0:
                result.append((sub, (prev, 0, bs - 1, h - 1)))
            prev = be + 1
        tail = img[:, prev:]
        if tail.size > 0:
            result.append((tail, (prev, 0, w - 1, h - 1)))
        if result:
            return result

    return [(img, (0, 0, w - 1, h - 1))]


def _easyocr_labels(
    img_path: Path,
    reader: easyocr.Reader,
    fig_regex: str,
) -> list[tuple[str, float, float]]:
    """
    Run EasyOCR on the full image and return (label_str, cx, cy) for every
    text detection that matches fig_regex.  Coordinates are in original pixels.

    Pre-loads with OpenCV (guarantees uint8) and passes the RGB array directly
    to avoid EasyOCR's internal scikit-image loader, which returns bool dtype
    for binary PNGs and causes a cvtColor crash.
    """
    img_bgr = cv2.imread(str(img_path))
    if img_bgr is None:
        return []
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    _re = re.compile(fig_regex, re.IGNORECASE)
    labels: list[tuple[str, float, float]] = []
    for bbox, text, _conf in reader.readtext(img_rgb):
        if _re.search(text):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            labels.append((text, sum(xs) / 4, sum(ys) / 4))
    return labels


def _parse_fig_key(label_str: str, fig_regex: str) -> tuple[int, str]:
    """Extract (num, letter) from a matched label string, e.g. 'FIG. 3A' → (3, 'A')."""
    m = re.search(fig_regex, label_str, re.IGNORECASE)
    if m:
        nm = re.match(r"^(\d+)([A-Za-z]?)$", m.group(1))
        if nm:
            return int(nm.group(1)), nm.group(2).upper()
    return 0, ""


def _description_fig_keys(description_text: str) -> list[tuple[int, str]]:
    """Return ordered unique (num, letter) figure keys from the description text."""
    seen: set[tuple[int, str]] = set()
    keys: list[tuple[int, str]] = []
    for m in _FIG_KEY_RE.finditer(description_text):
        nm = re.match(r"^(\d+)([A-Za-z]?)$", m.group(1).upper())
        if nm:
            key = (int(nm.group(1)), nm.group(2))
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _assign_labels_spatial(
    bboxes: list[tuple[int, int, int, int]],
    labels: list[tuple[str, float, float]],
    fig_regex: str,
) -> list[tuple[int, str] | None]:
    """
    For each crop bbox, assign the nearest unassigned OCR label whose center
    falls inside the bbox or within 80 px below it.
    Crops are processed in the order supplied (caller must sort beforehand).
    """
    assigned = [False] * len(labels)
    results: list[tuple[int, str] | None] = []

    for x1, y1, x2, y2 in bboxes:
        best_idx: int | None = None
        best_dist = float("inf")
        crop_cx = (x1 + x2) / 2
        crop_cy = (y1 + y2) / 2

        for i, (label_str, lcx, lcy) in enumerate(labels):
            if assigned[i]:
                continue
            in_box = x1 <= lcx <= x2 and y1 <= lcy <= y2
            below  = x1 <= lcx <= x2 and y2 < lcy <= y2 + 80
            if in_box or below:
                dist = ((lcx - crop_cx) ** 2 + (lcy - crop_cy) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i

        if best_idx is not None:
            assigned[best_idx] = True
            results.append(_parse_fig_key(labels[best_idx][0], fig_regex))
        else:
            results.append(None)

    return results


def _process_img_or_d(
    src_path: Path,
    src_type: str,
    patent_id: str,
    patent_out: Path,
    description_text: str,
    fig_regex: str,
    reader: easyocr.Reader,
    fu_counter: list[int],
) -> tuple[list[dict], bool]:
    """
    Process one img or D file.
    Returns (file_records, needs_review).
    """
    # Step 1 — EasyOCR on full image
    ocr_labels = _easyocr_labels(src_path, reader, fig_regex)

    # Step 2 — Whitespace band split + bbox recording
    crops = _split_with_bboxes(src_path)
    if not crops:
        return [], False
    crops.sort(key=lambda c: (c[1][1], c[1][0]))   # sort by (y1, x1)
    arrays = [c[0] for c in crops]
    bboxes = [c[1] for c in crops]

    file_records: list[dict] = []
    needs_review = False

    # Step 3 — Assign labels
    if ocr_labels:
        assignments = _assign_labels_spatial(bboxes, ocr_labels, fig_regex)
        for arr, assignment in zip(arrays, assignments):
            if assignment is not None:
                num, letter = assignment
                out_name = f"{patent_id}_F{num:03d}{letter}.png"
                label    = f"F{num:03d}{letter}"
            else:
                fu_counter[0] += 1
                out_name = f"{patent_id}_Fu{fu_counter[0]:03d}.png"
                label    = None
            cv2.imwrite(str(patent_out / out_name), arr)
            file_records.append({"original": src_path.name, "output": out_name,
                                  "label": label, "source_type": src_type})
    else:
        # Positional fallback
        fig_keys = _description_fig_keys(description_text)
        if len(arrays) == len(fig_keys) and fig_keys:
            for arr, (num, letter) in zip(arrays, fig_keys):
                out_name = f"{patent_id}_F{num:03d}{letter}.png"
                cv2.imwrite(str(patent_out / out_name), arr)
                file_records.append({"original": src_path.name, "output": out_name,
                                      "label": f"F{num:03d}{letter}", "source_type": src_type})
        else:
            needs_review = True
            for arr in arrays:
                fu_counter[0] += 1
                out_name = f"{patent_id}_Fu{fu_counter[0]:03d}.png"
                cv2.imwrite(str(patent_out / out_name), arr)
                file_records.append({"original": src_path.name, "output": out_name,
                                      "label": None, "source_type": src_type})

    return file_records, needs_review


# ─── Public API ───────────────────────────────────────────────────────────────

def build_easyocr_reader(gpu: bool = False) -> easyocr.Reader:
    """Initialise and return the EasyOCR reader. Call once per session."""
    models_dir = Path(__file__).resolve().parent.parent / "models"
    models_dir.mkdir(exist_ok=True)
    return easyocr.Reader(["en"], gpu=gpu, model_storage_directory=str(models_dir))


def process_patent(
    patent_id: str,
    raw_dir: Path,
    matched_dir: Path,
    description_text: str,
    cfg: dict,
    reader: easyocr.Reader,
) -> dict:
    """
    Process all PatSeer files for one patent.
    Returns a summary dict:
      {
        patent_id: str,
        total_crops: int,
        labeled: int,
        unlabeled: int,
        needs_review: bool,
        files: [{"original": str, "output": str, "label": str|None,
                 "source_type": "img"|"D"|"FAT"}]
      }
    """
    patent_raw = raw_dir / patent_id
    patent_out = matched_dir / patent_id
    patent_out.mkdir(parents=True, exist_ok=True)

    fig_regex = cfg["matching"]["fig_regex"]

    img_files = sorted(patent_raw.glob(f"{patent_id}_img*.png"),
                       key=lambda p: _file_sort_key(p.name))
    d_files   = sorted(patent_raw.glob(f"{patent_id}_D*.png"),
                       key=lambda p: _file_sort_key(p.name))
    fat_files = sorted(patent_raw.glob(f"{patent_id}_FAT*.png"),
                       key=lambda p: _file_sort_key(p.name))

    files_out: list[dict] = []
    needs_review = False
    fu_counter = [0]   # mutable so the helper can increment it

    for src_path, src_type in [(f, "img") for f in img_files] + [(f, "D") for f in d_files]:
        records, nr = _process_img_or_d(
            src_path, src_type, patent_id, patent_out,
            description_text, fig_regex, reader, fu_counter,
        )
        files_out.extend(records)
        if nr:
            needs_review = True

    # FAT — whitespace split only, all crops → _Fu
    for src_path in fat_files:
        crops = _split_with_bboxes(src_path)
        if not crops:
            continue
        crops.sort(key=lambda c: (c[1][1], c[1][0]))
        for arr, _ in crops:
            fu_counter[0] += 1
            out_name = f"{patent_id}_Fu{fu_counter[0]:03d}.png"
            cv2.imwrite(str(patent_out / out_name), arr)
            files_out.append({"original": src_path.name, "output": out_name,
                               "label": None, "source_type": "FAT"})

    labeled   = sum(1 for f in files_out if f["label"] is not None)
    unlabeled = len(files_out) - labeled

    return {
        "patent_id":    patent_id,
        "total_crops":  len(files_out),
        "labeled":      labeled,
        "unlabeled":    unlabeled,
        "needs_review": needs_review,
        "files":        files_out,
    }


def process_all_patents(
    df: pd.DataFrame,
    cfg: dict,
    reader: easyocr.Reader,
) -> pd.DataFrame:
    """
    Iterate over all patents in the DataFrame.
    Returns a results DataFrame with one row per output crop.
    """
    raw_dir     = cfg["paths"]["raw_images"]
    matched_dir = cfg["paths"]["matched"]
    folder_map  = _build_folder_map(raw_dir)

    rows: list[dict] = []

    for _, row in df.iterrows():
        excel_id = str(row.get("patent_id", "")).strip()
        if not excel_id:
            continue
        desc = str(row.get("description_of_drawings", "") or "")

        folder = folder_map.get(_patent_core(excel_id))
        if folder is None:
            print(f"  ⚠  No raw folder found for {excel_id} — skipping")
            continue
        actual_id = folder.name

        try:
            summary = process_patent(actual_id, raw_dir, matched_dir, desc, cfg, reader)
            for f in summary["files"]:
                rows.append({
                    "patent_id":    excel_id,
                    "original":     f["original"],
                    "output":       f["output"],
                    "label":        f["label"],
                    "source_type":  f["source_type"],
                    "needs_review": summary["needs_review"],
                    "labeled":      1 if f["label"] is not None else 0,
                    "unlabeled":    1 if f["label"] is None else 0,
                })
        except Exception as exc:
            print(f"  ✗  {excel_id}: {exc}")

    return pd.DataFrame(rows)
