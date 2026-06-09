"""
figure_matcher.py — Local GPU VLM-based figure labelling for PatSeer drawing sheets.
Replaces broken PaddleOCR components with Qwen2.5-VL-7B-Instruct.

Processing order per patent: img* → D* → FAT* (each group sorted numerically).
Raw files are never modified; all crops are written to matched/<patent_id>/.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
import cv2
import numpy as np
import pandas as pd
import torch
from PIL import Image
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

# ─── Internal helpers ─────────────────────────────────────────────────────────
# Add this line back in! It is critical for extraction to work.
_FIG_KEY_RE = re.compile(r"FIG(?:URE)?S?\.?\s*([0-9]+[A-Za-z]?)", re.IGNORECASE)

_MIN_CROP_PX = 150   # discard crops smaller than this in either dimension

def _file_sort_key(name: str) -> int:
    m = re.search(r"_(?:img|D|FAT)_([0-9]+)", name)
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

# Change the function signature to accept your config dictionary (cfg)
def build_engine(cfg: dict) -> tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor]:
    """
    Initialise Qwen2.5-VL-7B-Instruct once on your local GPU.
    Loads model weights from the cache directory configured inside config.yaml.
    """
    model_id = "Qwen/Qwen2.5-VL-7B-Instruct"
    
    # Read the cache folder path straight from your yaml settings dynamically
    cache_path = Path(cfg["paths"].get("model_cache", "models/Qwen"))
    cache_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading local GPU Vision Model: {model_id}...")
    print(f"Using workspace model repository location: {cache_path.resolve()}")
    
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        cache_dir=str(cache_path)  # Controlled via config.yaml
    )
    processor = AutoProcessor.from_pretrained(
        model_id,
        cache_dir=str(cache_path)  # Controlled via config.yaml
    )
    print("VLM Engine loaded successfully on GPU.")
    return model, processor


def process_file(
    img_path: Path,
    patent_id: str,
    matched_dir: Path,
    is_fat: bool,
    engine: tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor],
    fig_regex: str,
    desc_figs: list[str],
    positional_counter: list[int]
) -> list[dict]:
    """
    Processes a single drawing sheet using the local GPU VLM layout processor.
    """
    model, processor = engine
    
    # Load Image arrays
    pil_img = Image.open(img_path).convert("RGB")
    cv_img = cv2.imread(str(img_path))
    if cv_img is None:
        print(f"  ⚠  Could not read image: {img_path}")
        return []
        
    h, w, _ = cv_img.shape
    out_dir = matched_dir / patent_id
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # FAT files require cropping without automated labeling assignments
    if is_fat:
        prompt = """Analyze this patent sheet. Locate all sub-figure boundaries. 
        Return coordinates relative to the full image coordinates [x1, y1, x2, y2]. Use the format:
        [{"bbox_2d": [x1, y1, x2, y2], "label": "FIG. u"}]"""
    else:
        prompt = """Analyze this patent drawing sheet. 
        Identify all standalone sub-figures or cohesive schematic blocks.
        For each, return its bounding boxes in absolute coordinates [x1, y1, x2, y2] relative to the image canvas.
        Also read the exact sub-figure text label (e.g. 'FIG. 1', 'FIG. 3') associated with it.
        Return ONLY a clean JSON array matching this format:
        [{"bbox_2d": [x1, y1, x2, y2], "label": "FIG. 1"}]"""

    messages = [{"role": "user", "content": [{"type": "image", "image": pil_img}, {"type": "text", "text": prompt}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(images=pil_img, texts=text, return_tensors="pt").to("cuda")
    
    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=1000)
    
    generated_ids_trimmed = [out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
    output_text = processor.batch_decode(generated_ids_trimmed, skip_special_tokens=True)[0]
    
    # Parse coordinates and crop
    crops_produced = []
    try:
        clean_json = re.sub(r"```json\s*|\s*```", "", output_text).strip()
        predictions = json.loads(clean_json)
    except Exception:
        # Fallback to saving whole sheet as unconditional unlabelled block if JSON fails
        predictions = [{"bbox_2d": [0, 0, w, h], "label": "FIG. u"}]

    for idx, pred in enumerate(predictions):
        bbox = pred.get("bbox_2d", [0, 0, w, h])
        vlm_label = str(pred.get("label", "FIG. u")).strip()
        
        x1, y1 = max(0, int(bbox[0])), max(0, int(bbox[1]))
        x2, y2 = min(w, int(bbox[2])), min(h, int(bbox[3]))
        
        # Guard against zero-area crops or trash fragments
        if (x2 - x1) < _MIN_CROP_PX or (y2 - y1) < _MIN_CROP_PX:
            continue
            
        crop_arr = cv_img[y1:y2, x1:x2]
        method = "vlm_grounding"
        needs_review = False
        final_label = None
        
        # Clean label strings via Regex matches
        label_match = re.search(fig_regex, vlm_label, re.IGNORECASE)
        
        if label_match and not is_fat:
            final_label = label_match.group(1).upper()
            filename = f"{patent_id}_F{final_label.zfill(3)}.png"
        else:
            # Positional Fallback if the VLM found structural blocks but missed parsing specific labels
            method = "positional_fallback" if not is_fat else "fat_force_unlabeled"
            if not is_fat and positional_counter[0] < len(desc_figs):
                final_label = desc_figs[positional_counter[0]]
                filename = f"{patent_id}_F{final_label.zfill(3)}.png"
                positional_counter[0] += 1
            else:
                filename = f"{patent_id}_Fu{positional_counter[1]:03d}.png"
                positional_counter[1] += 1
                needs_review = True
                
        # Resolve any duplicate name collisions safely via alphabetic extensions
        out_path = out_dir / filename
        suffix_idx = 1
        while out_path.exists():
            letter_suffix = chr(97 + suffix_idx)  # 'b', 'c', etc.
            stem = out_path.stem
            if re.search(r"_[b-z]$", stem):
                stem = stem[:-2]
            out_path = out_dir / f"{stem}_{letter_suffix}.png"
            suffix_idx += 1

        cv2.imwrite(str(out_path), crop_arr)
        
        crops_produced.append({
            "original": img_path.name,
            "output": out_path.name,
            "label": final_label,
            "method": method,
            "is_fat": is_fat,
            "needs_review": needs_review
        })
        
    return crops_produced


def process_patent(
    patent_id: str,
    raw_dir: Path,
    matched_dir: Path,
    description_text: str,
    cfg: dict,
    engine: tuple[Qwen2_5_VLForConditionalGeneration, AutoProcessor]
) -> dict:
    """
    Collects raw assets and processes them sequentially via the loaded VLM engine.
    """
    p_folder = raw_dir / patent_id
    if not p_folder.is_dir():
        return {"patent_id": patent_id, "files": []}
        
    fig_regex = cfg["matching"]["fig_regex"]
    
    # Parse target sequence array out of PatSeer Excel text description block
    desc_figs = []
    if description_text:
        desc_figs = _FIG_KEY_RE.findall(description_text)
        
    all_files = list(p_folder.iterdir())
    imgs = sorted([f for f in all_files if "_img" in f.name], key=lambda x: _file_sort_key(x.name))
    ds   = sorted([f for f in all_files if "_D" in f.name], key=lambda x: _file_sort_key(x.name))
    fats = sorted([f for f in all_files if "_FAT" in f.name], key=lambda x: _file_sort_key(x.name))
    
    processing_queue = []
    for f in imgs: processing_queue.append((f, False))
    for f in ds:   processing_queue.append((f, False))
    for f in fats: processing_queue.append((f, True))
    
    positional_counter = [0, 1]  # [positional_idx, unlabeled_sequence_idx]
    results = []
    
    for img_path, is_fat in processing_queue:
        file_crops = process_file(
            img_path=img_path,
            patent_id=patent_id,
            matched_dir=matched_dir,
            is_fat=is_fat,
            engine=engine,
            fig_regex=fig_regex,
            desc_figs=desc_figs,
            positional_counter=positional_counter
        )
        results.extend(file_crops)
        
    return {"patent_id": patent_id, "files": results}


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
        except Exception as e:
            print(f"  ❌ Failed processing patent {excel_id}: {e}")
            
    return pd.DataFrame(rows)