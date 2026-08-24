# Batch 03 / Batch 04 reorganisation — company-first reassignment

**Date:** 2026-08-17
**Scope:** Batches 03 and 04 only. Batches 01, 02 and 05 were left untouched.
**Effect on labels:** none. No patent was added, removed, relabelled or duplicated — 393 of
the 676 unlabelled patents simply changed which batch they sit in.

---

## 1. Why

Batches were never cut on any substantive criterion. `00b1_grouping.ipynb` cell 3 sorts
patents by `display_order` — which groups them by `(company_canonical, prototype_label)`,
i.e. **alphabetically by company** — then slices a new batch every 300–400 patents. The
result is that each batch is an alphabetical band of the assignee list:

| Batch | Alphabetical band |
|---|---|
| 01 | A–B (AMSL, Aerhart, Airbus, Archer, Aurora, Bell/Textron …) |
| 02 | B–H (Beta, Boeing, Denso, Honda, Hyundai …) |
| 03 | I–L (Ishikawa, JAXA, Joby, KAIST, KARI, Kitty Hawk, Leonardo …) |
| 04 | L–P (Lilium, Lockheed, Mitsubishi, NASA, Porsche, Pipistrel …) |
| 05 | S–Z (Vertical, Volocopter, Wisk, Wofei/Geely …) |

Because the two catch-all buckets (`Individual Inventor`, `Unknown / Independent`) are large
and also land in alphabetical position, **Batch_03 ended up two-thirds individual inventors
(205 / 305)** while most of the significant companies sat in Batch_04.

That is the wrong priority order. Company-filed patents are the more valuable ones to label:
they are the real eVTOL programmes, they have better drawings, and they are what the thesis
actually argues about. Labelling is expensive and may stop early, so the corporate set should
be finished **first**. Batches 03 and 04 were therefore re-cut by *who filed the patent*
instead of *where the assignee falls in the alphabet*.

## 2. Scope, and why only 03 and 04

At the time of the change, labelling status was:

| Batch | Patents | Status |
|---|---|---|
| 01 | 352 | labelled, and through 02a/02b |
| 02 | 400 | labelled |
| 03 | 305 | **not labelled** |
| 04 | 371 | **not labelled** |
| 05 | 211 | labelled, and through 02b |

Only 03 and 04 were still unlabelled, so they are the only two that *can* be reshuffled
without invalidating completed work. **The remaining pool is exactly 676 patents**, and the
reorganisation is a pure re-partition of those 676.

A consequence worth stating plainly: because batch 05 was already labelled, the ~70
company-filed patents that live there stay there. "All companies are in Batch_03" is
therefore true **of the remaining unlabelled pool**, not of the corpus as a whole.

## 3. Classifying the filer

The existing `company_canonical` column could not be used directly, because it is misleading:

- `Unknown / Independent` does **not** mean "individual". `grouper.py::_normalise_company`
  falls back to that label whenever the assignee fails to match `COMPANY_LOOKUP`. Of the 127
  such rows in Batch_04, **all 127 are real companies** — ATMOS UAV, Odys Aviation, ONERA,
  Danfoss Power Solutions, Latitude Engineering, CETC Wuhu Diamond Aircraft, Sonic Blue
  Aerospace, and so on. They are simply missing from the lookup table.
- `Individual Inventor` is applied only when `_is_personal_name()` fires, which it does not
  always do (Cyrillic company forms, CJK names, city-suffixed assignee strings).

So each of the 676 patents was re-classified from the **raw PatSeer `Assignee` string** into
one of three classes:

| `filer_class` | Definition | Count |
|---|---|---|
| `recognised_company` | Has a real canonical company name (`company_canonical` is not one of the two catch-all buckets) | 344 |
| `unrecognised_firm` | Catch-all bucket, but the assignee string is an **organisation** | 142 |
| `individual` | Catch-all bucket, and the assignee string is a **natural person** | 190 |

Method: a named canonical company always wins (this rescues `SAFRAN` and `PIPISTREL DOO`,
which the token classifier misses since neither carries a recognised legal-form token). For
the two catch-all buckets only, the assignee is split on `;`, trailing parentheticals are
stripped (`(US)`, `(PUYANG CITY, CN)`), and each party is tested for legal-form tokens
(`INC`, `GMBH`, `LTD`, `OOO`, `DOO`, `PTY` …), descriptive stems (`AVIAT`, `AERO`, `TECHNOL`,
`UNIV`, `INSTITUT` …), Cyrillic legal forms (`ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ`),
quoted trade names and digits.

**Validation.** The classifier was cross-checked against an independent signal — the overlap
between the `Assignee` and `Inventors` name tokens, on the principle that a self-filed patent
names the inventor as assignee. The two agree on **623 / 676**. The 53 disagreements were
inspected by hand and are artefacts of the *overlap* test, not the classifier: missing
`Inventors` values, waived-inventor notices ("THE INVENTOR HAS WAIVED THE RIGHT TO BE
MENTIONED"), and transliteration differences (`ACIKEL GUERKAN` vs `ACIKEL GURKAN`).

## 4. The rule applied

> **Batch_03** — every `recognised_company` patent (344), topped up to a round **400** with
> 56 `individual` patents.
> **Batch_04** — every `unrecognised_firm` patent (142) plus the remaining 134 `individual`
> patents = **276**.

Two decisions inside that rule, recorded because they were judgement calls, not deductions:

1. **Batch_03 was capped at 400, not left at 486.** Keeping the established 300–400 batch
   size was preferred over a clean "all organisations in one batch" split. The cost is that
   the 142 small/unrecognised firms sit in Batch_04.
2. **"Important company" was read as "recognised company"** — i.e. present in the
   `COMPANY_LOOKUP` table. This is admittedly a proxy: the table's contents decide the
   boundary, so a small firm that happens to be listed outranks a larger one that is not.
   The alternative (any organisation counts) was rejected because it would have put
   Batch_03 at 486 and diluted it with one-patent Chinese workshop filings.

**Which 56 individuals stayed in Batch_03:** those already assigned to Batch_03, selected by
ascending `patent_id`. The criterion is deliberately neutral — it exists only to avoid
physically relocating figure crops that were already in the right place, and carries no
claim that those 56 patents are more interesting than the other 134.

## 5. Result

|  | Batch_03 | Batch_04 |
|---|---|---|
| **Before** | 305 (100 company / 205 individual-bucket) | 371 (244 company / 127 individual-bucket) |
| **After** | **400** | **276** |
| recognised companies | 344 | 0 |
| unrecognised firms | 0 | 142 |
| individual filers | 56 | 134 |

Batch_03 now holds **47 distinct companies** — Porsche (63), Kitty Hawk (30), Lilium (29),
Shenfeng Aviation (24), Joby Aviation (20), Leonardo (17), Rolls-Royce (16), KARI (14),
Sikorsky (10), Safran (9), Mitsubishi (9), Karem Aircraft (9), NASA (6), Supernal (5),
Overair (5), NUAA (5), Lockheed Martin (4), Uber Elevate (4), and 29 more.

**393 patents changed batch** — 244 moved 04 → 03, 149 moved 03 → 04.

## 6. What was physically changed

| Artefact | Change |
|---|---|
| `data/Global Statistics/batches.xlsx` | `Batch_03` / `Batch_04` sheets rewritten; `Summary` counts refreshed; new `Reassignment_Note` sheet |
| `data/Global Statistics/BATCH_03_04_REASSIGNMENT_LOG.csv` | **new** — the ledger: 676 rows, one per patent, with `filer_class`, `old_batch_id`, `new_batch_id`, `moved`, `reason` |
| `00b2_figure_crops/Batch_03\|04/` | 391 patent crop folders physically moved between the two directories |
| `crops_mapping_Batch_03\|04.csv` | rows moved (2407/2178 → 2502/2083) |
| `needs_human_review_Batch_03\|04.csv` | rows moved (780/882 → 939/723) |
| `notebooks/00b1_grouping.ipynb` | warning banner added to cell 0 |

Backups (all alongside the originals): `batches.PRE_BATCH34_COMPANY_RESHUFFLE_20260817_183813.xlsx`,
`*.PRE_RESHUFFLE_<ts>.csv`, `00b1_grouping.PRE_BATCH34_RESHUFFLE_<ts>.ipynb`.

**Nothing downstream was invalidated.** `ml_predict_labels_Batch_03/04.xlsx` had not been
generated yet, so 01a will build the wizard feed from the new membership on its next run. No
wizard export, no 02a/02b output and no processed 518px image exists for either batch.

## 7. Verification

Checked after the change, all passing:

- 1639 patents across the 5 batches, **all `patent_id` unique — no duplicates**
- Batch_03 = 400, Batch_04 = 276; `Summary` agrees with the sheets
- Batches 01, 02, 05 identical to the backup, row for row, in the same order
- every `recognised_company` is in Batch_03; every `unrecognised_firm` is in Batch_04
- ledger membership matches the sheets exactly, both directions
- every crop folder on disk sits under the batch its patent now belongs to
- `crops_mapping` 4585 rows and `needs_human_review` 1662 rows preserved, none lost

## 8. Caveats

- **`company_canonical` was deliberately not corrected.** 124 patents still read
  `Unknown / Independent` while being real companies. Fixing it would mean editing
  `COMPANY_LOOKUP` and re-running the grouper, which would re-cut every batch including the
  three already labelled. Use `filer_class` in the ledger for any company/individual analysis;
  do not use `company_canonical` for that purpose.
- **Re-running `00b1_grouping.ipynb` cells 3 and 5 destroys this.** It regenerates
  `batches.xlsx` from the alphabetical rule and would desynchronise it from the crop folders
  already moved. Cells 1, 2 and 4 are safe. To recover, re-apply from the ledger CSV.
- Batch sizes are now 352 / 400 / 400 / 276 / 211. Batch_04 falls below the old
  `MIN_BATCH_SIZE = 300` convention; this is intended, not a bug.
