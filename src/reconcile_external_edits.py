"""Merge out-of-notebook edits of the corrected wizard export into 02a's `df`.

Why this exists
---------------
02a Section 3 loads `reviewed_patents_<batch>.xlsx` once, and everything after it
works on the in-memory `df`: Section 4 applies the rule pipeline (and whatever the
reviewer un-ticked in the confirmation widget), Section 5c replays its decisions,
Section 6 exports **from `df`, not from the xlsx**. So any correction made to the
xlsx by a script *while the kernel is alive* — a one-off patent fix, a codebook
migration — is invisible to the export.

Re-running Section 3 picks those edits up but throws away the whole of Section 4:
the rule pipeline runs again and every per-patent tick has to be redone. This
module is the cheaper path: it diffs the xlsx against the snapshot it had when
`df` was loaded (a `PRE_*` backup) and replays *only that delta* onto `df`.

Safety
------
The delta is applied row by row, and a row the notebook itself has changed is
never silently overwritten:

    df value == xlsx value   -> already in sync, skipped
    df value == base value   -> a clean external edit, applied
    neither                  -> collision (Section 4/5c AND a script touched the
                                same row) — reported, and skipped unless
                                apply_collisions=True

That makes the choice of base forgiving: picking one that is older than `df`'s
real load point only produces extra no-ops, never a clobbered rule result. If no
base is given, the backup whose contents disagree with `df` the least is used.

Usage (a new cell, after 5c and before Section 6):

    from src.reconcile_external_edits import reconcile
    df = reconcile(df, REVIEWED_XLSX)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

KEY_COLS = ["Patent_ID", "Section", "Sub_Dimension", "Field"]
SYNC_COLS = ["Value", "Source", "Image_Path"]


def _keys(frame: pd.DataFrame) -> pd.Series:
    return frame[KEY_COLS].fillna("").astype(str).apply(lambda s: s.str.strip()).agg("|".join, axis=1)


def _norm(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index)
    return frame[col].fillna("").astype(str).str.strip()


def _read_review(path: Path, strict: bool = True) -> pd.DataFrame:
    """Read the 'Review' sheet.

    strict=True for the live working copy — 02a itself cannot read it without that
    sheet, so a missing one is a hard error. strict=False for the PRE_* backups: a
    backup taken from a file a sloppy script had already renamed to 'Sheet1' still
    holds a perfectly good snapshot, and refusing it only pushes the base further
    from where `df` actually was.
    """
    xls = pd.ExcelFile(path)
    if "Review" in xls.sheet_names:
        return pd.read_excel(xls, sheet_name="Review")
    if strict:
        raise ValueError(
            f"{path.name} has no 'Review' sheet (found: {xls.sheet_names}). A script "
            f"that rewrote it with df.to_excel(path, index=False) — no sheet_name — "
            f"renames the sheet to 'Sheet1'. Rename it back before reconciling."
        )
    if len(xls.sheet_names) != 1:
        raise ValueError(f"{path.name}: no 'Review' sheet and {len(xls.sheet_names)} others")
    return pd.read_excel(xls, sheet_name=xls.sheet_names[0])


def _snapshot(frame: pd.DataFrame) -> tuple[dict, set]:
    """key -> {col: normalised value}, plus the set of keys that appear more than once."""
    k = _keys(frame)
    dupes = set(k[k.duplicated(keep=False)])
    cols = {c: _norm(frame, c) for c in SYNC_COLS}
    snap = {}
    for pos, key in enumerate(k):
        if key in dupes:
            continue
        snap[key] = {c: cols[c].iat[pos] for c in SYNC_COLS}
    return snap, dupes


def _raw_lookup(frame: pd.DataFrame, dupes: set) -> dict:
    """key -> positional index in `frame`, so the UNnormalised cell can be copied over."""
    k = _keys(frame)
    return {key: frame.index[pos] for pos, key in enumerate(k) if key not in dupes}


def pick_base(df: pd.DataFrame, xlsx_path, top: int = 3, verbose: bool = True):
    """The `PRE_*` backup that looks most like `df` — i.e. closest to its load point."""
    xlsx_path = Path(xlsx_path)
    cands = sorted(xlsx_path.parent.glob(f"{xlsx_path.stem}.PRE_*.xlsx"))
    if not cands:
        return None
    df_snap, _ = _snapshot(df)
    scored = []
    for c in cands:
        try:
            snap, _ = _snapshot(_read_review(c, strict=False))
        except Exception as exc:                       # a backup written by a broken script
            if verbose:
                print(f"   (skipped {c.name}: {exc.__class__.__name__})")
            continue
        shared = df_snap.keys() & snap.keys()
        disagree = sum(1 for k in shared if df_snap[k]["Value"] != snap[k]["Value"])
        scored.append((disagree + len(df_snap.keys() ^ snap.keys()), disagree, c))
    if not scored:
        return None
    scored.sort()
    if verbose:
        print("base snapshot candidates (lower = closer to the df in memory):")
        for score, disagree, c in scored[:top]:
            print(f"   {score:6d}  ({disagree} value diffs)  {c.name}")
    return scored[0][2]


def reconcile(df: pd.DataFrame, xlsx_path, base_xlsx=None, *,
              apply_collisions: bool = False, verbose: bool = True,
              max_show: int = 25) -> pd.DataFrame:
    """Replay the xlsx's out-of-notebook edits onto `df`. Returns a new df.

    xlsx_path : the corrected working copy Section 3 read (REVIEWED_XLSX).
                If Section 3 fell back to the FROZEN export while 5c wrote the
                corrected copy, pass the corrected copy explicitly.
    base_xlsx : the snapshot to diff against. Auto-picked from the PRE_* backups
                when omitted.
    """
    xlsx_path = Path(xlsx_path)
    cur = _read_review(xlsx_path)

    base_xlsx = Path(base_xlsx) if base_xlsx else pick_base(df, xlsx_path, verbose=verbose)
    if base_xlsx is None:
        raise FileNotFoundError(
            f"no {xlsx_path.stem}.PRE_*.xlsx snapshot next to {xlsx_path.name} to diff "
            f"against — nothing to reconcile from. Re-run Section 3 instead."
        )
    base = _read_review(base_xlsx, strict=False)
    if verbose:
        print(f"\nbase : {base_xlsx.name}  ({len(base)} rows)")
        print(f"now  : {xlsx_path.name}  ({len(cur)} rows)")
        print(f"df   : {len(df)} rows in memory\n")

    base_snap, base_dupes = _snapshot(base)
    cur_snap, cur_dupes = _snapshot(cur)
    cur_raw = _raw_lookup(cur, cur_dupes)
    ambiguous = base_dupes | cur_dupes

    df = df.copy()
    df_key = _keys(df)
    df_dupes = set(df_key[df_key.duplicated(keep=False)])
    ambiguous |= df_dupes
    df["_rk"] = df_key
    by_key = {k: idx for k, idx in df.groupby("_rk").groups.items() if k not in df_dupes}

    applied, already, collisions, dropped, added, skipped_add = [], 0, [], [], [], []

    # ── value changes ────────────────────────────────────────────────────────
    for key in base_snap.keys() & cur_snap.keys():
        if key in ambiguous:
            continue
        b, c = base_snap[key], cur_snap[key]
        changed = [col for col in SYNC_COLS if b[col] != c[col]]
        if not changed:
            continue
        idx = by_key.get(key)
        if idx is None:                                 # the row is not in df at all
            continue
        i = idx[0]
        for col in changed:
            if col not in df.columns:
                continue
            dfv = "" if pd.isna(df.at[i, col]) else str(df.at[i, col]).strip()
            if dfv == c[col]:
                already += 1
            elif dfv == b[col]:
                # copy the raw cell, not the normalised string, so NaN stays NaN
                df.at[i, col] = cur.at[cur_raw[key], col]
                applied.append((key, col, b[col], c[col]))
            else:
                collisions.append((key, col, b[col], c[col], dfv))
                if apply_collisions:
                    df.at[i, col] = cur.at[cur_raw[key], col]

    # ── rows the scripts deleted ─────────────────────────────────────────────
    drop_idx = []
    for key in base_snap.keys() - cur_snap.keys():
        if key in ambiguous:
            continue
        idx = by_key.get(key)
        if idx is not None:
            drop_idx.extend(list(idx))
            dropped.append(key)
    if drop_idx:
        df = df.drop(index=drop_idx)

    # ── rows the scripts added ───────────────────────────────────────────────
    known_pids = set(df["Patent_ID"].astype(str).str.strip())
    new_keys = [k for k in (cur_snap.keys() - base_snap.keys())
                if k not in ambiguous and k not in by_key]
    if new_keys:
        cur_key = _keys(cur)
        want = cur_key.isin(set(new_keys))
        new_rows = cur[want].copy()
        in_scope = new_rows["Patent_ID"].astype(str).str.strip().isin(known_pids)
        skipped_add = sorted(set(new_rows.loc[~in_scope, "Patent_ID"].astype(str)))
        new_rows = new_rows[in_scope]
        if len(new_rows):
            added = list(cur_key[want][in_scope])
            df = pd.concat([df, new_rows.reindex(columns=df.columns)], ignore_index=True)

    df = df.drop(columns=["_rk"]).reset_index(drop=True)

    if verbose:
        print(f"values applied to df : {len(applied)}")
        print(f"already in sync      : {already}")
        print(f"rows dropped         : {len(dropped)}")
        print(f"rows added           : {len(added)}")
        print(f"collisions           : {len(collisions)}"
              f"{'  (APPLIED — apply_collisions=True)' if apply_collisions and collisions else '  (skipped)' if collisions else ''}")
        if ambiguous:
            print(f"ambiguous keys       : {len(ambiguous)}  (duplicated rows — left untouched)")
        for key, col, old, new in applied[:max_show]:
            pid, sec, sub, fld = key.split("|", 3)
            print(f"   set  {pid:22} {fld:24} {col:10} {old[:28]!r} -> {new[:28]!r}")
        if len(applied) > max_show:
            print(f"   ... {len(applied) - max_show} more")
        for key in dropped[:max_show]:
            pid, sec, sub, fld = key.split("|", 3)
            print(f"   drop {pid:22} {fld:24} {sub[:40]}")
        for key in added[:max_show]:
            pid, sec, sub, fld = key.split("|", 3)
            print(f"   add  {pid:22} {fld:24} {sub[:40]}")
        if skipped_add:
            print(f"   (new rows for {len(skipped_add)} patent(s) not in df were NOT added: "
                  f"{', '.join(skipped_add[:5])}{'...' if len(skipped_add) > 5 else ''})")
        for key, col, old, new, dfv in collisions:
            pid, sec, sub, fld = key.split("|", 3)
            print(f"   !!   {pid:22} {fld:24} {col}: base {old[:22]!r} | xlsx {new[:22]!r} "
                  f"| df {dfv[:22]!r}")
        if collisions and not apply_collisions:
            print("\n   collisions were NOT applied — the notebook changed those rows too.\n"
                  "   Review them, then re-run with apply_collisions=True to take the xlsx side.")
        print(f"\ndf now {len(df)} rows — Section 5b and Section 6 see the external edits.")
    return df


# Rules in Section 4 that legitimately ADD rows to `df` — rows that are supposed to
# be in the export and are supposed to be absent from the wizard xlsx.
RULE_ADDED_SOURCES = {
    "rule_c_propagation",          # Rule C — UAVSimilar tag propagated along a dup chain
    "rule_d_inherited",            # Rule D — topType / isApproved inherited from chain root
    "bug1_fixed_arch_legacy",      # A1 — acState_legacy row preserving the pre-force value
    "partc_multiarch_name_suffix",  # Part C — aircraftName_perArch
}


def orphans(df: pd.DataFrame, xlsx_path, verbose: bool = True) -> pd.DataFrame:
    """Rows in `df` that the xlsx does not have — the leftovers reconcile() cannot see.

    A reconcile only replays base->current. Anything deleted from the xlsx BEFORE the
    base snapshot is invisible to it and simply survives in `df`. Most of what shows up
    here is legitimate (Section 4 adds rows — see RULE_ADDED_SOURCES); anything else is
    a genuinely stale row that would ride into the Section 6 export.
    """
    cur = _read_review(Path(xlsx_path))
    cur_keys = set(_keys(cur))
    extra = df[~_keys(df).isin(cur_keys)].copy()
    if verbose:
        src = extra["Source"].fillna("(blank)").astype(str)
        rule_added = src.isin(RULE_ADDED_SOURCES)
        print(f"{len(extra)} row(s) in df are not in {Path(xlsx_path).name}")
        print(f"  {int(rule_added.sum())} added by Section 4 rules (expected):")
        for v, n in src[rule_added].value_counts().items():
            print(f"      {n:5d}  {v}")
        rest = extra[~rule_added]
        if len(rest):
            print(f"  {len(rest)} NOT explained by a rule — check these:")
            for (pid, fld, sc), n in rest.groupby(
                    [rest["Patent_ID"].astype(str), rest["Field"].astype(str),
                     rest["Source"].fillna("(blank)").astype(str)]).size().items():
                print(f"      {n:5d}  {pid:24} {fld:26} Source={sc}")
        else:
            print("  nothing unexplained — df's extra rows are all rule output.")
    return extra
