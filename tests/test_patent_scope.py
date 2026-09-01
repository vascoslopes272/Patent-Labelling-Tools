"""
test_patent_scope.py — unit tests for src/patent_scope.py (Stage 03a's
scope / architecture / specificity pass).

Runs without a GPU, without SBERT weights and without the storage volume: every
test exercises either a deterministic pass (claim-preamble keywords, G1 keyword
families, hedging density, figure-view rules, the specificity arithmetic) or the
`sbert_model=None` degradation path.

The failure that matters most
-----------------------------
The gazetteer in aircraft_identity.py matches on COMPANY. Without this module, a
Joby patent on a motor bearing is labelled `aircraft_name = S4` at confidence
0.95, and every statistic grouped by aircraft silently inherits that error.
`aircraft_link` is the column that separates "this patent's figures show the S4"
from "Joby filed this, and Joby makes the S4" — so the tests below pin that a
gazetteer-sourced name can NEVER reach `Depicted` on its own, and that a
component-level patent is never read as aircraft-specific.

Run: pytest tests/test_patent_scope.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import patent_scope as ps   # noqa: E402


# ─── Taxonomies are reused, not restated ─────────────────────────────────────

def test_taxonomies_are_the_pipelines_own():
    """A label emitted here must mean exactly what it means in the HTML wizard
    and in ml_predict_labels_<batch>.xlsx. Restating the vocabulary would let
    the two drift silently, which is the failure tests/test_taxonomy_alignment
    exists to prevent elsewhere."""
    from src.reviewer import _T1_SCOPE_DEFS, _T1_FIELD_DEFS, _G1_TOP_TYPE_DEFS

    assert ps.SCOPE_DEFS is _T1_SCOPE_DEFS
    assert ps.FIELD_DEFS is _T1_FIELD_DEFS
    assert ps.ARCHITECTURE_DEFS is _G1_TOP_TYPE_DEFS


def test_every_architecture_code_has_a_readable_label():
    """architecture_primary_label is what goes in a thesis table; a missing
    entry would put a bare two-letter code there instead."""
    assert set(ps.ARCHITECTURE_LABELS) == set(ps.ARCHITECTURE_DEFS)


# ─── Granularity ─────────────────────────────────────────────────────────────

def test_scope_component_claim_preamble():
    """The canonical component claim: '<part> for an aircraft'. SBERT reads this
    as 'about an aircraft' because it is — the giveaway is the preamble shape."""
    text = "A bearing assembly for an aircraft electric propulsion motor."
    pred = ps.classify_scope(text, None)
    assert pred["value"] == "Component-Level Generic"
    assert pred["source"] == "keyword"


def test_scope_whole_aircraft_claim_preamble():
    text = ("An aircraft comprising a fuselage, a wing extending from the fuselage, "
            "and a plurality of rotors mounted to booms.")
    pred = ps.classify_scope(text, None)
    assert pred["value"] == "Whole Aircraft Architecture"
    assert pred["source"] == "keyword"


def test_scope_subsystem_enabler():
    text = "A tilt mechanism for rotating a nacelle between hover and cruise positions."
    assert ps.classify_scope(text, None)["value"] == "Architectural Subsystem Enabler"


def test_scope_method_claim_is_subsystem():
    text = "A method for controlling the transition of a vertical takeoff aircraft."
    assert ps.classify_scope(text, None)["value"] == "Architectural Subsystem Enabler"


def test_scope_component_rule_beats_whole_aircraft_rule():
    """A component claim almost always also names the aircraft it goes in, so
    the ordering in _SCOPE_KEYWORD_RULES is what stops a false whole-aircraft
    reading."""
    text = ("A rotor hub assembly for an aircraft, the aircraft comprising a "
            "fuselage and a wing.")
    assert ps.classify_scope(text, None)["value"] == "Component-Level Generic"


def test_scope_empty_and_no_sbert():
    assert ps.classify_scope("", None)["value"] is None
    assert ps.classify_scope(None, None)["value"] is None
    # Nothing keyword-detectable and no model -> no guess, rather than a wrong one.
    assert ps.classify_scope("Some unrelated prose about weather.", None)["value"] is None


# ─── Architectures present ───────────────────────────────────────────────────

def test_architecture_single_named():
    arch = ps.architectures_present(
        "A tiltrotor aircraft in which the nacelles tilt to transition.", None)
    assert arch["primary"] == "TP"
    assert arch["primary_label"] == "Tilt-Propulsor"
    assert arch["count"] == 1
    assert arch["pure"] is True


def test_architecture_enumeration_is_detected():
    """The signature of an illustrative patent: it lists the architectures its
    component could be fitted to, rather than describing one."""
    text = ("The invention may be applied to a multirotor aircraft, a tiltrotor "
            "aircraft, or a lift plus cruise aircraft, and also to a helicopter.")
    arch = ps.architectures_present(text, None)
    assert arch["count"] >= ps.ARCH_COUNT_GENERIC
    assert arch["pure"] is False
    assert set(arch["all"]) >= {"MR", "TP", "SLC"}


def test_architecture_primary_is_first_in_all():
    text = "A tiltrotor aircraft, which may also be embodied as a multirotor."
    arch = ps.architectures_present(text, None)
    assert arch["all"][0] == arch["primary"]


def test_architecture_labels_are_readable():
    arch = ps.architectures_present("a multirotor aircraft with distributed rotors", None)
    assert "Multirotor" in arch["all_labels"]


def test_architecture_empty_text():
    arch = ps.architectures_present("", None)
    assert arch["count"] == 0 and arch["pure"] is None and arch["primary"] is None


# ─── Hedging density ─────────────────────────────────────────────────────────

def test_generic_language_high_density():
    text = (("In some embodiments the component may be used with any suitable "
             "aircraft, such as but not limited to various configurations, and "
             "may optionally be alternatively arranged. ") * 4)
    score = ps.generic_language_score(text)
    assert score["level"] == "high"
    assert score["density"] >= ps.GENERIC_DENSITY_HIGH


def test_generic_language_low_density():
    text = ("The aircraft has six rotors mounted on three booms. " * 12 +
            "Each rotor is driven by a dedicated electric motor. " * 8)
    assert ps.generic_language_score(text)["level"] == "low"


def test_generic_language_short_text_is_unknown():
    """Density over two sentences is noise; calling it 'low' would make every
    abstract-only patent look specific."""
    assert ps.generic_language_score("An aircraft with rotors.")["level"] == "unknown"
    assert ps.generic_language_score("")["level"] == "unknown"


# ─── Figure views ────────────────────────────────────────────────────────────

DESC = (
    "FIG. 1 is a perspective view of an aircraft according to an embodiment. "
    "FIG. 2 is a side elevation view of the aircraft in a hover configuration. "
    "FIG. 3 is an enlarged view of the tilt mechanism of FIG. 2. "
    "FIG. 4 is a cross-sectional view taken along line A-A. "
    "FIG. 5 is a block diagram of the flight control system."
)


def test_split_drawing_lines():
    lines = ps.split_drawing_lines(DESC)
    assert [entry["fig"] for entry in lines] == ["1", "2", "3", "4", "5"]
    assert "perspective view" in lines[0]["text"]


def test_split_drawing_lines_empty():
    assert ps.split_drawing_lines("") == []
    assert ps.split_drawing_lines(None) == []
    assert ps.split_drawing_lines("No figures are described here.") == []


def test_figure_views_classified():
    views = {f["fig"]: f["view"] for f in ps.classify_figure_views(DESC, None)}
    assert views["1"] == "WholeAircraft"
    assert views["2"] == "WholeAircraft"
    assert views["3"] == "DetailSection"
    assert views["4"] == "DetailSection"
    assert views["5"] == "Diagram"


def test_diagram_rule_beats_aircraft_mention():
    """'a block diagram of the propulsion system of an aircraft' contains the
    word aircraft and must not be read as a view of one."""
    desc = "FIG. 7 is a block diagram of the propulsion system of an aircraft."
    assert ps.classify_figure_views(desc, None)[0]["view"] == "Diagram"


def test_figure_summary_counts():
    summary = ps.summarise_figure_views(ps.classify_figure_views(DESC, None))
    assert summary["figures_total"] == 5
    assert summary["figures_whole_aircraft"] == 2
    assert summary["figures_detail"] == 2
    assert summary["figures_diagram"] == 1
    assert summary["whole_aircraft_share"] == pytest.approx(0.4)


def test_figure_summary_empty():
    summary = ps.summarise_figure_views([])
    assert summary["figures_total"] == 0
    assert summary["whole_aircraft_share"] is None


# ─── Specificity ─────────────────────────────────────────────────────────────

WHOLE = {"value": "Whole Aircraft Architecture", "confidence": 0.8}
SUBSYS = {"value": "Architectural Subsystem Enabler", "confidence": 0.8}
COMPONENT = {"value": "Component-Level Generic", "confidence": 0.8}

ONE_ARCH = {"count": 1, "pure": True}
MANY_ARCH = {"count": 4, "pure": False}

LOW_HEDGE = {"level": "low", "density": 0.5}
HIGH_HEDGE = {"level": "high", "density": 5.0}

FIGS_AIRCRAFT = {"figures_total": 6, "figures_whole_aircraft": 4}
FIGS_NONE = {"figures_total": 6, "figures_whole_aircraft": 0}


def test_specificity_whole_aircraft_is_specific():
    result = ps.assess_specificity(WHOLE, ONE_ARCH, LOW_HEDGE, FIGS_AIRCRAFT)
    assert result["value"] == "SpecificAircraft"
    assert result["score"] >= ps.SPECIFIC_THRESHOLD


def test_specificity_component_patent_is_illustrative():
    """The case the whole flag exists for: a component idea drawn on a
    throwaway airframe, enumerating the architectures it could be fitted to."""
    result = ps.assess_specificity(COMPONENT, MANY_ARCH, HIGH_HEDGE, FIGS_NONE)
    assert result["value"] == "IllustrativeOnly"
    assert result["score"] <= ps.GENERIC_THRESHOLD


def test_specificity_subsystem_lands_in_the_middle():
    result = ps.assess_specificity(SUBSYS, ONE_ARCH, LOW_HEDGE, FIGS_AIRCRAFT)
    assert result["value"] == "ArchitectureGeneric"


def test_specificity_reasons_are_recorded():
    """The verdict has to be defensible in the methodology chapter, so every
    signal that fired is written into the sheet."""
    result = ps.assess_specificity(COMPONENT, MANY_ARCH, HIGH_HEDGE, FIGS_NONE)
    joined = "; ".join(result["reasons"])
    assert "component-level scope" in joined
    assert "architectures" in joined
    assert "no figure shows a complete aircraft" in joined


def test_specificity_gazetteer_name_gives_no_credit():
    """A gazetteer name is COMPANY-level evidence. Letting it argue that this
    patent depicts the aircraft is exactly the error aircraft_link prevents."""
    with_gaz = ps.assess_specificity(SUBSYS, ONE_ARCH, LOW_HEDGE, FIGS_AIRCRAFT,
                                     aircraft_name="S4", aircraft_name_source="gazetteer")
    without = ps.assess_specificity(SUBSYS, ONE_ARCH, LOW_HEDGE, FIGS_AIRCRAFT)
    assert with_gaz["score"] == without["score"]


def test_specificity_llm_name_does_give_credit():
    """The LLM reads the abstract, so its name is evidence about this document."""
    with_llm = ps.assess_specificity(SUBSYS, ONE_ARCH, LOW_HEDGE, FIGS_AIRCRAFT,
                                     aircraft_name="S4", aircraft_name_source="llm")
    without = ps.assess_specificity(SUBSYS, ONE_ARCH, LOW_HEDGE, FIGS_AIRCRAFT)
    assert with_llm["score"] > without["score"]


def test_specificity_confidence_is_lower_near_a_boundary():
    """A verdict decided by one point must not be reported as a confident one."""
    borderline = ps.assess_specificity(SUBSYS, ONE_ARCH, {"level": "medium"}, {})
    decisive = ps.assess_specificity(COMPONENT, MANY_ARCH, HIGH_HEDGE, FIGS_NONE)
    assert borderline["confidence"] < decisive["confidence"]


def test_specificity_no_signals_is_zero_confidence():
    result = ps.assess_specificity({}, {}, {}, {})
    assert result["confidence"] == 0.0
    assert result["reasons"] == []


def test_no_figures_described_is_not_penalised():
    """Absent figure descriptions must not read as 'no aircraft figures' — many
    PatSeer rows simply have no drawings-description column populated."""
    result = ps.assess_specificity(WHOLE, ONE_ARCH, LOW_HEDGE,
                                   {"figures_total": 0, "figures_whole_aircraft": 0})
    assert not any("no figure shows" in r for r in result["reasons"])


# ─── aircraft_link ───────────────────────────────────────────────────────────

def test_link_depicted_only_when_specific():
    assert ps.aircraft_link_for("SpecificAircraft", "Midnight", "llm") == "Depicted"


def test_link_gazetteer_name_on_component_patent_is_attributed():
    """The headline case: Joby files a bearing patent, the gazetteer says S4.
    The name is kept — but the column says it is not depicted."""
    assert ps.aircraft_link_for("IllustrativeOnly", "S4", "gazetteer") == "CompanyAttributed"


def test_link_none_without_a_name():
    assert ps.aircraft_link_for("SpecificAircraft", None, None) == "None"
    assert ps.aircraft_link_for("IllustrativeOnly", "", "gazetteer") == "None"


def test_link_never_depicted_for_generic_specificity():
    for spec in ("ArchitectureGeneric", "IllustrativeOnly"):
        for source in ("gazetteer", "llm", "sbert", "regex", "human"):
            assert ps.aircraft_link_for(spec, "X", source) != "Depicted"


# ─── Row assembly ────────────────────────────────────────────────────────────

def test_build_scope_row_shape():
    row, figs, evidence = ps.build_scope_row(
        patent_id="US1",
        classify_text="An aircraft comprising a fuselage, a wing and a plurality of rotors.",
        description_of_drawings=DESC,
        sbert_model=None,
    )
    assert set(row) == set(ps.SCOPE_COLUMNS)
    assert len(figs) == 5
    assert all(set(f) >= {"patent_id", "fig", "view"} for f in figs)
    assert any(e["field"] == "specificity" for e in evidence)


def test_build_scope_row_component_patent_end_to_end():
    row, figs, _ = ps.build_scope_row(
        patent_id="US2",
        classify_text=(
            "A bearing assembly for an aircraft electric propulsion motor. "
            "In some embodiments the assembly may be used with any suitable "
            "aircraft, such as but not limited to a multirotor aircraft, a "
            "tiltrotor aircraft, or a lift plus cruise aircraft, and may "
            "optionally be alternatively arranged without departing from the "
            "scope of the invention. Various configurations are contemplated. "
            "It should be understood that the bearing may generally be "
            "substantially any suitable type."
        ),
        description_of_drawings=(
            "FIG. 1 is a cross-sectional view of the bearing assembly. "
            "FIG. 2 is an exploded view of the bearing assembly of FIG. 1."
        ),
        sbert_model=None,
        aircraft_name="S4", aircraft_name_source="gazetteer",
    )
    assert row["scope"] == "Component-Level Generic"
    assert row["specificity"] == "IllustrativeOnly"
    assert row["aircraft_link"] == "CompanyAttributed"
    assert row["figures_whole_aircraft"] == 0
    assert row["architecture_count"] >= ps.ARCH_COUNT_GENERIC
    assert row["architecture_pure"] is False


def test_build_scope_row_whole_aircraft_end_to_end():
    row, _, _ = ps.build_scope_row(
        patent_id="US3",
        classify_text=(
            "An aircraft comprising a fuselage, a wing extending from the "
            "fuselage, and a plurality of tiltrotor nacelles mounted to the wing. "
            + "Each nacelle tilts between a hover position and a cruise position. " * 10
        ),
        description_of_drawings=(
            "FIG. 1 is a perspective view of the aircraft. "
            "FIG. 2 is a plan view of the aircraft in a cruise configuration."
        ),
        sbert_model=None,
        aircraft_name="Midnight", aircraft_name_source="llm",
    )
    assert row["scope"] == "Whole Aircraft Architecture"
    assert row["specificity"] == "SpecificAircraft"
    assert row["aircraft_link"] == "Depicted"
    assert row["architecture_primary"] == "TP"


# ─── Integration with aircraft_identity ──────────────────────────────────────

def test_scope_columns_are_in_the_identity_schema():
    from src import aircraft_identity as ai

    for col in ps.SCOPE_COLUMNS:
        assert col in ai.IDENTITY_COLUMNS, f"{col} would be dropped by the export"


def test_attach_scope_flags_company_attributed_names():
    """A row can have a confident name, powertrain and specs and still need
    review — because the name is the company's aircraft, not this patent's."""
    from src import aircraft_identity as ai

    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01",
        meta={"assignee": "JOBY AERO INC (US)", "app_year": "2021",
              "abstract": "a battery pack and electric motors"},
        batch_meta={"company_canonical": "Joby Aviation"},
        gaz_hit={"aircraft_name": "S4", "powertrain": "BatteryElectric",
                 "_confidence": 0.95, "_match": "company+year"},
        powertrain_pred=ai.classify_powertrain("a battery pack", None),
    )
    assert row["aircraft_name"] == "S4"

    scope_row, _, _ = ps.build_scope_row(
        patent_id="US1",
        classify_text="A bearing assembly for an aircraft electric propulsion motor.",
        description_of_drawings="FIG. 1 is a cross-sectional view of the bearing.",
        sbert_model=None,
        aircraft_name=row["aircraft_name"],
        aircraft_name_source=row["aircraft_name_source"],
    )
    ai.attach_scope(row, scope_row)

    assert row["aircraft_link"] == "CompanyAttributed"
    assert row["needs_review"] is True
    assert "company-attributed" in row["review_reason"]
    # The name survives — it is real evidence about the company.
    assert row["aircraft_name"] == "S4"


def test_attach_scope_does_not_demand_a_name_from_a_component_patent():
    """Flagging 'no aircraft name' on a component patent would flag most of the
    corpus and bury the rows that actually need a human."""
    from src import aircraft_identity as ai

    row, _ = ai.build_identity_row(
        patent_id="US2", batch="Batch_01",
        meta={"assignee": "SOME SUPPLIER GMBH (DE)", "app_year": "2021"},
    )
    assert "no aircraft name" in row["review_reason"]

    scope_row, _, _ = ps.build_scope_row(
        patent_id="US2",
        classify_text=(
            "A bearing assembly for an aircraft electric propulsion motor. "
            "In some embodiments the assembly may be used with any suitable "
            "aircraft, such as but not limited to a multirotor aircraft, a "
            "tiltrotor aircraft or a helicopter, and may optionally be "
            "alternatively arranged without departing from the scope."
        ),
        description_of_drawings="FIG. 1 is a cross-sectional view of the bearing.",
        sbert_model=None,
    )
    ai.attach_scope(row, scope_row)

    assert "no aircraft name" not in (row["review_reason"] or "")
    assert "no aircraft expected" in row["review_reason"]
    assert row["aircraft_link"] == "None"
