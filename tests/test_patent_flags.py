"""
test_patent_flags.py — unit tests for src/patent_flags.py (takeoff mode + the
rejectable suggestion) and src/triage_report.py (the review page's ordering).

Runs without a GPU, SBERT or the storage volume.

The failure that would cost real data
-------------------------------------
eVTOL patents mention runways constantly — to say they do not need one. A
keyword pass that counts "takes off and lands without a runway" as
conventional-takeoff evidence gets the label exactly backwards, and because
`rejectable` reads that label, a valid eVTOL would be flagged for removal from
the corpus. The negation tests below pin that inversion shut.

The second guard is the threshold: nothing may raise the rejectable flag unless
its underlying label clears REJECTABLE_MIN_CONFIDENCE, and an *inferred* label
must never be able to clear it on its own.

Run: pytest tests/test_patent_flags.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import patent_flags as pf        # noqa: E402
from src import triage_report as tr       # noqa: E402


# ─── Takeoff mode ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("A vertical takeoff and landing aircraft with tilting rotors.", "VTOL"),
    ("An eVTOL aircraft that hovers before transitioning.", "VTOL"),
    ("A helicopter taking off vertically from a helipad.", "VTOL"),
    ("The vehicle lands vertically at a vertiport.", "VTOL"),
    ("A short takeoff and landing aircraft using blown flaps.", "STOL"),
    ("An eSTOL aircraft operating from short fields.", "STOL"),
    ("A V/STOL aircraft capable of both modes.", "VSTOL"),
    ("A conventional aeroplane accelerating along the runway before rotation.", "CTOL"),
])
def test_takeoff_mode_keywords(text, expected):
    pred = pf.classify_takeoff_mode(text, None)
    assert pred["value"] == expected


def test_takeoff_hyphen_and_spacing_tolerance():
    """'take-off', 'take off' and 'takeoff' are the same word in patent prose."""
    for variant in ("vertical take-off and landing", "vertical take off and landing",
                    "vertical takeoff and landing"):
        assert pf.classify_takeoff_mode(f"An aircraft for {variant}.", None)["value"] == "VTOL"


def test_negated_runway_is_not_conventional_takeoff():
    """The inversion this module exists to prevent: eVTOL patents say 'runway'
    to disclaim it, and reading that as CTOL would flag a valid eVTOL."""
    for text in ("The aircraft takes off and lands without a runway.",
                 "The invention obviates the need for a runway.",
                 "Operation requires no runways whatsoever.",
                 "A runway is not required for this vehicle."):
        pred = pf.classify_takeoff_mode(text, None)
        assert pred["value"] != "CTOL", text
        assert pred["value"] == "VTOL", text


def test_negated_runway_inference_cannot_raise_the_flag():
    """An inferred label is deliberately below the flag threshold, so a guess
    can never on its own mark a patent rejectable."""
    pred = pf.classify_takeoff_mode("The aircraft lands without a runway.", None)
    assert pred["source"] == "keyword_negation"
    assert pred["confidence"] < pf.REJECTABLE_MIN_CONFIDENCE
    assert pf.assess_rejectable(pred, {})["value"] is False


def test_positive_runway_still_reads_as_conventional():
    """The negation guard must not blind the classifier to a genuine runway."""
    pred = pf.classify_takeoff_mode(
        "The aeroplane accelerates along the runway until rotation speed.", None)
    assert pred["value"] == "CTOL"


def test_vstol_phrase_not_double_counted():
    """'V/STOL' contains both substrings; ordering stops it scoring twice."""
    pred = pf.classify_takeoff_mode("A V/STOL aircraft.", None)
    assert pred["value"] == "VSTOL"
    assert pred["confidence"] == pf._CONF_TAKEOFF_KEYWORD


def test_both_modes_named_is_vstol_at_lower_confidence():
    pred = pf.classify_takeoff_mode(
        "An aircraft with vertical takeoff and also short takeoff capability.", None)
    assert pred["value"] == "VSTOL"
    assert pred["confidence"] < pf._CONF_TAKEOFF_KEYWORD


def test_takeoff_unknown_rather_than_guessed():
    for text in ("A bearing assembly for an electric motor.", "", None):
        assert pf.classify_takeoff_mode(text, None)["value"] is None


def test_takeoff_records_the_triggering_sentence():
    """The triage page shows this so a wrong flag is dismissible at a glance."""
    pred = pf.classify_takeoff_mode(
        "This is a short takeoff and landing cargo aircraft.", None)
    assert "short takeoff" in (pred["evidence"] or "")


# ─── Rejectable ──────────────────────────────────────────────────────────────

def _t(value, conf=0.88):
    return {"value": value, "confidence": conf}


@pytest.mark.parametrize("mode, flagged", [
    ("STOL", True), ("CTOL", True), ("VTOL", False), ("VSTOL", False), (None, False),
])
def test_rejectable_by_takeoff_mode(mode, flagged):
    assert pf.assess_rejectable(_t(mode), _t("BatteryElectric"))["value"] is flagged


@pytest.mark.parametrize("power, flagged", [
    ("Turbine", True), ("Piston", True),
    ("BatteryElectric", False), ("HydrogenFuelCell", False),
])
def test_rejectable_by_powertrain(power, flagged):
    assert pf.assess_rejectable(_t("VTOL"), _t(power))["value"] is flagged


def test_hybrid_is_not_rejectable():
    """A series hybrid still flies on electric motors. Whether it belongs in the
    corpus is a scoping decision, not one this flag should pre-empt."""
    assert pf.assess_rejectable(_t("VTOL"), _t("HybridElectric"))["value"] is False


def test_vstol_is_not_rejectable():
    """A both-capable aircraft is still a vertical-takeoff aircraft."""
    assert pf.assess_rejectable(_t("VSTOL"), _t("BatteryElectric"))["value"] is False


def test_low_confidence_label_cannot_flag():
    below = pf.REJECTABLE_MIN_CONFIDENCE - 0.05
    assert pf.assess_rejectable(_t("STOL", below), _t("BatteryElectric"))["value"] is False
    assert pf.assess_rejectable(_t("VTOL"), _t("Turbine", below))["value"] is False


def test_both_reasons_reported_and_confidence_is_the_strongest():
    """Not an average — one decisive reason must not be diluted by a weak one."""
    out = pf.assess_rejectable(_t("STOL", 0.88), _t("Turbine", 0.72))
    assert "takeoff mode is STOL" in out["reason"]
    assert "propulsion is Turbine" in out["reason"]
    assert out["confidence"] == pytest.approx(0.88)


def test_flag_row_shape_matches_the_schema():
    row, _ev = pf.build_flag_row("A short takeoff and landing aircraft.",
                                 _t("Turbine"), None)
    assert set(row) == set(pf.FLAG_COLUMNS)
    assert row["rejectable"] is True


def test_flag_columns_are_in_the_identity_schema():
    from src import aircraft_identity as ai

    for col in pf.FLAG_COLUMNS:
        assert col in ai.IDENTITY_COLUMNS, f"{col} would be dropped by the export"


def test_attach_flags_adds_a_review_reason():
    """A rejectable suggestion is exactly the row a human must look at."""
    from src import aircraft_identity as ai

    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01",
        meta={"assignee": "X CO (US)", "app_year": "2020"})
    flag_row, _ = pf.build_flag_row("A short takeoff and landing aircraft.",
                                    _t("Turbine"), None)
    ai.attach_flags(row, flag_row)

    assert row["rejectable"] is True
    assert row["needs_review"] is True
    assert "REJECTABLE" in row["review_reason"]


def test_attach_flags_is_quiet_when_nothing_is_flagged():
    from src import aircraft_identity as ai

    row, _ = ai.build_identity_row(
        patent_id="US1", batch="Batch_01",
        meta={"assignee": "X CO (US)", "app_year": "2020"})
    before = row["review_reason"]
    flag_row, _ = pf.build_flag_row("A vertical takeoff aircraft.",
                                    _t("BatteryElectric"), None)
    ai.attach_flags(row, flag_row)
    assert row["rejectable"] is False
    assert row["review_reason"] == before


# ─── Triage ordering and page ────────────────────────────────────────────────

def _row(pid, **kw):
    base = {"patent_id": pid, "title": "t", "company_canonical": "C",
            "app_year": "2020", "rejectable": False}
    base.update(kw)
    return base


def test_rejectable_rows_sort_first():
    rows = [_row("A", takeoff_mode_confidence=0.99),
            _row("B", rejectable=True, takeoff_mode_confidence=0.99)]
    assert [r["patent_id"] for r in sorted(rows, key=tr.triage_sort_key)] == ["B", "A"]


def test_contradictions_sort_above_confident_rows():
    """VTOL text with a combustion powertrain means one of the two is wrong,
    and the text alone cannot say which."""
    rows = [_row("clean", takeoff_mode="VTOL", powertrain="BatteryElectric",
                 takeoff_mode_confidence=0.9, powertrain_confidence=0.9),
            _row("clash", takeoff_mode="VTOL", powertrain="Turbine",
                 takeoff_mode_confidence=0.9, powertrain_confidence=0.9)]
    assert [r["patent_id"] for r in sorted(rows, key=tr.triage_sort_key)][0] == "clash"


def test_lower_confidence_sorts_earlier():
    rows = [_row("sure", takeoff_mode_confidence=0.95, powertrain_confidence=0.95),
            _row("unsure", takeoff_mode_confidence=0.30, powertrain_confidence=0.30)]
    assert [r["patent_id"] for r in sorted(rows, key=tr.triage_sort_key)][0] == "unsure"


def test_triage_page_is_self_contained(tmp_path):
    """It opens from file:// with no network, so nothing may be fetched."""
    rows = [_row("US1", rejectable=True, rejectable_reason="propulsion is Turbine",
                 takeoff_mode="STOL", powertrain="Turbine"),
            _row("US2", takeoff_mode="VTOL", powertrain="BatteryElectric")]
    out = tr.build_triage_html(rows, "Batch_01", tmp_path / "t.html")
    doc = out.read_text()

    assert "<script src=" not in doc
    assert "<link rel=\"stylesheet\"" not in doc
    assert "https://" not in doc.split("<script>")[0].replace("http-equiv", "")
    assert "US1" in doc and "US2" in doc
    assert "REJECTABLE" in doc


def test_triage_page_escapes_patent_text(tmp_path):
    """Titles come from the PatSeer export; an unescaped angle bracket would
    break the page silently."""
    rows = [_row("US1", title='A <script>alert(1)</script> "quoted" & odd title')]
    doc = tr.build_triage_html(rows, "B", tmp_path / "t.html").read_text()
    assert "<script>alert(1)</script>" not in doc
    assert "&lt;script&gt;" in doc


def test_triage_page_handles_empty_batch(tmp_path):
    out = tr.build_triage_html([], "Batch_09", tmp_path / "t.html")
    assert out.exists()
    assert "Batch_09" in out.read_text()
