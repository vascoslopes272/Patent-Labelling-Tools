#!/usr/bin/env python3
"""Merge a NAME_SWEEP2.csv export (name_sweep2.html) into review_decisions/NAME_DECISIONS.csv.

Sections and actions written by the page:
  repeated   keep | dupe | other | clear   one aircraft of a repeated name keeps it, the others are settled
  unassigned assign | none                 a company name nobody had is given to one aircraft ("none" = no aircraft)
  set        ok | wrong | other            confirmation pass over every name already in the file

An "assign" on an aircraft that already carries another name replaces that name (the page notes it).
Run scripts/apply_duplicate_names.py afterwards to re-apply the vN rule.

    python scripts/apply_name_sweep2.py [NAME_SWEEP2.csv] [--apply]
"""
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
DEC = ROOT / "review_decisions" / "NAME_DECISIONS.csv"
LET = "abcdefghijklmnopqrstuvwxyz"


def main():
    argv = sys.argv[1:]
    apply = "--apply" in argv
    args = [a for a in argv if not a.startswith("--")]
    src = Path(args[0]) if args else max(
        [p for p in [ROOT / "review_decisions" / "NAME_SWEEP2.csv", Path.home() / "Downloads" / "NAME_SWEEP2.csv"] if p.exists()],
        key=lambda p: p.stat().st_mtime)
    sweep = list(csv.DictReader(open(src, newline="", encoding="utf-8")))
    rows = list(csv.DictReader(open(DEC, newline="", encoding="utf-8")))
    header = list(rows[0].keys())
    by = {r["patent_id"]: r for r in rows}

    ml = pd.read_excel(ROOT / "joined" / "master_labels.xlsx", keep_default_na=False, dtype=str,
                       usecols=["patent_id", "variant", "topType", "is_primary", "is_approved"])
    ml = ml[(ml.is_primary == "True") & (ml.is_approved == "True")]
    nvar = ml.groupby("patent_id").size().to_dict()
    idn = pd.read_excel(ROOT / "joined" / "aircraft_identity_ALL.xlsx", sheet_name="Identity").set_index("patent_id")

    def gname(pid, v):
        gv = [x.strip() for x in str(idn.at[pid, "aircraft_group_variants"]).split(";") if x.strip()]
        return gv[v - 1] if nvar.get(pid, 1) > 1 and v - 1 < len(gv) else str(idn.at[pid, "aircraft_group"])

    def set_name(pid, v, name, note):
        if pid not in by:
            r = {k: "" for k in header}
            r["patent_id"] = pid
            rows.append(r)
            by[pid] = r
        r = by[pid]
        n = nvar.get(pid, 1)
        parts = [x.strip() for x in str(r["name_final"]).split(";")] if r["decision"] != "clear" else []
        parts = (parts + [""] * n)[:n] if n > 1 else [parts[0] if parts else ""]
        old = r["name_final"]
        parts[v - 1] = name
        for i in range(n):
            if not parts[i]:
                parts[i] = gname(pid, i + 1) if n > 1 and any(parts) else parts[i]
        r["name_final"] = "; ".join(parts) if n > 1 else parts[0]
        r["decision"] = "known" if r["name_final"].strip("; ") else "clear"
        if not r["name_final"].strip("; "):
            r["name_final"] = ""
        r["comment"] = note
        r["decided_at"] = "2026-09-16T00:17"
        print(f"  {pid}{' ' + LET[v-1] if nvar.get(pid,1)>1 else '':3} {old or '(clear)':34} → {r['name_final'] or '(clear)'}")

    print(f"merging {src}")
    for s in sweep:
        pid, act, sec = s["patent_id"], s["action"], s["section"]
        v = (LET.index(s["aircraft"]) + 1) if s["aircraft"] else 1
        if act in ("none", "ok") or not pid:
            continue
        if sec == "unassigned" and act == "assign":
            set_name(pid, v, s["name"], f"sweep 2 2026-09-16: {s['name']}" + (f" ({s['note']})" if s["note"] else ""))
        elif sec == "set" and act == "wrong":
            set_name(pid, v, "", "sweep 2 2026-09-16: not this aircraft")
        elif sec == "set" and act == "other":
            set_name(pid, v, s["new_name"], "sweep 2 2026-09-16: renamed by the reviewer")
        elif sec == "repeated":
            if act == "keep":
                set_name(pid, v, s["name"], "sweep 2 2026-09-16: keeps the name")
            elif act == "clear":
                set_name(pid, v, "", "sweep 2 2026-09-16: different aircraft")
            elif act == "other":
                set_name(pid, v, s["new_name"], "sweep 2 2026-09-16: its own name")
            elif act == "dupe":
                print(f"  ⚠ {pid}: marked as the same aircraft as {s['duplicate_of']} — needs the duplicate flag in the wizard")
    if apply:
        bak = DEC.with_name(f"NAME_DECISIONS.PRE_SWEEP2MERGE_{pd.Timestamp.now():%Y%m%d_%H%M%S}.csv")
        DEC.rename(bak)
        with open(DEC, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=header, quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(rows)
        print("backup:", bak, "\nwrote", DEC)
    else:
        print("dry run — re-run with --apply")


if __name__ == "__main__":
    main()
