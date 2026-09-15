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
# A keyword in the short, dense fields is about this invention; one in the body
# may sit in a prior-art passage. Both are literal and quotable, so both decide
# is_electric (they clear _CONF_ELECTRIC_FLOOR) — the section column says which.
_CONF_KEYWORD_SIGNAL = 0.80
_CONF_KEYWORD_BODY = 0.65
# A body sentence that does not COMMIT — "an electric motor or an engine", "such
# drones are typically battery powered". The proposal and its quote are kept so
# the reviewer can see what was found, but the confidence stays under
# _CONF_ELECTRIC_FLOOR so is_electric abstains and the row stays in the queue.
_CONF_KEYWORD_BODY_HEDGED = 0.35
# Ruling 2026-09-13 (user): "if electric is an alternative, it can still be
# considered electric". An electric family offered as ONE OPTION — "an electric
# or hydraulic motor", "may be an internal combustion engine, an electric motor,
# or…" — counts as a statement that the aircraft can be electric. Above the
# floor so it decides; below a committed sentence so the sheet can tell them
# apart (confidence 0.60 == "electric by option"). Only prior-art framing
# ("such drones are typically battery powered") still counts for nothing: it is
# about other aircraft.
_CONF_KEYWORD_ALTERNATIVE = 0.60
ELECTRIC_OPTION_FAMILIES = {"BatteryElectric", "HydrogenFuelCell", "HybridElectric"}

# An explicit disjunction: the sentence offers this energy source as one option
# among others. "or an engine" needs its own test — a bare "engine" matches none
# of POWERTRAIN_KEYWORDS, so counting families would miss exactly the phrasing
# patent attorneys reach for most.
_NONCOMMITTAL_RE = re.compile(
    r"\bor\s+(?:an?\s+|any\s+|some\s+)?(?:other\s+)?"
    r"(?:engines?|motors?|combustion|turbines?|prime\s+movers?|"
    r"power\s*(?:plants?|sources?|units?)|energy\s+sources?)\b"
    r"|\bor\s+the\s+like\b"
    r"|\bany\s+other\s+(?:known\s+)?(?:type|kind|form|source|means)\b",
    re.IGNORECASE)

# For a COMBUSTION family only: a modal, an enumeration, an alternative
# embodiment or a contrast is not a statement that THIS aircraft burns fuel.
# Asymmetric on purpose — the burden of proof is on NOT electric, so a
# combustion mention must be firm ("the rotor is driven by a turboshaft
# engine", "wherein the engine is a gas turbine") before it decides anything,
# while an electric mention only ever confirms the presumption. Measured on the
# corpus: without this, 7 of 8 "both families stated" rows were background
# prose ("fixed-wing aircraft ... thrust from one or more jet engines or
# propellers") or options ("152 may include a gas turbine").
_MODAL_COMBUSTION_RE = re.compile(
    r"\b(?:may|might|can|could|would|should|alternatively|optionally|such\s+as|for\s+example|"
    r"e\.g\.|contemplated|envisaged|in\s+(?:some|other|another|certain|alternative|various|"
    r"further|one|an|any)\s+embodiments?|have\s+been\s+developed|recently|historically|"
    r"are\s+known|unlike|as\s+opposed\s+to|compared\s+(?:to|with)|rather\s+than|instead\s+of|"
    r"fixed[-\s]wing\s+aircraft|helicopters\s+(?:are|use|have))\b", re.IGNORECASE)

# Prior-art framing: the sentence is about what other aircraft do.
_PRIOR_ART_RE = re.compile(
    r"\b(typically|conventional(?:ly)?|prior\s+art|traditional(?:ly)?|generally|"
    r"commonly|hitherto|in\s+the\s+past|existing\s+\w+\s+(?:are|use)|well[-\s]known|"
    r"other\s+(?:known\s+)?(?:vtol\s+)?aircraft\s+(?:are|use))\b", re.IGNORECASE)

POWERTRAIN_KEYWORDS: list[tuple[str, str]] = [
    (r"\bfuel\s*cell\b|\bhydrogen\b|\bH2\s+(?:tank|storage)\b", "HydrogenFuelCell"),
    (r"\bhybrid[-\s]?electric\b|\bturbo\s*generator\b|\bturbogenerator\b"
     r"|\brange\s+extender\b|\bseries\s+hybrid\b|\bgenerator\s+set\b"
     # an engine driving a generator IS a hybrid, whether or not the word appears
     r"|\bengine\b[^.;]{0,80}\bgenerator\b|\bgenerator\b[^.;]{0,80}\bengine\b", "HybridElectric"),
    (r"\bbatter(?:y|ies)\b|\ball[-\s]?electric\b|\belectrically[-\s]+(?:powered|driven|propelled)\b"
     r"|\belectric(?:al)?[-\s]+(?:motors?|propulsion|powertrain|drive|power\s+(?:source|supply|plant)|engines?|aircraft|vehicle|VTOL)\b"
     r"|\bdistributed\s+electric\s+propulsion\b|\bDEP\b|\beVTOL\b|\be-?motor\b"
     # "an electric or hydraulic motor" — the option phrasing Bell's boilerplate uses
     r"|\belectric(?:al)?\s+(?:or|and|and/or)\s+\w+(?:\s+\w+)?\s+motors?\b", "BatteryElectric"),
    (r"\bturbo\s*shaft\b|\bturboshaft\b|\bturbo\s*prop\b|\bgas\s+turbine\b|\bturbine\s+engines?\b"
     r"|\bjet\s+engines?\b|\bturbofan\b|\bturbojet\b", "Turbine"),
    (r"\binternal\s+combustion\s+engine\b|\bcombustion\s+engines?\b|\bpiston\s+engine\b"
     r"|\breciprocating\s+engine\b|\bgasoline\b|\bdiesel\b|\bpetrol\b", "Piston"),
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

# Below this, a powertrain that SBERT alone proposed is not allowed to decide
# is_electric. Mirrors identity_schema.NEEDS_REVIEW_BELOW, which cannot be
# imported here (identity_schema imports THIS module) — the duplication is
# pinned by test_electric_floor_matches_the_review_threshold.
_CONF_ELECTRIC_FLOOR = 0.55


def electric_verdict(powertrain: str | None, source: str | None = None,
                     confidence: float | None = None,
                     company_all_electric: bool = False,
                     stated: bool = True,
                     presume_electric: bool = False) -> tuple[str, str | None]:
    """is_electric from powertrain — refusing to answer on a near-chance guess.

    Anything below _CONF_ELECTRIC_FLOOR abstains, whatever its source.
    Measured on the real corpus (2026-09-08): PatentSBERTa's zero-shot
    powertrain scores have a median margin of 0.30 and a maximum of 0.59, so
    letting them through would put "No" — the reviewer's disapproval verdict —
    on 209 patents on the strength of a coin-flip. The same floor catches a body
    sentence that names an option rather than a commitment. The proposal still
    shows in `powertrain` with its own source and confidence; only the derived
    verdict abstains, because that is the column a human acts on.

    A keyword (0.80) or gazetteer (0.70-0.95) powertrain always decides. Where
    it would otherwise abstain, a company that builds nothing but battery-
    electric aircraft decides instead (`company_all_electric`, from
    aircraft_gazetteer.all_electric_companies).

    `stated` is whether ANY propulsion family was committed to in the text.
    With `presume_electric`, a patent that states nothing at all is marked
    ("Unknown", "presumed"): this is an eVTOL corpus the annotator approved
    patent by patent, so the burden is on finding evidence it is NOT electric,
    and a row with no such evidence is not queued. The verdict stays Unknown —
    "presumed" is a source, not a fact.

    Returns (verdict, source) — the source is what the sheet shows in
    `is_electric_source`, so an abstention and a company call never look alike.
    """
    verdict, verdict_source = "Unknown", None
    if powertrain:
        # The floor is about the strength of the evidence, not where it came
        # from: it catches a 0.30 SBERT similarity and an equally weak
        # non-committal body sentence ("an electric motor or an engine") alike.
        if (confidence or 0) >= _CONF_ELECTRIC_FLOOR:
            verdict = ELECTRIC_BY_POWERTRAIN.get(powertrain, "Unknown")
            verdict_source = source if verdict != "Unknown" else None
    if verdict == "Unknown" and company_all_electric:
        return "Yes", "company"
    if verdict == "Unknown" and presume_electric and not stated:
        return "Unknown", "presumed"
    return verdict, verdict_source


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

def _sentence_around(text: str, lo: int, hi: int, window: int = 220) -> str:
    """The sentence the match sits in — the unit a commitment is judged on."""
    start, end = max(0, lo - window), min(len(text), hi + window)
    head, tail = text[start:lo], text[hi:end]
    m = list(re.finditer(r"[.;:!?]\s+|\n", head))
    if m:
        head = head[m[-1].end():]
    m = re.search(r"[.;!?](?:\s|$)|\n", tail)
    if m:
        tail = tail[:m.end()]
    return " ".join((head + text[lo:hi] + tail).split())


def _families_in(sentence: str) -> set:
    """Which powertrain families this one sentence names.

    A hybrid statement names its parts ("a turbogenerator charging the battery
    that feeds the motors") — that is a commitment to HYBRID, not a hedge
    between three families, so hybrid absorbs the others."""
    fams = {label for pattern, label in POWERTRAIN_KEYWORDS
            if re.search(pattern, sentence, re.IGNORECASE)}
    return {"HybridElectric"} if "HybridElectric" in fams else fams


ELECTRIC_FAMILIES = {"BatteryElectric", "HydrogenFuelCell"}
COMBUSTION_FAMILIES = {"Turbine", "Piston"}
# Retired 2026-09-13: a committed combustion sentence next to an electric one
# used to abstain at this confidence. Under the option rule the electric one
# decides and the combustion one is quoted as "other". Kept for old pickles.
_CONF_KEYWORD_CONFLICT = 0.40


def _committed_hits(text: str | None, conf_ok: float) -> dict:
    """Every propulsion family named in `text`, with its best sentence.

    For each family: the first COMMITTED sentence if there is one, else the
    first sentence that offers the family as an OPTION (electric families only —
    an option counts, rule 2026-09-13), else the first hedged one (kept so the
    reviewer can see what was found, at a confidence that decides nothing).

    Each hit carries `hedged` (decides nothing) and `alternative` (electric
    offered as one option among others: decides, at _CONF_KEYWORD_ALTERNATIVE).
    """
    out: dict = {}
    if not text or not str(text).strip():
        return out
    text = str(text)
    for pattern, label in POWERTRAIN_KEYWORDS:
        best = None
        for m in re.finditer(pattern, text, re.IGNORECASE):
            sentence = _sentence_around(text, m.start(), m.end())
            prior_art = bool(_PRIOR_ART_RE.search(sentence))
            option = (len(_families_in(sentence)) > 1
                      or bool(_NONCOMMITTAL_RE.search(sentence))
                      or bool(_MODAL_COMBUSTION_RE.search(sentence))
                      or bool(re.search(r"\b(?:or|and/or)\b", m.group(0), re.IGNORECASE)))
            if label in ELECTRIC_OPTION_FAMILIES:
                hedged, alternative = prior_art, (option and not prior_art)
            else:
                hedged, alternative = (prior_art or option), False
            rank = 2 if hedged else (1 if alternative else 0)
            hit = {"pattern": pattern, "match": m.group(0), "hedged": hedged,
                   "alternative": alternative, "rank": rank,
                   "confidence": (_CONF_KEYWORD_BODY_HEDGED if hedged
                                  else _CONF_KEYWORD_ALTERNATIVE if alternative else conf_ok)}
            if best is None or rank < best["rank"]:
                best = hit
            if rank == 0:
                break
        if best:
            out[label] = best
    return out


def detect_powertrain_families(text: str | None, body_text: str | None = None) -> dict:
    """{family: hit} across the signal text and the body — the signal text
    wins for a family both mention, unless the body's sentence is firmer
    (committed beats option beats hedged)."""
    fam = _committed_hits(text, _CONF_KEYWORD_SIGNAL)
    for label, hit in _committed_hits(body_text, _CONF_KEYWORD_BODY).items():
        if label not in fam or hit["rank"] < fam[label]["rank"]:
            fam[label] = hit
    return fam


def classify_powertrain(text: str | None, sbert_model=None,
                        body_text: str | None = None) -> dict:
    """Energy source, decided the way a reviewer would decide it.

    It is easy to show an aircraft is NOT electric — one committed sentence
    naming a turbine or a piston engine as the propulsion — and nearly
    impossible to show it IS, because every aircraft has an electric motor
    somewhere. So every family is collected first (`detect_powertrain_families`)
    and then, in order:

        hybrid stated                       -> HybridElectric
        electric stated, or offered as an   -> the electric one (Yes). A firmly
          OPTION among others                  stated turbine / piston next to it
          (rule 2026-09-13)                    is quoted as "other", not a conflict
        combustion stated, no electric      -> Turbine / Piston (the row is
                                               queued: a machine never disapproves)
        only hedged / prior-art mentions    -> the first one, under the floor
        nothing                             -> SBERT's guess, under the floor
                                               (and is_electric may be PRESUMED
                                               electric — see electric_verdict)

    "other" names the second family when two were stated, so the sheet can
    quote both; "basis" is "alternative" when the electric family was only
    offered as an option. Returns the pipeline's standard prediction dict.
    """
    fam = detect_powertrain_families(text, body_text)
    committed = [label for label, h in fam.items() if not h["hedged"]]
    firm = [label for label, h in fam.items() if h["rank"] == 0]

    def pick(label, other=None, conf=None):
        h = fam[label]
        return {"value": label, "source": "keyword", "margin": 1.0,
                "confidence": h["confidence"] if conf is None else conf,
                "pattern": h["pattern"], "match": h["match"],
                "basis": "alternative" if h.get("alternative") else "stated",
                "families": fam, "other": other,
                "other_pattern": fam[other]["pattern"] if other else None}

    elec = sorted((l for l in committed if l in ELECTRIC_FAMILIES), key=lambda l: fam[l]["rank"])
    comb = [l for l in firm if l in COMBUSTION_FAMILIES]
    if "HybridElectric" in firm:
        return pick("HybridElectric", other=(comb or elec or [None])[0])
    if elec:
        return pick(elec[0], other=(comb or [None])[0])
    if "HybridElectric" in committed:                  # hybrid offered as an option
        return pick("HybridElectric", other=(comb or [None])[0])
    if comb:
        return pick(comb[0])
    if fam:                                            # hedged mentions only
        label = next(iter(fam))
        return {**pick(label, conf=_CONF_KEYWORD_BODY_HEDGED), "hedged": True}
    if not text or not str(text).strip():
        return {"value": None, "confidence": 0.0, "source": None, "families": {}}
    return {**_margin_flag(_sbert_best(text, POWERTRAIN_DEFS, sbert_model)), "families": {}}


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

