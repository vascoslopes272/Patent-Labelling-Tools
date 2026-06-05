"""
cross_modal.py — SigLIP visual verification for patent figure matches.

Runs AFTER matcher.py has produced match results.  Each matched image is
compared visually to its description text using the SigLIP image-text model
(ViT-SO400M-14-SigLIP-384 via open_clip).

Key heuristic
-------------
If OCR said "FIG. 3" but the crop looks nothing like the description of FIG. 3,
siglip_score < 0.30 → flag needs_review / siglip_mismatch so a human sees it.

Public API
----------
load_siglip_model() → (model, tokenizer, preprocess, device)
    Download (once) and return the SigLIP model components.

compute_visual_score(img_path, description_text, model, tok, pre, dev) → float
    Cosine similarity between image and text, clamped to [0, 1].

verify_matches(match_results, raw_dir, patent_id, model, tok, pre, dev,
               skip_siglip=False) → list[dict]
    Enrich match dicts with siglip_score and composite_confidence.
    For _Fu crops: re-rank review_candidates by visual score.
"""

from __future__ import annotations

from pathlib import Path

from tqdm import tqdm


# ─── Model loading ────────────────────────────────────────────────────────────

def load_siglip_model() -> tuple:
    """
    Load the SigLIP ViT-SO400M-14 model via open_clip.

    Downloads ~3 GB of weights on first call (cached by HuggingFace Hub).
    Returns (model, tokenizer, preprocess, device).
    """
    import open_clip
    import torch

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
    return model, tokenizer, preprocess, device


# ─── Per-image visual score ───────────────────────────────────────────────────

def compute_visual_score(
    img_path: Path,
    description_text: str,
    model,
    tokenizer,
    preprocess,
    device: str,
) -> float:
    """
    Cosine similarity between an image crop and a description string.

    Parameters
    ----------
    img_path         : Path to the image file.
    description_text : The matched description line (e.g. "FIG. 3 is a view…").
    model/tokenizer/preprocess/device : From load_siglip_model().

    Returns
    -------
    float in [0, 1].  Higher = more visually consistent with the description.
    """
    import torch
    import torch.nn.functional as F
    from PIL import Image

    image  = Image.open(img_path).convert("RGB")
    img_t  = preprocess(image).unsqueeze(0).to(device)
    text_t = tokenizer([description_text]).to(device)

    with torch.no_grad():
        if device == "cuda":
            with torch.cuda.amp.autocast():
                img_feat  = model.encode_image(img_t)
                text_feat = model.encode_text(text_t)
        else:
            img_feat  = model.encode_image(img_t)
            text_feat = model.encode_text(text_t)

        img_feat  = F.normalize(img_feat,  dim=-1)
        text_feat = F.normalize(text_feat, dim=-1)
        sim       = (img_feat @ text_feat.T).item()

    return float(max(0.0, min(1.0, sim)))


# ─── Batch verification ───────────────────────────────────────────────────────

def verify_matches(
    match_results: list[dict],
    raw_dir: Path,
    patent_id: str,
    model,
    tokenizer,
    preprocess,
    device: str,
    skip_siglip: bool = False,
) -> list[dict]:
    """
    Enrich match results with SigLIP visual confidence scores.

    For each result with a matched_description:
      - Adds "siglip_score": float (or None when skip_siglip=True).
      - Adds "composite_confidence": weighted blend of text and visual scores.
      - If match_status == "matched" and siglip_score < 0.30: flags
        needs_review=True and siglip_mismatch=True (OCR vs. visual disagreement).

    For _Fu crops (human_required):
      - Runs SigLIP against each review_candidate description.
      - Re-sorts candidates by siglip_score descending.

    Parameters
    ----------
    match_results : Output of matcher.match_images().
    raw_dir       : cfg["paths"]["raw_images"].
    patent_id     : Used to locate the image folder (raw_dir / patent_id).
    skip_siglip   : When True, skip all SigLIP calls (fast "quick check" mode).
                    siglip_score will be None; composite_confidence = match_confidence.

    Returns
    -------
    Updated copy of match_results (new dicts, originals untouched).
    """
    patent_dir = raw_dir / patent_id
    updated: list[dict] = []

    for result in tqdm(match_results, desc=f"SigLIP {patent_id}", leave=False):
        r = dict(result)
        r.setdefault("siglip_mismatch", False)

        desc = result.get("matched_description")
        method = result.get("match_method", "exact")
        mc     = float(result.get("match_confidence") or 0.0)

        # ── No visual check possible (no matched description or fast mode) ─────
        if skip_siglip or desc is None:
            r["siglip_score"]         = None
            r["composite_confidence"] = mc
            updated.append(r)
            continue

        # ── Compute visual score for the matched description ───────────────────
        img_path = patent_dir / result["file"]
        siglip_score: float | None = None

        try:
            siglip_score = compute_visual_score(img_path, desc, model, tokenizer, preprocess, device)
        except Exception as exc:
            print(f"  [SigLIP] Error on {result['file']}: {exc}")

        r["siglip_score"] = siglip_score

        # ── Flag visual mismatches on OCR-exact matches ────────────────────────
        if result.get("match_status") == "matched" and siglip_score is not None and siglip_score < 0.30:
            r["needs_review"]   = True
            r["siglip_mismatch"] = True

        # ── Composite confidence ───────────────────────────────────────────────
        if siglip_score is not None:
            if method == "exact":
                r["composite_confidence"] = 0.4 * 0.95 + 0.6 * siglip_score
            elif method == "semantic":
                r["composite_confidence"] = 0.4 * mc + 0.6 * siglip_score
            elif method == "positional":
                r["composite_confidence"] = 0.3 * mc + 0.7 * siglip_score
            else:
                r["composite_confidence"] = mc
        else:
            r["composite_confidence"] = mc

        # ── Re-rank _Fu review candidates by visual score ─────────────────────
        if "_Fu" in result["file"] and result.get("review_candidates"):
            enriched: list[dict] = []
            for cand in result["review_candidates"]:
                c = dict(cand)
                if skip_siglip:
                    c["siglip_score"] = None
                else:
                    try:
                        c["siglip_score"] = compute_visual_score(
                            img_path, cand["description"],
                            model, tokenizer, preprocess, device,
                        )
                    except Exception:
                        c["siglip_score"] = None
                enriched.append(c)

            enriched.sort(key=lambda x: x.get("siglip_score") or 0.0, reverse=True)
            r["review_candidates"] = enriched

        updated.append(r)

    return updated
