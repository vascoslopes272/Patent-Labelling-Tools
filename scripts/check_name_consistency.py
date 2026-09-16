#!/usr/bin/env python3
"""Guard for the aircraft names: what is still missing a duplicate link, a name, or a vN tag.

Answers the question "how do I make sure no version is forgotten?" (2026-09-16). Five checks over
review_decisions/NAME_DECISIONS.csv + the live wizard record + the human architecture labels:

  A  a named aircraft has a near-twin (same company, labels >= THRESH) that carries NO name and NO duplicate link
     -> either the same aircraft (link it D1/D2 in the wizard) or a version (give it the name + vN)
  B  a D1/D2/D3 of a named original that does not carry the expected name (the vN rule missed it)
  C  the same base name on patents with no duplicate link between them (fine for concept stages, listed to be seen)
  D  gaps or repeats in the vN numbering of a name
  E  a named aircraft whose patent draws several aircraft and the other aircraft are unnamed (check they are different)

    python scripts/check_name_consistency.py            # report
    python scripts/check_name_consistency.py --csv      # + joined/name_consistency_<date>.csv
"""
import csv
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
DEC = ROOT / "review_decisions" / "NAME_DECISIONS.csv"
# pairs the reviewer has already looked at and ruled different — patent,other,verdict,decided
SEEN = ROOT / "review_decisions" / "name_pairs_checked.csv"
THRESH = 0.85          # D3 pairs sit at ~0.89 median, unrelated aircraft of the same type at ~0.40
LET = "abcdefghijklmnopqrstuvwxyz"


def main():
    dec = {r["patent_id"]: r for r in csv.DictReader(open(DEC, newline="", encoding="utf-8"))}
    idn = pd.read_excel(ROOT / "joined" / "aircraft_identity_ALL.xlsx", sheet_name="Identity").set_index("patent_id")
    ml = pd.read_excel(ROOT / "joined" / "master_labels.xlsx", keep_default_na=False, dtype=str)
    P = ml[(ml.is_primary == "True") & (ml.is_approved == "True")].copy()
    P["k"] = P.patent_id + "#" + P.variant
    R = P.set_index("k")
    bad = re.compile(r"^ml_|_conf$|[Nn]ote|Uncertain|otherTag|Oth$|^dinoUnderstanding|^uav_|electric|takeoff|identity_from|edgeTags")
    LAB = [c for c in ml.columns[list(ml.columns).index("topType"):] if not bad.search(c)]
    nvar = P.groupby("patent_id").size().to_dict()

    w = pd.read_excel(ROOT / "joined" / "wizard_all" / "reviewed_patents_Batch_ALL.xlsx", dtype=str,
                      keep_default_na=False, usecols=["Patent_ID", "Field", "Value"])
    w = w[w.Field.isin(["isDuplicate", "duplicateId", "duplicateType"])]
    w["pid"] = w.Patent_ID.str.replace(r"_arch\d+$", "", regex=True)
    f = w.groupby(["pid", "Field"]).Value.first().unstack().fillna("")
    link = {pid: (r.duplicateId.strip(), r.duplicateType.split(" — ")[0].strip())
            for pid, r in f.iterrows() if r.get("isDuplicate", "") in ("True", "true") and r.duplicateId.strip()}
    chain = defaultdict(set)
    for pid, (o, t) in link.items():
        chain[pid].add(o)
        chain[o].add(pid)

    def connected(a, b):
        seen, st = {a}, [a]
        while st:
            n = st.pop()
            if n == b:
                return True
            for m in chain[n]:
                if m not in seen:
                    seen.add(m)
                    st.append(m)
        return False

    def sim(a, b):
        if a not in R.index or b not in R.index:
            return None
        x, y = R.loc[a, LAB], R.loc[b, LAB]
        m = (x != "") | (y != "")
        return float((x[m] == y[m]).mean()) if m.sum() else None

    def names_of(pid):
        r = dec.get(pid)
        if not r or r["decision"] == "clear":
            return []
        parts = [p.strip() for p in r["name_final"].split(";")] if nvar.get(pid, 1) > 1 else [r["name_final"].strip()]
        return parts
    def name_at(pid, v):
        p = names_of(pid)
        n = p[v - 1] if v - 1 < len(p) else ""
        g = str(idn.at[pid, "aircraft_group_variants"]).split(";")
        gn = g[v - 1].strip() if nvar.get(pid, 1) > 1 and v - 1 < len(g) else str(idn.at[pid, "aircraft_group"])
        return "" if not n or n == gn else n

    ovp = ROOT / "review_decisions" / "name_overrides.csv"
    overrides = {r["patent_id"] for r in csv.DictReader(open(ovp, encoding="utf-8"))} if ovp.exists() else set()
    checked = set()
    if SEEN.exists():
        for r in csv.DictReader(open(SEEN, newline="", encoding="utf-8")):
            checked.add(frozenset((r["patent"], r["other"])))

    base = lambda n: re.sub(r"(\s+v\d+)+$", "", n).strip()
    named = {(pid, v): name_at(pid, v) for pid in dec for v in range(1, nvar.get(pid, 1) + 1) if name_at(pid, v)}
    out = []

    # A ── a named aircraft's near-twin that is neither named nor linked
    comp = idn.company_canonical.to_dict()
    for (pid, v), nm in sorted(named.items()):
        c = comp.get(pid)
        if not c or str(c) == "nan":
            continue
        for k in R.index:
            other, ov = k.split("#")[0], int(k.split("#")[1])
            if other == pid or comp.get(other) != c or (other, ov) in named:
                continue
            if str(c) in ("Unknown / Independent", "Individual Inventor", ""):   # not a real company match

                continue
            s = sim(f"{pid}#{v}", k)
            if s is not None and s >= THRESH and not connected(pid, other) and frozenset((pid, other)) not in checked:
                out.append(dict(check="A near-twin not named, not linked", name=nm, patent=pid,
                                aircraft=LET[v - 1] if nvar.get(pid, 1) > 1 else "",
                                other=other, other_aircraft=LET[ov - 1] if nvar.get(other, 1) > 1 else "",
                                labels_equal=round(s, 2),
                                todo=f"link {other} as a duplicate of {pid} in the wizard, or name it {base(nm)} vN"))

    # B ── duplicates of a named original that do not carry the expected name
    for pid, (o, t) in sorted(link.items()):
        if pid in overrides:
            continue
        root = o
        seen = {pid}
        while root in link and link[root][1] in ("1", "2") and root not in seen:
            seen.add(root)
            root = link[root][0]
        rn = name_at(root, 1)
        if not rn:
            continue
        has = name_at(pid, 1)
        want = base(rn) if t in ("1", "2") else f"{base(rn)} v?"
        # a duplicate of a versioned aircraft carries that version's name; of a multi-aircraft patent, any of its names
        root_names = {name_at(root, v) for v in range(1, nvar.get(root, 1) + 1)} - {""}
        if t in ("1", "2") and has not in (root_names or {rn}):
            out.append(dict(check=f"B D{t} of a named original without its name", name=rn, patent=pid,
                            aircraft="", other=root, other_aircraft="", labels_equal=sim(f"{pid}#1", f"{root}#1"),
                            todo=f"{pid} should carry {rn} (it is the same aircraft)"))
        if t == "3" and not has:
            out.append(dict(check="B D3 of a named original without a name", name=base(rn), patent=pid, aircraft="",
                            other=root, other_aircraft="", labels_equal=sim(f"{pid}#1", f"{root}#1"),
                            todo=f"{pid} should be {base(rn)} vN — re-run apply_duplicate_names.py"))

    # C / D ── one base name over several patents: links, numbering
    groups = defaultdict(list)
    for (pid, v), nm in named.items():
        groups[nm.lower()].append((pid, v, nm))   # the FULL name: versions are numbered, so only exact repeats matter
    for key, members in sorted(groups.items()):
        # D1/D2 records carry their original's name by rule — they are not a second aircraft with that name
        members = [m for m in members if not (m[0] in link and link[m[0]][1] in ("1", "2"))]
        if len(members) < 2:
            continue
        tags = sorted(int(re.search(r"v(\d+)$", nm).group(1)) for _, _, nm in members if re.search(r"v\d+$", nm))
        plain = [m for m in members if not re.search(r"v\d+$", m[2])]
        if len(plain) > 1 and not all(connected(a[0], b[0]) for a, b in combinations(plain, 2)):
            out.append(dict(check="D the bare name on two unlinked patents", name=members[0][2],
                            patent=plain[0][0], aircraft="", other=plain[1][0], other_aircraft="", labels_equal=None,
                            todo="only one aircraft keeps the bare name — re-run apply_duplicate_names.py"))
        if tags and tags != list(range(1, len(tags) + 1)):
            out.append(dict(check="D vN numbering has a gap or a repeat", name=base(members[0][2]), patent=members[0][0],
                            aircraft="", other="", other_aircraft="", labels_equal=None, todo=f"tags are {tags}"))
        for (a, av, an), (b, bv, bn) in combinations(members, 2):
            if not connected(a, b) and frozenset((a, b)) not in checked:
                out.append(dict(check="C the same full name on two unlinked aircraft", name=base(an), patent=a,
                                aircraft=LET[av - 1] if nvar.get(a, 1) > 1 else "", other=b,
                                other_aircraft=LET[bv - 1] if nvar.get(b, 1) > 1 else "",
                                labels_equal=None if sim(f"{a}#{av}", f"{b}#{bv}") is None else round(sim(f"{a}#{av}", f"{b}#{bv}"), 2),
                                todo="fine if they are different stages; link them in the wizard if they are one aircraft"))

    # E ── other aircraft of a multi-aircraft patent left unnamed
    for (pid, v), nm in sorted(named.items()):
        for ov in range(1, nvar.get(pid, 1) + 1):
            if ov != v and not name_at(pid, ov) and frozenset((f"{pid}#{v}", f"{pid}#{ov}")) not in checked:
                out.append(dict(check="E other aircraft of the same patent unnamed", name=nm, patent=pid,
                                aircraft=LET[v - 1], other=pid, other_aircraft=LET[ov - 1],
                                labels_equal=None if sim(f"{pid}#{v}", f"{pid}#{ov}") is None else round(sim(f"{pid}#{v}", f"{pid}#{ov}"), 2),
                                todo=f"check aircraft {LET[ov-1]}: another version ({base(nm)} vN) or a different aircraft"))

    df = pd.DataFrame(out)
    print(f"{len(named)} named aircraft · {len(df)} things to look at")
    for chk, g in df.groupby("check") if len(df) else []:
        print(f"\n{chk}  ({len(g)})")
        for r in g.itertuples():
            print(f"   {r.name:22} {r.patent:16}{' '+r.aircraft if r.aircraft else '  '} ↔ {r.other:16}{' '+r.other_aircraft if r.other_aircraft else '  '}"
                  f" {('' if r.labels_equal is None or pd.isna(r.labels_equal) else format(r.labels_equal, '.2f')):>5}  {r.todo}")
    if "--csv" in sys.argv and len(df):
        p = ROOT / "joined" / "names" / f"name_consistency_{pd.Timestamp.now():%Y%m%d}.csv"
        df.to_csv(p, index=False)
        print("\nwrote", p)


if __name__ == "__main__":
    main()
