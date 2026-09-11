#!/usr/bin/env python3
"""Score machine scope labels against the reviewer's blind decisions on the 100-patent sample.

    python scripts/scope_evaluate_sample.py [decisions.csv] [--llm text_scope/scope_llm_<date>.csv]
    python scripts/scope_evaluate_sample.py --selftest

Methods scored (each only where it has a value):
  sbert_pipeline   the Stage 03a `scope` column as it stands (keyword preamble rule, SBERT otherwise)
  sbert_rows       the same, restricted to rows SBERT decided (scope_source == sbert)
  keyword_rows     the same, restricted to rows the preamble rule decided
  llm              the claim-1 reading, when --llm is given

Statistics (design-weighted, w = N_h / n_h from scope_make_sample.py; "cannot tell" rows excluded):
  accuracy         Σw·correct / Σw, 95% Wilson interval on the Kish effective n with the
                   finite-population correction (N = 695)
  kappa            Cohen's κ on the weighted confusion matrix; 95% CI from a stratified bootstrap
  per class        weighted precision / recall; confusion matrix scaled to the population
Acceptance bar (fixed in the page header before labelling): accuracy lower bound ≥ 0.80 AND κ ≥ 0.60.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
SAMPLE = ROOT / "text_scope" / "scope_sample_100.csv"
DEFAULT_DECISIONS = Path.home() / "Downloads" / "scope_sample_decisions.csv"
N_POP = 695
Z = 1.959964
ACC_LOWER_BAR, KAPPA_BAR = 0.80, 0.60
CLASSES = ["Whole Aircraft Architecture", "Architectural Subsystem Enabler", "Component-Level Generic"]
BOOT = 2000


def wilson(p: float, n_eff: float, n: int) -> tuple[float, float]:
    fpc = (N_POP - n) / (N_POP - 1)
    m = n_eff / fpc if fpc > 0 else float("inf")
    den = 1 + Z * Z / m
    centre = (p + Z * Z / (2 * m)) / den
    half = Z * np.sqrt(p * (1 - p) / m + Z * Z / (4 * m * m)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def weighted_kappa_free(truth, pred, w) -> float:
    """Cohen's κ (unweighted-disagreement κ) from a design-weighted confusion matrix."""
    labels = sorted(set(truth) | set(pred))
    idx = {l: i for i, l in enumerate(labels)}
    cm = np.zeros((len(labels), len(labels)))
    for t, p, wi in zip(truth, pred, w):
        cm[idx[t], idx[p]] += wi
    tot = cm.sum()
    po = np.trace(cm) / tot
    pe = (cm.sum(1) * cm.sum(0)).sum() / tot ** 2
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def score(df: pd.DataFrame, pred_col: str, rng) -> dict:
    d = df[df[pred_col].notna()].copy()
    d[pred_col] = d[pred_col].astype(str)
    if d.empty:
        return {}
    w = d.weight.values
    correct = (d.truth.values == d[pred_col].values).astype(float)
    acc = float((w * correct).sum() / w.sum())
    n_eff = w.sum() ** 2 / (w ** 2).sum()
    lo, hi = wilson(acc, n_eff, len(d))
    kappa = weighted_kappa_free(d.truth.values, d[pred_col].values, w)
    boots = []
    groups = [g for _, g in d.groupby("stratum")]
    for _ in range(BOOT):
        b = pd.concat([g.sample(len(g), replace=True, random_state=int(rng.integers(1 << 31))) for g in groups])
        boots.append(weighted_kappa_free(b.truth.values, b[pred_col].values, b.weight.values))
    k_lo, k_hi = np.nanpercentile(boots, [2.5, 97.5])
    per_class = {}
    for c in CLASSES:
        tp = w[(d.truth == c).values & (d[pred_col] == c).values].sum()
        pp = w[(d[pred_col] == c).values].sum()
        ap = w[(d.truth == c).values].sum()
        per_class[c] = {"precision": tp / pp if pp else np.nan, "recall": tp / ap if ap else np.nan,
                        "n_pred": int((d[pred_col] == c).sum()), "n_true": int((d.truth == c).sum())}
    cm = pd.crosstab(d.truth, d[pred_col], values=d.weight, aggfunc="sum").fillna(0).round(1)
    return {"n": len(d), "n_eff": round(n_eff, 1), "accuracy_unweighted": round(correct.mean(), 3),
            "accuracy": round(acc, 3), "acc_ci_low": round(lo, 3), "acc_ci_high": round(hi, 3),
            "kappa": round(kappa, 3), "kappa_ci_low": round(k_lo, 3), "kappa_ci_high": round(k_hi, 3),
            "passes_bar": bool(lo >= ACC_LOWER_BAR and kappa >= KAPPA_BAR),
            "per_class": per_class, "confusion_weighted": cm}


def evaluate(decisions: pd.DataFrame, llm: pd.DataFrame | None = None, seed: int = 42) -> tuple[pd.DataFrame, dict]:
    smp = pd.read_csv(SAMPLE)
    dec = decisions.rename(columns={"scope_label": "truth"})[["patent_id", "truth", "decision"]]
    df = smp.merge(dec, on="patent_id", how="left")
    missing = df.truth.isna().sum()
    unsure = (df.decision == "U").sum()
    df = df[df.truth.notna() & (df.decision != "U")].copy()
    df["sbert_pipeline"] = df.scope.fillna("blank")
    df["sbert_rows"] = df.sbert_pipeline.where(df.scope_source == "sbert")
    df["keyword_rows"] = df.sbert_pipeline.where(df.scope_source == "keyword")
    methods = ["sbert_pipeline", "sbert_rows", "keyword_rows"]
    if llm is not None:
        df = df.merge(llm[["patent_id", "scope_llm"]], on="patent_id", how="left")
        df.loc[df.scope_llm.isin(["NS", "", None]), "scope_llm"] = np.nan
        methods.append("scope_llm")
    rng = np.random.default_rng(seed)
    res = {m: score(df, m, rng) for m in methods}
    summary = pd.DataFrame([{"method": m, **{k: v for k, v in r.items() if k not in ("per_class", "confusion_weighted")}}
                            for m, r in res.items() if r])
    summary.attrs.update(missing=int(missing), unsure=int(unsure))
    return summary, res


def write_report(summary: pd.DataFrame, res: dict, out: Path):
    lines = ["# Scope — blind 100-patent evaluation", "",
             f"Decisions missing: {summary.attrs['missing']} · marked cannot tell (excluded): {summary.attrs['unsure']}", "",
             f"Acceptance bar: accuracy 95% lower bound ≥ {ACC_LOWER_BAR:.2f} and κ ≥ {KAPPA_BAR:.2f}.", "",
             summary.to_markdown(index=False), ""]
    for m, r in res.items():
        if not r:
            continue
        lines += [f"## {m}", "", pd.DataFrame(r["per_class"]).T.round(3).to_markdown(), "",
                  "Confusion (rows = reviewer, columns = method; population-weighted counts):", "",
                  r["confusion_weighted"].to_markdown(), ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    summary.to_csv(out.with_suffix(".csv"), index=False)


def selftest():
    smp = pd.read_csv(SAMPLE)
    truth = smp.scope.fillna("Architectural Subsystem Enabler").copy()
    flip = smp.index[::10]                     # 10 rows wrong on purpose
    truth.loc[flip] = truth.loc[flip].map(lambda v: "Whole Aircraft Architecture"
                                          if v != "Whole Aircraft Architecture" else "Architectural Subsystem Enabler")
    dec = pd.DataFrame({"patent_id": smp.patent_id, "scope_label": truth, "decision": "W"})
    summary, res = evaluate(dec)
    r = res["sbert_pipeline"]
    exp_unw = 1 - len(flip) / len(smp) - (0 if smp.scope.notna().all() else
                                          int(smp.scope.isna()[~smp.index.isin(flip)].sum()) / len(smp))
    assert abs(r["accuracy_unweighted"] - exp_unw) < 1e-3, (r["accuracy_unweighted"], exp_unw)
    from sklearn.metrics import cohen_kappa_score
    d = smp.assign(truth=truth, pred=smp.scope.fillna("blank"))
    k_sk = cohen_kappa_score(d.truth, d.pred)
    k_ours = weighted_kappa_free(d.truth.values, d.pred.values, np.ones(len(d)))
    assert abs(k_sk - k_ours) < 1e-9, (k_sk, k_ours)
    perfect, _ = evaluate(pd.DataFrame({"patent_id": smp.patent_id, "scope_label": smp.scope.fillna("blank"), "decision": "W"}))
    assert perfect.set_index("method").at["sbert_pipeline", "accuracy"] == 1.0
    print(summary.to_string(index=False))
    print(f"selftest OK — unweighted accuracy {r['accuracy_unweighted']} = expected {exp_unw:.3f}; "
          f"κ matches sklearn ({k_sk:.4f}); perfect agreement scores 1.0")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else DEFAULT_DECISIONS
    llm = None
    if "--llm" in sys.argv:
        llm = pd.read_csv(sys.argv[sys.argv.index("--llm") + 1])
    summary, res = evaluate(pd.read_csv(path), llm)
    out = ROOT / "text_scope" / "scope_sample_evaluation.md"
    write_report(summary, res, out)
    print(summary.to_string(index=False))
    print("wrote", out)


if __name__ == "__main__":
    main()
