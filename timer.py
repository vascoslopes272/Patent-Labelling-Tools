"""
timer.py
Sends two prompts to VSCode Claude at scheduled times using clipboard paste.
CLIPBOARD METHOD — the entire prompt is pasted atomically with Ctrl+V.
Never uses typewrite(), which breaks on newlines, special chars, and long strings.

Schedule:
  Prompt 1 → 04:30
  Prompt 2 → 05:20  (50 min later)

Usage:
  1. pip install pyautogui pyperclip
  2. Have the image for Prompt 1 already pasted/attached in the VSCode chat.
  3. Click inside the VSCode chat input so the cursor is blinking there.
  4. python timer.py
"""

import time
import datetime
import pyautogui
import pyperclip

TARGET_TIME_P1 = "06:10"
TARGET_TIME_P2 = "06:30"
TARGET_TIME_P3 = "10:00" #generous gap: Task 2 does a full re-run + network fetches

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 1 — 04:30: SBERT accuracy upgrade (local text levers) + phase-2 setup
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_1 = """OVERNIGHT UNATTENDED TASK 1 of 3.

    ╔══════════════════════════════════════════════════════════════════════════╗
    ║ NO HUMAN IS PRESENT. The user is asleep and WILL NOT answer anything until ║
    ║ morning. Therefore, for this entire task you MUST:                          ║
    ║  • NEVER ask a question. NEVER call AskUserQuestion / EnterPlanMode or any  ║
    ║    tool that waits for a human reply — it will hang the whole night run.    ║
    ║  • NEVER wait for confirmation or approval. Decide, act, and continue.      ║
    ║  • When something is ambiguous, pick the safest reasonable option, WRITE    ║
    ║    DOWN the assumption in your final report, and keep going.                ║
    ║  • If you truly cannot proceed safely, STOP and clearly report why in your  ║
    ║    final message — do not idle waiting for input.                           ║
    ║  • Run to completion autonomously, then leave ONE clear summary for the     ║
    ║    morning.                                                                 ║
    ╚══════════════════════════════════════════════════════════════════════════╝

    CONTEXT (this is a continuation of work you already did earlier in this project):
    - Repo: /home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent-Labelling-Tools
    - Stage-01 pipeline classifies eVTOL patents with SigLIP (vision) + PatentSBERTa
    (text). The text classifier in src/reviewer.py builds `classify_text` inside
    process_patent() from: title + abstract + first_claim + description_of_drawings.
    - src/extractor.py's load_patseer_excel() ALSO loads `innovation_objective`
    (Summary/Advantages of Invention) per patent, but it is currently NOT fed to
    SBERT. It also loads backward_cites / forward_cites and has a working Google
    Patents fetcher (_fetch_google_patents).
    - Earlier you added G1 keyword priors (_G1_KEYWORD_RULES / classify_g1_keyword),
    a text-primary G1 resolver (resolve_g1), and margin-flagging (_margin_flag,
    _sbert_best now returns a `margin`). DO NOT regress any of that.

    GOAL: raise SBERT / keyword-prior accuracy on the architecture & kinematic fields
    using LOCAL text only (no network in this task — networking is Task 2). Implement
    all three levers below in src/ (Python only — do NOT touch the HTML wizard or any
    notebook; do NOT change config.yaml):

    LEVER 1 — Feed innovation_objective into SBERT.
        In process_patent() add excel_row.get("innovation_objective") to the
        `classify_text` join (after first_claim). One change, low risk.

    LEVER 2 — Kinematic-sentence mining (the high-value one).
        Add a helper (e.g. extract_kinematic_sentences(text)) that pulls only the
        sentences containing architecture/kinematic cue words — tilt, tilting,
        rotatable, pivot, pivoting, nacelle, lift and cruise, lift+cruise, stopped
        rotor, stowed, deflected slipstream, vectored, transition, hover, cruise
        propeller, coaxial, tandem, etc. Build a SECOND, signal-dense text string
        from first_claim + description (NOT description_of_drawings) restricted to
        those sentences, and feed it to: (a) classify_g1_keyword (so keyword priors
        can fire on claim/description text, not just title+abstract), and (b) the
        SBERT G1 / empKin / M3-orient / M3-propKin classifiers. Keep the existing
        blob for the genuinely-visual fields. The point is to stop diluting SBERT's
        384-token window with boilerplate — feed it the kinematic sentences only.

    LEVER 3 — Per-field text routing.
        Don't embed one blob for everything. Route the kinematic-sentence text to
        G1 + the kinematic fields (empKin, orient, propKin); keep title+abstract+
        first_claim for the structural/visual text fields. Make this explicit and
        commented so it's tunable.

    HARD CONSTRAINTS (unattended safety):
    - Python files only. Do NOT edit UI_for_taxonomy_caracterization_10.0.html or any
    .ipynb or config.yaml.
    - Keep all public function signatures backward-compatible (new args must be
    optional with safe defaults) so existing callers don't break.
    - After coding, you MUST: `python3 -m py_compile` every file you touched, AND
    write small inline unit tests proving (1) innovation_objective now reaches
    classify_text, (2) extract_kinematic_sentences returns only cue-word sentences
    and drops boilerplate, (3) a "lift plus cruise" sentence buried in a long
    description now triggers the SLC keyword prior. Paste the passing test output.
    - If anything fails to compile or a test fails, STOP, revert that change, and
    report it — do not leave the repo in a broken state for Task 2 to build on.
    - End with a concise diff summary: which files/functions changed and why."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 2 — 05:20: phase-2 citation enrichment + full re-run + validation gate
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_2 = """OVERNIGHT UNATTENDED TASK 2 of 3 — continues directly from Task 1 (the SBERT
local upgrades).

╔══════════════════════════════════════════════════════════════════════════╗
║ NO HUMAN IS PRESENT (user asleep). Do NOT ask questions, do NOT call        ║
║ AskUserQuestion/EnterPlanMode, do NOT wait for approval — any of these will ║
║ hang the run. Decide, act, finish, and leave one summary. If you cannot     ║
║ proceed safely, STOP and report why; never idle waiting for input.         ║
╚══════════════════════════════════════════════════════════════════════════╝

Repo: /home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent-Labelling-Tools

This task has THREE parts. Do them IN ORDER and STOP at the first hard failure.

PART A — Phase-2 citation/Google-Patents text enrichment (network).
- src/extractor.py already has _fetch_google_patents() + _GP_HEADERS and loads
  backward_cites / forward_cites per patent. Add an OPT-IN enrichment that, for a
  patent whose architecture is still ambiguous after the local pass (G1 flagged
  flagged_ambiguous, or G1 confidence below the config G1 threshold), fetches a
  small amount of text from its same-family / closest cited patent and uses it as
  an extra SBERT/keyword input to break the tie.
- NETWORK SAFETY (mandatory): wrap every request in try/except; hard timeout
  (<=30s, already the default); polite rate-limit (sleep between requests);
  cap total fetches (e.g. <=2 per ambiguous patent); on ANY network error,
  log and fall back to the local-only prediction — never crash the run. Cache
  fetched text to disk so a re-run doesn't refetch. Make enrichment OFF by
  default via a flag, ON for this run.

PART B — Full Stage-01 re-run (with a mandatory backup first).
- BEFORE running anything, back up the current export:
  copy data/matched/<batch>/ml_predict_labels_<batch>.xlsx to
  ml_predict_labels_<batch>.PRE_OVERNIGHT_BACKUP.xlsx (do NOT overwrite an
  existing backup — if one exists, add a timestamp). This is non-negotiable: the
  current export must remain recoverable.
- Then run run_stage01 on the batch with the Task-1 upgrades + Part-A enrichment.

PART C — Validation gate + report (THIS DECIDES IF THE RUN IS TRUSTWORTHY).
- Write a standalone audit (scripts/overnight_audit.py is fine) that reads the
  NEW export and reports, per the failure classes the user actually hits:
  (1) Vocabulary/schema drift — every Value in the xlsx must be a legal option in
      the HTML taxonomy (cross-check against UI_for_taxonomy_caracterization_10.0.html
      and the cross_modal/reviewer enums). List any illegal values.
  (2) Confident-wrong risk — count G1 predictions that are confident (above the
      config threshold) yet came ONLY from vision with text disagreeing; list them.
  (3) Flag coverage — how many ambiguous G1/kinematic guesses got flagged
      (needs_review) vs slipped through.
  (4) Completeness — patents/figures missing required fields.
- Compare NEW vs the PRE_OVERNIGHT_BACKUP: how many G1 / empKin / propKin values
  CHANGED, and spot-check that the changes move toward the keyword/text evidence
  (e.g. lift+cruise patents now SLC not TP).
- DECISION RULE: if Part C finds schema-drift (illegal values) or a regression
  vs backup (more confident-wrong than before), DO NOT present the new export as
  good — clearly flag it as FAILED VALIDATION and tell the user to keep using the
  backup until reviewed. If it passes, say so plainly with the numbers.

Finish with: a one-screen summary — what changed, the validation verdict
(PASS/FAIL with counts), where the backup is, and what the user should do next
before labeling the full set."""

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT 3 — 06:10: VISION ground-truth audit (open images, compare to the Excel)
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_3 = """OVERNIGHT UNATTENDED TASK 3 of 3 — the visual ground-truth audit. This runs
after Task 2 finished the re-run. The user will only ever review a FEW patents by
hand, so YOU are the one who actually looks at the drawings tonight.

╔══════════════════════════════════════════════════════════════════════════╗
║ NO HUMAN IS PRESENT (user asleep). Do NOT ask questions, do NOT call        ║
║ AskUserQuestion/EnterPlanMode, do NOT wait for approval — it will hang the  ║
║ run. Decide, act, finish, leave one report. If blocked, STOP and say why.   ║
╚══════════════════════════════════════════════════════════════════════════╝

Repo: /home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent-Labelling-Tools
You CAN open images directly with the Read tool (it renders PNGs visually). Use
that to compare the actual drawing against the label the pipeline assigned.

TASK — sample-based vision-vs-Excel cross-check:
1. Load the NEW post-re-run export ml_predict_labels_<batch>.xlsx (the one Task 2
   produced; if Task 2 FAILED validation, audit the PRE_OVERNIGHT_BACKUP instead
   and say so). The figure rows carry an Image_Path column pointing at the crop.
2. Pick a SMALL, representative sample — about 10-15 figures across different
   patents and different predicted classes. Deliberately include:
   - figures the pipeline marked needs_review / flagged_ambiguous,
   - a few high-confidence G1=TP and G1=SLC predictions (the tilt-vs-lift+cruise
     confusion the user cares most about),
   - a couple of duplicate-flagged images.
   Do NOT try to audit the whole batch — reading images is context-heavy; ~15 is
   the right size. State which figures you picked and why.
3. For EACH sampled figure: open the image with Read, look at it, and judge
   whether the pipeline's T2 labels (perspective, rendering style) and the
   patent's G1/M-field architecture labels are PLAUSIBLE given what you can see.
   You are checking for obvious contradictions (e.g. a clear top-view labeled
   "Front"; a fixed lift+cruise drawing confidently labeled tiltrotor; a
   shaded render labeled "Blueprint").
4. Produce a table: figure id | predicted label(s) | what you see | AGREE /
   SUSPECT / WRONG | short reason. Tally the agree/suspect/wrong counts.
5. Conclude with: the single most common error pattern you observed, whether the
   Task-1/Task-2 upgrades visibly helped the tilt-vs-lift+cruise cases, and a
   concrete recommendation — is the export trustworthy enough for the user to
   start labeling from, or should specific fields be re-checked first?

Constraints: read-only audit — do NOT modify the export or any source file in
this task; you are reporting, not fixing. If an Image_Path is missing/broken,
note it and move to the next figure rather than stopping."""


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
    print(f"  Prompt 1 → {TARGET_TIME_P1}  (SBERT accuracy upgrade — local text levers)")
    print(f"  Prompt 2 → {TARGET_TIME_P2}  (Citation enrichment + full re-run + validation gate)")
    print(f"  Prompt 3 → {TARGET_TIME_P3}  (Vision ground-truth audit — open images vs Excel)")  # 07:30
    print()
    print("⚠️  BEFORE LEAVING:")
    print("    1. These prompts are fully self-contained — no image needed.")
    print("    2. Click inside the VSCode chat input box.")
    print("    3. Make sure the cursor is blinking there.")
    print("    4. Do NOT touch the keyboard or mouse after that.")
    print("=" * 60)

    # ── Prompt 1 ──────────────────────────────────────────────────────────────
    wait_until(TARGET_TIME_P1, "Prompt 1")
    send_prompt("Prompt 1", PROMPT_1)

    # ── Wait until Prompt 2 ───────────────────────────────────────────────────
    print(f"\n⏳ Waiting for Prompt 2 at {TARGET_TIME_P2}...")
    wait_until(TARGET_TIME_P2, "Prompt 2")
    send_prompt("Prompt 2", PROMPT_2)

    # ── Wait until Prompt 3 ───────────────────────────────────────────────────
    print(f"\n⏳ Waiting for Prompt 3 at {TARGET_TIME_P3}...")
    wait_until(TARGET_TIME_P3, "Prompt 3")
    send_prompt("Prompt 3", PROMPT_3)

    print("\n🎉 All three prompts sent. Pipeline will run overnight.")