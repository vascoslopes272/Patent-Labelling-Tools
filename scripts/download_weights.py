"""
Download pre-trained HR-Net weights for figure segmentation.

Source: GoFigure-LANL/figure-segmentation (GitHub)
https://github.com/GoFigure-LANL/figure-segmentation

Run from the project root:
    python scripts/download_weights.py
"""

import requests
from pathlib import Path

GITHUB_URL = (
    "https://raw.githubusercontent.com/GoFigure-LANL/"
    "figure-segmentation/master/Pre-trained-weight/model-hrnet-new1.h5"
)
DEST = Path(__file__).resolve().parent.parent / "models" / "model-hrnet-new1.h5"


def main():
    if DEST.exists():
        size_mb = DEST.stat().st_size / (1024 * 1024)
        print(f"Weights already present: {DEST}  ({size_mb:.1f} MB)")
        return

    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading HR-Net weights from GitHub → {DEST}")

    resp = requests.get(GITHUB_URL, stream=True, timeout=120)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(DEST, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded / total * 100
                print(f"\r  {pct:.0f}%  ({downloaded // 1024} kB)", end="", flush=True)

    print()
    size_mb = DEST.stat().st_size / (1024 * 1024)
    print(f"Done. Saved {size_mb:.1f} MB to {DEST}")


if __name__ == "__main__":
    main()
