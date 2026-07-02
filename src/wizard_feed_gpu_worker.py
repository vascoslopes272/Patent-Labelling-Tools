"""
wizard_feed_gpu_worker.py — called by 01a_wizard_feed.ipynb's T1-pre-label
cell as an external subprocess when 2+ GPUs are selected.

Mirrors review_gpu_worker.py's pattern (used by 01_review.ipynb's
run_stage01_parallel()), scoped down to the much lighter T1-only workload:
each worker is a fresh Python process pinned to one physical GPU via
CUDA_VISIBLE_DEVICES, loads its own PatentSBERTa instance on cuda:0 (which the
OS remaps to whichever physical card the env var picked), and classifies its
assigned slice of patent_ids' T1 dimensions (scope/t1Field/t1Target) via
src.reviewer.classify_t1_dimensions() — unchanged, same function 01a's
single-GPU path calls directly.

Usage (internal):
    CUDA_VISIBLE_DEVICES=0 python wizard_feed_gpu_worker.py <args_json_path> <result_json_path>

args_json contains: patent_ids, texts ({patent_id: text})
result_json written on success: {t1_predictions, logs}
"""

import json, sys
from pathlib import Path


def main():
    args_path, result_path = sys.argv[1], sys.argv[2]
    args = json.loads(Path(args_path).read_text())

    patent_ids = args["patent_ids"]
    texts      = args["texts"]   # {patent_id: text} precomputed by the notebook

    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "src"))

    import torch
    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    from src.config_loader import load_config
    from sentence_transformers import SentenceTransformer
    from src.reviewer import classify_t1_dimensions

    cfg = load_config()
    sbert_model = SentenceTransformer(
        "AI-Growth-Lab/PatentSBERTa",
        cache_folder=str(cfg["paths"]["sbert_cache"]),
        device=device,
    )
    print(f"[{device}] PatentSBERTa loaded — {len(patent_ids)} patent(s) assigned", flush=True)

    t1_predictions: dict = {}
    logs: list[str] = []

    for pid in patent_ids:
        try:
            t1_predictions[pid] = classify_t1_dimensions(texts.get(pid, ""), sbert_model)
            log = f"  ✓ [{device}] {pid}"
        except Exception as exc:
            t1_predictions[pid] = {
                "scope":    {"value": None, "confidence": 0.0, "source": None},
                "t1Field":  {"value": None, "confidence": 0.0, "source": None},
                "t1Target": {"value": None, "confidence": 0.0, "source": None},
            }
            log = f"  ❌ [{device}] {pid}: {exc}"
        logs.append(log)
        print(log, flush=True)

    Path(result_path).write_text(json.dumps({
        "t1_predictions": t1_predictions,
        "logs":           logs,
    }))


if __name__ == "__main__":
    main()
