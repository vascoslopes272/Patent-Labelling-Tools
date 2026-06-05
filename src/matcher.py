"""
matcher.py — match figure numbers to description lines.

Parses the 'Description of Drawings' text into a {fig_num: line} dict,
then aligns each image's OCR label to its description.

match_status taxonomy
---------------------
matched        — OCR label found and uniquely maps to a description line.
semantic       — No exact match; semantic similarity fallback found a match (>0.5).
unmatched      — OCR label found but no description line matched (semantic below threshold).
no_label       — No OCR label; positional fallback used.
duplicate      — Same fig number maps to more than one image.
human_required — No OCR label and positional fallback disabled (splits detected).

Public API
----------
parse_description(text, cfg)    → dict[str, str]
    Maps normalised fig number (e.g. "3A") → description line.

match_images(image_files, ocr_labels, parsed_desc, cfg, ...) → list[dict]
    Returns one result dict per image with all match metadata.

label_from_filename(fname) → str | None
    Extract "FIG. N" from an already-renamed filename (_F* → label, _Fu* → None).
"""

from __future__ import annotations

import re
from pathlib import Path


# ─── Utility ──────────────────────────────────────────────────────────────────

def label_from_filename(fname: str) -> str | None:
    """
    Extract the FIG. label from an already-renamed patent figure filename.

    "US1234_F003.png"   → "FIG. 3"
    "US1234_F003A.png"  → "FIG. 3A"
    "US1234_Fu001.png"  → None   (_Fu = unlabeled)
    "US1234_F003_b.png" → None   (duplicate suffix — ambiguous, treat as unlabeled)
    """
    m = re.match(r"^.+_F(\d+)([A-Za-z]?)\.png$", fname, re.IGNORECASE)
    if m:
        num    = int(m.group(1))
        letter = m.group(2).upper()
        return f"FIG. {num}{letter}".strip()
    return None


# ─── Description parsing ──────────────────────────────────────────────────────

def parse_description(text: str, cfg: dict) -> dict[str, str]:
    """
    Parse the Description of Drawings into {fig_number: description_line}.

    Fig numbers are normalised to uppercase (e.g. "FIG. 3a" → key "3A").
    Multi-line descriptions for the same figure are joined with a space.
    The returned dict preserves document order (Python 3.7+).
    """
    if not text:
        return {}

    pattern = re.compile(cfg["matching"]["fig_regex"], re.IGNORECASE)
    result: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_key and current_lines:
            result[current_key] = " ".join(current_lines).strip()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.search(line)
        if m:
            _flush()
            current_key = m.group(1).upper()
            current_lines = [line]
        elif current_key:
            current_lines.append(line)

    _flush()
    return result


def _normalize(ocr_label: str | None, cfg: dict) -> str | None:
    """Extract and uppercase the numeric part from an OCR label string."""
    if not ocr_label:
        return None
    m = re.search(cfg["matching"]["fig_regex"], ocr_label, re.IGNORECASE)
    return m.group(1).upper() if m else None


# ─── Matching ─────────────────────────────────────────────────────────────────

def match_images(
    image_files: list[Path],
    ocr_labels: list[str | None],
    parsed_desc: dict[str, str],
    cfg: dict,
    sbert_model=None,
    total_desc_entries: int = 0,
    has_splits: bool = False,
) -> list[dict]:
    """
    Match each image to a description line and assign a match_status.

    Parameters
    ----------
    image_files        : Ordered list of image paths (document order).
    ocr_labels         : OCR result parallel to image_files (None = not found).
    parsed_desc        : Output of parse_description().
    cfg                : Full config dict.
    sbert_model        : Optional SentenceTransformer for semantic fallback.
                         When provided, unlabeled / unmatched images get cosine-
                         similarity ranked candidates from the description.
    total_desc_entries : Number of description FIG. entries; used to calibrate
                         positional-fallback confidence.
    has_splits         : True when HR-Net split at least one page.  Disables the
                         positional fallback entirely (crop order not guaranteed).

    Returns
    -------
    List of result dicts (one per image) with schema:
        file                 : str
        ocr_label            : str | None
        fig_number           : str | None
        matched_description  : str | None
        match_status         : str
        match_method         : str   "exact"|"semantic"|"positional"|"human_required"
        match_confidence     : float
        semantic_best_score  : float  (0.0 if not computed)
        review_candidates    : list   (non-empty only for _Fu files)
        needs_review         : bool
    """
    use_fallback = cfg["matching"].get("positional_fallback", True) and not has_splits
    desc_keys    = list(parsed_desc.keys())
    total_crops  = len(image_files)

    # ── Dynamic positional confidence ──────────────────────────────────────────
    if has_splits:
        positional_confidence = 0.0
    elif total_desc_entries > 0 and total_crops == total_desc_entries:
        positional_confidence = 0.60   # ordered US patent, counts match exactly
    else:
        positional_confidence = 0.25   # counts differ — rough guess

    # ── Duplicate detection (per fig number) ──────────────────────────────────
    fig_claim_count: dict[str, int] = {}
    for label in ocr_labels:
        key = _normalize(label, cfg)
        if key:
            fig_claim_count[key] = fig_claim_count.get(key, 0) + 1

    # ── Pre-compute SBERT embeddings for all description entries ──────────────
    desc_embeddings   = None
    desc_keys_ordered: list[str] = []

    if sbert_model is not None and parsed_desc:
        import numpy as np

        desc_keys_ordered = list(parsed_desc.keys())
        desc_texts        = [parsed_desc[k] for k in desc_keys_ordered]
        desc_embeddings   = sbert_model.encode(
            desc_texts, convert_to_numpy=True, normalize_embeddings=True
        )

    # ── Main matching loop ────────────────────────────────────────────────────
    results: list[dict] = []

    for i, (img_path, ocr_label) in enumerate(zip(image_files, ocr_labels)):
        fig_num = _normalize(ocr_label, cfg)
        is_fu   = "_Fu" in img_path.name

        entry: dict = {
            "file":                img_path.name,
            "ocr_label":           ocr_label,
            "fig_number":          fig_num,
            "matched_description": None,
            "match_status":        None,
            "match_method":        None,
            "match_confidence":    0.0,
            "semantic_best_score": 0.0,
            "review_candidates":   [],
            "needs_review":        False,
        }

        # ── Branch A: no OCR label (_Fu file) ─────────────────────────────────
        if fig_num is None:
            if has_splits:
                entry.update(
                    match_status    = "human_required",
                    match_method    = "human_required",
                    match_confidence= 0.0,
                    needs_review    = True,
                )
            elif use_fallback and i < len(desc_keys):
                fb_key = desc_keys[i]
                entry.update(
                    fig_number          = fb_key,
                    matched_description = parsed_desc[fb_key],
                    match_status        = "no_label",
                    match_method        = "positional",
                    match_confidence    = positional_confidence,
                    needs_review        = True,
                )
            else:
                entry.update(
                    match_status    = "no_label",
                    match_method    = "human_required",
                    match_confidence= 0.0,
                    needs_review    = True,
                )

        # ── Branch B: OCR label not in description → try semantic fallback ────
        elif fig_num not in parsed_desc:
            if sbert_model is not None and desc_embeddings is not None and len(desc_embeddings):
                import numpy as np

                query_text = ocr_label or f"FIG. {fig_num}"
                query_emb  = sbert_model.encode(
                    [query_text], convert_to_numpy=True, normalize_embeddings=True
                )
                sims      = (desc_embeddings @ query_emb.T).flatten()
                best_idx  = int(np.argmax(sims))
                best_score = float(sims[best_idx])

                entry["semantic_best_score"] = best_score

                if best_score > 0.5:
                    best_key = desc_keys_ordered[best_idx]
                    entry.update(
                        fig_number          = best_key,
                        matched_description = parsed_desc[best_key],
                        match_status        = "semantic",
                        match_method        = "semantic",
                        match_confidence    = best_score,
                        needs_review        = True,
                    )
                else:
                    entry.update(
                        match_status    = "unmatched",
                        match_method    = "exact",
                        match_confidence= 0.0,
                        needs_review    = True,
                    )
            else:
                entry.update(
                    match_status    = "unmatched",
                    match_method    = "exact",
                    match_confidence= 0.0,
                    needs_review    = True,
                )

        # ── Branch C: duplicate claim ──────────────────────────────────────────
        elif fig_claim_count.get(fig_num, 1) > 1:
            entry.update(
                matched_description = parsed_desc[fig_num],
                match_status        = "duplicate",
                match_method        = "exact",
                match_confidence    = 0.9,
                needs_review        = True,
                duplicate_group     = fig_num,
            )

        # ── Branch D: clean exact match ───────────────────────────────────────
        else:
            entry.update(
                matched_description = parsed_desc[fig_num],
                match_status        = "matched",
                match_method        = "exact",
                match_confidence    = 0.95,
                needs_review        = False,
            )

        # ── Enrich _Fu files with review_candidates ───────────────────────────
        if is_fu and parsed_desc:
            if sbert_model is not None and desc_embeddings is not None and len(desc_embeddings):
                import numpy as np

                query_text = ocr_label or "unlabeled figure"
                query_emb  = sbert_model.encode(
                    [query_text], convert_to_numpy=True, normalize_embeddings=True
                )
                sims = (desc_embeddings @ query_emb.T).flatten()

                candidates = [
                    {
                        "fig_num":      desc_keys_ordered[j],
                        "description":  parsed_desc[desc_keys_ordered[j]],
                        "semantic_score": float(sims[j]),
                    }
                    for j in range(len(desc_keys_ordered))
                ]
                candidates.sort(key=lambda x: x["semantic_score"], reverse=True)
            else:
                # No model — return top-5 in document order with score 0.0
                candidates = [
                    {"fig_num": k, "description": parsed_desc[k], "semantic_score": 0.0}
                    for k in desc_keys
                ]

            entry["review_candidates"] = candidates[:5]

        results.append(entry)

    return results
