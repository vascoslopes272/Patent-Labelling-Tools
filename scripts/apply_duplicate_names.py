#!/usr/bin/env python3
"""Make the real aircraft names in NAME_DECISIONS.csv follow the duplicate links (rulings 2026-09-15).

  * the ORIGINAL keeps the real name
  * a D3 of it is a modified aircraft: the same name + " vN", N numbered by priority date among that original's D3s
  * a D1 / D2 is the same aircraft: it carries the original's name
  * the "original" of a D3 is the nearest record up its chain that is not itself a D1/D2 (a D3 of a D1 belongs to the
    D1's original)
  * CLEAR below: aircraft the user ruled are NOT the named aircraft (unlinked patents that shared a name); a D3 whose
    original is cleared gets no name either

Duplicate links come from the live wizard record joined/wizard_all/reviewed_patents_Batch_ALL.xlsx (identity_ALL can be
older). Only the name of the FIRST aircraft of a multi-aircraft patent follows the rule when it held the original's name.

    python scripts/apply_duplicate_names.py [NAME_DECISIONS.csv]            # dry run: prints every change
    python scripts/apply_duplicate_names.py [NAME_DECISIONS.csv] --apply    # writes 1639_LABELLED/review_decisions/NAME_DECISIONS.csv
"""
import csv
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
WIZARD_ALL = ROOT / "joined" / "wizard_all" / "reviewed_patents_Batch_ALL.xlsx"
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
OUT = ROOT / "review_decisions" / "NAME_DECISIONS.csv"

# user rulings 2026-09-15 (name sweep): shared a real name with another patent but are a different, unlinked aircraft
CLEAR = {
    "EP3636545A1": "APT belongs to US11319064B1; this patent is not linked to it",
    "US2025242909A1": "H1 belongs to US2022081107A1; different aircraft (77% labels, other family)",
    "US2024059393A1": "Honda eVTOL belongs to US2024190562A1; different aircraft (tail, wing position)",
}


def s(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def main():
    argv = sys.argv[1:]
    apply = "--apply" in argv
    args = [a for a in argv if not a.startswith("--")]
    src = Path(args[0]) if args else (OUT if OUT.exists() else Path.home() / "Downloads" / "NAME_DECISIONS.csv")
    rows = list(csv.DictReader(open(src, newline="", encoding="utf-8")))
    header = list(rows[0].keys())
    by = {r["patent_id"]: r for r in rows}

    w = pd.read_excel(WIZARD_ALL, dtype=str, keep_default_na=False,
                      usecols=["Patent_ID", "Field", "Value"])
    w = w[w.Field.isin(["isDuplicate", "duplicateId", "duplicateType"])]
    w["pid"] = w.Patent_ID.str.replace(r"_arch\d+$", "", regex=True)
    f = w.groupby(["pid", "Field"]).Value.first().unstack().fillna("")
    link = {pid: (r.duplicateId.strip(), r.duplicateType.split(" — ")[0].strip())
            for pid, r in f.iterrows() if r.get("isDuplicate", "") in ("True", "true", "1") and r.duplicateId.strip()}
    prio = pd.read_excel(PATSEER, usecols=["Record Number", "Priority Date (Record)"]).set_index("Record Number")["Priority Date (Record)"]

    def original(pid):
        """nearest ancestor that is not a D1/D2 (the record whose name this one derives from)"""
        seen, o = {pid}, link[pid][0]
        while o in link and link[o][1] in ("1", "2") and o not in seen:
            seen.add(o)
            o = link[o][0]
        return o

    def first_name(pid):
        r = by.get(pid)
        if not r or r["decision"] == "clear" or pid in CLEAR:
            return ""
        return s(r["name_final"]).split(";")[0].strip()

    changes = []

    def base(n):
        return re.sub(r"(\s+v\d+)+$", "", n).strip()

    def set_first(pid, new, why):
        r = by[pid]
        parts = [p.strip() for p in s(r["name_final"]).split(";")] if r["decision"] != "clear" else [""]
        old = r["name_final"]
        if new:
            parts[0] = new
            r["decision"] = r["decision"] if r["decision"] in ("text", "known", "other", "fix") else "known"
        else:
            parts[0] = ""
        r["name_final"] = "; ".join(parts) if len(parts) > 1 else parts[0]
        if not r["name_final"].strip("; "):
            r["decision"], r["name_final"] = "clear", ""
        r["comment"] = (r["comment"] + " | " if r["comment"] else "") + why
        if r["name_final"] != old:
            changes.append((pid, old, r["name_final"], why))

    for pid, why in CLEAR.items():
        if pid in by:
            set_first(pid, "", "cleared: " + why)

    # D3 numbering per original, by priority date, over every D3 of that original (not only the ones on the page)
    d3_of = {}
    for pid, (o, t) in link.items():
        if t == "3":
            d3_of.setdefault(original(pid), []).append(pid)
    for orig, kids in d3_of.items():
        kids.sort(key=lambda p: (s(prio.get(p, ""))[:10] or "9999", p))
        root = base(first_name(orig))
        for n, pid in enumerate(kids, 1):
            if pid not in by:
                if not root:
                    continue
                # a D3 that never had a name candidate has no row yet: add one so it carries the variant name
                r = {k: "" for k in header}
                r.update(patent_id=pid, decision="clear")
                rows.append(r)
                by[pid] = r
            cur = first_name(pid)
            if not root:
                if cur and link[pid][0] and (orig in CLEAR or re.sub(r"\s+v\d+$", "", cur) == s(by.get(orig, {}).get("name_final", "")).split(";")[0].strip()):
                    set_first(pid, "", f"D3 of {orig}, which has no real name")
                continue
            if by[pid]["decision"] == "clear" and len(s(by[pid]["name_final"]).split(";")) > 1:
                print(f"  ⚠ {pid}: multi-aircraft D3 of {orig} ({root}) with no named aircraft — left for review")
                continue
            if not first_name(pid):
                set_first(pid, f"{root} v{n}", f"D3 of {orig} ({root}), variant {n} by priority date")

    # ONE scheme (user 2026-09-15: "I either choose versions or concepts"): patents that share a real name without
    # any duplicate link (concept stages of the same aircraft) are numbered the same way. Within a name, the keeper of
    # the bare name is the member that is nobody's D3 with the earliest priority date; every other member gets vN in
    # priority order, D3s and unlinked alike, so one name never sits bare on two patents.
    groups = {}
    for pid, r in by.items():
        n = first_name(pid)
        if n and not (pid in link and link[pid][1] in ("1", "2")):   # a D1/D2 legitimately carries its original's name
            groups.setdefault(base(n).lower(), []).append(pid)
    for key, members in groups.items():
        if len(members) < 2:
            continue
        pr = lambda p: (s(prio.get(p, ""))[:10] or "9999", p)
        d3_members = {p for p in members if p in link and link[p][1] == "3" and original(p) in members}
        keepers = sorted([p for p in members if p not in d3_members], key=pr) or sorted(members, key=pr)
        keeper = keepers[0]
        root = base(first_name(keeper))
        if first_name(keeper) != root:
            set_first(keeper, root, "keeps the bare name (earliest, nobody's D3)")
        for n, pid in enumerate(sorted([p for p in members if p != keeper], key=pr), 1):
            if first_name(pid) != f"{root} v{n}":
                why = (f"D3 of {original(pid)}" if pid in d3_members else f"same name as {keeper}, no duplicate link") + f" → {root} v{n} by priority date"
                set_first(pid, f"{root} v{n}", why)

    # D1 / D2 records that appear in the file carry the original's name
    for pid, (o, t) in link.items():
        if t in ("1", "2") and pid in by:
            root = first_name(original(pid) if original(pid) != pid else o)
            if root and first_name(pid) != root:
                set_first(pid, root, f"D{t} of {o}: the same aircraft, carries its name")

    print(f"read {src} ({len(rows)} patents); {len(changes)} name(s) changed")
    for pid, old, new, why in changes:
        print(f"  {pid:17} {old or '(clear)':32} → {new or '(clear)':28} {why}")
    names = {}
    for r in rows:
        for p in s(r["name_final"]).split(";"):
            if p.strip() and r["decision"] != "clear":
                names.setdefault(p.strip().lower(), []).append(r["patent_id"])
    rep = {k: v for k, v in names.items() if len(v) > 1}
    print("names still on more than one patent:", rep or "none")
    if apply:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        if OUT.exists():
            bak = OUT.with_name(f"NAME_DECISIONS.PRE_DUPNAMES_{pd.Timestamp.now():%Y%m%d_%H%M%S}.csv")
            OUT.rename(bak)
            print("backup:", bak)
        with open(OUT, "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=header, quoting=csv.QUOTE_ALL)
            wr.writeheader()
            wr.writerows(rows)
        print("wrote", OUT)
    else:
        print("dry run — re-run with --apply")


if __name__ == "__main__":
    main()
