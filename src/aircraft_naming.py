"""
aircraft_naming.py — mining candidate aircraft names out of patent text.

Stage 03a. Returns [] for most patents, which is the correct answer: applicants
write "an aircraft 100" precisely to avoid tying a claim to one product. The
gazetteer and the LLM are the real name sources; this is the third one.

Everything here exists to keep reference numerals ("the rotor 12"), figure
labels and CPC codes OUT of the aircraft_name column — a false name still looks
like clean data in a spreadsheet, which makes it worse than a blank.
"""

from __future__ import annotations

import re


# 104"), figure labels and classification codes, all of which look exactly like
# a model designation to a naive pattern. The blocklist and the shape rules
# below exist entirely to keep those out.

_STOP_TOKENS = {
    # Document furniture
    "FIG", "FIGS", "FIGURE", "US", "EP", "WO", "CN", "JP", "KR", "PCT", "USPTO",
    "ABSTRACT", "CLAIM", "CLAIMS", "SUMMARY", "PRIOR", "ART", "APPL", "PUB",
    "NO", "SER", "PAT", "REF", "PARA", "SECT", "EMBODIMENT",
    # CPC/IPC classes that survive the shape rules (B64C, B64D, G05D, H02K...)
    "B64C", "B64D", "B64F", "B64U", "G05D", "H02K", "H02J", "B60L", "G08G",
    # Units and physics that pattern-match as designations
    "RPM", "KW", "KG", "KM", "MPH", "FT", "LB", "LBS", "DC", "AC", "GPS",
    "VTOL", "EVTOL", "STOL", "UAV", "UAM", "AAM", "ESC", "BLDC", "PMSM",
    "ISO", "ASTM", "FAA", "EASA", "SAE", "IEEE",
}

# Shape 1 — letter-block + digit-block designation: S-A1, VX4, EH216, CX300,
# Alia-250, X-57, VA-1X. Requires >= 1 leading letter and >= 1 digit, and the
# letters must not be a known stop token.
_DESIGNATION_RE = re.compile(r"\b([A-Z][A-Za-z]{0,9})-?(\d{1,4})([A-Z]{0,2})\b")

# Shape 2 — CamelCase compound product names: CityAirbus, VoloCity, VoloDrone,
# AirCar, SkyDrive, LiliumJet. Two or more capitalised segments, no space.
_CAMEL_RE = re.compile(r"\b((?:[A-Z][a-z]{2,})(?:[A-Z][a-z]{2,})+)\b")

# Shape 3 — explicitly marked trade names. Highest-precision shape by far:
# a ™/® or an explicit naming verb is a direct statement that the token is a
# product name, not a part number.
_TRADEMARK_RE = re.compile(r"\b([A-Z][\w\- ]{1,28}?)\s*(?:™|®|\(TM\)|\(R\))")

# Stripped from a captured name — see _add() below.
_LEADING_ARTICLE_RE = re.compile(r"^(?:The|A|An|Its|Our|This|Said)\s+", re.IGNORECASE)
_NAMED_AS_RE = re.compile(
    r"\b(?:known|marketed|sold|designated|branded|referred\s+to)\s+as\s+"
    r"(?:the\s+)?[\"“']?([A-Z][\w\- ]{1,28}?)[\"”']?(?=[\s,.;)])",
    re.IGNORECASE,
)

# SBERT discriminative anchors. Scoring a candidate against a single "is this a
# product name" anchor is useless — every short token scores about the same.
# Scoring it against a POSITIVE and a NEGATIVE anchor and taking the difference
# is what actually separates "Midnight" from "rotor 12".
_NAME_ANCHOR_POS = (
    "the commercial model designation or product name of an electric vertical "
    "takeoff and landing aircraft built by an aerospace company"
)
_NAME_ANCHOR_NEG = (
    "a reference numeral, figure label, patent classification code or part "
    "number used inside a patent drawing description"
)


def mine_name_candidates(
    text: str | None,
    patent_id: str | None = None,
    sbert_model=None,
    max_candidates: int = 5,
) -> list[dict]:
    """Pull candidate aircraft designations out of patent text.

    Returns a list of {"value", "confidence", "source", "shape", "context"},
    best first. Returns [] for most patents — see the module docstring: patents
    are usually written to avoid naming the product, and an empty list is the
    honest answer rather than a failure.

    `sbert_model` is optional. Without it, candidates are ranked by shape
    precedence alone (trademark > named-as > camel > designation); with it,
    they are additionally scored by the positive-minus-negative anchor margin
    described above, which is what demotes reference numerals.
    """
    if not text or not str(text).strip():
        return []
    text = str(text)

    seen: dict[str, dict] = {}

    def _add(value: str, shape: str, base_conf: float, span: tuple[int, int]) -> None:
        value = value.strip(" -–—.,;:")
        # The trademark and named-as shapes start their capture at the first
        # capital letter, which is usually a sentence-initial article ("The
        # Midnight™ aircraft"). Left in, every such name would enter the sheet
        # as "The Midnight" and never match the gazetteer.
        value = _LEADING_ARTICLE_RE.sub("", value).strip(" -–—.,;:")
        if not value or len(value) > 32:
            return
        head = re.split(r"[-\s]", value)[0].upper()
        if head in _STOP_TOKENS or value.upper() in _STOP_TOKENS:
            return
        # Never propose the patent's own publication number as the aircraft name.
        if patent_id and value.upper().replace("-", "") in str(patent_id).upper():
            return
        # A designation must carry at least one letter AND one digit, or be a
        # multi-word / CamelCase name. A bare number is always a reference numeral.
        if not re.search(r"[A-Za-z]", value):
            return
        prev = seen.get(value.upper())
        if prev and prev["confidence"] >= base_conf:
            return
        lo, hi = max(0, span[0] - 60), min(len(text), span[1] + 60)
        seen[value.upper()] = {
            "value": value,
            "confidence": base_conf,
            "source": "regex",
            "shape": shape,
            "context": " ".join(text[lo:hi].split()),
        }

    for m in _TRADEMARK_RE.finditer(text):
        _add(m.group(1), "trademark", 0.70, m.span(1))
    for m in _NAMED_AS_RE.finditer(text):
        _add(m.group(1), "named_as", 0.65, m.span(1))
    for m in _CAMEL_RE.finditer(text):
        _add(m.group(1), "camelcase", 0.45, m.span(1))
    for m in _DESIGNATION_RE.finditer(text):
        letters, digits, suffix = m.group(1), m.group(2), m.group(3)
        # A single leading capital followed by digits ("A 12", "B 104") is the
        # reference-numeral shape, not a designation — require either >= 2
        # letters or an explicit hyphen in the source text.
        if len(letters) < 2 and "-" not in m.group(0):
            continue
        _add(f"{letters}{'-' if '-' in m.group(0) else ''}{digits}{suffix}",
             "designation", 0.35, m.span())

    candidates = list(seen.values())
    if not candidates:
        return []

    # SBERT re-ranking: positive-anchor similarity minus negative-anchor
    # similarity, folded into the shape confidence. A candidate that looks more
    # like a part number than a product name gets pushed down, not dropped —
    # the reviewer still sees it in the Evidence sheet.
    if sbert_model is not None:
        import numpy as np

        ctxs = [f"{c['value']} — {c['context']}" for c in candidates]
        emb = sbert_model.encode(ctxs, convert_to_numpy=True, normalize_embeddings=True)
        anchors = sbert_model.encode([_NAME_ANCHOR_POS, _NAME_ANCHOR_NEG],
                                     convert_to_numpy=True, normalize_embeddings=True)
        margins = emb @ anchors[0] - emb @ anchors[1]
        for cand, margin in zip(candidates, margins):
            cand["sbert_margin"] = round(float(margin), 4)
            # Margin is roughly [-0.3, 0.3]; map it to a +-0.15 adjustment so
            # shape precedence still dominates and SBERT only breaks ties.
            cand["confidence"] = round(
                max(0.05, min(0.95, cand["confidence"] + float(margin) * 0.5)), 4
            )
            cand["source"] = "sbert"

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates[:max_candidates]

