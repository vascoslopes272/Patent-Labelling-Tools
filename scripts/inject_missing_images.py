"""
inject_missing_images.py — make EVERY image file in a patent's matched/ folder
appear in the review wizard's T2 figure grid, whether or not the ML pipeline
gave it a row.

WHY: build_patent_rows() only emits "Image: <fname>" T2 row-groups for the
crops that survived the pipeline's quality filters (crop_quality merged/blank
etc. are dropped), so files sitting right there in matched/<Batch>/<patent>/
never reach the wizard — the reviewer can't even see them to decide. Per the
reviewer's call (2026-07-03): surface EVERYTHING on disk; the human approves/
disapproves in the wizard. This also covers images the user drops into the
folder manually (see the wizard's 📎 Attach Image button + [[labelling-ui-
manual-image-attach]] memory): once the file is in the folder, this script
gives it a row, so it appears on the next load with no attach step needed.

For each patent in the export, any *.png/jpg/jpeg/webp in its matched folder
that has no "Image: <fname>" Sub_Dimension group yet gets one minimal T2 row:
Field="match_status", Value="disk_only", Source="disk_scan", with Image_Path
set — enough for the wizard to render the image and let the human label it.
Non-crop originals (the full-page "..._imgN.png" sources and the PatSeer
front-page "...PAFP.png") are skipped by default: only files matching the
crop convention (_crop_ in the name, or _F*/_Fu* suffix) OR any file with no
sibling crops at all (so manually-added arbitrary names still surface) are
injected. Pass --all to inject every image file regardless.

SAFE: timestamped PRE_DISKIMG_ backup before writing; idempotent (skips
fnames already present; re-running adds nothing new).

Usage:
    python3 scripts/inject_missing_images.py <ml_predict_labels_xlsx> [--all]
"""

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
CROP_RE = re.compile(r"(_crop_|_F\w*\.(png|jpe?g|webp)$|_Fu)", re.I)
ORIGINAL_RE = re.compile(r"(_img\d+\.(png|jpe?g|webp)$|PAFP\.(png|jpe?g|webp)$|^\d+_\d+\.(png|jpe?g|webp)$)", re.I)


def patent_dir_for(matched_root: Path, batch: str, patent_id: str) -> Path | None:
    base = matched_root / batch
    direct = base / patent_id
    if direct.is_dir():
        return direct
    hits = sorted(base.glob(f"{patent_id}_*"))
    return hits[0] if hits and hits[0].is_dir() else None


def wanted_files(patent_dir: Path, inject_all: bool) -> list[Path]:
    imgs = [f for f in sorted(patent_dir.iterdir())
            if f.is_file() and f.suffix.lower() in IMG_EXTS]
    if inject_all:
        return imgs
    crops = [f for f in imgs if CROP_RE.search(f.name)]
    # Files that are neither pipeline crops nor pipeline originals are
    # manually-added images — always surface those too.
    manual = [f for f in imgs if not CROP_RE.search(f.name) and not ORIGINAL_RE.search(f.name)]
    return crops + manual


def inject(export_path: Path, matched_root: Path, batch: str, inject_all: bool) -> None:
    df = pd.read_excel(export_path)

    # Existing "Image: <fname>" groups per patent — never duplicate these.
    have: dict[str, set] = {}
    t2 = df[(df["Section"] == "T2")
            & df["Sub_Dimension"].astype(str).str.startswith("Image: ")]
    for pid, sub in zip(t2["Patent_ID"], t2["Sub_Dimension"]):
        have.setdefault(str(pid).strip(), set()).add(str(sub)[len("Image: "):].strip())

    new_rows, missing_dirs = [], []
    pids = list(dict.fromkeys(df["Patent_ID"].dropna().astype(str).str.strip()))
    for pid in pids:
        pdir = patent_dir_for(matched_root, batch, pid)
        if pdir is None:
            missing_dirs.append(pid)
            continue
        known = have.get(pid, set())
        for f in wanted_files(pdir, inject_all):
            if f.name in known:
                continue
            new_rows.append({
                "Patent_ID": pid, "Section": "T2",
                "Sub_Dimension": f"Image: {f.name}", "Field": "match_status",
                "Definition": f"Image: {f.name} — found on disk, not in ML export",
                "Options": "", "Value": "disk_only", "Confidence": None,
                "Source": "disk_scan", "Image_Path": str(f), "Needs_Review": True,
            })

    if new_rows:
        new_df = pd.DataFrame(new_rows).reindex(columns=df.columns)
        out = pd.concat([df, new_df], ignore_index=True)
    else:
        out = df

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = export_path.with_name(export_path.stem + f".PRE_DISKIMG_{ts}.xlsx")
    shutil.copy2(export_path, backup)
    out.to_excel(export_path, sheet_name="Review", index=False)

    print(f"  patents in export         : {len(pids)}")
    print(f"  image rows injected       : {len(new_rows)}")
    print(f"  patents with no matched/ folder: {len(missing_dirs)}")
    print(f"  backup                    : {backup}")
    print(f"  written                   : {export_path}")


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--all"]
    inject_all = "--all" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    export_path = Path(args[0])
    if not export_path.exists():
        raise SystemExit(f"Export not found: {export_path}")

    # Batch label from the filename (ml_predict_labels_Batch_01.xlsx → Batch_01),
    # falling back to the parent folder name (data/matched/<Batch_NN>/).
    m = re.search(r"(Batch_\d+)", export_path.name) or re.search(r"(Batch_\d+)", str(export_path.parent))
    if not m:
        raise SystemExit("Could not infer Batch_NN from the export path.")
    batch = m.group(1)

    from src.config_loader import load_config
    matched_root = Path(load_config()["paths"]["matched"])
    if not (matched_root / batch).is_dir():
        raise SystemExit(f"Not found: {matched_root / batch}")

    print(f"matched root: {matched_root / batch}")
    print(f"export      : {export_path}")
    inject(export_path, matched_root, batch, inject_all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
