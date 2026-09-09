"""
test_identity_review.py — the Stage 03a review contract.

What the reviewer types must survive a re-run, every value they sign off on
must point at the sentence it came from, and no patent may be left without a
working aircraft name. These tests pin those three promises, plus the PatSeer
column mapping that was silently missing the export's real legal-status column
(and would have called every pending "ACTIVE - APPLIED" row Granted).

Run: pytest tests/test_identity_review.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import aircraft_identity as ai            # noqa: E402
from src import identity_schema as schema          # noqa: E402
from src import patent_maturity as pm              # noqa: E402
from src import text_citation as tc                # noqa: E402
from src import wizard_link as wl                  # noqa: E402
from src.identity_excel import export_identity_excel, recompute_finals   # noqa: E402


# ─── text_citation ───────────────────────────────────────────────────────────

META = {
    "title": "Vertical take-off and landing aircraft",
    "abstract": "An aircraft 100 having a plurality of electric motors powered by a "
                "battery pack. The aircraft hovers and then transitions to forward flight.",
    "first_claim": "An aircraft comprising an S-4 fuselage.",
    "innovation_objective": None,
    "description_of_drawings": "FIG. 1 is a perspective view of the Midnight aircraft.",
}


def test_find_quote_reports_first_section_in_trust_order():
    hit = tc.find_quote(META, r"aircraft")
    assert hit["section"] == "Title"
    assert "Vertical take-off" in hit["quote"]


def test_literal_pattern_tolerates_hyphen_and_space_variants():
    for typed in ("S4", "S-4", "S 4"):
        hit = tc.find_quote(META, tc.literal_pattern(typed))
        assert hit and hit["section"] == "First claim", typed
    assert tc.find_quote(META, tc.literal_pattern("Midnight"))["section"] == "Description of drawings"
    assert tc.find_quote(META, tc.literal_pattern("Vertiia")) is None


def test_literal_pattern_is_whole_word():
    """'S4' must not be found inside 'S400' or 'US4'."""
    assert tc.find_quote({"abstract": "the US4 connector and part S400"},
                         tc.literal_pattern("S4")) is None


@pytest.mark.parametrize("text, expected", [
    ("A VTOL aircraft that hovers.", "VTOL"),
    ("A short take-off aircraft for grass strips.", "STOL"),
    ("A STOL aircraft with vertical take-off capability.", "V/STOL"),
    ("A conventional take-off aeroplane.", "CTOL"),
    ("A fixed-wing drone.", None),
])
def test_classify_takeoff(text, expected):
    pred = tc.classify_takeoff({"abstract": text})
    assert pred["value"] == expected


def test_stol_quote_is_the_stol_sentence_even_when_mixed():
    """The reviewer disapproves on STOL, so that is the sentence they must read."""
    pred = tc.classify_takeoff({"title": "VTOL aircraft",
                                "abstract": "In one embodiment the aircraft performs a short take-off."})
    assert pred["value"] == "V/STOL"
    assert "short take-off" in pred["quote"].lower()
    assert pred["confidence"] < tc._CONF_TAKEOFF_CLEAR


# ─── the row: citations and finals ───────────────────────────────────────────

def test_row_carries_powertrain_quote_and_takeoff_quote():
    row, ev = ai.build_identity_row(
        patent_id="US2021123456A1", batch="Batch_01", meta=META,
        powertrain_pred=ai.classify_powertrain(META["abstract"]),
        takeoff_pred=tc.classify_takeoff(META),
    )
    assert row["is_electric"] == "Yes"
    assert row["powertrain_section"] == "Abstract"
    assert "battery pack" in row["powertrain_quote"]
    assert row["takeoff_mode"] == "VTOL"
    assert row["takeoff_section"] == "Title"
    assert any(e["field"] == "takeoff_mode" for e in ev)
    assert row["needs_review"] is False


def test_gazetteer_name_is_marked_not_in_text():
    gaz = [{"company_canonical": "Joby Aviation", "aircraft_name": "S4", "aka": "",
            "year_from": "2015", "year_to": "2030", "powertrain": "BatteryElectric"}]
    meta = {**META, "first_claim": "An aircraft comprising a fuselage."}     # no S-4 here
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=meta,
        batch_meta={"company_canonical": "Joby Aviation"},
        gaz_hit=ai.match_gazetteer("Joby Aviation", "2020", gaz),
    )
    assert row["aircraft_name"] == "S4"
    assert row["aircraft_name_in_text"] == "No"
    assert row["aircraft_name_quote"] is None
    assert "not found in patent text" in row["review_reason"]
    assert row["powertrain_section"].startswith("gazetteer")


def test_gazetteer_name_found_in_text_is_quoted():
    gaz = [{"company_canonical": "Joby Aviation", "aircraft_name": "S4", "aka": "",
            "year_from": "2015", "year_to": "2030", "powertrain": "BatteryElectric"}]
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=META,
        batch_meta={"company_canonical": "Joby Aviation"},
        gaz_hit=ai.match_gazetteer("Joby Aviation", "2020", gaz),
    )
    assert row["aircraft_name_in_text"] == "Yes"
    assert row["aircraft_name_section"] == "First claim"
    assert "S-4" in row["aircraft_name_quote"]


def test_finals_fall_back_to_group_and_machine_values():
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=META,
        wizard={"approved": True, "aircraft_name": "Joby Aviation 2", "duplicate_type": None,
                "duplicate_of": None, "disapprove_reason": None},
        group={"aircraft_group": "Joby Aviation 2", "aircraft_group_source": "wizard",
               "aircraft_group_note": None},
        powertrain_pred=ai.classify_powertrain(META["abstract"]),
        takeoff_pred=tc.classify_takeoff(META),
    )
    assert row["wizard_approved"] is True
    assert row["aircraft_name_final"] == "Joby Aviation 2"
    assert row["is_electric_final"] == "Yes"
    assert row["takeoff_final"] == "VTOL"


def test_generated_group_name_is_a_review_reason():
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=META,
        group={"aircraft_group": "WANG XI 1", "aircraft_group_source": "generated",
               "aircraft_group_note": None},
    )
    assert "group name generated" in row["review_reason"]


def test_row_columns_match_schema_with_all_inputs():
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=META,
        takeoff_pred=tc.classify_takeoff(META),
        wizard={"approved": False}, group={"aircraft_group": "X 1"},
    )
    assert set(row) == set(ai.IDENTITY_COLUMNS)
    assert all(c in ai.IDENTITY_COLUMNS for c in schema.HUMAN_COLUMNS if c != "llm_answer")
    for final, human, machine in schema.FINAL_RULES:
        assert {final, human, machine} <= set(ai.IDENTITY_COLUMNS)


# ─── wizard_link: naming ─────────────────────────────────────────────────────

WIZ = {
    "P1": {"aircraft_name": "Bell Helicopter 12", "duplicate_type": None, "duplicate_of": None},
    "P2": {"aircraft_name": None, "duplicate_type": "2", "duplicate_of": "P1"},
    "P3": {"aircraft_name": None, "duplicate_type": "3", "duplicate_of": "P1"},
    "P4": {"aircraft_name": None, "duplicate_type": None, "duplicate_of": None},
    "P5": {"aircraft_name": "Bell Helicopter 9", "duplicate_type": "2", "duplicate_of": "P1"},
    "P7": {"aircraft_name": None, "duplicate_type": "2", "duplicate_of": "P2"},   # chain
}
BM = {p: {"company_canonical": "Bell / Textron"} for p in WIZ}
BM["P6"] = {"company_canonical": "Individual Inventor"}
IDX = {p: {"app_year": "2020", "assignee": "BELL HELICOPTER TEXTRON INC (US)"} for p in WIZ}
IDX["P6"] = {"app_year": "2019", "assignee": "WANG XI (CN)"}


@pytest.fixture
def groups():
    return wl.assign_aircraft_groups(list(WIZ) + ["P6"], BM, IDX, WIZ)


def test_every_patent_gets_a_group_name(groups):
    assert set(groups) == set(WIZ) | {"P6"}
    assert all(g["aircraft_group"] for g in groups.values())


def test_wizard_name_wins(groups):
    assert groups["P1"] == {"aircraft_group": "Bell Helicopter 12",
                            "aircraft_group_source": "wizard", "aircraft_group_note": None}


def test_d2_inherits_and_chains(groups):
    assert groups["P2"]["aircraft_group"] == "Bell Helicopter 12"
    assert groups["P2"]["aircraft_group_source"] == "inherited_D2"
    assert groups["P7"]["aircraft_group"] == "Bell Helicopter 12"      # D2 of a D2


def test_d3_is_a_different_aircraft_and_takes_the_next_number(groups):
    """The ruled convention: D1/D2 inherit, a D3 takes its OWN new number.
    Letters are reserved for the variants inside one patent."""
    assert groups["P3"]["aircraft_group"] == "Bell Helicopter 13"
    assert groups["P3"]["aircraft_group_source"] == "generated_D3"
    assert "different aircraft" in groups["P3"]["aircraft_group_note"]


def test_generated_number_uses_the_annotators_prefix_and_never_collides(groups):
    """The annotator wrote 'Bell Helicopter', not 'Bell / Textron', and used 9
    and 12; the D3 took 13 — so the plain generated one must be 14."""
    assert groups["P4"]["aircraft_group"] == "Bell Helicopter 14"
    assert groups["P4"]["aircraft_group_source"] == "generated"


def test_individual_inventor_uses_the_assignee_string(groups):
    assert groups["P6"]["aircraft_group"] == "WANG XI 1"


def test_d2_with_a_different_name_from_its_original_is_flagged(groups):
    assert "differs from original P1" in groups["P5"]["aircraft_group_note"]


def test_split_group_name():
    assert wl.split_group_name("Bell Helicopter 12b") == ("Bell Helicopter", 12, "b")
    assert wl.split_group_name("Archer Aviation") == ("Archer Aviation", None, "")
    assert wl.split_group_name("BEIHANG UNIV 3") == ("BEIHANG UNIV", 3, "")


def test_dup_type_parses_the_wizard_composite_value():
    assert wl._dup_type("2 — D2 — Same aircraft, same figures") == "2"
    assert wl._dup_type("3 — Same plane, small changes") == "3"
    assert wl._dup_type(None) is None


# ─── human edits survive a re-run ────────────────────────────────────────────

def test_human_columns_and_finals_survive_reexport(tmp_path):
    out = tmp_path / "aircraft_identity_Batch_99.xlsx"
    row, ev = ai.build_identity_row(
        patent_id="US1", batch="Batch_99", meta=META,
        group={"aircraft_group": "Joby Aviation 2", "aircraft_group_source": "wizard",
               "aircraft_group_note": None},
        powertrain_pred=ai.classify_powertrain(META["abstract"]),
        takeoff_pred=tc.classify_takeoff(META),
    )
    export_identity_excel([row], ev, [], out, preserve_human=True)

    # The reviewer types into the sheet.
    df = pd.read_excel(out, sheet_name="Identity", dtype=object)
    df.loc[0, "aircraft_name_human"] = "S4"
    df.loc[0, "is_electric_human"] = "No"
    df.loc[0, "takeoff_human"] = "STOL"
    df.loc[0, "review_status"] = "done"
    df.loc[0, "notes"] = "checked against the PDF"
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Identity", index=False)

    # A re-run with the same machine values must keep every typed cell and
    # recompute the finals from them.
    export_identity_excel([row], ev, [], out, preserve_human=True)
    again = pd.read_excel(out, sheet_name="Identity", dtype=object).iloc[0]
    assert again["aircraft_name_human"] == "S4"
    assert again["aircraft_name_final"] == "S4"
    assert again["is_electric_human"] == "No" and again["is_electric_final"] == "No"
    assert again["takeoff_human"] == "STOL" and again["takeoff_final"] == "STOL"
    assert again["review_status"] == "done"
    assert again["notes"] == "checked against the PDF"
    # ...and the machine columns are untouched by the human ones.
    assert again["is_electric"] == "Yes"
    assert again["takeoff_mode"] == "VTOL"
    assert again["aircraft_group"] == "Joby Aviation 2"
    # A backup of the edited file was taken before overwriting — into _backups/,
    # NOT beside the workbook: anything globbing the folder would otherwise read
    # every past generation as data (it tripled a corpus count on 2026-09-08).
    assert list((tmp_path / "_backups").glob("aircraft_identity_Batch_99.BACKUP_*.xlsx"))
    assert not list(tmp_path.glob("*.BACKUP_*.xlsx"))


def test_recompute_finals_treats_blank_and_nan_as_untyped():
    df = pd.DataFrame({"aircraft_name_human": [None, " ", float("nan"), " Vertiia "],
                       "aircraft_group": ["A 1", "A 2", "A 3", "A 4"],
                       "is_electric_human": [None] * 4, "is_electric": ["Yes"] * 4,
                       "takeoff_human": [None] * 4, "takeoff_mode": ["VTOL"] * 4})
    out = recompute_finals(df)
    assert out["aircraft_name_final"].tolist() == ["A 1", "A 2", "A 3", "Vertiia"]


# ─── PatSeer columns of THIS export ──────────────────────────────────────────

@pytest.mark.parametrize("pid, raw, stage, active", [
    ("US2022267016A1", "ACTIVE - APPLIED",                         "Application", True),
    ("US2022267016A1", "ACTIVE - GRANTED",                         "Granted",     True),
    ("US11524776B2",   "INACTIVE - NONPAYMENT",                    "Granted",     False),
    ("US11524776B2",   "INACTIVE - EXPIRED",                       "Granted",     False),
    ("US2022267016A1", "INACTIVE - REJECTED / REFUSED / SUSPENDED", "Application", False),
    ("US2022267016A1", "INACTIVE - WITHDRAWN / SURRENDERED",       "Application", False),
    ("US11524776B2",   "INACTIVE - WITHDRAWN / SURRENDERED",       "Granted",     False),
    ("US2022267016A1", "Patented Case",                            "Granted",     True),
    ("US2022267016A1", "Notice of Allowance Mailed - Application Received", "Application", True),
    ("US2022267016A1", "Publications - Issue Fee Payment Verified", "Application", True),
    ("US2022267016A1", "Abandoned - Failure to Respond to an Office Action", "Application", False),
    ("US2022267016A1", "Patent Expired Due to NonPayment of Maintenance Fees", "Granted", False),
])
def test_patseer_legal_status_strings(pid, raw, stage, active):
    out = pm.legal_stage_for(pid, raw)
    assert out["value"] == stage, raw
    assert out["active"] is active, raw


def test_active_alone_does_not_mean_granted():
    """'ACTIVE' says the right subsists; only the kind code can say granted-vs-filed."""
    out = pm.legal_stage_for("US2022267016A1", "ACTIVE")
    assert out["value"] == "Application"
    assert out["active"] is True
    assert "kind_code" in out["source"]


def test_unknown_kind_plus_stageless_status_does_not_crash():
    out = pm.legal_stage_for("XX12345Q7", "INACTIVE - WITHDRAWN / SURRENDERED")
    assert out["value"] == "Unknown"
    assert out["active"] is False


def test_export_column_names_are_matched(tmp_path):
    """The actual headers of the 2026-06 PatSeer export."""
    df = pd.DataFrame([{
        "Record Number": "US1", "Legal Status Current": "ACTIVE - APPLIED",
        "Legal Status (Dead/Alive)": "ALIVE", "Record Type": "Application",
        "Number Of Claims": "20", "No. of Simple Family Members": "3",
        "No. of Forward Citations (Individual)": "7", "Priority Date (Record)": "2018-10-30",
        "Assignee Country": "US", "Publication/Issue Date": "2020-01-09",
    }])
    path = tmp_path / "export.xlsx"
    df.to_excel(path, index=False)
    index = {"US1": {"assignee": "X", "pub_year": "2020", "app_year": "2019",
                     "backward_cites": [], "forward_cites": []}}
    found = pm.enrich_from_excel(index, path)["found"]
    for key in ("legal_status_raw", "legal_alive_raw", "record_type", "claim_count",
                "family_size", "fwd_cite_count_col", "priority_date", "assignee_country_col"):
        assert key in found, key
    assert "grant_date" not in found        # Publication/Issue Date is NOT a grant date
    row = pm.build_maturity_row("US1", index, snapshot_date="2026-06-08")
    assert row["legal_stage"] == "Application" and row["right_active"] is True
    assert row["claim_count"] == "20" and row["family_size"] == "3"
    assert row["forward_citations"] == 7
    assert row["priority_year"] == 2018
    assert row["snapshot_date"] == "2026-06-08"
    assert row["years_since_publication"] == 6          # 2026 - 2020, not today's year
    assert row["grant_lag_years"] is None


def test_dead_alive_column_wins_for_right_active():
    index = {"US11524776B2": {"assignee": "X", "pub_year": "2022", "app_year": "2019",
                              "legal_status_raw": "ACTIVE - GRANTED", "legal_alive_raw": "DEAD",
                              "backward_cites": [], "forward_cites": []}}
    row = pm.build_maturity_row("US11524776B2", index)
    assert row["legal_stage"] == "Granted"
    assert row["right_active"] is False


# ─── is_electric abstains on a coin-flip ─────────────────────────────────────
# Measured 2026-09-08 on the real corpus: PatentSBERTa's zero-shot powertrain
# margins run 0.21-0.59 (median 0.30), so 946 of 949 sat below the review
# threshold. Left unguarded they put "No" — the reviewer's disapproval verdict
# — on 209 patents. The proposal stays; the derived verdict abstains.

from src.aircraft_specs import electric_verdict, _CONF_ELECTRIC_FLOOR   # noqa: E402


def test_electric_floor_matches_the_review_threshold():
    """The constant is duplicated to avoid a circular import — pin the pair."""
    assert _CONF_ELECTRIC_FLOOR == schema.NEEDS_REVIEW_BELOW


@pytest.mark.parametrize("powertrain, source, conf, expected, expected_src", [
    ("Piston",          "sbert",     0.30, "Unknown", None),   # the coin-flip case
    ("Turbine",         "sbert",     0.54, "Unknown", None),
    ("HybridElectric",  "sbert",     0.30, "Unknown", None),
    ("Piston",          "sbert",     0.55, "No",      "sbert"),      # confident SBERT decides
    ("Piston",          "keyword",   0.80, "No",      "keyword"),    # keyword always decides
    ("Turbine",         "keyword",   0.80, "No",      "keyword"),
    ("BatteryElectric", "gazetteer", 0.95, "Yes",     "gazetteer"),
    ("HybridElectric",  "keyword",   0.80, "Hybrid",  "keyword"),
    ("BatteryElectric", "sbert",     0.30, "Unknown", None),   # abstains in BOTH directions
    (None,              None,        None, "Unknown", None),
])
def test_electric_verdict(powertrain, source, conf, expected, expected_src):
    assert electric_verdict(powertrain, source, conf) == (expected, expected_src)


@pytest.mark.parametrize("powertrain, source, conf, expected, expected_src", [
    (None,              None,      None, "Yes", "company"),   # nothing known -> the company decides
    ("Piston",          "sbert",   0.30, "Yes", "company"),   # a coin-flip does not outrank it
    ("Turbine",         "keyword", 0.80, "No",  "keyword"),   # the patent's own words DO
    ("BatteryElectric", "keyword", 0.80, "Yes", "keyword"),
])
def test_all_electric_company_fills_only_an_abstention(powertrain, source, conf, expected, expected_src):
    """"Archer only builds battery-electric aircraft" is real company-level
    evidence — but a turbine stated in this patent's own text still wins."""
    assert electric_verdict(powertrain, source, conf, company_all_electric=True) \
        == (expected, expected_src)


def test_all_electric_companies_is_read_off_the_gazetteer():
    gaz = [{"company_canonical": "Archer Aviation", "powertrain": "BatteryElectric"},
           {"company_canonical": "Archer Aviation", "powertrain": "BatteryElectric"},
           {"company_canonical": "Bell / Textron",  "powertrain": "BatteryElectric"},
           {"company_canonical": "Bell / Textron",  "powertrain": "Turbine"},
           {"company_canonical": "",                "powertrain": "BatteryElectric"}]
    assert ai.all_electric_companies(gaz) == {"Archer Aviation"}


# ─── the annotator's disapproval reason as ground truth ──────────────────────

@pytest.mark.parametrize("reason, expected", [
    ("Not VTOL — Not VTOL (STOL / CTOL)", {"takeoff": "STOL"}),
    ("Out of TD — STOL",                  {"takeoff": "STOL"}),
    ("Out of TD — Electric",              {"electric": "No"}),
    ("Other — non-electric aircraft",     {"electric": "No"}),
    # The reasons that settle nothing — today's undivided "Out of TD" above all.
    ("Out of Domain — Out of TD",                  {}),
    ("Out of Domain — Out of Technological Domain", {}),
    ("Out of TD — UAV Pure",                       {}),
    ("Pure UAV — Pure UAV",                        {"uav": "Pure"}),
    ("Pure UAV — Pure UAV (No Passenger/AAM application)", {"uav": "Pure"}),
    ("No Aircraft Image — No usable aircraft images", {}),
    ("Other — Other",                              {}),
    (None,                                         {}),
])
def test_human_truth_only_reads_reasons_that_name_the_thing(reason, expected):
    got = wl.human_truth({"disapprove_reason": reason, "approved": False})
    assert {k: v for k, v in got.items() if not k.endswith("_evidence")} == expected


def test_human_truth_ignores_an_approved_patent():
    assert wl.human_truth({"disapprove_reason": "Not VTOL — Not VTOL (STOL / CTOL)",
                           "approved": True}) == {}


def test_human_disapproval_outranks_the_keyword_pass():
    """The text says VTOL; the annotator looked at the drawings and said STOL."""
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=META,
        takeoff_pred=tc.classify_takeoff(META),
        wizard={"approved": False, "disapprove_reason": "Not VTOL — Not VTOL (STOL / CTOL)"},
    )
    assert row["takeoff_mode"] == "STOL"
    assert row["takeoff_source"] == "human"
    assert "wizard disapproval" in row["takeoff_section"]
    assert row["takeoff_final"] == "STOL"


# ─── the review queue ────────────────────────────────────────────────────────

def _row(**kw):
    base = {"wizard_approved": True, "aircraft_group_source": "wizard",
            "aircraft_group_note": None, "aircraft_name_in_text": "No",
            "aircraft_name_human": None, "is_electric": "Yes",
            "is_electric_human": None, "takeoff_mode": "VTOL", "takeoff_human": None}
    base.update(kw)
    return schema.review_flags(base)


def test_a_settled_row_is_not_in_the_queue():
    assert _row()["review_queue"] is None


def test_disapproved_patents_are_never_queued():
    """They are out of the corpus — re-deciding their powertrain is work for nothing."""
    f = _row(wizard_approved=False, is_electric="Unknown", takeoff_mode=None,
             aircraft_group_source="generated")
    assert f["review_queue"] is None
    assert not any((f["name_review"], f["electric_review"], f["takeoff_review"]))


@pytest.mark.parametrize("kw, expected", [
    ({"is_electric": "Unknown"},                      "electric"),
    ({"takeoff_mode": None},                          "takeoff"),
    ({"takeoff_mode": "V/STOL"},                      "takeoff"),
    ({"takeoff_mode": "STOL"},                        "takeoff"),
    ({"aircraft_group_source": "generated"},          "name"),
    ({"aircraft_name_in_text": "Yes"},                "name"),
    ({"aircraft_group_note": "D2 name differs from original US1 (X 2)"}, "name"),
    ({"is_electric": "Unknown", "takeoff_mode": None}, "electric+takeoff"),
    ({"aircraft_group_source": "generated", "is_electric": "Unknown",
      "takeoff_mode": None},                          "name+electric+takeoff"),
])
def test_queue_names_exactly_the_open_fields(kw, expected):
    assert _row(**kw)["review_queue"] == expected


@pytest.mark.parametrize("field, kw", [
    ("name",     {"aircraft_group_source": "generated", "aircraft_name_human": "S4"}),
    # answering "No" asks the ElectricSimilar follow-up, so answer that too
    ("electric", {"is_electric": "Unknown", "is_electric_human": "No",
                  "electric_similar_human": "ElectricSimilar"}),
    ("electric", {"is_electric": "Unknown", "is_electric_human": "Yes"}),
    ("takeoff",  {"takeoff_mode": None, "takeoff_human": "VTOL"}),
])
def test_a_field_leaves_the_queue_once_you_answer_it(field, kw):
    assert _row(**kw)["review_queue"] is None


def test_a_company_verdict_keeps_electric_out_of_the_queue():
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta={"assignee": "ARCHER AVIATION INC (US)"},
        batch_meta={"company_canonical": "Archer Aviation"},
        company_all_electric=True,
        takeoff_pred={"value": "VTOL", "source": "keyword", "confidence": 0.8,
                      "section": "Title", "quote": "VTOL aircraft"},
    )
    assert (row["is_electric"], row["is_electric_source"]) == ("Yes", "company")
    assert row["electric_review"] is False
    assert "all-electric portfolio" in row["review_reason"]


def test_low_confidence_sbert_powertrain_is_flagged_not_hidden():
    """The proposal must stay readable in its own column and never become a
    verdict. With nothing STATED in the text the row is presumed electric and
    not queued; with the presumption off it is queued with a reason."""
    pred = {"value": "Piston", "source": "sbert", "confidence": 0.30, "families": {}}
    row, _ = ai.build_identity_row(patent_id="US1", batch="Batch_01", meta=META,
                                   powertrain_pred=pred, takeoff_pred=tc.classify_takeoff(META))
    assert row["powertrain"] == "Piston"            # proposal kept
    assert row["powertrain_confidence"] == 0.30
    assert (row["is_electric"], row["is_electric_source"]) == ("Unknown", "presumed")
    assert row["electric_review"] is False
    assert row["is_electric_final"] == "Unknown"
    row2, _ = ai.build_identity_row(patent_id="US1", batch="Batch_01", meta=META,
                                    powertrain_pred=pred, takeoff_pred=tc.classify_takeoff(META),
                                    presume_electric=False)
    assert "low-confidence sbert guess (Piston)" in row2["review_reason"]
    assert row2["electric_review"] is True


def test_reviewer_can_still_override_an_abstention(tmp_path):
    out = tmp_path / "aircraft_identity_Batch_98.xlsx"
    row, ev = ai.build_identity_row(
        patent_id="US1", batch="Batch_98", meta=META,
        powertrain_pred={"value": "Piston", "source": "sbert", "confidence": 0.30},
        group={"aircraft_group": "X 1", "aircraft_group_source": "wizard",
               "aircraft_group_note": None},
        takeoff_pred=tc.classify_takeoff(META),
    )
    export_identity_excel([row], ev, [], out, preserve_human=True)
    df = pd.read_excel(out, sheet_name="Identity", dtype=object)
    df.loc[0, "is_electric_human"] = "No"
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Identity", index=False)
    export_identity_excel([row], ev, [], out, preserve_human=True)
    again = pd.read_excel(out, sheet_name="Identity", dtype=object).iloc[0]
    assert again["is_electric"] == "Unknown"        # machine still abstains
    assert again["is_electric_final"] == "No"       # the human decided


# ─── the body text: two thirds of the remaining powertrain answers ───────────

BODY = ("The aircraft of the present invention is propelled by six electric motors "
        "drawing current from a battery pack housed in the wing box.")


def test_signal_text_beats_the_body():
    pred = ai.classify_powertrain("A hybrid-electric aircraft.", body_text=BODY)
    assert (pred["value"], pred["confidence"]) == ("HybridElectric", 0.80)


def test_body_answers_what_the_abstract_never_states():
    """The abstract says nothing about propulsion; the description does."""
    pred = ai.classify_powertrain("An aircraft having a fuselage and wings.", body_text=BODY)
    assert pred["value"] == "BatteryElectric"
    assert pred["source"] == "keyword"
    assert pred["confidence"] == 0.65          # quotable, but weaker than a signal hit
    assert pred["confidence"] > schema.NEEDS_REVIEW_BELOW      # still decides is_electric


def test_body_hit_still_carries_a_quote_and_names_its_section():
    meta = {"abstract": "An aircraft having a fuselage and wings.", "description": BODY}
    pred = ai.classify_powertrain(meta["abstract"], body_text=BODY)
    cite = tc.find_quote(meta, pred["pattern"])
    assert cite["section"] == "Description"
    assert "battery pack" in cite["quote"]


def test_a_name_is_never_searched_in_the_body():
    """Patents name OTHER people's aircraft in their prior-art discussion —
    counting that as 'this patent names its aircraft' would queue it for nothing."""
    meta = {"abstract": "An aircraft having a fuselage.",
            "description": "Unlike the V-22 Osprey, the present invention has no proprotor."}
    assert tc.find_quote(meta, tc.literal_pattern("V-22"), sections=tc.NAME_SECTIONS) is None
    assert tc.find_quote(meta, tc.literal_pattern("V-22"))["section"] == "Description"


def test_no_text_at_all_is_still_unknown():
    pred = ai.classify_powertrain("", body_text=None)
    assert pred["value"] is None


# ─── a body sentence only counts when it COMMITS ─────────────────────────────
# Patents are drafted not to commit. "a drive unit may include an electric motor
# or an engine" enumerates options; reading the first one as the answer would
# put a wrong verdict in the column the reviewer acts on. Hedged sentences keep
# their proposal and their quote but stay under the abstention floor.

@pytest.mark.parametrize("body", [
    "A drive unit may include an electric motor or an engine.",
    "The rotors 44 can be electric motors or combustion engines or any other known type.",
    "The propulsion system comprises an electric motor or the like.",
    "Such drones are typically powered by onboard batteries.",
    "Multicopters are conventionally electrically powered.",
    "A propulsion unit driven by an electric motor or any other known means.",
])
def test_a_hedged_body_sentence_does_not_decide(body):
    pred = ai.classify_powertrain("An aircraft having a fuselage and wings.", body_text=body)
    assert pred["value"] is not None                       # the proposal is kept
    assert pred["confidence"] < schema.NEEDS_REVIEW_BELOW   # but it decides nothing
    assert electric_verdict(pred["value"], pred["source"], pred["confidence"]) == ("Unknown", None)


@pytest.mark.parametrize("body, expected", [
    ("The UAV also includes four electric motors driving the rotors.", "BatteryElectric"),
    ("The aircraft is powered by a hydrogen fuel cell stack.",         "HydrogenFuelCell"),
    ("Lift is produced by two turboshaft engines mounted on the wing.", "Turbine"),
])
def test_a_committed_body_sentence_decides(body, expected):
    pred = ai.classify_powertrain("An aircraft having a fuselage and wings.", body_text=body)
    assert pred["value"] == expected
    assert pred["confidence"] == 0.65
    assert electric_verdict(pred["value"], pred["source"], pred["confidence"])[0] != "Unknown"


def test_a_committed_sentence_is_preferred_over_an_earlier_hedged_one():
    """The background paragraph mentions turbines; the invention states a battery."""
    body = ("Conventional VTOL aircraft are typically driven by gas turbine engines. "
            "The aircraft of the present invention is driven by a battery pack.")
    pred = ai.classify_powertrain("An aircraft.", body_text=body)
    assert pred["value"] == "BatteryElectric"
    assert pred["confidence"] == 0.65


def test_a_hedged_row_is_visible_but_presumed_electric():
    """"an electric motor or an engine" states nothing — the proposal stays
    visible, the verdict abstains, and under the burden-of-proof rule the row is
    presumed electric rather than queued."""
    meta = {"abstract": "An aircraft having a fuselage.",
            "description": "A drive unit may include an electric motor or an engine."}
    pred = ai.classify_powertrain(meta["abstract"], body_text=meta["description"])
    tk = {"value": "VTOL", "source": "keyword", "confidence": 0.8, "section": "Title", "quote": "VTOL"}
    row, _ = ai.build_identity_row(patent_id="US1", batch="Batch_01", meta=meta,
                                   powertrain_pred=pred, takeoff_pred=tk)
    assert row["powertrain"] == "BatteryElectric"      # visible
    assert (row["is_electric"], row["is_electric_source"]) == ("Unknown", "presumed")
    assert row["electric_review"] is False
    row2, _ = ai.build_identity_row(patent_id="US1", batch="Batch_01", meta=meta,
                                    powertrain_pred=pred, takeoff_pred=tk, presume_electric=False)
    assert row2["electric_review"] is True
    assert "electric" in row2["review_queue"]


# ─── a machine must never disapprove on its own ──────────────────────────────

@pytest.mark.parametrize("verdict, source, queued", [
    ("No",      "keyword",   True),    # the machine says non-electric -> YOU confirm it
    ("No",      "gazetteer", True),
    ("Hybrid",  "keyword",   True),
    ("No",      "human",     False),   # the annotator already said so -> ground truth
    ("Yes",     "keyword",   False),   # approving needs no confirmation
    ("Yes",     "company",   False),
    ("Unknown", None,        True),
])
def test_a_non_electric_verdict_is_always_reviewed_unless_a_human_made_it(verdict, source, queued):
    f = schema.review_flags({"wizard_approved": True, "aircraft_group_source": "wizard",
                             "aircraft_group_note": None, "aircraft_name_in_text": "No",
                             "aircraft_name_human": None, "is_electric": verdict,
                             "is_electric_source": source, "is_electric_human": None,
                             "takeoff_mode": "VTOL", "takeoff_human": None})
    assert f["electric_review"] is queued


@pytest.mark.parametrize("mode, source, queued", [
    ("STOL",   "keyword", True),     # the machine read STOL -> YOU confirm before disapproving
    ("V/STOL", "keyword", True),
    ("STOL",   "human",   False),    # the annotator disapproved it as STOL -> ground truth
    ("VTOL",   "keyword", False),
    (None,     None,      True),
])
def test_a_stol_verdict_is_always_reviewed_unless_a_human_made_it(mode, source, queued):
    f = schema.review_flags({"wizard_approved": True, "aircraft_group_source": "wizard",
                             "aircraft_group_note": None, "aircraft_name_in_text": "No",
                             "aircraft_name_human": None, "is_electric": "Yes",
                             "is_electric_source": "keyword", "is_electric_human": None,
                             "takeoff_mode": mode, "takeoff_source": source,
                             "takeoff_human": None})
    assert f["takeoff_review"] is queued


def test_every_identity_column_has_a_colour_group_or_falls_through():
    """A column missing from COLUMN_GROUPS is fine (it gets the neutral fill),
    but a column named in COLUMN_GROUPS that does not exist is a typo."""
    named = {c for cols in schema.COLUMN_GROUPS.values() for c in cols}
    assert named <= set(ai.IDENTITY_COLUMNS), named - set(ai.IDENTITY_COLUMNS)



# ─── variants: the aircraft INSIDE one patent, from the annotator's record ───

def test_variant_names_give_each_aircraft_a_letter():
    assert schema.variant_names("Airbus Helicopters 4", 2) == \
        "Airbus Helicopters 4a; Airbus Helicopters 4b"
    assert schema.variant_names("Airbus Helicopters 4", "3") == \
        "Airbus Helicopters 4a; Airbus Helicopters 4b; Airbus Helicopters 4c"


def test_an_unnumbered_name_gets_a_space_before_the_letter():
    assert schema.variant_names("OVERAIR", 2) == "OVERAIR a; OVERAIR b"
    assert schema.variant_names("CityAirbus", 2) == "CityAirbus a; CityAirbus b"


@pytest.mark.parametrize("count", [None, 1, "1", "True", float("nan"), 0])
def test_a_single_aircraft_has_no_variant_names(count):
    assert schema.variant_names("Airbus Helicopters 4", count) is None


def test_wizard_loader_reads_variants_and_edge_tags(tmp_path):
    """<pid>_archN rows carry topType per aircraft; edgeTags on G1 only —
    the T2 'edgeTags' is a per-image flag with the same Field name."""
    rows = [
        ("EP1", "T1", "Approval", "isApproved", True),
        ("EP1", "T1", "Aircraft", "aircraftName", "AIRBUS HELICOPTERS 4"),
        ("EP1", "T1", "Count", "archCount", "2"),
        ("EP1", "G1", "Edge-Case Tags", "edgeTags", "UAVSimilar"),
        ("EP1_arch1", "G1", "Top", "topType", "MR — Wingless — Multirotor"),
        ("EP1_arch1", "G1", "Pure", "notPureArch", False),
        ("EP1_arch2", "G1", "Top", "topType", "TR — Vectored Thrust — Tilt Rotor"),
        ("EP1_arch2", "G1", "Edge-Case Tags", "edgeTags", "ElectricSimilar"),
        ("EP1", "T2", "Image: x.png", "edgeTags", "Image label is not correspponding"),
        ("EP2", "T1", "Approval", "isApproved", True),
        ("EP2", "T1", "Count", "archCount", "True"),
    ]
    df = pd.DataFrame(rows, columns=["Patent_ID", "Section", "Sub_Dimension", "Field", "Value"])
    with pd.ExcelWriter(tmp_path / "reviewed_patents_Batch_01.xlsx", engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Review", index=False)
    rec = wl.load_wizard_reviews(tmp_path, verbose=False)
    assert rec["EP1"]["arch_count"] == 2
    assert [v["top_type"] for v in rec["EP1"]["variants"]] == ["MR", "TR"]
    assert rec["EP1"]["edge_tags"] == ["ElectricSimilar", "UAVSimilar"]   # base + variant, G1 only
    assert rec["EP2"]["arch_count"] == 1 and rec["EP2"]["variants"] == []
    assert "EP1_arch1" not in rec                                          # folded into the base


def test_variant_columns_land_on_the_row_and_in_the_finals():
    row, _ = ai.build_identity_row(
        patent_id="EP1", batch="Batch_01", meta=META,
        wizard={"approved": True, "arch_count": 2, "edge_tags": ["UAVSimilar"],
                "variants": [{"n": 1, "top_type": "MR"}, {"n": 2, "top_type": "TR"}]},
        group={"aircraft_group": "AIRBUS HELICOPTERS 4", "aircraft_group_source": "wizard",
               "aircraft_group_note": None},
    )
    assert row["wizard_arch_count"] == 2
    assert row["wizard_variant_types"] == "MR | TR"
    assert row["aircraft_group_variants"] == "AIRBUS HELICOPTERS 4a; AIRBUS HELICOPTERS 4b"
    assert row["aircraft_name_final_variants"] == "AIRBUS HELICOPTERS 4a; AIRBUS HELICOPTERS 4b"
    assert "2 aircraft variants" in row["review_reason"]
    # a typed real name propagates to the variants on the next export
    row["aircraft_name_human"] = "CityAirbus"
    schema.apply_finals(row)
    assert row["aircraft_name_final_variants"] == "CityAirbus a; CityAirbus b"


# ─── UAV: a hint for the tag the annotator forgot ────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("An unmanned aerial vehicle with four rotors.",                  "UAV"),
    ("A drone for parcel delivery.",                                  "UAV"),
    ("An aircraft that may be manned or unmanned, carrying passengers.", "UAV-language"),
    ("A four-passenger air taxi.",                                    None),
    ("An aircraft having a fuselage.",                                None),
])
def test_classify_uav(text, expected):
    assert tc.classify_uav({"abstract": text})["value"] == expected


def test_uav_hint_never_reaches_the_final_by_itself():
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01",
        meta={"abstract": "An unmanned aerial vehicle with four rotors."},
        uav_pred=tc.classify_uav({"abstract": "An unmanned aerial vehicle with four rotors."}),
        wizard={"approved": True, "edge_tags": []},
    )
    assert row["uav_hint"] == "UAV" and "unmanned" in row["uav_quote"]
    assert row["uav_final"] is None            # a tag is a human decision
    assert row["uav_review"] is True           # ...so it is queued
    assert "uav" in row["review_queue"]


def test_an_existing_uav_tag_settles_it_and_becomes_the_final():
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01",
        meta={"abstract": "An unmanned aerial vehicle with four rotors."},
        uav_pred=tc.classify_uav({"abstract": "An unmanned aerial vehicle with four rotors."}),
        wizard={"approved": True, "edge_tags": ["UAVSimilar"]},
    )
    assert row["uav_final"] == "UAVSimilar"
    assert row["uav_review"] is False


def test_typed_uav_answer_survives_reexport(tmp_path):
    out = tmp_path / "aircraft_identity_Batch_97.xlsx"
    meta = {"abstract": "An unmanned aerial vehicle with four rotors."}
    row, ev = ai.build_identity_row(patent_id="US1", batch="Batch_97", meta=meta,
                                    uav_pred=tc.classify_uav(meta),
                                    wizard={"approved": True, "edge_tags": []})
    export_identity_excel([row], ev, [], out, preserve_human=True, write_figures=False)
    assert "Figures" not in pd.ExcelFile(out).sheet_names
    df = pd.read_excel(out, sheet_name="Identity", dtype=object)
    df.loc[0, "uav_human"] = "UAVSimilar"
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Identity", index=False)
    export_identity_excel([row], ev, [], out, preserve_human=True, write_figures=False)
    again = pd.read_excel(out, sheet_name="Identity", dtype=object).iloc[0]
    assert again["uav_human"] == "UAVSimilar" and again["uav_final"] == "UAVSimilar"


# ─── a real name per variant, when there is one to choose from ───────────────

def test_variant_proposals_only_when_there_are_variants_and_a_choice():
    assert ai._variant_proposals(2, "Nexus 4EX", "Nexus 6HX") == "Nexus 4EX; Nexus 6HX"
    assert ai._variant_proposals(2, None, "Nexus 4EX; Nexus 6HX") == "Nexus 4EX; Nexus 6HX"
    assert ai._variant_proposals(1, "Nexus 4EX", "Nexus 6HX") is None      # no variants
    assert ai._variant_proposals(2, "S4", None) is None                     # one name = the letters do it
    assert ai._variant_proposals(2, None, None) is None


def test_typed_variant_names_replace_the_letters():
    row = {"aircraft_name_human": None, "aircraft_group": "Bell Helicopter 12",
           "is_electric_human": None, "is_electric": "Yes", "takeoff_human": None,
           "takeoff_mode": "VTOL", "uav_human": None, "wizard_edge_tags": None,
           "wizard_arch_count": 2, "aircraft_name_human_variants": None}
    schema.apply_finals(row)
    assert row["aircraft_name_final_variants"] == "Bell Helicopter 12a; Bell Helicopter 12b"
    row["aircraft_name_human_variants"] = " Nexus 4EX ;Nexus 6HX "
    schema.apply_finals(row)
    assert row["aircraft_name_final_variants"] == "Nexus 4EX; Nexus 6HX"


def test_variants_with_several_candidates_are_queued_under_name():
    gaz = [{"company_canonical": "Bell / Textron", "aircraft_name": "Nexus 4EX", "aka": "",
            "year_from": "2018", "year_to": "2030", "powertrain": "HybridElectric"},
           {"company_canonical": "Bell / Textron", "aircraft_name": "Nexus 6HX", "aka": "",
            "year_from": "2018", "year_to": "2030", "powertrain": "HybridElectric"}]
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta={**META, "first_claim": "An aircraft."},
        batch_meta={"company_canonical": "Bell / Textron"},
        gaz_hit=ai.match_gazetteer("Bell / Textron", "2020", gaz),
        wizard={"approved": True, "arch_count": 2, "edge_tags": [],
                "variants": [{"n": 1, "top_type": "TR"}, {"n": 2, "top_type": "SLC"}]},
        group={"aircraft_group": "Bell Helicopter 12", "aircraft_group_source": "wizard",
               "aircraft_group_note": None},
        takeoff_pred={"value": "VTOL", "source": "keyword", "confidence": 0.8,
                      "section": "Title", "quote": "VTOL"},
    )
    assert row["aircraft_name_variant_proposals"] == "Nexus 4EX; Nexus 6HX"
    assert row["name_review"] is True
    assert "assign them" in row["review_reason"]
    # once assigned, it leaves the queue
    row["aircraft_name_human_variants"] = "Nexus 4EX; Nexus 6HX"
    assert schema.review_flags(row)["name_review"] is False



# ─── the burden of proof is on NOT electric ──────────────────────────────────
# It is easy to show an aircraft is not electric (one committed sentence naming
# a turbine or piston engine as the propulsion) and nearly impossible to show it
# is. So every family is collected and the combustion statement decides.

ABS = "A vertical take-off and landing aircraft."
TK = {"value": "VTOL", "source": "keyword", "confidence": 0.8, "section": "Title", "quote": "VTOL"}


def _elec_row(body, **kw):
    meta = {"abstract": ABS, "description": body}
    pred = ai.classify_powertrain(ABS, body_text=body)
    row, _ = ai.build_identity_row(patent_id="US1", batch="Batch_01", meta=meta,
                                   powertrain_pred=pred, takeoff_pred=TK, **kw)
    return row


def test_a_stated_turbine_beats_electric_actuators():
    """The old first-match order called this BatteryElectric."""
    row = _elec_row("The rotor is driven by a turboshaft engine. Electric actuators move the flaps.")
    assert row["powertrain"] == "Turbine"
    assert (row["is_electric"], row["is_electric_source"]) == ("No", "keyword")
    assert "turboshaft" in row["powertrain_quote"]
    assert row["electric_review"] is True               # a machine never disapproves alone
    assert "confirm before disapproving" in row["review_reason"]


def test_two_families_stated_abstains_and_quotes_both():
    row = _elec_row("Lift rotors are driven by a piston engine. In another embodiment the "
                    "rotors are driven by electric motors fed by a battery pack.")
    assert row["powertrain"] == "Piston"
    assert row["powertrain_other"] == "BatteryElectric"
    assert "piston engine" in row["powertrain_quote"]
    assert "battery pack" in row["powertrain_other_quote"]
    assert row["is_electric"] == "Unknown" and row["is_electric_source"] is None
    assert row["electric_review"] is True
    assert "read both quotes" in row["review_reason"]


def test_prior_art_turbine_does_not_count_as_a_statement():
    row = _elec_row("Conventional VTOL aircraft use gas turbine engines. "
                    "The present invention uses electric motors powered by a battery.")
    assert row["powertrain"] == "BatteryElectric"
    assert (row["is_electric"], row["is_electric_source"]) == ("Yes", "keyword")
    assert row["powertrain_other"] is None
    assert row["electric_review"] is False


def test_a_hybrid_sentence_naming_its_parts_is_hybrid_not_a_hedge():
    row = _elec_row("A hybrid-electric powertrain: a turbogenerator charges the battery "
                    "pack that feeds the electric motors.")
    assert row["powertrain"] == "HybridElectric"
    assert row["is_electric"] == "Hybrid"
    assert row["electric_review"] is True               # not purely electric -> confirm


def test_nothing_stated_is_presumed_electric_and_not_queued():
    row = _elec_row("The wing has a leading edge and a trailing edge.")
    assert (row["is_electric"], row["is_electric_source"]) == ("Unknown", "presumed")
    assert row["electric_review"] is False
    assert "presumed electric" in row["review_reason"]


def test_presumption_never_overrides_evidence_or_a_company():
    assert electric_verdict("Turbine", "keyword", 0.65, stated=True, presume_electric=True) == ("No", "keyword")
    assert electric_verdict(None, None, None, company_all_electric=True, stated=False,
                            presume_electric=True) == ("Yes", "company")
    assert electric_verdict(None, None, None, stated=False, presume_electric=False) == ("Unknown", None)


def test_merge_keeps_presumed_and_company_sources(tmp_path):
    """A re-export must not recompute is_electric for rows the reviewer did not
    touch — that would throw away 'presumed' and 'company'."""
    out = tmp_path / "aircraft_identity_Batch_96.xlsx"
    row = _elec_row("The wing has a leading edge.")
    export_identity_excel([row], [], [], out, preserve_human=True, write_figures=False)
    export_identity_excel([row], [], [], out, preserve_human=True, write_figures=False)
    again = pd.read_excel(out, sheet_name="Identity", dtype=object).iloc[0]
    assert again["is_electric_source"] == "presumed"


# ─── a combustion mention must be a FIRM statement to count ──────────────────
# Sampled from the corpus on 2026-09-09: 7 of 8 "both families stated" rows were
# background prose or options. Asymmetric on purpose: the burden is on showing
# NOT electric, so only a firm combustion sentence decides.

@pytest.mark.parametrize("body", [
    "Fixed-wing aircraft, such as airplanes, are capable of flight using wings that generate "
    "lift responsive to the forward airspeed of the aircraft, which is generated by thrust from "
    "one or more jet engines or propellers.",
    "The power source 152 may include a gas turbine.",
    "Alternatively, or in combination with the electric motor, the motor may be a combustion "
    "engine, such as an internal combustion engine or a turbine engine.",
    "Recently, alongside aircraft with turboprop propulsion, solutions using electric "
    "motorisations have been developed.",
    "In other embodiments the rotors are driven by a piston engine.",
    "Unlike helicopters powered by turboshaft engines, the present aircraft is quiet.",
])
def test_a_hedged_combustion_mention_is_not_a_statement(body):
    fam = ai.detect_powertrain_families(ABS, body)
    comb = {k: v for k, v in fam.items() if k in ("Turbine", "Piston")}
    assert comb, "the family must still be FOUND (visible to the reviewer)"
    assert all(v["hedged"] for v in comb.values()), body


@pytest.mark.parametrize("body, family", [
    ("The rotor is driven by a turboshaft engine.", "Turbine"),
    ("wherein the engine is a gas turbine engine coupled to the main rotor gearbox.", "Turbine"),
    ("The aircraft is powered by a four-cylinder piston engine.", "Piston"),
    ("A turbojet engine provides the forward thrust.", "Turbine"),
])
def test_a_firm_combustion_statement_still_decides(body, family):
    row = _elec_row(body)
    assert row["powertrain"] == family
    assert row["is_electric"] == "No"


def test_background_jet_engines_no_longer_hide_an_electric_invention():
    """The Bell boilerplate + a firm electric statement: Yes, not a conflict."""
    row = _elec_row("Fixed-wing aircraft are capable of flight using wings, which is generated by "
                    "thrust from one or more jet engines or propellers. The propulsion assemblies of "
                    "the present aircraft each comprise an electric motor and a battery.")
    assert row["is_electric"] == "Yes"
    assert row["powertrain_other"] is None
    assert row["electric_review"] is False


def test_engine_plus_generator_is_a_hybrid_without_the_word():
    row = _elec_row("The eVTOL comprises rotors, motors, a battery, a generator and an engine "
                    "driving the generator.")
    assert row["powertrain"] == "HybridElectric"
    assert row["is_electric"] == "Hybrid"


def test_well_known_other_aircraft_is_prior_art():
    fam = ai.detect_powertrain_families(ABS, "Other well-known VTOL aircraft are aircraft using "
                                        "turbojet engine thrust to support the aircraft during takeoff.")
    assert fam["Turbine"]["hedged"] is True


# ─── per-variant answers ─────────────────────────────────────────────────────
# A patent describing two aircraft can describe one battery-electric and one
# hybrid. The patent-level answer covers every variant unless overridden, so a
# patent whose variants agree still takes one click.

from src.identity_excel import build_variants_sheet    # noqa: E402


def _multi(**kw):
    row = {"patent_id": "US1", "batch": "Batch_01", "company_canonical": "X",
           "wizard_approved": True, "wizard_arch_count": 2,
           "wizard_variant_types": "TR | SLC", "wizard_edge_tags": None,
           "aircraft_group": "X 3", "aircraft_name_human": None,
           "aircraft_name_human_variants": None,
           "is_electric": "Yes", "is_electric_human": None, "is_electric_human_variants": None,
           "takeoff_mode": "VTOL", "takeoff_human": None, "takeoff_human_variants": None,
           "uav_human": None, "uav_human_variants": None, "review_status": None}
    row.update(kw)
    schema.apply_finals(row)
    return row


def test_the_patent_answer_covers_every_variant():
    r = _multi(is_electric_human="Hybrid")
    assert r["is_electric_final"] == "Hybrid"
    assert r["is_electric_final_variants"] == "Hybrid; Hybrid"


def test_a_variant_can_disagree_with_the_patent():
    r = _multi(is_electric_human="Yes", is_electric_human_variants="Yes; Hybrid",
               takeoff_human_variants="VTOL; STOL")
    assert r["is_electric_final_variants"] == "Yes; Hybrid"
    assert r["takeoff_final_variants"] == "VTOL; STOL"
    assert r["is_electric_final"] == "Yes"        # the patent-level answer is untouched


def test_a_blank_variant_slot_falls_back_to_the_patent_answer():
    r = _multi(is_electric_human="Yes", is_electric_human_variants="; Hybrid")
    assert r["is_electric_final_variants"] == "Yes; Hybrid"


def test_a_single_aircraft_patent_has_no_variant_columns():
    r = _multi(wizard_arch_count=1, wizard_variant_types=None, is_electric_human="No")
    for col, _, _ in schema.VARIANT_RULES:
        assert r[col] is None


def test_variants_sheet_is_one_row_per_aircraft():
    import pandas as pd
    ident = pd.DataFrame([
        _multi(is_electric_human="Yes", is_electric_human_variants="Yes; Hybrid",
               aircraft_name_human="Nexus"),
        _multi(patent_id="US2", wizard_arch_count=1, wizard_variant_types=None,
               is_electric_human="No"),
    ])
    v = build_variants_sheet(ident)
    assert list(v.variant_id) == ["US1_arch1", "US1_arch2", "US2"]
    assert list(v.variant_n) == [1, 2, 1]
    assert list(v.is_primary) == [True, False, True]
    assert list(v.top_type) == ["TR", "SLC", None]
    assert list(v.is_electric_final) == ["Yes", "Hybrid", "No"]
    assert list(v.aircraft_name_final) == ["Nexus a", "Nexus b", "X 3"]


def test_variants_sheet_ships_in_the_workbook(tmp_path):
    out = tmp_path / "aircraft_identity_Batch_95.xlsx"
    row, ev = ai.build_identity_row(
        patent_id="US1", batch="Batch_95", meta=META,
        wizard={"approved": True, "arch_count": 2, "edge_tags": [],
                "variants": [{"n": 1, "top_type": "TR"}, {"n": 2, "top_type": "SLC"}]},
        group={"aircraft_group": "X 3", "aircraft_group_source": "wizard",
               "aircraft_group_note": None})
    export_identity_excel([row], ev, [], out, preserve_human=True, write_figures=False)
    v = pd.read_excel(out, sheet_name="Variants", dtype=object)
    assert list(v.variant_id) == ["US1_arch1", "US1_arch2"]


# ─── one spelling per aircraft name ──────────────────────────────────────────

def test_the_same_name_typed_in_two_casings_becomes_one():
    """The annotator typed "AERHART LLC" on the original and "Aerhart Llc" on
    its duplicate. Same aircraft, so one spelling — the most-used one."""
    wiz = {"P1": {"aircraft_name": "AERHART LLC", "duplicate_type": None, "duplicate_of": None},
           "P2": {"aircraft_name": "Aerhart Llc", "duplicate_type": "2", "duplicate_of": "P1"},
           "P3": {"aircraft_name": "AERHART LLC", "duplicate_type": None, "duplicate_of": None}}
    bm = {p: {"company_canonical": "Aerhart"} for p in wiz}
    idx = {p: {"app_year": "2021", "assignee": "AERHART LLC (US)"} for p in wiz}
    g = wl.assign_aircraft_groups(list(wiz), bm, idx, wiz)
    assert {v["aircraft_group"] for v in g.values()} == {"AERHART LLC"}


def test_a_duplicate_takes_its_originals_spelling_even_when_it_is_the_rarer_one():
    wiz = {"P1": {"aircraft_name": "Aerhart Llc", "duplicate_type": None, "duplicate_of": None},
           "P2": {"aircraft_name": "Aerhart Llc", "duplicate_type": None, "duplicate_of": None},
           "P3": {"aircraft_name": "AERHART LLC", "duplicate_type": "2", "duplicate_of": "P1"}}
    bm = {p: {"company_canonical": "Aerhart"} for p in wiz}
    idx = {p: {"app_year": "2021", "assignee": "AERHART LLC (US)"} for p in wiz}
    g = wl.assign_aircraft_groups(list(wiz), bm, idx, wiz)
    assert g["P3"]["aircraft_group"] == "Aerhart Llc"
    assert g["P3"]["aircraft_group_note"] is None      # same name, not a mismatch


# ─── a duplicate is the same aircraft: it inherits and is never queued ───────
# D2 = same aircraft AND same figures; D1 = same aircraft, re-drawn. Electric,
# take-off, UAV and the name are properties of the AIRCRAFT, so answering them
# on a duplicate is answering the same question twice. Only a D3 is different.

def _dup_rows():
    root = {"patent_id": "P1", "wizard_approved": True, "wizard_duplicate_type": None,
            "wizard_duplicate_of": None, "aircraft_name_final": "Nexus",
            "is_electric_final": "Hybrid", "takeoff_final": "VTOL", "uav_final": None,
            "aircraft_name_final_variants": None, "is_electric_final_variants": None,
            "takeoff_final_variants": None, "uav_final_variants": None,
            "aircraft_group_source": "wizard", "aircraft_group_note": None,
            "aircraft_name_in_text": "No", "aircraft_name_human": None,
            "is_electric": "Hybrid", "is_electric_human": None, "takeoff_mode": "VTOL",
            "takeoff_human": None, "uav_human": None, "uav_hint": None,
            "wizard_edge_tags": None}
    def child(pid, dtype, parent, **kw):
        r = dict(root, patent_id=pid, wizard_duplicate_type=dtype, wizard_duplicate_of=parent,
                 aircraft_name_final="own", is_electric_final="Yes", takeoff_final="STOL",
                 uav_final="UAVSimilar")
        r.update(kw)
        return r
    return [root, child("P2", "2", "P1"), child("P3", "1", "P1"),
            child("P4", "2", "P2"),                       # a chain: D2 of a D2
            child("P5", "3", "P1"),                       # a D3 keeps its own
            child("P6", "2", "P_ELSEWHERE")]              # root in another batch


def test_a_duplicate_inherits_every_final_from_the_chain_root():
    rows = schema.propagate_duplicate_finals(_dup_rows())
    by = {r["patent_id"]: r for r in rows}
    for pid in ("P2", "P3", "P4"):
        assert by[pid]["duplicate_root"] == "P1", pid
        assert by[pid]["is_electric_final"] == "Hybrid", pid
        assert by[pid]["aircraft_name_final"] == "Nexus", pid
        assert by[pid]["takeoff_final"] == "VTOL", pid
        assert "inherited from P1" in by[pid]["duplicate_root_note"], pid


def test_a_d3_keeps_its_own_answers():
    by = {r["patent_id"]: r for r in schema.propagate_duplicate_finals(_dup_rows())}
    assert by["P5"]["duplicate_root"] is None
    assert by["P5"]["is_electric_final"] == "Yes"


def test_a_root_in_another_batch_is_flagged_not_guessed():
    by = {r["patent_id"]: r for r in schema.propagate_duplicate_finals(_dup_rows())}
    assert by["P6"]["duplicate_root"] == "P_ELSEWHERE"
    assert "another batch" in by["P6"]["duplicate_root_note"]
    assert by["P6"]["is_electric_final"] == "Yes"          # untouched


def test_an_answer_typed_on_the_duplicate_itself_is_kept():
    rows = _dup_rows()
    rows[1]["is_electric_human"] = "No"
    by = {r["patent_id"]: r for r in schema.propagate_duplicate_finals(rows)}
    assert by["P2"]["is_electric_final"] == "Yes"           # not overwritten
    assert "kept" in by["P2"]["duplicate_root_note"]


@pytest.mark.parametrize("dtype, queued", [("1", False), ("2", False), ("3", True), (None, True)])
def test_only_a_d3_reaches_the_review_queue(dtype, queued):
    f = schema.review_flags({"wizard_approved": True, "wizard_duplicate_type": dtype,
                             "aircraft_group_source": "generated", "aircraft_group_note": None,
                             "aircraft_name_in_text": "No", "aircraft_name_human": None,
                             "is_electric": "Unknown", "is_electric_source": None,
                             "is_electric_human": None, "takeoff_mode": None,
                             "takeoff_human": None, "uav_human": None})
    assert bool(f["review_queue"]) is queued


# ─── which aircraft of a multi-variant original does a duplicate copy? ───────
# duplicateId names a PATENT. When that patent describes several aircraft the
# link does not say which one — 27 rows in this corpus. Only a real disagreement
# between the original's aircraft makes it a question worth asking.

def _root_with_variants(**kw):
    r = {"patent_id": "R", "wizard_approved": True, "wizard_duplicate_type": None,
         "wizard_duplicate_of": None, "wizard_arch_count": 3,
         "aircraft_name_final": "Nexus", "is_electric_final": "Yes",
         "takeoff_final": "VTOL", "uav_final": None,
         "aircraft_name_final_variants": "Nexus a; Nexus b; Nexus c",
         "is_electric_final_variants": "Yes; Yes; Yes",
         "takeoff_final_variants": "VTOL; VTOL; VTOL",
         "uav_final_variants": "; ; "}
    r.update(kw)
    return r


def _dup_of_root(**kw):
    d = {"patent_id": "D", "wizard_approved": True, "wizard_duplicate_type": "2",
         "wizard_duplicate_of": "R", "wizard_arch_count": 1,
         "aircraft_name_human": None, "is_electric_human": None,
         "takeoff_human": None, "uav_human": None, "duplicate_root_variant": None}
    d.update(kw)
    return d


def test_agreeing_aircraft_make_the_link_unambiguous():
    rows = schema.propagate_duplicate_finals([_root_with_variants(), _dup_of_root()])
    d = rows[1]
    assert d["duplicate_root_aircraft"] == 3
    assert d["duplicate_ambiguous"] is False
    assert "agree on every answer" in d["duplicate_root_note"]
    assert schema.review_flags(d)["review_queue"] is None


def test_disagreeing_aircraft_are_reported_but_never_queued():
    """The link names a PATENT, not one of its aircraft. That is a property of
    the wizard record, so it is reported (column + note + the CSV + a printed
    warning) rather than re-asked patent by patent in the review page."""
    root = _root_with_variants(is_electric_final_variants="Yes; Hybrid; Yes")
    d = schema.propagate_duplicate_finals([root, _dup_of_root()])[1]
    assert d["duplicate_ambiguous"] is True
    assert "DIFFER on is_electric" in d["duplicate_root_note"]
    assert schema.review_flags(d)["review_queue"] is None


def test_naming_the_aircraft_resolves_it():
    root = _root_with_variants(is_electric_final_variants="Yes; Hybrid; Yes")
    d = schema.propagate_duplicate_finals([root, _dup_of_root(duplicate_root_variant="b")])[1]
    assert d["is_electric_final"] == "Hybrid"
    assert d["aircraft_name_final"] == "Nexus b"
    assert "aircraft b of 3" in d["duplicate_root_note"]
    assert d["duplicate_ambiguous"] is False
    assert schema.review_flags(d)["review_queue"] is None


@pytest.mark.parametrize("pick", ["z", "d", "", "1", None])
def test_a_nonsense_variant_letter_is_ignored_not_obeyed(pick):
    root = _root_with_variants(is_electric_final_variants="Yes; Hybrid; Yes")
    d = schema.propagate_duplicate_finals([root, _dup_of_root(duplicate_root_variant=pick)])[1]
    assert d["is_electric_final"] == "Yes"          # the patent-level answer, not slot 26
    assert d["duplicate_ambiguous"] is True


def test_a_single_aircraft_original_asks_nothing():
    root = _root_with_variants(wizard_arch_count=1, aircraft_name_final_variants=None,
                               is_electric_final_variants=None, takeoff_final_variants=None,
                               uav_final_variants=None)
    d = schema.propagate_duplicate_finals([root, _dup_of_root()])[1]
    assert d["duplicate_root_aircraft"] is None
    assert d["duplicate_ambiguous"] is False
    assert d["duplicate_root_note"] == "answers inherited from R"



# ─── "not electric" is only half an answer ───────────────────────────────────
# A turbine or piston aircraft whose ARCHITECTURE matches an electric one still
# belongs in a design-space study. That is the wizard's ElectricSimilar edge
# tag, and it is asked as soon as the answer is "No".

def _q(**kw):
    base = {"wizard_approved": True, "wizard_duplicate_type": None,
            "aircraft_group_source": "wizard", "aircraft_group_note": None,
            "aircraft_name_in_text": "No", "aircraft_name_human": None,
            "is_electric": "Yes", "is_electric_source": "keyword", "is_electric_human": None,
            "electric_similar_human": None, "electric_similar_final": None,
            "takeoff_mode": "VTOL", "takeoff_human": None, "uav_hint": None,
            "uav_human": None, "wizard_edge_tags": None}
    base.update(kw)
    return schema.review_flags(base)


def test_answering_not_electric_asks_whether_it_is_still_architecturally_similar():
    assert _q(is_electric_human="No")["review_queue"] == "electric"


@pytest.mark.parametrize("answer", ["ElectricSimilar", "No"])
def test_the_follow_up_closes_the_row(answer):
    assert _q(is_electric_human="No", electric_similar_human=answer)["review_queue"] is None


@pytest.mark.parametrize("verdict", ["Yes", "Hybrid"])
def test_the_follow_up_is_not_asked_when_the_aircraft_is_electric(verdict):
    assert _q(is_electric_human=verdict)["review_queue"] is None


def test_an_existing_wizard_tag_answers_it_already():
    assert _q(is_electric_human="No", electric_similar_final="ElectricSimilar")["review_queue"] is None


def test_electric_similar_final_comes_from_your_cell_then_the_wizard_tag():
    row = {"aircraft_name_human": None, "aircraft_group": "X 1", "is_electric_human": None,
           "is_electric": "No", "takeoff_human": None, "takeoff_mode": "VTOL",
           "uav_human": None, "electric_similar_human": None,
           "wizard_edge_tags": "ElectricSimilar", "wizard_arch_count": 1}
    schema.apply_finals(row)
    assert row["electric_similar_final"] == "ElectricSimilar"      # the tag you set in the wizard
    row["electric_similar_human"] = "No"
    schema.apply_finals(row)
    assert row["electric_similar_final"] == "No"                   # your cell wins


def test_electric_similar_can_differ_per_aircraft():
    row = {"aircraft_name_human": None, "aircraft_group": "X 1", "is_electric_human": "No",
           "is_electric": "No", "takeoff_human": None, "takeoff_mode": "VTOL",
           "uav_human": None, "electric_similar_human": "No",
           "electric_similar_human_variants": "ElectricSimilar; No",
           "wizard_edge_tags": None, "wizard_arch_count": 2}
    schema.apply_finals(row)
    assert row["electric_similar_final_variants"] == "ElectricSimilar; No"


# ─── "I looked, and the sources cannot answer it" ────────────────────────────
# The wizard's own t1_humanUncertain / g1_humanUncertain convention, applied to
# the four decisions. It IS an answer — the field leaves the queue — but the
# flag travels with the data instead of a guess. 93 % of the approved figures
# are exterior line drawings, so for some patents this is the only true answer.

def _open_row(**kw):
    r = {"wizard_approved": True, "wizard_duplicate_type": None,
         "aircraft_group_source": "generated", "aircraft_group_note": None,
         "aircraft_name_in_text": "No", "aircraft_name_human": None,
         "is_electric": "Unknown", "is_electric_source": None, "is_electric_human": None,
         "takeoff_mode": None, "takeoff_source": None, "takeoff_human": None,
         "uav_hint": "UAV", "uav_human": None, "wizard_edge_tags": None}
    r.update(kw)
    return schema.review_flags(r)


def test_everything_open_is_queued():
    assert _open_row()["review_queue"] == "name+electric+takeoff+uav"


@pytest.mark.parametrize("col, gone", [
    ("name_uncertain", "electric+takeoff+uav"),
    ("electric_uncertain", "name+takeoff+uav"),
    ("takeoff_uncertain", "name+electric+uav"),
    ("uav_uncertain", "name+electric+takeoff"),
])
def test_marking_a_field_unanswerable_takes_it_out_of_the_queue(col, gone):
    assert _open_row(**{col: True})["review_queue"] == gone


@pytest.mark.parametrize("value", [True, "TRUE", "true", "True", 1, "1", "yes"])
def test_the_flag_survives_a_round_trip_through_excel(value):
    """Excel gives a boolean back as TRUE/True/1 depending on the writer."""
    assert _open_row(electric_uncertain=value)["electric_review"] is False


@pytest.mark.parametrize("value", [None, "", False, "FALSE", "false", 0, "nan"])
def test_an_unset_flag_leaves_the_field_open(value):
    assert _open_row(electric_uncertain=value)["electric_review"] is True


def test_all_four_unanswerable_empties_the_queue():
    f = _open_row(name_uncertain=True, electric_uncertain=True,
                  takeoff_uncertain=True, uav_uncertain=True)
    assert f["review_queue"] is None


def test_the_flags_are_human_columns_and_survive_a_reexport(tmp_path):
    assert set(schema.UNCERTAIN_COLUMNS.values()) <= set(schema.HUMAN_COLUMNS)
    assert set(schema.UNCERTAIN_COLUMNS.values()) <= set(ai.IDENTITY_COLUMNS)
    out = tmp_path / "aircraft_identity_Batch_94.xlsx"
    row, ev = ai.build_identity_row(patent_id="US1", batch="Batch_94", meta=META,
                                    wizard={"approved": True}, group={"aircraft_group": "X 1"})
    export_identity_excel([row], ev, [], out, preserve_human=True, write_figures=False)
    df = pd.read_excel(out, sheet_name="Identity", dtype=object)
    df.loc[0, "electric_uncertain"] = True
    df.loc[0, "takeoff_uncertain"] = True
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Identity", index=False)
    export_identity_excel([row], ev, [], out, preserve_human=True, write_figures=False)
    again = pd.read_excel(out, sheet_name="Identity", dtype=object).iloc[0]
    assert bool(again["electric_uncertain"]) is True
    assert bool(again["takeoff_uncertain"]) is True
    assert again["electric_review"] in (False, "False", 0)


# ─── the Excel round trip ────────────────────────────────────────────────────
# An empty cell read back from a workbook is float('nan'), and bool(nan) is
# TRUE. A plain truthiness test therefore flags every blank row: the first time
# the reviewed workbooks were re-read this put 696 patents in the queue instead
# of 356. review_flags goes through _val() for exactly this reason.

NAN = float("nan")


def test_blank_cells_from_excel_do_not_invent_work():
    """Every optional field empty, as pandas hands them back."""
    f = schema.review_flags({
        "wizard_approved": True, "wizard_duplicate_type": NAN,
        "aircraft_group_source": "wizard", "aircraft_group_note": NAN,
        "aircraft_name_in_text": NAN, "aircraft_name_human": NAN,
        "aircraft_name_human_variants": NAN, "aircraft_name_variant_proposals": NAN,
        "is_electric": "Yes", "is_electric_source": "keyword", "is_electric_human": NAN,
        "electric_similar_human": NAN, "electric_similar_final": NAN,
        "takeoff_mode": "VTOL", "takeoff_source": "keyword", "takeoff_human": NAN,
        "uav_hint": NAN, "uav_human": NAN, "wizard_edge_tags": NAN,
    })
    assert f["review_queue"] is None, f


def test_an_empty_takeoff_cell_is_still_an_open_question():
    """The opposite error: NaN is not in ('', None, 'STOL', ...) either, so a
    membership test without _val() silently DROPS unknown take-off rows."""
    f = schema.review_flags({
        "wizard_approved": True, "wizard_duplicate_type": NAN,
        "aircraft_group_source": "wizard", "aircraft_group_note": NAN,
        "aircraft_name_in_text": NAN, "aircraft_name_human": NAN,
        "is_electric": "Yes", "is_electric_source": "keyword", "is_electric_human": NAN,
        "takeoff_mode": NAN, "takeoff_source": NAN, "takeoff_human": NAN,
        "uav_hint": NAN, "uav_human": NAN, "wizard_edge_tags": NAN,
    })
    assert f["takeoff_review"] is True
    assert f["review_queue"] == "takeoff"


def test_the_queue_is_identical_before_and_after_a_workbook_round_trip(tmp_path):
    """The real guarantee: rebuilding from the exported sheet must reproduce the
    same queue the notebook computed, or a re-import silently changes the work."""
    rows = []
    for i, kw in enumerate([
        {"uav_pred": {"value": "UAV", "source": "keyword", "confidence": 0.8,
                      "section": "Abstract", "quote": "an unmanned aerial vehicle"}},
        {"powertrain_pred": {"value": "Turbine", "source": "keyword", "confidence": 0.8,
                             "families": {"Turbine": {"hedged": False}}}},
        {"takeoff_pred": {"value": "VTOL", "source": "keyword", "confidence": 0.8,
                          "section": "Title", "quote": "VTOL"}},
    ]):
        r, _ = ai.build_identity_row(patent_id=f"US{i}", batch="Batch_93", meta=META,
                                     wizard={"approved": True}, group={"aircraft_group": f"X {i}"},
                                     **kw)
        rows.append(r)
    before = {r["patent_id"]: r["review_queue"] for r in rows}

    out = tmp_path / "aircraft_identity_Batch_93.xlsx"
    export_identity_excel(rows, [], [], out, preserve_human=True, write_figures=False)
    back = pd.read_excel(out, sheet_name="Identity", dtype=object).to_dict("records")
    after = {r["patent_id"]: schema.review_flags(r)["review_queue"] for r in back}
    assert after == before, {k: (before[k], after[k]) for k in before if before[k] != after[k]}
