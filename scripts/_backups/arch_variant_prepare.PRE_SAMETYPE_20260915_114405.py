#!/usr/bin/env python3
"""Inputs for the per-aircraft text reading of architecture (plan step C).

Only patents whose approved primary aircraft carry DIFFERENT image topTypes need a citation per aircraft;
everywhere else the patent-level citation of the G5 reading covers every aircraft.

For each such patent and each aircraft (_archN):
  - the approved figures assigned to it, with the figure number: the OCR-read printed "FIG. N" where the
    2026-09-09 audit found the stored key wrong or unreadable, the stored key otherwise
  - every sentence of the full Description that cites one of those figure numbers
  - the audit's verdict and note for the patent (MIXED / BROKEN / SUSPECT patents name misfiled figures)

Output: 1639_LABELLED/text_architecture/variant_reading/inputs_multitype.txt (+ .json)
"""
import json
import re
from pathlib import Path
import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
AUDIT = ROOT / "_audit_multi_aircraft_20260909"
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
OUT = ROOT / "text_architecture" / "variant_reading"
MAX_SENT_PER_AIRCRAFT = 14


def fig_number(key) -> str | None:
    m = re.search(r"(?:^|_F)(\d+[A-Za-z]?)$", str(key))
    return m.group(1).upper() if m else None


ml = pd.read_excel(ROOT / "joined" / "master_labels.xlsx",
                   usecols=["patent_id", "variant", "variant_id", "topType", "is_primary", "is_approved"])
prim = ml[(ml.is_primary == True) & (ml.is_approved == True)]
multi = prim.groupby("patent_id").topType.nunique()
pids = sorted(multi[multi > 1].index)
print("patents with different types:", len(pids))

mf = pd.read_excel(ROOT / "joined" / "master_figures.xlsx")
mf = mf[mf.patent_id.isin(pids) & (mf.status == "approved")]
ocr = pd.read_csv(AUDIT / "figkey_ocr_all.csv")
ocr = ocr.set_index(["patent_id", "image_file"])
audit = pd.read_csv(AUDIT / "arch_audit_findings.csv").set_index("patent_id")

head = pd.read_excel(PATSEER, nrows=0).columns
desc_col = next(c for c in head if str(c).strip().lower() == "description")
dod_col = next((c for c in head if "drawing" in str(c).lower()), None)
cols = ["Record Number", desc_col] + ([dod_col] if dod_col else [])
ps = pd.read_excel(PATSEER, dtype=str, usecols=cols).set_index("Record Number")


def sentences(text: str) -> list[str]:
    text = " ".join(str(text).split())
    return [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-Z\[])", text) if x.strip()]


def cites(sent: str, nums: set[str]) -> bool:
    for m in re.finditer(r"\bFIG(?:URE)?S?\.?\s*((?:\d+[A-Z]?(?:\s*(?:,|and|to|through|-|–)\s*)?)+)", sent, re.I):
        found = set(re.findall(r"\d+[A-Z]?", m.group(1).upper()))
        base = {re.sub(r"[A-Z]$", "", f) for f in found}
        if nums & found or {re.sub(r"[A-Z]$", "", n) for n in nums} & base:
            return True
    return False


items, blocks = [], []
for pid in pids:
    desc = ps.at[pid, desc_col] if pid in ps.index else ""
    sents = sentences(desc) if isinstance(desc, str) else []
    dod = ps.at[pid, dod_col] if dod_col and pid in ps.index and isinstance(ps.at[pid, dod_col], str) else ""
    v = prim[prim.patent_id == pid].sort_values("variant")
    au = audit.loc[pid] if pid in audit.index else None
    rec = {"pid": pid, "audit_verdict": "" if au is None else str(au.verdict),
           "audit_note": "" if au is None else " | ".join(str(au[c]) for c in ["arch_issue", "fig_key_issue", "note"] if pd.notna(au[c])),
           "drawings": " ".join(str(dod).split())[:2500], "aircraft": []}
    for r in v.itertuples():
        figs = mf[(mf.patent_id == pid) & (mf.arch == r.variant)]
        nums = set()
        for f in figs.itertuples():
            # trust order: the printed "FIG. N" read by OCR > the _F<N> token in the crop file name
            # (the crop naming convention) > the stored key, which is a sequential integer on some records
            n = None
            if (pid, f.image_file) in ocr.index:
                o = ocr.loc[(pid, f.image_file)]
                o = o.iloc[0] if isinstance(o, pd.DataFrame) else o
                if pd.notna(o.ocr_best):
                    n = str(o.ocr_best).upper()
            if n is None:
                m = re.search(r"_F(\d+[A-Za-z]?)(?:\.png)+$", str(f.image_file))
                n = m.group(1).upper() if m else fig_number(f.fig_key)
            if n:
                nums.add(n)
        hits = [s for s in sents if cites(s, nums)][:MAX_SENT_PER_AIRCRAFT]
        rec["aircraft"].append({"variant_id": r.variant_id, "image_type": r.topType, "figs": sorted(nums),
                                "sentences": hits})
    items.append(rec)
    lines = [f"### {pid}   (audit: {rec['audit_verdict'] or '—'})"]
    if rec["audit_note"]:
        lines.append(f"AUDIT: {rec['audit_note']}")
    lines.append(f"DRAWINGS: {rec['drawings']}")
    for a in rec["aircraft"]:
        lines.append(f"-- {a['variant_id']}  image={a['image_type']}  FIGs={', '.join(a['figs']) or '?'}")
        lines += [f"   • {s[:600]}" for s in a["sentences"]] or ["   (no Description sentence cites these figures)"]
    blocks.append("\n".join(lines))

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "inputs_multitype.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
(OUT / "inputs_multitype.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
n_air = sum(len(i["aircraft"]) for i in items)
n_empty = sum(1 for i in items for a in i["aircraft"] if not a["sentences"])
print(f"{len(items)} patents, {n_air} aircraft, {n_empty} aircraft with no citing sentence → {OUT}")
