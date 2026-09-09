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
    ("Pure UAV — Pure UAV",                        {}),
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
    ("electric", {"is_electric": "Unknown", "is_electric_human": "No"}),
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
    """The proposal must stay readable in its own column, with a reason saying why
    is_electric would not use it."""
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=META,
        powertrain_pred={"value": "Piston", "source": "sbert", "confidence": 0.30},
        takeoff_pred=tc.classify_takeoff(META),
    )
    assert row["powertrain"] == "Piston"            # proposal kept
    assert row["powertrain_confidence"] == 0.30
    assert row["is_electric"] == "Unknown"          # verdict withheld
    assert "low-confidence sbert guess (Piston)" in row["review_reason"]
    assert row["is_electric_final"] == "Unknown"


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


def test_a_hedged_row_lands_in_the_electric_queue_with_its_quote():
    meta = {"abstract": "An aircraft having a fuselage.",
            "description": "A drive unit may include an electric motor or an engine."}
    pred = ai.classify_powertrain(meta["abstract"], body_text=meta["description"])
    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01", meta=meta, powertrain_pred=pred,
        takeoff_pred={"value": "VTOL", "source": "keyword", "confidence": 0.8,
                      "section": "Title", "quote": "VTOL"},
    )
    assert row["powertrain"] == "BatteryElectric"      # visible
    assert row["is_electric"] == "Unknown"             # not a verdict
    assert row["electric_review"] is True              # queued
    assert "electric" in row["review_queue"]


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
