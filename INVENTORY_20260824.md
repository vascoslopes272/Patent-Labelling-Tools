# Inventory — repo + drive, 2026-08-24

What is live, what is finished, what can be archived, and what sits in the wrong place.
Classification is from evidence — `config.yaml` keys, `grep` over live code, and git —
not from filenames. **Nothing here has been moved or deleted.**

---

# A. Repo — `Patent-Labelling-Tools/`

## A1. Live — do not touch

| what | note |
|---|---|
| `config.yaml`, `.env`, `src/config_loader.py` | the config path everything actually uses |
| `src/` — `cross_modal` `reviewer` `excel_schema` `review_worklists` `processor` `vlm_extractor` `grouper` `triage_filter` `patseer_downloader` `extractor` `figure_cropping` `figure_labeling` `figure_matcher` `matcher` `doclayout_matcher` `cv_utils` `dinov2` `embedding_stats` `filtering` `gpu_worker` `review_gpu_worker` `wizard_feed_gpu_worker` `Rearranging th eexcell.py` | |
| `notebooks/` — `00a*` `00a1` `00a2` `00b1` `00b2` `01a_wizard_feed` `02a_preprocessing` `02a_legacy` `02b_postprocessing` | the pipeline |
| `notebooks/UI_..._15_3.html` | `paths.html_template` + `harness.js` both point here |
| `notebooks/UI_..._15_4.html` | the current labelling wizard |
| `scripts/` — `resolve_image_paths` `freeze_exports` `inject_pdf_links` `flag_missing_downloads` `inject_missing_images` `legacy_roundtrip_harness/` `overnight_audit` `smoke_test_vlm` `clipboard_watch.sh` `download_weights` `eval_cropping` `migrate_labels_to_excel` | |
| `tests/` | 39 pass, 1 pre-existing error |
| `models/` (20 GB: Qwen 16G, SigLIP 3.3G, SBERT 837M) | model caches, gitignored |
| `timer.py`, `assets/no_image_available.png` | |

## A2. Dead — nothing reads them

| what | evidence |
|---|---|
| **`config_loader.py`** (top level, 300 B) | defines `get_drive_root()`; **nothing imports it**. `main.py` and every notebook use `src/config_loader.py` instead. `DRIVE_PATH` in `.env` is read only by this dead file |
| **`Patent-Labelling-Tools/`** (nested inside itself) | holds one file, `timer_analysis.log` → belongs in `overnight_logs/` |
| `__pycache__/`, `.pytest_cache/`, `src/__pycache__`, `scripts/__pycache__` | regenerable (some `.pyc` are *tracked* in git — worth a `git rm --cached`) |

## A3. Archivable — superseded, safe to move to an `archive/` folder

**Old wizard versions.** No live code reads them; the only references are three
*markdown prose* lines in `02a_preprocessing` cells 20/24/26 (historical context) and one
comment in `config.yaml`:
`UI_..._13_0.html` · `UI_..._14_0.html` · `UI_..._15_2.html`

**Backups (21 files).** HEAD `c6a6a51` now contains every current version, so anything
older than today is redundant with git history:
- `src/*.PRE_HORIZSTAB_20260806*` and `*.PRE_RMECH3_20260806*` (6 files)
- `src/review_worklists.PRE_T1REASON_20260823*`
- `scripts/resolve_image_paths.PRE_BAREDIR_20260823*`
- `notebooks/02a_preprocessing.PRE_CLEANUP_20260823*`, `.PRE_T1REASON_20260823*`
- `config.yaml.PRE_FOLDER_RENAME_20260805`
- *today's* `PRE_TPTR` / `PRE_5CSYNC` / `PRE_5BSIZE` / `PRE_MLMETA` / `PRE_BOOMCOUNT` — **keep these a few days**, then drop

**Already archived, leave as-is:** `notebooks/archive/` (`01_review`, `02_taxonomy_review`,
`test_doclayout_extraction`), `src/_archive/`

**`notebooks/outputs/`** — six one-off files from 2026-06-16 (`1639_DS_audit.xlsx`,
patseer prompt txts). Finished; nothing reads them.

## A4. Docs — current vs finished

| keep | finished — archivable |
|---|---|
| `README.md` | `AUDIT_CODEBOOK_V2_STATUS.md` (v14 era) |
| `REVIEW_01_METHODOLOGY.md` (thesis material) | `prompt_html_v13_to_v14.md` (task prompt, executed) |
| `batch_audit_v154.md` (today) | `prompt_notebook_02a.md` (task prompt, executed) |
| `BATCH_03_04_REORGANISATION.md` | `UI_CHANGES_STATUS.md` (2026-07-01) |
| `PREFLIGHT_02A_20260824.md` | `OVERNIGHT_STATUS.md` (2026-07-01) |
| `PLAN_BATCH02_AND_LEGACY_CONFORMANCE.md` — mostly executed, check before filing | |

---

# B. Drive — `/mnt/storage_11tb/Drive_files_to_syncronize`

## B1. Live — the 1639_DS pipeline (every path below is a `config.yaml` key)

| folder | size | key |
|---|---|---|
| `1639_DS/00a_raw_downloads` | 875 M | `raw_images` |
| `1639_DS/00a2_triage_json` | 6.5 M | `triage` |
| `1639_DS/00b2_figure_crops` | 1.5 G | `matched` |
| `1639_DS/02b_POSTlabel_processed_518px` | 65 M | `processed` |
| `1639_DS/data/00b2_crops_and_01a_MACHINE_feed` | 7.2 M | `data_matched` |
| `1639_DS/data/02b_POSTlabel_manifests` | 312 K | `data_processed` |
| `1639_DS/data/03_HUMAN_wizard_exports` | 39 M | `html_review_exports` — **frozen, chmod 444** |
| `1639_DS/data/03c_CORRECTED_wizard_exports` | 25 M | `corrected_wizard_exports` — 02a's input |
| `1639_DS/data/02a_CLEANED_label_tables` | empty | `cleaned_label_tables` — 02a's output, 02b's input |
| `1639_DS/data/03b_CONFORMED_legacy` | 848 K | 02a_legacy outputs + `proposals/` |
| `1639_DS/data/Global Statistics` | 135 M | `batches_xlsx` |
| `1639_DS/data/citation_text_cache` | 3.9 M | |

> **`1639_DS/matched` and `1639_DS/processed` are symlinks and are LOAD-BEARING.**
> 5466 absolute `Image_Path` cells in `reviewed_patents_Batch_01.xlsx` (and every
> `src_path`/`dst_all`/`dst_main` in the Batch_01 manifest) contain `/matched/` and
> `/processed/`. Do not delete them until those stored paths are rewritten.

## B2. Concluded — safe to archive

| what | size | evidence |
|---|---|---|
| **`1639_DS.zip`** | **2.0 GB** | 2026-07-06 snapshot, i.e. *before* the 2026-08-05 folder rename. Nothing in any `.py`/`.yaml` references it. Biggest single win |
| **`1639_DS/data/_TEMP_v154_review`** | 162 M | its own README: *"Copies only. Nothing here is read by any pipeline stage. Delete when the decisions are made."* The decisions are made — `batch_audit_v154.md` is written and boomSplit was dropped |
| **`1639_DS/ARCHIVED_POSTlabel_approved_by_company`** | 445 M | `config.yaml` itself: *"Verified 2026-08-05: NOTHING in live code reads this key."* Presentation copy only |
| `HANDOFF_batches_01_02_05.md` | 0 B | empty since 2026-08-18 |
| `Image_Chose_&_Save_PAdding_Enhanced_224x224.ipynb` | 113 K | 2026-05-06, the 224px era — superseded by the 518px `processor.py` pipeline |

## B3. Other datasets — not part of this pipeline

`1627_DS` (kept: page crops are used by hand to identify FIG ids — see the manual-crop
workflow) · `521_Patents_DataSet_1st_big_DataSet` (superseded) · `DeepPatent2` (external)

## B4. Dead `config.yaml` keys

| key | points at | status |
|---|---|---|
| `structured` | `UNUSED_structured` | never existed on disk. **Cannot delete yet** — `00b1_grouping` cell 1 prints it and would `KeyError` |
| `text` | `UNUSED_text` | never existed. Safe to delete |
| `reviewed_excel` | `UNUSED_reviewed_patents.xlsx` | never existed. Only the archived `02_taxonomy_review.ipynb` reads it. Safe to delete |
| `reviewed` | `ARCHIVED_POSTlabel_approved_by_company` | folder exists, nothing reads the key |

---

# C. Suggested moves

```
# repo
mv Patent-Labelling-Tools/timer_analysis.log overnight_logs/ && rmdir Patent-Labelling-Tools
rm config_loader.py                        # dead; src/config_loader.py is the real one
mkdir -p archive/{wizards,backups,docs}
mv notebooks/UI_..._{13_0,14_0,15_2}.html  archive/wizards/
mv src/*.PRE_*2026080*.bak scripts/*.PRE_*2026082*.bak archive/backups/
mv AUDIT_CODEBOOK_V2_STATUS.md prompt_*.md UI_CHANGES_STATUS.md OVERNIGHT_STATUS.md archive/docs/
git rm --cached -r src/__pycache__          # .pyc files are currently tracked

# drive  (biggest win first)
mv "3 - Images DataSets & Labelling Outputs/1639_DS.zip"            <cold storage>   # 2.0 GB
mv "…/1639_DS/data/_TEMP_v154_review"                               <cold storage>   # 162 M
mv "…/1639_DS/ARCHIVED_POSTlabel_approved_by_company"               <cold storage>   # 445 M
```

Total reclaimed from the drive: **~2.6 GB**, none of it read by any pipeline stage.

**Do not touch:** the `matched` / `processed` symlinks, `03_HUMAN_wizard_exports/`,
or anything under B1.
