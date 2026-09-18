"""wizard_view.py — what the labelling wizard SHOWS for a record, replayed from the record alone.

The wizard (notebooks/UI_for_taxonomy_caracterization_15_4.html) locks some fields once the
architecture is known: it draws the locked value as a disabled chip whatever is stored. A stored
value that differs from the lock is therefore invisible on screen but lands in the export — the
screen says one thing, the Excel another. This module replays every lock on the long-form record
and lists each place where the two differ, so notebook 04 can check them and
scripts/apply_wizard_locks.py can write the locked value into the record.

Every rule below mirrors a named function in the wizard; keep them in sync:

  acState (per approved figure)  pageT2 "Aircraft State in this View" + isConvertibleArch() +
                                 archConfigChanges(): a fixed architecture whose record moves
                                 nothing is locked to Invariant (stored id 'HoverCruise')
  <card>_propKin                 propKinLock(): TW/DS/SLC/SRW/MR/TB/PTC/RC -> Fixed (card level
                                 only; per-type <card>_tN_propKin stays free)
  fusKin                         applyFusKinLock() / pageM1: PTC, RC -> BodyPitch; TB -> never Fixed
  wingN_tilt                     g1-subbtn handler + pageM2: TB, PTC -> Fixed; TW -> wing1 Tilt;
                                 RC, MR are wingless (no wing tilt)

One deliberate difference: the wizard evaluates archConfigChanges() on the architecture that is
active while T2 is drawn (always arch 1), so on a multi-aircraft patent the figures of arch 2+
are judged by arch 1's morphology. Here each figure is judged by its OWN architecture, which is
what the lock means.

    from src.wizard_view import replay, INVARIANT_ID
    diffs = replay(long_df)            # columns: see DIFF_COLS
"""
from __future__ import annotations

import re

import pandas as pd

SEP = " — "
INVARIANT_ID = "HoverCruise"          # the wizard's id for the option it displays as "Invariant"
INVARIANT_NAME = "Invariant"
CONVERTIBLE = {"TW", "TR", "DS", "CVT", "SRW"}                       # isConvertibleArch()
PROPKIN_FIXED = {"TW", "DS", "SLC", "SRW", "MR", "TB", "PTC", "RC"}  # propKinLock()
BODYPITCH = {"PTC", "RC"}                                            # BODYPITCH_ARCHS
WINGLESS = {"RC", "MR"}
RETIRED_AC = {"Ground", "Unclear", "NonApplicable"}
PROPKIN_CARD_RE = re.compile(r"^(core_layout|hull_array|fuselage|emp|boom|wing\d)_propKin$")
DIFF_COLS = ["patent_id", "arch", "scope", "figure", "field", "topType", "stored", "wizard_shows", "rule"]


def strip_label(v) -> str:
    s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    s = s.split(SEP, 1)[0].strip() if SEP in s else s.strip()
    return "" if s in ("nan", "None", "NaT") else s


def _long(L: pd.DataFrame) -> pd.DataFrame:
    L = L[["Patent_ID", "Section", "Sub_Dimension", "Field", "Value"]].copy()
    L["Patent_ID"] = L.Patent_ID.astype(str)
    L["v"] = L.Value.map(strip_label)
    L["base"] = L.Patent_ID.str.replace(r"_arch\d+$", "", regex=True)
    L["arch"] = pd.to_numeric(L.Patent_ID.str.extract(r"_arch(\d+)$")[0], errors="coerce").fillna(1).astype(int)
    return L


def locked_view(d: dict) -> dict:
    """The architecture's fields as the wizard exports them: card-level propKin and fusKin under their locks."""
    tt, v = d.get("topType", ""), dict(d)
    if tt in PROPKIN_FIXED:
        for k in v:
            if PROPKIN_CARD_RE.match(k) and v[k]: v[k] = "Fixed"
    if tt in BODYPITCH: v["fusKin"] = "BodyPitch"
    return v


def moves(d: dict) -> list[str]:
    """morphConfigChanges() on the exported morphology: something changes shape between hover and cruise."""
    why = []
    for k, x in locked_view(d).items():
        if re.fullmatch(r"boom\d+_(tilts|retracts)", k) and x == "True": why.append(k)
        elif re.fullmatch(r"wing\d+_tilt", k) and x == "Tilt": why.append(f"{k}=Tilt")
        elif k == "fusKin" and x == "LevelCabin": why.append("fusKin=LevelCabin")
        elif k == "empTilts" and x == "True": why.append("empTilts")
        elif k.endswith("_propKin") and x in ("Tilt", "Vectored"): why.append(f"{k}={x}")
        elif k.endswith("_rmech") and x in ("Retracting", "Retractable", "BladeFold"): why.append(f"{k}={x}")
    return sorted(why)


def architectures(L: pd.DataFrame) -> dict[tuple[str, int], dict]:
    """(patent, arch) -> {Field: id} for G1–M3 of every architecture that carries a topType."""
    L = _long(L)
    m = L[L.Section.isin(["G1", "M1", "M2", "M3"])]
    out = {}
    for k, g in m.groupby(["base", "arch"]):
        d = dict(zip(g.Field.astype(str), g.v))
        if d.get("topType"): out[k] = d
    return out


def figures(L: pd.DataFrame) -> pd.DataFrame:
    """One row per T2 figure block (placeholders '(fig N)' excluded): base, figure, arch, status, acState."""
    L = _long(L)
    t2 = L[(L.Section == "T2") & ~L.Sub_Dimension.astype(str).str.contains(r"\(fig", regex=True)]
    t2 = t2[t2.Field.isin(["arch", "status", "acState"])]
    F = t2.pivot_table(index=["base", "Sub_Dimension"], columns="Field", values="v", aggfunc="last").reset_index()
    for c in ("arch", "status", "acState"):
        if c not in F.columns: F[c] = ""
    F["arch"] = pd.to_numeric(F.arch.replace("", "1"), errors="coerce").fillna(1).astype(int)
    return F.rename(columns={"Sub_Dimension": "figure"}).fillna("")


def replay(L: pd.DataFrame) -> pd.DataFrame:
    """Every place where the record stores something other than what the wizard shows."""
    A = architectures(L)
    rows = []
    def diff(pid, arch, scope, fig, field, tt, stored, shows, rule):
        rows.append(dict(patent_id=pid, arch=arch, scope=scope, figure=fig, field=field, topType=tt,
                         stored=stored, wizard_shows=shows, rule=rule))

    for (pid, arch), d in A.items():
        tt = d["topType"]
        if tt in PROPKIN_FIXED:
            for f, x in d.items():
                if PROPKIN_CARD_RE.match(f) and x and x != "Fixed":
                    diff(pid, arch, "aircraft", "", f, tt, x, "Fixed", f"propKinLock: {tt} propulsors never articulate")
        fk = d.get("fusKin", "")
        if tt in BODYPITCH and fk != "BodyPitch":
            diff(pid, arch, "aircraft", "", "fusKin", tt, fk, "BodyPitch", f"applyFusKinLock: {tt} pitches as one body")
        if tt == "TB" and fk == "Fixed":
            diff(pid, arch, "aircraft", "", "fusKin", tt, fk, "", "applyFusKinLock: a TB body cannot be Fixed (pick TiltBody or LevelCabin)")
        for f, x in d.items():
            if not re.fullmatch(r"wing\d+_tilt", f) or not x: continue
            if tt in ("TB", "PTC") and x != "Fixed":
                diff(pid, arch, "aircraft", "", f, tt, x, "Fixed", f"wing-tilt lock: a {tt} wing is rigid to the airframe")
            elif tt in WINGLESS:
                diff(pid, arch, "aircraft", "", f, tt, x, "", f"{tt} is wingless: no wing tilt")
        if tt == "TW" and d.get("wing1_tilt", "") not in ("", "Tilt"):
            diff(pid, arch, "aircraft", "", "wing1_tilt", tt, d["wing1_tilt"], "Tilt", "wing-tilt lock: the TW primary wing tilts")

    for r in figures(L).itertuples():
        if r.status != "approved": continue
        d = A.get((r.base, r.arch))
        if not d: continue                                   # no topType (D1/D2, unclassifiable): nothing is locked
        tt = d["topType"]
        if tt in CONVERTIBLE or moves(d): continue           # unlocked: the reviewer's pick is what is shown
        if r.acState != INVARIANT_ID:
            diff(r.base, r.arch, "figure", r.figure, "acState", tt, r.acState, INVARIANT_ID,
                 f"acState lock: a {tt} whose record moves nothing shows Invariant on every figure")
    return pd.DataFrame(rows, columns=DIFF_COLS)


def unlocked_fixed(L: pd.DataFrame) -> pd.DataFrame:
    """Fixed-architecture records the wizard UNLOCKS because something moves (v15.8), with the reason."""
    rows = [dict(patent_id=p, arch=a, topType=d["topType"], moves="; ".join(moves(d)))
            for (p, a), d in architectures(L).items() if d["topType"] not in CONVERTIBLE and moves(d)]
    return pd.DataFrame(rows, columns=["patent_id", "arch", "topType", "moves"])
