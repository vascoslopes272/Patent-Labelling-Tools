"""
reviewer.py — assemble per-patent prediction records (T1 + T3) and auto-fill
visual fields. Records are returned in-memory and exported to
source_patents.xlsx by src/excel_schema.py — no per-patent JSON/HTML files.

Public API
----------
auto_fill_visual(description)                              → dict
classify_t1_dimensions(text, sbert_model)                  → dict
assemble_patent_json(patent_id, excel_row, match_results)  → dict
resolve_patent_image_dir(matched_dir, patent_id)           → Path
process_patent(patent_id, cfg, excel_index, raw_dir)       → dict
run_stage01(cfg, ...)                                       → pd.DataFrame
"""

from pathlib import Path

from src.matcher import label_from_filename

# Shown by 02_taxonomy_review.ipynb (and used by excel_schema.build_patent_rows)
# whenever a patent has zero figures or a row's Image_Path doesn't resolve to
# an existing file, so the review-UI image loop never crashes on a missing asset.
PLACEHOLDER_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "no_image_available.png"

# Lazily-populated cache of patent_id -> description_of_drawings, loaded from
# data/descriptions.csv (written by notebook 00b2). There is no text/ dir.
_DESC_CACHE: dict[str, str] = {}


def _load_review_flags(data_dir: Path, filename: str = "crops_mapping.csv") -> dict[str, dict[str, str]]:
    """
    Reads crops_mapping.csv (written by notebook 00b2 Cell 4, crop_quality column
    appended by Cell 5b, both updated live by the Cell 5c Keep/Relabel/Reject
    reviewer) — or, for a specific batch, data/<Batch_NN>/crops_mapping_<Batch_NN>.csv
    (pass that filename explicitly; 00b2 nests + renames this file per batch).

    Deliberately NOT needs_human_review.csv: that file is a one-time snapshot taken
    right after the OCR/Qwen pass, before crop_quality even exists and before any
    Cell 5c review happens, so it goes stale immediately and never gains
    crop_quality at all. crops_mapping.csv is the live, complete source — same data
    Cell 5c itself reads and writes — so flags here always reflect the current
    state, not a frozen pre-review snapshot.

    Only rows that actually need attention (needs_review == True, or a non-empty
    crop_quality) are included — crops_mapping.csv has one row per crop overall.

    Returns:
        {patent_id: {output_filename: crop_quality_string}}
    where output_filename is the bare filename (no directory prefix).
    Returns {} if the file does not exist or cannot be parsed.
    """
    import pandas as pd
    csv_path = Path(data_dir) / filename
    if not csv_path.exists():
        return {}
    try:
        df = pd.read_csv(csv_path)
        if "crop_quality" not in df.columns:
            df["crop_quality"] = ""
        df["crop_quality"] = df["crop_quality"].fillna("")
        needs_attention = (df["needs_review"] == True) | (df["crop_quality"] != "")  # noqa: E712
        flags: dict[str, dict[str, str]] = {}
        for _, row in df.loc[needs_attention].iterrows():
            pid = str(row.get("patent_id", "")).strip()
            out = str(row.get("output", "")).strip()
            qual = str(row.get("crop_quality", "")).strip()
            if pid and out:
                fname = Path(out).name   # strip any directory prefix
                flags.setdefault(pid, {})[fname] = qual
        return flags
    except Exception:
        return {}


def _resolve_crops_csv(cfg: dict, matched_dir: Path) -> Path:
    """
    Resolve the crops_mapping CSV to use for this run: prefers the per-batch
    nested copy 00b2 writes (data/matched/<Batch_NN>/crops_mapping_<Batch_NN>.csv,
    inferred from matched_dir's leaf folder when it's nested directly under
    cfg["paths"]["matched"]), falling back to the flat data/crops_mapping.csv
    when the nested copy isn't actually on disk — matched/ and data/matched/ don't
    always get nested in lockstep (e.g. matched/ was re-run per-batch before
    00b2 started writing the per-batch data/matched/ copy too).
    """
    data_dir          = Path(cfg["paths"]["data"])
    data_matched_dir  = Path(cfg["paths"].get("data_matched", data_dir))
    flat_matched_root = Path(cfg["paths"]["matched"])
    matched_dir       = Path(matched_dir)
    if matched_dir != flat_matched_root and matched_dir.parent == flat_matched_root:
        batch_label = matched_dir.name
        candidate   = data_matched_dir / batch_label / f"crops_mapping_{batch_label}.csv"
        if candidate.exists():
            return candidate
    return data_dir / "crops_mapping.csv"


def _load_match_results(data_dir: Path, filename: str = "crops_mapping.csv") -> dict[str, dict[str, dict]]:
    """
    Reads the matched_description/match_status/etc. columns from
    crops_mapping.csv — written by notebook 00b2's description-matching cell
    (moved there from process_patent(), which used to recompute this from
    scratch on every single Stage 01 run even though 00b2 already has
    everything needed: the filenames it just cropped + descriptions.csv).

    Returns:
        {patent_id: {output_filename: {matched_description, match_status,
                                        match_method, match_confidence,
                                        semantic_best_score, fig_number,
                                        duplicate_group}}}
    Returns {} if the file does not exist, predates this matching step (no
    "match_status" column yet), or cannot be parsed.
    """
    import pandas as pd
    csv_path = Path(data_dir) / filename
    if not csv_path.exists():
        return {}
    try:
        df = pd.read_csv(csv_path)
        if "match_status" not in df.columns:
            return {}

        def _clean(v):
            # NaN survives df.where()/fillna() tricks on numeric-dtype columns
            # (assigning None back into a float64 column just becomes NaN
            # again) — and float('nan') is truthy in Python, so callers doing
            # `if value:` would treat a missing value as present. pd.isna()
            # is the only check that catches both NaN and real None/empty.
            return None if pd.isna(v) else v

        results: dict[str, dict[str, dict]] = {}
        for _, row in df.iterrows():
            pid = str(_clean(row.get("patent_id")) or "").strip()
            out = str(_clean(row.get("output")) or "").strip()
            if not pid or not out:
                continue
            fname = Path(out).name
            results.setdefault(pid, {})[fname] = {
                "matched_description": _clean(row.get("matched_description")),
                "match_status":        _clean(row.get("match_status")) or "unmatched",
                "match_method":        _clean(row.get("match_method")),
                "match_confidence":    float(_clean(row.get("match_confidence")) or 0.0),
                "semantic_best_score": float(_clean(row.get("semantic_best_score")) or 0.0),
                "fig_number":          _clean(row.get("fig_number")),
                "duplicate_group":     _clean(row.get("duplicate_group")),
            }
        return results
    except Exception:
        return {}


# ─── Visual field keyword rules ─────────────────────────────────────────────
# Field names AND values below match the master HTML wizard's T2 enums
# exactly (per/acSty/acCol/bgSty/bgCol) so this output can be ingested
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

# Rendering-style vocab is [Render, Line Drawing, Draft, Blueprint] — matches
# T2_AC_STY in cross_modal.py and the HTML wizard. Unmatched text falls back to
# "Line Drawing" (the default in auto_fill_visual below), which also absorbs the
# old schematic/diagram cases since those are line art in this scheme.
_STYLE_RULES: list[tuple[list[str], str]] = [
    (["blueprint", "blue print", "cyanotype"],                       "Blueprint"),
    (["shaded", "rendered", "render", "solid model", "filled model",
      "photoreal", "perspective render"],                            "Render"),
    (["draft", "draught", "sketch", "preliminary"],                  "Draft"),
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

    Field names/values match the master HTML wizard exactly (per/acSty/
    acCol/bgSty/bgCol/parts). Fields that can be inferred get source="auto".
    Unknown fields get value=None, source=None (filled later by the wizard).
    """
    def _auto(value: str | None) -> dict:
        return {"value": value, "source": "auto" if value else None}

    if not description:
        return {
            "per":   {"value": None, "source": None},
            "acSty": {"value": None, "source": None},
            "acCol": {"value": None, "source": None},
            "bgSty": {"value": None, "source": None},
            "bgCol": {"value": None, "source": None},
            "parts": [],
        }

    return {
        "per":   _auto(_first_match(description, _PERSPECTIVE_RULES)),
        "acSty": _auto(_first_match(description, _STYLE_RULES) or "Line Drawing"),
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


# ─── G1/M1/M2/M3 text-based classification (SBERT) ──────────────────────────
# Patent text (title/abstract/claims/description) often states the whole-
# aircraft architecture explicitly ("a fixed-wing aircraft with a V-tail and
# skid landing gear..."), unlike T2 which is genuinely per-figure-visual and
# has no text equivalent. These mirror the *value* sets SigLIP uses in
# cross_modal.py exactly (same ids) so the two prediction sources can be
# merged field-by-field. Wording differs slightly (declarative "this patent
# describes X" vs SigLIP's "a patent drawing of X") since one is judged
# against running prose and the other against an image.

_G1_TOP_TYPE_DEFS = {
    "TW":  "this patent describes a tilt wing aircraft where the entire wing panel rotates to vector thrust",
    "TP":  "this patent describes tilt propulsors where propulsors tilt independently while the wing stays fixed",
    "DS":  "this patent describes a deflected slipstream aircraft with fixed propellers and structural flaps that deflect airflow",
    "CVT": "this patent describes a combined aircraft with fixed lift rotors plus tilting propulsors",
    "SLC": "this patent describes a lift plus cruise aircraft with separate fixed hover rotors and fixed cruise propulsors",
    "SRW": "this patent describes a stopped rotor wing aircraft where the rotors stop and lock in cruise to act as a fixed wing",
    "RC":  "this patent describes a rotorcraft, a single-rotor, coaxial, or tandem helicopter layout",
    "MR":  "this patent describes a multirotor aircraft with distributed fixed rotors in a drone or multicopter layout",
    "HB":  "this patent describes a motorcycle-style frame with tandem or side-by-side rotors mounted above a seated rider straddle position",
    "PFV": "this patent describes a wearable jetpack or thrust-vectored suit strapped directly to a standing human body with no separate vehicle frame",
}
# ── G1 keyword priors ───────────────────────────────────────────────────────
# High-precision phrase → topology rules. Architecture and (especially)
# whether propulsors TILT is almost always *stated* in the claims/abstract, but
# is invisible in a single static line drawing — so these giveaway phrases pin
# the unambiguous cases before the SBERT/SigLIP fight, which otherwise confuses
# the visually-near-identical SLC (separate fixed lift+cruise) and TP (tilting
# propulsors). Order matters: the most specific multi-word phrases are checked
# first (see classify_g1_keyword). Phrases are matched case-insensitively as
# substrings, with light separator tolerance (space/hyphen) applied in the
# matcher, so "tilt-rotor"/"tilt rotor"/"tiltrotor" all hit.
_G1_KEYWORD_RULES: list[tuple[list[str], str]] = [
    # Tilt families — explicit tilt language ⇒ a tilt topology, never SLC.
    (["tilt wing", "tiltwing"],                                              "TW"),
    (["tiltrotor", "tilt rotor", "tilt prop", "tilting prop", "tilting rotor",
      "tiltable", "rotatable nacelle", "tiltable nacelle", "nacelle tilts",
      "nacelles tilt", "tilts to transition", "tilt mechanism",
      "tilting mechanism", "pivoting nacelle"],                             "TP"),
    # Lift+Cruise / independent fixed thrust — the case that was misread as TP.
    (["lift plus cruise", "lift and cruise", "lift+cruise", "lift cruise",
      "dedicated cruise", "separate cruise", "independent cruise",
      "separate hover", "dedicated lift rotor", "no tilting",
      "non-tilting", "fixed cruise prop", "fixed lift rotor"],              "SLC"),
    (["deflected slipstream", "blown flap", "blown wing"],                  "DS"),
    (["stopped rotor", "stoppable rotor", "stop-fold", "stowed rotor"],     "SRW"),
    (["multirotor", "multicopter", "quadcopter", "octocopter",
      "distributed electric propulsion"],                                   "MR"),
    (["helicopter", "coaxial rotor", "tandem rotor", "main rotor and tail"], "RC"),
]


def classify_g1_keyword(text: str | None) -> "dict | None":
    """High-precision keyword prior for G1 topology. Returns a high-confidence
    {value, confidence, source:"keyword"} when a giveaway phrase is present, else
    None. Whitespace/hyphens between words are treated as interchangeable so
    "tilt-rotor"/"tilt rotor"/"tiltrotor" all match. Rules are evaluated in
    order; the first matching topology wins (most specific tilt phrases first)."""
    if not text or not text.strip():
        return None
    import re as _re
    # collapse runs of spaces/hyphens to a single space for tolerant matching
    hay = _re.sub(r"[\s\-]+", " ", text.lower())
    for phrases, value in _G1_KEYWORD_RULES:
        for p in phrases:
            needle = _re.sub(r"[\s\-]+", " ", p.lower())
            if needle in hay:
                return {"value": value, "confidence": 0.92, "source": "keyword"}
    return None


# ── Kinematic / architecture sentence mining ────────────────────────────────
# Cue words that mark a sentence as carrying architecture/kinematic signal
# (how thrust is vectored, whether propulsors tilt, lift-vs-cruise split, etc.).
# SBERT only sees ~384 tokens, so a long claim/description dilutes the few
# signal-bearing sentences with boilerplate. extract_kinematic_sentences()
# below keeps ONLY the sentences containing one of these cues, producing a
# short, signal-dense string to feed the G1 keyword prior + the SBERT
# G1/empKin/orient/propKin classifiers (see process_patent / LEVER 2 & 3).
# Matched case-insensitively as whole-ish substrings with space/hyphen
# tolerance (so "lift-and-cruise"/"lift and cruise"/"lift+cruise" all hit) —
# same normalisation as classify_g1_keyword.
_KINEMATIC_CUE_WORDS: list[str] = [
    # tilt / pivot / rotate articulation
    "tilt", "tilting", "tiltable", "tiltrotor", "tilt rotor", "tilt wing",
    "rotatable", "rotates", "rotating", "pivot", "pivoting", "pivotable",
    "swivel", "swiveling", "articulat",          # articulate/articulating/articulation
    "nacelle", "nacelles",
    # lift+cruise / dedicated-thrust split
    "lift and cruise", "lift plus cruise", "lift+cruise", "lift cruise",
    "dedicated cruise", "separate cruise", "independent cruise",
    "dedicated lift", "separate hover", "hover rotor", "cruise propeller",
    "cruise propulsor", "cruise prop", "forward thrust", "vertical lift",
    # stopped / stowed / folding rotor
    "stopped rotor", "stoppable rotor", "stop fold", "stop-fold",
    "stowed", "stowable", "stow", "folding rotor", "fold", "retract",
    # slipstream / vectoring / transition flight
    "deflected slipstream", "blown flap", "blown wing", "slipstream",
    "vector", "vectored", "vectoring", "thrust vector",
    "transition", "transitions", "transitioning",
    "hover", "hovering", "cruise flight", "forward flight",
    # rotor topology cues
    "coaxial", "tandem", "ducted", "shrouded", "propulsor", "propulsors",
    "actuat",                                     # actuate/actuator/actuation
]


def extract_kinematic_sentences(
    text: str | None,
    cue_words: list[str] | None = None,
    max_sentences: int | None = None,
) -> str:
    """Mine the architecture/kinematic-bearing sentences out of `text`.

    Splits `text` into sentences and keeps ONLY those containing at least one
    kinematic cue word (_KINEMATIC_CUE_WORDS by default), dropping boilerplate.
    The result is a short, signal-dense string suitable for SBERT's ~384-token
    window and for the keyword priors — the point is to stop diluting the
    embedding with background prose (see LEVER 2 in process_patent).

    Matching is case-insensitive with space/hyphen tolerance (so
    "lift-and-cruise" matches the cue "lift and cruise"), mirroring
    classify_g1_keyword's normalisation.

    Args:
        text:          raw prose (e.g. first_claim + innovation_objective).
        cue_words:     override cue list (defaults to _KINEMATIC_CUE_WORDS).
        max_sentences: optional cap on how many matched sentences to keep
                       (first-N, preserving order) to bound the output length.

    Returns:
        The matched sentences joined by " " (single space), or "" when `text`
        is empty / no sentence carries a cue. Backward-compatible: both extra
        args are optional with safe defaults.
    """
    if not text or not text.strip():
        return ""
    import re as _re

    cues = cue_words if cue_words is not None else _KINEMATIC_CUE_WORDS
    # Pre-normalise each cue (collapse space/hyphen runs) once.
    needles = [_re.sub(r"[\s\-]+", " ", c.lower()) for c in cues]

    # Sentence split on ., !, ? and newlines. Patent claims often have no
    # terminal punctuation between numbered clauses, so newlines and semicolons
    # also act as boundaries — keeps each clause independently filterable.
    sentences = _re.split(r"(?<=[.!?])\s+|[\n;]+", text)

    kept: list[str] = []
    for sent in sentences:
        s = sent.strip()
        if not s:
            continue
        hay = _re.sub(r"[\s\-]+", " ", s.lower())
        if any(n in hay for n in needles):
            kept.append(s)
            if max_sentences is not None and len(kept) >= max_sentences:
                break
    return " ".join(kept)


_M1_FUS_SHAPE_DEFS = {
    "Circular":    "the aircraft has a circular or cylindrical tubular fuselage",
    "Oval":        "the aircraft has an oval or elliptical fuselage cross-section",
    "Rectangular": "the aircraft has a rectangular or box-shaped fuselage",
    "Blended":     "the aircraft has a blended wing body or lifting body fuselage merged into the wings",
    "PodBoom":     "pod and boom fuselage: a small central pod or nacelle housing occupants or "
                   "payload, with one or two slender structural booms extending rearward to carry the "
                   "empennage, typical of Robinson R22-style helicopter derivatives and tandem-rotor UAVs",
}
_M1_FUS_KIN_DEFS = {
    "Fixed":    "the aircraft has a conventional fixed fuselage that does not tilt or pivot",
    "Variable": "the aircraft has a variable incidence or tilting fuselage body that rotates during transition",
}
_M1_GEAR_ARCH_DEFS = {
    "Skids":      "the aircraft has fixed skid-type landing gear or runners",
    "FixedWheel": "the aircraft has fixed non-retractable wheeled landing gear",
    "RetrWheel":  "the aircraft has retractable wheeled landing gear that folds into the body",
    "PadsHull":   "the aircraft has hull pads, pontoons, or belly-contact landing surfaces",
}
_M1_LAT_SYM_DEFS = {
    "true":  "the aircraft is laterally symmetric with mirror-identical left and right halves",
    "false": "the aircraft is laterally asymmetric with different left and right sides",
}
_M2_WING_CONF_DEFS = {
    "W":   "the aircraft has one or more distinct standard wing panels attached to the fuselage",
    "BWB": "the aircraft has a blended wing body where fuselage and wings merge smoothly",
    "FW":  "this is a flying wing aircraft with no distinct fuselage",
    "LB":  "this is a lifting body aircraft where the fuselage itself generates most of the lift without wings",
}
_M2_EMP_TYPE_DEFS = {
    "Tailless":     "the aircraft has no tail empennage, a tailless or flying wing design",
    "Conventional": "the aircraft has a conventional horizontal stabilizer at the base of the vertical tail",
    "Cruciform":    "the aircraft has a cruciform tail where the horizontal stabilizer is at mid-height on the vertical fin",
    "T-Tail":       "the aircraft has a T-tail where the horizontal stabilizer is mounted at the top of the vertical fin",
    "V-Tail":       "the aircraft has a V-shaped tail combining horizontal and vertical stabilization",
    "Inv_V-Tail":   "the aircraft has an inverted V-tail pointing downward",
    "H-Tail":       "the aircraft has an H-tail or twin-boom tail with two vertical fins connected by a horizontal stabilizer",
    "VertFin":      "the aircraft has one or more vertical fins only, with no horizontal stabilizer",
    "Fins":         "the aircraft has minimal small stabilizing fins rather than a full tail empennage",
}
_M2_EMP_KIN_DEFS = {
    "Fixed":      "the tail empennage is fixed and does not tilt or move",
    "Tilt":       "the entire aft tail assembly tilts together with the wing during transition",
    "Stabilator": "the aircraft has an all-moving stabilator where the entire horizontal tail pivots for pitch control",
}
_M2_WCOUNT_DEFS = {
    "1": "the aircraft has one single main wing",
    "2": "the aircraft has two wings such as a biplane, canard-wing, or tandem wing configuration",
    "3": "the aircraft has three wing panels or lifting surfaces",
    "4": "the aircraft has four or more wing panels",
}
_M3_CHORD_DEFS = {
    "Front": "the rotors or propellers are positioned at the front leading edge, pulling the aircraft forward",
    "Back":  "the rotors or propellers are positioned at the back trailing edge, pushing the aircraft",
}
# orient vocab is [Horizontal, Vertical, Mixed], identical to vlm_extractor.py
# (the reference) and the HTML wizard's m3OrientationOptions(), so the SigLIP,
# SBERT and VLM modalities all emit the same strings and merge cleanly.
_M3_ORIENT_DEFS = {
    "Horizontal": "the propulsors are oriented horizontally for forward cruise thrust",
    "Vertical":   "the rotors are oriented vertically for hovering lift",
    "Mixed":      "the rotors or propulsors tilt or vector between vertical hover and horizontal cruise",
}
# bmech = blade HOUSING only: Open (exposed) vs Ducted (shrouded). The HTML
# wizard's BLADE_MECH has exactly these two — folding/stowing is NOT a blade
# housing trait, it's captured separately by rmech (Retractable). "Folded" was
# dropped here so SigLIP/SBERT/VLM can never emit a bmech value the wizard
# can't display as selected.
_M3_BMECH_DEFS = {
    "Open":   "the aircraft has open free rotor or propeller blades exposed to airflow",
    "Ducted": "the rotors are inside a duct, shroud, or enclosed fan housing",
}
_M3_RMECH_DEFS = {
    "Exposed":     "the rotors are non-retractable and permanently exposed outside the aircraft structure",
    "Retractable": "the rotors are retractable and fold into the aircraft structure during cruise",
}
# propKin (propulsor articulation kinematics) — vocab mirrors vlm_extractor.py.
_M3_PROPKIN_DEFS = {
    "Fixed":    "the propulsor is fixed in place with no articulation",
    "Tilt":     "the propulsor tilts as a unit to vector thrust between hover and cruise",
    "Vectored": "the propulsor uses thrust vectoring to redirect the exhaust or slipstream",
    "Cyclic":   "the rotor uses cyclic swashplate pitch control like a helicopter",
}

# Core M3 fields (the four/five visually-classified attribute axes) vs the
# SPATIAL mounting-position fields (HTML M3 zone/boom options). SigLIP predicts
# both (cross_modal.classify_m3_fields), but only image-level — the spatial ones
# are best-effort and margin-flagged. SBERT/VLM do NOT predict spatial, so they
# pass through the merges untouched (text.get(f) is None ⇒ visual wins).
_M3_CORE_FIELDS    = ["chord", "orient", "bmech", "rmech", "propKin"]
_M3_SPATIAL_FIELDS = ["zoneChord", "zoneSpan", "zone", "boomAttach", "boomPos"]


def _empty_pred() -> dict:
    return {"value": None, "confidence": 0.0, "source": None}


def _sbert_best(text: str | None, defs: dict, sbert_model) -> dict:
    """Cosine-similarity zero-shot classification of `text` against `defs`
    (id -> definition sentence). Same pattern as classify_t1_dimensions, just
    factored out so it can be reused for G1/M1/M2/M3 text classification."""
    if not text or not text.strip() or sbert_model is None:
        return _empty_pred()

    import numpy as np

    ids     = list(defs.keys())
    text_emb = sbert_model.encode([text], convert_to_numpy=True, normalize_embeddings=True)
    def_emb  = sbert_model.encode([defs[i] for i in ids], convert_to_numpy=True, normalize_embeddings=True)
    sims     = (def_emb @ text_emb.T).flatten()
    best_i   = int(np.argmax(sims))
    # margin = how far the winner beats the runner-up. A tiny margin means the
    # model is effectively guessing between two near-equal options (e.g. SLC vs
    # TP) — _margin_flag() uses this to mark the prediction for human review.
    margin = 1.0
    if len(sims) > 1:
        srt = np.sort(sims)[::-1]
        margin = float(srt[0] - srt[1])
    return {"value": ids[best_i], "confidence": round(float(sims[best_i]), 4),
            "source": "sbert", "margin": round(margin, 4)}


# Margin / confidence thresholds for "guess but flag" on the hard, ambiguous
# architecture/kinematic calls. A prediction is kept (we still output the best
# guess) but its confidence is capped below the review threshold so the wizard
# highlights it for verification when EITHER the winner barely beats the
# runner-up (close call) OR the raw confidence is already low.
_MARGIN_FLAG_THRESHOLD = 0.05   # top1 - top2 below this ⇒ effectively a tie
_LOW_CONF_THRESHOLD    = 0.45   # matches excel_schema's needs-review cutoff
# Capped confidence applied to a flagged guess. Kept strictly below the lowest
# confidence_routing threshold in config.yaml (M3=0.35) so a flagged prediction
# reliably trips Needs_Review in EVERY section, not just the high-threshold ones.
_FLAGGED_CONFIDENCE    = 0.30


def _margin_flag(pred: "dict | None") -> "dict | None":
    """Guess-but-flag for ambiguous architecture/kinematic predictions. If the
    prediction is a near-tie (small margin) or already low-confidence, KEEP the
    value but cap its confidence below the review threshold so the human is
    prompted to verify it — instead of letting a confident-looking wrong guess
    (e.g. SLC misread as TP) pass silently. Keyword-sourced predictions are
    trusted and never flagged. Returns the (possibly modified) prediction."""
    if not pred or pred.get("value") is None:
        return pred
    if pred.get("source") == "keyword":
        return pred
    margin = pred.get("margin", 1.0)
    conf   = pred.get("confidence", 0.0) or 0.0
    if (margin is not None and margin < _MARGIN_FLAG_THRESHOLD) or conf < _LOW_CONF_THRESHOLD:
        flagged = dict(pred)
        flagged["confidence"] = min(conf, _FLAGGED_CONFIDENCE)
        flagged["flagged_ambiguous"] = True
        return flagged
    return pred


def classify_g1_text(text: str | None, sbert_model=None) -> "dict | None":
    """SBERT text-based G1 topType classification — counterpart to
    cross_modal.classify_g1_hint() for patents whose text states the
    architecture explicitly. Returns None when text/model unavailable."""
    pred = _sbert_best(text, _G1_TOP_TYPE_DEFS, sbert_model)
    return pred if pred["value"] is not None else None


def classify_m1_text(text: str | None, sbert_model=None) -> dict:
    """SBERT text-based M1 structural field classification — counterpart to
    cross_modal.classify_m1_fields()."""
    result = {
        "fusShape": _sbert_best(text, _M1_FUS_SHAPE_DEFS, sbert_model),
        "fusKin":   _sbert_best(text, _M1_FUS_KIN_DEFS,   sbert_model),
        "gearArch": _sbert_best(text, _M1_GEAR_ARCH_DEFS, sbert_model),
        "latSym":   _sbert_best(text, _M1_LAT_SYM_DEFS,   sbert_model),
    }
    if result["latSym"]["value"] is not None:
        result["latSym"]["value"] = result["latSym"]["value"] == "true"
    return result


def classify_m2_text(text: str | None, sbert_model=None) -> dict:
    """SBERT text-based M2 aerodynamic field classification — counterpart to
    cross_modal.classify_m2_fields()."""
    return {
        "wingConf": _sbert_best(text, _M2_WING_CONF_DEFS, sbert_model),
        "empType":  _sbert_best(text, _M2_EMP_TYPE_DEFS,  sbert_model),
        "empKin":   _sbert_best(text, _M2_EMP_KIN_DEFS,   sbert_model),
        "wCount":   _sbert_best(text, _M2_WCOUNT_DEFS,    sbert_model),
    }


def classify_m3_text(text: str | None, sbert_model=None) -> dict:
    """SBERT text-based M3 propulsion field classification — counterpart to
    cross_modal.classify_m3_fields()."""
    return {
        "chord":   _sbert_best(text, _M3_CHORD_DEFS,   sbert_model),
        "orient":  _sbert_best(text, _M3_ORIENT_DEFS,  sbert_model),
        "bmech":   _sbert_best(text, _M3_BMECH_DEFS,   sbert_model),
        "rmech":   _sbert_best(text, _M3_RMECH_DEFS,   sbert_model),
        "propKin": _sbert_best(text, _M3_PROPKIN_DEFS, sbert_model),
    }


# ─── Cross-modal ensemble weighting (tunable) ───────────────────────────────
# Relative trust given to each modality when a SigLIP (visual) prediction and
# an SBERT (text) prediction disagree on the same field. The two confidences
# are scaled by these weights before comparison, so raising VISUAL_WEIGHT lets
# a visual prediction win more close calls (good when the figures are cleaner
# than the description text) and raising TEXT_WEIGHT favours the text side.
# Both 1.0 reproduces the original "pick the raw higher-confidence side"
# behaviour. The returned confidence is always the winning side's *unscaled*
# value, so downstream thresholds keep their normal meaning.
VISUAL_WEIGHT = 1.0
TEXT_WEIGHT   = 1.0

# When a VLM second opinion (src/vlm_extractor) is wired in, the local VLM
# (InternVL2-8B, M1/M2/M3) is only invoked for a figure if SigLIP is
# under-confident on at least one field — i.e. any field's confidence is below
# this threshold — so we don't spend VLM compute on figures SigLIP already reads
# cleanly. All inference is local; the path is opt-in (off unless the caller
# passes a vlm_bundle), so the default batch run is unaffected.
VLM_TRIGGER_CONFIDENCE = 0.65


def merge_field_predictions(visual: dict | None, text: dict | None) -> dict:
    """Pick the higher-confidence prediction between a SigLIP (visual) and
    SBERT (text) prediction for one field. Either side may be None/empty.
    Marks source="ensemble" when both sides agree on the value (cross-modal
    confirmation), otherwise keeps the winning side's own source tag so a
    human reviewer can tell which modality produced it. Close-call ties are
    broken using VISUAL_WEIGHT / TEXT_WEIGHT (see above)."""
    v = visual if visual and visual.get("value") is not None else None
    t = text   if text   and text.get("value")   is not None else None
    if v is None and t is None:
        return _empty_pred()
    if v is None:
        return t
    if t is None:
        return v
    if v["value"] == t["value"]:
        return {"value": v["value"], "confidence": max(v["confidence"], t["confidence"]), "source": "ensemble"}
    return v if v["confidence"] * VISUAL_WEIGHT >= t["confidence"] * TEXT_WEIGHT else t


def merge_prediction_dicts(visual: dict, text: dict, fields: list[str]) -> dict:
    """Apply merge_field_predictions() across every field in `fields` for two
    {field: {value, confidence, source}} dicts (e.g. M1/M2/M3 prediction sets)."""
    return {f: merge_field_predictions(visual.get(f), text.get(f)) for f in fields}


# Confidence floor below which the SBERT text prediction is considered "weak"
# enough that the SigLIP visual side may override it as a tiebreaker.
_G1_TEXT_WEAK_THRESHOLD = 0.42


def resolve_g1(keyword: dict | None, text: dict | None, visual: dict | None) -> dict:
    """Resolve the G1 topology with TEXT as the authority and VISION as a
    tiebreaker — the opposite of merge_field_predictions' confidence race.

    Precedence (architecture/tilt is a text-level fact, rarely legible in a
    single static drawing — see classify_g1_keyword / G1_VISUAL_PROMPTS):
      1. A keyword giveaway phrase ("lift plus cruise", "tiltrotor", …) wins
         outright (high precision), never flagged.
      2. Otherwise SBERT text leads. Vision only OVERRIDES text when the text
         side is weak (confidence < _G1_TEXT_WEAK_THRESHOLD) AND vision is
         clearly more confident; agreement is marked source="ensemble".
      3. With no text and no visual, returns an empty prediction.
    The resolved guess is always kept, but _margin_flag() caps its confidence
    (so the wizard prompts for review) when it's a near-tie / low-confidence —
    we guess but flag, never silently emit a confident wrong topology."""
    if keyword and keyword.get("value") is not None:
        return keyword

    t = text   if text   and text.get("value")   is not None else None
    v = visual if visual and visual.get("value") is not None else None
    if t is None and v is None:
        return _empty_pred()
    if t is None:
        return _margin_flag(v) or _empty_pred()
    if v is None:
        return _margin_flag(t) or _empty_pred()

    if t["value"] == v["value"]:
        return {"value": t["value"],
                "confidence": max(t.get("confidence", 0.0), v.get("confidence", 0.0)),
                "source": "ensemble",
                "margin": max(t.get("margin", 1.0), v.get("margin", 1.0))}

    # Disagreement: text leads unless it's weak and vision is clearly stronger.
    t_conf, v_conf = t.get("confidence", 0.0) or 0.0, v.get("confidence", 0.0) or 0.0
    if t_conf < _G1_TEXT_WEAK_THRESHOLD and v_conf > t_conf:
        return _margin_flag(v) or _empty_pred()
    return _margin_flag(t) or _empty_pred()


# ─── Citation/Google-Patents text enrichment (Part A — opt-in, network) ────
# When the local pass (keyword + SBERT text + vision) still leaves G1 either
# flagged_ambiguous or below the configured confidence_routing.G1 threshold,
# the citing/cited patents in the same family very often restate the
# architecture explicitly (same inventor/assignee describing the same
# mechanism in a different filing) — a small fetch of cited-patent title+
# abstract can supply exactly the tiebreak signal the citing patent's own
# text lacked. OFF by default (enrich_citations=False in process_patent);
# only invoked per-patent, and only when the local prediction is still weak,
# so a normal run with the flag off makes zero network calls.

# Cap on total Google Patents fetches per ambiguous patent — keeps a single
# stubborn patent from hammering the API even if it has many citations.
_CITATION_ENRICH_MAX_FETCHES = 2
# Seconds to sleep between citation fetches — polite rate-limiting, same
# spirit as cfg["extractor"]["delay_seconds"] but hardcoded here since this
# path runs deep inside process_patent() without direct cfg access at the
# call site that matters.
_CITATION_ENRICH_DELAY = 1.0


def g1_needs_enrichment(g1_pred: dict | None, g1_threshold: float = 0.45) -> bool:
    """True when a resolved G1 prediction is still weak enough to be worth
    spending a network fetch on: explicitly flagged ambiguous by
    resolve_g1()/_margin_flag(), OR below the confidence_routing.G1 threshold,
    OR simply missing (no value at all)."""
    if not g1_pred or g1_pred.get("value") is None:
        return True
    if g1_pred.get("flagged_ambiguous"):
        return True
    conf = g1_pred.get("confidence", 0.0) or 0.0
    return conf < g1_threshold


def enrich_g1_with_citations(
    g1_pred: dict,
    excel_row: dict,
    kinematic_text: str,
    sbert_model,
    cache_dir: "Path | str",
    max_fetches: int = _CITATION_ENRICH_MAX_FETCHES,
    delay: float = _CITATION_ENRICH_DELAY,
) -> dict:
    """
    Re-resolve an ambiguous G1 prediction using a small amount of extra text
    fetched from the patent's closest cited patents (backward_cites first,
    then forward_cites, since a citing patent describing prior art it builds
    on is more likely to restate the same architecture than a later patent
    that merely cites this one in passing).

    Fetches at most `max_fetches` cited patents (network, via
    extractor.fetch_cited_patent_text — disk-cached, never raises) and appends
    their title+abstract to `kinematic_text` before re-running the keyword
    prior and the SBERT G1 classifier. Returns the BETTER of the original vs.
    enriched prediction: enrichment only replaces g1_pred when it produces a
    non-empty, non-flagged result, or a strictly higher confidence — it never
    downgrades a confident local prediction, and any fetch failure (caught
    inside fetch_cited_patent_text) just means the enriched text equals the
    original, so the call is a safe no-op on network trouble.

    `cache_dir` should be a writable directory (e.g. cfg["paths"]["data"] /
    "citation_text_cache") — see fetch_cited_patent_text() for the on-disk
    cache format.
    """
    from src.extractor import fetch_cited_patent_text
    import time as _time

    cite_ids = list(excel_row.get("backward_cites") or []) + list(excel_row.get("forward_cites") or [])
    cite_ids = cite_ids[:max_fetches]
    if not cite_ids:
        return g1_pred

    fetched_text: list[str] = []
    for i, cid in enumerate(cite_ids):
        text = fetch_cited_patent_text(cid, cache_dir)
        if text:
            fetched_text.append(text)
        if i < len(cite_ids) - 1:
            _time.sleep(delay)

    if not fetched_text:
        return g1_pred   # every fetch failed/empty — local prediction stands unchanged

    enriched_text = kinematic_text + " " + " ".join(fetched_text)

    enriched_keyword = classify_g1_keyword(enriched_text)
    enriched_sbert    = classify_g1_text(enriched_text, sbert_model)
    enriched_pred     = enriched_keyword or enriched_sbert
    if not enriched_pred or enriched_pred.get("value") is None:
        return g1_pred

    orig_conf = (g1_pred or {}).get("confidence", 0.0) or 0.0
    enr_conf  = enriched_pred.get("confidence", 0.0) or 0.0
    orig_flagged = bool((g1_pred or {}).get("flagged_ambiguous"))

    # Tag provenance so a human reviewer (and Part C's audit) can tell this
    # value came from a network-enriched re-resolution, not the local pass.
    enriched_pred = dict(enriched_pred)
    enriched_pred["source"] = f"{enriched_pred.get('source', 'sbert')}+citation"

    if orig_flagged or enr_conf > orig_conf:
        return enriched_pred
    return g1_pred


def _siglip_underconfident(pred: dict | None) -> bool:
    """True when a SigLIP prediction set is worth a VLM second opinion — i.e.
    it's empty, or any field's confidence is below VLM_TRIGGER_CONFIDENCE."""
    if not pred:
        return True
    return any((p or {}).get("confidence", 0.0) < VLM_TRIGGER_CONFIDENCE
               for p in pred.values())


# ─── M3 propulsion-card key derivation (mirrors m3Blueprints() in the HTML) ──
# ingestAI() writes predictions to S['m3_' + card.component + '_<field>'], but
# m3Card() only ever *renders* the component keys that m3Blueprints() returns
# for the patent's actual architecture (topType/wingConf/wCount/empType). A
# card sent under the wrong key (e.g. "core_layout" for a winged aircraft)
# is written to state but never displayed — silently dropped from the human's
# view. This function must stay in lockstep with m3Blueprints() in the HTML.

def m3_card_keys(top_type: str | None, wing_conf: str | None, w_count: int, emp_type: str | None) -> list[str]:
    has_tail = bool(emp_type) and emp_type != "Tailless"
    if top_type in ("RC", "MR"):
        return ["core_layout"]
    is_winged = top_type in ("TW", "TP", "DS", "CVT", "SLC", "SRW")
    if not is_winged or w_count == 0 or wing_conf in ("BWB", "FW", "LB"):
        keys = ["hull_array"] if wing_conf in ("BWB", "FW", "LB") else ["core_layout"]
        if has_tail:
            keys.append("emp")
        return keys
    keys = [f"wing{i}" for i in range(1, max(w_count, 1) + 1)]
    keys.append("fuselage")
    if has_tail:
        keys.append("emp")
    return keys


# ─── JSON assembly ─────────────────────────────────────────────────────────────

def assemble_patent_json(
    patent_id: str,
    excel_row: dict,
    match_results: list[dict],
    description_of_drawings: str = "",
    t1_dimensions: dict | None = None,
    m1_predictions: dict | None = None,
    m2_predictions: dict | None = None,
    m3_predictions: dict | None = None,
    g1_prediction: dict | None = None,
    review_flags: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Assemble the full per-patent JSON dict (T1 metadata + T3 image entries + M1/M2/M3)."""
    patent_flags = (review_flags or {}).get(patent_id, {})

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

        # ── Inject 00b2 review flags ─────────────────────────────────────
        # review_flags is loaded once per process_patent() call.
        fig_fname = Path(img_entry.get("file", "")).name
        if fig_fname in patent_flags:
            img_entry["needs_review"] = True
            cq = patent_flags[fig_fname]
            if cq:
                img_entry["crop_quality"] = cq

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
        "M1_predictions": m1_predictions or {},
        "M2_predictions": m2_predictions or {},
        "M3_predictions": m3_predictions or {},
        "G1_prediction": g1_prediction or None,
    }


def resolve_patent_image_dir(matched_dir: Path, patent_id: str) -> Path:
    """
    Resolve the matched/ folder for a bare patent_id.

    matched/ folders are named "{patent_id}_{record_number}" (e.g.
    "US2020031488A1_69179019"), not the bare patent_id used in batches.xlsx —
    callers must resolve the folder via this function rather than assuming
    matched_dir / patent_id exists directly. Returns the bare-id path
    unresolved (non-existent) if no match is found, so callers can check
    `.exists()` themselves.
    """
    direct = matched_dir / patent_id
    if direct.exists():
        return direct
    candidates = sorted(matched_dir.glob(f"{patent_id}_*"))
    return candidates[0] if candidates else direct


def process_patent(
    patent_id: str,
    cfg: dict,
    excel_index: dict,
    matched_dir: Path,
    sbert_model=None,
    siglip_bundle: tuple | None = None,
    skip_siglip: bool = False,
    skip_files: set | None = None,
    review_flags: dict[str, dict[str, str]] | None = None,
    match_results_cache: dict[str, dict[str, dict]] | None = None,
    vlm_bundle: tuple | None = None,
    enrich_citations: bool = True,
) -> dict:
    """
    Full Stage 01 pipeline for one patent.

    Reads figure crops from ``matched_dir/patent_id/`` — the output of Stage 00b2,
    where figures are already matched to description lines and named
    ``{id}_F*.png`` (matched) or ``{id}_Fu*.png`` (unmatched/positional).

    Steps
    -----
    1. Glob ``_F*.png`` / ``_Fu*.png`` from matched_dir/patent_id/
    2. Read precomputed match results (matched_description/match_status/etc.)
       from crops_mapping.csv — the actual figure-to-description-line matching
       now runs in notebook 00b2 (it already has the filenames + descriptions.csv
       right there; no need to recompute this on every Stage 01 run)
    3. SigLIP visual verification + T2/G1/M1/M2/M3 zero-shot classification
    4. SBERT T1 dimension classification (scope, field, target) — uses the full
       description text from data/descriptions.csv directly, separate from #2
    5. Assemble and return the in-memory record dict (exported to
       source_patents.xlsx by run_stage01() via src/excel_schema.py)

    Parameters
    ----------
    matched_dir   : cfg["paths"]["matched"] — output root of Stage 00b2.
    sbert_model   : SentenceTransformer (PatentSBERTa) — required.
    siglip_bundle : (model, tokenizer, preprocess, device) from load_siglip_model() — required.
    skip_siglip   : Pass True only for debugging/fast runs (disables all SigLIP calls).
    vlm_bundle    : Optional (model, tokenizer) from vlm_extractor.load_vlm_model().
                    When supplied, the local VLM (InternVL2-8B) gives a second
                    opinion on M1/M2/M3 for any figure where SigLIP is
                    under-confident (see VLM_TRIGGER_CONFIDENCE). All inference is
                    local. Default None → SigLIP+SBERT only.
    enrich_citations : OFF by default (no network calls). When True, a patent
                    whose G1 prediction is still ambiguous after the local pass
                    (flagged_ambiguous, or below confidence_routing.G1) gets a
                    small Google-Patents fetch of its closest cited patents'
                    title+abstract as extra tiebreak text — see
                    enrich_g1_with_citations(). Disk-cached, rate-limited,
                    capped, and never raises (falls back to the local
                    prediction on any network error).

    Returns
    -------
    The assembled record dict (see assemble_patent_json() for the shape).
    """
    from src.cross_modal import (
        verify_matches,
        classify_t2_fields,
        classify_g1_hint,
        classify_m1_fields,
        classify_m2_fields,
        classify_m3_fields,
        aggregate_architecture_predictions,
        encode_image_features,
    )
    # Optional second-opinion backends. Safe to import unconditionally:
    # vlm_extractor defers torch/transformers to call time, so this import never
    # pulls a hard dependency. The functions are only *invoked* when the caller
    # passes a vlm_bundle.
    from src.vlm_extractor import vlm_extract_m1, vlm_extract_m2, vlm_extract_m3

    # review_flags / match_results_cache are normally preloaded once (for the
    # whole batch) by run_stage01() and passed in here, since the correct file
    # may live at data/<Batch_NN>/crops_mapping_<Batch_NN>.csv and re-deriving
    # that path per-patent would mean guessing the batch from inside a
    # single-patent call. Both fall back to the flat data/crops_mapping.csv
    # for callers (e.g. the single-patent diagnostic cells) that invoke
    # process_patent() directly.
    if review_flags is None:
        review_flags = _load_review_flags(Path(cfg["paths"]["data"]))
    if match_results_cache is None:
        _crops_csv = _resolve_crops_csv(cfg, matched_dir)
        match_results_cache = _load_match_results(_crops_csv.parent, filename=_crops_csv.name)

    excel_row = excel_index.get(patent_id, {})
    patent_img_dir = resolve_patent_image_dir(matched_dir, patent_id)

    if not patent_img_dir.exists():
        image_files = []
    else:
        # patent_img_dir is already patent-specific (resolved above), so the
        # filename prefix before the figure label can be anything Stage 00b2
        # produced — e.g. "{patent_id}_img9_crop_1_F8B.png",
        # "{patent_id}_D00004_crop_0_Fu.png", a differently-formatted/kind-coded
        # publication number ("US12600459PAFP_..."), or no patent_id prefix at
        # all (e.g. EP records: "imgf0001_crop_0_F1.png"). Glob on the figure
        # suffix only — label_from_filename() doesn't care about the prefix
        # either, so requiring an exact patent_id match here just silently
        # drops every figure whenever the on-disk prefix doesn't match.
        labeled   = sorted(patent_img_dir.glob("*_F[0-9]*.png"))
        unlabeled = sorted(patent_img_dir.glob("*_Fu*.png"))
        image_files = labeled + unlabeled

    if skip_files:
        image_files = [f for f in image_files if f.name not in skip_files]

    # Description text — from data/descriptions.csv (written by notebook 00b2).
    # Still needed here for the T1/G1/M1/M2/M3 SBERT *text* classification
    # below — only the per-figure matching itself (matched_description/
    # match_status) has moved to 00b2; see _load_match_results() above.
    _desc_csv = Path(cfg["paths"]["data"]) / "descriptions.csv"
    if _desc_csv.exists() and not _DESC_CACHE:
        import pandas as _pd
        _df = _pd.read_csv(_desc_csv, dtype=str).fillna("")
        _DESC_CACHE.update(
            dict(zip(_df["patent_id"], _df["description_of_drawings"]))
        )
    desc_text = _DESC_CACHE.get(patent_id, "")

    # Build match_results from the precomputed cache instead of recomputing
    # via match_images() — falls back to an "unmatched" placeholder per file
    # when a crop isn't in the cache yet (e.g. crops_mapping.csv predates the
    # 00b2 matching cell, or this file was added after that cell last ran).
    patent_matches = match_results_cache.get(patent_id, {})
    match_results: list[dict] = []
    for f in image_files:
        m = patent_matches.get(f.name, {})
        match_status = m.get("match_status", "unmatched")
        match_results.append({
            "file":                 f.name,
            "ocr_label":            label_from_filename(f.name),
            "fig_number":           m.get("fig_number"),
            "matched_description":  m.get("matched_description"),
            "match_status":         match_status,
            "match_method":         m.get("match_method"),
            "match_confidence":     m.get("match_confidence", 0.0),
            "semantic_best_score":  m.get("semantic_best_score", 0.0),
            "review_candidates":    [],
            "needs_review":         match_status != "matched",
            **({"duplicate_group": m["duplicate_group"]} if m.get("duplicate_group") else {}),
        })

    # ── SigLIP visual verification (match scores + composite confidence) ──────
    if siglip_bundle is not None and not skip_siglip:
        model, tokenizer, preprocess, device = siglip_bundle
        match_results = verify_matches(
            match_results, patent_img_dir, patent_id,
            model, tokenizer, preprocess, device,
        )

    # ── G1 text-based classification (SBERT) — moved ahead of the SigLIP
    # per-figure loop below so its confidence is available as a real
    # cross-modal signal for classify_g1_hint()'s nlp_confidence gate,
    # instead of the hardcoded 0.0 ("always run") that bypassed the gate
    # entirely. Only needs classify_text (title/abstract/first_claim/
    # innovation_objective/desc_text), already available at this point.
    # classify_text is reused unchanged further below for T1/M1/M2 text
    # classification (the structural/visual fields).
    #
    # LEVER 1: innovation_objective (Summary/Advantages of Invention, loaded by
    # extractor.load_patseer_excel) is now joined in — it states what the
    # invention actually *does*, which is exactly the architecture/objective
    # signal T1/G1 want, and was previously dropped on the floor.
    classify_text = " ".join(
        t for t in [
            excel_row.get("title"),
            excel_row.get("abstract"),
            excel_row.get("first_claim"),
            excel_row.get("innovation_objective"),   # LEVER 1
            desc_text,
        ] if t
    )

    # LEVER 2 + 3: a SECOND, signal-dense text string built ONLY from the
    # architecture/kinematic-bearing sentences of the substantive prose
    # (first_claim + innovation_objective). description_of_drawings is
    # deliberately excluded (it's per-figure visual boilerplate, not kinematic
    # prose — see the task brief). This stops SBERT's ~384-token window from
    # being diluted by background text when judging the fields where tilt /
    # lift-vs-cruise / transition is the whole question. Routed (LEVER 3) to:
    #   • classify_g1_keyword  — so the keyword priors fire on claim/objective
    #                            text, not just title+abstract;
    #   • SBERT G1 + the KINEMATIC fields (empKin, orient, propKin).
    # The structural/visual fields keep the full classify_text blob below.
    # Falls back to classify_text when no kinematic sentence is found, so a
    # patent that simply doesn't phrase things kinematically isn't left blank.
    _kin_source = " ".join(
        t for t in [
            excel_row.get("first_claim"),
            excel_row.get("innovation_objective"),
        ] if t
    )
    kinematic_text = extract_kinematic_sentences(_kin_source) or classify_text

    g1_text = classify_g1_text(kinematic_text, sbert_model)
    g1_text_confidence = g1_text["confidence"] if g1_text else 0.0

    # ── Per-figure: T2 + G1 + M1 + M2 + M3 SigLIP classification ────────────
    m1_per_fig: list[dict] = []
    m2_per_fig: list[dict] = []
    m3_per_fig: list[dict] = []
    dino_per_fig: list[dict] = []

    if siglip_bundle is not None and not skip_siglip:
        model, tokenizer, preprocess, device = siglip_bundle
        for res in match_results:
            img_path = patent_img_dir / res["file"]
            if not img_path.exists():
                res["T2_predictions"] = {}
                res["G1_hint"]        = None
                continue

            img_feat = encode_image_features(img_path, model, preprocess, device)

            res["T2_predictions"] = classify_t2_fields(
                img_path, model, tokenizer, preprocess, device, img_feat=img_feat
            )
            # G1 hint is skipped only when the SBERT text classification is
            # already confident (nlp_confidence >= confidence_threshold) —
            # real cross-modal gate now, not a permanent bypass.
            res["G1_hint"] = classify_g1_hint(
                img_path, model, tokenizer, preprocess, device,
                nlp_confidence=g1_text_confidence,
                img_feat=img_feat,
            )
            m1_pred = classify_m1_fields(img_path, model, tokenizer, preprocess, device, img_feat=img_feat)
            m2_pred = classify_m2_fields(img_path, model, tokenizer, preprocess, device, img_feat=img_feat)
            m3_pred = classify_m3_fields(img_path, model, tokenizer, preprocess, device, img_feat=img_feat)

            # ── Optional local-VLM second opinion (opt-in; see vlm_bundle) ────
            # The same local InternVL2-8B backs up M1/M2/M3, invoked only when
            # SigLIP is under-confident on this figure (any of the three sets has
            # a weak field). merge_prediction_dicts keeps the higher-confidence
            # side per field (source="vlm" never beats a more-confident SigLIP
            # value), so a None/unavailable backend is a safe no-op. All local.
            if vlm_bundle is not None and (
                _siglip_underconfident(m1_pred)
                or _siglip_underconfident(m2_pred)
                or _siglip_underconfident(m3_pred)
            ):
                vlm_m1 = vlm_extract_m1(img_path, vlm_bundle)
                vlm_m2 = vlm_extract_m2(img_path, vlm_bundle)
                vlm_m3 = vlm_extract_m3(img_path, vlm_bundle)
                m1_pred = merge_prediction_dicts(m1_pred, vlm_m1, ["fusShape", "fusKin", "gearArch", "latSym"])
                m2_pred = merge_prediction_dicts(m2_pred, vlm_m2, ["wingConf", "empType", "empKin", "wCount"])
                # VLM has no spatial fields, so merge only the core axes and keep
                # SigLIP's spatial predictions (merge_prediction_dicts returns only
                # the listed keys, which would otherwise drop the spatial ones).
                m3_merged = merge_prediction_dicts(m3_pred, vlm_m3, _M3_CORE_FIELDS)
                for _sf in _M3_SPATIAL_FIELDS:
                    if _sf in m3_pred:
                        m3_merged[_sf] = m3_pred[_sf]
                m3_pred = m3_merged

            m1_per_fig.append(m1_pred)
            m2_per_fig.append(m2_pred)
            m3_per_fig.append(m3_pred)
            # dinoUnderstanding is per-ARCHITECTURE, not per-image — collected
            # here per figure and rolled up below (same aggregation pattern as
            # m1/m2/m3) into a single value alongside the rest of M1.
            dino_per_fig.append(res["T2_predictions"])

    # ── Aggregate per-figure SigLIP predictions → patent-level (visual) ───────
    m1_visual = aggregate_architecture_predictions(
        m1_per_fig, ["fusShape", "fusKin", "gearArch", "latSym"]
    ) if m1_per_fig else {}

    m2_visual = aggregate_architecture_predictions(
        m2_per_fig, ["wingConf", "empType", "empKin", "wCount"]
    ) if m2_per_fig else {}

    m3_visual = aggregate_architecture_predictions(
        m3_per_fig, _M3_CORE_FIELDS + _M3_SPATIAL_FIELDS
    ) if m3_per_fig else {}

    # dinoUnderstanding: per-architecture, not per-image — same highest-
    # confidence aggregation as m1/m2/m3, then folded into m1_predictions
    # below (no text/SBERT counterpart, so it skips merge_prediction_dicts).
    dino_visual = aggregate_architecture_predictions(
        dino_per_fig, ["dinoUnderstanding"]
    ) if dino_per_fig else {}

    g1_visual: dict | None = None
    for res in match_results:
        h = res.get("G1_hint")
        if h and h.get("value"):
            if g1_visual is None or h["confidence"] > g1_visual["confidence"]:
                g1_visual = h

    # ── T1 dimension classification (SBERT) ───────────────────────────────────
    # Title + abstract + first claim are most information-dense for SBERT
    # (full description is excluded: SBERT truncates ~384 tokens and the bulk
    # of a long description is generic background, not the invention itself).
    # classify_text was already built above (before the SigLIP loop) for the
    # G1 text classification that feeds classify_g1_hint()'s nlp_confidence
    # gate — reused here unchanged.
    t1_dimensions = classify_t1_dimensions(classify_text, sbert_model)

    # ── M1/M2/M3 text-based classification (SBERT) + merge with visual ────────
    # Patent text often states the architecture explicitly even when a figure
    # is hard to classify visually (or has no usable description line at all).
    # Merge picks whichever modality is more confident per field, field-by-field.
    # g1_text was already computed above (before the SigLIP loop) — reused here.
    #
    # LEVER 3 — per-field text routing. The STRUCTURAL/VISUAL fields (all of M1,
    # plus M2 wingConf/empType/wCount and M3 chord/bmech/rmech) keep the full
    # classify_text blob: they describe drawn geometry that the surrounding
    # prose helps disambiguate. The KINEMATIC fields (M2 empKin, M3 orient,
    # M3 propKin) are RE-classified against the signal-dense kinematic_text so
    # SBERT isn't reading tilt/transition language through a wall of boilerplate.
    # _sbert_best is the same per-field zero-shot helper classify_m*_text uses
    # internally, so these overrides are drop-in. (kinematic_text falls back to
    # classify_text when no kinematic sentence exists, so this never blanks a
    # field — see where kinematic_text is built above.)
    m1_text = classify_m1_text(classify_text, sbert_model)
    m2_text = classify_m2_text(classify_text, sbert_model)
    m3_text = classify_m3_text(classify_text, sbert_model)

    m2_text["empKin"]  = _sbert_best(kinematic_text, _M2_EMP_KIN_DEFS,  sbert_model)
    m3_text["orient"]  = _sbert_best(kinematic_text, _M3_ORIENT_DEFS,   sbert_model)
    m3_text["propKin"] = _sbert_best(kinematic_text, _M3_PROPKIN_DEFS,  sbert_model)

    # G1 topology: text-primary, vision-tiebreaker, with a high-precision
    # keyword prior on top (architecture/tilt is a text fact, not legible in a
    # static drawing). See resolve_g1() / classify_g1_keyword().
    # LEVER 2: the keyword prior now scans kinematic_text — the mined claim +
    # innovation_objective sentences — so a giveaway phrase buried in the claim
    # (e.g. "lift plus cruise") fires even when it never appears in title/abstract.
    g1_keyword     = classify_g1_keyword(kinematic_text)
    g1_prediction  = resolve_g1(g1_keyword, g1_text, g1_visual)

    # ── Part A: opt-in citation/Google-Patents enrichment ─────────────────
    # OFF unless the caller passes enrich_citations=True. Only spends a
    # network fetch when the local pass left G1 genuinely weak — see
    # g1_needs_enrichment() / enrich_g1_with_citations(). Any network failure
    # is swallowed inside fetch_cited_patent_text(), so this can never crash
    # the batch run; worst case it's a silent no-op for that patent.
    if enrich_citations and g1_needs_enrichment(
        g1_prediction, cfg.get("confidence_routing", {}).get("G1", 0.45)
    ):
        _cite_cache_dir = Path(cfg["paths"]["data"]) / "citation_text_cache"
        g1_prediction = enrich_g1_with_citations(
            g1_prediction, excel_row, kinematic_text, sbert_model, _cite_cache_dir,
        )

    m1_predictions = merge_prediction_dicts(m1_visual, m1_text, ["fusShape", "fusKin", "gearArch", "latSym"])
    # No text/SBERT counterpart for dinoUnderstanding (it's purely a visual
    # legibility judgment) — fold the aggregated visual guess straight in.
    m1_predictions["dinoUnderstanding"] = dino_visual.get(
        "dinoUnderstanding", {"value": None, "confidence": 0.0, "source": None}
    )
    m2_predictions = merge_prediction_dicts(m2_visual, m2_text, ["wingConf", "empType", "empKin", "wCount"])
    m3_predictions = merge_prediction_dicts(m3_visual, m3_text, _M3_CORE_FIELDS + _M3_SPATIAL_FIELDS)

    # Guess-but-flag the KINEMATIC fields (the tilt/motion question, like G1, is
    # not legible in a static drawing): cap confidence on a near-tie/low-conf
    # prediction so the wizard prompts the human to verify. The genuinely VISUAL
    # fields (fusShape, perspective, wingConf, …) are left untouched — vision is
    # the right authority for a drawn geometric fact. The SPATIAL mounting fields
    # (zone/zoneChord/zoneSpan/boom*) are inherently hard to read off a single
    # drawing, so they're flagged for review too.
    for _f in ("empKin",):
        if _f in m2_predictions:
            m2_predictions[_f] = _margin_flag(m2_predictions[_f])
    for _f in ["orient", "propKin"] + _M3_SPATIAL_FIELDS:
        if _f in m3_predictions:
            m3_predictions[_f] = _margin_flag(m3_predictions[_f])

    return assemble_patent_json(
        patent_id, excel_row, match_results, desc_text,
        t1_dimensions, m1_predictions, m2_predictions, m3_predictions,
        g1_prediction, review_flags,
    )


# ─── Batch Stage 01 runner ────────────────────────────────────────────────────

def run_stage01(
    cfg: dict,
    sbert_model=None,
    siglip_bundle: "tuple | None" = None,
    skip_siglip: bool = False,
    limit: "int | None" = None,
    patent_ids: list[str] | None = None,
    matched_dir: "Path | None" = None,
    enrich_citations: bool = True,
) -> "pd.DataFrame":
    """
    Batch Stage 01 runner. Processes all patent folders in matched/ (Stage 00b2 output)
    and writes data/matched/<batch_label>/source_patents_<batch_label>.xlsx —
    no per-patent JSON/HTML files are written.

    Parameters
    ----------
    limit : If set, process only the first N patents (for testing).
    enrich_citations : OFF by default. Passed through to process_patent() —
        see its docstring. When True, ambiguous-G1 patents get a small,
        disk-cached, rate-limited Google-Patents fetch of cited-patent text.

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
    from src.excel_schema import build_patent_rows, export_source_excel

    # Stage 00b2 now writes crops under matched/<Batch_NN>/ rather than flat matched/ —
    # pass matched_dir explicitly (e.g. cfg["paths"]["matched"] / "Batch_00") so this
    # stays in sync with whichever batch you're reviewing. Defaults to the flat root
    # for backward compatibility with older runs that didn't nest by batch.
    matched_dir = Path(matched_dir) if matched_dir is not None else Path(cfg["paths"]["matched"])
    excel_idx   = load_patseer_excel(cfg["paths"]["patseer_excel"])

    # Load review flags + match results ONCE for the whole batch (not per-patent —
    # process_patent() used to reload+reparse this CSV, and recompute matching
    # from scratch, on every single call). _resolve_crops_csv() picks the
    # per-batch nested copy when it's on disk, else falls back to the flat
    # data/crops_mapping.csv — see its docstring.
    _crops_csv   = _resolve_crops_csv(cfg, matched_dir)
    review_flags = _load_review_flags(_crops_csv.parent, filename=_crops_csv.name)
    match_results_cache = _load_match_results(_crops_csv.parent, filename=_crops_csv.name)

    # matched/ folders are named "{patent_id}_{record_number}" — strip the
    # record-number suffix to recover the bare patent_id used everywhere else
    # (excel_index keys, batches.xlsx, data/descriptions.csv).
    if patent_ids is not None:
        pids = list(patent_ids)
    else:
        pids = sorted({d.name.rsplit("_", 1)[0] for d in matched_dir.iterdir() if d.is_dir()})
    if limit:
        pids = pids[:limit]

    rows = []
    all_excel_rows: list[dict] = []
    for pid in tqdm(pids, desc="Stage 01"):
        try:
            data = process_patent(
                pid, cfg, excel_idx, matched_dir,
                sbert_model          = sbert_model,
                siglip_bundle        = siglip_bundle,
                skip_siglip          = skip_siglip,
                enrich_citations     = enrich_citations,
                review_flags         = review_flags,
                match_results_cache  = match_results_cache,
            )
            patent_img_dir = resolve_patent_image_dir(matched_dir, pid)
            all_excel_rows.extend(build_patent_rows(pid, data, patent_img_dir, cfg=cfg))

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

    # One ml_predict_labels_<batch_label>.xlsx per batch, living next to that
    # batch's crops_mapping_<batch_label>.csv under data/matched/<batch_label>/
    # — same per-batch convention, so re-running another batch never clobbers
    # a previous batch's output (unlike the old single root-level file).
    batch_label   = matched_dir.name
    data_matched  = Path(cfg["paths"].get("data_matched", cfg["paths"]["data"]))
    source_excel_path = data_matched / batch_label / f"ml_predict_labels_{batch_label}.xlsx"

    if all_excel_rows:
        export_source_excel(all_excel_rows, source_excel_path)

    df = pd.DataFrame(rows)
    print(f"\n{'='*55}")
    print(f"  Stage 01 complete: {len(df)} patents")
    print(f"  ml_predict_labels_{batch_label}.xlsx: {len(all_excel_rows)} rows -> {source_excel_path}")
    if "match_score" in df.columns and df["match_score"].notna().any():
        print(f"  Avg match score  : {df['match_score'].mean():.1%}")
        hr = df.get("human_required", pd.Series(dtype=int))
        rr = df.get("review_required", pd.Series(dtype=bool))
        print(f"  Human-required   : {hr.sum() if not hr.empty else 0} crops")
        print(f"  Needs review     : {rr.sum() if not rr.empty else 0} patents")
    print(f"{'='*55}")
    return df


def run_stage01_parallel(
    cfg: dict,
    matched_dir: Path,
    skip_siglip: bool = False,
    limit: "int | None" = None,
    patent_ids: list[str] | None = None,
    enrich_citations: bool = True,
    gpu_ids: list[str] | None = None,
    skip_files: set | None = None,
) -> "pd.DataFrame":
    """
    Same end result as run_stage01() (writes one ml_predict_labels_<batch>.xlsx
    and returns the same per-patent summary DataFrame), but splits the patent
    list evenly across one subprocess PER GPU in `gpu_ids` — same pattern as
    doclayout_matcher.process_patents_parallel()/gpu_worker.py for Stage 00b2.

    Each worker is a fresh process pinned to one physical GPU via
    CUDA_VISIBLE_DEVICES, loading its own SentenceTransformer + SigLIP
    instance — there is no shared model/GPU state between workers, so this
    is safe regardless of how many patents are in the batch (chunk sizes are
    computed by ceiling division, so it works for any batch size, including
    ones smaller than the number of GPUs).

    `sbert_model`/`siglip_bundle` are NOT accepted here (unlike run_stage01)
    because each worker must load its own instance on its own pinned device —
    a model object loaded in the launching notebook's process can't be hidden
    in another GPU's subprocess.

    gpu_ids: explicit physical GPU indices, e.g. ["0", "1"]. If None, defaults
    to one worker per visible GPU (or a single worker on GPU 0 if only one is
    visible).
    """
    import json, os, subprocess, sys, tempfile, threading, shutil
    import pandas as pd
    from pathlib import Path as _Path

    matched_dir = Path(matched_dir)

    if patent_ids is not None:
        pids = list(patent_ids)
    else:
        pids = sorted({d.name.rsplit("_", 1)[0] for d in matched_dir.iterdir() if d.is_dir()})
    if limit:
        pids = pids[:limit]

    if gpu_ids is None:
        import torch
        n_gpu = torch.cuda.device_count()
        gpu_ids = [str(i) for i in range(n_gpu)] if n_gpu >= 1 else ["0"]

    n_workers = len(gpu_ids)
    chunk = max(1, -(-len(pids) // n_workers))  # ceil division
    splits = [pids[i:i + chunk] for i in range(0, len(pids), chunk)] or [[]]
    while len(splits) < n_workers:
        splits.append([])

    worker_script = str(_Path(__file__).parent / "review_gpu_worker.py")
    python_exe    = sys.executable
    repo_root     = _Path(__file__).parent.parent

    tmp_dir = _Path(tempfile.mkdtemp(prefix="review_parallel_"))
    procs, result_paths = [], []

    for i in range(n_workers):
        if not splits[i]:
            result_paths.append(None)
            continue
        args_path   = tmp_dir / f"args_{i}.json"
        result_path = tmp_dir / f"result_{i}.json"
        result_paths.append(result_path)

        args_path.write_text(json.dumps({
            "patent_ids":      splits[i],
            "matched_dir":     str(matched_dir),
            "skip_siglip":     skip_siglip,
            "enrich_citations": enrich_citations,
            "visual_weight":   VISUAL_WEIGHT,
            "text_weight":     TEXT_WEIGHT,
            "skip_files":      sorted(skip_files) if skip_files else [],
        }))

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids[i]

        p = subprocess.Popen(
            [python_exe, worker_script, str(args_path), str(result_path)],
            cwd=str(repo_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        procs.append(p)
        print(f"[GPU {gpu_ids[i]}] worker started (PID {p.pid}) — {len(splits[i])} patent(s)")

    def _stream(proc, label):
        for line in proc.stdout:
            print(f"[GPU {label}] {line}", end="", flush=True)

    threads = [threading.Thread(target=_stream, args=(procs[j], gpu_ids[j]), daemon=True)
               for j in range(len(procs))]
    for t in threads: t.start()
    try:
        for p in procs:   p.wait()
        for t in threads: t.join()
    except BaseException:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        raise

    rows: list[dict] = []
    all_excel_rows: list[dict] = []
    for rp in result_paths:
        if rp is None:
            continue
        if not rp.exists() or rp.stat().st_size == 0:
            print(f"⚠  Result file missing/empty: {rp} — that worker crashed "
                  f"before writing results (its patents are NOT in this run's "
                  f"output — check the [GPU ...] traceback above, e.g. a CUDA "
                  f"OOM, and re-run once fixed).")
            continue
        try:
            data = json.loads(rp.read_text())
        except json.JSONDecodeError:
            print(f"⚠  Result file corrupt: {rp} — that worker crashed mid-write; skipping it.")
            continue
        rows.extend(data["summary_rows"])
        all_excel_rows.extend(data["excel_rows"])

    shutil.rmtree(tmp_dir, ignore_errors=True)

    from src.excel_schema import export_source_excel
    batch_label   = matched_dir.name
    data_matched  = Path(cfg["paths"].get("data_matched", cfg["paths"]["data"]))
    source_excel_path = data_matched / batch_label / f"ml_predict_labels_{batch_label}.xlsx"

    if all_excel_rows:
        export_source_excel(all_excel_rows, source_excel_path)

    df = pd.DataFrame(rows)
    print(f"\n{'='*55}")
    print(f"  Stage 01 (parallel, {n_workers} GPU worker(s)) complete: {len(df)} patents")
    print(f"  ml_predict_labels_{batch_label}.xlsx: {len(all_excel_rows)} rows -> {source_excel_path}")
    if "match_score" in df.columns and df["match_score"].notna().any():
        print(f"  Avg match score  : {df['match_score'].mean():.1%}")
        hr = df.get("human_required", pd.Series(dtype=int))
        rr = df.get("review_required", pd.Series(dtype=bool))
        print(f"  Human-required   : {hr.sum() if not hr.empty else 0} crops")
        print(f"  Needs review     : {rr.sum() if not rr.empty else 0} patents")
    print(f"{'='*55}")
    return df


# ─── Family deduplication ────────────────────────────────────────────────────
# Standalone helper — NOT called automatically anywhere in this module. Batch-
# processing code invokes it explicitly once a Simple Family ID grouping exists.

def select_family_primary(family_records: list[dict]) -> str | None:
    """
    Given a list of patent records sharing a Simple Family ID, return the patent_id
    of the primary (original) record using a three-tier tiebreaker:
      1. Earliest priority_date (ISO string YYYY-MM-DD, nulls last)
      2. Granted status: publication numbers ending in B1, B2, B, or EP Bx beat A-series
      3. Lowest application_number lexicographically
    Returns None if family_records is empty.
    """
    import re

    def _is_granted(patent_id: str) -> bool:
        return bool(re.search(r'B\d?$', patent_id, re.IGNORECASE))

    def _sort_key(r: dict):
        pid  = r.get("patent_id", "")
        date = r.get("priority_date") or "9999-99-99"
        granted = 0 if _is_granted(pid) else 1   # granted sorts before pending
        app_num = r.get("application_number") or pid
        return (date, granted, app_num)

    if not family_records:
        return None
    return min(family_records, key=_sort_key).get("patent_id")
