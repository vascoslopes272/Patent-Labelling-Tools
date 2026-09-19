#!/usr/bin/env python3
"""build_wing_boom_review_page.py — review page for aircraft whose wing rotors may be recorded on the wrong card
(wing card vs a boom attached to the wing). Candidates: notebook 04's wing_boom_candidate (rule accepted 2026-09-19).
    python scripts/build_wing_boom_review_page.py
Rule (codebook M1, boom definition): a member on a wing that carries a propulsor is a BOOM when it carries propulsors both
ahead of and behind the wing, reaches beyond the leading or trailing edge by more than the local wing chord, or carries a
tail surface. Otherwise it is a NACELLE or PYLON and the propulsor goes on the wing card (LE, TE, Above, Below). The
analysis pools both as wing-borne thrust, so this review only makes the detail tables consistent.
Export: WING_BOOM_DECISIONS.csv -> 0_labelling/inputs/review_decisions/. A "move" answer becomes a wizard-list row (the
move is done in the wizard: counts, zones and types change together). Nothing is written to the record here.
"""
import json
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
L0 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
TABLES = L0 / "outputs" / "tables"
OUT = REPO / "notebooks" / "post-process" / "wing_boom_review.html"
A = pd.read_csv(TABLES / "aircraft_table.csv", dtype=str, keep_default_na=False, low_memory=False)
F = pd.read_csv(TABLES / "figure_table.csv", dtype=str, keep_default_na=False, low_memory=False)
def g(r, c): v = r.get(c, ""); return "" if v in ("nan", "None") else v
def rot(v):
    try: return int(float(v))
    except Exception: return 0
def src(r):
    p = L0 / "outputs" / "images" / r.aircraft_id / r.image_file
    if p.exists(): return "file://" + str(p)
    q = (r.image_path or "").replace("file://", "")
    return ("file://" + q) if q and Path(q).exists() else ""

def recorded(r):
    """What the record says about the wing-borne rotors, in plain words."""
    lines = []
    for w in (1, 2, 3):
        if not (g(r, f"wing{w}_role") or g(r, f"wing{w}_tilt")): continue
        head = f"wing {w}: {g(r, f'wing{w}_role') or '?'}, tilt {g(r, f'wing{w}_tilt') or '?'}"
        nt = g(r, f"wing{w}_ntypes"); multi = nt not in ("", "True", "1", "False", "0")
        parts = []
        for p in ([f"wing{w}_t{t}" for t in range(1, 5) if g(r, f"wing{w}_t{t}_count") not in ("", "0", "False")] if multi else [f"wing{w}"]):
            c = g(r, p + "_count"); c = "1" if c == "True" else c
            if c in ("", "0", "False"): continue
            parts.append(f"{c} rotor(s) at {g(r, p + '_zoneChord') or '?'} / {g(r, p + '_zoneSpan') or '?'}, {g(r, p + '_orient') or '?'}, articulation {g(r, p + '_propKin') or '?'}")
        lines.append(head + (" — on the wing card: " + "; ".join(parts) if parts else " — no rotors on the wing card"))
    for i in range(1, 7):
        if not (g(r, f"boom{i}_attach") or g(r, f"boom{i}_count")): continue
        lines.append(f"boom group {i}: {g(r, f'boom{i}_count') or '?'} × attached to {g(r, f'boom{i}_attach') or '?'}"
                     + (f", {g(r, f'boom{i}_wingRel')} of the wing" if g(r, f"boom{i}_wingRel") else "")
                     + (f", span {g(r, f'boom{i}_span')}" if g(r, f"boom{i}_span") else "") + (f", {g(r, f'boom{i}_orient')}" if g(r, f"boom{i}_orient") else "")
                     + (", CARRIES ROTORS" if g(r, f"boom{i}_hasProps") == "True" else ", no rotors") + (", tilts" if g(r, f"boom{i}_tilts") == "True" else ""))
    bc = g(r, "boom_count")
    if bc not in ("", "0", "False"): lines.append(f"boom card: {bc} rotor(s)")
    return lines

cards = []
for _, r in A[(A.wing_boom_candidate == "True")].iterrows():
    f = F[F.patent_id == r.patent_id]
    figs = [dict(file=x.image_file, src=src(x), rot=rot(x.rotation_deg), ua=int(x.ua or 1), status=x.status, main=x.is_main == "True", per=x.per)
            for x in f.itertuples()]
    cards.append(dict(key=r.aircraft_id, pid=r.patent_id, ua=int(r.ua or 1), n_ua=int(r.n_variants) if str(r.n_variants).isdigit() else 1,
                      type=r.topType, name=r.aircraft_name, company=r.company, pdf=r.pdf_link, carrier=g(r, "wing_thrust_carrier"),
                      lines=recorded(r), figs=figs))
cards.sort(key=lambda c: (c["carrier"], c["company"], c["pid"], c["ua"]))
PAGE = (REPO / "scripts" / "wing_boom_review_template.html").read_text(encoding="utf-8")
OUT.write_text(PAGE.replace("__DATA__", json.dumps(dict(cards=cards), ensure_ascii=False)), encoding="utf-8")
print(f"wrote {OUT}: {len(cards)} aircraft; carriers {pd.Series([c['carrier'] for c in cards]).value_counts().to_dict()}; "
      f"figures without image {sum(1 for c in cards for x in c['figs'] if not x['src'])}")
