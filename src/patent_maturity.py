"""
patent_maturity.py — how far along a patent is: granted or merely filed, how
much it has been cited, and how that compares within the corpus.

Stage 03a's third module. `aircraft_identity` says which aircraft,
`patent_scope` says what the patent is about; this one says how much weight the
patent should carry in an argument.

Two independent axes, kept separate on purpose
----------------------------------------------
Collapsing "granted" and "well-cited" into one number would hide the two cases
that are most interesting to write about:

    legal_stage    Application | Granted | Unknown
                   Deterministic. Read from a Legal Status column when the
                   PatSeer export has one, otherwise from the publication
                   number's KIND CODE — US...B2 is granted, US...A1 is a
                   published application, and a WO number is never granted
                   because a PCT publication is an application by definition.

    impact_tier    Uncited | Low | Medium | High
                   Corpus-relative percentile of AGE-NORMALISED forward
                   citations (see below).

`maturity_tier` combines them, but both axes stay as columns so a thesis table
can cut either way — an *application* that is already heavily cited is a strong
signal about a company's direction, and it would be invisible in a single score.

Why age normalisation is not optional
-------------------------------------
A 2015 patent has had a decade to accumulate forward citations; a 2023 patent
has had two years. Ranking on raw forward-citation counts would order this
corpus by age and call it impact — and since eVTOL filing volume rose steeply
over exactly that window, the bias is large and systematic, not a rounding
error. Everything here ranks on `forward_citations_per_year`, and the raw count
is kept alongside so the difference is auditable.

In-corpus vs external citations
-------------------------------
`backward_cites` / `forward_cites` come from the PatSeer export already parsed
by extractor.load_patseer_excel(). Each is split into the part that lands inside
this 1639-patent eVTOL corpus and the part that does not. The ratio says whether
a patent is embedded in the eVTOL conversation or borrows from (and is used by)
a different field — a distinction worth a paragraph on its own.

`self_citations` counts backward citations to the SAME canonical company: a
company iterating on its own prior filings is a sustained programme, which is a
different kind of maturity from being cited by others.

Public API
----------
parse_kind_code(patent_id)                    -> dict
legal_stage_for(patent_id, legal_status_raw)  -> dict
enrich_from_excel(index, path)                -> int
citation_summary(patent_id, index)            -> dict
build_maturity_row(patent_id, meta, index, reference_year) -> dict
add_corpus_percentiles(rows)                  -> list[dict]
"""

from __future__ import annotations

import re
from datetime import date

from src.grouper import _pub_office, _normalise_company


# ─── Kind codes ──────────────────────────────────────────────────────────────
# The kind-code suffix on a publication number states whether the document is an
# application or a granted patent. This is the same rule reviewer.select_family_
# primary() uses for its granted-beats-pending tiebreak (`B\d?$`), written out
# per office here because the letter alone is not portable: CN "B" is granted,
# but JP "B" is granted while JP "A" is not, and a bare "A" means granted in no
# office at all.
#
# Only codes worth being confident about are listed. Anything else returns
# Unknown rather than a guess — a wrong "Granted" is worse than an honest gap.

_GRANTED_KINDS = {
    "US": {"B1", "B2", "C1", "C2", "C3", "E", "E1"},   # E = reissue of a grant
    "EP": {"B1", "B2", "B3", "B8", "B9"},
    "CN": {"B", "B1", "B2", "B8", "B9", "C", "C1"},
    "JP": {"B", "B1", "B2", "B7"},
    "KR": {"B1", "B2", "Y1", "Y2"},
    "DE": {"B", "B3", "B4", "C", "C1", "C2", "C5", "T2", "T5"},
    "GB": {"B", "B1", "B8"},
    "FR": {"B1", "B3"},
    "BR": {"B1", "B8"},
    "IT": {"B1"},
}

_APPLICATION_KINDS = {
    "US": {"A1", "A2", "A9", "P1", "S1"},
    "EP": {"A1", "A2", "A3", "A4", "A8", "A9"},
    "CN": {"A", "A1", "A8", "A9", "U", "U1", "Y"},   # U/Y = utility model
    "JP": {"A", "A1", "U", "U1"},
    "KR": {"A", "A1", "U", "U1"},
    "DE": {"A1", "A8", "A9", "U1"},
    "GB": {"A", "A1", "A8", "A9"},
    "FR": {"A1", "A2", "A3"},
    "BR": {"A2", "A8"},
    "IT": {"A1"},
}

# WO is a PCT publication — an international APPLICATION. There is no such thing
# as a granted WO document, whatever its kind code, so it is special-cased
# rather than given a kind-code table.
_APPLICATION_ONLY_OFFICES = {"WO"}

_KIND_CODE_RE = re.compile(r"^([A-Z]{2})\s*[\dA-Z]*?([A-Z]\d?)$")
_PUBNUM_RE = re.compile(r"^([A-Z]{2})(\d+)([A-Z]\d?)?$", re.IGNORECASE)

LEGAL_STAGE_OPTIONS = "Application|Granted|Unknown"


def parse_kind_code(patent_id: str | None) -> dict:
    """Split a publication number into office / serial / kind code.

    >>> parse_kind_code("US2022267016A1")["kind"]
    'A1'
    >>> parse_kind_code("US11524776B2")["kind"]
    'B2'
    >>> parse_kind_code("WO2021123456A1")["office"]
    'WO'
    """
    if not patent_id or not str(patent_id).strip():
        return {"office": None, "serial": None, "kind": None}
    pid = str(patent_id).strip().upper().replace(" ", "")
    m = _PUBNUM_RE.match(pid)
    if not m:
        return {"office": _pub_office(pid), "serial": None, "kind": None}
    return {"office": m.group(1), "serial": m.group(2), "kind": m.group(3) or None}


# Legal-status strings a PatSeer export may carry, mapped to the two stages.
# Ordered most-specific-first; matched as case-insensitive substrings.
_LEGAL_STATUS_RULES: list[tuple[str, str]] = [
    (r"\bgranted\b|\bissued\b|\bin\s*force\b|\bactive\b|\balive\b", "Granted"),
    (r"\bpending\b|\bpublished\b|\bfiled\b|\bapplication\b|\bexamination\b", "Application"),
    # Dead ends are recorded as their own stage rather than folded into either:
    # a lapsed grant WAS granted, and an abandoned application never was.
    (r"\blapsed\b|\bexpired\b|\brevoked\b|\bceased\b", "Granted"),
    (r"\bwithdrawn\b|\babandoned\b|\brefused\b|\brejected\b", "Application"),
]

# Statuses that mean the right no longer subsists. Kept as a separate boolean so
# "granted" and "still in force" are not conflated — a lapsed patent is still
# evidence the invention cleared examination.
_INACTIVE_RE = re.compile(
    r"\blapsed\b|\bexpired\b|\brevoked\b|\bceased\b|\bwithdrawn\b|"
    r"\babandoned\b|\brefused\b|\brejected\b", re.IGNORECASE)


def legal_stage_for(patent_id: str | None,
                    legal_status_raw: str | None = None) -> dict:
    """Whether the document is a granted patent or a published application.

    A Legal Status column, when the export has one, is authoritative and wins;
    the kind code is the fallback that always exists. `source` records which was
    used, so a reviewer can tell a documented status from an inferred one.
    """
    raw = (legal_status_raw or "").strip()
    if raw and raw.lower() not in ("nan", "none", "-"):
        for pattern, stage in _LEGAL_STATUS_RULES:
            if re.search(pattern, raw, re.IGNORECASE):
                return {"value": stage, "source": "legal_status",
                        "confidence": 0.95, "raw": raw,
                        "active": not bool(_INACTIVE_RE.search(raw))}

    parsed = parse_kind_code(patent_id)
    office, kind = parsed["office"], parsed["kind"]

    if office in _APPLICATION_ONLY_OFFICES:
        return {"value": "Application", "source": "kind_code", "confidence": 0.95,
                "raw": kind, "active": None}
    if office and kind:
        if kind in _GRANTED_KINDS.get(office, set()):
            return {"value": "Granted", "source": "kind_code", "confidence": 0.90,
                    "raw": kind, "active": None}
        if kind in _APPLICATION_KINDS.get(office, set()):
            return {"value": "Application", "source": "kind_code", "confidence": 0.90,
                    "raw": kind, "active": None}

    return {"value": "Unknown", "source": None, "confidence": 0.0,
            "raw": kind, "active": None}


# ─── Optional PatSeer columns ────────────────────────────────────────────────
# extractor.load_patseer_excel() deliberately loads a narrow set of fields. The
# maturity columns are read here instead of widening that function, so no
# existing notebook's behaviour changes. Column names differ across PatSeer
# accounts, hence the variant lists — same pattern as _archive/deduplicator.py.

_LEGAL_STATUS_VARIANTS = [
    "Legal Status", "Status", "Application Status", "Patent Status",
    "Current Status", "Legal Status - Simple",
]
_FAMILY_ID_VARIANTS = [
    "Simple Family ID", "Family ID", "INPADOC Family ID", "DOCDB Family ID",
]
_FAMILY_SIZE_VARIANTS = [
    "Family Size", "Simple Family Size", "INPADOC Family Size", "No. of Family Members",
]
_GRANT_DATE_VARIANTS = [
    "Grant Date", "Granted Date", "Issue Date", "Publication/Issue Date",
]
_PRIORITY_DATE_VARIANTS = [
    "Priority Date", "Earliest Priority Date", "First Priority Date",
]
_CLAIM_COUNT_VARIANTS = [
    "No. of Claims", "Claim Count", "Number of Claims", "Claims Count",
]
_FIGURE_COUNT_VARIANTS = [
    "No. of Drawings", "Drawing Count", "Figures", "Number of Drawings",
]
_FWD_CITE_COUNT_VARIANTS = [
    "No. of Forward Citations", "Forward Citation Count", "Cited By Count",
    "Times Cited",
]
_BWD_CITE_COUNT_VARIANTS = [
    "No. of Backward Citations", "Backward Citation Count", "Cites Count",
]

_OPTIONAL_COLUMNS = [
    ("legal_status_raw",   _LEGAL_STATUS_VARIANTS),
    ("family_id",          _FAMILY_ID_VARIANTS),
    ("family_size",        _FAMILY_SIZE_VARIANTS),
    ("grant_date",         _GRANT_DATE_VARIANTS),
    ("priority_date",      _PRIORITY_DATE_VARIANTS),
    ("claim_count",        _CLAIM_COUNT_VARIANTS),
    ("figure_count",       _FIGURE_COUNT_VARIANTS),
    ("fwd_cite_count_col", _FWD_CITE_COUNT_VARIANTS),
    ("bwd_cite_count_col", _BWD_CITE_COUNT_VARIANTS),
]


def enrich_from_excel(index: dict[str, dict], path) -> dict:
    """Merge the maturity columns into an existing load_patseer_excel() index.

    Mutates `index` in place, adding only keys that are actually present in the
    export, and returns a report of which columns were found. Every column here
    is optional: an export without a Legal Status column falls back to kind
    codes, one without Family Size simply leaves that column empty.
    """
    import pandas as pd

    df = pd.read_excel(path, dtype=str)
    found: dict[str, str] = {}
    for key, variants in _OPTIONAL_COLUMNS:
        col = next((c for c in variants if c in df.columns), None)
        if col:
            found[key] = col

    if not found:
        return {"found": {}, "enriched": 0, "columns_available": list(df.columns)}

    enriched = 0
    for _, row in df.iterrows():
        pid = str(row.get("Record Number", "")).strip()
        if not pid or pid == "nan" or pid not in index:
            continue
        for key, col in found.items():
            val = str(row.get(col, "")).strip()
            index[pid][key] = None if val in ("", "nan") else val
        enriched += 1

    return {"found": found, "enriched": enriched, "columns_available": None}


# ─── Citations ───────────────────────────────────────────────────────────────

def _core_id(patent_id: str | None) -> str:
    """Normalise a publication number for cross-referencing.

    Citation lists and Record Numbers are not always written with the same kind
    code or spacing, so matching on the raw string under-counts in-corpus links.
    Office + serial is the stable part.
    """
    parsed = parse_kind_code(patent_id)
    if parsed["office"] and parsed["serial"]:
        return f"{parsed['office']}{parsed['serial']}"
    return str(patent_id or "").strip().upper().replace(" ", "")


def citation_summary(patent_id: str, index: dict[str, dict]) -> dict:
    """Forward/backward citation counts, split by whether they land in-corpus.

    Prefers the explicit count columns when `enrich_from_excel` found them (a
    PatSeer count column reflects the full citation set, whereas the ID list is
    sometimes truncated by the export), and falls back to the length of the
    parsed ID lists otherwise.
    """
    meta = index.get(patent_id, {})
    bwd_ids = meta.get("backward_cites") or []
    fwd_ids = meta.get("forward_cites") or []

    corpus = {_core_id(p) for p in index}
    bwd_in = [c for c in bwd_ids if _core_id(c) in corpus]
    fwd_in = [c for c in fwd_ids if _core_id(c) in corpus]

    def _count(col_key: str, ids: list) -> tuple[int, str]:
        raw = meta.get(col_key)
        if raw is not None:
            try:
                return int(float(str(raw))), "patseer_column"
            except (TypeError, ValueError):
                pass
        return len(ids), "id_list"

    fwd_count, fwd_src = _count("fwd_cite_count_col", fwd_ids)
    bwd_count, bwd_src = _count("bwd_cite_count_col", bwd_ids)

    # Self-citation: a backward cite to the same canonical company. Only
    # computable for cites that are themselves in the corpus (we need their
    # assignee), so it is a floor, not a total — named accordingly.
    own = _normalise_company(meta.get("assignee") or "")
    self_cites = 0
    if own and own not in ("Unknown / Independent", "Individual Inventor"):
        by_core = {_core_id(p): m for p, m in index.items()}
        for c in bwd_in:
            cited = by_core.get(_core_id(c), {})
            if _normalise_company(cited.get("assignee") or "") == own:
                self_cites += 1

    return {
        "forward_citations": fwd_count,
        "backward_citations": bwd_count,
        "forward_citations_source": fwd_src,
        "backward_citations_source": bwd_src,
        "forward_citations_in_corpus": len(fwd_in),
        "backward_citations_in_corpus": len(bwd_in),
        "self_citations_in_corpus": self_cites,
    }


def _year(value) -> "int | None":
    if value is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(value))
    return int(m.group(0)) if m else None


# ─── Row assembly ────────────────────────────────────────────────────────────

MATURITY_COLUMNS = [
    "legal_stage", "legal_stage_source", "legal_stage_confidence",
    "kind_code", "legal_status_raw", "right_active",
    "forward_citations", "backward_citations",
    "forward_citations_per_year", "forward_citations_in_corpus",
    "backward_citations_in_corpus", "self_citations_in_corpus",
    "in_corpus_forward_share",
    "years_since_publication", "grant_lag_years",
    "family_id", "family_size", "claim_count", "figure_count",
    "forward_citation_percentile", "impact_tier", "maturity_tier",
]

IMPACT_TIER_OPTIONS = "Uncited|Low|Medium|High"
MATURITY_TIER_OPTIONS = "Filed|Active|Granted|Established|Unknown"

# Percentile cuts on age-normalised forward citations, within the corpus.
_IMPACT_HIGH_PCT = 0.80
_IMPACT_MED_PCT = 0.50


def build_maturity_row(patent_id: str,
                       index: dict[str, dict],
                       reference_year: int | None = None) -> dict:
    """Maturity columns for one patent. Percentile/tier columns are filled by
    add_corpus_percentiles() afterwards — they need the whole corpus."""
    meta = index.get(patent_id, {})
    reference_year = reference_year or date.today().year

    stage = legal_stage_for(patent_id, meta.get("legal_status_raw"))
    cites = citation_summary(patent_id, index)

    pub_year = _year(meta.get("pub_year"))
    app_year = _year(meta.get("app_year"))
    grant_year = _year(meta.get("grant_date"))

    # Age in years, floored at 1: a patent published this year has not had "zero
    # years" to be cited, and dividing by zero would make it infinitely impactful.
    years_since_pub = (max(1, reference_year - pub_year) if pub_year else None)
    per_year = (round(cites["forward_citations"] / years_since_pub, 3)
                if years_since_pub else None)

    grant_lag = None
    if stage["value"] == "Granted" and grant_year and app_year and grant_year >= app_year:
        grant_lag = grant_year - app_year

    fwd = cites["forward_citations"]
    return {
        "legal_stage": stage["value"],
        "legal_stage_source": stage["source"],
        "legal_stage_confidence": stage["confidence"],
        "kind_code": parse_kind_code(patent_id)["kind"],
        "legal_status_raw": meta.get("legal_status_raw"),
        "right_active": stage["active"],
        "forward_citations": fwd,
        "backward_citations": cites["backward_citations"],
        "forward_citations_per_year": per_year,
        "forward_citations_in_corpus": cites["forward_citations_in_corpus"],
        "backward_citations_in_corpus": cites["backward_citations_in_corpus"],
        "self_citations_in_corpus": cites["self_citations_in_corpus"],
        "in_corpus_forward_share": (
            round(cites["forward_citations_in_corpus"] / fwd, 3) if fwd else None),
        "years_since_publication": years_since_pub,
        "grant_lag_years": grant_lag,
        "family_id": meta.get("family_id"),
        "family_size": meta.get("family_size"),
        "claim_count": meta.get("claim_count"),
        "figure_count": meta.get("figure_count"),
        "forward_citation_percentile": None,
        "impact_tier": None,
        "maturity_tier": None,
    }


def add_corpus_percentiles(rows: list[dict]) -> list[dict]:
    """Fill forward_citation_percentile / impact_tier / maturity_tier in place.

    Percentiles are computed over the CITED rows only. Including the uncited
    ones would put the median somewhere inside a large block of zeros, making
    "Medium impact" mean "cited once" in a corpus where most patents are cited
    never — an artefact of the distribution, not a finding about the patents.
    Uncited rows get percentile 0.0 and their own tier.
    """
    scored = [r for r in rows
              if isinstance(r.get("forward_citations_per_year"), (int, float))
              and r["forward_citations_per_year"] > 0]
    ordered = sorted(r["forward_citations_per_year"] for r in scored)

    def _percentile(value: float) -> float:
        if not ordered:
            return 0.0
        below = sum(1 for v in ordered if v < value)
        return round(below / len(ordered), 4)

    for row in rows:
        per_year = row.get("forward_citations_per_year")
        if not isinstance(per_year, (int, float)) or per_year <= 0:
            row["forward_citation_percentile"] = 0.0 if per_year == 0 else None
            row["impact_tier"] = "Uncited" if per_year == 0 else None
        else:
            pct = _percentile(per_year)
            row["forward_citation_percentile"] = pct
            row["impact_tier"] = ("High" if pct >= _IMPACT_HIGH_PCT
                                  else "Medium" if pct >= _IMPACT_MED_PCT
                                  else "Low")

        stage, impact = row.get("legal_stage"), row.get("impact_tier")
        if stage == "Granted":
            # A grant that others build on is the strongest position in the
            # corpus; a grant nobody cites is still a cleared examination.
            row["maturity_tier"] = ("Established" if impact in ("High", "Medium")
                                    else "Granted")
        elif stage == "Application":
            # An application already being cited is a live, watched filing —
            # a genuinely different thing from one sitting untouched, and the
            # reason legal_stage and impact are kept as separate axes.
            row["maturity_tier"] = ("Active" if impact in ("High", "Medium")
                                    else "Filed")
        else:
            row["maturity_tier"] = "Unknown"
    return rows
