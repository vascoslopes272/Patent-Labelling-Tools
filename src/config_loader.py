import re
from pathlib import Path
import yaml

_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _resolve(value: str, flat: dict) -> str:
    """Replace {{ section.key }} references with their already-resolved values."""
    def _sub(m):
        key = m.group(1)
        return flat.get(key, m.group(0))
    prev = None
    while prev != value:
        prev = value
        value = _TEMPLATE_RE.sub(_sub, value)
    return value


def load_config(config_path: Path | None = None) -> dict:
    """Load config.yaml, resolve template variables, and return the dict.

    Path values (under the 'paths' key) are returned as Path objects.
    """
    if config_path is None:
        # Walk up from this file until we find config.yaml
        here = Path(__file__).resolve().parent
        for candidate in [here, here.parent]:
            p = candidate / "config.yaml"
            if p.exists():
                config_path = p
                break
        if config_path is None:
            raise FileNotFoundError("config.yaml not found near src/")

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    # Build a flat lookup of "section.key" → raw string value for template resolution
    flat: dict[str, str] = {}
    for section, block in cfg.items():
        if isinstance(block, dict):
            for k, v in block.items():
                if isinstance(v, str):
                    flat[f"{section}.{k}"] = v

    # Resolve templates in all string values (two passes handles nested refs)
    for _ in range(5):
        for section, block in cfg.items():
            if isinstance(block, dict):
                for k, v in block.items():
                    if isinstance(v, str):
                        resolved = _resolve(v, flat)
                        cfg[section][k] = resolved
                        flat[f"{section}.{k}"] = resolved

    # Convert path values to Path objects
    for k, v in cfg.get("paths", {}).items():
        if isinstance(v, str):
            cfg["paths"][k] = Path(v)

    return cfg
