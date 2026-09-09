"""
identity_excel.py — writing aircraft_identity_<batch>.xlsx.

Stage 03a's output. Five sheets:

    Identity     one row per patent — the table you join on patent_id
    Figures      one row per figure — what KIND of view each one is
    Evidence     every candidate every signal proposed, with its context
    LLM_Prompts  a ready-made question per patent for the chat step
    README       column dictionary, so the workbook explains itself

Re-running is safe. The existing file is backed up with a timestamp, then
merge_preserving_human() carries your edits forward: the free-text columns
always, and any field whose `*_source` you set to "human". That is the escape
hatch for correcting a value the pipeline got wrong without freezing the file.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.aircraft_specs import (
    SPEC_FIELDS, ELECTRIC_BY_POWERTRAIN, POWERTRAIN_DEFS, INDUSTRY_DEFS, electric_verdict,
)
from src.patent_scope import SCOPE_OPTIONS as _SCOPE_OPTIONS_DOC
from src.identity_schema import (
    IDENTITY_COLUMNS, EVIDENCE_COLUMNS, PROMPT_COLUMNS, HUMAN_COLUMNS,
    FINAL_RULES, FINAL_COLUMNS, HUMAN_OPTIONS, COLUMN_GROUPS, FILLS, apply_finals,
    VARIANT_RULES, arch_n, propagate_duplicate_finals, review_flags, _CONF_HUMAN,
)
from src.text_citation import TAKEOFF_OPTIONS

_README_ROWS = [
    ("HOW TO REVIEW", "Filter review_queue to non-empty and work down THOSE rows only — "
                      "everything else is already answered. For each one decide the fields "
                      "and type them into the *_human columns: aircraft_name_human, "
                      "is_electric_human, takeoff_human. Then set review_status = done "
                      "(or skip). Re-running the notebook keeps every *_human cell, "
                      "review_status, reviewed_by, reviewed_at and notes, and recomputes "
                      "the *_final columns from them."),
    ("COLOURS", "Amber = the cells you type into NOW. Teal = what you ALREADY decided in "
                "the wizard (read-only here; change it in the wizard export). Violet = the "
                "*_final columns the thesis joins on. Green = a verdict something citable "
                "already answered. Orange = a verdict still in your queue. Blue = the "
                "evidence behind a verdict, read it to decide. Grey = bibliographic fact "
                "from the PatSeer export. The header row is filtered: click the "
                "review_queue filter and untick (Blanks)."),
    ("aircraft_name_variant_proposals / aircraft_name_human_variants",
     "For a patent with several aircraft AND several candidate real names (the gazetteer "
     "knows more than one aircraft for that company, or the text names more than one): the "
     "candidates, ';'-separated. Type one real name per variant into "
     "aircraft_name_human_variants in _arch order ('Nexus 4EX; Nexus 6HX') and "
     "aircraft_name_final_variants uses them instead of the letters. Nobody but you can say "
     "which embodiment is which product — this is queued under 'name'."),
    ("VARIANTS", "wizard_arch_count = how many distinct aircraft the patent describes, from "
                 "your own labelling (the <pid>_archN records). wizard_variant_types lists "
                 "their topType codes in order. aircraft_group_variants gives each one a "
                 "letter: 'Airbus Helicopters 4a; Airbus Helicopters 4b'. "
                 "aircraft_name_final_variants does the same from your final name. Letters "
                 "are for variants INSIDE one patent; a D3 duplicate is a different aircraft "
                 "and takes the next number."),
    ("uav_hint", "Keyword reading of UAV vocabulary in the short sections: " + "UAV|UAV-language"
                 + ". UAV = unmanned vocabulary and nothing about people aboard; UAV-language "
                 "= both ('manned or unmanned'). A HINT only — it is queued when you never "
                 "tagged the patent UAVSimilar, so you can add the tag you forgot."),
    ("uav_human", HUMAN_OPTIONS["uav_human"]),
    ("uav_final", "uav_human if you typed it, else the UAVSimilar tag already in your wizard "
                  "record, else empty. The machine hint is never promoted."),
    ("wizard_edge_tags", "The G1 edge tags in your wizard record (UAVSimilar, ElectricSimilar), "
                         "base patent and variants together."),
    ("prototype_label", "NOT an aircraft name. An unsupervised HDBSCAN cluster id per "
                        "company from 00b1_grouping (Prototype_A/B/..., or Unclassified "
                        "for cluster noise, which is most of them). Ignore it — "
                        "aircraft_group is the identity column."),
    ("SHEET: Figures — where the labels come from",
     "NOT from an earlier notebook and NOT from the images. Stage 03a splits the PatSeer "
     "'Description of Drawings' text into one line per figure and classifies the WORDS "
     "by keyword, falling back to SBERT. The visual judgement of a figure is the wizard's "
     "T2 stage, not this. Off by default (WRITE_FIGURES in the notebook)."),
    ("review_queue", "Which of the three fields this row still needs: name | electric | "
                     "takeoff, joined by '+'. EMPTY means nothing is open — either the "
                     "annotator disapproved the patent (out of the corpus, never queued) or "
                     "every field was already answered by something trustworthy: a "
                     "disapproval reason that names the thing, a keyword read from the "
                     "patent's own words, the gazetteer, an all-electric company, or a "
                     "*_human cell you already filled. name_review / electric_review / "
                     "takeoff_review are the same thing as separate booleans."),
    ("Why a row is NOT queued for electric",
     "is_electric_source says who answered it: keyword (the patent's words, quoted in "
     "powertrain_quote), gazetteer (curated company -> aircraft), company (every aircraft "
     "that company builds is battery-electric), human (your cell, or the annotator's "
     "disapproval reason). A low-confidence SBERT guess answers nothing: it stays visible "
     "in powertrain with its score while is_electric abstains, and the row IS queued."),
    ("What a bare 'Out of Domain' disapproval settles", "Nothing. It is about to be split "
     "into sub-reasons, so today it does not say which one applied. A reason that names the "
     "thing ('Not VTOL', a future 'Out of TD - Electric') does settle that field."),
    ("aircraft_group", "The working aircraft name — never empty. Source order: the "
                       "wizard's aircraftName > inherited from the duplicate's original "
                       "(D1/D2 = same aircraft) > original's name + letter (D3 = variant) "
                       "> '<assignee> <N>' generated, N unique across the whole corpus. "
                       "aircraft_group_source says which; aircraft_group_note flags a "
                       "D1/D2 whose wizard name differs from its original's."),
    ("aircraft_name", "The machine's PROPOSAL for the real aircraft (S4, Vertiia...). "
                      "A gazetteer proposal is inferred from company + filing year and "
                      "usually does NOT appear in the patent — see aircraft_name_in_text. "
                      "It is never copied into *_final by itself."),
    ("aircraft_name_in_text / _section / _quote",
     "Whether the proposed name literally appears, and where. Searched in Title, "
     "Abstract, First claim, Summary of invention, Description of drawings ONLY — "
     "deliberately not the full Description, because patents routinely name other "
     "people's aircraft in their prior-art discussion. The powertrain pass DOES read "
     "the full Description (powertrain_section then says 'Description' or 'Claims')."),
    ("aircraft_name_human", HUMAN_OPTIONS["aircraft_name_human"]),
    ("aircraft_name_final", "aircraft_name_human if you typed one, else aircraft_group."),
    ("is_electric / powertrain", "Machine reading of the energy source, decided the way a "
                                 "reviewer would: it is easy to show an aircraft is NOT electric "
                                 "(one committed sentence naming a turbine or piston engine as "
                                 "the propulsion) and nearly impossible to show it IS. So every "
                                 "family the text states is collected; a combustion statement "
                                 "decides (Turbine/Piston -> No, queued for you to confirm); a "
                                 "hybrid statement -> Hybrid; only electric statements -> Yes; "
                                 "BOTH combustion and electric stated -> Unknown, queued, with "
                                 "both sentences (powertrain_quote and powertrain_other_quote). "
                                 "NOTHING stated -> Unknown with is_electric_source = presumed: "
                                 "this is an approved eVTOL corpus, the burden is on evidence "
                                 "of NOT electric, so the row is not queued. Prior-art and "
                                 "'or an engine' sentences never count as statements."),
    ("powertrain_other / powertrain_other_quote",
     "The second propulsion family the text also states, with its sentence — the "
     "battery inside a hybrid, or the turbine next to an electric motor. Read it before "
     "confirming."),
    ("is_electric_human", HUMAN_OPTIONS["is_electric_human"] + " — 'No' is your disapproval. "
                          "Every machine 'No' or 'Hybrid' is queued for you to confirm: a "
                          "machine must never disapprove a patent on its own. A 'No' the "
                          "annotator already gave is ground truth and is not re-asked."),
    ("takeoff_mode", "Keyword reading of the take-off vocabulary: " + TAKEOFF_OPTIONS + ". "
                     "V/STOL = the text uses BOTH vocabularies; for STOL and V/STOL the "
                     "quote is the STOL sentence — read it before disapproving. Empty = "
                     "no take-off vocabulary in the loaded sections."),
    ("takeoff_human", HUMAN_OPTIONS["takeoff_human"] + " — 'STOL' is your disapproval."),
    ("review_status", HUMAN_OPTIONS["review_status"]),
    ("wizard_*", "The human T1 record from the wizard export (03c): isApproved, "
                 "disapproval reason, aircraftName, duplicateType (1/2/3), duplicateId. "
                 "Use wizard_approved == TRUE to restrict any statistic to the approved "
                 "corpus."),
    ("Dates", "priority_year < app_year (filing) < pub_year (publication). "
              "snapshot_date is the PatSeer export date; anything with a priority "
              "date within ~2 years of it (US/DE/JP/KR publish ~18 months after "
              "priority; CN faster) is under-counted, so truncate time series there. "
              "This export has no grant-date column: grant_lag_years is empty on purpose."),
    ("", ""),
    ("SHEET: Identity", "One row per patent — the table to join onto your label data."),
    ("Duplicates — WHICH aircraft?",
     "duplicateId names a PATENT. When that patent describes several aircraft, 'a duplicate of "
     "it' does not say which one — 27 rows here. duplicate_root_aircraft gives the count. If the "
     "original's aircraft all carry the same answers the inheritance is unambiguous and nothing "
     "is asked; if they DIFFER, duplicate_ambiguous is TRUE, the row is queued as 'duplicate', "
     "and you name the aircraft in duplicate_root_variant (a, b, c …). Stated here so the thesis "
     "can state it."),
    ("Duplicates", "A D1 or D2 IS the original aircraft (D2 down to the same figures, D1 "
                   "re-drawn), so it is never in the review queue: it inherits every *_final "
                   "from the chain root, named in duplicate_root. Only a D3 — a different "
                   "aircraft — is reviewed on its own. duplicate_root_note says when a root "
                   "sits in another batch and the inheritance has to happen at the join."),
    ("SHEET: Variants", "One row per AIRCRAFT, derived from Identity: a patent describing "
                        "three aircraft gives three rows (variant_id US123_arch1/2/3). This is "
                        "the analysis unit for the design-space statistics — each aircraft "
                        "counts once. Every column is the resolved per-variant value: the "
                        "patent-level answer unless you overrode that variant in a "
                        "*_human_variants cell. Rebuilt on every export; never edit it."),
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
    ("blades_primary / blades_all",
     "Blades per propulsor, from the patent text. blades_all keeps the per-role "
     "detail ('5 (Lift); 3 (Cruise)') because differing lift and cruise "
     "propulsors are the interesting case. Empty is common — a patent claiming "
     "'a plurality of blades' is deliberately not committing to a number, and "
     "counting them off the drawing is the image pipeline's job, not this one's."),
    ("legal_stage", "Granted vs Application — the answer to 'was it accepted, "
                    "not just filed'. Read from a Legal Status column when the "
                    "export has one (legal_stage_source = legal_status), else "
                    "from the publication number's kind code (US...B2 granted, "
                    "US...A1 application, any WO number is an application)."),
    ("right_active", "FALSE when the status says lapsed/expired/withdrawn. Kept "
                     "separate from legal_stage: a lapsed patent still cleared "
                     "examination."),
    ("forward_citations_per_year",
     "Forward citations divided by years since publication. RANK ON THIS, not "
     "on the raw count — a 2015 patent has had a decade to accumulate citations "
     "and a 2023 patent has not, and eVTOL filing volume rose steeply over that "
     "window, so raw counts order the corpus by age and call it impact."),
    ("in_corpus_forward_share",
     "Share of forward citations that land inside this eVTOL corpus. Low means "
     "the patent is being used by a different field."),
    ("self_citations_in_corpus",
     "Backward citations to the same canonical company — a company building on "
     "its own filings. A floor, not a total: only computable for cites that are "
     "themselves in the corpus."),
    ("impact_tier", "Corpus-relative percentile band of forward_citations_per_year. "
                    "Percentiles are computed over CITED rows only, so 'Medium' "
                    "does not collapse to 'cited once'."),
    ("maturity_tier", "legal_stage x impact_tier. Established = granted and "
                      "cited. Granted = cleared examination, not yet built on. "
                      "Active = still an application but already cited — a live, "
                      "watched filing. Filed = application, uncited."),
    ("", ""),
    ("aircraft_name", "Best guess at the real aircraft. Empty = unknown, which is the "
                      "expected outcome for most patents."),
    ("*_source", "Where the value came from: gazetteer > llm > sbert > keyword > regex. "
                 "Set it to 'human' after you correct a value and a re-run will keep it."),
    ("*_confidence", "0-1. Below 0.55 the row is flagged in needs_review."),
    ("is_electric", "Yes | Hybrid | No | Unknown — derived from powertrain, never "
                    "predicted separately. It abstains (Unknown) when the only "
                    "powertrain evidence is an SBERT similarity score below 0.55: "
                    "the proposal stays visible in the powertrain column, but a "
                    "coin-flip must not read as a verdict in the column you act on."),
    ("powertrain", "|".join(POWERTRAIN_DEFS)),
    ("industry_primary", "|".join(INDUSTRY_DEFS)),
    ("region", "From the assignee's country code; falls back to the publication office."),
    ("Units", "mass kg | speed km/h | range km | endurance minutes | pax persons"),
    ("needs_review", "TRUE when one of the three reviewed fields needs a decision: a "
                     "generated group name, a proposed name not found in the text, an "
                     "unknown powertrain or take-off mode, STOL/CTOL language, or a "
                     "company-attributed proposal. review_reason says which. Specs, "
                     "scope and architecture never raise it."),
    ("Specs caution", "A spec with source='regex' came from the patent text and is "
                      "usually an illustrative embodiment, not the built aircraft. "
                      "Verify before citing."),
]


def _backup(path: Path) -> Path | None:
    """Timestamped backup before overwriting — same convention as scripts/.

    Into a `_backups/` subfolder, not beside the file: this stage re-runs often,
    and a pile of `aircraft_identity_Batch_01.BACKUP_*.xlsx` next to the real one
    is read by anything globbing the folder (it silently tripled a corpus count
    during the 2026-09-08 build).
    """
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = path.parent / "_backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{path.stem}.BACKUP_{stamp}{path.suffix}"
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
    # rather than letting the two columns drift apart. Same abstention rule as
    # the row builder, so a re-run cannot promote a low-confidence SBERT guess.
    # Only a row whose POWERTRAIN the reviewer overrode by hand (the older
    # *_source == "human" mechanism) needs its verdict recomputed; every other
    # row already carries the verdict the row builder just made, and
    # recomputing it here would throw away "company" / "presumed" / the
    # two-family abstention.
    for i, (p, ps, c) in enumerate(zip(merged["powertrain"], merged["powertrain_source"],
                                       merged["powertrain_confidence"])):
        if str(ps) == "human":
            v, src = electric_verdict(p, ps, c)
            merged.iloc[i, merged.columns.get_loc("is_electric")] = v
            merged.iloc[i, merged.columns.get_loc("is_electric_source")] = src
    merged = merged.reset_index()
    return recompute_finals(merged)


def recompute_finals(df):
    """*_final = *_human when typed, else the machine column — the same
    apply_finals() the row builder uses, so the two can never disagree."""
    rows = df.to_dict("records")
    for r in rows:
        apply_finals(r)
    # Re-run after a human edit too: answering the original of a duplicate chain
    # must reach its duplicates on the very next export.
    propagate_duplicate_finals(rows)
    for r in rows:
        r.update(review_flags(r))
    for c in FINAL_COLUMNS + ["duplicate_root", "duplicate_root_note",
                              "duplicate_root_aircraft", "duplicate_ambiguous",
                              "review_queue", "name_review", "electric_review",
                              "takeoff_review", "uav_review"]:
        df[c] = [r.get(c) for r in rows]
    return df


def _is_blank(v) -> bool:
    if v is None:
        return True
    try:
        if v != v:
            return True
    except Exception:
        pass
    return str(v).strip() == ""


def export_identity_excel(
    rows: list[dict],
    evidence: list[dict],
    prompts: list[dict],
    out_path: "str | Path",
    preserve_human: bool = True,
    figures: list[dict] | None = None,
    write_figures: bool = True,
) -> Path:
    """Write aircraft_identity_<batch>.xlsx.

    Sheets: Identity / [Figures] / Evidence / LLM_Prompts / README. The Figures
    sheet is a text-level guess at what each drawing shows and the reviewer does
    not use it; `write_figures=False` leaves it out (the per-patent figure
    counts on Identity are still computed).

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
        variants_df = build_variants_sheet(ident_df)
        variants_df.to_excel(writer, sheet_name="Variants", index=False)
        if write_figures:
            fig_df.to_excel(writer, sheet_name="Figures", index=False)
        ev_df.to_excel(writer, sheet_name="Evidence", index=False)
        pr_df.to_excel(writer, sheet_name="LLM_Prompts", index=False)
        readme_df.to_excel(writer, sheet_name="README", index=False)

        _format_identity_sheet(writer.sheets["Identity"], ident_df)

    return out_path


# ─── Making the Identity sheet readable ──────────────────────────────────────

def _format_identity_sheet(ws, df) -> None:
    """Freeze, widen, filter and colour.

    One sheet, not two: Identity must stay a single row-per-patent table you can
    join on patent_id. Colour carries "what is mine to fill / what is already a
    fact / what still needs me" without splitting the table in half.

        amber   the cells you type into NOW
        teal    what you already decided in the wizard (read-only here)
        violet  the *_final columns the thesis joins on
        green   a verdict something citable already answered
        orange  a verdict still in your queue
        blue    the evidence behind a verdict — read it to decide
        grey    bibliographic fact from the PatSeer export or your wizard record
    """
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    group_of = {c: g for g, cols in COLUMN_GROUPS.items() for c in cols}
    fills = {k: PatternFill("solid", fgColor=v) for k, v in FILLS.items()}

    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions          # so review_queue can be filtered in one click

    for idx, col in enumerate(IDENTITY_COLUMNS, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = (
            60 if col.endswith("_quote") else
            42 if col in ("title", "llm_reasoning", "aircraft_name_alternatives") else
            28 if col in ("assignee_raw", "company_canonical", "review_reason",
                          "aircraft_group", "aircraft_group_note", "review_queue",
                          "wizard_disapprove_reason", "aircraft_name_human") else 16)
        head = ws.cell(row=1, column=idx)
        head.fill = fills.get(group_of.get(col, "other"), fills["other"])
        head.font = Font(bold=True)
        head.alignment = Alignment(vertical="top", wrap_text=True)

    # Per-row colour on the three verdicts and the queue: green when something
    # citable answered it, orange when it is still yours to decide.
    col_at = {c: i + 1 for i, c in enumerate(IDENTITY_COLUMNS)}
    pairs = [("aircraft_group", "name_review"), ("aircraft_name", "name_review"),
             ("is_electric", "electric_review"), ("takeoff_mode", "takeoff_review"),
             ("uav_hint", "uav_review")]
    for r, (_, row) in enumerate(df.iterrows(), start=2):
        queued = bool(row.get("review_queue"))
        ws.cell(row=r, column=col_at["review_queue"]).fill = \
            fills["open"] if queued else fills["settled"]
        for value_col, flag_col in pairs:
            ws.cell(row=r, column=col_at[value_col]).fill = \
                fills["open"] if row.get(flag_col) else fills["settled"]
        for col in COLUMN_GROUPS["yours"]:
            ws.cell(row=r, column=col_at[col]).fill = fills["yours"]
        for col in COLUMN_GROUPS["final"]:
            ws.cell(row=r, column=col_at[col]).fill = fills["final"]
        for col in COLUMN_GROUPS["wizard"]:
            ws.cell(row=r, column=col_at[col]).fill = fills["wizard"]


# ─── The per-variant view ────────────────────────────────────────────────────

VARIANT_COLUMNS = [
    "variant_id", "patent_id", "batch", "variant_n", "variant_of", "is_primary",
    "company_canonical", "wizard_approved", "top_type",
    "aircraft_group", "aircraft_name_final",
    "is_electric_final", "takeoff_final", "uav_final",
    "review_status",
]


def build_variants_sheet(ident_df):
    """One row per AIRCRAFT, resolved from the Identity sheet.

    The analysis unit for the design-space work is the aircraft variant, not the
    patent (methodology framework, Part D-1): a patent describing three aircraft
    contributes three designs. Every value here is the per-variant answer where
    one was given and the patent-level answer otherwise, so this sheet is always
    complete and always agrees with Identity.
    """
    import pandas as pd

    def nth(joined, i, fallback):
        if joined is None or str(joined).strip() in ("", "nan", "None"):
            return fallback
        parts = [p.strip() for p in str(joined).split(";")]
        return parts[i] if i < len(parts) and parts[i] else fallback

    rows = []
    for _, r in ident_df.iterrows():
        n = arch_n(r.get("wizard_arch_count"))
        types = [t.strip() for t in str(r.get("wizard_variant_types") or "").split("|")]
        for i in range(n):
            rows.append({
                "variant_id": r["patent_id"] if n == 1 else f"{r['patent_id']}_arch{i + 1}",
                "patent_id": r["patent_id"],
                "batch": r.get("batch"),
                "variant_n": i + 1,
                "variant_of": n,
                "is_primary": i == 0,
                "company_canonical": r.get("company_canonical"),
                "wizard_approved": r.get("wizard_approved"),
                "top_type": types[i] if i < len(types) and types[i] not in ("", "?") else None,
                "aircraft_group": r.get("aircraft_group"),
                "aircraft_name_final": nth(r.get("aircraft_name_final_variants"), i,
                                           r.get("aircraft_name_final")),
                "is_electric_final": nth(r.get("is_electric_final_variants"), i,
                                         r.get("is_electric_final")),
                "takeoff_final": nth(r.get("takeoff_final_variants"), i, r.get("takeoff_final")),
                "uav_final": nth(r.get("uav_final_variants"), i, r.get("uav_final")),
                "review_status": r.get("review_status"),
            })
    return pd.DataFrame(rows, columns=VARIANT_COLUMNS)
