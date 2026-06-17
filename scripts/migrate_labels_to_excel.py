"""
migrate_labels_to_excel.py — one-off migration of pre-existing labels/*.json
(the old per-patent format, written by the now-deleted reviewer.write_patent_json())
into the new source_patents.xlsx row schema (src/excel_schema.py).

Old JSON files and a fresh run_stage01() both ultimately flow through
excel_schema.build_patent_rows(), so this script reuses that exact function —
no separate parsing/format logic to keep in sync.

Schema-alignment assertion: before writing the migrated workbook, this script
also builds rows for a small fresh sample (via process_patent()) and asserts
the migrated JSONs and the live pipeline emit the same set of Field keys per
Section. A mismatch means the old JSON format and the current pipeline have
drifted apart — failing loudly here prevents that drift from silently
corrupting source_patents.xlsx.

Usage:
    python3 scripts/migrate_labels_to_excel.py [--sample-size N] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
for p in (str(_repo_root), str(_repo_root / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.config_loader import load_config
from src.excel_schema import build_patent_rows, export_source_excel, rows_to_dataframe
from src.reviewer import process_patent, resolve_patent_image_dir


def _field_keys_by_section(rows: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(r["Section"], set()).add(r["Field"])
    return out


def assert_schema_alignment(migrated_rows: list[dict], fresh_rows: list[dict], sample_ids: list[str]) -> None:
    """
    Compare Field-key sets per matching Patent_ID (old JSON vs a fresh
    run_stage01() pass on the *same* patent), rather than across the whole
    corpus — a corpus-wide comparison would false-positive whenever the fresh
    sample happens to skip an architecture variant (e.g. a 4-wing patent)
    that exists elsewhere in the full migrated set but not in the sample.
    """
    mismatches = {}
    for pid in sample_ids:
        old_rows = [r for r in migrated_rows if r["Patent_ID"] == pid]
        new_rows = [r for r in fresh_rows if r["Patent_ID"] == pid]
        old_by_section = _field_keys_by_section(old_rows)
        new_by_section = _field_keys_by_section(new_rows)

        for section in set(old_by_section) | set(new_by_section):
            old_keys = old_by_section.get(section, set())
            new_keys = new_by_section.get(section, set())
            diff = old_keys ^ new_keys
            if diff:
                mismatches.setdefault(pid, {})[section] = {
                    "only_in_migrated": sorted(old_keys - new_keys),
                    "only_in_fresh":    sorted(new_keys - old_keys),
                }

    if mismatches:
        print("\nSCHEMA ALIGNMENT FAILURE — old JSON and a fresh run_stage01() pass "
              "produced different Field keys for the same patent(s):\n")
        for pid, sections in mismatches.items():
            print(f"  {pid}")
            for section, diff in sections.items():
                print(f"    [{section}]")
                if diff["only_in_migrated"]:
                    print(f"      only in old JSON  : {diff['only_in_migrated']}")
                if diff["only_in_fresh"]:
                    print(f"      only in fresh run : {diff['only_in_fresh']}")
        raise AssertionError(
            "Field-key sets differ between migrated labels/*.json and a fresh "
            "run_stage01() pass on the same patent(s) — see printed diff above. "
            "Refusing to write source_patents.xlsx with a drifted schema."
        )
    print(f"Schema alignment OK — old JSON and fresh run_stage01() Field-key sets "
          f"match for all {len(sample_ids)} sampled patent(s).")


def migrate(labels_dir: Path, matched_dir: Path) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    patent_ids: list[str] = []
    json_files = sorted(labels_dir.glob("*.json"))
    print(f"Found {len(json_files)} old label JSON(s) in {labels_dir}")
    for jf in json_files:
        patent_id = jf.stem
        record = json.loads(jf.read_text())
        patent_img_dir = resolve_patent_image_dir(matched_dir, patent_id)
        rows.extend(build_patent_rows(patent_id, record, patent_img_dir))
        patent_ids.append(patent_id)
    return rows, patent_ids


def fresh_sample_rows(cfg: dict, matched_dir: Path, candidate_ids: list[str],
                       sample_size: int, skip_siglip: bool = False) -> tuple[list[dict], list[str]]:
    """
    Re-process a sample drawn from the same patents already migrated, so each
    sampled patent can be compared old-vs-fresh on equal footing.

    skip_siglip must stay False for the comparison to be meaningful: without
    real SigLIP architecture classification, G1/M2 fall back to a generic
    "unclassified" path, so M3's per-component Field keys (which are named
    after the classified architecture's parts, e.g. "wing1_*"/"emp_*") would
    legitimately differ from the old JSON's real-classification keys — that's
    a sampling artifact, not schema drift.
    """
    from src.extractor import load_patseer_excel
    from src.cross_modal import load_siglip_model
    from sentence_transformers import SentenceTransformer

    excel_idx = load_patseer_excel(cfg["paths"]["patseer_excel"])
    available = {d.name.rsplit("_", 1)[0] for d in matched_dir.iterdir() if d.is_dir()}
    pids = [pid for pid in candidate_ids if pid in available][:sample_size]
    print(f"Running a fresh sample of {len(pids)} patent(s) for schema comparison: {pids}")

    sbert_model = None
    siglip_bundle = None
    if not skip_siglip:
        print("Loading SBERT + SigLIP for the fresh comparison sample (required for a faithful check)...")
        sbert_model = SentenceTransformer("AI-Growth-Lab/PatentSBERTa", cache_folder=str(cfg["paths"]["sbert_cache"]))
        siglip_bundle = load_siglip_model(cache_dir=cfg["paths"]["siglip_cache"])

    rows: list[dict] = []
    for pid in pids:
        data = process_patent(pid, cfg, excel_idx, matched_dir,
                               sbert_model=sbert_model, siglip_bundle=siglip_bundle, skip_siglip=skip_siglip)
        patent_img_dir = resolve_patent_image_dir(matched_dir, pid)
        rows.extend(build_patent_rows(pid, data, patent_img_dir))
    return rows, pids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=8,
                         help="Number of patents to freshly process for the schema-alignment check.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output path for the migrated workbook (defaults to cfg paths.source_excel).")
    parser.add_argument("--skip-siglip", action="store_true",
                         help="Skip loading SigLIP/SBERT for the comparison sample (faster, but the "
                              "schema check becomes meaningless for M2/M3 — only use for a quick smoke test).")
    args = parser.parse_args()

    cfg = load_config()
    # Must be set before any sentence_transformers/huggingface_hub import — see 01_review.ipynb.
    import os
    os.environ["HF_HUB_CACHE"] = str(cfg["paths"]["siglip_cache"])
    os.environ["HF_HOME"]      = str(cfg["paths"]["siglip_cache"])

    labels_dir  = Path(cfg["paths"]["labels"])
    matched_dir = Path(cfg["paths"]["matched"])
    out_path    = args.out or Path(cfg["paths"]["source_excel"])

    if not labels_dir.exists() or not any(labels_dir.glob("*.json")):
        print(f"No old label JSONs found at {labels_dir} — nothing to migrate.")
        return

    migrated_rows, migrated_ids = migrate(labels_dir, matched_dir)
    if not migrated_rows:
        print("No rows produced from old JSONs — aborting without writing anything.")
        return

    fresh_rows, sample_ids = fresh_sample_rows(cfg, matched_dir, migrated_ids, args.sample_size,
                                                skip_siglip=args.skip_siglip)
    if fresh_rows:
        assert_schema_alignment(migrated_rows, fresh_rows, sample_ids)
    else:
        print("WARNING: fresh sample produced zero rows — skipping schema-alignment check.")

    export_source_excel(migrated_rows, out_path)
    df = rows_to_dataframe(migrated_rows)
    print(f"\nMigrated {df['Patent_ID'].nunique()} patent(s), {len(df)} rows -> {out_path}")


if __name__ == "__main__":
    main()
