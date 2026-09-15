#!/usr/bin/env python3
"""
build_identity_all.py — one corpus-wide file from the five Stage 03a workbooks.

Stage 04 reads the wizard exports, not 03a. This is the bridge: it concatenates
the per-batch `aircraft_identity_Batch_NN.xlsx` files into

    1639_LABELLED/joined/aircraft_identity_ALL.xlsx
        Identity   1 row per patent   (join on patent_id)
        Variants   1 row per AIRCRAFT (join on variant_id; is_primary marks the first)
        Review     what is answered, what is flagged uncertain, what is still open

and prints the review state so a half-finished pass can never be mistaken for a
finished one.

Run it AFTER exporting from the review page and copying the exported workbooks
back over `labels/Batch_NN/`. **No 03a re-run is needed**: the review page writes
back your typed cells, and everything derived from them — the *_final columns,
the duplicate inheritance, the review queue and the Variants sheet — is
recomputed here in seconds by the same functions the notebook uses. Re-run the
notebook only when you want fresh MACHINE columns (new quotes, a changed
gazetteer, a rule change), which costs ~2 minutes a batch because of SBERT.

Corrections to the wizard record are applied here too, from

    1639_LABELLED/CORRECTIONS_identity.csv    patent_id, field, new_value, reason, decided

so a wrong duplicate link or aircraft count is fixed DOWNSTREAM and the human
export stays exactly as the annotator left it.

    python scripts/build_identity_all.py            # build + report
    python scripts/build_identity_all.py --check    # report only, write nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config_loader import load_config                      # noqa: E402
from src.identity_schema import (                              # noqa: E402
    UNCERTAIN_COLUMNS, FINAL_COLUMNS, apply_finals, propagate_duplicate_finals,
    review_flags,
)
from src.identity_excel import build_variants_sheet            # noqa: E402

CORRECTIONS = "CORRECTIONS_identity.csv"
# Which aircraft of a multi-aircraft original each duplicate repeats, answered
# by the annotator. `answer` is a letter (a, b, c …) or "all" when the duplicate
# covers every aircraft of the original — "all" leaves the pin empty, which is
# already the behaviour: the duplicate takes the original's patent-level answers.
VARIANT_ANSWERS = "DUPLICATE_ROOT_VARIANT.csv"
# Only fields of the WIZARD record may be corrected here. Everything else is
# either yours to type in the review page or derived from these.
CORRECTABLE = {"wizard_duplicate_type", "wizard_duplicate_of", "wizard_arch_count",
               "wizard_aircraft_name", "wizard_approved", "wizard_edge_tags"}

BATCHES = [f"Batch_{i:02d}" for i in range(1, 6)]


def _read(labels: Path, batch: str, sheet: str) -> pd.DataFrame:
    f = labels / batch / f"aircraft_identity_{batch}.xlsx"
    if not f.exists():
        raise FileNotFoundError(f"{f} — run the 03a notebook for {batch} first.")
    return pd.read_excel(f, sheet_name=sheet, dtype=object)


def apply_corrections(ident: pd.DataFrame, path: Path) -> list[str]:
    """Fix the wizard record downstream, never in the annotator's own export."""
    if not path.exists():
        return []
    import csv

    by_id = {pid: i for i, pid in enumerate(ident["patent_id"])}
    applied = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            pid, field = (row.get("patent_id") or "").strip(), (row.get("field") or "").strip()
            if not pid or not field:
                continue
            if field not in CORRECTABLE:
                applied.append(f"⚠  {pid}: '{field}' is not correctable here — ignored")
                continue
            if pid not in by_id:
                applied.append(f"⚠  {pid}: not in the corpus — ignored")
                continue
            raw = (row.get("new_value") or "").strip()
            new = None if raw == "" else raw
            i = by_id[pid]
            old = ident.at[i, field]
            ident.at[i, field] = new
            applied.append(f"   {pid}.{field}: {old!r} -> {new!r}  ({row.get('reason', '')[:70]})")
    return applied


def apply_variant_answers(ident: pd.DataFrame, path: Path) -> list[str]:
    """Pin each duplicate to one aircraft of its original, from the annotator's file."""
    if not path.exists():
        return []
    import csv

    by_id = {pid: i for i, pid in enumerate(ident["patent_id"])}
    out, pinned, covers_all = [], 0, 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            pid = (row.get("patent_id") or "").strip()
            ans = (row.get("answer") or row.get("duplicate_root_variant") or "").strip().lower()
            if not pid or pid not in by_id:
                if pid:
                    out.append(f"⚠  {pid}: not in the corpus — ignored")
                continue
            i = by_id[pid]
            if ans in ("", "all"):
                ident.at[i, "duplicate_root_variant"] = None
                covers_all += 1
            elif len(ans) == 1 and "a" <= ans <= "z":
                ident.at[i, "duplicate_root_variant"] = ans
                pinned += 1
            else:
                out.append(f"⚠  {pid}: answer {ans!r} is not a letter or 'all' — ignored")
    out.insert(0, f"   {pinned} duplicate(s) pinned to one aircraft, {covers_all} marked 'all'")
    return out


def recompute(ident: pd.DataFrame) -> pd.DataFrame:
    """Redo everything derived from the cells the reviewer typed.

    The same functions the 03a notebook calls, so the two can never disagree —
    but without the SBERT passes, which is why this takes seconds.
    """
    rows = ident.to_dict("records")
    for r in rows:
        apply_finals(r)
    propagate_duplicate_finals(rows)
    for r in rows:
        r.update(review_flags(r))
    return pd.DataFrame(rows, columns=list(ident.columns))


def build(labels: Path, out_dir: Path, write: bool = True,
          corrections: Path | None = None, answers: Path | None = None) -> dict:
    ident = pd.concat([_read(labels, b, "Identity") for b in BATCHES], ignore_index=True)
    fixes = apply_corrections(ident, corrections) if corrections else []
    if answers:
        fixes += apply_variant_answers(ident, answers)
    ident = recompute(ident)
    variants = build_variants_sheet(ident)

    approved = ident["wizard_approved"] == True                       # noqa: E712
    queued = ident["review_queue"].notna()
    status = ident["review_status"].fillna("").astype(str).str.strip().str.lower()

    review = []
    for field, unc in UNCERTAIN_COLUMNS.items():
        human = {"name": "aircraft_name_human", "electric": "is_electric_human",
                 "takeoff": "takeoff_human", "uav": "uav_human"}[field]
        review.append({
            "field": field,
            "answered_by_you": int(ident[human].notna().sum()),
            "marked_not_determinable": int(ident[unc].apply(_flag).sum()),
            "still_open": int(ident[f"{field}_review"].apply(_flag).sum()),
        })
    review = pd.DataFrame(review)

    summary = {
        "corrections_applied": sum(1 for f in fixes if not f.startswith("⚠")),
        "patents": len(ident),
        "approved": int(approved.sum()),
        "aircraft_rows": len(variants),
        "primary_aircraft": int((variants["is_primary"] == True).sum()),   # noqa: E712
        "marked_done": int((status == "done").sum()),
        "marked_skip": int((status == "skip").sum()),
        "still_in_the_queue": int(queued.sum()),
    }

    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "aircraft_identity_ALL.xlsx"
        with pd.ExcelWriter(out, engine="openpyxl") as w:
            ident.to_excel(w, sheet_name="Identity", index=False)
            variants.to_excel(w, sheet_name="Variants", index=False)
            review.to_excel(w, sheet_name="Review", index=False)
        summary["written_to"] = str(out)
    return {"summary": summary, "review": review, "ident": ident, "variants": variants,
            "fixes": fixes}


def _flag(v) -> bool:
    if v is None or v is False:
        return False
    if v is True:
        return True
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    a = ap.parse_args()

    cfg = load_config()
    labels = Path(cfg["paths"]["data_matched"])
    root = Path(cfg["paths"]["labelled"])
    r = build(labels, root / "joined", write=not a.check,
              corrections=root / CORRECTIONS, answers=root / VARIANT_ANSWERS)

    if r["fixes"]:
        print(f"corrections from {CORRECTIONS} and {VARIANT_ANSWERS}:")
        print("\n".join(r["fixes"]))
        print()
    print("\n".join(f"{k:22s} {v}" for k, v in r["summary"].items()))
    print("\nreview state per field:")
    print(r["review"].to_string(index=False))

    open_rows = int(r["summary"]["still_in_the_queue"])
    if open_rows:
        print(f"\n⚠  {open_rows} patent(s) still carry an open decision. The file is usable, but "
              f"say so if you publish numbers from it — the *_final columns fall back to the "
              f"machine value wherever you have not answered.")
    else:
        print("\nEvery decision is answered or marked not determinable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
