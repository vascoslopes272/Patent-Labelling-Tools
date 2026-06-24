"""
timer_ui_changes.py
Schedules SIX UNATTENDED prompts (A through F) to build a brand-new repository structure
inside /home/vasco/Vasco Workspace/Tese_Vasco_Lnx, implement data integrity auditing tools,
populate dataset overview notebooks, execute UI layout overrides, and generate an end-to-end summary.

Usage:
  1. pip install pyautogui pyperclip
  2. Click inside the VSCode chat window panel input line so the cursor is blinking there.
  3. python timer_ui_changes.py
"""

import os
import time
import datetime
import subprocess
import pyautogui
import pyperclip

# ── Set these to whenever you want each prompt to fire (24h HH:MM) ────────────
TARGET_TIME_A = "00:30"  # Repo creation & structure setup
TARGET_TIME_B = "02:00"  # src/audit_utils.py creation                   (+1h30)
TARGET_TIME_C = "03:30"  # notebooks/00a1_dataset_overview.ipynb gen     (+1h30)
TARGET_TIME_D = "05:00"  # T2 interface behavior updates (Single+chips)  (+1h30)
TARGET_TIME_E = "06:30"  # UI Layout modifications (4-column matrix)     (+1h30)
TARGET_TIME_F = "08:00"  # Final review & change summary report gen      (+1h30)

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overnight_logs")
LOG_PATH = os.path.join(LOG_DIR, "timer_ui.log")

# Shared unattended-safety header pasted at the top of all prompts.
_HEADER = """╔══════════════════════════════════════════════╗
║ SCHEDULED / UNATTENDED. The user may be away. Do NOT call AskUserQuestion / ║
║ EnterPlanMode or wait for approval — it hangs the run. Decide, act, verify,  ║
║ finish, leave one short report. If you truly cannot proceed safely, STOP   ║
║ and say why. Make reasonable choices and WRITE DOWN any assumption.        ║
╚══════════════════════════════════════════════╝"""

_NEW_REPO_NAME = "Patent-Analysis-New-Pipeline"
_BASE_DIR = "/home/vasco/Vasco Workspace/Tese_Vasco_Lnx"
_REPO = f"{_BASE_DIR}/{_NEW_REPO_NAME}"
_FILE = "notebooks/UI_for_taxonomy_caracterization_10.0.html"

_DONT_REGRESS = """DO NOT REGRESS the MULTI-ARCHITECTURE work already in this file style. Keep ALL of it
intact if migrating logic: getArchCount(), saveCurArchProfile()/loadArchProfile(), the archProfiles[]/
curArch state, the T2 "Assign To" architecture dropdown + "+ Add architecture"
button + "Distinct Architectures" banner, the "Architecture N of M" banner injected
in render() for steps gate/m1/m2/m3, the per-architecture export ("_arch{N}" suffix
in recordToRows), and ingestPatentRows()/basePatentId()/archSuffixNum()."""

_VERIFY = """VERIFY BEFORE FINISHING (do not skip):
 - Extract the largest <script> block and run `node --check` on it — it MUST pass.
 - Confirm braces {}, parens (), and brackets [] are balanced across the whole file
   (equal open/close counts).
This is a STATIC HTML edit: do not run the notebook, models, or any batch."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT A — REPOSITORY STRUCTURAL SCAFFOLDING
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_A = f"""UNATTENDED TASK A — REPOSITORY SETUP AND INITIALIZATION.

{_HEADER}

I am building a brand-new analysis repository for my thesis data inside `{_BASE_DIR}`. 

Please initialize a clean repository structure for me by creating the following folders and empty files if they do not exist:
- `{_REPO}/data/raw/`
- `{_REPO}/data/processed/`
- `{_REPO}/notebooks/`
- `{_REPO}/src/`
- `{_REPO}/config/`
- Empty placeholder file: `{_REPO}/notebooks/00a1_dataset_overview.ipynb`
- Empty placeholder file: `{_REPO}/src/audit_utils.py`

Once folders are ready, initialize a clean Git repository here (`git init`). Copy the base web application wizard file from your active layout into this new workspace path at `{_REPO}/{_FILE}`. Make sure the setup is completely modular so that files inside `notebooks/` can easily import utility functions from the `src/` directory.

HANDOFF: Leave a brief confirmation note at `{_REPO}/INITIALIZATION_STATUS.md` confirming the workspace is scaffolded and ready for Task B."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT B — DATA INTEGRITY AUDITING CORE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_B = f"""UNATTENDED TASK B — DATA INTEGRITY ENGINE IMPLEMENTATION.

{_HEADER}

Please write a robust Python utility script inside `{_REPO}/src/audit_utils.py` to handle data integrity auditing for my patent classification pipeline. 

Context:
- The data originates from files like `ml_predict_labels_Batch_05.xlsx` which tracks parameters across different verification phases (T1, T2, M1, M2, M3).
- In the T2 phase, we monitor specific figures and their relative physical storage file paths.

Requirements for the functions:
1. `build_dataset_audit(df, storage_base_path)`:
   - Scan the input pandas DataFrame. For rows corresponding to the T2 phase, check if the designated image path physically exists on disk (matching your 11TB storage system mount).
   - Catch and isolate any rows where `Needs_Review` evaluates to True, or where fields are marked as 'human_required'.
   - Group these anomalies cleanly by `Patent_ID` along with a descriptive, customized string reason explaining "why" it failed validation.

2. `cross_reference_master(current_df, master_list_path)`:
   - Extract unique `Patent_ID` keys from the current batch DataFrame and compare them against a master checklist CSV file tracking our complete collection target.
   - Identify any missing patents entirely absent from the current batch data stream and flag them.

Ensure both functions return fully structured, clean pandas DataFrames. Wrap everything in descriptive error handling logs.

HANDOFF: Verify the Python syntax using `python -m py_compile src/audit_utils.py` and log results to your status file."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT C — AUTOMATED NOTEBOOK INGESTION PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_C = f"""UNATTENDED TASK C — REPO DATA OVERVIEW NOTEBOOK GENERATION.

{_HEADER}

Please populate the notebook file `{_REPO}/notebooks/00a1_dataset_overview.ipynb` with a clean, professional structure by writing a script or generating the standard underlying JSON notebook structure directly.

The notebook must execute the following structured blocks:
1. **Environment Setup**: Initialize the execution space and append the root parent directory to `sys.path` so it can cleanly import `build_dataset_audit` and `cross_reference_master` from `src.audit_utils` without pathing failures.
2. **Data Loading Configuration**: Provide an explicit configuration block to read our long-format spreadsheet data (like `ml_predict_labels_Batch_05.xlsx`). Include clear top-level placeholder variables for the dataset path, the master list path, and the storage mount mount points.
3. **Audit Execution**: Call the freshly written audit utilities to display a comprehensive list of missing patents, missing figures, and pipeline anomalies grouped systematically per phase and per batch, displaying the reason 'why' they were isolated.
4. **Distribution Analytics**: Include a quick summary visualization or value count section showcasing high-level distributions of critical categorical parameters like "Topology Type" or structural markers.

Ensure all cell arrays are validly formatted JSON. Write out the finished notebook directly to disk."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT D — T2 INTERFACE BEHAVIOR FIXES & DATA CLEANING SUPPORT
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_D = f"""UNATTENDED TASK D — T2 BEHAVIOR FIXES AND DATA CLEANING.

{_HEADER}

Repo Target: `{_REPO}`
File to edit: `{_REPO}/{_FILE}`

{_DONT_REGRESS}

CONTEXT:
We are shifting to an architectural analysis using frozen DINOv2 embeddings. Background styles, over-assigned multi-tokens, and poorly sanitized image types inject visual style/viewpoint noise that can derail clustering algorithms. These additions directly isolate design signals.

CHANGE 1 — Make "Present Structural Elements (Visual Tokens)" SINGLE-select with a Multi-Toggle.
 - WHERE: pageT2(), inside the card titled "C. Present Structural Elements (Visual Tokens)". Tokens are managed via `ocArrFig('parts', p, p)`.
 - DO: Implement a layout variable `figData[fNum].partsMulti` (default = false).
     * Single Mode (Default): Clicking an unselected visual token sets `figData[fNum].parts = [clickedToken]`. Clicking it again empties the array to `[]`.
     * Multi Mode: Preserves original multi-select behavior.
     * Export Protection: Keep `parts` structurally formatted as an array to prevent breaking downstream `.xlsx` schemas or parsing via `recordToRows`.
 - UI ADDITION: Inject a small button ("Allow Multiple Tokens" ↔ "Enforce Single Token") at the top of Card C that flags `partsMulti`, updating via `renderPreserveScroll()`. If switching to Single when >1 tokens are active, truncate the array to element `[0]`.

CHANGE 2 — Figure Notes (EDGE_TOKENS) Rendered as Clickable Chips.
 - WHERE: pageT2(), inside the "Figure Notes" section containing `#t2-edge-tag-input` and `#edge-token-options`.
 - DO: Dynamically render all unique elements inside `EDGE_TOKENS` as clickable visual chips below the input bar. Clicking an idle chip directly updates `figGet(fNum, 'edgeTags')`, pushing it into the array and triggering a UI re-render. Keep the manual input box and standard deletion tags intact.

CHANGE 3 — DATA CLEANING CRITERIA: Add explicit "Bad Patent / Reject" Flag.
 - WHY: Low-quality drawings, generic text-only pages, or uninformative detail sheets must be easily tagged and removed from the pipeline.
 - WHERE: Add to T1 or T2 triage options where global metadata states are maintained.
 - DO: Add a standard boolean flag `isRejected` alongside a clear custom drop-down menu specifying the reason (e.g., "Bad Patent Illustration / Non-Aircraft Design / Text Only / Damaged File"). Ensure these export seamlessly as dedicated columns in your metadata schema.

{_VERIFY}

HANDOFF: Write a verification markdown report at `{_REPO}/UI_CHANGES_STATUS.md` detailing changes and state: "UI Task B (layout) can proceed." Stage and commit these updates."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT E — HIGH-DENSITY INTERFACE DESIGN
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_E = f"""UNATTENDED TASK E — HIGH-DENSITY INTERFACE ENGINEERING.

{_HEADER}

Repo Target: `{_REPO}`
File to edit: `{_REPO}/{_FILE}`

STEP 0 — READ THE HANDOFF FIRST: Read `{_REPO}/UI_CHANGES_STATUS.md` inside the repository to verify prior features persist perfectly.

{_DONT_REGRESS}
Preserve the single-select parts, Figure-Notes chips, and Reject flags implemented during Task D.

CHANGE 4 — High-Density 4-Column Layout for T2 (Drastically reduces scrolling footprint).
 - ARRANGEMENT CRITERIA:
     * Column 1: Active Main Figure Image (Large, high-resolution rendering canvas).
     * Column 2: Compact Figure Thumbnails Grid panel via `figGrid()`.
     * Column 3: Triage Elements Group 1 ("A. Projection Coordinates", "B. Image Rendering Style", Triage Info).
     * Column 4: Triage Elements Group 2 ("C. Present Structural Elements", "D. Image Quality", "Figure Notes" chips, Architecture Custom Allocation Block).
 - WHERE: pageT2() builds .t2-split with .t2-left and .t2-right; their CSS is near the top of the file.
 - DO: Restructure `.t2-split` into a multi-column flex/grid container with explicit CSS layout injection. Ensure each individual column is configured with independent vertical overflow scroll properties (`overflow-y: auto`), isolating long card expansions from shifting neighboring column positions. Include media-query fallback strategies for screen scaling protection.

CHANGE 5 — Sticky Main Figure Viewer for Morphology Classification (G1/M1/M2/M3).
 - DO: Extract the structural token or canonical main image designation via `S.mainFigure` and its reference path `FIG_IMAGE_PATH[S.mainFigure]`. Render a fixed, compact, floating image rail panel in a corner or side rail layout that remains pinned while the architectural forms scroll. 
 - FAILSAFE SAFETY: If `S.mainFigure` is missing or unassigned, query the patent configuration array and cleanly render the first approved, non-zero figure file. If no illustrations exist, elegantly suppress the block to prevent missing-image icon artifacts.
 - WHERE: render() already injects an "Architecture N of M" banner for steps ['gate','m1','m2','m3'] — add the image panel in that same area, preserving the banner completely.

{_VERIFY}

HANDOFF: Append structural layout changes to `{_REPO}/UI_CHANGES_STATUS.md` and commit layout modifications to the repository tree."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT F — STRUCTURAL COUPLING PERSISTENCE & SYSTEM CHANGE RESUME
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_F = f"""UNATTENDED TASK F — SYSTEM INTERACTION AUDIT & CHANGE SUMMARY.

{_HEADER}

Repo Target: `{_REPO}`

CRITICAL COMPREHENSION MANDATE:
Keep this core configuration architecture context in mind for our upcoming implementation stages: We have an operational scheduling engine (`timer_ui_changes.py`) orchestrating automated updates directly to our review wizard framework (`{_FILE}`). 

When we modify this pipeline or parse from source tables (`ml_predict_labels_Batch_05.xlsx`), we must ensure that any dataset flags generated by our new dataset overview notebook (like identifying missing records, missing figures, low-confidence evaluation entries, or 'human_required' fields) can easily be fed into or explicitly highlighted by the UI layout modifications scheduled in this script. Confirm you explicitly understand this pipeline connection.

FINAL DELIVERABLE — SUMMARY REPORT GENERATION:
Compile a clean, comprehensive, summary report detailing exactly every file modified or generated during this unattended overnight run. 

Write this complete operational summary directly to a file at the new repository root named:
`{_REPO}/PIPELINE_MODIFICATION_SUMMARY.md`

Organize the document using the following exact template:
- **Repository Setup Status**: Confirm configuration location and Git logging verification.
- **File Ingestion Table**: Grid displaying absolute paths, primary roles, and pass/fail execution checks.
- **Pipeline Inter-Connectivity Mapping**: Explaining how data anomaly flags raised inside `src/audit_utils.py` tie directly into visual highlights on your 4-column UI matrix layout.

No questions; execute, write the markdown summary, and terminate cleanly."""


# ─────────────────────────────────────────────────────────────────────────────
# Timer logic — clipboard paste (identical mechanism to timer.py)
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(msg)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def disable_sleep_and_lock():
    try:
        subprocess.run(["xset", "s", "off"], check=False)
        subprocess.run(["xset", "-dpms"], check=False)
        subprocess.run(["xset", "s", "noblank"], check=False)
        log("Disabled X11 screensaver/DPMS (best-effort).")
    except FileNotFoundError:
        log("WARNING: xset not found — could not disable screensaver/DPMS.")


def preflight():
    problems = []
    if not os.environ.get("DISPLAY"):
        problems.append("DISPLAY is not set — pyautogui cannot send keystrokes.")
    if os.environ.get("WAYLAND_DISPLAY"):
        problems.append("Running under Wayland — pyautogui/xdotool keystrokes usually do NOT work.")
    try:
        token = f"__timer_selftest_{int(time.time())}__"
        pyperclip.copy(token)
        time.sleep(0.2)
        if pyperclip.paste() != token:
            problems.append("Clipboard round-trip failed — install xclip or xsel.")
    except Exception as e:
        problems.append(f"Clipboard error: {e}")
    return problems


def _next_occurrence(hhmm: str) -> datetime.datetime:
    now = datetime.datetime.now()
    hh, mm = [int(x) for x in hhmm.split(":")]
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def send_prompt(label: str, text: str):
    log(f"Sending {label}...")
    pyperclip.copy(text)
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.8)
    pyautogui.press("enter")
    log(f"{label} sent! ({len(text)} chars)")


def wait_until(target_dt: datetime.datetime, label: str):
    log(f"Waiting until {target_dt.strftime('%Y-%m-%d %H:%M')} to send {label} "
        f"({(target_dt - datetime.datetime.now()).total_seconds()/60:.0f} min away)...")
    while datetime.datetime.now() < target_dt:
        remaining = (target_dt - datetime.datetime.now()).total_seconds()
        time.sleep(min(15, max(1, remaining)))


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    log("=" * 60)
    log("  Thesis Architecture Pipeline — Complete Repo & UI Automation")
    
    dt_a = _next_occurrence(TARGET_TIME_A)
    dt_b = _next_occurrence(TARGET_TIME_B)
    dt_c = _next_occurrence(TARGET_TIME_C)
    dt_d = _next_occurrence(TARGET_TIME_D)
    dt_e = _next_occurrence(TARGET_TIME_E)
    dt_f = _next_occurrence(TARGET_TIME_F)
        
    log(f"  Prompt A → {dt_a.strftime('%Y-%m-%d %H:%M')}  [Repo Infrastructure & Directory Scaffolding]")
    log(f"  Prompt B → {dt_b.strftime('%Y-%m-%d %H:%M')}  [Data Integrity Audit Engine Scripts]")
    log(f"  Prompt C → {dt_c.strftime('%Y-%m-%d %H:%M')}  [Automated Analytical Dataset Notebooks]")
    log(f"  Prompt d → {dt_d.strftime('%Y-%m-%d %H:%M')}  [T2 UI Behavior Updates & Reject Triage]")
    log(f"  Prompt E → {dt_e.strftime('%Y-%m-%d %H:%M')}  [High-Density 4-Column Responsive Layout]")
    log(f"  Prompt F → {dt_f.strftime('%Y-%m-%d %H:%M')}  [Pipeline Coupling Review & Change Summary]")
    log("=" * 60)

    problems = preflight()
    if problems:
        log("PRE-FLIGHT ERROR — Fix execution environment parameters:")
        for p in problems:
            log("   - " + p)
        raise SystemExit(1)

    disable_sleep_and_lock()
    log("\nREADY: Click inside the target Claude chat window input box to begin monitoring.\n")

    wait_until(dt_a, "Prompt A")
    send_prompt("Prompt A", PROMPT_A)

    wait_until(dt_b, "Prompt B")
    send_prompt("Prompt B", PROMPT_B)

    wait_until(dt_c, "Prompt C")
    send_prompt("Prompt C", PROMPT_C)

    wait_until(dt_d, "Prompt D")
    send_prompt("Prompt D", PROMPT_D)

    wait_until(dt_e, "Prompt E")
    send_prompt("Prompt E", PROMPT_E)

    wait_until(dt_f, "Prompt F")
    send_prompt("Prompt F", PROMPT_F)

    log("All structural pipeline components initialized and scheduled successfully.")