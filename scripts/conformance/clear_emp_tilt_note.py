#!/usr/bin/env python3
"""v15.5 — clear empTiltsNote, keep empTilts.

The "Describe the tilt mechanism (required)" note is retired: the tick alone is
the record. Of the 12 notes in the corpus, 5 were auto-migrated "legacy:" text no
reviewer wrote and the rest restate the tick ("it tilts", "all the empenage
tilts"), so the prose carried nothing the boolean did not.

`empTilts` is UNTOUCHED — that an empennage tilts is still recorded. Only the
note is cleared, and only where it is non-empty.

    python scripts/conformance/clear_emp_tilt_note.py            # dry run
    python scripts/conformance/clear_emp_tilt_note.py --apply
"""
from __future__ import annotations
import argparse, csv, datetime as dt, shutil, sys
from pathlib import Path

import pandas as pd

C3 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & "
          "Labelling Outputs/1639_DS/data/03c_CORRECTED_wizard_exports")
RULE = "v15.5 empTiltsNote retired — the empTilts tick alone is the record"
EVID = ("of the 12 notes in the corpus 5 were auto-migrated 'legacy:' text and the rest "
        "restate the tick; nothing unusual about a mechanism was recorded that the M2 "
        "comment box could not hold")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batches", nargs="+", default=["Batch_01", "Batch_05"])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    logged = []

    for b in a.batches:
        p = C3 / f"reviewed_patents_{b}.xlsx"
        if not p.exists():
            print(f"  !! {p.name} missing — skipped", file=sys.stderr)
            continue
        df = pd.read_excel(p, sheet_name="Review")
        note = df[df.Field.astype(str) == "empTiltsNote"]
        hot = note[note.Value.notna() & note.Value.astype(str).str.strip().ne("")]
        kept = (df[df.Field.astype(str) == "empTilts"].Value.astype(str) == "True").sum()
        print(f"  {b}: {len(hot)} note(s) to clear · empTilts=True on {kept} patent(s), kept")
        for _, r in hot.iterrows():
            print(f"        {r.Patent_ID:<22} {str(r.Value)[:46]!r}")
            logged.append(dict(batch=b, patent=r.Patent_ID, old=str(r.Value)))
        if a.apply and len(hot):
            shutil.copy2(p, p.with_name(f"{p.stem}.PRE_EMPNOTE_{ts}.xlsx"))
            df.loc[hot.index, "Value"] = None
            # sheet_name MUST stay "Review" — 02a Sections 3 and 5c read it by name.
            with pd.ExcelWriter(p, engine="openpyxl") as w:
                df.to_excel(w, sheet_name="Review", index=False)

    if not a.apply:
        print(f"\n  DRY RUN — {len(logged)} note(s) would be cleared. Re-run with --apply.")
        return
    if logged:
        with (C3 / "CORRECTIONS_LOG.csv").open("a", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            for c in logged:
                wr.writerow([now, c["batch"], c["patent"], "M2", "empTiltsNote", c["old"],
                             "(cleared)", RULE, EVID, "vasco"])
    print(f"\n  applied · backups PRE_EMPNOTE_{ts} · {len(logged)} row(s) logged")


if __name__ == "__main__":
    main()
