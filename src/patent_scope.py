"""
patent_scope.py — what a patent is actually ABOUT, at what granularity, and
whether it is tied to one real aircraft or is a generic idea illustrated on a
throwaway airframe.

Stage 03a's companion to aircraft_identity.py. That module answers "which
aircraft"; this one answers the prior question that decides whether "which
aircraft" is even a meaningful thing to ask:

  1. GRANULARITY   scope — whole aircraft architecture / architectural
                   subsystem enabler / component-level generic.
  2. DISCIPLINE    innovation_field — aero-structural, mechanical-kinematic,
                   propulsion-electrical, control-avionics.
  3. ARCHITECTURE  which eVTOL configuration(s) the patent represents, and
                   crucially HOW MANY — a patent that enumerates "a multirotor,
                   a tiltrotor or a lift-plus-cruise vehicle" is not describing
                   any of them.
  4. SPECIFICITY   is this patent's disclosure tied to one identifiable
                   aircraft, or is the drawing just a plausible carrier for a
                   component idea?

Why (4) matters more than it looks
----------------------------------
The gazetteer in aircraft_identity.py matches on COMPANY. Left alone, a Joby
patent on a motor bearing gets `aircraft_name = S4` with a 0.95 confidence,
because Joby's aircraft is the S4 — and that is a real error, not a rounding
one: the drawing in that patent is a generic airframe cartoon, and treating it
as an S4 figure pollutes every downstream statistic that groups by aircraft.

So `aircraft_link` separates the two relationships that were previously
conflated:

    Depicted           the patent's own drawings show this aircraft
    CompanyAttributed  the company makes this aircraft, but this patent is
                       about a subsystem or component and its figures are
                       illustrative
    None               no aircraft could be linked at all

Nothing is deleted — a CompanyAttributed row keeps its name — but the column
says which kind of claim it is, and a thesis table can filter on it.

Reuse, not reinvention
----------------------
The three taxonomies here are the ones the pipeline already uses, imported
from src/reviewer.py rather than restated, so a prediction made here means
exactly what the same label means in the HTML wizard and in
ml_predict_labels_<batch>.xlsx:

    _T1_SCOPE_DEFS      granularity (already the architecture/subsystem/component split)
    _T1_FIELD_DEFS      discipline
    _G1_TOP_TYPE_DEFS   architecture topology  (+ classify_g1_keyword's prior)

`architecture_count` and `architecture_pure` predict the wizard's own manual
`archCount` and `notPureArch` fields (see excel_schema._T1_MANUAL / _G1_MANUAL),
so the reviewer gets a starting value instead of an empty cell.

Public API
----------
classify_scope(text, sbert_model)                 -> dict
classify_innovation_field(text, sbert_model)      -> dict
architectures_present(text, sbert_model)          -> dict
generic_language_score(text)                      -> dict
split_drawing_lines(description_of_drawings)      -> list[dict]
classify_figure_views(description_of_drawings, sbert_model) -> list[dict]
assess_specificity(...)                           -> dict
aircraft_link_for(specificity, aircraft_name, ...) -> str
build_scope_row(...)                              -> tuple[dict, list[dict]]
"""

from __future__ import annotations

import re

from src.reviewer import (
    _T1_SCOPE_DEFS, _T1_FIELD_DEFS, _G1_TOP_TYPE_DEFS,
    _sbert_best, _margin_flag, classify_g1_keyword, _G1_KEYWORD_RULES,
)

# Re-exported so callers and tests have one import site for the vocabularies.
SCOPE_DEFS        = _T1_SCOPE_DEFS
FIELD_DEFS        = _T1_FIELD_DEFS
ARCHITECTURE_DEFS = _G1_TOP_TYPE_DEFS

SCOPE_OPTIONS = "|".join(SCOPE_DEFS)
FIELD_OPTIONS = "|".join(FIELD_DEFS)
ARCH_OPTIONS  = "|".join(ARCHITECTURE_DEFS)

# Human-readable architecture names for the exported sheet — the wizard's
# two-letter codes are unreadable in a thesis table.
ARCHITECTURE_LABELS = {
    "TW":  "Tilt-Wing",
    "TP":  "Tilt-Propulsor",
    "DS":  "Deflected Slipstream",
    "CVT": "Combined (fixed lift + tilting cruise)",
    "SLC": "Lift + Cruise",
    "SRW": "Stopped-Rotor Wing",
    "RC":  "Rotorcraft",
    "MR":  "Multirotor",
    "HB":  "Hoverbike",
    "PFV": "Personal Flying Vehicle",
}


# ─── Granularity: whole aircraft vs subsystem vs component ───────────────────
# A keyword prior in front of SBERT, for the same reason the powertrain
# classifier has one: claim preambles are formulaic. "An aircraft comprising a
# fuselage, a wing and a plurality of rotors" is a whole-architecture claim;
# "A bearing assembly for an electric motor" is a component claim. SBERT reads
# both as "about an aircraft" because both are, at 384 tokens, mostly aircraft
# nouns — the giveaway is the grammatical shape of the preamble, not the topic.

_SCOPE_WHOLE = "Whole Aircraft Architecture"
_SCOPE_SUBSYS = "Architectural Subsystem Enabler"
_SCOPE_COMPONENT = "Component-Level Generic"

# Ordered most-specific-first; first hit wins. Component patterns come first
# because a component claim almost always also names the aircraft it goes in
# ("a rotor hub FOR AN aircraft"), so a whole-aircraft rule would false-fire.
_SCOPE_KEYWORD_RULES: list[tuple[str, str]] = [
    # "<part> for a/an <aircraft>" — the canonical component-claim preamble.
    (r"^\s*(?:a|an)\s+[\w\s\-]{0,40}?"
     r"(?:assembly|bearing|bracket|fastener|connector|housing|seal|winding|"
     r"stator|rotor\s+hub|blade|spar|rib|linkage|actuator|gearbox|inverter|"
     r"busbar|cell|module|circuit|sensor|valve|damper|coupling|hinge)\b"
     r"[\w\s\-,]{0,60}?\bfor\s+(?:an?\s+)?(?:aircraft|vehicle|rotorcraft|eVTOL)",
     _SCOPE_COMPONENT),
    # Method/system claims scoped to one function rather than a vehicle.
    (r"^\s*(?:a|an)\s+(?:method|system|apparatus|arrangement)\s+(?:of|for)\s+"
     r"(?:controlling|monitoring|cooling|charging|detecting|manufacturing|"
     r"assembling|balancing|damping)\b", _SCOPE_SUBSYS),
    # Mechanism/enabler language: the thing that makes an architecture work.
    (r"\b(?:tilt|tilting|folding|fold|pivot|pivoting|retraction|deployment|"
     r"transition)\s+(?:mechanism|assembly|linkage|actuator|system)\b",
     _SCOPE_SUBSYS),
    # Whole-vehicle claim preamble: "An aircraft comprising ..." with the
    # airframe nouns that only appear when the whole vehicle is being claimed.
    # Three things this has to tolerate, all of which appear constantly and each
    # of which silently produced a blank scope before:
    #   - an adjective between article and noun ("A MULTIROTOR aircraft ...")
    #   - verbs other than "comprising" ("... WITH a battery pack and ...")
    #   - a multirotor having no wing, so rotors/propulsors count as the
    #     whole-vehicle noun alongside fuselage/wing/airframe/empennage
    # The component rule above runs first, so "a rotor hub for an aircraft
    # comprising ... rotor" is already claimed by it and cannot reach here.
    (r"^\s*(?:an?\s+)?(?:[\w-]+\s+){0,3}?"
     r"(?:aircraft|air\s+vehicle|rotorcraft|eVTOL|flying\s+vehicle|aerial\s+vehicle)\b"
     r"[\w\s\-,]{0,80}?\b(?:compris\w+|with|having|includ\w+)\b[\w\s\-,]{0,120}?"
     r"\b(?:fuselage|wing|airframe|empennage|rotors?|proprotors?|propulsors?)\b",
     _SCOPE_WHOLE),
]


def classify_scope(text: str | None, sbert_model=None) -> dict:
    """Granularity of the disclosure, over reviewer._T1_SCOPE_DEFS.

    Returns the pipeline's standard {"value", "confidence", "source", "margin"}
    prediction dict. Keyword prior first (see above), SBERT as the fallback,
    margin-flagged so a near-tie between subsystem and component is capped
    below the review threshold rather than presented as a clean call.
    """
    if not text or not str(text).strip():
        return {"value": None, "confidence": 0.0, "source": None}

    # Rules anchored with ^ are meant to match a CLAIM PREAMBLE, so they are
    # tried against each of the first few lines, not the whole blob.
    head = "\n".join(str(text).strip().splitlines()[:8])
    for pattern, label in _SCOPE_KEYWORD_RULES:
        for line in head.splitlines():
            if re.search(pattern, line.strip(), re.IGNORECASE):
                return {"value": label, "confidence": 0.78,
                        "source": "keyword", "margin": 1.0}
        if not pattern.startswith("^") and re.search(pattern, str(text), re.IGNORECASE):
            return {"value": label, "confidence": 0.75,
                    "source": "keyword", "margin": 1.0}

    return _margin_flag(_sbert_best(text, SCOPE_DEFS, sbert_model))


def classify_innovation_field(text: str | None, sbert_model=None) -> dict:
    """Which engineering discipline the innovation sits in (_T1_FIELD_DEFS)."""
    return _margin_flag(_sbert_best(text, FIELD_DEFS, sbert_model))


# ─── Architectures represented ───────────────────────────────────────────────
# Two independent counts, because they fail differently:
#
#   named_architectures  — how many distinct G1 keyword families the text
#     literally names. High precision: "multirotor", "tiltrotor" and
#     "lift plus cruise" all appearing means the applicant is enumerating
#     alternatives. Cannot detect an architecture described without its name.
#
#   sbert_close          — how many architecture definitions score within
#     ARCH_BAND of the winner. Catches the unnamed case, but is noisy on short
#     text, so it only ever RAISES the count when the keyword pass found ≤ 1.

# Cosine band below the top score inside which a runner-up architecture is
# treated as also present. 0.03 is deliberately tight: PatentSBERTa puts every
# eVTOL description in a narrow cone (the whole corpus is one tech domain), so
# a wide band would report every patent as covering all ten architectures.
ARCH_BAND = 0.03

# At or above this many distinct architectures, the patent is enumerating
# possible applications rather than describing one vehicle.
ARCH_COUNT_GENERIC = 3


def architectures_present(text: str | None, sbert_model=None) -> dict:
    """Which architecture(s) the patent represents, and how many.

    Returns:
        {"primary", "primary_label", "all", "all_labels", "count",
         "pure", "confidence", "source", "named_count", "sbert_close"}

    `pure` is False when more than one architecture is present — the predicted
    counterpart of the wizard's manual `notPureArch` checkbox, which asks the
    reviewer the same question.
    """
    empty = {"primary": None, "primary_label": None, "all": [], "all_labels": [],
             "count": 0, "pure": None, "confidence": 0.0, "source": None,
             "named_count": 0, "sbert_close": 0}
    if not text or not str(text).strip():
        return empty

    # ── Keyword pass: distinct architecture families literally named ────────
    hay = re.sub(r"[\s\-]+", " ", str(text).lower())
    named: list[str] = []
    for phrases, value in _G1_KEYWORD_RULES:
        if value in named:
            continue
        for phrase in phrases:
            if re.sub(r"[\s\-]+", " ", phrase.lower()) in hay:
                named.append(value)
                break

    # ── SBERT pass: the winner plus anything inside ARCH_BAND of it ─────────
    close: list[str] = []
    best = _sbert_best(text, ARCHITECTURE_DEFS, sbert_model)
    if sbert_model is not None and best.get("value"):
        import numpy as np

        ids = list(ARCHITECTURE_DEFS)
        temb = sbert_model.encode([text], convert_to_numpy=True, normalize_embeddings=True)
        demb = sbert_model.encode([ARCHITECTURE_DEFS[i] for i in ids],
                                  convert_to_numpy=True, normalize_embeddings=True)
        sims = (demb @ temb.T).flatten()
        top = float(np.max(sims))
        close = [ids[i] for i in range(len(ids)) if float(sims[i]) >= top - ARCH_BAND]

    # ── Primary: the existing keyword prior wins, exactly as in reviewer ────
    kw = classify_g1_keyword(text)
    primary_pred = kw or best
    primary = primary_pred.get("value")

    # The union is the honest answer to "which architectures appear here", but
    # SBERT's near-ties only get to ADD when the keyword pass was inconclusive
    # (0 or 1 family named) — where keywords found several, they are already
    # the better evidence and SBERT noise would only inflate the count.
    if len(named) >= 2:
        present = list(dict.fromkeys(named))
    else:
        present = list(dict.fromkeys(named + close))
    if primary and primary not in present:
        present.insert(0, primary)
    # Keep `primary` first so `all` reads as "primary, then also-present".
    if primary in present:
        present.remove(primary)
        present.insert(0, primary)

    return {
        "primary": primary,
        "primary_label": ARCHITECTURE_LABELS.get(primary),
        "all": present,
        "all_labels": [ARCHITECTURE_LABELS.get(a, a) for a in present],
        "count": len(present),
        "pure": (len(present) <= 1) if present else None,
        "confidence": primary_pred.get("confidence", 0.0),
        "source": primary_pred.get("source"),
        "named_count": len(named),
        "sbert_close": len(close),
    }


# ─── Generic / hedging language ──────────────────────────────────────────────
# Patent boilerplate that widens a disclosure beyond the thing actually built.
# Density, not presence: every patent contains some of this, so what separates
# "here is our aircraft" from "here is a component, usable on anything" is how
# much of the text is hedge.

_GENERIC_PHRASES = [
    "may be", "may include", "may comprise", "can be", "could be",
    "in some embodiments", "in other embodiments", "in various embodiments",
    "in one embodiment", "in another embodiment", "in certain embodiments",
    "for example", "such as", "but not limited to", "without limitation",
    "any suitable", "any other suitable", "any type of", "or the like",
    "and/or", "alternatively", "optionally", "by way of example",
    "it should be understood", "it will be appreciated", "one of ordinary skill",
    "without departing from", "the scope of the invention", "various",
    "generally", "typically", "preferably", "substantially",
]

# Hedge phrases per 100 words. Calibrated on the shape of the language rather
# than on this corpus specifically: an applicant describing a built vehicle
# still hedges, so the threshold sits well above zero.
GENERIC_DENSITY_HIGH = 3.0
GENERIC_DENSITY_LOW  = 1.0


def generic_language_score(text: str | None) -> dict:
    """Density of hedging/boilerplate language, per 100 words.

    Returns {"density", "hits", "words", "level"} where level is
    "high" | "medium" | "low". A short text (< 40 words) returns level
    "unknown": density on two sentences is noise, and reporting it as a
    confident "low" would make abstract-only patents look specific.
    """
    if not text or not str(text).strip():
        return {"density": 0.0, "hits": 0, "words": 0, "level": "unknown"}

    lowered = str(text).lower()
    words = len(lowered.split())
    if words < 40:
        return {"density": 0.0, "hits": 0, "words": words, "level": "unknown"}

    hits = sum(lowered.count(p) for p in _GENERIC_PHRASES)
    density = round(hits * 100.0 / words, 3)
    level = ("high" if density >= GENERIC_DENSITY_HIGH
             else "low" if density < GENERIC_DENSITY_LOW
             else "medium")
    return {"density": density, "hits": hits, "words": words, "level": level}


# ─── Per-figure view classification ──────────────────────────────────────────
# "A lot of the images are not of a specific aircraft" is answerable from the
# Brief Description of the Drawings alone: every figure has a line saying what
# kind of view it is, and the vocabulary is almost entirely formulaic.
#
# This is a TEXT-level judgment about what each figure depicts. It does not
# look at the image — the visual pass is the wizard's T2 stage. Its value is
# that it covers every patent cheaply, including the ones whose crops were
# never produced.

# A description of drawings is dense with CROSS-references — "FIG. 3 is an
# enlarged view of the tilt mechanism of FIG. 2" mentions two figures but
# describes one. Splitting on every "FIG. n" shreds those lines and leaves
# orphan fragments ("FIG. 2.") that classify as nothing.
#
# The discriminator is the predicate: a description reads "FIG. n IS/SHOWS ...",
# a cross-reference reads "of/in/shown in FIG. n". So a split point is a figure
# reference followed by a describing verb, and nothing else.
_FIG_DESC_VERB = (r"(?:is|are|shows?|showing|illustrates?|illustrating|depicts?|"
                  r"depicting|presents?|provides?|represents?|schematically|"
                  r"comprises?|contains?)")
_FIG_REF = r"FIGS?\s*\.?\s*\d+[A-Za-z]?(?:\s*(?:[-–]|to|and|through)\s*\d+[A-Za-z]?)*"

_FIG_SPLIT_RE = re.compile(
    rf"(?=\b{_FIG_REF}\s*,?\s+{_FIG_DESC_VERB}\b)", re.IGNORECASE)
_FIG_NUM_RE = re.compile(r"\bFIGS?\s*\.?\s*(\d+[A-Za-z]?)", re.IGNORECASE)

FIGURE_VIEW_OPTIONS = [
    "WholeAircraft", "SubsystemAssembly", "DetailSection", "Diagram", "Other",
]

# Ordered most-specific-first; first hit wins. Diagram before detail before
# whole-aircraft, because "a block diagram of the propulsion system of an
# aircraft" contains the word aircraft and must not be read as an aircraft view.
_FIG_VIEW_RULES: list[tuple[str, str]] = [
    (r"\b(?:block\s+diagram|flow\s*chart|flow\s+diagram|schematic\s+diagram|"
     r"circuit\s+diagram|graph|plot|chart|timeline|state\s+diagram|"
     r"control\s+diagram|wiring)\b", "Diagram"),
    (r"\b(?:enlarged|detail(?:ed)?\s+view|close[-\s]?up|cross[-\s]?section|"
     r"sectional\s+view|section\s+taken|exploded|cut[-\s]?away|partial\s+view|"
     r"fragmentary)\b", "DetailSection"),
    (r"\b(?:assembly|mechanism|linkage|actuator|hinge|gearbox|motor|stator|"
     r"rotor\s+hub|battery\s+pack|landing\s+gear|nacelle)\b(?![^.]*\baircraft\b)",
     "SubsystemAssembly"),
    # "side elevation view", "top plan view" — an optional intervening word, so
    # the compound forms patents actually use are matched, not just "side view".
    (r"\b(?:perspective|isometric|plan|top|side|front|rear|elevational?|bottom)\s+"
     r"(?:\w+\s+)?view\b[^.]{0,60}?\b(?:aircraft|vehicle|rotorcraft|eVTOL|airplane)\b",
     "WholeAircraft"),
    (r"\b(?:aircraft|air\s+vehicle|rotorcraft|eVTOL)\b[^.]{0,40}?"
     r"\b(?:in\s+a?\s*(?:hover|cruise|transition|forward\s+flight|vertical)|"
     r"configuration|mode|position)\b", "WholeAircraft"),
    (r"\b(?:perspective|isometric|plan|side|front|rear|elevational?)\s+"
     r"(?:\w+\s+)?view\b", "SubsystemAssembly"),
]

# SBERT anchors for the lines the keyword rules do not resolve.
_FIG_VIEW_DEFS = {
    "WholeAircraft": "a view of a complete aircraft showing the entire vehicle, "
                     "its wings, fuselage and rotors together",
    "SubsystemAssembly": "a view of an assembly or mechanism of an aircraft, such as "
                         "a tilting mechanism, a landing gear or a motor assembly",
    "DetailSection": "an enlarged, sectional, exploded or fragmentary detail view of "
                     "a small part of a larger structure",
    "Diagram": "a block diagram, flow chart, schematic or graph rather than a drawing "
               "of a physical object",
    "Other": "a view that does not clearly show an aircraft, an assembly, a detail or "
             "a diagram",
}


def split_drawing_lines(description_of_drawings: str | None) -> list[dict]:
    """Split a Brief Description of the Drawings into one entry per figure.

    Returns [{"fig": "1", "text": "FIG. 1 is a perspective view of ..."}, ...].
    A "FIGS. 2A-2C" line yields one entry keyed on the first number — the point
    is what KIND of view it is, and a range shares one description.
    """
    if not description_of_drawings or not str(description_of_drawings).strip():
        return []

    blob = " ".join(str(description_of_drawings).split())
    out: list[dict] = []
    for chunk in _FIG_SPLIT_RE.split(blob):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _FIG_NUM_RE.search(chunk)
        if not m:
            continue
        out.append({"fig": m.group(1), "text": chunk})
    return out


def classify_figure_views(description_of_drawings: str | None,
                          sbert_model=None) -> list[dict]:
    """Per-figure view type from the drawings description.

    Returns [{"fig", "view", "confidence", "source", "text"}, ...].
    """
    lines = split_drawing_lines(description_of_drawings)
    out: list[dict] = []
    for entry in lines:
        view, conf, source = None, 0.0, None
        for pattern, label in _FIG_VIEW_RULES:
            if re.search(pattern, entry["text"], re.IGNORECASE):
                view, conf, source = label, 0.80, "keyword"
                break
        if view is None:
            pred = _sbert_best(entry["text"], _FIG_VIEW_DEFS, sbert_model)
            view, conf, source = pred.get("value"), pred.get("confidence", 0.0), pred.get("source")
        out.append({"fig": entry["fig"], "view": view, "confidence": conf,
                    "source": source, "text": entry["text"]})
    return out


def summarise_figure_views(figure_views: list[dict]) -> dict:
    """Counts per view type, plus the share of figures showing a whole aircraft."""
    total = len(figure_views)
    counts = {v: 0 for v in FIGURE_VIEW_OPTIONS}
    for f in figure_views:
        if f.get("view") in counts:
            counts[f["view"]] += 1
    return {
        "figures_total": total,
        "figures_whole_aircraft": counts["WholeAircraft"],
        "figures_subsystem": counts["SubsystemAssembly"],
        "figures_detail": counts["DetailSection"],
        "figures_diagram": counts["Diagram"],
        "figures_other": counts["Other"],
        "whole_aircraft_share": round(counts["WholeAircraft"] / total, 3) if total else None,
    }


# ─── Specificity ─────────────────────────────────────────────────────────────
# The flag the study turns on. Deliberately built as a transparent, additive
# score over named signals rather than as one opaque model output: the thesis
# has to be able to state the rule, and you have to be able to re-threshold it
# without re-running anything (every input signal is exported as its own
# column alongside the verdict).

SPECIFICITY_OPTIONS = "SpecificAircraft|ArchitectureGeneric|IllustrativeOnly"

# net = specific_evidence - generic_evidence, in the units the weights below use.
SPECIFIC_THRESHOLD  = 3     # net >= this  -> SpecificAircraft
GENERIC_THRESHOLD   = -2    # net <= this  -> IllustrativeOnly
                            # in between   -> ArchitectureGeneric


def assess_specificity(
    scope_pred: dict | None,
    arch: dict | None,
    generic: dict | None,
    figure_summary: dict | None = None,
    aircraft_name: str | None = None,
    aircraft_name_source: str | None = None,
) -> dict:
    """Is this patent tied to one identifiable aircraft?

    Returns {"value", "confidence", "score", "reasons", "signals"} where
    `value` is one of SPECIFICITY_OPTIONS:

      SpecificAircraft     the disclosure is a whole-aircraft architecture,
                           committed to one configuration, and its figures show
                           complete vehicles.
      ArchitectureGeneric  tied to one architecture class, but nothing
                           identifies a particular aircraft.
      IllustrativeOnly     a subsystem or component idea; the airframe in the
                           drawings is a carrier for it, not its subject.

    `reasons` is the human-readable list of signals that fired, and is written
    into the sheet so a reviewer can see WHY a row was flagged instead of
    having to trust the number.
    """
    scope_pred = scope_pred or {}
    arch = arch or {}
    generic = generic or {}
    figure_summary = figure_summary or {}

    score = 0
    reasons: list[str] = []

    # ── Granularity: the single strongest signal ────────────────────────────
    scope = scope_pred.get("value")
    if scope == _SCOPE_WHOLE:
        score += 3
        reasons.append("whole-aircraft scope (+3)")
    elif scope == _SCOPE_SUBSYS:
        # -2, not -1: scope alone should roughly set the band, with the other
        # signals able to move a patent one band, not two. At -1 a subsystem
        # patent whose figures happen to show the whole vehicle reached
        # SpecificAircraft — and a tilt-mechanism patent is precisely the case
        # this flag exists to keep out of per-aircraft statistics.
        score -= 2
        reasons.append("subsystem-enabler scope (-2)")
    elif scope == _SCOPE_COMPONENT:
        score -= 3
        reasons.append("component-level scope (-3)")

    # ── Architecture multiplicity ──────────────────────────────────────────
    count = arch.get("count") or 0
    if count == 1:
        score += 1
        reasons.append("commits to one architecture (+1)")
    elif count >= ARCH_COUNT_GENERIC:
        score -= 2
        reasons.append(f"enumerates {count} architectures (-2)")

    # ── Hedging density ────────────────────────────────────────────────────
    level = generic.get("level")
    if level == "high":
        score -= 1
        reasons.append(f"heavy hedging language, {generic.get('density')}/100w (-1)")
    elif level == "low":
        score += 1
        reasons.append(f"little hedging language, {generic.get('density')}/100w (+1)")

    # ── What the figures actually show ─────────────────────────────────────
    total = figure_summary.get("figures_total") or 0
    whole = figure_summary.get("figures_whole_aircraft") or 0
    if total:
        share = whole / total
        if whole == 0:
            score -= 2
            reasons.append(f"no figure shows a complete aircraft (0/{total}) (-2)")
        elif share >= 0.5:
            score += 2
            reasons.append(f"{whole}/{total} figures show a complete aircraft (+2)")
        else:
            reasons.append(f"only {whole}/{total} figures show a complete aircraft (0)")

    # ── A name from a real source, not just company attribution ────────────
    # The gazetteer matches on COMPANY, so a gazetteer name is not evidence
    # that THIS patent depicts that aircraft — only the LLM (which reads the
    # abstract) and text mining (which found the name in the document) are.
    if aircraft_name and aircraft_name_source in ("llm", "sbert", "regex", "human"):
        score += 1
        reasons.append(f"aircraft named by {aircraft_name_source} (+1)")

    if score >= SPECIFIC_THRESHOLD:
        value = "SpecificAircraft"
    elif score <= GENERIC_THRESHOLD:
        value = "IllustrativeOnly"
    else:
        value = "ArchitectureGeneric"

    # Confidence scales with how far the score is from the nearest boundary —
    # a verdict decided by one point is reported as a weak verdict.
    distance = min(abs(score - SPECIFIC_THRESHOLD), abs(score - GENERIC_THRESHOLD))
    confidence = round(min(0.95, 0.45 + 0.12 * distance), 4)
    if not reasons:
        confidence = 0.0

    return {
        "value": value,
        "confidence": confidence,
        "score": score,
        "reasons": reasons,
        "signals": {
            "scope": scope,
            "architecture_count": count,
            "generic_level": level,
            "figures_total": total,
            "figures_whole_aircraft": whole,
        },
    }


def aircraft_link_for(specificity_value: str | None,
                      aircraft_name: str | None,
                      aircraft_name_source: str | None) -> str:
    """How the patent relates to the aircraft named on its row.

        Depicted           the patent's own figures show this aircraft
        CompanyAttributed  the name came from the company, but this patent is
                           about a subsystem/component — its drawings are not
                           evidence of that aircraft
        None               nothing linked

    This is the column that keeps a component patent from silently becoming a
    data point about the company's flagship aircraft.
    """
    if not aircraft_name:
        return "None"
    if specificity_value == "SpecificAircraft":
        return "Depicted"
    if aircraft_name_source in ("llm", "sbert", "regex", "human") and \
            specificity_value == "ArchitectureGeneric":
        # Named from the document itself, but the document is not committed to
        # depicting it — still weaker than Depicted.
        return "CompanyAttributed"
    return "CompanyAttributed"


# ─── Row assembly ────────────────────────────────────────────────────────────

SCOPE_COLUMNS = [
    "scope", "scope_source", "scope_confidence",
    "innovation_field", "innovation_field_source", "innovation_field_confidence",
    "architecture_primary", "architecture_primary_label", "architecture_all",
    "architecture_count", "architecture_pure",
    "architecture_source", "architecture_confidence",
    "specificity", "specificity_confidence", "specificity_score", "specificity_reason",
    "aircraft_link",
    "generic_language_density", "generic_language_level",
    "figures_total", "figures_whole_aircraft", "figures_subsystem",
    "figures_detail", "figures_diagram", "figures_other", "whole_aircraft_share",
]

FIGURE_COLUMNS = ["patent_id", "fig", "view", "confidence", "source", "text"]


def build_scope_row(
    patent_id: str,
    classify_text: str | None,
    description_of_drawings: str | None,
    sbert_model=None,
    aircraft_name: str | None = None,
    aircraft_name_source: str | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """Everything this module contributes for one patent.

    Returns (scope_columns, figure_rows, evidence_rows). The evidence rows use
    the same shape aircraft_identity emits, so both modules' evidence lands in
    one auditable sheet.
    """
    scope_pred = classify_scope(classify_text, sbert_model)
    field_pred = classify_innovation_field(classify_text, sbert_model)
    arch       = architectures_present(classify_text, sbert_model)
    generic    = generic_language_score(classify_text)

    figure_views = classify_figure_views(description_of_drawings, sbert_model)
    fig_summary  = summarise_figure_views(figure_views)

    spec = assess_specificity(
        scope_pred, arch, generic, fig_summary, aircraft_name, aircraft_name_source,
    )

    row = {
        "scope": scope_pred.get("value"),
        "scope_source": scope_pred.get("source"),
        "scope_confidence": scope_pred.get("confidence"),
        "innovation_field": field_pred.get("value"),
        "innovation_field_source": field_pred.get("source"),
        "innovation_field_confidence": field_pred.get("confidence"),
        "architecture_primary": arch.get("primary"),
        "architecture_primary_label": arch.get("primary_label"),
        "architecture_all": "; ".join(arch.get("all_labels") or []) or None,
        "architecture_count": arch.get("count"),
        "architecture_pure": arch.get("pure"),
        "architecture_source": arch.get("source"),
        "architecture_confidence": arch.get("confidence"),
        "specificity": spec["value"],
        "specificity_confidence": spec["confidence"],
        "specificity_score": spec["score"],
        "specificity_reason": "; ".join(spec["reasons"]) or None,
        "aircraft_link": aircraft_link_for(spec["value"], aircraft_name, aircraft_name_source),
        "generic_language_density": generic.get("density"),
        "generic_language_level": generic.get("level"),
        **fig_summary,
    }

    figure_rows = [{"patent_id": patent_id, **f} for f in figure_views]

    evidence = []
    for field, pred in (("scope", scope_pred), ("innovation_field", field_pred)):
        if pred.get("value"):
            evidence.append({
                "patent_id": patent_id, "field": field,
                "candidate_value": pred["value"], "source": pred.get("source"),
                "confidence": pred.get("confidence"),
                "context": f"margin={pred.get('margin')}",
            })
    for a in (arch.get("all") or []):
        evidence.append({
            "patent_id": patent_id, "field": "architecture",
            "candidate_value": ARCHITECTURE_LABELS.get(a, a),
            "source": arch.get("source") if a == arch.get("primary") else "sbert",
            "confidence": arch.get("confidence") if a == arch.get("primary") else None,
            "context": "primary" if a == arch.get("primary") else "also present",
        })
    evidence.append({
        "patent_id": patent_id, "field": "specificity",
        "candidate_value": spec["value"], "source": "rule",
        "confidence": spec["confidence"],
        "context": "; ".join(spec["reasons"]),
    })

    return row, figure_rows, evidence
