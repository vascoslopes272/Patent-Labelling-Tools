#!/usr/bin/env python3
"""v15.5 boom-Longitudinal migration — make the field fuselage-only.

`boomN_long` asks which third of the AIRFRAME a boom attaches in. That is a real
question for a fuselage-mounted boom and a meaningless one for a wing-mounted
boom, whose station is just its wing's station. The batches proved it by
answering the same geometry two opposite ways (Batch_01 filled in Fore/Aft on 73
of 74 single-wing wing-attached groups; Batch_05 answered NA on 52 of 58).

Wizard v15.5 asks `boomN_long` only when the group is NOT wing-referenced, and
asks a new `boomN_wingIdx` ("which M2 wing panel") when it IS wing-referenced and
the aircraft has >= 2 panels. This script brings the labelled exports into line:

    clear boomN_long + boomN_longOth on every group whose boomN_attach is
    Wings or Both, leaving fuselage/empennage/other groups untouched.

`boomN_wingIdx` is deliberately NOT written. No existing value maps onto it, so
inventing one would turn a human annotation into a machine guess; the wizard
raises it as a blocker when the patent is reopened.

Writes to 03c_CORRECTED_wizard_exports (the folder 02a reads), backs up each file
as PRE_BOOMLONG_<ts>, and appends one row per cleared cell to CORRECTIONS_LOG.csv.

    python scripts/conformance/migrate_boom_long.py                 # dry run
    python scripts/conformance/migrate_boom_long.py --apply
    python scripts/conformance/migrate_boom_long.py --apply --batches Batch_02
"""
from __future__ import annotations
import argparse, csv, datetime as dt, shutil, sys
from pathlib import Path

import pandas as pd

DATA = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & "
            "Labelling Outputs/1639_DS/data")
C3 = DATA / "03c_CORRECTED_wizard_exports"
LOG = C3 / "CORRECTIONS_LOG.csv"
WING_REFD = {"Wings", "Both"}
RULE = "v15.5 boomN_long is fuselage-only (wing booms answer boomN_wingIdx)"
EVIDENCE = ("the field asks which third of the AIRFRAME the boom attaches in; on a "
            "wing-attached boom that is the wing's station, not the boom's — B01 answered "
            "Fore/Aft on 73/74 single-wing groups, B05 answered NA on 52/58")


def code(v) -> str:
    return str(v).split(" — ")[0].strip()


def migrate(df: pd.DataFrame, batch: str) -> tuple[pd.DataFrame, list[dict]]:
    """Blank long/longOth wherever the same boom group attaches to a wing."""
    df = df.copy()
    fields = df["Field"].astype(str)
    grp = fields.str.extract(r"^boom(\d+)_(attach|long|longOth)$")
    grp.columns = ["g", "kind"]
    work = df.assign(_g=grp["g"], _kind=grp["kind"])

    # (Patent_ID, boom index) -> attachment code
    att = work[work._kind == "attach"]
    wing = {(p, g) for p, g, v in zip(att.Patent_ID, att._g, att.Value)
            if code(v) in WING_REFD}

    hits, changes = [], []
    for idx, (pid, g, kind, val) in enumerate(
            zip(work.Patent_ID, work._g, work._kind, work.Value)):
        if kind not in ("long", "longOth") or (pid, g) not in wing:
            continue
        if pd.isna(val) or str(val).strip() == "":
            continue                       # already blank, nothing to record
        hits.append(work.index[idx])
        changes.append(dict(batch=batch, patent_id=pid, field=f"boom{g}_{kind}",
                            old_value=str(val)))
    df.loc[hits, "Value"] = None
    return df, changes


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batches", nargs="+", default=["Batch_01", "Batch_05"])
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    a = ap.parse_args()
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    all_changes = []

    for b in a.batches:
        p = C3 / f"reviewed_patents_{b}.xlsx"
        if not p.exists():
            print(f"  !! {p.name} missing — skipped", file=sys.stderr)
            continue
        df = pd.read_excel(p, sheet_name="Review")
        out, changes = migrate(df, b)
        pats = len({c["patent_id"] for c in changes})
        print(f"  {b}: {len(changes):>4} cells cleared across {pats:>3} patents "
              f"({len(df)} rows total)")
        for c in changes[:4]:
            print(f"        {c['patent_id']:<22} {c['field']:<16} was {c['old_value']!r}")
        if len(changes) > 4:
            print(f"        … and {len(changes) - 4} more")
        all_changes += changes
        if a.apply:
            shutil.copy2(p, p.with_name(f"{p.stem}.PRE_BOOMLONG_{ts}.xlsx"))
            # sheet_name MUST stay "Review" — 02a Sections 3 and 5c read it by name.
            with pd.ExcelWriter(p, engine="openpyxl") as w:
                out.to_excel(w, sheet_name="Review", index=False)

    if not a.apply:
        print(f"\n  DRY RUN — {len(all_changes)} cells would be cleared. "
              f"Re-run with --apply.")
        return
    with LOG.open("a", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        for c in all_changes:
            wr.writerow([now, c["batch"], c["patent_id"], "M1", c["field"],
                         c["old_value"], "(cleared)", RULE, EVIDENCE, "vasco"])
    print(f"\n  applied · backups PRE_BOOMLONG_{ts} · {len(all_changes)} rows "
          f"appended to CORRECTIONS_LOG.csv")


if __name__ == "__main__":
    main()
