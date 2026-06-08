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

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# ─── CONFIGURATION ─────────────────────────────────────────────────────────────

# Paste your search URL from the browser (only the base part – no record number)
SEARCH_BASE_URL = "https://app1.patseer.com/#/result/ad056431-8522-11e8-944f-22000bd445e0"

TOTAL_RECORDS      = 1689    # total records in your search result
START_FROM         = 1     # change this to resume a previous run
LOGIN_WAIT_SECONDS = 60    # seconds to log in and navigate to search before script takes over

OUTPUT_DIR    = Path("patseer_drawings")   # overridden by notebook Cell 1 via cfg["paths"]["raw_images"]
DELAY_SECS    = 2.5      # pause between patents – keep this ≥ 2 to avoid hammering the server
HEADLESS      = False    # set True to run without a visible browser window

# ── Optional: reuse an existing Chrome session so you skip the login prompt.
# Find your profile path at  chrome://version/  →  "Profile Path"
#   Windows example : r"C:\Users\YourName\AppData\Local\Google\Chrome\User Data"
#   Linux example   : "/home/yourname/.config/google-chrome"
#   Mac example     : "/Users/yourname/Library/Application Support/Google/Chrome"
CHROME_PROFILE_DIR = ""      # leave empty to open a fresh browser
CHROME_PROFILE     = "Default"

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


def _fix_record_folder(record_dir: Path, out_dir: Path) -> str | None:
    """After downloading into a record_XXXX folder, extract the real patent ID from
    the downloaded filenames, rename all files + the folder, and update the manifest.
    Returns the new patent_id on success, None if it can't be determined.
    """
    if not record_dir.exists():
        return None

    pat       = re.compile(r"([A-Z]{2}\d{6,}[A-Z0-9]+)", re.IGNORECASE)
    patent_id = None

    for f in record_dir.iterdir():
        # Search the stem so the extension doesn't interfere
        m = pat.search(f.stem)
        if m:
            candidate = m.group(1).upper()
            if not candidate.upper().startswith("RECORD"):
                patent_id = candidate
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
    options = webdriver.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,900")
    else:
        options.add_argument("--start-maximized")
    if CHROME_PROFILE_DIR:
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
        options.add_argument(f"--profile-directory={CHROME_PROFILE}")
    # Reduces the chance of bot-detection flags
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


def extract_patent_number(driver: webdriver.Chrome, record_idx: int) -> str:
    """
    Try to read the patent publication number from the DetailsView DOM.
    Falls back to 'record_{idx}' if nothing can be parsed.
    """
    try:
        # Most reliable: the Angular navbar element carries appnum="US20221767359A1"
        for attr_sel, attr_name in [
            ("[class*='recordInfoContainer'][appnum]", "appnum"),
            ("[class*='recordInfoContainer'][recordnum]", "recordnum"),
            ("[appnum]", "appnum"),
            ("[recordnum]", "recordnum"),
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, attr_sel)
            for el in els:
                val = el.get_attribute(attr_name)
                if val:
                    m = re.search(r"([A-Z]{2}\d{6,}[A-Z0-9]*)", val, re.IGNORECASE)
                    if m:
                        return m.group(1).upper()
    except Exception:
        pass
    try:
        # Fallback: scan visible text in common header elements
        for sel in ["[class*='record-title']", "[class*='recordTitle']",
                    "[class*='record-head']", "[class*='patent-number']", "h2", "h3"]:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                text = el.text.strip()
                m = re.search(r"([A-Z]{2}\d{6,}[A-Z0-9]*)", text)
                if m:
                    return m.group(1).upper()
    except Exception:
        pass
    return f"record_{record_idx:04d}"


def click_next_patent(driver: webdriver.Chrome) -> bool:
    """Click the next-record arrow in DetailsView (ng-click='nextSelectedRecord')."""
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "[ng-click*='nextSelectedRecord']"))
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(2.5)
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
        time.sleep(1.8)
        return True
    except TimeoutException:
        return False


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
    time.sleep(2.5)   # let thumbnails finish loading

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
    for css in css_targeted:
        for img in driver.find_elements(By.CSS_SELECTOR, css):
            for attr in ("src", "data-src", "data-original", "data-lazy"):
                _add(img.get_attribute(attr) or "")

    # ── Pass 2: broad fallback — all <img> tags, filter by size + URL ────────
    if not urls:
        for img in driver.find_elements(By.TAG_NAME, "img"):
            src = img.get_attribute("src") or img.get_attribute("data-src") or ""
            if not src.startswith("http"):
                continue
            # Skip tiny icons/logos (width or height < 100px in natural size)
            try:
                nat_w = driver.execute_script("return arguments[0].naturalWidth;",  img)
                nat_h = driver.execute_script("return arguments[0].naturalHeight;", img)
                if nat_w and nat_h and (int(nat_w) < 100 or int(nat_h) < 100):
                    continue
            except Exception:
                pass
            # Skip obvious non-drawing resources
            if any(skip in src.lower() for skip in ("logo", "icon", "avatar", "spinner", "flag")):
                continue
            _add(src)

    # ── Pass 3: anchor hrefs pointing directly to image files ────────────────
    if not urls:
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
            href = a.get_attribute("href") or ""
            if re.search(r"\.(png|jpg|jpeg|gif|tif|tiff|bmp|webp)(\?|$)", href, re.IGNORECASE):
                _add(href)

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

    for i, url in enumerate(urls, start=1):
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            raw_name = _filename_from_response(r, i)

            # Extract publication date once (same for all files of this patent)
            if pub_date is None:
                pub_date = _extract_pub_date(raw_name)

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


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = build_driver()
    wait   = WebDriverWait(driver, 15)

    # ── Login + activate search ───────────────────────────────────────────────
    driver.get("https://app1.patseer.com")
    print("\n" + "="*60)
    print(f"  You have {LOGIN_WAIT_SECONDS} seconds to:")
    print("  1. Log in to PatSeer in the Chrome window")
    print("  2. Navigate to your search so the patent list is visible")
    print("  Script will open DetailsView automatically when the timer ends.")
    print("="*60)
    for remaining in range(LOGIN_WAIT_SECONDS, 0, -10):
        print(f"  {remaining}s remaining…")
        time.sleep(10)
    print("  Time up — taking over.\n")

    # ── Open DetailsView — shows patent 1 of the active search ───────────────
    driver.get("https://app1.patseer.com/DetailsView")
    time.sleep(4)

    # Fast-forward to START_FROM by clicking next (START_FROM - 1) times
    if START_FROM > 1:
        print(f"  Fast-forwarding to record {START_FROM} (clicking next {START_FROM-1} times)…")
        for _ in range(START_FROM - 1):
            click_next_patent(driver)

    # ── Main loop ─────────────────────────────────────────────────────────────
    total_images = 0
    errors: list[tuple] = []

    try:
        for idx in range(START_FROM, TOTAL_RECORDS + 1):
            print(f"\n[{idx:3d}/{TOTAL_RECORDS}]")

            patent_num = extract_patent_number(driver, idx)
            print(f"  Patent : {patent_num}")

            # Skip check
            patent_dir    = OUTPUT_DIR / patent_num
            manifest_path = patent_dir / f"{patent_num}_download_manifest.json"
            if manifest_path.exists():
                print(f"  Manifest exists — skipping")
                if idx < TOTAL_RECORDS:
                    click_next_patent(driver)
                continue

            # Click the Drawings tab
            if not click_drawings_tab(driver, wait):
                print(f"  ⚠  Drawings tab not found")
                print(f"     Tabs: {[el.text.strip() for el in driver.find_elements(By.XPATH, '//*[self::a or self::li or self::button][string-length(normalize-space(.)) < 30]') if el.text.strip()][:15]}")
                errors.append((idx, patent_num, "no Drawings tab"))
                if idx < TOTAL_RECORDS:
                    click_next_patent(driver)
                continue

            # Collect image URLs
            img_urls = collect_image_urls(driver)
            print(f"  Images : {len(img_urls)} found")

            if not img_urls:
                print("  ⚠  No image URLs collected.")
                errors.append((idx, patent_num, "no image URLs found"))
                if idx < TOTAL_RECORDS:
                    click_next_patent(driver)
                continue

            # Refine patent_num from image URLs if DOM extraction fell back
            if patent_num.startswith("record_"):
                from_url = _patent_id_from_urls(img_urls)
                if from_url:
                    patent_num = from_url
                    print(f"  Patent : {patent_num}  (from image URL)")
                    manifest_path = OUTPUT_DIR / patent_num / f"{patent_num}_download_manifest.json"
                    if manifest_path.exists():
                        print(f"  Manifest exists — skipping")
                        if idx < TOTAL_RECORDS:
                            click_next_patent(driver)
                        continue

            # Download
            session = make_requests_session(driver)
            n = download_images(img_urls, patent_num, session, OUTPUT_DIR, record_idx=idx)
            total_images += n

            # Post-download: if DOM and URL extraction both failed, read patent ID
            # directly from the downloaded filenames and rename the folder
            if patent_num.startswith("record_"):
                fixed = _fix_record_folder(OUTPUT_DIR / patent_num, OUTPUT_DIR)
                if fixed:
                    patent_num = fixed
                    print(f"  Patent : {patent_num}  (from downloaded filenames — folder renamed)")

            # Advance to next patent
            if idx < TOTAL_RECORDS:
                if not click_next_patent(driver):
                    print("  ⚠  Next-patent arrow not found — check selectors in click_next_patent()")
                    errors.append((idx, patent_num, "next arrow not found"))
                    break

            time.sleep(DELAY_SECS)

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
    print("="*60)


if __name__ == "__main__":
    main()