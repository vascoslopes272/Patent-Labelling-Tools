"""
patent_geography.py — where a patent comes from.

Stage 03a. Two different geographies, kept apart on purpose:

  assignee_country  where the APPLICANT is, parsed from the country code
                    PatSeer puts after the assignee name.
  pub_office        where protection was SOUGHT, from the publication number.

`region_for` prefers the applicant's country and only falls back to the office.
This corpus is US-heavy, so treating the office as the applicant's geography
would flatten the whole map into "North America" and erase the finding.
"""

from __future__ import annotations

import re

from src.grouper import _pub_office


# TEXTRON INC (US)" or "SICHUAN WOFEI CO LTD (CHENGDU CITY, CN)". Same two
# shapes grouper._preprocess_assignee() strips — parsed here instead of
# discarded, because for this stage the country IS the signal.
_ASSIGNEE_CC_RE = re.compile(r"\(\s*(?:[^)]*,\s*)?([A-Z]{2})\s*\)\s*$")

REGION_BY_COUNTRY: dict[str, str] = {
    "US": "North America", "CA": "North America", "MX": "North America",
    "BR": "South America", "AR": "South America", "CL": "South America",
    "GB": "Europe", "DE": "Europe", "FR": "Europe", "IT": "Europe",
    "ES": "Europe", "PT": "Europe", "NL": "Europe", "BE": "Europe",
    "CH": "Europe", "AT": "Europe", "SE": "Europe", "NO": "Europe",
    "DK": "Europe", "FI": "Europe", "PL": "Europe", "CZ": "Europe",
    "IE": "Europe", "SI": "Europe", "RO": "Europe", "GR": "Europe",
    "RU": "Europe", "UA": "Europe", "TR": "Europe",
    "CN": "Asia-Pacific", "JP": "Asia-Pacific", "KR": "Asia-Pacific",
    "IN": "Asia-Pacific", "SG": "Asia-Pacific", "TW": "Asia-Pacific",
    "AU": "Asia-Pacific", "NZ": "Asia-Pacific", "MY": "Asia-Pacific",
    "TH": "Asia-Pacific", "ID": "Asia-Pacific", "VN": "Asia-Pacific",
    "IL": "Middle East", "AE": "Middle East", "SA": "Middle East",
    "QA": "Middle East", "JO": "Middle East",
    "ZA": "Africa", "EG": "Africa", "MA": "Africa", "NG": "Africa",
}

# Patent offices are jurisdictions, not countries — EP and WO cover many.
REGION_BY_OFFICE: dict[str, str] = {
    "US": "North America", "CA": "North America", "BR": "South America",
    "EP": "Europe", "DE": "Europe", "FR": "Europe", "GB": "Europe", "IT": "Europe",
    "CN": "Asia-Pacific", "JP": "Asia-Pacific", "KR": "Asia-Pacific",
    "WO": "International (PCT)",
}


def assignee_country(raw: str | None) -> str | None:
    """ISO-3166 alpha-2 country of the FIRST assignee, or None.

    Only the first assignee is read, matching grouper._preprocess_assignee():
    a co-assigned patent is attributed to its lead assignee throughout this
    pipeline, and splitting that convention only here would make the company
    and geography columns disagree with each other.

    >>> assignee_country("BELL HELICOPTER TEXTRON INC (US)")
    'US'
    >>> assignee_country("SICHUAN WOFEI CO LTD (CHENGDU CITY, CN); ZHEJIANG GEELY")
    'CN'
    >>> assignee_country("JOBY AERO INC") is None
    True
    """
    if not raw or str(raw).strip().lower() in ("", "nan", "none"):
        return None
    first = str(raw).split(";")[0].strip()
    m = _ASSIGNEE_CC_RE.search(first)
    return m.group(1) if m else None


def region_for(country_code: str | None, pub_office: str | None = None) -> str:
    """Region of the assignee country, falling back to the publication office.

    The office is only a fallback: a US publication says where protection was
    sought, not where the applicant is, and this corpus is US-heavy enough that
    treating the office as the applicant's geography would flatten the whole
    map into "North America".
    """
    if country_code and country_code in REGION_BY_COUNTRY:
        return REGION_BY_COUNTRY[country_code]
    if pub_office and pub_office in REGION_BY_OFFICE:
        return REGION_BY_OFFICE[pub_office]
    return "Unknown"


def publication_office(patent_id: str) -> str:
    """Publication office from the patent number prefix (US2022267016A1 → US)."""
    return _pub_office(patent_id)

