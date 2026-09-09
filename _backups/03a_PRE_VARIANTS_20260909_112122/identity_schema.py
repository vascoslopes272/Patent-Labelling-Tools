"""
identity_schema.py — the column schema for aircraft_identity_<batch>.xlsx.

Stage 03a. Its own module because two things need it and neither should import
the other: src/aircraft_identity.py builds the rows, src/identity_excel.py
writes them. (Same reason the older stage keeps src/excel_schema.py separate.)

Holds the column order, the source-precedence table that decides which signal
wins a field, the confidence constants for sources that do not compute one, and
the review contract: which columns a human types into (HUMAN_COLUMNS), and how
a typed value becomes the *_final column (FINAL_RULES / apply_finals).
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
    # The sheet is read left to right by a reviewer, so the columns they act on
    # come first and the bibliometric tail comes last. Order matters for
    # nothing else — the export reindexes to this list.
    # ── Who / what ──────────────────────────────────────────────────────────
    "patent_id", "batch", "company_canonical", "assignee_raw", "prototype_label", "title",
    # ── The human record, read from the wizard export (src/wizard_link.py) ──
    "wizard_approved", "wizard_disapprove_reason", "wizard_aircraft_name",
    "wizard_duplicate_type", "wizard_duplicate_of",
    # ── Aircraft name: the group name is never empty; the real name is a
    #    machine PROPOSAL until the reviewer types it into *_human ───────────
    "aircraft_group", "aircraft_group_source", "aircraft_group_note",
    "aircraft_name", "aircraft_name_source", "aircraft_name_confidence",
    "aircraft_name_in_text", "aircraft_name_section", "aircraft_name_quote",
    "aircraft_name_alternatives",
    "aircraft_name_human", "aircraft_name_final",
    # ── Electric? ───────────────────────────────────────────────────────────
    "is_electric", "is_electric_source",
    "powertrain", "powertrain_source", "powertrain_confidence",
    "powertrain_section", "powertrain_quote",
    "is_electric_human", "is_electric_final",
    # ── VTOL or STOL? ───────────────────────────────────────────────────────
    "takeoff_mode", "takeoff_source", "takeoff_confidence",
    "takeoff_section", "takeoff_quote",
    "takeoff_human", "takeoff_final",
    # ── Review bookkeeping ──────────────────────────────────────────────────
    "review_queue", "name_review", "electric_review", "takeoff_review",
    "needs_review", "review_reason", "review_status",
    "reviewed_by", "reviewed_at", "notes",
    # ── Geography ───────────────────────────────────────────────────────────
    "pub_office", "assignee_country", "assignee_country_source", "region",
    # ── Dates (priority_year / snapshot_date live in the maturity block) ────
    "app_year", "pub_year",
    # ── Application domain (not reviewed now) ───────────────────────────────
    "industry_primary", "industry_source", "industry_confidence",
    # ── Specifications (not reviewed now) ───────────────────────────────────
    "pax", "mtow_kg", "payload_kg", "cruise_speed_kmh", "max_speed_kmh",
    "range_km", "endurance_min", "spec_source", "spec_confidence",
    *BLADE_COLUMNS,
    # ── Scope / architecture / specificity (src/patent_scope.py; informative,
    #    the wizard's human topType/archCount/notPureArch are the truth) ─────
    *_SCOPE_COLUMNS,
    # ── Maturity, citations, legal stage (src/patent_maturity.py) ───────────
    *_MATURITY_COLUMNS,
    "llm_reasoning",
]

# Columns the reviewer types into. A re-run must never overwrite these — see
# identity_excel.merge_preserving_human(). llm_answer lives on the LLM_Prompts
# sheet, the rest on Identity.
HUMAN_COLUMNS = [
    "aircraft_name_human", "is_electric_human", "takeoff_human",
    "review_status", "reviewed_by", "reviewed_at", "notes", "llm_answer",
]

# (final column, the human column that wins, the machine column it falls back
# to). Applied at build time AND again after the human merge, so a typed value
# shows up in *_final on the very next export.
FINAL_RULES = [
    ("aircraft_name_final", "aircraft_name_human", "aircraft_group"),
    ("is_electric_final",   "is_electric_human",   "is_electric"),
    ("takeoff_final",       "takeoff_human",       "takeoff_mode"),
]

# What the reviewer is asked to decide, in the words they use. The values a
# *_human cell accepts; free text for the name.
HUMAN_OPTIONS = {
    "aircraft_name_human": "the real aircraft name (free text) — leave empty to keep aircraft_group",
    "is_electric_human":   "Yes | Hybrid | No",
    "takeoff_human":       "VTOL | STOL | CTOL",
    "review_status":       "done | skip  (empty = still to do)",
}

# The columns a reviewer actually reads, for the notebook's compact preview.
REVIEW_COLUMNS = [
    "patent_id", "company_canonical", "review_queue", "aircraft_group",
    "aircraft_name", "aircraft_name_in_text", "aircraft_name_human",
    "is_electric", "is_electric_source", "is_electric_human",
    "takeoff_mode", "takeoff_human", "review_status", "review_reason",
]


# ─── How the sheet is coloured ───────────────────────────────────────────────
# One sheet, not two: Identity has to stay a single row-per-patent table you can
# join on patent_id, and splitting it would mean maintaining the join by hand.
# Colour carries the same information without breaking that.

COLUMN_GROUPS: dict[str, list[str]] = {
    # amber — the cells YOU fill in
    "yours": ["aircraft_name_human", "is_electric_human", "takeoff_human",
              "review_status", "reviewed_by", "reviewed_at", "notes"],
    # green/orange per row — the three verdicts, coloured by whether they are settled
    "verdict": ["aircraft_group", "aircraft_name", "is_electric", "takeoff_mode",
                "review_queue"],
    # blue — why the machine says what it says; read these to decide
    "evidence": ["aircraft_group_source", "aircraft_group_note", "aircraft_name_source",
                 "aircraft_name_confidence", "aircraft_name_in_text",
                 "aircraft_name_section", "aircraft_name_quote",
                 "aircraft_name_alternatives", "is_electric_source",
                 "powertrain", "powertrain_source", "powertrain_confidence",
                 "powertrain_section", "powertrain_quote",
                 "takeoff_source", "takeoff_confidence", "takeoff_section", "takeoff_quote",
                 "needs_review", "review_reason",
                 "name_review", "electric_review", "takeoff_review"],
    # grey — bibliographic fact from the PatSeer export or your own wizard record.
    # Nothing here is a judgement and nothing here is reviewed.
    "given": ["patent_id", "batch", "company_canonical", "assignee_raw", "prototype_label",
              "title", "app_year", "pub_year", "pub_office", "assignee_country",
              "assignee_country_source", "region",
              "wizard_approved", "wizard_disapprove_reason", "wizard_aircraft_name",
              "wizard_duplicate_type", "wizard_duplicate_of"],
    # the *_final columns — what the next stage joins on
    "final": ["aircraft_name_final", "is_electric_final", "takeoff_final"],
}

FILLS = {
    "yours":    "FFF2CC",   # amber   — type here
    "final":    "D9D2E9",   # violet  — what the thesis joins on
    "evidence": "DEEBF7",   # blue    — read this to decide
    "given":    "EFEFEF",   # grey    — bibliographic, never reviewed
    "other":    "F5F5F5",   # near-white — machine predictions you are not reviewing
    "settled":  "D9EAD3",   # green   — answered, with a source
    "open":     "FCE5CD",   # orange  — in your queue
}


# ─── What still needs a human ────────────────────────────────────────────────
# The queue, in one place, because it is the thing that decides how long the
# review takes. A field is in it only when nothing trustworthy already answered
# it: the annotator's own disapproval reason, a gazetteer or keyword powertrain,
# an all-electric company, or a name the annotator typed.

def review_flags(row: dict) -> dict:
    """{name_review, electric_review, takeoff_review, review_queue} for a row.

    A patent the annotator disapproved is not in the queue at all — it is out of
    the corpus, and re-deciding its powertrain would be work for nothing.
    """
    if row.get("wizard_approved") is False:
        return {"name_review": False, "electric_review": False,
                "takeoff_review": False, "review_queue": None}

    # NAME — only the actionable cases. A generated group name is valid and
    # unique, so it is not an error; it is simply the one the annotator never
    # gave, and the one place a real name would help. A name found verbatim in
    # the text is worth a yes/no. A D1/D2 disagreeing with its original is a bug
    # in the record.
    note = str(row.get("aircraft_group_note") or "")
    name_review = bool(
        _blank(row.get("aircraft_name_human")) and (
            row.get("aircraft_group_source") == "generated"
            or "differs from original" in note
            or row.get("aircraft_name_in_text") == "Yes"
        )
    )
    # ELECTRIC — two cases. (a) the machine abstained, so nobody has answered;
    # (b) the machine says NOT purely electric, which is a verdict that would
    # DISAPPROVE the patent. A machine must never disapprove on its own, so any
    # "No" or "Hybrid" it produced is queued no matter how confident it was.
    # The annotator's own "not electric" is ground truth and stays settled.
    elec, elec_src = row.get("is_electric"), row.get("is_electric_source")
    electric_review = bool(_blank(row.get("is_electric_human")) and (
        elec in (None, "", "Unknown")
        or (elec in ("No", "Hybrid") and elec_src != "human")
    ))
    # TAKE-OFF — same rule. Unknown, or anything that is not plainly VTOL,
    # because those are the rows a disapproval turns on; unless the annotator
    # is the one who said it.
    takeoff_review = bool(_blank(row.get("takeoff_human"))
                          and row.get("takeoff_source") != "human"
                          and row.get("takeoff_mode") in (None, "", "STOL", "V/STOL", "CTOL"))

    queue = [n for n, f in (("name", name_review), ("electric", electric_review),
                            ("takeoff", takeoff_review)) if f]
    return {"name_review": name_review, "electric_review": electric_review,
            "takeoff_review": takeoff_review, "review_queue": "+".join(queue) or None}


def _blank(v) -> bool:
    if v is None:
        return True
    try:
        if v != v:                      # NaN
            return True
    except Exception:
        pass
    return str(v).strip() == ""


def apply_finals(row) -> None:
    """Fill the *_final columns of a dict (or pandas row) in place."""
    for final, human, machine in FINAL_RULES:
        h = row.get(human) if hasattr(row, "get") else row[human]
        m = row.get(machine) if hasattr(row, "get") else row[machine]
        row[final] = m if _blank(h) else (str(h).strip())


EVIDENCE_COLUMNS = [
    "patent_id", "field", "candidate_value", "source", "confidence", "context",
]

PROMPT_COLUMNS = ["patent_id", "company_canonical", "app_year", "llm_prompt", "llm_answer"]




