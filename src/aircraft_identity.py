"""
aircraft_identity.py — Stage 03a's entry point: merge every signal about a
patent into one row.

This module owns the MERGE, not the extraction. Each signal lives in its own
module and is re-exported here, so a notebook needs exactly one import:

    src/patent_geography.py   where the applicant is, where it was filed
    src/aircraft_naming.py    candidate aircraft names mined from the text
    src/aircraft_specs.py     powertrain, industry, performance, blade counts
    src/aircraft_gazetteer.py the curated company -> aircraft table
    src/identity_llm.py       asking a model which aircraft it is
    src/patent_scope.py       scope, architecture, specificity, aircraft_link
    src/patent_maturity.py    granted vs filed, citations, maturity tier
    src/identity_excel.py     the workbook writer

The merge rule is one fixed precedence, so a weaker signal can never silently
overwrite a stronger one:

    human  >  gazetteer  >  llm  >  sbert  >  keyword  >  regex

Every field carries its own `*_source` and `*_confidence`, because none of these
questions is answerable for every patent and the sheet has to say which answers
you can actually cite. A patent with nothing known keeps empty cells and
needs_review=True — it never gets a guess dressed up as data.

Assembly order (the notebook follows it, and it matters):

    build_identity_row()  ->  attach_scope()  ->  attach_maturity()

attach_scope runs second because specificity depends on the resolved
aircraft_name AND on where that name came from: a gazetteer name is company-
level evidence and must not argue that this patent depicts that aircraft.

Public API
----------
build_identity_row(...)   -> (row, evidence_rows)
attach_scope(row, ...)    -> row      folds in src/patent_scope.py
attach_maturity(row, ...) -> row      folds in src/patent_maturity.py
export_identity_excel(...)-> Path     re-exported from src/identity_excel.py
plus every extractor from the modules listed above.
"""

from __future__ import annotations

# ── Re-exports: one import site for the whole stage ─────────────────────────
from src.patent_geography import (          # noqa: F401
    assignee_country, region_for, publication_office,
    REGION_BY_COUNTRY, REGION_BY_OFFICE,
)
from src.aircraft_naming import mine_name_candidates          # noqa: F401
from src.aircraft_specs import (             # noqa: F401
    classify_powertrain, classify_industry, extract_spec_hints,
    extract_blade_counts, summarise_blade_counts,
    POWERTRAIN_DEFS, POWERTRAIN_KEYWORDS, ELECTRIC_BY_POWERTRAIN,
    IS_ELECTRIC_OPTIONS, INDUSTRY_DEFS, SPEC_FIELDS, BLADE_COLUMNS,
    _CONF_REGEX_SPEC, _to_float,
)
from src.aircraft_gazetteer import (         # noqa: F401
    load_gazetteer, match_gazetteer, GAZETTEER_COLUMNS,
    _CONF_GAZETTEER_EXACT, _CONF_GAZETTEER_LOOSE,
)
from src.identity_llm import (               # noqa: F401
    build_llm_prompt, parse_llm_answer, ask_claude,
    LLM_SYSTEM_PROMPT, LLM_OUTPUT_SCHEMA,
)
from src.identity_excel import (             # noqa: F401
    export_identity_excel, merge_preserving_human,
)
from src.patent_scope import SCOPE_COLUMNS as _SCOPE_COLUMNS
from src.patent_maturity import MATURITY_COLUMNS as _MATURITY_COLUMNS
from src.identity_schema import (           # noqa: F401
    IDENTITY_COLUMNS, EVIDENCE_COLUMNS, PROMPT_COLUMNS, HUMAN_COLUMNS,
    SOURCE_PRECEDENCE, NEEDS_REVIEW_BELOW, _CONF_HUMAN,
)
from src.grouper import _normalise_company

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
    blade_hits: list[dict] | None = None,
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
    blade_hits = blade_hits or []
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

    # ── blade counts ─────────────────────────────────────────────────────────
    # Not merged through _pick(): the gazetteer has no blade column and the LLM
    # is not asked for one, so text is the only source and there is nothing to
    # outrank. Each hit still lands in Evidence with the sentence it came from.
    for hit in blade_hits:
        _ev(f"blades[{hit['role']}]", hit["count"], hit["source"],
            hit["confidence"], hit.get("context", ""))
    blade_cols = summarise_blade_counts(blade_hits)

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
        **blade_cols,
        # Filled by attach_scope() once src/patent_scope.py has run — it needs
        # the resolved aircraft_name, so it cannot run before this point.
        **{c: None for c in _SCOPE_COLUMNS},
        # Filled by attach_maturity().
        **{c: None for c in _MATURITY_COLUMNS},
        "needs_review": bool(reasons),
        "review_reason": "; ".join(reasons) or None,
        "llm_reasoning": (llm_answer.get("reasoning") or None),
        "reviewed_by": None,
        "reviewed_at": None,
        "notes": None,
    }
    return row, evidence


def attach_maturity(row: dict, maturity_row: dict) -> dict:
    """Fold src/patent_maturity.build_maturity_row()'s columns into a row.

    Order-independent of attach_scope(): maturity depends only on the patent's
    own bibliographic data, not on anything the other two modules resolve. It
    adds no review reasons — a patent being young or uncited is a fact about it,
    not something a reviewer can fix.
    """
    row.update({c: maturity_row.get(c) for c in _MATURITY_COLUMNS})
    return row


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


