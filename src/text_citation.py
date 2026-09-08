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
# a hit in the title outranks one buried in the drawings description.
SECTIONS: list[tuple[str, str]] = [
    ("title",                   "Title"),
    ("abstract",                "Abstract"),
    ("first_claim",             "First claim"),
    ("innovation_objective",    "Summary of invention"),
    ("description_of_drawings", "Description of drawings"),
]

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
               flags: int = re.IGNORECASE) -> dict | None:
    """First section (in SECTIONS order) where `pattern` matches.

    Returns {"section", "quote", "match"} or None. `meta` is one entry of the
    PatSeer index. Pass a compiled pattern or a regex string; use
    `literal_pattern()` for a name you want matched as a whole word.
    """
    if not meta:
        return None
    rx = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, flags)
    for key, label in SECTIONS:
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
