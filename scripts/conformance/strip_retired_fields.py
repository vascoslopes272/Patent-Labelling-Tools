#!/usr/bin/env python3
"""Drop rows for dimensions the wizard has retired — without deleting human answers.

A retired field keeps appearing in exports because the wizard still PARSES it so
an old save loads (see the retirement notes in the HTML). It is never rendered
and never re-asked, so the column rides through every load/save cycle and reaches
Stage 02 as noise.

The safety rule: a row is only dropped when it is EMPTY. A retired field that
still carries a value carries a human observation, and deleting it is a judgement
call, not a cleanup — those rows are reported and left alone until you pass
`--drop-valued <field>` to say you have looked at them.

    python scripts/conformance/strip_retired_fields.py                   # dry run
    python scripts/conformance/strip_retired_fields.py --apply
    python scripts/conformance/strip_retired_fields.py --apply --drop-valued tiltedInView
"""
from __future__ import annotations
import argparse, csv, datetime as dt, shutil, sys
from pathlib import Path

import pandas as pd

DATA = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & "
            "Labelling Outputs/1639_DS/data")
C3 = DATA / "03c_CORRECTED_wizard_exports"
LOG = C3 / "CORRECTIONS_LOG.csv"

RETIRED = {
    "imgApparentArch": "APPARENT_ARCH retired v15.3 — the card was removed and the "
                       "array only fed this one export row, which no reviewer ever filled",
    "tiltedInView":    "TILTED_IN_VIEW retired v14 (C1) — the per-figure pick carried no "
                       "signal beyond acState + topType",
    "empTiltsNote":    "the mandatory tilt-mechanism description retired v15.5 — the empTilts "
                       "tick alone is the record (empTilts itself is NOT retired)",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batches", nargs="+", default=["Batch_01", "Batch_05"])
    ap.add_argument("--drop-valued", nargs="*", default=[], metavar="FIELD",
                    help="also drop rows of these fields that carry a value")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    logged, held = [], []

    for b in a.batches:
        p = C3 / f"reviewed_patents_{b}.xlsx"
        if not p.exists():
            print(f"  !! {p.name} missing — skipped", file=sys.stderr)
            continue
        df = pd.read_excel(p, sheet_name="Review")
        drop, before = [], len(df)
        print(f"  {b}  ({before} rows)")
        for field, why in RETIRED.items():
            rows = df[df.Field.astype(str) == field]
            if rows.empty:
                continue
            valued = rows[rows.Value.notna() & rows.Value.astype(str).str.strip().ne("")]
            empty = rows.drop(valued.index)
            drop += list(empty.index)
            note = ""
            if len(valued):
                if field in a.drop_valued:
                    drop += list(valued.index)
                    for _, r in valued.iterrows():
                        logged.append(dict(batch=b, patent=r.Patent_ID, field=field,
                                           old=str(r.Value)))
                    note = f"  + {len(valued)} valued (dropped, you asked)"
                else:
                    held += [(b, r.Patent_ID, field, str(r.Value),
                              str(r.Sub_Dimension)) for _, r in valued.iterrows()]
                    note = f"  + {len(valued)} valued — HELD, needs your call"
            print(f"     {field:<18} {len(empty):>4} empty rows dropped{note}")
        if a.apply and drop:
            shutil.copy2(p, p.with_name(f"{p.stem}.PRE_STRIP_{ts}.xlsx"))
            out = df.drop(index=drop).reset_index(drop=True)
            # sheet_name MUST stay "Review" — 02a Sections 3 and 5c read it by name.
            with pd.ExcelWriter(p, engine="openpyxl") as w:
                out.to_excel(w, sheet_name="Review", index=False)
            print(f"     -> {before} rows becomes {len(out)}")

    if held:
        print(f"\n  HELD — {len(held)} row(s) carry a human answer. Look at them, then "
              f"re-run with --drop-valued <field>:")
        for b, pid, field, val, sub in held:
            print(f"     {b[-2:]} {pid:<22} {field:<15} {val[:38]:<40} {sub[:34]}")
    if not a.apply:
        print("\n  DRY RUN — re-run with --apply.")
        return
    if logged:
        with LOG.open("a", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            for c in logged:
                wr.writerow([now, c["batch"], c["patent"], "", c["field"], c["old"],
                             "(row removed)", "retired dimension stripped from the export",
                             RETIRED[c["field"]], "vasco"])
        print(f"\n  {len(logged)} valued row(s) logged to CORRECTIONS_LOG.csv")
    print(f"  applied · backups PRE_STRIP_{ts}")


if __name__ == "__main__":
    main()
