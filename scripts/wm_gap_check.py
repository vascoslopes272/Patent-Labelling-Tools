#!/usr/bin/env python3
"""WM gap check: is the patent shortfall of Wingless Multicopters (50 patents vs
332 eVTOL News aircraft) a query artefact or a real difference?

Deterministic, no model judgment. Three subcommands:

  photos    Step 5. Count cargo/uncrewed WM aircraft in the eVTOL News main set
            from the directory's own spec fields (piloting, capacity).
  patents   Steps 1-3. Set difference of each test export against the original,
            the fixed keyword flag, and the hand-check sheets (seeded sample).
  score     Step 4. Read the filled hand-check sheets and print the table:
            new | flagged | precision [Wilson 95% CI] | estimated manned WM [CI].

Usage
  python wm_gap_check.py photos
  python wm_gap_check.py patents --original ORIG.xlsx --test T1=t1.xlsx --test T2=t2.xlsx --test T3=t3.xlsx
  # fill column manned_wm with y / n in OUT/check_<T>.xlsx, then
  python wm_gap_check.py score
"""
import argparse, math, re, sys
from pathlib import Path
import pandas as pd

EVN = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/EVTOLNEWS_DS")
OUT = EVN / "3_embedding_evaluation" / "wm_gap_check"
SEED = 20261001
N_FLAGGED, N_UNFLAGGED = 30, 20

# ---------------------------------------------------------------- the rule
# Fixed in advance (plan of 2026-10-01). Only lexical fixes on top of the plan:
# word boundaries, plurals, hyphen variants; "rotary-wing" and "rotor wing" are removed before the
# wing test (it means rotorcraft, not a wing); "pilot" with a boundary so that
# "autopilot" does not count as manned; "person" does not match "personal".
MANNED = re.compile(r"\b(passengers?|occupants?|pilot(s|ed|ing)?|cabins?|seat(s|ed|ing)?|persons?)\b", re.I)
MULTI = re.compile(r"\b(multi-?copters?|multi-?rotors?|quad-?copters?|octo-?copters?)\b|\bplurality of (rotors|propellers)\b", re.I)
ROTARY_WING = re.compile(r"\b(rotary|rotor)[- ]wings?\b", re.I)  # "rotor wing" = machine translation of rotor
WING = re.compile(r"\bfixed[- ]wings?\b|\bwings?\b|\btilt\w*", re.I)
CPC_B64C27_08 = re.compile(r"\bB64C\s*27/08(?!\d)", re.I)


def flag(text: str, cpc: str):
    t = text or ""
    manned = bool(MANNED.search(t))
    multi = bool(MULTI.search(t)) or bool(CPC_B64C27_08.search(cpc or ""))
    wing = bool(WING.search(ROTARY_WING.sub(" ", t)))
    return manned, multi, wing, manned and multi and not wing


def wilson(k: int, n: int, z: float = 1.959964):
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


# ---------------------------------------------------------------- reading
COLS = {
    "family": [r"^simple family id$", r"family id", r"^familyid$"],
    "record": [r"^record number$", r"publication number", r"^pn$"],
    "title": [r"^title$", r"^title \(", r"^t$"],
    "abstract": [r"^abstract$", r"^abstract \(", r"^ab$"],
    "cpc": [r"^cpc$", r"^cpc classifications?$", r"^cpc \(all\)$", r"^current cpc"],
}


def find_col(cols, key):
    low = {c: str(c).strip().lower() for c in cols}
    for pat in COLS[key]:
        for c, l in low.items():
            if re.search(pat, l):
                return c
    return None


def read_export(path: Path) -> pd.DataFrame:
    """One row per family: joined title+abstract text and the union of CPCs."""
    if path.suffix.lower() in (".xlsx", ".xls"):
        raw = pd.read_excel(path, header=None, dtype=str)
    else:
        raw = pd.read_csv(path, header=None, dtype=str, sep=None, engine="python")
    hdr = next((i for i in range(min(20, len(raw)))
                if any(re.fullmatch(r"\s*title\s*", str(v), re.I) for v in raw.iloc[i])), None)
    if hdr is None:
        sys.exit(f"{path}: no header row with a 'Title' column in the first 20 rows")
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    got = {k: find_col(df.columns, k) for k in COLS}
    missing = [k for k in ("title", "abstract", "cpc") if got[k] is None]
    if missing or (got["family"] is None and got["record"] is None):
        sys.exit(f"{path}: columns not found: {missing or ['family/record']}; header = {list(df.columns)[:40]}")
    print(f"  {path.name}: columns {got}")
    fam = df[got["family"]] if got["family"] else df[got["record"]]
    fam = fam.fillna(df[got["record"]] if got["record"] else "").astype(str).str.strip()
    df = df.assign(_fam=fam).loc[lambda d: d._fam.ne("") & d._fam.ne("nan")]
    j = lambda s: " | ".join(dict.fromkeys(x.strip() for x in s.dropna().astype(str) if x.strip()))
    out = df.groupby("_fam").agg(
        record=(got["record"], "first") if got["record"] else ("_fam", "first"),
        title=(got["title"], j), abstract=(got["abstract"], j),
        cpc=(got["cpc"], lambda s: "; ".join(sorted({c.strip() for v in s.dropna() for c in re.split(r"[;|,\n]", v) if c.strip()}))),
    ).reset_index().rename(columns={"_fam": "family_id"})
    return out


# ---------------------------------------------------------------- photos (step 5)
NEG_HUMAN = re.compile(r"\b(no|0|zero)\s*(passengers?|pilots?|people|persons?)\b|^0\b|no pilots or passengers|uncrewed|unmanned(?! aircraft system traffic)", re.I)
HUMAN = re.compile(r"\b(passengers?|persons?|people|pilots?|patients?|paramedics?|attendants?|occupants?|fire ?fighters|victims|seats?)\b", re.I)
CARGO = re.compile(r"(?<!no )(?<!or )cargo|payload|firefight|retardant|grocer|container|instrument|\bkg\b|\blbs?\b|parcel|package|deliver|seeds|fertili", re.I)
REMOTE_AUTO = re.compile(r"autonom|remote|autopilot|auto-pilot|\bai\b|bvlos", re.I)


def crew_status(piloting: str, capacity: str, title: str = "") -> str:
    """Fixed order: capacity first (what the aircraft carries), then piloting.
    Uncrewed aircraft are split into cargo/utility by design (would be a drone
    patent) and uncrewed test vehicles with no payload role (often a demonstrator
    of a passenger design, which would be patented as manned)."""
    pil = "" if pd.isna(piloting) else str(piloting)
    cap = "" if pd.isna(capacity) else str(capacity)
    cap = "" if re.fullmatch(r"\s*(unknown\.?)?\s*", cap, re.I) else cap
    pil = "" if re.fullmatch(r"\s*(unknown\.?)?\s*", pil, re.I) else pil
    utility = bool(CARGO.search(cap) or re.search(r"cargo|drone|delivery|logistic", str(title), re.I))
    if NEG_HUMAN.search(cap):
        return "uncrewed: cargo/utility" if utility else "uncrewed: test vehicle, no payload role"
    if HUMAN.search(cap):
        return "crewed"
    if NEG_HUMAN.search(pil):
        return "uncrewed: cargo/utility" if utility else "uncrewed: test vehicle, no payload role"
    if HUMAN.search(pil):
        return "crewed"
    if CARGO.search(cap):
        return "uncrewed: cargo/utility"
    if pil and REMOTE_AUTO.search(pil):
        return "undetermined (autonomous/remote, no capacity)"
    return "undetermined (no data)"


def cmd_photos(_):
    m = pd.read_csv(EVN / "2_embedding_extraction/selection/sets/main.csv", low_memory=False)
    a = pd.read_csv(EVN / "0_source/aircraft.csv")
    wm = m.loc[m.topType == "WM", "aircraft_uid"].unique()
    w = a[a.slug_key.isin(wm)].copy()
    w["crew_status"] = [crew_status(p, c, t) for p, c, t in zip(w.spec_piloting, w.spec_capacity, w.title)]
    OUT.mkdir(parents=True, exist_ok=True)
    w[["slug_key", "title", "status", "spec_piloting", "spec_capacity", "crew_status", "url"]] \
        .sort_values(["crew_status", "slug_key"]).to_csv(OUT / "photos_wm_crew_status.csv", index=False)
    vc = w.crew_status.value_counts()
    n = len(w)
    t = pd.DataFrame({"aircraft": vc, "share": (vc / n * 100).round(1)})
    print(f"WM aircraft in main set: {n}\n{t.to_string()}")
    cu = int(vc.get("uncrewed: cargo/utility", 0))
    unc = int(vc.filter(like="uncrewed").sum())
    und = int(vc.filter(like="undetermined").sum())
    print(f"\ncargo/utility drones: {cu} ({cu / n:.1%});  all uncrewed: {unc} ({unc / n:.1%});  "
          f"upper bound incl. undetermined: {unc + und} ({(unc + und) / n:.1%})")
    print(f"crewed WM aircraft: {vc.get('crewed', 0)}  (lower bound on the photo side)")
    print(f"wrote {OUT / 'photos_wm_crew_status.csv'}")


# ---------------------------------------------------------------- patents (steps 1-3)
def cmd_patents(args):
    OUT.mkdir(parents=True, exist_ok=True)
    print("reading exports")
    orig = read_export(Path(args.original))
    base = set(orig.family_id)
    tests = dict(t.split("=", 1) for t in args.test)
    loaded = {name: read_export(Path(p)) for name, p in tests.items()}
    # Drift: the original was exported on 2026-06-08, the tests later. A family
    # that is new in EVERY test is new because the database changed (new
    # publications, reclassification), not because of the edited line.
    drift = set.intersection(*(set(d.family_id) - base for d in loaded.values())) if len(loaded) > 1 else set()
    print(f"drift (new in every test, excluded): {len(drift)}")
    pd.Series(sorted(drift), name="family_id").to_csv(OUT / "drift_families.csv", index=False)
    news, summary = {}, []
    for name, d in loaded.items():
        new = d[~d.family_id.isin(base | drift)].copy()
        r = [flag(f"{a} {b}", c) for a, b, c in zip(new.title, new.abstract, new.cpc)]
        new[["has_manned", "has_multirotor", "has_wing", "flagged"]] = pd.DataFrame(r, index=new.index)
        new["link"] = "https://patents.google.com/patent/" + new.record.astype(str).str.replace(r"\s", "", regex=True)
        news[name] = new
        new.to_csv(OUT / f"new_{name}.csv", index=False)
        fl, un = new[new.flagged], new[~new.flagged]
        s_fl = fl.sample(n=min(N_FLAGGED, len(fl)), random_state=SEED)
        s_un = un.sample(n=min(N_UNFLAGGED, len(un)), random_state=SEED)
        sheet = pd.concat([s_fl.assign(stratum="flagged"), s_un.assign(stratum="unflagged")])
        sheet = sheet[["stratum", "family_id", "record", "link", "title", "abstract", "cpc"]].assign(manned_wm="", note="")
        sheet.to_excel(OUT / f"check_{name}.xlsx", index=False)
        summary.append(dict(test=name, in_export=len(d), lost_vs_original=len(base - set(d.family_id)),
                            new_raw=len(set(d.family_id) - base), new=len(new), flagged=len(fl),
                            sampled_flagged=len(s_fl), sampled_unflagged=len(s_un)))
    names = list(news)
    print("\noverlap of new families between tests (flagged only):")
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            A, B = set(news[a].family_id[news[a].flagged]), set(news[b].family_id[news[b].flagged])
            print(f"  {a} & {b}: {len(A & B)}")
    pd.DataFrame(summary).to_csv(OUT / "patents_summary.csv", index=False)
    print(f"\nfill manned_wm (y/n) in {OUT}/check_<test>.xlsx, then run: score")


# ---------------------------------------------------------------- score (step 4)
def cmd_score(_):
    summ = pd.read_csv(OUT / "patents_summary.csv")
    rows = []
    for _, s in summ.iterrows():
        c = pd.read_excel(OUT / f"check_{s.test}.xlsx", dtype=str)
        c["y"] = c.manned_wm.fillna("").str.strip().str.lower().str[:1]
        if (c.y == "").any():
            print(f"  {s.test}: {int((c.y == '').sum())} rows not yet checked")
        fl = c[(c.stratum == "flagged") & c.y.isin(["y", "n"])]
        un = c[(c.stratum == "unflagged") & c.y.isin(["y", "n"])]
        k, n = int((fl.y == "y").sum()), len(fl)
        p, lo, hi = wilson(k, n)
        F = int(s.flagged)
        census = n == F
        est, elo, ehi = (k, k, k) if census else (F * p, F * lo, F * hi)
        ku, nu = int((un.y == "y").sum()), len(un)
        U = int(s.new) - F
        pu, _, _ = wilson(ku, nu)
        miss = U * pu if nu else float("nan")
        recall = est / (est + miss) if nu and (est + miss) > 0 else float("nan")
        rows.append({"test": s.test, "new families": int(s.new), "flagged": F,
                     "precision [95% CI]": f"{k}/{n} = {p:.2f} [{lo:.2f}, {hi:.2f}]" + (" (census)" if census else ""),
                     "est. manned WM [95% CI]": f"{est:.0f}" if census else f"{est:.0f} [{elo:.0f}, {ehi:.0f}]",
                     "unflagged yes": f"{ku}/{nu}", "rough recall": f"{recall:.2f}" if recall == recall else "-"})
    t = pd.DataFrame(rows)
    print(t.to_string(index=False))
    t.to_csv(OUT / "wm_gap_table.csv", index=False)
    print(f"\nwrote {OUT / 'wm_gap_table.csv'}")


# ---------------------------------------------------------------- review page result
def cmd_score_review(args):
    """Read wm_review_decisions.csv exported by REVIEW_crewed_multicopter.html."""
    d = pd.read_csv(args.csv, dtype=str).fillna("")
    summ = pd.read_csv(OUT / "patents_summary.csv").set_index("test")
    print(f"undecided: {int((d.decision == '').sum())}   unclear (?): {int((d.decision == 'q').sum())}")
    g = d.groupby("tab").decision.agg(total="size", y=lambda s: int((s == "y").sum()), n=lambda s: int((s == "n").sum()), q=lambda s: int((s == "q").sum()))
    print(g.to_string())
    k = int(g.loc["T1_plausible", "y"]) if "T1_plausible" in g.index else 0
    ys, ns = (int(g.loc["T1_rest_sample", c]) for c in ("y", "n")) if "T1_rest_sample" in g.index else (0, 0)
    rest_n = int(summ.loc["T1", "new"]) - int(g.loc["T1_plausible", "total"]) if "T1_plausible" in g.index else 0
    p, lo, hi = wilson(ys, ys + ns)
    m = int(g.loc["T2_all", "y"]) if "T2_all" in g.index else 0
    qk = int(g.loc["T1_plausible", "q"]) if "T1_plausible" in g.index else 0
    print(f"\nT1: {k} confirmed in the full review of the plausible group (+{qk} unclear)")
    print(f"T1 rest: {ys} of {ys + ns} sampled; 95% upper bound on the rest = {hi:.3f} x {rest_n} = at most {hi * rest_n:.0f} more")
    print(f"T2: {m} confirmed in the full review")
    print(f"WM drawings would rise from 50 to at most {50 + k + m + round(hi * rest_n)} (point estimate {50 + k + m + round(p * rest_n)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("photos").set_defaults(f=cmd_photos)
    pp = sp.add_parser("patents")
    pp.add_argument("--original", required=True)
    pp.add_argument("--test", action="append", required=True, metavar="NAME=PATH")
    pp.set_defaults(f=cmd_patents)
    sp.add_parser("score").set_defaults(f=cmd_score)
    sr = sp.add_parser("score-review")
    sr.add_argument("csv", nargs="?", default=str(Path.home() / "Downloads" / "wm_review_decisions.csv"))
    sr.set_defaults(f=cmd_score_review)
    a = ap.parse_args()
    a.f(a)
