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


# ─── Zero-shot T2 taxonomy classification ─────────────────────────────────────

def classify_t2_fields(
    img_path: Path,
    model,
    tokenizer,
    preprocess,
    device: str,
) -> dict:
    """
    Zero-shot classify a patent figure crop on T2 taxonomy axes using SigLIP.

    Returns predictions using the exact label strings from the HTML review tool
    so the UI can pre-fill T2 fields without any mapping step.

    Returns
    -------
    dict with keys matching HTML state fields::

        {
          "per":    {"value": str, "confidence": float},
          "sym":    {"value": str, "confidence": float},
          "acSty":  {"value": str, "confidence": float},
          "acCol":  {"value": str, "confidence": float},
          "bgSty":  {"value": str, "confidence": float},
          "bgCol":  {"value": str, "confidence": float},
          "parts":  [str, ...]
          "parts_scores": {str: float}
        }

    Returns empty dict if model is None or image cannot be loaded.
    """
    import torch
    import torch.nn.functional as F
    from PIL import Image

    PARTS_THRESHOLD = 0.20

    T2_PER    = ["Top", "Bottom/Down", "Front", "Back", "Side",
                 "Front-Isometric", "Rear-Isometric", "Generic 3D"]
    T2_SYM    = ["Symmetric View", "Asymmetric View"]
    T2_AC_STY = ["Line Drawing", "Shaded Render", "Solid/Filled Model", "Schematic"]
    T2_AC_COL = ["B/W (Monochrome)", "Grayscale", "Full Color"]
    T2_BG_STY = ["Solid Fill", "Shaded/Gradient", "Grid/Pattern"]
    T2_BG_COL = ["White", "Blueprint Blue", "Dark", "Grayscale"]
    T2_PARTS  = [
        "Whole Vehicle Layout", "Primary Wing", "Secondary/Canard Wing",
        "Empennage/Tail", "Rotor/Propeller Blade", "Tilt Hinge/Mechanism",
        "Fuselage Cross-section", "Landing Gear/Skids",
        "Internal Components/Batteries/Wiring",
    ]
    TEMPLATES = {
        "per":   "A patent drawing showing a {} view of an aircraft",
        "sym":   "This aircraft patent drawing has a {}",
        "acSty": "The aircraft in this patent figure is drawn as a {}",
        "acCol": "The rendering color of this patent figure is {}",
        "bgSty": "The background of this patent drawing is {}",
        "bgCol": "The background color of this patent drawing is {}",
        "parts": "This aircraft patent drawing shows a visible {}",
    }

    if model is None:
        return {}
    try:
        image = Image.open(img_path).convert("RGB")
        img_t = preprocess(image).unsqueeze(0).to(device)
    except Exception:
        return {}

    def _score(candidates: list, template: str) -> list:
        texts     = [template.format(c) for c in candidates]
        toks      = tokenizer(texts).to(device)
        with torch.no_grad():
            img_feat  = F.normalize(model.encode_image(img_t),  dim=-1)
            text_feat = F.normalize(model.encode_text(toks),    dim=-1)
            raw       = (img_feat @ text_feat.T).squeeze(0).cpu().tolist()
        return [float(max(0.0, min(1.0, s))) for s in raw]

    result: dict = {}
    for axis, candidates in [
        ("per",   T2_PER),
        ("sym",   T2_SYM),
        ("acSty", T2_AC_STY),
        ("acCol", T2_AC_COL),
        ("bgSty", T2_BG_STY),
        ("bgCol", T2_BG_COL),
    ]:
        try:
            scores  = _score(candidates, TEMPLATES[axis])
            best_i  = scores.index(max(scores))
            result[axis] = {"value": candidates[best_i],
                            "confidence": round(scores[best_i], 4)}
        except Exception:
            result[axis] = {"value": None, "confidence": 0.0}

    try:
        part_scores = _score(T2_PARTS, TEMPLATES["parts"])
        result["parts"]        = [T2_PARTS[i] for i, s in enumerate(part_scores)
                                   if s > PARTS_THRESHOLD]
        result["parts_scores"] = {T2_PARTS[i]: round(s, 4)
                                   for i, s in enumerate(part_scores)}
    except Exception:
        result["parts"]        = []
        result["parts_scores"] = {}

    return result


# ─── Zero-shot G1 architecture classification ─────────────────────────────────

def classify_g1_hint(
    img_path: Path,
    model,
    tokenizer,
    preprocess,
    device: str,
    nlp_confidence: float = 0.0,
    confidence_threshold: float = 0.55,
) -> "dict | None":
    """
    Conditionally classify G1 architecture type using SigLIP zero-shot.

    Only runs when ``nlp_confidence < confidence_threshold`` — if the NLP
    matcher is already confident the visual check is skipped to save compute.

    Returns
    -------
    ``{"value": str, "confidence": float, "source": "siglip"}``  or  ``None``
    if skipped.  ``value`` is one of the master HTML's G1 topology codes
    (``TW, TP, DS, CVT, SLC, SRW, RC, MR, HB, PFV``) matching the ``topType``
    field exactly — see ``UI_for_taxonomy_caracterization_10.0.html`` ``TOP``.
    """
    import torch
    import torch.nn.functional as F
    from PIL import Image

    if nlp_confidence >= confidence_threshold:
        return None

    # Definitions mirror the master wizard's G1 topology codes exactly
    # (same wording used in the archived src/_archive/ai_labeler.py prompt).
    G1_TOP_TYPES = {
        "TW":  "tilt wing aircraft where the entire wing panel rotates to vector thrust",
        "TP":  "tilt propulsors aircraft where propulsors tilt independently while the wing stays fixed",
        "DS":  "deflected slipstream aircraft with fixed propellers and large structural flaps that deflect airflow",
        "CVT": "combined aircraft with fixed lift rotors plus tilting propulsors, or ambiguous dual-rotation thrust",
        "SLC": "lift plus cruise aircraft with separate fixed hover rotors and fixed cruise propulsors, no tilting parts",
        "SRW": "stopped rotor wing aircraft where the rotors stop and lock in cruise to act as a fixed wing",
        "RC":  "rotorcraft, a single-rotor, coaxial, or tandem helicopter layout",
        "MR":  "multirotor aircraft with distributed fixed rotors in a drone or multicopter layout",
        "HB":  "hoverbike with a motorcycle riding posture and visible rider interface",
        "PFV": "personal flying vehicle such as a wearable suit, jetpack, or standing platform",
    }
    TEMPLATE = "A patent drawing of an eVTOL aircraft: {}"

    if model is None:
        return None
    try:
        image = Image.open(img_path).convert("RGB")
        img_t = preprocess(image).unsqueeze(0).to(device)
    except Exception:
        return None

    ids   = list(G1_TOP_TYPES.keys())
    texts = [TEMPLATE.format(G1_TOP_TYPES[k]) for k in ids]
    toks  = tokenizer(texts).to(device)

    with torch.no_grad():
        img_feat  = F.normalize(model.encode_image(img_t), dim=-1)
        text_feat = F.normalize(model.encode_text(toks),   dim=-1)
        scores    = (img_feat @ text_feat.T).squeeze(0).cpu().tolist()

    scores = [float(max(0.0, min(1.0, s))) for s in scores]
    best_i = scores.index(max(scores))

    return {
        "value":      ids[best_i],
        "confidence": round(scores[best_i], 4),
        "source":     "siglip",
    }
