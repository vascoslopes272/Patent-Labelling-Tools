"""
extractor.py — Patent drawing downloader and description parser.

Supports two source modes (set in config.yaml → extractor.mode):

  "google_patents"  (default / no credentials needed)
      Downloads drawing images and BRIEF DESCRIPTION from Google Patents.
      Free, no registration, works immediately.
      Use this while waiting for EPO OPS account approval.

  "epo"
      Uses the EPO Open Patent Services REST API.
      Requires free credentials from https://developers.epo.org/
      Set EPO_CLIENT_KEY and EPO_CLIENT_SECRET in .env once approved.

Public API
----------
build_epo_client(cfg)                               → EpoClient  (mode="epo" only)
download_drawings(patent_id, cfg, raw_dir, client)  → list[Path]
get_brief_description(patent_id, cfg, client)       → str
load_patseer_excel(path)                            → dict[str, dict]
save_description_text(patent_id, text, text_dir)    → Path
"""

import io
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from PIL import Image


# ─── EPO OPS constants ────────────────────────────────────────────────────────

_TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"
_BASE_URL  = "http://ops.epo.org/3.2/rest-services"
_OPS_NS    = "http://www.epo.org/exchange-ops"


# ─── EPO OPS client ───────────────────────────────────────────────────────────

class EpoClient:
    """
    Thin REST client for EPO OPS with automatic OAuth2 token refresh.

    Credentials are read from config (cfg["epo"]["client_key"] /
    cfg["epo"]["client_secret"]) with fallback to environment variables
    EPO_CLIENT_KEY and EPO_CLIENT_SECRET (loaded from .env by build_epo_client).
    """

    _TOKEN_LIFETIME = 1080   # refresh after 18 min (tokens expire at 20 min)

    def __init__(self, cfg: dict):
        self._cfg      = cfg
        self._token: str | None = None
        self._token_ts = 0.0

    def _key(self) -> str:
        return (
            self._cfg.get("epo", {}).get("client_key", "")
            or os.environ.get("EPO_CLIENT_KEY", "")
        )

    def _secret(self) -> str:
        return (
            self._cfg.get("epo", {}).get("client_secret", "")
            or os.environ.get("EPO_CLIENT_SECRET", "")
        )

    def _ensure_token(self) -> None:
        if self._token and (time.time() - self._token_ts) < self._TOKEN_LIFETIME:
            return
        key, secret = self._key(), self._secret()
        if not key or not secret:
            raise RuntimeError(
                "EPO OPS credentials not found.\n"
                "Set EPO_CLIENT_KEY and EPO_CLIENT_SECRET in the .env file.\n"
                "Register a free app at https://developers.epo.org/"
            )
        resp = requests.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(key, secret),
            timeout=30,
        )
        resp.raise_for_status()
        self._token    = resp.json()["access_token"]
        self._token_ts = time.time()
        print("  EPO OPS token acquired.")

    def get(self, path: str, accept: str = "application/xml", **kwargs) -> requests.Response:
        """Authenticated GET against the EPO OPS REST API."""
        self._ensure_token()
        url  = f"{_BASE_URL}/{path.lstrip('/')}"
        hdrs = {"Authorization": f"Bearer {self._token}", "Accept": accept}
        resp = requests.get(url, headers=hdrs,
                            timeout=self._cfg.get("epo", {}).get("timeout_seconds", 60),
                            **kwargs)
        if resp.status_code == 401:
            # Token may have expired mid-run — refresh once and retry.
            self._token = None
            self._ensure_token()
            hdrs["Authorization"] = f"Bearer {self._token}"
            resp = requests.get(url, headers=hdrs,
                                timeout=self._cfg.get("epo", {}).get("timeout_seconds", 60),
                                **kwargs)
        resp.raise_for_status()
        return resp


def build_epo_client(cfg: dict) -> "EpoClient":
    """
    Construct and warm-up the EPO client.
    Loads .env credentials and verifies they work before returning.
    """
    from dotenv import load_dotenv
    load_dotenv()
    client = EpoClient(cfg)
    client._ensure_token()   # fail fast if credentials are missing or wrong
    return client


# ─── Drawing images ───────────────────────────────────────────────────────────

def _drawing_page_count(patent_id: str, client: EpoClient) -> int:
    """Return the number of drawing pages available for this patent."""
    try:
        resp = client.get(f"published-data/publication/epodoc/{patent_id}/images")
        root = ET.fromstring(resp.text)
        for inst in root.iter(f"{{{_OPS_NS}}}document-instance"):
            if inst.attrib.get("desc", "").lower() == "drawing":
                return int(inst.attrib.get("number-of-pages", 0))
    except Exception as exc:
        print(f"  ⚠  Could not get image count for {patent_id}: {exc}")
    return 0


def _download_drawings_epo(
    patent_id: str,
    cfg: dict,
    raw_dir: Path,
    client: "EpoClient",
) -> list[Path]:
    """
    Download all drawing pages for a patent from EPO OPS.

    Each page is fetched as TIFF and saved as PNG:
        raw_dir / {patent_id} / fig_{page:02d}.png

    Skips patents whose folder already contains downloaded files.
    Returns list of saved Paths (empty if no drawings found).
    """
    patent_dir = raw_dir / patent_id
    patent_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(patent_dir.glob("fig_*.png"))
    if existing:
        print(f"  Already downloaded {len(existing)} image(s) — skipping")
        return existing

    n_pages = _drawing_page_count(patent_id, client)
    if n_pages == 0:
        print(f"  No drawing pages found for {patent_id}")
        return []

    print(f"  Drawing pages: {n_pages}")
    saved: list[Path] = []
    delay = cfg.get("extractor", {}).get("delay_seconds", 1.0)

    for page in range(1, n_pages + 1):
        dest = patent_dir / f"fig_{page:02d}.png"
        try:
            resp = client.get(
                f"published-data/publication/epodoc/{patent_id}/images/Drawing/{page}",
                accept="image/tiff",
            )
            img = Image.open(io.BytesIO(resp.content))
            img.save(dest, "PNG")
            print(f"      ✓ {dest.name}  ({len(resp.content) // 1024} kB)")
            saved.append(dest)
        except Exception as exc:
            print(f"      ✗ fig_{page:02d}: {exc}")
        time.sleep(delay)

    return saved


# ─── Full-text description ────────────────────────────────────────────────────

_BRIEF_DESC_RE = re.compile(
    r"BRIEF\s+DESCRIPTIONS?\s+OF\s+(THE\s+)?DRAWINGS?",
    re.IGNORECASE,
)


def _parse_brief_description(xml_text: str) -> str:
    """
    Parse EPO OPS description XML and return the BRIEF DESCRIPTION OF THE
    DRAWINGS section as plain text.

    Collects all <p>/<li> elements between the BRIEF DESCRIPTION <heading>
    and the next <heading> element.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""

    collecting = False
    lines: list[str] = []

    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()   # strip namespace prefix

        if tag == "heading":
            heading_text = " ".join("".join(el.itertext()).split())
            if _BRIEF_DESC_RE.search(heading_text):
                collecting = True
                continue
            elif collecting:
                break   # reached the next heading — done

        if collecting and tag in ("p", "li"):
            text = " ".join("".join(el.itertext()).split())
            if text:
                lines.append(text)

    return "\n".join(lines)


def _get_brief_description_epo(patent_id: str, client: "EpoClient") -> str:
    """
    Fetch the full-text description from EPO OPS and return the
    'BRIEF DESCRIPTION OF THE DRAWINGS' section as plain text.

    Returns empty string if the section is not found or the request fails.
    """
    try:
        resp = client.get(
            f"published-data/publication/epodoc/{patent_id}/description"
        )
        text = _parse_brief_description(resp.text)
        if text:
            return text
        print(f"  ⚠  BRIEF DESCRIPTION section not found in EPO text for {patent_id}")
    except Exception as exc:
        print(f"  ⚠  Full-text fetch failed for {patent_id}: {exc}")
    return ""


# ─── Excel metadata (patent ID list + T1 metadata) ────────────────────────────

_DRAWING_DESC_COLS = [
    "Description of Drawings",
    "Brief Description of Drawings",
    "Brief Description",
    "Drawing Description",
    "Drawing Descriptions",
]


def load_patseer_excel(path: Path) -> dict[str, dict]:
    """
    Read the PatSeer Excel export and index rows by Record Number.

    Used to obtain the ordered list of patent IDs and T1 metadata fields
    (title, assignee, pub/app year, abstract, citations) plus the Brief
    Description of the Drawings text (column "Description of Drawings" or
    common variants), stored as "description_of_drawings" in each entry.

    Prints all column headers on first load so column names can be verified.
    """
    import pandas as pd
    df = pd.read_excel(path, dtype=str)

    print(f"PatSeer Excel: {Path(path).name}  ({len(df)} rows, {len(df.columns)} columns)")
    print("Columns:")
    for i, col in enumerate(df.columns):
        print(f"  [{i:3d}] {col!r}")
    print()

    # Locate the drawings-description column once, before the row loop
    desc_col = next((c for c in _DRAWING_DESC_COLS if c in df.columns), None)
    if desc_col:
        print(f"  Description of Drawings column : {desc_col!r}")
    else:
        print("  ⚠  No 'Description of Drawings' column found in Excel.")
    print()

    index: dict[str, dict] = {}

    for _, row in df.iterrows():
        patent_id = str(row.get("Record Number", "")).strip()
        if not patent_id or patent_id == "nan":
            continue

        def _s(col: str) -> str:
            v = str(row.get(col, "")).strip()
            return "" if v == "nan" else v

        def _year(col: str) -> str | None:
            v = _s(col)
            return v[:4] if v else None

        def _cites(col: str) -> list[str]:
            v = _s(col)
            return [c.strip() for c in v.split(",") if c.strip()] if v else []

        index[patent_id] = {
            "patent_id":               patent_id,
            "record_number":           _s("Record Number"),
            "assignee":                _s("Assignee") or None,
            "pub_year":                _year("Publication/Issue Date"),
            "app_year":                _year("Filing/Application Date"),
            "title":                   _s("Title") or None,
            "abstract":                _s("Abstract") or None,
            "backward_cites":          _cites("Backward Citations"),
            "forward_cites":           _cites("Forward Citations"),
            "innovation_objective":    (
                _s("Summary of Invention") or _s("Advantages of Invention") or None
            ),
            "description_of_drawings": (_s(desc_col) if desc_col else None) or None,
        }

    return index


def save_description_text(patent_id: str, text: str, text_dir: Path) -> Path:
    """Write the BRIEF DESCRIPTION text to text_dir/<patent_id>.txt."""
    text_dir.mkdir(parents=True, exist_ok=True)
    dest = text_dir / f"{patent_id}.txt"
    dest.write_text(text, encoding="utf-8")
    return dest


# ─── Google Patents fallback (no credentials needed) ─────────────────────────

_GP_BASE    = "https://patents.google.com/patent"
_GP_CDN_RE  = re.compile(
    r'https://patentimages\.storage\.googleapis\.com/[^\s"\'<>]+\.png'
)
_GP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
# PatSeer stores US A-series publications with 6-digit sequence numbers,
# but Google Patents requires 7 digits (zero-padded).
# e.g.  US2022267016A1  →  US20220267016A1
_US_PUBNUM_RE = re.compile(r'^(US)(\d{4})(\d{6})(A\d)$')


def _normalize_for_google(patent_id: str) -> str:
    """Pad PatSeer US publication numbers to the format Google Patents expects."""
    m = _US_PUBNUM_RE.match(patent_id)
    if m:
        return f"{m.group(1)}{m.group(2)}0{m.group(3)}{m.group(4)}"
    return patent_id


def _fetch_google_patents(patent_id: str, timeout: int = 30) -> str:
    """Fetch the Google Patents HTML page for a patent. Returns raw HTML."""
    norm = _normalize_for_google(patent_id)
    url  = f"{_GP_BASE}/{norm}/en"
    resp = requests.get(url, headers=_GP_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def download_drawings_google(patent_id: str, cfg: dict, raw_dir: Path) -> list[Path]:
    """
    Download drawing images from the Google Patents public CDN.

    No credentials required. Each drawing page is saved as:
        raw_dir / {patent_id} / fig_{n:02d}.png

    Google Patents serves each drawing at two CDN paths (thumbnail + full).
    We deduplicate by filename (the D000XX part) and keep one URL per page.
    """
    patent_dir = raw_dir / patent_id
    patent_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(patent_dir.glob("fig_*.png"))
    if existing:
        print(f"  Already downloaded {len(existing)} image(s) — skipping")
        return existing

    try:
        html = _fetch_google_patents(patent_id)
    except Exception as exc:
        print(f"  ⚠  Google Patents fetch failed for {patent_id}: {exc}")
        return []

    # Google Patents serves each drawing twice: thumbnail first, full-size second.
    # Deduplicate by filename (D000XX part), keeping the LAST URL = full-size.
    all_urls = _GP_CDN_RE.findall(html)
    seen_names: dict[str, str] = {}
    for url in all_urls:
        fname = url.rsplit("/", 1)[-1]
        seen_names[fname] = url   # overwrite → last one wins (full-size)

    # Sort by drawing number (D00000, D00001, …)
    ordered = sorted(seen_names.items(), key=lambda kv: kv[0])

    if not ordered:
        print(f"  ⚠  No drawing images found on Google Patents for {patent_id}")
        return []

    print(f"  Drawing pages: {len(ordered)}")
    saved: list[Path] = []
    delay = cfg.get("extractor", {}).get("delay_seconds", 1.0)

    for i, (fname, url) in enumerate(ordered, start=1):
        dest = patent_dir / f"fig_{i:02d}.png"
        try:
            r = requests.get(url, headers=_GP_HEADERS, timeout=30)
            r.raise_for_status()
            dest.write_bytes(r.content)
            print(f"      ✓ {dest.name}  ({len(r.content) // 1024} kB)")
            saved.append(dest)
        except Exception as exc:
            print(f"      ✗ fig_{i:02d}: {exc}")
        time.sleep(delay)

    return saved


def get_brief_description_google(patent_id: str, cfg: dict) -> str:
    """
    Scrape the BRIEF DESCRIPTION OF THE DRAWINGS from the Google Patents page.

    Google Patents wraps this section in a <description-of-drawings> tag
    with <div class="description-paragraph"> children.
    """
    try:
        html = _fetch_google_patents(patent_id)
    except Exception as exc:
        print(f"  ⚠  Google Patents fetch failed for {patent_id}: {exc}")
        return ""

    # Extract the <description-of-drawings>…</description-of-drawings> block
    block_m = re.search(
        r"<description-of-drawings[^>]*>(.*?)</description-of-drawings>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not block_m:
        print(f"  ⚠  No <description-of-drawings> block found for {patent_id}")
        return ""

    block = block_m.group(1)

    # Extract text from <div class="description-paragraph"> or "description-line"
    paras = re.findall(
        r'<div[^>]*class="description-(?:paragraph|line)"[^>]*>(.*?)</div>',
        block,
        re.IGNORECASE | re.DOTALL,
    )
    lines = []
    for p in paras:
        text = re.sub(r"<[^>]+>", " ", p)          # strip inner tags
        text = " ".join(text.split()).strip()        # normalise whitespace
        if text:
            lines.append(text)

    if not lines:
        print(f"  ⚠  Description-of-drawings block is empty for {patent_id}")

    return "\n".join(lines)


# ─── Unified public API (mode-aware routers) ──────────────────────────────────

def download_drawings(
    patent_id: str,
    cfg: dict,
    raw_dir: Path,
    client=None,          # EpoClient — required only when mode="epo"
) -> list[Path]:
    """
    Download drawing images for one patent.

    Dispatches to the correct backend based on cfg["extractor"]["mode"]:
      "google_patents"  — free, no credentials (default)
      "epo"             — EPO OPS API (requires EpoClient)
    """
    mode = cfg.get("extractor", {}).get("mode", "google_patents")
    if mode == "epo":
        return _download_drawings_epo(patent_id, cfg, raw_dir, client)
    return download_drawings_google(patent_id, cfg, raw_dir)


def get_brief_description(
    patent_id: str,
    cfg: dict,
    client=None,          # EpoClient — required only when mode="epo"
) -> str:
    """
    Fetch the BRIEF DESCRIPTION OF THE DRAWINGS for one patent.

    Dispatches to the correct backend based on cfg["extractor"]["mode"].
    """
    mode = cfg.get("extractor", {}).get("mode", "google_patents")
    if mode == "epo":
        return _get_brief_description_epo(patent_id, client)
    return get_brief_description_google(patent_id, cfg)
