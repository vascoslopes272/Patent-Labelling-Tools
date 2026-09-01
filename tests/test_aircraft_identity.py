"""
test_aircraft_identity.py — unit tests for the pure helpers in
src/aircraft_identity.py (Stage 03a).

Everything here runs without a GPU, without SBERT weights and without the
external storage volume: the functions under test are the deterministic half of
the stage (geography parsing, name mining, powertrain keywords, spec regexes,
gazetteer matching, source precedence). The SBERT half is exercised only
through its `sbert_model=None` degradation path, which is what the notebook
actually falls back to on a machine without the weights.

Why these in particular
-----------------------
Two failure modes would quietly corrupt the thesis dataset rather than crash:

  1. **Reference numerals mistaken for aircraft names.** Patent prose is full of
     "the rotor 12" / "wing 104", and a name miner that accepts those fills the
     aircraft_name column with garbage that still looks plausible in a
     spreadsheet. The mining tests pin the rejections, not just the accepts.
  2. **A weak source overwriting a strong one.** build_identity_row() merges up
     to four signals per field; if precedence breaks, a regex guess can silently
     replace a curated gazetteer value and nothing in the output says so. The
     precedence tests pin that ordering, including the "a None from a strong
     source must not blank the field" case.

Run: pytest tests/test_aircraft_identity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import aircraft_identity as ai   # noqa: E402


# ─── Geography ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("BELL HELICOPTER TEXTRON INC (US)", "US"),
    ("SICHUAN WOFEI CO LTD (CHENGDU CITY, CN); ZHEJIANG GEELY", "CN"),
    ("VOLOCOPTER GMBH (DE)", "DE"),
    ("JOBY AERO INC", None),          # no bracket at all
    ("", None),
    (None, None),
    ("nan", None),
])
def test_assignee_country(raw, expected):
    assert ai.assignee_country(raw) == expected


def test_assignee_country_uses_first_assignee_only():
    """A co-assigned patent is attributed to its lead assignee everywhere else
    in this pipeline (grouper._preprocess_assignee); geography must agree."""
    raw = "AIRBUS SAS (FR); SOME PARTNER CO (JP)"
    assert ai.assignee_country(raw) == "FR"


def test_region_prefers_country_over_office():
    # A Chinese applicant filing in the US is Asia-Pacific, not North America.
    assert ai.region_for("CN", "US") == "Asia-Pacific"


def test_region_falls_back_to_office_then_unknown():
    assert ai.region_for(None, "EP") == "Europe"
    assert ai.region_for(None, "WO") == "International (PCT)"
    assert ai.region_for(None, None) == "Unknown"
    assert ai.region_for("ZZ", None) == "Unknown"


def test_publication_office():
    assert ai.publication_office("US2022267016A1") == "US"
    assert ai.publication_office("WO2021123456A1") == "WO"
    assert ai.publication_office("XX999") == "Other"


# ─── Name mining ─────────────────────────────────────────────────────────────

def test_mining_rejects_reference_numerals():
    """The core false-positive class: patent prose reference numerals."""
    text = ("An aircraft 100 includes a fuselage 102, a wing 104 and a plurality "
            "of rotors 12, 14 and 16 mounted to booms 110 as shown in FIG. 3.")
    values = {c["value"].upper() for c in ai.mine_name_candidates(text, "US2022267016A1")}
    for junk in ("100", "102", "104", "12", "14", "16", "110", "FIG. 3", "FIG"):
        assert junk not in values, f"reference numeral {junk!r} leaked through"


def test_mining_rejects_classification_codes_and_units():
    text = "Classified under B64C 29/00 and B64D 27/24, the motor develops 150 kW at 2400 RPM."
    values = {c["value"].upper() for c in ai.mine_name_candidates(text, "US1")}
    assert "B64C" not in values and "B64D" not in values
    assert "RPM" not in values


def test_mining_finds_trademark_name():
    text = "The Midnight™ aircraft carries four passengers between vertiports."
    cands = ai.mine_name_candidates(text, "US1")
    assert cands, "trademark-marked name should always be found"
    assert cands[0]["value"] == "Midnight"
    assert cands[0]["shape"] == "trademark"


def test_mining_finds_named_as_phrase():
    text = "The vehicle, known as the VoloCity, uses eighteen rotors."
    values = [c["value"] for c in ai.mine_name_candidates(text, "US1")]
    assert "VoloCity" in values


def test_mining_finds_designation_and_camelcase():
    text = "The EH216 platform and the CityAirbus demonstrator share a multirotor layout."
    values = {c["value"] for c in ai.mine_name_candidates(text, "US1")}
    assert "EH216" in values
    assert "CityAirbus" in values


def test_mining_never_returns_the_patents_own_number():
    text = "This application US2022267016A1 describes an S-A1 type vehicle."
    values = {c["value"].upper() for c in ai.mine_name_candidates(text, "US2022267016A1")}
    assert "US2022267016A1" not in values


def test_mining_empty_text_is_empty_list():
    assert ai.mine_name_candidates("", "US1") == []
    assert ai.mine_name_candidates(None, "US1") == []


def test_mining_ranks_trademark_above_bare_designation():
    text = "The Midnight™ vehicle supersedes the M200 testbed."
    cands = ai.mine_name_candidates(text, "US1")
    assert cands[0]["value"] == "Midnight"


# ─── Powertrain ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("a plurality of electric motors powered by a battery pack", "BatteryElectric"),
    ("an all-electric distributed propulsion system", "BatteryElectric"),
    ("a hydrogen fuel cell stack supplies the motors", "HydrogenFuelCell"),
    ("a turbogenerator acts as a range extender for the battery", "HybridElectric"),
    ("a hybrid-electric powerplant with a battery pack", "HybridElectric"),
    ("driven by a turboshaft engine through a main gearbox", "Turbine"),
    ("an internal combustion engine drives the propeller", "Piston"),
])
def test_powertrain_keywords(text, expected):
    pred = ai.classify_powertrain(text, sbert_model=None)
    assert pred["value"] == expected
    assert pred["source"] == "keyword"


def test_powertrain_hybrid_beats_battery_when_both_present():
    """A hybrid description always also mentions batteries and electric motors.
    Ordering in POWERTRAIN_KEYWORDS is what stops it being read as pure BEV."""
    text = ("a hybrid-electric powertrain in which a gas turbine charges the "
            "battery pack feeding the electric motors")
    assert ai.classify_powertrain(text, None)["value"] == "HybridElectric"


def test_powertrain_hydrogen_beats_hybrid_and_battery():
    text = "a hydrogen fuel cell charges the battery pack driving the electric motors"
    assert ai.classify_powertrain(text, None)["value"] == "HydrogenFuelCell"


def test_powertrain_no_signal_without_sbert():
    pred = ai.classify_powertrain("a fuselage with a wing and an empennage", None)
    assert pred["value"] is None
    assert pred["confidence"] == 0.0


def test_is_electric_is_derived_not_predicted():
    """is_electric must be a pure function of powertrain so the two columns can
    never contradict each other in the exported sheet."""
    assert ai.ELECTRIC_BY_POWERTRAIN["BatteryElectric"] == "Yes"
    assert ai.ELECTRIC_BY_POWERTRAIN["HydrogenFuelCell"] == "Yes"
    assert ai.ELECTRIC_BY_POWERTRAIN["HybridElectric"] == "Hybrid"
    assert ai.ELECTRIC_BY_POWERTRAIN["Turbine"] == "No"
    assert ai.ELECTRIC_BY_POWERTRAIN["Unspecified"] == "Unknown"
    # Every taxonomy label must have a mapping, or a new powertrain silently
    # becomes "Unknown" in the sheet.
    assert set(ai.POWERTRAIN_DEFS) == set(ai.ELECTRIC_BY_POWERTRAIN)


# ─── Spec hints ──────────────────────────────────────────────────────────────

def test_spec_hints_metric():
    text = ("The aircraft has a maximum takeoff weight of 2400 kg, a payload of "
            "200 kg, a cruise speed of 250 km/h and a range of 160 km.")
    hints = ai.extract_spec_hints(text)
    assert hints["mtow_kg"]["value"] == 2400
    assert hints["payload_kg"]["value"] == 200
    assert hints["cruise_speed_kmh"]["value"] == 250
    assert hints["range_km"]["value"] == 160


def test_spec_hints_convert_imperial_to_si():
    text = "a payload of 1000 lbs and a range of 100 miles"
    hints = ai.extract_spec_hints(text)
    assert hints["payload_kg"]["value"] == pytest.approx(453.59, abs=0.05)
    assert hints["range_km"]["value"] == pytest.approx(160.93, abs=0.05)


def test_spec_hints_convert_knots_and_hours():
    hints = ai.extract_spec_hints("a cruise speed of 100 knots and an endurance of 2 hours")
    assert hints["cruise_speed_kmh"]["value"] == pytest.approx(185.2, abs=0.1)
    assert hints["endurance_min"]["value"] == pytest.approx(120.0, abs=0.1)


def test_spec_hints_passengers_words_and_digits():
    assert ai.extract_spec_hints("carrying four passengers")["pax"]["value"] == 4
    assert ai.extract_spec_hints("seating 6 occupants")["pax"]["value"] == 6


def test_spec_hints_reject_implausible_passenger_counts():
    """'passengers 250' is a reference numeral, not a seat count."""
    assert "pax" not in ai.extract_spec_hints("the passenger compartment 250 passengers")


def test_spec_hints_carry_low_confidence_and_context():
    """A number in a patent is an embodiment, not a specification — it must
    never arrive in the sheet looking authoritative."""
    hints = ai.extract_spec_hints("in one embodiment the payload is about 200 kg")
    assert hints["payload_kg"]["confidence"] == ai._CONF_REGEX_SPEC
    assert hints["payload_kg"]["confidence"] < ai.NEEDS_REVIEW_BELOW
    assert "200 kg" in hints["payload_kg"]["context"]


def test_spec_hints_empty_text():
    assert ai.extract_spec_hints("") == {}
    assert ai.extract_spec_hints(None) == {}


# ─── Gazetteer ───────────────────────────────────────────────────────────────

GAZ = [
    {"company_canonical": "Archer Aviation", "aircraft_name": "Maker", "aka": "",
     "year_from": "2019", "year_to": "2022", "powertrain": "BatteryElectric"},
    {"company_canonical": "Archer Aviation", "aircraft_name": "Midnight", "aka": "",
     "year_from": "2023", "year_to": "2030", "powertrain": "BatteryElectric"},
    {"company_canonical": "Lilium", "aircraft_name": "Lilium Jet", "aka": "",
     "year_from": "2015", "year_to": "2030", "powertrain": "BatteryElectric"},
]


def test_gazetteer_year_selects_between_two_aircraft():
    hit = ai.match_gazetteer("Archer Aviation", "2019", GAZ)
    assert hit["aircraft_name"] == "Maker"
    assert hit["_match"] == "company+year"
    assert hit["_confidence"] == ai._CONF_GAZETTEER_EXACT


def test_gazetteer_single_aircraft_needs_no_year():
    hit = ai.match_gazetteer("Lilium", None, GAZ)
    assert hit["aircraft_name"] == "Lilium Jet"
    assert hit["_match"] == "company_only"
    assert hit["_confidence"] == ai._CONF_GAZETTEER_LOOSE


def test_gazetteer_ambiguous_reports_candidates_rather_than_guessing():
    """Two aircraft, no year to separate them: naming one at random would put a
    confident-looking wrong answer in the sheet."""
    hit = ai.match_gazetteer("Archer Aviation", None, GAZ)
    assert hit["_match"] == "ambiguous"
    assert hit["aircraft_name"] == ""
    assert hit["_confidence"] == 0.0
    assert "Maker" in hit["_candidates"] and "Midnight" in hit["_candidates"]


def test_gazetteer_text_tie_break():
    hit = ai.match_gazetteer("Archer Aviation", None, GAZ,
                             text="the Midnight vehicle described herein")
    assert hit["aircraft_name"] == "Midnight"
    assert hit["_match"] == "company+name_in_text"


def test_gazetteer_year_slack_still_matches():
    """Filings run a few years ahead of a public name — hence +-3 years slack."""
    hit = ai.match_gazetteer("Archer Aviation", "2017", GAZ)
    assert hit["aircraft_name"] == "Maker"
    assert hit["_match"] == "company+year_slack"


def test_gazetteer_strict_window_beats_slack_overlap():
    """Consecutive programmes at one company overlap once +-3 years of slack is
    applied (Maker 2019-2022 and Midnight 2023-2030 both cover 2020 at +-3).
    A year inside a stated window must resolve cleanly, not fall to ambiguous."""
    hit = ai.match_gazetteer("Archer Aviation", "2020", GAZ)
    assert hit["aircraft_name"] == "Maker"
    assert hit["_match"] == "company+year"

    hit = ai.match_gazetteer("Archer Aviation", "2024", GAZ)
    assert hit["aircraft_name"] == "Midnight"
    assert hit["_match"] == "company+year"


def test_gazetteer_misses_are_none_not_errors():
    assert ai.match_gazetteer("Some Unknown Startup", "2020", GAZ) is None
    assert ai.match_gazetteer("Unknown / Independent", "2020", GAZ) is None
    assert ai.match_gazetteer("Archer Aviation", "2020", []) is None
    assert ai.match_gazetteer(None, "2020", GAZ) is None


def test_shipped_gazetteer_parses_and_has_no_invented_specs():
    """The shipped file must stay spec-free: any number in it needs a citable
    spec_source, and shipping unsourced figures is how a thesis table goes wrong."""
    rows = ai.load_gazetteer(REPO_ROOT / "reference" / "evtol_gazetteer.csv")
    assert len(rows) > 20, "gazetteer failed to parse"
    for row in rows:
        for field in ai.SPEC_FIELDS:
            value = (row.get(field) or "").strip()
            if value:
                assert (row.get("spec_source") or "").strip(), (
                    f"{row['company_canonical']}/{row['aircraft_name']}: {field}={value} "
                    f"has no spec_source"
                )


def test_shipped_gazetteer_companies_match_grouper_canonical_names():
    """A company_canonical that grouper never emits can never match a patent."""
    from src.grouper import _CANONICAL_NAMES

    rows = ai.load_gazetteer(REPO_ROOT / "reference" / "evtol_gazetteer.csv")
    known = set(_CANONICAL_NAMES)
    unknown = sorted({r["company_canonical"] for r in rows} - known)
    assert not unknown, f"not in grouper.COMPANY_LOOKUP values: {unknown}"


def test_shipped_gazetteer_powertrains_are_valid_labels():
    rows = ai.load_gazetteer(REPO_ROOT / "reference" / "evtol_gazetteer.csv")
    for row in rows:
        pt = (row.get("powertrain") or "").strip()
        if pt:
            assert pt in ai.POWERTRAIN_DEFS, f"{pt!r} is not a POWERTRAIN_DEFS label"


# ─── Source precedence ───────────────────────────────────────────────────────

def test_precedence_ordering_is_total():
    order = ["regex", "keyword", "sbert", "llm", "gazetteer", "human"]
    ranks = [ai.SOURCE_PRECEDENCE[s] for s in order]
    assert ranks == sorted(ranks), "SOURCE_PRECEDENCE is not strictly increasing"


def test_pick_prefers_higher_precedence_over_higher_confidence():
    """A very confident regex must not beat a modest gazetteer entry."""
    value, source, _ = ai._pick([
        ("Reference 12", "regex", 0.99),
        ("Midnight", "gazetteer", 0.70),
    ])
    assert (value, source) == ("Midnight", "gazetteer")


def test_pick_skips_none_from_a_strong_source():
    """An LLM that honestly answers null must fall through, not blank the field."""
    value, source, _ = ai._pick([
        (None, "llm", 0.9),
        ("EH216", "sbert", 0.4),
    ])
    assert (value, source) == ("EH216", "sbert")


def test_pick_breaks_ties_on_confidence():
    value, _, _ = ai._pick([("A", "sbert", 0.3), ("B", "sbert", 0.8)])
    assert value == "B"


def test_pick_all_empty_returns_default():
    assert ai._pick([(None, "llm", 0.9), ("", "sbert", 0.4)]) == (None, None, None)


# ─── Row assembly ────────────────────────────────────────────────────────────

META = {
    "assignee": "ARCHER AVIATION INC (US)",
    "app_year": "2019",
    "pub_year": "2021",
    "title": "Vertical takeoff and landing aircraft",
    "abstract": "An aircraft with electric motors powered by a battery pack.",
}


def test_row_gazetteer_wins_and_geography_is_filled():
    row, evidence = ai.build_identity_row(
        patent_id="US2021123456A1", batch="Batch_01", meta=META,
        batch_meta={"company_canonical": "Archer Aviation"},
        gaz_hit=ai.match_gazetteer("Archer Aviation", "2019", GAZ),
        powertrain_pred=ai.classify_powertrain(META["abstract"], None),
        name_candidates=[{"value": "Aircraft 100", "confidence": 0.35,
                          "source": "regex", "context": ""}],
    )
    assert row["aircraft_name"] == "Maker"
    assert row["aircraft_name_source"] == "gazetteer"
    assert row["is_electric"] == "Yes"
    assert row["powertrain"] == "BatteryElectric"
    assert row["assignee_country"] == "US"
    assert row["region"] == "North America"
    assert row["pub_office"] == "US"
    # The losing candidate is preserved for audit rather than discarded.
    assert "Aircraft 100" in (row["aircraft_name_alternatives"] or "")
    assert any(e["source"] == "regex" for e in evidence)


def test_row_llm_fills_what_the_gazetteer_could_not():
    row, _ = ai.build_identity_row(
        patent_id="US2021123456A1", batch="Batch_01", meta=META,
        batch_meta={"company_canonical": "Unknown / Independent"},
        gaz_hit=None,
        llm_answer={"aircraft_name": "Some Prototype", "confidence": 0.8,
                    "powertrain": "HybridElectric", "pax": 4,
                    "reasoning": "matches the company's announced programme"},
    )
    assert row["aircraft_name"] == "Some Prototype"
    assert row["aircraft_name_source"] == "llm"
    assert row["powertrain"] == "HybridElectric"
    assert row["is_electric"] == "Hybrid"
    assert row["pax"] == 4
    assert row["spec_source"] == "llm"


def test_row_with_nothing_known_is_flagged_not_invented():
    row, _ = ai.build_identity_row(
        patent_id="US2021123456A1", batch="Batch_01",
        meta={"assignee": "SOME INVENTOR", "app_year": "2020"},
    )
    assert row["aircraft_name"] is None
    assert row["powertrain"] is None
    assert row["is_electric"] == "Unknown"
    assert row["needs_review"] is True
    assert "no aircraft name" in row["review_reason"]
    assert "no specifications" in row["review_reason"]


def test_row_columns_match_the_declared_schema():
    """Drift guard: the export reindexes to IDENTITY_COLUMNS, so a key the row
    builder emits under a name not in that list would be silently dropped."""
    row, _ = ai.build_identity_row(patent_id="US1", batch="Batch_01", meta=META)
    assert set(row) == set(ai.IDENTITY_COLUMNS)


def test_row_gazetteer_spec_beats_regex_hint():
    gaz = [{"company_canonical": "Lilium", "aircraft_name": "Lilium Jet", "aka": "",
            "year_from": "2015", "year_to": "2030", "powertrain": "BatteryElectric",
            "payload_kg": "200", "spec_source": "EASA TCDS"}]
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=META,
        batch_meta={"company_canonical": "Lilium"},
        gaz_hit=ai.match_gazetteer("Lilium", "2020", gaz),
        spec_hints=ai.extract_spec_hints("in one embodiment the payload is about 900 kg"),
    )
    assert row["payload_kg"] == 200.0
    assert row["spec_source"] == "gazetteer"
