"""
dinov2.py — embed patent drawings with DINOv2 (Stage 04, stub).

Loads the model specified in cfg["dinov2"]["model"] from HuggingFace,
embeds each filtered image, and saves the CLS-token vectors to disk.

Public API (to be implemented)
-------------------------------
load_model(cfg)                              → tuple[model, processor]
embed_image(img_path, model, processor)      → np.ndarray   (shape: [embed_dim])
embed_patent(patent_id, cfg, model, processor) → dict[str, np.ndarray]
save_embeddings(patent_id, embeddings, cfg)  → Path
"""

from pathlib import Path


def load_model(cfg: dict):
    """
    Load the DINOv2 model and feature extractor from HuggingFace.

    TODO: use transformers.AutoModel.from_pretrained(cfg["dinov2"]["model"])
          and transformers.AutoFeatureExtractor.from_pretrained(...)
          Move model to GPU if available.
    """
    raise NotImplementedError("Stage 04: load_model not yet implemented")


def embed_image(img_path: Path, model, processor) -> "np.ndarray":
    """
    Embed a single image and return the CLS-token vector as a 1-D numpy array.

    TODO: open image, run through processor, forward pass through model,
          extract last_hidden_state[:, 0, :].squeeze(), return as numpy.
    """
    raise NotImplementedError("Stage 04: embed_image not yet implemented")


def embed_patent(
    patent_id: str,
    cfg: dict,
    model=None,
    processor=None,
) -> dict:
    """
    Embed all filtered images for one patent.

    Reads from cfg["paths"]["processed"] / patent_id (post-filter images).
    Returns {filename: embedding_vector}.

    TODO: load model if not provided, iterate images, call embed_image,
          collect results into dict.
    """
    raise NotImplementedError("Stage 04: embed_patent not yet implemented")


def save_embeddings(patent_id: str, embeddings: dict, cfg: dict) -> Path:
    """
    Save the embeddings dict to disk as a compressed numpy archive (.npz).

    Writes to cfg["paths"]["processed"] / patent_id / "embeddings.npz".

    TODO: np.savez_compressed(dest, **{k: v for k, v in embeddings.items()})
    """
    raise NotImplementedError("Stage 04: save_embeddings not yet implemented")
