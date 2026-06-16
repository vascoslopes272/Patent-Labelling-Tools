"""
ai_labeler.py — Calls the Anthropic Claude API with patent images + text to generate
T1/T2/G1/M1 taxonomy pre-labels for a single patent.

Output written to: labels/{patent_id}/ai_prelabel.json
"""

import base64
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import yaml

logger = logging.getLogger(__name__)

_AI_MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """\
You are an expert eVTOL patent analyst with deep knowledge of aircraft architecture taxonomy.
You will receive patent figures and text. Analyze everything together and return ONLY a single
valid JSON object conforming to the schema below. No markdown, no explanation, no preamble.

════════════ TAXONOMY RULES — MANDATORY ════════════

G1 TOPOLOGY — use ONLY these exact codes:
  TW   Tilt Wing         : the ENTIRE wing panel rotates to vector thrust
  TP   Tilt Propulsors   : propulsors tilt independently; wing is FIXED
  DS   Deflected Slipstream: fixed props + large structural flaps deflect flow
  CVT  Combined (CVT)    : fixed lift rotors + tilting propulsors, OR ambiguous dual-rotation
  SLC  Lift + Cruise     : separate fixed hover rotors AND fixed cruise propulsors (no tilt)
  SRW  Stopped Rotor Wing: rotors stop/lock in cruise and act as wings
  RC   Rotorcraft        : single-rotor, coaxial, or tandem helicopter
  MR   Multirotor        : distributed fixed rotors, drone / multicopter layout
  HB   Hoverbike         : motorcycle posture, rider interface visible
  PFV  Personal Flying Vehicle: wearable suit, jetpack, standing platform

FORBIDDEN — do NOT use: FW, LW, Lift+Cruise (write SLC), Slow Rotor Winged, Hybrid, Other

CLASSIFICATION RULE: always driven by the MOST COMPLEX propulsive/structural system present.
If multiple systems coexist, classify by the highest-complexity one.

WING 1 RULE (mandatory for all winged topologies):
  Wing 1 = the largest lifting surface by projected area/span.
  If two surfaces are equal in size, Wing 1 = the FORWARD-MOST surface.
  Never assign Wing 1 to a canard. Never assign Wing 1 to a tailplane.

REJECTION CRITERIA — set approved=false and disapprove_reason when:
  "Pure UAV"      : no passenger or AAM intent evident in text or figures
  "Out of Domain" : not an aircraft (ground vehicle, marine, static structure, etc.)
  "Unreadable"    : figures are corrupt, blank, or text is missing/illegible

CONFIDENCE THRESHOLDS:
  >= 0.85  → high confidence, AI likely correct
  0.60–0.84→ medium, human should verify
  < 0.60   → low, set needs_review: true

T1 SCOPE — use ONLY:
  "Whole Aircraft Architecture"        : patent claims or illustrates a complete aircraft layout
  "Architectural Subsystem Enabler"    : a subsystem that enables a specific architecture
  "Component-Level Generic"            : low-level component with no architecture specificity

T1 FIELD — use ONLY:
  "Aerodynamic/Structural" | "Mechanical/Kinematic" | "Propulsion/Electrical" |
  "Control/Avionics" | "Other / Unidentified"

T1 TARGET — use ONLY:
  "Layout Convergence" | "Weight/Complexity Reduction" | "Aerodynamic Efficiency" |
  "Redundancy/Safety" | "Other / Unidentified"

T2 PERSPECTIVE — use ONLY:
  "Top" | "Bottom/Down" | "Front" | "Back" | "Side" |
  "Front-Isometric" | "Rear-Isometric" | "Generic 3D"

T2 STYLE — use ONLY:
  "Line Drawing" | "Shaded Render" | "Solid/Filled Model" | "Schematic"

T2 SYMMETRY — use ONLY:
  "Symmetric View" | "Asymmetric View"

T2 PARTS — use ONLY items from this list (can be multiple):
  "Whole Vehicle Layout", "Primary Wing", "Secondary/Canard Wing",
  "Empennage/Tail", "Rotor/Propeller Blade", "Tilt Hinge/Mechanism",
  "Fuselage Cross-section", "Landing Gear/Skids",
  "Internal Components/Batteries/Wiring"

WING CONFIG — use ONLY:
  "W"   Standard Wings (discrete panels)
  "BWB" Blended Wing Body
  "FW"  Flying Wing (no distinct fuselage)
  "LB"  Lifting Body

EMP TYPE — use ONLY:
  "Tailless" | "Conventional" | "Cruciform" | "T-Tail" | "V-Tail" |
  "Inv_V-Tail" | "H-Tail" | "Fins"

FUS SHAPE — use ONLY:
  "Circular" | "Oval" | "Rectangular" | "Blended"

GEAR ARCH — use ONLY:
  "Skids" | "FixedWheel" | "RetrWheel" | "PadsHull"
════════════════════════════════════════════════════
"""

_USER_INSTRUCTION_TEMPLATE = """\
Patent text (abstract + description of drawings):
{text}

Analyze all figures above together with the patent text.
Return ONLY the following JSON object — no markdown, no extra keys, no comments:

{{
  "T1": {{
    "approved": true | false,
    "disapprove_reason": "Pure UAV" | "Out of Domain" | "Unreadable" | null,
    "scope": "Whole Aircraft Architecture" | "Architectural Subsystem Enabler" | "Component-Level Generic",
    "t1Field": "Aerodynamic/Structural" | "Mechanical/Kinematic" | "Propulsion/Electrical" | "Control/Avionics" | "Other / Unidentified",
    "t1Target": "Layout Convergence" | "Weight/Complexity Reduction" | "Aerodynamic Efficiency" | "Redundancy/Safety" | "Other / Unidentified",
    "arch_count": 1,
    "confidence": 0.0,
    "reasoning": "max 40 words"
  }},
  "G1": {{
    "topType": "TW" | "TP" | "DS" | "CVT" | "SLC" | "SRW" | "RC" | "MR" | "HB" | "PFV",
    "confidence": 0.0,
    "reasoning": "max 30 words — cite the specific visual evidence (rotor positions, wing motion, etc.)"
  }},
  "M1": {{
    "wingConf": "W" | "BWB" | "FW" | "LB" | null,
    "wCount": 1,
    "wing1_role": "Primary Lifting Surface — largest area or forward-most if equal",
    "empType": "Tailless" | "Conventional" | "Cruciform" | "T-Tail" | "V-Tail" | "Inv_V-Tail" | "H-Tail" | "Fins" | null,
    "fusShape": "Circular" | "Oval" | "Rectangular" | "Blended" | null,
    "gearArch": "Skids" | "FixedWheel" | "RetrWheel" | "PadsHull" | null,
    "latSym": true | false,
    "confidence": 0.0
  }},
  "T2": {{
    "<fig_number>": {{
      "per": "Top" | "Bottom/Down" | "Front" | "Back" | "Side" | "Front-Isometric" | "Rear-Isometric" | "Generic 3D",
      "acSty": "Line Drawing" | "Shaded Render" | "Solid/Filled Model" | "Schematic",
      "sym": "Symmetric View" | "Asymmetric View",
      "acCol": "B/W (Monochrome)" | "Grayscale" | "Full Color",
      "bgSty": "Solid Fill" | "Shaded/Gradient" | "Grid/Pattern",
      "bgCol": "White" | "Blueprint Blue" | "Dark" | "Grayscale",
      "parts": ["Whole Vehicle Layout"],
      "confidence": 0.0,
      "needs_review": false
    }}
  }},
  "overall_confidence": 0.0
}}
"""


def _load_images(patent_id: str, cfg: dict) -> list[dict]:
    """Load all PNG figures for a patent, returning b64-encoded image dicts."""
    matched_dir = Path(cfg["paths"]["matched"]) / patent_id
    images = []
    skipped = []

    png_files = sorted(matched_dir.glob("*.png"))
    if not png_files:
        logger.warning("No PNG images found for patent %s in %s", patent_id, matched_dir)
        return images

    for png_path in png_files:
        # Extract fig_number from filename: _F(\w+)\.png → fig number, _Fu(\d+) → "Fu{n}"
        fu_match = re.search(r"_Fu(\d+)\.png$", png_path.name)
        f_match = re.search(r"_F(\w+)\.png$", png_path.name)

        if fu_match:
            fig_number = f"Fu{fu_match.group(1)}"
        elif f_match:
            fig_number = f_match.group(1)
        else:
            fig_number = png_path.stem

        try:
            b64 = base64.standard_b64encode(png_path.read_bytes()).decode("utf-8")
            images.append({
                "filename": png_path.name,
                "fig_number": fig_number,
                "b64": b64,
                "media_type": "image/png",
            })
        except OSError:
            logger.warning("Failed to load image %s — skipping", png_path)
            skipped.append(png_path.name)

    if skipped:
        logger.warning("Skipped %d image(s) for patent %s: %s", len(skipped), patent_id, skipped)

    return images


def _load_text(patent_id: str, cfg: dict) -> str:
    """Read patent text file. Returns empty string with a warning if missing."""
    text_path = Path(cfg["paths"]["text"]) / f"{patent_id}.txt"
    if not text_path.exists():
        logger.warning("Text file not found for patent %s at %s — proceeding images-only", patent_id, text_path)
        return ""
    return text_path.read_text(encoding="utf-8")


def _build_prompt(images: list[dict], text: str) -> list[dict]:
    """Build the Anthropic messages list with interleaved image and caption blocks."""
    content = []

    for img in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["b64"],
            },
        })
        content.append({
            "type": "text",
            "text": f"Figure {img['fig_number']}: {img['filename']}",
        })

    instruction = _USER_INSTRUCTION_TEMPLATE.format(text=text)
    content.append({"type": "text", "text": instruction})

    return [{"role": "user", "content": content}]


def _call_claude(prompt_messages: list[dict]) -> dict:
    """Send the prompt to Claude and parse the JSON response."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=_AI_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=prompt_messages,
    )

    raw_text = response.content[0].text

    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Failed to parse Claude response as JSON. Raw response: %s", raw_text[:500])
        return {"error": "parse_failed", "raw": raw_text}


def _write_output(patent_id: str, result: dict, cfg: dict, skipped_images: list[str] | None = None) -> Path:
    """Inject metadata into result and write ai_prelabel.json."""
    output_dir = Path(cfg["paths"]["labels"]) / patent_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "ai_prelabel.json"

    metadata = {
        "patent_id": patent_id,
        "ai_model": _AI_MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if skipped_images:
        metadata["skipped_images"] = skipped_images

    output = {"metadata": metadata, **result}
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    logger.info("Wrote AI pre-label for patent %s to %s", patent_id, output_path)
    return output_path


def run_ai_labeler(patent_id: str, cfg: dict) -> Path:
    """
    Generate T1/T2/G1/M1 taxonomy pre-labels for a single patent via Claude API.

    Args:
        patent_id: Patent identifier (used to locate images, text, and output path).
        cfg: Config dict with at minimum cfg["paths"]["matched"], cfg["paths"]["text"],
             and cfg["paths"]["labels"] keys.

    Returns:
        Path to the written ai_prelabel.json file.
    """
    logger.info("Starting AI labeling for patent %s", patent_id)

    images = _load_images(patent_id, cfg)
    skipped_images = []

    # Collect names of any images that failed to load (already warned in _load_images)
    matched_dir = Path(cfg["paths"]["matched"]) / patent_id
    all_pngs = {p.name for p in matched_dir.glob("*.png")} if matched_dir.exists() else set()
    loaded_names = {img["filename"] for img in images}
    skipped_images = sorted(all_pngs - loaded_names)

    text = _load_text(patent_id, cfg)

    # If no text, confidence cap is enforced via the system prompt instruction
    prompt_messages = _build_prompt(images, text)
    result = _call_claude(prompt_messages)

    return _write_output(patent_id, result, cfg, skipped_images or None)
