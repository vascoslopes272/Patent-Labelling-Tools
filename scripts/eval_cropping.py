"""
eval_cropping.py — ground-truth scoring harness for doclayout_matcher.py.

Without this, every threshold/constant change to the cropping pipeline is judged
by eyeballing a handful of crops — which is exactly how the clip-on-corner /
overlapping-isometric-figure regressions kept slipping back in. This script turns
"does this look better?" into three numbers you can diff across changes:

  - figure_count_accuracy: fraction of sheets where the number of saved crops
    matches the ground-truth figure count
  - label_accuracy:        fraction of GT figures whose label was correctly read
                           (matched by closest box overlap, not naming order)
  - clip_rate:             fraction of *labeled* (non-_Fu) saved crops where
                           _crop_touches_border still fires — i.e. crops that look
                           "done" but are silently slicing through real content

Usage:
    1. Pick ~30-50 sheets spanning your hard cases (overlapping isometric views,
       multi-rotor, rotated, light line-art, FAT files).
    2. Fill in a ground-truth JSON (see `write_template` below for the schema).
    3. Run:
         python scripts/eval_cropping.py --raw-dir /path/to/sheets \\
             --gt eval/ground_truth.json --out-dir /tmp/eval_crops

Re-run after any change to doclayout_matcher.py and diff the printed summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import doclayout_matcher as dm


def write_template(path: Path, raw_dir: Path) -> None:
    """Write a ground-truth JSON skeleton — one entry per image in raw_dir, ready to fill in."""
    sheets = sorted(p.name for p in raw_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"})
    template = {
        name: {"n_figures": None, "labels": []}   # fill labels with e.g. ["1", "2A", "2B"]
        for name in sheets
    }
    path.write_text(json.dumps(template, indent=2))
    print(f"Wrote template for {len(sheets)} sheets to {path}. Fill in n_figures + labels before scoring.")


def _label_matches(records: list[dict], gt_labels: list[str]) -> tuple[int, int]:
    """
    Match saved crop labels against GT labels by set membership (order-independent —
    naming doesn't promise GT ordering). Returns (n_correct, n_gt).
    """
    predicted = [r["label"] for r in records if r.get("label")]
    gt_remaining = list(gt_labels)
    correct = 0
    for lbl in predicted:
        if lbl in gt_remaining:
            gt_remaining.remove(lbl)
            correct += 1
    return correct, len(gt_labels)


def run_eval(raw_dir: Path, gt_path: Path, out_dir: Path, weights: str, device: str) -> None:
    gt = json.loads(gt_path.read_text())
    engine = dm.build_engine(weights=weights, device=device)

    n_sheets = 0
    n_count_correct = 0
    n_label_correct = 0
    n_label_total = 0
    n_clipped = 0
    n_labeled_crops = 0
    per_sheet_rows = []

    for name, entry in gt.items():
        if entry.get("n_figures") is None:
            continue   # not filled in yet — skip
        img_path = raw_dir / name
        if not img_path.exists():
            print(f"  ⚠ skipping {name} — not found in {raw_dir}")
            continue

        n_sheets += 1
        result = dm.process_image(engine, img_path, out_dir)
        records = result["crops"]

        pred_count = len(records)
        gt_count = entry["n_figures"]
        count_ok = pred_count == gt_count
        n_count_correct += int(count_ok)

        correct, total = _label_matches(records, entry.get("labels", []))
        n_label_correct += correct
        n_label_total += total

        sheet_clipped = 0
        sheet_labeled = 0
        for r in records:
            if r.get("needs_review"):
                continue
            sheet_labeled += 1
            crop_path = out_dir / r["output"]
            crop = dm.cv2.imread(str(crop_path))
            if crop is not None and dm._crop_touches_border(crop):
                sheet_clipped += 1
        n_clipped += sheet_clipped
        n_labeled_crops += sheet_labeled

        per_sheet_rows.append({
            "sheet": name, "pred_count": pred_count, "gt_count": gt_count,
            "count_ok": count_ok, "label_correct": correct, "label_total": total,
            "clipped": sheet_clipped, "labeled": sheet_labeled,
        })

    print(f"\n{'sheet':<45} {'count':>10} {'labels':>10} {'clipped':>10}")
    for row in per_sheet_rows:
        print(f"{row['sheet']:<45} "
              f"{row['pred_count']:>4}/{row['gt_count']:<5} "
              f"{row['label_correct']:>4}/{row['label_total']:<5} "
              f"{row['clipped']:>4}/{row['labeled']:<5}")

    print("\n── Summary ──────────────────────────────────────────")
    print(f"sheets scored:           {n_sheets}")
    if n_sheets:
        print(f"figure_count_accuracy:   {n_count_correct / n_sheets:.1%}  ({n_count_correct}/{n_sheets})")
    if n_label_total:
        print(f"label_accuracy:          {n_label_correct / n_label_total:.1%}  ({n_label_correct}/{n_label_total})")
    if n_labeled_crops:
        print(f"clip_rate:               {n_clipped / n_labeled_crops:.1%}  ({n_clipped}/{n_labeled_crops})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, required=True, help="directory of raw patent sheet images")
    ap.add_argument("--gt", type=Path, required=True, help="path to ground_truth.json (created with --write-template if missing)")
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/eval_crops"), help="where to write crops for this run")
    ap.add_argument("--weights", default=dm.DEFAULT_WEIGHTS)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--write-template", action="store_true",
                     help="write a ground-truth JSON skeleton to --gt instead of scoring")
    args = ap.parse_args()

    if args.write_template:
        write_template(args.gt, args.raw_dir)
        return

    if not args.gt.exists():
        print(f"{args.gt} does not exist — run with --write-template first.")
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    run_eval(args.raw_dir, args.gt, args.out_dir, args.weights, args.device)


if __name__ == "__main__":
    main()
