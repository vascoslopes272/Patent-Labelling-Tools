#!/usr/bin/env python3
"""Embed, into the 03a identity review page, the sentences of each patent that bear on the three
questions the reviewer answers: electric or not, VTOL or STOL, UAV or not.

The workbook already carries the ONE sentence each machine pass decided on. This adds the other side
of every question — the combustion sentence next to the electric one, the STOL sentence next to the
VTOL one, the "pilot / passenger" sentence next to the "unmanned" one — so a decision can be made from
the page without opening the PDF, and a patent that says the opposite is visible at once.

Patterns are the pipeline's own (aircraft_specs.POWERTRAIN_KEYWORDS, text_citation.TAKEOFF_KEYWORDS,
_UAV_RE, _CREWED_RE), so a quote here means what the same words mean everywhere else. Per question and
per side: the first hit in the short sections (title, abstract, claim 1, summary, drawings) and the
first hit in the body (claims, full Description), each labelled with its section.

    python scripts/build_identity_evidence.py

Writes 1639_LABELLED/joined/identity_evidence_<date>.json and rewrites the EVIDENCE block inside
notebooks/post-process/03a_identity_review.html (idempotent — re-run it whenever the corpus changes).
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.extractor import load_patseer_excel                                  # noqa: E402
from src.text_citation import (enrich_full_text, SIGNAL_SECTIONS,             # noqa: E402
                               BODY_SECTIONS, TAKEOFF_KEYWORDS, _UAV_RE, _CREWED_RE)
from src.aircraft_specs import (POWERTRAIN_KEYWORDS, _PRIOR_ART_RE,           # noqa: E402
                                _NONCOMMITTAL_RE, _MODAL_COMBUSTION_RE, _families_in)

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling/inputs")   # 2026-09-17: stage-0 INPUTS of the 1639_LABELLED tree
OUT = ROOT.parent / "outputs"                                                                                   # what notebook 04 writes
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
PAGE = REPO / "notebooks" / "post-process" / "03a_identity_review.html"
OUT_JSON = ROOT / "identity" / "identity_evidence_20260913.json"
BEGIN, END = "/* EVIDENCE:BEGIN */", "/* EVIDENCE:END */"
MAXLEN = 330

_pt = {lab: pat for pat, lab in POWERTRAIN_KEYWORDS}
_to = {lab: pat for pat, lab in TAKEOFF_KEYWORDS}
CATS = [
    ("electric",   "|".join((_pt["BatteryElectric"], _pt["HydrogenFuelCell"]))),
    ("hybrid",     _pt["HybridElectric"]),
    ("combustion", "|".join((_pt["Turbine"], _pt["Piston"]))),
    ("vtol",       _to["VTOL"]),
    ("stol",       _to["STOL"]),
    ("ctol",       _to["CTOL"]),
    ("uav",        _UAV_RE),
    ("crewed",     _CREWED_RE),
]


# A quote must start where its sentence starts: a window cut mid-phrase ("… and the electric motor")
# does not say what it is about. Patent bodies also number their paragraphs ("[0043] The aircraft …"),
# so a paragraph marker counts as a boundary too. The matched words travel with the quote, so the page
# can highlight them.
# A claim splits its elements with semicolons, so a semicolon only starts a sentence when a capital
# follows it; otherwise the quote would open on "and the sensor comprises …", which says nothing.
_BOUND = re.compile(r"(?:[.!?]\s+|\n|\]\s|;\s+(?=[A-Z]))")
# Only true fragments count as a weak opening. "The …" is how most sentences start; treating it as
# weak would drag the previous sentence into every quote.
_WEAK_START = re.compile(r"^(?:and|or|but|wherein|which|whereby|whereas|while|said|thereby|therein|thereof|such that|so that|to|in|of|for|with|by|from)\b", re.I)


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence holding the match, walked back until it starts on its own feet."""
    bounds = [0] + [m.end() for m in _BOUND.finditer(text, 0, start)]
    tail = re.search(r"[.!?](?:\s|$)", text[end:])
    stop = end + (tail.end() if tail else min(200, len(text) - end))
    best = None
    for begin in reversed(bounds):
        quote = " ".join(text[begin:stop].split())
        if len(quote) > MAXLEN:
            break
        best = quote
        if not _WEAK_START.match(quote):
            break
    if best is None:                      # one very long sentence: keep the near window
        best = " ".join(text[bounds[-1]:stop].split())[:MAXLEN].rstrip() + "\u2026"
    return best


# How firm a powertrain sentence is, with the pipeline's own tests (aircraft_specs):
#   stated     — a commitment about this aircraft
#   option     — offered as one possibility among others ("an electric or hydraulic motor",
#                "may include a gas turbine"). Rule 2026-09-13: an electric OPTION counts as
#                electric; a combustion option decides nothing.
#   prior-art  — about other aircraft ("such drones are typically…"); counts for nothing.
POWERTRAIN_CATS = {"electric", "hybrid", "combustion"}


def grade(cat: str, sentence: str, matched: str = "") -> str:
    # "manned or unmanned" names both sides in one breath — an option, not a statement.
    if cat == "uav":
        return "option" if re.search(_CREWED_RE, sentence, re.I) else "stated"
    if cat == "crewed":
        return "option" if re.search(_UAV_RE, sentence, re.I) else "stated"
    if cat not in POWERTRAIN_CATS:
        return "stated"
    if _PRIOR_ART_RE.search(sentence):
        return "prior-art"
    if (len(_families_in(sentence)) > 1 or _NONCOMMITTAL_RE.search(sentence)
            or _MODAL_COMBUSTION_RE.search(sentence)
            or re.search(r"\b(?:or|and/or)\b", matched, re.I)):
        return "option"
    return "stated"


def quotes(meta, pattern, cat="") -> list[list[str]]:
    """[section, sentence, matched words, grade] — one from the short sections, one from the body."""
    rx = re.compile(pattern, re.I)
    out, seen = [], set()
    for sections in (SIGNAL_SECTIONS, BODY_SECTIONS):
        for key, label in sections:
            text = meta.get(key)
            if not text:
                continue
            m = rx.search(str(text))
            if not m:
                continue
            sentence = _sentence(str(text), m.start(), m.end())
            if sentence.lower() not in seen:
                seen.add(sentence.lower())
                out.append([label, sentence, m.group(0), grade(cat, sentence, m.group(0))])
            break
    return out


def main() -> int:
    idn = pd.read_excel(ROOT / "identity" / "aircraft_identity_ALL.xlsx", sheet_name="Identity",
                        usecols=["patent_id", "wizard_approved"])
    pids = list(idn.loc[idn.wizard_approved == True, "patent_id"])            # noqa: E712
    index = load_patseer_excel(PATSEER)
    enrich_full_text(index, PATSEER, verbose=False)

    pack, counts = {}, {c: 0 for c, _ in CATS}
    for pid in pids:
        meta = index.get(pid)
        if not meta:
            continue
        ev = {}
        for cat, pattern in CATS:
            q = quotes(meta, pattern, cat)
            if q:
                ev[cat] = q
                counts[cat] += 1
        if ev:
            pack[pid] = ev
    OUT_JSON.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    print(f"{len(pack)} of {len(pids)} approved patents carry evidence · "
          + " ".join(f"{c}:{n}" for c, n in counts.items()))
    print(f"{OUT_JSON} {OUT_JSON.stat().st_size/1e6:.1f} MB")

    html = PAGE.read_text(encoding="utf-8")
    block = f"{BEGIN}\nvar EVID = {json.dumps(pack, ensure_ascii=False, separators=(',', ':'))};\n{END}"
    if BEGIN in html:
        html = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block, html, flags=re.S)
    else:
        anchor = "<script>\n"
        i = html.index(anchor, html.index("</style>")) + len(anchor)
        html = html[:i] + block + "\n" + html[i:]
    PAGE.write_text(html, encoding="utf-8")
    print(f"embedded in {PAGE} ({PAGE.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
