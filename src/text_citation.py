"""
text_citation.py — "where in the patent does it say that?"

Stage 03a. The reviewer wants every value they sign off on to come with the
sentence it came from and the section that sentence sits in, so the workbook
can be checked without opening the PDF. This module is that lookup, plus the
one classifier (VTOL / STOL) that did not exist elsewhere.

Only the sections `extractor.load_patseer_excel()` loads are searchable:

    title, abstract, first_claim, innovation_objective (Summary of Invention),
    description_of_drawings

The full Description column is deliberately not loaded (see extractor), so
"not in text" here means "not in those five sections", and the README says so.
"""

from __future__ import annotations

import re

# (index key, label the reviewer sees). Order = search order = trust order:
# a hit in the title outranks one buried in the body.
#
# SIGNAL_SECTIONS are what load_patseer_excel() loads: short, dense, and about
# THIS invention. BODY_SECTIONS are the full Description and Claims, loaded only
# by enrich_full_text() — tens of thousands of characters that also contain the
# prior-art discussion, so a hit there is real evidence but weaker, and the
# section column always says which it was.
SIGNAL_SECTIONS: list[tuple[str, str]] = [
    ("title",                   "Title"),
    ("abstract",                "Abstract"),
    ("first_claim",             "First claim"),
    ("innovation_objective",    "Summary of invention"),
    ("description_of_drawings", "Description of drawings"),
]
BODY_SECTIONS: list[tuple[str, str]] = [
    ("claims_full",  "Claims"),
    ("description",  "Description"),
]
SECTIONS = SIGNAL_SECTIONS + BODY_SECTIONS

# The aircraft NAME is searched in the signal sections only. A patent's
# Description routinely names other people's aircraft ("unlike the V-22
# Osprey…"), and counting that as "this patent names its aircraft" would put
# every such row in the review queue for nothing.
NAME_SECTIONS = SIGNAL_SECTIONS

QUOTE_WINDOW = 140          # characters kept on each side of the match


def _clip(text: str, lo: int, hi: int) -> str:
    """The sentence-ish span around [lo, hi): cut at the nearest sentence
    boundary inside the window, so the reviewer reads a phrase, not a shard."""
    start = max(0, lo - QUOTE_WINDOW)
    end = min(len(text), hi + QUOTE_WINDOW)
    head = text[start:lo]
    tail = text[hi:end]
    # nearest sentence start in the head, nearest sentence end in the tail
    m = list(re.finditer(r"[.;:!?]\s+|\n", head))
    if m:
        head = head[m[-1].end():]
    elif start > 0:                       # no sentence start in reach: cut at a word, mark it
        ws = head.find(" ")
        head = ("…" + head[ws:]) if ws >= 0 else "…" + head
    m = re.search(r"[.;!?](?:\s|$)|\n", tail)
    if m:
        tail = tail[:m.end()]
    elif end < len(text):
        ws = tail.rfind(" ")
        tail = (tail[:ws] + " …") if ws >= 0 else tail + "…"
    quote = (head + text[lo:hi] + tail).strip()
    return " ".join(quote.split())


def find_quote(meta: dict | None, pattern: "str | re.Pattern",
               flags: int = re.IGNORECASE, sections: list | None = None) -> dict | None:
    """First section (in trust order) where `pattern` matches.

    Returns {"section", "quote", "match"} or None. `meta` is one entry of the
    PatSeer index. Pass a compiled pattern or a regex string; use
    `literal_pattern()` for a name you want matched as a whole word.
    `sections` defaults to every section present — pass NAME_SECTIONS to keep
    the search out of the prior-art body.
    """
    if not meta:
        return None
    rx = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, flags)
    for key, label in (sections or SECTIONS):
        text = meta.get(key)
        if not text:
            continue
        text = str(text)
        m = rx.search(text)
        if m:
            return {"section": label, "quote": _clip(text, m.start(), m.end()),
                    "match": m.group(0)}
    return None


def literal_pattern(name: str) -> re.Pattern:
    """Whole-word, case-insensitive match of a trade name, tolerant of the
    hyphen/space variants patents use ("S-4", "S4", "S 4")."""
    # Split on whitespace/hyphens AND at letter<->digit boundaries, so "S4"
    # also finds "S-4" and "S 4", and "Alia-250" finds "Alia 250".
    tokens = re.findall(r"[A-Za-z]+|\d+|[^\sA-Za-z\d\-]+", str(name))
    parts = [re.escape(t) for t in tokens if t]
    body = r"[\s\-]?".join(parts) if parts else re.escape(str(name))
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


# ─── The full body text ──────────────────────────────────────────────────────
# extractor.load_patseer_excel() deliberately loads only the short, dense
# fields — widening it would change every other notebook's SBERT input. The
# body is read here instead, for Stage 03a alone, and used for two things only:
# a propulsion keyword that the abstract never stated, and the sentence to
# quote for it. Measured 2026-09-08: it answers the powertrain for 432 of the
# 577 patents the signal sections leave open.

_BODY_COLUMNS = [("description", ["Description"]), ("claims_full", ["Claims"])]


def enrich_full_text(index: dict[str, dict], path, verbose: bool = True) -> dict:
    """Merge the Description and Claims columns into a load_patseer_excel index.

    Mutates `index` in place. Optional: an export without those columns simply
    leaves the keys unset and every caller degrades to the signal sections.
    """
    import pandas as pd

    df = pd.read_excel(path, dtype=str)
    by_norm = {" ".join(str(c).split()).lower(): c for c in df.columns}
    found = {key: by_norm[v.lower()] for key, variants in _BODY_COLUMNS
             for v in variants if v.lower() in by_norm}
    if not found:
        if verbose:
            print("⚠  No Description/Claims columns in this export — "
                  "powertrain will be read from the abstract and claim only.")
        return {"found": {}, "enriched": 0}

    enriched = 0
    for _, row in df.iterrows():
        pid = str(row.get("Record Number", "")).strip()
        if not pid or pid == "nan" or pid not in index:
            continue
        for key, col in found.items():
            val = str(row.get(col, "")).strip()
            index[pid][key] = None if val in ("", "nan") else val
        enriched += 1
    if verbose:
        chars = sum(len(index[p].get("description") or "") for p in index)
        print(f"Full text: {', '.join(sorted(found))} for {enriched} patents "
              f"({chars/1e6:.0f} M characters of Description).")
    return {"found": found, "enriched": enriched}


# ─── UAV language ────────────────────────────────────────────────────────────
# The annotator tags an approved patent "UAVSimilar" when the aircraft is a UAV
# in an eVTOL-like configuration — and, by their own account, forgot some. This
# pass finds the language so those rows can be offered for tagging. It is a
# HINT: only the annotator's tag or a *_human cell ever reaches uav_final.
# Signal sections only — nearly every Description says "manned or unmanned"
# somewhere in its boilerplate, which would flag the whole corpus.

_UAV_RE = (r"\bunmanned\b|\bUAVs?\b|\bUASs?\b|\bdrones?\b|\bremotely[\s-]+piloted\b"
           r"|\bunpiloted\b|\bpilotless\b|\bautonomous\s+aerial\b")
_CREWED_RE = (r"\bpassengers?\b|\boccupants?\b|(?<!un)\bmanned\b|\bcrew\b|\bair\s+taxi\b"
              r"|\bcockpit\b|\bhuman[\s-]carrying\b|\bpersonal\s+air\b")
UAV_HINT_OPTIONS = "UAV|UAV-language"


def classify_uav(meta: dict | None) -> dict:
    """UAV = the signal sections use UAV vocabulary and never mention people
    aboard. UAV-language = both vocabularies appear ("manned or unmanned"),
    worth a look but weaker. None = no UAV vocabulary at all."""
    uav = find_quote(meta, _UAV_RE, sections=SIGNAL_SECTIONS)
    if not uav:
        return {"value": None, "confidence": 0.0, "source": None, "section": None, "quote": None}
    crewed = find_quote(meta, _CREWED_RE, sections=SIGNAL_SECTIONS)
    if crewed:
        return {"value": "UAV-language", "confidence": 0.50, "source": "keyword",
                "section": uav["section"], "quote": uav["quote"]}
    return {"value": "UAV", "confidence": 0.80, "source": "keyword",
            "section": uav["section"], "quote": uav["quote"]}


# ─── Take-off mode ───────────────────────────────────────────────────────────
# The reviewer disapproves a STOL-only aircraft, so this is the one field where
# a keyword miss matters more than a false positive. Both classes are searched
# and a document that uses both vocabularies is reported as such ("V/STOL")
# rather than silently picking one.

TAKEOFF_KEYWORDS: list[tuple[str, str]] = [
    (r"\bSTOL\b|\bshort[\s\-]*take[\s\-]*off\b|\bshort[\s\-]*field\b"
     r"|\bshort\s+runway\b", "STOL"),
    (r"\bVTOL\b|\beVTOL\b|\bvertical[\s\-]*take[\s\-]*off\b"
     r"|\bvertically\s+(?:take|taking)\s+off\b|\bvertical\s+(?:lift|flight|landing)\b"
     r"|\bhover(?:s|ing)?\b|\bhelicopter\b|\bmulti[\s\-]?(?:rotor|copter)\b"
     r"|\btilt[\s\-]?(?:rotor|wing|prop)\b|\brotorcraft\b", "VTOL"),
    (r"\bCTOL\b|\bconventional[\s\-]*take[\s\-]*off\b", "CTOL"),
]
TAKEOFF_OPTIONS = "VTOL|STOL|V/STOL|CTOL"

_CONF_TAKEOFF_CLEAR = 0.80
_CONF_TAKEOFF_MIXED = 0.50


def classify_takeoff(meta: dict | None) -> dict:
    """VTOL / STOL / V/STOL / CTOL from the loaded sections, with its quote.

    Returns the pipeline's standard prediction dict plus "section" / "quote".
    For STOL and V/STOL the quote is the STOL sentence — that is the one the
    reviewer needs to read before disapproving. A document with no take-off
    vocabulary at all returns value None; it is not assumed to be VTOL just
    because it is in an eVTOL corpus.
    """
    hits = {label: find_quote(meta, pattern) for pattern, label in TAKEOFF_KEYWORDS}
    stol, vtol, ctol = hits["STOL"], hits["VTOL"], hits["CTOL"]

    if stol and vtol:
        return {"value": "V/STOL", "confidence": _CONF_TAKEOFF_MIXED, "source": "keyword",
                "section": stol["section"], "quote": stol["quote"]}
    if stol:
        return {"value": "STOL", "confidence": _CONF_TAKEOFF_CLEAR, "source": "keyword",
                "section": stol["section"], "quote": stol["quote"]}
    if vtol:
        return {"value": "VTOL", "confidence": _CONF_TAKEOFF_CLEAR, "source": "keyword",
                "section": vtol["section"], "quote": vtol["quote"]}
    if ctol:
        return {"value": "CTOL", "confidence": _CONF_TAKEOFF_MIXED, "source": "keyword",
                "section": ctol["section"], "quote": ctol["quote"]}
    return {"value": None, "confidence": 0.0, "source": None, "section": None, "quote": None}
