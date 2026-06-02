"""
extractor.py — PatSeer Selenium downloader and Excel metadata reader.

Images are saved to paths.raw_images/<patent_id>/fig_XX.png.
Description text is saved to paths.text/<patent_id>.txt.

Public API
----------
build_driver(cfg)                           → webdriver.Chrome
login_flow(driver, cfg)                     → None
make_requests_session(driver)               → requests.Session
iter_records(driver, cfg, start, limit)     → Iterator[int]
extract_drawings_for_record(driver, wait, idx) → tuple[str, list[str]]
download_images(urls, patent_id, session, raw_dir) → int
load_patseer_excel(path)                    → dict[str, dict]
save_description_text(patent_id, row, text_dir) → Path

Notes
-----
PatSeer's ToS may restrict automated access. Only run with a licensed
subscription. The manual-login flow (headless=false) is the recommended
approach to avoid bot-detection.
"""

import re
import time
from pathlib import Path

import pandas as pd
import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# ─── Driver setup ──────────────────────────────────────────────────────────────

def build_driver(cfg: dict) -> webdriver.Chrome:
    """Build a Chrome WebDriver from extractor config."""
    ext = cfg["extractor"]
    options = webdriver.ChromeOptions()
    if ext.get("headless", False):
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,900")
    else:
        options.add_argument("--start-maximized")

    profile_dir = ext.get("chrome_profile_dir", "")
    if profile_dir:
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument(f"--profile-directory={ext.get('chrome_profile', 'Default')}")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def login_flow(driver: webdriver.Chrome, cfg: dict) -> None:
    """Navigate to PatSeer and wait for manual login if no Chrome profile is set."""
    driver.get("https://app1.patseer.com")
    if cfg["extractor"].get("chrome_profile_dir", ""):
        print("Using existing Chrome profile — waiting for PatSeer to load…")
        time.sleep(3)
    else:
        print("\n" + "=" * 60)
        print("  Log in to PatSeer in the browser window that just opened.")
        print("  Once fully logged in, come back here and press Enter.")
        print("=" * 60)
        input("  ▶ Press Enter when ready: ")


def make_requests_session(driver: webdriver.Chrome) -> requests.Session:
    """Mirror browser cookies and user-agent into a requests.Session."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": driver.execute_script("return navigator.userAgent"),
        "Referer": "https://app1.patseer.com/",
    })
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"])
    return session


# ─── Record iteration ──────────────────────────────────────────────────────────

def iter_records(
    driver: webdriver.Chrome,
    cfg: dict,
    start: int = 1,
    limit: int | None = None,
):
    """
    Yield record indices one by one, navigating to each PatSeer record URL.

    Parameters
    ----------
    start : first record index (1-based)
    limit : stop after this many records; None = process all total_records
    """
    ext = cfg["extractor"]
    base_url = ext["search_base_url"]
    total = ext["total_records"]
    stop = min(start + limit - 1, total) if limit else total
    delay = ext.get("delay_seconds", 2.5)

    for idx in range(start, stop + 1):
        record_url = f"{base_url}/{idx}"
        print(f"\n[{idx:3d}/{stop}] {record_url}")
        driver.get(record_url)
        time.sleep(2.2)
        yield idx
        time.sleep(delay)


def extract_patent_number(driver: webdriver.Chrome, record_idx: int) -> str:
    """
    Read the patent publication number from the PatSeer record panel.
    Falls back to 'record_{idx:04d}' if nothing is parseable.
    """
    try:
        selectors = [
            "[class*='record-title']",
            "[class*='recordTitle']",
            "[class*='record-head']",
            "[class*='patent-number']",
            "h2", "h3",
        ]
        for sel in selectors:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                text = el.text.strip()
                m = re.search(r"([A-Z]{2}\d{6,}[A-Z0-9]*)", text)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return f"record_{record_idx:04d}"


def click_drawings_tab(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """Click the Drawings tab in the right-hand record panel."""
    try:
        tab = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//*[self::a or self::li or self::button or self::span]"
            "[normalize-space(.)='Drawings']"
        )))
        driver.execute_script("arguments[0].scrollIntoView(true);", tab)
        driver.execute_script("arguments[0].click();", tab)
        time.sleep(1.8)
        return True
    except TimeoutException:
        return False


def collect_image_urls(driver: webdriver.Chrome) -> list[str]:
    """
    Collect all drawing image URLs visible after clicking the Drawings tab.
    Tries multiple CSS selectors; strips thumbnail size parameters.
    """
    time.sleep(2)

    css_candidates = [
        "div[class*='drawing'] img",
        "div[class*='Drawing'] img",
        "div[class*='drawings'] img",
        "div[class*='Drawings'] img",
        ".drawings-panel img",
        ".thumbnails img",
        "figure img",
        "img[class*='drawing']",
        "img[class*='thumbnail']",
    ]

    seen: set[str] = set()
    urls: list[str] = []

    for css in css_candidates:
        for img in driver.find_elements(By.CSS_SELECTOR, css):
            src = (img.get_attribute("src") or
                   img.get_attribute("data-src") or
                   img.get_attribute("data-original") or "")
            if not src.startswith("http"):
                continue
            full = re.sub(r"[?&](size|thumb|thumbnail|w|h|width|height)=[^&]*", "", src)
            full = full.rstrip("?&")
            if full not in seen:
                seen.add(full)
                urls.append(full)

    return urls


def extract_drawings_for_record(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    record_idx: int,
) -> tuple[str, list[str]]:
    """
    Extract patent number and image URLs for the currently-loaded record.

    Returns
    -------
    (patent_id, image_urls) — image_urls is empty if no drawings found.
    """
    patent_id = extract_patent_number(driver, record_idx)
    print(f"  Patent : {patent_id}")

    if not click_drawings_tab(driver, wait):
        print("  ⚠  Drawings tab not found — no drawings for this record?")
        return patent_id, []

    urls = collect_image_urls(driver)
    print(f"  Images : {len(urls)} found")

    if not urls:
        print("  ⚠  No image URLs collected.")
        print("     Tip: open DevTools → Network → filter 'Img' to inspect URLs manually.")

    return patent_id, urls


def download_images(
    urls: list[str],
    patent_id: str,
    session: requests.Session,
    raw_dir: Path,
) -> int:
    """
    Download image URLs into raw_dir/patent_id/fig_XX.<ext>.

    Returns the number of images successfully saved.
    """
    dest_dir = raw_dir / patent_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = 0

    for i, url in enumerate(urls, start=1):
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            ext = "jpg" if "jpeg" in ct else ("gif" if "gif" in ct else "png")
            dest = dest_dir / f"fig_{i:02d}.{ext}"
            if dest.exists():
                print(f"      {dest.name} – already exists, skipping")
                saved += 1
                continue
            dest.write_bytes(r.content)
            print(f"      ✓ {dest.name}  ({len(r.content) // 1024} kB)")
            saved += 1
        except Exception as exc:
            print(f"      ✗ fig_{i:02d}: {exc}")

    return saved


# ─── Excel metadata ────────────────────────────────────────────────────────────

def load_patseer_excel(path: Path) -> dict[str, dict]:
    """
    Read the PatSeer Excel export and index rows by patent ID (Record Number).

    Prints column headers on first load so you can verify column names.

    Returns
    -------
    dict mapping patent_id → {
        patent_id, record_number, assignee, pub_year, app_year,
        title, abstract, backward_cites, forward_cites,
        innovation_objective, description_of_drawings
    }
    """
    df = pd.read_excel(path, dtype=str)

    print(f"PatSeer Excel: {Path(path).name}  ({len(df)} rows, {len(df.columns)} columns)")
    print("Columns:")
    for i, col in enumerate(df.columns):
        print(f"  [{i:3d}] {col!r}")
    print()

    index: dict[str, dict] = {}

    for _, row in df.iterrows():
        patent_id = str(row.get("Record Number", "")).strip()
        if not patent_id or patent_id == "nan":
            continue

        def _s(col: str, default: str = "") -> str:
            v = str(row.get(col, default)).strip()
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
            "innovation_objective":    _s("Summary of Invention") or _s("Advantages of Invention") or None,
            "description_of_drawings": _s("Description of Drawings") or None,
        }

    return index


def save_description_text(patent_id: str, row: dict, text_dir: Path) -> Path:
    """Write 'description_of_drawings' to text_dir/<patent_id>.txt."""
    text_dir.mkdir(parents=True, exist_ok=True)
    dest = text_dir / f"{patent_id}.txt"
    dest.write_text(row.get("description_of_drawings") or "", encoding="utf-8")
    return dest
