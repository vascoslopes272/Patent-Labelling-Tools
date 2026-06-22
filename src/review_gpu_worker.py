"""
review_gpu_worker.py — called by run_stage01_parallel() as an external subprocess.

Mirrors gpu_worker.py's pattern (used by 00b2's process_patents_parallel) for
Stage 01: each worker is a fresh Python process pinned to one physical GPU via
CUDA_VISIBLE_DEVICES, loads its own SentenceTransformer + SigLIP instance on
cuda:0 (which the OS remaps to whichever physical card the env var picked),
and processes its assigned slice of patent_ids through process_patent().

Usage (internal):
    CUDA_VISIBLE_DEVICES=0 python review_gpu_worker.py <args_json_path> <result_json_path>

args_json contains: patent_ids, matched_dir, skip_siglip, enrich_citations,
visual_weight, text_weight, skip_files (list)
result_json written on success: {summary_rows, excel_rows, logs}
"""

import json, sys
from pathlib import Path


def main():
    args_path, result_path = sys.argv[1], sys.argv[2]
    args = json.loads(Path(args_path).read_text())

    patent_ids       = args["patent_ids"]
    matched_dir       = Path(args["matched_dir"])
    skip_siglip       = args["skip_siglip"]
    enrich_citations  = args["enrich_citations"]
    visual_weight     = args["visual_weight"]
    text_weight       = args["text_weight"]
    skip_files        = set(args.get("skip_files") or [])

    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "src"))

    import torch
    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    from src.config_loader import load_config
    from src.extractor import load_patseer_excel
    from src.cross_modal import load_siglip_model
    from sentence_transformers import SentenceTransformer
    import src.reviewer as reviewer
    from src.reviewer import process_patent, resolve_patent_image_dir, _resolve_crops_csv, _load_review_flags, _load_match_results
    from src.excel_schema import build_patent_rows

    reviewer.VISUAL_WEIGHT = visual_weight
    reviewer.TEXT_WEIGHT   = text_weight

    cfg = load_config()
    excel_idx = load_patseer_excel(cfg["paths"]["patseer_excel"])

    sbert_model = SentenceTransformer(
        "AI-Growth-Lab/PatentSBERTa",
        cache_folder=str(cfg["paths"]["sbert_cache"]),
        device=device,
    )
    siglip_bundle = None if skip_siglip else load_siglip_model(
        cache_dir=cfg["paths"]["siglip_cache"], device=device,
    )
    print(f"[{device}] models loaded — {len(patent_ids)} patent(s) assigned", flush=True)

    _crops_csv   = _resolve_crops_csv(cfg, matched_dir)
    review_flags = _load_review_flags(_crops_csv.parent, filename=_crops_csv.name)
    match_results_cache = _load_match_results(_crops_csv.parent, filename=_crops_csv.name)

    summary_rows: list[dict] = []
    excel_rows: list[dict] = []
    logs: list[str] = []

    for pid in patent_ids:
        try:
            data = process_patent(
                pid, cfg, excel_idx, matched_dir,
                sbert_model         = sbert_model,
                siglip_bundle       = siglip_bundle,
                skip_siglip         = skip_siglip,
                skip_files          = skip_files,
                enrich_citations    = enrich_citations,
                review_flags        = review_flags,
                match_results_cache = match_results_cache,
            )
            patent_img_dir = resolve_patent_image_dir(matched_dir, pid)
            excel_rows.extend(build_patent_rows(pid, data, patent_img_dir, cfg=cfg))

            figs     = data.get("T3_images", [])
            statuses = [f.get("match_status", "") for f in figs]
            summary_rows.append({
                "patent_id":         pid,
                "match_score":       round(
                    sum(1 for s in statuses
                        if s in ("matched", "semantic", "positional"))
                    / max(len(statuses), 1), 3),
                "matched":           statuses.count("matched"),
                "semantic":          statuses.count("semantic"),
                "positional":        statuses.count("positional"),
                "unmatched":         statuses.count("unmatched"),
                "human_required":    statuses.count("human_required"),
                "has_splits":        data.get("has_splits", False),
                "review_required":   any(f.get("needs_review") for f in figs),
                "description_found": bool(data.get("description_of_drawings")),
                "t2_labeled":        sum(1 for f in figs if f.get("T2_predictions")),
                "total_crops":       len(figs),
                "error":             None,
            })
            log = f"  ✓ [{device}] {pid}  crops={len(figs)}"
        except Exception as exc:
            summary_rows.append({
                "patent_id":   pid,
                "error":       str(exc),
                "match_score": 0.0,
                "total_crops": 0,
            })
            log = f"  ❌ [{device}] {pid}: {exc}"
        logs.append(log)
        print(log, flush=True)
        torch.cuda.empty_cache()

    Path(result_path).write_text(json.dumps({
        "summary_rows": summary_rows,
        "excel_rows":   excel_rows,
        "logs":         logs,
    }))


if __name__ == "__main__":
    main()
