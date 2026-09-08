"""
aircraft_specs.py — what the patent text says about the aircraft itself:
propulsion type, application domain, performance figures and blade counts.

Stage 03a. Every extractor here is text-only and returns a confidence, because
none of these is stated by every patent:

  classify_powertrain     energy source -> is_electric        keyword, then SBERT
  classify_industry       application domain                  SBERT zero-shot
  extract_spec_hints      MTOW / payload / pax / speed / range / endurance
  extract_blade_counts    blades per propulsor, tagged by role

A number scraped from patent prose is usually an illustrative embodiment ("in
one embodiment the payload is about 200 kg"), not the built aircraft — hence
the low fixed confidence on spec hints, and the rule that a gazetteer value
always outranks them.
"""

from __future__ import annotations

import re

from src.reviewer import _sbert_best, _margin_flag

# A number scraped out of patent prose is usually an illustrative embodiment,
# not the built aircraft's specification — so it sits below the review
# threshold by construction and a gazetteer value always outranks it.
_CONF_REGEX_SPEC = 0.40


# ─── Powertrain taxonomy ─────────────────────────────────────────────────────
# One-sentence anchors, written the way reviewer.py writes its _*_DEFS: full
# sentences, because SBERT embeds sentences far better than bare labels.
POWERTRAIN_DEFS: dict[str, str] = {
    "BatteryElectric": (
        "The aircraft is powered purely by electric motors drawing current from "
        "onboard rechargeable battery packs, with no combustion engine of any kind."
    ),
    "HybridElectric": (
        "The aircraft uses a hybrid powerplant in which a combustion engine or gas "
        "turbine drives a generator that charges a battery and feeds electric motors, "
        "a turbogenerator or series hybrid range extender."
    ),
    "HydrogenFuelCell": (
        "The aircraft is powered by electric motors fed by a hydrogen fuel cell stack "
        "with compressed or liquid hydrogen storage tanks."
    ),
    "Turbine": (
        "The aircraft is propelled by gas turbine engines, turboshafts, turboprops or "
        "jet engines burning kerosene aviation fuel."
    ),
    "Piston": (
        "The aircraft is propelled by an internal combustion piston engine burning "
        "gasoline or diesel fuel and driving a propeller through a gearbox."
    ),
    "Unspecified": (
        "The document describes the airframe geometry, structure and control surfaces "
        "without stating what kind of engine or energy source drives the propulsors."
    ),
}

# Deterministic prior. Patent language around propulsion is formulaic enough
# that a keyword hit is usually more reliable than the cosine score, so a
# keyword win is trusted and never margin-flagged (same convention as
# reviewer._margin_flag, which exempts source == "keyword").
POWERTRAIN_KEYWORDS: list[tuple[str, str]] = [
    (r"\bfuel\s*cell\b|\bhydrogen\b|\bH2\s+(?:tank|storage)\b", "HydrogenFuelCell"),
    (r"\bhybrid[-\s]?electric\b|\bturbo\s*generator\b|\bturbogenerator\b"
     r"|\brange\s+extender\b|\bseries\s+hybrid\b|\bgenerator\s+set\b", "HybridElectric"),
    (r"\bbattery\s*(?:pack|module|cell)s?\b|\ball[-\s]?electric\b"
     r"|\belectric\s+(?:motor|propulsion|powertrain)\b|\bdistributed\s+electric\s+propulsion\b"
     r"|\bDEP\b|\beVTOL\b", "BatteryElectric"),
    (r"\bturbo\s*shaft\b|\bturboshaft\b|\bturbo\s*prop\b|\bgas\s+turbine\b"
     r"|\bjet\s+engine\b|\bturbofan\b", "Turbine"),
    (r"\binternal\s+combustion\s+engine\b|\bpiston\s+engine\b|\breciprocating\s+engine\b",
     "Piston"),
]

# A hybrid statement contains battery/electric words too, so the scan must be
# ordered most-specific-first and stop at the first hit — hence the list above
# is ordered, not a dict.

# is_electric is reported as a 4-value string rather than a bool: "Hybrid" is a
# real and common answer in this corpus and collapsing it to True or False
# would lose exactly the distinction the thesis is drawing.
ELECTRIC_BY_POWERTRAIN: dict[str, str] = {
    "BatteryElectric":  "Yes",
    "HydrogenFuelCell": "Yes",     # electric propulsion; hydrogen is the energy carrier
    "HybridElectric":   "Hybrid",
    "Turbine":          "No",
    "Piston":           "No",
    "Unspecified":      "Unknown",
}
IS_ELECTRIC_OPTIONS = "Yes|Hybrid|No|Unknown"


# ─── Application-domain (industry) taxonomy ──────────────────────────────────
INDUSTRY_DEFS: dict[str, str] = {
    "UAM_Passenger": (
        "An air taxi or urban air mobility vehicle carrying fare-paying passengers on "
        "short intercity or intra-city trips between vertiports."
    ),
    "Cargo_Logistics": (
        "An unmanned or optionally-piloted freight aircraft carrying parcels, pallets "
        "or middle-mile logistics payloads between distribution centres."
    ),
    "Medical_EMS": (
        "An air ambulance or medical evacuation aircraft carrying a patient on a "
        "stretcher, organs for transplant, or emergency medical crew."
    ),
    "Military_Defence": (
        "A military aircraft for reconnaissance, surveillance, troop insertion, "
        "resupply of forward positions or weapons carriage in a contested environment."
    ),
    "Agriculture": (
        "An agricultural aircraft for crop spraying, seeding, fertiliser dispersal or "
        "livestock and field monitoring over farmland."
    ),
    "Inspection_Survey": (
        "An inspection and survey aircraft for photographing power lines, pipelines, "
        "wind turbines, construction sites or for aerial mapping and photogrammetry."
    ),
    "Emergency_SAR": (
        "A search and rescue or firefighting aircraft for locating casualties, "
        "delivering rescue equipment or dropping water over a fire."
    ),
    "Recreation_Sport": (
        "A personal, recreational or sport aircraft flown by an owner-pilot for "
        "leisure, including single-seat personal air vehicles and flying motorcycles."
    ),
    "Infrastructure_Utility": (
        "A utility aircraft supporting construction, heavy lift, cable laying, "
        "offshore platform servicing or telecommunications relay."
    ),
    "General_Unspecified": (
        "A general-purpose aircraft configuration described without committing to any "
        "particular commercial mission or end user."
    ),
}


# ─── Powertrain / industry classification ────────────────────────────────────

def classify_powertrain(text: str | None, sbert_model=None) -> dict:
    """Classify the energy source. Keyword prior first, SBERT as the fallback.

    Returns the pipeline's standard prediction dict —
    {"value", "confidence", "source", "margin"} — so it merges the same way
    every other prediction in this codebase does.

    The keyword pass runs first and wins outright when it hits: propulsion
    language in patents is formulaic ("a plurality of electric motors powered
    by a battery pack"), so a literal match is stronger evidence than a cosine
    score over a 384-token truncation of the same text.
    """
    if not text or not str(text).strip():
        return {"value": None, "confidence": 0.0, "source": None}

    lowered = str(text)
    for pattern, label in POWERTRAIN_KEYWORDS:
        if re.search(pattern, lowered, re.IGNORECASE):
            return {"value": label, "confidence": 0.80, "source": "keyword", "margin": 1.0}

    return _margin_flag(_sbert_best(text, POWERTRAIN_DEFS, sbert_model))


def classify_industry(text: str | None, sbert_model=None) -> dict:
    """Zero-shot application domain over INDUSTRY_DEFS.

    No keyword prior here on purpose: mission statements in patents are prose
    ("for transporting a passenger between rooftop landing sites"), not
    keywords, which is precisely the case SBERT handles better than a regex.
    """
    return _margin_flag(_sbert_best(text, INDUSTRY_DEFS, sbert_model))


# ─── Spec hints from the patent text ─────────────────────────────────────────
# Patents state numbers only occasionally, and when they do it is usually a
# range or an "about". These are recorded as HINTS with low confidence and the
# sentence they came from, so a reviewer can accept or reject them against the
# source. They are never promoted over a gazetteer value.

_NUM = r"(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"

# (canonical field, unit-converted-to, keyword pattern, unit pattern, factor)
_SPEC_PATTERNS: list[tuple[str, str, str, str, float]] = [
    ("mtow_kg", "kg", r"(?:maximum\s+take[-\s]?off\s+(?:weight|mass)|MTOW|gross\s+weight)",
     r"kg|kilograms?", 1.0),
    ("mtow_kg", "kg", r"(?:maximum\s+take[-\s]?off\s+(?:weight|mass)|MTOW|gross\s+weight)",
     r"lbs?|pounds?", 0.45359237),
    ("payload_kg", "kg", r"payload", r"kg|kilograms?", 1.0),
    ("payload_kg", "kg", r"payload", r"lbs?|pounds?", 0.45359237),
    ("range_km", "km", r"(?:mission\s+)?range", r"km|kilometers?|kilometres?", 1.0),
    ("range_km", "km", r"(?:mission\s+)?range", r"mi|miles", 1.609344),
    ("range_km", "km", r"(?:mission\s+)?range", r"nm|nmi|nautical\s+miles", 1.852),
    ("cruise_speed_kmh", "km/h", r"cruise\s+(?:speed|velocity)",
     r"km\s*/?\s*h|kph|kilometers?\s+per\s+hour", 1.0),
    ("cruise_speed_kmh", "km/h", r"cruise\s+(?:speed|velocity)", r"mph|miles\s+per\s+hour", 1.609344),
    ("cruise_speed_kmh", "km/h", r"cruise\s+(?:speed|velocity)", r"kts?|knots?", 1.852),
    ("max_speed_kmh", "km/h", r"(?:maximum|top)\s+(?:speed|velocity)",
     r"km\s*/?\s*h|kph", 1.0),
    ("max_speed_kmh", "km/h", r"(?:maximum|top)\s+(?:speed|velocity)", r"mph", 1.609344),
    ("max_speed_kmh", "km/h", r"(?:maximum|top)\s+(?:speed|velocity)", r"kts?|knots?", 1.852),
    ("endurance_min", "min", r"(?:endurance|flight\s+time|hover\s+time)",
     r"min(?:ute)?s?", 1.0),
    ("endurance_min", "min", r"(?:endurance|flight\s+time|hover\s+time)", r"h(?:ou)?rs?", 60.0),
]

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_PAX_RE = re.compile(
    r"\b(?:(\d{1,3})|(" + "|".join(_WORD_NUMBERS) + r"))\s+"
    r"(?:passengers?|occupants?|seats?|persons?|people|crew\s+members?)\b",
    re.IGNORECASE,
)

SPEC_FIELDS = ["mtow_kg", "payload_kg", "pax", "cruise_speed_kmh",
               "max_speed_kmh", "range_km", "endurance_min"]


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return None


def extract_spec_hints(text: str | None) -> dict[str, dict]:
    """Best-effort numeric specs stated in the patent text.

    Returns {field: {"value", "confidence", "source", "context"}} for the
    fields that were found. Confidence is fixed low (_CONF_REGEX_SPEC): a
    number written in a patent is typically an illustrative embodiment ("in one
    embodiment the payload is about 200 kg"), not the built aircraft's
    specification, so these are review prompts, not data.
    """
    if not text or not str(text).strip():
        return {}
    text = str(text)
    out: dict[str, dict] = {}

    for field, unit, kw_pat, unit_pat, factor in _SPEC_PATTERNS:
        # keyword ... number unit   (within ~60 chars — same sentence in practice)
        pattern = rf"{kw_pat}[^.;]{{0,60}}?{_NUM}\s*(?:{unit_pat})\b"
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        val = _to_float(m.group(1))
        if val is None:
            continue
        val = round(val * factor, 2)
        if field in out and out[field]["confidence"] >= _CONF_REGEX_SPEC:
            continue
        lo, hi = max(0, m.start() - 40), min(len(text), m.end() + 40)
        out[field] = {
            "value": val, "confidence": _CONF_REGEX_SPEC, "source": "regex",
            "unit": unit, "context": " ".join(text[lo:hi].split()),
        }

    m = _PAX_RE.search(text)
    if m:
        val = int(m.group(1)) if m.group(1) else _WORD_NUMBERS[m.group(2).lower()]
        # A patent claiming "one or more passengers" is not stating a seat count.
        if 1 <= val <= 20:
            lo, hi = max(0, m.start() - 40), min(len(text), m.end() + 40)
            out["pax"] = {
                "value": val, "confidence": _CONF_REGEX_SPEC, "source": "regex",
                "unit": "persons", "context": " ".join(text[lo:hi].split()),
            }
    return out


# ─── Blade count per propulsor ───────────────────────────────────────────────
# Patents state blade counts far more often than they state performance, because
# the count is structural and gets claimed ("a three-bladed proprotor"). Two
# false-positive classes have to be kept out:
#
#   1. Reference numerals — "the blade 12". Handled by requiring the number to
#      be BOUND to the word (hyphen, or immediately preceding "blades"), never
#      just nearby.
#   2. Non-count uses — "blade pitch", "blade element momentum", "blade root".
#      Handled by requiring a plural/participle form after the number.
#
# An eVTOL commonly has DIFFERENT counts on different propulsor groups (five-
# blade lift rotors, three-blade cruise propeller), so each hit records the role
# it was found next to rather than collapsing to one number.

_BLADE_WORD_NUM = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_BLADE_NUM = r"(\d{1,2}|" + "|".join(_BLADE_WORD_NUM) + r")"

_BLADE_PATTERNS = [
    # "three-bladed propeller", "5-blade rotor", "two bladed proprotor"
    rf"\b{_BLADE_NUM}[-\s]blade[ds]?\b",
    # "propellers each having three blades", "rotor with five blades"
    rf"\b(?:propeller|rotor|proprotor|fan|propulsor|blade\s+assembly)s?\b[^.;]{{0,40}}?"
    rf"\b(?:having|with|comprising|includes?|carries|carrying|defines?)\b[^.;]{{0,20}}?"
    rf"\b{_BLADE_NUM}\s+blades\b",
    # "three blades per propeller", "five blades on each rotor"
    rf"\b{_BLADE_NUM}\s+blades\s+(?:per|on\s+each|for\s+each|of\s+each)\b",
    # "a plurality of blades, namely four blades"
    rf"\bnamely\s+{_BLADE_NUM}\s+blades\b",
]

# Role of the propulsor group a count was found next to. Ordered most-specific
# first; searched in a window around the match.
_BLADE_ROLE_RULES = [
    (r"\b(?:lift|hover|vertical\s+lift|vtol)\s*(?:rotor|fan|propeller|propulsor|unit)s?\b"
     r"|\blift\s+rotor", "Lift"),
    (r"\b(?:cruise|forward\s+flight|pusher|tractor|propulsion)\s*"
     r"(?:propeller|rotor|propulsor|fan)s?\b", "Cruise"),
    (r"\b(?:main|primary)\s+rotor\b", "Main"),
    (r"\b(?:tail|anti[-\s]?torque)\s+rotor\b", "Tail"),
    (r"\bproprotors?\b|\btilt(?:ing)?[-\s]?(?:rotor|prop|propulsor)s?\b", "Tilt"),
]

# Blade counts outside this range are almost always a misparse (a reference
# numeral that slipped through, or a turbine stage count).
_BLADE_MIN, _BLADE_MAX = 2, 12

_BLADE_CONF = 0.65   # above the spec-hint floor: a claimed blade count is a
                     # structural fact, not an illustrative performance figure


def _blade_int(raw: str) -> "int | None":
    raw = str(raw).strip().lower()
    if raw in _BLADE_WORD_NUM:
        return _BLADE_WORD_NUM[raw]
    try:
        return int(raw)
    except ValueError:
        return None


# A count's propulsor group sits on one side or the other depending on the
# grammatical form, and the search must not cross into the next clause — these
# are the boundaries it stops at.
_CLAUSE_BREAK_RE = re.compile(r"[.;,]|\band\b|\bwhile\b|\bwhereas\b", re.IGNORECASE)

# "five-bladed rotor" is adjectival: the noun follows. "the rotor has five
# blades" is predicative: the noun precedes.
_BLADE_ADJECTIVAL_RE = re.compile(r"[-\s]blade[d]\b", re.IGNORECASE)


def _blade_role(text: str, start: int, end: int, matched: str) -> str:
    """Which propulsor group a blade count belongs to.

    Direction is decided by the grammatical form, and both searches stop at a
    clause boundary. Getting either wrong silently mislabels the data rather
    than failing: "five-bladed lift rotors and a three-bladed cruise propeller"
    tagged both as Lift when the search was direction-blind, and "the lift
    rotors each have five blades, while the pusher propeller has three blades"
    tagged the five as Cruise when it was clause-blind.
    """
    def _clause_start(pos: int) -> int:
        breaks = [m.end() for m in _CLAUSE_BREAK_RE.finditer(text[:pos])]
        return breaks[-1] if breaks else 0

    def _clause_end(pos: int) -> int:
        m = _CLAUSE_BREAK_RE.search(text, pos)
        return m.start() if m else len(text)

    def _nearest(lo: int, hi: int) -> "str | None":
        if lo >= hi:
            return None
        best, best_dist = None, None
        for pattern, role in _BLADE_ROLE_RULES:
            for m in re.finditer(pattern, text[lo:hi], re.IGNORECASE):
                pos = lo + m.start()
                dist = 0 if start <= pos <= end else min(abs(pos - end), abs(pos - start))
                if best_dist is None or dist < best_dist:
                    best, best_dist = role, dist
        return best

    # A role noun inside the match itself always wins — the longer patterns span
    # it ("propellers each having three blades").
    role = _nearest(start, end)
    if role:
        return role

    adjectival = bool(_BLADE_ADJECTIVAL_RE.search(matched))
    windows = ([(end, _clause_end(end)), (_clause_start(start), start)]
               if adjectival else
               [(_clause_start(start), start), (end, _clause_end(end))])
    for lo, hi in windows:
        role = _nearest(lo, hi)
        if role:
            return role
    return "Unspecified"


def extract_blade_counts(text: str | None) -> list[dict]:
    """Blade counts stated in the patent text, one entry per distinct
    (count, role) pair.

    Returns [{"count", "role", "confidence", "source", "context"}, ...] sorted
    by count. Returns [] when nothing is stated, which is common — a patent that
    claims "a plurality of blades" deliberately avoids committing to a number,
    and inventing one from the drawing is the image pipeline's job, not this one's.
    """
    if not text or not str(text).strip():
        return []
    text = str(text)

    seen: dict[tuple, dict] = {}
    for pattern in _BLADE_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            count = _blade_int(m.group(1))
            if count is None or not (_BLADE_MIN <= count <= _BLADE_MAX):
                continue
            role = _blade_role(text, m.start(), m.end(), m.group(0))
            key = (count, role)
            if key in seen:
                continue
            lo, hi = max(0, m.start() - 50), min(len(text), m.end() + 50)
            seen[key] = {
                "count": count, "role": role, "confidence": _BLADE_CONF,
                "source": "regex", "context": " ".join(text[lo:hi].split()),
            }

    # A count found with a role supersedes the same count found without one:
    # "three-bladed" early in the abstract and "three-bladed lift rotors" later
    # are one fact, and the roled version is the informative one.
    roled = {c["count"] for c in seen.values() if c["role"] != "Unspecified"}
    out = [c for k, c in seen.items()
           if c["role"] != "Unspecified" or c["count"] not in roled]
    return sorted(out, key=lambda c: (c["count"], c["role"]))


def summarise_blade_counts(blades: list[dict]) -> dict:
    """Flatten blade hits into sheet columns.

    `blades_all` keeps the per-role detail ("5 (Lift); 3 (Cruise)") because an
    eVTOL with different lift and cruise propulsors is the interesting case, and
    a single `blades_primary` number would erase exactly that.
    """
    if not blades:
        return {"blades_primary": None, "blades_all": None, "blades_min": None,
                "blades_max": None, "blades_distinct": 0,
                "blade_count_source": None, "blade_count_confidence": None}

    counts = [b["count"] for b in blades]
    # Primary = the count on the lift/main group when one is identified (that is
    # the rotor an eVTOL is characterised by), else the most common count.
    primary = next((b["count"] for b in blades if b["role"] in ("Lift", "Main", "Tilt")), None)
    if primary is None:
        primary = max(set(counts), key=counts.count)

    return {
        "blades_primary": primary,
        "blades_all": "; ".join(
            f"{b['count']}" + (f" ({b['role']})" if b["role"] != "Unspecified" else "")
            for b in blades),
        "blades_min": min(counts),
        "blades_max": max(counts),
        "blades_distinct": len(blades),
        "blade_count_source": "regex",
        "blade_count_confidence": _BLADE_CONF,
    }


BLADE_COLUMNS = ["blades_primary", "blades_all", "blades_min", "blades_max",
                 "blades_distinct", "blade_count_source", "blade_count_confidence"]

