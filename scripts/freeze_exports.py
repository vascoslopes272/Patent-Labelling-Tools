#!/usr/bin/env python3
"""freeze_exports.py — make the human wizard exports immutable, and hand out
editable working copies.

The wizard exports in `paths.html_review_exports` (03_HUMAN_wizard_exports/) are the
only record of what the annotator actually clicked. Once a batch is finished they are
frozen: chmod 444 + a SHA-256 line in PRISTINE_MANIFEST.sha256. Nothing downstream
writes to them again.

Every correction after that — cross-batch duplicate links, codebook conformance,
physics-consistency fixes (a tilt-wing whose wings do not tilt) — is applied to a COPY
in `paths.corrected_wizard_exports` (03c_CORRECTED_wizard_exports/), which is what 02a
reads. A copy can always be thrown away and remade from the frozen original.

    python scripts/freeze_exports.py --status
    python scripts/freeze_exports.py --freeze Batch_01 Batch_02 Batch_05
    python scripts/freeze_exports.py --copy   Batch_01 Batch_02 Batch_05
    python scripts/freeze_exports.py --verify              # tamper check
    python scripts/freeze_exports.py --copy Batch_02 --force   # redo a copy from frozen
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config_loader import load_config  # noqa: E402

MANIFEST_NAME = "PRISTINE_MANIFEST.sha256"
# Batch_05's export has always carried a stray space before ".xlsx"; the working copy
# normalises it away so 02a's exact-name lookup stops falling back to its near-miss rescue.
def export_name(batch: str) -> str:
    return f"reviewed_patents_{batch}.xlsx"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_export(src_dir: Path, batch: str) -> Path | None:
    exact = src_dir / export_name(batch)
    if exact.exists():
        return exact
    near = [p for p in src_dir.glob("reviewed_patents_*.xlsx")
            if p.name.replace(" ", "") == exact.name.replace(" ", "")]
    return near[0] if near else None


def read_manifest(src_dir: Path) -> dict[str, str]:
    mf = src_dir / MANIFEST_NAME
    out: dict[str, str] = {}
    if mf.exists():
        for line in mf.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, name = line.split("  ", 1)
            out[name] = digest
    return out


def write_manifest(src_dir: Path, entries: dict[str, str]) -> None:
    lines = [
        "# SHA-256 of the frozen human wizard exports. Written by scripts/freeze_exports.py.",
        "# A mismatch means an export was edited in place — corrections belong in the",
        "# corrected_wizard_exports copy, never here. Restore from backup before continuing.",
    ]
    lines += [f"{d}  {n}" for n, d in sorted(entries.items())]
    (src_dir / MANIFEST_NAME).write_text("\n".join(lines) + "\n")


def is_frozen(path: Path) -> bool:
    return not (path.stat().st_mode & stat.S_IWUSR)


def cmd_status(src: Path, dst: Path, batches: list[str]) -> int:
    manifest = read_manifest(src)
    print(f"frozen originals : {src}")
    print(f"working copies   : {dst}\n")
    print(f"{'batch':<10} {'original':<38} {'frozen':<7} {'manifest':<9} {'working copy'}")
    for b in batches:
        p = find_export(src, b)
        if p is None:
            print(f"{b:<10} {'(no export)':<38}")
            continue
        c = dst / export_name(b)
        copy_state = "—"
        if c.exists():
            same = sha256(c) == sha256(p)
            copy_state = "same as original" if same else f"EDITED ({datetime.fromtimestamp(c.stat().st_mtime):%Y-%m-%d %H:%M})"
        print(f"{b:<10} {p.name:<38} {'yes' if is_frozen(p) else 'NO':<7} "
              f"{'yes' if p.name in manifest else 'no':<9} {copy_state}")
    return 0


def cmd_verify(src: Path) -> int:
    manifest = read_manifest(src)
    if not manifest:
        print(f"no {MANIFEST_NAME} yet — run --freeze first.")
        return 1
    bad = []
    for name, digest in manifest.items():
        p = src / name
        if not p.exists():
            bad.append((name, "MISSING"))
        elif sha256(p) != digest:
            bad.append((name, "CHANGED"))
    for name, why in bad:
        print(f"  ✗ {why}: {name}")
    print(f"verified {len(manifest)} frozen export(s), {len(bad)} problem(s).")
    return 1 if bad else 0


def cmd_freeze(src: Path, batches: list[str]) -> int:
    manifest = read_manifest(src)
    for b in batches:
        p = find_export(src, b)
        if p is None:
            print(f"  ✗ {b}: no export found in {src}")
            continue
        manifest[p.name] = sha256(p)
        os.chmod(p, 0o444)
        print(f"  ✓ frozen {p.name}  ({p.stat().st_size/1e6:.1f} MB)")
    write_manifest(src, manifest)
    print(f"manifest: {src/MANIFEST_NAME} ({len(manifest)} entries)")
    return 0


def cmd_copy(src: Path, dst: Path, batches: list[str], force: bool) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    for b in batches:
        p = find_export(src, b)
        if p is None:
            print(f"  ✗ {b}: no export found in {src}")
            continue
        target = dst / export_name(b)
        if target.exists() and not force:
            same = sha256(target) == sha256(p)
            print(f"  · {b}: working copy already exists"
                  f"{' (identical to original)' if same else ' WITH EDITS — use --force to discard them'}")
            continue
        if target.exists():
            backup = target.with_suffix(f".PRE_REFRESH_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
            shutil.move(target, backup)
            print(f"    kept your edited copy as {backup.name}")
        shutil.copy2(p, target)
        os.chmod(target, 0o644)          # the copy is the writable one
        print(f"  ✓ {b}: {p.name} -> {target.name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show freeze/copy state per batch")
    ap.add_argument("--verify", action="store_true", help="re-hash the frozen exports against the manifest")
    ap.add_argument("--freeze", nargs="+", metavar="BATCH", help="chmod 444 + manifest these batches")
    ap.add_argument("--copy", nargs="+", metavar="BATCH", help="create/refresh editable working copies")
    ap.add_argument("--force", action="store_true", help="with --copy: replace an edited copy (backed up first)")
    a = ap.parse_args()

    cfg = load_config()
    src = Path(cfg["paths"]["html_review_exports"])
    dst = Path(cfg["paths"].get("corrected_wizard_exports",
                                Path(cfg["paths"]["data"]) / "03c_CORRECTED_wizard_exports"))
    known = sorted({p.stem.removeprefix("reviewed_patents_").strip().split(".")[0]
                    for p in src.glob("reviewed_patents_*.xlsx")})

    if a.freeze:
        return cmd_freeze(src, a.freeze)
    if a.copy:
        return cmd_copy(src, dst, a.copy, a.force)
    if a.verify:
        return cmd_verify(src)
    return cmd_status(src, dst, known)


if __name__ == "__main__":
    raise SystemExit(main())
