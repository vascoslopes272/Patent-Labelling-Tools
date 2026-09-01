"""
identity_schema.py — the column schema for aircraft_identity_<batch>.xlsx.

Stage 03a. Its own module because two things need it and neither should import
the other: src/aircraft_identity.py builds the rows, src/identity_excel.py
writes them. (Same reason the older stage keeps src/excel_schema.py separate.)

Holds the column order, the source-precedence table that decides which signal
wins a field, and the confidence constants for sources that do not compute one.
"""

from __future__ import annotations

from src.aircraft_specs import BLADE_COLUMNS
from src.patent_scope import SCOPE_COLUMNS as _SCOPE_COLUMNS
from src.patent_maturity import MATURITY_COLUMNS as _MATURITY_COLUMNS

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
    # Blade counts — structural, so kept with the specs rather than in the
    # maturity block (see extract_blade_counts()).
    *BLADE_COLUMNS,
    # What the patent is about, and whether it is tied to one aircraft
    # (src/patent_scope.py — appended by attach_scope()).
    *_SCOPE_COLUMNS,
    # How far along the patent is (src/patent_maturity.py — appended by
    # attach_maturity()).
    *_MATURITY_COLUMNS,
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


