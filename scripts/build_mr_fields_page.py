#!/usr/bin/env python3
"""build_mr_fields_page.py — review page for the multirotor propulsion fields that were never recorded.
    python scripts/build_mr_fields_page.py
Why (audit_8, 2026-09-19): wizard v13–v15.2 drew every card of an RC/MR aircraft with only count + enclosure + zone,
so MR type blocks labelled before 2026-08-09 never got Tractor/Pusher Arrangement (chord), Thrust Kinematics (orient)
or Retraction Kinematics (rmech); and while MR was locked to Fixed the per-type export wrote propKin empty. No snapshot
holds a human value for any of them (354 snapshots searched), so they need a pick. m3Ready() now demands them (v15.15).
Reads notebook 04's aircraft/figure tables and the wizard's option names. One card per MR aircraft with a blank:
its morphology, every propulsion group (blanks as buttons), all its figures.
Export: MR_FIELDS_DECISIONS.csv -> 0_labelling/inputs/review_decisions/; scripts/apply_mr_fields.py writes it.
"""
import json, subprocess, tempfile
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
L0 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
TABLES = L0 / "outputs" / "tables"
HTML = REPO / "notebooks" / "UI_for_taxonomy_caracterization_15_4.html"
OUT = REPO / "notebooks" / "post-process" / "mr_fields_review.html"
FIELDS = ["orient", "chord", "rmech", "propKin"]            # the four a multirotor type block can lack
STATIONS = [("fuselage", "Fuselage body"), ("boom", "Booms"), ("emp", "Empennage"), ("hull_array", "Hull array"), ("core_layout", "Hub array")]

tmp = Path(tempfile.mkstemp(suffix=".json")[1])
subprocess.run(["node", str(REPO / "scripts" / "conformance" / "extract_html_schema.js"), str(HTML), str(tmp)], check=True, capture_output=True)
LAB = json.loads(tmp.read_text())["labels"]
OPTS = {"orient": [["Vertical", "Vertical (hover / lift)"], ["Horizontal", "Horizontal (cruise)"], ["Mixed", "Mixed (vectoring / tilting)"]],
        "chord": [[k, LAB["CHORD"][k]] for k in ("Front", "Back", "None")],
        "rmech": [[k, LAB["RETRACT_MECH"][k]] for k in ("Exposed", "BladeFold", "Retracting")],
        "propKin": [[k, LAB["PROP_KIN"][k]] for k in ("Fixed", "Tilt", "Other")]}
FNAME = {"orient": "Thrust kinematics (direction)", "chord": "Tractor / pusher arrangement", "rmech": "Retraction kinematics", "propKin": "Articulation (does the unit tilt on its mount?)"}
ZONE = {**LAB.get("M3_ZONE", {}), **LAB.get("M3_ZONE_EMP", {})}
TOPNAME = LAB["TOP"]

A = pd.read_csv(TABLES / "aircraft_table.csv", dtype=str, keep_default_na=False, low_memory=False)
F = pd.read_csv(TABLES / "figure_table.csv", dtype=str, keep_default_na=False, low_memory=False)
IMG_ROOT = L0 / "inputs" / "images"
_idx = {}
for q in IMG_ROOT.rglob("*.png"): _idx.setdefault((q.parent.name.split("_")[0], q.name), str(q))
def src(pid, path, fname):
    p = (path or "").replace("file://", "")
    if p and pid in p and Path(p).exists(): return "file://" + p
    q = _idx.get((pid, fname)); return ("file://" + q) if q else ""
def rot(v):
    try: return int(float(v))
    except Exception: return 0
def figures(pid):
    return [dict(file=x.image_file, src=src(pid, x.image_path, x.image_file), rot=rot(x.rotation_deg), ua=int(x.ua or 1),
                 status=x.status, main=(x.is_main == "True"), per=x.per, state=x.acState) for x in F[F.patent_id == pid].itertuples()]

def groups(r):
    """Every counted propulsion group of the aircraft: key prefix, label, count, the four fields, context."""
    out = []
    for st, lab in STATIONS:
        if r.get(f"{st}_quickOverride") == "True": continue
        nt = r.get(f"{st}_ntypes", ""); multi = nt not in ("", "True", "1", "False", "0")
        pres = [(f"{st}_t{t}", f"{lab}, type {t}") for t in range(1, 8) if r.get(f"{st}_t{t}_count", "") not in ("", "0", "False")] if multi else [(st, lab)]
        for p, pl in pres:
            c = r.get(p + "_count", "")
            if c in ("", "0", "False"): continue
            out.append(dict(key=p, label=pl, count=("1" if c == "True" else c), vals={f: r.get(f"{p}_{f}", "") for f in FIELDS},
                            bmech=LAB["BLADE_MECH"].get(r.get(p + "_bmech", ""), r.get(p + "_bmech", "")),
                            zone=", ".join(ZONE.get(z, z) for z in r.get(p + "_zone", "").split("|") if z) or r.get(f"{st}_zone", ""),
                            ctrl=r.get(p + "_ctrlOnly") == "True", notes=r.get(f"{st}_notes", "")))
    return out

cards = []
for _, r in A[A.topType == "MR"].iterrows():
    gs = groups(r)
    if not any(v == "" for g in gs for v in g["vals"].values()): continue
    booms = "; ".join(f"group {i}: {r.get(f'boom{i}_count') or '?'} × to {r.get(f'boom{i}_attach') or '?'}"
                      + (", TILTS" if r.get(f"boom{i}_tilts") == "True" else "") for i in range(1, 7) if r.get(f"boom{i}_count") or r.get(f"boom{i}_attach"))
    cards.append(dict(key=r.aircraft_id, pid=r.patent_id, ua=int(r.ua or 1), n_ua=int(r.n_variants) if str(r.n_variants).isdigit() else 1,
                      type=r.topType, typeName=TOPNAME.get(r.topType, ""), name=r.aircraft_name, company=r.company, title=r.title, pdf=r.pdf_link,
                      morph=[["body motion", LAB["FUS_KIN"].get(r.fusKin, r.fusKin) or "—"], ["booms", booms or "none"]],
                      groups=gs, figs=figures(r.patent_id)))
cards.sort(key=lambda c: (c["company"], c["pid"], c["ua"]))
data = json.dumps(dict(cards=cards, opts=OPTS, fname=FNAME, fields=FIELDS), ensure_ascii=False, default=str)
OUT.write_text((REPO / "scripts" / "mr_fields_template.html").read_text(encoding="utf-8").replace("__DATA__", data), encoding="utf-8")
n = sum(1 for c in cards for g in c["groups"] for v in g["vals"].values() if v == "")
print(f"wrote {OUT}: {len(cards)} aircraft, {len({c['pid'] for c in cards})} patents, {n} blank values")
