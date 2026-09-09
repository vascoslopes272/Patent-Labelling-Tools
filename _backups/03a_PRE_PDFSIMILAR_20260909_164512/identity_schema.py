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
    "wizard_arch_count", "wizard_variant_types", "wizard_edge_tags",
    "duplicate_root", "duplicate_root_note",
    "duplicate_root_aircraft", "duplicate_root_variant", "duplicate_ambiguous",
    # ── Aircraft name: the group name is never empty; the real name is a
    #    machine PROPOSAL until the reviewer types it into *_human ───────────
    "aircraft_group", "aircraft_group_source", "aircraft_group_note",
    "aircraft_group_variants", "aircraft_name_variant_proposals",
    "aircraft_name", "aircraft_name_source", "aircraft_name_confidence",
    "aircraft_name_in_text", "aircraft_name_section", "aircraft_name_quote",
    "aircraft_name_alternatives",
    "aircraft_name_human", "aircraft_name_human_variants",
    "aircraft_name_final", "aircraft_name_final_variants",
    # ── Electric? ───────────────────────────────────────────────────────────
    "is_electric", "is_electric_source",
    "powertrain", "powertrain_source", "powertrain_confidence",
    "powertrain_section", "powertrain_quote",
    "powertrain_other", "powertrain_other_quote",
    "is_electric_human", "is_electric_human_variants",
    "is_electric_final", "is_electric_final_variants",
    "electric_similar_human", "electric_similar_human_variants",
    "electric_similar_final", "electric_similar_final_variants",
    # ── VTOL or STOL? ───────────────────────────────────────────────────────
    "takeoff_mode", "takeoff_source", "takeoff_confidence",
    "takeoff_section", "takeoff_quote",
    "takeoff_human", "takeoff_human_variants",
    "takeoff_final", "takeoff_final_variants",
    # ── UAV? (a hint for the UAVSimilar edge tag the annotator may have missed)
    "uav_hint", "uav_source", "uav_confidence", "uav_section", "uav_quote",
    "uav_human", "uav_human_variants",
    "uav_final", "uav_final_variants",
    # ── Review bookkeeping ──────────────────────────────────────────────────
    "review_queue", "name_review", "electric_review", "takeoff_review", "uav_review",
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
    "duplicate_root_variant",
    "aircraft_name_human", "aircraft_name_human_variants",
    "is_electric_human", "is_electric_human_variants",
    "electric_similar_human", "electric_similar_human_variants",
    "takeoff_human", "takeoff_human_variants",
    "uav_human", "uav_human_variants",
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
    "aircraft_name_human_variants": "one real name per variant, in _arch order, separated by ';' "
                                    "(e.g. 'Nexus 4EX; Nexus 6HX') — leave empty to keep the letters",
    "is_electric_human":   "Yes | Hybrid | No",
    "takeoff_human":       "VTOL | STOL | CTOL",
    "uav_human":           "UAVSimilar | No | Pure  (UAVSimilar = the edge tag you would add in the wizard)",
    "electric_similar_human": "ElectricSimilar | No — keep a NON-electric aircraft in the corpus "
                              "because its architecture is equivalent to an electric one",
    "duplicate_root_variant": "a | b | c …  — WHICH aircraft of the original this duplicates, "
                              "when the original describes more than one",
    "review_status":       "done | skip  (empty = still to do)",
}

FINAL_COLUMNS = ["aircraft_name_final", "aircraft_name_final_variants",
                 "is_electric_final", "is_electric_final_variants",
                 "electric_similar_final", "electric_similar_final_variants",
                 "takeoff_final", "takeoff_final_variants",
                 "uav_final", "uav_final_variants"]

# The three verdicts a variant can differ on. A patent describing two aircraft
# can describe one battery-electric and one hybrid, and the analysis unit is the
# VARIANT, not the patent (methodology framework, Part D-1). The patent-level
# answer covers every variant unless one of these ';'-separated cells overrides
# it, so a patent whose variants agree still takes one click.
VARIANT_RULES = [
    ("aircraft_name_final_variants", "aircraft_name_human_variants", "aircraft_name_final"),
    ("is_electric_final_variants",   "is_electric_human_variants",   "is_electric_final"),
    ("electric_similar_final_variants", "electric_similar_human_variants",
     "electric_similar_final"),
    ("takeoff_final_variants",       "takeoff_human_variants",       "takeoff_final"),
    ("uav_final_variants",           "uav_human_variants",           "uav_final"),
]


def arch_n(arch_count) -> int:
    try:
        n = int(float(arch_count)) if arch_count is not None and str(arch_count) != "nan" else 1
    except (TypeError, ValueError):
        n = 1
    return max(n, 1)


def variant_values(human_variants, patent_value, arch_count, letters_from=None):
    """One value per variant, ';'-joined — or None for a single-aircraft patent.

    A blank slot falls back to the patent-level answer, so answering once still
    fills every variant. `letters_from` is used by the NAME rule: with no typed
    per-variant names, the variants are the patent name plus a, b, c…
    """
    n = arch_n(arch_count)
    if n < 2:
        return None
    typed = [] if _blank(human_variants) else [t.strip() for t in str(human_variants).split(";")]
    if not any(typed) and letters_from is not None:
        return variant_names(letters_from, n)
    base = "" if _blank(patent_value) else str(patent_value).strip()
    return "; ".join((typed[i] if i < len(typed) and typed[i] else base) for i in range(n))


def variant_names(group_name, arch_count) -> "str | None":
    """'Airbus Helicopters 4' with 2 variants → 'Airbus Helicopters 4a; Airbus Helicopters 4b'.

    The annotator names the PATENT; the wizard's <pid>_archN records say how
    many distinct aircraft it describes. A letter per variant keeps them apart
    without inventing a new number — numbers are for different patents (D3)."""
    try:
        n = int(float(arch_count)) if arch_count is not None and str(arch_count) != "nan" else 1
    except (TypeError, ValueError):
        n = 1
    if not group_name or _blank(group_name) or n < 2:
        return None
    name = str(group_name).strip()
    # "Bell Textron 10" -> "10a"; an un-numbered name ("OVERAIR") gets a space
    # so the letter does not read as part of the word.
    sep = "" if name[-1].isdigit() else " "
    return "; ".join(f"{name}{sep}{chr(96 + i)}" for i in range(1, n + 1))

# The columns a reviewer actually reads, for the notebook's compact preview.
REVIEW_COLUMNS = [
    "patent_id", "company_canonical", "review_queue", "aircraft_group",
    "aircraft_group_variants", "aircraft_name", "aircraft_name_in_text", "aircraft_name_human",
    "is_electric", "is_electric_source", "is_electric_human", "electric_similar_human",
    "takeoff_mode", "takeoff_human", "uav_hint", "wizard_edge_tags", "uav_human",
    "review_status", "review_reason",
]


# ─── How the sheet is coloured ───────────────────────────────────────────────
# One sheet, not two: Identity has to stay a single row-per-patent table you can
# join on patent_id, and splitting it would mean maintaining the join by hand.
# Colour carries the same information without breaking that.

COLUMN_GROUPS: dict[str, list[str]] = {
    # amber — the cells YOU fill in NOW
    "yours": ["duplicate_root_variant",
              "aircraft_name_human", "aircraft_name_human_variants",
              "is_electric_human", "is_electric_human_variants",
              "electric_similar_human", "electric_similar_human_variants",
              "takeoff_human", "takeoff_human_variants",
              "uav_human", "uav_human_variants",
              "review_status", "reviewed_by", "reviewed_at", "notes"],
    # teal — what you ALREADY decided in the wizard. Read-only here: change it
    # in the wizard export, not on this sheet.
    "wizard": ["wizard_approved", "wizard_disapprove_reason", "wizard_aircraft_name",
               "wizard_duplicate_type", "wizard_duplicate_of",
               "wizard_arch_count", "wizard_variant_types", "wizard_edge_tags",
               "duplicate_root", "duplicate_root_note", "duplicate_root_aircraft",
               "duplicate_ambiguous"],
    # green/orange per row — the verdicts, coloured by whether they are settled
    "verdict": ["aircraft_group", "aircraft_name", "is_electric", "takeoff_mode",
                "uav_hint", "electric_similar_final", "review_queue"],
    # blue — why the machine says what it says; read these to decide
    "evidence": ["aircraft_group_source", "aircraft_group_note", "aircraft_group_variants",
                 "aircraft_name_variant_proposals", "aircraft_name_source",
                 "aircraft_name_confidence", "aircraft_name_in_text",
                 "aircraft_name_section", "aircraft_name_quote",
                 "aircraft_name_alternatives", "is_electric_source",
                 "powertrain", "powertrain_source", "powertrain_confidence",
                 "powertrain_section", "powertrain_quote",
                 "powertrain_other", "powertrain_other_quote",
                 "takeoff_source", "takeoff_confidence", "takeoff_section", "takeoff_quote",
                 "uav_source", "uav_confidence", "uav_section", "uav_quote",
                 "needs_review", "review_reason",
                 "name_review", "electric_review", "takeoff_review", "uav_review"],
    # grey — bibliographic fact from the PatSeer export. Never a judgement.
    "given": ["patent_id", "batch", "company_canonical", "assignee_raw", "prototype_label",
              "title", "app_year", "pub_year", "pub_office", "assignee_country",
              "assignee_country_source", "region"],
    # the *_final columns — what the next stage joins on
    "final": FINAL_COLUMNS,
}

FILLS = {
    "wizard":   "D0E0E3",   # teal    — your wizard record, already decided
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

def propagate_duplicate_finals(rows: list) -> list:
    """A D1/D2 takes the chain root's answers — it is the same aircraft.

    Resolves the chain (a D2 whose original is itself a D2 — 46 of them in this
    corpus) and copies every *_final column from the root. A duplicate whose
    root sits in ANOTHER batch keeps its own values and says so in
    `duplicate_root_note`: the per-batch workbook cannot see that row, and the
    join stage resolves it on `duplicate_root`.

    Never overwrites an answer the reviewer typed on the duplicate itself.
    """
    by_id = {r["patent_id"]: r for r in rows if r.get("patent_id")}
    if not by_id:
        return rows

    def root_of(pid):
        seen = {pid}
        cur = by_id.get(pid)
        while cur and str(cur.get("wizard_duplicate_type") or "") in ("1", "2"):
            parent = (cur.get("wizard_duplicate_of") or "").strip() or None
            if not parent or parent in seen:
                break
            seen.add(parent)
            if parent not in by_id:
                return parent, False              # outside this batch
            pid, cur = parent, by_id[parent]
        return pid, True

    for r in rows:
        if not r.get("patent_id"):
            continue
        if str(r.get("wizard_duplicate_type") or "") not in ("1", "2"):
            r["duplicate_root"] = None
            r["duplicate_root_note"] = None
            continue
        root, here = root_of(r["patent_id"])
        r["duplicate_root"] = root
        if not here or root == r["patent_id"]:
            r["duplicate_root_note"] = (f"original {root} is in another batch — answers not "
                                        f"inherited in this workbook") if not here else None
            continue
        src = by_id[root]
        typed = any(not _blank(r.get(h)) for h in
                    ("aircraft_name_human", "is_electric_human", "takeoff_human", "uav_human"))
        if typed:
            r["duplicate_root_note"] = "you answered this duplicate yourself — kept"
            continue

        # `duplicateId` names a PATENT. When that patent describes several
        # aircraft, "a duplicate of it" does not say WHICH one — 27 rows in this
        # corpus. Pin it with duplicate_root_variant (a/b/c); otherwise inherit
        # the original's patent-level answer, and flag the row only when the
        # original's aircraft actually disagree, because only then is the choice
        # a real one.
        n_root = arch_n(src.get("wizard_arch_count"))
        r["duplicate_root_aircraft"] = n_root if n_root > 1 else None
        pick = str(r.get("duplicate_root_variant") or "").strip().lower()
        idx = (ord(pick) - 97) if len(pick) == 1 and "a" <= pick <= "z" else None
        if idx is not None and not (0 <= idx < n_root):
            idx = None

        for col in FINAL_COLUMNS:
            r[col] = src.get(col)

        divergent = []
        for variants_col, _, patent_col in VARIANT_RULES:
            parts = [p.strip() for p in str(src.get(variants_col) or "").split(";") if p.strip()]
            if idx is not None and idx < len(parts):
                r[patent_col] = parts[idx]          # the aircraft you pinned
            elif len(set(parts)) > 1 and patent_col != "aircraft_name_final":
                # The NAME always differs per aircraft — that is the a/b/c
                # convention, not a disagreement, and a D1/D2 carries the
                # original's name by rule either way.
                divergent.append(patent_col.replace("_final", ""))

        r["duplicate_ambiguous"] = bool(divergent)
        if n_root < 2:
            r["duplicate_root_note"] = f"answers inherited from {root}"
        elif idx is not None:
            r["duplicate_root_note"] = (f"inherited from {root}, aircraft "
                                        f"{chr(97 + idx)} of {n_root}")
        elif divergent:
            r["duplicate_root_note"] = (f"{root} describes {n_root} aircraft and they DIFFER on "
                                        f"{', '.join(divergent)} — say which one with "
                                        f"duplicate_root_variant (a…{chr(96 + n_root)})")
        else:
            r["duplicate_root_note"] = (f"inherited from {root}, which describes {n_root} "
                                        f"aircraft that agree on every answer")
    return rows


def review_flags(row: dict) -> dict:
    """{name_review, electric_review, takeoff_review, review_queue} for a row.

    A patent the annotator disapproved is not in the queue at all — it is out of
    the corpus, and re-deciding its powertrain would be work for nothing.
    """
    if row.get("wizard_approved") is False:
        return {"name_review": False, "electric_review": False,
                "takeoff_review": False, "uav_review": False, "review_queue": None}
    # A D1 or D2 IS the original aircraft — D2 down to the same figures, D1
    # re-drawn. Electric, take-off, UAV and the name are properties of the
    # AIRCRAFT, so answering them twice is the same answer twice. They inherit
    # from the chain root (propagate_duplicate_finals) and are never queued.
    # A D3 is a DIFFERENT aircraft and is queued like any other patent.
    if str(row.get("wizard_duplicate_type") or "") in ("1", "2"):
        # Never queued, even when its original describes several aircraft whose
        # answers differ. `duplicateId` names a patent, not one of its aircraft,
        # and that is a property of the wizard record, not something to re-ask
        # patent by patent — it is reported instead (duplicate_ambiguous, the
        # DUPLICATES_OF_MULTI_AIRCRAFT_PATENTS files, and a printed warning in
        # the notebook). Fill duplicate_root_variant by hand in the xlsx if a
        # case ever needs pinning.
        return {"name_review": False, "electric_review": False,
                "takeoff_review": False, "uav_review": False, "review_queue": None}

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
    ) or bool(
        # a patent with several aircraft AND several candidate real names:
        # only you can say which variant is which product
        _blank(row.get("aircraft_name_human_variants"))
        and row.get("aircraft_name_variant_proposals")
    )
    # ELECTRIC — the burden is on showing an aircraft is NOT electric. Two
    # cases are queued: (a) the machine says NOT purely electric, a verdict
    # that would DISAPPROVE the patent, and a machine never disapproves on its
    # own; (b) the machine abstained because the text states two families or
    # because nothing decided. A patent that states NO propulsion at all is
    # "presumed" electric (this is an approved eVTOL corpus) and is NOT queued
    # — there is nothing to read. The annotator's own "not electric" is ground
    # truth and stays settled.
    elec, elec_src = row.get("is_electric"), row.get("is_electric_source")
    electric_review = bool(_blank(row.get("is_electric_human")) and (
        (elec in (None, "", "Unknown") and elec_src != "presumed")
        or (elec in ("No", "Hybrid") and elec_src != "human")
    ))
    # TAKE-OFF — same rule. Unknown, or anything that is not plainly VTOL,
    # because those are the rows a disapproval turns on; unless the annotator
    # is the one who said it.
    takeoff_review = bool(_blank(row.get("takeoff_human"))
                          and row.get("takeoff_source") != "human"
                          and row.get("takeoff_mode") in (None, "", "STOL", "V/STOL", "CTOL"))

    # UAV — the text uses UAV vocabulary and the annotator never tagged it.
    # The annotator's own tag settles it; so does a Pure-UAV disapproval (that
    # row is disapproved and never reaches here anyway).
    uav_review = bool(_blank(row.get("uav_human"))
                      and row.get("uav_hint")
                      and "UAVSimilar" not in str(row.get("wizard_edge_tags") or ""))

    # "Not electric" is only half an answer: say whether the aircraft is still
    # architecturally equivalent to an electric one (the ElectricSimilar edge
    # tag) so it can stay in the corpus. Asked only once the answer IS "No".
    similar_review = bool(_blank(row.get("electric_similar_human"))
                          and _blank(row.get("electric_similar_final"))
                          and str(row.get("is_electric_human") or "") == "No")

    queue = [n for n, f in (("name", name_review), ("electric", electric_review or similar_review),
                            ("takeoff", takeoff_review), ("uav", uav_review)) if f]
    return {"name_review": name_review, "electric_review": electric_review or similar_review,
            "takeoff_review": takeoff_review, "uav_review": uav_review,
            "review_queue": "+".join(queue) or None}


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
    g = (lambda k: row.get(k)) if hasattr(row, "get") else (lambda k: row[k])
    for final, human, machine in FINAL_RULES:
        h, m = g(human), g(machine)
        row[final] = m if _blank(h) else (str(h).strip())
    # UAV and ElectricSimilar: your cell, else the tag the annotator already
    # gave in the wizard. A machine hint is NEVER promoted — a tag is a human
    # decision. ElectricSimilar is how a non-electric aircraft stays in the
    # corpus: "not electric, but architecturally equivalent to one".
    tags = str(g("wizard_edge_tags") or "")
    for col, tag in (("uav", "UAVSimilar"), ("electric_similar", "ElectricSimilar")):
        h = g(f"{col}_human")
        row[f"{col}_final"] = (str(h).strip() if not _blank(h)
                               else (tag if tag in tags else None))
    # One value per variant for each verdict. The name rule additionally falls
    # back to letters on the patent's final name.
    count = g("wizard_arch_count")
    for final_col, human_col, patent_col in VARIANT_RULES:
        row[final_col] = variant_values(
            g(human_col), row.get(patent_col), count,
            letters_from=(row.get(patent_col) if final_col.startswith("aircraft_name") else None))


EVIDENCE_COLUMNS = [
    "patent_id", "field", "candidate_value", "source", "confidence", "context",
]

PROMPT_COLUMNS = ["patent_id", "company_canonical", "app_year", "llm_prompt", "llm_answer"]




