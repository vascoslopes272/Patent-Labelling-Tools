import time
import datetime
import pyautogui

# Set your target time ("17:50" for 5:50 PM, or "05:50" for 5:50 AM)
TARGET_TIME = "05:50" 

PROMPT_TEXT = """**Task: Create ONE new file only — `src/taxonomy_review_ui.py`.**

Do not touch any existing files. This file will be imported by `notebooks/01_review.ipynb`.

---

**Context — what already exists:**

`src/reviewer.py` already has:
- `assemble_patent_json(patent_id, cfg)` → builds the per-patent dict with figure paths, metadata, and SigLIP pre-fill suggestions
- `auto_fill_visual(patent_json, siglip_bundle)` → fills T2/G1 suggestion fields
- `process_patent(patent_id, cfg, siglip_bundle)` → runs the full pre-fill chain, returns a dict with keys `patent_id`, `label_json` (pre-filled JSON string), `label_token` (empty string at this stage)
- `run_stage01(cfg, siglip_bundle)` → batch-processes all patents, returns a DataFrame with columns `patent_id`, `label_json`, `label_token`

`notebooks/01_review.ipynb` already has:
- Config loading cell: `cfg = load_config("config.yaml")`
- SigLIP model loading cell: `siglip_bundle = load_siglip_model(cfg)`
- A cell that calls `run_stage01(cfg, siglip_bundle)` and stores the result as `df`

What is missing is the **human review UI** that takes `df` and lets the annotator work through each patent.

---

**Create `src/taxonomy_review_ui.py`** with the following:

**Module-level taxonomy constants** (exact strings — SigLIP outputs already match these):

```python
TOP = [("TW","Tilt Wing"),("TP","Tilt Propulsors"),("DS","Deflected Slipstream"),
       ("CVT","Combined CVT"),("SLC","Lift+Cruise"),("SRW","Stopped Rotor Wing"),
       ("RC","Rotorcraft"),("MR","Multirotor"),("HB","Hoverbike"),("PFV","Personal Flying Vehicle")]
WINGED     = {"TW","TP","DS","CVT","SLC","SRW"}
ROTORBORNE = {"RC","MR"}
WING_CONFIG = [("W","Standard Wings"),("BWB","Blended Wing Body"),("FW","Flying Wing"),("LB","Lifting Body")]
W_POS_V  = [("High","High/Hub"),("Mid","Mid/Center"),("Low","Low/Down")]
W_POS_L  = [("Fwd","Forward"),("Cent","Center CG"),("Aft","Aft/Rear")]
W_PLAN   = [("Str","Straight"),("Swp","Swept"),("Del","Delta"),("Oth","Other")]
W_ROLE   = [("Canard","Canard"),("Tandem","Tandem"),("AftStab","Aft Stabilizer"),("Stacked","Stacked")]
W_TILT   = [("Fixed","Fixed Surface"),("Tilt","Tiltable")]
EMP_TYPE = [("Tailless","Tailless"),("Conventional","Conventional"),("Cruciform","Cruciform"),
            ("T-Tail","T-Tail"),("V-Tail","V-Tail"),("Inv_V-Tail","Inv V-Tail"),
            ("H-Tail","H-Tail"),("Fins","Fins")]
EMP_KIN  = [("Fixed","Fixed"),("Tilt","Full aft tilt"),("Stabilator","All-Moving")]
FUS_SHAPE= [("Circular","Circular"),("Oval","Oval"),("Rectangular","Rectangular"),("Blended","Blended")]
FUS_KIN  = [("Fixed","Fixed"),("Variable","Variable Incidence")]
GEAR_ARCH= [("Skids","Skids"),("FixedWheel","Fixed Wheel"),("RetrWheel","Retractable Wheel"),("PadsHull","Pads/Hull")]
CHORD    = [("Front","Front/Puller"),("Back","Back/Pusher")]
BLADE_MECH=[("Open","Open Rotor"),("Ducted","Ducted Fan"),("Folded","Folding Blades")]
RETRACT  = [("Exposed","Non-Retractable"),("Retractable","Retractable")]
ZONE_CHORD=[("LE","Leading Edge"),("TE","Trailing Edge"),("Above","Above Surface"),("Below","Below Surface")]
ZONE_SPAN =[("Inboard","Inboard"),("MidSpan","Mid-Span"),("Outboard","Outboard"),("Wingtip","Wingtip")]
ZONE_EMP  =[("StackV","Stacked V"),("StackH","Stacked H"),("Tip","Tip Mounted")]
ZONE_FUSE =[("Nose","Nose"),("Aft","Aft"),("Side","Side"),("Dorsal","Dorsal"),("Ventral","Ventral")]
T1_SCOPE = ["Whole Aircraft Architecture","Architectural Subsystem Enabler","Component-Level Generic"]
T1_FIELD = ["Aerodynamic/Structural","Mechanical/Kinematic","Propulsion/Electrical","Control/Avionics","Other"]
T1_TARGET= ["Layout Convergence","Weight/Complexity Reduction","Aerodynamic Efficiency","Redundancy/Safety","Other"]
T1_REJECT= ["Pure UAV (No Passenger Intent)","Out of Technological Domain","Unreadable/Corrupt","Other"]
T2_PER   = ["Top","Bottom/Down","Front","Back","Side","Front-Isometric","Rear-Isometric","Generic 3D"]
T2_SYM   = ["Symmetric View","Asymmetric View"]
T2_ACST  = ["Line Drawing","Shaded Render","Solid/Filled Model","Schematic"]
T2_ACCOL = ["B/W (Monochrome)","Grayscale","Full Color"]
T2_BGST  = ["Solid Fill","Shaded/Gradient","Grid/Pattern"]
T2_BGCOL = ["White","Blueprint Blue","Dark","Grayscale"]
T2_PARTS = ["Whole Vehicle Layout","Primary Wing","Secondary/Canard Wing","Empennage/Tail",
            "Rotor/Propeller Blade","Tilt Hinge/Mechanism","Fuselage Cross-section",
            "Landing Gear/Skids","Internal Components/Batteries/Wiring"]
```

---

**`fresh_state() -> dict`** — returns a clean annotation dict. Fields:
`isApproved` (None), `t1DisapproveReason`, `t1DisapproveOther`, `isDuplicate` (False), `duplicateId`, `archCount` (1), `t1Scope`, `t1Field`, `t1Target`, `t2figNum` ("1"), `mainFigure` (None), `figData` ({}), `t2customParts` ([]), `topType` (None), `wingConf` (None), `wCount` (1), `wTilt1-4`, `wPosV1-4`, `wPosL1-4`, `wPlan1-4`, `wPlanOth1-4`, `wRole2-4` (all None), `latSym` (True), `longSym` (False), `empType`, `empKin`, `empNotes`, `fusShape`, `fusKin`, `fusNotes`, `gearArch`, `gearNotes`, `footLen`, `footWid`, `footHgt`, `footAmbiguous` (False), `wingNotes`, `comments`, `m3Comments`. M3 flat keys written later by sync: `m3_{key}_{count/sym/chord/orient/bmech/rmech/zone/zoneChord/zoneSpan/notes}`.

**`build_label_token(S) -> str`** — compact string e.g. `"WholeAircraftArchitecture_TP_W×2_W1:F-Mid-Cent-Str_W2:Canard-F-Low-Fwd-Del_Conventional_FUS:Circular_LSYM"`. Components: scope (spaces stripped) + topology + wingConf (with ×N if Standard) + per-wing descriptor (tilt T/F, posV, posL, plan, role if i>1) + empType first word + FUS:shape + LSYM/FSYM + m3 count tokens like `WING1x4`.

---

**Helper: `_IntStepper`** — class wrapping a `− N +` HBox. `__init__(label, value, min_val, max_val, on_change=None)`. Exposes `.widget` and `.value` (int property with setter that clamps and updates the display HTML).

**Helper: `_tbgroup(options, value=None)`** — takes `[(id, label), ...]`, returns `ToggleButtons(options=[(label,id),...], value=None, style={"button_width":"auto"}, layout=Layout(flex_wrap="wrap"))`.

---

**Class `TaxonomyReviewUI`:**

```python
def __init__(self, df: pd.DataFrame, id_col="patent_id",
            save_col="label_json", token_col="label_token"):
```

The `df` comes directly from `run_stage01()` — it already has a `label_json` column with SigLIP pre-fill JSON strings. The UI must **restore those pre-filled values** when loading a record (not start from `fresh_state()` if a saved JSON exists). This is the key integration point: `_restore_from_export(json.loads(row[save_col]))` populates `self.S` so the human sees the model's suggestions pre-loaded into the widgets.

**Tab structure** — `widgets.Tab` with 6 tabs titled: `T1 Meta`, `T2 Image`, `G1 Arch`, `M1+M2 Struct`, `M3 Prop`, `Summary`.

**Tab 0 — T1:** Approve/Disapprove buttons (toggle `button_style` success/danger). On Approve: show approved section (scope, field, target, arch count). On Disapprove: show reject reason dropdown + Other textarea. Duplicate checkbox + ID text. `_IntStepper` for archCount. `_tbgroup` for t1Scope. Dropdown for t1Field, t1Target. Global comments Textarea.

**Tab 1 — T2:** Figure nav (◄ Text ► + "of N" HTML). Buttons: ✓ Approve, ✗ Reject, ★ Set as Main, ↺ Reset. Status HTML. Arch dropdown (hidden when archCount==1). `_tbgroup` for per/sym/acst/accol/bgst/bgcol. Checkboxes for T2_PARTS. Custom tag input + Add button. Per-figure state is saved to/loaded from `S["figData"][fnum]` on every navigation event (`_t2_save_fig` / `_t2_load_fig`).

**Tab 2 — G1:** 10 Buttons grouped into 3 VBox cards (Winged, Wingless, Others). On click: highlight button, call `_apply_physics_locks(tt)`, `_update_wing_section_visibility()`, `_render_m3()`. Physics locks: TW → force wing0 tilt to "Tilt" + disabled; TP → force all wing tilts to "Fixed" + disabled; RC/MR → show suppression badge. All use `self._loading=True` during forced value sets.

**Tab 3 — M1+M2:** Wing section (hidden for non-WINGED): wingConf `_tbgroup` → show/hide wCount stepper + 4 wing cards. Each wing card: role (wings 2-4), tilt (with TP/TW locks), posV, posL, plan, planOth text (shown when plan=="Oth"). Symmetry checkboxes. Empennage: empType `_tbgroup` → show/hide empKin (hidden for Tailless/Fins; TW forces Fixed+disabled). Fuselage: fusShape, fusKin. Gear: gearArch. Footprint: 3 BoundedFloatTexts + ambiguous checkbox.

**Tab 4 — M3:** DEP flag HTML + `widgets.Output()` for dynamic cards. Cards rebuilt by `_render_m3()` on every topology/wingConf/wCount/empType change. Blueprints: RC→core_layout/rc; MR→core_layout/mr; winged+W→one card per wing (mode=wing, is_tw flag); else→core_layout/fuselage. Always add fuselage card. Add emp card if empType not in (None, Tailless, Fins). Each card: count `_IntStepper`, sym checkbox, blade mech, then (if not rc/mr): chord, orient (TW+wing→lock Fixed_Horizontal+disabled), retract, zone (wing→chordwise+spanwise, emp→ZONE_EMP, else→ZONE_FUSE), notes Textarea. Store live widget refs in `self._m3_live[key]`.

**Tab 5 — Summary:** Auto-refreshes on tab activation. Shows label token (monospace dark box), full JSON Textarea, validation warnings list, Save & Next + Save (Stay) buttons. Validation checks: approval set; if approved → scope+field assigned; topology selected; if winged → wingConf set; empType/fusShape/gearArch set; ≥1 approved figure; mainFigure set.

---

**Key methods:**

`_sync_widgets_to_state()` — reads all live widgets into `self.S`. Call `_t2_save_fig()` first. Harvest M3 live widget refs from `self._m3_live`.

`_push_state_to_widgets()` — bulk-write `self.S` to all widgets, wrapped in `self._loading=True/False`.

`_restore_from_export(saved: dict)` — maps saved export dict back to `self.S`. This runs on load when `df[save_col]` already has SigLIP pre-fill JSON — so pre-filled T2/G1 suggestions appear in widgets automatically.

`_build_export_dict()` — returns full annotation record: recordId, labelTimestamp, all T1 fields, figData, topologyClass, wings array (one entry per wCount), emp/fus/gear fields, propulsionCards list, labelToken.

`_do_save()` — `_sync_widgets_to_state()` → `_build_export_dict()` → write to `df.at[idx, save_col]` and `df.at[idx, token_col]`.

`_load_record(idx)` — update header, try `json.loads(df.iloc[idx][save_col])` → `_restore_from_export()`, else `fresh_state()`. Then `_push_state_to_widgets()`, `_apply_physics_locks()`, `_render_m3()`.

`go_to(idx)` — save current, load new.

**Public API:** `display()`, `go_to(idx)`, `labeled_df` property (calls `_do_save()`, returns `df.copy()`).

---

**Critical notes:**
- Use `self._loading = True/False` in all `observe()` callbacks to block cascade during bulk loads.
- `ToggleButtons` supports `value=None` — use it as default.
- M3 cards rendered via `Output` + `clear_output(wait=True)`. `_m3_live[key]` persists across re-renders to preserve entered values.
- `ToggleButtons options` must be `[(label, value)]` not `[(value, label)]`.
- Never embed unescaped `"` inside a double-quoted Python string — use single-quoted strings or `&ldquo;`/`&rdquo;` for HTML quotes.
- `DINOv2` is NOT used anywhere in this file.

Please write out the complete code for src/taxonomy_review_ui.py in a single code block. Do not use placeholders or omit repetitive sections like the wing loop fields, as I need to write this file directly to disk."""

print(f"⏰ Timer active. Waiting until {TARGET_TIME}...")
print("⚠️ CRITICAL: Click your mouse inside the Claude chat box right now so the cursor is blinking there!")

while True:
    now = datetime.datetime.now().strftime("%H:%M")
    if now == TARGET_TIME:
        # Taps the keys to type your prompt and hits enter
        pyautogui.typewrite(PROMPT_TEXT, interval=0.01)
        pyautogui.press('enter')
        print("� Prompt sent successfully!")
        break
    time.sleep(5) # Double-checks every 5 seconds