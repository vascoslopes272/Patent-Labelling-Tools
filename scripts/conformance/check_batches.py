#!/usr/bin/env python3
"""Codebook conformance harness — do the labelled batches still agree with the wizard?

The wizard HTML is the source of truth for the taxonomy (see the ML<->HTML sync
note in the repo). Batches were labelled over months against successive wizard
builds, so an export can disagree with today's codebook in five distinct ways.
This script names all five, per batch, and writes a per-patent worklist so a
finding can actually be acted on.

  C1  invalid option    a Value whose id is in NO current option list
  C2  retired option    an id kept in the array only to render legacy saves
                        (derived automatically: ids(X) - X_CHOICES)
  C2b unguarded list    a list with retired ids but no *_CHOICES guard, so the
                        retired option is STILL PICKABLE today
  C3  retired field     a Field the wizard no longer renders or re-exports
  C4  required gap      a field the wizard now makes mandatory that is absent
                        on rows where its precondition holds
  C5  convention drift  a valid field whose ANSWER DISTRIBUTION differs sharply
                        between batches — same option list, different habit
  C6  META coverage     approved patents missing codebook_version / timestamp

Usage:
    python scripts/conformance/check_batches.py                     # all batches
    python scripts/conformance/check_batches.py --batches Batch_01 Batch_05
    python scripts/conformance/check_batches.py --out report/       # + CSV worklists
"""
from __future__ import annotations
import argparse, collections, itertools, json, re, subprocess, sys, tempfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DEFAULT_HTML = REPO / "notebooks" / "UI_for_taxonomy_caracterization_15_4.html"
DEFAULT_DIR = Path(
    "/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs"
    "/1639_DS/data/03c_CORRECTED_wizard_exports"
)
DEFAULT_BATCHES = ["Batch_01", "Batch_02", "Batch_03", "Batch_04", "Batch_05"]

# ── how an exported Field maps onto a wizard option list ────────────────────
# Keyed by (Section, field suffix) because the same suffix means different
# things in different sections: M1 `orient` is the boom axis (BOOM_ORIENT),
# M3 `orient` is the thrust axis (a list built at render time, not a var).
FIELD_LIST = {
    ("G1", "topType"): "TOP",
    ("M2", "wingConf"): "WING_CONFIG",
    ("M2", "posV"): "W_POS_V", ("M2", "posL"): "W_POS_L",
    ("M2", "plan"): "W_PLAN", ("M2", "role"): "W_ROLE",
    ("M2", "tilt"): "W_TILT", ("M2", "empType"): "EMP_TYPE",
    ("M3", "chord"): "CHORD", ("M3", "bmech"): "BLADE_MECH",
    ("M3", "rmech"): "RETRACT_MECH", ("M3", "propKin"): "PROP_KIN",
    ("M1", "attach"): "BOOM_ATTACH", ("M1", "long"): "BOOM_POS_LONG",
    ("M1", "span"): "BOOM_POS_SPAN", ("M1", "wingRel"): "BOOM_WING_REL",
    ("M1", "orient"): "BOOM_ORIENT", ("M1", "fusShape"): "FUS_SHAPE",
    ("M1", "fusKin"): "FUS_KIN", ("M1", "gearArch"): "GEAR_ARCH",
    ("M1", "dinoUnderstanding"): "DINO_UNDERSTANDING",
    ("T2", "per"): "T2_PER", ("T2", "acSty"): "T2_AC_STY",
    ("T2", "acCol"): "T2_AC_COL", ("T2", "bgSty"): "T2_BG_STY",
    ("T2", "bgCol"): "T2_BG_COL", ("T2", "acState"): "AC_STATE",
    ("T2", "qualityFlag"): "QUALITY_FLAGS",
    ("META", "duplicateType"): "DUP_TYPES",
    ("T1", "t1DisapproveReason"): "T1_DISAPPROVE_REASONS",
}
# Values that are legitimate but are not ids in the list (render-time defaults).
EXTRA_OK = {("M2", "role"): {"Main"}}
# The HTML does not name its guards uniformly: T1_DISAPPROVE_REASONS is guarded
# by T1_DISAPPROVE_CHOICES, not T1_DISAPPROVE_REASONS_CHOICES. Without this alias
# the "<LIST>_CHOICES" lookup misses and the list reads as having no retirements
# at all — which is how 6 legacy 'Unreadable' rows in Batch_02 went unreported.
# extract_html_schema.js flags any guard that binds to nothing, so a future
# mismatch shows up as a warning instead of a silent gap.
GUARD_ALIAS = {"T1_DISAPPROVE_REASONS": "T1_DISAPPROVE_CHOICES"}
# Lists whose retirement is documented in a code COMMENT but not enforced by a
# *_CHOICES guard, so the retired ids stay pickable. Kept here rather than
# derived, because only a human reading the comment knows they are retired.
# T2_AC_STY was here until 2026-09-02; it now has a real T2_AC_STY_CHOICES guard,
# so C2 derives its retirement on its own and C2b stops flagging it. AC_STATE is
# the last list whose retirement lives only in a comment.
# v15.7 (2026-09-05) declared AC_STATE_CHOICES, so C2 now DERIVES the acState
# retirement on its own and the hardcoded entry would double-report it. GEAR_ARCH
# gained GEAR_ARCH_CHOICES the same day. Nothing is left in this dict — keep it,
# because the next comment-only retirement will need it again.
UNGUARDED_RETIRED: dict[str, set[str]] = {}
# Fields the wizard stopped rendering. It still PARSES them so an old save loads
# (see the retirement notes in the HTML), so they survive a load/save round trip.
DEAD_FIELDS = {
    r"boom\d+_wingSpan": "BOOM_WING_SPAN retired 2026-08-06",
    r"imgApparentArch": "APPARENT_ARCH retired v15.3",
    r"tiltedInView": "TILTED_IN_VIEW retired v14 (C1)",
    r"boom\d+_format": "boomXFormat retired v14 (C5)",
    r"empTiltsNote": "mandatory tilt-mechanism note retired v15.5 (empTilts itself stays)",
    # v15.6 (2026-09-05): dropped from the M3 cards AND from the export. Ticked 4
    # and 6 times in 2,532 each, all in Batch_05, and fed no rule. NOTE the M1 boom
    # group's own boomN_circSym is a DIFFERENT field and is NOT retired, so these
    # patterns are anchored to the M3 card keys only.
    r"(fuselage|emp|boom|core_layout|hull_array|wing\d)(_t\d)?_symLong":
        "M3 card longitudinal symmetry retired v15.6",
    r"(fuselage|emp|boom|core_layout|hull_array|wing\d)(_t\d)?_symCirc":
        "M3 card circular symmetry retired v15.6",
}
# C4 — (label, precondition field regex, precondition ids, required field regex)
# grouped per boom index so a per-group requirement is checked per group.
REQUIRED = [("boom wingRel (mandatory since 2026-08-07 when boom attaches to a wing)",
             r"boom(\d+)_attach", {"Wings", "Both"}, r"boom(\d+)_wingRel"),
            # v15.6 (2026-09-05): spanwise is measured along the WING, so it is now
            # rendered, required and exported only for a wing-referenced group —
            # the exact mirror of what v15.5 did to boomN_long.
            ("boom span (v15.6: wing-referenced only, and required there)",
             r"boom(\d+)_attach", {"Wings", "Both"}, r"boom(\d+)_span")]
# The mirror of REQUIRED: a field that must be ABSENT where the precondition holds.
# v15.5 made boomN_long fuselage-only, so a value surviving on a wing-attached
# group means the migration has not been run on that batch.
FORBIDDEN = [("boom long must be blank on a wing-attached group (v15.5: fuselage-only)",
              r"boom(\d+)_attach", {"Wings", "Both"}, r"boom(\d+)_long")]
# The other direction: a field that must be absent where the precondition does NOT
# hold. v15.6 stopped exporting boomN_span for a non-wing-attached group.
FORBIDDEN_UNLESS = [("boom span must be blank on a non-wing-attached group (v15.6)",
                     r"boom(\d+)_attach", {"Wings", "Both"}, r"boom(\d+)_span")]
# C5 — fields whose divergence is expected and uninformative. t1Field/t1Target/
# scope are unreviewed SBERT pre-labels that 02a strips at export, so drift in
# them measures the model, not the labeller.
DRIFT_IGNORE = {"T1.t1Field", "T1.t1Target", "T1.scope", "T1.labelToken"}


def code(v: object) -> str:
    """Exported Values are 'ID — Human Label' composites; keep the id."""
    return str(v).split(" — ")[0].strip()


def suffix(field: str) -> str:
    """Strip the group prefixes so wing2_posL and 3_wing1_posL both read posL."""
    f = re.sub(r"^\d+_", "", str(field))
    f = re.sub(r"^(boom|wing|hull_array|core_layout|emp|fuselage)\d*_", "", f)
    return re.sub(r"^t\d+_", "", f)


def load_schema(html: Path) -> dict:
    js = Path(__file__).with_name("extract_html_schema.js")
    out = Path(tempfile.mkstemp(suffix=".json")[1])
    r = subprocess.run(["node", str(js), str(html), str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"schema extraction failed ({html}):\n{r.stderr}")
    print(f"  schema: {html.name} — {r.stderr.strip()}", file=sys.stderr)
    schema = json.loads(out.read_text())
    stray = [g for g in schema.get("unbound_guards", []) if g not in GUARD_ALIAS.values()]
    if stray:
        print(f"  !! guard(s) bound to no option list: {stray} — add a GUARD_ALIAS "
              f"entry or their retirements will not be checked", file=sys.stderr)
    return schema


def load_batches(d: Path, names: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for b in names:
        hits = sorted(d.glob(f"reviewed_patents_{b}*.xlsx"))
        hits = [h for h in hits if re.fullmatch(rf"reviewed_patents_{b} ?\.xlsx", h.name)]
        if not hits:
            print(f"  !! no export for {b} in {d}", file=sys.stderr)
            continue
        df = pd.read_excel(hits[0], sheet_name="Review")
        df["_sfx"] = df["Field"].map(suffix)
        df["_code"] = df["Value"].map(code)
        out[b] = df
        print(f"  {b}: {len(df):>6} rows, {df.Patent_ID.nunique():>4} patents"
              f"  <- {hits[0].name}", file=sys.stderr)
    return out


def retired_ids(schema: dict) -> dict[str, set]:
    """ids(X) - X_CHOICES for every guarded list, plus the comment-only ones."""
    out = {}
    for lst, all_ids in schema["lists"].items():
        guard = schema["choices"].get(GUARD_ALIAS.get(lst, f"{lst}_CHOICES"))
        if guard is not None:
            gone = set(all_ids) - set(guard)
            if gone:
                out[lst] = gone
    for lst, gone in UNGUARDED_RETIRED.items():
        out.setdefault(lst, set()).update(gone)
    return out


def run(schema, batches, out_dir: Path | None):
    lists = {k: set(v) for k, v in schema["lists"].items()}
    retired = retired_ids(schema)
    inv = {v: k for k, v in GUARD_ALIAS.items()}
    guarded = {inv.get(n, n[: -len("_CHOICES")]) for n in schema["choices"]}
    rows: list[dict] = []            # per-patent worklist
    def hit(check, batch, **kw): rows.append(dict(check=check, batch=batch, **kw))

    B = list(batches)
    span = lambda c: " ".join(f"{b.replace('Batch_', 'B')}={c.get(b, 0):<5}" for b in B)
    head = lambda t: print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")

    # ── C1 / C2 ────────────────────────────────────────────────────────────
    head("C1/C2  option ids that today's codebook does not offer")
    agg = collections.defaultdict(collections.Counter)
    for b, df in batches.items():
        for (sec, sfx), lst in FIELD_LIST.items():
            ok = lists[lst] | EXTRA_OK.get((sec, sfx), set())
            sub = df[(df.Section == sec) & (df._sfx == sfx)]
            for v, n in sub._code.value_counts().items():
                if v in ("nan", "", "None"):
                    continue
                kind = ("C1 invalid" if v not in ok else
                        "C2 retired" if v in retired.get(lst, set()) else None)
                if kind:
                    agg[(kind, lst, f"{sec}.{sfx}", v)][b] += n
                    for pid in sub[sub._code == v].Patent_ID.unique():
                        hit(kind, b, patent=pid, field=f"{sec}.{sfx}", value=v, detail=lst)
    if not agg:
        print("  clean")
    for (kind, lst, fld, v), c in sorted(agg.items(), key=lambda x: -sum(x[1].values())):
        pick = "" if lst in guarded or kind.startswith("C1") else "  <- STILL PICKABLE"
        print(f"  {kind}  {fld:<26} {lst:<22} {v!r:<24} {span(c)}{pick}")

    # ── C2b ────────────────────────────────────────────────────────────────
    head("C2b  lists with retired ids but no *_CHOICES guard (reviewers can still pick them)")
    for lst in sorted(retired):
        if lst not in guarded:
            print(f"  {lst:<22} unguarded: {sorted(retired[lst])}")

    # ── C3 ─────────────────────────────────────────────────────────────────
    head("C3  retired FIELDS still carried in an export (survive load/save, never rendered)")
    for pat, why in DEAD_FIELDS.items():
        c = {}
        for b, df in batches.items():
            sub = df[df.Field.astype(str).str.fullmatch(pat, na=False)]
            c[b] = len(sub)
            for pid in sub.Patent_ID.unique():
                hit("C3 retired field", b, patent=pid, field=pat, value="", detail=why)
        if any(c.values()):
            print(f"  {pat:<24} {span(c)} ({why})")

    # ── C4 ─────────────────────────────────────────────────────────────────
    head("C4  fields now mandatory that are missing where their precondition holds")
    for label, pre_pat, pre_ids, req_pat in REQUIRED:
        c, cp = {}, {}
        for b, df in batches.items():
            pre = df[df.Field.astype(str).str.fullmatch(pre_pat, na=False)].copy()
            req = df[df.Field.astype(str).str.fullmatch(req_pat, na=False)].copy()
            if pre.empty:
                c[b] = cp[b] = 0
                continue
            pre["_g"] = pre.Field.astype(str).str.extract(pre_pat)[0]
            req["_g"] = req.Field.astype(str).str.extract(req_pat)[0]
            have = set(zip(req.Patent_ID, req._g))
            need = pre[pre._code.isin(pre_ids)]
            miss = need[[ (p, g) not in have for p, g in zip(need.Patent_ID, need._g) ]]
            c[b], cp[b] = len(miss), miss.Patent_ID.nunique()
            for pid in miss.Patent_ID.unique():
                hit("C4 required gap", b, patent=pid, field=req_pat, value="",
                    detail=label)
        print(f"  {label}\n      groups missing: {span(c)}\n      patents:        {span(cp)}")

    head("C4b  fields that must be BLANK where their precondition holds")
    for label, pre_pat, pre_ids, bad_pat in FORBIDDEN:
        c, cp = {}, {}
        for b, df in batches.items():
            pre = df[df.Field.astype(str).str.fullmatch(pre_pat, na=False)].copy()
            bad = df[df.Field.astype(str).str.fullmatch(bad_pat, na=False)].copy()
            bad = bad[bad.Value.notna() & bad.Value.astype(str).str.strip().ne("")]
            if pre.empty:
                c[b] = cp[b] = 0
                continue
            pre["_g"] = pre.Field.astype(str).str.extract(pre_pat)[0]
            bad["_g"] = bad.Field.astype(str).str.extract(bad_pat)[0]
            hot = {(p, g) for p, g, v in zip(pre.Patent_ID, pre._g, pre._code) if v in pre_ids}
            stray = bad[[(p, g) in hot for p, g in zip(bad.Patent_ID, bad._g)]]
            c[b], cp[b] = len(stray), stray.Patent_ID.nunique()
            for pid in stray.Patent_ID.unique():
                hit("C4b forbidden value", b, patent=pid, field=bad_pat, value="", detail=label)
        print(f"  {label}\n      stray values: {span(c)}\n      patents:      {span(cp)}")

    # C4c is C4b's mirror: the value must be blank where the precondition does NOT
    # hold. v15.6 gave boomN_span the same wing-referenced gate boomN_long got in
    # v15.5, so a fuselage boom carrying a spanwise answer is now stale data.
    for label, pre_pat, pre_ids, bad_pat in FORBIDDEN_UNLESS:
        c, cp = {}, {}
        for b, df in batches.items():
            pre = df[df.Field.astype(str).str.fullmatch(pre_pat, na=False)].copy()
            bad = df[df.Field.astype(str).str.fullmatch(bad_pat, na=False)].copy()
            bad = bad[bad.Value.notna() & bad.Value.astype(str).str.strip().ne("")]
            if pre.empty:
                c[b] = cp[b] = 0
                continue
            pre["_g"] = pre.Field.astype(str).str.extract(pre_pat)[0]
            bad["_g"] = bad.Field.astype(str).str.extract(bad_pat)[0]
            cold = {(p, g) for p, g, v in zip(pre.Patent_ID, pre._g, pre._code) if v not in pre_ids}
            stray = bad[[(p, g) in cold for p, g in zip(bad.Patent_ID, bad._g)]]
            c[b], cp[b] = len(stray), stray.Patent_ID.nunique()
            for pid in stray.Patent_ID.unique():
                hit("C4c forbidden value", b, patent=pid, field=bad_pat, value="", detail=label)
        print(f"  {label}\n      stray values: {span(c)}\n      patents:      {span(cp)}")

    # ── C5 ─────────────────────────────────────────────────────────────────
    head("C5  convention drift — same option list, different habit between batches")
    prof: dict[str, dict[str, dict]] = {}
    for b, df in batches.items():
        k = df.Section.astype(str) + "." + df._sfx
        for key, g in df.assign(_k=k).groupby("_k"):
            if key in DRIFT_IGNORE or len(g) < 40:
                continue
            vc = g._code.value_counts()
            if len(vc) < 2 or len(vc) > 14 or vc.index.str.len().max() > 40:
                continue                       # free text, not a coded field
            prof.setdefault(key, {})[b] = (vc / vc.sum()).to_dict()
    ranked = []
    for key, per in prof.items():
        if len(per) < 3:
            continue
        keys = set().union(*(set(v) for v in per.values()))
        worst, pair = 0.0, None
        for x, y in itertools.combinations(per, 2):
            tvd = 0.5 * sum(abs(per[x].get(k, 0) - per[y].get(k, 0)) for k in keys)
            if tvd > worst:
                worst, pair = tvd, (x, y)
        ranked.append((worst, key, pair, per))
    for w, key, pair, per in sorted(ranked, reverse=True)[:12]:
        flag = "  <<< look at this" if w >= 0.35 else ""
        print(f"  TVD={w:.2f}  {key:<28} worst {pair[0][-2:]}/{pair[1][-2:]}{flag}")
        for b in B:
            if b in per:
                top = sorted(per[b].items(), key=lambda x: -x[1])[:4]
                print(f"        {b}: " + ", ".join(f"{k}={v*100:.0f}%" for k, v in top))

    # ── C6 ─────────────────────────────────────────────────────────────────
    head("C6  META coverage — approved patents with no codebook_version / timestamp")
    for b, df in batches.items():
        ap = df[(df.Field.astype(str) == "isApproved") & (df.Value.astype(str) == "True")]
        ap = set(ap.Patent_ID)
        cv = set(df[df.Field.astype(str) == "codebook_version"].Patent_ID)
        ts = set(df[df.Field.astype(str) == "timestamp"].Patent_ID)
        for pid in (ap - cv) | (ap - ts):
            hit("C6 META gap", b, patent=pid, field="codebook_version/timestamp",
                value="", detail="approved but unstamped")
        print(f"  {b}: patents={df.Patent_ID.nunique():>4} approved={len(ap):>4}"
              f"  no codebook_version={len(ap - cv):>3}  no timestamp={len(ap - ts):>3}")
    stamps = {b: sorted(set(df[df.Field.astype(str) == "codebook_version"]
                            ._code.astype(str))) for b, df in batches.items()}
    print(f"\n  codebook_version values in file: {stamps}")
    print(f"  codebook_version in {'HTML'}: {schema['codebook_version']!r}"
          "   <- never bumped, so this stamp cannot tell two schema revisions apart")

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "conformance_worklist.csv"
        pd.DataFrame(rows).drop_duplicates().to_csv(p, index=False)
        print(f"\n  per-patent worklist -> {p}  ({len(set(map(str, rows)))} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--batches", nargs="+", default=DEFAULT_BATCHES)
    ap.add_argument("--out", type=Path, default=None, help="write per-patent CSV here")
    a = ap.parse_args()
    print("loading:", file=sys.stderr)
    schema = load_schema(a.html)
    batches = load_batches(a.dir, a.batches)
    if not batches:
        sys.exit("no batches loaded")
    run(schema, batches, a.out)


if __name__ == "__main__":
    main()
