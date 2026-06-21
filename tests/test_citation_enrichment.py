"""
test_citation_enrichment.py — Part A network-safety proofs for
src/extractor.fetch_cited_patent_text and src/reviewer.{g1_needs_enrichment,
enrich_g1_with_citations, process_patent(enrich_citations=...)}.

Covers the mandatory NETWORK SAFETY properties:
  1. A network failure is swallowed (try/except) and never raises.
  2. The failure result is disk-cached, so a repeat call doesn't refetch.
  3. A live fetch + cache hit makes the SECOND call with zero network requests.
  4. g1_needs_enrichment()'s threshold/flag logic.
  5. enrich_g1_with_citations() with zero citations is a no-op (no network call
     is even attempted — there's nothing to fetch).
  6. process_patent(enrich_citations=False) — the default — makes ZERO network
     calls, proving the feature is genuinely off unless explicitly enabled.

Test 3 needs live network (Google Patents). If offline, it is skipped with a
printed note rather than failing the whole suite.

Run: python3 tests/test_citation_enrichment.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.extractor as ext
import src.reviewer as rv


def test_network_failure_swallowed_and_cached():
    tmp = Path(tempfile.mkdtemp())
    try:
        orig = ext._fetch_google_patents

        def boom(pid, timeout=30):
            raise TimeoutError("simulated network failure")

        ext._fetch_google_patents = boom
        try:
            result = ext.fetch_cited_patent_text("US9999999A1", tmp)
        finally:
            ext._fetch_google_patents = orig

        assert result == "", result

        cache_file = tmp / "US9999999A1.json"
        assert cache_file.exists(), "failure result was not cached"
        data = json.loads(cache_file.read_text())
        assert data["text"] == ""
        print("  [1,2] network failure swallowed + empty result cached  OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_live_fetch_and_cache_hit():
    tmp = Path(tempfile.mkdtemp())
    try:
        try:
            r1 = ext.fetch_cited_patent_text("US2020031488A1", tmp)
        except Exception as e:
            print(f"  [3] SKIPPED (no network?): {e}")
            return
        if not r1:
            print("  [3] SKIPPED (empty result, likely no network)")
            return

        calls = {"n": 0}
        real = ext._fetch_google_patents

        def counting(pid, timeout=30):
            calls["n"] += 1
            return real(pid, timeout)

        ext._fetch_google_patents = counting
        try:
            r2 = ext.fetch_cited_patent_text("US2020031488A1", tmp)
        finally:
            ext._fetch_google_patents = real

        assert calls["n"] == 0, "second call refetched instead of using cache"
        assert r2 == r1
        print("  [3] live fetch + cache hit (0 network calls on repeat)  OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_g1_needs_enrichment_logic():
    assert rv.g1_needs_enrichment(None) is True
    assert rv.g1_needs_enrichment({"value": None}) is True
    assert rv.g1_needs_enrichment({"value": "TP", "confidence": 0.9, "flagged_ambiguous": True}) is True
    assert rv.g1_needs_enrichment({"value": "TP", "confidence": 0.30}, g1_threshold=0.45) is True
    assert rv.g1_needs_enrichment({"value": "TP", "confidence": 0.92}, g1_threshold=0.45) is False
    print("  [4] g1_needs_enrichment threshold/flag logic  OK")


def test_enrich_no_citations_is_noop():
    calls = {"n": 0}
    real = ext._fetch_google_patents

    def counting(pid, timeout=30):
        calls["n"] += 1
        return real(pid, timeout)

    ext._fetch_google_patents = counting
    try:
        orig_pred = {"value": "TP", "confidence": 0.30, "flagged_ambiguous": True, "source": "sbert"}
        out = rv.enrich_g1_with_citations(
            orig_pred, {"backward_cites": [], "forward_cites": []},
            "some kinematic text", None, "/tmp/nonexistent_cache_dir_xyz",
        )
        assert out == orig_pred
        assert calls["n"] == 0
        print("  [5] zero citations -> zero network calls, original pred returned  OK")
    finally:
        ext._fetch_google_patents = real


def test_process_patent_default_off_makes_zero_network_calls():
    real = ext._fetch_google_patents
    calls = {"n": 0}

    def boom(pid, timeout=30):
        calls["n"] += 1
        raise RuntimeError("should never be called when enrich_citations=False")

    ext._fetch_google_patents = boom
    try:
        excel_row = {
            "title": "An eVTOL aircraft", "abstract": "rotors", "first_claim": "A vehicle.",
            "innovation_objective": None,
            "backward_cites": ["US2020031488A1"], "forward_cites": [],
        }
        cfg = {
            "paths": {"data": "/nonexistent_data_dir_xyz", "matched": "/nonexistent"},
            "confidence_routing": {"G1": 0.45},
        }
        rv.process_patent(
            patent_id="TESTPID2", cfg=cfg, excel_index={"TESTPID2": excel_row},
            matched_dir=Path("/nonexistent"), sbert_model=None, siglip_bundle=None,
            skip_siglip=True, review_flags={}, match_results_cache={},
            enrich_citations=False,
        )
        assert calls["n"] == 0, f"network called {calls['n']} times with enrich_citations=False"
        print("  [6] process_patent default (enrich_citations=False) -> 0 network calls  OK")
    finally:
        ext._fetch_google_patents = real


def main() -> int:
    print("Running citation-enrichment safety tests...")
    failures = 0
    for fn in (
        test_network_failure_swallowed_and_cached,
        test_live_fetch_and_cache_hit,
        test_g1_needs_enrichment_logic,
        test_enrich_no_citations_is_noop,
        test_process_patent_default_off_makes_zero_network_calls,
    ):
        try:
            fn()
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")

    print("-" * 60)
    if failures:
        print(f"RESULT: {failures} test(s) FAILED")
        return 1
    print("RESULT: all tests PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
