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
images. It answers, per patent:

| Question | Key columns |
|---|---|
| What is the patent about, at what level? | `scope` — whole aircraft / subsystem / component |
| Which architecture(s)? | `architecture_primary`, `architecture_all`, `architecture_count`, `architecture_pure` |
| Tied to one real aircraft? | `specificity`, **`aircraft_link`** |
| Which aircraft? | `aircraft_name` |
| Electric? | `is_electric`, `powertrain` |
| Its numbers? | `pax`, `mtow_kg`, `range_km`, …, `blades_primary`, `blades_all` |
| Where / what for? | `assignee_country`, `region`, `pub_office`, `industry_primary` |
| Accepted, or only filed? | `legal_stage`, `maturity_tier`, `impact_tier`, citations |

Output: `<data_matched>/<Batch_NN>/aircraft_identity_<Batch_NN>.xlsx` — sheets
**Identity** (one row per patent), **Figures** (one row per figure),
**Evidence** (every candidate every signal proposed), **LLM_Prompts**, and
**README** (the column dictionary).

**The one rule:** filter `aircraft_link == "Depicted"` before any statistic
grouped by aircraft. `CompanyAttributed` means "Joby filed this and Joby makes
the S4" — real evidence about the *company*, not about that aircraft's design.

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
