"""
excel_schema.py — flat row schema bridging the Stage 01 ML predictions
(in-memory dict shape built by reviewer.process_patent()) to the two Excel
workbooks that replace the old labels/*.json + per-patent HTML review flow:

    source_patents.xlsx   — one "Review" sheet, every taxonomy leaf field as
                             its own row, written once per Stage 01 run.
    reviewed_patents.xlsx — same columns + Reviewer/Reviewed_At, appended to
                             by the 02_taxonomy_review.ipynb UI as a human
                             confirms/corrects each patent.

Row columns (fixed order, see COLUMNS):
    Patent_ID | Section | Sub_Dimension | Field | Definition | Options |
    Value | Confidence | Source | Image_Path

One row per leaf field keeps the layout flexible — patents with more figures,
wings, or propulsion cards just add more rows, never new columns.

Public API
----------
build_patent_rows(patent_id, record, patent_img_dir) -> list[dict]
rows_to_dataframe(rows)                              -> pd.DataFrame
export_source_excel(all_rows, out_path)              -> None
append_reviewed_rows(rows, out_path)                  -> None
"""

from __future__ import annotations

from pathlib import Path

from src.cross_modal import T2_PER, T2_SYM, T2_AC_STY, T2_AC_COL, T2_BG_STY, T2_BG_COL, T2_PARTS, T2_ROT, G1_TOP_TYPES
from src.reviewer import (
    _T1_SCOPE_DEFS, _T1_FIELD_DEFS, _T1_TARGET_DEFS,
    _M1_FUS_SHAPE_DEFS, _M1_FUS_KIN_DEFS, _M1_GEAR_ARCH_DEFS, _M1_LAT_SYM_DEFS,
    _M2_WING_CONF_DEFS, _M2_EMP_TYPE_DEFS, _M2_EMP_KIN_DEFS, _M2_WCOUNT_DEFS,
    _M3_CHORD_DEFS, _M3_ORIENT_DEFS, _M3_BMECH_DEFS, _M3_RMECH_DEFS,
    m3_card_keys, PLACEHOLDER_IMAGE_PATH,
)

COLUMNS = [
    "Patent_ID", "Section", "Sub_Dimension", "Field", "Definition",
    "Options", "Value", "Confidence", "Source", "Image_Path", "Needs_Review",
]

_OPT = lambda d: "|".join(d.keys()) if isinstance(d, dict) else "|".join(d)


def _row(patent_id, section, sub_dim, field, definition, options, value=None,
         confidence=None, source=None, image_path=None, needs_review=None) -> dict:
    return {
        "Patent_ID": patent_id, "Section": section, "Sub_Dimension": sub_dim,
        "Field": field, "Definition": definition, "Options": options,
        "Value": value, "Confidence": confidence, "Source": source,
        "Image_Path": image_path, "Needs_Review": needs_review,
    }


def _pred_val(pred_dict: dict | None, key: str):
    entry = (pred_dict or {}).get(key) or {}
    return entry.get("value"), entry.get("confidence"), entry.get("source")


# ─── Manual-only fields (no ML prediction — human fills from scratch) ────────
# Mirrors HTML wizard fields that have no SigLIP/SBERT counterpart.

_T1_MANUAL = [
    ("isApproved",          "T1 — Approval Status",       "true|false"),
    ("t1DisapproveReason",  "T1 — Disapproval Reason",    "Pure UAV|Out of Domain|Unreadable|Other"),
    ("archCount",           "T1 — Distinct Architectures", ""),
    ("isDuplicate",         "T1 — Duplicate Flag",        "true|false"),
    ("duplicateId",         "T1 — Duplicate Of (Patent ID)", ""),
]

_M1_MANUAL = [
    ("footLen",  "M1 — Footprint Length (m)", ""),
    ("footWid",  "M1 — Footprint Width (m)",  ""),
    ("footHgt",  "M1 — Footprint Height (m)", ""),
    ("footAmbiguous", "M1 — Footprint Ambiguous", "true|false"),
    ("longSym",  "M1 — Longitudinal Symmetry", "true|false"),
]

_WING_MANUAL = [
    ("wTilt",  "Tilt",            "Fixed|Tilt"),
    ("wPosV",  "Vertical Position", "High|Mid|Low"),
    ("wPosL",  "Longitudinal Position", "Fwd|Cent|Aft"),
    ("wPlan",  "Planform",        "Str|Swp|Del|Oth"),
    ("wRole",  "Role",            "Canard|Tandem|Aft|Stacked"),
]

_M3_MANUAL = [
    ("count",     "Count",              ""),
    ("sym",       "Symmetric",          "true|false"),
    ("zone",      "Zone",               "Nose|Aft|Side|Dorsal|Ventral|StackV|StackH|Tip"),
    ("zoneChord", "Zone — Chordwise",   "LE|TE|Above|Below"),
    ("zoneSpan",  "Zone — Spanwise",    "Inboard|MidSpan|Outboard|Wingtip"),
    ("notes",     "Notes",              ""),
]


def build_patent_rows(patent_id: str, record: dict, patent_img_dir: "Path | None" = None,
                       cfg: dict | None = None) -> list[dict]:
    """
    Flatten one Stage 01 record dict (the shape reviewer.process_patent()
    builds in-memory) into the flat row schema described at module top.
    `patent_img_dir` is used to resolve absolute Image_Path values for T2 rows.
    `cfg` is optional — when given, cfg["confidence_routing"][section] supplies
    a per-section confidence floor below which Needs_Review is set True.
    """
    rows: list[dict] = []
    t1 = record.get("T1", {})

    # Confidence-based review routing — per-section threshold from
    # cfg["confidence_routing"] (config.yaml). Returns None (no flag) when
    # cfg/threshold/confidence are unavailable, so existing callers that don't
    # pass cfg see identical behavior to before this was added.
    routing_cfg = (cfg or {}).get("confidence_routing", {})

    def _needs_review(section: str, confidence) -> "bool | None":
        threshold = routing_cfg.get(section, 0.0)
        if threshold > 0.0 and isinstance(confidence, float) and confidence < threshold:
            return True
        return None

    # ── T1 ──────────────────────────────────────────────────────────────────
    for field, definition in [
        ("title", "Patent Title"), ("abstract", "Abstract"),
        ("assignee", "Assignee"), ("pub_year", "Publication Year"),
        ("app_year", "Application Year"),
    ]:
        rows.append(_row(patent_id, "T1", definition, field, definition, "", t1.get(field)))

    rows.append(_row(
        patent_id, "T1", "Description of Drawings", "description_of_drawings",
        "Description of Drawings", "", record.get("description_of_drawings"),
    ))

    for field, defs in [("scope", _T1_SCOPE_DEFS), ("t1Field", _T1_FIELD_DEFS), ("t1Target", _T1_TARGET_DEFS)]:
        value, conf, source = _pred_val(t1, field)
        rows.append(_row(patent_id, "T1", field, field, field, _OPT(defs), value, conf, source,
                          needs_review=_needs_review("T1", conf)))

    for field, sub_dim, options in _T1_MANUAL:
        rows.append(_row(patent_id, "T1", sub_dim, field, sub_dim, options))

    # ── T2 — per-figure rows ───────────────────────────────────────────────
    # No figures at all → a single placeholder row so the review UI still has
    # something to render instead of an empty middle pane.
    images = record.get("T3_images", []) or [{}]
    for img in images:
        fname = img.get("file", "")
        img_path = str(patent_img_dir / fname) if patent_img_dir and fname else None
        if not img_path or not Path(img_path).exists():
            img_path = str(PLACEHOLDER_IMAGE_PATH)
        sub_dim = f"Image: {fname}" if fname else "Image: (none available)"
        preds = img.get("T2_predictions") or {}

        for field, options in [
            ("per", T2_PER), ("sym", T2_SYM), ("acSty", T2_AC_STY),
            ("acCol", T2_AC_COL), ("bgSty", T2_BG_STY), ("bgCol", T2_BG_COL),
        ]:
            entry = preds.get(field) or {}
            rows.append(_row(
                patent_id, "T2", sub_dim, field, f"{sub_dim} — {field}", "|".join(options),
                entry.get("value"), entry.get("confidence"), "siglip" if entry.get("value") else None,
                img_path, needs_review=_needs_review("T2", entry.get("confidence")),
            ))

        parts = preds.get("parts") or []
        rows.append(_row(
            patent_id, "T2", sub_dim, "parts", f"{sub_dim} — visible parts", "|".join(T2_PARTS),
            "|".join(parts), None, "siglip" if parts else None, img_path,
        ))

        rows.append(_row(
            patent_id, "T2", sub_dim, "match_status", f"{sub_dim} — OCR/description match status", "",
            img.get("match_status"), img.get("composite_confidence"), img.get("match_method"), img_path,
        ))

    # ── G1 ──────────────────────────────────────────────────────────────────
    g1 = record.get("G1_prediction") or {}
    top_type = g1.get("value")
    rows.append(_row(
        patent_id, "G1", "Topology Type", "topType", "Architecture topology type",
        _OPT(G1_TOP_TYPES), top_type, g1.get("confidence"), g1.get("source"),
        needs_review=_needs_review("G1", g1.get("confidence")),
    ))

    # ── M1 ──────────────────────────────────────────────────────────────────
    m1 = record.get("M1_predictions") or {}
    for field, defs in [
        ("fusShape", _M1_FUS_SHAPE_DEFS), ("fusKin", _M1_FUS_KIN_DEFS),
        ("gearArch", _M1_GEAR_ARCH_DEFS), ("latSym", _M1_LAT_SYM_DEFS),
    ]:
        value, conf, source = _pred_val(m1, field)
        rows.append(_row(patent_id, "M1", field, field, field, _OPT(defs), value, conf, source,
                          needs_review=_needs_review("M1", conf)))

    for field, sub_dim, options in _M1_MANUAL:
        rows.append(_row(patent_id, "M1", sub_dim, field, sub_dim, options))

    # ── M2 ── sanitize against wizard's option filters (mirrors the old
    # build_patent_html()'s eOpts/kOpts/physics-lock logic) ──────────────────
    m2 = record.get("M2_predictions") or {}
    is_winged = top_type in ("TW", "TP", "DS", "CVT", "SLC", "SRW")
    g1_focus  = "winged" if is_winged else ("wingless" if top_type in ("RC", "MR") else "other")

    wing_conf, wing_conf_conf, wing_conf_src = _pred_val(m2, "wingConf")
    if not is_winged:
        wing_conf, wing_conf_conf, wing_conf_src = None, None, None

    w_count_v, w_count_conf, w_count_src = _pred_val(m2, "wCount")
    w_count = int(w_count_v) if w_count_v and str(w_count_v).isdigit() else 1

    emp_type, emp_type_conf, emp_type_src = _pred_val(m2, "empType")
    if (g1_focus == "other" or top_type == "MR") and emp_type not in ("Tailless", "Fins", None):
        emp_type, emp_type_conf, emp_type_src = None, None, None

    emp_kin, emp_kin_conf, emp_kin_src = _pred_val(m2, "empKin")
    if top_type == "RC":
        if emp_kin not in ("Fixed", "Stabilator", None):
            emp_kin, emp_kin_conf, emp_kin_src = None, None, None
    elif emp_kin == "Stabilator":
        emp_kin, emp_kin_conf, emp_kin_src = None, None, None
    if top_type == "TW" and emp_type not in (None, "Tailless", "Fins"):
        emp_kin, emp_kin_conf, emp_kin_src = "Fixed", emp_kin_conf, "ensemble"  # physics lock

    rows.append(_row(patent_id, "M2", "wingConf", "wingConf", "wingConf", _OPT(_M2_WING_CONF_DEFS),
                      wing_conf, wing_conf_conf, wing_conf_src,
                      needs_review=_needs_review("M2", wing_conf_conf)))
    rows.append(_row(patent_id, "M2", "wCount", "wCount", "wCount", _OPT(_M2_WCOUNT_DEFS),
                      w_count_v, w_count_conf, w_count_src,
                      needs_review=_needs_review("M2", w_count_conf)))
    rows.append(_row(patent_id, "M2", "empType", "empType", "empType", _OPT(_M2_EMP_TYPE_DEFS),
                      emp_type, emp_type_conf, emp_type_src,
                      needs_review=_needs_review("M2", emp_type_conf)))
    rows.append(_row(patent_id, "M2", "empKin", "empKin", "empKin", _OPT(_M2_EMP_KIN_DEFS),
                      emp_kin, emp_kin_conf, emp_kin_src,
                      needs_review=_needs_review("M2", emp_kin_conf)))

    if is_winged and wing_conf == "W":
        for wi in range(1, max(w_count, 1) + 1):
            for field, label, options in _WING_MANUAL:
                rows.append(_row(
                    patent_id, "M2", f"Wing {wi} — {label}", f"wing{wi}_{field}",
                    f"Wing {wi} — {label}", options,
                ))

    # ── M3 — one set of rows per propulsion-card component ───────────────────
    m3 = record.get("M3_predictions") or {}
    orient_v, orient_conf, orient_src = _pred_val(m3, "orient")
    if top_type in ("SLC", "SRW") and orient_v == "Tilting_Mechanism":
        orient_v, orient_conf, orient_src = None, None, None
    # Stopped_Wing is only ever offered as a choice for SRW in the HTML
    # wizard's m3OrientationOptions() — strip it for every other topology so
    # an ML prediction can never disagree with what a human reviewer is even
    # allowed to pick.
    if top_type != "SRW" and orient_v == "Stopped_Wing":
        orient_v, orient_conf, orient_src = None, None, None
    chord_v, chord_conf, chord_src = _pred_val(m3, "chord")
    bmech_v, bmech_conf, bmech_src = _pred_val(m3, "bmech")
    rmech_v, rmech_conf, rmech_src = _pred_val(m3, "rmech")

    for component in m3_card_keys(top_type, wing_conf, w_count, emp_type):
        sub_dim = f"Propulsion: {component}"
        for field, defs, value, conf, source in [
            ("chord",  _M3_CHORD_DEFS,  chord_v,  chord_conf,  chord_src),
            ("orient", _M3_ORIENT_DEFS, orient_v, orient_conf, orient_src),
            ("bmech",  _M3_BMECH_DEFS,  bmech_v,  bmech_conf,  bmech_src),
            ("rmech",  _M3_RMECH_DEFS,  rmech_v,  rmech_conf,  rmech_src),
        ]:
            rows.append(_row(patent_id, "M3", sub_dim, f"{component}_{field}",
                              f"{sub_dim} — {field}", _OPT(defs), value, conf, source,
                              needs_review=_needs_review("M3", conf)))
        for field, label, options in _M3_MANUAL:
            rows.append(_row(patent_id, "M3", sub_dim, f"{component}_{field}",
                              f"{sub_dim} — {label}", options))

    return rows


def rows_to_dataframe(rows: list[dict]):
    import pandas as pd
    return pd.DataFrame(rows, columns=COLUMNS)


def export_source_excel(all_rows: list[dict], out_path: Path) -> None:
    """Write source_patents.xlsx (single 'Review' sheet) from scratch."""
    df = rows_to_dataframe(all_rows)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, sheet_name="Review", index=False)


def append_reviewed_rows(rows: list[dict], out_path: Path) -> None:
    """
    True append (no full-file rewrite) into reviewed_patents.xlsx's 'Review'
    sheet — keeps "Save & Next" fast even as the file grows across a long
    review session. Creates the workbook with header if it doesn't exist yet.
    """
    import openpyxl

    out_path = Path(out_path)
    extra_cols = ["Reviewer", "Reviewed_At"]
    full_columns = COLUMNS + extra_cols

    if out_path.exists():
        wb = openpyxl.load_workbook(out_path)
        ws = wb["Review"]
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Review"
        ws.append(full_columns)

    for row in rows:
        ws.append([row.get(col) for col in full_columns])

    wb.save(out_path)
