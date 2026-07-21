# Audit — codebook v2.0 implementation (wizard v14 + notebook 02a)

Run 2026-07-21, unattended (`timer.py` PROMPT_C). Independent audit against
`prompt_html_v13_to_v14.md` and `prompt_notebook_02a.md` as ground truth.
Report-only — nothing fixed in this pass.

## Verdict: **FIX FIRST** (for 02a) / **SAFE TO LABEL** (for the HTML wizard alone)

The HTML wizard (v14) is a clean, complete, independently-verified implementation of C1–C8.
It can be used for labelling today. The notebook 02a extension was **not started** — paused
mid-task for a compatibility review that hadn't concluded before this audit ran. That is not
a bug; see "Correction to audit premise" below. Do not run 02a's new (nonexistent) rules —
there's nothing to run yet.

## Correction to audit premise

This audit's own framing says "Both change-sets have been implemented." That's true for the
HTML, false for the notebook. `02a_preprocessing.ipynb` is byte-for-byte unchanged since
2026-07-06 (`git diff` clean) — the extension was paused after finding 6 real conflicts
between the new spec and the notebook's existing rules (see `prompt_notebook_02a.md`'s status
note and Claude's memory `02a-v2-compat-review`), pending the annotator's call on how to
resolve them. Audit B below reports every 02a item as NOT IMPLEMENTED rather than
MAJOR/broken, since nothing was attempted.

## Known execution-order deviation (priority #1) — RESOLVED, no issue

- C6 (`BOOM_POS` shim deletion): **(a) left untouched.** Confirmed two ways: zero
  `BOOM_POS`/`BOOM_POS_LONG`/`BOOM_POS_SPAN` lines in the full v13→v14 diff (36 hunks, none
  touch this code), and the annotator's own answer during implementation ("No/not sure — leave
  it alone"), recorded in `prompt_html_v13_to_v14.md`'s resolution log.
- 02a's D2 check: doesn't exist yet (02a unimplemented). The "downgrade to WARNING if D2
  passes and shim was deleted" branch doesn't apply — nothing was deleted, so there's nothing
  to reconcile. No action needed on this axis.

## Audit A — HTML v14 vs spec

Verified via `sha256sum` (v13 baseline), a full `diff -u` of v13→v14 (36 hunks, +256/−61
lines, every hunk traced to a spec item), and a Node `vm` + mocked-DOM harness exercising the
actual functions (not just reading code).

| Item | Status | Evidence |
|---|---|---|
| C1 — retire TILTED_IN_VIEW | ✅ done | array deleted, render block removed, export row removed; ingest path (`figSet` in ingestAI T2 loop, `rowsToAIData`'s parse) deliberately kept for old-save tolerance |
| C2 — DUP_TYPES rework | ✅ done | id `4` deleted from array; ids `1/2/3` kept, relabelled D1/D2/D3; `autoCopyDupMorphology`/`buildExport` untouched (label-only, per spec); legacy id-4 banner added in pageT1 |
| C3 — AC_STATE rework | ✅ done | `isConvertibleArch()` exhaustive 6+6 split verified against live `TOP` array; provisional 4-option UI + G1-click reconciliation for the T2-before-G1 ordering issue (see Q1 below) |
| C4 — retire EMP_KIN | ✅ done | 3-option selector removed; universal `empTilts` checkbox + mandatory-note-when-ticked; legacy `Tilt`/`Stabilator`→ticked+note mapping; old TW/TB/RC hard locks removed (per Q4) |
| C5 — BOOM_ORIENT X | ✅ done | `{id:'X',...}` with exact spec tooltip text added; `bgGrid()` extended to show it |
| C6 — BOOM_POS shim | ✅ correctly left untouched | see above |
| C7 — physics locks (1–5) | ✅ all 5 done | MR/RC wCount→0 (both hook points); CVT M3 mix check; TW M2 wing-tilt check; TB→FUS_KIN lock (`applyFusKinLock()`, new); DS added to `propKinLock()` |
| C8 — tooltips | ✅ done | R-06 text verbatim near FUS_KIN; R-09 text verbatim near ★ (as tooltip *and* a visible note) |

### Acceptance checklist — pass/fail

| # | Item | Result |
|---|---|---|
| 1 | v13 byte-identical to baseline | **PASS** — sha256 `cb4c3754...` matches `git show HEAD:...` exactly |
| 2 | old v13 record loads without error, retired fields ingest silently | **PASS** — tested: old `tiltedInView` array, legacy `duplicateType=4`, legacy `empKin` values all ingest cleanly |
| 3 | fixed-arch: HoverCruise badge, no question asked | **PASS** — tested via `pageT2()` render for a live-MR figure |
| 4 | convertible-arch: exactly 4 options + mechanism-wins tooltip | **PASS** — array literal is exactly 4 entries (`Hover/Transition/Cruise/Other`), tooltip text verbatim in both `title=` and a visible note |
| 5 | TB: FUS_KIN locked TiltBody, non-editable | **PASS** — `applyFusKinLock()` + disabled single-option render (`dis` flag) |
| 6 | CVT-only-tilting: completion blocked, clear message | **PASS** — tested both the blocked and the (Fixed-added) unblocked case |
| 7 | DS: propKin locked Fixed; TW-no-tilt: M2 blocked | **PASS** — `propKinLock('DS')==='Fixed'`; tested TW block/unblock directly in this audit pass (not covered by the original session's smoke test — closed that gap here) |
| 8 | MR/RC: wing cards hidden / count→0 | **PASS** — `wCount` forced to 0 at both hook points (ingestAI G1 block + g1-subbtn handler); card-hiding was already correct pre-v14 via `isWinged()` |
| 9 | empennage: no 3-way selector; unticked by default; note mandatory when ticked | **PASS** |
| 10 | DUP_TYPES: D1/D2/D3 wording, ids 1/2/3, no type 4 selectable, legacy-4 doesn't crash | **PASS** |
| 11 | BOOM_ORIENT X + crossing-criterion tooltip | **PASS** — tooltip text verified verbatim |
| 12 | export: has `empTilts`, no tilt-in-view/EMP_KIN columns | **PASS** |
| 13 | R-06 + R-09 tooltips present | **PASS** |

**13/13 PASS.**

### Findings beyond literal spec text (Audit D input, reported here as NOTES not defects)

All of the following were disclosed and approved via 4 clarifying questions the implementer
asked before writing code (full record in `prompt_html_v13_to_v14.md`'s "Resolution log"):

- **`boomXFormat` UI retired** (checkbox removed from `m1BoomsCard()`, its export row and
  click handler removed) — not literally requested by C5's text, but the implementer found
  this whole-airframe boolean already existed (added 2026-07-05, before this spec was
  written) and asked whether to keep it alongside the new per-group `BOOM_ORIENT='X'`. Answer:
  retire it (state key + ingest path kept for old-save round-trip). **NOTE, not a finding** —
  informed decision, correctly implemented per the answer given.
- **T2-before-G1 reconciliation** (`isConvertibleArch()`, `topTypeOfArch()` helpers, and the
  G1-click sweep that forces/clears `HoverCruise`) — C3's text didn't anticipate that T2 (where
  AC_STATE lives) is visited *before* G1 (where topType is picked) in the wizard's own step
  order, so topType is usually unknown on a first pass. This is necessary infrastructure to
  make C3 implementable at all, not scope creep — flagged and resolved via clarifying
  question before implementation, verified independently in this audit (see Audit C.6 below).
- One **pre-existing stale comment fixed incidentally**: a v13 comment already read
  `TW/DS/SLC/SRW/MR/TB→Fixed` for `propKinLock()`, but the actual v13 *code* didn't lock DS —
  only the comment was wrong (predates this spec). Now that DS is genuinely locked (C7.5), the
  comment is accurate. Trivial, typo-level, no separate action needed.

No other deviations found. Everything else in the diff traces 1:1 to a C1–C8 item.

## Audit B — notebook 02a vs spec

**Every item below: NOT IMPLEMENTED.** The notebook is unchanged since 2026-07-06. This is
not a defect — see "Correction to audit premise." Existing (pre-v2.0, unmodified) rules in the
notebook that are *related* but not the same as what's asked are noted for context.

| Item | Status | Note |
|---|---|---|
| A1 (acState→HoverCruise) | not implemented | related existing rule: `Rule E` (Ground→Other), v13-anchored, architecture-agnostic — will need rescoping once A1 is added, per the compat review |
| A2 (empKin→empTilts) | not implemented as specified | related existing rule: `Step 0b`, but it encodes `Stabilator` differently (drops it) and never writes an explicit `False` or a legacy note — a real conflict, not a duplicate, per the compat review |
| A3 (TB→TiltBody) | not implemented | no existing equivalent |
| A4 (dup-type rename + assert 0 type-4) | not implemented | no existing equivalent |
| B1–B4 (worklists) | not implemented | B4's territory is already substantially covered by existing `Rule F` (X-format backfill); B2's territory overlaps existing `Rule G` (ambiguous fusKin flag), which already excludes nothing re: TB since A3 doesn't exist yet |
| H1–H6, S1–S2 | not implemented | `Rule A` (Combined Thrust) exists but checks the *opposite* direction from H3 (flags TP patents that might be CVT; doesn't check whether declared-CVT patents show the required mix) |
| D1 (completeness) | not implemented as specified | existing `_check_label_completeness` is a flat field list, not derived from `nextBlockers()`'s actual per-topType logic as the new spec asks |
| D2 (BOOM_POS completeness) | not implemented | no existing equivalent; needed before C6 can ever be revisited |
| D3 (UAVSimilar × duplicates) | not implemented as specified | existing `Rule C` unconditionally propagates the tag across every duplicate chain regardless of type — conflicts with the new spec's "independent for D3" |
| D4 (image-path joins) | not implemented | Section 3's `resolve_image_paths` logic already resolves paths in-memory; a dedicated report isn't there yet |
| Final summary cell | not implemented | n/a |

Sub-checks (state_legacy column, assert-zero-type-4, no-auto-swap, TB-exclusion, H5-assert,
soft-rules-warn-only, paste-able summary) are all **N/A — nothing to check.**

## Audit C — cross-consistency HTML ↔ notebook

| # | Check | Result |
|---|---|---|
| 1 | `HoverCruise` token identical HTML badge/export vs 02a A1 | **N/A** — 02a A1 doesn't exist. HTML-side alone: consistent (badge id, export id, and the state-key literal are all the same string `'HoverCruise'`) |
| 2 | fixed/convertible architecture sets match spec exactly | **PASS (HTML side)** — `isConvertibleArch` = exactly `{TW,TP,DS,CVT,TB,PTC}`, verified exhaustively against the live 12-entry `TOP` array (no drift, no missing/extra id, PTC correctly on the convertible side). 02a side N/A, not implemented |
| 3 | `empTilts` name/encoding identical | **PRE-EXISTING DRIFT, flagged** — HTML always writes an explicit boolean row (`true`/`false`); the *existing* (pre-v2.0) `Step 0b` in 02a only ever writes `True` rows and treats absence as False, and doesn't recognize `Stabilator` as tilting at all. Same finding as Audit B's A2 row — must be resolved when 02a is actually extended, not before |
| 4 | duplicate-type ids: HTML keeps 1/2/3, 02a A4 maps the same | **N/A** — A4 doesn't exist. No drift risk here structurally: HTML never changed the underlying ids, so whenever A4 is written it has a stable target |
| 5 | lock parity (HTML hard rules ↔ 02a H1–H6) | **0/6 — none exist yet.** All 5 new HTML locks (C7.1–C7.5) plus the pre-existing `propKinLock()` currently have no notebook-side validation counterpart at all |
| 6 | legacy AC_STATE values survive an open-and-resave cycle ("the subtle one") | **PASS, independently tested in this audit.** Full cycle run: seed a figure with raw `acState='NonApplicable'` on a CVT (convertible) patent → `pageT2()` render (display correctly shows "Other" selected) → confirm `S.figData` still holds the raw `'NonApplicable'` (not mutated) → `buildExport()`→`recordToRows()` (exported row is `NonApplicable`, not `Other`) → `rowsToAIData()`→`ingestAI()` (simulated re-open of the resaved file) → raw value is still `NonApplicable`. Zero silent overwrites anywhere in the cycle |

## Audit D — scope discipline

**HTML v13→v14**: every one of the 36 diff hunks traces to C1–C8. The only items not literally
spelled out in the spec text (boomXFormat retirement, the T2/G1 reconciliation
infrastructure) were surfaced via clarifying questions and approved before implementation —
see Audit A's "Findings beyond literal spec text" above. No unrequested/undisclosed changes.

**Notebook 02a**: zero changes (confirmed via `git diff --quiet`) — nothing to audit for scope
creep; there is no creep because there is no change.

## Next step

Six specific conflicts block a straightforward 02a implementation (full detail already in
`prompt_notebook_02a.md` and Claude's memory `02a-v2-compat-review`): the `Stabilator`
handling gap in A2/Step 0b, the D3-vs-Rule-C propagation conflict, the H3-vs-Rule-A direction
mismatch, D1's completeness scope, and the A1/Rule-E sequencing question. None of these are
audit findings against existing work — they're open design decisions waiting on the
annotator, unchanged since the last session's compatibility report.
