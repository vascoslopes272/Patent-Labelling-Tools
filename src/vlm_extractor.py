"""
vlm_extractor.py — Second-opinion extraction layer for the M1/M2/M3 architecture
fields, used to back up the SigLIP zero-shot path in src/cross_modal.py.

ALL inference is LOCAL. M1 (fuselage / gear), M2 (wing / empennage) and M3
(propulsion) are extracted by the SAME local vision-language model:
InternVL2-8B (4-bit). InternVL2 is preferred over Qwen2.5-VL because it runs on
transformers 4.x and so avoids the PyTorch 2.5.1 dependency conflict that
currently blocks the quantised Qwen2.5-VL build. There is NO external API call
and NO network dependency anywhere in this module.

Design contract
---------------
Every function returns a dict in the SAME shape the matching
classify_m*_fields() function in cross_modal.py returns —
``{field: {"value": ..., "confidence": float, "source": "vlm"}}`` — so
reviewer.merge_field_predictions() / merge_prediction_dicts() consume the
output with no changes. Confidence is 0.75 for a clean structured response,
0.55 for a partial one (some fields missing), and 0.0 for a field that is
absent or fails to parse — a 0.0 lets the SigLIP/SBERT side win the merge.

Value vocabularies
------------------
The prompts request the canonical taxonomy values used by the pipeline. For
M1/M2 and for M3's chord/bmech/rmech these match ``classify_m*_fields()`` exactly
(also the option strings the HTML wizard renders). M3 additionally uses an
``orient`` vocabulary [Horizontal, Vertical, Mixed] and a new ``propKin``
field [Fixed, Tilt, Vectored, Cyclic] as specified for this extractor. The
_NORMALIZE maps below also fold common synonyms into the canonical value, so a
near-miss from the model still resolves rather than being dropped.

All heavy imports (torch, transformers) are done lazily inside the functions so
this module is always importable even in an env without them; a missing backend
degrades to None / 0.0-confidence rather than raising.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Local VLM identifier (the only model this module uses)
_VLM_MODEL_ID = "OpenGVLab/InternVL2-8B"

# Per-response confidence tiers (see module docstring)
_CONF_CLEAN   = 0.75   # every requested field present and valid
_CONF_PARTIAL = 0.55   # JSON parsed, but at least one field missing/invalid
_CONF_FAIL    = 0.0    # field absent or whole response unparseable

# Lazy module-level cache. _VLM_LOAD_FAILED guards against re-attempting a load
# that already failed (e.g. model not in the env) on every single figure.
_VLM_CACHE = None
_VLM_LOAD_FAILED = False


# ─── Canonical value vocabularies (must match classify_m*_fields in cross_modal) ──
_M1_FIELDS = ["fusShape", "fusKin", "gearArch", "latSym"]
_M2_FIELDS = ["wingConf", "empType", "empKin", "wCount"]
_M3_FIELDS = ["chord", "orient", "bmech", "rmech", "propKin"]

# Normalisation maps: canonical values map to themselves; the task brief's
# alternative vocabulary is folded into the canonical value. Keys are matched
# case-insensitively (see _normalize). Anything unmapped → None (treated missing).
_NORMALIZE = {
    # ── M1 ──
    "fusShape": {
        "circular": "Circular", "tubular": "Circular", "cylindrical": "Circular",
        "oval": "Oval", "elliptical": "Oval", "ellipse": "Oval",
        "rectangular": "Rectangular", "box": "Rectangular", "boxy": "Rectangular",
        "blended": "Blended", "podboom": "Blended", "pod-boom": "Blended",
        "liftingbody": "Blended", "bwb": "Blended",
    },
    "fusKin": {
        "fixed": "Fixed", "rigid": "Fixed", "conventional": "Fixed",
        "variable": "Variable", "articulated": "Variable", "tilting": "Variable",
    },
    "gearArch": {
        "skids": "Skids", "skid": "Skids", "runners": "Skids",
        "fixedwheel": "FixedWheel", "tricycle": "FixedWheel",
        "taildragger": "FixedWheel", "quadricycle": "FixedWheel",
        "fixedwheels": "FixedWheel", "wheeled": "FixedWheel",
        "retrwheel": "RetrWheel", "retractable": "RetrWheel",
        "retractablewheel": "RetrWheel",
        "padshull": "PadsHull", "pads": "PadsHull", "float": "PadsHull",
        "floats": "PadsHull", "pontoon": "PadsHull", "hull": "PadsHull",
    },
    # ── M2 ──
    "wingConf": {
        "w": "W", "monowing": "W", "biwing": "W", "biplane": "W",
        "tandem": "W", "standard": "W", "wing": "W",
        "bwb": "BWB", "blendedwingbody": "BWB",
        "fw": "FW", "flyingwing": "FW",
        "lb": "LB", "liftingbody": "LB",
    },
    "empType": {
        "tailless": "Tailless", "notail": "Tailless", "none": "Tailless",
        "conventional": "Conventional",
        "cruciform": "Cruciform",
        "t-tail": "T-Tail", "ttail": "T-Tail",
        "v-tail": "V-Tail", "vtail": "V-Tail",
        "inv_v-tail": "Inv_V-Tail", "invvtail": "Inv_V-Tail",
        "inverted-v": "Inv_V-Tail",
        "h-tail": "H-Tail", "htail": "H-Tail", "tailboom": "H-Tail",
        "twin-boom": "H-Tail", "twinboom": "H-Tail",
        "fins": "Fins", "fin": "Fins",
    },
    "empKin": {
        "fixed": "Fixed",
        "tilt": "Tilt", "tilting": "Tilt",
        "stabilator": "Stabilator", "allmoving": "Stabilator",
    },
    # ── M3 ──
    "chord": {
        "front": "Front", "leading": "Front", "tractor": "Front", "puller": "Front",
        "back": "Back", "rear": "Back", "trailing": "Back", "pusher": "Back",
    },
    "orient": {
        "horizontal": "Horizontal", "fixed_horizontal": "Horizontal",
        "vertical": "Vertical", "fixed_vertical": "Vertical",
        "mixed": "Mixed", "tilting": "Mixed", "tilting_mechanism": "Mixed",
        "tilt": "Mixed", "vectored": "Mixed",
    },
    "bmech": {
        "open": "Open", "openrotor": "Open", "exposed": "Open", "free": "Open",
        "ducted": "Ducted", "shrouded": "Ducted", "fan": "Ducted",
        "folded": "Folded", "folding": "Folded", "stowable": "Folded",
    },
    "rmech": {
        "exposed": "Exposed", "nonretractable": "Exposed", "fixed": "Exposed",
        "retractable": "Retractable", "stowing": "Retractable",
    },
    "propKin": {
        "fixed": "Fixed", "rigid": "Fixed",
        "tilt": "Tilt", "tilting": "Tilt",
        "vectored": "Vectored", "vector": "Vectored", "thrustvectored": "Vectored",
        "cyclic": "Cyclic", "swashplate": "Cyclic",
    },
}


def _normalize(field: str, raw) -> "object | None":
    """Fold a raw model value into the canonical taxonomy value for `field`.

    latSym is a bool; wCount resolves to a "1".."4" string id (clamped). Every
    other field uses the _NORMALIZE lookup. Returns None when the value can't be
    mapped, so the caller can mark it missing (confidence 0.0)."""
    if raw is None:
        return None

    if field == "latSym":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "yes", "symmetric", "1"):
            return True
        if s in ("false", "no", "asymmetric", "0"):
            return False
        return None

    if field == "wCount":
        try:
            n = int(round(float(raw)))
        except (ValueError, TypeError):
            return None
        n = max(1, min(4, n))      # canonical ids are "1".."4"; clamp 0/5+ in
        return str(n)

    table = _NORMALIZE.get(field, {})
    key = re.sub(r"[\s_]+", "", str(raw).strip().lower())
    # try the de-spaced key first, then the raw lowercased key (table has both forms)
    return table.get(key) or table.get(str(raw).strip().lower())


def _finalize_fields(parsed: "dict | None", fields: list[str]) -> dict:
    """Build the ``{field: {value, confidence, source:"vlm"}}`` result from a
    parsed JSON dict, applying the 0.75 / 0.55 / 0.0 confidence tiers."""
    if not isinstance(parsed, dict):
        # whole response unparseable → every field 0.0 so SigLIP/SBERT wins
        return {f: {"value": None, "confidence": _CONF_FAIL, "source": "vlm"} for f in fields}

    normed = {f: _normalize(f, parsed.get(f)) for f in fields}
    n_valid = sum(1 for f in fields if normed[f] is not None)
    if n_valid == len(fields):
        resp_conf = _CONF_CLEAN
    elif n_valid > 0:
        resp_conf = _CONF_PARTIAL
    else:
        resp_conf = _CONF_FAIL

    return {
        f: {
            "value":      normed[f],
            "confidence": resp_conf if normed[f] is not None else _CONF_FAIL,
            "source":     "vlm",
        }
        for f in fields
    }


def _parse_json_blob(raw_text: str) -> "dict | None":
    """Strip markdown fences and parse the first JSON object out of model text."""
    if not raw_text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # fall back to the first {...} span if the model added prose around it
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


# ─── Local InternVL2-8B loading ──────────────────────────────────────────────

def load_vlm_model(cache_dir: "Path | None" = None) -> "tuple | None":
    """Load InternVL2-8B in 4-bit and cache it module-level.

    Returns (model, tokenizer), or None if the model / its deps are unavailable
    in this env — in which case callers fall back to the SigLIP+SBERT path. The
    failure is remembered so a missing model isn't re-attempted on every figure.
    """
    global _VLM_CACHE, _VLM_LOAD_FAILED
    if _VLM_CACHE is not None:
        return _VLM_CACHE
    if _VLM_LOAD_FAILED:
        return None

    try:
        import torch
        from transformers import AutoModel, AutoTokenizer, BitsAndBytesConfig

        quant_cfg = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        kwargs = dict(
            quantization_config=quant_cfg,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )
        if cache_dir is not None:
            kwargs["cache_dir"] = str(cache_dir)

        model = AutoModel.from_pretrained(_VLM_MODEL_ID, **kwargs).eval()
        tok_kwargs = {"trust_remote_code": True, "use_fast": False}
        if cache_dir is not None:
            tok_kwargs["cache_dir"] = str(cache_dir)
        tokenizer = AutoTokenizer.from_pretrained(_VLM_MODEL_ID, **tok_kwargs)

        _VLM_CACHE = (model, tokenizer)
        logger.info("Loaded VLM %s (4-bit) for M1/M2 extraction", _VLM_MODEL_ID)
        return _VLM_CACHE
    except Exception as exc:  # ImportError, OSError (no weights), CUDA OOM, …
        _VLM_LOAD_FAILED = True
        logger.warning(
            "VLM %s unavailable (%s) — M1/M2 will use the SigLIP+SBERT path only",
            _VLM_MODEL_ID, exc,
        )
        return None


def _load_pixel_values(img_path: Path, input_size: int = 448):
    """InternVL2 single-tile image preprocessing → a [1,3,H,W] bfloat16 tensor
    on the model's device. Returns None if the image can't be read."""
    try:
        import torch
        import torchvision.transforms as T
        from torchvision.transforms.functional import InterpolationMode
        from PIL import Image

        mean = (0.485, 0.456, 0.406)
        std = (0.229, 0.224, 0.225)
        transform = T.Compose([
            T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
            T.ToTensor(),
            T.Normalize(mean, std),
        ])
        image = Image.open(img_path).convert("RGB")
        pixel_values = transform(image).unsqueeze(0).to(torch.bfloat16)
        if torch.cuda.is_available():
            pixel_values = pixel_values.cuda()
        return pixel_values
    except Exception as exc:
        logger.warning("Failed to preprocess image %s for VLM: %s", img_path, exc)
        return None


def _vlm_chat(vlm_bundle, img_path: Path, question: str) -> "dict | None":
    """Run one InternVL2 chat turn on a single figure and parse its JSON reply."""
    if not vlm_bundle:
        return None
    model, tokenizer = vlm_bundle
    pixel_values = _load_pixel_values(img_path)
    if pixel_values is None:
        return None
    try:
        gen_cfg = dict(max_new_tokens=512, do_sample=False)
        response = model.chat(tokenizer, pixel_values, question, gen_cfg)
        return _parse_json_blob(response)
    except Exception as exc:
        logger.warning("VLM chat failed on %s: %s", img_path, exc)
        return None


_M1_QUESTION = (
    "<image>\nYou are an eVTOL patent figure analyst. Look at this single patent "
    "drawing and classify the airframe. Reply with ONLY a JSON object, no prose:\n"
    "{\n"
    '  "fusShape": one of ["Circular","Oval","Rectangular","Blended"],\n'
    '  "fusKin":   one of ["Fixed","Variable"],\n'
    '  "gearArch": one of ["Skids","FixedWheel","RetrWheel","PadsHull"],\n'
    '  "latSym":   true or false\n'
    "}\n"
    "fusShape = fuselage cross-section; fusKin = whether the fuselage tilts; "
    "gearArch = landing gear type; latSym = left-right mirror symmetry. "
    "If a field is not determinable from this figure, omit that key."
)

_M2_QUESTION = (
    "<image>\nYou are an eVTOL patent figure analyst. Look at this single patent "
    "drawing and classify the lifting surfaces. Reply with ONLY a JSON object, no prose:\n"
    "{\n"
    '  "wingConf": one of ["W","BWB","FW","LB"],\n'
    '  "empType":  one of ["Tailless","Conventional","Cruciform","T-Tail","V-Tail","Inv_V-Tail","H-Tail","Fins"],\n'
    '  "empKin":   one of ["Fixed","Tilt","Stabilator"],\n'
    '  "wCount":   integer number of main wing panels, 1 to 4\n'
    "}\n"
    "wingConf = wing configuration (W=standard panels, BWB=blended wing body, "
    "FW=flying wing, LB=lifting body); empType = empennage/tail type; "
    "empKin = whether the tail tilts; wCount = count of distinct main wings. "
    "If a field is not determinable from this figure, omit that key."
)


def vlm_extract_m1(img_path: Path, vlm_bundle) -> dict:
    """Extract M1 fields (fusShape, fusKin, gearArch, latSym) from one figure via
    the local VLM. Returns a dict matching classify_m1_fields()'s schema."""
    parsed = _vlm_chat(vlm_bundle, img_path, _M1_QUESTION)
    return _finalize_fields(parsed, _M1_FIELDS)


def vlm_extract_m2(img_path: Path, vlm_bundle) -> dict:
    """Extract M2 fields (wingConf, empType, empKin, wCount) from one figure via
    the local VLM. Returns a dict matching classify_m2_fields()'s schema."""
    parsed = _vlm_chat(vlm_bundle, img_path, _M2_QUESTION)
    return _finalize_fields(parsed, _M2_FIELDS)


_M3_QUESTION = (
    "<image>\nYou are an eVTOL patent figure analyst. Look at this single patent "
    "drawing and classify the propulsion system. Reply with ONLY a JSON object, no prose:\n"
    "{\n"
    '  "chord":   one of ["Front","Back"],\n'
    '  "orient":  one of ["Horizontal","Vertical","Mixed"],\n'
    '  "bmech":   one of ["Open","Ducted","Folded"],\n'
    '  "rmech":   one of ["Exposed","Retractable"],\n'
    '  "propKin": one of ["Fixed","Tilt","Vectored","Cyclic"]\n'
    "}\n"
    "chord = rotors at the front/leading edge (pulling) vs back/trailing edge (pushing); "
    "orient = rotor disc orientation (Horizontal lift, Vertical cruise, or Mixed); "
    "bmech = blade housing (Open exposed blades, Ducted/shrouded, or Folding/stowable); "
    "rmech = whether rotors are permanently Exposed or Retractable into the structure; "
    "propKin = propulsor articulation (Fixed, Tilt, thrust-Vectored, or Cyclic swashplate). "
    "If a field is not determinable from this figure, omit that key."
)


def vlm_extract_m3(img_path: Path, vlm_bundle) -> dict:
    """Extract M3 propulsion fields (chord, orient, bmech, rmech, propKin) from
    one figure via the same local VLM as M1/M2. Returns a dict in the
    {field: {value, confidence, source:"vlm"}} schema. Any failure yields
    0.0-confidence fields so the SigLIP/SBERT side wins the merge."""
    parsed = _vlm_chat(vlm_bundle, img_path, _M3_QUESTION)
    return _finalize_fields(parsed, _M3_FIELDS)
