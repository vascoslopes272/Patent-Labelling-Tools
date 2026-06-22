# REVIEW_01 — Stage-01 human-review + save methodology audit

**Date:** 2026-06-22 · **Type:** read-only review (no code changed) · **Scope:** the HTML
review wizard (`notebooks/UI_for_taxonomy_caracterization_10.0.html`), the reviewed-xlsx
save/reload path, and the Stage-01 labeling heuristics (`src/excel_schema.py`,
`src/reviewer.py`, `src/cross_modal.py`, `config.yaml`, `notebooks/01_review.ipynb`).

Line numbers are as of this audit; function names are the stable anchors.

> **RESOLUTION (2026-06-22, applied after this audit):** the persistence findings
> **C1–C7** and **H1–H5** were fixed in `notebooks/UI_for_taxonomy_caracterization_10.0.html`
> (backup: `…PRE_PERSISTFIX_20260622_090924.html`). `recordToRows()` now emits the
> per-figure `qualityFlag/hasLegends/comment/edgeTags/arch` and M3 `propKin/sym`;
> `buildMorphologyObj()` now captures `sym`; and the readers (`rowsToAIData()`,
> `ingestAI()`, `loadBatchPatent()`) restore all of those plus figure `status`,
> `rotation_deg`, the M1/M2 notes, `mainFigure`, and patent-level `comments`. The change
> adds **rows only** — `EXCEL_COLUMNS` is still the same 10 columns, so it is fully
> backward-compatible and needs no batch re-run. Verified: `node --check` passes, brackets
> balanced, and a round-trip simulation using the real `recordToRows`→`rowsToAIData`
> functions confirms all 15 fields survive. **H6** (Needs_Review / blank Options schema
> drift) and all **MEDIUM heuristic** items (M1–M7) were intentionally **left unchanged**
> (out of the chosen scope; heuristics would require a batch re-run and are the user's call).

---

## 1. Executive summary

The architecture (G1 / M1-M2-M3) text path is in good shape and round-trips correctly,
**but the per-figure T2 labels and several morphology sub-fields the human can edit are
silently dropped on Save** — they are captured in memory by `buildExport()` yet never
written to the reviewed `.xlsx` by `recordToRows()`, or written but never read back on
reload. Because the reviewed workbook *is* the intended ground-truth label set
(`excel_schema.py` module docstring), these are real losses of human work, not cosmetic.

The single most consequential cluster: **`qualityFlag`, `hasLegends`, per-figure
`comment`, `edgeTags`, per-figure `arch` assignment, M3 `propKin`, and M3 `sym` are set
in the UI but never reach the saved file.** (Note: Task A just added the Figure-Notes
edge-tag chips that feed `comment`/`edgeTags` — those two fields are not persisted at
all, so that UX improvement currently writes to a dead end.)

The good news on the "known lead": dropping `Needs_Review` from the reviewed export is
**harmless for the only current consumer** (notebook cell 18 reads just `T1/isApproved`).
It only bites if you point a schema/Needs_Review validator at a *reviewed* file (PART 4
addresses this).

### Findings table (by severity)

| ID | Sev | Area | One-line |
|----|-----|------|----------|
| C1 | CRITICAL | save | Per-figure `qualityFlag` (D. Image Quality) set in UI, never emitted by `recordToRows()` → lost on save |
| C2 | CRITICAL | save | Per-figure `hasLegends` (callouts/legends checkbox) → lost on save |
| C3 | CRITICAL | save | Per-figure `comment` (Figure Notes) → lost on save (the field Task A's chips feed) |
| C4 | CRITICAL | save | Per-figure `edgeTags` (edge-case tags) → lost on save |
| C5 | CRITICAL | save | Per-figure `arch` (figure→architecture assignment) → lost on save (morphologies survive via `_archN`; the figure↔arch mapping does not) |
| C6 | CRITICAL | save | M3 per-card `propKin` (Propulsor Articulation) captured by `buildMorphologyObj()` but omitted from `recordToRows()` M3 list → lost on save (only TP re-derivable) |
| C7 | CRITICAL | save | M3 per-card `sym` (Laterally Symmetric Pairs) human-editable but never captured by `buildMorphologyObj()` → lost on save |
| H1 | HIGH | round-trip | Per-figure `status` (approve/disapprove) emitted but not restored on reload |
| H2 | HIGH | round-trip | Per-figure `rotation_deg` emitted but not restored on reload (only `rotation_deg_suggested` is read) |
| H3 | HIGH | round-trip | `mainFigure` written to META but never read back on reload |
| H4 | HIGH | round-trip | M1/M2 free-text notes `wingNotes`/`empNotes`/`fusNotes`/`gearNotes` emitted but not restored on reload |
| H5 | HIGH | round-trip | Patent-level `comments` written to META but never read back on reload |
| H6 | HIGH | schema drift | Reviewed export = 10 cols (no `Needs_Review`) and blanks `Options`/`Definition` on every row, vs Python's 11-col schema with populated Options; breaks any Needs_Review/Options-based validator pointed at a reviewed file |
| M1 | MEDIUM | heuristic | SigLIP `acSty` over-labels "Render" (~85%) — argmax on raw cosines, no prior toward line art |
| M2 | MEDIUM | heuristic | SigLIP `parts` over-assigned — absolute `PARTS_THRESHOLD = 0.20` |
| M3 | MEDIUM | heuristic | SigLIP `per` (perspective) unreliable on top/bottom/side (known, Task 3) |
| M4 | MEDIUM | heuristic | Auto-approval at avg conf ≥ 0.45 is a weak in-domain proxy (mitigated: stays `Needs_Review=True`) |
| M5 | MEDIUM | heuristic | `confidence_routing` thresholds + `_margin_flag` (0.05 / 0.45) are admitted guesses; calibrate from the real distribution |
| M6 | MEDIUM | heuristic | G1 keyword priors fire at a hardcoded 0.92 and are never flagged; "helicopter"/"main rotor and tail" risk false positives in comparative prose |
| M7 | MEDIUM | heuristic | G1 keyword set has **no rules for HB or PFV** even though both are in the def/vocab set (Task 3 saw HB-vs-TP) |
| L1 | LOW | nit | `parts` join/split on `"\|"` corrupts a custom token containing `\|` |
| L2 | LOW | nit | Wing-1 `role` emitted but ignored on reload (`ingestAI` `i>1` guard); harmless (defaults "Main") |
| L3 | LOW | nit | Very long `description_of_drawings` may hit Excel's 32767-char cell cap |
| L4 | LOW | nit | `labelToken`/`timestamp`/`familyId` META not reloaded (regenerated — fine) |

---

## 2. The four parts

### PART 1 — Save-path + field-coverage audit

**Save path (wizard → file):**
`S.*` state + `S.figData[fNum]` → `buildExport()`
(html:1639) → builds `rec` incl. `figures` (a shallow copy of every `figData` field) and
`architectures: buildArchitectures()` (html:1624, one morphology per arch via
`buildMorphologyObj()` html:1608) → `commitReviewedRows(pid, record)` (html:2249) calls
`recordToRows(record, pid)` (html:1910) and replaces any prior rows for that base id in
`REVIEWED_ROWS` → `exportReviewedBatch()` (html:2017) =
`XLSX.utils.json_to_sheet(REVIEWED_ROWS, {header: EXCEL_COLUMNS})` → `XLSX.writeFile` →
`reviewed_patents_<label>.xlsx`.

**Reload path (file → wizard):**
xlsx upload handler (html:2379) `sheet_to_json` → group rows by `basePatentId` →
`loadBatchPatent(idx)` (html:2312) → `ingestPatentRows(rows)` (html:2288) → per
architecture: `rowsForArch()` (html:2277) → `rowsToAIData()` (html:2072) →
`ingestAI()` (html:1663) → `captureAircraftSnapshot()` into `archProfiles[]`.

**Key structural fact:** `buildExport().figures[fNum]` is `Object.assign({}, fd, …)` — it
captures *every* `figData` field. So the loss is **not** in `buildExport`; it is in
`recordToRows()` (which serialises only a subset to rows) and in
`rowsToAIData()`/`ingestAI()` (which read back an even smaller subset).

#### Field-by-field coverage table

Legend: ✔ = handled · ✘ = dropped · n/a = not applicable.

**T1 / patent-level (`S.*`)**

| Field (UI) | in buildExport | emitted by recordToRows | restored on reload | Verdict |
|---|---|---|---|---|
| isApproved | ✔ | ✔ T1 (html:1925) | ✔ (rowsToAIData:2090 → ingestAI:1667) | OK |
| t1DisapproveReason | ✔ | ✔ (html:1926) | ✔ | OK |
| disapproveOther | ✔ | ✔ META (html:1934) | ✔ (rowsToAIData:2092) | OK |
| scope / t1Field / t1Target | ✔ | ✔ (html:1922-1924) | ✔ (rowsToAIData:2081-2083) | OK |
| aircraftName | ✔ | ✔ T1 (html:1916) | ✔ (loadBatchPatent metaVal:2350) | OK |
| archCount | ✔ | ✔ (html:1927) | ✔ (rowsToAIData:2093 + ingestPatentRows:2309) | OK |
| isDuplicate / duplicateId | ✔ | ✔ (html:1928-1929) | ✔ (rowsToAIData:2094-2095) | OK |
| duplicateType | ✔ | ✔ META (html:1933) | ✔ (rowsToAIData:2096) | OK |
| **mainFigure** | ✔ | ✔ META (html:1935) | **✘** (no reader) | **H3** |
| **comments (patent)** | ✔ | ✔ META (html:1936) | **✘** (no reader) | **H5** |

**T2 per-figure (`S.figData[fNum]`)**

| Field (UI) | in buildExport | emitted by recordToRows | restored on reload | Verdict |
|---|---|---|---|---|
| per / acSty / acCol / bgSty / bgCol | ✔ | ✔ (html:1950-1952) | ✔ (rowsToAIData:2134 → ingestAI:1754) | OK |
| parts | ✔ | ✔ join "\|" (html:1953) | ✔ split "\|" (rowsToAIData:2137) | OK |
| dupOfPatent / dupOfFig | ✔ | ✔ (html:1956-1957) | ✔ (rowsToAIData:2134) | OK |
| **status** (approve/disapprove) | ✔ | ✔ (html:1954) | **✘** (rowsToAIData T2 list omits it; ingestAI:1766 deliberately won't auto-set) | **H1** |
| **rotation_deg** | ✔ | ✔ (html:1955) | **✘** (only `rotation_deg_suggested` read, ingestAI:1763) | **H2** |
| **qualityFlag** | ✔ | **✘** | — | **C1** |
| **hasLegends** | ✔ | **✘** | — | **C2** |
| **comment** (figure notes) | ✔ | **✘** | — | **C3** |
| **edgeTags** | ✔ | **✘** | — | **C4** |
| **arch** (figure→arch) | ✔ | **✘** | — | **C5** |

> Source for "set in UI": `figSet(... 'qualityFlag')` html:2684 (`data-fig-quality`),
> `hasLegends` via `data-fig-bool` html:2957-2959, `comment` via `data-fig-comment`
> html:3010-3012, `edgeTags` html:2695/2710/2720, `arch` via `data-t2-arch` html:2955.
> `recordToRows()`'s T2 loop (html:1950-1957) emits only per/acSty/acCol/bgSty/bgCol /
> parts / status / rotation_deg / dupOfPatent / dupOfFig — the five fields above are
> absent. `partsMulti`/`gridShowText` are transient UI state and correctly dropped.

**G1 / M1 / M2 / M3 (per architecture)**

| Field (UI) | in buildExport | emitted by recordToRows | restored on reload | Verdict |
|---|---|---|---|---|
| G1 topType | ✔ | ✔ per-arch (html:1970) | ✔ (rowsToAIData:2098 → ingestAI:1681) | OK |
| M1 fusShape/fusKin/gearArch/latSym | ✔ | ✔ (html:1973-1976) | ✔ (rowsToAIData:2103) | OK |
| M1 footLen/footWid/footHgt/footAmbiguous/longSym | ✔ | ✔ (html:1977-1981) | ✔ (rowsToAIData:2104) | OK |
| **wingNotes/empNotes/fusNotes/gearNotes** | ✔ | ✔ (html:1982-1985) | **✘** (rowsToAIData M1 list:2103-2104 excludes notes; ingestAI never sets) | **H4** |
| M2 wingConf/wCount/empType/empKin | ✔ | ✔ (html:1988-1991) | ✔ (rowsToAIData:2103) | OK |
| M2 per-wing wing{i}_tilt/posV/posL/plan/role | ✔ | ✔ (html:1992-1999) | ✔ (rowsToAIData:2167-2181 → ingestAI:1729) | OK (wing-1 role ignored, L2) |
| M3 count/chord/orient/bmech/rmech/zone/zoneChord/zoneSpan/notes | ✔ | ✔ (html:2004) | ✔ (rowsToAIData:2146-2160 → ingestAI:1780) | OK |
| **M3 propKin** | ✔ (buildMorphologyObj:1616) | **✘** (M3 emit list html:2004 omits it) | (TP re-derived via lock) | **C6** |
| **M3 sym** | **✘** (buildMorphologyObj:1616 never reads it) | **✘** | — | **C7** |

#### Known-lead confirmation (Needs_Review / META / pdf_link)

- **`EXCEL_COLUMNS` (html:1894) = 10 columns, no `Needs_Review`.** `COLUMNS`
  (`excel_schema.py:40`) = 11, with `Needs_Review`. Every `reviewRow()` object (html:1896)
  has exactly the 10 keys, so the reviewed sheet has exactly 10 columns — `Needs_Review`
  is simply never written (it is not "filtered out" by the header; there is no key to
  filter). **Does anything rely on it?** The only current consumer of the reviewed file,
  notebook **cell 18**, reads only `Section=="T1" & Field=="isApproved"` → harmless.
  `scripts/overnight_audit.py` *does* read `Needs_Review` (line 109/116) and `Options`
  (line 67), but it is pointed at the **ML** `ml_predict_labels_*.xlsx` (which has both),
  not the reviewed file. **Verdict:** dropping `Needs_Review` is harmless today but is a
  latent landmine for PART 4 (see H6).
- **`Options`/`Definition` are blank on every reviewed row** (`reviewRow` html:1899 sets
  both to `""`). This is the bigger schema drift than the missing column: a
  vocabulary validator that checks `Value ∈ Options` (as `overnight_audit.check_schema_drift`
  does) will **skip every reviewed row** (empty Options ⇒ no check). Validate reviewed
  files against the canonical vocab imported from code, not the Options column.
- **META rows survive** the export (they are ordinary `reviewRow` objects with the 10
  keys; `json_to_sheet` writes all array elements). On reload they are grouped under the
  base `Patent_ID` and read by `Field` (duplicateType/disapproveOther are consumed;
  mainFigure/comments/labelToken/timestamp are written but never read — H3/H5/L4).
- **`pdf_link`**: produced by `scripts/inject_pdf_links.py` into the ML file and read on
  load (`metaVal('pdf_link')` html:2347). `recordToRows()` does **not** re-emit a
  `pdf_link` row, so a reviewed file reloaded later loses the PatSeer PDF link (the wizard
  falls back to the always-resolvable EPO Espacenet link, html:2344 — acceptable, LOW).

#### Multi-architecture round-trip

Confirmed working **for the morphologies**: `recordToRows()` suffixes G1/M rows with
`_arch{N}` when `record.architectures.length > 1` (html:1965-1967); the upload handler
collapses them under `basePatentId` (html:2396); `ingestPatentRows()` (html:2288) derives
`archIdxs` from the suffixes, rebuilds `S.archProfiles[]` per arch via
`rowsForArch()`+`rowsToAIData()`+`ingestAI()`, and `getArchCount()` (reviewer parity:
`getArchCount` html) keeps the count via `archProfiles.length`. Re-saving emits the same
N architectures. **What is lost (C5):** the per-figure `arch` assignment is never emitted,
so after one round-trip every figure's "Assign To" reverts to *Architecture 1*. The
architecture *count* and each architecture's *morphology* survive; the *figure↔arch
mapping* does not.

---

### PART 2 — XLSX save correctness / bug hunt

- **`json_to_sheet(rows, {header: EXCEL_COLUMNS})` and "extra keys":** not triggered
  today — every row is a `reviewRow()` with exactly the 10 header keys. Note for the
  future: if someone adds a key to `reviewRow` that is **not** in `EXCEL_COLUMNS`, SheetJS
  appends it as a trailing column rather than dropping it (the inverse risk of the
  Needs_Review case), so keep `reviewRow` and `EXCEL_COLUMNS` in lockstep.
- **Booleans:** `isApproved`/`isDuplicate`/`latSym`/`longSym`/`footAmbiguous`/m3 `sym`
  are stored as real JS booleans in `Value`; SheetJS writes Excel boolean cells; reload
  coerces via `xlBool()` (html:2059), which also accepts `"true"/"false"/1/0/yes/no/""`
  from hand-edited files. **Correct.** One asymmetry: `xlBool("")` and `xlBool("false")`
  both return `false`, so a *blank* boolean cell reads as `false`, not "unset" — fine for
  these fields but worth knowing.
- **`null`/empty:** `reviewRow` writes `null` → empty cell; reload uses
  `sheet_to_json({defval:null})` and treats `'' `/`null` as absent (`val()` html:2077,
  `metaVal` html:2331). Consistent.
- **Delimiter collisions:** `parts` is the only `"|"`-joined field; a custom part token
  containing `"|"` would split wrong on reload (L1). No field is `","`-joined, and `.xlsx`
  is XML (not CSV) so commas/newlines/quotes/non-ASCII in notes or
  `description_of_drawings` are stored verbatim and survive — **except** Excel's hard
  32767-char-per-cell limit could truncate a very long `description_of_drawings` (L3).
- **`commitReviewedRows()` dedup (html:2249):** correct. It drops *all* prior rows whose
  `basePatentId(r.Patent_ID) === pid` (html:2253) before concatenating the fresh rows, so
  re-saving a patent — including a multi-arch one whose rows are `pid_arch1/_arch2` —
  never leaves stale architecture rows or duplicates. Edge case that is fine: if a patent
  previously had 3 architectures and now has 2, the old `_arch3` rows are correctly
  removed because the base-id filter catches them.
- **Producer-vs-loader field-name drift** (Python `build_patent_rows` writes / HTML
  `rowsToAIData` reads):
  - Python emits `match_status` + `composite_confidence` per image (excel_schema:212) and
    `parts_scores` is *not* emitted (only the thresholded `parts` list). The HTML loader
    ignores `match_status` on the T2 read (only per/acSty/acCol/bgSty/bgCol/parts/
    dupOfPatent/dupOfFig are mapped, html:2134) — harmless, it is informational.
  - Python emits T1 `abstract`, `pub_year`, `app_year`, `description_of_drawings`,
    `title` — all read via `metaVal` on load. ✔
  - Python emits M3 `propKin` and `{component}_sym` rows; the HTML **reads** them on load
    (`ingestAI` html:1784/1789) but **does not re-emit** them on save (C6/C7) — so the
    ML→wizard direction is fine; the wizard→reviewed direction loses them.
  - Python emits `{component}_count/zone/zoneChord/zoneSpan/notes` (manual M3) — all
    round-trip. ✔
  - HTML emits a `META` section Python never produces; Python emits a `T1`
    `description_of_drawings`/`abstract` the HTML treats as metadata. No crash either way
    (both sides group by `Field`/`Section` defensively), but a *strict* schema validator
    should expect `META` rows and blank Options in reviewed files.

---

### PART 3 — Labeling-heuristic review (assess + recommend; no code changed)

**M4 — Auto-approval (`excel_schema.py:160-181`).** `isApproved=True` when all three of
scope/t1Field/t1Target predicted **and** their average confidence ≥ `0.45`; `False`
("Unreadable") only when none of the three predicted. *Assessment:* the threshold is
defensible for *PatentSBERTa*'s compressed confidence range (the in-code comment cites a
real batch floor ~0.40, median ~0.51) and — crucially — it is **only a suggestion**:
`Needs_Review` stays `True` (excel_schema:176) so a human always confirms. The real
weakness is conceptual: "all three triage fields predicted with decent avg confidence" is
a *weak proxy for in-domain* — an out-of-domain patent can still get three plausible-
looking guesses and be auto-suggested approved. *Recommendation:* **keep 0.45 but harden
the gate** — require (a) all three present, (b) avg ≥ 0.45, **and** (c) no single field
below a floor (~0.35); and consider wiring the existing `src/triage_filter.py` signal as
the actual in-domain test rather than reusing the taxonomy classifier. Monitor the
auto-approve rate per batch; if >~90% clear it, the suggestion has stopped discriminating.

**M5 — `confidence_routing` + `_margin_flag` (config.yaml:51-56; reviewer.py:567-593).**
Thresholds G1 0.45 / M1 0.40 / M2 0.40 / M3 0.35 / T2 0.35, margin flag at top1−top2 <
0.05 or conf < 0.45, flagged guesses capped to 0.30. The config comment itself says
"Start conservative … Tighten after inspecting the confidence distribution" — i.e. these
are seeds, not calibrated. *Recommendation — concrete calibration recipe:* from a
finished `ml_predict_labels_<batch>.xlsx`, for each `Section` take
`df[df.Section==S].Confidence.dropna()`, plot the histogram, and set the routing threshold
at the **target human-review budget** (e.g. flag the lowest 25% → threshold = 25th
percentile) or at the visible bimodal valley between the "confident" and "guessing" lobes.
For `_MARGIN_FLAG_THRESHOLD`, look at the distribution of `margin` (already stored on each
SBERT pred, reviewer.py:558) for the *known-confusable* pairs (SLC/TP/CVT) and set it
above the median margin of the *wrong* calls in a labeled golden set. Re-run
`scripts/overnight_audit.py` after each change to watch flag coverage.

**M6/M7 — G1 resolution (`resolve_g1` reviewer.py:693; `classify_g1_keyword`
reviewer.py:344; `_G1_KEYWORD_RULES` reviewer.py:324).** The text-primary / vision-
tiebreaker design is sound and Task 3 confirmed it kills the confident-wrong tilt-vs-
lift+cruise case. Two concerns:
- *False-positive risk (M6):* keyword hits return a hardcoded **0.92** and `_margin_flag`
  explicitly **never flags keyword-sourced predictions** (reviewer.py:584). So a single
  substring false hit is silently confident. The riskiest rules are the broad single
  words mapped to a class — `"helicopter"` and `"main rotor and tail"` → **RC**: a
  compound/lift+cruise patent that says "unlike a conventional helicopter…" would mis-fire
  to RC. `"multirotor"/"quadcopter"` → MR is safer (rarely used comparatively).
  *Recommendation:* (a) add light negation/comparative guards for `helicopter` (skip when
  immediately preceded by "unlike a/not a/conventional/than a"); (b) when a keyword hit
  *disagrees* with a strong SBERT prediction (SBERT conf high and different class), allow
  `_margin_flag` to flag it instead of trusting blindly; (c) optionally drop keyword conf
  from 0.92 to ~0.80 so a confidently-disagreeing SBERT can contest it.
- *Coverage gap (M7):* `HB` (hoverbike/straddle) and `PFV` (jetpack/wearable) are in
  `_G1_TOP_TYPE_DEFS`/the vocab but have **no keyword rules**, so they can only ever come
  from SBERT/SigLIP — exactly the HB-vs-TP miss Task 3 saw (CA2958445A1).
  *Recommendation:* add `(["hoverbike","straddle","saddle","motorcycle-style","seated
  rider"], "HB")` and `(["jetpack","jet pack","wearable","backpack thruster","worn by"],
  "PFV")` to `_G1_KEYWORD_RULES`.

**M1 — `acSty` over-labels "Render" ~85% (`cross_modal.py:317,366,399`).** Root cause:
`classify_t2_fields` takes the **argmax of raw SigLIP cosine similarities** over
`["Render","Line Drawing","Draft","Blueprint"]` with one generic prompt ("The aircraft in
this patent figure is drawn as a {}"). There is **no prior and no margin** — whichever
label SigLIP's contrastive space rates marginally highest wins on every figure, and for
this corpus that is consistently "Render", which is implausible for a line-art-dominated
patent set. *Recommendation (cheapest reliable fix first):* **default `acSty="Line
Drawing"` and only flip to "Render" when (a) `render_score − linedrawing_score >` a
calibrated margin (~0.05-0.10) AND (b) a corroborating signal exists — `acCol != "B/W
(Monochrome)"` or `bgSty == "Shaded/Gradient"`.** Secondarily, sharpen the prompts the
way `T2_PER_PROMPTS` already does for perspective (e.g. "a clean black-and-white technical
line drawing with uniform stroke width and no shading" vs "a photorealistic shaded 3D
render with gradients, reflections and soft shadows"). Calibrate the margin on the golden
set from PART 4. Until fixed, treat `acSty` as untrusted (consistent with Task 3's GO/NO-GO).

**M2 — `parts` over-assigned (`cross_modal.py:362,407-409`).** `PARTS_THRESHOLD = 0.20`
is an **absolute** cosine cutoff; SigLIP's clamped cosines for these prompts routinely sit
above 0.20, so many parts are tagged on a single layout figure. *Recommendation:* align
the *prediction* with Task A's new single-select UI default — **export only the top-1 part
as the suggestion** (or top-1 plus any part within a small margin of it), or switch to a
**relative** rule (keep parts with score ≥ max_score − δ) and/or require the part to beat
the "Whole Vehicle Layout" baseline. Calibrate δ/threshold on the golden set. This plus
Task A's single-select UI fixes both the prediction and the human-entry side.

**Physics locks — assessment (excel_schema.py:280-328; ingestAI html:1686-1747,1790-1799).**
- `TP → propKin=Tilt` (excel_schema:327, html:1688/1799): correct by definition.
- `TW → empKin=Fixed` + wing orient Horizontal (excel_schema:289, html:1689-1691): a
  tilt-wing rotates the whole wing, so a separate empennage is normally fixed and the
  wing-mounted thrust is horizontal *relative to the wing*. Generally correct; only mild
  over-constraint is forcing `empKin=Fixed` if a TW genuinely had an all-moving
  stabilator (rare). Keep.
- `RC/MR → wTilt=null` (excel_schema:284, html:1692-1693): rotorcraft/multirotor have no
  tilting *wing* by taxonomy — correct.
- `SLC/SRW → strip "Mixed" orient` (excel_schema:319, html:1795-1796): SLC (fixed
  lift+cruise) and SRW (stopped rotor) do not tilt/vector, so a "Mixed" orient is
  physically impossible — correct, and it sensibly prevents an ML guess the human can't
  even pick. **Verdict: the locks are physically sound; keep all of them.** (They are the
  reason C6's `propKin` loss is only *partially* recoverable — TP is reconstructed by the
  lock, the others are not.)

---

### PART 4 — Test plan before full-batch labeling (≈30-min checklist)

Goal: prove the round-trip is lossless **or** document exactly which fields are lost
(this audit predicts the C/H findings will show up). Do it on a tiny golden set first.

**A. Build a golden set (5-6 patents) in the wizard (~10 min)**
1. Load `ml_predict_labels_<batch>.xlsx` via "Load Batch". Pick: ① a normal multi-figure
   patent, ② one you mark **Disapproved**, ③ one you flag **Duplicate** (set dupOfPatent /
   dupOfFig), ④ a **no-figure** patent, ⑤ a **multi-architecture** patent (use "Assign To"
   to put figures on Architecture 1 and 2, "+ Add architecture", give the two archs
   *different* G1/M values).
2. On at least one figure, set **every at-risk field to a distinctive value**:
   `qualityFlag` (pick a non-default), tick `hasLegends`, type a unique **figure note**
   ("AUDIT-NOTE-123"), add an **edge tag** ("AUDIT-TAG"), **approve** one figure /
   **disapprove** another, **rotate** one 90°, **Set as Main** one figure, assign a figure
   to **Architecture 2**.
3. On M3 for a **non-TP** patent: set a `propKin` ≠ Tilt and tick a `sym` checkbox. Type
   `wingNotes`/`fusNotes` and a patent-level comment.

**B. Export + reload (~5 min)**
4. Click "Export batch" → `reviewed_patents_<label>.xlsx` (lands in
   `cfg.paths.html_review_exports`, default `~/Downloads`).
5. **Reload that reviewed file** into the wizard and step through. Record which of the
   step-2/3 values survived. *Expected per this audit:* per/acSty/acCol/bgSty/bgCol/parts/
   dupOfPatent/dupOfFig + all M1/M2/M3 (except propKin/sym) + topType + T1 triage survive;
   **lost on reload:** figure status, rotation, mainFigure, M-notes, patent comments;
   **never in the file at all:** qualityFlag, hasLegends, figure comment, edgeTags, figure
   arch, M3 propKin, M3 sym.

**C. Inspect the file directly (~10 min)** — run in a scratch cell / `python3`:
```python
import pandas as pd
df = pd.read_excel("~/Downloads/reviewed_patents_<label>.xlsx", sheet_name="Review")
# 1) Prove the SAVE losses (these Field values should be ABSENT):
for f in ["qualityFlag","hasLegends","comment","edgeTags","arch","propKin","sym"]:
    print(f, "rows:", (df.Field.astype(str).str.contains(f)).sum())   # expect 0 (propKin/sym only as *_propKin/_sym)
# 2) Prove the SAVE survivors that don't reload (should be PRESENT):
for f in ["status","rotation_deg","mainFigure","wingNotes","comments"]:
    print(f, "rows:", (df.Field==f).sum())                            # expect >0
# 3) Multi-arch: both arch suffixes present and morphologies differ
print(sorted({p for p in df.Patent_ID if "_arch" in str(p)}))
# 4) Schema drift checks
print("has Needs_Review col:", "Needs_Review" in df.columns)          # expect False
print("nonblank Options rows:", (df.Options.fillna("")!="").sum())    # expect 0
```
6. **Spot-check ~10 values** in the open xlsx against what you typed in step 2/3 (the
   surviving fields should match exactly; "AUDIT-NOTE-123"/"AUDIT-TAG" should be **gone**).

**D. Validate vocabulary the right way (~5 min).** Do **not** reuse
`overnight_audit.check_schema_drift` as-is on a reviewed file (Options is blank → it
checks nothing; and `check_flag_coverage` will `KeyError` on the missing `Needs_Review`).
Instead build the legal-vocab map from code and guard the Needs_Review column:
```python
from src.excel_schema import _OPT
from src.reviewer import (_T1_SCOPE_DEFS,_T1_FIELD_DEFS,_T1_TARGET_DEFS,
   _M1_FUS_SHAPE_DEFS,_M1_FUS_KIN_DEFS,_M1_GEAR_ARCH_DEFS,
   _M2_WING_CONF_DEFS,_M2_EMP_TYPE_DEFS,_M2_EMP_KIN_DEFS,
   _M3_CHORD_DEFS,_M3_ORIENT_DEFS,_M3_BMECH_DEFS,_M3_RMECH_DEFS,_M3_PROPKIN_DEFS)
from src.cross_modal import G1_TOP_TYPES,T2_PER,T2_AC_STY,T2_AC_COL,T2_BG_STY,T2_BG_COL
VOCAB = {"scope":_OPT(_T1_SCOPE_DEFS),"t1Field":_OPT(_T1_FIELD_DEFS),
   "t1Target":_OPT(_T1_TARGET_DEFS),"topType":_OPT(G1_TOP_TYPES),
   "per":"|".join(T2_PER),"acSty":"|".join(T2_AC_STY), ...}  # extend per field
# For each df row whose Field is in VOCAB, assert str(Value) in VOCAB[Field].split("|")
```
7. **Confirm images resolve:** for every `Section=="T2"` row, check `Path(Image_Path)`
   exists on disk or equals the `no_image_available.png` placeholder; flag any other
   missing path.

**E. Go/No-Go.** If C/H losses are unacceptable for your ground-truth, fix
`recordToRows()` (+ matching readers in `rowsToAIData`/`ingestAI`) **before** labeling a
full batch — every patent labeled before the fix will silently lack those fields and would
need re-labeling. If you only need G1/M1/M2/M3 (minus propKin/sym) + T1 triage + the core
T2 visual fields right now, the current path is safe to proceed with, with the at-risk
fields treated as not-yet-captured.

---

## 3. Pointers for a future fix (not done here — review only)

The CRITICAL cluster is a one-function fix surface: extend `recordToRows()` (html:1910)
to emit `qualityFlag/hasLegends/comment/edgeTags/arch` per T2 figure and `propKin/sym` per
M3 card, add `sym` to `buildMorphologyObj()` (html:1616), and mirror each new field in the
readers `rowsToAIData()` (html:2072) / `ingestAI()` (html:1663) to also close H1/H2/H4
(status/rotation/notes) and have `loadBatchPatent()` read `mainFigure`/patent `comments`
back (H3/H5). Keep `EXCEL_COLUMNS` and `reviewRow` in lockstep, and decide whether the
reviewed export should re-populate `Options` (re-enables Options-based validation) and add
`Needs_Review` for parity with the 11-column Python schema (H6). None of these were
changed in this review.
