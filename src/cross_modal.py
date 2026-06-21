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

def load_siglip_model(cache_dir: "Path | str | None" = None, device: "str | None" = None) -> tuple:
    """
    Load the SigLIP ViT-SO400M-14 model via open_clip.

    Downloads ~3 GB of weights on first call. When `cache_dir` is given
    (cfg["paths"]["siglip_cache"]), weights are cached there instead of the
    default `~/.cache/huggingface` so the project stays self-contained.

    `device` overrides auto-detection (e.g. "cuda:1") — pass this whenever the
    caller already picked a specific GPU (see the notebook's GPU-selection
    cell): plain "cuda" always resolves to device 0, which silently ignores
    that choice and can OOM a GPU some other process already filled.
    Returns (model, tokenizer, preprocess, device).
    """
    import os
    import open_clip
    import torch

    if cache_dir is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        os.environ["HF_HUB_CACHE"] = str(cache_dir)

    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:timm/ViT-SO400M-14-SigLIP-384"
    )
    tokenizer = open_clip.get_tokenizer("hf-hub:timm/ViT-SO400M-14-SigLIP-384")

    if device is None:
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
    patent_dir: Path,
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
    patent_dir    : Already-resolved directory containing this patent's image
                    files (matched/{patent_id}_{record_number}/ — folder names
                    in matched/ carry a record-number suffix the bare patent_id
                    does not, so callers must resolve the folder first).
    patent_id     : Used only for log/progress labelling.
    skip_siglip   : When True, skip all SigLIP calls (fast "quick check" mode).
                    siglip_score will be None; composite_confidence = match_confidence.

    Returns
    -------
    Updated copy of match_results (new dicts, originals untouched).
    """
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


# ─── Shared image encoding ─────────────────────────────────────────────────────

def encode_image_features(img_path: Path, model, preprocess, device: str):
    """
    Encode an image once and return its normalized SigLIP feature vector.

    process_patent() calls this once per figure and passes the result into
    every classify_*_fields() call for that figure (T2/G1/M1/M2/M3), instead
    of each classifier re-running model.encode_image() on the same crop —
    that redundancy was ~20 forward passes per figure before this existed.

    Returns None if the image cannot be loaded.
    """
    import torch
    import torch.nn.functional as F
    from PIL import Image

    try:
        image = Image.open(img_path).convert("RGB")
        img_t = preprocess(image).unsqueeze(0).to(device)
    except Exception:
        return None

    with torch.no_grad():
        if device == "cuda":
            with torch.cuda.amp.autocast():
                feat = model.encode_image(img_t)
        else:
            feat = model.encode_image(img_t)
        feat = F.normalize(feat, dim=-1)
    return feat


def _text_features(texts: list[str], model, tokenizer, device: str):
    import torch
    import torch.nn.functional as F

    toks = tokenizer(texts).to(device)
    with torch.no_grad():
        if device == "cuda":
            with torch.cuda.amp.autocast():
                feat = model.encode_text(toks)
        else:
            feat = model.encode_text(toks)
        feat = F.normalize(feat, dim=-1)
    return feat


# ─── T2 taxonomy option lists (module-level — reused by excel_schema.py) ──────

T2_PER    = ["Top", "Bottom/Down", "Front", "Back", "Side",
             "Front-Isometric", "Rear-Isometric", "Generic 3D"]

# Per-label prompt overrides for the "per" (perspective) axis. The returned
# *value* stays the canonical T2_PER label (the HTML wizard consumes those
# strings verbatim), but SigLIP is scored against a longer, discriminative
# sentence instead of the generic "A patent drawing showing a {} view…" template.
#
# "Front" vs "Front-Isometric" was the dominant confusion pair: a flat
# orthographic nose elevation and a three-quarter front perspective both contain
# the nose + wing roots, so the short template embeddings sat almost on top of
# each other in SigLIP's contrastive space. These two prompts deliberately
# push the embeddings apart along the features SigLIP can actually see:
#   • Front  → bilateral symmetry, NO depth/foreshortening, NO top surface,
#              wing leading edges as thin horizontal lines (single visible face).
#   • Front-Isometric → visible depth/foreshortening, fuselage TOP + one wing's
#              UPPER surface visible, near wing root vs far wing tip (three faces).
# (Sanity check — a top-down helicopter: "Front" shows the rotor disc as a thin
# ellipse with no hub depth; "Front-Isometric" shows the disc raked at an angle
# with part of the fuselage top — exactly the depth/top-surface split below.)
# Labels not listed here fall back to the generic TEMPLATES["per"] sentence.
T2_PER_PROMPTS = {
    "Front":
        "a patent technical line drawing of an aircraft viewed directly from the "
        "nose in a flat orthographic front elevation: left-right bilateral symmetry, "
        "no visible depth or foreshortening, wing leading edges appear as thin "
        "horizontal lines, no top surface visible",
    "Front-Isometric":
        "a patent technical line drawing of an aircraft in a three-quarter front "
        "perspective view: simultaneously shows the nose, one wing's upper surface, "
        "and the fuselage top, with visible depth foreshortening, wing tips appear "
        "further away than wing roots, three faces visible",
}
T2_AC_STY = ["Render", "Line Drawing", "Draft", "Blueprint"]
T2_AC_COL = ["B/W (Monochrome)", "Grayscale", "Full Color"]
T2_BG_STY = ["Solid Fill", "Shaded/Gradient", "Grid/Pattern"]
T2_BG_COL = ["White", "Blueprint Blue", "Dark", "Grayscale"]
T2_PARTS  = [
    "Whole Vehicle Layout", "Primary Wing", "Secondary/Canard Wing",
    "Empennage/Tail", "Rotor/Propeller Blade", "Tilt Hinge/Mechanism",
    "Fuselage Cross-section", "Landing Gear/Skids",
    "Internal Components/Batteries/Wiring",
]
T2_ROT = [0, 90, 180, 270]


# ─── Zero-shot T2 taxonomy classification ─────────────────────────────────────

def classify_t2_fields(
    img_path: Path,
    model,
    tokenizer,
    preprocess,
    device: str,
    img_feat=None,
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
          "acSty":  {"value": str, "confidence": float},
          "acCol":  {"value": str, "confidence": float},
          "bgSty":  {"value": str, "confidence": float},
          "bgCol":  {"value": str, "confidence": float},
          "parts":  [str, ...]
          "parts_scores": {str: float}
        }

    Returns empty dict if model is None or image cannot be loaded.
    """
    PARTS_THRESHOLD = 0.20

    TEMPLATES = {
        "per":   "A patent drawing showing a {} view of an aircraft",
        "acSty": "The aircraft in this patent figure is drawn as a {}",
        "acCol": "The rendering color of this patent figure is {}",
        "bgSty": "The background of this patent drawing is {}",
        "bgCol": "The background color of this patent drawing is {}",
        "parts": "This aircraft patent drawing shows a visible {}",
    }

    if model is None:
        return {}
    feat = img_feat if img_feat is not None else encode_image_features(img_path, model, preprocess, device)
    if feat is None:
        return {}

    def _score(candidates: list, template: str, prompt_overrides: dict | None = None) -> list:
        overrides = prompt_overrides or {}
        texts     = [overrides.get(c, template.format(c)) for c in candidates]
        text_feat = _text_features(texts, model, tokenizer, device)
        raw       = (feat @ text_feat.T).squeeze(0).cpu().tolist()
        return [float(max(0.0, min(1.0, s))) for s in raw]

    result: dict = {}
    for axis, candidates in [
        ("per",   T2_PER),
        ("acSty", T2_AC_STY),
        ("acCol", T2_AC_COL),
        ("bgSty", T2_BG_STY),
        ("bgCol", T2_BG_COL),
    ]:
        try:
            # The "per" axis uses discriminative per-label prompt overrides
            # (T2_PER_PROMPTS) to separate Front vs Front-Isometric; every
            # other axis uses its plain template.
            overrides = T2_PER_PROMPTS if axis == "per" else None
            scores  = _score(candidates, TEMPLATES[axis], overrides)
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

    ROTATION_PROMPTS = {
        0:   "a patent technical drawing of an aircraft in correct upright orientation",
        90:  "a patent technical drawing of an aircraft rotated 90 degrees clockwise, "
             "with the aircraft on its side",
        180: "a patent technical drawing of an aircraft upside down",
        270: "a patent technical drawing of an aircraft rotated 90 degrees "
             "counter-clockwise, with the aircraft on its side",
    }
    try:
        rot_candidates = [ROTATION_PROMPTS[r] for r in T2_ROT]
        rot_scores     = _score(rot_candidates, "{}")
        best_i         = rot_scores.index(max(rot_scores))
        result["rotation_deg_suggested"] = {
            "value":      T2_ROT[best_i],
            "confidence": round(rot_scores[best_i], 4),
            "source":     "siglip",
        }
    except Exception:
        result["rotation_deg_suggested"] = {"value": 0, "confidence": 0.0, "source": "siglip"}

    return result


# ─── G1 topology option list (module-level — reused by excel_schema.py) ───────
# Mirrors the master wizard's G1 topology codes exactly
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
    "HB":  "a motorcycle-style frame with tandem or side-by-side rotors mounted above a seated rider straddle position",
    "PFV": "a wearable jetpack or thrust-vectored suit strapped directly to a standing human body with no separate vehicle frame",
}

# Discriminative VISION prompts for the confusable TP/SLC/CVT trio, used only
# by SigLIP (classify_g1_hint). The plain G1_TOP_TYPES defs describe the
# architecture's *kinematics* ("propulsors tilt") — which is invisible in a
# single static line drawing, so SigLIP collapses these three together. These
# rewrites instead describe the DRAWN EVIDENCE that separates them in a figure:
# a visible pivot/hinge/tilt-arrow (TP), two physically-distinct fixed rotor
# sets (SLC), or a mix of fixed lift rotors and a separate tilting unit (CVT).
# Topologies not listed here keep their G1_TOP_TYPES wording.
G1_VISUAL_PROMPTS = {
    "TP":  "aircraft with rotor nacelles drawn with a visible tilt pivot, hinge, "
           "rotation axis, or curved motion arrow at the wing tips or booms, "
           "showing the propulsors rotate between up and forward",
    "SLC": "aircraft with two physically separate and distinct sets of fixed "
           "rotors drawn — upward-facing vertical lift rotors AND a separate "
           "horizontal pusher or tractor propeller — with no hinge, pivot, or "
           "tilt mechanism drawn anywhere",
    "CVT": "aircraft drawing combining fixed upward lift rotors together with a "
           "separate tilting or rotating propulsor unit shown with a pivot",
}


# ─── Zero-shot G1 architecture classification ─────────────────────────────────

def classify_g1_hint(
    img_path: Path,
    model,
    tokenizer,
    preprocess,
    device: str,
    nlp_confidence: float = 0.0,
    confidence_threshold: float = 0.55,
    img_feat=None,
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
    if nlp_confidence >= confidence_threshold:
        return None

    TEMPLATE = "A patent drawing of an eVTOL aircraft: {}"

    if model is None:
        return None
    feat = img_feat if img_feat is not None else encode_image_features(img_path, model, preprocess, device)
    if feat is None:
        return None

    ids       = list(G1_TOP_TYPES.keys())
    # Use the sharper, drawn-evidence prompts for the visually-confusable
    # TP/SLC/CVT trio where available (G1_VISUAL_PROMPTS), else the plain def.
    texts     = [TEMPLATE.format(G1_VISUAL_PROMPTS.get(k, G1_TOP_TYPES[k])) for k in ids]
    text_feat = _text_features(texts, model, tokenizer, device)
    scores    = (feat @ text_feat.T).squeeze(0).cpu().tolist()

    scores = [float(max(0.0, min(1.0, s))) for s in scores]
    best_i = scores.index(max(scores))
    # margin = winner minus runner-up; a tiny margin means SigLIP can't really
    # separate the top two topologies from this drawing (downstream uses it to
    # flag the guess for review).
    _sorted = sorted(scores, reverse=True)
    margin  = float(_sorted[0] - _sorted[1]) if len(_sorted) > 1 else 1.0

    return {
        "value":      ids[best_i],
        "confidence": round(scores[best_i], 4),
        "margin":     round(margin, 4),
        "source":     "siglip",
    }


# ─── Zero-shot M1 structural classification ───────────────────────────────────

def classify_m1_fields(
    img_path: Path,
    model,
    tokenizer,
    preprocess,
    device: str,
    img_feat=None,
) -> dict:
    """
    Zero-shot classify M1 structural/airframe fields from a patent figure.

    Returns predictions keyed by the exact M1 field names used by the HTML wizard:
    fusShape, fusKin, gearArch, latSym — each with {value, confidence, source}.
    """
    if model is None:
        return {}
    feat = img_feat if img_feat is not None else encode_image_features(img_path, model, preprocess, device)
    if feat is None:
        return {}

    def _best(candidates: list[tuple], template: str) -> dict:
        ids    = [c[0] for c in candidates]
        descs  = [template.format(c[1]) for c in candidates]
        tf_    = _text_features(descs, model, tokenizer, device)
        sims   = (feat @ tf_.T).squeeze(0).cpu().tolist()
        sims   = [float(max(0.0, min(1.0, s))) for s in sims]
        best_i = sims.index(max(sims))
        return {"value": ids[best_i], "confidence": round(sims[best_i], 4), "source": "siglip"}

    FUS_SHAPE = [
        ("Circular",    "aircraft with a circular or cylindrical tubular fuselage"),
        ("Oval",        "aircraft with an oval or elliptical fuselage cross-section"),
        ("Rectangular", "aircraft with a rectangular or box-shaped fuselage"),
        ("Blended",     "aircraft with a blended wing body or lifting body fuselage merged into the wings"),
        ("PodBoom",     "pod-and-boom fuselage: compact central body with one or two thin tail booms, "
                         "no conventional fuselage tube"),
    ]
    FUS_KIN = [
        ("Fixed",    "aircraft with a conventional fixed fuselage that does not tilt or pivot"),
        ("Variable", "aircraft with a variable incidence or tilting fuselage body that rotates during transition"),
    ]
    GEAR_ARCH = [
        ("Skids",      "aircraft with fixed skid-type landing gear or runners underneath"),
        ("FixedWheel", "aircraft with fixed non-retractable wheeled landing gear"),
        ("RetrWheel",  "aircraft with retractable wheeled landing gear that folds into the body"),
        ("PadsHull",   "aircraft with hull pads, pontoons, or belly-contact landing surfaces"),
    ]
    LAT_SYM = [
        ("true",  "aircraft that is laterally symmetric with mirror-identical left and right halves"),
        ("false", "aircraft that is laterally asymmetric with different left and right sides"),
    ]

    try:
        result = {
            "fusShape": _best(FUS_SHAPE, "A patent drawing of an eVTOL {}"),
            "fusKin":   _best(FUS_KIN,   "A patent drawing of an eVTOL {}"),
            "gearArch": _best(GEAR_ARCH, "A patent drawing of an eVTOL {}"),
            "latSym":   _best(LAT_SYM,   "A patent drawing of an eVTOL {}"),
        }
        # Convert latSym value to bool
        result["latSym"]["value"] = result["latSym"]["value"] == "true"
        return result
    except Exception:
        return {}


# ─── Zero-shot M2 aerodynamic classification ──────────────────────────────────

def classify_m2_fields(
    img_path: Path,
    model,
    tokenizer,
    preprocess,
    device: str,
    img_feat=None,
) -> dict:
    """
    Zero-shot classify M2 aerodynamic/lifting-surface fields from a patent figure.

    Returns predictions for wingConf, empType, empKin, plus a wCount_hint integer.
    Each field: {value, confidence, source}.
    """
    if model is None:
        return {}
    feat = img_feat if img_feat is not None else encode_image_features(img_path, model, preprocess, device)
    if feat is None:
        return {}

    def _best(candidates: list[tuple], template: str) -> dict:
        ids    = [c[0] for c in candidates]
        descs  = [template.format(c[1]) for c in candidates]
        tf_    = _text_features(descs, model, tokenizer, device)
        sims   = (feat @ tf_.T).squeeze(0).cpu().tolist()
        sims   = [float(max(0.0, min(1.0, s))) for s in sims]
        best_i = sims.index(max(sims))
        return {"value": ids[best_i], "confidence": round(sims[best_i], 4), "source": "siglip"}

    WING_CONF = [
        ("W",   "aircraft with one or more distinct standard wing panels attached to the fuselage"),
        ("BWB", "aircraft with a blended wing body where fuselage and wings merge smoothly"),
        ("FW",  "flying wing aircraft with no distinct fuselage, the entire body generates lift"),
        ("LB",  "lifting body aircraft where the fuselage itself generates most of the lift without wings"),
    ]
    EMP_TYPE = [
        ("Tailless",    "aircraft with no tail empennage, tailless or flying wing design"),
        ("Conventional","aircraft with a conventional horizontal stabilizer at the base of the vertical tail"),
        ("Cruciform",   "aircraft with cruciform tail where horizontal stabilizer is at mid-height on the vertical fin"),
        ("T-Tail",      "aircraft with a T-tail where horizontal stabilizer is mounted at the top of the vertical fin"),
        ("V-Tail",      "aircraft with a V-shaped tail combining horizontal and vertical stabilization"),
        ("Inv_V-Tail",  "aircraft with an inverted V-tail pointing downward"),
        ("H-Tail",      "aircraft with an H-tail or twin-boom tail with two vertical fins connected by a horizontal stabilizer"),
        ("Fins",        "aircraft with minimal small stabilizing fins rather than a full tail empennage"),
    ]
    EMP_KIN = [
        ("Fixed",       "aircraft with a fixed tail empennage that does not tilt or move"),
        ("Tilt",        "aircraft where the entire aft tail assembly tilts together with the wing during transition"),
        ("Stabilator",  "aircraft with an all-moving stabilator where the entire horizontal tail pivots for pitch control"),
    ]
    WCOUNT = [
        ("1", "aircraft with one single main wing"),
        ("2", "aircraft with two wings such as a biplane, canard-wing, or tandem wing configuration"),
        ("3", "aircraft with three wing panels or lifting surfaces"),
        ("4", "aircraft with four or more wing panels"),
    ]

    try:
        return {
            "wingConf": _best(WING_CONF, "A patent drawing of an eVTOL {}"),
            "empType":  _best(EMP_TYPE,  "A patent drawing of an eVTOL {}"),
            "empKin":   _best(EMP_KIN,   "A patent drawing of an eVTOL {}"),
            "wCount":   _best(WCOUNT,    "A patent drawing of an eVTOL {}"),
        }
    except Exception:
        return {}


# ─── M3 propulsion classification ─────────────────────────────────────────────

def classify_m3_fields(
    img_path: Path,
    model,
    tokenizer,
    preprocess,
    device: str,
    img_feat=None,
) -> dict:
    """
    Zero-shot classify M3 propulsion sub-fields from a patent figure.

    Returns predictions for chord, orient, bmech, rmech — each with {value, confidence, source}.
    These are used to populate propulsion card fields in the HTML wizard.
    """
    if model is None:
        return {}
    feat = img_feat if img_feat is not None else encode_image_features(img_path, model, preprocess, device)
    if feat is None:
        return {}

    def _best(candidates: list[tuple], template: str) -> dict:
        ids    = [c[0] for c in candidates]
        descs  = [template.format(c[1]) for c in candidates]
        tf_    = _text_features(descs, model, tokenizer, device)
        sims   = (feat @ tf_.T).squeeze(0).cpu().tolist()
        sims   = [float(max(0.0, min(1.0, s))) for s in sims]
        best_i = sims.index(max(sims))
        return {"value": ids[best_i], "confidence": round(sims[best_i], 4), "source": "siglip"}

    CHORD = [
        ("Front", "rotors or propellers positioned at the front leading edge pulling the aircraft forward"),
        ("Back",  "rotors or propellers positioned at the back trailing edge pushing the aircraft"),
    ]
    # orient vocab is [Horizontal, Vertical, Mixed] — identical strings to
    # vlm_extractor.py (the reference), _M3_ORIENT_DEFS in src/reviewer.py and
    # the HTML wizard's m3OrientationOptions(), so all modalities merge cleanly.
    ORIENT = [
        ("Horizontal", "propulsors oriented horizontally for forward cruise thrust"),
        ("Vertical",   "rotors oriented vertically for hovering lift"),
        ("Mixed",      "rotors or propulsors with a visible tilting or vectoring mechanism that rotates between hover and cruise"),
    ]
    BLADE_MECH = [
        ("Open",   "open free rotor or propeller blades exposed to airflow"),
        ("Ducted", "rotors inside a duct or shroud or enclosed fan housing"),
        ("Folded", "folding or stowable rotor blades that collapse when not in use"),
    ]
    RETRACT_MECH = [
        ("Exposed",     "non-retractable rotors permanently exposed outside the aircraft structure"),
        ("Retractable", "retractable rotors that fold or retract into the aircraft structure during cruise"),
    ]
    # propKin (propulsor articulation kinematics) — SigLIP is deliberately
    # restricted to a binary [Tilt, Fixed]. A static B&W patent line drawing
    # shows a tilt mechanism explicitly (pivot/actuator/phantom-position lines),
    # but "Vectored" (flow deflection, not drawn geometry) and "Cyclic"
    # (swashplate, a claims-level distinction) are not visually separable from a
    # single frame — SigLIP would only ever produce false positives on them.
    # The full 4-value vocab [Fixed, Tilt, Vectored, Cyclic] still lives in
    # reviewer._M3_PROPKIN_DEFS (SBERT) and vlm_extractor.py; SBERT/text is the
    # authority for Vectored/Cyclic and merge_field_predictions() reconciles the
    # two sides (a binary SigLIP value never blocks a text-side Vectored/Cyclic).
    PROP_KIN = [
        ("Tilt",  "a propulsor that tilts as a unit to vector thrust between hover and cruise"),
        ("Fixed", "a fixed propulsor with no articulation"),
    ]

    try:
        return {
            "chord":   _best(CHORD,       "A patent drawing showing an eVTOL with {}"),
            "orient":  _best(ORIENT,      "A patent drawing showing an eVTOL with {}"),
            "bmech":   _best(BLADE_MECH,  "A patent drawing showing an eVTOL with {}"),
            "rmech":   _best(RETRACT_MECH, "A patent drawing showing an eVTOL with {}"),
            "propKin": _best(PROP_KIN,    "A patent drawing showing an eVTOL with {}"),
        }
    except Exception:
        return {}


# ─── Aggregate per-figure predictions to patent-level ─────────────────────────

# ─── Duplicate detection ──────────────────────────────────────────────────────
# Two complementary modalities, kept strictly separate per the pipeline design:
#   • SigLIP image-to-image  → figure-level duplicates (the SAME drawing reused
#                              across patents — e.g. continuations of one
#                              aircraft sharing a main architecture figure).
#   • PatentSBERTa text-to-text → patent-level duplicates (near-identical
#                              title/abstract/claim text).
# SigLIP is NOT used on text and SBERT is NOT used on images — image similarity
# and document similarity are different questions and conflating them produces
# false matches (two different aircraft described in similar words, or one
# aircraft drawn two different ways).

def detect_image_duplicates(
    entries: list[dict],
    model,
    preprocess,
    device: str,
    threshold: float = 0.85,
) -> dict:
    """
    Find figures whose crop is (near-)identical to an earlier figure's, using
    SigLIP image embeddings.

    Parameters
    ----------
    entries : list of {"patent_id": str, "fig_num": str, "image_path": str|Path}.
              Processed in the given order — the FIRST occurrence of a visual is
              treated as the canonical original; later near-identical crops point
              back to it. Order entries so the patent you want treated as the
              "original" (e.g. earliest publication) comes first.
    threshold : cosine-similarity cutoff in [0, 1]. Pairs at/above this are
                considered the same image. ~0.85+ is a safe "same drawing"
                cutoff for SigLIP on patent line art.

    Returns
    -------
    dict keyed by (patent_id, fig_num) for each DUPLICATE figure ->
        {"dup_of_patent": str, "dup_of_fig": str, "score": float}.
    Figures with no earlier match (the originals) are absent from the dict.
    """
    # Encode every crop once. encode_image_features already L2-normalizes, so a
    # plain dot product is cosine similarity.
    feats = [(e, encode_image_features(Path(e["image_path"]), model, preprocess, device))
             for e in entries]

    dups: dict = {}
    canonical: list = []   # [(entry, feat)] — first-seen visuals
    for e, f in feats:
        if f is None:
            continue
        best = None  # (score, original_entry)
        for oe, of in canonical:
            score = float((f @ of.T).item())
            if score >= threshold and (best is None or score > best[0]):
                best = (score, oe)
        if best is not None:
            dups[(e["patent_id"], e["fig_num"])] = {
                "dup_of_patent": best[1]["patent_id"],
                "dup_of_fig":    best[1]["fig_num"],
                "score":         round(best[0], 4),
            }
        else:
            canonical.append((e, f))
    return dups


def detect_text_duplicates(
    text_by_patent: dict,
    sbert_model,
    threshold: float = 0.70,
) -> dict:
    """
    Find patents whose text is a near-duplicate of an earlier patent's, using
    PatentSBERTa sentence embeddings (text-to-text only — no image input).

    Parameters
    ----------
    text_by_patent : {patent_id: text}. Insertion order defines which patent is
                     treated as the original (earlier key = original).
    threshold : cosine-similarity cutoff in [0, 1].

    Returns
    -------
    dict keyed by the DUPLICATE patent_id ->
        {"dup_of_patent": str, "score": float}.
    """
    import numpy as np

    pids = [p for p, t in text_by_patent.items() if t and str(t).strip()]
    if len(pids) < 2:
        return {}

    embs = sbert_model.encode(
        [text_by_patent[p] for p in pids],
        convert_to_numpy=True, normalize_embeddings=True,
    )

    dups: dict = {}
    for i in range(len(pids)):
        best = None  # (score, original_pid)
        for j in range(i):
            score = float(np.dot(embs[i], embs[j]))
            if score >= threshold and (best is None or score > best[0]):
                best = (score, pids[j])
        if best is not None:
            dups[pids[i]] = {"dup_of_patent": best[1], "score": round(best[0], 4)}
    return dups


def aggregate_architecture_predictions(
    per_figure_preds: list[dict],
    fields: list[str],
) -> dict:
    """
    Aggregate per-figure SigLIP predictions to a single patent-level prediction
    by taking the highest-confidence figure for each field.

    Parameters
    ----------
    per_figure_preds : List of dicts, each from classify_m1_fields() or classify_m2_fields().
    fields           : Which keys to aggregate (e.g. ["fusShape", "fusKin", "gearArch"]).

    Returns
    -------
    Dict keyed by field, each value: {value, confidence, source}.
    """
    result: dict = {}
    for field in fields:
        best: dict | None = None
        for pred in per_figure_preds:
            entry = pred.get(field)
            if entry and entry.get("value") is not None:
                if best is None or entry["confidence"] > best["confidence"]:
                    best = entry
        result[field] = best or {"value": None, "confidence": 0.0, "source": None}
    return result
