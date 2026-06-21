"""
test_kinematic_levers.py — inline proofs for the three text-routing levers
added to src/reviewer.py (Task 1, overnight):

  LEVER 1: innovation_objective now reaches the classify_text blob.
  LEVER 2: extract_kinematic_sentences() keeps only cue-word sentences and
           drops boilerplate.
  LEVER 3: a "lift plus cruise" sentence buried in a long description triggers
           the SLC keyword prior via the mined kinematic_text path.

Run: python3 tests/test_kinematic_levers.py   (no pytest required, no network,
no model — sbert_model is stubbed to None / a fake so nothing is downloaded).
"""

import sys
from pathlib import Path

# Allow `import src.reviewer` when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.reviewer as reviewer
from src.reviewer import extract_kinematic_sentences, classify_g1_keyword


# ─── LEVER 2 + 3: extract_kinematic_sentences ───────────────────────────────

def test_extract_keeps_only_cue_sentences():
    text = (
        "The present invention relates generally to aircraft. "
        "It is well known in the art that many configurations exist. "
        "The nacelles tilt forward during transition to cruise flight. "
        "Various embodiments are described below in detail. "
        "A dedicated cruise propeller provides forward thrust."
    )
    out = extract_kinematic_sentences(text)
    # Boilerplate dropped:
    assert "relates generally to aircraft" not in out, out
    assert "well known in the art" not in out, out
    assert "Various embodiments" not in out, out
    # Signal-bearing sentences kept:
    assert "nacelles tilt" in out, out
    assert "dedicated cruise propeller" in out.lower(), out
    print("  [LEVER 2] extract_kinematic_sentences keeps cue sentences, drops boilerplate  OK")


def test_extract_empty_and_no_cue():
    assert extract_kinematic_sentences("") == ""
    assert extract_kinematic_sentences(None) == ""
    # A paragraph with zero cue words returns empty (caller then falls back).
    assert extract_kinematic_sentences(
        "This document describes a generic fastener with a threaded bolt and nut."
    ) == ""
    print("  [LEVER 2] empty / no-cue input returns ''  OK")


def test_buried_lift_plus_cruise_triggers_slc():
    # A long, boilerplate-heavy description with ONE buried SLC giveaway.
    long_desc = (
        "Background of the invention. " * 30
        + "In one embodiment the aircraft uses a lift plus cruise architecture "
          "with separate fixed hover rotors. "
        + "Further background discussion follows for several paragraphs. " * 30
    )
    mined = extract_kinematic_sentences(long_desc)
    assert "lift plus cruise" in mined.lower(), mined
    # The keyword prior fires on the mined text and resolves to SLC.
    pred = classify_g1_keyword(mined)
    assert pred is not None and pred["value"] == "SLC", pred
    assert pred["source"] == "keyword"
    # And it would NOT have fired on the surrounding boilerplate alone.
    assert classify_g1_keyword("Background of the invention. " * 30) is None
    print("  [LEVER 2/3] buried 'lift plus cruise' -> SLC keyword prior fires  OK")


def test_separator_tolerance():
    # hyphen / plus variants normalise the same way classify_g1_keyword does.
    for variant in ("lift-plus-cruise", "lift+cruise", "lift   plus   cruise"):
        s = f"The vehicle employs a {variant} layout for redundancy."
        mined = extract_kinematic_sentences(s)
        assert mined, (variant, mined)
        assert classify_g1_keyword(mined) is not None, variant
    print("  [LEVER 2] space/hyphen/plus separator tolerance  OK")


# ─── LEVER 1: innovation_objective reaches classify_text ─────────────────────

def test_innovation_objective_reaches_classify_text(monkeypatch_like):
    """Prove the text blob built inside process_patent() now contains the
    innovation_objective. We capture the string handed to classify_g1_text()
    (the first consumer of classify_text) without running any real model."""
    captured = {}

    def _spy_classify_g1_text(text, sbert_model=None):
        captured["text"] = text
        return None  # short-circuit; we only care about the input

    monkeypatch_like(reviewer, "classify_g1_text", _spy_classify_g1_text)

    sentinel_obj = "ZZZOBJECTIVEZZZ improves redundancy via separate hover rotors"
    excel_row = {
        "title": "An eVTOL aircraft",
        "abstract": "An aircraft with rotors.",
        "first_claim": "A vehicle comprising a fuselage.",
        "innovation_objective": sentinel_obj,
    }
    cfg = {"paths": {"data": "/nonexistent_data_dir_for_test", "matched": "/nonexistent"}}

    # skip_siglip + no model => process_patent runs the text-blob assembly and
    # the (stubbed) classify_g1_text, then proceeds with empty visual preds.
    reviewer.process_patent(
        patent_id="TESTPID",
        cfg=cfg,
        excel_index={"TESTPID": excel_row},
        matched_dir=Path("/nonexistent"),
        sbert_model=None,
        siglip_bundle=None,
        skip_siglip=True,
        review_flags={},            # avoid CSV loads
        match_results_cache={},     # avoid CSV loads
    )

    assert "text" in captured, "classify_g1_text was not called"
    assert "ZZZOBJECTIVEZZZ" in captured["text"], captured.get("text")
    print("  [LEVER 1] innovation_objective reaches classify_text  OK")


# ─── tiny monkeypatch shim (no pytest dependency) ────────────────────────────

class _Patcher:
    def __init__(self):
        self._undo = []

    def __call__(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def restore(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)


def main() -> int:
    print("Running kinematic-lever tests (no network, no model)...")
    failures = 0

    # Tests that don't need patching.
    for fn in (
        test_extract_keeps_only_cue_sentences,
        test_extract_empty_and_no_cue,
        test_buried_lift_plus_cruise_triggers_slc,
        test_separator_tolerance,
    ):
        try:
            fn()
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {fn.__name__}: {e}")

    # Test that needs the monkeypatch shim.
    patcher = _Patcher()
    try:
        test_innovation_objective_reaches_classify_text(patcher)
    except AssertionError as e:
        failures += 1
        print(f"  FAIL test_innovation_objective_reaches_classify_text: {e}")
    except Exception as e:  # surface unexpected runtime errors as a failure
        failures += 1
        print(f"  ERROR test_innovation_objective_reaches_classify_text: {type(e).__name__}: {e}")
    finally:
        patcher.restore()

    print("-" * 60)
    if failures:
        print(f"RESULT: {failures} test(s) FAILED")
        return 1
    print("RESULT: all tests PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
