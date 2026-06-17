"""
gpu_worker.py — called by process_patents_parallel() as an external subprocess.

Usage (internal):
    CUDA_VISIBLE_DEVICES=0 python gpu_worker.py <args_json_path> <result_json_path>

args_json contains: patent_ids, weights, raw_dir, matched_dir, triage_dir
result_json written on success: {rows, triage_skipped_total, logs}
"""

import json, re, shutil, sys
from pathlib import Path


def main():
    args_path, result_path = sys.argv[1], sys.argv[2]
    args = json.loads(Path(args_path).read_text())

    patent_ids  = args["patent_ids"]
    weights     = args["weights"]
    raw_dir     = Path(args["raw_dir"])
    matched_dir = Path(args["matched_dir"])
    triage_dir  = Path(args["triage_dir"])

    # Import heavy deps only after process starts (CUDA_VISIBLE_DEVICES already set)
    import torch
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    import doclayout_matcher as dm

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    engine = dm.build_engine(weights, device=device)

    _CLEAN_RE   = re.compile(r"[^A-Za-z0-9]")
    _NUM_SUFFIX = re.compile(r"_\d+$")
    _DL_SUFFIX  = re.compile(r"PAFP$|PAF$", re.IGNORECASE)
    _KIND_CODES = ["A1","A2","A3","B1","B2","C1","U1"]
    _NON_SHEET  = re.compile(r"manifest|thumbnail|cover|abstract|front.?page", re.IGNORECASE)
    _SHEET_RE   = re.compile(r"""
        (?:
            _[Dd]\d{3,}|PAFP_img\d|PAF_img\d|_img[af]?\d|fig_\d|record__fig_\d|
            ^img[af]?\d|^pat\d|^FT_\d|^HDA\d|^\d+\.|^srep\d|sN_img\d
        )""", re.VERBOSE | re.IGNORECASE)

    def _core(pid):
        p = _NUM_SUFFIX.sub("", pid)
        c = _CLEAN_RE.sub("", p).upper()
        c = _DL_SUFFIX.sub("", c)
        for sfx in _KIND_CODES:
            if c.endswith(sfx): return c[:-len(sfx)]
        return c

    def _is_sheet(f):
        if f.suffix.lower() != ".png": return False
        if _NON_SHEET.search(f.name): return False
        return bool(_SHEET_RE.search(f.name))

    def _excluded(pid):
        p = triage_dir / f"{pid}.json"
        if not p.exists(): return set()
        try:
            data = json.loads(p.read_text())
            return {fig["file"] for fig in data.get("figures", [])
                    if fig.get("keep") is False and fig.get("locked") is True}
        except Exception:
            return set()

    folder_map = {_core(p.name): p for p in raw_dir.iterdir() if p.is_dir()}

    rows: list[dict] = []
    triage_skipped_total = 0
    logs: list[str] = []

    for excel_id in patent_ids:
        folder = folder_map.get(_core(excel_id))
        if folder is None:
            logs.append(f"  ⚠  [{device}] No raw folder for {excel_id} — skipping")
            continue

        out_dir = matched_dir / folder.name
        out_dir.mkdir(parents=True, exist_ok=True)

        files     = sorted(folder.iterdir())
        img_files = [f for f in files if _is_sheet(f)]
        fat_files = [f for f in files if re.search(r"_FAT\d", f.name)]
        excl      = _excluded(folder.name)

        if excl:
            triage_skipped_total += sum(1 for f in img_files + fat_files if f.name in excl)
            img_files = [f for f in img_files if f.name not in excl]
            fat_files = [f for f in fat_files if f.name not in excl]

        for f in fat_files:
            out_path = out_dir / f"{f.stem}_Fu.png"
            shutil.copy2(f, out_path)
            rows.append({"patent_id": excel_id, "original": f.name, "output": out_path.name,
                         "label": None, "method": "fat_copy", "needs_review": True, "review_hint": ""})

        for img_path in img_files:
            try:
                res = dm.process_image(engine, img_path, out_dir)
                for c in res["crops"]:
                    rows.append({"patent_id": excel_id, "original": c["original"],
                                 "output": c["output"], "label": c["label"],
                                 "method": c["method"], "needs_review": c["needs_review"],
                                 "review_hint": c.get("review_hint", "")})
            except Exception as e:
                logs.append(f"    ❌ [{device}] {img_path.name}: {e}")

        torch.cuda.empty_cache()
        total    = sum(1 for r in rows if r["patent_id"] == excel_id)
        labelled = sum(1 for r in rows if r["patent_id"] == excel_id and not r["needs_review"])
        log = f"  ✓ [{device}] {excel_id}  sheets={len(img_files)}  crops={total}  labelled={labelled}"
        logs.append(log)
        print(log, flush=True)

    Path(result_path).write_text(json.dumps({
        "rows": rows,
        "triage_skipped_total": triage_skipped_total,
        "logs": logs,
    }))


if __name__ == "__main__":
    main()
