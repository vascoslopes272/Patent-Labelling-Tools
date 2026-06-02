"""
config_loader.py — single entry point for all configuration.

Resolves {{ paths.base }} template references, then converts all path
strings to absolute pathlib.Path objects.

Usage
-----
    from src.config_loader import load_config
    cfg = load_config()
    cfg["paths"]["raw_images"]      # Path object
    cfg["extractor"]["scan_limit"]  # int
"""

import re
from pathlib import Path

import yaml


def _find_config() -> Path:
    """Walk up from src/ until config.yaml is found (works from notebooks/ too)."""
    here = Path(__file__).resolve().parent  # src/
    for candidate in [here.parent, here, here.parent.parent]:
        p = candidate / "config.yaml"
        if p.exists():
            return p
    raise FileNotFoundError("config.yaml not found searching from " + str(here))


def _resolve_templates(cfg: dict) -> dict:
    """Replace {{ paths.base }} references in all path values."""
    paths = cfg.get("paths", {})
    base = paths.get("base", "")
    cfg["paths"] = {
        k: v.replace("{{ paths.base }}", base) if isinstance(v, str) else v
        for k, v in paths.items()
    }
    return cfg


def load_config(config_path: str | Path | None = None) -> dict:
    """
    Load config.yaml, resolve templates, and convert path strings to Path objects.

    Parameters
    ----------
    config_path : explicit path to config.yaml; if None, searches upward from src/.
    """
    if config_path is None:
        config_path = _find_config()
    config_path = Path(config_path).resolve()

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cfg = _resolve_templates(cfg)

    for key, val in cfg.get("paths", {}).items():
        if val:
            cfg["paths"][key] = Path(val)

    return cfg
