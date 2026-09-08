#!/usr/bin/env python3
"""Image_Path repair, as a registered promotion step.

Two jobs, both of which were being done by hand and therefore lost on every
promotion (promote_download.py rebuilds 03c from the raw download, so anything
not in its STEPS list is silently discarded):

  1. RESOLVE — a figure attached through the wizard's 📎 button comes back with
     a blank Image_Path, because a browser never sees a real disk path. Fill it
     in by locating the filename under the patent's own matched/ folder.
     (This is scripts/resolve_image_paths.py, wrapped in the --batches/--apply
     CLI the promotion expects.)

  2. REPAIR — a stored path whose file does not exist, where the SAME basename
     with a different extension does. Real case, Batch_04 2026-09-06:
     US2022097837A1's FIG. 19 is a .jpg on disk, and the figure key in the
     export says .jpg, but the Image_Path column said .png — 13 rows pointing at
     a file that was never there. Only an extension swap is ever applied, and
     only when exactly one candidate exists, so this cannot silently repoint a
     figure at a different drawing.

Paths that stay broken are REPORTED, never guessed at: a missing crop_0 whose
siblings survive means the crops were re-cut or deleted, and picking a
neighbouring file would attach the wrong drawing to a label.

    python scripts/conformance/fix_image_paths.py --batches Batch_04 --apply
"""
from __future__ import annotations
import argparse, shutil, sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.resolve_image_paths import find_image          # noqa: E402
from src.config_loader import load_config                    # noqa: E402

DATA = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & "
            "Labelling Outputs/1639_DS/data/03c_CORRECTED_wizard_exports")
BATCHES = ["Batch_01", "Batch_02", "Batch_03", "Batch_04", "Batch_05"]
PLACEHOLDER = "(fig "


def run(batch: str, matched_root: Path, apply: bool, f: Path | None = None) -> dict:
    f = f or DATA / f"reviewed_patents_{batch}.xlsx"
    if not f.exists():
        return dict(resolved=0, repaired=0, broken=[], missing=0)
    d = pd.read_excel(f, sheet_name="Review")
    is_img = d["Sub_Dimension"].astype(str).str.startswith("Image: ")
    resolved = repaired = 0
    broken: list[tuple[str, str, str]] = []

    for i, r in d[is_img].iterrows():
        fname = str(r["Sub_Dimension"])[7:].strip()
        if not fname or fname.startswith(PLACEHOLDER) or fname == "(none available)":
            continue
        pid = str(r["Patent_ID"]).strip()
        cur = str(r["Image_Path"]).strip() if pd.notna(r["Image_Path"]) else ""

        if cur in ("", "nan", "None", "null"):                       # 1 — resolve
            hit = find_image(matched_root, pid, fname)
            if hit:
                d.at[i, "Image_Path"] = str(hit)
                resolved += 1
            else:
                broken.append((pid, fname, "no file found"))
            continue

        p = Path(cur)
        if p.exists():
            continue
        # 2a — TRUST THE FIGURE KEY. The Sub_Dimension "Image: <filename>" is the
        # wizard's own identifier for this figure; the Image_Path column is only a
        # convenience for rendering. When they disagree and the key names a file
        # that exists, the key wins. Real case, Batch_04 2026-09-06:
        # US2019340933A1's key said _img6_crop_0_F7.png (on disk) while the path
        # said _img1_crop_0_F7.png (never existed) — on the APPROVED MAIN figure.
        hit = find_image(matched_root, pid, fname)
        if hit:
            d.at[i, "Image_Path"] = str(hit)
            repaired += 1
            continue
        # 2b — otherwise an extension swap, only when exactly one candidate exists
        cands = [q for q in p.parent.glob(p.stem + ".*") if q.is_file()] \
            if p.parent.is_dir() else []
        if len(cands) == 1:
            d.at[i, "Image_Path"] = str(cands[0])
            repaired += 1
        else:
            why = "no file on disk" if not cands else f"{len(cands)} candidates — ambiguous"
            broken.append((pid, p.name, why))

    if apply and (resolved or repaired):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(f, f.with_suffix(f".PRE_IMGFIX_{ts}.xlsx"))
        d.to_excel(f, sheet_name="Review", index=False)
    return dict(resolved=resolved, repaired=repaired, broken=broken, missing=len(broken))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batches", nargs="+", default=BATCHES)
    ap.add_argument("--file", type=Path, help="repair this xlsx instead of the 03c copies "
                                              "(for a raw download, which the wizard "
                                              "overwrites on every export)")
    a = ap.parse_args()
    print("APPLYING" if a.apply else "DRY RUN — nothing written (use --apply)")
    matched_root = Path(load_config()["paths"]["matched"])
    targets = [(a.file.stem, a.file)] if a.file else [(b, None) for b in a.batches]
    for b, f in targets:
        s = run(b, matched_root, a.apply, f)
        print(f"  {b}  resolved {s['resolved']:>4} · extension repaired {s['repaired']:>3} "
              f"· still broken {s['missing']:>3}")
        seen = set()
        for pid, fn, why in s["broken"]:
            if (pid, fn) in seen:
                continue
            seen.add((pid, fn))
            print(f"       ! {pid}  {fn}  ({why})")
