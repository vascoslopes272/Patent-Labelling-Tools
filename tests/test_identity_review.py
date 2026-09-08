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


def test_d3_gets_a_variant_letter(groups):
    assert groups["P3"]["aircraft_group"] == "Bell Helicopter 12a"
    assert groups["P3"]["aircraft_group_source"] == "generated_D3_variant"


def test_generated_number_uses_the_annotators_prefix_and_never_collides(groups):
    """The annotator wrote 'Bell Helicopter', not 'Bell / Textron', and used 9
    and 12 — the generated one must be 13 under the same prefix."""
    assert groups["P4"]["aircraft_group"] == "Bell Helicopter 13"
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
    # a backup of the edited file was taken before overwriting
    assert list(tmp_path.glob("aircraft_identity_Batch_99.BACKUP_*.xlsx"))


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
