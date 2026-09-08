#!/usr/bin/env python3
"""Tick "Laterally Symmetric Pairs" where an even count of 2 makes it tautological.

Default is a DRY RUN; pass --apply.

WHY this gap exists. Symmetry defaults to TICKED on the wing, boom, empennage and
hull cards, but to UNTICKED on Fuselage and Main Rotor Layout. So on those two the
question was never put in front of the annotator: 181 cards carry an even count
with the flag off, and almost all are `fuselage`.

WHAT THIS DOES. Only cards with EXACTLY 2 propulsors, where "a pair is a pair" is
not an inference worth calling one. Anything with 4 or more is LEFT ALONE and goes
to the review queue instead — a 14-propulsor fuselage array may be radial, stacked
or genuinely asymmetric, and a script cannot tell.

NOT TOUCHED: cards whose symmetry defaults to true and was actively UNTICKED (176
of them). That is a decision the annotator made and this script must not reverse.
"""
from __future__ import annotations
import argparse, re, shutil, collections
from datetime import datetime
from pathlib import Path
import pandas as pd

DATA = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & "
            "Labelling Outputs/1639_DS/data/03c_CORRECTED_wizard_exports")
BATCHES = ["Batch_01", "Batch_02", "Batch_03", "Batch_04", "Batch_05"]
DEFAULT_TRUE = {"wing1", "wing2", "wing3", "wing4", "emp", "hull_array", "boom"}


def cnt(v):
    s = str(v).strip().lower()
    if s == "true":  return 1.0
    if s in ("false", "nan", "none", ""): return 0.0
    try: return float(s)
    except ValueError: return 0.0


def tf(v): return str(v).strip().lower() == "true"


def run(batch: str, apply: bool):
    f = DATA / f"reviewed_patents_{batch}.xlsx"
    d = pd.read_excel(f, sheet_name="Review")
    d["Field"] = d["Field"].astype(str)

    counts = collections.defaultdict(float)
    for _, r in d[d["Field"].str.match(r"^[a-z_0-9]+?(_t\d+)?_count$")].iterrows():
        if r["Field"].startswith("boom"): continue
        m = re.match(r"^([a-z_0-9]+?)(_t\d+)?_count$", r["Field"])
        counts[(r["Patent_ID"], m.group(1) + (m.group(2) or ""))] += cnt(r["Value"])

    ticked = skipped = 0
    for i, r in d.iterrows():
        m = re.match(r"^([a-z_0-9]+?)(_t\d+)?_sym$", r["Field"])
        if not m or r["Field"].startswith("boom"): continue
        card = m.group(1) + (m.group(2) or "")
        fam = m.group(1)
        if fam in DEFAULT_TRUE: continue          # never reverse an active untick
        if tf(r["Value"]): continue
        c = int(counts.get((r["Patent_ID"], card), 0))
        if c == 2:
            d.at[i, "Value"] = True; ticked += 1
        elif c >= 4:
            skipped += 1                            # goes to the review queue
    if apply and ticked:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(f, f.with_suffix(f".PRE_SYMPAIR_{ts}.xlsx"))
        d.to_excel(f, sheet_name="Review", index=False)
    return ticked, skipped


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batches", nargs="+", default=BATCHES)
    a = ap.parse_args()
    print("APPLYING" if a.apply else "DRY RUN — nothing written (use --apply)")
    T = S = 0
    for b in a.batches:
        t, s = run(b, a.apply); T += t; S += s
        print(f"  {b}  ticked {t:>3} (count = 2) · left for review {s:>3} (count >= 4)")
    print(f"  {'TOTAL':<10} ticked {T:>3} · left for review {S:>3}")
