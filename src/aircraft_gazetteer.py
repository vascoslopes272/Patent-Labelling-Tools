"""
aircraft_gazetteer.py — the curated company -> aircraft table.

Stage 03a. Reads reference/evtol_gazetteer.csv and matches a patent to an
aircraft on canonical company plus filing-year window. The highest-precision
signal in the stage, and the ONLY one that should ever supply a specification
number cited in the thesis.

It matches on COMPANY, which is exactly why src/patent_scope.py exists: a
gazetteer hit says "this company makes that aircraft", never "this patent
depicts it". See `aircraft_link` there.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.grouper import _normalise_company

# Confidence for a gazetteer hit; mirrored in aircraft_identity's precedence table.
_CONF_GAZETTEER_EXACT = 0.95   # canonical company matched AND year inside window
_CONF_GAZETTEER_LOOSE = 0.70   # company matched, year outside the window


GAZETTEER_COLUMNS = [
    "company_canonical", "aircraft_name", "aka", "year_from", "year_to",
    "powertrain", "mtow_kg", "payload_kg", "pax", "cruise_speed_kmh",
    "max_speed_kmh", "range_km", "endurance_min", "spec_source", "notes",
]

# Years are matched against the FILING year with this much slack on each side:
# a patent is typically filed 1-3 years before the aircraft it protects is
# publicly named, and companies keep filing after first flight.
_GAZETTEER_YEAR_SLACK = 3


def load_gazetteer(path: "str | Path") -> list[dict]:
    """Read reference/evtol_gazetteer.csv. Missing file → [] (not an error).

    A missing or empty gazetteer degrades this stage to LLM + SBERT only rather
    than failing the run, which is the right behaviour for a reference table
    the user is expected to grow over time.
    """
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            if not (raw.get("company_canonical") or "").strip():
                continue
            if (raw.get("company_canonical") or "").strip().startswith("#"):
                continue
            rows.append({k: (v.strip() if isinstance(v, str) else v)
                         for k, v in raw.items()})
    return rows


def _year_int(v) -> int | None:
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def match_gazetteer(
    company_canonical: str | None,
    app_year: str | None,
    gazetteer: list[dict],
    assignee_raw: str | None = None,
    text: str | None = None,
) -> dict | None:
    """Find the gazetteer entry for a patent. Returns None when nothing matches.

    Matching is on the canonical company name the grouper already assigned
    (batches.xlsx carries it), so the fuzzy assignee cleanup is not repeated
    here. When a company has several aircraft, the filing year picks between
    them; when the year is missing or outside every window, the entry whose
    name appears in the patent text wins, and failing that the single entry —
    a company with exactly one known aircraft needs no disambiguation.
    """
    if not gazetteer:
        return None

    company = (company_canonical or "").strip()
    if not company or company in ("Unknown / Independent", "Individual Inventor"):
        # Fall back to normalising the raw assignee ourselves — a patent can
        # reach this stage without ever having gone through the grouper.
        if assignee_raw:
            company = _normalise_company(assignee_raw)
        if not company or company in ("Unknown / Independent", "Individual Inventor"):
            return None

    hits = [g for g in gazetteer
            if (g.get("company_canonical") or "").strip().lower() == company.lower()]
    if not hits:
        return None

    year = _year_int(app_year)
    if year is not None:
        def _window(g, slack):
            lo, hi = _year_int(g.get("year_from")), _year_int(g.get("year_to"))
            lo = (lo - slack) if lo is not None else None
            hi = (hi + slack) if hi is not None else None
            return ((lo is None or year >= lo) and (hi is None or year <= hi))

        # Strict window first. The slack exists because filings run ahead of a
        # public name, but applying it up front makes consecutive programmes at
        # the same company overlap (Maker 2019-2022 and Midnight 2023-2030 both
        # swallow 2019 at +-3), turning a clean hit into a false ambiguity.
        # A year inside somebody's *stated* window is not ambiguous at all.
        strict = [g for g in hits if _window(g, 0)]
        if len(strict) == 1:
            return {**strict[0], "_match": "company+year",
                    "_confidence": _CONF_GAZETTEER_EXACT}

        in_window = strict if len(strict) > 1 else [g for g in hits if _window(g, _GAZETTEER_YEAR_SLACK)]
        if len(in_window) == 1:
            return {**in_window[0], "_match": "company+year_slack",
                    "_confidence": _CONF_GAZETTEER_EXACT}
        if len(in_window) > 1:
            hits = in_window   # narrowed; fall through to the text tie-break

    # Tie-break on the aircraft name actually appearing in the patent text.
    if text:
        blob = str(text).lower()
        named = [g for g in hits
                 if (g.get("aircraft_name") or "").lower() in blob
                 or ((g.get("aka") or "").lower() and (g["aka"]).lower() in blob)]
        if len(named) == 1:
            return {**named[0], "_match": "company+name_in_text",
                    "_confidence": _CONF_GAZETTEER_EXACT}

    if len(hits) == 1:
        return {**hits[0], "_match": "company_only", "_confidence": _CONF_GAZETTEER_LOOSE}

    # Several candidates and nothing to separate them — reporting ambiguity is
    # more useful than silently picking the first row.
    return {
        "company_canonical": company,
        "aircraft_name": "",
        "_match": "ambiguous",
        "_confidence": 0.0,
        "_candidates": "; ".join(sorted(g.get("aircraft_name", "") for g in hits)),
    }

