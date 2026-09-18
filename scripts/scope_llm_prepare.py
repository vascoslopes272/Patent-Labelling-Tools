#!/usr/bin/env python3
"""Write the chunk files for the LLM claim-1 reading of scope + innovation field (plan lines G6/G7).

Same mechanism as the G5 architecture reading (text_architecture/chunk_NN.txt): text only, no figures,
no machine label. Each patent block carries the title, claim 1 (numbering stripped; long claims cut at
CLAIM_CAP characters — the preamble and the start of the body are what decide scope) and the opening of
the abstract as context.

Output: 1639_LABELLED/text_scope/llm_chunks/chunk_NN.txt + llm_inputs_695.json
Reading protocol (the reader must follow it; the answers go to text_scope/scope_llm_<date>.csv):
  patent_id, scope_llm (W | S | C | NS), field_llm, quote (verbatim words of claim 1 that decide it),
  confidence (H | M | L), note
"""
import json
import re
from pathlib import Path
import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling/inputs")   # 2026-09-17: stage-0 INPUTS of the 1639_LABELLED tree
OUT = ROOT.parent / "outputs"                                                                                   # what notebook 04 writes
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
OUT = ROOT / "text_scope" / "llm_chunks"
CHUNK = 35
CLAIM_CAP = 1400
ABSTRACT_CAP = 350


def s(v) -> str:
    return "" if pd.isna(v) else " ".join(str(v).split())


ml = pd.read_csv(OUT / "tables" / "aircraft_table.csv", usecols=["patent_id", "is_primary", "is_approved"])
pids = sorted(set(ml[(ml.is_primary == True) & (ml.is_approved == True)].patent_id))
ps = pd.read_excel(PATSEER, dtype=str, usecols=["Record Number", "Title", "Abstract", "First Claim",
                                                "Independent Claims"]).set_index("Record Number")
items = []
for pid in pids:
    r = ps.loc[pid]
    claim = re.sub(r"^\s*(?:\d+\s*\.\s*)+", "", s(r["First Claim"]) or s(r["Independent Claims"]))
    items.append({"pid": pid, "title": s(r["Title"]),
                  "claim1": claim[:CLAIM_CAP] + (" […]" if len(claim) > CLAIM_CAP else ""),
                  "abstract": s(r["Abstract"])[:ABSTRACT_CAP]})
assert len(items) == 695
OUT.mkdir(parents=True, exist_ok=True)
(OUT.parent / "llm_inputs_695.json").write_text(json.dumps(items, ensure_ascii=False, indent=0), encoding="utf-8")
for k in range(0, len(items), CHUNK):
    blocks = [f"### {it['pid']}\nT: {it['title']}\nC1: {it['claim1'] or '(no claim text)'}\nA: {it['abstract']}"
              for it in items[k:k + CHUNK]]
    (OUT / f"chunk_{k // CHUNK + 1:02d}.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
print(f"{len(items)} patents → {(len(items) + CHUNK - 1) // CHUNK} chunks in {OUT}; "
      f"no claim text: {sum(1 for i in items if not i['claim1'])}")
