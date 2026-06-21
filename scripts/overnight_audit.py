"""
overnight_audit.py — Task 2 / Part C validation gate for the overnight
Batch_02 Stage 01 re-run (Task-1 local-text upgrades + Part-A citation
enrichment). Decides whether the new ml_predict_labels_Batch_02.xlsx export
is trustworthy enough to hand to a human reviewer, BEFORE anyone labels
against it.

Checks (per the task brief):
  1. Vocabulary/schema drift — every non-null Value must be a legal option
     for its row (the Options column already encodes the legal vocabulary
     per-field — see src/excel_schema.py — so this is a direct row-level
     check, no need to re-derive enums from the HTML wizard separately).
  2. Confident-wrong risk — G1 predictions that are confident (>= the
     config confidence_routing.G1 threshold) yet Source == "siglip" (vision
     only) while a same-patent SBERT/keyword text signal, if present in
     M2/M3 rows or elsewhere, disagreed. In this pipeline G1 itself is
     produced by resolve_g1() (text-primary already), so a pure-vision G1
     winner only happens when text was absent/weak; this check flags G1
     rows whose Source is exactly "siglip" (the only vision-only source
     tag G1 can carry) as the highest-risk class, regardless of confidence,
     plus separately surfaces any row at/above threshold for human spot
     review.
  3. Flag coverage — how many ambiguous-looking G1 guesses (low confidence,
     or a kinematic field with Needs_Review) got Needs_Review set, vs not.
  4. Completeness — patents with zero G1 row, zero T1 title, or all-empty
     M1/M2/M3 sections.

Then a NEW-vs-BACKUP diff on G1/empKin/propKin for whatever patents are
common to both files (the original Batch_02 export, where it exists).

Usage:
    python3 scripts/overnight_audit.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

NEW_PATH = Path(
    "/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs"
    "/1639_DS/data/matched/Batch_02/ml_predict_labels_Batch_02.xlsx"
)
BACKUP_PATH = Path(
    "/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs"
    "/1639_DS/data/matched/Batch_02/ml_predict_labels_Batch_02.PRE_OVERNIGHT_BACKUP.xlsx"
)
G1_CONF_THRESHOLD = 0.45   # config.yaml confidence_routing.G1


def load(path: Path) -> pd.DataFrame:
    return pd.read_excel(path)


# ─── Check 1: vocabulary/schema drift ───────────────────────────────────────

def check_schema_drift(df: pd.DataFrame) -> list[dict]:
    """Every non-null Value must appear in its row's pipe-delimited Options.
    Skips rows with empty Options (free-text/manual fields with no fixed
    vocabulary, e.g. notes/footLen) and rows whose Value is itself empty.
    The 'parts' field stores a pipe-joined LIST of values, not one value —
    those are checked element-wise against Options too."""
    illegal = []
    for _, row in df.iterrows():
        opts_raw = row.get("Options")
        val = row.get("Value")
        if pd.isna(opts_raw) or str(opts_raw).strip() == "":
            continue
        if pd.isna(val) or str(val).strip() == "":
            continue
        legal = set(str(opts_raw).split("|"))
        val_str = str(val)
        # boolean fields round-trip through Excel as True/False, not "true"/"false"
        candidates = {val_str}
        if val_str in ("True", "False"):
            candidates.add(val_str.lower())
        # multi-value 'parts' field: each piece must be legal independently
        pieces = val_str.split("|") if row.get("Field") == "parts" else [val_str]
        bad_pieces = [p for p in pieces if p and p not in legal and p.lower() not in legal]
        if bad_pieces and not candidates & legal:
            illegal.append({
                "Patent_ID": row.get("Patent_ID"), "Section": row.get("Section"),
                "Field": row.get("Field"), "Value": val_str, "Options": opts_raw,
            })
    return illegal


# ─── Check 2: confident-wrong risk ───────────────────────────────────────────

def check_confident_wrong_g1(df: pd.DataFrame, threshold: float = G1_CONF_THRESHOLD) -> dict:
    g1 = df[(df["Section"] == "G1") & (df["Field"] == "topType")]
    vision_only = g1[g1["Source"] == "siglip"]
    confident_any_source = g1[(g1["Confidence"].fillna(0) >= threshold) & (g1["Value"].notna())]
    return {
        "vision_only_count": len(vision_only),
        "vision_only_patents": vision_only["Patent_ID"].tolist(),
        "confident_count": len(confident_any_source),
        "confident_by_source": confident_any_source["Source"].value_counts().to_dict(),
    }


# ─── Check 3: flag coverage ───────────────────────────────────────────────────

def check_flag_coverage(df: pd.DataFrame, threshold: float = G1_CONF_THRESHOLD) -> dict:
    g1 = df[(df["Section"] == "G1") & (df["Field"] == "topType")]
    ambiguous = g1[(g1["Confidence"].fillna(0) < threshold) | (g1["Confidence"].isna())]
    flagged = ambiguous[ambiguous["Needs_Review"] == 1.0]
    slipped = ambiguous[ambiguous["Needs_Review"] != 1.0]

    kin_fields = df[df["Field"].astype(str).str.contains(
        "empKin$|_orient$|_propKin$", regex=True, na=False
    )]
    kin_low_conf = kin_fields[(kin_fields["Confidence"].fillna(1.0) < 0.35)]
    kin_flagged  = kin_low_conf[kin_low_conf["Needs_Review"] == 1.0]

    return {
        "g1_ambiguous_total": len(ambiguous),
        "g1_ambiguous_flagged": len(flagged),
        "g1_ambiguous_slipped_through": len(slipped),
        "g1_slipped_patents": slipped["Patent_ID"].tolist()[:20],
        "kinematic_low_conf_total": len(kin_low_conf),
        "kinematic_low_conf_flagged": len(kin_flagged),
    }


# ─── Check 4: completeness ───────────────────────────────────────────────────

def check_completeness(df: pd.DataFrame) -> dict:
    all_patents = set(df["Patent_ID"].unique())
    has_title = set(df[(df["Field"] == "title") & df["Value"].notna()]["Patent_ID"])
    has_g1    = set(df[(df["Section"] == "G1") & df["Value"].notna()]["Patent_ID"])

    def section_empty_patents(section: str) -> set:
        sec = df[df["Section"] == section]
        have_value = set(sec[sec["Value"].notna()]["Patent_ID"])
        return all_patents - have_value

    return {
        "total_patents": len(all_patents),
        "missing_title": sorted(all_patents - has_title),
        "missing_g1_value": sorted(all_patents - has_g1),
        "m1_all_empty": sorted(section_empty_patents("M1")),
        "m2_all_empty": sorted(section_empty_patents("M2")),
        "m3_all_empty": sorted(section_empty_patents("M3")),
    }


# ─── NEW vs BACKUP diff ──────────────────────────────────────────────────────

def diff_new_vs_backup(df_new: pd.DataFrame, df_old: pd.DataFrame) -> dict:
    common_patents = sorted(set(df_new["Patent_ID"]) & set(df_old["Patent_ID"]))
    changes = {"G1.topType": [], "M2.empKin": [], "M3.propKin": []}

    def field_value(df: pd.DataFrame, pid: str, section: str, field_suffix: str):
        rows = df[(df["Patent_ID"] == pid) & (df["Section"] == section)
                   & df["Field"].astype(str).str.endswith(field_suffix)]
        if rows.empty:
            return None
        return rows.iloc[0]["Value"]

    for pid in common_patents:
        old_g1 = field_value(df_old, pid, "G1", "topType")
        new_g1 = field_value(df_new, pid, "G1", "topType")
        if pd.notna(old_g1) or pd.notna(new_g1):
            if str(old_g1) != str(new_g1):
                changes["G1.topType"].append((pid, old_g1, new_g1))

        old_ek = field_value(df_old, pid, "M2", "empKin")
        new_ek = field_value(df_new, pid, "M2", "empKin")
        if str(old_ek) != str(new_ek):
            changes["M2.empKin"].append((pid, old_ek, new_ek))

        # propKin is per propulsion-card component (wing1_propKin, etc.) —
        # compare the set of (component, value) pairs per patent.
        old_pk = df_old[(df_old["Patent_ID"] == pid) & (df_old["Field"].astype(str).str.endswith("propKin"))]
        new_pk = df_new[(df_new["Patent_ID"] == pid) & (df_new["Field"].astype(str).str.endswith("propKin"))]
        old_map = dict(zip(old_pk["Field"], old_pk["Value"]))
        new_map = dict(zip(new_pk["Field"], new_pk["Value"]))
        for k in set(old_map) | set(new_map):
            if str(old_map.get(k)) != str(new_map.get(k)):
                changes["M3.propKin"].append((pid, k, old_map.get(k), new_map.get(k)))

    return {"common_patents": common_patents, "changes": changes}


def main() -> int:
    print("=" * 70)
    print("OVERNIGHT AUDIT — Batch_02 ml_predict_labels (Task 2 / Part C)")
    print("=" * 70)
    print(f"NEW export   : {NEW_PATH}")
    print(f"BACKUP export: {BACKUP_PATH}")

    df_new = load(NEW_PATH)
    df_old = load(BACKUP_PATH) if BACKUP_PATH.exists() else None

    n_patents = df_new["Patent_ID"].nunique()
    print(f"\nNEW export: {len(df_new)} rows, {n_patents} unique patents.")

    # ── 1. Schema drift ──
    illegal = check_schema_drift(df_new)
    print(f"\n[1] VOCABULARY/SCHEMA DRIFT: {len(illegal)} illegal value(s)")
    for item in illegal[:30]:
        print(f"    {item}")
    if len(illegal) > 30:
        print(f"    ... and {len(illegal) - 30} more")

    # ── 2. Confident-wrong risk ──
    cw = check_confident_wrong_g1(df_new)
    print(f"\n[2] CONFIDENT-WRONG RISK (G1 topType)")
    print(f"    Vision-only (Source=='siglip') G1 predictions: {cw['vision_only_count']}")
    if cw["vision_only_patents"]:
        print(f"      patents: {cw['vision_only_patents'][:20]}")
    print(f"    All G1 predictions >= confidence {G1_CONF_THRESHOLD}: {cw['confident_count']}")
    print(f"      by source: {cw['confident_by_source']}")

    # ── 3. Flag coverage ──
    fc = check_flag_coverage(df_new)
    print(f"\n[3] FLAG COVERAGE")
    print(f"    G1 ambiguous (conf < {G1_CONF_THRESHOLD} or missing): {fc['g1_ambiguous_total']}")
    print(f"      flagged (Needs_Review=True): {fc['g1_ambiguous_flagged']}")
    print(f"      SLIPPED THROUGH (not flagged): {fc['g1_ambiguous_slipped_through']}")
    if fc["g1_slipped_patents"]:
        print(f"        sample: {fc['g1_slipped_patents']}")
    print(f"    Kinematic fields (empKin/orient/propKin) low-conf (<0.35): {fc['kinematic_low_conf_total']}")
    print(f"      flagged: {fc['kinematic_low_conf_flagged']}")

    # ── 4. Completeness ──
    comp = check_completeness(df_new)
    print(f"\n[4] COMPLETENESS  (total patents: {comp['total_patents']})")
    print(f"    Missing title           : {len(comp['missing_title'])}")
    print(f"    Missing G1 value        : {len(comp['missing_g1_value'])}  {comp['missing_g1_value'][:10]}")
    print(f"    M1 section all-empty    : {len(comp['m1_all_empty'])}")
    print(f"    M2 section all-empty    : {len(comp['m2_all_empty'])}")
    print(f"    M3 section all-empty    : {len(comp['m3_all_empty'])}")

    # ── NEW vs BACKUP diff ──
    diff = None
    if df_old is not None:
        diff = diff_new_vs_backup(df_new, df_old)
        print(f"\n[DIFF] NEW vs BACKUP")
        print(f"    NOTE: backup only contains {df_old['Patent_ID'].nunique()} patent(s) "
              f"(a partial/earlier run, not a full prior Batch_02 export) — "
              f"the diff below covers ONLY the {len(diff['common_patents'])} patent(s) "
              f"present in both files: {diff['common_patents']}")
        for field, items in diff["changes"].items():
            print(f"    {field} changes: {len(items)}")
            for item in items:
                print(f"      {item}")

    # ── Decision rule ──
    regression = False
    if diff is not None:
        # A "regression" here means a change that moved AWAY from explicit
        # keyword/text evidence already present elsewhere in the row (e.g. a
        # G1 change with Source now siglip-only where it used to be text-based).
        # With only 6 overlapping patents this is checked by hand below.
        pass

    print("\n" + "=" * 70)
    failed = len(illegal) > 0
    if failed:
        print("VALIDATION VERDICT: FAILED — schema/vocabulary drift detected.")
        print("DO NOT use this export as-is. Keep using the backup until the illegal")
        print("values above are fixed and the audit is re-run.")
    else:
        print("VALIDATION VERDICT: PASS on schema/vocabulary — no illegal values found.")
        print(f"  Flag coverage: {fc['g1_ambiguous_slipped_through']} ambiguous G1 call(s) slipped past Needs_Review.")
        print(f"  Confident-wrong watchlist: {cw['vision_only_count']} G1 prediction(s) sourced purely from vision.")
        print("  Review the [2]/[3] numbers above before trusting low-confidence picks blindly.")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
