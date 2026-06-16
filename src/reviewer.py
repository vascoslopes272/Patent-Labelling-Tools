"""
reviewer.py — assemble per-patent JSON (T1 + T3) and auto-fill visual fields.

Public API
----------
auto_fill_visual(description)                              → dict
classify_t1_dimensions(text, sbert_model)                  → dict
assemble_patent_json(patent_id, excel_row, match_results)  → dict
write_patent_json(patent_id, data, labels_dir)             → Path
process_patent(patent_id, cfg, excel_index, raw_dir)       → Path
"""

import json
from pathlib import Path

from src.matcher import parse_description, match_images, label_from_filename


# ─── Visual field keyword rules ─────────────────────────────────────────────
# Field names AND values below match the master HTML wizard's T2 enums
# exactly (per/acSty/sym/acCol/bgSty/bgCol) so this output can be ingested
# by ingestAI() with zero mapping step.

_PERSPECTIVE_RULES: list[tuple[list[str], str]] = [
    (["top view", "top-view", "plan view"],             "Top"),
    (["bottom view"],                                   "Bottom/Down"),
    (["front view", "front-view", "elevation view"],    "Front"),
    (["rear view", "back view"],                         "Back"),
    (["side view", "side-view", "lateral view"],         "Side"),
    (["front-isometric", "front isometric"],             "Front-Isometric"),
    (["rear-isometric", "rear isometric"],               "Rear-Isometric"),
    (["perspective view", "isometric", "3d view"],       "Generic 3D"),
]

_STYLE_RULES: list[tuple[list[str], str]] = [
    (["schematic", "block diagram", "flow field", "flow plot",
      "cfd", "graph", "chart", "plot"],                  "Schematic"),
    (["shaded", "rendered", "render"],                    "Shaded Render"),
    (["solid model", "filled model", "solid/filled"],      "Solid/Filled Model"),
]

_SYMMETRY_RULES: list[tuple[list[str], str]] = [
    (["asymmetric", "asymmetrical"],  "Asymmetric View"),
    (["symmetric", "symmetrical"],    "Symmetric View"),   # order matters: check asym first
]


def _first_match(text: str, rules: list[tuple[list[str], str]]) -> str | None:
    lower = text.lower()
    for keywords, value in rules:
        if any(kw in lower for kw in keywords):
            return value
    return None


def auto_fill_visual(description: str | None) -> dict:
    """
    Keyword-scan a figure description line and return the visual field dict.

    Field names/values match the master HTML wizard exactly (per/acSty/sym/
    acCol/bgSty/bgCol/parts). Fields that can be inferred get source="auto".
    Unknown fields get value=None, source=None (filled later by the wizard).
    """
    def _auto(value: str | None) -> dict:
        return {"value": value, "source": "auto" if value else None}

    if not description:
        return {
            "per":   {"value": None, "source": None},
            "acSty": {"value": None, "source": None},
            "sym":   {"value": None, "source": None},
            "acCol": {"value": None, "source": None},
            "bgSty": {"value": None, "source": None},
            "bgCol": {"value": None, "source": None},
            "parts": [],
        }

    return {
        "per":   _auto(_first_match(description, _PERSPECTIVE_RULES)),
        "acSty": _auto(_first_match(description, _STYLE_RULES) or "Line Drawing"),
        "sym":   _auto(_first_match(description, _SYMMETRY_RULES)),
        "acCol": {"value": None, "source": None},
        "bgSty": {"value": None, "source": None},
        "bgCol": {"value": None, "source": None},
        "parts": [],
    }


# ─── T1 dimension classification (SBERT semantic match) ────────────────────
# The master HTML stores only option id/label strings, no definitions — these
# one-sentence anchors are written here so SBERT has something to embed
# against. Wording follows the same intent as the archived ai_labeler.py
# Claude prompt, just turned into plain descriptive sentences.

_T1_SCOPE_DEFS = {
    "Whole Aircraft Architecture":     "this patent describes or claims a complete aircraft layout, covering the overall vehicle configuration as a whole",
    "Architectural Subsystem Enabler": "this patent describes a subsystem or mechanism that enables a specific aircraft architecture, such as a tilting, folding, or actuation mechanism",
    "Component-Level Generic":         "this patent describes a generic, low-level component or part with no architecture-specific context",
}

_T1_FIELD_DEFS = {
    "Aerodynamic/Structural": "the innovation concerns aerodynamics or structural design, such as wings, fuselage, airframe, or lifting surfaces",
    "Mechanical/Kinematic":   "the innovation concerns mechanical or kinematic systems, such as tilting, folding, hinges, or actuation mechanisms",
    "Propulsion/Electrical":  "the innovation concerns propulsion or electrical systems, such as motors, rotors, propellers, batteries, or powertrains",
    "Control/Avionics":       "the innovation concerns flight control, avionics, sensors, or guidance systems",
    "Other / Unidentified":   "the innovation does not clearly fit aerodynamic, mechanical, propulsion, or control categories",
}

_T1_TARGET_DEFS = {
    "Layout Convergence":          "the goal is to converge on or optimize the overall aircraft layout or configuration",
    "Weight/Complexity Reduction": "the goal is to reduce weight, part count, or mechanical complexity",
    "Aerodynamic Efficiency":      "the goal is to improve aerodynamic efficiency, lift, or drag performance",
    "Redundancy/Safety":           "the goal is to improve safety, redundancy, or fault tolerance",
    "Other / Unidentified":        "the goal does not clearly match layout, weight, aerodynamics, or safety objectives",
}


def classify_t1_dimensions(text: str | None, sbert_model=None) -> dict:
    """
    Pick the best-fitting option for each T1 dimension (scope, t1Field,
    t1Target) by embedding `text` (title + abstract + description of
    drawings) and each candidate definition with SBERT, then taking the
    highest cosine similarity per dimension.

    Returns {"scope": {...}, "t1Field": {...}, "t1Target": {...}}, each
    {"value": str|None, "confidence": float, "source": "auto"|None} —
    same {value, source} provenance convention as auto_fill_visual /
    the master wizard.
    """
    def _empty() -> dict:
        return {"value": None, "confidence": 0.0, "source": None}

    result = {"scope": _empty(), "t1Field": _empty(), "t1Target": _empty()}

    if not text or not text.strip() or sbert_model is None:
        return result

    import numpy as np

    text_emb = sbert_model.encode(
        [text], convert_to_numpy=True, normalize_embeddings=True
    )

    for dim_key, defs in (
        ("scope",    _T1_SCOPE_DEFS),
        ("t1Field",  _T1_FIELD_DEFS),
        ("t1Target", _T1_TARGET_DEFS),
    ):
        ids     = list(defs.keys())
        def_emb = sbert_model.encode(
            [defs[i] for i in ids], convert_to_numpy=True, normalize_embeddings=True
        )
        sims   = (def_emb @ text_emb.T).flatten()
        best_i = int(np.argmax(sims))
        result[dim_key] = {
            "value":      ids[best_i],
            "confidence": round(float(sims[best_i]), 4),
            "source":     "auto",
        }

    return result


# ─── JSON assembly ─────────────────────────────────────────────────────────────

def assemble_patent_json(
    patent_id: str,
    excel_row: dict,
    match_results: list[dict],
    description_of_drawings: str = "",
    t1_dimensions: dict | None = None,
) -> dict:
    """Assemble the full per-patent JSON dict (T1 metadata + T3 image entries)."""
    t3_images = []
    for res in match_results:
        img_entry = {
            "file":                 res["file"],
            "ocr_label":            res["ocr_label"],
            "fig_number":           res["fig_number"],
            "matched_description":  res["matched_description"],
            "match_status":         res["match_status"],
            "match_method":         res.get("match_method"),
            "match_confidence":     res["match_confidence"],
            "composite_confidence": res.get("composite_confidence"),
            "semantic_best_score":  res.get("semantic_best_score", 0.0),
            "siglip_score":         res.get("siglip_score"),
            "siglip_mismatch":      res.get("siglip_mismatch", False),
            "review_candidates":    res.get("review_candidates", []),
            "needs_review":         res["needs_review"],
            "visual":               auto_fill_visual(res.get("matched_description")),
            "T2_predictions": res.get("T2_predictions"),
            "G1_hint":        res.get("G1_hint"),
        }
        if "duplicate_group" in res:
            img_entry["duplicate_group"] = res["duplicate_group"]
        t3_images.append(img_entry)

    t1 = {
        "assignee":             excel_row.get("assignee"),
        "pub_year":             excel_row.get("pub_year"),
        "app_year":             excel_row.get("app_year"),
        "title":                excel_row.get("title"),
        "abstract":             excel_row.get("abstract"),
        "backward_cites":       excel_row.get("backward_cites", []),
        "forward_cites":        excel_row.get("forward_cites", []),
        "innovation_objective": excel_row.get("innovation_objective"),
    }
    if t1_dimensions:
        t1.update(t1_dimensions)   # scope, t1Field, t1Target — from classify_t1_dimensions()

    has_splits = any(r.get("match_status") in ("no_label", "human_required")
                      for r in match_results)

    return {
        "patent_id":    patent_id,
        "record_number": excel_row.get("record_number"),
        "T1": t1,
        "description_of_drawings": description_of_drawings or None,
        "T3_images": t3_images,
        "has_splits": has_splits,
    }


def write_patent_json(patent_id: str, data: dict, labels_dir: Path) -> Path:
    """Write assembled JSON to labels_dir/<patent_id>.json."""
    labels_dir.mkdir(parents=True, exist_ok=True)
    dest = labels_dir / f"{patent_id}.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return dest


def process_patent(
    patent_id: str,
    cfg: dict,
    excel_index: dict,
    raw_dir: Path,
    sbert_model=None,
    siglip_bundle: tuple | None = None,
    skip_siglip: bool = False,
) -> Path:
    """
    Full Stage 01 pipeline for one patent.

    Stage 00 already renamed all figure crops to ``{id}_F*.png`` / ``{id}_Fu*.png``.
    Stage 01 reads the fig label from the filename (no re-OCR) and matches to the
    description text from ``text/{patent_id}.txt``.

    Steps
    -----
    1. Glob ``_F*.png`` / ``_Fu*.png`` from raw_dir/patent_id/
    2. Extract OCR label from each filename via label_from_filename()
    3. Read description text from text/<patent_id>.txt
    4. Parse description and match images to descriptions
    5. (Optional) SigLIP visual verification
    6. Assemble and write the JSON to cfg["paths"]["labels"]

    Parameters
    ----------
    sbert_model   : SentenceTransformer for semantic fallback in match_images().
    siglip_bundle : (model, tokenizer, preprocess, device) from load_siglip_model().
    skip_siglip   : Pass True to skip SigLIP calls (fast mode).

    Returns
    -------
    Path to the written JSON file.
    """
    from src.cross_modal import verify_matches

    excel_row      = excel_index.get(patent_id, {})
    patent_img_dir = raw_dir / patent_id

    if not patent_img_dir.exists():
        image_files = []
    else:
        labeled   = sorted(patent_img_dir.glob(f"{patent_id}_F[0-9]*.png"))
        unlabeled = sorted(patent_img_dir.glob(f"{patent_id}_Fu*.png"))
        image_files = labeled + unlabeled

    # Stage 00 already encoded the label into the filename — no re-OCR needed.
    ocr_labels = [label_from_filename(p.name) for p in image_files]

    # Description from EPO/Google scrape or PatSeer Excel (written by Stage 00).
    text_path = Path(cfg["paths"]["text"]) / f"{patent_id}.txt"
    if text_path.exists():
        desc_text = text_path.read_text(encoding="utf-8")
    else:
        # Fallback: read from data/descriptions.csv (written by Stage 00b)
        import csv as _csv
        _csv_path = Path(cfg["paths"]["data"]) / "descriptions.csv"
        desc_text = ""
        if _csv_path.exists():
            with open(_csv_path, newline="", encoding="utf-8") as _f:
                for row in _csv.DictReader(_f):
                    if row.get("patent_id") == patent_id:
                        desc_text = row.get("description_of_drawings", "")
                        break
    parsed_desc = parse_description(desc_text, cfg)

    has_splits = any(label is None for label in ocr_labels)   # any _Fu → uncertain order

    match_results = match_images(
        image_files,
        ocr_labels,
        parsed_desc,
        cfg,
        sbert_model       = sbert_model,
        total_desc_entries = len(parsed_desc),
        has_splits         = has_splits,
    )

    if siglip_bundle is not None:
        model, tokenizer, preprocess, device = siglip_bundle
        match_results = verify_matches(
            match_results, raw_dir, patent_id,
            model, tokenizer, preprocess, device,
            skip_siglip=skip_siglip,
        )

    # ── T2 auto-labeling (SigLIP per-image taxonomy prediction) ──────────────
    if siglip_bundle is not None and not skip_siglip:
        from src.cross_modal import classify_t2_fields, classify_g1_hint
        model, tokenizer, preprocess, device = siglip_bundle
        for res in match_results:
            img_path = raw_dir / patent_id / res["file"]
            if img_path.exists():
                res["T2_predictions"] = classify_t2_fields(
                    img_path, model, tokenizer, preprocess, device
                )
                nlp_conf = float(
                    res.get("composite_confidence")
                    or res.get("match_confidence")
                    or 0.0
                )
                res["G1_hint"] = classify_g1_hint(
                    img_path, model, tokenizer, preprocess, device,
                    nlp_confidence=nlp_conf,
                )
            else:
                res["T2_predictions"] = {}
                res["G1_hint"]        = None

    # ── T1 dimension classification (SBERT: title + abstract + first claim + drawings desc) ──
    # "First Claim" is short and information-dense — the single best statement
    # of what the invention actually is. The full "Description" column is
    # deliberately excluded: SBERT truncates ~256-384 tokens, so most of a
    # multi-thousand-word description would never be read, and what survives
    # tends to be generic background text rather than the invention itself.
    classify_text = " ".join(
        t for t in [
            excel_row.get("title"),
            excel_row.get("abstract"),
            excel_row.get("first_claim"),
            desc_text,
        ] if t
    )
    t1_dimensions = classify_t1_dimensions(classify_text, sbert_model)

    data = assemble_patent_json(patent_id, excel_row, match_results, desc_text, t1_dimensions)
    return write_patent_json(patent_id, data, cfg["paths"]["labels"])


# ─── Batch Stage 01 runner ────────────────────────────────────────────────────

def run_stage01(
    cfg: dict,
    sbert_model=None,
    siglip_bundle: "tuple | None" = None,
    skip_siglip: bool = False,
    limit: "int | None" = None,
    patent_ids: list[str] | None = None,
) -> "pd.DataFrame":
    """
    Batch Stage 01 runner. Processes all patent folders in raw_images/.

    Parameters
    ----------
    limit : If set, process only the first N patents (for testing).

    Returns
    -------
    pandas DataFrame with one row per patent:
    patent_id | match_score | matched | semantic | positional | unmatched |
    human_required | has_splits | review_required | description_found |
    t2_labeled | total_crops | error
    """
    import pandas as pd
    from tqdm import tqdm
    from src.extractor import load_patseer_excel

    raw_dir   = cfg["paths"]["raw_images"]
    excel_idx = load_patseer_excel(cfg["paths"]["patseer_excel"])

    patent_dirs = sorted([d for d in raw_dir.iterdir() if d.is_dir()])
    if patent_ids is not None:
        patent_dirs = [d for d in patent_dirs if d.name in set(patent_ids)]
    if limit:
        patent_dirs = patent_dirs[:limit]

    rows = []
    for patent_dir in tqdm(patent_dirs, desc="Stage 01"):
        pid = patent_dir.name
        try:
            json_path = process_patent(
                pid, cfg, excel_idx, raw_dir,
                sbert_model   = sbert_model,
                siglip_bundle = siglip_bundle,
                skip_siglip   = skip_siglip,
            )
            data     = json.loads(json_path.read_text(encoding="utf-8"))
            figs     = data.get("T3_images", [])
            statuses = [f.get("match_status", "") for f in figs]
            rows.append({
                "patent_id":         pid,
                "match_score":       round(
                    sum(1 for s in statuses
                        if s in ("matched", "semantic", "positional"))
                    / max(len(statuses), 1), 3),
                "matched":           statuses.count("matched"),
                "semantic":          statuses.count("semantic"),
                "positional":        statuses.count("positional"),
                "unmatched":         statuses.count("unmatched"),
                "human_required":    statuses.count("human_required"),
                "has_splits":        data.get("has_splits", False),
                "review_required":   any(f.get("needs_review") for f in figs),
                "description_found": bool(data.get("description_of_drawings")),
                "t2_labeled":        sum(1 for f in figs if f.get("T2_predictions")),
                "total_crops":       len(figs),
                "error":             None,
            })
        except Exception as exc:
            rows.append({
                "patent_id":   pid,
                "error":       str(exc),
                "match_score": 0.0,
                "total_crops": 0,
            })

    df = pd.DataFrame(rows)
    print(f"\n{'='*55}")
    print(f"  Stage 01 complete: {len(df)} patents")
    if "match_score" in df.columns and df["match_score"].notna().any():
        print(f"  Avg match score  : {df['match_score'].mean():.1%}")
        hr = df.get("human_required", pd.Series(dtype=int))
        rr = df.get("review_required", pd.Series(dtype=bool))
        print(f"  Human-required   : {hr.sum() if not hr.empty else 0} crops")
        print(f"  Needs review     : {rr.sum() if not rr.empty else 0} patents")
    print(f"{'='*55}")
    return df
