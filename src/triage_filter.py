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

def _best_cuda_device() -> str:
    """Return the cuda device index with the most free VRAM, as 'cuda:N'."""
    best_idx, best_free = 0, 0
    for i in range(torch.cuda.device_count()):
        free = torch.cuda.mem_get_info(i)[0]
        if free > best_free:
            best_free, best_idx = free, i
    return f"cuda:{best_idx}"


def load_siglip_model(cfg: dict) -> tuple:
    """
    Load SigLIP ViT-SO400M-14-SigLIP-384 via open_clip.

    Speed optimisations applied here:
    - fp16: halves VRAM (~1.7 GB vs ~3.3 GB) and uses tensor-core GEMM on RTX cards.
    - GPU selection: picks the CUDA device with the most free VRAM, so it coexists
      with Qwen (or any other model) loaded on the other GPU.
    - Pre-computed text embeddings: the two prompt embeddings are computed once at
      load time and stored in the returned processor tuple. score_image() and
      score_batch() reuse them directly — no redundant encode_text() per image.

    Weights are cached in cfg["paths"]["siglip_cache"] (models/SigLIP/).
    Returns (model, processor, device) where processor = (preprocess, text_feats).
    """
    import os
    import open_clip

    cache_dir = Path(cfg["paths"]["siglip_cache"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_CACHE"] = str(cache_dir)
    print(f"[SigLIP] Cache: {cache_dir}")

    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:timm/ViT-SO400M-14-SigLIP-384"
    )
    tokenizer = open_clip.get_tokenizer("hf-hub:timm/ViT-SO400M-14-SigLIP-384")

    if torch.cuda.is_available():
        device = _best_cuda_device()
        torch.backends.cudnn.benchmark = True  # fixed 384x384 input size — safe speedup
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    model = model.to(device, dtype=torch.float16).eval()

    # Pre-compute and normalise text embeddings once — reused for every image.
    with torch.no_grad():
        text_tokens = tokenizer([_PROMPT_KEEP, _PROMPT_FLAG]).to(device)
        text_feats  = model.encode_text(text_tokens).float()
        text_feats  = text_feats / text_feats.norm(dim=-1, keepdim=True)
        text_feats  = text_feats.half()   # keep in fp16 for dot-product consistency

    free_gb = torch.cuda.mem_get_info(torch.device(device).index)[0] / 1e9
    print(f"[SigLIP] Loaded fp16 on {device}  ({free_gb:.1f} GB VRAM remaining)")
    return model, (preprocess, text_feats), device


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _make_result(name: str, probs: list[float] | None, threshold: float) -> dict:
    """Build a standardised result dict from a [score_drawing, score_table] pair."""
    if probs is None:
        return {"file": name, "pred": "error", "score_drawing": 0.0, "score_table": 0.0, "keep": True}
    s_draw, s_tab = probs[0], probs[1]
    return {
        "file":          name,
        "pred":          "drawing" if s_draw >= s_tab else "table",
        "score_drawing": round(s_draw, 4),
        "score_table":   round(s_tab,  4),
        "keep":          s_draw >= threshold,
    }


def score_batch(
    img_paths: list[Path],
    model,
    processor: tuple,
    device: str,
    threshold: float = 0.60,
) -> list[dict]:
    """
    Score a batch of images in a single forward pass.

    processor = (preprocess, text_feats) as returned by load_siglip_model().
    text_feats are pre-normalised fp16 tensors — no encode_text() call per batch.
    Any image that fails to load falls back to keep=True (fail-safe).
    """
    preprocess, text_feats = processor
    results: list[dict] = []

    tensors, valid_names, failed_names = [], [], []
    for p in img_paths:
        try:
            tensors.append(preprocess(Image.open(p).convert("RGB")))
            valid_names.append(p.name)
        except Exception:
            failed_names.append(p.name)

    if tensors:
        batch = torch.stack(tensors).to(device, dtype=torch.float16)
        with torch.no_grad():
            img_feats = model.encode_image(batch).float()
            img_feats = img_feats / img_feats.norm(dim=-1, keepdim=True)
            logits = (img_feats.half() @ text_feats.T)
            probs  = logits.softmax(dim=-1).cpu().tolist()
        for name, p in zip(valid_names, probs):
            results.append(_make_result(name, p, threshold))

    for name in failed_names:
        results.append(_make_result(name, None, threshold))

    order = {p.name: i for i, p in enumerate(img_paths)}
    results.sort(key=lambda r: order.get(r["file"], 9999))
    return results


def score_image(
    img_path: Path,
    model,
    processor: tuple,
    device: str,
    threshold: float = 0.60,
) -> dict:
    """Score a single image. Thin wrapper around score_batch for API compatibility."""
    return score_batch([img_path], model, processor, device, threshold)[0]


class _PatentDataset(torch.utils.data.Dataset):
    """Minimal Dataset for parallel image loading via DataLoader workers."""
    def __init__(self, paths: list[Path], preprocess):
        self.paths     = paths
        self.preprocess = preprocess

    def __len__(self): return len(self.paths)

    def __getitem__(self, idx):
        p = self.paths[idx]
        try:
            tensor = self.preprocess(Image.open(p).convert("RGB"))
            return tensor, p.name, True   # (tensor, name, ok)
        except Exception:
            # Return a zero tensor so the DataLoader batch stays uniform
            dummy = torch.zeros(3, 384, 384)
            return dummy, p.name, False


def score_all(
    img_paths: list[Path],
    model,
    processor: tuple,
    device: str,
    threshold: float = 0.60,
    batch_size: int = 48,
    num_workers: int = 8,
) -> list[dict]:
    """
    Score a large list of images using parallel I/O + batched GPU inference.

    num_workers DataLoader workers preprocess images on CPU while the GPU runs
    the previous batch — hides the I/O bottleneck for large patent folders.
    Results are returned in the same order as img_paths.
    """
    preprocess, text_feats = processor
    dataset = _PatentDataset(img_paths, preprocess)
    loader  = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=num_workers,
        pin_memory=device.startswith("cuda"),
        prefetch_factor=2 if num_workers > 0 else None,
    )

    results_map: dict[str, dict] = {}

    for tensors, names, oks in loader:
        names = list(names)
        oks   = oks.tolist()

        # Split valid / failed within the batch
        valid_idx = [i for i, ok in enumerate(oks) if ok]
        if valid_idx:
            valid_tensors = tensors[valid_idx].to(device, dtype=torch.float16)
            valid_names   = [names[i] for i in valid_idx]
            with torch.no_grad():
                img_feats = model.encode_image(valid_tensors).float()
                img_feats = img_feats / img_feats.norm(dim=-1, keepdim=True)
                logits    = (img_feats.half() @ text_feats.T)
                probs     = logits.softmax(dim=-1).cpu().tolist()
            for name, p in zip(valid_names, probs):
                results_map[name] = _make_result(name, p, threshold)

        for i, (name, ok) in enumerate(zip(names, oks)):
            if not ok:
                results_map[name] = _make_result(name, None, threshold)

    # Return in original order
    return [results_map[p.name] for p in img_paths]


# ─── Per-patent triage ────────────────────────────────────────────────────────

def triage_patent(
    patent_id: str,
    raw_dir: Path,
    model,
    processor: tuple,
    device: str,
    threshold: float = 0.60,
    batch_size: int = 48,
    num_workers: int = 8,
) -> dict:
    """
    Score all .png files in raw_dir/patent_id/ using batched inference.

    batch_size=48 is tuned for an 11 GB GPU with SigLIP fp16 (~1.7 GB weights) —
    plenty of headroom. Lower it if you see OOM, raise it if VRAM stays mostly free.

    Returns:
    {
        "patent_id": str,
        "total":     int,
        "flagged":   int,
        "figures":   [...]   # one result per image, sorted by filename
    }
    """
    patent_dir = raw_dir / patent_id
    if not patent_dir.is_dir():
        return {"patent_id": patent_id, "total": 0, "flagged": 0, "figures": []}

    png_files = sorted(patent_dir.glob("*.png"))
    if not png_files:
        return {"patent_id": patent_id, "total": 0, "flagged": 0, "figures": []}

    figures = score_all(png_files, model, processor, device, threshold, batch_size, num_workers)

    flagged = sum(1 for f in figures if not f["keep"])
    return {"patent_id": patent_id, "total": len(figures), "flagged": flagged, "figures": figures}


# ─── Full-dataset triage ──────────────────────────────────────────────────────

def run_triage(
    cfg: dict,
    threshold: float = 0.60,
    limit: int | None = None,
    batch_size: int = 48,
    num_workers: int = 8,
    force: bool = False,
) -> None:
    """
    Score every image in raw_dir, writing one JSON per patent and a summary CSV.

    Output locations (both under cfg["paths"]["triage"]):
        <patent_id>.json      — per-patent scores
        triage_summary.csv    — one row per patent: patent_id, total_images,
                                flagged_count, flagged_ratio

    Already-processed patents are skipped (JSON exists → skip), so this is safe
    to re-run after a crash or to pick up newly-added patent folders. This also
    means any locked review decisions are preserved, since their files are never
    rewritten.

    To change the keep/discard threshold on already-scored images, do NOT call
    this again — use rethreshold_existing() or reset_threshold() instead, which
    re-apply a new threshold to the existing scores without re-running SigLIP
    and without touching locked figures.

    Parameters
    ----------
    cfg       : config dict from load_config()
    threshold : score_drawing >= threshold → keep=True  (default 0.60)
    limit     : if set, process only the first N patent folders (for testing)
    force     : if True, re-score and overwrite patents that already have a
                triage JSON, DESTROYING any locked review decisions for them.
                Only use this intentionally (e.g. raw images changed).
    """
    raw_dir    = Path(cfg["paths"]["raw_images"])
    triage_dir = Path(cfg["paths"]["triage"])
    triage_dir.mkdir(parents=True, exist_ok=True)

    patent_dirs = sorted(p for p in raw_dir.iterdir() if p.is_dir())
    if limit is not None:
        patent_dirs = patent_dirs[:limit]

    if not force:
        already_done = {p.stem for p in triage_dir.glob("*.json") if p.stem != "triage_summary"}
        skipped = [p for p in patent_dirs if p.name in already_done]
        patent_dirs = [p for p in patent_dirs if p.name not in already_done]
        if skipped:
            print(f"Skipping {len(skipped)} already-triaged patents (use force=True to re-score and "
                  f"overwrite — this destroys any locked review decisions).")
        if not patent_dirs:
            print("Nothing to do — all patents already triaged. "
                  "To change the threshold, use rethreshold_existing() or reset_threshold() instead.")
            return

    model, processor, device = load_siglip_model(cfg)

    summary_rows: list[dict] = []

    for patent_path in patent_dirs:
        patent_id = patent_path.name
        result    = triage_patent(patent_id, raw_dir, model, processor, device, threshold, batch_size, num_workers)

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

    # Rebuild summary CSV from every JSON on disk (not just this run's patents),
    # so a partial/incremental run doesn't drop rows for already-triaged patents.
    summary_csv = triage_dir / "triage_summary.csv"
    all_summary_rows = []
    for json_path in sorted(triage_dir.glob("*.json")):
        if json_path.stem == "triage_summary":
            continue
        with open(json_path) as fh:
            data = json.load(fh)
        total = data.get("total", 0)
        flagged = data.get("flagged", 0)
        all_summary_rows.append({
            "patent_id":     data["patent_id"],
            "total_images":  total,
            "flagged_count": flagged,
            "flagged_ratio": round(flagged / total, 4) if total else 0.0,
        })

    if all_summary_rows:
        fieldnames = ["patent_id", "total_images", "flagged_count", "flagged_ratio"]
        with open(summary_csv, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_summary_rows)
        total_imgs    = sum(r["total_images"]  for r in summary_rows) if summary_rows else 0
        total_flagged = sum(r["flagged_count"] for r in summary_rows) if summary_rows else 0
        print(f"\nTriage complete: {len(summary_rows)} patents newly scored | "
              f"{total_imgs} images | {total_flagged} flagged "
              f"({100*total_flagged/max(1,total_imgs):.1f}% of newly-scored)")
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
            if fig.get("locked"):
                continue  # user-confirmed decision — never overridden by threshold
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
            if fig.get("locked"):
                continue  # user-confirmed decision — never overridden by threshold
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


# ─── Lock / unlock confirmed decisions ───────────────────────────────────────

def lock_discards(cfg: dict) -> None:
    """
    Stamp ``"locked": true`` on every image currently marked keep=False.

    Locked images are permanently excluded from the active processing queue and
    are never re-enabled by reset_threshold or rethreshold_existing, even if
    you lower the threshold later.  Use this to preserve manual overrides (e.g.
    images you flipped to KEEP via the Cell-10 UI) and confirmed SigLIP discards
    before experimenting with a new threshold.

    Call unlock_discards() to clear all locks and start fresh.
    """
    triage_dir = Path(cfg["paths"]["triage"])
    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")
    if not json_paths:
        print("No triage JSONs found — run run_triage first.")
        return

    total_locked = 0
    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)
        newly_locked = 0
        for fig in data["figures"]:
            if not fig["keep"] and not fig.get("locked"):
                fig["locked"] = True
                newly_locked += 1
        if newly_locked:
            with open(json_path, "w") as fh:
                json.dump(data, fh, indent=2)
            total_locked += newly_locked

    print(f"lock_discards: {total_locked} images stamped as locked across "
          f"{len(json_paths)} patents.")
    print("These images will be skipped by reset_threshold and rethreshold_existing.")


def lock_keeps(cfg: dict) -> None:
    """
    Stamp ``"locked": true`` on every image currently marked keep=True.

    Use this to protect images you have already confirmed as KEEP (e.g. after a
    manual review pass in Cell 8) so a more aggressive threshold cannot discard
    them again.
    """
    triage_dir = Path(cfg["paths"]["triage"])
    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")
    if not json_paths:
        print("No triage JSONs found — run run_triage first.")
        return

    total_locked = 0
    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)
        newly_locked = 0
        for fig in data["figures"]:
            if fig["keep"] and not fig.get("locked"):
                fig["locked"] = True
                newly_locked += 1
        if newly_locked:
            with open(json_path, "w") as fh:
                json.dump(data, fh, indent=2)
            total_locked += newly_locked

    print(f"lock_keeps: {total_locked} images stamped as locked.")


def unlock_all(cfg: dict) -> None:
    """
    Remove all ``locked`` stamps from every triage JSON.

    After calling this, reset_threshold and rethreshold_existing will re-evaluate
    every image from its raw scores.  Use only when you want a clean slate.
    """
    triage_dir = Path(cfg["paths"]["triage"])
    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")
    if not json_paths:
        print("No triage JSONs found.")
        return

    total_unlocked = 0
    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)
        changed = False
        for fig in data["figures"]:
            if fig.pop("locked", None) is not None:
                total_unlocked += 1
                changed = True
        if changed:
            with open(json_path, "w") as fh:
                json.dump(data, fh, indent=2)

    print(f"unlock_all: {total_unlocked} locks removed.")


def commit_review(
    cfg: dict,
    approved: set[tuple[str, str]],
    reviewed_keys: set[tuple[str, str]] | None = None,
) -> dict:
    """
    Persist the outcome of a manual review session from the Cell-6 viewer.

    For every non-locked discard image whose (patent_id, file) is in
    ``reviewed_keys`` (i.e. it was actually displayed/paged through this
    session — pass None to fall back to the old "commit everything pending"
    behaviour):
      - If also in ``approved``: set keep=True, pred="drawing", locked=True
        (user confirmed it should stay)
      - Otherwise: set locked=True, keep=False  (user confirmed discard)

    Images already locked before this call, and images not in
    ``reviewed_keys`` (pages you never scrolled to), are left untouched and
    remain pending for a future review session.

    Returns a stats dict: {"newly_kept": int, "newly_locked_discard": int}
    """
    triage_dir = Path(cfg["paths"]["triage"])
    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")

    newly_kept            = 0
    newly_locked_discard  = 0

    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)
        changed = False
        for fig in data["figures"]:
            if fig.get("locked") or fig["keep"]:
                continue  # already settled — skip
            key = (data["patent_id"], fig["file"])
            if reviewed_keys is not None and key not in reviewed_keys:
                continue  # never shown to the reviewer this session — leave pending
            if key in approved:
                fig["keep"]   = True
                fig["pred"]   = "drawing"
                fig["locked"] = True
                newly_kept   += 1
            else:
                fig["locked"] = True   # confirmed discard
                newly_locked_discard += 1
            changed = True
        if changed:
            data["flagged"] = sum(1 for f in data["figures"] if not f["keep"])
            with open(json_path, "w") as fh:
                json.dump(data, fh, indent=2)

    # Rewrite summary CSV
    summary_rows = []
    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)
        summary_rows.append({
            "patent_id":     data["patent_id"],
            "total_images":  data["total"],
            "flagged_count": data["flagged"],
            "flagged_ratio": round(data["flagged"] / data["total"], 4) if data["total"] else 0.0,
        })
    summary_csv = triage_dir / "triage_summary.csv"
    import csv as _csv
    with open(summary_csv, "w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=["patent_id", "total_images", "flagged_count", "flagged_ratio"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"commit_review: {newly_kept} images flipped to KEEP (locked).")
    print(f"               {newly_locked_discard} discards locked permanently.")
    print(f"Summary rewritten: {summary_csv}")
    return {"newly_kept": newly_kept, "newly_locked_discard": newly_locked_discard}


def reset_review(cfg: dict) -> None:
    """
    Undo a commit_review call: remove all locks from images that are currently
    keep=False (discards).  Locked KEEPs (user-approved) are preserved.

    After calling this, the Cell-6 viewer will show those images again for
    another review pass.  Use before reset_threshold if you want a full clean slate.
    """
    triage_dir = Path(cfg["paths"]["triage"])
    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")

    total_unlocked = 0
    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)
        changed = False
        for fig in data["figures"]:
            if not fig["keep"] and fig.pop("locked", None) is not None:
                total_unlocked += 1
                changed = True
        if changed:
            with open(json_path, "w") as fh:
                json.dump(data, fh, indent=2)

    print(f"reset_review: {total_unlocked} discard locks removed.")
    print("Run the Cell-6 viewer again to re-review those images.")


def locked_stats(cfg: dict) -> None:
    """Print a summary of locked vs unlocked images across all triage JSONs."""
    triage_dir = Path(cfg["paths"]["triage"])
    json_paths = sorted(p for p in triage_dir.glob("*.json")
                        if p.stem != "triage_summary")

    n_locked_discard = 0
    n_locked_keep    = 0
    n_free           = 0

    for json_path in json_paths:
        with open(json_path) as fh:
            data = json.load(fh)
        for fig in data["figures"]:
            if fig.get("locked"):
                if fig["keep"]:
                    n_locked_keep += 1
                else:
                    n_locked_discard += 1
            else:
                n_free += 1

    total = n_locked_discard + n_locked_keep + n_free
    print(f"Triage lock status ({total} images total):")
    print(f"  Locked DISCARD : {n_locked_discard:,}")
    print(f"  Locked KEEP    : {n_locked_keep:,}")
    print(f"  Free (unlocked): {n_free:,}")
