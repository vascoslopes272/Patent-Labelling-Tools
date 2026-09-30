#!/usr/bin/env python3
"""build_hybrid_powertrain_review_page.py — review page for the powertrain domain rule (user 2026-09-27/30).
    python scripts/build_hybrid_powertrain_review_page.py
Rule: an aircraft is in the domain when its patent states that its propulsors can be driven by electric motors fed
from on-board BATTERIES (the only source or one of the stated options). Anything that needs a combustion engine to fly
(engine turning a propulsor, or engine making the electricity) is out; a fuel cell does not count as electric.
Rows: the 83 patents of review_decisions/HYBRID_POWERTRAIN_DECISIONS_20260930.csv (77 Hybrid + 6 Yes), with Claude's
proposal preselected; the user confirms or changes each one. Figures, the patent's powertrain sentences and a search over
the full PatSeer text (title/abstract/summary/description/claims) are embedded.
Export: HYBRID_POWERTRAIN_REVIEW.csv -> 0_labelling/inputs/review_decisions/ (the apply step reads confirmed rows only).
"""
import json
import re
from pathlib import Path
import pandas as pd
from hybrid_powertrain_citations import CITES

REPO = Path(__file__).resolve().parents[1]
L0 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
TABLES = L0 / "outputs" / "tables"
DEC = L0 / "inputs" / "review_decisions" / "HYBRID_POWERTRAIN_DECISIONS_20260930.csv"
PATSEER = L0 / "inputs" / "reference" / "patseer_1639_08_06_26.xlsx"
OUT = REPO / "notebooks" / "post-process" / "hybrid_powertrain_review.html"

PROP = {"A": "keep", "A0": "yes", "B": "remove_gen", "C": "remove_mech", "E": "remove_none", "D": "unknown"}  # class -> proposed option
CLASS_TEXT = {
    "A": "The patent says the aircraft can fly on batteries + electric motors (alone, as one of the options, or in an electric mode).",
    "A0": "Not really a hybrid: \"hybrid\" appears only in background text, a definition or a cited patent. The aircraft is electric.",
    "B": "The combustion engine makes the electricity for the motors (series hybrid / turbo-electric / range extender). No battery-only flight is stated.",
    "C": "A combustion engine turns a propeller or fan directly (mixed thrust, e.g. engine for cruise, battery rotors for lift).",
    "E": "Not electric at all: a turbine / turboshaft aircraft (the word \"generator\" or \"hybrid\" misled the keyword pass).",
    "D": "The patent never says where the energy comes from.",
}
KW = re.compile(r"hybrid|generator|batter|accumulator|fuel cell|energy stor|electrochemical|lithium|internal combustion|combustion|"
                r"turbine|turboshaft|turbofan|turbojet|turboprop|piston|diesel|gasoline|kerosene|fuel|engine|range extender|"
                r"all[- ]electric|fully electric|purely electric|electric[- ]only|electric motor|power source|power supply|energy source", re.I)
STRONG = re.compile(r"all[- ]electric|fully[- ]electric|purely electric|electric[- ]only|battery[- ]only|sole electrical|only (?:by |from )?(?:the )?batter|"
                    r"range extender|series hybrid|turbo-?generator|alternatively|or (?:a |an )?batter|batter[^.]{0,60}(?:or|and/or)|"
                    r"(?:generator|engine|fuel cell)[^.]{0,60}(?:or|and/or)[^.]{0,40}batter|power (?:source|supply)[^.]{0,40}(?:may|is|comprise|include)", re.I)


def sentences(text):
    return re.split(r"(?<=[.;])\s+(?=[A-Z0-9\[])", re.sub(r"\s+", " ", text))


def evidence(text, cap=45):
    seen, out = set(), []
    for s in sentences(text):
        if not KW.search(s) or len(s) < 25:
            continue
        k = s[:140].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s[:700])
    strong = [s for s in out if STRONG.search(s)]
    return (strong + [s for s in out if s not in strong])[:cap], len(out)


dec = pd.read_csv(DEC, dtype=str, keep_default_na=False)
pids = list(dec.patent_id)
A = pd.read_csv(TABLES / "aircraft_table.csv", dtype=str, keep_default_na=False, low_memory=False)
F = pd.read_csv(TABLES / "figure_table.csv", dtype=str, keep_default_na=False, low_memory=False)
F = F[(F.status == "approved") & F.patent_id.isin(pids)]
P = pd.read_excel(PATSEER, dtype=str, keep_default_na=False,
                  usecols=["Record Number", "Title", "Abstract", "Summary of Invention", "Description", "Claims"])
P = P[P["Record Number"].isin(pids)].set_index("Record Number")


SECTIONS = ["Claims", "Abstract", "Summary of Invention", "Description", "Title"]
COUNT_TERMS = {"battery": r"batter(?:y|ies)|accumulator", "fuel cell": r"fuel[- ]cell", "engine": r"\bengines?\b",
               "generator": r"generators?", "turbine": r"turbine|turboshaft|turbofan|turbojet", "hybrid": r"hybrid",
               "electric motor": r"electric(?:al)? motors?"}


def norm(t):
    return re.sub(r"\s+", " ", str(t or ""))


def tidy(sent):
    sent = re.sub(r"^[\s…]*(?:\[?\d{4}\]\s*)?", "", sent.strip())
    return ("… " + sent) if sent[:1].islower() else sent


def cite(pt, phrase):
    """Full sentence around a verbatim phrase: section, paragraph number, and every other section holding it."""
    pat = re.compile(r"\s*".join(re.escape(w) for w in phrase.split()), re.I)
    hits = []
    for sec in SECTIONS:
        t = norm(pt[sec])
        m = pat.search(t)
        if not m:
            continue
        a = max(t.rfind(". ", 0, m.start()), t.rfind("; ", 0, m.start()), t.rfind("\uff1b", 0, m.start()), t.rfind("] ", 0, m.start()) - 6)
        a = 0 if a < 0 else a + 2
        ends = [i for i in (t.find(". ", m.end()), t.find("; ", m.end()), t.find("\uff1b", m.end())) if i >= 0]
        b = min(ends) + 1 if ends else len(t)
        if m.start() - a > 450:
            a = m.start() - 450
        if b - m.end() > 450:
            b = m.end() + 450
        para = re.findall(r"\[(\d{4})\]", t[:m.end()])
        hits.append(dict(section=sec.replace("Summary of Invention", "Summary"), para=para[-1] if para and sec != "Claims" else "",
                         sentence=tidy(t[a:b]),
                         phrase=m.group(0)))
    if not hits:
        return None
    first = dict(hits[0])
    first["also"] = [h["section"] for h in hits[1:]]
    return first


def src(r):
    p = L0 / "outputs" / "images" / r.aircraft_id / r.image_file
    if p.exists():
        return "file://" + str(p)
    q = (r.image_path or "").replace("file://", "")
    return ("file://" + q) if q and Path(q).exists() else ""


def rot(v):
    try:
        return int(float(v))
    except Exception:
        return 0


items, MISSING = [], []
for r in dec.itertuples():
    pid = r.patent_id
    rows = A[(A.patent_id == pid) & (A.is_primary == "True") & (A.is_approved == "True")]
    aircraft = []
    for a in rows.itertuples():
        figs = F[F.aircraft_id == a.aircraft_id].copy()
        figs["o"] = (figs.is_main != "True").astype(int) * 2 + (figs.parts != "Whole Vehicle Layout").astype(int)
        figs = figs.sort_values(["o", "image_file"]).head(4)
        aircraft.append(dict(aid=a.aircraft_id, name=a.aircraft_name if a.name_is_real == "True" else "", tt=a.topType,
                             tags=a.edgeTags, figs=[dict(src=src(f), rot=rot(f.rotation_deg), file=f.image_file) for f in figs.itertuples()]))
    dups = sorted(set(A[(A.dup_root == pid) & (A.patent_id != pid)].patent_id))
    head = rows.iloc[0] if len(rows) else A[A.patent_id == pid].iloc[0]
    pt = P.loc[pid] if pid in P.index else None
    text = " ".join(str(pt[c]) for c in ["Title", "Abstract", "Summary of Invention", "Description", "Claims"]) if pt is not None else ""
    ev, n_ev = evidence(text)
    cites = []
    for ph in CITES[pid]:
        c = cite(pt, ph)
        if c is None:
            MISSING.append((pid, ph))
        else:
            cites.append(c)
    counts = {k: len(re.findall(v, text, re.I)) for k, v in COUNT_TERMS.items()}
    items.append(dict(pid=pid, title=head.title, company=head.company, year=head.app_year, pdf=head.pdf_link,
                      cur=r.current_final, prop=PROP[r._3], cls=r._3,  # the "class" column (a keyword, renamed by itertuples)
                      why=r.evidence, aircraft=aircraft, dups=dups, cites=cites, counts=counts, ev=ev, n_ev=n_ev, text=re.sub(r"\s+", " ", text)))

if MISSING:
    raise SystemExit("citation phrase not found:\n" + "\n".join(f"  {p}: {ph}" for p, ph in MISSING))
ORDER = {"remove_gen": 0, "remove_mech": 1, "remove_none": 2, "unknown": 3, "yes": 4, "keep": 5}
items.sort(key=lambda i: (ORDER[i["prop"]], i["company"], i["pid"]))
data = json.dumps(dict(items=items, classText=CLASS_TEXT), ensure_ascii=False)
OUT.write_text((REPO / "scripts" / "hybrid_powertrain_review_template.html").read_text(encoding="utf-8").replace("__DATA__", data), encoding="utf-8")
n_img = sum(len(a["figs"]) for i in items for a in i["aircraft"])
print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.1f} MB): {len(items)} patents, "
      f"{sum(len(i['aircraft']) for i in items)} aircraft, {n_img} figures "
      f"({sum(1 for i in items for a in i['aircraft'] for f in a['figs'] if not f['src'])} not found), "
      f"no text: {[i['pid'] for i in items if not i['text']]}")
print({k: sum(1 for i in items if i["prop"] == k) for k in ORDER})
