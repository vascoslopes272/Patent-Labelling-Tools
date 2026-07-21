# Task: Update taxonomy wizard `UI_for_taxonomy_caracterization_13_0.html` → v14.0

(Verbatim record of the prompt used to generate v14 — saved for `PROMPT_C`'s audit pass,
which compares the implementation against this file as ground truth. Implemented
2026-07-21 in this session; see `labelling-ui-v14-codebook-v2.md` in Claude's memory for
the full changelog, the 4 clarifying questions asked/answered, and verification notes.)

## Role & ground rules
You are updating a production labelling wizard used daily by a single human annotator.
The changes below implement codebook v2.0 decisions (Phase 0, closed 2026-07-20). They are
final decisions — do not redesign, do not "improve" beyond what is listed.

- Save as a NEW file `UI_for_taxonomy_caracterization_14_0.html`. Never modify v13 in place.
- Preserve backward compatibility on LOAD: old saved records (v13 and earlier) must still
  ingest correctly. Where a field is retired, keep its ingest path but stop rendering/exporting it.
- **If ANYTHING is ambiguous — variable ownership, where a value is consumed, whether a field
  feeds the export — ASK before changing. Do not guess.** Wrong assumptions feed a live pipeline.

## Changes

### C1 — Retire `TILTED_IN_VIEW` (PR-01)
Remove the per-figure "Wings tilted / Rotors tilted" UI and its export columns.
Keep ingest tolerance for old saves (silently drop the values). Delete the `TILTED_IN_VIEW` array
once nothing references it.

### C2 — Duplicate types rework (PR-02)
In `DUP_TYPES`: delete type `4` (Component Overlap). Rename remaining to inheritance semantics:
- `1` → `D1 — Same aircraft, new figures` desc: "Same aircraft under a different patent ID with
  figures worth labelling. Inherit M1–M3 from the original; relabel T2 fresh."
- `2` → `D2 — Same aircraft, same figures` desc: "Identical aircraft and figures. Inherit T2–M3;
  nothing new to label."
- `3` → `D3 — Same aircraft, modified` desc: "Same core invention with visible differences.
  Inherit nothing; full relabel."
Keep old ids `1/2/3` internally so saved records stay valid; only labels/descriptions change.
Old id `4` on ingest: keep the value visible in notes/flag for manual re-assignment, do not crash.

### C3 — `AC_STATE` rework (PR-04 / PR-05)
New scheme, per-figure:
- If the patent's G1 `topType` is a CONVERTIBLE architecture (TW, TP, DS, CVT, TB, PTC):
  show four options: `Hover`, `Transition`, `Cruise`, `Other`.
  Tooltip: "Decide by the MECHANISM ANGLE drawn — mechanism state wins even if the aircraft
  is drawn on the ground. Other = figure shows no flight configuration (exploded, unclear, N/A)."
- If `topType` is a FIXED architecture (SLC, SRW, RC, MR, HB, PFV):
  do NOT ask. Auto-set the figure state to a new value `HoverCruise`
  (label: "Hover & Cruise (state-invariant)"). Render it as a non-interactive badge.
  Tooltip: "Fixed architectures never change shape; hover and cruise are the same drawing."
- Old values on ingest: `Ground`, `Unclear`, `NonApplicable` map to `Other` ONLY for display;
  keep the original raw value stored so notebook 02a can build the directed re-pass worklist.
  Do not silently overwrite saved raw values.

### C4 — Retire `EMP_KIN` as a choice field (PR-06)
Remove the three-option Fixed/Tilt/Stabilator selector. Replace with:
- Default assumption: empennage is Fixed (no UI element states this; it's the documented default).
- One opt-in checkbox: "Empennage tilts (exception)". When ticked, a note field becomes
  MANDATORY (blocker) describing the mechanism.
- Ingest mapping for old saves: `Fixed` → unticked; `Tilt` or `Stabilator` → ticked, and copy the
  old value into the note as "legacy: <value>".
- Export: boolean column `empTilts` + its note. Keep the legacy `EMP_KIN` column out of new exports.

### C5 — `BOOM_ORIENT`: add X format (PR-03)
Add option: `{id:'X', n:'X / Diagonal (crossing)'}` with tooltip:
"Booms run diagonally and converge or cross at a central region, forming an X in top view.
Booms that run parallel to each other — even if swept or angled — are NOT X format."
(The labelled excels were already migrated by notebook 02a; this change is HTML-side only.)

### C6 — Remove `BOOM_POS` migration shim — CONDITIONAL
`BOOM_POS` exists only to migrate pre-split saved values on load (see its comment / ingestAI).
Notebook 02a will first verify no un-migrated saves remain. **Ask the annotator whether that
check has passed before deleting.** If confirmed: delete the array and its ingest branch.
If not confirmed: leave untouched.

### C7 — New physics locks (PR-12, Hard rules only)
Existing `propKinLock()` (RC/TW/SLC/SRW/MR) stays. Add, in the same style (lock + explanatory
comment, blocking invalid entry):
1. `topType ∈ {MR, RC}` ⇒ M2 wing count locked to 0 / wing cards hidden.
2. `topType = CVT` ⇒ validation at M3 completion: require BOTH a Fixed and a Tilt propulsor
   (or wing-tilt + rotor-tilt combination) across cards; block "done" with a clear message if not.
3. `topType = TW` ⇒ at least one wing with `W_TILT = Tilt` required at M2 completion.
4. `topType = TB` ⇒ `FUS_KIN` locked to `TiltBody` (auto-set, non-editable, with comment).
5. `topType = DS` ⇒ all `propKin` locked to `Fixed`.
Soft rules (TP wings-fixed, SRW rotor pattern) are NOT implemented in the HTML — they live in
notebook 02a as warnings only. Do not add them here.

### C8 — Documentation tooltips (small, high value)
1. Near `FUS_KIN`: add the R-06 criterion as a comment/tooltip:
   "Compare hover vs cruise figures: wing rotates + cabin stays level = Variable Incidence;
   cabin/fuselage itself reorients (tailsitter: everything rotates, no internal joint) = Tilting Body;
   nothing reorients = Fixed."
2. Near the "★ Set as Main Figure" button: "Convention: for convertibles the main figure is the
   CRUISE (or isometric) configuration — hover views of tilt aircraft are visually confusable
   with multirotors." (R-09; currently undocumented in the tool.)

## Out of scope — do not touch
- Any notebook, `src/*.py`, or export files.
- The G1 taxonomy list (`TOP`) itself — no architecture additions/removals.
- Any field not listed above.

## Acceptance checklist (self-verify before finishing)
- [ ] v13 file untouched; v14 is a new file.
- [ ] An old v13 saved record loads without errors; retired fields ingest silently.
- [ ] Fixed-arch patent: T2 shows the HoverCruise badge, no state question asked.
- [ ] Convertible patent: 4 state options with mechanism-wins tooltip.
- [ ] TB patent: FUS_KIN shows TiltBody locked.
- [ ] CVT patent with only tilting props: completion blocked with message.
- [ ] Empennage tick unchecked by default; ticking it makes the note mandatory.
- [ ] Export contains no TILTED_IN_VIEW / EMP_KIN choice columns; contains empTilts.

## Resolution log (added post-implementation, 2026-07-21)
Four points were genuinely ambiguous relative to the ACTUAL v13 file at implementation time
(not knowable from this prompt alone) and were resolved with the annotator before writing code:

1. **T2-before-G1 ordering.** T2 (where AC_STATE lives) is STEPS index 1, G1 (topType) is
   index 2 — topType is usually unknown when a reviewer answers "flight configuration shown"
   on a first pass. Resolved: provisional 4-option UI whenever topType is unknown, reconciled
   the instant G1 is picked (force `HoverCruise` if fixed / clear a stale `HoverCruise` if
   corrected back to convertible) — never on ingest of an old file, only on a live click.
2. **BOOM_POS (C6).** Not confirmed migrated — left untouched, per its own conditional clause.
3. **`boomXFormat` overlap.** A whole-airframe "X formation" boolean already existed
   (added 2026-07-05), overlapping the new per-group `BOOM_ORIENT='X'`. Resolved: retire
   `boomXFormat`'s UI now (state key + ingest path kept for old-save compatibility).
4. **Empennage architecture lock.** TW/TB were hard-locked to Fixed empennage kinematics with
   an explanatory "physics lock" banner; RC was restricted to Fixed/Stabilator only. Resolved:
   make the new `empTilts` checkbox universal, no architecture restriction — it's explicitly an
   "(exception)" flag, so a human should be able to flag any patent that defies the normal case.

Two lower-stakes judgment calls were made and documented in-file rather than blocked on:
D2's "Inherit T2–M3" wording is label/description-only (the existing blank-morphology export
mechanic for type 2 is unchanged, per this prompt's own "only labels/descriptions change"
instruction); the CVT M3-completion boolean is
`(∃ Tilt propKin) AND ((∃ Fixed propKin) OR (∃ wing W_TILT='Tilt'))`, derived directly from
this file's own G1 CVT description text.
