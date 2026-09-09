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
    extract_blade_counts, summarise_blade_counts, electric_verdict,
    detect_powertrain_families,
    POWERTRAIN_DEFS, POWERTRAIN_KEYWORDS, ELECTRIC_BY_POWERTRAIN,
    IS_ELECTRIC_OPTIONS, INDUSTRY_DEFS, SPEC_FIELDS, BLADE_COLUMNS,
    _CONF_REGEX_SPEC, _to_float,
)
from src.aircraft_gazetteer import (         # noqa: F401
    load_gazetteer, match_gazetteer, all_electric_companies, GAZETTEER_COLUMNS,
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
    FINAL_RULES, FINAL_COLUMNS, HUMAN_OPTIONS, REVIEW_COLUMNS, COLUMN_GROUPS,
    apply_finals, review_flags, variant_names, propagate_duplicate_finals,
    SOURCE_PRECEDENCE, NEEDS_REVIEW_BELOW, _CONF_HUMAN,
)
from src.text_citation import (             # noqa: F401
    find_quote, literal_pattern, classify_takeoff, classify_uav, enrich_full_text,
    UAV_HINT_OPTIONS,
    TAKEOFF_OPTIONS, SECTIONS, SIGNAL_SECTIONS, BODY_SECTIONS, NAME_SECTIONS,
)
from src.wizard_link import (               # noqa: F401
    load_wizard_reviews, assign_aircraft_groups, group_summary, split_group_name,
    human_truth, HUMAN_TRUTH_REASONS,
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
    takeoff_pred: dict | None = None,
    wizard: dict | None = None,
    group: dict | None = None,
    company_all_electric: bool = False,
    uav_pred: dict | None = None,
    presume_electric: bool = True,
) -> tuple[dict, list[dict]]:
    """Merge every signal for one patent into (identity_row, evidence_rows).

    `meta` is the PatSeer excel entry (extractor.load_patseer_excel), and
    `batch_meta` the batches.xlsx row (company_canonical / prototype_label).
    `wizard` is the patent's T1 record from src/wizard_link.load_wizard_reviews
    and `group` its entry from assign_aircraft_groups; `takeoff_pred` comes
    from src/text_citation.classify_takeoff. Every argument beyond patent_id /
    batch / meta is optional so the notebook can run any subset of the stages
    — gazetteer-only, or SBERT without the LLM — and still get a well-formed sheet.
    """
    batch_meta = batch_meta or {}
    gaz_hit = gaz_hit or {}
    llm_answer = llm_answer or {}
    spec_hints = spec_hints or {}
    name_candidates = name_candidates or []
    blade_hits = blade_hits or []
    takeoff_pred = takeoff_pred or {}
    uav_pred = uav_pred or {}
    wizard = wizard or {}
    group = group or {}
    variants = wizard.get("variants") or []
    edge_tags = wizard.get("edge_tags") or []
    # What the annotator's own disapproval reason already settled. Never
    # re-asked; see wizard_link.human_truth for why "Out of Domain" is excluded.
    truth = human_truth(wizard)
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
    country, country_src = assignee_country(assignee_raw), "assignee_string"
    if not country and meta.get("assignee_country_col"):
        # The export's own "Assignee Country" column, when the assignee string
        # carries no "(US)" suffix to parse.
        cc = str(meta["assignee_country_col"]).strip().upper()
        if len(cc) == 2 and cc.isalpha():
            country, country_src = cc, "patseer_column"
    if not country:
        country_src = None
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
    # It abstains on a low-confidence SBERT powertrain, and on a text that
    # states two families; a text that states nothing is PRESUMED electric
    # (this is an approved eVTOL corpus) — see electric_verdict().
    families = powertrain_pred.get("families") or {}
    stated = any(not h.get("hedged") for h in families.values())
    is_electric, elec_src = electric_verdict(powertrain, pt_src, pt_conf,
                                             company_all_electric,
                                             stated=stated, presume_electric=presume_electric)
    if truth.get("electric"):
        is_electric, elec_src = truth["electric"], "human"
        _ev("is_electric", is_electric, "human", _CONF_HUMAN, truth["electric_evidence"])

    # ── "where does it say that?" — the citations the reviewer reads ─────────
    # Name: does the proposed real name literally appear in the loaded text?
    # A gazetteer name usually does NOT (it is inferred from company + year),
    # and the reviewer must know that before accepting it.
    name_in_text, name_section, name_quote = None, None, None
    if name:
        # NAME_SECTIONS, not the body: a patent's Description routinely names
        # other people's aircraft in its prior-art discussion.
        cite = find_quote(meta, literal_pattern(str(name)), sections=NAME_SECTIONS)
        if cite:
            name_in_text, name_section, name_quote = "Yes", cite["section"], cite["quote"]
        else:
            name_in_text = "No"
    # Powertrain: the keyword pass reports the pattern that fired; SBERT and
    # the gazetteer have no sentence to point at, and the column says so.
    pt_section, pt_quote = None, None
    pt_other, pt_other_quote = None, None
    if pt_src == "keyword" and powertrain_pred.get("pattern"):
        cite = find_quote(meta, powertrain_pred["pattern"])
        if cite:
            pt_section, pt_quote = cite["section"], cite["quote"]
        # The second family the text also states (a turbine next to an electric
        # motor, the battery inside a hybrid): quoted so the reviewer reads both.
        if powertrain_pred.get("other") and powertrain_pred.get("other_pattern"):
            pt_other = powertrain_pred["other"]
            cite2 = find_quote(meta, powertrain_pred["other_pattern"])
            if cite2:
                pt_other_quote = f"{cite2['section']}: {cite2['quote']}"
    elif pt_src == "gazetteer":
        pt_section = "gazetteer (company-level, no sentence)"
    elif pt_src in ("sbert", "llm"):
        pt_section = f"{pt_src} (no literal sentence)"

    # ── take-off mode (VTOL / STOL) ──────────────────────────────────────────
    takeoff = takeoff_pred.get("value")
    takeoff_src, takeoff_conf = takeoff_pred.get("source"), takeoff_pred.get("confidence")
    takeoff_section, takeoff_quote = takeoff_pred.get("section"), takeoff_pred.get("quote")
    _ev("takeoff_mode", takeoff, takeoff_src, takeoff_conf,
        f"{takeoff_section}: {takeoff_quote}" if takeoff else "")
    if truth.get("takeoff"):
        # The annotator threw this patent out for not being VTOL. That is a
        # decision, not a prediction — it outranks the keyword pass.
        takeoff, takeoff_src, takeoff_conf = truth["takeoff"], "human", _CONF_HUMAN
        takeoff_section, takeoff_quote = "wizard disapproval", truth["takeoff_evidence"]
        _ev("takeoff_mode", takeoff, "human", _CONF_HUMAN, truth["takeoff_evidence"])

    # ── UAV language (a hint for the UAVSimilar edge tag) ────────────────────
    uav = uav_pred.get("value")
    _ev("uav_hint", uav, uav_pred.get("source"), uav_pred.get("confidence"),
        f"{uav_pred.get('section')}: {uav_pred.get('quote')}" if uav else "")
    if truth.get("uav"):
        _ev("uav_hint", truth["uav"], "human", _CONF_HUMAN, truth["uav_evidence"])

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
    # Only the fields the reviewer actually decides (name / electric / VTOL)
    # raise a flag. Specs, scope and architecture are informative columns and
    # flagging them would mark every row.
    reasons: list[str] = []
    if wizard.get("approved") is False:
        reasons.append(f"disapproved by the annotator ({wizard.get('disapprove_reason')}) "
                       f"— not in the review queue")
    if group.get("aircraft_group_source") == "generated":
        reasons.append("group name generated — no wizard aircraftName")
    if group.get("aircraft_group_note", "") and "differs from original" in str(group.get("aircraft_group_note")):
        reasons.append("D1/D2 name differs from its original")
    if name and name_in_text == "No":
        reasons.append("proposed real name not found in patent text")
    elif name and (name_conf or 0) < NEEDS_REVIEW_BELOW:
        reasons.append("low-confidence name")
    if gaz_hit.get("_match") == "ambiguous":
        reasons.append("multiple gazetteer aircraft for this company")
    # Ordered by what the reviewer would DO about it: a decided verdict first
    # (say where it came from), then the ones still open.
    if elec_src == "company":
        reasons.append("electric from the company's all-electric portfolio, not this text")
    elif elec_src == "human":
        pass                       # the annotator already decided; nothing to ask
    elif elec_src == "presumed":
        reasons.append("no propulsion stated — presumed electric (approved eVTOL corpus), not queued")
    elif pt_other and is_electric == "Unknown":
        reasons.append(f"text states BOTH {powertrain} and {pt_other} — read both quotes")
    elif is_electric in ("No", "Hybrid"):
        reasons.append(f"{powertrain} stated — confirm before disapproving")
    elif not powertrain:
        reasons.append("powertrain unknown")
    elif is_electric == "Unknown":
        reasons.append(f"powertrain is a low-confidence {pt_src} guess ({powertrain})")
    elif (pt_conf or 0) < NEEDS_REVIEW_BELOW:
        reasons.append("low-confidence powertrain")
    if not takeoff:
        reasons.append("take-off mode unknown")
    elif takeoff in ("STOL", "V/STOL", "CTOL") and takeoff_src != "human":
        reasons.append(f"take-off language says {takeoff}")
    if uav and "UAVSimilar" not in edge_tags and wizard.get("approved") is not False:
        reasons.append(f"{uav} vocabulary, no UAVSimilar tag in the wizard")
    if wizard.get("arch_count", 1) and int(wizard.get("arch_count") or 1) > 1:
        reasons.append(f"{wizard['arch_count']} aircraft variants in this patent "
                       f"({row_variant_types(variants)})"
                       + (" — several candidate real names, assign them"
                          if _variant_proposals(wizard.get("arch_count"), name, alternatives)
                          else ""))

    row = {
        "patent_id": patent_id,
        "batch": batch,
        "company_canonical": company,
        "assignee_raw": assignee_raw,
        "prototype_label": batch_meta.get("prototype_label"),
        "app_year": meta.get("app_year"),
        "pub_year": meta.get("pub_year"),
        "title": meta.get("title"),
        "wizard_approved": wizard.get("approved"),
        "wizard_disapprove_reason": wizard.get("disapprove_reason"),
        "wizard_aircraft_name": wizard.get("aircraft_name"),
        "wizard_duplicate_type": wizard.get("duplicate_type"),
        "wizard_duplicate_of": wizard.get("duplicate_of"),
        "wizard_arch_count": wizard.get("arch_count"),
        "wizard_variant_types": (" | ".join(v.get("top_type") or "?" for v in variants) or None),
        "wizard_edge_tags": ("|".join(edge_tags) or None),
        "duplicate_root": None, "duplicate_root_note": None,
        "aircraft_group": group.get("aircraft_group"),
        "aircraft_group_source": group.get("aircraft_group_source"),
        "aircraft_group_note": group.get("aircraft_group_note"),
        "aircraft_group_variants": variant_names(group.get("aircraft_group"), wizard.get("arch_count")),
        # For a patent that describes several aircraft: every real name the
        # gazetteer or the text offers for this company, so the reviewer can
        # say which variant is which product. Empty unless there ARE variants
        # and there IS more than one candidate — one candidate is just the
        # patent's name, and the letters already handle that.
        "aircraft_name_variant_proposals": _variant_proposals(
            wizard.get("arch_count"), name, alternatives),
        "pub_office": office,
        "assignee_country": country,
        "assignee_country_source": country_src,
        "region": region_for(country, office),
        "aircraft_name": name,
        "aircraft_name_source": name_src,
        "aircraft_name_confidence": round(name_conf, 4) if name_conf is not None else None,
        "aircraft_name_in_text": name_in_text,
        "aircraft_name_section": name_section,
        "aircraft_name_quote": name_quote,
        "aircraft_name_alternatives": alternatives or None,
        "aircraft_name_human": None,
        "aircraft_name_human_variants": None,
        "aircraft_name_final": None,
        "aircraft_name_final_variants": None,
        "is_electric": is_electric,
        "is_electric_source": elec_src,
        "powertrain": powertrain,
        "powertrain_source": pt_src,
        "powertrain_confidence": round(pt_conf, 4) if pt_conf is not None else None,
        "powertrain_section": pt_section,
        "powertrain_quote": pt_quote,
        "powertrain_other": pt_other,
        "powertrain_other_quote": pt_other_quote,
        "is_electric_human": None,
        "is_electric_human_variants": None,
        "is_electric_final": None,
        "is_electric_final_variants": None,
        "takeoff_mode": takeoff,
        "takeoff_source": takeoff_src,
        "takeoff_confidence": (round(float(takeoff_conf), 4)
                               if takeoff and takeoff_conf is not None else None),
        "takeoff_section": takeoff_section if takeoff else None,
        "takeoff_quote": takeoff_quote if takeoff else None,
        "takeoff_human": None,
        "takeoff_human_variants": None,
        "takeoff_final": None,
        "takeoff_final_variants": None,
        "uav_hint": uav,
        "uav_source": uav_pred.get("source") if uav else None,
        "uav_confidence": (round(float(uav_pred["confidence"]), 4)
                           if uav and uav_pred.get("confidence") is not None else None),
        "uav_section": uav_pred.get("section") if uav else None,
        "uav_quote": uav_pred.get("quote") if uav else None,
        "uav_human": None,
        "uav_human_variants": None,
        "uav_final": None,
        "uav_final_variants": None,
        "review_queue": None, "name_review": None,
        "electric_review": None, "takeoff_review": None, "uav_review": None,
        "review_status": None,
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
    apply_finals(row)
    row.update(review_flags(row))
    return row, evidence


def _variant_proposals(arch_count, name, alternatives) -> "str | None":
    try:
        n = int(float(arch_count)) if arch_count is not None else 1
    except (TypeError, ValueError):
        n = 1
    if n < 2:
        return None
    cands = [c.strip() for c in ([name] if name else []) + str(alternatives or "").split(";")
             if c and c.strip()]
    cands = list(dict.fromkeys(cands))
    return "; ".join(cands) if len(cands) > 1 else None


def row_variant_types(variants: list[dict]) -> str:
    return " | ".join(v.get("top_type") or "?" for v in variants) or "types unknown"


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

    `needs_review` / `review_reason` are re-derived so a row whose proposed
    real name is only company-attributed is flagged even when every other
    field is confidently filled — that is exactly the row a reviewer must
    look at before accepting the name.
    """
    row.update({k: scope_row.get(k) for k in _SCOPE_COLUMNS})

    reasons = [r for r in (row.get("review_reason") or "").split("; ") if r]

    # The one scope fact the reviewer needs when judging the proposed real
    # name: the name came from the company, and this patent does not depict a
    # whole aircraft. Architecture-count and specificity confidence are left
    # in their own columns — they are not reviewed in this pass.
    if row.get("aircraft_link") == "CompanyAttributed":
        reasons.append("proposed name is company-attributed, not depicted")

    row["needs_review"] = bool(reasons)
    row["review_reason"] = "; ".join(dict.fromkeys(reasons)) or None
    return row


