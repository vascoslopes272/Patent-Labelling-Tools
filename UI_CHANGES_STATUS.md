# UI Changes Status

## UI TASK A

**STATUS: DONE** — both behaviour fixes implemented in `notebooks/UI_for_taxonomy_caracterization_10.0.html` (the only file edited). Backup made at `notebooks/UI_for_taxonomy_caracterization_10.0.PRE_UICHANGE_A_20260621_235215.html`.

**Verification (passed):**
- Largest inline `<script>` extracted → `node --check` PASS.
- Whole-file balance: braces 838/838, parens 2828/2828, brackets 455/455 — all equal.
- Multi-architecture work confirmed intact (getArchCount, save/loadArchProfile, archProfiles, data-t2-arch dropdown, "+ Add architecture", "Distinct Architectures", `_arch` export suffix, ingestPatentRows/basePatentId/archSuffixNum all still present).

**CHANGE 1 — Structural Elements single-select (default) + edge-case multi toggle:**
- `pageT2()` card "C. Present Structural Elements (Visual Tokens)": added a per-figure
  `figData[fNum].partsMulti` flag (default falsy = single). Card head now shows a
  `#btn-parts-multi-toggle` button ("Allow multiple (edge case)" ↔ "Back to single")
  and an `m3-sub` line stating the current mode.
- Panel click listener, `data-figarrfield` branch: when field is `parts` and not
  `partsMulti`, behaves radio-like (click sets `parts=[val]`; click selected token
  clears to `[]`). MULTI mode and all other figarrfields keep the legacy toggle.
- Added `#btn-parts-multi-toggle` handler: flips `partsMulti`, re-renders; on
  multi→single it keeps only `parts[0]` when >1 was selected (commented).
- `#btn-add-part` (custom token): in single mode now REPLACES selection
  (`parts=[newTag]`) instead of appending, to preserve the length-1 invariant.
- `parts` stays an ARRAY (length 0 or 1 in single mode); export schema unchanged.

**CHANGE 2 — Figure Notes EDGE_TOKENS as clickable chips:**
- `pageT2()` "Figure Notes" card: renders all `EDGE_TOKENS` as clickable `.crumb`
  chips (`data-add-edge-tag`), applied ones highlighted with `.crumb.hi`. Text input
  `#t2-edge-tag-input` + `#btn-add-edge-tag` (creates new tokens) and the existing
  removable applied-tag chips (`data-remove-tag`) and the datalist are all kept.
- Added `data-add-edge-tag` click handler: appends the tag to `figData[fNum].edgeTags`
  if absent, then re-renders. `edgeTags` stays an array; export schema unchanged.
- Added `[data-add-edge-tag]` to `DIRTY_SEL` so applying a tag flips the save
  indicator (parity with parts, which already mark the patent dirty).

**Assumptions:**
- Chips styled with the existing `.crumb` class (matches the already-applied edgeTag
  chips) rather than the larger `.opt` grid style — cleaner in-card parity.
- `partsMulti` is a transient per-figure UI flag, deliberately NOT added to
  `FIG_LABEL_KEYS`, so it is never exported nor snapshotted into the figure/arch
  registries.
- Made `#btn-add-part` respect single mode (not in the original spec) to keep the
  single-select length-1 invariant consistent.
- Added `[data-add-edge-tag]` to `DIRTY_SEL` (the pre-existing `data-remove-tag` is
  not in it; left that gap alone as out of scope).

UI Task B (layout) can proceed.

## UI TASK B

**STATUS: DONE** — both layout changes implemented in `notebooks/UI_for_taxonomy_caracterization_10.0.html` (only file edited). Backup of the post-Task-A state at `notebooks/UI_for_taxonomy_caracterization_10.0.PRE_UICHANGE_B_20260622_041011.html`.

**Verification (passed):**
- Largest inline `<script>` extracted → `node --check` PASS.
- Whole-file balance: braces 863/863, parens 2873/2873, brackets 464/464 — all equal. Literal `<div>`/`</div>` 267/267.
- Multi-architecture work confirmed intact (getArchCount, save/loadArchProfile, archProfiles, single data-t2-arch dropdown, "+ Add architecture", "Distinct Architectures", "Architecture N of M" banner, `_arch` export suffix, ingestPatentRows/basePatentId/archSuffixNum).
- Task A preserved: `partsMulti`, `#btn-parts-multi-toggle`, `data-add-edge-tag` chips, `data-remove-tag`, `#btn-add-edge-tag` all still present and unchanged.

**CHANGE 3 — 4-column T2 layout:**
- `pageT2()` container changed from `.t2-split` (2-col: `.t2-left`/`.t2-right`) to a new `.t2-grid4` CSS grid with four independently-scrolling `.t2-col` columns:
  - Col 1 (`.t2-col-img`): the ACTIVE figure image + FIG.# input + brief-description + rotate controls (former `.t2-left` content).
  - Col 2 (`.t2-col-thumbs`): `figGrid()` thumbnail list.
  - Col 3 (`.t2-col-tags`): Duplicate Image Cross-Reference + A. Projection Coordinates + B. Image Rendering Style.
  - Col 4 (`.t2-col-tags`): Figure Validation & Assignment (Set-Main / Assign-To architecture dropdown / + Add architecture / Distinct-Architectures banner — relocated here) + C. Present Structural Elements + D. Image Quality Flag + Figure Notes.
- Cards were only MOVED/REGROUPED — every id, data-attribute, handler and inner markup is byte-for-byte the same (the Validation card was cut from col 3's old spot and pasted into col 4). No card deleted. The `!fNum` branch renders the "No Figure Selected" flag in col 3 and an empty col 4.
- New CSS added next to the old `.t2-*` rules (old rules left in place, now dead but harmless): `.t2-grid4`/`.t2-col`/`.t2-col-img`/`.t2-col-thumbs`/`.t2-col-tags`, with `@media (max-width:1200px)` → 2 columns and `@media (max-width:768px)` → 1 column (stacks).
- `renderPreserveScroll()` updated to capture/restore scrollTop for all `.t2-col` columns by index (it previously targeted `.t2-left`/`.t2-right`).

**CHANGE 4 — main figure image on G1/M1/M2/M3:**
- Added `morphologyMainImage()` helper: prefers `S.mainFigure`, falls back to the first approved figure with an image, then any figure with an image; returns `''` (renders nothing, no broken `<img>`) when none. Builds the URL via the existing `realFigImage()`/`pathToFileURL()`.
- `render()` prepends `morphologyMainImage()` to `content` only for step ids `gate`/`m1`/`m2`/`m3`, in the same block as the "Architecture N of M" banner — the banner markup/logic is untouched.
- New CSS `.morph-mainfig`: `position:fixed` top-right (floats in the empty margin beside the 820px-wide `.wiz` on wide screens so it stays visible while the form scrolls and never overlaps); `@media (max-width:1300px)` switches it to static normal-flow at the top.

**Assumptions:**
- Duplicate Image Cross-Reference card (not named in the spec's example grouping) placed in col 3 with A & B; the architecture assignment panel placed in col 4 per the spec example.
- On wide screens the sticky image uses `position:fixed` in the wizard's right margin (the page scrolls on the window); below 1300px it falls back to a static top card to avoid overlap. Image uses `object-fit:contain` so aspect ratio is preserved.
- Old `.t2-split`/`.t2-left`/`.t2-right` CSS rules left in the stylesheet (unused) to minimize churn; no markup references them anymore.
- Layout-only: no export schema, control id, or handler logic changed.

