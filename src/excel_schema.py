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

from src.cross_modal import (
    T2_PER, T2_AC_STY, T2_AC_COL, T2_BG_STY, T2_BG_COL, T2_PARTS, T2_ROT,
    T2_AC_STATE, T2_TILTED, T2_DINO_UNDERSTANDING, G1_TOP_TYPES,
)
from src.reviewer import (
    _T1_SCOPE_DEFS, _T1_FIELD_DEFS, _T1_TARGET_DEFS,
    _M1_FUS_SHAPE_DEFS, _M1_FUS_KIN_DEFS, _M1_GEAR_ARCH_DEFS, _M1_LAT_SYM_DEFS,
    _M2_WING_CONF_DEFS, _M2_EMP_TYPE_DEFS, _M2_EMP_KIN_DEFS, _M2_WCOUNT_DEFS,
    _M3_CHORD_DEFS, _M3_ORIENT_DEFS, _M3_BMECH_DEFS, _M3_RMECH_DEFS, _M3_PROPKIN_DEFS,
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
    ("t1DisapproveReason",  "T1 — Disapproval Reason",    "Pure UAV|Out of Domain|Unreadable|No Aircraft Image|Other"),
    ("archCount",           "T1 — Distinct Architectures", ""),
    ("isDuplicate",         "T1 — Duplicate Flag",        "true|false"),
    ("duplicateId",         "T1 — Duplicate Of (Patent ID)", ""),
]

# G1 has one predicted field (topType, emitted directly below) plus this
# human-only reviewer judgment: whether the patent is NOT a single clean
# architecture (a hybrid / mixed / transitional concept). No ML signal for it —
# mirrors the HTML wizard's "Architecture Purity" checkbox (G1 page).
_G1_MANUAL = [
    ("notPureArch", "Architecture Purity", "true|false"),
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
    ("wPosV",  "Vertical Position", "High|Mid|Low|Unknown"),
    ("wPosL",  "Longitudinal Position", "Fwd|Cent|Aft"),
    ("wPlan",  "Planform",        "Str|Swp|Del|Oth"),
    ("wRole",  "Role",            "Canard|Tandem|Aft|Stacked"),
]

# sym / symLong stay human-only (blank); symCirc is filled from a SigLIP
# best-guess (margin-flagged) — see classify_m3_fields() + process_patent().
_M3_MANUAL = [
    ("count",     "Count",              ""),
    ("sym",       "Symmetric",          "true|false"),
    ("symLong",   "Longitudinally Symmetric",  "true|false"),
    ("symCirc",   "Circular / Radial Symmetry", "true|false"),
    ("zone",      "Zone",               "Nose|Aft|FusFront|FusRear|Side|Dorsal|Ventral|StackV|StackH|Tip|Other"),
    ("zoneChord", "Zone — Chordwise",   "LE|TE|Above|Below"),
    ("zoneSpan",  "Zone — Spanwise",    "Inboard|MidSpan|Outboard|Wingtip|FullSpan"),
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

    t1_triage_preds = {}
    for field, defs in [("scope", _T1_SCOPE_DEFS), ("t1Field", _T1_FIELD_DEFS), ("t1Target", _T1_TARGET_DEFS)]:
        value, conf, source = _pred_val(t1, field)
        t1_triage_preds[field] = (value, conf)
        rows.append(_row(patent_id, "T1", field, field, field, _OPT(defs), value, conf, source,
                          needs_review=_needs_review("T1", conf)))

    # isApproved auto-suggestion — Stage 01 has no dedicated domain classifier,
    # but scope/t1Field/t1Target predictions double as a cheap in-domain
    # signal: if SBERT/the ensemble couldn't predict any of the three at all,
    # the patent is very likely unreadable/out of domain; if it predicted all
    # three with decent average confidence, it's very likely in domain. Either
    # way this is a SUGGESTION, not a final call — Needs_Review stays True so
    # the human reviewer (02_taxonomy_review UI) always confirms or overrides
    # it rather than silently trusting the heuristic.
    # PatentSBERTa's T1 scope/field/target confidences run much lower in
    # absolute terms than e.g. SigLIP's — a real batch's average confidences
    # ranged ~0.40-0.57 (floor ~0.40, median ~0.51). 0.45 sits just above
    # that floor: it auto-suggests the clear majority of a batch (~25/30 in
    # that sample) while still excluding the handful of genuinely lowest-
    # confidence outliers. Going much lower than ~0.43 stops discriminating
    # at all in that distribution — everything clears it, making the
    # "suggestion" meaningless.
    _AUTO_APPROVAL_CONF_THRESHOLD = 0.45
    scope_v, scope_conf   = t1_triage_preds["scope"]
    field_v, field_conf   = t1_triage_preds["t1Field"]
    target_v, target_conf = t1_triage_preds["t1Target"]
    confs = [c for c in (scope_conf, field_conf, target_conf) if isinstance(c, (int, float))]
    avg_conf = sum(confs) / len(confs) if confs else None

    auto_approved, auto_reason = None, None
    if scope_v and field_v and target_v and avg_conf is not None and avg_conf >= _AUTO_APPROVAL_CONF_THRESHOLD:
        auto_approved = True
    elif not scope_v and not field_v and not target_v:
        auto_approved, auto_reason = False, "Unreadable"

    for field, sub_dim, options in _T1_MANUAL:
        if field == "isApproved" and auto_approved is not None:
            rows.append(_row(patent_id, "T1", sub_dim, field, sub_dim, options,
                              auto_approved, avg_conf, "auto_heuristic", needs_review=True))
        elif field == "t1DisapproveReason" and auto_reason is not None:
            rows.append(_row(patent_id, "T1", sub_dim, field, sub_dim, options,
                              auto_reason, None, "auto_heuristic", needs_review=True))
        else:
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
            ("per", T2_PER), ("acSty", T2_AC_STY),
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

        # acState — flight configuration shown in this figure (single-select).
        # NonApplicable is a rule override (classify_t2_fields), not a SigLIP
        # guess — listed in the options for round-trip parity with the HTML.
        ac_state = preds.get("acState") or {}
        rows.append(_row(
            patent_id, "T2", sub_dim, "acState", f"{sub_dim} — flight configuration shown",
            "|".join(T2_AC_STATE + ["NonApplicable"]), ac_state.get("value"), ac_state.get("confidence"),
            ac_state.get("source") if ac_state.get("value") else None, img_path,
            needs_review=_needs_review("T2", ac_state.get("confidence")),
        ))
        # tiltedInView — what is tilted/deployed in this view (multi-select).
        tilted = preds.get("tiltedInView") or []
        rows.append(_row(
            patent_id, "T2", sub_dim, "tiltedInView", f"{sub_dim} — what is tilted in view",
            "|".join(T2_TILTED), "|".join(tilted), None, "siglip" if tilted else None, img_path,
        ))

        rows.append(_row(
            patent_id, "T2", sub_dim, "match_status", f"{sub_dim} — OCR/description match status", "",
            img.get("match_status"), img.get("composite_confidence"), img.get("match_method"), img_path,
        ))

        # ── Duplicate-image cross-reference (SigLIP image-to-image) ───────────
        # Populated by the notebook's duplicate-detection cell (or a human in
        # the HTML wizard); emitted here — empty by default — so the schema is
        # stable and the wizard's rowsToAIData() always finds these fields.
        # dupOfPatent = the original patent this exact drawing first appeared
        # in; dupOfFig = that patent's figure number.
        rows.append(_row(
            patent_id, "T2", sub_dim, "dupOfPatent", f"{sub_dim} — duplicate of patent",
            "", img.get("dup_of_patent"), img.get("dup_score"),
            "siglip" if img.get("dup_of_patent") else None, img_path,
        ))
        rows.append(_row(
            patent_id, "T2", sub_dim, "dupOfFig", f"{sub_dim} — duplicate of figure",
            "", img.get("dup_of_fig"), None,
            "siglip" if img.get("dup_of_fig") else None, img_path,
        ))

    # ── G1 ──────────────────────────────────────────────────────────────────
    g1 = record.get("G1_prediction") or {}
    top_type = g1.get("value")
    rows.append(_row(
        patent_id, "G1", "Topology Type", "topType", "Architecture topology type",
        _OPT(G1_TOP_TYPES), top_type, g1.get("confidence"), g1.get("source"),
        needs_review=_needs_review("G1", g1.get("confidence")),
    ))
    # Human-only architecture-purity flag (no ML prediction) — blank for the
    # reviewer to tick in the wizard when the patent isn't one clean architecture.
    for field, sub_dim, options in _G1_MANUAL:
        rows.append(_row(patent_id, "G1", sub_dim, field, sub_dim, options))

    # ── M1 ──────────────────────────────────────────────────────────────────
    m1 = record.get("M1_predictions") or {}
    for field, defs in [
        ("fusShape", _M1_FUS_SHAPE_DEFS), ("fusKin", _M1_FUS_KIN_DEFS),
        ("gearArch", _M1_GEAR_ARCH_DEFS), ("latSym", _M1_LAT_SYM_DEFS),
    ]:
        value, conf, source = _pred_val(m1, field)
        rows.append(_row(patent_id, "M1", field, field, field, _OPT(defs), value, conf, source,
                          needs_review=_needs_review("M1", conf)))

    # dinoUnderstanding — projected level of understanding by DINOv2. This is
    # per-ARCHITECTURE in the HTML wizard, not per-image/patent: the pipeline
    # has no concept of multiple architectures yet, so this row pre-fills
    # architecture 1 only, exactly like every other M1 field above (a
    # multi-architecture patent's later architectures are filled by hand).
    dino_value, dino_conf, dino_source = _pred_val(m1, "dinoUnderstanding")
    rows.append(_row(
        patent_id, "M1", "dinoUnderstanding", "dinoUnderstanding", "dinoUnderstanding",
        _OPT(T2_DINO_UNDERSTANDING), dino_value, dino_conf, dino_source,
        needs_review=_needs_review("M1", dino_conf),
    ))

    # The pipeline never extracts real footprint dimensions (length/width/height),
    # so default footAmbiguous=True — this makes the wizard's "Bypass Missing
    # Measurements" button render pre-ticked, instead of forcing the reviewer to
    # tick it on every patent. The reviewer can still un-bypass and enter values.
    _m1_foot = record.get("M1_predictions") or {}
    _has_dims = any(_m1_foot.get(k) for k in ("footLen", "footWid", "footHgt"))
    for field, sub_dim, options in _M1_MANUAL:
        if field == "footAmbiguous" and not _has_dims:
            rows.append(_row(patent_id, "M1", sub_dim, field, sub_dim, options,
                              True, None, "auto_heuristic"))
        else:
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
    elif is_winged and wing_conf in ("BWB", "FW", "LB"):
        # Integrated-hull frameworks (Blended Wing Body / Flying Wing / Lifting
        # Body) have no discrete countable wing panel, so per-panel tilt/position/
        # role are bypassed — but the HTML wizard still records the overall
        # planform of the hull-as-wing (wing1_wPlan). Emit just that one row so
        # the pre-label structure matches the wizard. Human-only (planform isn't
        # ML-predicted for any wing config).
        _wplan_opts = next(o for f, l, o in _WING_MANUAL if f == "wPlan")
        rows.append(_row(
            patent_id, "M2", "Wing 1 — Planform", "wing1_wPlan",
            "Wing 1 — Planform", _wplan_opts,
        ))

    # ── M3 — one set of rows per propulsion-card component ───────────────────
    m3 = record.get("M3_predictions") or {}
    orient_v, orient_conf, orient_src = _pred_val(m3, "orient")
    # SLC (separate fixed lift+cruise) and SRW (stopped rotor) don't tilt, so a
    # "Mixed" (tilting/vectoring) orient prediction is disallowed for them —
    # strip it so an ML guess can't disagree with what the human can even pick.
    if top_type in ("SLC", "SRW") and orient_v == "Mixed":
        orient_v, orient_conf, orient_src = None, None, None
    chord_v, chord_conf, chord_src = _pred_val(m3, "chord")
    bmech_v, bmech_conf, bmech_src = _pred_val(m3, "bmech")
    rmech_v, rmech_conf, rmech_src = _pred_val(m3, "rmech")
    propkin_v, propkin_conf, propkin_src = _pred_val(m3, "propKin")
    # NOTE: TP no longer force-locks propKin=Tilt, and DS is no longer locked to
    # Fixed either. The HTML wizard's physics matrix leaves articulation FREE for
    # TP, CVT and DS (a deflected-slipstream patent can still articulate its
    # propulsors) — while only TW/SLC/SRW/MR lock to Fixed and RC to Cyclic
    # (handled by the wizard / SBERT side). So we pass SigLIP/SBERT's predicted
    # propKin through unchanged for these and let the reviewer confirm it (it's
    # margin-flagged for review).

    # Spatial mounting predictions (image-level, best-effort, margin-flagged).
    # Applied PER component type below: wing cards take zoneChord/zoneSpan;
    # fuselage/core/hull cards take zone (Nose/Aft/Side/Dorsal/Ventral). The emp
    # card's zone uses a different vocab (StackV/StackH/Tip) that SigLIP isn't
    # scored against, so it's left blank for the human. Boom geometry is not
    # emitted here at all — it lives in the M1 "boom groups" (human-only,
    # variable-count, round-tripped by the HTML wizard); the pipeline emits no
    # dedicated boom card and no per-card boom attach/position fields.
    zonechord_v, zonechord_conf, zonechord_src = _pred_val(m3, "zoneChord")
    zonespan_v,  zonespan_conf,  zonespan_src  = _pred_val(m3, "zoneSpan")
    zone_v,      zone_conf,      zone_src       = _pred_val(m3, "zone")
    # symCirc (circular/radial propulsor arrangement) — one card-level SigLIP
    # best-guess applied to every propulsion card (margin-flagged for review).
    symcirc_v,   symcirc_conf,  symcirc_src    = _pred_val(m3, "symCirc")

    for component in m3_card_keys(top_type, wing_conf, w_count, emp_type):
        sub_dim = f"Propulsion: {component}"
        is_wing = component.startswith("wing")
        # fuselage/core_layout/hull_array share the Nose/Aft/Side/Dorsal/Ventral
        # zone vocab; emp does NOT (StackV/StackH/Tip), so it stays unpredicted.
        zone_predicted = component in ("fuselage", "core_layout", "hull_array")
        for field, defs, value, conf, source in [
            ("chord",   _M3_CHORD_DEFS,   chord_v,   chord_conf,   chord_src),
            ("orient",  _M3_ORIENT_DEFS,  orient_v,  orient_conf,  orient_src),
            ("bmech",   _M3_BMECH_DEFS,   bmech_v,   bmech_conf,   bmech_src),
            ("rmech",   _M3_RMECH_DEFS,   rmech_v,   rmech_conf,   rmech_src),
            ("propKin", _M3_PROPKIN_DEFS, propkin_v, propkin_conf, propkin_src),
        ]:
            rows.append(_row(patent_id, "M3", sub_dim, f"{component}_{field}",
                              f"{sub_dim} — {field}", _OPT(defs), value, conf, source,
                              needs_review=_needs_review("M3", conf)))
        for field, label, options in _M3_MANUAL:
            # Fill the spatial mounting fields from SigLIP per component type;
            # everything else (count/sym/notes) stays human-entered (blank).
            sp_val = sp_conf = sp_src = None
            if field == "zoneChord" and is_wing:
                sp_val, sp_conf, sp_src = zonechord_v, zonechord_conf, zonechord_src
            elif field == "zoneSpan" and is_wing:
                sp_val, sp_conf, sp_src = zonespan_v, zonespan_conf, zonespan_src
            elif field == "zone" and zone_predicted:
                sp_val, sp_conf, sp_src = zone_v, zone_conf, zone_src
            elif field == "symCirc":
                sp_val, sp_conf, sp_src = symcirc_v, symcirc_conf, symcirc_src
            rows.append(_row(patent_id, "M3", sub_dim, f"{component}_{field}",
                              f"{sub_dim} — {label}", options, sp_val, sp_conf, sp_src,
                              needs_review=_needs_review("M3", sp_conf) if sp_val else None))

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
