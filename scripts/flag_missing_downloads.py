"""
flag_missing_downloads.py — flag patents that appear in an ml_predict_labels
export but were NEVER downloaded (no folder under paths.raw).

WHY: a handful of patents in the PatSeer family list never produced a raw
download — the source site had no retrievable images, the publication is a
design/utility-model stub, etc. They still flow through grouping/labelling
(their Image_Path rows point at assets/no_image_available.png), so they reach
the human-review wizard looking like a normal patent with "no images" — easy to
mistake for a crop-extraction failure. We can only get these documents "in the
end" (manual retrieval), so they must be visibly flagged NOW, not silently
carried, or they'll be lost in the final merge.

This audits each patent in the export against the actual download folders under
paths.raw and, for any patent with no folder, injects ONE extra row:
    Section=T1, Field="missing_from_download", Value="true", Source="download_audit"

The wizard reads it back with metaVal('missing_from_download') (same flat
Patent_ID/Section/Field/Value lookup it uses for title/pdf_link/etc.) and shows
a red banner, so no schema change is needed.

Detection: raw download folders are named "<publication_number>_<record_number>"
(e.g. "US2019161188A1_56263910"). A patent counts as downloaded when some raw
folder's publication-number prefix equals its Patent_ID. We match on the prefix
ONLY (not the record-number suffix) because the export's Patent_ID is the
publication number.

SAFE: backs up the export before writing (timestamped, never overwrites an
existing backup); idempotent (removes any prior missing_from_download rows
before re-adding, so re-running doesn't duplicate); read-only on paths.raw.

Usage:
    python3 scripts/flag_missing_downloads.py <ml_predict_labels_xlsx> [raw_dir]

If raw_dir is omitted, it's read from config.yaml (paths.raw_images).
"""

import shutil
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd

# Cosmetic: our flag rows have all-NA Confidence/Image_Path columns, which trips
# a pandas concat deprecation warning. The behaviour is what we want, so silence
# just this one.
warnings.filterwarnings(
    "ignore",
    message="The behavior of DataFrame concatenation with empty or all-NA entries",
    category=FutureWarning,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def downloaded_publication_numbers(raw_dir: Path) -> set[str]:
    """Return the set of publication numbers that have a raw download folder.

    Folders are "<pub_num>_<record_num>"; we keep the prefix before the LAST
    underscore so publication numbers that themselves contain underscores (none
    observed, but be safe) aren't truncated."""
    pubs: set[str] = set()
    for entry in raw_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        pub = name.rsplit("_", 1)[0] if "_" in name else name
        pubs.add(pub.strip())
    return pubs


def flag(export_path: Path, downloaded: set[str]) -> int:
    df = pd.read_excel(export_path)

    # Drop any pre-existing flag rows so re-running is idempotent.
    before = len(df)
    df = df[df["Field"] != "missing_from_download"].copy()
    removed = before - len(df)

    # One flag row per patent whose publication number has no raw folder,
    # mirroring the existing T1 metadata row shape so metaVal() finds it.
    new_rows = []
    pids = list(dict.fromkeys(df["Patent_ID"].dropna().tolist()))  # unique, ordered
    missing = []
    for pid in pids:
        if str(pid).strip() in downloaded:
            continue
        missing.append(pid)
        new_rows.append({
            "Patent_ID": pid, "Section": "T1", "Sub_Dimension": "Download Audit",
            "Field": "missing_from_download", "Definition":
                "No raw download folder for this patent — images are placeholders. "
                "Source document must be retrieved manually before the final merge.",
            "Options": "", "Value": "true", "Confidence": None,
            "Source": "download_audit", "Image_Path": None, "Needs_Review": True,
        })

    # Align new rows to existing columns before concat so pandas doesn't warn
    # about all-NA columns (Confidence/Image_Path are None here).
    if new_rows:
        new_df = pd.DataFrame(new_rows).reindex(columns=df.columns)
        out = pd.concat([df, new_df], ignore_index=True)
    else:
        out = df

    # Backup before writing (timestamped, never clobber an existing backup).
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = export_path.with_name(export_path.stem + f".PRE_MISSINGDL_{ts}.xlsx")
    shutil.copy2(export_path, backup)

    out.to_excel(export_path, sheet_name="Review", index=False)

    print(f"  removed {removed} stale missing_from_download row(s)")
    print(f"  patents in export          : {len(pids)}")
    print(f"  MISSING FROM DOWNLOAD      : {len(missing)}")
    for m in missing:
        print(f"      - {m}")
    print(f"  backup                     : {backup}")
    print(f"  written                    : {export_path}")
    return len(missing)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    export_path = Path(sys.argv[1])
    if not export_path.exists():
        raise SystemExit(f"Export not found: {export_path}")

    if len(sys.argv) >= 3:
        raw_dir = Path(sys.argv[2])
    else:
        from src.config_loader import load_config
        raw_dir = Path(load_config()["paths"]["raw_images"])
    if not raw_dir.exists():
        raise SystemExit(f"Raw download dir not found: {raw_dir}")

    print(f"Raw download dir: {raw_dir}")
    print(f"Export          : {export_path}")
    downloaded = downloaded_publication_numbers(raw_dir)
    print(f"  download folders found: {len(downloaded)}")
    flag(export_path, downloaded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
