"""
test_patent_maturity.py — unit tests for src/patent_maturity.py (Stage 03a's
legal-stage + citation pass) and for the blade-count extraction that lives in
src/aircraft_identity.py.

Runs without a GPU, SBERT or the storage volume: every function under test is
deterministic.

The two failures that would be invisible
----------------------------------------
  1. **Ranking on raw forward citations.** A 2015 patent has had a decade to
     accumulate citations and a 2023 one has had two years, and eVTOL filing
     volume rose steeply over that window — so raw counts sort the corpus by age
     and call the result impact. The percentile tests pin that ranking runs on
     the age-normalised figure and that a young, densely-cited patent can beat
     an old, thinly-cited one.
  2. **Blade counts attached to the wrong propulsor.** "five-bladed lift rotors
     and a three-bladed cruise propeller" is the shape that matters for eVTOLs,
     and a direction-blind or clause-blind search silently tags both counts with
     the same role rather than failing.

Run: pytest tests/test_patent_maturity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import patent_maturity as pm      # noqa: E402
from src import aircraft_identity as ai    # noqa: E402


# ─── Kind codes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pid, office, kind", [
    ("US2022267016A1", "US", "A1"),
    ("US11524776B2",   "US", "B2"),
    ("WO2021123456A1", "WO", "A1"),
    ("EP3838752B1",    "EP", "B1"),
    ("CN112124569A",   "CN", "A"),
    ("CN112124569B",   "CN", "B"),
])
def test_parse_kind_code(pid, office, kind):
    parsed = pm.parse_kind_code(pid)
    assert parsed["office"] == office
    assert parsed["kind"] == kind


def test_parse_kind_code_handles_junk():
    for junk in ("", None, "not-a-number"):
        assert pm.parse_kind_code(junk)["kind"] is None


@pytest.mark.parametrize("pid, expected", [
    ("US2022267016A1", "Application"),
    ("US11524776B2",   "Granted"),
    ("EP3838752B1",    "Granted"),
    ("EP3838752A1",    "Application"),
    ("CN112124569B",   "Granted"),
    ("CN112124569A",   "Application"),
    ("JP2021123456A",  "Application"),
])
def test_legal_stage_from_kind_code(pid, expected):
    stage = pm.legal_stage_for(pid)
    assert stage["value"] == expected
    assert stage["source"] == "kind_code"


def test_wo_is_never_granted():
    """A PCT publication is an international APPLICATION by definition — there
    is no granted WO document, whatever the kind code looks like."""
    for pid in ("WO2021123456A1", "WO2019876543A2", "WO2020111111B1"):
        assert pm.legal_stage_for(pid)["value"] == "Application"


def test_bare_letter_is_office_dependent():
    """'B' is granted in CN and JP; 'A' is granted nowhere. Reading the letter
    without the office would get half the corpus wrong."""
    assert pm.legal_stage_for("CN112124569B")["value"] == "Granted"
    assert pm.legal_stage_for("JP6879865B")["value"] == "Granted"
    assert pm.legal_stage_for("CN112124569A")["value"] == "Application"
    assert pm.legal_stage_for("JP2021123456A")["value"] == "Application"


def test_unknown_kind_code_is_unknown_not_a_guess():
    stage = pm.legal_stage_for("XX12345Q7")
    assert stage["value"] == "Unknown"
    assert stage["confidence"] == 0.0


def test_legal_status_column_wins_over_kind_code():
    """A documented status beats an inferred one — and source says which."""
    stage = pm.legal_stage_for("US2022267016A1", "Granted")
    assert stage["value"] == "Granted"
    assert stage["source"] == "legal_status"
    assert stage["confidence"] > pm.legal_stage_for("US2022267016A1")["confidence"]


def test_lapsed_grant_is_still_granted_but_not_active():
    """A lapsed patent cleared examination; that is different from never having
    been granted, so the two facts are separate columns."""
    stage = pm.legal_stage_for("US11524776B2", "Lapsed")
    assert stage["value"] == "Granted"
    assert stage["active"] is False


def test_abandoned_application_is_application_and_inactive():
    stage = pm.legal_stage_for("US2022267016A1", "Abandoned")
    assert stage["value"] == "Application"
    assert stage["active"] is False


def test_empty_legal_status_falls_through_to_kind_code():
    for blank in ("", "   ", "nan", "-", None):
        stage = pm.legal_stage_for("US11524776B2", blank)
        assert stage["value"] == "Granted"
        assert stage["source"] == "kind_code"


# ─── Citations ───────────────────────────────────────────────────────────────

INDEX = {
    "US2019111111A1": {"assignee": "JOBY AERO INC (US)", "pub_year": "2019",
                       "app_year": "2017",
                       "backward_cites": [], "forward_cites": ["US2021333333A1", "US9999999B2"]},
    "US2020222222A1": {"assignee": "JOBY AERO INC (US)", "pub_year": "2020",
                       "app_year": "2018",
                       "backward_cites": ["US2019111111A1"], "forward_cites": []},
    "US2021333333A1": {"assignee": "ARCHER AVIATION INC (US)", "pub_year": "2021",
                       "app_year": "2019",
                       "backward_cites": ["US2019111111A1", "US8888888B2"],
                       "forward_cites": []},
}


def test_citation_counts_and_in_corpus_split():
    summary = pm.citation_summary("US2019111111A1", INDEX)
    assert summary["forward_citations"] == 2
    # Only one of the two forward cites is another patent in this corpus.
    assert summary["forward_citations_in_corpus"] == 1


def test_self_citation_detected_via_canonical_company():
    """Joby citing Joby is a sustained programme; Archer citing Joby is not."""
    assert pm.citation_summary("US2020222222A1", INDEX)["self_citations_in_corpus"] == 1
    assert pm.citation_summary("US2021333333A1", INDEX)["self_citations_in_corpus"] == 0


def test_citation_count_column_beats_the_id_list():
    """A PatSeer count column reflects the full citation set; the exported ID
    list is sometimes truncated."""
    index = {"US1": {**INDEX["US2019111111A1"], "fwd_cite_count_col": "57"}}
    summary = pm.citation_summary("US1", index)
    assert summary["forward_citations"] == 57
    assert summary["forward_citations_source"] == "patseer_column"


def test_citation_summary_of_unknown_patent_is_zeros_not_an_error():
    summary = pm.citation_summary("NOT_IN_INDEX", INDEX)
    assert summary["forward_citations"] == 0
    assert summary["self_citations_in_corpus"] == 0


# ─── Maturity rows and age normalisation ─────────────────────────────────────

def test_forward_citations_per_year_normalises_by_age():
    row = pm.build_maturity_row("US2019111111A1", INDEX, reference_year=2025)
    assert row["years_since_publication"] == 6
    assert row["forward_citations_per_year"] == pytest.approx(2 / 6, abs=1e-3)


def test_same_year_publication_does_not_divide_by_zero():
    index = {"US1": {"assignee": "X", "pub_year": "2025", "app_year": "2024",
                     "backward_cites": [], "forward_cites": ["A", "B"]}}
    row = pm.build_maturity_row("US1", index, reference_year=2025)
    assert row["years_since_publication"] == 1
    assert row["forward_citations_per_year"] == 2.0


def test_grant_lag_only_for_granted_patents():
    index = {"US11524776B2": {"assignee": "X", "pub_year": "2022", "app_year": "2019",
                              "grant_date": "2022-12-13",
                              "backward_cites": [], "forward_cites": []},
             "US2022267016A1": {"assignee": "X", "pub_year": "2022", "app_year": "2019",
                                "backward_cites": [], "forward_cites": []}}
    assert pm.build_maturity_row("US11524776B2", index)["grant_lag_years"] == 3
    assert pm.build_maturity_row("US2022267016A1", index)["grant_lag_years"] is None


def test_maturity_row_columns_match_the_schema():
    row = pm.build_maturity_row("US2019111111A1", INDEX)
    assert set(row) == set(pm.MATURITY_COLUMNS)


# ─── Corpus percentiles ──────────────────────────────────────────────────────

def _row(per_year, stage="Application"):
    return {"forward_citations_per_year": per_year, "legal_stage": stage}


def test_uncited_rows_get_their_own_tier():
    rows = pm.add_corpus_percentiles([_row(0.0), _row(0.0), _row(5.0)])
    assert rows[0]["impact_tier"] == "Uncited"
    assert rows[0]["forward_citation_percentile"] == 0.0


def test_percentiles_ignore_uncited_rows():
    """With 90 uncited rows and 10 cited ones, including the zeros would put the
    median inside the block of zeros, so 'Medium' would mean 'cited once'."""
    rows = [_row(0.0) for _ in range(90)] + [_row(float(i)) for i in range(1, 11)]
    pm.add_corpus_percentiles(rows)
    cited = [r for r in rows if r["forward_citations_per_year"] > 0]
    assert [r["impact_tier"] for r in cited].count("High") >= 1
    # The single least-cited of the cited rows must not be called Medium.
    assert min(cited, key=lambda r: r["forward_citations_per_year"])["impact_tier"] == "Low"


def test_young_dense_patent_outranks_old_thin_one():
    """The whole point of normalising: 6 citations in 2 years beats 10 in 20."""
    young = {"forward_citations": 6, "forward_citations_per_year": 3.0,
             "legal_stage": "Application"}
    old = {"forward_citations": 10, "forward_citations_per_year": 0.5,
           "legal_stage": "Application"}
    pm.add_corpus_percentiles([young, old] + [_row(float(i)) for i in range(1, 9)])
    assert young["forward_citation_percentile"] > old["forward_citation_percentile"]
    assert old["forward_citations"] > young["forward_citations"]   # raw count disagrees


@pytest.mark.parametrize("stage, per_year, expected", [
    ("Granted",     9.0, "Established"),
    ("Granted",     0.0, "Granted"),
    ("Application", 9.0, "Active"),
    ("Application", 0.0, "Filed"),
    ("Unknown",     9.0, "Unknown"),
])
def test_maturity_tier_combines_both_axes(stage, per_year, expected):
    rows = [_row(per_year, stage)] + [_row(float(i)) for i in range(1, 9)]
    pm.add_corpus_percentiles(rows)
    assert rows[0]["maturity_tier"] == expected


def test_application_that_is_cited_is_distinguishable():
    """An application already being cited is a live, watched filing — the case
    a single combined score would hide."""
    rows = [_row(9.0, "Application"), _row(0.0, "Application")]
    rows += [_row(float(i)) for i in range(1, 9)]
    pm.add_corpus_percentiles(rows)
    assert rows[0]["maturity_tier"] == "Active"
    assert rows[1]["maturity_tier"] == "Filed"


def test_percentiles_on_an_all_uncited_corpus_do_not_crash():
    rows = pm.add_corpus_percentiles([_row(0.0) for _ in range(5)])
    assert all(r["impact_tier"] == "Uncited" for r in rows)
    assert all(r["maturity_tier"] == "Filed" for r in rows)


# ─── Blade counts ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("An aircraft having five-bladed lift rotors and a three-bladed cruise propeller.",
     {(5, "Lift"), (3, "Cruise")}),
    ("The lift rotors each have five blades, while the pusher propeller has three blades.",
     {(5, "Lift"), (3, "Cruise")}),
    ("Each of the eight lift fans has five blades and the tractor propeller has two blades.",
     {(5, "Lift"), (2, "Cruise")}),
    ("A two-bladed main rotor and a four-bladed tail rotor.",
     {(2, "Main"), (4, "Tail")}),
    ("A three-bladed proprotor for a tiltrotor aircraft.", {(3, "Tilt")}),
    # Plural role nouns: "proprotors" failed the \b-terminated pattern and fell
    # through to Unspecified, losing the role on exactly the tiltrotor patents
    # the corpus is full of.
    ("Three-bladed proprotors driven by electric motors.", {(3, "Tilt")}),
    ("The tilting propulsors each have four blades.", {(4, "Tilt")}),
    # An UNQUALIFIED "propeller" stays Unspecified. Reading it as Cruise would
    # assume any bare propeller is a cruise propulsor, and on an eVTOL a lift
    # propulsor is routinely called a propeller too — a wrong role is worse
    # than an honest blank, because it lands in a per-role column.
    ("The propeller has four blades.", {(4, "Unspecified")}),
])
def test_blade_counts_and_roles(text, expected):
    got = {(b["count"], b["role"]) for b in ai.extract_blade_counts(text)}
    assert got == expected


def test_blade_role_respects_direction_and_clause():
    """Both halves of the hard case in one assertion: the adjectival form points
    forward, the predicative form points backward, and neither crosses the
    clause boundary."""
    text = ("A five-bladed lift rotor is provided, while the cruise propeller "
            "has three blades.")
    got = {(b["count"], b["role"]) for b in ai.extract_blade_counts(text)}
    assert got == {(5, "Lift"), (3, "Cruise")}


def test_blade_reference_numerals_rejected():
    """'blades 14' is a reference numeral. Requiring the number to be BOUND to
    the word is what keeps it out."""
    text = "The propeller comprises a plurality of blades 14 mounted to the hub 12."
    assert ai.extract_blade_counts(text) == []


def test_blade_non_count_uses_rejected():
    for text in ("Blade pitch is varied by the blade 12 root actuator.",
                 "Blade element momentum theory is used to size the rotor.",
                 "The blade root is attached to the hub."):
        assert ai.extract_blade_counts(text) == [], text


def test_blade_counts_outside_plausible_range_rejected():
    """A count of 1 or 40 is a misparse, not a propeller."""
    assert ai.extract_blade_counts("a 40-blade assembly") == []
    assert ai.extract_blade_counts("a 1-bladed rotor") == []


def test_blade_summary_prefers_the_lift_rotor():
    """An eVTOL is characterised by its lift rotors, so that is the primary
    figure — but the per-role detail is what makes the column useful."""
    blades = ai.extract_blade_counts(
        "five-bladed lift rotors and a three-bladed cruise propeller")
    summary = ai.summarise_blade_counts(blades)
    assert summary["blades_primary"] == 5
    assert "5 (Lift)" in summary["blades_all"]
    assert "3 (Cruise)" in summary["blades_all"]
    assert summary["blades_min"] == 3 and summary["blades_max"] == 5
    assert summary["blades_distinct"] == 2


def test_blade_summary_empty():
    summary = ai.summarise_blade_counts([])
    assert summary["blades_primary"] is None
    assert summary["blade_count_source"] is None
    assert set(summary) == set(ai.BLADE_COLUMNS)


def test_blade_counts_reach_the_identity_row():
    row, evidence = ai.build_identity_row(
        patent_id="US1", batch="Batch_01",
        meta={"assignee": "JOBY AERO INC (US)", "app_year": "2021"},
        blade_hits=ai.extract_blade_counts(
            "five-bladed lift rotors and a three-bladed cruise propeller"),
    )
    assert row["blades_primary"] == 5
    assert row["blades_distinct"] == 2
    # Every hit keeps the sentence it came from, in the Evidence sheet.
    assert any(e["field"].startswith("blades[") for e in evidence)


# ─── Schema integration ──────────────────────────────────────────────────────

def test_all_new_columns_are_in_the_identity_schema():
    for col in list(pm.MATURITY_COLUMNS) + list(ai.BLADE_COLUMNS):
        assert col in ai.IDENTITY_COLUMNS, f"{col} would be dropped by the export"


def test_attach_maturity_fills_every_maturity_column():
    row, _ = ai.build_identity_row(
        patent_id="US2019111111A1", batch="Batch_01", meta=INDEX["US2019111111A1"])
    ai.attach_maturity(row, pm.build_maturity_row("US2019111111A1", INDEX,
                                                  reference_year=2025))
    assert row["legal_stage"] == "Application"
    assert row["kind_code"] == "A1"
    assert row["forward_citations"] == 2
    assert row["forward_citations_per_year"] is not None


def test_attach_maturity_adds_no_review_reasons():
    """Being young or uncited is a fact about a patent, not something a reviewer
    can fix — flagging it would bury the rows that do need a human."""
    row, _ = ai.build_identity_row(
        patent_id="US2019111111A1", batch="Batch_01", meta=INDEX["US2019111111A1"])
    before = row["review_reason"]
    ai.attach_maturity(row, pm.build_maturity_row("US2019111111A1", INDEX))
    assert row["review_reason"] == before
