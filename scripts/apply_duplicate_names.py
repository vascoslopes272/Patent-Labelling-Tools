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

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling/inputs")   # 2026-09-17: stage-0 INPUTS of the 1639_LABELLED tree
OUT = ROOT.parent / "outputs"                                                                                   # what notebook 04 writes
WIZARD_ALL = ROOT / "record" / "reviewed_patents_Batch_ALL.xlsx"
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
OUT = ROOT / "review_decisions" / "NAME_DECISIONS.csv"

# which record carries the PLAIN name when the links would put it elsewhere (user rulings 2026-09-16)
PLAIN = {
    "honda evtol": "US2024190562A1",            # "the original one shall be US2024190562A1"
    "porsche-boeing concept": "DE102023108565B3",
}

# user rulings 2026-09-15 (name sweep): shared a real name with another patent but are a different, unlinked aircraft
# (US2024059393A1 was here until 2026-09-16: "all the duplicates and originals need to be named")
CLEAR = {
    "EP3636545A1": "APT belongs to US11319064B1; this patent is not linked to it",
    "US2025242909A1": "H1 belongs to US2022081107A1; different aircraft (77% labels, other family)",
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

    # ── one aircraft = one cluster of D1/D2 links ("the same aircraft"); a D3 is a different aircraft, so a different
    # cluster. Each cluster carries one name: the one the reviewer typed on any of its members. When several clusters
    # carry the same name (a D3 version, or two unlinked patents of the same aircraft family), the reviewer's cluster
    # keeps the bare name and the others get vN by priority date — "if they are the same names they shall have vN"
    # (user 2026-09-16). Nothing is written onto a record in CLEAR.
    pr = lambda p: (s(prio.get(p, ""))[:10] or "9999", p)
    nb = {}
    for pid, (o, t) in link.items():
        nb.setdefault(pid, []).append((o, t))
        nb.setdefault(o, []).append((pid, t))

    # name overrides (review_decisions/name_overrides.csv): a duplicate the reviewer knows is a different named aircraft
    # while the wizard link stays (e.g. the Midnight patents filed as D2 of the Maker). They leave their cluster.
    ov_path = OUT.parent / "name_overrides.csv"
    overrides = {r["patent_id"]: r["name"] for r in csv.DictReader(open(ov_path, encoding="utf-8"))} if ov_path.exists() else {}
    for pid, nm in overrides.items():
        if pid not in by:
            rr = {k: "" for k in header}
            rr["patent_id"] = pid
            rows.append(rr)
            by[pid] = rr
        if first_name(pid) != nm:
            set_first(pid, nm, "name override (review_decisions/name_overrides.csv)")
        by[pid]["decision"] = "known"

    pool = (set(by) | set(link) | {o for o, _ in link.values()}) - set(overrides)
    cid, cluster_of, clusters = 0, {}, {}
    for pid in sorted(pool, key=pr):
        if pid in cluster_of:
            continue
        cid += 1
        stack, members = [pid], set()
        while stack:                                   # same aircraft = reachable through D1/D2 links only
            m = stack.pop()
            if m in members:
                continue
            members.add(m)
            cluster_of[m] = cid
            for o, t in nb.get(m, []):
                if t in ("1", "2") and o not in members and o not in overrides:
                    stack.append(o)
        clusters[cid] = members

    anchors = {}                                        # cluster -> (priority key, name the reviewer typed)
    # the most recently decided record wins inside a cluster: a later sweep may rename the aircraft (CX300 → Alia-250)
    for pid in sorted(pool, key=lambda p: (s(by.get(p, {}).get("decided_at", "")), pr(p)), reverse=True):
        nm = first_name(pid)
        if nm and pid not in CLEAR:
            anchors.setdefault(cluster_of[pid], (pr(pid), nm))   # first in this (newest-first) order wins
    names = {c: v[1] for c, v in anchors.items()}

    for _ in range(3):                                  # a D3 of a named aircraft is a version of it
        for pid, (o, t) in link.items():
            if t != "3":
                continue
            a_, b_ = cluster_of.get(pid), cluster_of.get(o)
            if a_ and b_ and (a_ in names) != (b_ in names):
                src_, dst_ = (a_, b_) if a_ in names else (b_, a_)
                if all(m not in CLEAR for m in clusters[dst_]):
                    names[dst_] = base(names[src_])

    groups_by_name = {}
    for c, nm in names.items():
        groups_by_name.setdefault(base(nm).lower(), []).append(c)
    final = {}
    for key, cs in groups_by_name.items():
        bn = base(names[cs[0]])
        # the bare name goes to the aircraft the others derive from: not a D3 of anything, reviewer-named, earliest
        is_d3 = lambda c: any(link.get(m, ("", ""))[1] == "3" for m in clusters[c])
        owner = PLAIN.get(key)
        keyfn = lambda c: (0 if owner and owner in clusters[c] else 1,
                           1 if is_d3(c) else 0,
                           0 if c in anchors and not re.search(r"\s+v\d+$", anchors[c][1]) else 1,
                           anchors[c][0] if c in anchors else min(pr(m) for m in clusters[c]))
        cs = sorted(cs, key=keyfn)
        for i, c in enumerate(cs):
            final[c] = bn if i == 0 else f"{bn} v{i}"
    # a patent that draws several aircraft: aircraft a takes its cluster's name, the other aircraft of the same family take
    # the next free version numbers (2026-09-16 — so no "vN" is ever on two different aircraft)
    top = {}
    for c, nm in final.items():
        mm = re.match(r"^(.*?)(?:\s+v(\d+))?$", nm)
        top[mm.group(1).lower()] = max(top.get(mm.group(1).lower(), 0), int(mm.group(2) or 0))
    for c, nm in sorted(final.items(), key=lambda kv: kv[1].lower()):
        for m in sorted(clusters[c], key=pr):
            r = by.get(m)
            if not r or r["decision"] == "clear" or ";" not in s(r["name_final"]):
                continue
            parts = [x.strip() for x in s(r["name_final"]).split(";")]
            fam_idx = [i for i, x in enumerate(parts) if base(x).lower() == base(nm).lower()]
            # the aircraft that keeps the cluster name: the one the reviewer left without a vN, else the first of the family
            keep = next((i for i in fam_idx if base(parts[i]) == parts[i]), fam_idx[0] if fam_idx else 0)
            want = list(parts)
            want[keep] = nm
            for i in fam_idx:
                if i != keep:
                    top[base(nm).lower()] += 1
                    want[i] = f"{base(nm)} v{top[base(nm).lower()]}"
            full = "; ".join(want)
            if full != r["name_final"]:
                changes.append((m, r["name_final"], full, "multi-aircraft patent: a = cluster name, others next free vN"))
                r["name_final"] = full

    for c, nm in final.items():
        for m in sorted(clusters[c], key=pr):
            if m in CLEAR or m not in prio.index:
                continue
            if m not in by:
                r = {k: "" for k in header}
                r.update(patent_id=m, decision="clear")
                rows.append(r)
                by[m] = r
            # a patent that draws several aircraft carries one name per aircraft: never rewrite it from a cluster name,
            # and give its duplicates the whole list (2026-09-16)
            multi = ";" in s(by[m]["name_final"])
            src_multi = next((x for x in clusters[c] if ";" in s(by.get(x, {}).get("name_final", ""))), None)
            if multi:
                continue
            # a duplicate of a multi-aircraft patent carries the cluster name (one name, the aircraft it copies)
            if first_name(m) != nm:
                t = link.get(m, ("", ""))[1]
                set_first(m, nm, (f"D{t} of {link[m][0]}" if t in ("1", "2") else "same aircraft") + f" → {nm}")

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
            bak = OUT.parent / "_backups" / "names" / f"NAME_DECISIONS.PRE_DUPNAMES_{pd.Timestamp.now():%Y%m%d_%H%M%S}.csv"
            bak.parent.mkdir(parents=True, exist_ok=True)
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
