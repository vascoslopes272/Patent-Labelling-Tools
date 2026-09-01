"""
aircraft_identity.py — Stage 03a: link each patent to the real-world aircraft
it describes, and characterise that aircraft.

Answers four questions per patent, each with an explicit provenance and a
confidence, because none of them is answerable for every patent:

  1. WHICH AIRCRAFT?   aircraft_name  ("Joby S4", "Midnight", "VoloCity", ...)
  2. IS IT ELECTRIC?   powertrain     (BatteryElectric / HybridElectric /
                                       HydrogenFuelCell / Turbine / Piston /
                                       Unspecified) → is_electric
  3. WHAT ARE ITS NUMBERS?  mtow_kg, payload_kg, pax, cruise_speed_kmh,
                            max_speed_kmh, range_km, endurance_min
  4. WHERE AND FOR WHAT?    assignee_country, region, pub_office,
                            industry_primary

Four independent signals feed those fields. They are merged by a fixed
precedence (`SOURCE_PRECEDENCE`) so a weaker signal can never silently
overwrite a stronger one:

    human  >  gazetteer  >  llm  >  sbert  >  keyword  >  regex

  - `gazetteer`  reference/evtol_gazetteer.csv — a curated company→aircraft
                 table, matched on canonical company + filing-year window.
                 Highest precision, needs no network, and is the ONLY source
                 that should ever supply a spec number you cite in the thesis.
  - `llm`        an LLM asked "which aircraft was <company> flying around
                 <year>?" — either via the Anthropic API or, by default, via
                 an exported prompt sheet you paste into a chat and read back.
  - `sbert`      PatentSBERTa zero-shot cosine over the anchor definitions in
                 this module (POWERTRAIN_DEFS / INDUSTRY_DEFS), reusing
                 reviewer._sbert_best()/_margin_flag() exactly as the rest of
                 the pipeline does.
  - `keyword`/`regex`  deterministic passes over the patent text: propulsion
                 keywords, spec numbers next to their unit, candidate model
                 designations.

Honest expectations
-------------------
Patents very rarely name the product. `mine_name_candidates()` will come back
empty for most of the corpus, and that is the correct result, not a bug — the
gazetteer and the LLM are the real name sources, and every patent that gets
neither keeps aircraft_name empty with needs_review=True. Likewise the
shipped gazetteer deliberately carries NO spec numbers: every numeric cell is
blank with a `spec_source` column for you to fill from a citable source.
Fabricated performance figures in a thesis are worse than missing ones.

Public API
----------
assignee_country(raw)                              -> str | None
region_for(country_code)                           -> str
mine_name_candidates(text, patent_id, sbert_model) -> list[dict]
classify_powertrain(text, sbert_model)             -> dict
classify_industry(text, sbert_model)               -> dict
extract_spec_hints(text)                           -> dict
load_gazetteer(path)                               -> list[dict]
match_gazetteer(entry, gazetteer)                  -> dict | None
build_llm_prompt(entry)                            -> str
parse_llm_answer(text)                             -> dict
ask_claude(prompts, model, ...)                    -> dict[str, dict]
build_identity_row(...)                            -> tuple[dict, list[dict]]
export_identity_excel(rows, evidence, prompts, out_path) -> Path
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

# Reused verbatim from the rest of the pipeline so a prediction written here
# behaves the same as one written by 01a/01_review: same cosine scoring, same
# "guess but flag it" capping on a near-tie.
from src.reviewer import _sbert_best, _margin_flag
from src.grouper import _pub_office, _normalise_company
# Scope/architecture/specificity live in their own module; only its column list
# is needed here, so the two stay independently testable.
from src.patent_scope import SCOPE_COLUMNS as _SCOPE_COLUMNS


# ─── Provenance ordering ─────────────────────────────────────────────────────
# Higher wins. `human` sits on top so re-running this notebook over a sheet you
# have already corrected by hand never clobbers your corrections
# (see merge_preserving_human()).
SOURCE_PRECEDENCE = {
    None: -1, "": -1,
    "regex": 0, "keyword": 1, "sbert": 2, "llm": 3, "gazetteer": 4, "human": 5,
}

# Confidence attached to a source that does not compute one of its own.
_CONF_GAZETTEER_EXACT = 0.95   # canonical company matched AND year inside window
_CONF_GAZETTEER_LOOSE = 0.70   # company matched, year outside the window
_CONF_REGEX_SPEC      = 0.40   # a number next to its unit next to a keyword
_CONF_HUMAN           = 1.00

# Below this, a field is flagged for human confirmation in the output sheet.
NEEDS_REVIEW_BELOW = 0.55


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


# ─── Geography ───────────────────────────────────────────────────────────────
# PatSeer writes the assignee country as a trailing bracket: "BELL HELICOPTER
# TEXTRON INC (US)" or "SICHUAN WOFEI CO LTD (CHENGDU CITY, CN)". Same two
# shapes grouper._preprocess_assignee() strips — parsed here instead of
# discarded, because for this stage the country IS the signal.
_ASSIGNEE_CC_RE = re.compile(r"\(\s*(?:[^)]*,\s*)?([A-Z]{2})\s*\)\s*$")

REGION_BY_COUNTRY: dict[str, str] = {
    "US": "North America", "CA": "North America", "MX": "North America",
    "BR": "South America", "AR": "South America", "CL": "South America",
    "GB": "Europe", "DE": "Europe", "FR": "Europe", "IT": "Europe",
    "ES": "Europe", "PT": "Europe", "NL": "Europe", "BE": "Europe",
    "CH": "Europe", "AT": "Europe", "SE": "Europe", "NO": "Europe",
    "DK": "Europe", "FI": "Europe", "PL": "Europe", "CZ": "Europe",
    "IE": "Europe", "SI": "Europe", "RO": "Europe", "GR": "Europe",
    "RU": "Europe", "UA": "Europe", "TR": "Europe",
    "CN": "Asia-Pacific", "JP": "Asia-Pacific", "KR": "Asia-Pacific",
    "IN": "Asia-Pacific", "SG": "Asia-Pacific", "TW": "Asia-Pacific",
    "AU": "Asia-Pacific", "NZ": "Asia-Pacific", "MY": "Asia-Pacific",
    "TH": "Asia-Pacific", "ID": "Asia-Pacific", "VN": "Asia-Pacific",
    "IL": "Middle East", "AE": "Middle East", "SA": "Middle East",
    "QA": "Middle East", "JO": "Middle East",
    "ZA": "Africa", "EG": "Africa", "MA": "Africa", "NG": "Africa",
}

# Patent offices are jurisdictions, not countries — EP and WO cover many.
REGION_BY_OFFICE: dict[str, str] = {
    "US": "North America", "CA": "North America", "BR": "South America",
    "EP": "Europe", "DE": "Europe", "FR": "Europe", "GB": "Europe", "IT": "Europe",
    "CN": "Asia-Pacific", "JP": "Asia-Pacific", "KR": "Asia-Pacific",
    "WO": "International (PCT)",
}


def assignee_country(raw: str | None) -> str | None:
    """ISO-3166 alpha-2 country of the FIRST assignee, or None.

    Only the first assignee is read, matching grouper._preprocess_assignee():
    a co-assigned patent is attributed to its lead assignee throughout this
    pipeline, and splitting that convention only here would make the company
    and geography columns disagree with each other.

    >>> assignee_country("BELL HELICOPTER TEXTRON INC (US)")
    'US'
    >>> assignee_country("SICHUAN WOFEI CO LTD (CHENGDU CITY, CN); ZHEJIANG GEELY")
    'CN'
    >>> assignee_country("JOBY AERO INC") is None
    True
    """
    if not raw or str(raw).strip().lower() in ("", "nan", "none"):
        return None
    first = str(raw).split(";")[0].strip()
    m = _ASSIGNEE_CC_RE.search(first)
    return m.group(1) if m else None


def region_for(country_code: str | None, pub_office: str | None = None) -> str:
    """Region of the assignee country, falling back to the publication office.

    The office is only a fallback: a US publication says where protection was
    sought, not where the applicant is, and this corpus is US-heavy enough that
    treating the office as the applicant's geography would flatten the whole
    map into "North America".
    """
    if country_code and country_code in REGION_BY_COUNTRY:
        return REGION_BY_COUNTRY[country_code]
    if pub_office and pub_office in REGION_BY_OFFICE:
        return REGION_BY_OFFICE[pub_office]
    return "Unknown"


def publication_office(patent_id: str) -> str:
    """Publication office from the patent number prefix (US2022267016A1 → US)."""
    return _pub_office(patent_id)


# ─── Candidate aircraft-name mining ──────────────────────────────────────────
# Patent prose is saturated with reference numerals ("the rotor 12", "wing
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


# ─── Gazetteer ───────────────────────────────────────────────────────────────

GAZETTEER_COLUMNS = [
    "company_canonical", "aircraft_name", "aka", "year_from", "year_to",
    "powertrain", "mtow_kg", "payload_kg", "pax", "cruise_speed_kmh",
    "max_speed_kmh", "range_km", "endurance_min", "spec_source", "notes",
]

# Years are matched against the FILING year with this much slack on each side:
# a patent is typically filed 1-3 years before the aircraft it protects is
# publicly named, and companies keep filing after first flight.
_GAZETTEER_YEAR_SLACK = 3


def load_gazetteer(path: "str | Path") -> list[dict]:
    """Read reference/evtol_gazetteer.csv. Missing file → [] (not an error).

    A missing or empty gazetteer degrades this stage to LLM + SBERT only rather
    than failing the run, which is the right behaviour for a reference table
    the user is expected to grow over time.
    """
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            if not (raw.get("company_canonical") or "").strip():
                continue
            if (raw.get("company_canonical") or "").strip().startswith("#"):
                continue
            rows.append({k: (v.strip() if isinstance(v, str) else v)
                         for k, v in raw.items()})
    return rows


def _year_int(v) -> int | None:
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def match_gazetteer(
    company_canonical: str | None,
    app_year: str | None,
    gazetteer: list[dict],
    assignee_raw: str | None = None,
    text: str | None = None,
) -> dict | None:
    """Find the gazetteer entry for a patent. Returns None when nothing matches.

    Matching is on the canonical company name the grouper already assigned
    (batches.xlsx carries it), so the fuzzy assignee cleanup is not repeated
    here. When a company has several aircraft, the filing year picks between
    them; when the year is missing or outside every window, the entry whose
    name appears in the patent text wins, and failing that the single entry —
    a company with exactly one known aircraft needs no disambiguation.
    """
    if not gazetteer:
        return None

    company = (company_canonical or "").strip()
    if not company or company in ("Unknown / Independent", "Individual Inventor"):
        # Fall back to normalising the raw assignee ourselves — a patent can
        # reach this stage without ever having gone through the grouper.
        if assignee_raw:
            company = _normalise_company(assignee_raw)
        if not company or company in ("Unknown / Independent", "Individual Inventor"):
            return None

    hits = [g for g in gazetteer
            if (g.get("company_canonical") or "").strip().lower() == company.lower()]
    if not hits:
        return None

    year = _year_int(app_year)
    if year is not None:
        def _window(g, slack):
            lo, hi = _year_int(g.get("year_from")), _year_int(g.get("year_to"))
            lo = (lo - slack) if lo is not None else None
            hi = (hi + slack) if hi is not None else None
            return ((lo is None or year >= lo) and (hi is None or year <= hi))

        # Strict window first. The slack exists because filings run ahead of a
        # public name, but applying it up front makes consecutive programmes at
        # the same company overlap (Maker 2019-2022 and Midnight 2023-2030 both
        # swallow 2019 at +-3), turning a clean hit into a false ambiguity.
        # A year inside somebody's *stated* window is not ambiguous at all.
        strict = [g for g in hits if _window(g, 0)]
        if len(strict) == 1:
            return {**strict[0], "_match": "company+year",
                    "_confidence": _CONF_GAZETTEER_EXACT}

        in_window = strict if len(strict) > 1 else [g for g in hits if _window(g, _GAZETTEER_YEAR_SLACK)]
        if len(in_window) == 1:
            return {**in_window[0], "_match": "company+year_slack",
                    "_confidence": _CONF_GAZETTEER_EXACT}
        if len(in_window) > 1:
            hits = in_window   # narrowed; fall through to the text tie-break

    # Tie-break on the aircraft name actually appearing in the patent text.
    if text:
        blob = str(text).lower()
        named = [g for g in hits
                 if (g.get("aircraft_name") or "").lower() in blob
                 or ((g.get("aka") or "").lower() and (g["aka"]).lower() in blob)]
        if len(named) == 1:
            return {**named[0], "_match": "company+name_in_text",
                    "_confidence": _CONF_GAZETTEER_EXACT}

    if len(hits) == 1:
        return {**hits[0], "_match": "company_only", "_confidence": _CONF_GAZETTEER_LOOSE}

    # Several candidates and nothing to separate them — reporting ambiguity is
    # more useful than silently picking the first row.
    return {
        "company_canonical": company,
        "aircraft_name": "",
        "_match": "ambiguous",
        "_confidence": 0.0,
        "_candidates": "; ".join(sorted(g.get("aircraft_name", "") for g in hits)),
    }


# ─── LLM enrichment ──────────────────────────────────────────────────────────
# Two ways to run this, both producing the same {patent_id: answer_dict} shape:
#
#   MODE "export"  (default)  build_llm_prompt() → the LLM_Prompts sheet → you
#                             paste into a chat → paste the reply back into the
#                             llm_answer column → parse_llm_answer() reads it.
#   MODE "api"                ask_claude() calls the Anthropic API directly.
#
# The export mode is the default deliberately: it needs no API key, it keeps a
# verbatim record of every prompt and answer in the workbook (which is what a
# thesis methodology chapter needs to be reproducible), and it lets you use
# whatever chat interface you already have open.

LLM_SYSTEM_PROMPT = (
    "You are an aerospace research assistant helping build a dataset of eVTOL and "
    "advanced air mobility aircraft for a master's thesis.\n\n"
    "You are given a patent's assignee company, its filing and publication years, and "
    "its title and abstract. Identify the real, publicly announced aircraft this patent "
    "most likely relates to.\n\n"
    "Rules you must follow:\n"
    "- Answer ONLY from what you actually know about the company's announced aircraft. "
    "Never invent a model name, and never invent a performance figure.\n"
    "- If you do not know which aircraft it is, set aircraft_name to null and say why "
    "in reasoning. An honest null is far more useful here than a guess.\n"
    "- Give every specification only if you are confident of it. Any figure you are "
    "unsure of must be null, not an estimate.\n"
    "- confidence is your own 0-1 estimate that aircraft_name is correct.\n"
    "- Units are fixed: mass in kg, speed in km/h, range in km, endurance in minutes."
)

# Kept as a raw JSON schema (not Pydantic) so the module imports without
# pydantic installed — the notebook's export mode never touches the API path.
LLM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "aircraft_name": {"type": ["string", "null"]},
        "manufacturer": {"type": ["string", "null"]},
        "powertrain": {
            "type": ["string", "null"],
            "enum": [*POWERTRAIN_DEFS.keys(), None],
        },
        "is_electric": {"type": ["string", "null"], "enum": ["Yes", "Hybrid", "No", "Unknown", None]},
        "pax": {"type": ["number", "null"]},
        "mtow_kg": {"type": ["number", "null"]},
        "payload_kg": {"type": ["number", "null"]},
        "cruise_speed_kmh": {"type": ["number", "null"]},
        "max_speed_kmh": {"type": ["number", "null"]},
        "range_km": {"type": ["number", "null"]},
        "endurance_min": {"type": ["number", "null"]},
        "industry_primary": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["aircraft_name", "confidence", "reasoning"],
    "additionalProperties": False,
}


def build_llm_prompt(entry: dict) -> str:
    """The per-patent question. `entry` is one row of the identity table."""
    abstract = (entry.get("abstract") or "")[:1200]
    return (
        f"Patent: {entry.get('patent_id')}\n"
        f"Assignee (raw): {entry.get('assignee_raw') or 'unknown'}\n"
        f"Company (normalised): {entry.get('company_canonical') or 'unknown'}\n"
        f"Filing year: {entry.get('app_year') or 'unknown'}\n"
        f"Publication year: {entry.get('pub_year') or 'unknown'}\n"
        f"Title: {entry.get('title') or ''}\n"
        f"Abstract: {abstract}\n\n"
        "Which real aircraft does this most likely relate to? "
        "Reply with a single JSON object using exactly these keys: "
        "aircraft_name, manufacturer, powertrain "
        f"({'|'.join(POWERTRAIN_DEFS)}), is_electric ({IS_ELECTRIC_OPTIONS}), "
        "pax, mtow_kg, payload_kg, cruise_speed_kmh, max_speed_kmh, range_km, "
        "endurance_min, industry_primary, confidence, reasoning. "
        "Use null for anything you do not confidently know."
    )


_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_llm_answer(text: str | None) -> dict:
    """Tolerantly parse a pasted chat reply into the answer dict.

    Chat replies arrive wrapped in prose and ```json fences, so the first
    balanced-looking {...} blob is extracted rather than requiring clean JSON.
    An unparseable answer returns {} instead of raising — one bad paste in a
    350-row sheet must not abort the export.
    """
    if not text or not str(text).strip():
        return {}
    raw = str(text).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    m = _JSON_BLOB_RE.search(raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def ask_claude(
    prompts: dict[str, str],
    model: str = "claude-opus-5",
    max_tokens: int = 4096,
    max_workers: int = 8,
    progress: bool = True,
) -> dict[str, dict]:
    """Optional API path for the LLM step. `prompts` is {patent_id: prompt}.

    Uses structured outputs (output_config.format) so every reply is valid JSON
    against LLM_OUTPUT_SCHEMA — no prose stripping, no retry-on-malformed loop.
    Requests are independent, so they run on a small thread pool; the SDK
    already retries 429/5xx with backoff, so nothing is layered on top of that.

    Credentials resolve the SDK's normal way (ANTHROPIC_API_KEY, or an
    `ant auth login` profile) — nothing is read from config.yaml.
    """
    import anthropic
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = anthropic.Anthropic()
    results: dict[str, dict] = {}

    def _one(pid: str, prompt: str) -> tuple[str, dict]:
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": LLM_OUTPUT_SCHEMA}},
            )
            if resp.stop_reason == "refusal":
                return pid, {"_error": "refusal"}
            text = next((b.text for b in resp.content if b.type == "text"), "")
            return pid, (json.loads(text) if text else {})
        except Exception as exc:                      # noqa: BLE001 — one bad
            return pid, {"_error": f"{type(exc).__name__}: {exc}"}   # patent must
                                                                     # not kill the run
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_one, pid, p) for pid, p in prompts.items()]
        for i, fut in enumerate(as_completed(futures), 1):
            pid, data = fut.result()
            results[pid] = data
            if progress and (i % 25 == 0 or i == len(futures)):
                print(f"  LLM {i}/{len(futures)}")
    return results


# ─── Row assembly ────────────────────────────────────────────────────────────

IDENTITY_COLUMNS = [
    # Identity / provenance of the patent itself
    "patent_id", "batch", "company_canonical", "assignee_raw", "prototype_label",
    "app_year", "pub_year", "title",
    # Geography
    "pub_office", "assignee_country", "region",
    # Aircraft identity
    "aircraft_name", "aircraft_name_source", "aircraft_name_confidence",
    "aircraft_name_alternatives",
    # Propulsion
    "is_electric", "powertrain", "powertrain_source", "powertrain_confidence",
    # Application domain
    "industry_primary", "industry_source", "industry_confidence",
    # Specifications
    "pax", "mtow_kg", "payload_kg", "cruise_speed_kmh", "max_speed_kmh",
    "range_km", "endurance_min", "spec_source", "spec_confidence",
    # What the patent is about, and whether it is tied to one aircraft
    # (src/patent_scope.py — appended by attach_scope()).
    *_SCOPE_COLUMNS,
    # Bookkeeping
    "needs_review", "review_reason", "llm_reasoning",
    "reviewed_by", "reviewed_at", "notes",
]

EVIDENCE_COLUMNS = [
    "patent_id", "field", "candidate_value", "source", "confidence", "context",
]

PROMPT_COLUMNS = ["patent_id", "company_canonical", "app_year", "llm_prompt", "llm_answer"]

# Columns a human edits by hand in the exported sheet. A re-run must never
# overwrite these — see merge_preserving_human().
HUMAN_COLUMNS = ["reviewed_by", "reviewed_at", "notes", "llm_answer"]


def _pick(field_sources: list[tuple], default=None) -> tuple:
    """Choose the winning (value, source, confidence) by SOURCE_PRECEDENCE.

    Ties on precedence break on confidence. A candidate with a None value never
    wins, so a high-precedence source that simply had nothing to say (an LLM
    that honestly answered null) falls through to the next one instead of
    blanking the field.
    """
    best = (default, None, None)
    best_rank = -2
    for value, source, conf in field_sources:
        if value is None or value == "":
            continue
        rank = SOURCE_PRECEDENCE.get(source, 0)
        if rank > best_rank or (
            rank == best_rank and (conf or 0) > (best[2] or 0)
        ):
            best, best_rank = (value, source, conf), rank
    return best


def build_identity_row(
    patent_id: str,
    batch: str,
    meta: dict,
    batch_meta: dict | None = None,
    gaz_hit: dict | None = None,
    powertrain_pred: dict | None = None,
    industry_pred: dict | None = None,
    name_candidates: list[dict] | None = None,
    spec_hints: dict | None = None,
    llm_answer: dict | None = None,
) -> tuple[dict, list[dict]]:
    """Merge every signal for one patent into (identity_row, evidence_rows).

    `meta` is the PatSeer excel entry (extractor.load_patseer_excel), and
    `batch_meta` the batches.xlsx row (company_canonical / prototype_label).
    Every argument beyond those is optional so the notebook can run any subset
    of the stages — gazetteer-only, or SBERT without the LLM — and still get a
    well-formed sheet.
    """
    batch_meta = batch_meta or {}
    gaz_hit = gaz_hit or {}
    llm_answer = llm_answer or {}
    spec_hints = spec_hints or {}
    name_candidates = name_candidates or []
    evidence: list[dict] = []

    def _ev(field, value, source, conf, context=""):
        if value not in (None, ""):
            evidence.append({
                "patent_id": patent_id, "field": field, "candidate_value": value,
                "source": source, "confidence": conf, "context": context,
            })

    assignee_raw = meta.get("assignee")
    company = (batch_meta.get("company_canonical")
               or (_normalise_company(assignee_raw) if assignee_raw else None))
    country = assignee_country(assignee_raw)
    office = publication_office(patent_id)

    # ── aircraft_name ────────────────────────────────────────────────────────
    gaz_name = gaz_hit.get("aircraft_name") or None
    llm_name = llm_answer.get("aircraft_name") or None
    best_regex = name_candidates[0] if name_candidates else {}

    _ev("aircraft_name", gaz_name, "gazetteer", gaz_hit.get("_confidence"),
        gaz_hit.get("_match", ""))
    _ev("aircraft_name", llm_name, "llm", llm_answer.get("confidence"),
        (llm_answer.get("reasoning") or "")[:300])
    for cand in name_candidates:
        _ev("aircraft_name", cand["value"], cand["source"], cand["confidence"],
            cand.get("context", ""))

    name, name_src, name_conf = _pick([
        (gaz_name, "gazetteer", gaz_hit.get("_confidence")),
        (llm_name, "llm", llm_answer.get("confidence")),
        (best_regex.get("value"), best_regex.get("source"), best_regex.get("confidence")),
    ])
    alternatives = "; ".join(
        dict.fromkeys(                      # de-dupe, keep order
            [c["value"] for c in name_candidates if c["value"] != name]
            + ([gaz_hit["_candidates"]] if gaz_hit.get("_candidates") else [])
        )
    )

    # ── powertrain / is_electric ─────────────────────────────────────────────
    powertrain_pred = powertrain_pred or {}
    gaz_pt = gaz_hit.get("powertrain") or None
    llm_pt = llm_answer.get("powertrain") or None

    _ev("powertrain", gaz_pt, "gazetteer", gaz_hit.get("_confidence"), gaz_hit.get("_match", ""))
    _ev("powertrain", llm_pt, "llm", llm_answer.get("confidence"), "")
    _ev("powertrain", powertrain_pred.get("value"), powertrain_pred.get("source"),
        powertrain_pred.get("confidence"), f"margin={powertrain_pred.get('margin')}")

    powertrain, pt_src, pt_conf = _pick([
        (gaz_pt, "gazetteer", gaz_hit.get("_confidence")),
        (llm_pt, "llm", llm_answer.get("confidence")),
        (powertrain_pred.get("value"), powertrain_pred.get("source"),
         powertrain_pred.get("confidence")),
    ])
    # is_electric is derived from powertrain rather than predicted separately —
    # one source of truth, so the two columns can never contradict each other.
    is_electric = ELECTRIC_BY_POWERTRAIN.get(powertrain, "Unknown") if powertrain else "Unknown"

    # ── industry ─────────────────────────────────────────────────────────────
    industry_pred = industry_pred or {}
    llm_ind = llm_answer.get("industry_primary") or None
    _ev("industry_primary", llm_ind, "llm", llm_answer.get("confidence"), "")
    _ev("industry_primary", industry_pred.get("value"), industry_pred.get("source"),
        industry_pred.get("confidence"), f"margin={industry_pred.get('margin')}")

    industry, ind_src, ind_conf = _pick([
        (llm_ind, "llm", llm_answer.get("confidence")),
        (industry_pred.get("value"), industry_pred.get("source"),
         industry_pred.get("confidence")),
    ])

    # ── specs ────────────────────────────────────────────────────────────────
    specs: dict[str, object] = {}
    spec_srcs: list[str] = []
    spec_confs: list[float] = []
    for field in SPEC_FIELDS:
        gaz_v = _to_float(gaz_hit.get(field)) if gaz_hit.get(field) else None
        llm_v = llm_answer.get(field)
        hint = spec_hints.get(field) or {}

        _ev(field, gaz_v, "gazetteer", gaz_hit.get("_confidence"),
            gaz_hit.get("spec_source", ""))
        _ev(field, llm_v, "llm", llm_answer.get("confidence"), "")
        _ev(field, hint.get("value"), "regex", hint.get("confidence"), hint.get("context", ""))

        value, src, conf = _pick([
            (gaz_v, "gazetteer", gaz_hit.get("_confidence")),
            (llm_v, "llm", llm_answer.get("confidence")),
            (hint.get("value"), "regex", hint.get("confidence")),
        ])
        specs[field] = value
        if value is not None:
            spec_srcs.append(src)
            if conf is not None:
                spec_confs.append(float(conf))

    # ── review routing ───────────────────────────────────────────────────────
    reasons: list[str] = []
    if not name:
        reasons.append("no aircraft name")
    elif (name_conf or 0) < NEEDS_REVIEW_BELOW:
        reasons.append("low-confidence name")
    if not powertrain:
        reasons.append("no powertrain")
    elif (pt_conf or 0) < NEEDS_REVIEW_BELOW:
        reasons.append("low-confidence powertrain")
    if gaz_hit.get("_match") == "ambiguous":
        reasons.append("multiple gazetteer aircraft for this company")
    if not any(specs.values()):
        reasons.append("no specifications")

    row = {
        "patent_id": patent_id,
        "batch": batch,
        "company_canonical": company,
        "assignee_raw": assignee_raw,
        "prototype_label": batch_meta.get("prototype_label"),
        "app_year": meta.get("app_year"),
        "pub_year": meta.get("pub_year"),
        "title": meta.get("title"),
        "pub_office": office,
        "assignee_country": country,
        "region": region_for(country, office),
        "aircraft_name": name,
        "aircraft_name_source": name_src,
        "aircraft_name_confidence": round(name_conf, 4) if name_conf is not None else None,
        "aircraft_name_alternatives": alternatives or None,
        "is_electric": is_electric,
        "powertrain": powertrain,
        "powertrain_source": pt_src,
        "powertrain_confidence": round(pt_conf, 4) if pt_conf is not None else None,
        "industry_primary": industry,
        "industry_source": ind_src,
        "industry_confidence": round(ind_conf, 4) if ind_conf is not None else None,
        **specs,
        "spec_source": "; ".join(sorted(set(spec_srcs))) or None,
        "spec_confidence": round(sum(spec_confs) / len(spec_confs), 4) if spec_confs else None,
        # Filled by attach_scope() once src/patent_scope.py has run — it needs
        # the resolved aircraft_name, so it cannot run before this point.
        **{c: None for c in _SCOPE_COLUMNS},
        "needs_review": bool(reasons),
        "review_reason": "; ".join(reasons) or None,
        "llm_reasoning": (llm_answer.get("reasoning") or None),
        "reviewed_by": None,
        "reviewed_at": None,
        "notes": None,
    }
    return row, evidence


def attach_scope(row: dict, scope_row: dict) -> dict:
    """Fold src/patent_scope.build_scope_row()'s columns into an identity row.

    Runs AFTER build_identity_row() because specificity depends on the resolved
    aircraft_name and its source, and mutates `row` in place (returning it for
    convenience). Two things change beyond adding columns:

      1. `needs_review` / `review_reason` are re-derived, so a row whose name
         is only company-attributed is flagged even when every other field is
         confidently filled — that is exactly the row a reviewer must look at.
      2. "no aircraft name" stops counting as a review reason for a genuinely
         component-level patent. There is no aircraft to name, so demanding one
         would flag most of the corpus and drown the rows that matter.
    """
    row.update({k: scope_row.get(k) for k in _SCOPE_COLUMNS})

    reasons = [r for r in (row.get("review_reason") or "").split("; ") if r]
    spec = scope_row.get("specificity")

    if spec == "IllustrativeOnly" and "no aircraft name" in reasons:
        reasons.remove("no aircraft name")
        reasons.append("component/subsystem patent — no aircraft expected")

    if row.get("aircraft_link") == "CompanyAttributed":
        reasons.append("aircraft name is company-attributed, not depicted")
    if scope_row.get("architecture_pure") is False:
        reasons.append(f"covers {scope_row.get('architecture_count')} architectures")
    if (scope_row.get("specificity_confidence") or 0) < NEEDS_REVIEW_BELOW:
        reasons.append("low-confidence specificity call")

    row["needs_review"] = bool(reasons)
    row["review_reason"] = "; ".join(dict.fromkeys(reasons)) or None
    return row


# ─── Excel export ────────────────────────────────────────────────────────────

from src.patent_scope import SCOPE_OPTIONS as _SCOPE_OPTIONS_DOC

_README_ROWS = [
    ("SHEET: Identity", "One row per patent — the table to join onto your label data."),
    ("SHEET: Evidence", "Every candidate every signal proposed, with its context. "
                        "Use it to audit or override a value in Identity."),
    ("SHEET: Figures", "One row per figure, from the Brief Description of the "
                       "Drawings: what KIND of view each figure is. This is a "
                       "text-level judgment — it does not look at the image."),
    ("SHEET: LLM_Prompts", "Per-patent prompt for the chat step. Paste the reply into "
                           "llm_answer, then re-run the notebook's ingest cell."),
    ("", ""),
    ("scope", "Granularity of the disclosure: " + _SCOPE_OPTIONS_DOC),
    ("architecture_primary", "eVTOL configuration class (wizard G1 code); "
                             "architecture_primary_label is the readable name."),
    ("architecture_all", "EVERY architecture the patent represents. More than one "
                         "means the patent enumerates alternatives rather than "
                         "describing a single vehicle."),
    ("architecture_count / architecture_pure",
     "Predicted counterparts of the wizard's manual archCount / notPureArch. "
     "When architecture_pure is FALSE, architecture_primary is whichever one "
     "the keyword pass hit first and is NOT meaningful on its own — read "
     "architecture_all instead, and exclude those rows from any chart that "
     "counts patents per architecture."),
    ("specificity", "SpecificAircraft = the disclosure is one whole-aircraft "
                    "architecture whose figures show complete vehicles. "
                    "ArchitectureGeneric = tied to a configuration class but not "
                    "to a particular aircraft. IllustrativeOnly = a subsystem or "
                    "component idea; the airframe in the drawings is a carrier, "
                    "not the subject."),
    ("specificity_reason", "Every signal that fired, with its weight. The verdict "
                           "is an additive rule over these — re-threshold in the "
                           "thesis without re-running anything."),
    ("aircraft_link", "Depicted = this patent's figures show that aircraft. "
                      "CompanyAttributed = the company makes it, but this patent "
                      "is about a subsystem/component and its figures are NOT "
                      "evidence of that aircraft. Filter on this before any "
                      "per-aircraft statistic."),
    ("figures_whole_aircraft", "How many figures show a complete aircraft. Zero, "
                               "with figures present, is the strongest single "
                               "signal that the drawings are illustrative."),
    ("", ""),
    ("aircraft_name", "Best guess at the real aircraft. Empty = unknown, which is the "
                      "expected outcome for most patents."),
    ("*_source", "Where the value came from: gazetteer > llm > sbert > keyword > regex. "
                 "Set it to 'human' after you correct a value and a re-run will keep it."),
    ("*_confidence", "0-1. Below 0.55 the row is flagged in needs_review."),
    ("is_electric", "Yes | Hybrid | No | Unknown — derived from powertrain, never "
                    "predicted separately."),
    ("powertrain", "|".join(POWERTRAIN_DEFS)),
    ("industry_primary", "|".join(INDUSTRY_DEFS)),
    ("region", "From the assignee's country code; falls back to the publication office."),
    ("Units", "mass kg | speed km/h | range km | endurance minutes | pax persons"),
    ("needs_review", "TRUE when a key field is missing or low-confidence. "
                     "review_reason says which."),
    ("Specs caution", "A spec with source='regex' came from the patent text and is "
                      "usually an illustrative embodiment, not the built aircraft. "
                      "Verify before citing."),
]


def _backup(path: Path) -> Path | None:
    """Timestamped backup before overwriting — same convention as scripts/."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path.with_name(f"{path.stem}.BACKUP_{stamp}{path.suffix}")
    dest.write_bytes(path.read_bytes())
    return dest


def merge_preserving_human(new_df, out_path: Path):
    """Carry human edits from an existing sheet onto a freshly computed one.

    Two things survive a re-run: the HUMAN_COLUMNS (notes, reviewer, and any
    pasted llm_answer), and any field whose `*_source` was set to "human" —
    that is the escape hatch for correcting a value the pipeline got wrong
    without having to freeze the whole file.
    """
    import pandas as pd

    if not out_path.exists():
        return new_df
    try:
        old = pd.read_excel(out_path, sheet_name="Identity", dtype=object)
    except (ValueError, KeyError):
        return new_df
    if "patent_id" not in old.columns:
        return new_df

    old = old.set_index("patent_id")
    merged = new_df.copy().set_index("patent_id")

    for pid in merged.index:
        if pid not in old.index:
            continue
        old_row = old.loc[pid]
        if isinstance(old_row, type(merged)):        # duplicate patent_id rows
            old_row = old_row.iloc[0]

        for col in HUMAN_COLUMNS:
            if col in old.columns and pd.notna(old_row.get(col)):
                merged.at[pid, col] = old_row[col]

        # Field-level human overrides, keyed off the *_source column.
        for value_col, source_col in (
            ("aircraft_name", "aircraft_name_source"),
            ("powertrain", "powertrain_source"),
            ("industry_primary", "industry_source"),
        ):
            if source_col in old.columns and str(old_row.get(source_col)).lower() == "human":
                merged.at[pid, value_col] = old_row.get(value_col)
                merged.at[pid, source_col] = "human"
                conf_col = source_col.replace("_source", "_confidence")
                if conf_col in merged.columns:
                    merged.at[pid, conf_col] = _CONF_HUMAN
        if "spec_source" in old.columns and str(old_row.get("spec_source")).lower() == "human":
            for f in SPEC_FIELDS:
                if f in old.columns:
                    merged.at[pid, f] = old_row.get(f)
            merged.at[pid, "spec_source"] = "human"
            merged.at[pid, "spec_confidence"] = _CONF_HUMAN

    # is_electric is derived, so recompute it after any human powertrain edit
    # rather than letting the two columns drift apart.
    merged["is_electric"] = merged["powertrain"].map(
        lambda p: ELECTRIC_BY_POWERTRAIN.get(p, "Unknown") if p else "Unknown"
    )
    return merged.reset_index()


def export_identity_excel(
    rows: list[dict],
    evidence: list[dict],
    prompts: list[dict],
    out_path: "str | Path",
    preserve_human: bool = True,
    figures: list[dict] | None = None,
) -> Path:
    """Write aircraft_identity_<batch>.xlsx.

    Sheets: Identity / Figures / Evidence / LLM_Prompts / README.

    Backs up any existing file first, then merges human edits forward, so this
    is safe to re-run over a sheet you have already been editing.
    """
    import pandas as pd

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ident_df = pd.DataFrame(rows, columns=IDENTITY_COLUMNS)
    if preserve_human and out_path.exists():
        ident_df = merge_preserving_human(ident_df, out_path)
        ident_df = ident_df.reindex(columns=IDENTITY_COLUMNS)

    ev_df   = pd.DataFrame(evidence, columns=EVIDENCE_COLUMNS)
    pr_df   = pd.DataFrame(prompts,  columns=PROMPT_COLUMNS)
    if preserve_human and out_path.exists():
        try:
            old_pr = pd.read_excel(out_path, sheet_name="LLM_Prompts", dtype=object)
            answers = dict(zip(old_pr.get("patent_id", []), old_pr.get("llm_answer", [])))
            pr_df["llm_answer"] = pr_df["patent_id"].map(answers)
        except (ValueError, KeyError):
            pass

    from src.patent_scope import FIGURE_COLUMNS
    fig_df = pd.DataFrame(figures or [], columns=FIGURE_COLUMNS)
    readme_df = pd.DataFrame(_README_ROWS, columns=["Item", "Meaning"])

    _backup(out_path)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        ident_df.to_excel(writer, sheet_name="Identity", index=False)
        fig_df.to_excel(writer, sheet_name="Figures", index=False)
        ev_df.to_excel(writer, sheet_name="Evidence", index=False)
        pr_df.to_excel(writer, sheet_name="LLM_Prompts", index=False)
        readme_df.to_excel(writer, sheet_name="README", index=False)

        # Freeze the header row and widen the columns people actually read —
        # the Identity sheet is meant to be looked at, not just joined.
        ws = writer.sheets["Identity"]
        ws.freeze_panes = "B2"
        for idx, col in enumerate(IDENTITY_COLUMNS, start=1):
            width = 42 if col in ("title", "llm_reasoning", "aircraft_name_alternatives") else \
                    28 if col in ("assignee_raw", "company_canonical", "review_reason") else 16
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width

    return out_path
