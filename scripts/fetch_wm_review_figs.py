#!/usr/bin/env python3
"""Fetch a few drawings per family for the crewed-multicopter review page.

Google Patents drawing PNGs when the page has them (first 4 sheets); otherwise
the publication PDF, rendered with pdftoppm: page 1 (CN/US front page carries the
abstract figure) and the last 3 pages (CN drawings sit at the end).
Writes figs/<record>/NN.jpg next to the page and figs/index.json.
"""
import io, json, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from PIL import Image

OUT_DIR = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/EVTOLNEWS_DS/3_embedding_evaluation/wm_gap_check")
FIGS = OUT_DIR / "figs"
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
PNG = re.compile(r'https://patentimages\.storage\.googleapis\.com/[^\s"\'<>]+\.png')
PDF = re.compile(r'https://patentimages\.storage\.googleapis\.com/[^\s"\'<>]+\.pdf')
US = re.compile(r'^(US)(\d{4})(\d{6})(A\d)$')
MAXW = 900


def norm(pn):
    m = US.match(pn)
    return f"{m[1]}{m[2]}0{m[3]}{m[4]}" if m else pn


def save_jpg(img: Image.Image, dest: Path):
    img = img.convert("L")
    if img.width > MAXW:
        img = img.resize((MAXW, round(img.height * MAXW / img.width)))
    img.save(dest, "JPEG", quality=80)


def fetch(rec):
    d = FIGS / rec
    have = sorted(d.glob("*.jpg"))
    if have:
        return rec, [f"figs/{rec}/{p.name}" for p in have], "cached"
    try:
        r = requests.get(f"https://patents.google.com/patent/{norm(rec)}/en", headers=H, timeout=30)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        return rec, [], f"page error {e.__class__.__name__}"
    d.mkdir(parents=True, exist_ok=True)
    pngs = {}
    for u in PNG.findall(html):
        pngs[u.rsplit("/", 1)[-1]] = u          # last = full size
    out = []
    if pngs:
        for i, (_, u) in enumerate(sorted(pngs.items())[:4]):
            try:
                b = requests.get(u, headers=H, timeout=30).content
                save_jpg(Image.open(io.BytesIO(b)), d / f"{i:02d}.jpg")
                out.append(f"figs/{rec}/{i:02d}.jpg")
            except Exception:
                pass
        return rec, out, "png"
    pdfs = PDF.findall(html)
    if not pdfs:
        return rec, [], "no images"
    try:
        b = requests.get(pdfs[0], headers=H, timeout=60).content
        with tempfile.TemporaryDirectory() as t:
            pf = Path(t) / "a.pdf"; pf.write_bytes(b)
            info = subprocess.run(["pdfinfo", str(pf)], capture_output=True, text=True).stdout
            n = int(re.search(r"Pages:\s+(\d+)", info)[1])
            pages = sorted({1, *range(max(2, n - 2), n + 1)})
            for k, pg in enumerate(pages):
                subprocess.run(["pdftoppm", "-r", "70", "-f", str(pg), "-l", str(pg), "-png", str(pf), f"{t}/p{k}"], check=True)
                png = next(Path(t).glob(f"p{k}*.png"))
                save_jpg(Image.open(png), d / f"{k:02d}.jpg")
                out.append(f"figs/{rec}/{k:02d}.jpg")
        return rec, out, f"pdf pages {pages} of {n}"
    except Exception as e:
        return rec, out, f"pdf error {e.__class__.__name__}"


if __name__ == "__main__":
    recs = json.loads(sys.stdin.read())
    FIGS.mkdir(parents=True, exist_ok=True)
    idx_path = FIGS / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    with ThreadPoolExecutor(6) as ex:
        for i, (rec, imgs, how) in enumerate(ex.map(fetch, [r for r in recs if not idx.get(r)]), 1):
            idx[rec] = imgs
            if i % 25 == 0 or not imgs:
                print(f"{i}: {rec} {len(imgs)} imgs ({how})", flush=True)
    idx_path.write_text(json.dumps(idx, indent=0))
    print("with images:", sum(1 for r in recs if idx.get(r)), "of", len(recs))
