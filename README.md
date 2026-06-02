# patseer_drawing_pipeline

Patent drawing dataset pipeline for eVTOL patents (dataset 1635).
Downloads figures from PatSeer, OCR-labels each image, matches it to
its description line, and assembles per-patent JSON ready for DINOv2 embedding.

## Stage order

| # | Notebook | src module | What it does |
|---|----------|-----------|--------------|
| 00 | `00_image_extractor.ipynb` | `extractor.py` | Selenium download of drawings + Excel metadata |
| 01 | `01_review.ipynb` | `ocr_labeler`, `matcher`, `reviewer` | OCR → match → JSON assembly + review table |
| 02 | `02_processing.ipynb` | `processor.py` | Pad to square + resize to 518×518 |
| 03 | `03_filtering.ipynb` | `filtering.py` | Remove blank / tiny / duplicate images |
| 04 | `04_dinov2.ipynb` | `dinov2.py` | DINOv2 embeddings (facebook/dinov2-base) |
| 05 | `05_embedding_stats.ipynb` | `embedding_stats.py` | PCA / UMAP / clustering |

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
