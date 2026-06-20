"""
smoke_test_vlm.py — Standalone smoke test for the local VLM (InternVL2-8B)
extraction layer in src/vlm_extractor.py.

Loads the model once, runs vlm_extract_m1/m2/m3 on the first figure found
under cfg["paths"]["matched"], prints raw + parsed output for each, flags any
returned value that isn't in that field's canonical enum, and reports timing.

This script makes no changes to any pipeline file — it only imports and calls
the existing public functions.

Run with: python scripts/smoke_test_vlm.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config_loader import load_config
from src.vlm_extractor import (
    load_vlm_model,
    vlm_extract_m1,
    vlm_extract_m2,
    vlm_extract_m3,
    _load_pixel_values,
    _M1_QUESTION,
    _M2_QUESTION,
    _M3_QUESTION,
)

# Canonical enums — must match classify_m*_fields() in src/cross_modal.py /
# the _M*_FIELDS DEFS in src/reviewer.py (vlm_extractor.py is the reference).
CANONICAL_ENUMS = {
    "fusShape": {"Circular", "Oval", "Rectangular", "Blended"},
    "fusKin":   {"Fixed", "Variable"},
    "gearArch": {"Skids", "FixedWheel", "RetrWheel", "PadsHull"},
    "latSym":   {True, False},
    "wingConf": {"W", "BWB", "FW", "LB"},
    "empType":  {"Tailless", "Conventional", "Cruciform", "T-Tail", "V-Tail",
                 "Inv_V-Tail", "H-Tail", "Fins"},
    "empKin":   {"Fixed", "Tilt", "Stabilator"},
    "wCount":   {"1", "2", "3", "4"},
    "chord":    {"Front", "Back"},
    "orient":   {"Horizontal", "Vertical", "Mixed"},
    "bmech":    {"Open", "Ducted", "Folded"},
    "rmech":    {"Exposed", "Retractable"},
    "propKin":  {"Fixed", "Tilt", "Vectored", "Cyclic"},
}


def find_first_figure(matched_dir: Path) -> "Path | None":
    """First .png or .jpg under matched_dir, recursive, deterministic order."""
    if not matched_dir.exists():
        return None
    candidates = sorted(
        p for p in matched_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
    return candidates[0] if candidates else None


def check_enum(field: str, value) -> str:
    """Return 'OK', 'ENUM MISMATCH', or 'N/A (no canonical list)' for one field."""
    if field not in CANONICAL_ENUMS:
        return "N/A (no canonical list)"
    if value is None:
        return "OK (None/unset)"
    return "OK" if value in CANONICAL_ENUMS[field] else "ENUM MISMATCH"


def capture_raw_output(vlm_bundle, img_path: Path, question: str) -> str:
    """Run the model.chat() call directly (same path _vlm_chat uses internally)
    so we can show the operator the raw text before it's parsed into JSON.
    vlm_extract_m*() doesn't expose its raw response, so this duplicates the
    single chat() call rather than modifying src/vlm_extractor.py."""
    model, tokenizer = vlm_bundle
    pixel_values = _load_pixel_values(img_path)
    if pixel_values is None:
        return "<failed to preprocess image>"
    try:
        gen_cfg = dict(max_new_tokens=512, do_sample=False)
        return model.chat(tokenizer, pixel_values, question, gen_cfg)
    except Exception as exc:
        return f"<vlm chat call failed: {exc}>"


def run_and_report(label: str, question: str, extract_fn, vlm_bundle, img_path: Path) -> dict:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")

    raw_text = capture_raw_output(vlm_bundle, img_path, question)
    print("--- RAW VLM OUTPUT ---")
    print(raw_text)

    parsed = extract_fn(img_path, vlm_bundle)
    print("--- PARSED RESULT ---")
    for field, pred in parsed.items():
        status = check_enum(field, pred.get("value"))
        flag = "  <<< ENUM MISMATCH" if status == "ENUM MISMATCH" else ""
        print(f"  {field:10s} value={pred.get('value')!r:20s} "
              f"confidence={pred.get('confidence')} source={pred.get('source')}  [{status}]{flag}")

    return parsed


def main() -> int:
    cfg = load_config()
    matched_dir = Path(cfg["paths"]["matched"])

    print(f"Searching for a figure under: {matched_dir}")
    img_path = find_first_figure(matched_dir)
    if img_path is None:
        print(f"No .png/.jpg files found under {matched_dir} — cannot run smoke test.")
        return 1
    print(f"Using figure: {img_path}")

    print("\nLoading InternVL2-8B via load_vlm_model() ...")
    vlm_bundle = load_vlm_model()
    if vlm_bundle is None:
        print("InternVL2 failed to load — check transformers version and GPU availability")
        return 1
    print("Model loaded.")

    start = time.perf_counter()
    run_and_report("M1 — vlm_extract_m1()", _M1_QUESTION, vlm_extract_m1, vlm_bundle, img_path)
    run_and_report("M2 — vlm_extract_m2()", _M2_QUESTION, vlm_extract_m2, vlm_bundle, img_path)
    run_and_report("M3 — vlm_extract_m3()", _M3_QUESTION, vlm_extract_m3, vlm_bundle, img_path)
    elapsed = time.perf_counter() - start

    print(f"\n{'=' * 70}")
    print(f"Total wall-clock time for M1+M2+M3 calls: {elapsed:.2f}s")
    print(f"{'=' * 70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
