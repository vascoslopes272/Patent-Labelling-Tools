"""Build the per-aircraft TRL table (NASA NPR 7123.1D scale) — 2026-09-22.

Reads, in 0_labelling/inputs/trl/:
    trl_scale_nasa.csv          the nine NASA levels, verbatim, + the eVTOL evidence rule per level
    aircraft_programme_status.csv  active / paused / ended / superseded / unknown per ruled aircraft
    company_status.csv          companies that ended or paused (applied to their unruled aircraft)
    aircraft_trl_evidence.csv   the rulings: one row per aircraft that has public evidence
                                (quote + source), hand-written from the evtol.news crawl of
                                2026-09-17 and web sources checked 2026-09-22 — edit THIS file
and 0_labelling/outputs/tables/aircraft_table.csv (notebook 04).

Writes 0_labelling/inputs/trl/aircraft_trl.csv: every primary approved aircraft, one row each.
An aircraft with no ruling is TRL 2 "patent only" — NASA's TRL 2 hardware description
("Invention begins ... no experimental proof or detailed analysis is available") — which means
no PUBLIC evidence of hardware, not that none exists.

    python scripts/build_aircraft_trl.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
TRL_DIR = ROOT / "inputs" / "trl"
AIRCRAFT = ROOT / "outputs" / "tables" / "aircraft_table.csv"


def truthy(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def main() -> None:
    scale = pd.read_csv(TRL_DIR / "trl_scale_nasa.csv")
    ev = pd.read_csv(TRL_DIR / "aircraft_trl_evidence.csv", keep_default_na=False)
    ac = pd.read_csv(AIRCRAFT, low_memory=False)
    ac = ac[truthy(ac["is_approved"]) & truthy(ac["is_primary"])]
    ac = ac[["aircraft_id", "patent_id", "aircraft_name", "name_is_real", "company", "topType", "app_year"]]

    unknown = sorted(set(ev["aircraft_id"]) - set(ac["aircraft_id"]))
    if unknown:
        raise SystemExit(f"rulings for aircraft not in the table: {unknown}")

    out = ac.merge(ev, on="aircraft_id", how="left")
    has = out["trl"].notna()
    out["trl_basis"] = has.map({True: "evidence", False: "patent only"})
    out.loc[~has, "trl"] = 2
    out.loc[~has, "programme_trl"] = 2
    out.loc[~has, "evidence_quote"] = "(no public evidence of hardware found; not linked to evtol.news)"
    out.loc[~has, "confidence"] = "default"
    for c in ["arch_match", "public_arch", "source", "note", "review"]:
        out[c] = out[c].fillna("")
    out["trl"] = out["trl"].astype(int)
    out["programme_trl"] = out["programme_trl"].astype(int)
    out = out.merge(scale[["trl", "nasa_definition"]], on="trl", how="left")

    # programme status (active / paused / ended / superseded / unknown), per ruled aircraft;
    # an aircraft with no ruling takes its company's status when the company itself ended or paused
    status = pd.read_csv(TRL_DIR / "aircraft_programme_status.csv", keep_default_na=False)
    company = pd.read_csv(TRL_DIR / "company_status.csv", keep_default_na=False)
    missing = sorted(set(ev["aircraft_id"]) - set(status["aircraft_id"]))
    if missing:
        raise SystemExit(f"ruled aircraft without a programme status: {missing}")
    out = out.merge(status, on="aircraft_id", how="left")
    comp = company.set_index("company")
    no_status = out["programme_status"].isna()
    by_company = no_status & out["company"].isin(comp.index)
    for col_out, col_in in [("programme_status", "company_status"), ("status_since", "status_since"),
                            ("status_evidence", "status_evidence"), ("status_source", "status_source")]:
        out.loc[by_company, col_out] = out.loc[by_company, "company"].map(comp[col_in])
    out.loc[by_company, "status_note"] = "company status (no aircraft-level ruling)"
    out.loc[out["programme_status"].isna(), "programme_status"] = "not tracked"
    for c in ["status_since", "status_confidence", "status_evidence", "status_source", "status_note"]:
        out[c] = out[c].fillna("")

    cols = ["aircraft_id", "patent_id", "aircraft_name", "company", "topType", "app_year",
            "trl", "nasa_definition", "trl_basis", "confidence", "evidence_quote", "source",
            "programme_trl", "arch_match", "public_arch", "note",
            "programme_status", "status_since", "status_confidence", "status_evidence", "status_source", "status_note"]
    out[cols].to_csv(TRL_DIR / "aircraft_trl.csv", index=False)

    print(f"{len(out)} aircraft -> {TRL_DIR / 'aircraft_trl.csv'}")
    print(out.groupby(["trl", "trl_basis"]).size().rename("aircraft").to_string())
    print(out["programme_status"].value_counts().to_string())
    print("patent against the public aircraft:", out.loc[out["arch_match"] != "", "arch_match"].str.split(" ").str[0].value_counts().to_dict())


if __name__ == "__main__":
    main()
