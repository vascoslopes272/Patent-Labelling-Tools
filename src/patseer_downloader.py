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

import re
import time
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

TOTAL_RECORDS = 162      # total records in your search result
START_FROM    = 1        # change this to resume a previous run

OUTPUT_DIR    = Path("patseer_drawings")   # folder where images are saved
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
    Try to read the patent publication number from the record panel header.
    Falls back to 'record_{idx}' if nothing can be parsed.
    """
    try:
        # PatSeer shows the number in the top of the right panel, e.g. "1.US2015014475A1"
        selectors = [
            "[class*='record-title']",
            "[class*='recordTitle']",
            "[class*='record-head']",
            "[class*='patent-number']",
            "h2", "h3",
        ]
        for sel in selectors:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                text = el.text.strip()
                match = re.search(r"([A-Z]{2}\d{6,}[A-Z0-9]*)", text)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return f"record_{record_idx:04d}"


def open_details_view(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """
    Select the currently highlighted record in the search results list, then
    navigate to DetailsView.

    PatSeer keeps the selected record in session state. The correct two-step
    flow is:
      1. Let the search-result URL finish loading (so the record is selected)
      2. Navigate to /DetailsView — it picks up the session-selected patent
    """
    # If we somehow already landed on DetailsView, nothing to do
    if "DetailsView" in driver.current_url or "detailsview" in driver.current_url.lower():
        return True

    # Wait a bit longer for Angular hash-routing to register the selected record
    time.sleep(2.0)

    # Navigate to DetailsView — session state carries the selected record over
    driver.get("https://app1.patseer.com/DetailsView")
    time.sleep(3.5)   # give it time to load the patent content

    return "DetailsView" in driver.current_url or "detailsview" in driver.current_url.lower()


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


def collect_image_urls(driver: webdriver.Chrome) -> list[str]:
    """
    Collect all drawing image URLs visible after clicking the Drawings tab.
    Filenames are NOT read from the DOM — they come from the Content-Disposition
    header returned when each URL is fetched.
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
        if full not in seen:
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
) -> int:
    """Download images into out_dir/patent_num/, using the server-supplied filename
    from the Content-Disposition response header."""
    dest_dir = out_dir / patent_num
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = 0

    for i, url in enumerate(urls, start=1):
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
            name = _filename_from_response(r, i)
            # Prefix with patent number if the server-supplied name doesn't include it
            if patent_num.lower() not in name.lower():
                name = f"{patent_num}_{name}"
            dest = dest_dir / name
            if dest.exists():
                print(f"      {name} – already exists, skipping")
                saved += 1
                continue
            dest.write_bytes(r.content)
            print(f"      ✓ {name}  ({len(r.content)//1024} kB)")
            saved += 1
        except Exception as exc:
            print(f"      ✗ fig_{i:02d}: {exc}")

    return saved


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    driver = build_driver()
    wait   = WebDriverWait(driver, 15)

    # ── Login ────────────────────────────────────────────────────────────────
    if CHROME_PROFILE_DIR:
        print("Using existing Chrome profile – navigating directly to PatSeer…")
        driver.get("https://app1.patseer.com")
        time.sleep(3)
    else:
        driver.get("https://app1.patseer.com")
        print("\n" + "="*60)
        print("  Please log in to PatSeer in the browser window that opened.")
        print("  Once you are fully logged in, come back here and press Enter.")
        print("="*60)
        input("  ▶ Press Enter when ready: ")

    # ── Main loop ─────────────────────────────────────────────────────────────
    total_images = 0
    errors: list[tuple] = []

    try:
        for idx in range(START_FROM, TOTAL_RECORDS + 1):
            record_url = f"{SEARCH_BASE_URL}/{idx}"
            print(f"\n[{idx:3d}/{TOTAL_RECORDS}] {record_url}")
            driver.get(record_url)
            time.sleep(3.5)   # wait for Angular hash-routing to register the selected record

            print(f"  URL    : {driver.current_url}")

            # Open the DetailsView for this record (contains the Drawings tab)
            if not open_details_view(driver, wait):
                print("  ⚠  Could not open DetailsView — check URL structure above")
                print(f"     Current URL after attempt: {driver.current_url}")
                errors.append((idx, f"record_{idx:04d}", "DetailsView not reached"))
                continue

            print(f"  Detail : {driver.current_url}")

            patent_num = extract_patent_number(driver, idx)
            print(f"  Patent : {patent_num}")

            # Skip patents we already completed
            patent_dir = OUTPUT_DIR / patent_num
            if patent_dir.exists() and any(patent_dir.glob("fig_*")):
                count = len(list(patent_dir.glob("fig_*")))
                print(f"  Already downloaded {count} image(s) – skipping")
                continue

            # Click the Drawings tab
            if not click_drawings_tab(driver, wait):
                print("  ⚠  Drawings tab not found")
                print(f"     Tabs visible: {[el.text for el in driver.find_elements(By.XPATH, '//*[self::a or self::li or self::button][string-length(normalize-space(.)) < 30]')][:15]}")
                errors.append((idx, patent_num, "no Drawings tab"))
                continue

            # Collect image URLs
            img_urls = collect_image_urls(driver)
            print(f"  Images : {len(img_urls)} found")

            if not img_urls:
                print("  ⚠  No image URLs collected.")
                print("     Tip: open DevTools → Network → filter 'Img' and inspect manually.")
                errors.append((idx, patent_num, "no image URLs found"))
                continue

            # Download — filenames come from Content-Disposition response headers
            session = make_requests_session(driver)
            n = download_images(img_urls, patent_num, session, OUTPUT_DIR)
            total_images += n

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