"""
PatSeer Drawing Downloader
==========================
Iterates through every record in a PatSeer search and downloads all drawing
images for each patent into an organised folder.

IMPORTANT
---------
PatSeer's Terms of Service may restrict automated web access. Using the
built-in PDF Cart / Bulk Download is the officially supported bulk route.
Only run this script if you have a legitimate licensed subscription and
understand the ToS implications.

REQUIREMENTS
------------
    pip install selenium webdriver-manager requests

HOW TO RUN
----------
1. Set the configuration block below (SEARCH_BASE_URL, TOTAL_RECORDS, etc.)
2. Run:  python patseer_downloader.py
3. A browser window will open – log in to PatSeer when prompted, then press
   Enter in the terminal.  The script will then process all records.

TIP: To skip the manual-login step on future runs, set CHROME_PROFILE_DIR to
your Chrome profile directory (see the comment below).
"""

import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# ─── CONFIGURATION ─────────────────────────────────────────────────────────────

# Paste your search URL from the browser (only the base part – no record number)
SEARCH_BASE_URL = "https://app1.patseer.com/#/result/ad056431-8522-11e8-944f-22000bd445e0"

TOTAL_RECORDS      = 1639    # total records in your search result
START_FROM         = 1     # change this to resume a previous run
LOGIN_WAIT_SECONDS = 35    # seconds to log in and navigate to search before script takes over

OUTPUT_DIR    = Path("patseer_drawings")   # overridden by notebook Cell 1 via cfg["paths"]["raw_images"]
EXCEL_PATH    = Path("")   # overridden by notebook Cell 1; used to resolve record_ folder names from Excel row
DELAY_SECS    = 1.5      # pause between patents – keep this ≥ 1 to avoid hammering the server
HEADLESS      = False    # set True to run without a visible browser window

# ── Optional: reuse an existing Chrome session so you skip the login prompt.
# Find your profile path at  chrome://version/  →  "Profile Path"
#   Windows example : r"C:\Users\YourName\AppData\Local\Google\Chrome\User Data"
#   Linux example   : "/home/yourname/.config/google-chrome"
#   Mac example     : "/Users/yourname/Library/Application Support/Google/Chrome"
CHROME_PROFILE_DIR = "/home/vasco/.config/google-chrome"
CHROME_PROFILE     = "Default"   # vasco.lopes@tecnico.ulisboa.pt

# ───────────────────────────────────────────────────────────────────────────────


# ─── Filename cleaning ────────────────────────────────────────────────────────

_PUB_DATE_RE = re.compile(r"-(\d{4})(\d{2})(\d{2})-")


def clean_filename(raw_name: str, patent_id: str) -> str:
    """
    Clean a raw PatSeer filename into the canonical pipeline format.

    Transformations (in order):
      1. Strip record_NNNN_ prefix          record_0002_US…A1-…-img003.png
      2. Collapse -YYYYMMDD- date segment   → US…A1-img003.png
      3. Replace remaining hyphens with _   → US…A1_img003.png

    The patent_id parameter is accepted for API symmetry; the ID is
    already embedded in the raw filename so no substitution is needed.
    """
    name = re.sub(r"^record_\d+_", "", raw_name)   # strip record prefix
    name = re.sub(r"-\d{8}-", "-", name)             # collapse date segment
    name = name.replace("-", "_")                    # normalise separator
    return name


def _extract_pub_date(raw_name: str) -> str | None:
    """Extract publication date from a raw PatSeer filename as YYYY-MM-DD."""
    m = _PUB_DATE_RE.search(raw_name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _patent_id_from_urls(urls: list[str]) -> str | None:
    """Extract the patent publication number from collected image URLs.

    PatSeer CDN paths embed the original filename, which always contains the
    patent number (e.g. …/record_0001_US20220267016A1-20220825-D00001.png).
    This is far more reliable than scraping the DOM.
    """
    pat = re.compile(r"([A-Z]{2}\d{6,}[A-Z0-9]+)", re.IGNORECASE)
    for url in urls:
        path = unquote(urlparse(url).path)
        m = pat.search(path)
        if m:
            return m.group(1).upper()
    return None


def _lookup_patent_id_from_excel(record_position: int, excel_path: Path) -> str | None:
    """Look up the patent ID in the PatSeer Excel export by record position.

    record_position stored in the manifest is 1-based (record 1 = first patent =
    Excel data row 0 in zero-based df indexing).  Returns None if the Excel is not
    found or the row index is out of range.
    """
    if not excel_path or not excel_path.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_excel(excel_path, usecols=[0])   # only the first column (Record Number)
        row_idx = record_position - 1
        if 0 <= row_idx < len(df):
            val = str(df.iloc[row_idx, 0]).strip()
            if val and val.lower() not in ("nan", "none", ""):
                return val
    except Exception:
        pass
    return None


def _fix_record_folder(record_dir: Path, out_dir: Path,
                       excel_path: Path | None = None) -> str | None:
    """After downloading into a record_XXXX folder, find the real patent ID and
    rename all files + the folder + manifest accordingly.

    ID resolution order:
      1. Excel lookup via record_position stored in the manifest (most reliable —
         the filenames are only fig_NN.png so the ID is not embedded in them).
      2. Regex scan of filenames for an embedded patent number (fallback for
         patents whose filenames do carry the number).

    Returns the new patent_id on success, None if it can't be determined.
    """
    if not record_dir.exists():
        return None

    patent_id = None

    # ── Strategy 1: look up record_position in the Excel ─────────────────────
    manifest_candidates = list(record_dir.glob("*manifest*.json"))
    if manifest_candidates and excel_path:
        try:
            data = json.loads(manifest_candidates[0].read_text())
            rec_pos = data.get("record_position")
            if rec_pos:
                patent_id = _lookup_patent_id_from_excel(int(rec_pos), excel_path)
                if patent_id:
                    print(f"  Patent : {patent_id}  (from Excel row {rec_pos})")
        except Exception:
            pass

    # ── Strategy 2: regex scan of filenames ──────────────────────────────────
    if not patent_id:
        pat = re.compile(r"([A-Z]{2}\d{6,}[A-Z0-9]+)", re.IGNORECASE)
        for f in record_dir.iterdir():
            m = pat.search(f.stem)
            if m:
                candidate = m.group(1).upper()
                if not candidate.upper().startswith("RECORD"):
                    patent_id = candidate
                    print(f"  Patent : {patent_id}  (from filename scan)")
                    break

    if not patent_id:
        return None

    new_dir = out_dir / patent_id
    if new_dir.exists():
        print(f"  ⚠  Cannot rename: {patent_id}/ already exists")
        return None

    record_name = record_dir.name   # "record_0003"
    prefix      = record_name + "_"

    # Rename files: manifest gets a new name, all others lose the record_XXXX_ prefix
    for f in list(record_dir.iterdir()):
        if f.name == f"{record_name}_download_manifest.json":
            f.rename(record_dir / f"{patent_id}_download_manifest.json")
        elif f.name.startswith(prefix):
            f.rename(record_dir / f.name[len(prefix):])

    # Update manifest content
    manifest_path = record_dir / f"{patent_id}_download_manifest.json"
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text())
        data["patent_id"] = patent_id

        def _fix(n: str) -> str:
            return n[len(prefix):] if n.startswith(prefix) else n

        data["img_files"] = [_fix(n) for n in data.get("img_files", [])]
        data["d_files"]   = [_fix(n) for n in data.get("d_files", [])]
        data["fat_files"] = [_fix(n) for n in data.get("fat_files", [])]
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Finally rename the folder itself
    record_dir.rename(new_dir)
    return patent_id


def _url_matches_type_filter(url: str, file_type_filter: str) -> bool:
    """
    Heuristic check: does a PatSeer image URL belong to the requested type?
    PatSeer embeds the original filename in the URL path, so we inspect the
    path segment.  Returns True for "all" or when the URL cannot be classified.
    """
    if file_type_filter == "all":
        return True
    path = urlparse(url).path.lower()
    if file_type_filter == "img":
        return bool(re.search(r"[-_]img\d", path))
    if file_type_filter == "D":
        return bool(re.search(r"[-_]d\d{4,}", path))
    if file_type_filter == "FAT":
        return bool(re.search(r"[-_]fat\d", path))
    return True


# ─── Selenium helpers ─────────────────────────────────────────────────────────

def build_driver() -> webdriver.Chrome:
    import os, shutil, subprocess, glob as _glob, tempfile

    # Kill any running Chrome that would lock the profile
    subprocess.run(["pkill", "-f", "/opt/google/chrome/chrome$"],
                   capture_output=True)
    time.sleep(1.5)

    options = webdriver.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,900")
    else:
        options.add_argument("--start-maximized")

    if CHROME_PROFILE_DIR:
        # Copy only the cookies file to a temp profile — using the live profile
        # directly crashes Chrome under Selenium (exit code 144) on Linux because
        # extensions and other profile state are incompatible with the automation driver.
        tmp_dir = tempfile.mkdtemp(prefix="chrome_selenium_")
        src_profile = os.path.join(CHROME_PROFILE_DIR, CHROME_PROFILE)
        tmp_profile  = os.path.join(tmp_dir, CHROME_PROFILE)
        os.makedirs(tmp_profile, exist_ok=True)

        for cookie_file in ("Cookies", "Cookies-journal"):
            src = os.path.join(src_profile, cookie_file)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tmp_profile, cookie_file))

        options.add_argument(f"--user-data-dir={tmp_dir}")
        options.add_argument(f"--profile-directory={CHROME_PROFILE}")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def make_requests_session(driver: webdriver.Chrome) -> requests.Session:
    """Mirror the browser's cookies and user-agent into a requests.Session."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": driver.execute_script("return navigator.userAgent"),
        "Referer": "https://app1.patseer.com/",
    })
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"])
    return session


# Single JS round-trip: same selectors and same priority as before, but the
# browser does the element iteration internally instead of one Selenium HTTP
# call per element (this function is polled every 0.5s while waiting for the
# next-record click, so per-call cost dominates the whole run).
_POS_SCAN_JS = """
const sels = ["[ng-bind*='currentRecord']", "[class*='recordCount']",
              "[class*='record-count']", "[class*='recordNav']",
              "[class*='pager']", "[class*='pagination']"];
const targeted = [], fallback = [];
const visible = el => el.offsetWidth || el.offsetHeight || el.getClientRects().length;
for (const sel of sels) {
    let els;
    try { els = document.querySelectorAll(sel); } catch (e) { continue; }
    for (const el of els) {
        if (!visible(el)) continue;
        const t = (el.innerText || '').trim();
        if (t) targeted.push(t);
    }
}
// Broad fallback: any short visible text containing '/'
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
let node;
while ((node = walker.nextNode())) {
    const v = node.nodeValue.trim();
    if (v.length > 0 && v.length < 20 && v.includes('/')) {
        const p = node.parentElement;
        if (p && visible(p)) fallback.push(v);
    }
}
return [targeted, fallback];
"""


def read_browser_record_position(driver: webdriver.Chrome) -> int | None:
    """Read the actual current record position from the PatSeer DetailsView UI.

    PatSeer shows "X / Y" in the navigation bar — this is the ground truth.
    Returns the integer position, or None if it cannot be read.
    """
    try:
        targeted, fallback = driver.execute_script(_POS_SCAN_JS)
        for text in targeted:
            m = re.search(r"\b(\d+)\s*[/of]+\s*\d+", text)
            if m:
                return int(m.group(1))
        for text in fallback:
            m = re.search(r"^\s*(\d+)\s*/\s*\d+\s*$", text)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


_PATENT_ID_RE = re.compile(r"([A-Z]{2}\d{6,}[A-Z0-9]*)", re.IGNORECASE)

# Selector that successfully yielded the patent ID on a previous record.
# PatSeer renders the pub number in the same element on every record, so after
# the first hit we query just that one selector — a single tiny JS call instead
# of re-scanning the whole selector list on every poll.
_ID_SELECTOR_CACHE: dict = {"css": None}

# Same selectors and same priority order as before, checked inside ONE
# JavaScript call (one Selenium round-trip instead of one per element).
_ID_CSS_SELECTORS = [
    "[class*='recordInfoContainer'][appnum]",
    "[class*='recordInfoContainer'][recordnum]",
    "[appnum]", "[recordnum]",
    "[class*='record-title']", "[class*='recordTitle']",
    "[class*='record-head']", "[class*='patent-number']",
    "[class*='pubNum']", "[class*='pub-num']",
    "[class*='recordNum']", "[class*='record-num']",
    "[class*='appNum']", "[class*='app-num']",
    "h1", "h2", "h3",
]

_ID_SCAN_JS = """
const sels = arguments[0];
const out = [];
const visible = el => el.offsetWidth || el.offsetHeight || el.getClientRects().length;
for (const sel of sels) {
    let els;
    try { els = document.querySelectorAll(sel); } catch (e) { continue; }
    for (const el of els) {
        const ap = el.getAttribute('appnum');
        if (ap) out.push([sel, ap]);
        const rn = el.getAttribute('recordnum');
        if (rn) out.push([sel, rn]);
        if (!visible(el)) continue;
        const t = (el.textContent || '').trim();
        if (t && t.length < 300) out.push([sel, t]);
        if (out.length > 500) return out;
    }
}
return out;
"""


def extract_patent_number(driver: webdriver.Chrome, record_idx: int) -> str:
    """Read the patent publication number from the DetailsView DOM.

    Tries sources in order of reliability:
      0. The cached selector that worked on a previous record (the pub number
         is always rendered in the same element — one cheap JS call)
      1. HTML attributes on the record container (appnum / recordnum)
      2. Text content of targeted title/heading elements
      3. Page title (document.title)
      4. Current URL hash/path
      5. Broad scan of ALL visible text on the page — catches any element
         PatSeer uses to display the pub number, regardless of class name.
         Scored: elements closer to the top of the DOM rank higher.
    Falls back to 'record_{record_idx}' only if nothing can be parsed.
    """
    def _search(text: str | None) -> str | None:
        m = _PATENT_ID_RE.search(text or "")
        return m.group(1).upper() if m else None

    # ── 0. Cached selector from a previous record ─────────────────────────────
    cached = _ID_SELECTOR_CACHE["css"]
    if cached:
        try:
            for _sel, txt in (driver.execute_script(_ID_SCAN_JS, [cached]) or []):
                found = _search(txt)
                if found:
                    return found
        except Exception:
            pass

    # ── 1+2. Attributes & targeted text elements (one JS round-trip) ─────────
    try:
        for sel, txt in (driver.execute_script(_ID_SCAN_JS, _ID_CSS_SELECTORS) or []):
            found = _search(txt)
            if found:
                _ID_SELECTOR_CACHE["css"] = sel
                return found
    except Exception:
        pass

    # ── 3. Page title ─────────────────────────────────────────────────────────
    try:
        found = _search(driver.title)
        if found:
            return found
    except Exception:
        pass

    # ── 4. Current URL ────────────────────────────────────────────────────────
    try:
        found = _search(driver.current_url)
        if found:
            return found
    except Exception:
        pass

    # ── 5. Broad full-page text scan ──────────────────────────────────────────
    # Walk every element that has direct visible text and collect all patent-ID
    # candidates. The first match from the top of the DOM wins — PatSeer always
    # shows the pub number near the top of the detail panel.
    try:
        candidates = driver.execute_script("""
            var results = [];
            var walker = document.createTreeWalker(
                document.body,
                NodeFilter.SHOW_TEXT,
                null, false
            );
            var node;
            while ((node = walker.nextNode())) {
                var txt = node.nodeValue.trim();
                if (txt.length > 3 && txt.length < 60) {
                    results.push(txt);
                }
            }
            return results;
        """)
        for txt in (candidates or []):
            found = _search(txt)
            if found:
                return found
    except Exception:
        pass

    return f"record_{record_idx:04d}"


def click_next_patent(driver: webdriver.Chrome, timeout: int = 60) -> bool:
    """Click the next-record arrow in DetailsView and wait for the page to change.

    Waits up to `timeout` seconds for the browser position counter to increment.
    A generous default handles slow Wi-Fi / heavy PatSeer pages without skipping
    a record (which would corrupt the record_position → patent ID mapping).
    """
    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "[ng-click*='nextSelectedRecord']"))
        )
        pos_before = read_browser_record_position(driver)
        driver.execute_script("arguments[0].click();", btn)

        if pos_before is not None:
            deadline = time.time() + timeout
            while time.time() < deadline:
                time.sleep(0.3)
                pos_after = read_browser_record_position(driver)
                if pos_after is not None and pos_after != pos_before:
                    return True
            # Timed out — position never changed; log and return False so caller
            # can decide whether to retry rather than silently skipping a record.
            print(f"  ⚠  click_next_patent: position stayed at {pos_before} after {timeout}s")
            return False
        else:
            time.sleep(4.0)   # fallback if position counter is unreadable
        return True
    except Exception:
        return False


def click_drawings_tab(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """Click the 'Drawings' tab in the DetailsView panel."""
    # Broader text variants — PatSeer may localise or abbreviate the label
    tab_texts = ["Drawings", "Drawing", "Figures", "Images", "Patents Drawings"]
    xpath_conditions = " or ".join(
        f"contains(normalize-space(.), '{t}')" for t in tab_texts
    )
    xpath = (
        f"//*[self::a or self::li or self::button or self::span or self::div]"
        f"[{xpath_conditions}]"
        f"[not(descendant::*[self::a or self::button or self::li])]"  # avoid container divs
    )
    try:
        tab = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        driver.execute_script("arguments[0].scrollIntoView(true);", tab)
        driver.execute_script("arguments[0].click();", tab)
        # Poll until the drawing panel has at least one img, up to 8s.
        # Falls back to a 1s minimum so the DOM has time to start rendering.
        deadline = time.time() + 8
        while time.time() < deadline:
            time.sleep(0.4)
            try:
                if driver.execute_script(_DRAWINGS_READY_JS):
                    break
            except Exception:
                pass
        else:
            time.sleep(1.0)   # panel never lit up — give it one more second
        return True
    except TimeoutException:
        return False


# All three collection passes run inside the browser in single JS calls.
# _DRAWINGS_READY_JS uses a broad ANY-img check as the ready signal:
# PatSeer renders drawings in many different container class names depending on
# the record type, so checking every <img> on the page is more reliable than
# targeting specific class names.  Icon/logo images are tiny (<50px) and are
# excluded by the naturalWidth check.
_DRAWINGS_READY_JS = """
const allImgs = document.getElementsByTagName('img');
for (const el of allImgs) {
    const s = el.getAttribute('src') || el.getAttribute('data-src') || '';
    if (s.indexOf('http') !== 0) continue;
    // Skip tiny icons (naturalWidth available once image has loaded)
    if (el.naturalWidth && el.naturalWidth < 50) continue;
    return true;
}
return false;
"""

_COLLECT_TARGETED_JS = """
const sels = arguments[0];
const out = [];
for (const sel of sels) {
    let els;
    try { els = document.querySelectorAll(sel); } catch (e) { continue; }
    for (const el of els) {
        for (const a of ['src', 'data-src', 'data-original', 'data-lazy']) {
            const v = el.getAttribute(a);
            if (v) out.push(v);
        }
    }
}
return out;
"""

_COLLECT_BROAD_JS = """
const out = [];
for (const img of document.getElementsByTagName('img')) {
    const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
    if (src.indexOf('http') !== 0) continue;
    // Skip only very tiny icons (< 50px) — 100px was too aggressive and
    // caused thumbnails to be missed on some PatSeer record types.
    if (img.naturalWidth && img.naturalWidth < 50) continue;
    out.push(src);
}
return out;
"""

_COLLECT_HREF_JS = """
const out = [];
for (const a of document.querySelectorAll('a[href]')) {
    const h = a.href || '';
    if (/\\.(png|jpg|jpeg|gif|tif|tiff|bmp|webp)(\\?|$)/i.test(h)) out.push(h);
}
return out;
"""


def collect_image_urls(
    driver: webdriver.Chrome,
    file_type_filter: str = "all",   # "img", "D", "FAT", or "all"
) -> list[str]:
    """
    Collect drawing image URLs visible after clicking the Drawings tab.

    Filenames are NOT read from the DOM — they come from the Content-Disposition
    header when each URL is fetched.  file_type_filter applies a URL-heuristic
    pre-filter based on the filename segment embedded in the PatSeer CDN path.
    """
    # Wait until at least one drawing image appears (up to 60s on slow connections).
    # Poll every 0.5s; once images appear, wait up to 1.5s more for lazy-loaded
    # thumbnails to finish — but only up to that cap, not a full 2s every time.
    deadline = time.time() + 60
    appeared_at: float | None = None
    while time.time() < deadline:
        try:
            if driver.execute_script(_DRAWINGS_READY_JS):
                if appeared_at is None:
                    appeared_at = time.time()
                elif time.time() - appeared_at >= 1.5:
                    break   # images stable for 1.5s — done waiting
        except Exception:
            pass
        time.sleep(0.5)

    seen: set[str] = set()
    urls: list[str] = []

    def _add(src: str) -> None:
        if not src or not src.startswith("http"):
            return
        # Strip thumbnail size parameters to request the full-resolution image
        full = re.sub(r"[?&](size|thumb|thumbnail|w|h|width|height|scale|dpi)=[^&]*", "", src)
        full = full.rstrip("?&")
        if full not in seen and _url_matches_type_filter(full, file_type_filter):
            seen.add(full)
            urls.append(full)

    # ── Pass 1: targeted drawing-panel selectors ──────────────────────────────
    css_targeted = [
        "div[class*='drawing'] img",
        "div[class*='Drawing'] img",
        "div[class*='drawings'] img",
        "div[class*='Drawings'] img",
        "div[class*='figure'] img",
        "div[class*='Figure'] img",
        "div[class*='image'] img",
        ".drawings-panel img",
        ".thumbnails img",
        ".thumbnail-list img",
        "figure img",
        "img[class*='drawing']",
        "img[class*='thumbnail']",
        "img[class*='figure']",
        # PatSeer sometimes wraps each drawing in an anchor
        "a[class*='drawing'] img",
        "a[class*='thumbnail'] img",
    ]
    try:
        for src in driver.execute_script(_COLLECT_TARGETED_JS, css_targeted) or []:
            _add(src)
    except Exception:
        pass

    # ── Pass 2: broad fallback — all <img> tags, filter by size + URL ────────
    if not urls:
        try:
            for src in driver.execute_script(_COLLECT_BROAD_JS) or []:
                # Skip obvious non-drawing resources
                if any(skip in src.lower() for skip in ("logo", "icon", "avatar", "spinner", "flag")):
                    continue
                _add(src)
        except Exception:
            pass

    # ── Pass 3: anchor hrefs pointing directly to image files ────────────────
    if not urls:
        try:
            for href in driver.execute_script(_COLLECT_HREF_JS) or []:
                _add(href)
        except Exception:
            pass

    return urls


def _filename_from_response(resp: requests.Response, fallback_idx: int) -> str:
    """
    Derive the filename for a downloaded image.

    Priority:
      1. Content-Disposition header  (e.g. 'attachment; filename="D00002.png"')
      2. Last path component of the URL (if it has a recognisable extension)
      3. fig_NN.<ext> derived from Content-Type
    """
    cd = resp.headers.get("Content-Disposition", "")
    if cd:
        # RFC 5987 extended value:  filename*=UTF-8''D00002.png
        m = re.search(r"filename\*=['\"]?(?:[\w\-]+'')?([^;\"'\s]+)", cd, re.IGNORECASE)
        if m:
            return unquote(m.group(1))
        # Plain value:  filename="D00002.png"  or  filename=D00002.png
        m = re.search(r'filename=["\']?([^;"\']+)["\']?', cd, re.IGNORECASE)
        if m:
            return unquote(m.group(1).strip())

    # Fall back to URL path
    try:
        path = unquote(urlparse(resp.url).path)
        name = Path(path).name
        if name and re.search(r"\.[a-zA-Z]{2,4}$", name):
            return name
    except Exception:
        pass

    # Last resort: generic name with extension from Content-Type
    ct = resp.headers.get("content-type", "")
    ext_map = {"jpeg": "jpg", "png": "png", "gif": "gif",
               "tiff": "tif", "bmp": "bmp", "webp": "webp"}
    ext = next((e for mime, e in ext_map.items() if mime in ct.lower()), "png")
    return f"fig_{fallback_idx:02d}.{ext}"


def download_images(
    urls: list[str],
    patent_num: str,
    session: requests.Session,
    out_dir: Path,
    record_idx: int = 0,
) -> int:
    """
    Download images into out_dir/patent_num/.

    For each file:
      - Filename is taken from the Content-Disposition response header.
      - clean_filename() is applied immediately to normalise to the
        pipeline convention (US…A1_img003.png, US…A1_D00005.png, etc.).
      - Files are categorised into img / D / FAT lists for the manifest.

    A manifest JSON is saved at out_dir/patent_num/{patent_num}_download_manifest.json.
    """
    dest_dir = out_dir / patent_num
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved     = 0
    pub_date: str | None = None

    img_files:  list[str] = []
    d_files:    list[str] = []
    fat_files:  list[str] = []

    resolved_patent_num: str | None = None   # set once we see the real ID in a response filename

    for i, url in enumerate(urls, start=1):
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            raw_name = _filename_from_response(r, i)

            # Extract publication date once (same for all files of this patent)
            if pub_date is None:
                pub_date = _extract_pub_date(raw_name)

            # If the folder is still named record_XXXX, try to resolve the real
            # patent ID from the Content-Disposition filename of the first response.
            # PatSeer always embeds the patent number in the raw filename even when
            # CDN URLs are opaque (e.g. "US20220267016A1-20220825-img003.png").
            if patent_num.startswith("record_") and resolved_patent_num is None:
                m = _PATENT_ID_RE.search(raw_name)
                if m:
                    resolved_id  = m.group(1).upper()
                    new_dest_dir = out_dir / resolved_id
                    if not new_dest_dir.exists():
                        dest_dir.rename(new_dest_dir)
                        dest_dir   = new_dest_dir
                        patent_num = resolved_id
                        resolved_patent_num = resolved_id
                        print(f"  Patent : {patent_num}  (resolved from response filename)")

            name = clean_filename(raw_name, patent_num)
            # Ensure patent ID prefix is present (fallback for unexpected raw names)
            if patent_num.lower() not in name.lower():
                name = f"{patent_num}_{name}"

            dest = dest_dir / name
            if dest.exists():
                print(f"      {name} – already exists, skipping")
            else:
                dest.write_bytes(r.content)
                print(f"      ✓ {name}  ({len(r.content)//1024} kB)")
            saved += 1

            # Categorise
            name_lower = name.lower()
            if "_img" in name_lower:
                img_files.append(name)
            elif re.search(r"_d\d{4,}", name_lower):
                d_files.append(name)
            elif "_fat" in name_lower:
                fat_files.append(name)

        except Exception as exc:
            print(f"      ✗ file_{i:02d}: {exc}")

    # ── Save download manifest ────────────────────────────────────────────────
    manifest = {
        "patent_id":          patent_num,
        "publication_date":   pub_date,
        "record_position":    record_idx,
        "img_files":          sorted(img_files),
        "d_files":            sorted(d_files),
        "fat_files":          sorted(fat_files),
        "download_timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    manifest_path = dest_dir / f"{patent_num}_download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return saved


def _dismiss_alert_and_relogin(driver: webdriver.Chrome) -> None:
    """
    Dismisses the PatSeer session-expired alert and navigates back to the
    PatSeer home page so the user can log in again.
    """
    try:
        alert = driver.switch_to.alert
        alert_text = alert.text
        alert.accept()
        print(f"\n  ⚠  Browser alert dismissed: \"{alert_text}\"")
    except Exception:
        pass

    driver.get("https://app1.patseer.com")


def _append_errors_csv(errors: list[tuple], out_dir: Path, start_from: int) -> Path:
    """Append this run's errors to a persistent CSV in out_dir."""
    csv_path = out_dir / "download_errors.csv"
    is_new   = not csv_path.exists()
    run_ts   = datetime.now().isoformat(timespec="seconds")

    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["record_idx", "patent_id", "reason", "run_start_from", "timestamp"])
        for idx, patent_num, reason in errors:
            writer.writerow([idx, patent_num, reason, start_from, run_ts])

    return csv_path


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = build_driver()
    wait   = WebDriverWait(driver, 45)   # generous timeout for slow Wi-Fi

    # ── Navigate directly to the search URL ──────────────────────────────────
    print("\n" + "="*60)
    print(f"  Chrome opened. Loading your PatSeer search…")
    print("="*60 + "\n")

    driver.get(SEARCH_BASE_URL)
    time.sleep(5)

    # ── Wait for login if needed ──────────────────────────────────────────────
    # Stop waiting as soon as the URL is anywhere on patseer.com and is no
    # longer a login/signin page — PatSeer may land on a dashboard after login,
    # not directly on the search URL, so only the absence of "login" matters.
    deadline    = time.time() + LOGIN_WAIT_SECONDS
    on_login    = False
    warned_once = False
    while time.time() < deadline:
        url        = driver.current_url.lower()
        on_login   = "login" in url or "signin" in url
        on_search  = "patseer.com/#/result/" in url or "detailsview" in url
        on_patseer = "patseer.com" in url and not on_login

        if on_search:
            print("  ✓ Search loaded — proceeding.")
            break
        if on_patseer:
            # Logged in but on dashboard / home — navigate to search now
            print("  ✓ Logged in — navigating to search URL…")
            driver.get(SEARCH_BASE_URL)
            time.sleep(4)
            continue
        if on_login and not warned_once:
            print("  ⚠  Login page detected — please log in in the Chrome window.")
            warned_once = True
        time.sleep(2)
    else:
        print("  ⚠  Timeout — proceeding anyway.")

    # ── Wait for the user to open DetailsView ─────────────────────────────────
    # Navigate manually in Chrome: open your search, switch to Details View and
    # land on the record you want to start from. Nothing is read until Enter,
    # and Enter is only accepted once the browser is actually on Details View
    # (URL contains "detailsview" or the "X / Y" record counter is readable).
    while True:
        input("\n  In Chrome, open the Details View on the record you want to "
              "start from,\n  then press Enter here to begin downloading… ")
        on_details = ("detailsview" in driver.current_url.lower()
                      or read_browser_record_position(driver) is not None)
        if on_details:
            break
        print("  ⚠  Not on the Details View page yet — open a record in "
              "Details View in Chrome, then press Enter again.")

    start = START_FROM
    print(f"  Starting from record {start}…\n")

    # ── Main loop ─────────────────────────────────────────────────────────────
    total_images = 0
    errors: list[tuple] = []
    idx = start

    try:
        while idx <= TOTAL_RECORDS:
            # Read the actual position shown in the browser — ground truth.
            # If the browser and counter agree, great. If not, trust the browser.
            browser_pos = read_browser_record_position(driver)
            if browser_pos is not None and browser_pos != idx:
                print(f"\n  ⚠  Counter says {idx} but browser shows {browser_pos} — syncing to browser.")
                idx = browser_pos

            print(f"\n[{idx:3d}/{TOTAL_RECORDS}]")

            try:
                # ── Step 1: wait for page to stabilise, then get patent ID ────
                # On slow connections the DOM may not have loaded the record
                # details yet. Poll extract_patent_number until it returns a
                # real ID (not record_XXXX), up to 30s.
                deadline_id = time.time() + 30
                patent_num  = extract_patent_number(driver, idx)
                while patent_num.startswith("record_") and time.time() < deadline_id:
                    time.sleep(1.0)
                    patent_num = extract_patent_number(driver, idx)

                # ── Step 2: click Drawings tab ────────────────────────────────
                if not click_drawings_tab(driver, wait):
                    print(f"  Patent : {patent_num}")
                    print(f"  ⚠  Drawings tab not found")
                    print(f"     Tabs: {[el.text.strip() for el in driver.find_elements(By.XPATH, '//*[self::a or self::li or self::button][string-length(normalize-space(.)) < 30]') if el.text.strip()][:15]}")
                    errors.append((idx, patent_num, "no Drawings tab"))
                    if idx < TOTAL_RECORDS:
                        click_next_patent(driver)
                    idx += 1
                    continue

                # ── Step 3: collect image URLs ────────────────────────────────
                img_urls = collect_image_urls(driver)

                # ── Step 4: resolve patent ID from URLs (most reliable source)
                # Image CDN paths embed the original filename which always
                # contains the patent publication number — use this as the
                # authoritative ID rather than the DOM, which often fails.
                from_url = _patent_id_from_urls(img_urls)
                if from_url:
                    patent_num = from_url
                elif patent_num.startswith("record_"):
                    # Last resort: DOM gave nothing and URLs gave nothing.
                    # Log a warning — do NOT use Excel row lookup because the
                    # Excel is not sorted to match PatSeer's display order.
                    print(f"  ⚠  Could not resolve patent ID from DOM or image URLs — saving as {patent_num}")

                print(f"  Patent : {patent_num}")

                # ── Step 5: skip if already downloaded ────────────────────────
                # Only skip on a *real* patent ID — never skip a record_XXXX
                # folder, because those represent failed previous runs and must
                # be retried.  (record_XXXX manifests exist but contain no images.)
                already_done = False
                if not patent_num.startswith("record_"):
                    manifest_path = OUTPUT_DIR / patent_num / f"{patent_num}_download_manifest.json"
                    if manifest_path.exists():
                        already_done = True
                if already_done:
                    print(f"  Manifest exists — skipping")
                    if idx < TOTAL_RECORDS:
                        click_next_patent(driver)
                    idx += 1
                    continue

                print(f"  Images : {len(img_urls)} found")

                if not img_urls:
                    print("  ⚠  No image URLs collected.")
                    errors.append((idx, patent_num, "no image URLs found"))
                    if idx < TOTAL_RECORDS:
                        click_next_patent(driver)
                    idx += 1
                    continue

                # ── Step 6: download ──────────────────────────────────────────
                session = make_requests_session(driver)
                n = download_images(img_urls, patent_num, session, OUTPUT_DIR, record_idx=idx)
                total_images += n

                # Advance to next patent — retry once before giving up.
                # Never increment idx until the browser position confirms the
                # change: a wrong record_position corrupts the Excel ID lookup.
                if idx < TOTAL_RECORDS:
                    advanced = click_next_patent(driver)
                    if not advanced:
                        print("  ↺  Retrying next-patent click after 5s…")
                        time.sleep(5)
                        advanced = click_next_patent(driver)
                    if not advanced:
                        print("  ⚠  Next-patent arrow failed twice — stopping to preserve ordering.")
                        errors.append((idx, patent_num, "next arrow failed"))
                        break

                idx += 1
                time.sleep(DELAY_SECS)

            except UnexpectedAlertPresentException:
                _dismiss_alert_and_relogin(driver)
                print(f"\n  ⚠  Session expired at record {idx}.")
                print(f"  Waiting {LOGIN_WAIT_SECONDS}s for re-login…")
                # Wait for the search page to come back after re-login
                deadline = time.time() + LOGIN_WAIT_SECONDS
                while time.time() < deadline:
                    if "patseer.com/#/result/" in driver.current_url:
                        driver.get("https://app1.patseer.com/DetailsView")
                        time.sleep(4)
                        print(f"  Resuming from record {idx}…\n")
                        break
                    time.sleep(2)

    except KeyboardInterrupt:
        print("\n⏹  Run interrupted by user.  Re-run with START_FROM set to resume.")
    finally:
        driver.quit()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print(f"  Total images saved : {total_images}")
    print(f"  Output folder      : {OUTPUT_DIR.resolve()}")
    if errors:
        print(f"\n  Records with issues ({len(errors)}):")
        for i, pn, reason in errors:
            print(f"    Record {i:3d}  ({pn})  →  {reason}")
        csv_path = _append_errors_csv(errors, OUTPUT_DIR, start)
        print(f"\n  Errors appended to : {csv_path}")
    print("="*60)


if __name__ == "__main__":
    main()