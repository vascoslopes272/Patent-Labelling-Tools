"""
main.py — thin orchestrator for the patseer_drawing_pipeline.

Usage
-----
    python main.py stage00          # download all 162 records
    python main.py stage00 --scan   # download first scan_limit (10) records only
    python main.py stage01          # OCR + matching + JSON assembly
"""

import argparse

from src.config_loader import load_config


def run_stage00(cfg: dict, scan: bool = False) -> None:
    from selenium.webdriver.support.ui import WebDriverWait
    from src.extractor import (
        build_driver, login_flow, iter_records,
        extract_drawings_for_record, download_images,
        make_requests_session, load_patseer_excel, save_description_text,
    )

    limit = cfg["extractor"]["scan_limit"] if scan else None
    raw_dir = cfg["paths"]["raw_images"]
    text_dir = cfg["paths"]["text"]

    excel_index = load_patseer_excel(cfg["paths"]["patseer_excel"])

    driver = build_driver(cfg)
    wait = WebDriverWait(driver, 15)
    login_flow(driver, cfg)

    total_images = 0
    errors: list[tuple] = []

    try:
        for idx in iter_records(driver, cfg, limit=limit):
            patent_id, urls = extract_drawings_for_record(driver, wait, idx)

            patent_dir = raw_dir / patent_id
            if patent_dir.exists() and any(patent_dir.glob("fig_*")):
                count = len(list(patent_dir.glob("fig_*")))
                print(f"  Already downloaded {count} image(s) — skipping")
                continue

            if not urls:
                errors.append((idx, patent_id, "no image URLs found"))
                continue

            session = make_requests_session(driver)
            n = download_images(urls, patent_id, session, raw_dir)
            total_images += n

            if patent_id in excel_index:
                save_description_text(patent_id, excel_index[patent_id], text_dir)

    except KeyboardInterrupt:
        print("\n⏹  Interrupted. Re-run to resume (completed folders are skipped automatically).")
    finally:
        driver.quit()

    print(f"\nTotal images saved : {total_images}")
    if errors:
        print(f"Records with issues ({len(errors)}):")
        for i, pn, reason in errors:
            print(f"  Record {i:3d}  ({pn})  →  {reason}")


def run_stage01(cfg: dict) -> None:
    from src.extractor import load_patseer_excel
    from src.reviewer import process_patent

    excel_index = load_patseer_excel(cfg["paths"]["patseer_excel"])
    raw_dir = cfg["paths"]["raw_images"]

    if not raw_dir.exists():
        print(f"raw_images dir not found: {raw_dir}")
        return

    for patent_dir in sorted(raw_dir.iterdir()):
        if not patent_dir.is_dir():
            continue
        patent_id = patent_dir.name
        print(f"Processing {patent_id}…")
        json_path = process_patent(patent_id, cfg, excel_index, raw_dir)
        print(f"  → {json_path}")


_STAGES = {
    "stage00": run_stage00,
    "stage01": run_stage01,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="PatSeer drawing pipeline")
    parser.add_argument("stage", choices=list(_STAGES.keys()))
    parser.add_argument("--scan", action="store_true",
                        help="Stage 00 only: limit to first scan_limit records")
    args = parser.parse_args()

    cfg = load_config()

    if args.stage == "stage00":
        run_stage00(cfg, scan=args.scan)
    else:
        _STAGES[args.stage](cfg)


if __name__ == "__main__":
    main()
