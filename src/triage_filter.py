"""
triage_filter.py — Stage 00a.2: SigLIP zero-shot triage of raw patent images.

Scores every raw image before Stage 00b (figure cropping) to flag non-drawing
content (tables, text pages, data grids) so the downstream figure-matcher only
receives genuine technical drawings.

THIS MODULE IS READ-ONLY WITH RESPECT TO THE RAW DIRECTORY.
No files are moved, copied, renamed, or deleted. Output is JSON/CSV manifests only.

Config requirement
------------------
Add the following to config.yaml under the ``paths`` section:

    triage: "{{ paths.base }}/triage"

SigLIP loading
--------------
Uses open_clip (same backend as src/cross_modal.py) for model consistency.
Loaded independently here — does NOT import cross_modal — to keep concerns separate.
"""

from __future__ import annotations

import json
import csv
from pathlib import Path

import torch
from PIL import Image

# ─── Prompts ──────────────────────────────────────────────────────────────────

_PROMPT_KEEP = "patent engineering drawing showing aircraft or vehicle structure and mechanical components with dimension lines and reference numerals"
_PROMPT_FLAG = "a flowchart, state diagram, block diagram, process flow, or text page with boxes and arrows but no mechanical drawing of physical parts"

# ─── Model loading ────────────────────────────────────────────────────────────

def load_siglip_model(cfg: dict) -> tuple:
    """
    Load SigLIP ViT-SO400M-14-SigLIP-384 via open_clip.

    Downloads ~3 GB of weights on first call (cached by HuggingFace Hub).
    Returns (model, processor, device).

    ``processor`` here is a (tokenizer, preprocess) pair stored as a tuple so
    callers can unpack it:  model, (tokenizer, preprocess), device = load_siglip_model(cfg)
    """
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:timm/ViT-SO400M-14-SigLIP-384"
    )
    tokenizer = open_clip.get_tokenizer("hf-hub:timm/ViT-SO400M-14-SigLIP-384")

    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    model = model.to(device).eval()
    print(f"[SigLIP] Loaded ViT-SO400M-14-SigLIP-384 on {device}")
    return model, (tokenizer, preprocess), device


# ─── Per-image scoring ────────────────────────────────────────────────────────

def score_image(
    img_path: Path,
    model,
    processor: tuple,
    device: str,
    threshold: float = 0.60,
) -> dict:
    """
    Run SigLIP zero-shot classification on a single image.

    Returns a dict with keys:
        file           – filename only (not the full path)
        pred           – "drawing" | "table" | "error"
        score_drawing  – softmax probability for the KEEP prompt
        score_table    – softmax probability for the FLAG prompt
        keep           – True when score_drawing >= threshold (fail-safe on error)
    """
    tokenizer, preprocess = processor

    try:
        img = preprocess(Image.open(img_path).convert("RGB")).unsqueeze(0).to(device)

        texts = tokenizer([_PROMPT_KEEP, _PROMPT_FLAG]).to(device)

        with torch.no_grad():
            img_feat  = model.encode_image(img)
            text_feat = model.encode_text(texts)

            # SigLIP uses sigmoid rather than softmax internally, but for a
            # two-class argmax either normalisation works; we use softmax so
            # the two scores sum to 1 and are easy to threshold.
            img_feat  = img_feat  / img_feat.norm(dim=-1, keepdim=True)
            text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)
            logits = (img_feat @ text_feat.T).squeeze(0)
            probs  = logits.softmax(dim=-1).cpu().tolist()

        score_drawing, score_table = probs[0], probs[1]
        pred = "drawing" if score_drawing >= score_table else "table"
        keep = score_drawing >= threshold

        return {
            "file": img_path.name,
            "pred": pred,
            "score_drawing": round(score_drawing, 4),
            "score_table":   round(score_table,   4),
            "keep": keep,
        }

    except Exception:
        # Fail safe: unknown images are always kept, never silently discarded.
        return {
            "file": img_path.name,
            "pred": "error",
            "score_drawing": 0.0,
            "score_table":   0.0,
            "keep": True,
        }


# ─── Per-patent triage ────────────────────────────────────────────────────────

def triage_patent(
    patent_id: str,
    raw_dir: Path,
    model,
    processor: tuple,
    device: str,
    threshold: float = 0.60,
) -> dict:
    """
    Score all .png files in raw_dir/patent_id/.

    Returns:
    {
        "patent_id": str,
        "total":     int,
        "flagged":   int,          # images where keep=False
        "figures":   [...]         # one score_image result per image, sorted by filename
    }

    Silently returns an empty result if the folder does not exist or has no PNGs.
    """
    patent_dir = raw_dir / patent_id
    if not patent_dir.is_dir():
        return {"patent_id": patent_id, "total": 0, "flagged": 0, "figures": []}

    png_files = sorted(patent_dir.glob("*.png"))
    if not png_files:
        return {"patent_id": patent_id, "total": 0, "flagged": 0, "figures": []}

    figures = [
        score_image(p, model, processor, device, threshold=threshold)
        for p in png_files
    ]
    flagged = sum(1 for f in figures if not f["keep"])

    return {
        "patent_id": patent_id,
        "total":     len(figures),
        "flagged":   flagged,
        "figures":   figures,
    }


# ─── Full-dataset triage ──────────────────────────────────────────────────────

def run_triage(
    cfg: dict,
    threshold: float = 0.60,
    limit: int | None = None,
) -> None:
    """
    Score every image in raw_dir, writing one JSON per patent and a summary CSV.

    Output locations (both under cfg["paths"]["triage"]):
        <patent_id>.json      — per-patent scores
        triage_summary.csv    — one row per patent: patent_id, total_images,
                                flagged_count, flagged_ratio

    Parameters
    ----------
    cfg       : config dict from load_config()
    threshold : score_drawing >= threshold → keep=True  (default 0.60)
    limit     : if set, process only the first N patent folders (for testing)
    """
    raw_dir    = Path(cfg["paths"]["raw_images"])
    triage_dir = Path(cfg["paths"]["triage"])
    triage_dir.mkdir(parents=True, exist_ok=True)

    model, processor, device = load_siglip_model(cfg)

    patent_dirs = sorted(p for p in raw_dir.iterdir() if p.is_dir())
    if limit is not None:
        patent_dirs = patent_dirs[:limit]

    summary_rows: list[dict] = []

    for patent_path in patent_dirs:
        patent_id = patent_path.name
        result    = triage_patent(patent_id, raw_dir, model, processor, device, threshold)

        if result["total"] == 0:
            continue

        # Write per-patent JSON
        out_json = triage_dir / f"{patent_id}.json"
        with open(out_json, "w") as fh:
            json.dump(result, fh, indent=2)

        summary_rows.append({
            "patent_id":     patent_id,
            "total_images":  result["total"],
            "flagged_count": result["flagged"],
            "flagged_ratio": round(result["flagged"] / result["total"], 4) if result["total"] else 0.0,
        })

        print(f"  ✓ {patent_id}  total={result['total']}  flagged={result['flagged']}")

    # Write summary CSV
    summary_csv = triage_dir / "triage_summary.csv"
    if summary_rows:
        fieldnames = ["patent_id", "total_images", "flagged_count", "flagged_ratio"]
        with open(summary_csv, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summary_rows)
        total_imgs    = sum(r["total_images"]  for r in summary_rows)
        total_flagged = sum(r["flagged_count"] for r in summary_rows)
        print(f"\nTriage complete: {len(summary_rows)} patents | "
              f"{total_imgs} images | {total_flagged} flagged "
              f"({100*total_flagged/max(1,total_imgs):.1f}%)")
        print(f"Summary written to: {summary_csv}")
    else:
        print("No patents processed.")


# ─── Re-threshold without re-scoring ─────────────────────────────────────────

def rethreshold_existing(
    cfg: dict,
    new_threshold: float,
) -> None:
    """
    Re-apply a new threshold to all existing triage JSONs without re-running SigLIP.

    Rules:
    - Images already marked keep=False are NEVER upgraded back to keep=True.
      (Confirmed discards stay discarded.)
    - Images currently keep=True are re-evaluated: if score_drawing < new_threshold
      they become keep=False.

    Updates every <patent_id>.json in-place and rewrites triage_summary.csv.
    """
    triage_dir = Path(cfg["paths"]["triage"])
    summary_rows = []

    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")
    if not json_paths:
        print("No triage JSONs found — run run_triage first.")
        return

    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)

        changed = 0
        for fig in data["figures"]:
            if not fig["keep"]:
                continue  # already discarded — never re-enable
            new_keep = fig["score_drawing"] >= new_threshold
            if not new_keep:
                fig["keep"] = False
                fig["pred"] = "table"
                changed += 1

        data["flagged"] = sum(1 for f in data["figures"] if not f["keep"])

        with open(json_path, "w") as fh:
            json.dump(data, fh, indent=2)

        summary_rows.append({
            "patent_id":     data["patent_id"],
            "total_images":  data["total"],
            "flagged_count": data["flagged"],
            "flagged_ratio": round(data["flagged"] / data["total"], 4) if data["total"] else 0.0,
        })
        if changed:
            print(f"  {data['patent_id']}: +{changed} newly discarded")

    summary_csv = triage_dir / "triage_summary.csv"
    fieldnames = ["patent_id", "total_images", "flagged_count", "flagged_ratio"]
    with open(summary_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    total_imgs    = sum(r["total_images"]  for r in summary_rows)
    total_flagged = sum(r["flagged_count"] for r in summary_rows)
    print(f"\nRe-threshold complete (threshold={new_threshold}): "
          f"{total_imgs} images | {total_flagged} flagged "
          f"({100*total_flagged/max(1,total_imgs):.1f}%)")
    print(f"Summary rewritten: {summary_csv}")


# ─── Reset threshold (re-derives keep from raw scores) ───────────────────────

def reset_threshold(
    cfg: dict,
    threshold: float,
) -> None:
    """
    Re-derive keep for every image purely from score_drawing >= threshold.

    Unlike rethreshold_existing, this works in BOTH directions — it can
    re-enable images that were over-discarded by a previous rethreshold call.
    Use this to correct an overly aggressive threshold.

    Rewrites all <patent_id>.json files and triage_summary.csv in-place.
    """
    triage_dir = Path(cfg["paths"]["triage"])
    summary_rows = []

    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")
    if not json_paths:
        print("No triage JSONs found — run run_triage first.")
        return

    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)

        for fig in data["figures"]:
            if fig["pred"] == "error":
                continue  # leave error entries untouched
            fig["keep"] = fig["score_drawing"] >= threshold
            fig["pred"] = "drawing" if fig["keep"] else "table"

        data["flagged"] = sum(1 for f in data["figures"] if not f["keep"])

        with open(json_path, "w") as fh:
            json.dump(data, fh, indent=2)

        summary_rows.append({
            "patent_id":     data["patent_id"],
            "total_images":  data["total"],
            "flagged_count": data["flagged"],
            "flagged_ratio": round(data["flagged"] / data["total"], 4) if data["total"] else 0.0,
        })

    summary_csv = triage_dir / "triage_summary.csv"
    fieldnames = ["patent_id", "total_images", "flagged_count", "flagged_ratio"]
    with open(summary_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    total_imgs    = sum(r["total_images"]  for r in summary_rows)
    total_flagged = sum(r["flagged_count"] for r in summary_rows)
    print(f"Reset complete (threshold={threshold}): "
          f"{total_imgs} images | {total_flagged} flagged "
          f"({100*total_flagged/max(1,total_imgs):.1f}%)")
    print(f"Summary rewritten: {summary_csv}")
