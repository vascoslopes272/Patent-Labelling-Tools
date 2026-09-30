"""
timer_analysis_battery.py
Schedules six UNATTENDED prompts (A → B → C and D → E → F) that build and refine 
the eVTOL structural taxonomy and execute the Core Analysis Battery, pasted 
into VSCode Claude via clipboard.

Usage:
  1. pip install pyautogui pyperclip
  2. Click inside the VSCode chat input so the cursor is blinking there.
  3. python timer_analysis_battery.py
  4. Edit target times below to the times you want.
  5. Edit the <<EDIT-ME>> placeholders in the configurations below before firing.
"""

import os
import time
import datetime
import subprocess
import pyautogui
import pyperclip

# ── TAXONOMY SUITE TARGET TIMES (24h HH:MM) ──────────────────────────────────
TARGET_TIME_A = "02:40"   # Taxonomy Design
TARGET_TIME_B = "03:30"   # Adversarial Review
TARGET_TIME_C = "04:30"   # Hard Configuration Stress-Testing

# ── CORE ANALYSIS SUITE TARGET TIMES (24h HH:MM) ──────────────────────────────
TARGET_TIME_D = "23:20"   # Labels layer (fastest; XLSX -> parquet + QC)
TARGET_TIME_E = "23:20"   # Probe battery — leave generous gap; E depends on D
TARGET_TIME_F = "23:20"   # Clustering + retrieval + visuals — F depends on D and E

# Folder constraint containment
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Patent-Labelling-Tools")
LOG_PATH = os.path.join(LOG_DIR, "timer_analysis.log")

# ── CORE ANALYSIS SUITE CONFIGURATION PARAMETERS ─────────────────────────────
_REPO = ""
_LABELS_EXPORT_GLOB = ""
_META_PATH = ""
_META_COL_PATENT_ID = ""
_META_COL_ASSIGNEE = ""
_META_COL_YEAR     = ""

# Shared unattended-safety header pasted at the top of the core analysis battery prompts.
_HEADER = """╔══════════════════════════════════════════════════════════════════════════╗
║ SCHEDULED / UNATTENDED. The user may be away. Do NOT call AskUserQuestion / ║
║ EnterPlanMode or wait for approval — it hangs the run. Decide, act, verify,  ║
║ finish, leave one short report. If you truly cannot proceed safely, STOP   ║
║ and say why. Make reasonable choices and WRITE DOWN any assumption.        ║
╚══════════════════════════════════════════════════════════════════════════╝"""

_HARD_RULES = """HARD RULES (apply to every task in this sequence):
 - Raw input files are IMMUTABLE — never modify or delete them.
 - Thin notebooks: only import/call/display from src/. No business logic inline.
 - All paths via src/config_loader.py -> config.yaml (paths: block, optional
   $DRIVE_PATH from .env). No hardcoded paths anywhere.
 - Environment: conda env doclayout_yolo2, torch 2.5.1, transformers >=4.35,<5.0.
 - Surgical, minimal diffs. New functionality goes in NEW files; do not refactor
   working modules."""

_DONT_TOUCH = """DO NOT MODIFY these existing files (they are the historical record of the
binary shrouded/open study and must remain intact):
 - src/analysis.py                 (Stage-1 binary machinery: binary_labels(),
                                    permutation_separation, structure_report, etc.)
 - notebooks/11_structure_separation.ipynb
You may READ them for conventions (statistical discipline: never in-sample scores,
PCA before probing because p >> n, permutation nulls) — but you may not edit them."""

_VERIFY_PYTHON = """VERIFY BEFORE FINISHING (do not skip):
 - `python -m py_compile` passes on every new .py file.
 - Execute the new notebook end-to-end with `jupyter nbconvert --to notebook
   --execute --inplace` on a SMOKE subset first (see task-specific smoke knob),
   then launch the full run.
 - Sanity assertions listed per task must actually run and pass in code
   (assert statements, not just prose).
 - If the full run cannot finish in the session, leave the cache resumable
   and document EXACTLY how to resume in the report."""


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_A = """ Continue please, i am not here to answer anythign, so move one with tthe things you believe are good and anser ust wahat you fif so i can confimr if it is ok """

PROMPT_B = f""""{_HEADER}

{_HARD_RULES}

{_DONT_TOUCH}

# Task: Extend notebook 02a — codebook v2.0 conversions, worklists, and validations

## Role & ground rules
You are extending the existing preprocessing/QA notebook (02a) that operates on the reviewed
labelling excels. It implements the codebook v2.0 decisions closed 2026-07-20.
- NEVER modify raw patent images or original reviewed excel files in place — always write
  corrected copies / new columns / separate worklist files.
- Every automated fix must print a count of affected rows and write a log entry
  (rule ID, date, n affected) — these logs feed the thesis change-log table.
- **If unsure which column/sheet holds a value, ASK — do not guess.**

## A. Automated conversions (no human input)

### A1 — AC_STATE auto-set for fixed architectures (PR-04/05)
For every figure belonging to a patent with `topType ∈ (SLC, SRW, RC, MR, HB, PFV)`:
set state = `HoverCruise` ("Hover & Cruise (state-invariant)"), REGARDLESS of previous value.
Log previous-value distribution before overwriting (keep a `state_legacy` column).

### A2 — EMP_KIN → empTilts flag (PR-06)
New boolean column `empTilts`: `Tilt` or `Stabilator` → True (+ copy old value into notes as
"legacy: <value>"); `Fixed`/empty → False. Freeze old `EMP_KIN` column as `EMP_KIN_legacy`.

### A3 — TB ⇒ TiltBody auto-fix (PR-12 #7 Hard)
All patents with `topType = TB`: set `FUS_KIN = TiltBody`. Log count + previous values.

### A4 — Duplicate type rename (PR-02)
Map duplicate-type labels to D1/D2/D3 wording. Assert count of type-4 == 0; if any exist,
STOP and output the list (annotator expects zero — nonzero means something is wrong).

## B. Directed re-pass worklists (output = list of patent/figure IDs for the human)

### B1 — AC_STATE manual worklist (PR-04)
Figures of CONVERTIBLE patents (`topType ∈ (TW, TP, DS, CVT, TB, PTC)`) whose stored state is
`Ground`, `Other`, `Unclear`, or `NonApplicable`. These get re-labelled by mechanism-wins rule.

### B2 — FUS_KIN VarInc/TiltBody re-check (R-06 reversal)
All patents with `FUS_KIN ∈ (VarInc, TiltBody)` (any spelling variant, incl. legacy
"Variable — Variable Incidence / Tilting Body" strings — normalize first, list variants found).
The annotator suspects systematic reversal; DO NOT auto-swap. Output side-by-side worklist
(patent ID, current value, main-figure path if available). Exclude TB patents already fixed by A3.

### B3 — Empennage/fuselage mount audit (PR-07)
Patents where any M3 mount / fuselage_zone ∈ (Empennage, Aft/tail variants, Fuselage-rear).
New rule: empennage iff stabilizing surfaces present; bare tailcone = fuselage. Output worklist.

### B4 — X-boom sweep (PR-03)
Grep notes/comments for X-format mentions (case-insensitive: 'x format', 'x-format', 'em x',
'X booms', etc.) on patents NOT already migrated; output any stragglers.

## C. Validation suite (PR-12 rule table → per-rule worklists)

Implement as a rules table looped over patents; each rule outputs its own flagged list.
HARD (data error — must be fixed):
- H1 `topType=SLC` & any propulsor `propKin=Tilt`
- H2 `topType∈(MR,RC)` & wing count > 0
- H3 `topType=CVT` & NOT (has Fixed AND has Tilt propulsors [or wing-tilt+rotor-tilt combo])  ← existing PR-11 check, fold in
- H4 `topType=TW` & no wing with `W_TILT=Tilt`
- H5 `topType=TB` & `FUS_KIN≠TiltBody` (should be empty after A3 — assert)
- H6 `topType=DS` & any propulsor `propKin≠Fixed`
SOFT (warning — eyeball list):
- S1 `topType=TP` & any wing `W_TILT=Tilt` (legitimate iff folding/clearance tilt per R-18 — check note exists)
- S2 `topType=SRW` & (propulsor count high OR no central large-rotor pattern)

## D. Integrity checks

- D1 Completeness: every APPROVED patent has all required fields for its `topType`
  (derive "required" from the wizard's blocker logic — ask if unclear). Output missing-field report.
- D2 `BOOM_POS` migration completeness: zero records still carrying an old-style combined
  boom-position value. Report result — HTML v14's C6 deletion is conditional on this passing.
- D3 UAVSimilar × duplicates (PR-14): list duplicate groups containing ≥1 `UAVSimilar` patent,
  tags side-by-side. Rule: tag must MATCH within D1/D2 pairs; independent for D3. Flag mismatches.
- D4 Image-path joining: verify every kept figure resolves to an existing image file; report misses.

## Output
One summary cell at the end: per section, counts (converted / flagged / clean) — formatted so the
numbers can be pasted directly into the thesis change-log table.

Before you do any change, we need to talk, because i belive i forgot some changes i did alrad on this notebook,so lets see what is already done, what is imconatible wihht waht we already done to 02a (i belive nothing ahah) and then, i can agree and you mov eon 
{_VERIFY_PYTHON} """

# (Assuming PROMPT_C, D, E, F are defined elsewhere or you will paste them in)
PROMPT_C = """ {_HEADER}

{_HARD_RULES}

{_DONT_TOUCH}

# Task: Audit the codebook v2.0 implementation (wizard v14 + notebook 02a)

## Role
You are an independent auditor. Both change-sets have been implemented — the wizard
(`UI_for_taxonomy_caracterization_14_0.html`, generated from `prompt_html_v13_to_v14.md`) and
the preprocessing notebook 02a (extended from `prompt_notebook_02a.md`). Your job is to verify
the implementation against those two prompt files, which are the ground-truth specification.
**Report findings — do NOT fix anything in this pass** unless explicitly trivial (typo-level) and
you flag it. The pipeline is live; silent changes are worse than reported bugs.

## Context you must read first
1. `prompt_html_v13_to_v14.md` — the HTML specification (changes C1–C8 + acceptance checklist)
2. `prompt_notebook_02a.md` — the notebook specification (sections A–D + output requirement)
3. `UI_for_taxonomy_caracterization_13_0.html` — frozen baseline (must be byte-identical to before)
4. `UI_for_taxonomy_caracterization_14_0.html` — the implementation under audit
5. The modified notebook 02a
If any of these files is missing or you find multiple candidate versions, STOP and ask.

## Known execution-order deviation (audit priority #1)
The HTML prompt was executed BEFORE notebook 02a, although C6 (deletion of the `BOOM_POS`
migration shim) was conditional on 02a's check D2 passing first. Verify explicitly:
- What did the v14 implementation do with C6? (a) left shim untouched, (b) asked and waited,
  or (c) deleted it anyway?
- If (c): report as CRITICAL with the exact code that must be restored from v13 (the `BOOM_POS`
  array and its ingest branch).
- What does 02a's D2 check report when run? If D2 passes AND the shim was deleted, downgrade
  to WARNING (outcome accidentally fine, but record it).

## Audit A — HTML v14 vs spec (walk C1–C8 one by one)
For each change C1–C8: implemented? exactly as specified? anything extra added that the spec
didn't ask for? Then execute the spec's acceptance checklist items and report pass/fail each:
- v13 file byte-identical to its previous state (hash/diff it)
- an old v13-format saved record loads without errors; retired fields ingest silently
- fixed-architecture patent (SLC/SRW/RC/MR/HB/PFV): T2 shows non-interactive
  "Hover & Cruise (state-invariant)" badge; state question never asked
- convertible patent (TW/TP/DS/CVT/TB/PTC): exactly four state options
  (Hover/Transition/Cruise/Other) with the mechanism-wins tooltip
- TB patent: FUS_KIN locked to TiltBody, non-editable
- CVT patent with only tilting propulsors: completion blocked with a clear message
- DS patent: propKin locked Fixed; TW patent without any tilting wing: M2 completion blocked
- MR/RC patent: wing cards hidden / count locked to 0
- empennage: no Fixed/Tilt/Stabilator selector; unticked "Empennage tilts" checkbox by default;
  ticking makes the note a blocker
- DUP_TYPES shows D1/D2/D3 wording, internal ids still 1/2/3, no type 4 selectable;
  a legacy type-4 record ingests without crashing
- BOOM_ORIENT contains the X / Diagonal option with the crossing-criterion tooltip
- export contains `empTilts`, contains NO tilt-in-view or EMP_KIN choice columns
- R-06 tooltip near FUS_KIN and the main-figure=cruise tooltip near ★ both present

## Audit B — notebook 02a vs spec (walk A1–A4, B1–B4, C-suite H1–H6/S1–S2, D1–D4)
For each item: implemented? Does it write NEW columns/copies rather than overwriting originals?
Does every automated fix print a count and write a log entry (rule ID, date, n)? Specifically:
- A1 keeps a `state_legacy` column and logs the previous-value distribution
- A4 ASSERTS zero type-4 duplicates and stops with a list if nonzero
- B2 does NOT auto-swap VarInc/TiltBody — worklist only, with normalization of legacy spellings
- B2 excludes TB patents already auto-fixed by A3
- H5 asserts empty after A3
- Soft rules S1/S2 produce warnings/worklists, never modify data
- Final summary cell exists and outputs per-section counts in a paste-able table

## Audit C — cross-consistency HTML ↔ notebook (the drift check)
These two artifacts were generated in separate passes; verify they agree on:
1. The exact id/string for the invariant state (`HoverCruise` vs any variant) — HTML badge,
   HTML export, and 02a's A1 must write/read the SAME token.
2. The fixed-vs-convertible architecture sets — both must use
   fixed = {SLC, SRW, RC, MR, HB, PFV}, convertible = {TW, TP, DS, CVT, TB, PTC}. Any deviation
   (e.g. PTC placed in fixed somewhere) is CRITICAL.
3. `empTilts` column name and boolean encoding identical in HTML export and 02a A2.
4. Duplicate-type ids: HTML keeps internal 1/2/3; 02a's A4 rename maps the same ids.
5. Lock parity: every Hard rule enforced in HTML (L3–L7 + existing propKinLock) has a matching
   02a check (H1–H6) with the SAME logic — same fields, same architecture codes. Soft rules
   exist ONLY in 02a, not as HTML blocks.
6. Legacy AC_STATE values (`Ground`,`Unclear`,`NonApplicable`): HTML maps to Other for display
   while preserving raw stored values; 02a's B1 worklist is built from the RAW values. Confirm
   the raw values survive an open-and-resave cycle in v14 (this is the subtle one — test it).

## Audit D — scope discipline
Diff v13 → v14 and the old → new notebook. List EVERY change not traceable to a spec item
(C1–C8 / A–D). Unrequested "improvements" are findings, even if they look harmless.

## Output format
One report, grouped: CRITICAL (breaks data or violates a Hard decision) / MAJOR (spec item
missing or wrong) / MINOR (cosmetic, naming, tooltips) / NOTES (observations, no action).
For each finding: spec item ID, file + location, what was expected, what was found, proposed
fix direction (description only — no code changes in this pass).
End with the acceptance checklist as a pass/fail table and a one-line verdict:
SAFE TO LABEL / FIX FIRST.

## If anything is ambiguous — ASK
Unsure which file is authoritative, whether something is intentional, or what a spec line means:
ask the annotator before concluding. Do not guess, and do not mark items pass by assumption.

"""
PROMPT_D = """ """
PROMPT_E = """ """
PROMPT_F = """ """


# ─────────────────────────────────────────────────────────────────────────────
# CORE EXECUTION UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(msg)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def disable_sleep_and_lock():
    """Best-effort prevention of screensaver locks to safeguard window focus."""
    try:
        subprocess.run(["xset", "s", "off"], check=False)
        subprocess.run(["xset", "-dpms"], check=False)
        subprocess.run(["xset", "s", "noblank"], check=False)
        log("Disabled X11 screensaver/DPMS parameters.")
    except FileNotFoundError:
        log("WARNING: xset executable missing — could not adjust screensaver settings.")


def preflight():
    """Validates baseline OS interface environments and configuration flags."""
    problems = []
    if not os.environ.get("DISPLAY"):
        problems.append("DISPLAY environment variable unset — pyautogui GUI actions missing.")
    if os.environ.get("WAYLAND_DISPLAY"):
        problems.append("Wayland display server detected — standard hotkeys may fail. Switch to X11.")
    try:
        token = f"__timer_selftest_{int(time.time())}__"
        pyperclip.copy(token)
        time.sleep(0.2)
        if pyperclip.paste() != token:
            problems.append("Clipboard interface mismatch — verify xclip or xsel configurations.")
    except Exception as e:
        problems.append(f"Clipboard operational breakdown: {e}")
        
    # Check for placeholder edits inside user variables
    if "<<EDIT-ME" in _REPO:
        problems.append(f"_REPO path includes unmodified placeholder tag: {_REPO}")
    if "<<EDIT-ME" in _LABELS_EXPORT_GLOB:
        problems.append(f"_LABELS_EXPORT_GLOB path includes unmodified placeholder tag: {_LABELS_EXPORT_GLOB}")
    if "<<EDIT-ME" in _META_PATH:
        problems.append(f"_META_PATH path includes unmodified placeholder tag: {_META_PATH}")
        
    return problems


def _next_occurrence(hhmm: str) -> datetime.datetime:
    """Computes the next logical occurrence of an arbitrary 24h timestamp."""
    now = datetime.datetime.now()
    hh, mm = [int(x) for x in hhmm.split(":")]
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def send_prompt(label: str, text: str):
    log(f"Transmitting prompt sequence: {label}...")
    pyperclip.copy(text)
    time.sleep(0.5)                     
    pyautogui.hotkey("ctrl", "v")       
    time.sleep(0.8)                     
    pyautogui.press("enter")            
    log(f"{label} transmission pipeline executed successfully ({len(text)} characters compiled).")


def wait_until(target_dt: datetime.datetime, label: str):
    """Execution block loop that holds thread processing until target datetime bounds meet."""
    log(f"Holding pipeline for {label}. Fire scheduled at {target_dt.strftime('%Y-%m-%d %H:%M')} "
        f"({(target_dt - datetime.datetime.now()).total_seconds()/60:.1f} minutes remaining)...")
    while datetime.datetime.now() < target_dt:
        remaining = (target_dt - datetime.datetime.now()).total_seconds()
        time.sleep(min(15, max(1, remaining)))


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    log("=" * 70)
    log("  Unified Master Analysis Battery — Automation Pipeline")
    log("=" * 70)

    # 1. Resolve day-roll constraints internal to separate suites
    dt_a = _next_occurrence(TARGET_TIME_A)
    dt_b = _next_occurrence(TARGET_TIME_B)
    if dt_b <= dt_a:
        dt_b += datetime.timedelta(days=1)
    dt_c = _next_occurrence(TARGET_TIME_C)
    if dt_c <= dt_b:
        dt_c += datetime.timedelta(days=1)

    dt_d = _next_occurrence(TARGET_TIME_D)
    dt_e = _next_occurrence(TARGET_TIME_E)
    if dt_e <= dt_d:
        dt_e += datetime.timedelta(days=1)
    dt_f = _next_occurrence(TARGET_TIME_F)
    if dt_f <= dt_e:
        dt_f += datetime.timedelta(days=1)

    # 2. Consolidate and sort across the global timeline
    master_timeline = [
        (dt_a, "Prompt A (Taxonomy Design)", PROMPT_A),
        (dt_b, "Prompt B (Adversarial Review)", PROMPT_B),
        (dt_c, "Prompt C (Stress-Testing)", PROMPT_C),
        (dt_d, "Prompt D (Labels Layer Process)", PROMPT_D),
        (dt_e, "Prompt E (Probe Battery Matrix)", PROMPT_E),
        (dt_f, "Prompt F (Cluster/Retrieval Evaluation)", PROMPT_F),
    ]
    master_timeline.sort(key=lambda item: item[0])

    # Print planned sequence for confirmation
    for idx, (target_time, label, _) in enumerate(master_timeline, start=1):
        log(f"  [{idx}] Scheduled: {target_time.strftime('%Y-%m-%d %H:%M')} ➔ {label}")
    log("=" * 70)

    # Preflight evaluations
    problems = preflight()
    if problems:
        log("PRE-FLIGHT CHECKS FAILURE — Automation execution terminated:")
        for p in problems:
            log("    - " + p)
        raise SystemExit(1)
    log("Pre-flight state verified: X11 interface ready, path configurations parsed.")

    disable_sleep_and_lock()

    log("")
    log("ATTENTION: Focus target VSCode interface chat frame input window now.")
    log("           Ensure interface cursor is actively pulsing. Leave input setup clear.")
    log("")

    # 3. Global execution run loop
    for target_time, label, prompt_payload in master_timeline:
        wait_until(target_time, label)
        send_prompt(label, prompt_payload)

    log("Global overnight analysis matrix execution completed successfully.")