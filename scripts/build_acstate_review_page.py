#!/usr/bin/env python3
"""build_acstate_review_page.py — review page for the flight state of figures that may show TWO states.
    python scripts/build_acstate_review_page.py
Rule (user 2026-09-19, codebook R2-02 (e)): when a moving part is drawn in two positions, the state drawn in SOLID lines
is recorded and the dashed one is ignored; when both are drawn with the same weight, the figure is Both (new state,
2026-09-19); Other is only "no configuration can be read". Lift units
drawn beside cruise units do not make a two-state figure: the state is read from the parts that move. Invariant is never
used for a figure showing two positions.
Figures shown: every approved figure labelled Other (section 1, the 60 the user asked for; the lift+cruise ones labelled
Other "because both modes are represented" are explained), then an optional section: Invariant figures of convertible
types and figures with a state note. Current value preselected; one click to change.
Export: ACSTATE_DECISIONS.csv -> 0_labelling/inputs/review_decisions/; scripts/apply_acstate_decisions.py writes it.
"""
import json
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
L0 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
TABLES = L0 / "outputs" / "tables"
OUT = REPO / "notebooks" / "post-process" / "acstate_review.html"
CONVERTIBLE = {"TW", "TR", "CVT", "DS", "SRW"}
LIFT_CRUISE_NOTE = ("You labelled this Other because the lift rotors and the cruise propellers are both drawn. Under the new rule that alone "
                    "is not two states: read the parts that MOVE. If nothing on this aircraft moves between hover and cruise, it is "
                    "Invariant. If a part moves (e.g. a tilting wing section), pick the position that part is drawn in (solid lines), or Both if it is "
                    "drawn in both positions with the same weight.")

F = pd.read_csv(TABLES / "figure_table.csv", dtype=str, keep_default_na=False, low_memory=False)
A = pd.read_csv(TABLES / "aircraft_table.csv", dtype=str, keep_default_na=False, low_memory=False).set_index("aircraft_id")
F = F[F.status == "approved"].copy()
F["tt"] = F.aircraft_id.map(A.topType).fillna("")
def src(r):
    p = L0 / "outputs" / "images" / r.aircraft_id / r.image_file          # notebook 04's approved copy
    if p.exists(): return "file://" + str(p)
    q = (r.image_path or "").replace("file://", "")
    return ("file://" + q) if q and Path(q).exists() else ""
def rot(v):
    try: return int(float(v))
    except Exception: return 0
def item(r, section):
    lc = r.acState == "Other" and "both cruise and hover" in r.stateNote.lower()
    return dict(key=f"{r.aircraft_id}|{r.image_file}", aid=r.aircraft_id, pid=r.patent_id, file=r.image_file, src=src(r), rot=rot(r.rotation_deg),
                tt=r.tt, cur=("HoverCruise" if r.acState == "Invariant" else r.acState),
                main=r.is_main == "True", per=r.per, note=r.stateNote, section=section, explain=LIFT_CRUISE_NOTE if lc else "")
S1 = F[F.acState == "Other"].sort_values(["patent_id", "aircraft_id", "image_file"])
S2 = F[((F.acState == "Invariant") & F.tt.isin(CONVERTIBLE)) | ((F.stateNote != "") & (F.acState != "Other"))].sort_values(["patent_id", "aircraft_id"])
items = [item(r, 1) for r in S1.itertuples()] + [item(r, 2) for r in S2.itertuples()]
opts = [["Hover", "Hover (VTOL)"], ["Transition", "Transition"], ["Cruise", "Cruise / Forward"], ["HoverCruise", "Invariant"], ["Both", "Both (two positions drawn)"], ["Other", "Other"]]
data = json.dumps(dict(items=items, opts=opts), ensure_ascii=False)
OUT.write_text((REPO / "scripts" / "acstate_review_template.html").read_text(encoding="utf-8").replace("__DATA__", data), encoding="utf-8")
print(f"wrote {OUT}: section 1 (Other) {len(S1)}, section 2 (optional) {len(S2)}; no image: {sum(1 for i in items if not i['src'])}")
