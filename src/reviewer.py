"""
reviewer.py — assemble per-patent JSON (T1 + T3) and auto-fill visual fields.

Public API
----------
auto_fill_visual(description)                              → dict
assemble_patent_json(patent_id, excel_row, match_results)  → dict
write_patent_json(patent_id, data, labels_dir)             → Path
process_patent(patent_id, cfg, excel_index, raw_dir)       → Path
"""

import json
from pathlib import Path

from src.ocr_labeler import ocr_figure_label
from src.matcher import parse_description, match_images


# ─── Visual field keyword rules ────────────────────────────────────────────────

_PERSPECTIVE_RULES: list[tuple[list[str], str]] = [
    (["top view", "top-view", "plan view"],            "Orthographic Top"),
    (["front view", "front-view", "elevation view"],   "Orthographic Front"),
    (["rear view", "back view"],                       "Orthographic Rear"),
    (["bottom view"],                                  "Orthographic Bottom"),
    (["side view", "side-view", "lateral view"],       "Orthographic Side"),
    (["perspective view", "isometric", "3d view"],     "Isometric/3D Perspective"),
    (["exploded"],                                     "Exploded View"),
    (["cross-section", "cross section", "sectional"],  "Cross-Section"),
]

_STYLE_RULES: list[tuple[list[str], str]] = [
    (["schematic", "block diagram"],       "Schematic Block Diagram"),
    (["cfd", "flow field", "flow plot"],   "CFD Plot"),
    (["graph", "chart", "plot"],           "Graph/Chart"),
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

    Fields that can be inferred get source="auto".
    Unknown fields get value=None, source=None (filled later by taxonomy wizard).
    Style defaults to "Line Drawing (Standard)" if no other style matches.
    """
    def _auto(value: str | None) -> dict:
        return {"value": value, "source": "auto" if value else None}

    if not description:
        return {
            "perspective": {"value": None, "source": None},
            "style":       {"value": None, "source": None},
            "symmetry":    {"value": None, "source": None},
            "color":       {"value": None, "source": None},
            "background":  {"value": None, "source": None},
            "parts":       [],
        }

    return {
        "perspective": _auto(_first_match(description, _PERSPECTIVE_RULES)),
        "style":       _auto(_first_match(description, _STYLE_RULES) or "Line Drawing (Standard)"),
        "symmetry":    _auto(_first_match(description, _SYMMETRY_RULES)),
        "color":       {"value": None, "source": None},
        "background":  {"value": None, "source": None},
        "parts":       [],
    }


# ─── JSON assembly ─────────────────────────────────────────────────────────────

def assemble_patent_json(
    patent_id: str,
    excel_row: dict,
    match_results: list[dict],
    description_of_drawings: str = "",
) -> dict:
    """Assemble the full per-patent JSON dict (T1 metadata + T3 image entries)."""
    t3_images = []
    for res in match_results:
        img_entry = {
            "file":                res["file"],
            "ocr_label":           res["ocr_label"],
            "fig_number":          res["fig_number"],
            "matched_description": res["matched_description"],
            "match_status":        res["match_status"],
            "match_confidence":    res["match_confidence"],
            "needs_review":        res["needs_review"],
            "visual":              auto_fill_visual(res.get("matched_description")),
        }
        if "duplicate_group" in res:
            img_entry["duplicate_group"] = res["duplicate_group"]
        t3_images.append(img_entry)

    return {
        "patent_id":    patent_id,
        "record_number": excel_row.get("record_number"),
        "T1": {
            "assignee":             excel_row.get("assignee"),
            "pub_year":             excel_row.get("pub_year"),
            "app_year":             excel_row.get("app_year"),
            "title":                excel_row.get("title"),
            "abstract":             excel_row.get("abstract"),
            "backward_cites":       excel_row.get("backward_cites", []),
            "forward_cites":        excel_row.get("forward_cites", []),
            "innovation_objective": excel_row.get("innovation_objective"),
        },
        "description_of_drawings": description_of_drawings or None,
        "T3_images": t3_images,
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
) -> Path:
    """
    Full Stage 01 pipeline for one patent:
      1. Glob image files from raw_dir/patent_id/
      2. OCR each image for a figure label
      3. Read BRIEF DESCRIPTION text from text/<patent_id>.txt (written by Stage 00)
      4. Parse description text and match images to descriptions
      5. Assemble and write the JSON to cfg["paths"]["labels"]

    Returns the path to the written JSON file.
    """
    excel_row = excel_index.get(patent_id, {})
    patent_img_dir = raw_dir / patent_id
    image_files = sorted(patent_img_dir.glob("fig_*")) if patent_img_dir.exists() else []

    ocr_labels = [ocr_figure_label(p, cfg) for p in image_files]

    # Description now comes from the EPO-sourced .txt file, not the Excel
    text_path = Path(cfg["paths"]["text"]) / f"{patent_id}.txt"
    desc_text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
    parsed_desc = parse_description(desc_text, cfg)

    match_results = match_images(image_files, ocr_labels, parsed_desc, cfg)

    data = assemble_patent_json(patent_id, excel_row, match_results, desc_text)
    return write_patent_json(patent_id, data, cfg["paths"]["labels"])
