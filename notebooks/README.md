# Notebooks — what each one does

Read this before opening any of them. Every notebook is a **stage**: it reads
some files, writes some files, and hands off to the next one. Nothing here is
run automatically — you open one, set the batch number at the top, and run it.

Open notebooks **from the repo root** so `src/` is importable. Each one puts the
repo root on `sys.path` itself, so this works from anywhere inside the repo.

---

## The main line

Run in this order. The arrow is "writes the file the next one reads".

```
00a   download          PatSeer → raw/ images, one folder per patent
 ↓
00a2  triage            drop images that aren't technical drawings (SigLIP)
 ↓
00b1  grouping          assign company + prototype cluster + batch → batches.xlsx
 ↓
00b2  crop & match      cut sheets into single figures, match to "FIG. n" lines
 ↓
01a   wizard feed       pre-label T1 + find duplicates → ml_predict_labels_<batch>.xlsx
 ↓
      [ HUMAN REVIEW in the HTML wizard → reviewed_patents_<batch>.xlsx ]
 ↓
02a   preprocessing     validate and clean the human export
 ↓
02b   postprocessing    pad + resize approved images to 518×518 for DINOv2
```

| # | Notebook | Reads | Writes |
|---|---|---|---|
| 00a | `00a_patseer_download_&_Label_matching` | PatSeer search results (Selenium) | `raw/<patent>/*.png` + a manifest per patent |
| 00a2 | `00a2_triage_filter` | `raw/` | `triage/` — scores every image, drops tables / text pages / title sheets before the expensive stages |
| 00b1 | `00b1_grouping` | PatSeer export | `data/.../batches.xlsx` — one sheet per batch, with `company_canonical` and `prototype_label` |
| 00b2 | `00b2_figure_crop_&_Brief_DD_matching` | `raw/`, PatSeer export | `matched/<batch>/<patent>/` cropped figures + `data/descriptions.csv` |
| 01a | `01a_wizard_feed` | `batches.xlsx`, `matched/` | `ml_predict_labels_<batch>.xlsx` — T1 pre-labels + duplicate flags for the HTML wizard |
| 02a | `02a_preprocessing` | the wizard's `reviewed_patents_<batch>.xlsx` | `Review_postprocess_<batch>_<ts>.xlsx` — validated and cleaned |
| 02b | `02b_postprocessing` | 02a's output | `processed/<batch>/` — padded + resized images |

## Side branches

These do not feed the image pipeline. Run them whenever you like.

| # | Notebook | What it is for |
|---|---|---|
| 00a1 | `00a1_dataset_audit` | Checks `raw/` against the PatSeer export: what downloaded, what is missing, what has a mismatched name. Run after 00a, or any time downloads look wrong. |
| 00a1 | `00a1_dataset_overview` | Bird's-eye counts at every stage — how many patents and images survive each step. Good for a status figure in the thesis. |
| **03a** | **`03a_aircraft_identity`** | **Metadata only, no images.** Which real aircraft each patent relates to, what the patent is about, and how mature it is → `aircraft_identity_<batch>.xlsx`. See below. |

## Archived

`archive/` holds superseded notebooks kept for reference — `01_review`
(replaced by `01a_wizard_feed` plus the HTML wizard), `02_taxonomy_review`
(replaced by the HTML wizard itself), and a DocLayout-YOLO experiment. **Do not
run these**; they write to paths the current pipeline no longer uses.

---

## Stage 03a in detail

`03a_aircraft_identity` is the newest stage and the only one that reads no
images. It joins the wizard's human T1 record (approval, `aircraftName`,
duplicates, read from `03c_CORRECTED_wizard_exports`) onto the PatSeer
metadata and asks the reviewer three questions per patent, each with the
sentence the machine answer came from:

| Decision | Machine columns | Citation | Reviewer types into |
|---|---|---|---|
| Real aircraft name | `aircraft_group` (never empty), `aircraft_name` (proposal), `aircraft_name_in_text` | `aircraft_name_section` / `_quote` | `aircraft_name_human` |
| Electric? | `is_electric`, `powertrain` | `powertrain_section` / `_quote` | `is_electric_human` (No = disapproved) |
| VTOL? | `takeoff_mode` VTOL / STOL / V/STOL / CTOL | `takeoff_section` / `_quote` | `takeoff_human` (STOL = disapproved) |

`*_final` = the human value when typed, else the machine value. Every
`*_human` cell, `review_status`, `notes` survives a re-run
(`identity_excel.merge_preserving_human`).

`aircraft_group` follows the annotator's naming scheme (`src/wizard_link.py`):
wizard `aircraftName` → inherited from the duplicate's original (D1/D2 = same
aircraft) → original + letter (D3 = variant) → `<assignee> <N>` generated, `N`
unique across the whole corpus. A D1/D2 whose wizard name differs from its
original's is flagged in `aircraft_group_note`.

Also on the sheet, informative only: geography, dates (`priority_year`,
`app_year`, `pub_year`, `snapshot_date`), legal stage from the export's
*Legal Status Current* column, citations and maturity tiers, scope /
architecture predictions, specs, blade counts.

Output: `<data_matched>/<Batch_NN>/aircraft_identity_<Batch_NN>.xlsx` — sheets
**Identity** (one row per patent), **Figures** (one row per figure),
**Evidence** (every candidate every signal proposed), **LLM_Prompts**, and
**README** (the column dictionary and the review contract).

Quotes are searched in five sections only — Title, Abstract, First claim,
Summary of invention, Description of drawings. The full Description is not
loaded, so `aircraft_name_in_text = No` means "not in those five".

**Reviewing without Excel:** open `notebooks/post-process/03a_identity_review.html` in Chrome
(all the review pages — identity, scope sample, 03b architecture, names — live in `notebooks/post-process/`)
(same SheetJS CDN as the wizard, so it needs the network once), pick the
`1639_LABELLED/labels` folder, choose a batch. It walks the `review_queue` rows
one patent at a time with the figures on the left and the four decisions on
the right — each with the machine's proposal and the sentence it came from —
and buttons instead of typed codes. Answers persist in the browser; **Export**
writes `aircraft_identity_Batch_NN.xlsx` to Downloads with the `*_human`
columns filled. Move it over `labels/Batch_NN/` and re-run notebook cells 4–9
to refresh the queue and the colours.

**Electric is decided by the burden of proof** (`PRESUME_ELECTRIC = True`). It is
easy to show an aircraft is *not* electric — one committed sentence naming a
turbine or piston engine as the propulsion — and nearly impossible to show it
*is*, because every aircraft has an electric motor somewhere. So
`classify_powertrain` collects every family the text states: a combustion
statement decides (queued for confirmation, a machine never disapproves); a
hybrid statement is Hybrid; both combustion and electric stated abstains and
quotes both (`powertrain_other_quote`); nothing stated is *presumed* electric
(`is_electric_source = presumed`) and not queued. Prior-art sentences and
"or an engine" hedges never count as statements.

`USE_SBERT = True` (the default) fills `powertrain`, `scope`, `innovation_field`
and `industry_primary` for the rows the keyword pass could not answer — with it
off, roughly 70 % of `powertrain` cells stay Unknown. Those values come from
cosine similarity rather than a literal match, so their `*_section` reads
`sbert (no literal sentence)` and there is no quote to read. The name proposal,
the take-off mode and a keyword-matched powertrain always cite a real sentence,
SBERT or not.

Full explanation of the signals and their precedence: the repo `README.md`.

---

## House style

Every notebook here follows the same shape, and 03a is the cleanest example:

- **Logic lives in `src/`, not in cells.** A notebook is a recipe — set the
  knobs, call the functions, look at the output. If a cell grows past ~30
  lines, its body belongs in a `src/` module where it can be tested.
- **One config cell at the top** with the batch number and the switches, so you
  never have to hunt through the notebook to change a setting.
- **Every prediction carries `*_source` and `*_confidence`.** No stage in this
  pipeline writes a bare value; you can always tell where a number came from and
  how much to trust it.
- **Re-running is safe.** Outputs are backed up with a timestamp before being
  overwritten, and hand-made corrections survive.

## Known housekeeping

- `00a1_dataset_audit` and `00a1_dataset_overview` share the number `00a1` but
  are different notebooks.
- `02a_preprocessing` has two timestamped backup copies alongside it
  (`.PRE_DRAFTMIGFIX_…`, `.PRE_RULEB_QUALFLAGS_…`). Only
  `02a_preprocessing.ipynb` is current.
