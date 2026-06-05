"""
ocr_labeler.py — Extract figure labels from patent drawing crops.

Implements the label-extraction method from:
    GoFigure-LANL/figure-segmentation  (patent-label/label_recognition.py)
    SDU@AAAI 2021: "Recognizing Figure Labels in Patents"
    Gong, Oyen et al.

The algorithm (replacing the previous simple top/bottom strip approach):
  1. Otsu threshold → binary image
  2. Fill holes → connected components → filter by area to isolate text-sized blobs
  3. Erosion to remove dashed leader lines
  4. Alpha-shape (Delaunay-based) to cluster surviving text blobs into label regions
  5. Pytesseract OCR on each candidate region (rotated if portrait)
  6. Regex filter to keep only "FIG. N[A]" tokens

Public API
----------
ocr_figure_label(img_path, cfg) → str | None
    Returns the normalised figure token ("FIG. 3A") or None if not found.
"""

import copy
import re
from pathlib import Path

import numpy as np
import scipy.ndimage
import skimage
import skimage.draw
import skimage.filters
import skimage.measure
import skimage.morphology
import skimage.transform
from PIL import Image
from scipy.spatial import Delaunay
from skimage.color import rgb2gray
from skimage.filters import threshold_otsu
from skimage.io import imsave

_FIG_TOKEN = re.compile(r"FIG\.?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)


def _find_fig_labels_with_positions(
    im: "Image.Image",
    scale: float,
) -> "list[tuple[str, int, int]]":
    """
    Run word-level OCR on an already-resized image and return every detected
    FIG. label together with its center in *original* page pixel coordinates.

    Parameters
    ----------
    im    : Resized PIL image fed to tesseract.
    scale : resize_factor = resized_dimension / original_dimension.
            Use to convert tesseract pixel coords back to original-page coords.

    Returns
    -------
    list of (label, cx_orig, cy_orig) sorted top-to-bottom, left-to-right.
    e.g. [("FIG. 2", 340, 812), ("FIG. 3", 890, 812)]
    """
    import pytesseract

    try:
        data = pytesseract.image_to_data(
            im, config="--psm 6", output_type=pytesseract.Output.DICT
        )
    except Exception:
        return []

    words   = data["text"]
    lefts   = data["left"]
    tops    = data["top"]
    widths  = data["width"]
    heights = data["height"]
    n       = len(words)

    labels: list[tuple[str, int, int]] = []
    seen:   set[str] = set()

    i = 0
    while i < n:
        w = words[i].strip()
        if not w:
            i += 1
            continue

        if re.match(r"^(FIG\.?|FIGURE)$", w, re.IGNORECASE):
            # Look ahead up to 5 tokens for the figure number (handles "FIG . 2A")
            for j in range(i + 1, min(i + 6, n)):
                nw = words[j].strip().rstrip(".")
                if not nw:
                    continue
                m = re.match(r"^(\d+[A-Za-z]?)$", nw)
                if m:
                    label = f"FIG. {m.group(1).upper()}"
                    if label not in seen:
                        seen.add(label)
                        # Bounding box spans from start of "FIG" to end of number token
                        x0 = lefts[i]
                        x1 = lefts[j] + widths[j]
                        y0 = min(tops[i], tops[j])
                        y1 = max(tops[i] + heights[i], tops[j] + heights[j])
                        cx_resized = (x0 + x1) // 2
                        cy_resized = (y0 + y1) // 2
                        labels.append((
                            label,
                            int(cx_resized / scale),
                            int(cy_resized / scale),
                        ))
                    break  # found number — stop looking further
        i += 1

    # Sort in reading order: top-to-bottom, left-to-right
    labels.sort(key=lambda t: (t[2], t[1]))
    return labels


def _set_tesseract_cmd() -> None:
    """
    Ensure pytesseract can find the tesseract binary.
    When running inside a conda environment, tesseract lives in the env's bin/
    rather than on the system PATH.  We auto-detect it once and cache the result.
    """
    import shutil
    import pytesseract as _pt
    if shutil.which("tesseract"):
        return   # already on PATH, nothing to do
    # Try the conda env that owns the current Python interpreter
    import sys, os
    conda_bin = os.path.join(os.path.dirname(sys.executable), "tesseract")
    if os.path.isfile(conda_bin):
        _pt.pytesseract.tesseract_cmd = conda_bin


# ─── Alpha-shape helpers (ported from GoFigure label_recognition.py) ─────────

def _edge_length(pa: np.ndarray, pb: np.ndarray) -> float:
    return float(np.sqrt((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2))


def _add_edge(edges: set, i: int, j: int, only_outer: bool = True) -> None:
    if (i, j) in edges or (j, i) in edges:
        if only_outer:
            edges.discard((j, i))
        return
    edges.add((i, j))


def _alpha_shape(points: np.ndarray, alpha: float, only_outer: bool = True) -> set:
    """Compute the alpha-shape (concave hull) of a 2-D point set."""
    tri = Delaunay(points)
    edges: set = set()
    for ia, ib, ic in tri.vertices:
        pa, pb, pc = points[ia], points[ib], points[ic]
        a = _edge_length(pa, pb)
        b = _edge_length(pb, pc)
        c = _edge_length(pc, pa)
        s = (a + b + c) / 2.0
        area = np.sqrt(max(s * (s - a) * (s - b) * (s - c), 0.0))
        if area < 1e-10:
            continue
        circum_r = a * b * c / (4.0 * area)
        if circum_r < alpha:
            _add_edge(edges, ia, ib, only_outer)
            _add_edge(edges, ib, ic, only_outer)
            _add_edge(edges, ic, ia, only_outer)
    return edges


def _draw_mask(points: np.ndarray, edges: set, shape: tuple) -> np.ndarray:
    """Rasterise alpha-shape edges and flood-fill to get a solid mask."""
    mask = np.zeros(shape, dtype=np.uint8)
    for i, j in edges:
        r0, c0 = int(points[i][0]), int(points[i][1])
        r1, c1 = int(points[j][0]), int(points[j][1])
        rr, cc = skimage.draw.line(r0, c0, r1, c1)
        rr = np.clip(rr, 0, shape[0] - 1)
        cc = np.clip(cc, 0, shape[1] - 1)
        mask[rr, cc] = 1
    return scipy.ndimage.binary_fill_holes(mask).astype(np.uint8)


def _pad_box(box: tuple, padding: int, shape: tuple) -> tuple:
    r0, c0, r1, c1 = box
    return (
        max(r0 - padding, 0),
        max(c0 - padding, 0),
        min(r1 + padding, shape[0]),
        min(c1 + padding, shape[1]),
    )


# ─── Core label extraction ────────────────────────────────────────────────────

def _extract_labels(
    im: Image.Image,
    kernel_width: int = 2,
    region_size_min: int = 45,
    region_size_max: int = 5000,
    alpha: float = 36.0,
    box_padding: int = 5,
) -> list[str]:
    """
    Extract all OCR strings that look like figure labels from one image.

    Returns a list of raw pytesseract strings for regions that passed the
    size filter and alpha-shape grouping.  Caller applies the regex filter.
    """
    import pytesseract

    orig = np.array(im)
    gray = rgb2gray(orig) if orig.ndim == 3 else orig.astype(float) / 255.0

    threshold = threshold_otsu(gray)
    bw = gray < threshold
    filled = scipy.ndimage.binary_fill_holes(bw)

    labeled = skimage.measure.label(filled)
    regions = skimage.measure.regionprops(labeled)

    # Keep only blobs in the text-size range
    candidates = np.zeros(gray.shape, dtype=bool)
    for region in regions:
        if region_size_min <= region.area <= region_size_max:
            candidates[labeled == region.label] = True

    if not candidates.any():
        return []

    # Erode to remove dashed lines
    h_kernel = np.ones((1, kernel_width), dtype=bool)
    v_kernel = np.ones((kernel_width, 1), dtype=bool)
    eroded = skimage.morphology.binary_erosion(candidates, h_kernel)
    eroded = skimage.morphology.binary_erosion(eroded, v_kernel)

    points = np.argwhere(eroded)
    if len(points) <= 3:
        return []

    try:
        edges = _alpha_shape(points, alpha=alpha)
    except Exception:
        return []

    mask = _draw_mask(points, edges, gray.shape)

    labeled2 = skimage.measure.label(mask)
    regions2 = skimage.measure.regionprops(labeled2, orig)

    results: list[str] = []

    for region in regions2:
        box = _pad_box(region.bbox, box_padding, gray.shape)
        r0, c0, r1, c1 = box
        region_crop = skimage.img_as_ubyte(orig[r0:r1, c0:c1])

        # Rotate portrait regions 90° (labels printed sideways on some pages)
        h, w = region_crop.shape[:2]
        if h > w:
            region_crop = skimage.transform.rotate(
                region_crop, 270, resize=True, preserve_range=True
            ).astype(np.uint8)

        # Point to the conda-env tesseract binary if not on system PATH
        _set_tesseract_cmd()
        text = pytesseract.image_to_string(region_crop).strip()
        if text:
            results.append(text)

    return results


# ─── Public API ───────────────────────────────────────────────────────────────

def ocr_figure_label(img_path: Path, cfg: dict) -> str | None:
    """
    Detect the "FIG. N" label from a patent figure crop.

    Strategy
    --------
    1. Resize the image to a fixed height (max_ocr_height) so OCR is
       scale-invariant regardless of source resolution.
    2. Run pytesseract on the full resized image and search for FIG. N.
    3. If nothing found, try again on just the bottom 25% (where labels
       are most often printed in US patents).
    4. If still nothing, fall back to the GoFigure alpha-shape method.

    Returns the normalised token (e.g. "FIG. 3A") or None.
    """
    import pytesseract

    _set_tesseract_cmd()
    ocr_cfg = cfg.get("ocr", {})

    try:
        im = Image.open(img_path).convert("RGB")
    except Exception as exc:
        print(f"    OCR: cannot open {Path(img_path).name}: {exc}")
        return None

    # Resize so OCR parameters are scale-invariant
    max_h = ocr_cfg.get("max_ocr_height", 800)
    w, h  = im.size
    if h > max_h:
        im = im.resize((int(w * max_h / h), max_h), Image.LANCZOS)

    # ── Strategy 1: full image ────────────────────────────────────────────
    try:
        text = pytesseract.image_to_string(im, config="--psm 6")
        m = _FIG_TOKEN.search(text)
        if m:
            return f"FIG. {m.group(1).upper()}"
    except Exception:
        pass

    # ── Strategy 2: bottom 25% strip (figure labels often appear here) ───
    try:
        w2, h2  = im.size
        strip   = im.crop((0, int(h2 * 0.75), w2, h2))
        text    = pytesseract.image_to_string(strip, config="--psm 6")
        m = _FIG_TOKEN.search(text)
        if m:
            return f"FIG. {m.group(1).upper()}"
    except Exception:
        pass

    # ── Strategy 3: GoFigure alpha-shape (handles rotated/partial labels) ─
    try:
        candidates = _extract_labels(
            im,
            kernel_width=ocr_cfg.get("kernel_width", 2),
            region_size_min=ocr_cfg.get("region_size_min", 45),
            region_size_max=ocr_cfg.get("region_size_max", 5000),
            alpha=float(ocr_cfg.get("alpha", 36)),
            box_padding=ocr_cfg.get("box_padding", 5),
        )
        for text in candidates:
            m = _FIG_TOKEN.search(text)
            if m:
                return f"FIG. {m.group(1).upper()}"
    except Exception:
        pass

    return None


# ─── Page-level OCR (run before segmentation) ────────────────────────────────

def ocr_all_pages(
    pages: list[Path], cfg: dict
) -> "dict[str, list[tuple[str, int, int]]]":
    """
    OCR every original drawing page before segmentation and return all detected
    FIG. labels together with their positions on the page.

    Must be called BEFORE ``segment_patent()`` — original full pages must still
    be on disk.  Once HR-Net crops and deletes them, label positions are lost.

    Returns
    -------
    dict mapping page_stem → list of (label, cx, cy) tuples where cx/cy are
    the center of the detected label text in original page pixel coordinates.

        { "fig_08": [("FIG. 7", 420, 930)],
          "fig_21": [("FIG. 16A", 310, 860), ("FIG. 16B", 890, 860)] }

    The spatial coordinates allow ``assign_and_rename_crops()`` to match each
    HR-Net crop to its label even when the label text fell outside the crop bbox.
    """
    _set_tesseract_cmd()

    ocr_cfg = cfg.get("ocr", {})
    max_h   = ocr_cfg.get("max_ocr_height", 800)
    result: dict[str, list[tuple[str, int, int]]] = {}

    for page in pages:
        try:
            im_orig = Image.open(page).convert("RGB")
        except Exception:
            result[page.stem] = []
            continue

        orig_w, orig_h = im_orig.size
        if orig_h > max_h:
            scale = max_h / orig_h
            im    = im_orig.resize((int(orig_w * scale), max_h), Image.LANCZOS)
        else:
            scale = 1.0
            im    = im_orig

        labels = _find_fig_labels_with_positions(im, scale)
        result[page.stem] = labels

    total_pages  = sum(1 for v in result.values() if v)
    total_labels = sum(len(v) for v in result.values())
    print(f"  Page-level OCR: {total_pages}/{len(pages)} pages with FIG. labels "
          f"({total_labels} labels total)")
    return result


# ─── Figure-number formatting ─────────────────────────────────────────────────

def _format_fig_num(raw: str) -> str:
    """
    Convert a raw figure number to a zero-padded filename component.
        "1"   → "001"
        "2A"  → "002A"
        "12B" → "012B"
    """
    m = re.match(r"(\d+)([A-Za-z]?)", raw.strip())
    if not m:
        return raw.upper()
    return f"{int(m.group(1)):03d}{m.group(2).upper()}"


# ─── Spatial label matching (for split pages) ─────────────────────────────────

def _spatial_match_labels(
    crops: "list[tuple[Path, tuple | None]]",
    page_labels: "list[tuple[str, int, int]]",
) -> "list[str | None]":
    """
    Greedy nearest-neighbor assignment of page-level FIG. labels to crops.

    Used for *split* pages where a single drawing page was segmented into
    multiple sub-figure crops.  The label text may have been cropped away
    from the sub-figure image, but its position on the original page is known
    from the pre-segmentation OCR pass.

    Algorithm
    ---------
    Crops are processed in top-to-bottom order.  For each crop, the closest
    unassigned label whose center is either inside the crop bounding box or
    below it (patent labels typically appear below or beside their figure) is
    assigned.  Labels that are more than one crop-height *above* the crop are
    skipped — they belong to a figure higher on the page.

    Parameters
    ----------
    crops       : list of (crop_path, bbox) from segment_patent().
                  bbox = (x1, y1, x2, y2) in original page pixel coords.
                  None bbox → crop is skipped.
    page_labels : list of (label, cx, cy) from ocr_all_pages(), sorted
                  top-to-bottom.  cx/cy in original page pixel coords.

    Returns
    -------
    list[str | None] — same length as ``crops``.  None where no label matched.
    """
    if not page_labels or not crops:
        return [None] * len(crops)

    assigned = [False] * len(page_labels)
    result: list[str | None] = [None] * len(crops)

    # Process crops in top-to-bottom order (mirrors reading order of labels)
    crop_order = sorted(
        range(len(crops)),
        key=lambda i: (
            crops[i][1][1] if crops[i][1] else 0,   # bbox y1
            crops[i][1][0] if crops[i][1] else 0,   # bbox x1
        ),
    )

    for ci in crop_order:
        _, bbox = crops[ci]
        if bbox is None:
            continue

        x1, y1, x2, y2 = bbox
        crop_h = max(y2 - y1, 1)

        best_j    = None
        best_dist = float("inf")

        for j, (label, lx, ly) in enumerate(page_labels):
            if assigned[j]:
                continue
            # Labels clearly above this crop belong to a figure higher on the page
            if ly < y1 - crop_h:
                continue
            # Distance from label center to crop bbox (0 if label is inside)
            dx   = max(x1 - lx, 0, lx - x2)
            dy   = max(y1 - ly, 0, ly - y2)
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_j    = j

        if best_j is not None:
            result[ci]       = page_labels[best_j][0]
            assigned[best_j] = True

    return result


# ─── Rename crops by figure label ─────────────────────────────────────────────

def assign_and_rename_crops(
    patent_id: str,
    page_to_crops: "dict[str, list[tuple[Path, tuple | None]]]",
    page_labels:   "dict[str, list[tuple[str, int, int]]]",
    cfg: dict,
    description_text: str = "",
) -> list[Path]:
    """
    Assign figure labels to crops using a three-source strategy, then rename.

    For each page and its crops (in document order):

    1. **Crop-level OCR** — run GoFigure OCR directly on the crop image.
    2. **Page-level fallback** — if crop OCR finds nothing:
       - Single-figure pages: consume the next unassigned label from the
         pre-segmentation full-page OCR (``page_labels``).
       - Split pages with bbox data: use ``_spatial_match_labels()`` to match
         each crop to the nearest FIG. label detected on the original page.
         This rescues cases where HR-Net's tight crop excluded the label text.
    3. **Description positional fallback** — only when *no* pages were split.
       Overrides any remaining unlabeled crops with description order.
    4. **Unlabeled** — crop gets ``_Fu`` name.

    Parameters
    ----------
    patent_id     : e.g. "US11787551B1"
    page_to_crops : {page_stem: [(crop_path, bbox|None)]} — from segment_patent()
    page_labels   : {page_stem: [(label, cx, cy)]}        — from ocr_all_pages()
    cfg           : full config dict

    Returns
    -------
    Ordered list of final renamed Paths.
    """
    # Build flat list of (page_stem, crop_path, bbox) in document order
    items: list[tuple[str, Path, tuple | None]] = []
    for page_stem in sorted(page_to_crops.keys()):
        for crop_path, bbox in page_to_crops[page_stem]:
            items.append((page_stem, crop_path, bbox))

    # Pointer into page_labels for single-figure pages (consumed sequentially)
    page_label_idx: dict[str, int] = {s: 0 for s in page_to_crops}

    # Pre-compute spatial assignments for all split pages (done once per page,
    # not per crop, to avoid greedy ordering artifacts)
    spatial_cache: dict[str, list[str | None]] = {}
    for page_stem, crops in page_to_crops.items():
        if len(crops) > 1:
            avail = page_labels.get(page_stem, [])
            if avail:
                spatial_cache[page_stem] = _spatial_match_labels(crops, avail)

    # Pass 1: determine labels for every crop
    raw_labels: list[tuple[Path, str | None]] = []

    for page_stem, crop_path, bbox in items:
        # Strategy 1: crop-level OCR
        label = ocr_figure_label(crop_path, cfg)

        if label is None:
            crops_on_page = page_to_crops.get(page_stem, [])
            n_crops       = len(crops_on_page)
            avail_labels  = page_labels.get(page_stem, [])  # [(label, cx, cy)]

            if n_crops == 1:
                # Strategy 2a: single-figure page — consume next page label
                idx = page_label_idx.get(page_stem, 0)
                if idx < len(avail_labels):
                    label = avail_labels[idx][0]
                    page_label_idx[page_stem] = idx + 1

            elif page_stem in spatial_cache and bbox is not None:
                # Strategy 2b: split page — look up pre-computed spatial match
                crop_idx = next(
                    (i for i, (cp, _) in enumerate(crops_on_page) if cp == crop_path),
                    None,
                )
                if crop_idx is not None:
                    label = spatial_cache[page_stem][crop_idx]
                    if label:
                        print(f"    [spatial] {crop_path.name}  →  {label}")

        raw_labels.append((crop_path, label))
        if label:
            print(f"    {crop_path.name}  →  {label}")
        else:
            print(f"    {crop_path.name}  →  —")

    # Pass 1b: description positional fallback
    # Only when NO pages were split — in that case page order = figure order.
    any_splits = any(len(v) > 1 for v in page_to_crops.values())
    if description_text and not any_splits:
        from src.matcher import parse_description
        parsed_desc = parse_description(description_text, cfg)
        desc_figs   = list(parsed_desc.keys())
        n_assign    = min(len(items), len(desc_figs))
        for i in range(n_assign):
            crop, _ = raw_labels[i]
            raw_labels[i] = (crop, f"FIG. {desc_figs[i]}")
        leftover = len(items) - n_assign
        print(f"  Positional assignment (no splits): {n_assign}/{len(items)} labeled"
              + (f", {leftover} extra crops → _Fu" if leftover else ""))
    elif description_text and any_splits:
        n_spatial = sum(1 for ps in spatial_cache for _ in spatial_cache[ps] if _ is not None)
        n_spatial_total = sum(
            sum(1 for lbl in lbls if lbl is not None)
            for lbls in spatial_cache.values()
        )
        msg = f"  Spatial matching rescued {n_spatial_total} crop(s) on split pages"
        if not n_spatial_total:
            msg = "  Positional assignment skipped (splits detected; no page-level labels found)"
        print(msg)

    # Pass 2: detect duplicates, assign final names, rename
    label_count: dict[str, int] = {}
    for _, label in raw_labels:
        if label:
            m = _FIG_TOKEN.search(label)
            if m:
                key = _format_fig_num(m.group(1))
                label_count[key] = label_count.get(key, 0) + 1

    used_names:    set[str]       = set()
    dup_seen:      dict[str, int] = {}
    unlabeled_idx: int            = 0
    new_paths:     list[Path]     = []

    for crop, label in raw_labels:
        fig_key: str | None = None
        if label:
            m = _FIG_TOKEN.search(label)
            if m:
                fig_key = _format_fig_num(m.group(1))

        if fig_key:
            if label_count[fig_key] == 1:
                stem = f"{patent_id}_F{fig_key}"
            else:
                dup_seen[fig_key] = dup_seen.get(fig_key, 0) + 1
                suffix = chr(ord("a") + dup_seen[fig_key] - 1)
                stem = f"{patent_id}_F{fig_key}_{suffix}"
        else:
            unlabeled_idx += 1
            stem = f"{patent_id}_Fu{unlabeled_idx:03d}"

        candidate = stem + ".png"
        extra = 0
        while candidate in used_names:
            extra += 1
            candidate = f"{stem}_{extra}.png"

        used_names.add(candidate)
        new_path = crop.parent / candidate
        if crop != new_path:
            crop.rename(new_path)
        new_paths.append(new_path)

    labeled   = sum(1 for _, l in raw_labels if l)
    unlabeled = len(raw_labels) - labeled
    print(f"  Renamed {len(new_paths)} crops  ({labeled} labeled  {unlabeled} unlabeled)")
    return new_paths


def ocr_and_rename_crops(
    patent_id: str,
    figure_paths: list[Path],
    cfg: dict,
) -> list[Path]:
    """
    OCR every crop for a "FIG. X" label and rename files to the final names.

    Naming rules
    ------------
    Labeled   → {patent_id}_F{num:03d}[letter].png   e.g. US1234_F001.png
    Unlabeled → {patent_id}_Fu{n:03d}.png             e.g. US1234_Fu001.png
    Duplicate → {patent_id}_F001_b.png, _F001_c.png …

    Two-pass approach:
      Pass 1 — OCR all crops, collect (path, label) pairs.
      Pass 2 — detect duplicates, assign final names, rename files.

    Returns the ordered list of final Paths.
    """
    # Pass 1: OCR
    ocr_results: list[tuple[Path, str | None]] = []
    for path in figure_paths:
        label = ocr_figure_label(path, cfg)
        ocr_results.append((path, label))
        status = label if label else "—"
        print(f"    OCR  {path.name}  →  {status}")

    # Pass 2: assign names, detect duplicates
    label_count: dict[str, int] = {}
    for _, label in ocr_results:
        if label:
            m = _FIG_TOKEN.search(label)
            if m:
                key = _format_fig_num(m.group(1))
                label_count[key] = label_count.get(key, 0) + 1

    used_names:    set[str]  = set()
    dup_seen:      dict[str, int] = {}
    unlabeled_idx: int       = 0
    new_paths:     list[Path] = []

    for path, label in ocr_results:
        fig_key: str | None = None
        if label:
            m = _FIG_TOKEN.search(label)
            if m:
                fig_key = _format_fig_num(m.group(1))

        if fig_key:
            if label_count[fig_key] == 1:
                stem = f"{patent_id}_F{fig_key}"
            else:
                dup_seen[fig_key] = dup_seen.get(fig_key, 0) + 1
                suffix = chr(ord("a") + dup_seen[fig_key] - 1)   # a, b, c…
                stem = f"{patent_id}_F{fig_key}_{suffix}"
        else:
            unlabeled_idx += 1
            stem = f"{patent_id}_Fu{unlabeled_idx:03d}"

        # Guard against any remaining conflicts
        candidate = stem + ".png"
        extra = 0
        while candidate in used_names:
            extra += 1
            candidate = f"{stem}_{extra}.png"

        used_names.add(candidate)
        new_path = path.parent / candidate

        if path != new_path:
            path.rename(new_path)

        new_paths.append(new_path)

    labeled   = sum(1 for _, l in ocr_results if l)
    unlabeled = len(ocr_results) - labeled
    print(f"  Renamed {len(new_paths)} crops  ({labeled} labeled  {unlabeled} unlabeled)")
    return new_paths


# ─── Retroactive relabeling pass ──────────────────────────────────────────────

def relabel_unlabeled_patent(
    patent_id: str,
    cfg: dict,
    raw_dir: Path,
    text_dir: Path,
    epo_client=None,
    excel_desc: "dict[str, str] | None" = None,
) -> dict:
    """
    Retroactively apply description-based positional labeling to a patent
    whose figures were all left as ``_Fu*.png`` (OCR completely failed).

    Only acts when **every** figure in the folder is unlabeled — if at least
    one ``_F[0-9]*.png`` exists we leave the patent alone to avoid conflicts.

    Steps
    -----
    1. Collect ``_Fu*.png`` files in numeric order.
    2. Load the description ``.txt`` if it exists; otherwise try to fetch it
       from Google Patents (or EPO if ``epo_client`` is provided).
    3. Parse the description to extract an ordered list of FIG. numbers.
    4. Map positionally: ``_Fu001`` → first FIG. number in description, etc.
       If there are more images than description entries, the extras stay as
       ``_Fu*``.  If there are fewer images, only the matched prefix is renamed.
    5. Rename files and return a result summary dict.

    Parameters
    ----------
    patent_id  : e.g. "US2022234745A1"
    cfg        : full config dict from load_config()
    raw_dir    : cfg["paths"]["raw_images"]
    text_dir   : cfg["paths"]["text"]
    epo_client : optional EpoClient (only needed when extractor.mode="epo")

    Returns
    -------
    dict with keys:
        patent_id, status, n_fu_before, n_relabeled, n_fu_after, reason
    """
    from src.extractor import get_brief_description, save_description_text
    from src.matcher  import parse_description

    patent_dir = raw_dir / patent_id

    result = dict(
        patent_id   = patent_id,
        status      = "skipped",
        n_fu_before = 0,
        n_relabeled = 0,
        n_fu_after  = 0,
        reason      = "",
    )

    if not patent_dir.exists():
        result["reason"] = "folder_missing"
        return result

    fu_files  = sorted(patent_dir.glob(f"{patent_id}_Fu*.png"))
    labeled   = sorted(patent_dir.glob(f"{patent_id}_F[0-9]*.png"))

    result["n_fu_before"] = len(fu_files)

    if not fu_files:
        result["reason"] = "no_unlabeled_files"
        return result

    if labeled:
        result["reason"] = (
            f"partially_labeled ({len(labeled)} already named) — skipped to avoid conflicts"
        )
        return result

    # ── Ensure description text is available ──────────────────────────────────
    txt_path = text_dir / f"{patent_id}.txt"
    desc_text = ""

    if txt_path.exists():
        desc_text = txt_path.read_text(encoding="utf-8")
        print(f"  [{patent_id}] Description loaded from .txt ({len(desc_text.splitlines())} lines)")
    else:
        print(f"  [{patent_id}] No .txt found — fetching from web …")
        try:
            desc_text = get_brief_description(patent_id, cfg, epo_client)
        except Exception as exc:
            print(f"  [{patent_id}] Fetch failed: {exc}")

        if desc_text:
            save_description_text(patent_id, desc_text, text_dir)
            print(f"  [{patent_id}] Description fetched and saved ({len(desc_text.splitlines())} lines)")
        else:
            # Third fallback: PatSeer Excel "Description of Drawings" column
            excel_text = (excel_desc or {}).get(patent_id, "").strip() if excel_desc else ""
            if excel_text:
                desc_text = excel_text
                save_description_text(patent_id, desc_text, text_dir)
                print(f"  [{patent_id}] Description loaded from PatSeer Excel "
                      f"({len(desc_text.splitlines())} lines)")
            else:
                print(f"  [{patent_id}] No description available — cannot relabel")
                result["reason"] = "no_description_text"
                result["n_fu_after"] = len(fu_files)
                return result

    # ── Parse description for ordered FIG. numbers ────────────────────────────
    parsed = parse_description(desc_text, cfg)   # {"1": "FIG. 1 is …", "2": …}
    fig_keys = list(parsed.keys())               # in document order

    if not fig_keys:
        print(f"  [{patent_id}] Description parsed but no FIG. entries found")
        result["reason"] = "description_has_no_fig_entries"
        result["n_fu_after"] = len(fu_files)
        return result

    print(f"  [{patent_id}] {len(fu_files)} unlabeled files, "
          f"{len(fig_keys)} FIG. entries in description")

    # ── Positional renaming ───────────────────────────────────────────────────
    n_assign = min(len(fu_files), len(fig_keys))
    label_count: dict[str, int] = {}
    # Pre-count to detect description-side duplicates
    for k in fig_keys[:n_assign]:
        fmt = _format_fig_num(k)
        label_count[fmt] = label_count.get(fmt, 0) + 1

    dup_seen:  dict[str, int] = {}
    used_names: set[str] = set()
    n_renamed = 0

    for i, fu_path in enumerate(fu_files):
        if i < n_assign:
            fig_key = _format_fig_num(fig_keys[i])
            if label_count[fig_key] == 1:
                stem = f"{patent_id}_F{fig_key}"
            else:
                dup_seen[fig_key] = dup_seen.get(fig_key, 0) + 1
                suffix = chr(ord("a") + dup_seen[fig_key] - 1)
                stem = f"{patent_id}_F{fig_key}_{suffix}"

            candidate = stem + ".png"
            extra = 0
            while candidate in used_names:
                extra += 1
                candidate = f"{stem}_{extra}.png"
            used_names.add(candidate)

            new_path = patent_dir / candidate
            fu_path.rename(new_path)
            n_renamed += 1
            print(f"    {fu_path.name}  →  {candidate}")
        else:
            print(f"    {fu_path.name}  →  (kept as _Fu, no matching description entry)")

    result.update(
        status      = "relabeled",
        n_relabeled = n_renamed,
        n_fu_after  = len(fu_files) - n_renamed,
        reason      = (
            f"positional_from_description "
            f"({'complete' if n_renamed == len(fu_files) else 'partial'})"
        ),
    )
    return result


def relabel_all_unlabeled(
    cfg: dict,
    raw_dir: Path,
    text_dir: Path,
    epo_client=None,
) -> None:
    """
    Run ``relabel_unlabeled_patent`` for every patent folder in *raw_dir*
    that has ONLY ``_Fu*.png`` files (complete OCR failure).

    Prints a per-patent summary and a final aggregate table.
    """
    patent_dirs = [d for d in sorted(raw_dir.iterdir()) if d.is_dir()]
    if not patent_dirs:
        print("No patent folders found in", raw_dir)
        return

    # Build Excel description lookup once (PatSeer "Description of Drawings" column)
    excel_desc: dict[str, str] = {}
    excel_path = cfg.get("paths", {}).get("patseer_excel")
    if excel_path:
        try:
            import pandas as pd
            _xdf = pd.read_excel(excel_path, dtype=str, usecols=["Record Number", "Description of Drawings"])
            for _, row in _xdf.iterrows():
                pid_key = str(row.get("Record Number", "")).strip()
                val     = str(row.get("Description of Drawings", "")).strip()
                if pid_key and val and val.lower() not in ("nan", "none", ""):
                    excel_desc[pid_key] = val
            print(f"PatSeer Excel: loaded {len(excel_desc)} description-of-drawings entries\n")
        except Exception as exc:
            print(f"Warning: could not load PatSeer Excel for description fallback: {exc}\n")

    results = []
    print(f"Scanning {len(patent_dirs)} patent folders …\n")

    for patent_dir in patent_dirs:
        pid = patent_dir.name
        fu  = list(patent_dir.glob(f"{pid}_Fu*.png"))
        lab = list(patent_dir.glob(f"{pid}_F[0-9]*.png"))

        if not fu:
            continue   # nothing to do
        if lab:
            continue   # partially labeled — skip

        # All files are _Fu* → candidate for relabeling
        r = relabel_unlabeled_patent(pid, cfg, raw_dir, text_dir, epo_client, excel_desc)
        results.append(r)

    if not results:
        print("No fully-unlabeled patents found — nothing to relabel.")
        return

    print()
    print("=" * 70)
    print("Retroactive relabeling summary")
    print("=" * 70)
    print(f"  {'Patent':<25} {'Before':>6}  {'Relabeled':>9}  {'After_Fu':>8}  Status")
    print("  " + "─" * 66)
    for r in results:
        print(f"  {r['patent_id']:<25} {r['n_fu_before']:>6}  "
              f"{r['n_relabeled']:>9}  {r['n_fu_after']:>8}  {r['reason']}")
    total_relabeled = sum(r["n_relabeled"] for r in results)
    total_remaining = sum(r["n_fu_after"]  for r in results)
    print("  " + "─" * 66)
    print(f"  {'TOTAL':<25} {sum(r['n_fu_before'] for r in results):>6}  "
          f"{total_relabeled:>9}  {total_remaining:>8}")
    print("=" * 70)
