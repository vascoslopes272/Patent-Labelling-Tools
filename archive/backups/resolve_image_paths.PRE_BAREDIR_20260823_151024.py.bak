"""
resolve_image_paths.py — fill in the Image_Path column for T2 rows whose
Sub_Dimension is "Image: <filename>" but whose Image_Path is blank.

WHY: the HTML wizard's "📎 Attach/Replace Image" button (pageT2) lets a
reviewer pick a file that's already sitting in the patent's matched/ folder
(e.g. a manually-cropped screenshot the pipeline never matched). Browsers
never expose a real disk path for a picked File, so the wizard can only
record the filename (into the "Image: <filename>" Sub_Dimension) and preview
it via a session-only blob: URL — the exported row's Image_Path column comes
back blank. This script closes that gap on the Python side: for every blank
Image_Path, it searches paths.matched (config.yaml) for a file with that
exact basename anywhere under the patent's own matched/**/<patent_id>*/
folder, and fills in the absolute path so the *next* time this xlsx is
loaded in the wizard, the real image renders instead of "no image on disk".

SAFE: backs up the export before writing (timestamped); idempotent (only
touches rows with a currently-blank Image_Path); never touches the image
files themselves, only the xlsx.

Usage:
    python3 scripts/resolve_image_paths.py <ml_predict_labels_or_reviewed_xlsx>
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def find_image(matched_root: Path, patent_id: str, filename: str) -> Path | None:
    """Look for `filename` under any matched/**/<patent_id>*/ folder."""
    for patent_dir in matched_root.glob(f"**/{patent_id}_*"):
        if not patent_dir.is_dir():
            continue
        hit = patent_dir / filename
        if hit.exists():
            return hit
    # Also check a folder named exactly the bare patent_id (no record suffix).
    direct = matched_root / patent_id / filename
    if direct.exists():
        return direct
    return None


def resolve(export_path: Path, matched_root: Path) -> None:
    df = pd.read_excel(export_path)

    is_image_row = df["Section"] == "T2"
    is_image_row &= df["Sub_Dimension"].astype(str).str.startswith("Image: ")
    blank_path = df["Image_Path"].isna() | (df["Image_Path"].astype(str).str.strip() == "")
    candidates = df[is_image_row & blank_path]

    resolved = 0
    unresolved = []
    for idx, row in candidates.iterrows():
        fname = str(row["Sub_Dimension"])[len("Image: "):].strip()
        if not fname or fname == "(none available)":
            continue
        hit = find_image(matched_root, str(row["Patent_ID"]).strip(), fname)
        if hit:
            df.at[idx, "Image_Path"] = str(hit)
            resolved += 1
        else:
            unresolved.append((row["Patent_ID"], fname))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = export_path.with_name(export_path.stem + f".PRE_IMGPATH_{ts}.xlsx")
    shutil.copy2(export_path, backup)

    df.to_excel(export_path, sheet_name="Review", index=False)

    print(f"  blank Image_Path rows checked: {len(candidates)}")
    print(f"  resolved                     : {resolved}")
    print(f"  still unresolved              : {len(unresolved)}")
    for pid, fname in unresolved:
        print(f"    - {pid}: {fname}")
    print(f"  backup                        : {backup}")
    print(f"  written                       : {export_path}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    export_path = Path(sys.argv[1])
    if not export_path.exists():
        raise SystemExit(f"Export not found: {export_path}")

    from src.config_loader import load_config
    matched_root = Path(load_config()["paths"]["matched"])
    if not matched_root.exists():
        raise SystemExit(f"matched/ root not found: {matched_root}")

    print(f"matched root: {matched_root}")
    print(f"export      : {export_path}")
    resolve(export_path, matched_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
