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
VARIANT_ANSWERS = "review_decisions/duplicate_root_variant.csv"   # 2026-09-17: the page export is the one file (root copy archived)
# The annotator's rulings from notebooks/post-process/name_review.html (every aircraft-name proposal with its evidence),
# exported as NAME_DECISIONS.csv and copied into 1639_LABELLED/. They fill the *_human name cells only
# where the identity review page left them empty — a name typed in that page always wins.
NAME_DECISIONS = "NAME_DECISIONS.csv"
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


def _is_blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "None")


def apply_name_decisions(ident: pd.DataFrame, path: Path) -> list[str]:
    """Write the name-review rulings into the human name cells that are still empty.

    decision  text | known | other | fix  -> the typed name (';'-separated = one per aircraft)
              clear                        -> the generated group name, so the question counts as answered
    """
    if not path.exists():
        return []
    import csv

    by_id = {pid: i for i, pid in enumerate(ident["patent_id"])}
    out, filled, kept, fixes = [], 0, 0, []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            pid = (row.get("patent_id") or "").strip()
            decision = (row.get("decision") or "").strip()
            if not pid or not decision:
                continue
            if pid not in by_id:
                out.append(f"⚠  {pid}: not in the corpus — name decision ignored")
                continue
            i = by_id[pid]
            if decision == "clear":
                name = ident.at[i, "aircraft_group"]
            elif decision in ("text", "known", "other", "fix"):
                name = (row.get("name_final") or "").strip()
            else:
                out.append(f"⚠  {pid}: unknown name decision {decision!r} — ignored")
                continue
            if _is_blank(name):
                out.append(f"⚠  {pid}: decision {decision!r} without a name — ignored")
                continue
            # a ";" name is one name per aircraft: it goes to the variants column, and the patent-level cell takes the
            # first aircraft's name so the question counts as answered (2026-09-16)
            col = "aircraft_name_human_variants" if ";" in str(name) else "aircraft_name_human"
            if col == "aircraft_name_human_variants" and _is_blank(ident.at[i, "aircraft_name_human"]):
                ident.at[i, "aircraft_name_human"] = str(name).split(";")[0].strip()
            # only the TARGET cell is protected: a one-name-per-aircraft decision may still fill the variants column of a
            # patent whose patent-level name was typed in the 03a page (2026-09-16)
            if not _is_blank(ident.at[i, col]):
                kept += 1
                continue
            ident.at[i, col] = str(name).strip()
            filled += 1
            if decision == "fix":
                fixes.append(f"   {pid}: wizard name should read {name!r} (was {ident.at[i, 'wizard_aircraft_name']!r})")
    out.insert(0, f"   {filled} name(s) filled from {path.name}, {kept} left as typed in the review page")
    return out + fixes


# Ruling 2026-09-13: a row whose powertrain was only PRESUMED (the patent never states one) but whose
# own text carries a turbine / piston sentence contradicts the presumption, so the electric question is
# re-opened on it. The evidence file is the one embedded in the review page, so page and report agree.
EVIDENCE = "identity/identity_evidence_20260913.json"   # 2026-09-17 layout: 0_labelling/inputs/identity/


def flag_presumed_conflicts(ident: pd.DataFrame, path: Path) -> list[str]:
    if not path.exists():
        return []
    import json

    ev = json.loads(path.read_text(encoding="utf-8"))
    opened = 0
    for i, row in ident.iterrows():
        if str(row.get("is_electric_source") or "") != "presumed":
            continue
        if not _is_blank(row.get("aircraft_name_human")) and False:
            continue
        if not _is_blank(row.get("is_electric_human")):
            continue
        # Only a STATED combustion sentence contradicts the presumption. An option
        # ("may include a gas turbine") or Bell's background boilerplate ("fixed-wing
        # aircraft … jet engines or propellers") is graded by build_identity_evidence.py
        # and does not count — before this check all 41 re-opened rows were such noise.
        comb = ev.get(row["patent_id"], {}).get("combustion") or []
        if not any((q[3] if len(q) > 3 else "stated") == "stated" for q in comb):
            continue
        ident.at[i, "electric_review"] = True
        queue = "" if _is_blank(row.get("review_queue")) else str(row["review_queue"])
        if "electric" not in queue:
            ident.at[i, "review_queue"] = (queue + "+electric") if queue else "electric"
        opened += 1
    return [f"   {opened} presumed-electric row(s) re-opened: their own text mentions a turbine or piston"]


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
          corrections: Path | None = None, answers: Path | None = None,
          names: Path | None = None) -> dict:
    ident = pd.concat([_read(labels, b, "Identity") for b in BATCHES], ignore_index=True)
    fixes = apply_corrections(ident, corrections) if corrections else []
    if answers:
        fixes += apply_variant_answers(ident, answers)
    if names:
        fixes += apply_name_decisions(ident, names)
    ident = recompute(ident)
    fixes += flag_presumed_conflicts(ident, Path(str(corrections).rsplit("/", 1)[0]) / EVIDENCE) if corrections else []
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
    r = build(labels, root / "identity", write=not a.check,                       # 2026-09-17: identity_ALL is a derived INPUT of 04
              corrections=root / "review_decisions" / CORRECTIONS, answers=root / VARIANT_ANSWERS,
              names=next((p for p in [root / "review_decisions" / NAME_DECISIONS, root / NAME_DECISIONS]
                          if p.exists()), root / "review_decisions" / NAME_DECISIONS))

    if r["fixes"]:
        print(f"corrections from {CORRECTIONS}, {VARIANT_ANSWERS} and {NAME_DECISIONS}:")
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
