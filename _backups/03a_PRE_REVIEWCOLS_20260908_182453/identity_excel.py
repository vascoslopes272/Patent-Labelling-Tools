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

from src.aircraft_specs import SPEC_FIELDS, ELECTRIC_BY_POWERTRAIN, POWERTRAIN_DEFS, INDUSTRY_DEFS
from src.patent_scope import SCOPE_OPTIONS as _SCOPE_OPTIONS_DOC
from src.identity_schema import (
    IDENTITY_COLUMNS, EVIDENCE_COLUMNS, PROMPT_COLUMNS, HUMAN_COLUMNS,
    _CONF_HUMAN,
)

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
