"""
processor.py — Stage 02: wizard-driven padding + resizing for DINOv2.

Reads the IMGPATH-resolved wizard export (reviewed_patents_<batch>.xlsx,
Review sheet), takes every approved figure, applies the reviewer's rotation,
resizes with aspect ratio preserved, pads to a square with a background-aware
fill and writes processing.target_size PNGs (518x518 -> DINOv2 ViT-L/14's
native hi-res input, 37x37 patches).

Outputs (mirrors the matched/ <-> data/matched convention):
    processed/<batch>/all/<patent_dir>/<patent>_arch<N>[_dupSame|_dupSimilar][_main|_2|_3...].png
    processed/<batch>/main/<patent>_arch<N>[_dupSame|_dupSimilar]_main.png   flat canonical set
    data/processed/<batch>/processing_manifest_<batch>.csv

duplicateType "1" (Same Aircraft) / "3" (small changes) patents keep their
own T2 and are processed like any other patent, but get a _dupSame /
_dupSimilar marker in the filename so provenance is visible without
cross-referencing the manifest's duplicate_type column. duplicateType "2"
(exact duplicate, images AND aircraft identical) never appears here — 02a
strips its T2 rows entirely, so it produces no output at all.

The manifest is the contract with DINOv2_eVTOL_frozen_Analysis: it maps the
wizard export's Image_Path (matched/ crop) to the processed 518px file plus
per-image labels (isMain, arch, bgSty/bgCol/acSty/acCol, qualityFlag, dupOf)
so the analysis repo never parses filenames.

Padding decision (adaptive_pad_resize) — evolved from
Patent_Images_Extractor_&_FT_2.0's 03_processing adaptive_padding_resize:
  1. optional 1.20x sharpen, only when downscaling (preserves thin strokes);
  2. resize longest side to target (LANCZOS), aspect preserved;
  3. sample the outermost 1-3 px border ring of the RESIZED image;
  4. pick the fill:
       - reviewer's bgSty label, when present, decides: Solid Fill -> flat
         median fill; Shaded/Gradient or Grid/Pattern -> mirror-extend
         (BORDER_REFLECT_101, REPLICATE when padding exceeds the image);
       - unlabelled: solid fill iff >= solid_dominant_frac of border pixels
         lie within border_color_tol of the per-channel median. This replaces
         the old raw-std<15 rule, which mis-fired on tight crops where black
         strokes cross the border (std blows up, reflect then mirrors phantom
         aircraft geometry into the padding — poison for rotor/wing counting).

Pure PIL + numpy — no cv2, so it runs in the plain anaconda kernel.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageEnhance

# per-image T2 fields carried into the manifest
_T2_FIELDS = ["status", "isMain", "arch", "rotation_deg", "figKey",
              "bgSty", "bgCol", "acSty", "acCol", "qualityFlag", "dupOf"]

_ARCH_SUFFIX_RE = re.compile(r"^(?P<base>.+?)_arch(?P<n>\d+)$")

_REFLECT_BG_STY = {"Shaded/Gradient", "Grid/Pattern"}


# ── image ops ────────────────────────────────────────────────────────────────

def _to_rgb(img: Image.Image) -> Image.Image:
    """RGB-ify, compositing any transparency over white (never over black)."""
    if img.mode == "P":
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA"):
        base = Image.new("RGB", img.size, (255, 255, 255))
        base.paste(img, mask=img.getchannel("A"))
        return base
    return img.convert("RGB")


def rotate_image(img: Image.Image, deg: float) -> Image.Image:
    """Match the wizard preview: CSS rotate(Ndeg) is clockwise, PIL is CCW."""
    if not deg:
        return img
    return img.rotate(-deg, expand=True, fillcolor=(255, 255, 255))


def _border_ring(arr: np.ndarray) -> np.ndarray:
    """Outermost 1-3 px ring (thickness scales with image size), as Nx3."""
    h, w = arr.shape[:2]
    t = max(1, min(3, w // 20, h // 20))
    strips = [arr[:t, :].reshape(-1, 3), arr[-t:, :].reshape(-1, 3)]
    if h > 2 * t:
        strips += [arr[t:-t, :t].reshape(-1, 3), arr[t:-t, -t:].reshape(-1, 3)]
    return np.vstack(strips)


def border_seam_std(img: Image.Image, t: int = 3) -> float:
    """Mean per-channel std of the outermost t px — seam-visibility proxy."""
    return float(_border_ring(np.asarray(_to_rgb(img), dtype=np.uint8)).std(axis=0).mean())


def adaptive_pad_resize(
    image: Image.Image,
    target_size: int,
    *,
    sharpen_factor: float = 1.20,
    solid_dominant_frac: float = 0.70,
    border_color_tol: int = 24,
    bg_sty: str | None = None,
    force_white: bool = False,
) -> tuple[Image.Image, dict]:
    """Resize (aspect kept) + pad to target_size square. Returns (img, stats)."""
    img = _to_rgb(image)
    w, h = img.size
    scale = target_size / max(w, h)
    if sharpen_factor and sharpen_factor != 1.0 and scale < 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpen_factor)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    pad_top    = (target_size - new_h) // 2
    pad_bottom = target_size - new_h - pad_top
    pad_left   = (target_size - new_w) // 2
    pad_right  = target_size - new_w - pad_left

    arr = np.asarray(resized, dtype=np.uint8)
    ring = _border_ring(arr)
    median = np.median(ring, axis=0)
    border_std = float(ring.std(axis=0).mean())
    near = (np.abs(ring.astype(np.int16) - median).max(axis=1)
            <= border_color_tol)
    dominant_frac = float(near.mean())

    if force_white:
        solid, fill = True, (255, 255, 255)
    elif bg_sty in _REFLECT_BG_STY:
        solid, fill = False, None
    elif bg_sty == "Solid Fill" or dominant_frac >= solid_dominant_frac:
        solid, fill = True, tuple(int(v) for v in median)
    else:
        solid, fill = False, None

    if solid:
        canvas = Image.new("RGB", (target_size, target_size), fill)
        canvas.paste(resized, (pad_left, pad_top))
        out, method = canvas, "solid"
    else:
        # np.pad "reflect" == cv2 BORDER_REFLECT_101 (edge row not repeated),
        # but needs pad < image extent on that axis; "edge" == REPLICATE.
        can_reflect = (pad_top < new_h and pad_bottom < new_h
                       and pad_left < new_w and pad_right < new_w)
        mode = "reflect" if can_reflect else "edge"
        out = Image.fromarray(np.pad(
            arr, ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)), mode=mode))
        method = "reflect" if can_reflect else "replicate"
        fill = tuple(int(v) for v in median)   # reported, not painted

    stats = {
        "fill_method": method,
        "fill_color_hex": "#%02x%02x%02x" % fill,
        "border_std": round(border_std, 2),
        "dominant_frac": round(dominant_frac, 3),
        "scale": round(scale, 4),
    }
    return out, stats


# ── wizard-export ingestion ──────────────────────────────────────────────────

def parse_arch_id(pid: str) -> tuple[str, int]:
    """``US..._arch2`` -> (``US...``, 2); unsuffixed ids are architecture 1."""
    m = _ARCH_SUFFIX_RE.match(str(pid))
    if m:
        return m.group("base"), int(m.group("n"))
    return str(pid), 1


def _strip_label(value) -> str | None:
    """Wizard export Values are "ID — Label" composites (e.g. "1 — Same
    Aircraft"). Return just the ID part; None for NaN/blank. Mirrors
    02a_preprocessing's _strip_label / the HTML's stripLabel()."""
    if pd.isna(value):
        return None
    return str(value).split(" — ")[0].strip()


def load_review_images(reviewed_xlsx: Path) -> pd.DataFrame:
    """One row per (Patent_ID, Image_Path) with the T2 fields in _T2_FIELDS.

    Same pivot convention as the analysis repo's labels.image_table. If one
    image serves several architectures the first T2 row wins (aggfunc first).
    """
    long = pd.read_excel(reviewed_xlsx, sheet_name="Review")
    t2 = long[(long["Section"] == "T2") & long["Image_Path"].notna()]
    piv = t2.pivot_table(index=["Patent_ID", "Image_Path"], columns="Field",
                         values="Value", aggfunc="first").reset_index()
    piv.columns.name = None
    for f in _T2_FIELDS:
        if f not in piv.columns:
            piv[f] = None

    parsed = piv["Patent_ID"].map(parse_arch_id)
    piv["base_patent_id"] = parsed.map(lambda t: t[0])
    arch_field = pd.to_numeric(piv["arch"], errors="coerce")
    piv["arch_index"] = arch_field.fillna(parsed.map(lambda t: t[1])).astype(int)
    piv["is_main"] = piv["isMain"].astype(str).str.lower().isin(
        ["true", "1", "yes", "main"])
    piv["approved"] = piv["status"].astype(str).str.lower().eq("approved")
    piv["rotation"] = pd.to_numeric(piv["rotation_deg"], errors="coerce").fillna(0)

    # duplicateType lives on T1, keyed by the BASE patent id (Rule D never
    # inherits it — every duplicate carries its own). Type "2" (exact
    # duplicate) never reaches here since 02a strips its T2 rows entirely;
    # types "1" (Same Aircraft) and "3" (small changes) keep their own T2
    # and are processed normally, but get flagged in the output filename
    # (see process_batch) so the processed/ tree self-documents provenance.
    dup_type_rows = long.loc[long["Field"] == "duplicateType"]
    dup_type_by_patent = (
        dup_type_rows.set_index(dup_type_rows["Patent_ID"].astype(str))["Value"]
        .map(_strip_label)
    )
    piv["duplicate_type"] = piv["base_patent_id"].astype(str).map(dup_type_by_patent)
    return piv


_FIG_SUFFIX_RE = re.compile(r"_F([A-Za-z0-9]+)$")


def _fig_label(src: Path, fig_key) -> str:
    """Short figure label for the flat main/ filename.

    The stage-00b crop convention ends stems with ``_F<label>`` (``F15``,
    ``F11C``, ``Fu`` = unknown) — prefer that; fall back to a sanitized
    figKey (often NaN for US patents, a stem fragment for CN ones).
    """
    m = _FIG_SUFFIX_RE.search(src.stem)
    if m:
        return m.group(1)
    if fig_key is not None and not (isinstance(fig_key, float) and pd.isna(fig_key)):
        s = re.sub(r"[^A-Za-z0-9]+", "-", str(fig_key)).strip("-")
        if s:
            return s
    return "u"


def _fill_matches_label(fill_hex: str, bg_col) -> bool | None:
    """Rough agreement check between the painted fill and the bgCol label."""
    if bg_col is None or (isinstance(bg_col, float) and pd.isna(bg_col)):
        return None
    r, g, b = (int(fill_hex[i:i + 2], 16) for i in (1, 3, 5))
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    label = str(bg_col)
    if label == "White":
        return min(r, g, b) >= 225
    if label == "Dark":
        return lum < 110
    if label == "Grayscale":
        return max(r, g, b) - min(r, g, b) <= 18 and 60 <= lum <= 225
    if label == "Blueprint Blue":
        return b > r and b > g
    return None


# ── batch driver ─────────────────────────────────────────────────────────────

def process_batch(sheet_name: str, cfg: dict, force: bool | None = None,
                  reviewed_xlsx: "Path | None" = None) -> pd.DataFrame:
    """Process one batch's approved wizard images; returns + writes the manifest.

    `reviewed_xlsx` overrides the input file — used by 02b_postprocessing to
    consume 02a_preprocessing's preprocessed_patents_<batch>_<ts>.xlsx output
    (its "Review" sheet is the same flat schema, already IMGPATH-resolved).
    Defaults to the legacy wizard_resolved_dir convention.
    """
    p = cfg["processing"]
    target = int(p["target_size"][0])
    force = bool(p.get("overwrite", False)) if force is None else force
    force_white = p.get("pad_color_mode", "auto") == "white"
    use_labels = p.get("pad_color_mode", "auto") == "auto"

    if reviewed_xlsx is None:
        reviewed_xlsx = Path(cfg["paths"]["wizard_resolved_dir"]) / f"reviewed_patents_{sheet_name}.xlsx"
    reviewed_xlsx = Path(reviewed_xlsx)
    if not reviewed_xlsx.exists():
        raise FileNotFoundError(
            f"{reviewed_xlsx} not found — run 02a_preprocessing (or export from "
            f"the wizard + scripts/resolve_image_paths.py) first.")

    all_root  = Path(cfg["paths"]["processed"]) / sheet_name / "all"
    main_root = Path(cfg["paths"]["processed"]) / sheet_name / "main"
    data_dir  = Path(cfg["paths"]["data_processed"]) / sheet_name
    for d in (all_root, main_root, data_dir):
        d.mkdir(parents=True, exist_ok=True)

    images = load_review_images(reviewed_xlsx)
    rows = []
    used_names: set[str] = set()

    def _claim_name(stem: str) -> str:
        """First figure of an arch gets the bare stem; extras get _2, _3, ..."""
        if stem not in used_names:
            used_names.add(stem)
            return stem
        n = 2
        while f"{stem}_{n}" in used_names:
            n += 1
        used_names.add(f"{stem}_{n}")
        return f"{stem}_{n}"

    for _, r in images.iterrows():
        rec = {
            "patent_id": r["Patent_ID"], "base_patent_id": r["base_patent_id"],
            "arch": r["arch_index"], "fig_key": r["figKey"],
            "is_main": r["is_main"], "status": r["status"],
            "src_path": r["Image_Path"], "dst_all": None, "dst_main": None,
            "processed": False, "skip_reason": None,
            "rotation_deg": r["rotation"],
            "bg_sty": r["bgSty"], "bg_col": r["bgCol"],
            "ac_sty": r["acSty"], "ac_col": r["acCol"],
            "quality_flag": r["qualityFlag"], "dup_of": r["dupOf"],
            "duplicate_type": r["duplicate_type"],
            # Only ever populated on a freshly-processed (non-cached) row —
            # initialized here so the manifest column always exists even
            # when every row in a run happens to hit the cache.
            "fill_vs_label_ok": None, "fill_color_hex": None, "dominant_frac": None,
        }
        src = Path(str(r["Image_Path"]))
        if p.get("approved_only", True) and not r["approved"]:
            rec["skip_reason"] = "not_approved"
            rows.append(rec); continue
        if not src.exists():
            rec["skip_reason"] = "missing_file"
            rows.append(rec); continue

        # <patent>_arch<N>.png for every figure (mains get _main; extra
        # figures of the same arch get _2, _3, ... to avoid collisions).
        # duplicateType "1"/"3" patents keep their own T2 and are processed
        # like any other patent, but get a _dupSame/_dupSimilar marker so the
        # processed/ tree self-documents provenance (type "2" exact
        # duplicates never reach here — 02a strips their T2 rows entirely).
        dup_suffix = {"1": "_dupSame", "3": "_dupSimilar"}.get(r["duplicate_type"], "")
        base_stem = f"{r['base_patent_id']}_arch{r['arch_index']}{dup_suffix}"
        stem = _claim_name(f"{base_stem}_main" if r["is_main"] else base_stem)
        dst_all = all_root / src.parent.name / f"{stem}.png"
        rec["dst_all"] = str(dst_all)
        try:
            if dst_all.exists() and not force:
                out = Image.open(dst_all)
                rec.update({"fill_method": "cached", "seam_std": border_seam_std(out)})
            else:
                img = rotate_image(Image.open(src), r["rotation"])
                out, stats = adaptive_pad_resize(
                    img, target,
                    sharpen_factor=float(p.get("sharpen_factor", 1.20)),
                    solid_dominant_frac=float(p.get("solid_dominant_frac", 0.70)),
                    border_color_tol=int(p.get("border_color_tol", 24)),
                    bg_sty=(str(r["bgSty"]) if use_labels and pd.notna(r["bgSty"]) else None),
                    force_white=force_white,
                )
                dst_all.parent.mkdir(parents=True, exist_ok=True)
                out.save(dst_all, "PNG")
                rec.update(stats)
                rec["seam_std"] = round(border_seam_std(out), 2)
                rec["fill_vs_label_ok"] = _fill_matches_label(
                    stats["fill_color_hex"], r["bgCol"])
            rec["processed"] = True
            if r["is_main"]:
                dst_main = main_root / f"{stem}.png"
                out.save(dst_main, "PNG")
                rec["dst_main"] = str(dst_main)
        except Exception as exc:                       # keep the batch going
            rec["skip_reason"] = f"error: {exc}"
        rows.append(rec)

    manifest = pd.DataFrame(rows)
    out_csv = data_dir / f"processing_manifest_{sheet_name}.csv"
    manifest.to_csv(out_csv, index=False)
    n_ok = int(manifest["processed"].sum())
    n_main = manifest["dst_main"].notna().sum()
    print(f"[process_batch] {sheet_name}: {n_ok}/{len(manifest)} images processed "
          f"({n_main} mains) -> {all_root.parent}\n  manifest: {out_csv}")
    return manifest
