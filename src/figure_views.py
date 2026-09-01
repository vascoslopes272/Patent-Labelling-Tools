"""
figure_views.py — what KIND of view each figure is, read from the Brief
Description of the Drawings.

Stage 03a. Answers "how many of these images are not of an aircraft at all"
for every patent cheaply, including the ones whose crops were never produced.

    WholeAircraft      a view of the complete vehicle
    SubsystemAssembly  a mechanism or assembly
    DetailSection      enlarged, sectional, exploded, fragmentary
    Diagram            block diagram, flow chart, schematic, graph
    Other

This is a TEXT-level judgment about what a figure depicts — it never looks at
the image. The visual pass is the HTML wizard's T2 stage.

The splitting is the fiddly part. A drawings description is dense with
CROSS-references ("FIG. 3 is an enlarged view of the mechanism of FIG. 2"), and
splitting on every "FIG. n" shreds those lines into orphan fragments that
classify as nothing. The discriminator is the predicate: a description reads
"FIG. n IS/SHOWS ...", a cross-reference reads "of/in FIG. n".
"""

from __future__ import annotations

import re

from src.reviewer import _sbert_best

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


