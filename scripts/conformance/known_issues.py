#!/usr/bin/env python3
"""Locate the KNOWN codebook problems in each batch, with per-patent worklists.

check_batches.py answers "does this export still match the wizard?". This one
answers "where do the problems we already know about actually live?" — one query
per open codebook issue, so each is a number and a patent list instead of a
memory. Add an issue by writing one function and appending it to ISSUES.

Usage:
    python scripts/conformance/known_issues.py
    python scripts/conformance/known_issues.py --out report/     # + CSV
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from check_batches import (DEFAULT_DIR, DEFAULT_BATCHES, load_batches, code)  # noqa: E402

W = None            # per-issue rows, filled by note()
def note(rows, issue, batch, pid, detail=""):
    rows.append(dict(issue=issue, batch=batch, patent=pid, detail=detail))


def fld(df, pat):
    return df[df.Field.astype(str).str.fullmatch(pat, na=False)]


def per_group(df, pat, grp=r"boom(\d+)_"):
    """Boom fields carry their group index in the name; split it out."""
    s = fld(df, pat).copy()
    s["_g"] = s.Field.astype(str).str.extract(grp)[0]
    return s


# ── one function per open issue ────────────────────────────────────────────
def i1_boom_long_convention(b, df, rows):
    """`Longitudinal` is airframe-referenced, so on a WING-attached boom it is
    either meaningless or answered inconsistently. Measure how each batch coped."""
    at = per_group(df, r"boom\d+_attach"); lo = per_group(df, r"boom\d+_long")
    m = at.merge(lo, on=["Patent_ID", "_g"], suffixes=("_a", "_l"))
    w = m[m._code_a.isin(["Wings", "Both"])]
    if w.empty:
        return "no wing-attached booms"
    na = (w._code_l == "NA").sum()
    for pid in w[w._code_l == "NA"].Patent_ID.unique():
        note(rows, "boom-long-NA-on-wing", b, pid)
    return (f"{len(w):>3} wing-attached groups; answered NA {na:>3} ({na/len(w)*100:.0f}%) "
            f"— B01 answers Fore/Aft here, B05 answers NA: same boom, different code")


def i2_multi_wing_booms(b, df, rows):
    """Which wing does the boom hang on? Only bites when the airframe has >=2
    wing panels AND a wing-attached boom. `Bridge` already covers the two-wing
    case, so the rest is the genuinely ambiguous set."""
    wc = fld(df, r"wCount").copy()
    def n(v):
        v = str(v)
        return 1 if v == "True" else (int(float(v)) if re.fullmatch(r"[\d.]+", v) else 0)
    multi = set(wc[wc.Value.map(n) >= 2].Patent_ID)
    at = per_group(df, r"boom\d+_attach")
    wr = per_group(df, r"boom\d+_wingRel")
    bridged = set(wr[wr._code == "Bridge"].Patent_ID)
    hits = at[at._code.isin(["Wings", "Both"]) & at.Patent_ID.isin(multi)]
    amb = sorted(set(hits.Patent_ID) - bridged)
    for pid in amb:
        note(rows, "multi-wing-boom-ambiguous", b, pid)
    return (f"{len(multi):>3} patents with >=2 wing panels; {hits.Patent_ID.nunique():>3} of them "
            f"carry wing-attached booms; {len(amb):>3} not yet resolved by Bridge")


def i3_straddle(b, df, rows):
    """`Straddle` may be one boom crossing the chord, or two groups mislabelled
    as one. Small enough to re-read by hand."""
    wr = per_group(df, r"boom\d+_wingRel")
    st = wr[wr._code == "Straddle"]
    for pid in st.Patent_ID.unique():
        note(rows, "straddle-review", b, pid)
    return f"{len(st):>3} of {len(wr):>3} wing-referenced groups: {sorted(st.Patent_ID.unique())}"


def i4_emp_tilt(b, df, rows):
    """Empennage articulation is being removed from the codebook — this is the
    full set of records that carry it, i.e. the whole cost of removing it."""
    t = fld(df, r"empTilts"); tt = t[t.Value.astype(str) == "True"]
    nt = fld(df, r"empTiltsNote")
    legacy = nt[nt.Value.astype(str).str.startswith("legacy:", na=False)]
    for pid in tt.Patent_ID.unique():
        note(rows, "emp-tilt-to-delete", b, pid)
    return (f"{len(tt):>3} of {len(t):>3} patents tick it ({len(legacy)} of those are auto-migrated "
            f"'legacy:' notes, not human answers): {sorted(tt.Patent_ID.unique())}")


def i5_line_drawing(b, df, rows):
    """'Simple Line Drawing' and 'Line Drawing' name the same thing; the option
    is retired in comment only, so it stays pickable."""
    s = fld(df, r"acSty")
    sld = s[s.Value.astype(str) == "Simple Line Drawing"]
    for pid in sld.Patent_ID.unique():
        note(rows, "simple-line-drawing", b, pid)
    ld = (s.Value.astype(str) == "Line Drawing").sum()
    return f"{len(sld):>3} figures vs {ld:>3} 'Line Drawing': {sorted(sld.Patent_ID.unique())}"


def i6_disapprove_granularity(b, df, rows):
    """'No Aircraft Image' was BROADENED in v15.4 to absorb three different
    judgements (nothing depicted / too few figures / illegible). Nothing in the
    export distinguishes them, so 'disapproved for want of a hover view' is
    unrecoverable — the note field is the only place it could hide."""
    r = fld(df, r"t1DisapproveReason")
    nai = r[r._code == "No Aircraft Image"]
    oth = fld(df, r"t1DisapproveReason_otherNote")
    for pid in nai.Patent_ID.unique():
        note(rows, "disapprove-collapsed-bucket", b, pid)
    return (f"{len(nai):>3} of {len(r):>3} disapprovals sit in the merged bucket; "
            f"{len(oth):>3} carry a free-text note that could disambiguate")


def i7_aircraft_name(b, df, rows):
    """Names are already derived from the assignee, but by hand — so the same
    company appears in two casings and collides."""
    an = fld(df, r"aircraftName")
    v = an.Value.astype(str).str.strip()
    v = v[v.ne("") & v.ne("nan")]
    g = {}
    for x in v:
        g.setdefault(x.upper(), set()).add(x)
    coll = {k: sorted(s) for k, s in g.items() if len(s) > 1}
    for k in coll:
        for pid in an[an.Value.astype(str).str.strip().str.upper() == k].Patent_ID.unique():
            note(rows, "aircraftname-case-collision", b, pid, detail=str(coll[k]))
    pid_n = df.Patent_ID.nunique()
    return (f"{len(v):>3}/{pid_n:>3} patents named ({len(v)/pid_n*100:.0f}%); "
            f"{v.nunique():>3} distinct; {len(coll):>3} are the same name in two casings")


def i8_vertical_stabiliser(b, df, rows):
    """The 'a vertical stabiliser is always one' convention has NO field to live
    in — EMP_TYPE's VertFin explicitly says the count is not part of the test.
    So it cannot be audited from the exports; report the exposure instead."""
    e = fld(df, r"empType")
    vf = e[e._code.isin(["VertFin", "H-Tail", "Fins"])]
    return (f"{len(vf):>3} patents on a fin-count-sensitive empType "
            f"({dict(vf._code.value_counts())}) — no count is recorded anywhere, "
            f"so the convention is unverifiable from the export")


ISSUES = [
    ("1  boom Longitudinal is useless on wings", i1_boom_long_convention),
    ("2  booms on the same wing vs different wings", i2_multi_wing_booms),
    ("3  Straddle — split into two groups?", i3_straddle),
    ("4  empennage tilt — delete the dimension", i4_emp_tilt),
    ("5  Simple Line Drawing == Line Drawing", i5_line_drawing),
    ("6  disapprove reasons — 'no hover image' is unrecoverable", i6_disapprove_granularity),
    ("7  aircraft name from company name", i7_aircraft_name),
    ("8  vertical stabiliser count convention", i8_vertical_stabiliser),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--batches", nargs="+", default=DEFAULT_BATCHES)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    batches = load_batches(a.dir, a.batches)
    rows: list[dict] = []
    for title, fn in ISSUES:
        print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
        for b, df in batches.items():
            print(f"  {b}: {fn(b, df, rows)}")
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        p = a.out / "known_issues_worklist.csv"
        pd.DataFrame(rows).drop_duplicates().to_csv(p, index=False)
        print(f"\nper-patent worklist -> {p} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
