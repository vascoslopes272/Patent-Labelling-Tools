# Phase 0 — Literature-grounding audit of the taxonomy

Date: 2026-09-08. Read-only. Inputs: `Taxonomy_labeller_v2.docx` (Method chapter + Appendix A codebook, 141 KB, edited 2026-09-08 16:26) and the live wizard `notebooks/UI_for_taxonomy_caracterization_15_4.html` (v17.1).

**Question answered:** for every dimension and option the labeller fills, is the definition anchored in a published source, and is that source actually cited — or is it this study's own construction, and does the codebook say so?

Verdict legend

| Code | Meaning |
|---|---|
| **A** | Grounded in a cited source, and the citation is the right one. |
| **B** | Grounded (the concept exists in the literature) but the citation is missing, weak, or points at a source that I could not confirm covers it. Fix = add / replace a citation. |
| **C** | Author-defined, and the codebook **says so** (P-5 honoured). Fine. |
| **C!** | Author-defined, and the codebook **does not say so**. This is what a chair attacks. |
| **X** | Internal inconsistency between codebook, wizard, or data. |

Two caveats on my side. I have not re-read the cited papers for this audit; where I say "verify" I mean the claim is plausible but I could not confirm the source says exactly that. And terminology recommendations below are Phase 1 input — nothing in the wizard, xlsx or docx was changed by this audit.

---

## 1. Headline findings (read this if nothing else)

1. **P-5 under-declares.** The codebook says "One G1 code is affected, the PTC." That is not true. Author-defined names at G1 also include **CVT** ("Combined Vectored Thrust" is not a family name in [3]/[4]/[5]; the *concept* of mixing fixed and tilting thrust is in the literature, the label is yours) and **TB** (the literature family is **tail-sitter**; "Tilt Body" is your name). At M1, **Whole-Body Pitch** is declared, but **Variable Incidence** is a borrowed analogy from variable-incidence *wings* [15] and should be declared as such. At M2 the five empennage options that are not in Raymer's aft-tail set are undeclared extensions. Rewrite P-5's last sentence as a list.
2. **The technological domain is defined by "distributed electric propulsion" and there is no DEP citation anywhere.** Nor one for the word *propulsor*. Add a DEP source (see §5).
3. **`ElectricSimilar` is named in Table A.6 and never defined.** R1-01 defines UAVSimilar only; Table A.6 points at R1-01 for both. The wizard tooltip is the only definition in existence. Write it into R1-01 while renaming it (§3.4).
4. **Deflected Slipstream is two things wearing one code.** The literature DS (fixed propulsors, slipstream turned by flaps/vanes) plus your v1.6 extension "fixed wing with DEP, no lift rotors, no deflecting structure". The extension has a physical-plausibility problem the codebook itself would catch under R0-01(1): a fixed wing with fixed propellers and *no* deflecting structure cannot hover, so either the flaps exist and were not drawn (then it is DS proper) or the aircraft is STOL (then it is *Not VTOL*). Decide which and say it; the "visual signature overlaps" argument is a modelling convenience, not a definition. The `notPureArch` tick you already require is the right instrument to keep them separable.
5. **Rotor vs propeller: the scheme is already right at the level of concepts** (rotor lifts, propeller propels, "propulsor" is the generic unit) — the codebook's own M3 intro says exactly that. The remaining defects are three wizard strings and one dimension name (§3.1). Do not touch any `id`.
6. **AFT vs REAR is not one problem but three**, and only one of them needs a change (§3.2). "Rear-Isometric" is the correct drawing-standard term and stays.
7. Document hygiene: four `[TODO]`/`[CONFIRM]` markers, one dead reference URL, two empty enumerations (R6-04 items 2–3), and ~40 empty headings/bullets after the Locks table and after the References (§6). A chair will see those before anything else.

---

## 2. Per-stage audit table

### T1 — Patent triage

| Dimension / option | Verdict | Notes |
|---|---|---|
| Approval | C | Trivially author-defined; nothing to cite. |
| Disapproval reasons (6) | C | Domain-specific; well argued in R1-01 and Method 2.3.2. "Out of Technological Domain" is the right top-level name (you confirmed TD, not TP). |
| Not VTOL (STOL/CTOL) | C | Good addition; the "hard negatives" argument is a genuine methodological point — keep it in the thesis. Anchor STOL/CTOL definitions to Raymer [10] if you want a citation. |
| Duplicate D1/D2/D3 | **B** | Author-defined inheritance semantics (fine), but the underlying notion — several filings of one invention — has a standard anchor: the **EPO DOCDB simple patent family** (same priority set) and continuation/divisional practice. Cite it; it also gives you the correct tool for cross-batch duplicate management later (a real family id, not the placeholder currently in META). |
| Aircraft name (R1-03) | C | Working identifier; nothing to cite. |
| Edge tag UAVSimilar | C | Defined and argued in R1-01. |
| Edge tag ElectricSimilar | **C!** | Named in Table A.6, **never defined in the codebook**. Tooltip in the wizard only. See §3.4. |

### T2 — Figure triage and characterisation

| Dimension | Verdict | Notes |
|---|---|---|
| View / Projection (Top · Bottom · Front · Back · Side · Front-Isometric · Rear-Isometric · Generic 3D) | **B** | These are the principal views of engineering drawing practice. Cite **ISO 128** or **ASME Y14.3** (multiview and sectional-view drawings). "Rear" is the standard word there — keep it. Note the set mixes "Back" (orthographic) with "Rear-Isometric"; pick one word, the standard is *rear*. |
| Rendering style / colour, background style / colour | C | Dataset-description fields, not aircraft taxonomy; no literature needed. Fine. |
| Image quality (Clean · Partial · Poor) | C | Author-defined, ordinal; the definition of "Partial Quality: the middle case" is circular — give it one sentence of its own. |
| Present structural elements | C | Fine. |
| Aircraft state (Hover · Transition · Cruise · Invariant · Other) | C | The hover/transition/cruise triad is universal in the convertible-VTOL literature ([3], [9]); a one-line cite would make it A. "Invariant" is yours; declared implicitly by R2-02(a). |
| Architecture legibility | C | Author-defined, fine. |
| Main-figure preference order (R2-01c) | C | Fine. |

### G1 — Global architecture

| Code | Verdict | Notes |
|---|---|---|
| Branch structure (Winged/Vectored–Independent, Wingless, Residual) | **B** | Ugwueze et al. [8] for layering: plausible. The claim that **EASA SC-VTOL-01 [7] distinguishes dedicated lift/thrust units from dual-function units** — verify. SC-VTOL-01 defines "lift/thrust unit" generically and sets the safety objectives; I could not confirm it draws the vectored-vs-independent distinction. If the anchor is actually the MOC (Means of Compliance) documents, cite those instead. |
| TW Tilt Wing | A | [3], [5]. |
| TR Tilt Rotor | A | [3], [5]. (Technically a tilt-rotor unit is a *proprotor*; the family name "tilt-rotor" is standard and stays.) |
| DS Deflected Slipstream | **B / X** | The family is real and old (Ryan VZ-3RY, Fairchild VZ-5, 1950s–60s). I am not confident [3] covers it; add a primary source — J. P. Campbell, *Vertical Takeoff and Landing Aircraft* (1962) or B. W. McCormick, *Aerodynamics of V/STOL Flight* (1967; Dover 1999). The v1.6 extension to un-deflected DEP fixed wings is the plausibility problem in §1.4. |
| CVT Combined Vectored Thrust | **C!** | Codebook says it "corresponds to the 'combined' family discussed in [3]". I could not confirm [3] names such a family. The mix test (R3-02) is sound and is yours. Declare the name under P-5. |
| TB Tilt Body | **C! / X** | Literature family = **tail-sitter** ([9]; VFS usage). "Tilt Body" is your name, undeclared. The codebook label is "Tilt Body (Tailsitter)", the wizard (since v15.4) is "Tilt Body" — mismatch. Resolution in §3.3. |
| PTC Pitch-to-Cruise | C | Declared, and the four-argument defence in the Method chapter is the best-argued passage in the document. Keep. |
| SLC Separate Lift + Cruise | A | VFS "Lift + Cruise" [5]; [3], [6]. |
| SRW Stopped / Slowed Rotor Wing | **B** | Real family (Sikorsky X-Wing / S-72, Boeing X-50A Canard Rotor/Wing). Cited to [3] — verify; add a direct source (e.g., the CRW programme papers, AIAA 2003; or NASA X-Wing reports). |
| RC Rotorcraft | A | VFS "Electric Rotorcraft" [5]. Note the VFS category includes autogyros; your definition ("helicopter-type rotor layout") silently excludes them — say whether a wingless autogyro is RC. |
| MR Multirotor | A | VFS [5]; [6]. |
| HB / PFV | **C** (declared) | VFS has ONE category [5]; the split into two is yours, justified by P-2/P-3. Declared adequately. |
| humanUncertain / notPureArch | C | Declared. |
| "Thrust vectoring" definition | A | Standard usage; fine. |

### M1 — Structure morphology

| Dimension | Verdict | Notes |
|---|---|---|
| Fuselage shape (Circular · Oval · Rectangular · Blended/Lifting body · Other) | **B / X** | Raymer [10] discusses fuselage cross-sections; cite in the row. "Blended / Lifting Body" as a *cross-section* option overlaps M2 Wing Architecture BWB and LB — two dimensions asking one question. Either drop it here or define it as cross-section-only. |
| Fuselage kinematics: Fixed | C | Fine. |
| Variable Incidence | **C!** | Borrowed from variable-incidence *wing* practice [15] — an analogy, not a term for this. Declare it ("no fuselage-level term exists; borrowed by analogy"). Reference [15]'s URL is `[TODO-5]`. |
| Whole-Body Pitch | C | Declared. Good. |
| Tilting Body | C! | See §3.3 — rename with the TB code. |
| Ground contact (Skids · Wheeled · Pads/Hull · Unknown) | **B** | Raymer ch. 11 covers gear types; cite. The 2026-09-06 retirement of "Retractable" is the right call and the reasoning (inference vs observation) should be in the Method chapter as an example of P-2. |
| Airframe lateral symmetry | C | Fine. |
| Boom (definition, count, attachment, positions, orientation, tilt, retract) | **C / X** | Author-defined throughout (fine — "boom" has no crisp textbook definition), but the **Open question "boom vs nacelle is undefined"** is a live defect in already-labelled data. Raymer defines *nacelle*; adopt the proposed test (boom spans a distance and carries something along it; nacelle is a housing around one propulsor) and cite Raymer for nacelle. |
| Inboard/outboard reserved for spanwise; fore/mid/aft for longitudinal | A | Correct and standard. Extend the sentence to say "rear" is not used outside the drawing-view names (§3.2). |

### M2 — Aero morphology

| Dimension | Verdict | Notes |
|---|---|---|
| Wing architecture (W · BWB · FW · LB · Other · Unknown) | A | [10], [11]. |
| Vertical position "High / Hub · Mid / Center · Low / Down" | **B / X** | Raymer's terms are **high, mid, low** (plus parasol and shoulder). "Hub" and "Down" are not terms. Rename: `High (shoulder)`, `Mid`, `Low`. Ids stay. |
| Longitudinal position (Forward · Center · Aft) | C | Fine. |
| Planform (Straight · Swept · Delta · Trapezoidal/Tapered · Other) | **B** | Raymer [10] vocabulary; cite in the row (Table A.8 cites [10] only for Wing Architecture). The R5-07 scope limit on taper is exemplary — keep it. |
| Tip-joined | C | Fine; box-wing/joined-wing anchor available in Raymer if wanted. |
| Tilt (Fixed · Tiltable) | C | Fine. |
| Role: Canard · Tandem · Aft stabiliser · **Stacked** · Other | **B** | Raymer terms: canard, tandem, three-surface, **biplane**. "Stacked" → `Biplane (stacked)`. |
| Empennage type | **C!** | Conventional, T, cruciform, V, inverted-V, Y, H/twin, box-wing are Raymer's aft-tail variations — cite [10]. `Tailless`, `Single Vertical Fin Only`, `Stabilizing Fins (2+)`, `Horizontal Stabiliser Only` are your decidability-driven extensions — say so. The count-based test (R5-05, v1.7) is good. |
| empTilts | C | Fine. |

### M3 — Propulsion morphology

| Dimension | Verdict | Notes |
|---|---|---|
| "Propulsor" definition | **B** | Correct and important. Cite a DEP source that uses it (§5). |
| Mount locations (Wing N · Fuselage · Boom · Empennage) | A | Roskam Part II [12]. After today's change, the wizard has ONE body card for MR/RC ("Fuselage Body"); the wingless non-rotorcraft fallback card is still titled "Fuselage & Airframe Hub Array". Rename that title to "Fuselage Body" too so the codebook's single row is literally true (key `core_layout` stays). |
| Thrust kinematics (Horizontal · Vertical · Mixed) | C | Fine. |
| Propulsor articulation (Fixed · Tilt · Other) | C | Fine. R6-01's separation of the two is well written. |
| Control / stability only | C | Fine, scope limit stated. |
| **"Rotor Chordwise Position"** (Front/tractor · Back/pusher · None) | **A / X** | The *concept* is Roskam's tractor/pusher [12]. The *name* is wrong twice: "chordwise" is wing jargon, and tractor/pusher is propeller vocabulary applied here to rotors and fans alike. Rename the dimension `Tractor / Pusher arrangement`; id `chord` stays. |
| **"Aerodynamic Blade Behaviour"** (Open · Ducted) | **X** | The dimension records the *installation* (free vs shrouded), not blade behaviour. Rename `Propulsor enclosure: Open / Ducted`. Ducted-fan anchor: Raymer [10] or Roskam [12]. |
| Retraction kinematics (Fixed · Blade-folding · Retracting) | C | Fine; folding props are documented on Joby/Lilium-class aircraft if you want an example. |
| Airframe mounting zone | **B / X** | Roskam covers fuselage engine placement; cite. Naming issue in §3.2. "Side outriggers" — the codebook admits the word is wrong for booms; here it is fine (it is an outrigger). |
| Wing chordwise / spanwise zone | B | Roskam covers over-/under-wing and leading-edge placement; cite. "Across the extension of the wing" → `Spanning (full span)`. |
| Symmetry flag | C | Fine. |
| R6-03 enumeration | C | Fine. |

### Principles and locks

| Item | Verdict | Notes |
|---|---|---|
| P-1 MECE [2] | A | Minto is the origin of the term; a consulting text, but the correct citation. |
| P-2, P-3, P-4, P-6 | C | Author principles, fine. |
| P-5 | **X** | Under-declares (§1.1). |
| Locks L1–L10 | C | Author-defined consistency constraints; fine. R4-10 candidate lock has a `[TODO]`. |

---

## 3. Terminology decisions this audit feeds into Phase 1

### 3.1 Rotor vs propeller — rule, and the exact defects

**Rule for the thesis and the codebook (one paragraph, put it in the M3 intro):** a *rotor* is a rotating wing whose primary job is to support weight — axis near-vertical in hover, low disc loading, articulated or hingeless hub. A *propeller* produces propulsive thrust while a wing carries the weight — axis along the flight path, high disc loading, rigid hub. A unit that does both across the transition is a *proprotor* (the tilt-rotor case). A shrouded unit is a *fan*. Whenever the codebook means the whole thrust unit generically, it says *propulsor*, and rotor/propeller/proprotor are **derived at analysis time** from thrust kinematics + articulation + whether a fixed wing carries lift — never asked of the labeller.

The scheme already obeys this in substance. Correct uses that stay: TR "Tilt Rotor" (family name), SLC "lift rotors … cruise propulsors", SRW, RC, MR "lift-rotor array", T2 "Rotor or Propeller Blade" (it *is* the blade).

Defects to fix (display strings and titles only, ids untouched):

| Where | Now | Change to |
|---|---|---|
| Wizard M3 card, line ~2735 | "Distinct propeller types here" | "Distinct propulsor types here" |
| Wizard M3 tier headers, lines ~2759/2777 | "Propeller Type N" | "Propulsor Type N" |
| Wizard M3 stepper hint, line ~2739 | "…mixes different propellers" | "…mixes different propulsors" |
| Wizard CHORD tooltips, lines 612–613 | "Propeller/rotor mounted AHEAD/BEHIND…" | "Propulsor mounted AHEAD/BEHIND…" |
| Codebook + wizard dimension name | "Rotor Chordwise Position" | "Tractor / Pusher arrangement" |
| Codebook + wizard dimension name | "Aerodynamic Blade Behaviour" | "Propulsor enclosure" (Open / Ducted) |

### 3.2 AFT vs REAR — three cases, one change

| Case | Where | Verdict |
|---|---|---|
| Drawing views | T2 "Rear-Isometric" (and "Back") | **Keep "rear"** — it is the ISO/ASME term. Make the orthographic view "Rear" too, not "Back". |
| Synonym glosses | W_POS_L "Aft (Tail / Rear position)", BOOM_POS_LONG "Aft / Rear", tooltip "REAR third" | Harmless; drop "Rear" from the gloss and say "aft third" so one word carries the axis. |
| **Two distinct M3 zones** | "Aft/Pusher (tail tip)" **and** "Fuselage — Rear (body)" | Not vestigial — these are two positions (the tail tip vs the aft body). Rename so the axis word is the same and the *noun* separates them: `Tail tip (aft-most)` / `Aft fuselage (body)`; mirror at the front: `Nose tip` / `Forward fuselage (body)`. Ids `Nose/Aft/FusFront/FusRear` stay. |

Codebook sentence to add under M1 (next to the inboard/outboard rule): "The longitudinal axis is described only by fore, mid and aft, judged in thirds of the reference structure; *rear* appears only in the names of drawing views. Thirds are the coarsest division that two readers resolve identically on a patent line drawing (P-3)." That converts the ambiguity criticism into a stated design choice.

### 3.3 Tilt Body → what?

Literature family: **tail-sitter** [9]. A level-cabin tail-sitter (cabin on its own joint, airframe rotates ~90°) is still a tail-sitter — the airframe sits on its tail. Your "Tilting Frame" captures exactly the property that matters (the *frame* rotates, whatever the cabin does), and it is the better word for the M1 kinematics value, where "Body" wrongly implies the cabin.

Recommendation, two names for two different things:

| Field | Now | Recommend | Why |
|---|---|---|---|
| G1 code TB display name | codebook "Tilt Body (Tailsitter)", wizard "Tilt Body" | **"Tail-sitter (tilting frame)"** | Literature name first; your descriptor second; resolves the codebook/wizard mismatch; encompasses the variable-incidence case explicitly. |
| M1 fusKin id `TiltBody` | "Tilting Body" | **"Tilting Frame (cabin fixed to the frame)"** | Pairs cleanly with `LevelCabin` = "Variable Incidence (cabin on its own joint)". |

Ids `TB`, `TiltBody`, `LevelCabin` never change; xlsx labels change on next re-save or by a one-line label sweep (the "ID — Label" composite).

### 3.4 ElectricSimilar — define it, then rename it

Current tooltip (the only definition): "Not clearly an electric VTOL, but close enough to share the design space — a hybrid, an unstated powerplant, a conventional aircraft of the same morphology. Records 'near the boundary', not 'inside it'."

That is a good definition — it belongs in R1-01 as item (b) beside UAVSimilar, with the same two-part argument (the image carries the same structural information; the tag costs nothing later). Name: mirror the sibling. UAVSimilar reads "UAV, but similar enough"; this one should read **"Non-electric (or unstated), but similar enough"**, id `ElectricSimilar` unchanged. Drop "adjacent" everywhere.

---

## 4. Wizard ↔ codebook mismatches found while reading

| # | Codebook | Wizard | Fix |
|---|---|---|---|
| 1 | TB "Tilt Body (Tailsitter)" | "Tilt Body" (v15.4) | §3.3 |
| 2 | W_POS_V "High / Hub" | same | Both wrong; §2 M2 |
| 3 | Table A.9 one "Fuselage / Core Layout" row | two card titles ("Fuselage Body" / "Fuselage & Airframe Hub Array") | Rename the fallback title |
| 4 | R6-04 lists one symmetry flag | one checkbox | consistent ✔ |
| 5 | R2-02(a) convertible set "TW, TR, DS, CVT, SRW" | `isConvertibleArch()` | not verified this pass — check in Phase 2 |
| 6 | Table A.6 "Electric-adjacent, but similar enough" | same | §3.4 |
| 7 | Method 2.3.1: variants get letter suffixes (Archer 2a/2b) | data: `_archN` ids, names carry numerals across patents (Joby Aero 1/2, today's pass) | consistent — numerals distinguish aircraft *across* patents, letters distinguish variants *within* one; say both in R1-03 |

---

## 5. Citations to add (all verify before use)

| For | Suggested source |
|---|---|
| Distributed electric propulsion, "propulsor" | H. D. Kim, A. T. Perry, P. J. Ansell, "A review of distributed electric propulsion concepts for air vehicle technology," AIAA/IEEE EATS, 2018. Alternatively M. D. Moore, B. Fredericks, "Misconceptions of electric aircraft and their emerging aviation markets," AIAA 2014-0535. |
| Deflected slipstream (and the whole 1950s–60s V/STOL family set) | J. P. Campbell, *Vertical Takeoff and Landing Aircraft*, Macmillan, 1962; B. W. McCormick, *Aerodynamics of V/STOL Flight*, Academic Press 1967 / Dover 1999. |
| Stopped / slowed rotor | Boeing X-50A CRW programme papers (AIAA, c. 2003); NASA/Sikorsky X-Wing (RSRA) reports. |
| Drawing views | ISO 128 (technical drawings — general principles) or ASME Y14.3 (orthographic and pictorial views). |
| Patent duplicates / families | EPO, "DOCDB simple patent family" definition (Espacenet help / EPO Patent Information). |
| Fuselage cross-sections, landing gear types, wing position, planform, aft-tail variations, nacelle | Raymer [10] — already in the list; add it in each row where it is the anchor (Tables A.7, A.8). |
| Reference [15] | The RF-8G object record URL is `[TODO-5]`; a better anchor for the variable-incidence wing is any F-8 Crusader design reference, or Raymer's mention of variable incidence. |

---

## 6. Document defects (mechanical, fix before anyone else reads it)

- R1-01 item 4 carries `[CONFIRM: check this matches what the option means in the interface.]` — it does match the wizard's "No content" definition; delete the marker.
- R4-08 `[TODO: confirm the highest panel index…]`; R4-10 `[TODO: count the Bridge and More than one records…]`; R5-05 `[TODO: fix the area fraction…]`. Each is a real open decision — either resolve or move to *Open questions*.
- R6-04 has empty items 2) and 3) (leftover from retiring the two symmetry flags on 2026-09-06).
- Reference [15] URL is `[TODO-5]`.
- After the Locks table (Open Items area) and after the References: ~10 empty `##`/`###` headings and ~35 empty bullet lines — a deleted skeleton. Remove.
- Cross-references "Section 2.3.2", "A.2.1", "Section A.11", "Automation and QA Notes section" — check each resolves after the cleanup.
- Title: "Patent-Image Taxonomy: Method" / "Codebook" — fine.

---

## 7. What is *not* a problem (so you do not spend time on it)

- The Method chapter's separation of "label the image, not the aircraft" (R0-01) from the physical-plausibility carve-out is sound and well argued.
- The PTC defence is the strongest passage in the document; do not weaken it.
- The R5-07 taper scope limit, the R6-06 positive-marker scope limit, and the Known Limitations list are exactly the kind of honesty a chair rewards.
- Retiring "Retractable Wheeled Gear" (inference, not observation) is a textbook P-2 application — cite it as an example in the Method chapter.
- The MECE principle citing Minto is correct even if it looks odd in an aerospace bibliography; it is where the term comes from.
