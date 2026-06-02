"""
processor.py — image padding and resizing (Stage 02, stub).

Pads each drawing to a square canvas then resizes to processing.target_size
so all images fed to DINOv2 are identical in dimension.

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
    raise NotImplementedError("Stage 02: pad_to_square not yet implemented")


def resize_image(img: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    """
    Resize img to target_size with high-quality Lanczos resampling.

    TODO: return img.resize(target_size, Image.LANCZOS)
    """
    raise NotImplementedError("Stage 02: resize_image not yet implemented")


def process_image(src_path: Path, dst_path: Path, cfg: dict) -> None:
    """
    Pad and resize a single image; write result to dst_path.

    TODO: open src_path, call pad_to_square + resize_image, save to dst_path.
    Reads pad_color and target_size from cfg["processing"].
    """
    raise NotImplementedError("Stage 02: process_image not yet implemented")


def process_patent(patent_id: str, cfg: dict) -> int:
    """
    Process all images for one patent.
    Reads from  cfg["paths"]["raw_images"] / patent_id
    Writes to   cfg["paths"]["processed"]  / patent_id

    TODO: iterate fig_* images, call process_image for each, return count.
    """
    raise NotImplementedError("Stage 02: process_patent not yet implemented")
