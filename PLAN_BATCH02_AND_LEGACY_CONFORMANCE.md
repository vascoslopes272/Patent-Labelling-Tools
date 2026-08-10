# Plan — Batch_02 sign-off, 02b split, and legacy (B01/B05) conformance

Written 2026-08-10. Nothing has been changed yet. Three chunks, meant to be fed
back one at a time. Chunk 1 is the only one that blocks Batch_02.

Constraint driving every choice below: **6 days left, ~600 patents still to label.**
Anything that costs annotator hours has to justify itself against those 600.

---

## 0. What I verified before writing this (facts, not assumptions)

**Batch_02 export** — `data/03_HUMAN_wizard_exports/reviewed_patents_Batch_02.xlsx`
(11.6 MB, written today 13:30), 34 959 rows, one `Review` sheet, 7 columns.

| Quantity | Value |
|---|---|
| Distinct `Patent_ID` values | 448 |
| … of which real patents | 399 (batch is defined as **400** — one is missing) |
| … of which `_archN` multi-arch variants | 49 (normal — they inherit T1) |
| `isApproved = True` | 258 |
| `isApproved = False` | 136 |
| `isApproved` blank | 5 — all D2 duplicates, auto-resolved by Rule D |
| Duplicate types present | D1 (18), D2 (84), D3 (3) — no retired type 4 |
| Legacy fields present | none (no `longSym`, no `empKin`, no `boom_t1_*`) |

**The missing 400th patent is `US12377973B1`** — "Flight control of lift plus cruise
quadcopter aircraft". It is present in `batches.xlsx/Batch_02` and in the ML feed
(37 rows), and it has **12 crops on disk** under
`00b2_figure_crops/Batch_02/US12377973B1_96587791/`. It is simply absent from the
export: never labelled, or opened and skipped. This is the one real piece of
labelling work left in Batch_02.

**The 5 blanks are not work.** All five are `isDuplicate=True`,
`duplicateType = 2 — D2 — Same aircraft, same figures`, each pointing at a chain
root that is itself approved:

| Blank patent | Chain root | Root approved? |
|---|---|---|
| `WO2024154415A1` | `US2023006598A1` | True |
| `US2024367808A1` | `US2023006598A1` | True |
| `US2023406528A1` | `US2024059393A1` | True |
| `US2024217652A1` | `US2022388648A1` | True |
| `US2006113426A1` | `US2004155143A1` | True |

Across the whole batch, of 84 D2 duplicates: 79 approved, **0 disapproved**, 5 blank.
**Do not hand-edit them.** 02a's Rule D (`_inherit_from_duplicate_root`) already
covers exactly this case — `if not has_appr and pd.notna(root_appr)` writes the
root's value into the existing blank row. Running 02a resolves all five to `True`
automatically, with `Source = rule_d_inherited` for provenance. Hand-editing would
lose that audit trail.

The 49 IDs with no `isApproved` row are all `<id>_arch1`-style multi-architecture
variants — that is by design, not missing work.

**Your list (a) is stale.** v15_3 already ships items (i)–(viii). I checked each
array in the HTML: `PROP_KIN` is Fixed/Tilt/Other; `QUALITY_FLAGS` is
clean / "Partial Quality" / "Poor Quality" with Draft moved into `T2_AC_STY`;
Blueprint, Grid/Pattern and Blueprint Blue are retired (v15.2, with comments
explaining the retirement); `FUS_SHAPE` has no Pod-and-Boom; `BOOM_ORIENT` has
`X — X / Diagonal (crossing)`; `DUP_TYPES` is 1/2/3; `T1_EDGE_TAGS` is UAVSimilar
alone; the `longSym` export row is deleted with a `v15.3:` comment saying so — and
Batch_02's export confirms it, no `longSym` rows.

**Only item (ix) — L6 — is actually open.** In `pageM1`, `topType === 'TB'` hard-locks
`fusKin` to `TiltBody` via `physicsLock`. Your settled rule allows `VarInc` too.
Blast radius is small: 5 TB patents in Batch_02, 12 in Batch_01, 0 in Batch_05.

**Architecture counts** (for sizing the checks in your list (b)):

| | TW | TB | CVT |
|---|---|---|---|
| Batch_01 | 10 | 12 | 18 |
| Batch_02 | 17 | 5 | 15 |
| Batch_05 | 4 | 0 | 10 |

So the L5 TW→CVT check touches **31 patents total**, not hundreds.

**Schema drift B01/B05 → B02** is real but bounded: 55 fields exist only in B02,
68 only in B01/B05. Most of it is one structural rename (the per-card `wing1_t3_*`
/ `boom_t1_boomAttach` scheme became `wing3_*` / `boom1_attach`). B05 additionally
carries 10 rows of the ambiguous legacy `fusKin = "Variable"` that B01 and B02
do not have.

---

## 1. My one disagreement with the plan as you stated it

**Do not split 02b.** I opened it: 10 cells, and it is almost pure image geometry —
copy approved files, collect batch xlsx, run the 518 px background-aware pad/resize
for DINOv2, QC the seams. The only place a *label* enters is `bgSty` steering
`pad_color_mode: auto`. There is nothing codebook-versioned in there to split.

Splitting it would give you two copies of the image pipeline, and that is a
defensibility problem, not just a maintenance one: the first question about a
dataset processed by two code paths is whether the embeddings are comparable. You
want to be able to say *one* preprocessing function produced all 1639 images.

The split you actually want is **one stage upstream**, at 02a, where the label
semantics live — and 02a is already half-built for it (it already carries
`empKin→empTilts`, the Draft migration, `boomXFormat→BOOM_ORIENT`, A3 `TB→fusKin`,
Rule G for ambiguous `fusKin`). So:

```
Batch_02/03/04  →  02a (current)          ─┐
                                           ├→  02b  (ONE image pipeline, unchanged)
Batch_01/05     →  02a_legacy (NEW, small) ─┘
```

`02a_legacy` is *not* a copy of 02a. It is a short notebook: load raw export →
apply the rename map → apply the value remaps → run the same completeness/consistency
checks → write `Review_postprocess_<batch>_conformed_<ts>.xlsx`. 02b then reads it
like any other batch and needs **zero** changes.

If you'd rather still call the new notebook "02b-legacy", fine — the name doesn't
matter, the single image pipeline does.

---

## 1b. What to strip out of 02a for Batches 02/03/04

You're right that 02a carries things these batches no longer need. Concretely,
8 of its 52 cells only ever fire on a pre-v15_3 export:

| Cell(s) | Rule | Why it's dead for B02/03/04 | Action |
|---|---|---|---|
| 13–14 | Step 0b `empKin`→`empTilts` | v15_3 exports `empTilts` directly; no `empKin` in B02 | move to 02a_legacy |
| 15–16 | Step 0c Draft: quality→style | v15_3 already has Draft in `T2_AC_STY` | move to 02a_legacy |
| 17–18 | Rule B | retired 2026-07-22, dead code kept for history | delete (it's in git) |
| 19–20 | Rule B retroactive check | only meaningful for batches an old Rule B ran on | move to 02a_legacy |
| 29–30 | Rule F — boom X backfill from `boomNotes` | `boomXFormat` retired; X is a real `BOOM_ORIENT` option now | move to 02a_legacy |
| 31–32 | Rule G — ambiguous `fusKin="Variable"` | 10 rows in B05, **zero** in B01 and B02 | move to 02a_legacy |
| 33–34 | **A3 — TB → `fusKin=TiltBody`** | see conflict below | **delete, don't move** |
| 35–36 | Rule H — `boomXFormat` migration (A5) | same retired field as F | move to 02a_legacy |

Keep in current-02a: A4 (cheap guard), Rule A (CVT combined thrust), Rules C/D
(duplicate chains — these are what resolve your 5 blanks), A1/E (`acState`),
S3/D5, the completeness check, Sections 5/5b/6.

**⚠ A3 conflicts with L6.** Rule A3 retroactively forces `fusKin = TiltBody` on
every `topType = TB` patent. The L6 widening says a TB may legitimately be
`VarInc`. If you widen L6 in the HTML and leave A3 running, 02a will silently
overwrite exactly the answers the widening was meant to allow — the same failure
mode that got Rule B retired in July. A3 must be deleted from both notebooks in
the same change as the L6 widening, not merely gated.

---

## CHUNK 1 — Sign off Batch_02 and push it through 02b
*Target: one sitting, ~1–2 h, mostly unattended. This is the only thing blocking you.*

1. **Label `US12377973B1`** — the missing 400th patent. 12 crops are on disk and
   the ML feed row exists, so it loads in the wizard normally. Re-export the batch
   afterwards. The 5 blank approvals need **no** action: Rule D inherits them.
2. **Run 02a on Batch_02** (after the cleanup in §1b below). Its completeness
   check, A4 (no dup type 4),
   Rule C/D duplicate chains, A1/E `acState`, S3/D5 empennage-tilt audit and the
   multi-arch name suffix all apply unchanged to a v15_3 export. Expect the legacy
   migration cells (0b, 0c, H, A3, G) to report zero changes — if any of them
   reports a non-zero count on Batch_02, stop and tell me, because that means the
   export is not as clean as the field-vocabulary check suggests.
3. **Build the "aft pusher / front puller" worklist.** This is your own note and
   it is the one thing I can't size from the schema. It is a *systematic* error, so
   it gets a targeted worklist, not a full re-read: I'll generate the list of
   Batch_02 records whose propulsor mounting zone reads forward/pulling, filtered to
   the architectures where an aft pusher is plausible. You review only that list.
   Give me a rough sense of when you think you introduced it and I can narrow it
   further by position in the batch.
4. **Run `scripts/resolve_image_paths.py`**, then 02b pre-flight (cell 6) — it
   reports missing files before processing. Then cell 7, then the QC cells.

**Do not** hold Batch_02 for items (b) or for anything legacy. It is clean; ship it.

---

## CHUNK 2 — The two new checks (your list (b))
*Target: ~2 h of my work, ~30 min of your review. Run over B02 first, then reused
verbatim by 02a_legacy for B01/B05.*

Both go into **02a** (report-only worklists, in the style of the existing Rule B
retroactive check), not 02b.

**Check L5 — TW carrying a non-tilting wing.**
One correction before this gets written, and it matters: you stated it as "a
tilting wing alongside a wing that does not tilt → CVT". The wizard was corrected
on 2026-08-07 to a narrower rule — **only a *propelled* fixed wing makes it CVT.**
An unpropelled fixed surface next to a tilting wing is still TW. The codebook's L5
text still carries the old, wider wording. If I implement your sentence literally,
the check will over-flag and contradict the wizard. I'll implement the wizard's
version and you fix the codebook text (see Chunk 3, item 1). Output: worklist of
TW patents with ≥1 tilting wing group and ≥1 non-tilting **propelled** wing group.
Expected size: a handful out of 31 TW patents.

**Check R4-02(c) — full-length boom with fore *and* aft propulsors.**
Straightforward as you specified it: boom group with `span = Full length` and
propulsors recorded both forward and aft of the attachment → manual review list,
so the full-length counting exception is confirmed against real cases. Report-only.

Both emit `(Patent_ID, topType, evidence_fields)` CSVs next to the other 02a
outputs. Neither writes to the data — same discipline as `_rule_b_retroactive_check`,
and the right discipline for the thesis: an automated *flag* is defensible, an
automated *relabel* of a visual judgement is not.

---

## CHUNK 3 — Legacy conformance for B01/B05, without re-reading them
*Target: ~half a day total, and the decision points are yours.*

The governing idea: sort every B01/B05 ↔ B02 difference into four buckets, then
only spend annotator time on bucket D.

| Bucket | What it is | Who fixes it | Est. size |
|---|---|---|---|
| **A — mechanical rename** | Same question, new field name (`wing1_t3_*`→`wing3_*`, `boom_t1_boomAttach`→`boom1_attach`, …) | script, no eyes | ~60 fields |
| **B — deterministic value remap** | `empKin`→`empTilts`, Draft→style, dup type 4→3, retired bgSty/acSty tokens | script, already largely written in 02a | small |
| **C — never asked** | New codebook asks something the old interface had no control for. Confirmed case: boom `wingRel` (added 2026-08-07 — B01/B05 have none). Also the per-group boom span/orient split. | **nobody** — see below | to be counted |
| **D — needs the image again** | L5 TW/CVT, L6 TB `fusKin`, B05's 10 `fusKin="Variable"` rows | you, worklist only | ~30–45 patents |

### The actual exposure, counted (2026-08-10)

I queried both legacy exports for every retired token. The result is much smaller
than the schema diff suggests:

| Retired thing | Batch_01 | Batch_05 | Deterministic? |
|---|---|---|---|
| `propKin = Cyclic` | 1 patent (3 rows) | 0 | ❌ needs image |
| `Draft` sitting in image quality | 1 patent | 0 | ✅ 02a Step 0c |
| `bgSty = Grid/Pattern` | 0 | 1 patent (5 rows) | ❌ needs image |
| `fusShape = PodBoom` | 0 | 1 patent | ✅ → shape + boom dims |
| `t1EdgeTags = Tailsitter` | 0 | 5 patents | ✅ drop (TB covers it) |
| `t1EdgeTags = OutOfScope` | 0 | 1 patent | ✅ → disapproval reason |
| `fusKin = "Variable — Variable Incidence / Tilting Body"` | 0 | 10 patents | ❌ needs image |
| `longSym` | 152 rows | 118 rows | ✅ delete column |
| `empKin`, `boomXFormat`, `wing*_t3_*`, `boom_t*_*` | all | all | ✅ 02a rules |

**~19 patents in total carry a value that a human has to look at again**, and 12 of
those 19 are the `Cyclic` + `Grid/Pattern` + `fusKin=Variable` cases. That is one
afternoon, not a re-labelling campaign.

Two of these are worth noting for the write-up:

- **`longSym` is `False` in 100 % of the 270 rows** where it was ever collected.
  Dropping it loses no information, and you can say precisely that: the field was
  constant across every record in which it was measured, which is why it was
  retired. That sentence turns a deletion into evidence of good instrument design.
- **`fusKin = "Variable — Variable Incidence / Tilting Body"`** is the one genuinely
  lossy legacy value: the old option *merged* two categories that the current
  codebook separates. Those 10 records cannot be split by any rule — the old label
  is ambiguous by construction. 10 patents, one look each.

**Bucket C is where you must not cheat.** You cannot recover `wingRel` for a batch
whose interface never asked the question. Three options, in order of how well they
survive a viva:

1. **Report it as a coverage limitation.** "Boom wing-relative position was
   introduced at Batch_02; analyses using it are restricted to Batches 02–04
   (n = …)." This is completely standard in annotation-study reporting and costs
   you nothing. **Recommended.**
2. **Targeted mini-relabel** of only the affected records — B01/B05 patents that
   have a boom group attached to a wing. If that count turns out to be ~20–30
   patents, it's an hour and you get full coverage. Chunk 3's first task is to
   produce that count so you can decide with a number instead of a feeling.
3. Infer it from other fields. **Don't.** Imputed values presented as observed
   labels is the one thing here that would genuinely damage the work.

**Bucket D is a worklist, never an auto-fix.** ~30–45 patents across both batches.
That is an afternoon, not a re-label.

Deliverable of Chunk 3: `02a_legacy.ipynb` + a `LEGACY_FIELD_MAP` table that is
also the appendix table for your dissertation (old field → new field → rule → date).

---

## 3b. The legacy review UI — hard requirements

02a's Section 5 widget is not good enough for this and I can see why from the code:
`image_panel` is `widgets.Output(layout=Layout(width="45%"))` inside a notebook
output cell, and the image inside it is `max_width:100%` — so the figure renders at
45 % of an already narrow column, with no explicit height, and one image at a time.
That is the whole problem.

The legacy notebook's review widget is to be built to this spec, non-negotiable:

1. **Image area ≥ 900 px wide and ≥ 700 px tall, fixed.** Absolute pixels, never
   percentages. A fixed height means the layout does not jump between records —
   the reason the current rows feel "very short" is that the `Output` collapses to
   whatever the content is.
2. **All figures of the patent at once**, in a wrapping grid, each ≥ 420 px, with
   the FIG number under it. The judgements in bucket D (does the cabin stay level?
   does that wing carry propulsors?) are *comparisons between figures* — hover vs
   cruise. One image at a time makes them impossible.
3. **Click any figure to open it full-width** below the grid.
4. **One keystroke per decision, then auto-advance.** Number keys pick the answer,
   `n`/`p` move, `u` undoes the last decision. No mouse round-trip per record.
5. **Only the fields under question**, rendered large (≥ 15 px), with the current
   value highlighted. Not a dump of all 80 fields — the current widget's `meta_panel`
   at `width:55%` is competing with the image for space it should not have.
6. **A progress counter and the reason this record is in the list** —
   "14 / 19 · fusKin = 'Variable' is ambiguous under codebook v2".
7. **Write the decision to CSV immediately after every keystroke**, not at the end.
   Crash-safe, resumable, and it doubles as the provenance log.
8. **Never re-show a decided record** on re-run; resume where you stopped.

Worklists are ~19 patents for the legacy batches and ~30–45 for bucket D overall,
so this widget will be used for well under 100 records total. It still pays for
itself: a bad widget on 100 comparison-heavy records costs more than building a
good one.

---

## 4. Defensibility — what I'd flag before your defence

You asked me to be straight about this, so:

**Fix these (cheap, and each is a question you'd otherwise get asked):**

1. **The codebook contradicts the wizard on L5.** The doc still says any
   non-tilting wing makes it CVT; the wizard says only a propelled one. Anyone
   reading the codebook and then the data finds the contradiction. This is a
   *documentation* fix — 15 minutes, no relabelling. Do it.
2. **`codebook_version` says `1.0` in Batch_02's export** even though Batch_02 was
   labelled under what you call codebook v2 on wizard v15_3. Right now nothing in
   the data distinguishes a v1-codebook batch from a v2-codebook one. Stamp the
   real version (and ideally the wizard file version) per patent, and carry batch +
   codebook version into every downstream table. This is the single highest
   credibility-per-minute change available. Without it, "which batches were labelled
   under which rules" is answerable only from your memory.
3. **Your list (a) is stale by ~8 items.** Not a data problem, but if that list is
   sitting in a methods chapter as "known outstanding", it reads as sloppier than
   the work actually is. v15_3 shipped almost all of it.

**Already defensible, don't spend time on it:**

- Retiring taxonomy options mid-study is normal, *and your provenance is unusually
  good* — every retirement in that HTML has a dated comment saying what was removed,
  why, and that old records still load unchanged. Extract those comments into one
  appendix table and this becomes a strength rather than an apology.
- Report-only checks that produce worklists for a human, rather than auto-fixing
  visual judgements. Keep doing exactly that.

**The one thing I'd spend annotator hours on that isn't on your list:**

You are a single annotator with no reliability measure. In a defence, "how do we
know your labels are consistent?" is close to certain, and right now the answer is
"trust me". The standard, cheap mitigation: **re-label a random sample of ~50
already-done patents blind, and report intra-annotator agreement (Cohen's κ) per
dimension.** Half a day, and it converts your weakest methodological point into a
reported number. Against 600 remaining patents, I think 50 of those days-worth of
labels are worth less than that κ. Your call, but if you asked me where the last
half-day should go, it's here — not into B01/B05.

**Where I'd let it go:** full re-labelling of B01/B05. The effort curve has flattened;
bucket A+B is free, bucket D is an afternoon, and bucket C is honestly reportable as
a coverage limitation. That is the right place to stop.

---

## 5. How the wizard narrowed L5 — text you can feed the codebook

**The old rule (still in the codebook doc):** a Tilt Wing requires *every* wing to
tilt. A tilting wing next to any non-tilting wing ⇒ CVT.

**Why it was wrong:** it made a fixed canard or a small stabiliser-like panel enough
to disqualify TW. But a fixed panel that carries no propulsion is not a
"fixed thrust mechanism" — tilting it would achieve nothing aerodynamically, and
CVT is defined by a *mix of thrust mechanisms*, not a mix of surface angles.
Under the old rule, ordinary tilt-wings with a fixed canard were being pushed into
CVT, which polluted the class that is supposed to mean "this aircraft genuinely has
both fixed and vectoring thrust at once".

**The corrected rule (wizard, 2026-08-07), in two clauses:**

> **(1)** At least one wing must be set to Tilt.
> **(2)** Every **propelled** wing must be one of the tilting ones.
>
> A wing is **propelled** when propulsors are recorded on *that wing's own M3
> station*. A boom that happens to attach to the wing carries its propulsors on
> the **boom** card, and does **not** make the wing propelled.
>
> A fixed wing carrying **no** propulsors is perfectly fine on a Tilt Wing.
> A **propelled** wing that does not tilt, while another wing does, makes the
> aircraft **CVT**, not TW.

The operative change is the single word **propelled**. The test is not "do all the
wings tilt?" — it is "is there lift-producing *thrust* that stays fixed while other
thrust vectors?"

Two implementation details worth a footnote in the codebook, because they explain
why the wizard sometimes flags late:

- The wing tilt flags are entered in **M2**, but the propulsor counts are entered in
  **M3**. On a first pass through M2 the counts are still zero, so only clause (1)
  can fire there; clause (2) is re-checked in M3 once the counts exist. The check
  can therefore under-fire early, never wrongly block — the safe direction.
- A wing whose propulsor count was entered through the **Quick Count Override**
  still counts as propelled (`m3StationCount()` honours the override), so the lock
  asks the same question the card header displays.

Also update the CVT entry itself: its G1 description already says "a wing that tilts
alongside a second wing that does not" — that phrasing carries the old, wider rule
and should gain the word *propelled* too, or the codebook will contradict itself
internally.

---

## 6. Change the data, or just state it? — the rule, and where it goes in the thesis

### The test

Ask one question of every difference:

> **Can I derive the current-codebook value from the old record alone, without
> looking at the image?**

- **Yes → change the data.** This is a *translation*, not a re-judgement. A reader
  can verify it from your mapping table, and it costs no annotator time.
- **No → leave the data alone and state it.** Producing the value would require a
  new judgement about the figure. Writing one in by inference and presenting it as
  an observed label is the one move here that would genuinely damage the work.

### Applied to your data

**CHANGE (deterministic, scripted, logged):**

| What | Where |
|---|---|
| `empKin` → `empTilts` | 02a Step 0b |
| `Draft` moved from image quality → rendering style (1 patent, B01) | 02a Step 0c |
| `boomXFormat` boolean → per-group `orient = X` | 02a Rules F / H |
| Field renames `wing*_t3_*` → `wing3_*`, `boom_t*_boomAttach` → `boom*_attach` | new `LEGACY_FIELD_MAP` |
| Delete `longSym` (constant `False` in all 270 rows) | new |
| `t1EdgeTags = Tailsitter` → drop (TB architecture already encodes it) — 5 patents | new |
| `t1EdgeTags = OutOfScope` → the existing Out-of-Domain disapproval reason — 1 patent | new |
| `fusShape = PodBoom` → base shape + the boom group that already exists — 1 patent | new |

**STATE ONLY (needs a judgement, or was never asked):**

| What | What you say |
|---|---|
| Boom `wingRel` | introduced at Batch_02; coverage restricted to Batches 02–04 |
| Per-group boom span / orientation granularity | same |
| `fusKin = "Variable"` (10 patents, B05) | old option merged two current categories; resolved by review, or reported as ambiguous |
| `propKin = Cyclic` (1 patent, B01) | retired for visual non-decidability |
| `bgSty = Grid/Pattern` (1 patent, B05) | retired as unused |
| "generic" → "Partial Quality" | **display rename only, id unchanged — the data does not change at all** |
| L5 / L6 re-checks | resolved by targeted review, reported as a worklist |

### Where it goes — and how you keep ONE codebook version in the text

You're right to want a single codebook in the thesis. The structure that gives you
that without hiding anything:

**Methodology — present the final codebook as *the* instrument.** Present tense,
one version, no history. "Each figure is annotated along … Propulsor articulation
takes the values Fixed, Tilt, Other." Never narrate the revisions in the body.

**Methodology — one short subsection, ~150 words, called something like
"Instrument refinement and label harmonisation".** This is your whole honesty
budget, and it is enough:

> The annotation instrument was refined during data collection. Batches labelled
> under earlier revisions were harmonised to the final specification by a
> deterministic mapping applied in post-processing (Appendix X); no label was
> reinterpreted without reference to the source figure. Where a dimension was
> introduced after a batch had been annotated, the affected records are reported as
> missing rather than imputed, and per-field coverage is given in Table Y.

**Appendix X — the harmonisation table.** Old field/value → new → rule →
deterministic (Y/N) → n affected. This is the table that makes the single-version
claim in the body legitimate. It is also nearly free: 02a's rule cells already carry
dated comments explaining every retirement, so the appendix is an extraction job,
not a writing job.

**Dataset description (Results) — a coverage table.** One row per field, one column
per batch, n available. "Field introduced at Batch_02" stops being a caveat and
becomes a number in a table, which is where a reader expects it.

**Limitations — two sentences.** Fields with partial coverage, and the fact that
harmonisation was deterministic-only.

The unchanged retirements you asked about — the ones where nothing in the data
moves — collapse to exactly one line each in Appendix X (e.g. *"Blueprint (rendering
style): retired as unused; 0 records affected"*). They never need to appear in the
body at all.

---

## 7. Cohen's κ — what it is, why here, and exactly how

### The problem it solves

Every label in this dataset was assigned by one person: you. Right now, if someone
asks "how do we know these labels are consistent?", the answer is your word. That is
the weakest joint in the work, and it is a *predictable* question at a defence — a
hand-built taxonomy with a single annotator is precisely where an examiner probes.

### What κ is

Cohen's κ measures agreement between two sets of labels over the same items,
**corrected for the agreement you would get by chance**. Raw percent-agreement is
misleading when one class dominates: if 60 % of your patents are TP or SLC, two
careless annotators agree ~40 % of the time by luck alone. κ subtracts that.

κ runs from −1 to 1. The conventional reading (Landis & Koch):

| κ | reading |
|---|---|
| < 0.20 | slight |
| 0.21–0.40 | fair |
| 0.41–0.60 | moderate |
| 0.61–0.80 | substantial |
| 0.81–1.00 | almost perfect |

### Inter- vs intra-annotator — be precise, it matters

- **Inter-annotator** = two different people label the same items. You cannot do
  this; you have one annotator.
- **Intra-annotator (test–retest)** = the *same* person re-labels the same items
  later, blind to the first attempt. This is what you can do, and it is a
  legitimate, published reliability measure — you simply must call it by its right
  name. Reporting it correctly as intra-annotator agreement is itself a mark of
  care; presenting it as inter-annotator would be the error.

### The procedure, concretely

1. Draw a **random sample of ~50 already-labelled patents**, stratified so the rare
   architectures (TB, RC, PFV, SRW) are represented — otherwise κ is dominated by
   TP/SLC and tells you nothing about the hard classes.
2. **Re-label them blind.** Your tooling makes this almost free: load
   `ml_predict_labels_<batch>.xlsx` (the machine feed) rather than the reviewed
   export, and the wizard opens with no human labels visible. You are re-annotating
   from the figures, not editing your old answers.
3. Ideally wait ≥ 1 week so you are not recalling specific patents. If you cannot
   wait, say so.
4. **Compute κ per dimension**, not one global number — `topType`, `fusKin`,
   `empType`, `gearArch`, boom orientation, T2 fields.

### Report per dimension — this is the part that pays

A single κ hides everything useful. Per-dimension κ lets you write sentences like:
*"Architecture type showed substantial agreement (κ = 0.78); boom orientation only
moderate (κ = 0.52), so boom-level findings are reported with correspondingly wider
caution."* That is a researcher who knows the limits of their own instrument, and it
pre-empts the examiner's question by answering it first.

It also *directs your remaining effort*: a dimension with low κ is a dimension whose
codebook entry is ambiguous, and that is worth more to fix than more volume.

### Why this over 50 more patents

Going 600 → 650 patents is ~8 % more data. It will not change a single conclusion
in your thesis. Going from *no reliability estimate* to *per-dimension κ* changes
the epistemic status of **all ~1000 patents you have already labelled** — from
unverified to quantified. Same half-day; incomparable return.

### The honest caveat, which you should write down yourself

Test–retest by one annotator measures **consistency, not validity**. It cannot
detect a systematic misunderstanding, because you would repeat it identically both
times and score perfect agreement. Your own aft-pusher / front-puller error is
exactly that kind of mistake — κ would have scored it 1.0. State this limitation
explicitly and pair κ with the rule-based checks (L5, L6, R4-02(c)), which *do*
catch systematic errors. Together they cover both failure modes, and saying so shows
you understand what each measure can and cannot do.

---

## Suggested order

```
Today/tomorrow   Chunk 1            → Batch_02 signed off and through 02b
Then             Chunk 3 item 1     → count bucket-C patents (a number, ~20 min)
                 §4 fixes 1 and 2   → codebook L5 text + version stamping
Then             Chunk 2            → the two checks, run on B02
Then             Chunk 3            → 02a_legacy for B01/B05
If time          §4 last item       → 50-patent reliability sample
```

Feed me back whichever chunk you want to start.

---

## Appendix — your items (i)–(ix), spelled out with status

These are the nine "the interface has not caught up" items from your own note.
Status column verified against `UI_for_taxonomy_caracterization_15_3.html` on
2026-08-10.

| # | The decision | Status in v15_3 | Evidence |
|---|---|---|---|
| **i** | Propulsor Articulation reduced to Fixed / Tilt / Other (Cyclic dropped) | ✅ done | `PROP_KIN` has exactly those 3 |
| **ii** | Image Quality reduced to Clean / Partial Quality / Poor Quality; Draft moves to rendering style | ✅ done | `QUALITY_FLAGS` = clean / generic→"Partial Quality" / poor_quality; `T2_AC_STY` contains 'Draft' |
| **iii** | Blueprint out of style, Grid/Pattern out of bg fill type, Blueprint Blue out of bg colour | ✅ done (v15.2) | all three absent from `T2_AC_STY` / `T2_BG_STY` / `T2_BG_COL` |
| **iv** | Pod and Boom removed from Fuselage Shape | ✅ done | `FUS_SHAPE` = Circular / Oval / Rectangular / Blended / Other |
| **v** | X / Diagonal added to Boom Orientation | ✅ done (v14) | `BOOM_ORIENT` has `{id:'X', n:'X / Diagonal (crossing)'}` |
| **vi** | Duplicate types reduced to D1, D2, D3 | ✅ done (v14) | `DUP_TYPES` = 1/2/3; type 4 deleted; B02 data has no type 4 |
| **vii** | UAVSimilar the only edge tag | ✅ done (v15.3) | `T1_EDGE_TAGS` = UAVSimilar; Tailsitter and OutOfScope retired |
| **viii** | Drop M1 `longSym` from the export | ✅ done (v15.3) | export builder comments "the longSym row is removed"; B02 has no `longSym` rows |
| **ix** | **L6 widened** — see below | ❌ **still open** | `pageM1` `physicsLock('TB', …)` |

### What L6 is

L6 is the codebook lock tying **architecture** to **fuselage kinematics**.

Today, in `pageM1`, when `topType === 'TB'` (tailsitter / tilt-body) the wizard
does not offer you the `fusKin` list at all — it shows a locked banner and forces
the single value `TiltBody — Tilting Body`.

Your widening says that's too strict. A tailsitter can be built with the **cabin
on its own joint**: the airframe rotates for cruise while the cabin stays level.
That aircraft is architecturally TB, but its fuselage kinematics are
`VarInc — Variable Incidence`, because what defines VarInc is the body staying
level while the lift/thrust producers change angle.

So the lock changes from *"TB ⇒ TiltBody"* to *"TB ⇒ TiltBody **or** VarInc,
never Fixed"* — a two-option pick instead of a forced one.

**Blast radius:** 5 TB patents in Batch_02, 12 in Batch_01, 0 in Batch_05 = 17
records where the forced value may be wrong. Each needs one look at the figure to
answer "does the cabin stay level?". That is ~20 minutes of review, and it must be
paired with deleting Rule A3 (see §1b) or the notebook will overwrite your answers.
