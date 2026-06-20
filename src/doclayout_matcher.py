"""
doclayout_matcher.py — public entrypoint + orchestration for the DocLayout-YOLO +
EasyOCR figure extraction pipeline.

Free, local alternative to the Claude API route. DocLayout-YOLO (a document-layout
detector) natively finds the `figure` regions on each patent drawing sheet and the
`figure_caption` regions; EasyOCR then reads each caption to recover the `FIG. N`
label for naming.

Raw files are never modified; crops are written to the chosen output directory using
the project naming convention: ``_F<label>`` when a label is read, ``_Fu`` otherwise.

The actual pipeline stages live in sibling modules — this file is a thin facade that
re-exports the public surface (so existing callers using ``import doclayout_matcher
as dm`` need no changes) and owns only the multiprocessing/subprocess orchestration,
which has to stay module-level here for pickling:

  - figure_detection.py — YOLO engine + per-sheet figure/caption detection
  - figure_labeling.py  — caption matching, OCR cascade, Qwen2.5-VL fallback, rotation
  - figure_cropping.py  — merge/pad/snap logic + writing the final crop PNGs
  - cv_utils.py          — shared binarization + box-geometry primitives
"""

from __future__ import annotations

from pathlib import Path

import cv2  # re-exported: scripts/eval_cropping.py reads crops via dm.cv2

from figure_detection import (
    DEFAULT_WEIGHTS, YOLO_CONF, CAPTION_CONF, NMS_IOU, IMGSZ,
    build_engine, detect_regions,
)
from figure_labeling import (
    FIG_KEY_RE, MAX_FIG_NUMBER, QWEN_PAD_BELOW_PX, QWEN_PAD_SIDE_PX,
    valid_fig_label, match_caption, read_label,
)
from figure_cropping import (
    MIN_CROP_PX, NOISE_FLOOR_PX, CROP_PAD_FRAC,
    FU_MERGE_GAP_PX, SAME_LABEL_MERGE_GAP_PX,
    crop_pad_px, crop_and_save, draw_regions,
    _crop_touches_border,   # re-exported: scripts/eval_cropping.py scores clip rate with this
)

__all__ = [
    "DEFAULT_WEIGHTS", "YOLO_CONF", "CAPTION_CONF", "NMS_IOU", "IMGSZ",
    "build_engine", "detect_regions",
    "FIG_KEY_RE", "MAX_FIG_NUMBER", "QWEN_PAD_BELOW_PX", "QWEN_PAD_SIDE_PX",
    "valid_fig_label", "match_caption", "read_label",
    "MIN_CROP_PX", "NOISE_FLOOR_PX", "CROP_PAD_FRAC",
    "FU_MERGE_GAP_PX", "SAME_LABEL_MERGE_GAP_PX",
    "crop_pad_px", "crop_and_save", "draw_regions",
    "process_image", "process_patents_parallel",
]


# ─── Orchestration ────────────────────────────────────────────────────────────

def process_image(engine, img_path: Path, out_dir: Path) -> dict:
    """
    Detect + crop one sheet.
    engine is the mutable list [model, reader, device, qwen_model, qwen_processor]
    returned by build_engine(). Qwen slots are populated lazily on first OCR miss.
    """
    model, reader, device = engine[0], engine[1], engine[2]
    figures, captions = detect_regions(model, img_path, device=device)
    crops = crop_and_save(img_path, figures, captions, engine, out_dir)
    return {"image": img_path.name, "figures": figures, "captions": captions, "crops": crops}


def process_patents_parallel(
    patent_rows,
    folder_map,
    matched_dir: Path,
    triage_dir: Path,
    engines,
    is_sheet_fn,
    triage_excluded_fn,
    cfg: dict,
    weights: str = DEFAULT_WEIGHTS,
    gpu_ids: list[str] | None = None,
) -> tuple[list[dict], int]:
    """
    Process patents across one or more GPUs using subprocess.Popen + CUDA_VISIBLE_DEVICES.
    Each worker is a fresh Python process that sees only its assigned GPU as cuda:0,
    so there is no CUDA re-init conflict and no GIL contention.
    Results are exchanged via temp JSON files.

    gpu_ids: explicit list of physical GPU indices to use, e.g. ["0"] or ["0", "1"].
    If None, defaults to one worker per visible GPU (or a single worker on GPU 0
    if only one GPU is visible) — the old behaviour.
    """
    import json, os, subprocess, sys, tempfile, torch
    from pathlib import Path as _Path

    ids = [str(r).strip() for r in patent_rows]

    if gpu_ids is None:
        n_gpu = torch.cuda.device_count()
        gpu_ids = [str(i) for i in range(n_gpu)] if n_gpu >= 1 else ["0"]

    n_workers = len(gpu_ids)
    chunk = max(1, -(-len(ids) // n_workers))  # ceil division
    splits = [ids[i:i + chunk] for i in range(0, len(ids), chunk)] or [[]]
    while len(splits) < n_workers:
        splits.append([])

    worker_script = str(_Path(__file__).parent / "gpu_worker.py")
    python_exe    = sys.executable

    tmp_dir = _Path(tempfile.mkdtemp(prefix="dm_parallel_"))
    procs   = []
    result_paths = []

    for i in range(n_workers):
        args_path   = tmp_dir / f"args_{i}.json"
        result_path = tmp_dir / f"result_{i}.json"
        result_paths.append(result_path)

        args_path.write_text(json.dumps({
            "patent_ids": splits[i],
            "weights":    weights,
            "raw_dir":    str(cfg["paths"]["raw_images"]),
            "matched_dir": str(matched_dir),
            "triage_dir":  str(triage_dir),
        }))

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids[i]

        p = subprocess.Popen(
            [python_exe, worker_script, str(args_path), str(result_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        procs.append(p)
        print(f"[GPU {gpu_ids[i]}] worker started (PID {p.pid})")

    # Stream output from both processes as they run
    import threading
    def _stream(proc, label):
        for line in proc.stdout:
            print(f"[GPU {label}] {line}", end="", flush=True)

    threads = [threading.Thread(target=_stream, args=(procs[i], gpu_ids[i]), daemon=True)
               for i in range(n_workers)]
    for t in threads: t.start()
    try:
        for p in procs:   p.wait()
        for t in threads: t.join()
    except BaseException:
        # An interrupt (Ctrl-C / Jupyter "Interrupt Kernel") only reliably
        # reaches whichever worker the signal happens to land on — the other
        # GPU's worker is otherwise left running unsupervised in the
        # background with nothing to ever stop it. Make sure every worker
        # actually dies before this function exits, no matter why we're
        # leaving early.
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        raise

    # Collect results
    all_rows: list[dict] = []
    triage_skipped_total = 0
    for rp in result_paths:
        if rp.exists():
            data = json.loads(rp.read_text())
            all_rows.extend(data["rows"])
            triage_skipped_total += data["triage_skipped_total"]
            continue
        # Worker crashed/was killed before writing its final result_json — fall
        # back to the incrementally-flushed partial CSV so patents it already
        # finished aren't silently lost.
        partial_csv = _Path(str(rp) + ".partial.csv")
        if partial_csv.exists():
            import csv as _csv
            with open(partial_csv, newline="") as f:
                partial_rows = list(_csv.DictReader(f))
            for r in partial_rows:
                r["needs_review"] = r["needs_review"] == "True"
            all_rows.extend(partial_rows)
            print(f"⚠  Result file missing: {rp} — worker crashed, recovered "
                  f"{len(partial_rows)} row(s) from its partial CSV")
        else:
            print(f"⚠  Result file missing: {rp} — worker may have crashed (no partial CSV either)")

    # Cleanup temp dir
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return all_rows, triage_skipped_total
