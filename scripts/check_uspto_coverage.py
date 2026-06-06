"""
check_uspto_coverage.py — Check which patents in the PatSeer export are indexed
in the PatentsView database.

Can be run as a standalone script:
    python scripts/check_uspto_coverage.py

Or imported and called from the Stage 00 notebook:
    from scripts.check_uspto_coverage import check_uspto_coverage
    summary_df = check_uspto_coverage(cfg)
"""

import re
import time
from pathlib import Path

import pandas as pd
import requests


_PATENTSVIEW_URL = "https://api.patentsview.org/patents/query"
_US_STRIP_RE     = re.compile(r'^US(\d+)[A-Z]\d*$', re.IGNORECASE)
_BATCH_SIZE      = 25
_BATCH_SLEEP     = 0.3   # seconds between PatentsView batches


def _strip_us_patent_number(patent_id: str) -> str | None:
    """Strip US prefix and kind code → numeric core: US11299268B2 → '11299268'."""
    m = _US_STRIP_RE.match(patent_id)
    return m.group(1) if m else None


def _query_patentsview_batch(numeric_ids: list[str]) -> dict[str, dict]:
    """
    Query PatentsView for a batch of numeric patent numbers.

    Returns mapping numeric_id → {patent_number, patent_title, patent_date}.
    Missing patents are absent from the returned dict.
    """
    if not numeric_ids:
        return {}

    payload = {
        "q": {"patent_number": {"$in": numeric_ids}},
        "f": ["patent_number", "patent_title", "patent_date"],
        "o": {"per_page": len(numeric_ids)},
    }
    try:
        resp = requests.post(_PATENTSVIEW_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            p["patent_number"]: p
            for p in (data.get("patents") or [])
        }
    except Exception as exc:
        print(f"  [PatentsView] batch query failed: {exc}")
        return {}


def check_uspto_coverage(cfg: dict) -> pd.DataFrame:
    """
    Check coverage of PatSeer patents against the PatentsView database.

    Reads cfg['paths']['patseer_excel'] and queries PatentsView for every
    record starting with 'US'.  Writes results to data/uspto_coverage_check.csv.

    Parameters
    ----------
    cfg : Loaded config dict (from load_config()).

    Returns
    -------
    DataFrame with columns:
        record_number, stripped_number, found_in_uspto, patent_title, patent_date
    """
    excel_path = Path(cfg["paths"]["patseer_excel"])
    data_dir   = Path(cfg["paths"]["data"])
    out_csv    = data_dir / "uspto_coverage_check.csv"

    # ── Load Excel ─────────────────────────────────────────────────────────────
    df_raw  = pd.read_excel(excel_path, dtype=str)
    all_ids = df_raw["Record Number"].dropna().str.strip().tolist()

    # ── Filter to US-only records ──────────────────────────────────────────────
    us_records = [
        (rec_num, _strip_us_patent_number(rec_num))
        for rec_num in all_ids
        if rec_num.upper().startswith("US")
    ]
    us_records_valid = [(r, n) for r, n in us_records if n is not None]

    print(f"PatSeer total  : {len(all_ids):>6,}")
    print(f"US patents     : {len(us_records):>6,}")
    print(f"Parseable      : {len(us_records_valid):>6,}  (others have unexpected number format)")

    # ── Batch query PatentsView ────────────────────────────────────────────────
    # Build lookup: numeric_id → original record_number
    numeric_to_record: dict[str, str] = {}
    for rec_num, numeric in us_records_valid:
        numeric_to_record.setdefault(numeric, rec_num)

    unique_numerics = list(numeric_to_record.keys())
    n_batches = max(1, (len(unique_numerics) + _BATCH_SIZE - 1) // _BATCH_SIZE)
    print(f"\nQuerying PatentsView in {n_batches} batch(es) of ≤{_BATCH_SIZE}…")

    found: dict[str, dict] = {}   # numeric → PatentsView patent dict
    for i in range(0, len(unique_numerics), _BATCH_SIZE):
        batch     = unique_numerics[i : i + _BATCH_SIZE]
        result    = _query_patentsview_batch(batch)
        found.update(result)
        batch_num = i // _BATCH_SIZE + 1
        print(f"  batch {batch_num:>3}/{n_batches}: {len(result):>3}/{len(batch)} found")
        if i + _BATCH_SIZE < len(unique_numerics):
            time.sleep(_BATCH_SLEEP)

    # ── Build results DataFrame ────────────────────────────────────────────────
    rows = []
    for rec_num, numeric in us_records:
        if numeric is None:
            rows.append({
                "record_number":   rec_num,
                "stripped_number": None,
                "found_in_uspto":  False,
                "patent_title":    None,
                "patent_date":     None,
            })
        elif numeric in found:
            p = found[numeric]
            rows.append({
                "record_number":   rec_num,
                "stripped_number": numeric,
                "found_in_uspto":  True,
                "patent_title":    p.get("patent_title"),
                "patent_date":     p.get("patent_date"),
            })
        else:
            rows.append({
                "record_number":   rec_num,
                "stripped_number": numeric,
                "found_in_uspto":  False,
                "patent_title":    None,
                "patent_date":     None,
            })

    result_df = pd.DataFrame(rows)

    # ── Save ───────────────────────────────────────────────────────────────────
    data_dir.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(out_csv, index=False)
    print(f"\nSaved → {out_csv}")

    # ── Summary ────────────────────────────────────────────────────────────────
    n_found   = int(result_df["found_in_uspto"].sum())
    n_missing = len(result_df) - n_found
    pct_found = 100.0 * n_found / max(len(result_df), 1)

    print(f"\n{'='*50}")
    print(f"  US patents checked : {len(result_df):>6,}")
    print(f"  Found in USPTO     : {n_found:>6,}  ({pct_found:.1f} %)")
    print(f"  Not found          : {n_missing:>6,}  (applications not yet granted, or format mismatch)")
    print(f"{'='*50}")

    return result_df


if __name__ == "__main__":
    import sys
    from pathlib import Path as _Path

    _repo = _Path(__file__).resolve().parent.parent
    if str(_repo) not in sys.path:
        sys.path.insert(0, str(_repo))

    from src.config_loader import load_config
    check_uspto_coverage(load_config())
