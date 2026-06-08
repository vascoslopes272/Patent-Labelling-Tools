"""
figure_matcher.py — pure positional matching of patent figures to description keys.

No OCR, no external models, no PatFig.  Matching is based solely on document
order: the Nth figure crop is matched to the Nth key in the Brief Description
of the Drawings.  If the crop count does not equal the description count, all
figures are flagged as needs_review and assigned _Fu names.

Supported file types (as produced by patseer_downloader.py):
  img   — individual figure crops, no splitting applied
  D     — full drawing sheets, split at whitespace bands if needed
  FAT   — composite sheets, split at whitespace bands if needed

Processing order: img* → D* → FAT* (each group sorted numerically).
Original D and FAT files are always kept alongside their crops.

Public API
----------
clean_patent_filename(raw_name)            → (patent_id, file_type, file_index)
parse_description_figures(description)     → list[str]
detect_split_needed(img_path)              → int
split_image_by_whitespace(img_path)        → list[np.ndarray]
match_positionally(patent_id, img_dir, description_text) → list[dict]
rename_matched_files(matches, img_dir)     → dict
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np


# ─── Filename parsing ─────────────────────────────────────────────────────────

_CLEAN_NAME_RE = re.compile(
    r"^([A-Z]{2}[0-9]{4,}[A-Z0-9]*)_(img|D|FAT)(\d+)\.",
    re.IGNORECASE,
)


def clean_patent_filename(raw_name: str) -> tuple[str, str, str]:
    """
    Parse a cleaned PatSeer filename into (patent_id, file_type, file_index).

    Examples
    --------
    "US20220267016A1_img003.png"  → ("US20220267016A1", "img", "003")
    "US20220267016A1_D00005.png"  → ("US20220267016A1", "D",   "00005")
    "US20220267016A1_FAT001.png"  → ("US20220267016A1", "FAT", "001")
    """
    m = _CLEAN_NAME_RE.match(raw_name)
    if not m:
        raise ValueError(f"Cannot parse cleaned PatSeer filename: {raw_name!r}")
    patent_id  = m.group(1).upper()
    file_type  = m.group(2).upper() if m.group(2).upper() in ("D", "FAT") else "img"
    file_index = m.group(3)
    return patent_id, file_type, file_index


# ─── Description parsing ──────────────────────────────────────────────────────

_FIG_KEY_RE = re.compile(r"FIG(?:URE)?S?\.?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)


def _parse_description_map(description_text: str) -> dict[str, str]:
    """
    Parse the Brief Description of the Drawings into {fig_key: full_line}.
    Keys are normalised to uppercase (e.g. "2b" → "2B").
    Preserves document order (Python 3.7+).
    """
    result: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_key and current_lines:
            result[current_key] = " ".join(current_lines).strip()

    for line in description_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _FIG_KEY_RE.search(line)
        if m:
            _flush()
            current_key = m.group(1).upper()
            current_lines = [line]
        elif current_key:
            current_lines.append(line)

    _flush()
    return result


def parse_description_figures(description_text: str) -> list[str]:
    """
    Extract the ordered list of figure keys from a Brief Description text.

    Deduplicates while preserving document order.  Keys are normalised to
    uppercase.

    Example output: ["1", "2A", "2B", "2C", "3A", "3B", "3C"]
    """
    seen:   set[str]  = set()
    keys:   list[str] = []
    for m in _FIG_KEY_RE.finditer(description_text):
        key = m.group(1).upper()
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


# ─── Whitespace-band split detection ─────────────────────────────────────────

def _find_band_boundaries(
    white_mask: np.ndarray,
    min_thickness: int,
    offset: int = 0,
) -> list[tuple[int, int]]:
    """
    Find contiguous runs of True in white_mask that are >= min_thickness long.
    Returns a list of (start, end) positions in original-image coordinates.
    """
    bands:    list[tuple[int, int]] = []
    in_band   = False
    run_start = 0

    for i, val in enumerate(white_mask):
        if val and not in_band:
            in_band   = True
            run_start = i
        elif not val and in_band:
            if i - run_start >= min_thickness:
                bands.append((run_start + offset, i - 1 + offset))
            in_band = False

    if in_band and len(white_mask) - run_start >= min_thickness:
        bands.append((run_start + offset, len(white_mask) - 1 + offset))

    return bands


def _white_row_mask(gray: np.ndarray, threshold: float = 0.95) -> np.ndarray:
    """Boolean array: True for each row where ≥ threshold fraction of pixels ≥ 250."""
    return (gray >= 250).mean(axis=1) >= threshold


def _white_col_mask(gray: np.ndarray, threshold: float = 0.95) -> np.ndarray:
    """Boolean array: True for each column where ≥ threshold fraction of pixels ≥ 250."""
    return (gray >= 250).mean(axis=0) >= threshold


def detect_split_needed(img_path: Path) -> int:
    """
    Return the number of sub-figures detected in one image file.

    Searches only the middle 60 % of the image (rows 20 %–80 %, cols 20 %–80 %)
    to avoid confusing page borders with content bands.  A whitespace band must
    be ≥ 15 px thick and have > 95 % white pixels per row/column.

    Horizontal bands are checked first; vertical bands only if none found.
    Returns 1 when no band is detected (no split needed).
    """
    gray = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return 1

    h, w = gray.shape
    row_s, row_e = int(h * 0.2), int(h * 0.8)
    col_s, col_e = int(w * 0.2), int(w * 0.8)

    # ── Horizontal bands ─────────────────────────────────────────────────────
    mid_rows  = gray[row_s:row_e, :]
    h_mask    = _white_row_mask(mid_rows)
    h_bands   = _find_band_boundaries(h_mask, min_thickness=15, offset=row_s)
    if h_bands:
        return len(h_bands) + 1

    # ── Vertical bands ────────────────────────────────────────────────────────
    mid_cols  = gray[:, col_s:col_e]
    v_mask    = _white_col_mask(mid_cols)
    v_bands   = _find_band_boundaries(v_mask, min_thickness=15, offset=col_s)
    if v_bands:
        return len(v_bands) + 1

    return 1


def split_image_by_whitespace(img_path: Path) -> list[np.ndarray]:
    """
    Split an image at detected whitespace bands and return sub-images.

    Checks horizontal bands first; falls back to vertical bands.
    If no band is detected, returns the original image as a single-item list.
    Order: top-to-bottom, then left-to-right within each row.
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    row_s, row_e = int(h * 0.2), int(h * 0.8)
    col_s, col_e = int(w * 0.2), int(w * 0.8)

    # ── Try horizontal split ──────────────────────────────────────────────────
    mid_rows = gray[row_s:row_e, :]
    h_mask   = _white_row_mask(mid_rows)
    h_bands  = _find_band_boundaries(h_mask, min_thickness=15, offset=row_s)
    if h_bands:
        return _split_along_bands(img, h_bands, axis=0)

    # ── Try vertical split ────────────────────────────────────────────────────
    mid_cols = gray[:, col_s:col_e]
    v_mask   = _white_col_mask(mid_cols)
    v_bands  = _find_band_boundaries(v_mask, min_thickness=15, offset=col_s)
    if v_bands:
        return _split_along_bands(img, v_bands, axis=1)

    return [img]


def _split_along_bands(
    img: np.ndarray,
    bands: list[tuple[int, int]],
    axis: int,
) -> list[np.ndarray]:
    """Cut the image at band positions and return the non-band sub-images."""
    slices: list[np.ndarray] = []
    prev = 0
    for band_start, band_end in bands:
        sub = img[prev:band_start, :] if axis == 0 else img[:, prev:band_start]
        if sub.size > 0:
            slices.append(sub)
        prev = band_end + 1
    tail = img[prev:, :] if axis == 0 else img[:, prev:]
    if tail.size > 0:
        slices.append(tail)
    return slices


# ─── Positional matching ──────────────────────────────────────────────────────

def _file_sort_key(name: str) -> int:
    """Numeric sort key for patent figure filenames."""
    m = re.search(r"_(?:img|D|FAT)(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def _fig_key_to_label(fig_key: str) -> str:
    """Convert a description fig key ("2B") to an output label ("F002B")."""
    m = re.match(r"^(\d+)([A-Za-z]?)$", fig_key.upper())
    if m:
        return f"F{int(m.group(1)):03d}{m.group(2)}"
    return f"F{fig_key.upper()}"


def match_positionally(
    patent_id: str,
    img_dir: Path,
    description_text: str,
) -> list[dict]:
    """
    Match all figure crops for a patent to description figure keys by position.

    Processing order
    ----------------
    1. All {patent_id}_img*.png  (sorted numerically) — no splitting
    2. All {patent_id}_D*.png    (sorted numerically) — splitting applied
    3. All {patent_id}_FAT*.png  (sorted numerically) — splitting applied

    Validation
    ----------
    Total crops MUST equal the number of description figure keys.
    If equal  → positional 1-to-1 match; needs_review = False.
    If NOT    → all matches flagged needs_review = True; _Fu names assigned.

    Returns one dict per final figure crop with the schema:

        source_file      : str   original filename in img_dir
        source_type      : str   "img" | "D" | "FAT"
        was_split        : bool  True when the source was split
        split_index      : int   0 if not split, 1/2/3… per crop
        fig_key          : str | None   from description order, or None
        description_line : str | None   full description line, or None
        match_method     : str  "positional"
        needs_review     : bool
        output_filename  : str
    """
    img_files  = sorted(img_dir.glob(f"{patent_id}_img*.png"),
                        key=lambda p: _file_sort_key(p.name))
    d_files    = sorted(img_dir.glob(f"{patent_id}_D*.png"),
                        key=lambda p: _file_sort_key(p.name))
    fat_files  = sorted(img_dir.glob(f"{patent_id}_FAT*.png"),
                        key=lambda p: _file_sort_key(p.name))

    desc_map  = _parse_description_map(description_text)
    fig_keys  = list(desc_map.keys())

    # ── Build global ordered crop list ────────────────────────────────────────
    crops: list[dict] = []

    for f in img_files:
        crops.append({
            "source_file":  f.name,
            "source_type":  "img",
            "was_split":    False,
            "split_index":  0,
            "_crop_array":  None,
        })

    for f in d_files:
        sub_images = split_image_by_whitespace(f)
        if len(sub_images) > 1:
            for j, arr in enumerate(sub_images, start=1):
                crops.append({
                    "source_file":  f.name,
                    "source_type":  "D",
                    "was_split":    True,
                    "split_index":  j,
                    "_crop_array":  arr,
                })
        else:
            crops.append({
                "source_file":  f.name,
                "source_type":  "D",
                "was_split":    False,
                "split_index":  0,
                "_crop_array":  sub_images[0] if sub_images else None,
            })

    for f in fat_files:
        sub_images = split_image_by_whitespace(f)
        if len(sub_images) > 1:
            for j, arr in enumerate(sub_images, start=1):
                crops.append({
                    "source_file":  f.name,
                    "source_type":  "FAT",
                    "was_split":    True,
                    "split_index":  j,
                    "_crop_array":  arr,
                })
        else:
            crops.append({
                "source_file":  f.name,
                "source_type":  "FAT",
                "was_split":    False,
                "split_index":  0,
                "_crop_array":  sub_images[0] if sub_images else None,
            })

    # ── Validate and assign names ─────────────────────────────────────────────
    needs_review = len(crops) != len(fig_keys)
    fu_counter   = 0
    results:  list[dict] = []

    for i, crop in enumerate(crops):
        source_stem = Path(crop["source_file"]).stem   # e.g. US…_img003

        if not needs_review and i < len(fig_keys):
            fig_key  = fig_keys[i]
            fig_label = _fig_key_to_label(fig_key)
            if crop["was_split"]:
                out_name = f"{source_stem}_crop{crop['split_index']:02d}_{fig_label}.png"
            else:
                out_name = f"{source_stem}_{fig_label}.png"
            matched_line = desc_map.get(fig_key)
        else:
            fu_counter += 1
            fig_key  = None
            fig_label = f"Fu{fu_counter:03d}"
            matched_line = None
            if crop["was_split"]:
                out_name = f"{source_stem}_crop{crop['split_index']:02d}_{fig_label}.png"
            else:
                out_name = f"{source_stem}_{fig_label}.png"

        results.append({
            "source_file":      crop["source_file"],
            "source_type":      crop["source_type"],
            "was_split":        crop["was_split"],
            "split_index":      crop["split_index"],
            "fig_key":          fig_key,
            "description_line": matched_line,
            "match_method":     "positional",
            "needs_review":     needs_review,
            "output_filename":  out_name,
            "_crop_array":      crop["_crop_array"],  # internal — used by rename_matched_files
        })

    return results


# ─── File renaming ────────────────────────────────────────────────────────────

def rename_matched_files(matches: list[dict], img_dir: Path) -> dict:
    """
    Rename or create files in img_dir according to the match results.

    Rules
    -----
    - Non-split img/D/FAT (was_split=False) : rename source_file → output_filename
    - Split D/FAT crop    (was_split=True)  : cv2.imwrite crop array to output_filename;
                                              original source file is KEPT alongside

    Returns a summary dict:
        renamed_F       : files saved with _F label (matched)
        renamed_Fu      : files saved with _Fu label (unmatched)
        kept_originals  : count of original D/FAT files kept alongside splits
        errors          : count of exceptions
    """
    renamed_F       = 0
    renamed_Fu      = 0
    errors          = 0
    kept_src:  set[str] = set()   # source files whose originals are kept

    for match in matches:
        src_path  = img_dir / match["source_file"]
        dest_path = img_dir / match["output_filename"]
        out_name  = match["output_filename"]

        try:
            if match["was_split"]:
                # Save crop as a new file; original source stays on disk
                arr = match.get("_crop_array")
                if arr is not None and arr.size > 0:
                    cv2.imwrite(str(dest_path), arr)
                kept_src.add(match["source_file"])
            else:
                # Rename the original file
                if src_path.exists():
                    src_path.rename(dest_path)

            if "_Fu" in out_name:
                renamed_Fu += 1
            else:
                renamed_F += 1

        except Exception as exc:
            print(f"  ✗  rename {match['source_file']} → {out_name}: {exc}")
            errors += 1

    return {
        "renamed_F":      renamed_F,
        "renamed_Fu":     renamed_Fu,
        "kept_originals": len(kept_src),
        "errors":         errors,
    }
