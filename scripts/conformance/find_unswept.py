#!/usr/bin/env python3
"""Which records should carry a field that was added AFTER they were labelled?

The recurring problem: a new option or checkbox is a POSITIVE MARKER — blank is
legal, so nothing flags its absence. `wingN_plan='Trap'` looked like it did not
exist outside Batch_04; in fact only Batch_04 had been asked the question. The
same now applies to `boomN_retracts`, `ctrlOnly`, `ElectricSimilar` and the
widened `chord='None'`.

You cannot re-read 1,600 patents. This narrows each field to the records that
carry EVIDENCE for it, so the re-read is tens of patents, not thousands. Every
rule is deliberately over-inclusive: it produces candidates to look at, never
edits. A candidate is not a finding — the drawing decides.

    python scripts/conformance/find_unswept.py                 # all batches
    python scripts/conformance/find_unswept.py --batches Batch_02 --field retracts
"""
from __future__ import annotations
import argparse, re, collections
from pathlib import Path
import pandas as pd

DATA = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & "
            "Labelling Outputs/1639_DS/data/03c_CORRECTED_wizard_exports")
BATCHES = ["Batch_01", "Batch_02", "Batch_03", "Batch_04", "Batch_05"]

COAX = re.compile(r"coax|contra[- ]?rotat|counter[- ]?rotat|stacked rotor|"
                  r"upper and lower rotor|双旋翼|共轴", re.I)
RETRACT = re.compile(r"\bretract|\bstow|\bfold(s|ed|ing)?\b|\bswing(s|ing)? (in|up|back)|"
                     r"\bwithdraw|telescop", re.I)
CTRL = re.compile(r"\bstabilit(y|ies)\b|\bstabilis|\bstabiliz|\banti[- ]?torque|"
                  r"\byaw control|\bpitch control|\btail rotor\b|\bsmall (rear|aft|tail)", re.I)
ELECTRIC = re.compile(r"\belectric|\bbattery|\bmotor[- ]?driven|\bBLDC\b", re.I)


def load(batch: str):
    d = pd.read_excel(DATA / f"reviewed_patents_{batch}.xlsx", sheet_name="Review")
    d["Field"] = d["Field"].astype(str)
    d["Patent_ID"] = d["Patent_ID"].astype(str)
    F = collections.defaultdict(dict)
    TXT = collections.defaultdict(list)
    for _, r in d.iterrows():
        v = r["Value"]
        if not str(r["Sub_Dimension"]).startswith("Image: "):
            F[r["Patent_ID"]][r["Field"]] = v
        if v is not None and str(v) != "nan":
            TXT[r["Patent_ID"]].append(str(v))
    return d, F, TXT


def ident(v):
    s = str(v).strip()
    return s.split("—")[0].strip() if "—" in s else s


def base(p):
    return re.sub(r"_arch\d+$", "", p)


def f_chord_none(d, F, TXT):
    """chord='None' now also means 'cannot tell'. Candidates: a coaxial/contra-
    rotating mention in the text while some card still answers Front or Back."""
    out = []
    for p, f in F.items():
        blob = " ".join(TXT.get(p, [])) + " " + " ".join(TXT.get(base(p), []))
        rc = ident(f.get("topType", "")) == "RC"
        if not (COAX.search(blob) or rc):
            continue
        picked = [k for k, v in f.items()
                  if k.endswith("_chord") and ident(v) in ("Front", "Back")]
        if picked:
            out.append((p, f"{'RC hub' if rc else 'text says coaxial'}; "
                           f"still Front/Back on: {', '.join(sorted(picked)[:4])}"))
    return out


def f_retracts(d, F, TXT):
    """boomN_retracts (v15.6). Candidates: a boom group exists, retracts is not
    ticked, and either a propulsor on it is Retracting/Stowing or the text says so."""
    out = []
    for p, f in F.items():
        groups = {m.group(1) for k in f if (m := re.match(r"^boom(\d+)_attach$", k))}
        if not groups:
            continue
        blob = " ".join(TXT.get(p, [])) + " " + " ".join(TXT.get(base(p), []))
        rmech = [k for k, v in f.items()
                 if "_rmech" in k and ident(v) in ("Retracting", "Stowing", "Stow")]
        if not (rmech or RETRACT.search(blob)):
            continue
        for g in sorted(groups):
            if str(f.get(f"boom{g}_retracts")) not in ("True", "1"):
                why = f"propulsor {rmech[0]} is retracting" if rmech else "text mentions retract/stow/fold"
                out.append((p, f"boom group {g}: {why}"))
    return out


def f_ctrlonly(d, F, TXT):
    """'Control / stability only' (#12, 2026-09-05). Candidates: a convertible
    architecture with a small non-tilting propulsor group that the TR/CVT test
    would otherwise count as a thrust source."""
    out = []
    for p, f in F.items():
        tt = ident(f.get("topType", ""))
        if tt not in ("TW", "TR", "TB", "CVT"):
            continue
        if any(str(v) in ("True", "1") for k, v in f.items() if k.endswith("_ctrlOnly")):
            continue
        blob = " ".join(TXT.get(p, [])) + " " + " ".join(TXT.get(base(p), []))
        stations = [k.replace("_propKin", "") for k, v in f.items()
                    if k.endswith("_propKin") and ident(v) == "Fixed"
                    and (k.startswith("emp") or k.startswith("fuselage"))]
        if stations and (CTRL.search(blob) or tt in ("TW", "TR")):
            out.append((p, f"{tt} with fixed thrust on {', '.join(sorted(set(stations))[:3])}"
                           f"{' + text mentions stability/anti-torque' if CTRL.search(blob) else ''}"))
    return out


def f_electric(d, F, TXT):
    """edgeTags 'ElectricSimilar' (G1; legacy exports: META/t1EdgeTags).
    Candidates: the text is explicitly electric and no edge tag records it."""
    out = []
    for p, f in F.items():
        if "Electric" in str(f.get("edgeTags", "")) + str(f.get("t1EdgeTags", "")):
            continue
        blob = " ".join(TXT.get(p, []))
        if ELECTRIC.search(blob):
            out.append((p, "text is explicitly electric/battery-driven"))
    return out


FIELDS = {"chord": ("chord='None' — coaxial or cannot tell", f_chord_none),
          "retracts": ("boomN_retracts — the boom stows/folds", f_retracts),
          "ctrlonly": ("ctrlOnly — control/stability-only propulsor", f_ctrlonly),
          "electric": ("edgeTags ElectricSimilar", f_electric)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", nargs="+", default=BATCHES)
    ap.add_argument("--field", nargs="+", default=list(FIELDS), choices=list(FIELDS))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    rows = []
    for b in a.batches:
        d, F, TXT = load(b)
        print(f"\n{'='*74}\n  {b}\n{'='*74}")
        for key in a.field:
            label, fn = FIELDS[key]
            hits = fn(d, F, TXT)
            seen, uniq = set(), []
            for p, why in hits:
                if p not in seen:
                    seen.add(p); uniq.append((p, why))
            print(f"\n  {label}  —  {len(uniq)} candidate patent(s)")
            for i, (p, why) in enumerate(uniq):
                # the CSV gets every candidate; only the console is truncated
                rows.append({"batch": b, "field": key, "patent": p, "evidence": why})
                if i < 40:
                    print(f"     {p:<24} {why}")
            if len(uniq) > 40:
                print(f"     … and {len(uniq)-40} more (all of them are in --out)")
    if a.out and rows:
        pd.DataFrame(rows).to_csv(a.out, index=False)
        print(f"\n  worklist -> {a.out}  ({len(rows)} rows)")
