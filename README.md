# patseer_drawing_pipeline

Patent drawing dataset pipeline for eVTOL patents (dataset 1635).
Downloads figures from PatSeer, OCR-labels each image, matches it to
its description line, and assembles per-patent JSON ready for DINOv2 embedding.

## Stage order

| # | Notebook | src module | What it does |
|---|----------|-----------|--------------|
| 00a | `00a_patseer_download.ipynb` | `patseer_downloader.py` | Selenium download from PatSeer → canonical filenames + manifest JSON |
| 00b | `00b_figure_crop_&_Brief_DD_matching.ipynb` | `figure_matcher.py`, `extractor.py` | Export descriptions CSV + positional matching of figures to description keys; renames to `_F` / `_Fu` |
| 00 | `00_image_extractor.ipynb` | `extractor.py` | Legacy EPO/Google Patents download + Excel metadata (Stage 01 fallback path) |
| 01 | `01_review.ipynb` | `ocr_labeler`, `matcher`, `reviewer` | OCR → match → JSON assembly + review table (Stage 01 fallback) |
| 02 | `02_processing.ipynb` | `processor.py` | Pad to square + resize to 518×518 |
| 03 | `03_filtering.ipynb` | `filtering.py` | Remove blank / tiny / duplicate images |
| 04 | `04_dinov2.ipynb` | `dinov2.py` | DINOv2 embeddings (facebook/dinov2-base) |
| 05 | `05_embedding_stats.ipynb` | `embedding_stats.py` | PCA / UMAP / clustering |

### PatSeer pipeline (00a → 00b)

The preferred path for the 1635-patent dataset.  Runs independently of the
legacy 00 → 01 flow.

```
00a_patseer_download   Downloads img / D / FAT files; saves manifest per patent
        ↓
00b_figure_matching    Splits D/FAT sheets at whitespace bands; assigns _F / _Fu
        ↓
02_processing          (same as legacy path onwards)
```

### Aircraft identity (03a) — side branch, metadata only

`03a_aircraft_identity.ipynb` + `src/aircraft_identity.py` +
`src/patent_scope.py` answer a different question from the rest of the
pipeline: not *what does this drawing show*, but *what is this patent about, at
what level, which architecture, is it tied to one real aircraft, is that
aircraft electric, what are its numbers, and where and for what industry was it
filed*.

It reads `batches.xlsx` and the PatSeer export only — no images, no figure
crops — so it runs independently of 00a/00b/01a and writes exactly one file of
its own per batch:

```
<data_matched>/<Batch_NN>/aircraft_identity_<Batch_NN>.xlsx
    Identity     one row per patent (join on patent_id)
    Figures      one row per figure — what KIND of view each one is
    Evidence     every candidate every signal proposed, with its context
    LLM_Prompts  a ready-made question per patent for the chat step
    README       column dictionary
```

#### Scope, architecture and specificity (`src/patent_scope.py`)

Most patents in the corpus are not about a whole aircraft — they claim a
subsystem or a component, and their drawings put it on a throwaway airframe.
Three columns say so, over the taxonomies the pipeline already uses
(`reviewer._T1_SCOPE_DEFS`, `_T1_FIELD_DEFS`, `_G1_TOP_TYPE_DEFS` +
`classify_g1_keyword`), imported rather than restated:

| Column | What it says |
|---|---|
| `scope` | Whole Aircraft Architecture / Architectural Subsystem Enabler / Component-Level Generic |
| `innovation_field` | Aero-structural, mechanical-kinematic, propulsion-electrical, control-avionics |
| `architecture_primary` / `architecture_all` / `architecture_count` / `architecture_pure` | Which configuration(s) the patent represents, and how many. Several means it enumerates alternatives rather than describing one vehicle. `architecture_count` / `architecture_pure` are predicted starting values for the wizard's manual `archCount` / `notPureArch`. |
| `specificity` | SpecificAircraft / ArchitectureGeneric / IllustrativeOnly |
| `aircraft_link` | **Depicted** — the patent's figures show that aircraft. **CompanyAttributed** — the company makes it, but this patent is about a subsystem/component and its figures are not evidence of it. **None**. |

`aircraft_link` exists because the gazetteer matches on **company**. Without it,
a Joby patent on a motor bearing is labelled `aircraft_name = S4` at confidence
0.95 and every statistic grouped by aircraft inherits that error. The name is
kept — it is real evidence about the company — but the column says which kind of
claim it is. **Filter `aircraft_link == "Depicted"` before any per-aircraft
statistic.**

`specificity` is an additive score over four named signals (granularity,
architecture multiplicity, hedging density, and what the figures show) with two
thresholds in `patent_scope.py`. Deliberately a stated rule rather than a
learned classifier: it fits in four lines of a methodology chapter, every input
is exported as its own column, and `specificity_reason` records exactly which
signals fired and with what weight — so re-thresholding is a spreadsheet filter,
not a re-run.

Four signals per field, merged by a fixed precedence
(`human > gazetteer > llm > sbert > keyword > regex`), each field carrying its
own `*_source` and `*_confidence`:

| Signal | Where it comes from |
|---|---|
| `gazetteer` | `reference/evtol_gazetteer.csv` — curated company → aircraft table, matched on canonical company + filing year. The only source precise enough to carry a spec number into the thesis. |
| `llm` | An LLM asked "which aircraft was *company* flying around *year*?" — via exported prompts you paste into a chat (default, no API key), or the Anthropic API. |
| `sbert` | PatentSBERTa zero-shot over the anchors in `aircraft_identity.py`, reusing `reviewer._sbert_best()`. |
| `keyword` / `regex` | Propulsion keywords, spec numbers next to their unit, candidate model designations. |

Two things about it are deliberate and worth knowing before you read the
output: **most patents never name the aircraft** (applicants write "an aircraft
100" on purpose), so an empty `aircraft_name` is usually the correct answer
rather than a failure; and the **shipped gazetteer carries no spec numbers** —
every numeric cell is blank with a `spec_source` column for you to fill from a
citable source.

Correct anything by hand in the Identity sheet and set that field's `*_source`
to `human`; re-running the notebook backs the file up and keeps your edits.

## Setup

```bash
pip install -r requirements.txt
# also install tesseract-ocr system package:
# Ubuntu: sudo apt install tesseract-ocr
# Mac:    brew install tesseract
```

## Running from the terminal

```bash
# Stage 00 — scan first 10 records (notebook 00 equivalent)
python main.py stage00 --scan

# Stage 00 — full run (all 162 records)
python main.py stage00

# Stage 01 — OCR + matching + JSON assembly
python main.py stage01
```

## Running notebooks

Open each notebook from the repo root so that `src/` is on the path.
All notebooks add the repo root to `sys.path` automatically.

## Data layout (external, not in repo)

```
/mnt/storage_11tb/.../1635/
├── raw/          # downloaded images — one subfolder per patent_id
│   └── US2022267016A1/
│       ├── fig_01.png
│       └── fig_02.png
├── text/         # description text per patent — <patent_id>.txt
├── labels/       # assembled JSON per patent — <patent_id>.json
└── processed/    # padded + resized images (stage 02)
```

## Config

All paths and parameters live in `config.yaml`.
`paths.base` points at the external storage root.
`extractor.search_base_url` is the PatSeer search result URL (already set to the 1635 search).
