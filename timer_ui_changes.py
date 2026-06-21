"""
timer_ui_changes.py
Schedules two UNATTENDED prompts that improve the T2 page of the review wizard
(notebooks/UI_for_taxonomy_caracterization_10.0.html), pasted into VSCode Claude
via clipboard (same proven method as timer.py).

  Prompt A → behavior fixes  (single-select parts + clickable Figure-Notes tags)
  Prompt B → layout          (4-column T2 + main image on G1/M1/M2/M3)

Run A first, then B (B regroups the same markup A touches, so it must come second).

Usage:
  1. pip install pyautogui pyperclip
  2. Click inside the VSCode chat input so the cursor is blinking there.
  3. python timer_ui_changes.py
  4. Edit TARGET_TIME_A / TARGET_TIME_B below to the times you want.
"""

import os
import time
import datetime
import subprocess
import pyautogui
import pyperclip

# ── Set these to whenever you want each prompt to fire (24h HH:MM) ────────────
TARGET_TIME_A = "03:55"
TARGET_TIME_B = "04:10"   # leave a gap; B depends on A being finished
TARGET_TIME_C = "04:55"   # generous gap; C reviews the post-A/B state (read-only)

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overnight_logs")
LOG_PATH = os.path.join(LOG_DIR, "timer_ui.log")

# Shared unattended-safety header pasted at the top of both prompts.
_HEADER = """╔══════════════════════════════════════════════╗
║ SCHEDULED / UNATTENDED. The user may be away. Do NOT call AskUserQuestion / ║
║ EnterPlanMode or wait for approval — it hangs the run. Decide, act, verify,  ║
║ finish, leave one short report. If you truly cannot proceed safely, STOP   ║
║ and say why. Make reasonable choices and WRITE DOWN any assumption.        ║
╚══════════════════════════════════════════════╝"""

_FILE = "notebooks/UI_for_taxonomy_caracterization_10.0.html"
_REPO = "/home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent-Labelling-Tools"

_DONT_REGRESS = """DO NOT REGRESS the MULTI-ARCHITECTURE work already in this file. Keep ALL of it
intact: getArchCount(), saveCurArchProfile()/loadArchProfile(), the archProfiles[]/
curArch state, the T2 "Assign To" architecture dropdown + "+ Add architecture"
button + "Distinct Architectures" banner, the "Architecture N of M" banner injected
in render() for steps gate/m1/m2/m3, the per-architecture export ("_arch{N}" suffix
in recordToRows), and ingestPatentRows()/basePatentId()/archSuffixNum(). If a change
might touch these, leave them alone."""

_VERIFY = """VERIFY BEFORE FINISHING (do not skip):
 - Extract the largest <script> block and run `node --check` on it — it MUST pass.
 - Confirm braces {}, parens (), and brackets [] are balanced across the whole file
   (equal open/close counts).
 - If either check fails, REVERT your edits (restore from the backup you made) and
   report the failure — do NOT leave the file broken.
This is a STATIC HTML edit: do not run the notebook, models, or any batch."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT A — T2 behavior fixes
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_A = f"""UNATTENDED UI TASK A of B — T2 behavior fixes.

{_HEADER}

Repo: {_REPO}
File to edit (the ONLY file you may change): {_FILE}
It is one self-contained HTML file with a single large <script>.

STEP 0 — BACK UP FIRST: copy the file to
  {_FILE.replace('.html','.PRE_UICHANGE_A_<timestamp>.html')}
before editing. Do NOT overwrite an existing backup.

{_DONT_REGRESS}
Some changes from this prompt have already been done, beacause this prompt has already been fed. Continue them, you can see the history of this changes in this chat.
CHANGE 1 — Make "Present Structural Elements (Visual Tokens)" SINGLE-select, with an
edge-case button to allow multiple.
 - WHY: SigLIP over-assigns parts (it tags many elements on a single architectural-
   layout figure). The human should normally pick exactly ONE structural token, but
   be able to opt into multiple for genuine edge cases.
 - WHERE: pageT2(), the card titled "C. Present Structural Elements (Visual Tokens)"
   (search that exact string). Tokens are rendered with ocArrFig('parts', p, p) — a
   MULTI-select that stores figData[fNum].parts as an ARRAY (the option markup carries
   data-figarrfield="parts"). The export reads this array (recordToRows joins parts
   with "|"), so KEEP parts as an array — just constrain it to length 1 in single mode.
 - DO: add a per-figure flag figData[fNum].partsMulti (default falsy = single mode).
     * SINGLE mode: clicking a token SETS figData[fNum].parts = [thatToken] (replacing
       any previous); clicking the already-selected token clears it to []. (Radio-like.)
     * MULTI mode: keep today's toggle-in/out-of-array behavior.
   Branch on partsMulti inside the existing click handler for data-figarrfield="parts"
   (find where data-figarrfield is handled in the panel click listener).
 - ADD a small button in that card, e.g. "Allow multiple (edge case)" ↔ "Back to single",
   that toggles figData[fNum].partsMulti and re-renders (renderPreserveScroll). Show the
   current mode clearly. When switching multi→single with >1 token selected, keep only
   the first (comment this choice).

CHANGE 2 — Figure Notes custom tags as CLICKABLE CHIPS (parity with Structural Elements).
 - WHY: Structural-Elements custom tags (PART_TOKENS) reappear as one-click chips on
   every later figure; Figure-Notes tags (EDGE_TOKENS) only show as a <datalist>
   autocomplete, so the user must retype them. Make them one-click too.
 - WHERE: pageT2(), the "Figure Notes" card (search that string). It has a text input
   (#t2-edge-tag-input) + datalist (#edge-token-options) from EDGE_TOKENS, and renders
   already-applied tags as removable chips (data-remove-tag).
 - DO: render ALL EDGE_TOKENS as clickable chips (styled like the parts chips) in that
   card. Clicking a chip appends that tag to figGet(fNum,'edgeTags') if not already
   present, then re-renders. Keep the text input for CREATING new tags (the
   btn-add-edge-tag handler already pushes new tags into EDGE_TOKENS). Keep the existing
   removable applied-tag chips. The datalist may stay or be removed.

HARD CONSTRAINTS:
 - Edit ONLY {_FILE}. No Python, no other files, no config.
 - Backward-compatible storage: parts stays an array; edgeTags stays an array. Do NOT
   change the export row schema.
{_VERIFY}

HANDOFF: write a file at repo root UI_CHANGES_STATUS.md with a "## UI TASK A" section:
STATUS (DONE/FAILED+why), exactly what you changed (which functions/sections), any
assumption, and a final line "UI Task B (layout) can proceed." Keep it short — it is the
ONLY thing the layout agent (Task B) will see from you."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT B — T2 4-column layout + main image on morphology pages
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_B = f"""UNATTENDED UI TASK B of B — T2 4-column layout + main image on G1/M1/M2/M3.

{_HEADER}

Repo: {_REPO}
File to edit (the ONLY file you may change): {_FILE}

STEP 0 — READ THE HANDOFF FIRST: read UI_CHANGES_STATUS.md at the repo root (UI Task A
edited this same file; preserve its changes). THEN BACK UP: copy the file to
  {_FILE.replace('.html','.PRE_UICHANGE_B_<timestamp>.html')}
Do NOT overwrite an existing backup.

{_DONT_REGRESS}
ALSO preserve whatever UI Task A changed (single-select parts + Figure-Notes chips).

CHANGE 3 — 4-column T2 layout (less scrolling).
 - WHY: today T2 is 2 columns (.t2-split → .t2-left = image/context, .t2-right = all tag
   boxes stacked), forcing lots of vertical scrolling.
 - GOAL: a 4-column layout so the reviewer rarely scrolls:
     Col 1 = the ACTIVE figure image (large),
     Col 2 = the figure thumbnail list (figGrid()),
     Col 3 = tag boxes group 1 (e.g. "A. Projection Coordinates" + "B. Image Rendering Style"),
     Col 4 = tag boxes group 2 (e.g. "C. Present Structural Elements" + "D. Image Quality"
             + "Figure Notes" + the architecture "Assign To"/"+ Add architecture" panel).
 - WHERE: pageT2() builds .t2-split with .t2-left and .t2-right; their CSS is near the top
   of the file (search ".t2-split", ".t2-left", ".t2-right"). figGrid() renders thumbnails;
   the active image is in the context/left panel.
 - DO: restructure pageT2's container into 4 columns (CSS grid or flex) and add the CSS.
   Distribute the EXISTING cards across the columns — do NOT delete any card (perspective,
   rendering, structural elements, quality, figure notes, duplicate cross-reference, the
   architecture assignment panel). Keep every existing id, data-attribute and handler
   intact — only MOVE/REGROUP markup, do not rewrite the controls. Make each column
   independently scrollable so one long column doesn't stretch the others. Keep it
   responsive (stack on narrow widths, like the existing @media (max-width:768px) rule).

CHANGE 4 — Show the MAIN figure image on the G1/M1/M2/M3 pages.
 - WHY: while classifying architecture the reviewer currently can't see the drawing.
 - DO: on the morphology pages (step ids 'gate','m1','m2','m3'), show the MAIN figure
   image: S.mainFigure, whose path is FIG_IMAGE_PATH[S.mainFigure], converted to a URL
   via the existing file-url helper used in T2 (search FIG_IMAGE_PATH usage / pathToFileURL).
   Render it as a COMPACT, STICKY panel (e.g. a top-right card or a side rail) that stays
   visible while the form scrolls. If S.mainFigure is unset, fall back to the first
   approved/available figure; if there is no usable image, render nothing (no broken <img>).
 - WHERE: render() already injects an "Architecture N of M" banner for steps
   ['gate','m1','m2','m3'] — add the image panel in that same area (or inside each page
   function), but do NOT disturb that banner.

HARD CONSTRAINTS:
 - Edit ONLY {_FILE}. No Python/other files.
 - Layout only: do NOT change any export schema, control id, or handler logic.
{_VERIFY}

HANDOFF: append a "## UI TASK B" section to UI_CHANGES_STATUS.md at repo root: STATUS,
what changed, assumptions, and confirm UI Task A's changes were preserved."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT C — extensive REVIEW of the Stage-01 review/save methodology (read-only)
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_C = f"""UNATTENDED REVIEW TASK C — extensive, READ-ONLY audit of the Stage-01 human-review
+ save methodology (the HTML wizard, the reviewed-xlsx save path, and the labeling
heuristics). This is a REVIEW that produces a written report; it does NOT change code.

{_HEADER}

Repo: {_REPO}
Key files to study:
 - {_FILE}  (the review wizard; one big <script>)
 - src/excel_schema.py  (build_patent_rows / export_source_excel — the PYTHON side that
   writes ml_predict_labels_<batch>.xlsx and defines COLUMNS)
 - src/reviewer.py  (process_patent, resolve_g1, classify_g1_keyword, _margin_flag,
   confidence_routing usage, the M1/M2/M3 SBERT classifiers)
 - src/cross_modal.py  (SigLIP T2/G1/M classifiers + the option vocabularies)
 - notebooks/01_review.ipynb  (the batch runner + "Finalize this batch" cells)
 - config.yaml  (confidence_routing thresholds, paths)
 - OVERNIGHT_STATUS.md  (prior Task 1/2/3 context — read it for background)

SCOPE — do ALL FOUR parts and write ONE thorough report.

PART 1 — SAVE-PATH + FIELD-COVERAGE AUDIT (the highest-value part; be exhaustive).
 - Trace the full save path in the wizard: every reviewer-editable field
   (S.* state + figData[fNum] per-figure) → buildExport() → recordToRows() →
   REVIEWED_ROWS → exportReviewedBatch() (SheetJS XLSX.writeFile) →
   reviewed_patents_<batch>.xlsx. Then the reload path: rowsToAIData() → ingestAI() /
   ingestPatentRows() → loadBatchPatent().
 - Build an explicit field-by-field table: for EVERY field the human can set in the UI
   (T1 triage: isApproved/disapprove reason+other/scope/field/target/aircraftName/
   duplicate flags/duplicateType/archCount; T2 per-figure: per/acSty/acCol/bgSty/bgCol/
   parts/edgeTags/comment/status/rotation/quality/dupOfPatent/dupOfFig/hasLegends/arch
   assignment/mainFigure; G1 topType; M1/M2/M3 incl. per-wing wing{{i}}_* and per
   propulsion-card component_* fields, notes), mark whether it is (a) captured in
   buildExport, (b) emitted by recordToRows, (c) restored by the reload path. FLAG any
   field that is set in the UI but LOST on save, or saved but LOST on reload — that is
   silent data loss and is the #1 thing to find.
 - KNOWN LEAD TO CONFIRM: the wizard's EXCEL_COLUMNS is 10 columns and does NOT include
   "Needs_Review", but src/excel_schema.py COLUMNS has 11 and DOES. Determine: does the
   reviewed export drop Needs_Review? Does anything downstream rely on it? Is that a bug
   or harmless? Also confirm any extra rows (META section, pdf_link) survive or are
   silently dropped by json_to_sheet(header=EXCEL_COLUMNS).
 - CONFIRM the just-added multi-architecture round-trip: a patent with 2+ architectures
   exports G1/M rows as Patent_ID_arch1/_arch2 and reloads (ingestPatentRows rebuilds
   archProfiles). Verify nothing is lost across that round-trip.

PART 2 — XLSX SAVE CORRECTNESS / BUG HUNT.
 - exportReviewedBatch uses XLSX.utils.json_to_sheet(rows, {{header: EXCEL_COLUMNS}}).
   Check edge cases: fields in rows NOT listed in EXCEL_COLUMNS (dropped silently?),
   boolean values (true/false vs "true"/"false" — see xlBool on reload), null/empty,
   values containing "|" or "," or newlines or quotes, very long description text,
   non-ASCII patent text. Note any that corrupt or mis-round-trip.
 - Check commitReviewedRows() dedup (the basePatentId filter) is correct for re-saving a
   patent (incl. multi-arch) without leaving stale rows or duplicating.
 - Compare the PRODUCER schema (src/excel_schema.build_patent_rows, the ml_predict_labels
   the wizard LOADS) against the wizard's loader (rowsToAIData field names). List any
   field-name drift where the Python writes a field the HTML never reads, or vice-versa.

PART 3 — LABELING HERISTIC REVIEW (identify + assess + RECOMMEND; do NOT change code).
 For each heuristic below: state what it does, where it lives, whether it is sound, and a
 concrete recommendation (keep / retune / change). The user is open to changing these.
 - Auto-approval: isApproved=true when avg T1 scope/field/target confidence >= 0.45
   (src/excel_schema.py). Is 0.45 right? Risk of auto-approving out-of-domain patents.
 - Physics locks: TP -> propKin=Tilt; TW -> empKin=Fixed + wing orient Horizontal;
   RC/MR -> wTilt=null; SLC/SRW -> strip "Mixed" orient (excel_schema.py + ingestAI in
   the HTML). Are these always physically correct? Any topology where they over-constrain?
 - confidence_routing thresholds (config.yaml: G1 0.45 / M1 0.40 / M2 0.40 / M3 0.35 /
   T2 0.35) and _margin_flag (_MARGIN_FLAG_THRESHOLD 0.05, low-conf 0.45). Calibrated, or
   guesses? Recommend how to calibrate from the actual confidence distribution.
 - G1 resolution: resolve_g1 (text-primary, vision-tiebreaker) + classify_g1_keyword
   priors (_G1_KEYWORD_RULES). Any keyword with false-positive risk? Any topology the
   keyword set misses?
 - KNOWN ISSUES from prior audits (see OVERNIGHT_STATUS.md "## TASK 3"): SigLIP
   over-assigns T2 parts, and over-labels acSty as "Render" (~85% of figures) when most
   patent drawings are line art. Assess root cause and recommend a fix (e.g. prompt
   reweighting, a prior, or defaulting acSty=Line Drawing).

PART 4 — TEST PLAN before committing to full-batch labeling.
 Produce a concrete, ordered, runnable test plan, e.g.: label a small "golden set"
 (include one multi-architecture patent, one Disapproved, one Duplicate, one no-figure
 patent) in the wizard; export; reload the reviewed xlsx and diff to prove the round-trip
 is lossless; open the xlsx and spot-check ~10 fields against what was entered; run a
 schema/vocabulary validator on the reviewed xlsx (adapt scripts/overnight_audit.py);
 confirm every Value is a legal option; confirm images resolve. Make it a checklist the
 user can actually follow in 30 minutes.

CONSTRAINTS:
 - READ-ONLY. Do NOT modify the HTML, any .py, the notebook, or config. You are
   reviewing and recommending, not fixing. (Heuristic changes are the user's call.)
 - The ONLY file you may write is the report (next line).
 - No questions; decide and produce the report.

OUTPUT / HANDOFF: write a thorough markdown report at the repo root:
  {_REPO}/REVIEW_01_METHODOLOGY.md
Organize it as: (1) Executive summary with a findings table sorted by SEVERITY
(CRITICAL = silent data loss / save bug; HIGH = round-trip or schema drift; MEDIUM =
heuristic concern; LOW = nit), (2) the four parts above with specifics and exact
file:function references, (3) the test-plan checklist. Be concrete and cite line/function
names so the user can act on each item directly."""


# ─────────────────────────────────────────────────────────────────────────────
# Timer logic — clipboard paste (identical mechanism to timer.py)
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(msg)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def disable_sleep_and_lock():
    """Best-effort: stop X screensaver/DPMS so focus isn't stolen mid-paste.
    NOTE: this does NOT stop a separate lock manager (gnome-screensaver,
    light-locker, xscreensaver). If the screen LOCKS overnight the paste lands
    nowhere — disable the lock screen manually before leaving."""
    try:
        subprocess.run(["xset", "s", "off"], check=False)
        subprocess.run(["xset", "-dpms"], check=False)
        subprocess.run(["xset", "s", "noblank"], check=False)
        log("Disabled X11 screensaver/DPMS (best-effort).")
    except FileNotFoundError:
        log("WARNING: xset not found — could not disable screensaver/DPMS.")


def preflight():
    """Fail LOUDLY at startup if the paste mechanism can't possibly work, so a
    broken setup is caught now instead of silently doing nothing overnight."""
    problems = []
    if not os.environ.get("DISPLAY"):
        problems.append("DISPLAY is not set — pyautogui cannot send keystrokes.")
    if os.environ.get("WAYLAND_DISPLAY"):
        problems.append("Running under Wayland — pyautogui/xdotool keystrokes "
                        "usually do NOT work. Use an X11 session.")
    # Verify clipboard actually round-trips (pyperclip needs xclip or xsel).
    try:
        token = f"__timer_selftest_{int(time.time())}__"
        pyperclip.copy(token)
        time.sleep(0.2)
        if pyperclip.paste() != token:
            problems.append("Clipboard round-trip failed — install xclip or xsel.")
    except Exception as e:
        problems.append(f"Clipboard error: {e} — install xclip or xsel.")
    return problems


def _next_occurrence(hhmm: str) -> datetime.datetime:
    """Resolve 'HH:MM' to the NEXT datetime it occurs: today if still ahead,
    otherwise tomorrow. This is the key fix over the old exact-string match —
    starting the script a minute late no longer means waiting ~24h by accident,
    and a time you set for 'tonight' always resolves to the upcoming one."""
    now = datetime.datetime.now()
    hh, mm = [int(x) for x in hhmm.split(":")]
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def send_prompt(label: str, text: str):
    log(f"Sending {label}...")
    pyperclip.copy(text)
    time.sleep(0.5)                     # let clipboard settle
    pyautogui.hotkey("ctrl", "v")       # paste whole prompt atomically
    time.sleep(0.8)                     # let the UI receive it
    pyautogui.press("enter")            # submit
    log(f"{label} sent! ({len(text)} chars)")


def wait_until(target_dt: datetime.datetime, label: str):
    """Fire when now >= target (robust to a missed exact minute / brief sleep)."""
    log(f"Waiting until {target_dt.strftime('%Y-%m-%d %H:%M')} to send {label} "
        f"({(target_dt - datetime.datetime.now()).total_seconds()/60:.0f} min away)...")
    while datetime.datetime.now() < target_dt:
        remaining = (target_dt - datetime.datetime.now()).total_seconds()
        time.sleep(min(15, max(1, remaining)))   # tighten cadence near the deadline


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    log("=" * 60)
    log("  Wizard T2 UI changes — prompt timer")

    # Resolve absolute fire times up front and PRINT them so you can confirm
    # they're when you expect before walking away.
    dt_a = _next_occurrence(TARGET_TIME_A)
    dt_b = _next_occurrence(TARGET_TIME_B)
    if dt_b <= dt_a:   # keep B strictly after A even across a midnight roll
        dt_b += datetime.timedelta(days=1)
    dt_c = _next_occurrence(TARGET_TIME_C)
    if dt_c <= dt_b:   # keep C strictly after B
        dt_c += datetime.timedelta(days=1)
    log(f"  Prompt A → {dt_a.strftime('%Y-%m-%d %H:%M')}  (behavior: single-select parts + Figure-Notes chips)")
    log(f"  Prompt B → {dt_b.strftime('%Y-%m-%d %H:%M')}  (layout: 4-column T2 + image on G1/M1/M2/M3)")
    log(f"  Prompt C → {dt_c.strftime('%Y-%m-%d %H:%M')}  (read-only review of save methodology + heuristics)")
    log(f"  Gaps: A→B {(dt_b - dt_a).total_seconds()/60:.0f} min, "
        f"B→C {(dt_c - dt_b).total_seconds()/60:.0f} min "
        f"(each gap must exceed how long the previous agent runs)")
    log("=" * 60)

    problems = preflight()
    if problems:
        log("PRE-FLIGHT FAILED — the paste will NOT work. Fix these and re-run:")
        for p in problems:
            log("   - " + p)
        raise SystemExit(1)
    log("Pre-flight OK: DISPLAY set, X11, clipboard round-trips.")

    disable_sleep_and_lock()

    log("")
    log("NOW: click inside the VSCode chat input so the cursor is blinking there,")
    log("     make sure the screen will NOT lock, then leave it untouched.")
    log("")

    wait_until(dt_a, "Prompt A")
    send_prompt("Prompt A", PROMPT_A)

    wait_until(dt_b, "Prompt B")
    send_prompt("Prompt B", PROMPT_B)

    wait_until(dt_c, "Prompt C")
    send_prompt("Prompt C", PROMPT_C)

    log("All three prompts sent.")
