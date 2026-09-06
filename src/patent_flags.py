"""
patent_flags.py — the two disqualifying labels, and the rejectable flag they feed.

Stage 03a. Two questions that decide whether a patent belongs in an eVTOL
corpus at all:

  1. TAKEOFF MODE   VTOL / STOL / CTOL / VSTOL — a short-takeoff or
                    conventional-takeoff aircraft is not an eVTOL.
  2. PROPULSION     already answered by aircraft_specs.classify_powertrain();
                    a turbine or piston aircraft is not an *electric* VTOL.

Both are LABELS, not deletions. `rejectable` is a suggestion with a reason and
a score attached — it never removes a row, never edits the wizard, and never
decides anything on its own. You confirm or override it in the triage page.

The threshold is the whole design
---------------------------------
A flag only fires when its underlying label clears REJECTABLE_MIN_CONFIDENCE.
The asymmetry matters and runs one way on purpose:

  - a FALSE flag costs you a few seconds of review, and you overrule it;
  - a MISSED flag leaves a runway aeroplane sitting in an eVTOL corpus.

So the flag is tuned to fire readily and be easy to dismiss, rather than to be
quietly right. Everything it fires on is sorted to the top of the triage page
with the sentence that triggered it, so dismissing a wrong one is one keystroke.

Why "runway" cannot be taken at face value
------------------------------------------
eVTOL patents talk about runways constantly — to say they do not need one.
"takes off and lands without a runway" is VTOL evidence, not CTOL evidence, and
a naive keyword pass gets it exactly backwards. Negation is checked before any
conventional-takeoff cue is counted.

Public API
----------
classify_takeoff_mode(text, sbert_model)  -> dict
assess_rejectable(takeoff_pred, powertrain_pred) -> dict
build_flag_row(text, powertrain_pred, sbert_model) -> dict
"""

from __future__ import annotations

import re

from src.reviewer import _sbert_best, _margin_flag


# ─── Takeoff mode ────────────────────────────────────────────────────────────

TAKEOFF_MODE_OPTIONS = "VTOL|STOL|CTOL|VSTOL|Unknown"

TAKEOFF_DEFS: dict[str, str] = {
    "VTOL": (
        "The aircraft takes off and lands vertically, rising straight up under rotor "
        "or fan thrust and hovering, without needing a runway or any ground roll."
    ),
    "STOL": (
        "The aircraft takes off and lands within a very short ground roll, using a "
        "short field or short runway, high-lift devices and blown flaps, but it "
        "cannot hover or rise vertically."
    ),
    "CTOL": (
        "The aircraft takes off and lands conventionally along a paved runway with a "
        "normal takeoff roll, like an ordinary fixed-wing aeroplane."
    ),
    "VSTOL": (
        "The aircraft is capable of both vertical and short takeoff and landing, "
        "operating either way depending on load and site."
    ),
}

# Cue phrases, matched with space/hyphen tolerance. Collected as a SET of modes
# named, then resolved below — a patent that names two modes is a different
# answer from one that names either alone.
_TAKEOFF_CUES: list[tuple[str, str]] = [
    # Explicit both-capable forms first: "V/STOL" contains both substrings and
    # would otherwise be double-counted as VTOL + STOL.
    (r"\bv\s*/\s*stol\b|\bvstol\b|\bv\s+or\s+s\s*tol\b"
     r"|\bvertical\s+(?:and\s*/?\s*or|or)\s+short\s+take\s*off\b", "VSTOL"),
    (r"\bshort\s+take\s*off\b|\bstol\b|\bshort\s+field\b|\bshort\s+runway\b"
     r"|\bshortened\s+take\s*off\b|\breduced\s+take\s*off\s+(?:roll|run|distance)\b",
     "STOL"),
    # tak\w+ covers take/takes/taking/took off; helipad/vertiport/rooftop are
    # site words that only make sense for an aircraft that lands vertically.
    (r"\bvertical\s+take\s*off\b|\bvtol\b|\btak\w*\s+off\s+vertically\b"
     r"|\bvertically\s+tak\w*\s+off\b|\bland\w*\s+vertically\b"
     r"|\bvertical\s+(?:lift|launch|flight|ascent|descent)\b"
     r"|\bhelipads?\b|\bvertiports?\b|\bhover\w*\b", "VTOL"),
    (r"\bconventional\s+take\s*off\b|\bctol\b|\btake\s*off\s+roll\b"
     r"|\btake\s*off\s+run\b|\bground\s+roll\b", "CTOL"),
]

# "without a runway", "does not require a runway", "no runway needed" — these are
# VTOL claims. Counting them as conventional-takeoff evidence inverts the label.
_RUNWAY_RE = re.compile(r"\brunways?\b")
_RUNWAY_NEGATED_RE = re.compile(
    r"\b(?:without|no|not|never|eliminat\w+|avoid\w*|free\s+of|independent\s+of|"
    r"does\s+not\s+require|do\s+not\s+require|obviat\w+)\b[^.;]{0,40}?\brunways?\b"
    r"|\brunways?\b[^.;]{0,30}?\b(?:is|are)\s+not\s+(?:required|needed)\b")

_ESTOL_RE = re.compile(r"\be\s*-?\s*stol\b")

_CONF_TAKEOFF_KEYWORD = 0.88   # an explicit "vertical takeoff and landing" is decisive
_CONF_TAKEOFF_MIXED   = 0.60   # two modes named without a V/STOL phrase
# Below REJECTABLE_MIN_CONFIDENCE on purpose — an inference must never be strong
# enough to flag a patent on its own.
_CONF_TAKEOFF_INFERRED = 0.62


def _normalise(text: str) -> str:
    """Collapse whitespace and hyphens so 'take-off'/'take off'/'takeoff' match."""
    return re.sub(r"[\s\-]+", " ", str(text).lower())


def classify_takeoff_mode(text: str | None, sbert_model=None) -> dict:
    """VTOL / STOL / CTOL / VSTOL from the patent text.

    Returns the pipeline's standard prediction dict, plus `modes_named` — every
    mode the text explicitly names, which is what the triage page shows when a
    patent claims more than one.
    """
    empty = {"value": None, "confidence": 0.0, "source": None, "modes_named": [],
             "evidence": None}
    if not text or not str(text).strip():
        return empty

    hay = _normalise(text)
    modes: list[str] = []
    evidence: dict[str, str] = {}

    for pattern, mode in _TAKEOFF_CUES:
        m = re.search(pattern, hay, re.IGNORECASE)
        if not m:
            continue
        if mode == "CTOL":
            # Only count conventional-takeoff cues once the runway negation
            # check below has had its say — handled after the loop.
            modes.append(mode)
            evidence[mode] = _snippet(hay, m.start(), m.end())
            continue
        modes.append(mode)
        evidence[mode] = _snippet(hay, m.start(), m.end())

    # eSTOL is a named product category and is decisive on its own.
    if _ESTOL_RE.search(hay) and "STOL" not in modes:
        modes.append("STOL")
        m = _ESTOL_RE.search(hay)
        evidence["STOL"] = _snippet(hay, m.start(), m.end())

    # Runway mentions: only conventional-takeoff evidence when NOT negated.
    if _RUNWAY_RE.search(hay) and not _RUNWAY_NEGATED_RE.search(hay):
        if "CTOL" not in modes:
            m = _RUNWAY_RE.search(hay)
            modes.append("CTOL")
            evidence["CTOL"] = _snippet(hay, m.start(), m.end())
    elif _RUNWAY_NEGATED_RE.search(hay):
        # "without a runway" is a vertical-takeoff claim, so a CTOL cue that came
        # only from the word runway is withdrawn.
        if "CTOL" in modes and evidence.get("CTOL", "").find("runway") >= 0:
            modes.remove("CTOL")
            evidence.pop("CTOL", None)

    modes = list(dict.fromkeys(modes))

    # "takes off and lands without a runway" names no mode positively, but in
    # this domain it is a vertical-takeoff claim. Inferred at a confidence
    # deliberately BELOW REJECTABLE_MIN_CONFIDENCE, so it can fill the label
    # column without ever being able to raise the rejectable flag by itself.
    if not modes and _RUNWAY_NEGATED_RE.search(hay):
        m = _RUNWAY_NEGATED_RE.search(hay)
        return {"value": "VTOL", "confidence": _CONF_TAKEOFF_INFERRED,
                "source": "keyword_negation", "margin": 1.0,
                "modes_named": [], "evidence": _snippet(hay, m.start(), m.end())}

    if not modes:
        pred = _margin_flag(_sbert_best(text, TAKEOFF_DEFS, sbert_model))
        pred["modes_named"] = []
        pred["evidence"] = None
        return pred

    value, conf = _resolve_modes(modes)
    return {
        "value": value,
        "confidence": conf,
        "source": "keyword",
        "margin": 1.0,
        "modes_named": modes,
        "evidence": evidence.get(value) or next(iter(evidence.values()), None),
    }


def _resolve_modes(modes: list[str]) -> tuple[str, float]:
    """Turn the set of named modes into one label.

    An explicit V/STOL phrase settles it. Otherwise VTOL wins over STOL and CTOL
    when they co-occur: in this corpus a patent that mentions both is nearly
    always an eVTOL contrasting itself against runway aircraft, and calling that
    one STOL would flag a valid patent as rejectable. Confidence drops to mark
    it as a mixed reading, which is what routes it to the top of the triage page.
    """
    if "VSTOL" in modes:
        return "VSTOL", _CONF_TAKEOFF_KEYWORD
    if len(modes) == 1:
        return modes[0], _CONF_TAKEOFF_KEYWORD
    if "VTOL" in modes and "STOL" in modes:
        return "VSTOL", _CONF_TAKEOFF_MIXED
    if "VTOL" in modes:
        return "VTOL", _CONF_TAKEOFF_MIXED
    if "STOL" in modes:
        return "STOL", _CONF_TAKEOFF_MIXED
    return modes[0], _CONF_TAKEOFF_MIXED


def _snippet(text: str, start: int, end: int, pad: int = 55) -> str:
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    return " ".join(text[lo:hi].split())


# ─── Rejectable ──────────────────────────────────────────────────────────────

# A label must be at least this confident before it may raise the flag. Set it
# lower to catch more and dismiss more; higher to be shown fewer, at the cost of
# missing some. Every input is exported as its own column, so re-thresholding is
# a spreadsheet filter rather than a re-run.
REJECTABLE_MIN_CONFIDENCE = 0.70

# Takeoff modes that disqualify a patent from an eVTOL corpus. VSTOL is NOT
# here: a both-capable aircraft is still a vertical-takeoff aircraft.
_REJECTABLE_TAKEOFF = {"STOL", "CTOL"}

# Powertrains that are not electric propulsion. Hybrid is NOT here — a series
# hybrid still flies on electric motors, and whether it belongs in the corpus is
# your scoping decision, not one this flag should pre-empt.
_REJECTABLE_POWERTRAIN = {"Turbine", "Piston"}

FLAG_COLUMNS = [
    "takeoff_mode", "takeoff_mode_source", "takeoff_mode_confidence",
    "takeoff_modes_named", "takeoff_evidence",
    "rejectable", "rejectable_reason", "rejectable_confidence",
]


def assess_rejectable(takeoff_pred: dict | None,
                      powertrain_pred: dict | None) -> dict:
    """Should this patent be suggested for rejection, and why?

    Returns {"value": bool, "reason": str|None, "confidence": float}. Both
    checks can fire; the reasons are joined and the confidence is the strongest
    single reason, not an average — one decisive signal should not be diluted
    by a weak second one.
    """
    takeoff_pred = takeoff_pred or {}
    powertrain_pred = powertrain_pred or {}

    reasons: list[str] = []
    confs: list[float] = []

    tv, tc = takeoff_pred.get("value"), takeoff_pred.get("confidence") or 0.0
    if tv in _REJECTABLE_TAKEOFF and tc >= REJECTABLE_MIN_CONFIDENCE:
        reasons.append(f"takeoff mode is {tv}, not VTOL")
        confs.append(float(tc))

    pv, pc = powertrain_pred.get("value"), powertrain_pred.get("confidence") or 0.0
    if pv in _REJECTABLE_POWERTRAIN and pc >= REJECTABLE_MIN_CONFIDENCE:
        reasons.append(f"propulsion is {pv}, not electric")
        confs.append(float(pc))

    return {
        "value": bool(reasons),
        "reason": "; ".join(reasons) or None,
        "confidence": round(max(confs), 4) if confs else None,
    }


def build_flag_row(text: str | None,
                   powertrain_pred: dict | None = None,
                   sbert_model=None) -> tuple[dict, list[dict]]:
    """Everything this module contributes for one patent: (columns, evidence)."""
    takeoff = classify_takeoff_mode(text, sbert_model)
    rejectable = assess_rejectable(takeoff, powertrain_pred)

    row = {
        "takeoff_mode": takeoff.get("value"),
        "takeoff_mode_source": takeoff.get("source"),
        "takeoff_mode_confidence": takeoff.get("confidence"),
        "takeoff_modes_named": "; ".join(takeoff.get("modes_named") or []) or None,
        "takeoff_evidence": takeoff.get("evidence"),
        "rejectable": rejectable["value"],
        "rejectable_reason": rejectable["reason"],
        "rejectable_confidence": rejectable["confidence"],
    }

    evidence = []
    if takeoff.get("value"):
        evidence.append({
            "patent_id": None, "field": "takeoff_mode",
            "candidate_value": takeoff["value"], "source": takeoff.get("source"),
            "confidence": takeoff.get("confidence"),
            "context": takeoff.get("evidence") or "",
        })
    if rejectable["value"]:
        evidence.append({
            "patent_id": None, "field": "rejectable",
            "candidate_value": True, "source": "rule",
            "confidence": rejectable["confidence"], "context": rejectable["reason"],
        })
    return row, evidence
