"""
grouper.py — Company normalisation and prototype-generation clustering.

Two sequential steps:

  Step 1 — Company normalisation
    Maps messy assignee strings to canonical company names via an exact lookup
    table followed by rapidfuzz fuzzy matching (threshold 85).

  Step 2 — Prototype inference (NLP)
    Embeds each patent's title + abstract with PatentSBERTa, then clusters
    within each company group using HDBSCAN (min_cluster_size=3).
    Clusters are labelled Prototype_A / _B / … ordered by mean filing date.

Public API
----------
run_grouping(df, cfg)  →  grouped_df

run_grouping also saves:
  cfg["paths"]["data"] / grouped_patents.csv
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ─── Column name variants ─────────────────────────────────────────────────────

_PUB_NUMBER_VARIANTS  = [
    "Publication Number", "Pub. No.", "Patent Number", "Record Number",
]
_ASSIGNEE_VARIANTS    = ["Assignee", "Applicant", "Assignee/Applicant"]
_FILING_DATE_VARIANTS = [
    "Filing Date", "Application Date", "App. Date", "Filing/Application Date",
]
_TITLE_VARIANTS       = ["Title", "Patent Title", "Invention Title"]
_ABSTRACT_VARIANTS    = ["Abstract", "Abstract Text"]


# ─── Company lookup table ─────────────────────────────────────────────────────
# Keys are lowercase stripped variants; values are canonical display names.
# Add new rows freely — the fuzzy fallback catches anything not listed here.

COMPANY_LOOKUP: dict[str, str] = {
    # ── Joby Aviation ─────────────────────────────────────────────────────────
    "joby aviation inc.":          "Joby Aviation",
    "joby aviation inc":           "Joby Aviation",
    "joby aviation, inc.":         "Joby Aviation",
    "joby aviation":               "Joby Aviation",
    "joby aero, inc.":             "Joby Aviation",
    "joby aero inc.":              "Joby Aviation",
    "joby aero inc":               "Joby Aviation",
    "joby aero":                   "Joby Aviation",
    "joby":                        "Joby Aviation",
    # ── Archer Aviation ───────────────────────────────────────────────────────
    "archer aviation inc.":        "Archer Aviation",
    "archer aviation inc":         "Archer Aviation",
    "archer aviation":             "Archer Aviation",
    "archer":                      "Archer Aviation",
    # ── Lilium ────────────────────────────────────────────────────────────────
    "lilium gmbh":                 "Lilium",
    "lilium n.v.":                 "Lilium",
    "lilium nv":                   "Lilium",
    "lilium eaircraft gmbh":       "Lilium",
    "lilium":                      "Lilium",
    # ── Wisk Aero ─────────────────────────────────────────────────────────────
    "wisk aero llc":               "Wisk Aero",
    "wisk aero":                   "Wisk Aero",
    "wisk":                        "Wisk Aero",
    # ── Kitty Hawk ────────────────────────────────────────────────────────────
    "kitty hawk corporation":      "Kitty Hawk",
    "kitty hawk corp":             "Kitty Hawk",
    "kitty hawk":                  "Kitty Hawk",
    # ── Volocopter ────────────────────────────────────────────────────────────
    "volocopter gmbh":             "Volocopter",
    "volocopter":                  "Volocopter",
    # ── EHang ─────────────────────────────────────────────────────────────────
    "ehang holdings limited":      "EHang",
    "ehang inc.":                  "EHang",
    "ehang inc":                   "EHang",
    "ehang":                       "EHang",
    # ── Beta Technologies ─────────────────────────────────────────────────────
    "beta air llc":                "Beta Technologies",
    "beta technologies llc":       "Beta Technologies",
    "beta technologies inc.":      "Beta Technologies",
    "beta technologies":           "Beta Technologies",
    # ── Vertical Aerospace ────────────────────────────────────────────────────
    "vertical aerospace ltd":      "Vertical Aerospace",
    "vertical aerospace group ltd":"Vertical Aerospace",
    "vertical aerospace":          "Vertical Aerospace",
    # ── Overair ───────────────────────────────────────────────────────────────
    "overair inc.":                "Overair",
    "overair inc":                 "Overair",
    "overair":                     "Overair",
    # ── Aurora Flight Sciences ────────────────────────────────────────────────
    "aurora flight sciences corporation": "Aurora Flight Sciences",
    "aurora flight sciences":      "Aurora Flight Sciences",
    "aurora flight science corp":  "Aurora Flight Sciences",   # PatSeer abbr.
    "aurora flight science":       "Aurora Flight Sciences",
    # ── Airbus (all subsidiaries) ─────────────────────────────────────────────
    "airbus sas":                  "Airbus",
    "airbus se":                   "Airbus",
    "airbus helicopters":          "Airbus",
    "airbus helicopters deutschland gmbh": "Airbus",           # PatSeer form
    "airbus urban mobility":       "Airbus",
    "a3 by airbus":                "Airbus",
    "airbus":                      "Airbus",
    # ── Boeing / NeXt ─────────────────────────────────────────────────────────
    "the boeing company":          "Boeing",
    "the boeing co":               "Boeing",                   # PatSeer abbr.
    "boeing":                      "Boeing",
    "boeing next":                 "Boeing",
    # ── Bell / Textron ────────────────────────────────────────────────────────
    "bell helicopter textron inc": "Bell / Textron",           # PatSeer (156 patents)
    "bell textron inc.":           "Bell / Textron",
    "bell textron inc":            "Bell / Textron",           # PatSeer abbr.
    "bell textron":                "Bell / Textron",
    "bell flight":                 "Bell / Textron",
    "textron innovations inc":     "Bell / Textron",           # PatSeer abbr.
    "textron innovations inc.":    "Bell / Textron",
    "textron inc.":                "Bell / Textron",
    "textron inc":                 "Bell / Textron",
    "textron":                     "Bell / Textron",
    # ── Embraer / Eve ─────────────────────────────────────────────────────────
    "embraer s.a.":                "Embraer / Eve",
    "embraer":                     "Embraer / Eve",
    "eve uam, llc":                "Embraer / Eve",
    "eve uam llc":                 "Embraer / Eve",
    "eve air mobility":            "Embraer / Eve",
    # ── Supernal (Hyundai subsidiary) ────────────────────────────────────────
    "supernal, llc":               "Supernal",
    "supernal llc":                "Supernal",
    "supernal":                    "Supernal",
    # ── Hyundai Motor ─────────────────────────────────────────────────────────
    "hyundai motor company":       "Hyundai",
    "hyundai motor co":            "Hyundai",                  # PatSeer abbr.
    "hyundai motor group":         "Hyundai",
    "hyundai":                     "Hyundai",
    # ── Porsche ───────────────────────────────────────────────────────────────
    "porsche ag":                  "Porsche",                  # 62 patents
    "dr ing h c f porsche ag":     "Porsche",
    "porsche":                     "Porsche",
    # ── Honda ─────────────────────────────────────────────────────────────────
    "honda motor co ltd":          "Honda",                    # PatSeer abbr.
    "honda motor co., ltd.":       "Honda",
    "honda motor company":         "Honda",
    "honda":                       "Honda",
    # ── Leonardo (AW169 / AW609 etc.) ────────────────────────────────────────
    "leonardo spa":                "Leonardo",                 # PatSeer abbr.
    "leonardo s.p.a.":             "Leonardo",
    "agusta westland":             "Leonardo",
    "agusta":                      "Leonardo",
    "leonardo":                    "Leonardo",
    # ── Rolls-Royce ───────────────────────────────────────────────────────────
    "rolls royce plc":             "Rolls-Royce",
    "rolls-royce plc":             "Rolls-Royce",
    "rolls royce deutschland ltd & co kg": "Rolls-Royce",     # PatSeer form
    "rolls royce":                 "Rolls-Royce",
    # ── Sikorsky / Lockheed Martin ────────────────────────────────────────────
    "sikorsky aircraft corporation": "Sikorsky",
    "sikorsky aircraft corp":      "Sikorsky",                 # PatSeer abbr.
    "sikorsky":                    "Sikorsky",
    # ── Safran ────────────────────────────────────────────────────────────────
    "safran":                      "Safran",
    "safran helicopter engines":   "Safran",
    "safran aircraft engines":     "Safran",
    # ── General Electric / GE Aviation ───────────────────────────────────────
    "general electric co":         "General Electric",         # PatSeer abbr.
    "general electric company":    "General Electric",
    "ge aviation":                 "General Electric",
    "general electric":            "General Electric",
    # ── Karem Aircraft ────────────────────────────────────────────────────────
    "karem aircraft inc":          "Karem Aircraft",
    "karem aircraft inc.":         "Karem Aircraft",
    "karem aircraft":              "Karem Aircraft",
    # ── Ascendance Flight Technologies ────────────────────────────────────────
    "ascendance flight tech":      "Ascendance Flight Technologies",  # PatSeer abbr.
    "ascendance flight technologies": "Ascendance Flight Technologies",
    "ascendance":                  "Ascendance Flight Technologies",
    # ── Mitsubishi Heavy Industries ───────────────────────────────────────────
    "mitsubishi heavy ind ltd":    "Mitsubishi",               # PatSeer abbr.
    "mitsubishi heavy industries": "Mitsubishi",
    "mhi":                         "Mitsubishi",
    # ── Korea Aerospace Research Institute ────────────────────────────────────
    "korea aerospace res inst":    "KARI",                     # PatSeer abbr.
    "korea aerospace research institute": "KARI",
    "kari":                        "KARI",
    # ── Aeronext (Japan) ──────────────────────────────────────────────────────
    "aeronext inc":                "Aeronext",
    "aeronext inc.":               "Aeronext",
    "aeronext":                    "Aeronext",
    # ── SkyDrive (Japan) ──────────────────────────────────────────────────────
    "skydrive inc.":               "SkyDrive",
    "skydrive inc":                "SkyDrive",
    "skydrive":                    "SkyDrive",
    # ── Opener / BlackFly ─────────────────────────────────────────────────────
    "opener inc.":                 "Opener",
    "opener inc":                  "Opener",
    "opener":                      "Opener",
    # ── Shenfeng Aviation (China) ─────────────────────────────────────────────
    "foshan shenfeng aviation tech co ltd":          "Shenfeng Aviation",
    "shenfeng science & technology of aviation co ltd": "Shenfeng Aviation",
    "foshan shenfeng":             "Shenfeng Aviation",
    "shenfeng":                    "Shenfeng Aviation",
    # ── Sichuan Wofei / Geely (China) ────────────────────────────────────────
    "sichuan wofei changkong technology development co ltd": "Wofei / Geely Aviation",
    "zhejiang geely holding group co ltd": "Wofei / Geely Aviation",
    "wofei":                       "Wofei / Geely Aviation",
    # ── Uber Elevate ──────────────────────────────────────────────────────────
    "uber technology inc":         "Uber Elevate",
    "uber technologies inc":       "Uber Elevate",
    "uber elevate":                "Uber Elevate",
    "uber":                        "Uber Elevate",
    # ── Amazon / Prime Air ────────────────────────────────────────────────────
    "amazon technology inc":       "Amazon",
    "amazon technologies inc":     "Amazon",
    "amazon":                      "Amazon",
    # ── BAE Systems ───────────────────────────────────────────────────────────
    "bae system plc":              "BAE Systems",             # PatSeer abbr.
    "bae systems plc":             "BAE Systems",
    "bae systems":                 "BAE Systems",
    # ── Lockheed Martin ───────────────────────────────────────────────────────
    "lockheed corp":               "Lockheed Martin",         # PatSeer abbr.
    "lockheed martin corporation": "Lockheed Martin",
    "lockheed martin":             "Lockheed Martin",
    # ── Honeywell ─────────────────────────────────────────────────────────────
    "honeywell international inc": "Honeywell",               # PatSeer abbr.
    "honeywell international":     "Honeywell",
    "honeywell":                   "Honeywell",
    # ── Denso (Japan) ─────────────────────────────────────────────────────────
    "nippon denso co":             "Denso",                   # PatSeer abbr.
    "denso corporation":           "Denso",
    "denso corp":                  "Denso",
    "denso":                       "Denso",
    # ── IHI Corporation (Japan) ───────────────────────────────────────────────
    "ihi corp":                    "IHI",                     # PatSeer abbr.
    "ihi corporation":             "IHI",
    "ihi":                         "IHI",
    # ── Urban Aeronautics ─────────────────────────────────────────────────────
    "urban aeronautics ltd":       "Urban Aeronautics",
    "urban aeronautics":           "Urban Aeronautics",
    # ── AutoFlight (China/Germany) ────────────────────────────────────────────
    "shanghai autoflight co ltd":  "AutoFlight",
    "autoflight":                  "AutoFlight",
    # ── Pipistrel (Slovenia) ──────────────────────────────────────────────────
    "pipistrel doo":               "Pipistrel",               # PatSeer abbr.
    "pipistrel d.o.o.":            "Pipistrel",
    "pipistrel":                   "Pipistrel",
    # ── Whisper Aero ──────────────────────────────────────────────────────────
    "whisper aero inc":            "Whisper Aero",
    "whisper aero":                "Whisper Aero",
    # ── Doroni Aerospace ──────────────────────────────────────────────────────
    "doroni aerospace inc":        "Doroni Aerospace",
    "doroni aerospace":            "Doroni Aerospace",
    # ── Alphabet / X Development (Google) ────────────────────────────────────
    "x development llc":          "Alphabet / X",
    "x development":              "Alphabet / X",
    # ── Joby Aviation (extra PatSeer abbreviation) ────────────────────────────
    "joby aviat inc":             "Joby Aviation",            # PatSeer abbr.
    # ── Embraer / Eve (extra forms) ───────────────────────────────────────────
    "embraer sa":                 "Embraer / Eve",            # PatSeer abbr.
    # ── Airbus (extra subsidiary forms) ──────────────────────────────────────
    "airbus helicopters sas":     "Airbus",                   # PatSeer abbr.
    "airbus defence & space gmbh":"Airbus",
    "airbus defence and space":   "Airbus",
    # ── Leonardo (AgustaWestland) ─────────────────────────────────────────────
    "agustawestland spa":         "Leonardo",                 # PatSeer abbr.
    "agustawestland":             "Leonardo",
    # ── Bell / Textron (extra subsidiaries) ───────────────────────────────────
    "textron system corp":        "Bell / Textron",           # PatSeer abbr.
    "textron systems corp":       "Bell / Textron",
    "textron systems":            "Bell / Textron",
    # ── NASA ──────────────────────────────────────────────────────────────────
    "national aeronautics & space administration":    "NASA",
    "national aeronautics and space administration":  "NASA",
    "nasa":                       "NASA",
    "govt of the united states as represented by the national aeronautics & space administration": "NASA",
    # ── Subaru ────────────────────────────────────────────────────────────────
    "subaru corp":                "Subaru",                   # PatSeer abbr.
    "subaru corporation":         "Subaru",
    "fuji heavy industries":      "Subaru",
    "subaru":                     "Subaru",
    # ── AeroVironment ─────────────────────────────────────────────────────────
    "aerovironment inc":          "AeroVironment",            # PatSeer abbr.
    "aerovironment":              "AeroVironment",
    # ── Israel Aerospace Industries ───────────────────────────────────────────
    "israel aerospace ind ltd":   "IAI",                      # PatSeer abbr.
    "israel aerospace industries":"IAI",
    "iai":                        "IAI",
    # ── Anduril Industries ────────────────────────────────────────────────────
    "anduril industry inc":       "Anduril",                  # PatSeer abbr.
    "anduril industries":         "Anduril",
    "anduril":                    "Anduril",

    # ── Airbus (Eurocopter legacy forms) ──────────────────────────────────────
    "eurocopter france":          "Airbus",
    "eurocopter deutschland gmbh":"Airbus",
    "eurocopter":                 "Airbus",

    # ── Boeing (alternate PatSeer abbreviation) ───────────────────────────────
    "boeing co":                  "Boeing",

    # ── Bell / Textron (AAI Corporation subsidiary) ───────────────────────────
    "aai corp":                   "Bell / Textron",
    "aai corporation":            "Bell / Textron",

    # ── Collins Aerospace / RTX (Hamilton Sundstrand) ─────────────────────────
    "hamilton sundstrand corp":   "Collins Aerospace",
    "hamilton sundstrand corporation": "Collins Aerospace",
    "hamilton sundstrand":        "Collins Aerospace",
    "utc aerospace systems":      "Collins Aerospace",
    "collins aerospace":          "Collins Aerospace",

    # ── Amazon (alternate PatSeer abbreviation) ───────────────────────────────
    "amazon tech inc":            "Amazon",

    # ── Safran (subsidiary forms) ─────────────────────────────────────────────
    "safran electrical & power":  "Safran",
    "safran landing systems":     "Safran",
    "safran power units":         "Safran",

    # ── DJI ───────────────────────────────────────────────────────────────────
    "sz dji technology co ltd":   "DJI",
    "dji":                        "DJI",

    # ── GKN Aerospace ─────────────────────────────────────────────────────────
    "gkn aerospace service ltd":  "GKN Aerospace",
    "gkn aerospace services ltd": "GKN Aerospace",
    "gkn aerospace":              "GKN Aerospace",

    # ── Daimler ───────────────────────────────────────────────────────────────
    "daimler ag":                 "Daimler",

    # ── JAXA ──────────────────────────────────────────────────────────────────
    "japan aerospace exploration": "JAXA",
    "jaxa":                        "JAXA",

    # ── Universities & research institutes ────────────────────────────────────
    "beihang univ":               "Beihang University",
    "beihang university":         "Beihang University",
    "changsha aeronautical vocational & technical college": "Changsha Aeronautical College",
    "nanjing univ of aeronautics & astronautics": "NUAA",
    "nanjing university of aeronautics and astronautics": "NUAA",
    "northwestern polytechnic univ": "Northwestern Polytechnic University",
    "northwestern polytechnical university": "Northwestern Polytechnic University",
    "korea advanced institute of science & technology": "KAIST",
    "korea advanced institute of science and technology": "KAIST",
    "tongji univ":                "Tongji University",
    "sun yat sen univ":           "Sun Yat-sen University",
    "univ nanchang hangkong":     "Nanchang Hangkong University",
    "univ texas":                 "University of Texas",
    "univ shenyang aerospace":    "Shenyang Aerospace University",
    "national univ of defense technology": "NUDT",
    "zhejiang univ":              "Zhejiang University",
    "zhejiang univ ningbo five in one campus education development center": "Zhejiang University",
    "china helicopter res & development inst": "CHRDI",
    "second research institute of casic": "CASIC",
    "hubei institute of aerospacecraft": "Hubei Aerospace Institute",
    "beijing aeronautical science & technology research institute commercial aircraft corp": "COMAC Research Institute",

    # ── Chinese eVTOL / drone companies ──────────────────────────────────────
    "xian aisheng technology group co ltd": "Xi'an Aisheng Technology",
    "xian inno aviation tech co ltd": "Xi'an Inno Aviation",
    "shanghai wollant aviation technology co ltd": "Wollant Aviation",
    "shanghai shidi technology co ltd": "Shanghai Shidi Technology",
    "tianjing nanning aircraft mfg co ltd": "Tianjin Nanning Aircraft",
    "fuzhou high tech zone fujing aircraft technology co ltd": "Fujing Aircraft",
    "jiangxi handun duoyu technology co ltd": "Jiangxi Handun Duoyu",
    "zhuhai phoenix aircraft tech center": "Phoenix Aircraft",
    "foshan god navi tech co ltd": "Foshan God-Navi",
    "tianjin air technology co ltd": "Tianjin Air Technology",
    "shanghai shangshi energy technology co ltd": "Shanghai Shangshi Energy",

    # ── Western eVTOL / UAM startups ─────────────────────────────────────────
    "emt ingenieurgesellschaft dipl ing hartmut euer mbh": "EMT",
    "amsl innovations pl":        "AMSL Innovations",
    "greensky srl":               "GreenSky",
    "baxter aerospace llc":       "Baxter Aerospace",
    "aerhart llc":                "Aerhart",
    "hop flyt inc":               "Hop Flyt",
    "zuri com se":                "Zuri",
    "tetra aviation corp":        "Tetra Aviation",
    "hi lite aircraft":           "Hi-Lite Aircraft",
    "horizon aircraft inc":       "Horizon Aircraft",
    "levanta tech inc":           "Levanta Tech",
    "jetoptera inc":              "Jetoptera",
    "delorean aerospace llc":     "DeLorean Aerospace",
    "kymatics llc":               "Kymatics",
    "neoptera ltd":               "Neoptera",
    "method aeronautics llc":     "Method Aeronautics",
    "hoversurf inc":              "Hoversurf",
    "cyclotech gmbh":             "CycloTech",
    "martin uav llc":             "Martin UAV",
    "sunlight photonics inc":     "Sunlight Photonics",
    "ishikawa energy research co ltd": "Ishikawa Energy Research",
    "ntn toyo bearing co ltd":    "NTN Corporation",
    "p3x gmbh & co kg":           "P3X",
    "colugo system ltd":          "Colugo Systems",
    "pinnacle vista llc":         "Pinnacle Vista",
    "zipair":                     "ZIPAIR",
    "zircon chambers pl":         "Zircon Chambers",
    "baaz gmbh":                  "BAAZ",
}

# Canonical names (unique set of values) — used by fuzzy fallback
_CANONICAL_NAMES: list[str] = sorted(set(COMPANY_LOOKUP.values()))

# Fuzzy threshold (0–100)
_FUZZY_THRESHOLD = 85

# Words that indicate an entity is an organisation (not a personal name).
# If ANY word in the preprocessed assignee string matches one of these, the
# string is treated as a company/institution rather than an individual.
_COMPANY_KEYWORDS: frozenset[str] = frozenset({
    # Legal entity suffixes
    "inc", "llc", "ltd", "corp", "corporation", "gmbh", "srl", "se", "ag",
    "sa", "bv", "nv", "oy", "pl", "pty", "ab", "sas", "kg", "mbh", "zao",
    "ooo", "company", "companies", "limited", "holdings", "group", "trust",
    # Academic
    "univ", "university", "college", "institute", "school", "polytechnic", "academy",
    # Industry descriptors
    "technology", "technologies", "tech",
    "aviation", "aerospace", "aircraft", "helicopter", "aero",
    "flight", "drone", "uav", "rotor",
    "systems", "solutions", "labs", "laboratory", "laboratories",
    "industrial", "industries", "manufacturing", "mfg",
    "center", "centre", "research", "development",
    "energy", "power", "electric", "photonics", "robotics",
    "capital", "ventures", "partners", "air",
})


def _is_personal_name(cleaned: str) -> bool:
    """
    Return True if the preprocessed assignee string looks like a personal name.

    Heuristic rules (ALL must hold):
      - At least 2 words (first + last name minimum)
      - At most 5 words (longer strings are company descriptions)
      - No digits (company/product codes)
      - No word matches a known company/institution keyword
    """
    if not cleaned:
        return False
    words = cleaned.split()
    if len(words) < 2 or len(words) > 5:
        return False
    if any(ch.isdigit() for ch in cleaned):
        return False
    if any(w.lower() in _COMPANY_KEYWORDS for w in words):
        return False
    return True


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _find_col(df: pd.DataFrame, variants: list[str], required: bool = True) -> Optional[str]:
    """Return the first matching column name from variants, or raise / return None."""
    for v in variants:
        if v in df.columns:
            return v
    if required:
        raise KeyError(
            f"None of the expected column variants found.\n"
            f"  Expected one of: {variants}\n"
            f"  Available columns: {list(df.columns[:20])} ..."
        )
    return None


def _preprocess_assignee(raw: str) -> str:
    """
    Normalise a raw PatSeer assignee string for lookup.

    PatSeer format:  "BELL HELICOPTER TEXTRON INC (US)"
                     "SICHUAN WOFEI CO LTD (CHENGDU CITY, CN); ZHEJIANG GEELY"
    Steps:
      1. Take only the first assignee when multiple are joined with '; '.
      2. Strip trailing country-code suffix:  (US) / (DE) / (JP) …
         Also handles city+country variant:   (CHENGDU CITY, CN)
      3. Lowercase.
    """
    s = str(raw).strip()
    s = s.split(';')[0].strip()                          # first assignee only
    s = re.sub(r'\s*\([^)]+,\s*[A-Z]{2}\)\s*$', '', s)  # city+country
    s = re.sub(r'\s*\([A-Z]{2,3}\)\s*$', '', s)          # plain country code
    return s.strip().lower()


def _normalise_company(raw: str) -> str:
    """
    Map a raw assignee string to a canonical company name.

    Resolution order:
      1. Preprocess: take first assignee, strip trailing "(XX)" country code,
         lowercase — this makes PatSeer's ALL-CAPS abbreviated forms match
         the lookup table keys.
      2. Exact match in COMPANY_LOOKUP.
      3. Fuzzy match against all COMPANY_LOOKUP keys via rapidfuzz (score ≥ 85).
      4. Fuzzy match against canonical names directly.
      5. "Unknown / Independent"
    """
    if not raw or str(raw).strip().lower() in ("", "nan", "none"):
        return "Unknown / Independent"

    cleaned = _preprocess_assignee(raw)
    key     = cleaned

    # 1. Exact lookup
    if key in COMPANY_LOOKUP:
        return COMPANY_LOOKUP[key]

    # 2 & 3. Fuzzy matching
    try:
        from rapidfuzz import process as rf_process, fuzz as rf_fuzz

        # Match against variant keys first (covers abbreviations / typos)
        result = rf_process.extractOne(
            key,
            list(COMPANY_LOOKUP.keys()),
            scorer=rf_fuzz.ratio,
            score_cutoff=_FUZZY_THRESHOLD,
        )
        if result:
            matched_key = result[0]
            return COMPANY_LOOKUP[matched_key]

        # Match directly against canonical names
        result2 = rf_process.extractOne(
            cleaned,
            _CANONICAL_NAMES,
            scorer=rf_fuzz.ratio,
            score_cutoff=_FUZZY_THRESHOLD,
        )
        if result2:
            return result2[0]

    except ImportError:
        warnings.warn(
            "rapidfuzz not installed — fuzzy company matching disabled. "
            "Only exact lookup table matches will be applied.",
            stacklevel=2,
        )

    # Last resort: distinguish personal names from truly unknown organisations
    if _is_personal_name(cleaned):
        return "Individual Inventor"
    return "Unknown / Independent"


# ─── Prototype inference ──────────────────────────────────────────────────────

_SBERT_MODEL = "AI-Growth-Lab/PatentSBERTa"


def _embed_texts(texts: list[str]) -> np.ndarray:
    """
    Embed a list of text strings with PatentSBERTa.

    Returns an ndarray of shape (N, embedding_dim).
    The model is downloaded from HuggingFace on first call (~500 MB).
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(_SBERT_MODEL)
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return embeddings


def _cluster_company_group(
    group_df: pd.DataFrame,
    embeddings: np.ndarray,
    date_col: str,
    min_cluster_size: int = 3,
) -> tuple[list[str], list[int]]:
    """
    Run HDBSCAN on a company's patent embeddings and return labelled results.

    Cluster IDs are remapped so that Prototype_A has the earliest mean filing
    date, Prototype_B the second earliest, etc.  Noise points (HDBSCAN label
    -1) are labelled "Unclassified".

    Returns
    -------
    prototype_labels    : list[str] — e.g. ["Prototype_A", "Unclassified", …]
    prototype_cluster_ids : list[int] — raw HDBSCAN cluster id (-1 = noise)
    """
    n = len(group_df)

    if n < min_cluster_size:
        # Too small to cluster: everything is one prototype
        return ["Prototype_A"] * n, [0] * n

    try:
        from sklearn.cluster import HDBSCAN as SklearnHDBSCAN
        clusterer = SklearnHDBSCAN(min_cluster_size=min_cluster_size)
        raw_labels = clusterer.fit_predict(embeddings)
    except Exception as exc:
        warnings.warn(f"HDBSCAN clustering failed: {exc}. Assigning all to Prototype_A.")
        return ["Prototype_A"] * n, [0] * n

    unique_ids = [c for c in sorted(set(raw_labels)) if c >= 0]

    if not unique_ids:
        # All noise — treat as one unclustered group
        return ["Unclassified"] * n, list(raw_labels)

    # Compute mean filing date per cluster to order alphabetically
    dates = pd.to_datetime(group_df[date_col], errors="coerce")
    cluster_mean_dates: dict[int, pd.Timestamp] = {}
    for cid in unique_ids:
        mask = raw_labels == cid
        cluster_dates = dates.iloc[list(np.where(mask)[0])]
        mean_date = cluster_dates.dropna().mean()
        cluster_mean_dates[cid] = mean_date if pd.notna(mean_date) else pd.Timestamp.max

    # Sort clusters by mean date → assign A, B, C, …
    sorted_clusters = sorted(unique_ids, key=lambda c: cluster_mean_dates[c])
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    cid_to_label: dict[int, str] = {
        cid: f"Prototype_{alphabet[i]}"
        for i, cid in enumerate(sorted_clusters)
        if i < len(alphabet)
    }

    prototype_labels = []
    for lbl in raw_labels:
        if lbl == -1:
            prototype_labels.append("Unclassified")
        else:
            prototype_labels.append(cid_to_label.get(lbl, "Unclassified"))

    return prototype_labels, list(raw_labels)


# ─── Public API ───────────────────────────────────────────────────────────────

def run_grouping(
    df: pd.DataFrame,
    cfg: dict,
) -> pd.DataFrame:
    """
    Add company_canonical, prototype_label, prototype_cluster_id, and
    display_order columns to a deduplicated patent DataFrame.

    Parameters
    ----------
    df  : Deduplicated DataFrame (output of deduplicator.run_deduplication).
    cfg : Configuration dict from load_config().

    Returns
    -------
    grouped_df : df extended with the four new columns, sorted by display_order.

    Side-effects
    ------------
    Writes cfg["paths"]["data"] / grouped_patents.csv
    """
    df = df.copy()

    # ── Resolve columns ───────────────────────────────────────────────────────
    pub_col      = _find_col(df, _PUB_NUMBER_VARIANTS,  required=True)
    assignee_col = _find_col(df, _ASSIGNEE_VARIANTS,    required=True)
    date_col     = _find_col(df, _FILING_DATE_VARIANTS, required=True)
    title_col    = _find_col(df, _TITLE_VARIANTS,       required=False)
    abstract_col = _find_col(df, _ABSTRACT_VARIANTS,    required=False)

    print(f"[grouper] Columns resolved:")
    print(f"  pub_number  → {pub_col!r}")
    print(f"  assignee    → {assignee_col!r}")
    print(f"  filing_date → {date_col!r}")
    print(f"  title       → {title_col!r}")
    print(f"  abstract    → {abstract_col!r}")
    print()

    # ── Step 1: Company normalisation ─────────────────────────────────────────
    print("[grouper] Normalising company names …")
    df["company_canonical"] = df[assignee_col].apply(_normalise_company)

    n_known   = (df["company_canonical"] != "Unknown / Independent").sum()
    n_unknown = (df["company_canonical"] == "Unknown / Independent").sum()
    print(f"  Known companies     : {n_known:>5,}")
    print(f"  Unknown/Independent : {n_unknown:>5,}")
    print()

    # ── Step 2: Prototype inference ───────────────────────────────────────────
    print(f"[grouper] Embedding {len(df)} patents with PatentSBERTa …")
    print(f"  Model: {_SBERT_MODEL}")
    print("  (downloads ~500 MB on first call)")

    def _text(row: pd.Series) -> str:
        parts = []
        if title_col and pd.notna(row.get(title_col)):
            parts.append(str(row[title_col]).strip())
        if abstract_col and pd.notna(row.get(abstract_col)):
            parts.append(str(row[abstract_col]).strip())
        return " [SEP] ".join(parts) if parts else ""

    texts = [_text(row) for _, row in df.iterrows()]

    try:
        all_embeddings = _embed_texts(texts)
    except Exception as exc:
        warnings.warn(
            f"PatentSBERTa embedding failed: {exc}\n"
            "Prototype clustering will be skipped — "
            "all patents will be labelled Prototype_A.",
            stacklevel=2,
        )
        all_embeddings = None

    print()
    print("[grouper] Clustering by company group …")

    prototype_labels:      list[str] = [""] * len(df)
    prototype_cluster_ids: list[int] = [0]  * len(df)

    min_cluster_size = cfg.get("grouper", {}).get("hdbscan_min_cluster_size", 3)

    for company, group_idx in df.groupby("company_canonical").groups.items():
        group_df = df.loc[group_idx]
        pos_list = [df.index.get_loc(i) for i in group_idx]

        if all_embeddings is not None:
            group_embs = all_embeddings[pos_list]
            labels, raw_ids = _cluster_company_group(
                group_df.reset_index(drop=True),
                group_embs,
                date_col,
                min_cluster_size=min_cluster_size,
            )
        else:
            labels  = ["Prototype_A"] * len(group_df)
            raw_ids = [0] * len(group_df)

        for i, (pos, lbl, rid) in enumerate(zip(pos_list, labels, raw_ids)):
            prototype_labels[pos]      = lbl
            prototype_cluster_ids[pos] = rid

        n_proto = len(set(l for l in labels if l != "Unclassified"))
        n_uncl  = labels.count("Unclassified")
        print(f"  {company:<40s} {len(group_df):>4} patents → "
              f"{n_proto} prototype(s), {n_uncl} unclassified")

    df["prototype_label"]      = prototype_labels
    df["prototype_cluster_id"] = prototype_cluster_ids

    # ── Step 3: Display order ─────────────────────────────────────────────────
    # Parse dates for sorting (keep string column intact)
    df["_date_sort"] = pd.to_datetime(df[date_col], errors="coerce")

    df_sorted = df.sort_values(
        ["company_canonical", "prototype_label", "_date_sort"],
        na_position="last",
    ).drop(columns=["_date_sort"])

    df_sorted = df_sorted.reset_index(drop=True)
    df_sorted["display_order"] = df_sorted.index

    # ── Save grouped CSV ──────────────────────────────────────────────────────
    out_dir = Path(cfg["paths"]["data"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "grouped_patents.csv"
    df_sorted.to_csv(out_path, index=False)
    print(f"\n[grouper] Saved: {out_path}")

    # ── Update family_map.csv with grouping columns ───────────────────────────
    fmap_path = out_dir / "family_map.csv"
    if fmap_path.exists():
        fmap = pd.read_csv(fmap_path, dtype=str)
        # Drop old grouping columns if they exist (re-run idempotency)
        for col in ("company_canonical", "prototype_label", "display_order"):
            if col in fmap.columns:
                fmap = fmap.drop(columns=[col])
        group_info = (
            df_sorted[[pub_col, "company_canonical", "prototype_label", "display_order"]]
            .copy()
            .rename(columns={pub_col: "canonical_pub_number"})
            .assign(display_order=lambda d: d["display_order"].astype(str))
        )
        fmap = fmap.merge(group_info, on="canonical_pub_number", how="left")
        fmap.to_csv(fmap_path, index=False)
        print(f"[grouper] Updated: {fmap_path}")

    # ── Dataset summary CSV ───────────────────────────────────────────────────
    summary_path = _save_dataset_summary(df_sorted, pub_col, date_col, out_dir)
    print(f"[grouper] Saved: {summary_path}")

    # ── Console summary table ─────────────────────────────────────────────────
    summary = (
        df_sorted
        .groupby(["company_canonical", "prototype_label"])
        .agg(
            count=(pub_col, "count"),
            earliest=(date_col, lambda x: x.dropna().min() if x.notna().any() else ""),
            latest=(date_col, lambda x: x.dropna().max() if x.notna().any() else ""),
        )
        .reset_index()
    )

    print("\n[grouper] Company / Prototype summary:")
    print(f"  {'Company':<40} {'Prototype':<16} {'Count':>6}  Date range")
    print("  " + "─" * 80)
    for _, row in summary.iterrows():
        date_range = f"{str(row['earliest'])[:7]} – {str(row['latest'])[:7]}"
        print(f"  {str(row['company_canonical']):<40} {str(row['prototype_label']):<16} "
              f"{row['count']:>6}  {date_range}")

    return df_sorted


# ─── Dataset summary ──────────────────────────────────────────────────────────

def _pub_office(pub_num: str) -> str:
    """Infer publication office from the patent number prefix."""
    s = str(pub_num).strip().upper()
    for prefix in ("US", "EP", "WO", "CN", "JP", "KR", "DE", "FR", "GB", "BR", "IT"):
        if s.startswith(prefix):
            return prefix
    return "Other"


def _save_dataset_summary(
    df: pd.DataFrame,
    pub_col: str,
    date_col: str,
    out_dir: Path,
) -> Path:
    """
    Build and save data/dataset_summary.csv — one row per company.

    Columns
    -------
    company           : canonical company name
    n_patents         : total patent count
    pct_of_total      : share of the full dataset (%)
    n_prototypes      : distinct prototype labels
    prototypes        : e.g. "Prototype_A; Prototype_B"
    first_filing      : earliest filing (YYYY-MM)
    last_filing       : latest filing (YYYY-MM)
    active_years      : year span  (last − first)
    n_us / n_ep / n_wo / n_cn / n_jp / n_kr / n_other  : patents per office
    top_offices       : top-3 offices joined with "/"
    """
    total = len(df)
    rows: list[dict] = []

    # Infer office from pub number
    df = df.copy()
    df["_office"] = df[pub_col].apply(_pub_office)

    for company, grp in df.groupby("company_canonical", sort=False):
        # Prototype info
        protos      = sorted(grp["prototype_label"].dropna().unique())
        proto_str   = "; ".join(p for p in protos if p != "Unclassified")
        n_protos    = len([p for p in protos if p != "Unclassified"])

        # Filing dates
        dates    = pd.to_datetime(grp[date_col], errors="coerce").dropna()
        first    = str(dates.min())[:7] if len(dates) else ""
        last     = str(dates.max())[:7] if len(dates) else ""
        try:
            span = dates.dt.year.max() - dates.dt.year.min()
        except Exception:
            span = None

        # Publication office breakdown
        office_counts = grp["_office"].value_counts()
        def _cnt(office: str) -> int:
            return int(office_counts.get(office, 0))

        offices_sorted = office_counts.index.tolist()
        top3 = "/".join(offices_sorted[:3])

        rows.append({
            "company":       company,
            "n_patents":     len(grp),
            "pct_of_total":  round(len(grp) / total * 100, 1),
            "n_prototypes":  n_protos,
            "prototypes":    proto_str or "Prototype_A",
            "first_filing":  first,
            "last_filing":   last,
            "active_years":  span,
            "n_us":          _cnt("US"),
            "n_ep":          _cnt("EP"),
            "n_wo":          _cnt("WO"),
            "n_cn":          _cnt("CN"),
            "n_jp":          _cnt("JP"),
            "n_kr":          _cnt("KR"),
            "n_other":       _cnt("Other"),
            "top_offices":   top3,
        })

    summary_df = pd.DataFrame(rows).sort_values("n_patents", ascending=False).reset_index(drop=True)

    # Append TOTAL row
    total_row = {
        "company":      "TOTAL",
        "n_patents":    total,
        "pct_of_total": 100.0,
        "n_prototypes": "",
        "prototypes":   "",
        "first_filing": str(pd.to_datetime(df[date_col], errors="coerce").dropna().min())[:7],
        "last_filing":  str(pd.to_datetime(df[date_col], errors="coerce").dropna().max())[:7],
        "active_years": "",
        "n_us":         int((df["_office"] == "US").sum()),
        "n_ep":         int((df["_office"] == "EP").sum()),
        "n_wo":         int((df["_office"] == "WO").sum()),
        "n_cn":         int((df["_office"] == "CN").sum()),
        "n_jp":         int((df["_office"] == "JP").sum()),
        "n_kr":         int((df["_office"] == "KR").sum()),
        "n_other":      int((df["_office"] == "Other").sum()),
        "top_offices":  "",
    }
    summary_df = pd.concat([summary_df, pd.DataFrame([total_row])], ignore_index=True)

    dest = out_dir / "dataset_summary.csv"
    summary_df.to_csv(dest, index=False)
    return dest


# ─── Standalone entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from src.config_loader import load_config
    from src.deduplicator import run_deduplication

    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else None)

    print(f"Loading Excel: {cfg['paths']['patseer_excel']}")
    raw_df = pd.read_excel(cfg["paths"]["patseer_excel"], dtype=str)
    print(f"Loaded {len(raw_df)} rows.\n")

    dedup_df, _ = run_deduplication(raw_df, cfg)
    print()

    grouped_df = run_grouping(dedup_df, cfg)
    print(f"\nGrouped DataFrame shape: {grouped_df.shape}")
    print(grouped_df[["company_canonical", "prototype_label", "display_order"]].head(20))
