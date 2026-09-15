"""NAME_DECISIONS.csv (exported by notebooks/post-process/name_review.html) -> the human name cells, via build_identity_all."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_identity_all", REPO / "scripts" / "build_identity_all.py")
bia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bia)


def _ident():
    return pd.DataFrame({
        "patent_id": ["A", "B", "C", "D", "E"],
        "aircraft_group": ["Acme 1", "Beta 2", "Gamma 3", "Delta 4", "Eps 5"],
        "wizard_aircraft_name": ["Acme 1", "Beta 2", "Gamma 3", "Delta 4", "EPS"],
        "aircraft_name_human": [float("nan"), "Typed in page", None, float("nan"), ""],
        "aircraft_name_human_variants": [float("nan"), None, None, float("nan"), None],
    }, dtype=object)


def _write(tmp_path, rows):
    p = tmp_path / "NAME_DECISIONS.csv"
    pd.DataFrame(rows, columns=["patent_id", "decision", "name_final", "source_note", "candidates",
                                "comment", "decided_at"]).to_csv(p, index=False)
    return p


def test_decisions_fill_only_empty_cells_and_nan_counts_as_empty(tmp_path):
    ident = _ident()
    p = _write(tmp_path, [
        ["A", "text", "Vertiia", "", "Vertiia", "", ""],
        ["B", "other", "Something else", "", "", "", ""],      # page already answered -> kept
        ["C", "clear", "", "", "APT", "", ""],
        ["D", "other", "Delta a; Delta b", "", "", "", ""],     # one name per aircraft
        ["E", "fix", "Eps Aero 5", "", "EPS", "", ""],
    ])
    msgs = bia.apply_name_decisions(ident, p)
    got = ident.set_index("patent_id")
    assert got.at["A", "aircraft_name_human"] == "Vertiia"
    assert got.at["B", "aircraft_name_human"] == "Typed in page"
    assert got.at["C", "aircraft_name_human"] == "Gamma 3"
    assert got.at["D", "aircraft_name_human_variants"] == "Delta a; Delta b"
    assert bia._is_blank(got.at["D", "aircraft_name_human"])
    assert got.at["E", "aircraft_name_human"] == "Eps Aero 5"
    assert msgs[0].strip().startswith("4 name(s) filled")
    assert any("wizard name should read 'Eps Aero 5'" in m for m in msgs)


def test_bad_rows_are_reported_not_applied(tmp_path):
    ident = _ident()
    p = _write(tmp_path, [["ZZZ", "text", "X", "", "", "", ""], ["A", "other", "", "", "", "", ""],
                          ["A", "maybe", "X", "", "", "", ""]])
    msgs = bia.apply_name_decisions(ident, p)
    assert bia._is_blank(ident.at[0, "aircraft_name_human"])
    assert sum(m.startswith("⚠") for m in msgs) == 3


def test_missing_file_is_a_no_op(tmp_path):
    assert bia.apply_name_decisions(_ident(), tmp_path / "absent.csv") == []
