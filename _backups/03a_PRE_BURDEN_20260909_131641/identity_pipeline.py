"""
identity_pipeline.py — the Stage 03a runner.

Everything the 03a notebook does, as five functions, so the notebook stays a
recipe you can read in one screen instead of 500 lines of loop bodies:

    load_inputs(cfg, batch_id, limit)   -> Stage03aInputs
    analyse(inputs, sbert)              -> Stage03aResults      (no LLM yet)
    build_prompts(inputs, results, ...) -> {patent_id: prompt}
    apply_llm(inputs, results, answers) -> Stage03aResults       (re-merged)
    export(inputs, results, prompts)    -> Path
    report(results)                     -> prints the coverage summary

The assembly ORDER inside analyse() is the part that matters, and it is the
reason this lives in one place rather than being retyped in every cell that
needs it:

    build_identity_row()      merge gazetteer / LLM / text signals into a row
        -> attach_scope()     scope, architecture, specificity, aircraft_link
        -> attach_maturity()  granted vs filed, citations, tier
        -> add_corpus_percentiles()   once, over every row

attach_scope must run after the identity row because specificity depends on
WHERE the aircraft name came from: a gazetteer name is company-level evidence
and must never argue that this particular patent depicts that aircraft.
add_corpus_percentiles must run last because a percentile needs the whole set.

Citation links and percentiles are computed against the FULL PatSeer index, not
the batch — otherwise a patent's rank would depend on which batch it landed in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src import aircraft_identity as ai
from src import patent_scope as ps
from src import patent_maturity as pm
from src import wizard_link as wl
from src.text_citation import classify_takeoff, classify_uav, enrich_full_text
from src.extractor import load_patseer_excel


@dataclass
class Stage03aInputs:
    """Everything the stage reads. Built once by load_inputs()."""
    cfg: dict
    batch: str                       # "Batch_01"
    patent_ids: list[str]
    excel_index: dict                # full PatSeer index, NOT batch-scoped
    batch_meta: dict                 # patent_id -> company_canonical / prototype_label
    gazetteer: list[dict]
    enrichment: dict = field(default_factory=dict)   # which optional columns were found
    wizard: dict = field(default_factory=dict)       # patent_id -> T1 human record (all batches)
    groups: dict = field(default_factory=dict)       # patent_id -> aircraft_group (whole corpus)
    snapshot_date: "str | None" = None               # PatSeer export date, ISO

    def classify_text(self, pid: str) -> str:
        """Title + abstract + first claim + summary.

        Signal-first, because PatentSBERTa truncates around 384 tokens. The full
        Description is not available by design — load_patseer_excel() skips it
        (most would be truncated away and what survives is boilerplate).
        """
        m = self.excel_index.get(pid, {})
        return "\n".join(x for x in (m.get("title"), m.get("abstract"),
                                     m.get("first_claim"),
                                     m.get("innovation_objective")) if x)

    def body_text(self, pid: str) -> str:
        """Full Description + Claims, when enrich_full_text() loaded them.

        Only the powertrain keyword pass reads this. It is where most patents
        actually state their energy source, and a hit here still quotes a real
        sentence — see text_citation.BODY_SECTIONS.
        """
        m = self.excel_index.get(pid, {})
        return "\n".join(x for x in (m.get("claims_full"), m.get("description")) if x)

    def name_text(self, pid: str) -> str:
        """Same, plus the drawings description — a trade name, when it appears
        at all, tends to appear in the figure captions."""
        m = self.excel_index.get(pid, {})
        return "\n".join(x for x in (m.get("title"), m.get("abstract"),
                                     m.get("description_of_drawings"),
                                     m.get("innovation_objective")) if x)


@dataclass
class Stage03aResults:
    rows: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    figures: list[dict] = field(default_factory=list)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=ai.IDENTITY_COLUMNS)


# ─── 1. Load ─────────────────────────────────────────────────────────────────

def load_inputs(cfg: dict, batch_id: int, limit: int | None = None,
                repo_root: "Path | None" = None, verbose: bool = True,
                snapshot_date: "str | None" = None,
                wizard_dir: "str | Path | None" = None,
                full_text: bool = True) -> Stage03aInputs:
    """Read batches.xlsx, the PatSeer export, the gazetteer and the wizard record.

    `snapshot_date` is the ISO date of the PatSeer export; ages are measured to
    it (see patent_maturity.build_maturity_row). `wizard_dir` defaults to
    cfg paths.corrected_wizard_exports (03c) — the live human record.

    The wizard files and the aircraft-group index are built over EVERY batch,
    not just `batch_id`: a duplicate's original may sit in another batch, and
    a generated "<assignee> <N>" must be unique corpus-wide.
    """
    batch = f"Batch_{batch_id:02d}"
    batches_path = cfg["paths"]["batches_xlsx"]
    if not Path(batches_path).exists():
        raise FileNotFoundError(
            f"batches.xlsx not found at {batches_path} — run 00b1_grouping first.")

    # company_canonical / prototype_label are already on the batch sheets
    # (written by 00b1_grouping). Reusing them keeps this workbook's company
    # column identical to the one every other stage sees.
    sheets = pd.read_excel(batches_path, sheet_name=None, dtype=str)
    batch_sheets = {k: v.fillna("") for k, v in sheets.items() if k.startswith("Batch_")}
    if batch not in batch_sheets:
        raise KeyError(f"{batch} is not a sheet of {batches_path}: {sorted(batch_sheets)}")

    def _meta(df):
        return {
            str(r["patent_id"]).strip(): {
                "company_canonical": (r.get("company_canonical") or "").strip() or None,
                "prototype_label": (r.get("prototype_label") or "").strip() or None,
                "batch": (r.get("batch_id") or "").strip() or None,
            }
            for _, r in df.iterrows()
        }
    all_meta: dict = {}
    for df in batch_sheets.values():
        all_meta.update(_meta(df))
    all_ids = list(all_meta)

    patent_ids = batch_sheets[batch]["patent_id"].str.strip().tolist()
    if limit:
        patent_ids = patent_ids[:limit]

    excel_index = load_patseer_excel(cfg["paths"]["patseer_excel"])
    # Maturity columns are merged in here rather than by widening
    # load_patseer_excel(), so no other notebook's behaviour changes.
    enrichment = pm.enrich_from_excel(excel_index, cfg["paths"]["patseer_excel"])
    # The full Description/Claims, for the powertrain keyword pass only.
    if full_text:
        enrichment["full_text"] = enrich_full_text(
            excel_index, cfg["paths"]["patseer_excel"], verbose=verbose)

    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    gazetteer = ai.load_gazetteer(root / "reference" / "evtol_gazetteer.csv")

    wdir = Path(wizard_dir) if wizard_dir else Path(cfg["paths"].get("corrected_wizard_exports", ""))
    wizard = wl.load_wizard_reviews(wdir, verbose=verbose) if str(wdir) else {}
    groups = wl.assign_aircraft_groups(all_ids, all_meta, excel_index, wizard)

    inputs = Stage03aInputs(cfg, batch, patent_ids, excel_index, all_meta,
                            gazetteer, enrichment, wizard, groups, snapshot_date)
    if verbose:
        _print_load_summary(inputs, limit)
    return inputs


def _print_load_summary(inputs: Stage03aInputs, limit: int | None) -> None:
    n = len(inputs.patent_ids)
    print(f"{inputs.batch}: {n} patents"
          + (f" (LIMIT={limit})" if limit else "")
          + f"; PatSeer index has {len(inputs.excel_index)} rows.")

    companies = {g["company_canonical"] for g in inputs.gazetteer}
    covered = sum(1 for p in inputs.patent_ids
                  if inputs.batch_meta.get(p, {}).get("company_canonical") in companies)
    print(f"Gazetteer: {len(inputs.gazetteer)} aircraft across {len(companies)} "
          f"companies — covers the company of {covered}/{n} patents in this batch.")

    found = inputs.enrichment.get("found") or {}
    if found:
        print(f"Maturity columns found: {', '.join(sorted(found))}")
    else:
        print("No optional maturity columns in this export — legal_stage will come "
              "from kind codes (reliable for granted-vs-filed), and family / claim / "
              "figure columns stay empty.")

    missing = [p for p in inputs.patent_ids if p not in inputs.excel_index]
    if missing:
        print(f"⚠  {len(missing)} patent(s) have no PatSeer row: {missing[:5]}")

    gs = wl.group_summary(inputs.groups, inputs.patent_ids)
    print("Aircraft group names: " + ", ".join(f"{k}={v}" for k, v in sorted(gs.items())))
    if inputs.snapshot_date:
        print(f"Snapshot date: {inputs.snapshot_date} (ages and citation rates measured to it)")
    else:
        print("⚠  No SNAPSHOT_DATE — ages measured to today, not to the export date.")


# ─── 2. Analyse ──────────────────────────────────────────────────────────────

def analyse(inputs: Stage03aInputs, sbert=None,
            llm_answers: dict | None = None, verbose: bool = True) -> Stage03aResults:
    """Run every signal over the batch and assemble one row per patent."""
    llm_answers = llm_answers or {}
    results = Stage03aResults()
    all_electric = ai.all_electric_companies(inputs.gazetteer)

    for i, pid in enumerate(inputs.patent_ids, 1):
        meta = inputs.excel_index.get(pid, {})
        ctext, ntext = inputs.classify_text(pid), inputs.name_text(pid)

        row, ev = ai.build_identity_row(
            patent_id=pid, batch=inputs.batch, meta=meta,
            batch_meta=inputs.batch_meta.get(pid, {}),
            gaz_hit=ai.match_gazetteer(
                inputs.batch_meta.get(pid, {}).get("company_canonical"),
                meta.get("app_year"), inputs.gazetteer,
                assignee_raw=meta.get("assignee"), text=ntext),
            powertrain_pred=ai.classify_powertrain(ctext, sbert,
                                                   body_text=inputs.body_text(pid)),
            industry_pred=ai.classify_industry(ctext, sbert),
            name_candidates=ai.mine_name_candidates(ntext, pid, sbert),
            spec_hints=ai.extract_spec_hints(ctext),
            blade_hits=ai.extract_blade_counts(ctext),
            llm_answer=llm_answers.get(pid),
            takeoff_pred=classify_takeoff(meta),
            wizard=inputs.wizard.get(pid),
            group=inputs.groups.get(pid),
            company_all_electric=(
                inputs.batch_meta.get(pid, {}).get("company_canonical") in all_electric),
            uav_pred=classify_uav(meta),
        )

        scope_row, figs, scope_ev = ps.build_scope_row(
            patent_id=pid, classify_text=ctext,
            description_of_drawings=meta.get("description_of_drawings"),
            sbert_model=sbert,
            aircraft_name=row["aircraft_name"],
            aircraft_name_source=row["aircraft_name_source"],
        )
        ai.attach_scope(row, scope_row)
        ai.attach_maturity(row, pm.build_maturity_row(
            pid, inputs.excel_index, snapshot_date=inputs.snapshot_date))

        results.rows.append(row)
        results.evidence.extend(ev)
        results.evidence.extend(scope_ev)
        results.figures.extend(figs)

        if verbose and (i % 50 == 0 or i == len(inputs.patent_ids)):
            print(f"  {i}/{len(inputs.patent_ids)}")

    # Percentiles need every row, so this is a second pass over the finished set.
    pm.add_corpus_percentiles(results.rows)
    return results


# ─── 3. LLM step ─────────────────────────────────────────────────────────────

def build_prompts(inputs: Stage03aInputs, results: Stage03aResults,
                  only_unresolved: bool = True) -> dict[str, str]:
    """One question per patent for the chat step.

    `only_unresolved` skips the patents the gazetteer already named — the cheap
    default. Set it False once, to measure how often the LLM and the gazetteer
    agree on the rows both cover; that overlap is your evidence for how far to
    trust the LLM, and it belongs in the methodology chapter.
    """
    named = {r["patent_id"] for r in results.rows
             if r["aircraft_name"] and r["aircraft_name_source"] == "gazetteer"}
    prompts = {}
    for pid in inputs.patent_ids:
        if only_unresolved and pid in named:
            continue
        meta = inputs.excel_index.get(pid, {})
        prompts[pid] = ai.build_llm_prompt({
            "patent_id": pid,
            "company_canonical": inputs.batch_meta.get(pid, {}).get("company_canonical"),
            "assignee_raw": meta.get("assignee"),
            "app_year": meta.get("app_year"), "pub_year": meta.get("pub_year"),
            "title": meta.get("title"), "abstract": meta.get("abstract"),
        })
    return prompts


def read_pasted_answers(xlsx_path: "str | Path") -> dict[str, dict]:
    """Parse the llm_answer column of an exported workbook's LLM_Prompts sheet.

    Tolerant of ```json fences and surrounding prose. A cell that cannot be
    parsed is reported, not raised — one bad paste must not abort a 350-row run.
    """
    pasted = pd.read_excel(xlsx_path, sheet_name="LLM_Prompts", dtype=object)
    answers, unparseable = {}, []
    for _, r in pasted.iterrows():
        parsed = ai.parse_llm_answer(r.get("llm_answer"))
        pid = str(r["patent_id"]).strip()
        if parsed:
            answers[pid] = parsed
        elif pd.notna(r.get("llm_answer")) and str(r.get("llm_answer")).strip():
            unparseable.append(pid)
    print(f"Parsed {len(answers)} answer(s).")
    if unparseable:
        print(f"⚠  {len(unparseable)} cell(s) were not parseable JSON: {unparseable[:5]}")
    return answers


# ─── 4. Export ───────────────────────────────────────────────────────────────

def export(inputs: Stage03aInputs, results: Stage03aResults,
           prompts: dict[str, str] | None = None, write_figures: bool = True) -> Path:
    """Write aircraft_identity_<batch>.xlsx next to the batch's other artefacts."""
    prompt_rows = [
        {"patent_id": pid,
         "company_canonical": inputs.batch_meta.get(pid, {}).get("company_canonical"),
         "app_year": inputs.excel_index.get(pid, {}).get("app_year"),
         "llm_prompt": prompt, "llm_answer": None}
        for pid, prompt in (prompts or {}).items()
    ]
    data_matched = Path(inputs.cfg["paths"].get("data_matched", inputs.cfg["paths"]["data"]))
    out_path = data_matched / inputs.batch / f"aircraft_identity_{inputs.batch}.xlsx"

    ai.export_identity_excel(results.rows, results.evidence, prompt_rows, out_path,
                             preserve_human=True, figures=results.figures,
                             write_figures=write_figures)
    print(f"Wrote {len(results.rows)} patent row(s), {len(results.figures)} figure row(s), "
          f"{len(results.evidence)} evidence row(s)\n  -> {out_path}")
    return out_path


# ─── 5. Report ───────────────────────────────────────────────────────────────

def report(results: Stage03aResults) -> pd.DataFrame:
    """Print what this batch can actually support in the thesis.

    Read the "answered" counts as the population each downstream statistic is
    computed over. A 40% naming rate is a real result about patent drafting
    practice, not a failed run.
    """
    ident = results.frame()
    n = len(ident)
    if not n:
        print("No rows.")
        return ident

    def pct(k):
        return f"{k:>5} / {n}  ({k / n:6.1%})"

    print(f"=== {ident['batch'].iloc[0]} — {n} patents ===\n")

    # The queue first: it is the number that decides how long the review takes.
    ap = (ident["wizard_approved"] == True)                      # noqa: E712
    q = ident["review_queue"].fillna("")
    print("REVIEW QUEUE — what still needs you")
    print(f"  in the queue    {pct((q != '').sum())}   "
          f"(of {int(ap.sum())} the annotator approved)")
    print(f"    name          {pct(ident['name_review'].fillna(False).sum())}")
    print(f"    electric      {pct(ident['electric_review'].fillna(False).sum())}")
    print(f"    take-off      {pct(ident['takeoff_review'].fillna(False).sum())}")
    print(f"    uav tag       {pct(ident['uav_review'].fillna(False).sum())}")
    print(f"  settled         {pct(((q == '') & ap).sum())}   (approved, nothing open)")
    print(f"  disapproved     {pct((ident['wizard_approved'] == False).sum())}   "
          f"(out of the corpus, never queued)")     # noqa: E712
    print("\n  by combination:")
    print(ident.loc[q != '', 'review_queue'].value_counts().to_string())
    print("\n  electric answered by:")
    print(ident["is_electric_source"].value_counts(dropna=False).to_string())

    print("\nREVIEW PROGRESS")
    status = ident["review_status"].fillna("").astype(str).str.strip().str.lower()
    print(f"  done            {pct((status == 'done').sum())}")
    print(f"  skip            {pct((status == 'skip').sum())}")
    print(f"  still to do     {pct((~status.isin(['done', 'skip'])).sum())}")
    print(f"  flagged         {pct(ident['needs_review'].sum())}   (needs_review)")
    print(f"  wizard approved {pct((ident['wizard_approved'] == True).sum())}")

    print("\nAIRCRAFT GROUP (working name) — by source")
    print(ident["aircraft_group_source"].value_counts(dropna=False).to_string())
    print(f"  distinct groups in this batch: {ident['aircraft_group'].nunique()}")
    print("\nREAL NAME PROPOSALS")
    print(f"  proposed        {pct(ident['aircraft_name'].notna().sum())}")
    print(f"  ...in text      {pct((ident['aircraft_name_in_text'] == 'Yes').sum())}")
    print(f"  typed by you    {pct(ident['aircraft_name_human'].notna().sum())}")
    print("\nELECTRIC (machine)  /  TAKE-OFF (machine)")
    print(ident["is_electric"].value_counts(dropna=False).to_string())
    print(ident["takeoff_mode"].value_counts(dropna=False).to_string())
    print(f"  electric decided by you  {pct(ident['is_electric_human'].notna().sum())}")
    print(f"  take-off decided by you  {pct(ident['takeoff_human'].notna().sum())}")

    print("\nOTHER COLUMNS (informative, not reviewed)")
    print(f"  scope           {pct(ident['scope'].notna().sum())}")
    print(f"  blade count     {pct(ident['blades_primary'].notna().sum())}")
    print(f"  any spec value  {pct(ident[ai.SPEC_FIELDS].notna().any(axis=1).sum())}")

    # The headline number: how many patents actually support a per-aircraft
    # claim. Everything else is company-level or architecture-level evidence.
    depicted = (ident["aircraft_link"] == "Depicted").sum()
    print(f"\nFigures DEPICT a named aircraft: {pct(depicted)}")
    print("  ^ the population for any statistic grouped by aircraft. The")
    print("    CompanyAttributed rows are company-level evidence only.")

    for title, col in [
        ("REGION", "region"),
        ("LEGAL STAGE — accepted, or only filed?", "legal_stage"),
        ("RIGHT ACTIVE", "right_active"),
        ("MATURITY TIER", "maturity_tier"),
        ("AIRCRAFT LINK (of the proposed name)", "aircraft_link"),
        ("NAME SOURCE", "aircraft_name_source"),
    ]:
        print(f"\n{title}")
        print(ident[col].value_counts(dropna=False).to_string())

    fy = ident["forward_citations_per_year"].fillna(0)
    print(f"\nCITATIONS  median {fy.median():.2f}/yr, max {fy.max():.2f}/yr "
          f"(rank on the per-year figure, never the raw count)")
    top = ident.nlargest(8, "forward_citations_per_year")
    if len(top):
        print(top[["patent_id", "company_canonical", "app_year", "legal_stage",
                   "forward_citations", "forward_citations_per_year",
                   "maturity_tier"]].to_string(index=False))

    print("\nTOP COMPANIES")
    print(ident["company_canonical"].value_counts().head(10).to_string())

    print("\nREVIEW REASONS")
    reasons = (ident["review_reason"].dropna().str.split("; ").explode().value_counts())
    print(reasons.to_string() if len(reasons) else "  none")
    return ident


# ─── Whole-corpus convenience ────────────────────────────────────────────────

def run_all_batches(cfg: dict, sbert=None, repo_root: "Path | None" = None,
                    limit: int | None = None, snapshot_date: "str | None" = None,
                    wizard_dir: "str | Path | None" = None,
                    full_text: bool = True) -> pd.DataFrame:
    """Every Batch_NN sheet in batches.xlsx, one workbook each plus a combined
    table for the thesis. The LLM step is skipped: the export/paste loop is
    per batch, and an unattended API sweep over the whole corpus should be a
    deliberate choice rather than a side effect of running the last cell.
    """
    import openpyxl

    sheets = openpyxl.load_workbook(cfg["paths"]["batches_xlsx"], read_only=True).sheetnames
    all_rows = []
    for sheet in [s for s in sheets if s.startswith("Batch_")]:
        batch_id = int(sheet.split("_")[1])
        inputs = load_inputs(cfg, batch_id, limit=limit, repo_root=repo_root, verbose=False,
                             snapshot_date=snapshot_date, wizard_dir=wizard_dir,
                             full_text=full_text)
        results = analyse(inputs, sbert, verbose=False)
        export(inputs, results)
        all_rows.extend(results.rows)

    combined = Path(cfg["paths"]["data"]) / "Global Statistics" / "aircraft_identity_ALL.xlsx"
    combined.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(all_rows, columns=ai.IDENTITY_COLUMNS)
    df.to_excel(combined, index=False)
    print(f"\nCombined {len(df)} rows -> {combined}")
    return df
