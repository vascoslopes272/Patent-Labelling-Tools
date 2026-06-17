"""
timer.py
Sends two prompts to VSCode Claude at scheduled times using clipboard paste.
CLIPBOARD METHOD — the entire prompt is pasted atomically with Ctrl+V.
Never uses typewrite(), which breaks on newlines, special chars, and long strings.

Schedule:
  Prompt 1 → 04:20
  Prompt 2 → 04:50  (30 min later)

Usage:
  1. pip install pyautogui pyperclip
  2. Click inside the VSCode chat input so the cursor is blinking there.
  3. python timer.py
"""

import time
import datetime
import pyautogui
import pyperclip

TARGET_TIME_P1 = "04:20"
TARGET_TIME_P2 = "04:50"

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 1 — 00b2: Crop quality post-processing + ipywidgets crop review UI
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_1 = """You are working inside the Patent-Labelling-Tools repository for eVTOL patents. The pipeline processes ~1500 patents and ~30000 figures. Read the existing code carefully before writing anything. Do NOT touch any cell, module, or file that is already working. Add only the two new cells described below.

HARD CONSTRAINTS (non-negotiable):
- Raw files in the raw/ directory are NEVER deleted, moved, or modified.
- Do not re-run YOLO or EasyOCR. This is a pure post-processing pass on already-saved crops.
- Use only libraries already in requirements.txt: opencv-python, numpy, pandas, ipywidgets, Pillow.

────────────────────────────────────────────────────────────────
TASK 1 — New Cell 5b in notebooks/00b2_figure_crop_&_Brief_DD_matching.ipynb
Insert this cell immediately after the existing Cell 5 (the one that saves needs_human_review.csv).

Purpose: Compute a crop_quality flag for every row in crops_mapping.csv by inspecting the already-saved PNG files. Append the column and overwrite crops_mapping.csv in place.

Logic (check in this order — first match wins, store as string):
  "blank"     → mean pixel brightness of the crop > 248  (nearly white, YOLO false-positive on margin)
  "too_small" → either dimension of the crop < 80 px
  "low_conf"  → column "conf" exists in crops_mapping.csv AND value < 0.40
  "merged"    → column "review_hint" exists AND value == "possible_multi_fig"
  ""          → passes all checks (clean crop)

Where to find the PNG files: for each row, the file is at:
    Path(cfg["paths"]["matched"]) / row["patent_id"] / row["output"]

If the file does not exist (e.g. triage-excluded), set crop_quality = "missing".

After computing, overwrite crops_mapping.csv. Print a summary table:
  crop_quality | count
  -------------|------
  (empty)      |  N
  blank        |  N
  too_small    |  N
  low_conf     |  N
  merged       |  N
  missing      |  N

────────────────────────────────────────────────────────────────
TASK 2 — New Cell 5c in notebooks/00b2_figure_crop_&_Brief_DD_matching.ipynb
Insert this cell immediately after Cell 5b. This is an ipywidgets interactive crop reviewer.

Purpose: Show only the crops that need human attention — i.e. rows where needs_review == True OR crop_quality != "" — and allow the reviewer to Keep / Relabel / Reject each one.

UI layout:
  - A header showing "X crops need attention (Y patents)"
  - A progress counter: "Reviewed: N / X"
  - Navigation: [◄ Prev] [patent N/total] [Next ►] — navigates between patents
  - For each patent: a scrollable grid of cards (3 columns), one card per flagged crop
  - Each card contains:
      * The crop image embedded as base64 PNG, max 220px wide, max 200px tall, object-fit: contain
      * A colored badge: red for "blank"/"too_small"/"missing", orange for "low_conf"/"merged", yellow for needs_review with no quality issue
      * The label text: current label from filename (e.g. "3B") or "Fu" if None
      * The crop_quality value in small grey text
      * Three buttons on one row: [✓ Keep]  [✎ Relabel]  [✗ Reject]

Button behaviour:
  Keep    → sets crop_quality to "" (confirmed clean), updates crops_mapping.csv row in memory
  Relabel → reveals a text input + [Apply] button; on Apply: renames the file from *_Fu.png
             to *_F{new_label}.png (using Path.rename — this is in matched/, not raw/),
             updates the "output", "label", "needs_review", and "crop_quality" columns in memory
  Reject  → sets crop_quality = "rejected" in memory. Does NOT delete or move the file.

On every Keep/Relabel/Reject action: immediately call
    results_df.to_csv(crops_csv, index=False)
so progress is saved incrementally and survives kernel restarts.

Use ipywidgets Output widget for rendering. No JavaScript. No external CSS files."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 2 — 01 notebook: crop quality pre-filter + JSON collector cell
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_2 = """You are working inside the Patent-Labelling-Tools repository for eVTOL patents. Read ALL existing code carefully before writing anything. Make only the two targeted additions described below. Do NOT rewrite, rename, or restructure any existing module (reviewer.py, cross_modal.py, excel_schema.py, doclayout_matcher.py, gpu_worker.py must not be modified beyond the single optional parameter addition in Task 1).

HARD CONSTRAINTS:
- Raw files are never deleted or modified.
- The master taxonomy reference is the HTML file at the repo root: UI_for_taxonomy_caracterization_10_0.html
- SigLIP (ViT-SO400M-14-SigLIP-384) is the only vision model for classification. DINOv2 is NOT used here.

────────────────────────────────────────────────────────────────
TASK 1 — Crop quality pre-filter in notebooks/01_review.ipynb

Find the main processing loop cell — the one that iterates over patent_ids and calls reviewer.process_patent(). Add the following logic at the TOP of that cell, before the loop begins:

Step A — Load crops_mapping.csv once:
    crops_csv = Path(cfg["paths"]["data"]) / "crops_mapping.csv"
    crops_df = pd.read_csv(crops_csv, dtype=str) if crops_csv.exists() else pd.DataFrame()

Step B — Build a skip_files dict and a cap_files dict keyed by patent_id:
    SKIP_QUALITIES = {"blank", "too_small", "rejected", "missing"}
    CAP_QUALITIES  = {"low_conf", "merged"}
    skip_files_map = {}
    cap_files_map  = {}
    if not crops_df.empty and "crop_quality" in crops_df.columns:
        for pid, grp in crops_df.groupby("patent_id"):
            skip_files_map[pid] = set(grp.loc[grp["crop_quality"].isin(SKIP_QUALITIES), "output"])
            cap_files_map[pid]  = set(grp.loc[grp["crop_quality"].isin(CAP_QUALITIES),  "output"])

Step C — Inside the loop, pass skip_files to process_patent():
    skip = skip_files_map.get(patent_id, set())
    cap  = cap_files_map.get(patent_id, set())
    record = reviewer.process_patent(..., skip_files=skip)   # add this kwarg

Step D — After process_patent() returns, cap SigLIP confidence for degraded crops:
    For every figure result in record["figures"] whose filename is in cap:
        for any confidence value > 0.55 in T2_predictions, G1_hint, m1/m2/m3 sub-dicts,
        clip it to 0.55. This prevents noisy crops from dominating patent-level aggregation.

Step E — Add skip_files=None as an optional parameter to reviewer.process_patent() in src/reviewer.py.
    At the top of the image_files assembly block (just before match_images() is called),
    add: if skip_files: image_files = [f for f in image_files if f.name not in skip_files]
    No other change to reviewer.py.

────────────────────────────────────────────────────────────────
TASK 2 — HTML wizard JSON collector cell in notebooks/01_review.ipynb

Add a new final cell at the bottom of 01_review.ipynb. This cell runs independently of the main loop and can be re-run at any time.

Purpose: Collect JSON files exported by the HTML wizard (UI_for_taxonomy_caracterization_10_0.html) and write them into reviewed_patents.xlsx via excel_schema.append_reviewed_rows().

Logic:
1. Read html_review_exports path from config: cfg["paths"].get("html_review_exports").
   If the key is absent, default to Path(cfg["paths"]["data"]) / "html_exports".
   Create the directory and a processed/ subdirectory if they do not exist.
   Also add the key to config.yaml with the default path if it was absent (write back with yaml.dump).

2. Scan the html_exports/ directory for *.json files (not inside processed/).

3. For each JSON file:
   a. Read and parse it.
   b. Extract patent_id from the JSON (key: "patentId" or "patent_id" — check both).
   c. Call excel_schema.build_patent_rows(patent_id, record_dict, patent_img_dir) where
      record_dict is the parsed JSON and patent_img_dir is matched/<patent_id>/.
   d. Call excel_schema.append_reviewed_rows(rows, reviewed_xlsx_path).
   e. Move the JSON file to html_exports/processed/<filename> using Path.rename().
   f. Print: "  ✓ Ingested patent_id from filename.json"

4. At the end print a summary:
   "Ingested N JSON exports → reviewed_patents.xlsx now contains M patents."
   where M is the count of unique Patent_ID values in the reviewed sheet.

Use only pandas, pathlib, yaml, and excel_schema (already in the repo). No new dependencies."""


# ─────────────────────────────────────────────────────────────────────────────
# Timer logic — clipboard paste, all at once
# ─────────────────────────────────────────────────────────────────────────────

def send_prompt(label: str, text: str):
    """Copy text to clipboard and paste into the focused window atomically."""
    print(f"\n🚀 Sending {label}...")
    pyperclip.copy(text)
    time.sleep(0.4)                   # let clipboard settle
    pyautogui.hotkey("ctrl", "v")     # paste entire prompt at once
    time.sleep(0.6)                   # let the UI receive the paste
    pyautogui.press("enter")          # submit
    print(f"📨 {label} sent! ({len(text)} chars)")


def wait_until(target_hhmm: str, label: str):
    print(f"⏳ Waiting for {target_hhmm} to send {label}...")
    while True:
        now = datetime.datetime.now().strftime("%H:%M")
        if now == target_hhmm:
            return
        time.sleep(10)   # check every 10 seconds


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  eVTOL Patent Pipeline — Overnight Prompt Timer")
    print("=" * 60)
    print(f"  Prompt 1 → {TARGET_TIME_P1}  (00b2 crop quality + review UI)")
    print(f"  Prompt 2 → {TARGET_TIME_P2}  (01 crop filter + JSON collector)")
    print()
    print("⚠️  BEFORE LEAVING:")
    print("    1. Click inside the VSCode chat input box")
    print("    2. Make sure the cursor is blinking there")
    print("    3. Do NOT touch the keyboard or mouse after that")
    print("=" * 60)

    # ── Prompt 1 ──────────────────────────────────────────────────────────────
    wait_until(TARGET_TIME_P1, "Prompt 1")
    send_prompt("Prompt 1", PROMPT_1)

    # ── Wait 30 minutes ───────────────────────────────────────────────────────
    print(f"\n⏳ Waiting 30 minutes for Prompt 2 at {TARGET_TIME_P2}...")
    wait_until(TARGET_TIME_P2, "Prompt 2")
    send_prompt("Prompt 2", PROMPT_2)

    print("\n🎉 Both prompts sent. Pipeline will run overnight.")
    print("   Check crops_mapping.csv and reviewed_patents.xlsx in the morning.")