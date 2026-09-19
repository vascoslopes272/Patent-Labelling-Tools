#!/usr/bin/env python3
"""build_contradiction_review_page.py — review page for aircraft whose own labels contradict the codebook definition of
their architecture (audit 2026-09-18, audit_6: rules no wizard lock or notebook-04 check enforces).
    python scripts/build_contradiction_review_page.py [violations_all.csv]
Reads the audit's violations (default: the copy in 0_labelling/audit_2026-09-18/audit_6_codebook_rules/), the record,
notebook 04's tables and the wizard's option names. Writes notebooks/post-process/contradiction_review.html (template
scripts/contradiction_review_template.html): one card per aircraft — every rule it breaks in plain words, a summary of
its morphology (type, body, wings, booms, every propulsion card: count / thrust direction / articulation / retraction),
all its figures, and the answers: label right (rule too strict — say why, the wizard / check changes), change the type,
change a part, (multirotors) rotors/booms tilt or whole-body pitch, not sure — each with a free-text box.
Export: CONTRADICTION_DECISIONS.csv into 0_labelling/inputs/review_decisions/. Nothing is written to the record here.
Patents on review_decisions/PENDING_WIZARD_REVIEW.csv are left out (the user fixes those in the wizard).
"""
import json, re, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
L0 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
VIOL = Path(sys.argv[1]) if len(sys.argv) > 1 else L0 / "audit_2026-09-18" / "audit_6_codebook_rules" / "violations_now.csv"
TABLES = L0 / "outputs" / "tables"
PENDING = L0 / "inputs" / "review_decisions" / "PENDING_WIZARD_REVIEW.csv"
HTML = REPO / "notebooks" / "UI_for_taxonomy_caracterization_15_4.html"
OUT = REPO / "notebooks" / "post-process" / "contradiction_review.html"

# rule -> (plain words: what the codebook says, suggested types, kind)
RULES = {
    "VECTORED_2_OF_3": ("RULE (user, 2026-09-18): CVT = at least TWO of these three on the same aircraft — a tilting rotor (on its own mount or on a tilting boom: on a boom the two are the same thing), a fixed rotor (thrust that does not tilt at all), a tilting wing (carrying its rotors, which are Fixed on their mounts). So a boom that tilts + another that stays fixed = CVT. Only tilting rotors = TR; only a tilting wing = TW. The record's type does not match what it holds.", [], "type"),
    "L4_CVT_NO_FIXED_THRUST(=TR/TW)": ("CVT (Combined) means a MIX: some thrust tilts and some stays fixed. Here every thrust source tilts — the codebook calls that TR (the propulsors tilt) or TW (the wing tilts and carries them).", ["TR", "TW"], "type"),
    "L4_CVT_NOTHING_TILTS": ("CVT needs at least one thrust source that tilts. Here nothing tilts (no tilting wing, boom or propulsor) — fixed lift + fixed cruise units is SLC.", ["SLC"], "type"),
    "R3-02_TR_HAS_FIXED_THRUST(=CVT)": ("TR (Tilt Rotor) means the propulsors tilt. Here some thrust tilts and some is fixed — the codebook calls that mix CVT.", ["CVT"], "type"),
    "TR_NOTHING_TILTS": ("TR, but the record shows nothing that tilts (no tilting propulsor, boom or wing).", ["SLC", "CVT", "PTC"], "type"),
    "L8_TR_WING_TILTS": ("TR keeps the wing fixed (only the propulsors tilt). Here a wing tilts — that is TW, or CVT if some thrust stays fixed.", ["TW", "CVT"], "type"),
    "L5_TW_THRUST_OFF_TILTING_WING": ("TW: all thrust tilts WITH the wing. Here some thrust sits off the tilting wing (fuselage / tail) and does not tilt — the codebook calls that CVT.", ["CVT"], "type"),
    "L1_SLC_SOMETHING_TILTS": ("SLC (Lift + Cruise): separate fixed lift units and fixed cruise units — nothing tilts. Here something tilts.", ["CVT", "TR"], "type"),
    "SLC_NOT_TWO_SETS": ("SLC needs two separate sets: lift units (thrust Vertical) AND cruise units (thrust Horizontal). The record does not show both.", ["MR", "PTC", "CVT"], "type"),
    "SRW_SOMETHING_TILTS": ("SRW (stopped/slowed rotor): the rotor stops or slows to become the wing — nothing tilts. Here something tilts.", ["CVT", "TR"], "type"),
    "L9_SRW_NO_LIFT_ROTOR": ("SRW needs a lift rotor that stops/slows for cruise. The record shows no vertical lift rotor.", ["SLC"], "type"),
    "PTC_HAS_CRUISE_PROPULSOR": ("PTC (pitch-to-cruise): the whole vehicle pitches forward; there is no separate cruise propulsor. Here a Horizontal (cruise) unit exists — that is SLC.", ["SLC"], "type"),
    "L6_TB_FUSKIN": ("TB (Tilt Body): body motion must be Tilting Body or Variable Incidence — it is empty.", [], "part"),
    "TAILSITTER_NOT_TB": ("Body motion 'Tilting Body' (the whole airframe reorients ~90°) is recorded, but the type is not TB.", ["TB"], "type"),
    # "MR_HAS_CRUISE_PROPULSOR" REMOVED (user 2026-09-18, CN111846213A): SLC needs wings — a wingless aircraft with a
    # horizontal (cruise) rotor is still a multirotor, so it is not a contradiction.
    "MR_BODY_NOT_PITCHING_AND_NOTHING_TILTS": ("A multirotor moves forward by pitching its WHOLE BODY, by TILTING its rotors/booms, or with a cruise (horizontal) rotor. Here body motion is not Whole-Body Pitch, nothing is marked as tilting and there is no cruise rotor. Which is it?", [], "mr"),
    # "RC_BOOM_TILTS" REMOVED (user 2026-09-18): forward-flight propellers on an RC may tilt — still a rotorcraft.
    "RC_MORE_THAN_TWO_LIFT_ROTORS": ("RC (Rotorcraft) = ONE main lift rotor, or a coaxial / tandem pair. Propellers for forward flight (fixed or tilting) are allowed and do not count. Here more than two rotors point straight up (lift) — that is MR.", ["MR"], "type"),
    "VARINC_NOTHING_REORIENTS": ("Variable Incidence = the airframe reorients while the cabin stays level on its own joint. Here nothing reorients (no tilting body, wing or booms).", [], "part"),
    "NO_THRUST_ON_APPROVED": ("An approved aircraft with 0 propulsors recorded on every card.", [], "part"),
    "M1_CARRYING_GROUP_WITHOUT_M3_BOOM_PROPS": ("M1 says a boom group carries propulsors, but the M3 boom card counts 0 propulsors.", [], "part"),
    "M3_BOOM_PROPS_WITHOUT_CARRYING_GROUP": ("The M3 boom card has propulsors, but no M1 boom group says it carries them.", [], "part"),
    # "VARIANTS_IDENTICAL" REMOVED (user 2026-09-19, WO2024252755A1: "label is right — both aircraft are very similar; in those
    # cases they are D3"): two aircraft of one patent with identical labels are different aircraft of the same configuration.
}
ORIENT = {"Vertical": "Vertical (lift)", "Horizontal": "Horizontal (cruise)", "Mixed": "Mixed (vectoring/tilting)"}

def sid(v): v = "" if v is None else str(v); return v.split(" — ", 1)[0].strip()
tmp = Path(tempfile.mkstemp(suffix=".json")[1])
subprocess.run(["node", str(REPO / "scripts" / "conformance" / "extract_html_schema.js"), str(HTML), str(tmp)], check=True, capture_output=True)
SCHEMA = json.loads(tmp.read_text()); LAB = SCHEMA["labels"]
def name(lst, v): return LAB.get(lst, {}).get(v, v) if v else ""
TOPNAME = LAB["TOP"]

V = pd.read_csv(VIOL, dtype=str, keep_default_na=False)
V = V[V.rule.isin(RULES) & (V.primary_approved == "True")]
pend = set(pd.read_csv(PENDING, dtype=str, keep_default_na=False).patent_id) if PENDING.exists() else set()
V = V[~V.patent_id.isin(pend)]
# patents the user has already reviewed in the wizard (review_decisions/REVIEWED_IN_WIZARD.csv, filled from each installed
# export's diff) — user 2026-09-19: "I just changed some patents in the wizard, take them off the contradiction page"
REVIEWED = L0 / "inputs" / "review_decisions" / "REVIEWED_IN_WIZARD.csv"
done = set(pd.read_csv(REVIEWED, dtype=str, keep_default_na=False).patent_id) if REVIEWED.exists() else set()
print("left out (already reviewed in the wizard):", sorted(done & set(V.patent_id)))
V = V[~V.patent_id.isin(done)]
# quick overrides (user 2026-09-18, US2019135426A1): an override means the drawing is too hard to read, so the details
# behind it are deliberately not recorded — no rule that needs those details can judge the aircraft. Left out.
_A0 = pd.read_csv(TABLES / "aircraft_table.csv", dtype=str, keep_default_na=False, low_memory=False).set_index("aircraft_id")
_qo = [c for c in _A0.columns if c.endswith("quickOverride") and not c.startswith("ml_") and c not in ("t1_quickOverride", "g1_quickOverride")]
QO = {a for a in V.aircraft_id.unique() if a in _A0.index and any(str(_A0.at[a, c]) == "True" for c in _qo)}
V = V[~V.aircraft_id.isin(QO)]
print("left out (quick override):", sorted(QO))
# aircraft the user has ruled fine as they stand — never shown again
USER_OK = {"US2023121845A1_ua1": "PFV (an 'Other' type) whose detail cards were never filled: user 2026-09-19, 'this one is overridden, so there is no problem here'"}
print("left out (user ruled fine):", sorted(set(USER_OK) & set(V.aircraft_id)))
V = V[~V.aircraft_id.isin(USER_OK)]
A = pd.read_csv(TABLES / "aircraft_table.csv", dtype=str, keep_default_na=False, low_memory=False).set_index("aircraft_id")
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

STATIONS = [("wing1", "wing 1"), ("wing2", "wing 2"), ("wing3", "wing 3"), ("fuselage", "fuselage"), ("emp", "empennage"),
            ("boom", "booms"), ("hull_array", "hull array"), ("core_layout", "core layout")]
def g(r, c): return str(r[c]) if c in r.index and str(r[c]) not in ("nan", "None") else ""
def morphology(r):
    """Plain-words summary of what the record says about this aircraft."""
    rows = [["type", f"{g(r,'topType')} — {TOPNAME.get(g(r,'topType'), '')}"],
            ["body motion", name("FUS_KIN", g(r, "fusKin")) or "—"],
            ["wings", (f"{g(r,'wCount') or '0'} × {name('WING_CONFIG', g(r,'wingConf'))}" if g(r, "wingConf") else f"{g(r,'wCount') or '0'}")
             + "".join(f"; wing {i}: {g(r, f'wing{i}_role') or '—'}, tilt {name('W_TILT', g(r, f'wing{i}_tilt')) or '—'}" for i in (1, 2, 3) if g(r, f"wing{i}_role") or g(r, f"wing{i}_tilt"))],
            ["empennage", (name("EMP_TYPE", g(r, "empType")) or "—") + (" · TILTS" if g(r, "empTilts") == "True" else "")]]
    bg = []
    for i in range(1, 7):
        if g(r, f"boom{i}_attach") or g(r, f"boom{i}_count"):
            bg.append(f"group {i}: {g(r, f'boom{i}_count') or '?'} × to {g(r, f'boom{i}_attach') or '?'}, orient {g(r, f'boom{i}_orient') or '—'}"
                      + (", carries propulsors" if g(r, f"boom{i}_hasProps") == "True" else "") + (", TILTS" if g(r, f"boom{i}_tilts") == "True" else "")
                      + (", retracts" if g(r, f"boom{i}_retracts") == "True" else ""))
    rows.append(["booms", "; ".join(bg) or "none"])
    cards = []
    for st, lab in STATIONS:
        nt = g(r, f"{st}_ntypes"); nt = 2 if nt not in ("", "True", "1", "False", "0") else 1
        tys = [(f"{st}_t{t}_", f" type {t}") for t in range(1, 4) if g(r, f"{st}_t{t}_count")] if nt > 1 else [(f"{st}_", "")]
        for pre, tl in tys:
            c = g(r, pre + "count")
            c = "1" if c == "True" else "0" if c in ("False", "") else c
            if c == "0": continue
            cards.append([lab + tl, c, ORIENT.get(g(r, pre + "orient"), g(r, pre + "orient") or "—"),
                          name("PROP_KIN", g(r, pre + "propKin")) or "—", name("RETRACT_MECH", g(r, pre + "rmech")) or "—",
                          "control only" if g(r, pre + "ctrlOnly") == "True" else ""])
    return rows, cards

def figures(pid, ua):
    f = F[F.patent_id == pid].copy()
    out = []
    for x in f.itertuples():
        out.append(dict(file=x.image_file, src=src(pid, x.image_path, x.image_file), rot=rot(x.rotation_deg), ua=int(x.ua or 1),
                        status=x.status, main=(x.is_main == "True"), per=x.per, state=x.acState, sty=x.acSty))
    return out

cards = []
for aid, grp in V.groupby("aircraft_id", sort=False):
    if aid not in A.index: continue
    r = A.loc[aid]; pid, ua = r.patent_id, int(r.ua)
    morph, props = morphology(r)
    def _sugg(x):
        if x.rule != "VECTORED_2_OF_3": return RULES[x.rule][1]
        m = re.search(r"expected (\w+)$", x.detail)
        return [m.group(1)] if m and m.group(1) in TOPNAME else ["SLC", "MR", "PTC"]   # nothing tilts: not a vectored type
    rules = [dict(rule=x.rule, text=RULES[x.rule][0], detail=x.detail, suggest=_sugg(x), kind=RULES[x.rule][2]) for x in grp.itertuples()]
    kinds = {x["kind"] for x in rules}
    sugg = sorted({t for x in rules for t in x["suggest"] if t != r.topType})
    opts = [["right", "Label is right — the rule is too strict (say why)"]]
    if "mr" in kinds:
        opts += [["mr_tilt", "Its rotors / booms tilt (say which)"], ["mr_pitch", "It moves by pitching the whole body → Whole-Body Pitch"]]
    opts += [["type", "Change the type (pick below)"], ["part", "Change a part (say what)"], ["unsure", "Not sure"]]
    cards.append(dict(key=aid, pid=pid, ua=ua, n_ua=int(r.n_variants or 1) if str(r.n_variants).isdigit() else 1,
                      type=r.topType, typeName=TOPNAME.get(r.topType, ""), name=r.aircraft_name, company=r.company, title=r.title,
                      pdf=r.pdf_link, uncertain=(r.g1_humanUncertain == "True"), rules=rules, morph=morph, props=props,
                      suggest=sugg, opts=opts, figs=figures(pid, ua)))
ORDER = {"type": 0, "mr": 1, "part": 2}
cards.sort(key=lambda c: (min(ORDER[x["kind"]] for x in c["rules"]), c["type"], c["company"], c["pid"], c["ua"]))
data = json.dumps(dict(cards=cards, top=[[k, v] for k, v in TOPNAME.items()]), ensure_ascii=False, default=str)
PAGE = (REPO / "scripts" / "contradiction_review_template.html").read_text(encoding="utf-8")
OUT.write_text(PAGE.replace("__DATA__", data), encoding="utf-8")
print(f"wrote {OUT}: {len(cards)} aircraft, {len(V)} rule breaks {V.rule.value_counts().to_dict()}; {len(pend)} pending patents left out")
