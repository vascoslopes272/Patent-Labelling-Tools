# Task: Extend notebook 02a — codebook v2.0 conversions, worklists, and validations

(Verbatim record of the prompt fired by `timer.py`'s `PROMPT_B`, saved for `PROMPT_C`'s audit
pass, which compares the implementation against this file as ground truth.)

> **STATUS as of 2026-07-21: NOT YET IMPLEMENTED.** This prompt's own text asked to pause
> before any change ("before you do any change, we need to talk... I can agree and you move
> on"). Claude found this file was fired unattended (via `timer.py`, confirmed by reading that
> script) and could not get a live confirmation, so it did read-only investigation instead —
> comparing this spec against the CURRENT `02a_preprocessing.ipynb` (last committed
> 2026-07-06, before v14 existed) — and left a full compatibility report in the conversation
> for the annotator to read and confirm before implementation starts. See that report (or the
> memory entry it produced) for the specific conflicts found, especially: Step 0b's existing
> `empKin→empTilts` migration handles `Stabilator` differently than v14 does; Rule C's
> unconditional `UAVSimilar` duplicate-chain propagation conflicts with this prompt's D3
' ("independent for D3"); Rule A (Combined Thrust) checks the opposite direction from H3; D1's
> "derive required fields from the wizard's blocker logic" is a much larger undertaking now
> that v14 added several new per-topType blockers. If `PROMPT_C` is auditing and finds this
> notebook UNCHANGED from its 2026-07-06 state, that is expected — it means the compatibility
> conversation had not concluded yet, not that the work was silently skipped.

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
