"""
matcher.py — match figure numbers to description lines.

Parses the 'Description of Drawings' text into a {fig_num: line} dict,
then aligns each image's OCR label to its description. Handles the full
match_status taxonomy: matched / unmatched / no_label / duplicate.

Public API
----------
parse_description(text, cfg)    → dict[str, str]
    Maps normalised fig number (e.g. "3A") → description line.

match_images(image_files, ocr_labels, parsed_desc, cfg) → list[dict]
    Returns one result dict per image with all match metadata.
"""

import re
from pathlib import Path


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


def match_images(
    image_files: list[Path],
    ocr_labels: list[str | None],
    parsed_desc: dict[str, str],
    cfg: dict,
) -> list[dict]:
    """
    Match each image to a description line and assign a match_status.

    match_status values
    -------------------
    matched   — OCR label found and uniquely maps to a description line.
    unmatched — OCR label found but no matching description line exists.
    no_label  — OCR found nothing; positional fallback used if enabled.
    duplicate — same fig number maps to more than one image.

    Parameters
    ----------
    image_files  : ordered list of image paths (document order)
    ocr_labels   : OCR result parallel to image_files (None = not found)
    parsed_desc  : output of parse_description()
    cfg          : full config dict

    Returns
    -------
    List of result dicts (one per image).
    """
    use_fallback = cfg["matching"].get("positional_fallback", True)
    desc_keys = list(parsed_desc.keys())   # document order for positional fallback

    # Count how many images claim each fig number → detect duplicates
    fig_claim_count: dict[str, int] = {}
    for label in ocr_labels:
        key = _normalize(label, cfg)
        if key:
            fig_claim_count[key] = fig_claim_count.get(key, 0) + 1

    results: list[dict] = []

    for i, (img_path, ocr_label) in enumerate(zip(image_files, ocr_labels)):
        fig_num = _normalize(ocr_label, cfg)

        entry: dict = {
            "file":                img_path.name,
            "ocr_label":           ocr_label,
            "fig_number":          fig_num,
            "matched_description": None,
            "match_status":        None,
            "match_confidence":    None,
            "needs_review":        False,
        }

        if fig_num is None:
            if use_fallback and i < len(desc_keys):
                fb_key = desc_keys[i]
                entry.update(
                    fig_number=fb_key,
                    matched_description=parsed_desc[fb_key],
                    match_status="no_label",
                    match_confidence=0.3,
                    needs_review=True,
                )
            else:
                entry.update(
                    match_status="no_label",
                    match_confidence=0.0,
                    needs_review=True,
                )

        elif fig_num not in parsed_desc:
            entry.update(
                match_status="unmatched",
                match_confidence=0.0,
                needs_review=True,
            )

        elif fig_claim_count.get(fig_num, 1) > 1:
            entry.update(
                matched_description=parsed_desc[fig_num],
                match_status="duplicate",
                match_confidence=0.9,
                needs_review=True,
                duplicate_group=fig_num,
            )

        else:
            entry.update(
                matched_description=parsed_desc[fig_num],
                match_status="matched",
                match_confidence=0.95,
                needs_review=False,
            )

        results.append(entry)

    return results
