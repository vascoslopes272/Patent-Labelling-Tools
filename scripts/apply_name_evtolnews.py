#!/usr/bin/env python3
"""Merge a NAME_EVTOLNEWS.csv export (name_evtolnews.html) into review_decisions/NAME_DECISIONS.csv.

action  assign   the aircraft IS the evtol.news aircraft → its name replaces the generated one (the page URL is kept
                 in source_note, so every name added by this pass cites its source)
        none     nothing changes

A patent already marked "clear" or "other" in the file gets the name all the same — that earlier ruling was made
without the evtol.news directory. A patent that already carries a REAL name for that aircraft is not touched (reported).
Run scripts/apply_duplicate_names.py afterwards (vN rule), then build_identity_all.py and notebook 04.

    python scripts/apply_name_evtolnews.py [NAME_EVTOLNEWS.csv] [--apply]
"""
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling/inputs")
OUT = ROOT.parent / "outputs"
DEC = ROOT / "review_decisions" / "NAME_DECISIONS.csv"
LET = "abcdefghijklmnopqrstuvwxyz"
TAG = f"evtol.news {pd.Timestamp.now():%Y-%m-%d}"


def main():
    argv = sys.argv[1:]
    apply = "--apply" in argv
    args = [a for a in argv if not a.startswith("--")]
    src = Path(args[0]) if args else max(
        [p for p in [ROOT / "review_decisions" / "NAME_EVTOLNEWS.csv", Path.home() / "Downloads" / "NAME_EVTOLNEWS.csv"] if p.exists()],
        key=lambda p: p.stat().st_mtime)
    picks = [r for r in csv.DictReader(open(src, newline="", encoding="utf-8")) if r["action"] == "assign" and r["name"].strip()]
    rows = list(csv.DictReader(open(DEC, newline="", encoding="utf-8")))
    header = list(rows[0].keys())
    by = {r["patent_id"]: r for r in rows}

    tab = pd.read_csv(OUT / "tables" / "aircraft_table.csv", keep_default_na=False, dtype=str,
                      usecols=["patent_id", "variant", "is_primary", "is_approved", "aircraft_name", "name_is_real"])
    prim = tab[(tab.is_primary == "True") & (tab.is_approved == "True")]
    nvar = prim.groupby("patent_id").size().to_dict()
    real = {(r.patent_id, int(r.variant or 1)) for r in prim.itertuples() if r.name_is_real == "True"}
    idn = pd.read_excel(ROOT / "identity" / "aircraft_identity_ALL.xlsx", sheet_name="Identity").set_index("patent_id")

    def gname(pid, v):
        gv = [x.strip() for x in str(idn.at[pid, "aircraft_group_variants"]).split(";") if x.strip()]
        return gv[v - 1] if nvar.get(pid, 1) > 1 and v - 1 < len(gv) else str(idn.at[pid, "aircraft_group"])

    print(f"merging {src}: {len(picks)} name(s)")
    for s in picks:
        pid, name = s["patent_id"], s["name"].strip()
        v = (LET.index(s["aircraft"]) + 1) if s["aircraft"] else 1
        n = nvar.get(pid, 1)
        if (pid, v) in real:
            print(f"  ⚠ {pid} {s['aircraft']}: already has a real name — {name!r} not written")
            continue
        if pid not in by:
            r = {k: "" for k in header}
            r["patent_id"] = pid
            rows.append(r)
            by[pid] = r
        r = by[pid]
        old = r["name_final"] if r["decision"] != "clear" else ""
        if n > 1:
            parts = [x.strip() for x in old.split(";")] if old else []
            parts = (parts + [""] * n)[:n]
            parts = [p or gname(pid, i + 1) for i, p in enumerate(parts)]
            parts[v - 1] = name
            r["name_final"] = "; ".join(parts)
        else:
            r["name_final"] = name
        r["decision"] = "known"
        src_note = f"{s['page_title']} <{s['url']}>"
        r["source_note"] = "; ".join(x for x in [r.get("source_note", ""), src_note] if x)
        r["comment"] = f"{TAG}: {name}" + (f" ({s['note']})" if s.get("note") else "") + (f" | was: {r['comment']}" if r["comment"] else "")
        r["decided_at"] = f"{pd.Timestamp.now():%Y-%m-%dT%H:%M}"
        print(f"  {pid}{' ' + s['aircraft'] if s['aircraft'] else '':3} {old or '(generated)':34} → {r['name_final']}")
    # names that now sit on more than one aircraft → the user decides: same aircraft (flag D1/D2) or versions (vN)
    import re as _re
    base = lambda n: _re.sub(r"\s+v\d+$", "", str(n).strip(), flags=_re.I).lower()
    names = {}
    for r in rows:
        for i, nm in enumerate([x.strip() for x in str(r["name_final"]).split(";")] if r["decision"] != "clear" else []):
            if nm:
                names.setdefault(base(nm), []).append(r["patent_id"] + (f" {LET[i]}" if ";" in r["name_final"] else ""))
    touched = {base(s["name"]) for s in picks}
    rep = {k: v for k, v in names.items() if k in touched and len(v) > 1}
    if rep:
        print("\n⚠ names on more than one patent — same aircraft? flag the later one as D1/D2 in the wizard; "
              "different versions? keep (apply_duplicate_names.py numbers them vN):")
        for k, v in sorted(rep.items()):
            print(f"  {k:16} {len(v)}: {', '.join(v)}")
    if apply:
        bak = DEC.parent / "_backups" / "names" / f"NAME_DECISIONS.PRE_EVTOLNEWS_{pd.Timestamp.now():%Y%m%d_%H%M%S}.csv"
        bak.parent.mkdir(parents=True, exist_ok=True)
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
