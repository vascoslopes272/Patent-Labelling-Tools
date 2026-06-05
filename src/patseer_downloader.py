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


def click_drawings_tab(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """Click the 'Drawings' tab in the right-hand record panel."""
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
    PatSeer loads thumbnails; we try to get the highest-resolution version.

    ── If images still aren't found, open DevTools → Network → filter 'Img',
       click on a drawing, and inspect the request URL. Update the selector
       or URL patterns below to match what you see.
    """
    time.sleep(2)   # let thumbnails finish loading

    # Multiple candidate selectors – one of these should match PatSeer's DOM
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
            # Attempt to strip thumbnail parameters to get full-size image
            full = re.sub(r"[?&](size|thumb|thumbnail|w|h|width|height)=[^&]*", "", src)
            full = full.rstrip("?&")
            if full not in seen:
                seen.add(full)
                urls.append(full)

    return urls


def download_images(
    urls: list[str],
    patent_num: str,
    session: requests.Session,
    out_dir: Path,
) -> int:
    """Download a list of image URLs into out_dir / patent_num /. Returns count saved."""
    dest_dir = out_dir / patent_num
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = 0

    for i, url in enumerate(urls, start=1):
        # Guess extension from content-type header
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
            print(f"      ✓ {dest.name}  ({len(r.content)//1024} kB)")
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
            time.sleep(2.2)

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
                print("  ⚠  Drawings tab not found – no drawings for this record?")
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

            # Download
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