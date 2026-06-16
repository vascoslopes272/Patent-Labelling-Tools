"""
figure_matcher.py — Local GPU VLM-based figure labelling for PatSeer drawing sheets.
Replaces broken PaddleOCR components with Qwen2.5-VL-7B-Instruct.

Processing order per patent: img* → D* → FAT* (each group sorted numerically).
Raw files are never modified; all crops are written to matched/<patent_id>/.
"""

from __future__ import annotations

import re
import json
import shutil
from pathlib import Path
import cv2
import numpy as np
import pandas as pd
import torch
from PIL import Image
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info

# ─── Internal helpers ─────────────────────────────────────────────────────────

_FIG_KEY_RE = re.compile(r"FIG(?:URE)?S?\.?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)
_MIN_CROP_PX = 150   # discard crops smaller than this in either dimension

def _file_sort_key(name: str) -> int:
    m = re.search(r"_(?:img|D|FAT)_?([0-9]+)", name)
    return int(m.group(1)) if m else 999999

def _patent_core(pid: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", pid).upper()
    for sfx in ["A1", "A2", "A3", "B1", "B2", "C1", "U1"]:
        if cleaned.endswith(sfx):
            return cleaned[:-len(sfx)]
    return cleaned

def _build_folder_map(raw_dir: Path) -> dict[str, Path]:
    mapping = {}
    if not raw_dir.is_dir():
        return mapping
    for p in raw_dir.iterdir():
        if p.is_dir():
            mapping[_patent_core(p.name)] = p
    return mapping

# ─── Public API ───────────────────────────────────────────────────────────────

def build_engine(cfg: dict) -> tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor]:
    """
    Initialise Qwen2.5-VL-7B-Instruct (4-bit quantized) on your local GPU.
    4-bit NF4 quantization brings weight footprint to ~4 GB, leaving sufficient
    VRAM headroom for activation allocations on a 10-11 GB card.
    """
    model_id = "Qwen/Qwen2.5-VL-7B-Instruct"

    cache_path = Path(cfg["paths"].get("model_cache", "models/Qwen"))
    cache_path.mkdir(parents=True, exist_ok=True)

    print(f"Loading local GPU Vision Model (4-bit): {model_id}...")
    print(f"Using model cache repository path: {cache_path.resolve()}")

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        llm_int8_enable_fp32_cpu_offload=True,
    )

    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_id,
        quantization_config=bnb_cfg,
        device_map="auto",
        cache_dir=str(cache_path),
    )

    processor = AutoProcessor.from_pretrained(
        model_id,
        cache_dir=str(cache_path),
        min_pixels=256 * 28 * 28,
        max_pixels=768 * 28 * 28,
        padding_side="left",
    )

    print("VLM Engine loaded successfully on GPU within memory limits.")
    return model, processor

def process_file(
    img_path: Path,
    out_dir: Path,
    desc: str,
    is_fat: bool,
    engine: tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor]
) -> list[dict]:
    """
    Processes a single patent drawing sheet using the unified VLM interface.
    """
    model, processor = engine
    crops_produced = []

    if is_fat:
        out_path = out_dir / f"{img_path.stem}_crop_0_Fu.png"
        img = cv2.imread(str(img_path))
        if img is not None:
            cv2.imwrite(str(out_path), img)
            crops_produced.append({
                "original": img_path.name,
                "output": out_path.name,
                "label": None,
                "method": "vlm_fat_fallback",
                "is_fat": True,
                "needs_review": True
            })
        return crops_produced

    # Structural prompt architecture to enforce valid JSON parsing outputs
    prompt = (
        "Analyze this patent drawing sheet. Identify all sub-figures present in the layout.\n"
        "For each sub-figure, provide the exact figure label string (e.g., 'FIG. 1', 'FIG. 2A') "
        "and its bounding box coordinate array formatted exactly like: [ymin, xmin, ymax, xmax] normalized from 0 to 1000.\n"
        "Context description information:\n"
        f"\"{desc}\"\n\n"
        "Return your structural answer as a raw JSON list with no markdown wrapper blocks: "
        "[{\"box\": [ymin, xmin, ymax, xmax], \"label\": \"FIG. X\"}]"
    )

    try:
        # Load via PIL to match the vision processing inputs expected by qwen_vl_utils
        raw_image = Image.open(img_path).convert("RGB")

        # Properly structured messages schema mapping
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": raw_image},
                    {"type": "text", "text": prompt}
                ]
            }
        ]

        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt"
        ).to("cuda")

        with torch.no_grad():
            generated_ids = model.generate(**inputs, max_new_tokens=512)
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]

        # Extract code strings from possible markdown blocks securely
        cleaned_json = output_text.strip()
        if "```json" in cleaned_json:
            cleaned_json = cleaned_json.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned_json:
            cleaned_json = cleaned_json.split("```")[1].split("```")[0].strip()

        parsed_data = json.loads(cleaned_json)

        img = cv2.imread(str(img_path))
        if img is None:
            return crops_produced
        h, w = img.shape[:2]

        for idx, item in enumerate(parsed_data):
            box = item.get("box", [])
            label = item.get("label", None)
            
            if len(box) == 4:
                ymin, xmin, ymax, xmax = box
                ymin_px = int((ymin / 1000.0) * h)
                xmin_px = int((xmin / 1000.0) * w)
                ymax_px = int((ymax / 1000.0) * h)
                xmax_px = int((xmax / 1000.0) * w)
                
                ymin_px = max(0, min(ymin_px, h - 1))
                xmin_px = max(0, min(xmin_px, w - 1))
                ymax_px = max(ymin_px + 10, min(ymax_px, h))
                xmax_px = max(xmin_px + 10, min(xmax_px, w))

                crop = img[ymin_px:ymax_px, xmin_px:xmax_px]
                if crop.shape[0] < _MIN_CROP_PX or crop.shape[1] < _MIN_CROP_PX:
                    continue

                clean_lbl = "unassigned"
                needs_review = True
                if label:
                    match = _FIG_KEY_RE.search(label)
                    if match:
                        clean_lbl = match.group(1)
                        needs_review = False

                lbl_suffix = f"_F{clean_lbl}" if not needs_review else "_Fu"
                out_path = out_dir / f"{img_path.stem}_crop_{idx}{lbl_suffix}.png"
                cv2.imwrite(str(out_path), crop)

                crops_produced.append({
                    "original": img_path.name,
                    "output": out_path.name,
                    "label": clean_lbl if not needs_review else None,
                    "method": "vlm_spatial_ocr",
                    "is_fat": False,
                    "needs_review": needs_review
                })

    except Exception as e:
        print(f"    ⚠ Visual parsing warning for {img_path.name}: {e}")
        out_path = out_dir / f"{img_path.stem}_crop_fallback_Fu.png"
        img = cv2.imread(str(img_path))
        if img is not None:
            cv2.imwrite(str(out_path), img)
            crops_produced.append({
                "original": img_path.name,
                "output": out_path.name,
                "label": None,
                "method": "vlm_error_fallback",
                "is_fat": False,
                "needs_review": True
            })

    # Cleanup variables and empty the cache at the end of every individual file loop iteration
    if "inputs" in locals(): 
        del inputs
    if "generated_ids" in locals(): 
        del generated_ids
    if "generated_ids_trimmed" in locals(): 
        del generated_ids_trimmed
    torch.cuda.empty_cache()

    return crops_produced

def process_patent(
    patent_id: str,
    raw_dir: Path,
    matched_dir: Path,
    desc: str,
    cfg: dict,
    engine: tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor]
) -> dict:
    """
    Handles file execution sequence groups (img -> D -> FAT).
    """
    p_dir = raw_dir / patent_id
    out_dir = matched_dir / patent_id
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted([p for p in p_dir.iterdir() if p.is_file()], key=lambda x: _file_sort_key(x.name))
    
    img_files = [f for f in files if re.search(r"_img\d", f.name)]
    d_files   = [f for f in files if re.search(r"_D\d", f.name)]
    fat_files = [f for f in files if re.search(r"_FAT\d", f.name)]

    patent_summary = {"patent_id": patent_id, "files": []}

    for f in img_files:
        patent_summary["files"].extend(process_file(f, out_dir, desc, False, engine))
    for f in d_files:
        patent_summary["files"].extend(process_file(f, out_dir, desc, False, engine))
    for f in fat_files:
        patent_summary["files"].extend(process_file(f, out_dir, desc, True, engine))

    return patent_summary

def rename_matched_files(matches: list[dict], img_dir: Path, dest_dir: Path | None = None) -> dict:
    """
    Write matched figure crops to dest_dir (or img_dir if not given).
    Raw files in img_dir are never modified — non-split files are copied
    with shutil.copy2(), split crops are written fresh with cv2.imwrite().

    Each entry in `matches` provides:
        out_name   : destination filename
        was_split  : True if this crop came from a split (D/FAT) sheet
        src_path   : Path to copy from, when was_split is False
        arr        : np.ndarray crop, when was_split is True
        label      : figure label string, or None if unlabeled
    """
    dest_root = dest_dir if dest_dir is not None else img_dir
    dest_root.mkdir(parents=True, exist_ok=True)

    result = {"renamed_F": 0, "renamed_Fu": 0, "kept_originals": 0, "errors": []}

    for m in matches:
        out_name = m.get("out_name")
        was_split = m.get("was_split", False)
        try:
            if was_split:
                cv2.imwrite(str(dest_root / out_name), m["arr"])
            else:
                src_path = m["src_path"]
                shutil.copy2(src_path, dest_root / out_name)
                result["kept_originals"] += 1

            if m.get("label"):
                result["renamed_F"] += 1
            else:
                result["renamed_Fu"] += 1
        except Exception as e:
            result["errors"].append({"out_name": out_name, "error": str(e)})

    return result


def process_all_patents(
    df: pd.DataFrame,
    cfg: dict,
    engine: tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor]
) -> pd.DataFrame:
    """
    Iterates across database frames parsing figure segments using the VLM backend.
    """
    raw_dir     = Path(cfg["paths"]["raw_images"])
    matched_dir = Path(cfg["paths"]["matched"])
    folder_map  = _build_folder_map(raw_dir)

    rows: list[dict] = []

    for _, row in df.iterrows():
        excel_id = str(row.get("patent_id", "")).strip()
        if not excel_id:
            continue
        desc = str(row.get("description_of_drawings", "") or "")

        folder = folder_map.get(_patent_core(excel_id))
        if folder is None:
            print(f"  ⚠  No raw folder found for {excel_id} — skipping")
            continue
        actual_id = folder.name

        try:
            summary = process_patent(actual_id, raw_dir, matched_dir, desc, cfg, engine)
            for f in summary["files"]:
                rows.append({
                    "patent_id":    excel_id,
                    "original":     f["original"],
                    "output":       f["output"],
                    "label":        f["label"],
                    "method":       f["method"],
                    "is_fat":       f["is_fat"],
                    "needs_review": f["needs_review"],
                    "labeled":      1 if f["label"] is not None else 0,
                    "unlabeled":    1 if f["label"] is None else 0,
                })
            print(f"  ✓ Successfully processed patent {excel_id}")
        except Exception as e:
            print(f"  ❌ Failed processing patent {excel_id}: {e}")

    return pd.DataFrame(rows)