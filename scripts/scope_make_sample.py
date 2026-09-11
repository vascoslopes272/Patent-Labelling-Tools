#!/usr/bin/env python3
"""Draw the blind 100-patent sample that validates the Stage 03a SBERT scope label (plan line G6).

Population : the 695 approved primary patents (master_labels: is_primary & is_approved).
Strata     : the machine's own answer, <scope>|<source> (source = keyword preamble rule or sbert).
             Stratifying on the prediction lets every predicted class get enough rows to estimate
             its precision; the rare strata would otherwise draw 0-1 rows.
Allocation : every stratum gets min(N_h, MIN_PER_STRATUM); the rest of the 100 is split between
             the remaining strata in proportion to N_h (largest remainder).
Weights    : w = N_h / n_h, so a weighted statistic estimates the population value.

Output (1639_LABELLED/text_scope/):
  scope_sample_100.csv            one row per sampled patent, with stratum + weight (NOT shown to the reviewer)
  scope_sample_strata.csv         N_h, n_h, weight per stratum
  scope_sample_representativeness.csv   sample vs population on batch, priority window, office, topType, assignee type

Re-running with the same SEED reproduces the identical sample.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import chisquare

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
OUT = ROOT / "text_scope"
SEED = 42
N_SAMPLE = 100
MIN_PER_STRATUM = 8
WINDOWS = [(0, 2011, "<=2011"), (2012, 2015, "2012-15"), (2016, 2019, "2016-19"),
           (2020, 2023, "2020-23"), (2024, 9999, "2024-26")]


def population() -> pd.DataFrame:
    ml = pd.read_excel(ROOT / "joined" / "master_labels.xlsx",
                       usecols=["patent_id", "batch", "topType", "is_primary", "is_approved"])
    prim = ml[(ml.is_primary == True) & (ml.is_approved == True)]
    types = prim.groupby("patent_id").topType.agg(
        lambda s: s.dropna().astype(str).iloc[0] if s.dropna().nunique() == 1
        else ("none" if s.dropna().empty else "multi"))
    batch = prim.groupby("patent_id").batch.first()
    idn = pd.read_excel(ROOT / "joined" / "aircraft_identity_ALL.xlsx", sheet_name="Identity",
                        usecols=["patent_id", "scope", "scope_source", "scope_confidence",
                                 "pub_office", "priority_year", "company_canonical"])
    pop = idn[idn.patent_id.isin(types.index)].copy()
    pop["batch"] = pop.patent_id.map(batch)
    pop["top_type"] = pop.patent_id.map(types)
    pop["stratum"] = pop.scope.fillna("blank") + "|" + pop.scope_source.fillna("none")
    pop["window"] = pop.priority_year.map(
        lambda y: next((w for lo, hi, w in WINDOWS if lo <= y <= hi), "unknown") if pd.notna(y) else "unknown")
    pop["office"] = pop.pub_office.where(pop.pub_office.isin(["US", "CN", "WO", "DE", "EP"]), "other")
    pop["assignee_type"] = pop.company_canonical.map(
        lambda c: c if c in ("Individual Inventor", "Unknown / Independent") else "Company")
    assert len(pop) == 695 and pop.patent_id.is_unique, len(pop)
    return pop.sort_values("patent_id").reset_index(drop=True)


def allocate(sizes: pd.Series) -> pd.Series:
    n = sizes.clip(upper=MIN_PER_STRATUM)
    left = N_SAMPLE - n.sum()
    room = sizes - n
    share = room / room.sum() * left
    extra = np.floor(share).astype(int)
    for k in (share - extra).sort_values(ascending=False).index[: left - extra.sum()]:
        extra[k] += 1
    n = n + extra
    assert n.sum() == N_SAMPLE and (n <= sizes).all()
    return n


def representativeness(pop: pd.DataFrame, smp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for var in ["batch", "window", "office", "top_type", "assignee_type"]:
        p = pop[var].value_counts(normalize=True)
        # merge categories too small for a chi-square cell (expected < 5 in a sample of 100)
        small = p[p * N_SAMPLE < 5].index
        pv = pop[var].where(~pop[var].isin(small), "(small cats)")
        sv = smp[var].where(~smp[var].isin(small), "(small cats)")
        p = pv.value_counts(normalize=True)
        obs = sv.value_counts().reindex(p.index, fill_value=0)
        wsh = smp.groupby(sv).weight.sum().reindex(p.index, fill_value=0) / smp.weight.sum()
        stat, pval = chisquare(obs.values, p.values * obs.sum())
        for cat in p.index:
            rows.append({"variable": var, "category": cat, "population_share": round(p[cat], 3),
                         "sample_share_unweighted": round(obs[cat] / obs.sum(), 3),
                         "sample_share_weighted": round(wsh[cat], 3),
                         "chi2_unweighted": round(stat, 2), "p_value": round(pval, 3)})
    return pd.DataFrame(rows)


def main():
    pop = population()
    sizes = pop.stratum.value_counts().sort_index()
    alloc = allocate(sizes)
    rng = np.random.default_rng(SEED)
    parts = []
    for stratum, n_h in alloc.items():
        grp = pop[pop.stratum == stratum]
        pick = rng.choice(grp.index.values, size=int(n_h), replace=False)
        parts.append(pop.loc[sorted(pick)].assign(N_h=len(grp), n_h=int(n_h), weight=len(grp) / n_h))
    smp = pd.concat(parts)
    # presentation order: shuffled, so the reviewer never sees the strata grouped together
    smp["page_order"] = rng.permutation(len(smp)) + 1
    smp = smp.sort_values("page_order").reset_index(drop=True)
    assert len(smp) == N_SAMPLE and smp.patent_id.is_unique and abs(smp.weight.sum() - 695) < 1e-6

    OUT.mkdir(exist_ok=True)
    smp[["page_order", "patent_id", "stratum", "N_h", "n_h", "weight", "batch", "priority_year", "window",
         "office", "top_type", "assignee_type", "scope", "scope_source", "scope_confidence"]
        ].to_csv(OUT / "scope_sample_100.csv", index=False)
    strata = pd.DataFrame({"N_h": sizes, "n_h": alloc, "weight": sizes / alloc})
    strata.to_csv(OUT / "scope_sample_strata.csv", index_label="stratum")
    rep = representativeness(pop, smp)
    rep.to_csv(OUT / "scope_sample_representativeness.csv", index=False)

    pd.set_option("display.width", 160)
    print(strata, "\n")
    print(rep.groupby("variable")[["chi2_unweighted", "p_value"]].first(), "\n")
    print(rep.to_string(index=False))
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
