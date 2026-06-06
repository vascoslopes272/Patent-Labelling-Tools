"""
processor.py — image padding and resizing (Stage 02, stub).

Pads each drawing to a square canvas then resizes to processing.target_size
so all images have identical dimensions for downstream embedding models.

Public API (to be implemented)
-------------------------------
pad_to_square(img, pad_color)           → PIL.Image
resize_image(img, target_size)          → PIL.Image
process_image(src_path, dst_path, cfg)  → None
process_patent(patent_id, cfg)          → int   (number of images processed)
"""

from pathlib import Path
from PIL import Image


def pad_to_square(img: Image.Image, pad_color: str = "white") -> Image.Image:
    """
    Pad img to a square canvas (side = max(width, height)) using pad_color.

    TODO: create a new RGB image of size (max_side, max_side), paste img
          centred, return the padded result.
    """
    w, h   = img.size
    side   = max(w, h)
    canvas = Image.new("RGB", (side, side), pad_color)
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    return canvas


def resize_image(img: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    """
    Resize img to target_size with high-quality Lanczos resampling.

    TODO: return img.resize(target_size, Image.LANCZOS)
    """
    return img.resize(target_size, Image.LANCZOS)


def process_image(src_path: Path, dst_path: Path, cfg: dict) -> None:
    """
    Pad and resize a single image; write result to dst_path.

    TODO: open src_path, call pad_to_square + resize_image, save to dst_path.
    Reads pad_color and target_size from cfg["processing"].
    """
    pad_color   = cfg.get("processing", {}).get("pad_color", "white")
    target_size = tuple(cfg.get("processing", {}).get("target_size", [518, 518]))
    img = Image.open(src_path).convert("RGB")
    img = pad_to_square(img, pad_color)
    img = resize_image(img, target_size)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst_path, "PNG")


def process_patent(patent_id: str, cfg: dict) -> int:
    """
    Process all images for one patent.
    Reads from  cfg["paths"]["raw_images"] / patent_id
    Writes to   cfg["paths"]["processed"]  / patent_id

    TODO: iterate fig_* images, call process_image for each, return count.
    """
    raw_dir  = Path(cfg["paths"]["raw_images"])  / patent_id
    proc_dir = Path(cfg["paths"]["processed"])   / patent_id
    proc_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in sorted(raw_dir.glob("*.png")):
        dst = proc_dir / src.name
        if dst.exists():
            continue
        try:
            process_image(src, dst, cfg)
            count += 1
        except Exception as exc:
            print(f"  processor: skipped {src.name}: {exc}")
    return count
