"""
deduplicator.py — Robust patent family deduplication for the PatSeer pipeline.

Each patent family may be represented by several publication numbers (USPTO,
EPO, WIPO…).  This module selects ONE canonical member per family using a
deterministic three-level priority:

  1. Member with the MOST figures / drawings  (maximize image data)
  2. Tie-break: earliest filing date
  3. Tie-break: office preference  US > EP > WO > other

Public API
----------
run_deduplication(df, cfg)  →  (deduplicated_df, family_map_df)

run_deduplication also saves:
  cfg["paths"]["data"] / deduplicated_patents.csv
  cfg["paths"]["data"] / family_map.csv
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd


# ─── Column name variants (PatSeer exports differ across accounts) ─────────────

_PUB_NUMBER_VARIANTS = [
    "Publication Number", "Pub. No.", "Patent Number", "Record Number",
]
_FAMILY_ID_VARIANTS = [
    "Simple Family ID", "Family ID", "INPADOC Family ID", "DOCDB Family ID",
]
_FILING_DATE_VARIANTS = [
    "Filing Date", "Application Date", "App. Date", "Filing/Application Date",
]
_ASSIGNEE_VARIANTS = [
    "Assignee", "Applicant", "Assignee/Applicant",
]
_FIGURE_COUNT_VARIANTS = [
    "No. of Drawings", "Drawing Count", "Figures", "Number of Drawings",
]
_TITLE_VARIANTS   = ["Title", "Patent Title", "Invention Title"]
_ABSTRACT_VARIANTS = ["Abstract", "Abstract Text"]

# figure-count range that triggers the "review_family" flag
_REVIEW_FIGURE_DIFF = 3


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _find_col(df: pd.DataFrame, variants: list[str], required: bool = True) -> Optional[str]:
    """
    Return the first column name from *variants* that is present in *df*.

    Parameters
    ----------
    required : if True and no variant is found, raise a KeyError with a
               descriptive message naming the missing column variants.
    """
    for v in variants:
        if v in df.columns:
            return v
    if required:
        raise KeyError(
            f"None of the expected column name variants were found in the DataFrame.\n"
            f"  Expected one of: {variants}\n"
            f"  Available columns: {list(df.columns[:20])} ..."
        )
    return None


def _office_rank(pub_number: str) -> int:
    """Lower is better: US=0, EP=1, WO=2, everything else=3."""
    s = str(pub_number).upper()
    if s.startswith("US"):
        return 0
    if s.startswith("EP"):
        return 1
    if s.startswith("WO"):
        return 2
    return 3


def _selection_reason(
    group: pd.DataFrame,
    canonical_idx: int,
    fig_col: Optional[str],
    date_col: str,
    pub_col: str,
) -> str:
    """Return a short human-readable string explaining the canonical choice."""
    if len(group) == 1:
        return "sole_member"

    figs = (
        pd.to_numeric(group[fig_col], errors="coerce").fillna(0).astype(int)
        if fig_col else pd.Series([0] * len(group), index=group.index)
    )
    canonical_figs = figs[canonical_idx]
    max_figs       = figs.max()
    min_figs       = figs.min()

    dates = pd.to_datetime(group[date_col], errors="coerce")
    canonical_date = dates[canonical_idx]

    if max_figs > 0 and canonical_figs == max_figs and max_figs > min_figs:
        return f"max_figures={canonical_figs}"

    # All tied on figures — was the date the decisive factor?
    tied_candidates = group[figs == max_figs]
    tied_dates = dates[figs == max_figs]
    if tied_dates.nunique() > 1 and pd.notna(canonical_date):
        return f"tied_figures_earliest_date={str(canonical_date)[:10]}"

    office = _office_rank(group.loc[canonical_idx, pub_col])
    office_name = {0: "US", 1: "EP", 2: "WO"}.get(office, "other")
    return f"tied_figures_tied_date_office={office_name}"


# ─── Core selection logic ─────────────────────────────────────────────────────

def _pick_canonical(
    group: pd.DataFrame,
    pub_col: str,
    date_col: str,
    fig_col: Optional[str],
) -> int:
    """
    Select the canonical representative from *group* and return its index.

    Priority (lexicographic sort):
      1. Descending figure count  (most figures first)
      2. Ascending filing date    (earliest first)
      3. Ascending office rank    (US=0 < EP=1 < WO=2 < other=3)
    """
    tmp = group[[pub_col, date_col]].copy()

    # Figure count key (negate for descending sort)
    if fig_col and fig_col in group.columns:
        tmp["_fig"] = -pd.to_numeric(group[fig_col], errors="coerce").fillna(0)
    else:
        tmp["_fig"] = 0

    # Filing date key
    tmp["_date"] = pd.to_datetime(group[date_col], errors="coerce")

    # Office rank key
    tmp["_office"] = group[pub_col].apply(_office_rank)

    tmp = tmp.sort_values(["_fig", "_date", "_office"])
    return tmp.index[0]


def _review_flag(group: pd.DataFrame, fig_col: Optional[str]) -> bool:
    """
    True if the spread of figure counts within the family exceeds the threshold.
    Families with no figure data are never flagged.
    """
    if not fig_col or len(group) < 2:
        return False
    figs = pd.to_numeric(group[fig_col], errors="coerce").dropna()
    if len(figs) < 2:
        return False
    return int(figs.max() - figs.min()) > _REVIEW_FIGURE_DIFF


# ─── Public API ───────────────────────────────────────────────────────────────

def run_deduplication(
    df: pd.DataFrame,
    cfg: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Deduplicate a PatSeer export DataFrame by patent family.

    For each family group the canonical member is selected using figure count,
    filing date, and office-of-publication as a three-level priority key.

    Parameters
    ----------
    df  : Raw pandas DataFrame loaded from the PatSeer Excel file (all columns
          kept so downstream modules receive the full row).
    cfg : Configuration dict from load_config().  Used for output paths.

    Returns
    -------
    deduplicated_df : One row per canonical patent.
    family_map_df   : One row per family; records which member was kept and why.

    Side-effects
    ------------
    Writes CSVs to cfg["paths"]["data"]:
      deduplicated_patents.csv
      family_map.csv
    """
    # ── Resolve column names ──────────────────────────────────────────────────
    pub_col    = _find_col(df, _PUB_NUMBER_VARIANTS, required=True)
    family_col = _find_col(df, _FAMILY_ID_VARIANTS,  required=True)
    date_col   = _find_col(df, _FILING_DATE_VARIANTS, required=True)
    fig_col    = _find_col(df, _FIGURE_COUNT_VARIANTS, required=False)  # optional
    assignee_col = _find_col(df, _ASSIGNEE_VARIANTS,  required=False)

    print(f"[deduplicator] Columns resolved:")
    print(f"  pub_number  → {pub_col!r}")
    print(f"  family_id   → {family_col!r}")
    print(f"  filing_date → {date_col!r}")
    print(f"  fig_count   → {fig_col!r}  (None = column absent, default 0)")
    print(f"  assignee    → {assignee_col!r}")
    print()

    # ── Normalise publication numbers (strip whitespace) ──────────────────────
    df = df.copy()
    df[pub_col] = df[pub_col].astype(str).str.strip()

    # ── Assign pseudo-family-id for rows with missing family_id ───────────────
    # PatSeer sometimes leaves Simple Family ID blank for singleton patents.
    family_vals = df[family_col].astype(str).str.strip()
    mask_missing = family_vals.isin(["", "nan", "NaN", "None"])
    # Use the publication number itself as a unique family id for those rows
    family_vals[mask_missing] = df.loc[mask_missing, pub_col]
    df["_family_id"] = family_vals

    n_input = len(df)

    # ── Process each family ───────────────────────────────────────────────────
    canonical_indices: list[int] = []
    family_map_rows:   list[dict] = []

    for fam_id, group in df.groupby("_family_id", sort=False):
        canonical_idx = _pick_canonical(group, pub_col, date_col, fig_col)
        canonical_pub = group.loc[canonical_idx, pub_col]
        all_members   = group[pub_col].tolist()
        dropped       = [p for p in all_members if p != canonical_pub]
        reason        = _selection_reason(group, canonical_idx, fig_col, date_col, pub_col)
        review        = _review_flag(group, fig_col)

        canonical_indices.append(canonical_idx)
        family_map_rows.append({
            "family_id":          fam_id,
            "canonical_pub_number": canonical_pub,
            "family_size":        len(group),
            "all_members":        "; ".join(all_members),
            "members_dropped":    "; ".join(dropped),
            "selection_reason":   reason,
            "review_family":      review,
        })

    # ── Build deduplicated DataFrame ──────────────────────────────────────────
    deduplicated_df = df.loc[canonical_indices].copy()
    deduplicated_df = deduplicated_df.drop(columns=["_family_id"])
    deduplicated_df = deduplicated_df.reset_index(drop=True)

    # Attach the review flag so downstream steps can surface it
    fam_review = {
        r["canonical_pub_number"]: r["review_family"] for r in family_map_rows
    }
    deduplicated_df["review_family"] = deduplicated_df[pub_col].map(fam_review)

    family_map_df = pd.DataFrame(family_map_rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    n_families  = len(family_map_rows)
    n_kept      = len(deduplicated_df)
    n_dropped   = n_input - n_kept
    n_multi     = sum(1 for r in family_map_rows if r["family_size"] > 1)
    n_review    = family_map_df["review_family"].sum()

    print("=" * 60)
    print("[deduplicator] Summary")
    print(f"  Input rows          : {n_input:>6,}")
    print(f"  Unique families     : {n_families:>6,}")
    print(f"  Patents kept        : {n_kept:>6,}")
    print(f"  Patents dropped     : {n_dropped:>6,}")
    print(f"  Families > 1 member : {n_multi:>6,}")
    print(f"  Families to review  : {n_review:>6,}  (figure count spread > {_REVIEW_FIGURE_DIFF})")
    print("=" * 60)

    # ── Save CSVs ─────────────────────────────────────────────────────────────
    out_dir = Path(cfg["paths"]["data"])
    out_dir.mkdir(parents=True, exist_ok=True)

    dedup_path  = out_dir / "deduplicated_patents.csv"
    fmap_path   = out_dir / "family_map.csv"

    deduplicated_df.to_csv(dedup_path, index=False)
    family_map_df.to_csv(fmap_path,   index=False)

    print(f"  Saved: {dedup_path}")
    print(f"  Saved: {fmap_path}")

    return deduplicated_df, family_map_df


# ─── Standalone entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Allow: python -m src.deduplicator  [path/to/config.yaml]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from src.config_loader import load_config
    from src.extractor import load_patseer_excel  # noqa: F401 (print column list)

    cfg  = load_config(sys.argv[1] if len(sys.argv) > 1 else None)
    excel_path = cfg["paths"]["patseer_excel"]

    print(f"Loading Excel: {excel_path}")
    df = pd.read_excel(excel_path, dtype=str)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns.\n")

    dedup_df, fmap_df = run_deduplication(df, cfg)
    print(f"\nDeduplicated DataFrame shape : {dedup_df.shape}")
    print(f"Family map shape             : {fmap_df.shape}")
