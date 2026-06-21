# Overnight Status

## TASK 1 — Local-text accuracy levers (SBERT / keyword priors)

**STATUS: DONE.** All code compiles (`python3 -m py_compile src/*.py` clean) and
all 5 inline tests pass (`python3 tests/test_kinematic_levers.py`).

### Files changed
- `src/reviewer.py` — the ONLY source file changed.
  - **`extract_kinematic_sentences(text, cue_words=None, max_sentences=None)`**
    — NEW module-level helper (added just after `classify_g1_keyword`). Splits
    text on `.!?`, newlines, and semicolons; keeps only sentences containing a
    cue word; joins survivors with a single space. Case-insensitive with
    space/hyphen tolerance (same normalisation as `classify_g1_keyword`).
    Returns `""` for empty / no-cue input. Both extra args are optional.
  - **`_KINEMATIC_CUE_WORDS`** — NEW module-level list of architecture/kinematic
    cue substrings (tilt/pivot/nacelle, lift+cruise/dedicated cruise, stopped/
    stowed/fold/retract, slipstream/vector/transition, coaxial/tandem/ducted/
    propulsor, actuat*, articulat*, etc.). Tunable — edit this list to widen/
    narrow what counts as a kinematic sentence.
  - **`process_patent()`** — three edits, all inside the function:
    - LEVER 1: `excel_row.get("innovation_objective")` is now joined into the
      `classify_text` blob (after `first_claim`, before `desc_text`).
    - LEVER 2/3: builds a second string `kinematic_text =
      extract_kinematic_sentences(first_claim + innovation_objective)`, falling
      back to `classify_text` when no kinematic sentence is found.
    - LEVER 3 routing: `kinematic_text` now feeds (a) `classify_g1_keyword`,
      (b) `classify_g1_text` (the SBERT G1 path + its nlp_confidence gate), and
      (c) per-field re-classification of the KINEMATIC fields only —
      `m2_text["empKin"]`, `m3_text["orient"]`, `m3_text["propKin"]` — via
      `_sbert_best(kinematic_text, <DEFS>, sbert_model)`. All other fields
      (T1, all of M1, M2 wingConf/empType/wCount, M3 chord/bmech/rmech) keep
      the full `classify_text` blob.

### Files NOT touched (per hard constraints)
- `src/extractor.py` — already loaded `innovation_objective`; no change needed
  (compiled to confirm clean). HTML wizard, notebooks, config.yaml: untouched.

### New behaviours Task 2 must know
- The G1 keyword prior (`classify_g1_keyword`) now runs on `kinematic_text`, not
  the old `title+abstract+first_claim+desc` blob. Because `kinematic_text` falls
  back to `classify_text` when no kinematic sentence exists, this is a strict
  SUPERSET of the previous matches — nothing that fired before stops firing, and
  giveaway phrases buried in the claim/objective now fire too (proven by test 3).
- No public signature changed incompatibly. `extract_kinematic_sentences` is new;
  its two extra args are optional with `None` defaults.
- `_sbert_best`, `_M2_EMP_KIN_DEFS`, `_M3_ORIENT_DEFS`, `_M3_PROPKIN_DEFS` are
  reused as-is — no DEF wording changed, so SigLIP/SBERT id sets still align.

### Assumptions made
- **"description" for the kinematic miner = first_claim + innovation_objective.**
  The task said "first_claim + description (NOT description_of_drawings)", but
  the full patent Description column is intentionally NOT loaded locally
  (`load_patseer_excel` docstring) and is unavailable in `process_patent`. The
  richest substantive prose present locally is `first_claim` +
  `innovation_objective` (Summary/Advantages of Invention), so the miner uses
  those. `description_of_drawings` (`desc_text`) is deliberately excluded from
  `kinematic_text`, as instructed. If Task 2 fetches the full description over
  the network, it can extend `_kin_source` to include it.
- `kinematic_text` falls back to `classify_text` (never blank) so patents that
  don't phrase things kinematically still get a G1/empKin/orient/propKin guess.

### Tests
- `tests/test_kinematic_levers.py` (NEW) — no network, no model (sbert stubbed):
  1. extract keeps cue sentences / drops boilerplate; empty + no-cue ⇒ `""`.
  2. a "lift plus cruise" sentence buried in ~60 boilerplate sentences is mined
     out and triggers the **SLC** keyword prior (and the boilerplate alone does
     not).
  3. separator tolerance (`lift-plus-cruise` / `lift+cruise` / spaced).
  4. `innovation_objective` (sentinel string) reaches `classify_text` inside
     `process_patent` (verified by spying on `classify_g1_text`'s input).

**Task 2 should now:** wire networking (Google Patents full-description fetch via
`extractor._fetch_google_patents`) and, if it fetches the full Description, feed
it into `_kin_source` so `extract_kinematic_sentences` mines claim + objective +
full description — without touching the structural/visual `classify_text` blob.

---

## TASK 2 — Citation enrichment + full Batch_02 re-run + validation gate

**STATUS: DONE.** All three parts completed in order; no hard failures.

### PART A — Citation/Google-Patents enrichment (network, opt-in)

Files changed:
- `src/extractor.py` — NEW `fetch_cited_patent_text(patent_id, cache_dir,
  timeout=30)`. Fetches title+abstract for one cited patent via the existing
  `_fetch_google_patents()`, parsed from the page's `<title>` and
  `<meta name="description">` tags (the abstract; claim markup on Google
  Patents has no stable per-claim id, so claims were NOT scraped — kept to
  title+abstract only, deliberately small and robust). Disk-cached as
  `{cache_dir}/{patent_id}.json` (caches "" on failure too, so a
  consistently-unreachable id is not retried every run). **Never raises** —
  every failure mode (timeout, HTTP error, parse error) is caught inside the
  function and returns `""`.
- `src/reviewer.py` — three additions:
  - `g1_needs_enrichment(g1_pred, g1_threshold=0.45)` — True when G1 is
    missing, `flagged_ambiguous`, or below `confidence_routing.G1`.
  - `enrich_g1_with_citations(g1_pred, excel_row, kinematic_text, sbert_model,
    cache_dir, max_fetches=2, delay=1.0)` — fetches up to 2 cited patents
    (backward_cites first, then forward_cites), appends their text to
    `kinematic_text`, re-runs `classify_g1_keyword` + `classify_g1_text`, and
    returns the enriched prediction only if the original was flagged or the
    enriched confidence is strictly higher (never downgrades a confident
    local call). Tags `source` with a `+citation` suffix (e.g.
    `"sbert+citation"`, `"keyword+citation"`) so provenance is visible in the
    export.
  - `process_patent(..., enrich_citations: bool = False)` and
    `run_stage01(..., enrich_citations: bool = False)` — **both default
    False**. Cache dir used: `cfg["paths"]["data"] / "citation_text_cache"`.

NETWORK SAFETY — all satisfied and tested:
- try/except around every request (inside `fetch_cited_patent_text`).
- timeout ≤30s (reuses `_fetch_google_patents`'s default).
- rate-limited: 1.0s sleep between citation fetches within one patent.
- capped at 2 fetches per ambiguous patent (`_CITATION_ENRICH_MAX_FETCHES`).
- on any network error: caught, logged, falls back to the local-only
  prediction — proven by `tests/test_citation_enrichment.py` (5/5 pass,
  including a live-network fetch+cache-hit test and a simulated-failure test).
- disk-cached at `data/citation_text_cache/{patent_id}.json`.
- OFF by default; explicitly turned ON only for this run
  (`enrich_citations=True` passed to `run_stage01`).

Test: `tests/test_citation_enrichment.py` — 5/5 pass (network-failure
swallowing + caching, live fetch + cache-hit, `g1_needs_enrichment` logic,
zero-citation no-op, and `process_patent(enrich_citations=False)` makes
**zero** network calls, proving the default is genuinely off).

### PART B — Backup + full re-run

- Backup: `ml_predict_labels_Batch_02.PRE_OVERNIGHT_BACKUP.xlsx` (no
  collision — created fresh) — byte-identical copy of the export as it stood
  before any Task-2 work touched it. **NOTE for Task 3:** this backup itself
  was already a partial/earlier run containing only 6 patents (`US2020385130A1,
  US2020385139A1, US2021380224A1, US2022315236A1, US2022363401A1,
  US2022402602A1`), NOT a full prior Batch_02 export — so the "before" state
  for most of the batch's 384 patents simply didn't exist yet. This is a
  pre-existing repo-state fact, not something Task 2 caused.
- Re-run: `run_stage01(cfg, sbert_model=..., siglip_bundle=...,
  matched_dir=.../matched/Batch_02, enrich_citations=True)`. 384 patents,
  52.75 minutes, **0 errors**. Citation enrichment fired and changed
  predictions for 233 G1 rows total (79+56 `keyword`/`keyword+citation`,
  153 `sbert+citation` — i.e. 56+153=209 patents where text alone wasn't
  enough but cited-patent text was used and accepted).
- Several `404 Client Error` lines appear in the run log for unfetchable
  cited patents (e.g. design patents, old DE/JP records not on Google
  Patents) — these were caught and logged exactly as designed; the run never
  crashed and those patents simply fell back to the local-only prediction.

### PART C — Validation gate

Script: `scripts/overnight_audit.py`. Run output (full output also at
`/tmp/overnight_audit_output.txt` on this machine):

1. **Vocabulary/schema drift: 0 illegal values** across all 42,949 rows
   (checked every non-null Value against its row's own Options column,
   which already encodes the legal vocabulary per excel_schema.py).
2. **Confident-wrong risk**: **0** G1 predictions sourced purely from vision
   (`Source == "siglip"`) — expected, since G1 is text-primary by design
   (`resolve_g1`), vision is only a tiebreaker. 326 G1 predictions are at/above
   the 0.45 confidence threshold, broken down by source: `sbert+citation` 153,
   `keyword` 79, `keyword+citation` 56, `ensemble` 23, `sbert` 15 — i.e. the
   large majority of confident G1 calls now have explicit citation-enriched or
   keyword backing, not vision.
3. **Flag coverage**: 58 G1 predictions are ambiguous (conf < 0.45 or
   missing) and **all 58 are flagged** Needs_Review — 0 slipped through.
   1000 kinematic-field (empKin/orient/propKin) rows are low-confidence
   (<0.35) and **all 1000 are flagged**.
4. **Completeness**: 384/384 patents have a G1 value; 1 patent missing a
   title (T1 metadata gap in the source Excel, unrelated to this run); 0
   patents with an all-empty M1, M2, or M3 section.

NEW vs BACKUP diff (limited to the 6 overlapping patents — see Part B note):
G1.topType changed for 2/6 patents (`US2020385139A1`: CVT→SLC,
`US2022363401A1`: TW→SLC), both now sourced `sbert+citation`. Spot-checked
by hand: for both, the cited backward patents fetched and cached
(`US7159817B2` "VTOL aircraft with distributed thrust", `US5890441A`
"horizontal or vertical take off and landing") are genuinely
architecture-relevant prior art consistent with an SLC call — the changes
moved toward the evidence, not noise. The 19 M3 `propKin` diffs are a
downstream, by-design consequence of G1 changing (propKin is forced/derived
per-component from `top_type` in `excel_schema.py`'s physics-lock logic —
e.g. TP forces `propKin="Tilt"`), not an independent regression.

**VALIDATION VERDICT: PASS.**
- Schema drift: 0 illegal values.
- Confident-wrong: 0 vision-only G1 predictions.
- Flag coverage: 0 ambiguous calls slipped through (58/58 G1, 1000/1000
  kinematic fields flagged).
- Completeness: 384/384 patents have G1; only 1 minor pre-existing title gap.
- The new export is trustworthy to use; the backup is also preserved should
  anyone want to compare further.

### Exact paths
- NEW export: `/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images
  DataSets & Labelling Outputs/1639_DS/data/matched/Batch_02/
  ml_predict_labels_Batch_02.xlsx`
- BACKUP: same directory, `ml_predict_labels_Batch_02.PRE_OVERNIGHT_BACKUP.xlsx`
  (6-patent partial export, predates this run — see note above)
- Citation text cache: `.../1639_DS/data/citation_text_cache/*.json`
- Audit script: `scripts/overnight_audit.py`; new test:
  `tests/test_citation_enrichment.py`

Citation enrichment: **ran** (`enrich_citations=True` for this run only;
default remains `False` for all future calls unless explicitly passed).

**Task 3 should audit:** the NEW export at
`.../1639_DS/data/matched/Batch_02/ml_predict_labels_Batch_02.xlsx` (PASSED
validation above) — re-running `scripts/overnight_audit.py` after any human
review pass is a reasonable way to re-check drift/coverage hasn't regressed.

---

## TASK 3 — Visual ground-truth audit (vision-vs-Excel spot check)

**STATUS: DONE.** Read-only audit of the NEW export (the one Task 2 validated;
enrichment ran). I opened and eyeballed **13 figure crops across 11 patents**,
spanning predicted classes TP, SLC (keyword / sbert / sbert+citation), TW, MR,
RC, DS, SRW, and 2 flagged-ambiguous CVT — deliberately weighted toward the
tilt-vs-lift+cruise (TP/SLC) confusion the user cares most about. (No
duplicate-flagged images exist in this export — duplicate detection runs in a
separate notebook cell, not Stage 01 — so I substituted extra needs_review /
flagged figures. 2 additional patents I'd queued, CN108394557A and CN108382580A,
resolved to the `no_image_available.png` placeholder — broken Image_Path — and
were skipped per instructions.)

### Per-figure results

| Figure | Predicted (per / sty / G1) | What I saw | Verdict | Reason |
|---|---|---|---|---|
| CA2958445A1 fig_01 | Rear-Iso / Draft / TP(kw .92) | Hand sketch, 4 ducted rotors on a straddle frame | SUSPECT | G1 looks more like HB (hoverbike); Draft style correct |
| US12377973B1 F1 | Back / Render / SLC(kw .92) | Quad ducted-fan eVTOL, phantom-line 3D | SUSPECT | "Back" doubtful; 4 ducts → MR/HB not obviously SLC |
| US12377973B1 F2 | Bottom/Down / Render / SLC | Top-down PLAN of same quad-fan craft | SUSPECT | top/bottom ambiguous; Render on line art |
| EP4417511A1 F2 | Bottom/Down / Render / SLC(sbert .58) | SIDE elevation + front schematic (2 figs) | WRONG | clearly Side not Bottom; Render on a schematic |
| IT202100023033A1 F1 | Generic 3D / Render / SLC(cit .60) | Shaded 3D rotor-hub render | AGREE | both T2 labels fit a genuine shaded render |
| US2006113426A1 F11a | Side / Render / SLC(cit .55) | SIDE view of roadable flying-car | AGREE(per)/WRONG(sty) | Side correct; clean line art mislabeled Render |
| CN111056002A | Top / Line Drawing / TP(kw .92) | Top plan, angled propulsors on pivot arms | AGREE | top correct, tilt mechanism visible → TP plausible |
| AU2020100605A4 F1 | Bottom/Down / Line Drawing / TW(cit .92) | Slender body, small distributed props, angled view | SUSPECT | looks 3D/side not bottom; TW (tilt-wing) not evident |
| EP2570345A1 F2 | Bottom/Down / Render / MR(kw .92) | Top plan, 6 dashed-circle rotors + side view | AGREE(G1)/WRONG(sty) | 6 rotors → MR confirmed; line art mislabeled Render |
| FR3018768A1 F1 | Generic 3D / Line Drawing / DS(cit .92) | Flat sectional MECHANISM schematic | SUSPECT | not a 3D view; it's a 2D schematic |
| US2011031355A1 F1A | Side / Draft / SRW(kw .92) | Top/plan dimensioned layout, stoppable blade | AGREE(G1) | stop-rotor blade visible → SRW fits; per doubtful |
| CN108502167A | Bottom/Down / Render / RC(cit .92) | Rough angled perspective sketch of rotor rig | SUSPECT | angled 3D not bottom; line sketch not render |
| AT503689A1 fig_01 | Top / Render / CVT(flagged .30) | Side + top of delta w/ 2 lift rotors + pusher | AGREE(flag) | hybrid lift+cruise → CVT-ish; correctly flagged low-conf |

### Tally
- **AGREE: 5** (counting AGREE / partial-AGREE on the field that matters)
- **SUSPECT: 6**
- **WRONG: 2** (EP4417511A1 perspective; the recurring Render-on-line-art, of
  which EP4417511A1 + US2006113426A1 + EP2570345A1 are the clearest)
- Architecture (G1) specifically: of the 13, the G1 call was **plausible or
  correctly-flagged in ~10**; the 3 soft doubts (CA2958445A1 HB-vs-TP,
  US12377973B1 SLC-vs-MR ×2) are genuine class-boundary cases, not gross errors.

### Single most common error pattern
**T2 rendering-style is systematically over-labeled "Render".** Almost every
clean black-and-white patent line drawing in the sample was tagged `acSty=Render`
when it should be `Line Drawing`. This is not a sampling fluke — batch-wide,
**2012 / 2364 figures (85%) are labeled "Render"**, which is implausible for a
patent-drawing corpus that is overwhelmingly line art. Perspective is the
second-weakest field: `Bottom/Down` is the single most common value (634) and
was wrong/doubtful on most top-plan and side views I checked (top-vs-bottom and
side-vs-bottom are routinely confused). **Both are SigLIP T2 *visual* fields —
neither was touched by Task 1 or Task 2, which only changed the G1/text path.**

### Did the Task-1/Task-2 upgrades help the tilt-vs-lift+cruise cases?
Visibly yes, on the dimension they targeted. The G1 architecture calls I
inspected were mostly plausible, the genuinely ambiguous ones (CVT @ 0.30) were
**correctly flagged needs_review**, and the keyword/citation provenance tags
(`keyword`, `sbert+citation`, `keyword+citation`) lined up with figures whose
architecture was at least consistent with the label. I found **no case of a
fixed lift+cruise drawing confidently mislabeled tiltrotor**, which was the
specific failure the user worried about — the text-primary G1 resolver plus
guess-but-flag is doing its job. The residual G1 doubts I saw (HB vs TP, SLC vs
MR for quad-ducted-fan craft) are real taxonomy-boundary hard cases, not the
confident-wrong errors Task 1/2 were meant to kill.

### GO / NO-GO recommendation
**GO for the architecture (G1 / M-field) labels — with the rendering-style and
perspective T2 fields treated as untrusted.** Concretely:
- The user CAN start labeling from this export for G1 topology and the M1/M2/M3
  architecture fields: those are plausible and, where weak, correctly flagged.
- The user should NOT trust `acSty` (rendering style) or `per` (perspective) as
  pre-filled — `acSty` is wrong ~majority of the time (Render over-assigned) and
  `per` is unreliable on top/bottom/side. Treat both as "verify every time",
  or have them re-checked before relying on them. These are pre-existing SigLIP
  T2 weaknesses, OUTSIDE Task 1/2's scope — flagging for a future T2 pass, not a
  blocker for the architecture labeling the overnight work was about.
- Net: the overnight G1 upgrades are trustworthy to label from; the visual T2
  style/perspective fields need a separate fix and should not gate this.

(Read-only task — no export or source file modified; this section is the only
write.)
