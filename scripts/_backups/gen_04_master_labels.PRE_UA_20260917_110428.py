"""(Kept in the repo from 2026-09-15; it used to live only in a session scratchpad.)
Generate notebooks/04_master_labels.ipynb from cell sources (kept here so the
notebook can be regenerated deterministically instead of hand-patched JSON)."""
import nbformat as nbf
from pathlib import Path

cells = []
def md(s): cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))
def code(s): cells.append(nbf.v4.new_code_cell(s.strip("\n")))

md(r"""
# 04 — Master labels (one wide sheet, one row per variant aircraft)

**Stage 04 = the batch join.** Reads the five human-corrected wizard exports (read-only), the current
wizard HTML (for option ids / display names) and, when it exists, the SBERT/LLM disapproval-reasons
workbook; writes a *disposable* master under `1639_LABELLED/joined/`. Re-run at any time — nothing
here writes back to a batch file.

Decisions this notebook implements (Phase 3, 2026-09-08/09 — see the `codebook-v2-phase-plan` and
`phase3-check-c7-c10` notes):

| what | rule |
|---|---|
| grain | one row per **variant aircraft** = `(patent_id, variant)`; single-arch patents are variant 1; rejected patents are one row with empty morphology |
| columns | only fields that will be analysed; G1–M3 keep the wizard's own Field names, wide (`boom1_…boom6_`, `wing1_…wing3_`, `<card>_t1_…`), capped at the observed maximum |
| values | bare **ids** — the `"id — Label"` composite is stripped (1,361 rows carried labels the wizard has since renamed); booleans as True/False; counts as integers (the wizard stores 1 as `True`) |
| duplicates | D1/D2 **inherit G1–M3 from the chain root** (flagged `labels_inherited_from`, `is_primary=False`); D3 keep their own labels; every duplicate is re-ordered directly under its original |
| `Other` notes | raw note kept + a normalised `<field>_otherTag` from `04_other_note_tags.csv` (editable; unmapped → `Misc`) |
| re-codes | `US2021284333A1 wing1_plan Oth→Trap` (reviewer typed the option id); two `T2.parts` free texts → `Other`, text moved to the figure comment |
| dropped | `codebook_version`, `timestamp`, `familyId`, `labelToken`, SBERT pre-labels (`scope/t1Field/t1Target`), long bibliographic text, retired fields (`longSym`, `empTiltsNote`, `*_symLong/_symCirc`, `footAmbiguous`, `boomN_cards`) |
| disapproval reason | `REASON_SOURCE` switch: `human` (default) / `sbert` / `sbert_when_human_empty`; a disagreement report is written whenever the SBERT workbook is present |
| images | every approved figure with a file is **copied** to `joined/approved_images/<batch>/<patent>/` (manifest with sha256) |
| identity review (03a) | 2026-09-14: `uav_final` / `is_electric_final` / `takeoff_final` + `*_uncertain` per aircraft row, spread over duplicate groups; edge tags UAVSimilar / ElectricSimilar / STOLSimilar merged into `edgeTags` (section 7b) |
| ML pre-labels | 2026-09-15: the `ml_predict_labels_<batch>.xlsx` predictions with an `ml_` prefix beside the human column they mirror, `ml_*_agrees` flags, per-figure SigLIP columns on the figures sheet (section 7c); never merged into the human record |
""")

code(r"""
import os, re, sys, json, shutil, hashlib, subprocess, tempfile, collections
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd

repo_root = Path().resolve().parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
from src.config_loader import load_config
cfg = load_config(); P = cfg["paths"]

# ── switches (env overrides so the notebook can run unattended) ─────────────
REASON_SOURCE = os.environ.get("NB04_REASON_SOURCE", "human")      # human | sbert | sbert_when_human_empty
SBERT_XLSX    = os.environ.get("NB04_SBERT_XLSX") or None           # the SBERT/LLM disapproval-reasons workbook (may not exist yet)
COPY_IMAGES   = os.environ.get("NB04_COPY_IMAGES", "1") == "1"      # real copies of every approved figure
BATCHES       = ["Batch_01", "Batch_02", "Batch_03", "Batch_04", "Batch_05"]

IN_DIR      = Path(P["corrected_wizard_exports"])                   # 1639_LABELLED/labels — the human record (== 03c apart from the Image_Path prefix)
ARCHIVE_03C = Path(P["base"]) / "data" / "03c_CORRECTED_wizard_exports"
HTML        = Path(P["html_template"])
OUT_DIR     = Path(os.environ.get("NB04_OUT_DIR") or P["labelled_outputs"])   # NB04_OUT_DIR: test builds elsewhere
TAGS_CSV    = Path("04_other_note_tags.csv")                        # beside this notebook; edit freely
SCHEMA_JS   = repo_root / "scripts" / "conformance" / "extract_html_schema.js"
assert REASON_SOURCE in ("human", "sbert", "sbert_when_human_empty"), REASON_SOURCE
RUN_TS = datetime.now().strftime("%Y-%m-%d %H:%M")
LOG: list[str] = [f"# 04_master_labels build log — {RUN_TS}", ""]
def log(s=""): print(s); LOG.append(str(s))
log(f"input : {IN_DIR}"); log(f"output: {OUT_DIR}"); log(f"wizard: {HTML.name}"); log(f"REASON_SOURCE={REASON_SOURCE}  SBERT_XLSX={SBERT_XLSX}  COPY_IMAGES={COPY_IMAGES}")
""")

md("## 1 — Load the five exports (long form) and verify they equal the archived 03c")
code(r"""
SEP = " — "
def strip_label(v):
    s = str(v); return s.split(SEP, 1)[0].strip() if SEP in s else s.strip()
def is_empty(v):
    return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() in ("", "nan", "None", "NaT")
def base_id(p): return re.sub(r"_arch\d+$", "", str(p))
def arch_idx(p):
    m = re.search(r"_arch(\d+)$", str(p)); return int(m.group(1)) if m else 1

frames = []
for b in BATCHES:
    f = IN_DIR / f"reviewed_patents_{b}.xlsx"
    df = pd.read_excel(f, sheet_name="Review"); df["batch"] = b; frames.append(df)
    log(f"  {b}: {len(df):>6} rows, {df.Patent_ID.nunique():>4} ids  <- {f.name}")
L = pd.concat(frames, ignore_index=True)
L["Field"] = L.Field.astype(str); L["Section"] = L.Section.astype(str)
L["base"] = L.Patent_ID.map(base_id); L["arch"] = L.Patent_ID.map(arch_idx)
L["_pos"] = L.groupby("batch").cumcount()          # file order, used to re-sort under originals
log(f"long table: {len(L)} rows, {L.base.nunique()} patents, {L.Patent_ID.nunique()} ids")

# The work tree must be the archived 03c apart from the Image_Path prefix swap — say so, don't assume it.
if ARCHIVE_03C.exists():
    for b in BATCHES:
        a = pd.read_excel(ARCHIVE_03C / f"reviewed_patents_{b}.xlsx", sheet_name="Review")
        w = L[L.batch == b].reset_index(drop=True)
        cols = [c for c in a.columns if c != "Image_Path"]
        same = a[cols].fillna("").astype(str).equals(w[cols].fillna("").astype(str))
        log(f"  {b}: equals archived 03c on every column but Image_Path -> {same}")
        if not same: log("  !! DIVERGED from 03c — check CORRECTIONS_LOG before trusting this build")
""")

md("## 2 — Wizard schema (option ids + display names) for the data dictionary and value checks")
code(r"""
schema_out = Path(tempfile.mkstemp(suffix=".json")[1])
r = subprocess.run(["node", str(SCHEMA_JS), str(HTML), str(schema_out)], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
SCHEMA = json.loads(schema_out.read_text())
LISTS  = {k: list(v) for k, v in SCHEMA["lists"].items()}
LABELS = SCHEMA.get("labels", {})
log(f"schema: {len(LISTS)} option lists, codebook_version {SCHEMA['codebook_version']!r} (not carried into the master)")

# suffix -> option list (mirrors scripts/conformance/check_batches.py FIELD_LIST + FIELD_LIST_EXTRA)
CODED = {("G1","topType"):"TOP", ("G1","edgeTags"):"T1_EDGE_TAGS",
         ("M1","attach"):"BOOM_ATTACH", ("M1","long"):"BOOM_POS_LONG", ("M1","span"):"BOOM_POS_SPAN",
         ("M1","wingRel"):"BOOM_WING_REL", ("M1","wingIdx"):"BOOM_WING_IDX", ("M1","orient"):"BOOM_ORIENT",
         ("M1","fusShape"):"FUS_SHAPE", ("M1","fusKin"):"FUS_KIN", ("M1","gearArch"):"GEAR_ARCH",
         ("M1","dinoUnderstanding"):"DINO_UNDERSTANDING",
         ("M2","wingConf"):"WING_CONFIG", ("M2","posV"):"W_POS_V", ("M2","posL"):"W_POS_L", ("M2","plan"):"W_PLAN",
         ("M2","role"):"W_ROLE", ("M2","tilt"):"W_TILT", ("M2","empType"):"EMP_TYPE",
         ("M3","chord"):"CHORD", ("M3","bmech"):"BLADE_MECH", ("M3","rmech"):"RETRACT_MECH", ("M3","propKin"):"PROP_KIN",
         ("M3","orient"):"M3_ORIENT", ("M3","zone"):"M3_ZONE", ("M3","zoneChord"):"M3_ZONE_CHORD", ("M3","zoneSpan"):"M3_ZONE_SPAN",
         ("T2","per"):"T2_PER", ("T2","acSty"):"T2_AC_STY", ("T2","acCol"):"T2_AC_COL", ("T2","bgSty"):"T2_BG_STY",
         ("T2","bgCol"):"T2_BG_COL", ("T2","acState"):"AC_STATE", ("T2","qualityFlag"):"QUALITY_FLAGS", ("T2","parts"):"T2_PARTS_DEFAULT",
         ("META","duplicateType"):"DUP_TYPES", ("T1","t1DisapproveReason"):"T1_DISAPPROVE_REASONS"}
MULTI = {("M3","zone"), ("G1","edgeTags"), ("T2","parts")}
def suffix(field):
    f = re.sub(r"^\d+_", "", str(field))
    f = re.sub(r"^(boom|wing|hull_array|core_layout|emp|fuselage)\d*_", "", f)
    return re.sub(r"^t\d+_", "", f)
def list_for(section, field): return CODED.get((section, suffix(field)))
""")

md("""
## 3 — Column registry

What the master carries, in order, and what it deliberately drops. Patent-level fields are renamed
to snake_case; G1–M3 keep the wizard's own Field names so the codebook maps 1:1.
""")
code(r"""
# ── patent level (T1 + META), in output order: (wizard Field, master column) ──
PATENT_COLS = [
    ("isApproved", "is_approved"), ("aircraftName", "aircraft_name"), ("assignee", "assignee"),
    ("title", "title"), ("app_year", "app_year"), ("pub_year", "pub_year"), ("pdf_link", "pdf_link"),
    ("archCount", "n_variants_declared"),
    ("isDuplicate", "is_duplicate"), ("duplicateType", "dup_type"), ("duplicateId", "dup_of"),
    ("t1DisapproveReason", "reason_human"), ("t1DisapproveReason_otherNote", "reason_note"),
    ("imgNotReflect", "img_not_reflect"),
    ("t1_humanUncertain", "t1_humanUncertain"), ("t1_uncertainNote", "t1_uncertainNote"),
    ("t1_quickOverride", "t1_quickOverride"), ("t1_quickNote", "t1_quickNote"),
]
# legacy name of reason_note on 4 Batch_05 records — merged into reason_note, never its own column
LEGACY_MERGE = {"disapproveOther": "reason_note"}
DROP_PATENT = {"abstract": "long bibliographic text", "description_of_drawings": "long bibliographic text",
               "scope": "unreviewed SBERT pre-label", "t1Field": "unreviewed SBERT pre-label", "t1Target": "unreviewed SBERT pre-label",
               "labelToken": "SBERT token", "timestamp": "save stamp", "codebook_version": "schema stamp (user decision: not in the master)",
               "familyId": "hardcoded placeholder", "mainFigure": "legacy patent-level flag, superseded by per-figure isMain",
               "comments": "free text, not analysed", "patentImageComments": "free text, not analysed"}
# ── variant level (G1..M3): retired / structural fields that get no column ──
DROP_VARIANT_RE = {r"^longSym$": "retired v13", r"^empTiltsNote$": "retired v15.5", r"_symLong$": "retired v15.6",
                   r"_symCirc$": "retired v15.6", r"^footAmbiguous$": "constant True", r"^boom\d+_cards$": "structural marker"}
# ── canonical order inside each section (N-suffixed groups expand to the observed max) ──
G1_ORDER = ["topType", "notPureArch", "edgeTags", "edgeTags_wizard",
            "uav_final", "uav_uncertain", "is_electric_final", "electric_uncertain", "electric_similar_final",
            "takeoff_final", "takeoff_uncertain", "identity_from", "g1_humanUncertain", "g1_uncertainNote", "g1_quickOverride", "g1_quickNote"]
M1_FIXED = ["fusShape", "fusShapeOtherNote", "fusKin", "gearArch", "latSym", "dinoUnderstanding", "boomsPresent"]
M1_BOOM  = ["count", "attach", "attachOth", "wingRel", "wingRelOth", "wingIdx", "span", "long", "longOth",
            "orient", "orientOth", "sym", "circSym", "hasProps", "tilts", "retracts"]
M1_TAIL  = ["wingNotes", "boomNotes", "fusNotes", "empNotes", "gearNotes", "m1_humanUncertain", "m1_uncertainNote", "m1_quickOverride"]
M2_FIXED = ["wingConf", "wingConfOtherNote", "wCount", "empType", "empTypeOtherNote", "empTilts"]
M2_WING  = ["role", "role_otherNote", "tilt", "posV", "posL", "plan", "plan_otherNote", "tipJoin"]
M2_TAIL  = ["m2_humanUncertain", "m2_uncertainNote", "m2_quickOverride", "m2_quickNote"]
M3_CARDS = ["fuselage", "wing1", "wing2", "wing3", "emp", "boom", "core_layout", "hull_array"]
M3_CARD  = ["count", "sym", "ntypes", "zone", "zoneChord", "zoneSpan", "quickOverride", "quickCount", "notes",
            "chord", "orient", "bmech", "rmech", "propKin", "propKinOth", "ctrlOnly"]         # the last 7: legacy single-type cards
M3_TYPE  = ["count", "chord", "orient", "bmech", "rmech", "propKin", "propKinOth", "ctrlOnly", "zone", "zoneChord", "zoneSpan"]
M3_TAIL  = ["m3_humanUncertain", "m3_uncertainNote"]
COUNT_FIELDS_RE = re.compile(r"(^|_)(count|ntypes|quickCount|wCount|archCount)$")
""")

md("## 4 — Pivot: patent-level table and variant-level table")
code(r"""
def pivot(section_rows, index):
    d = section_rows[["Patent_ID", "Field", "Value"]].copy()
    dup = d.duplicated(["Patent_ID", "Field"], keep=False)
    if dup.any():
        log(f"  !! {dup.sum()} duplicated (id, Field) cells — keeping the LAST (file order); ids: "
            f"{sorted(d[dup].Patent_ID.unique())[:8]}")
    return d.drop_duplicates(["Patent_ID", "Field"], keep="last").pivot(index="Patent_ID", columns="Field", values="Value")

PT = pivot(L[L.Section.isin(["T1", "META"])], "Patent_ID")          # keyed on the BASE id
VT = pivot(L[L.Section.isin(["G1", "M1", "M2", "M3"])], "Patent_ID") # keyed on the VARIANT id (bare or _archN)
PT.index.name = VT.index.name = None
assert all(base_id(p) == p for p in PT.index), "T1/META rows on an _archN id"
batch_of = L.drop_duplicates("base").set_index("base").batch.to_dict()
pos_of   = L.drop_duplicates("base").set_index("base")._pos.to_dict()

# a patent with BOTH a bare-id morphology and _archN rows would be ambiguous — report, prefer _archN
bare = {p for p in VT.index if arch_idx(p) == 1 and not p.endswith("_arch1")}
archd = {base_id(p) for p in VT.index if re.search(r"_arch\d+$", p)}
both = sorted(bare & archd)
if both: log(f"  !! {len(both)} patents carry morphology on the bare id AND on _archN ids (bare ignored): {both[:6]}")
VT = VT.drop(index=[p for p in both])
log(f"patent table {PT.shape}  variant table {VT.shape}")
var_ids = collections.defaultdict(list)
for v in VT.index: var_ids[base_id(v)].append(v)
for k in var_ids: var_ids[k].sort(key=arch_idx)
""")

md("## 5 — Assemble one row per variant (rejected patents and label-less duplicates get an empty morphology)")
code(r"""
patent_cols = [c for c, _ in PATENT_COLS]
rows = []
for pid in PT.index:
    variants = var_ids.get(pid, [])
    if not variants:
        rows.append(dict(patent_id=pid, variant=1, variant_id=pid, n_variants=0))
    for v in variants:
        rows.append(dict(patent_id=pid, variant=arch_idx(v), variant_id=v, n_variants=len(variants)))
M = pd.DataFrame(rows)
M["batch"] = M.patent_id.map(batch_of)
for src, dst in PATENT_COLS:
    M[dst] = M.patent_id.map(PT[src]) if src in PT.columns else np.nan
for src, dst in LEGACY_MERGE.items():
    if src in PT.columns:
        legacy = M.patent_id.map(PT[src]); fill = M[dst].map(is_empty) & ~legacy.map(is_empty)
        M.loc[fill, dst] = legacy[fill]; log(f"  {src}: {int(fill.sum())} legacy notes merged into {dst}")
variant_cols = [c for c in VT.columns if not any(re.search(p, c) for p in DROP_VARIANT_RE)]
VTm = VT[variant_cols].reindex(M.variant_id)
VTm.index = M.index
M = pd.concat([M, VTm], axis=1)
dropped_v = sorted(set(VT.columns) - set(variant_cols))
log(f"master skeleton: {len(M)} rows ({M.patent_id.nunique()} patents), {len(variant_cols)} variant columns kept, dropped {dropped_v}")
""")

md("## 6 — Normalise values: ids only, booleans, integer counts, the re-codes, the `Other` tags")
code(r"""
sec_of = L.drop_duplicates("Field").set_index("Field").Section.to_dict()
def norm_cell(v, lst, multi):
    if is_empty(v): return np.nan
    parts = str(v).split("|") if multi else [str(v)]
    out = [strip_label(p) for p in parts if p.strip()]
    return "|".join(out)
coded_cols, bool_cols, int_cols = [], [], []
for c in variant_cols:
    sec = sec_of.get(c); lst = list_for(sec, c) if sec else None
    if lst:
        coded_cols.append(c)
        M[c] = M[c].map(lambda v, lst=lst, m=(sec, suffix(c)) in MULTI: norm_cell(v, lst, m))
for c in ["reason_human", "dup_type"]:
    M[c] = M[c].map(lambda v: np.nan if is_empty(v) else strip_label(v))
# booleans: every non-empty value is True/False
for c in list(M.columns):
    vals = {str(x) for x in M[c].dropna().unique()}
    if vals and vals <= {"True", "False"}:
        M[c] = M[c].map(lambda v: np.nan if is_empty(v) else str(v) == "True").astype("boolean"); bool_cols.append(c)
# counts: the wizard writes a count of 1 as True (xlCount)
for c in list(M.columns):
    if COUNT_FIELDS_RE.search(c) and c not in bool_cols:
        M[c] = M[c].map(lambda v: np.nan if is_empty(v) else (1 if str(v) == "True" else 0 if str(v) == "False" else int(float(v)))).astype("Int64"); int_cols.append(c)
for c in ["app_year", "pub_year"]:
    M[c] = pd.to_numeric(M[c], errors="coerce").astype("Int64")
log(f"normalised: {len(coded_cols)} coded columns stripped to ids, {len(bool_cols)} boolean, {len(int_cols)} integer")

# every coded value must be a current option id — anything else is listed, never silently kept
bad = collections.Counter()
for c in coded_cols:
    lst = list_for(sec_of[c], c); ok = set(LISTS[lst]) | ({"Main"} if suffix(c) == "role" else set())
    for v in M[c].dropna():
        for p in str(v).split("|"):
            if p not in ok: bad[(c, p)] += 1
if bad: log(f"  !! values that are not current option ids: {dict(bad)}")
else:   log("  every coded value is a current option id")

# ── re-codes (documented decisions, applied here and only here) ──
RECODES = [("US2021284333A1", "wing1_plan", "Oth", "Trap", "reviewer typed the option id into plan_otherNote; drawing confirms taper (2026-09-09)")]
for vid, col, old, new, why in RECODES:
    i = M.index[M.variant_id == vid]
    assert len(i) == 1 and M.loc[i[0], col] == old, (vid, col, M.loc[i, col].tolist())
    M.loc[i[0], col] = new; log(f"  recode {vid} {col}: {old} -> {new}  ({why})")

# ── normalised tags for every 'Other' note ──
tags = pd.read_csv(TAGS_CSV)
tags["k"] = tags.note_text.map(lambda t: re.sub(r"\s+", " ", str(t).strip().lower()))
tag_of = {(r.note_field, r.k): r.tag for r in tags.itertuples()}
def note_field_key(col):                      # wing2_plan_otherNote -> wingN_plan_otherNote
    return re.sub(r"^(boom|wing)\d+_", r"\1N_", col)
PAIRS = [("attach", "attachOth"), ("wingRel", "wingRelOth"), ("long", "longOth"), ("orient", "orientOth"),
         ("fusShape", "fusShapeOtherNote"), ("empType", "empTypeOtherNote"), ("plan", "plan_otherNote"),
         ("role", "role_otherNote"), ("wingConf", "wingConfOtherNote"), ("propKin", "propKinOth")]
tag_cols, unmapped = [], collections.Counter()
for note_col in [c for c in variant_cols if any(c.endswith(s) for _, s in PAIRS)]:
    coded_sfx = next(cs for cs, ns in PAIRS if note_col.endswith(ns))
    coded_col = note_col[: -len(next(ns for cs, ns in PAIRS if note_col.endswith(ns)))] + coded_sfx
    tcol = coded_col + "_otherTag"
    nf = note_field_key(note_col) if not note_col.endswith("propKinOth") else "propKinOth"
    def _t(v, nf=nf):
        if is_empty(v): return np.nan
        k = re.sub(r"\s+", " ", str(v).strip().lower()); t = tag_of.get((nf, k))
        if t is None: unmapped[(nf, k)] += 1
        return t or "Misc"
    M[tcol] = M[note_col].map(_t); tag_cols.append(tcol)
log(f"  {len(tag_cols)} _otherTag columns; unmapped notes -> Misc: {sum(unmapped.values())}")

# rejected patents keep NO morphology in the master (decision 2026-09-08) — a rejected record that was
# labelled before it was rejected is reported, then blanked
rej_mask = ~M.is_approved.fillna(False).astype(bool)
had = M[rej_mask & M.topType.notna()][["patent_id", "topType", "reason_human"]]
REJECTED_WITH_MORPH = had.copy()
if len(had): log(f"  {len(had)} rejected patents carried a morphology, blanked: {had.to_dict('records')}")
M.loc[rej_mask, variant_cols + tag_cols] = np.nan
if unmapped: log("  " + "; ".join(f"{k[0]}: {k[1][:50]!r}" for k in list(unmapped)[:10]))
""")

md("## 7 — Duplicates: chain roots, D1/D2 inherit G1–M3, D3 keep their own, `is_primary`")
code(r"""
dup_of   = {p: strip_label(v) for p, v in PT["duplicateId"].dropna().items() if not is_empty(v)}
dup_type = {p: strip_label(v) for p, v in PT["duplicateType"].dropna().items() if not is_empty(v)}
known = set(PT.index)
def chain_root(p):
    # follow duplicateId until a record that is not itself a D1/D2 (a D3 keeps its own labels)
    seen = [p]
    while p in dup_of and dup_type.get(p) in ("1", "2"):
        p = dup_of[p]
        if p in seen or p not in known: return p, False
        seen.append(p)
    return p, True
def top_original(p):
    # the ultimate non-duplicate the row is re-ordered under (D3 included)
    seen = [p]
    while p in dup_of:
        p = dup_of[p]
        if p in seen or p not in known: return p
        seen.append(p)
    return p

M["dup_root"] = np.nan; M["labels_inherited_from"] = np.nan; M["is_primary"] = True; M["dup_of_missing"] = False
g1m3_cols = [c for c in variant_cols] + tag_cols
missing_root, cross_batch, d1_diff = [], 0, []
out_rows = []
for pid, grp in M.groupby("patent_id", sort=False):
    t = dup_type.get(pid)
    if t in ("1", "2"):
        root, ok = chain_root(pid)
        anchor = top_original(pid)
        if not ok or root not in var_ids:
            missing_root.append((pid, root)); grp = grp.copy(); grp["dup_root"] = root; grp["is_primary"] = False; grp["dup_of_missing"] = True
            out_rows.append(grp); continue
        if batch_of.get(root) != batch_of.get(pid): cross_batch += 1
        src = M[(M.patent_id == root)].sort_values("variant")
        if t == "1":   # D1 carries a wizard-side copy already; count where it differs from the root before overwriting
            own = grp.sort_values("variant").iloc[0]; rt = src.iloc[0]
            for c in g1m3_cols:
                a, b = own[c], rt[c]
                if not (is_empty(a) and is_empty(b)) and str(a) != str(b):
                    d1_diff.append(dict(patent_id=pid, root=root, column=c, own=a, root_value=b))
        new = []
        for _, r in src.iterrows():          # one row per ROOT variant — a D1/D2 is the same aircraft(s)
            row = grp.iloc[0].copy()
            for c in g1m3_cols: row[c] = r[c]
            row["variant"] = r["variant"]; row["variant_id"] = f"{pid}_arch{r['variant']}" if len(src) > 1 else pid
            row["n_variants"] = len(src); row["dup_root"] = root; row["labels_inherited_from"] = root; row["is_primary"] = False
            new.append(row)
        out_rows.append(pd.DataFrame(new))
    elif t == "3":
        grp = grp.copy(); grp["dup_root"] = top_original(pid); grp["is_primary"] = True; out_rows.append(grp)
    else:
        out_rows.append(grp)
M = pd.concat(out_rows, ignore_index=True)
log(f"duplicates: {len(dup_of)} links — D1 {sum(1 for v in dup_type.values() if v=='1')}, D2 {sum(1 for v in dup_type.values() if v=='2')}, D3 {sum(1 for v in dup_type.values() if v=='3')}")
log(f"  D1/D2 rows inheriting G1–M3: {int((~M.is_primary & M.labels_inherited_from.notna()).sum())}  (cross-batch roots: {cross_batch})")
log(f"  D1 cells that differed from their root before inheriting: {len(d1_diff)} on {len({d['patent_id'] for d in d1_diff})} patents")
if missing_root: log(f"  !! {len(missing_root)} D1/D2 whose root has no morphology (left empty, dup_of_missing=True): {missing_root[:8]}")
log(f"master: {len(M)} rows, {M.patent_id.nunique()} patents, primary rows {int(M.is_primary.sum())}")
""")

md(r"""
## 7b — Identity review (03a) → edge tags

Rulings 2026-09-14 (identity review closed): `uav_final == UAVSimilar` → **UAVSimilar**; `is_electric_final == No`
(or the ElectricSimilar tag given on the review page) → **ElectricSimilar**; `takeoff_final == STOL` (STOL only) →
**STOLSimilar**. V/STOL is still a VTOL: kept, no tag. Yes / Hybrid / Unknown electric → no tag. `*_uncertain` is an
uncertainty measure — the chosen label stays and the flag is carried. Per-aircraft answers (`*_variants`) apply per
`_archN` row.

**Duplicate groups** = a root + every D1/D2 that inherits from it. An answer the reviewer gave on ANY member (a
`*_human` cell, or a non-empty final on a `review_status == done` record) is the group's answer when the reviewed members
agree — a reviewed D2 carries its answer up to an unreviewed original and across to its siblings. With no reviewed
member the root's answer is inherited. Reviewed members that disagree keep their own answers and are flagged. Tags are the
union over the group, per aircraft row. `edgeTags` = the wizard's tags ∪ the identity tags (nothing is removed); the
wizard's own value stays in `edgeTags_wizard`. Rejected rows carry no identity answers and no tags.
""")
code(r"""
ID_XLSX = Path(P["labelled"]) / "identity" / "aircraft_identity_ALL.xlsx"   # rebuilt by scripts/build_identity_all.py
IDT = pd.read_excel(ID_XLSX, sheet_name="Identity", keep_default_na=False, dtype=str).set_index("patent_id")
log(f"identity: {len(IDT)} patents <- {ID_XLSX.name} (review_status done: {int((IDT.review_status == 'done').sum())})")
missing_id = sorted(set(M.patent_id) - set(IDT.index))
assert not missing_id, f"patents missing from the identity workbook: {missing_id[:10]}"

STOL_TAG = "STOLSimilar"
if STOL_TAG not in LISTS["T1_EDGE_TAGS"]:                  # notebook-only tag: not in the wizard's T1_EDGE_TAGS
    LISTS["T1_EDGE_TAGS"] = LISTS["T1_EDGE_TAGS"] + [STOL_TAG]
    LABELS.setdefault("T1_EDGE_TAGS", {})[STOL_TAG] = "STOL only (no vertical take-off), but similar enough"
# final column -> (human column, uncertainty column or None)
ID_FIELDS = {"uav_final": ("uav_human", "uav_uncertain"), "is_electric_final": ("is_electric_human", "electric_uncertain"),
             "takeoff_final": ("takeoff_human", "takeoff_uncertain"), "electric_similar_final": ("electric_similar_human", None)}
ID_UNC = ["uav_uncertain", "electric_uncertain", "takeoff_uncertain"]

def id_value(pid, col, v):
    # patent `pid`'s answer for aircraft row v: the per-aircraft cell when it lists that aircraft, else the patent answer
    r = IDT.loc[pid]; vc = col + "_variants"
    if vc in IDT.columns and r[vc].replace(";", "").strip():
        parts = [p.strip() for p in r[vc].split(";")]
        if len(parts) >= v: return parts[v - 1]
    return r[col].strip()
def is_true(s): return str(s).strip().upper() == "TRUE"
def tagset(v): return set() if is_empty(v) else set(str(v).split("|"))

appr_mask = M.is_approved.fillna(False).astype(bool)
M["edgeTags_wizard"] = M["edgeTags"]
M["group_root"] = M.labels_inherited_from.where(M.labels_inherited_from.notna(), M.patent_id)

# ── reviewed aircraft names (2026-09-16): review_decisions/NAME_DECISIONS.csv -> scripts/build_identity_all.py ->
# aircraft_name_final[_variants] in the identity workbook. A D1/D2 row takes the name of the aircraft it copies (its
# chain root, same variant). The name the annotator typed in the wizard stays beside it as aircraft_name_wizard.
M["aircraft_name_wizard"] = M["aircraft_name"]
def real_name(pid, root, v, fallback):
    src = root if root in IDT.index else pid
    vi = int(v) if str(v).strip().isdigit() else 1
    n = id_value(src, "aircraft_name_final", vi) if src in IDT.index else ""
    return n or fallback
M["aircraft_name"] = [real_name(p, r, v, w) for p, r, v, w in zip(M.patent_id, M.group_root, M.variant, M.aircraft_name_wizard)]
log(f"aircraft names: {int((M.aircraft_name != M.aircraft_name_wizard).sum())} rows carry the reviewed name; "
    f"{M.loc[appr_mask, 'aircraft_name'].nunique()} distinct names on approved rows")
for c in list(ID_FIELDS) + ID_UNC + ["identity_from"]:
    M[c] = np.nan
M[list(ID_FIELDS) + ["identity_from"]] = M[list(ID_FIELDS) + ["identity_from"]].astype(object)
TAG_OF_FIELD = {"uav_final": "UAVSimilar", "is_electric_final": "ElectricSimilar", "electric_similar_final": "ElectricSimilar",
                "takeoff_final": STOL_TAG}
ID_CONFLICTS, lifted, src_of = [], collections.Counter(), collections.defaultdict(list)
CONTESTED = collections.defaultdict(set)          # (root, variant) -> tags that must NOT spread across the group
for (root, v), g in M[appr_mask].groupby(["group_root", "variant"]):
    members = list(dict.fromkeys([root] + g.patent_id.tolist()))
    for fcol, (hcol, ucol) in ID_FIELDS.items():
        reviewed = {}
        for p in members:
            val = id_value(p, fcol, v)
            if val and (id_value(p, hcol, v) or IDT.at[p, "review_status"] == "done"):
                reviewed[p] = val
        vals = set(reviewed.values())
        if TAG_OF_FIELD[fcol] in CONTESTED[(root, v)] and len(vals) == 1:   # the electric answer is contested: the tag does not spread either
            vals = {None, *vals}
        for i, r in g.iterrows():
            if len(vals) == 1:   src = r.patent_id if r.patent_id in reviewed else next(iter(reviewed))
            elif len(vals) > 1:  src = r.patent_id if r.patent_id in reviewed else root
            else:                src = root
            if src != root: lifted[fcol] += 1
            val = id_value(src, fcol, v)
            M.at[i, fcol] = val if val else np.nan
            if ucol and is_true(IDT.at[src, ucol]): M.at[i, ucol] = True
            if src not in src_of[i]: src_of[i].append(src)
        if len(vals) > 1 and None in vals: continue
        if len(vals) > 1:
            CONTESTED[(root, v)].add(TAG_OF_FIELD[fcol])
            ID_CONFLICTS.append(dict(root=root, variant=v, field=fcol, answers="; ".join(f"{p}={a}" for p, a in reviewed.items())))
for i, s in src_of.items(): M.at[i, "identity_from"] = "; ".join(s)
for c in ID_UNC: M[c] = M[c].astype("boolean")
log(f"  rows whose answer came from a reviewed group member other than the root: {dict(lifted)}")
if ID_CONFLICTS: log(f"  !! {len(ID_CONFLICTS)} duplicate groups whose reviewed members disagree (own answers kept): {ID_CONFLICTS}")

def id_tags(r):
    t = set()
    if r.uav_final == "UAVSimilar": t.add("UAVSimilar")
    if r.is_electric_final == "No" or r.electric_similar_final == "ElectricSimilar": t.add("ElectricSimilar")
    if r.takeoff_final == "STOL": t.add(STOL_TAG)
    return t
group_tags = collections.defaultdict(set)
for i, r in M[appr_mask].iterrows(): group_tags[(r.group_root, r.variant)] |= id_tags(r) - CONTESTED[(r.group_root, r.variant)]
ROW_TAGS = {i: group_tags[(r.group_root, r.variant)] | (id_tags(r) & CONTESTED[(r.group_root, r.variant)])
            for i, r in M[appr_mask].iterrows()}      # a contested tag stays only on the row whose own answer gives it
TAG_ORDER = LISTS["T1_EDGE_TAGS"]
# The identity review is the later, dedicated pass: a wizard tag its answer contradicts is REMOVED, unless listed here.
WIZARD_TAG_KEEP = {("US11124286B1", "UAVSimilar"): "user 2026-09-14: UAV but similar stays, although uav_final=No"}
# (KR102712524B1/STOLSimilar was here until 2026-09-17: its identity takeoff is STOL now, so nothing contradicts the tag.)
def contradicted(i):
    # wizard tags the identity answer of row i contradicts -> {tag: why}
    out = {}
    if M.at[i, "uav_final"] == "No": out["UAVSimilar"] = "uav_final=No"
    if M.at[i, "is_electric_final"] in ("Yes", "Hybrid") and M.at[i, "electric_similar_final"] != "ElectricSimilar":
        out["ElectricSimilar"] = f"is_electric_final={M.at[i, 'is_electric_final']}"
    if M.at[i, "takeoff_final"] in ("VTOL", "V/STOL"): out[STOL_TAG] = f"takeoff_final={M.at[i, 'takeoff_final']}"
    return out
TAG_REMOVED, TAG_KEPT = [], []
def merged(i):
    t = tagset(M.at[i, "edgeTags_wizard"])
    if appr_mask[i]:
        pid = M.at[i, "patent_id"]; group = ROW_TAGS[i]
        for tag, why in contradicted(i).items():
            if tag in t and tag not in group:
                if (pid, tag) in WIZARD_TAG_KEEP: TAG_KEPT.append((pid, tag, why, WIZARD_TAG_KEEP[(pid, tag)]))
                else: t.discard(tag); TAG_REMOVED.append((pid, tag, why))
        t |= group
    return "|".join([x for x in TAG_ORDER if x in t] + sorted(t - set(TAG_ORDER))) if t else np.nan
M["edgeTags"] = [merged(i) for i in M.index]
TAG_REMOVED, TAG_KEPT = sorted(set(TAG_REMOVED)), sorted(set(TAG_KEPT))
unused_keep = set(WIZARD_TAG_KEEP) - {(p, t) for p, t, _, _ in TAG_KEPT}
if unused_keep: log(f"  !! WIZARD_TAG_KEEP entries that matched nothing: {sorted(unused_keep)}")
A_ = M[appr_mask]
for t in TAG_ORDER:
    has = A_.edgeTags.map(lambda v, t=t: t in tagset(v)); had = A_.edgeTags_wizard.map(lambda v, t=t: t in tagset(v))
    log(f"  edge tag {t:<16}: {int(has.sum()):>4} rows / {A_[has].patent_id.nunique():>3} patents   (wizard alone: {int(had.sum())} rows)")
log(f"  takeoff_final (approved rows): {A_.takeoff_final.value_counts().to_dict()}   is_electric_final: {A_.is_electric_final.value_counts().to_dict()}")
log(f"  uncertainty flags carried: { {c: int(A_[c].fillna(False).sum()) for c in ID_UNC} }")
log(f"  wizard tags removed (identity answer contradicts): {TAG_REMOVED}")
log(f"  wizard tags kept by WIZARD_TAG_KEEP: {TAG_KEPT}")
M = M.drop(columns=["group_root"])
""")

md(r"""
## 7c — Wizard ML pre-labels (`ml_predict_labels_<batch>.xlsx`) beside the human labels

The machine side of the wizard record, carried with an `ml_` prefix and never merged into the human
columns: SBERT `scope` / `t1Field` / `t1Target` (+ confidence), the auto-heuristic approval, the
family-based duplicate suggestion, SigLIP figure-duplicate suggestions, and — only for the batches that
ran the full stage-01 pass (Batch_05) — the G1/M1/M2 architecture and morphology predictions. Every ML
column is the patent's OWN prediction (D1/D2 rows do not inherit it). `ml_*_agrees` compares machine
and human where both exist. Per-figure SigLIP predictions go on the figures sheet.
""")
code(r"""
mlf = []
for b in BATCHES:
    d = pd.read_excel(IN_DIR / b / f"ml_predict_labels_{b}.xlsx", sheet_name="Review", keep_default_na=False, dtype=str)
    d["batch"] = b; mlf.append(d)
ML = pd.concat(mlf, ignore_index=True); ML["Field"] = ML.Field.astype(str)
log(f"ML feed: {len(ML)} rows, {ML.Patent_ID.nunique()} patents; sources {ML.Source.value_counts().to_dict()}")
missing_ml = sorted(set(PT.index) - set(ML.Patent_ID))
if missing_ml: log(f"  !! {len(missing_ml)} patents absent from the ML feed: {missing_ml[:8]}")

def ml_pivot(rows, what, index="Patent_ID"):
    keys = [index, "Field"] if isinstance(index, str) else list(index) + ["Field"]
    return rows.drop_duplicates(keys, keep="last").pivot(index=index, columns="Field", values=what)
def clean(v, coded=False):
    if is_empty(v): return np.nan
    return strip_label(v) if coded else str(v).strip()
def conf(v):
    try: return round(float(v), 3)
    except (TypeError, ValueError): return np.nan
def to_bool(col): return col.map(lambda v: np.nan if is_empty(v) else str(v) == "True").astype("boolean")

# ── patent level ──
t1 = ML[ML.Section.isin(["T1", "META"])]
V, C, S = ml_pivot(t1, "Value"), ml_pivot(t1, "Confidence"), ml_pivot(t1, "Source")
ML_T1 = ["scope", "t1Field", "t1Target", "isApproved", "isDuplicate", "duplicateId", "duplicateType"]
ML_SOURCE_FOR = {"scope", "isApproved", "isDuplicate", "topType"}      # one source column per family, not per field
ml_head = []
for f in ML_T1:
    if f not in V.columns: continue
    c = "ml_" + f
    M[c] = M.patent_id.map(V[f]).map(lambda v, k=(f == "duplicateType"): clean(v, k)); ml_head.append(c)
    if f in ("isApproved", "isDuplicate"): M[c] = to_bool(M[c])
    if f in C.columns and C[f].replace("", np.nan).notna().any():
        M[c + "_conf"] = M.patent_id.map(C[f]).map(conf); ml_head.append(c + "_conf")
    if f in ML_SOURCE_FOR and f in S.columns:
        M[c + "_source"] = M.patent_id.map(S[f]).map(clean); ml_head.append(c + "_source")
t2d = ML[(ML.Field == "dupOfPatent") & (ML.Value != "")]
M["ml_n_fig_dup_suggestions"] = M.patent_id.map(t2d.groupby("Patent_ID").size()).fillna(0).astype(int)
M["ml_fig_dup_patents"] = M.patent_id.map(t2d.groupby("Patent_ID").Value.agg(lambda s: "|".join(sorted(set(s)))))
ml_head += ["ml_n_fig_dup_suggestions", "ml_fig_dup_patents"]

# ── G1–M2 (only where the full stage-01 pass ran) ──
morph = ML[ML.Section.isin(["G1", "M1", "M2", "M3"])]
ML_MORPH = ["topType", "fusShape", "fusKin", "gearArch", "latSym", "wingConf", "wCount", "empType"]
ml_morph = []
if len(morph):
    Vm, Cm, Sm = ml_pivot(morph, "Value"), ml_pivot(morph, "Confidence"), ml_pivot(morph, "Source")
    for f in ML_MORPH:
        if f not in Vm.columns: continue
        c = "ml_" + f
        M[c] = M.patent_id.map(Vm[f]).map(lambda v: clean(v, True)); ml_morph.append(c)
        if f in Cm.columns: M[c + "_conf"] = M.patent_id.map(Cm[f]).map(conf); ml_morph.append(c + "_conf")
        if f in ML_SOURCE_FOR and f in Sm.columns: M[c + "_source"] = M.patent_id.map(Sm[f]).map(clean); ml_morph.append(c + "_source")
    if "ml_latSym" in M.columns: M["ml_latSym"] = to_bool(M["ml_latSym"])
    if "ml_topType" in M.columns:      # the feed predates the TP -> TR rename (2026-08-24); compare on current ids
        n_tp = int((M.ml_topType == "TP").sum()); M["ml_topType"] = M.ml_topType.replace({"TP": "TR"})
        log(f"  ml_topType: {n_tp} rows recoded TP -> TR (retired code)")
    not_carried = sorted(set(morph.Field) - set(ML_MORPH))
    log(f"  G1–M3 predictions exist for {morph.Patent_ID.nunique()} patents (batches {sorted(morph.batch.unique())}); "
        f"carried {ML_MORPH}; {len(not_carried)} per-wing / per-card M2–M3 fields NOT carried (sparse) — ask if needed")
else:
    log("  no G1–M3 predictions in any feed")

# ── agreement flags (only where both sides exist) ──
def agrees(a, b):
    both = a.notna() & b.notna()
    return pd.array(np.where(both, a.astype(str).values == b.astype(str).values, None), dtype="boolean")
M["ml_approved_agrees"] = agrees(M.ml_isApproved, M.is_approved)
M["ml_dup_agrees"] = agrees(M.ml_duplicateId, M.dup_of) if "ml_duplicateId" in M.columns else pd.array([None] * len(M), dtype="boolean")
ml_head += ["ml_approved_agrees", "ml_dup_agrees"]
if "ml_topType" in M.columns:
    M["ml_topType_agrees"] = agrees(M.ml_topType, M.topType); ml_morph.append("ml_topType_agrees")
    both = M.ml_topType.notna() & M.topType.notna()
    log(f"  ml_topType vs human topType: {int(M.ml_topType_agrees[both].sum())} / {int(both.sum())} agree")
appr_both = M.ml_isApproved.notna() & M.is_approved.notna()
log(f"  ml_isApproved vs human is_approved: {int(M.ml_approved_agrees[appr_both].sum())} / {int(appr_both.sum())} agree; "
    f"ml_duplicateId suggestions {int(M.ml_duplicateId.notna().sum()) if 'ml_duplicateId' in M.columns else 0}, "
    f"of which equal to the human dup_of {int(M.ml_dup_agrees.fillna(False).sum())}")
log(f"  ML columns added: {len(ml_head) + len(ml_morph)}")
""")

md("## 8 — Order: batch → original → its duplicates directly under it → variants")
code(r"""
def anchor(pid):
    return top_original(pid) if pid in dup_of else pid
M["_anchor"] = M.patent_id.map(anchor)
M["_abatch"] = M._anchor.map(batch_of).fillna(M.batch)
M["_apos"]   = M._anchor.map(pos_of).fillna(10**9)
M["_self"]   = (M.patent_id != M._anchor).astype(int)
M["_dt"]     = M.dup_type.fillna("0")
# second level: a D3 (own labels) is a sub-original — it sits after the original's direct D1/D2 copies and its own
# D1/D2 copies sit directly under it, so every dup_root block is contiguous
def sub_anchor(pid):
    t = dup_type.get(pid)
    if t == "3": return pid
    if t in ("1", "2"):
        root, _ = chain_root(pid)
        if dup_type.get(root) == "3": return root
    return None
M["_sub"]    = M.patent_id.map(sub_anchor)
M["_subpos"] = M._sub.map(pos_of).fillna(-1)
M["_subself"] = ((M._sub.notna()) & (M.patent_id != M._sub)).astype(int)
M = M.sort_values(["_abatch", "_apos", "_self", "_subpos", "_subself", "_dt", "patent_id", "variant"]).reset_index(drop=True)
M = M.drop(columns=["_anchor", "_abatch", "_apos", "_self", "_dt", "_sub", "_subpos", "_subself"])
""")

md("## 9 — Figures: one row per figure with a file; per-variant figure counts and the main figure on the master")
code(r"""
T2 = L[L.Section == "T2"].copy()
T2["block"] = T2.Sub_Dimension.astype(str)
placeholder = T2.block.str.contains(r"\(fig", regex=True)
n_placeholder = T2[placeholder & (T2.Field == "status")].groupby("base").size()
T2 = T2[~placeholder]
F = T2.drop_duplicates(["base", "block", "Field"], keep="last").pivot(index=["base", "block"], columns="Field", values="Value").reset_index()
F.columns.name = None
ip = T2.dropna(subset=["Image_Path"]).drop_duplicates(["base", "block"]).set_index(["base", "block"]).Image_Path
F["image_path"] = [ip.get((b, k), np.nan) for b, k in zip(F.base, F.block)]
F = F.rename(columns={"base": "patent_id", "figKey": "fig_key", "isMain": "is_main"})
F["batch"] = F.patent_id.map(batch_of)
F["image_file"] = F.image_path.map(lambda p: Path(str(p)).name if not is_empty(p) else np.nan)
F["file_exists"] = F.image_path.map(lambda p: (not is_empty(p)) and Path(str(p)).exists())
for c in ["per", "acSty", "acCol", "bgSty", "bgCol", "acState", "qualityFlag", "parts"]:
    if c in F.columns: F[c] = F[c].map(lambda v, m=(c == "parts"): norm_cell(v, None, m))
# T2.parts free text -> Other, text kept on the comment (decision 2026-09-09)
if "parts" in F.columns:
    okp = set(LISTS["T2_PARTS_DEFAULT"])
    for i in F.index[F.parts.notna()]:
        ps = str(F.at[i, "parts"]).split("|"); badp = [p for p in ps if p not in okp]
        if badp:
            F.at[i, "parts"] = "|".join([p for p in ps if p in okp] + ["Other"])
            F.at[i, "comment"] = ("" if is_empty(F.at[i, "comment"]) else str(F.at[i, "comment"]) + " | ") + "parts: " + "; ".join(badp)
            log(f"  parts recode {F.at[i,'patent_id']} {F.at[i,'fig_key']}: {badp} -> Other (text on comment)")
F["arch"] = pd.to_numeric(F.get("arch"), errors="coerce").astype("Int64")
for c in ["is_main", "hasLegends"]:
    if c in F.columns: F[c] = F[c].map(lambda v: np.nan if is_empty(v) else str(v) == "True").astype("boolean")
F["rotation_deg"] = F.rotation_deg.map(lambda v: 0 if str(v) == "False" else v).pipe(pd.to_numeric, errors="coerce").astype("Int64") if "rotation_deg" in F.columns else np.nan
F = F.rename(columns={"edgeTags": "fig_tags"})

# ── per-figure SigLIP pre-labels from the ML feed, keyed on (patent, image file name) ──
t2m = ML[ML.Section == "T2"].copy()
t2m["image_file"] = [Path(str(p)).name if not is_empty(p) else re.sub(r"^Image:\s*", "", str(s)).strip()
                     for p, s in zip(t2m.Image_Path, t2m.Sub_Dimension)]
t2m = t2m[t2m.image_file != ""]
Vf, Cf = ml_pivot(t2m, "Value", ["Patent_ID", "image_file"]), ml_pivot(t2m, "Confidence", ["Patent_ID", "image_file"])
ML_FIG = ["per", "acSty", "acCol", "bgSty", "bgCol", "acState", "parts", "tiltedInView", "match_status", "dupOfPatent", "dupOfFig"]
ML_FIG_CODED = {"per", "acSty", "acCol", "bgSty", "bgCol", "acState", "parts"}
fkeys = list(zip(F.patent_id, F.image_file))
ml_fig_cols = []
for f in ML_FIG:
    if f not in Vf.columns: continue
    F["ml_" + f] = [clean(Vf[f].get(k, np.nan), f in ML_FIG_CODED) for k in fkeys]; ml_fig_cols.append("ml_" + f)
    if f in ML_FIG_CODED and f in Cf.columns:
        F["ml_" + f + "_conf"] = [conf(Cf[f].get(k, np.nan)) for k in fkeys]; ml_fig_cols.append("ml_" + f + "_conf")
hit = F[[c for c in ml_fig_cols if not c.endswith("_conf")]].notna().any(axis=1)
log(f"  per-figure ML: {int(hit.sum())} / {len(F)} figures matched a feed row ({len(ml_fig_cols)} ml_ columns)")
for f in [c for c in ("per", "acSty", "acCol", "bgSty", "bgCol", "acState") if c in F.columns and "ml_" + c in F.columns]:
    both = F[f].notna() & F["ml_" + f].notna()
    F["ml_" + f + "_agrees"] = pd.array(np.where(both, F[f].astype(str).values == F["ml_" + f].astype(str).values, None), dtype="boolean")
    ml_fig_cols.append("ml_" + f + "_agrees")
FIG_COLS = ["batch", "patent_id", "fig_key", "block", "image_path", "image_file", "file_exists", "status", "arch", "is_main",
            "per", "acSty", "acCol", "bgSty", "bgCol", "parts", "qualityFlag", "acState", "stateNote", "hasLegends",
            "dupOf", "comment", "fig_tags", "rotation_deg"] + ml_fig_cols
F = F[[c for c in FIG_COLS if c in F.columns]]
F["approved_copy_path"] = np.nan
log(f"figures: {len(F)} with a file reference ({int(F.file_exists.sum())} files present, {int((F.status=='approved').sum())} approved); "
    f"{int(n_placeholder.sum())} '(fig N)' placeholder blocks dropped (0 approved)")

# per-variant counts + main figure on the master
appr = F[F.status == "approved"]
M["n_figures"] = M.patent_id.map(F.groupby("patent_id").size()).fillna(0).astype(int)
M["n_approved"] = M.patent_id.map(appr.groupby("patent_id").size()).fillna(0).astype(int)
M["n_fig_placeholders"] = M.patent_id.map(n_placeholder).fillna(0).astype(int)
byv = appr.groupby(["patent_id", "arch"]).size()
M["n_approved_this_variant"] = [int(byv.get((p, v), 0)) for p, v in zip(M.patent_id, M.variant)]
mainfig = appr[appr.is_main == True].drop_duplicates(["patent_id", "arch"]).set_index(["patent_id", "arch"]).image_path
M["main_figure"] = [mainfig.get((p, v), np.nan) for p, v in zip(M.patent_id, M.variant)]
# inherited rows point at the ROOT's figures (a D2 has the same figures by definition)
for i in M.index[M.labels_inherited_from.notna()]:
    if is_empty(M.at[i, "main_figure"]):
        M.at[i, "main_figure"] = mainfig.get((M.at[i, "labels_inherited_from"], M.at[i, "variant"]), np.nan)
""")

md("## 10 — Disapproval reason: the human/SBERT precedence switch and the disagreement report")
code(r"""
M["reason_sbert"] = np.nan; M["sub_reason"] = np.nan
sbert = None
if SBERT_XLSX and Path(SBERT_XLSX).exists():
    sbert = pd.read_excel(SBERT_XLSX)
    sbert.columns = [str(c).strip().lower() for c in sbert.columns]
    need = {"patent_id", "reason"}
    assert need <= set(sbert.columns), f"SBERT workbook needs columns {need} (+ optional sub_reason, confidence); has {list(sbert.columns)}"
    sbert = sbert.drop_duplicates("patent_id").set_index("patent_id")
    M["reason_sbert"] = M.patent_id.map(sbert["reason"])
    if "sub_reason" in sbert.columns: M["sub_reason"] = M.patent_id.map(sbert["sub_reason"])
    dis = M[~M.is_approved.fillna(False).astype(bool)].drop_duplicates("patent_id")[["batch", "patent_id", "aircraft_name", "reason_human", "reason_note", "reason_sbert", "sub_reason"]]
    dis["agree"] = dis.reason_human.fillna("").str.lower() == dis.reason_sbert.fillna("").str.lower()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dis.to_excel(OUT_DIR / "reason_disagreement_report.xlsx", index=False)
    log(f"SBERT: {len(sbert)} rows; rejected patents compared {len(dis)}, agree {int(dis.agree.sum())}, disagree {int((~dis.agree).sum())} -> reason_disagreement_report.xlsx")
    log(pd.crosstab(dis.reason_human.fillna("(empty)"), dis.reason_sbert.fillna("(empty)")).to_string())
elif REASON_SOURCE != "human":
    log(f"  !! REASON_SOURCE={REASON_SOURCE} but no SBERT workbook at {SBERT_XLSX!r} — falling back to human"); REASON_SOURCE = "human"

if REASON_SOURCE == "human":
    M["reason"] = M.reason_human; M["reason_source"] = np.where(M.reason_human.notna(), "human", None)
elif REASON_SOURCE == "sbert":
    M["reason"] = M.reason_sbert; M["reason_source"] = np.where(M.reason_sbert.notna(), "sbert", None)
else:
    use_h = M.reason_human.notna()
    M["reason"] = np.where(use_h, M.reason_human, M.reason_sbert)
    M["reason_source"] = np.where(use_h, "human", np.where(M.reason_sbert.notna(), "sbert", None))
log(f"reason column filled from: {M.reason_source.value_counts(dropna=False).to_dict()}")
""")

md("## 11 — Final column order, data dictionary, write everything, copy the approved images")
code(r"""
def expand(prefix_re, order, cols):
    # order group columns (boom1_x, boom2_x, ...) by group index, then by the canonical field order
    groups = sorted({int(m.group(1)) for c in cols for m in [re.match(prefix_re, c)] if m})
    out = []
    for g in groups:
        pre = re.match(prefix_re, next(c for c in cols if re.match(prefix_re, c) and int(re.match(prefix_re, c).group(1)) == g)).group(0)
        out += [pre + f for f in order if pre + f in cols]
    return out
def m3_block(cols):
    out = []
    for card in M3_CARDS:
        out += [f"{card}_{f}" for f in M3_CARD if f"{card}_{f}" in cols]
        types = sorted({int(m.group(1)) for c in cols for m in [re.match(rf"^{card}_t(\d+)_", c)] if m})
        for t in types: out += [f"{card}_t{t}_{f}" for f in M3_TYPE if f"{card}_t{t}_{f}" in cols]
    return out
cols = set(M.columns)
HEAD = ["batch", "patent_id", "variant", "variant_id", "n_variants", "aircraft_name", "aircraft_name_wizard", "assignee", "title", "app_year", "pub_year", "pdf_link",
        "is_approved", "reason", "reason_source", "sub_reason", "reason_human", "reason_sbert", "reason_note",
        "is_duplicate", "dup_type", "dup_of", "dup_root", "is_primary", "labels_inherited_from", "dup_of_missing",
        "n_figures", "n_approved", "n_approved_this_variant", "n_fig_placeholders", "main_figure", "img_not_reflect",
        "t1_humanUncertain", "t1_uncertainNote", "t1_quickOverride", "t1_quickNote"]
g1 = [c for c in G1_ORDER if c in cols]
m1 = [c for c in M1_FIXED if c in cols] + (["fusShape_otherTag"] if "fusShape_otherTag" in cols else [])
m1 += expand(r"^boom(\d+)_", M1_BOOM + [f"{x}_otherTag" for x in ("attach", "wingRel", "long", "orient")], cols)
m1 += [c for c in M1_TAIL if c in cols]
m2 = [c for c in M2_FIXED if c in cols] + [c for c in ("wingConf_otherTag", "empType_otherTag") if c in cols]
m2 += expand(r"^wing(\d+)_", M2_WING + ["role_otherTag", "plan_otherTag"], cols) + [c for c in M2_TAIL if c in cols]
m3 = m3_block(cols) + [c for c in cols if c.endswith("propKin_otherTag")] + [c for c in M3_TAIL if c in cols]
ORDER = HEAD + [c for c in ml_head if c in cols] + g1 + m1 + m2 + m3
def insert_after(order, anchor, items):
    # place ML prediction columns right after the human column they mirror (or at the end when the anchor is absent)
    items = [i for i in items if i in cols and i not in order]
    if anchor in order: i = order.index(anchor) + 1; order[i:i] = items
    else: order += items
for f in ML_MORPH:
    insert_after(ORDER, f, [f"ml_{f}", f"ml_{f}_conf", f"ml_{f}_source", f"ml_{f}_agrees"])
leftover = [c for c in M.columns if c not in ORDER and c != "n_variants_declared"]
if leftover: log(f"  columns not in the template (appended at the end): {leftover}")
M = M[ORDER + leftover]
log(f"final master: {M.shape[0]} rows x {M.shape[1]} columns")

# ── data dictionary ──
dd = []
for c in M.columns:
    sec = sec_of.get(c); lst = list_for(sec, c) if sec else None
    kind = ("tag" if c.endswith("_otherTag") else "id" if lst else "bool" if str(M[c].dtype) == "boolean" else
            "int" if str(M[c].dtype) == "Int64" else "text")
    opts = " | ".join(f"{i}={LABELS[lst].get(i, i)}" if LABELS.get(lst) else i for i in LISTS[lst]) if lst else ""
    dd.append(dict(column=c, section=sec or ("derived" if c in HEAD else ""), kind=kind, options=opts,
                   non_empty=int(M[c].notna().sum())))
DD = pd.DataFrame(dd)

# ── write ──
OUT_DIR.mkdir(parents=True, exist_ok=True)
M.to_excel(OUT_DIR / "master_labels.xlsx", sheet_name="master", index=False, engine="openpyxl")
F.to_excel(OUT_DIR / "master_figures.xlsx", sheet_name="figures", index=False, engine="openpyxl")
DD.to_csv(OUT_DIR / "data_dictionary.csv", index=False)
pd.DataFrame(d1_diff).to_csv(OUT_DIR / "d1_inheritance_diff.csv", index=False)
shutil.copy2(TAGS_CSV, OUT_DIR / "other_note_tags_used.csv")
excluded = [dict(field=k, why=v) for k, v in DROP_PATENT.items()] + [dict(field=k, why=v) for k, v in DROP_VARIANT_RE.items()]
pd.DataFrame(excluded).to_csv(OUT_DIR / "excluded_fields.csv", index=False)
log(f"wrote master_labels.xlsx, master_figures.xlsx, data_dictionary.csv, d1_inheritance_diff.csv, excluded_fields.csv -> {OUT_DIR}")

# ── approved images: real copies, sha256 manifest, idempotent ──
if COPY_IMAGES:
    root = OUT_DIR / "approved_images"; man = []; missing = 0; copied = 0
    for i, r in F[(F.status == "approved")].iterrows():
        if not r.file_exists: missing += 1; continue
        dst = root / r.batch / r.patent_id / r.image_file
        dst.parent.mkdir(parents=True, exist_ok=True)
        src = Path(r.image_path)
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst); copied += 1
        F.at[i, "approved_copy_path"] = str(dst)
        man.append(dict(batch=r.batch, patent_id=r.patent_id, fig_key=r.fig_key, src=str(src), dst=str(dst),
                        bytes=dst.stat().st_size, sha256=hashlib.sha256(dst.read_bytes()).hexdigest()))
    pd.DataFrame(man).to_csv(root / "MANIFEST.csv", index=False)
    F.to_excel(OUT_DIR / "master_figures.xlsx", sheet_name="figures", index=False, engine="openpyxl")
    log(f"approved images: {len(man)} in {root} ({copied} newly copied, {missing} approved figures whose file is missing on disk)")
""")

md("## 12 — Checks and summary")
code(r"""
checks = []
def chk(name, ok, detail=""): checks.append((name, bool(ok), detail)); log(f"  [{'OK' if ok else 'FAIL'}] {name}  {detail}")
chk("every patent present", M.patent_id.nunique() == PT.shape[0], f"{M.patent_id.nunique()} / {PT.shape[0]}")
chk("no label separator left in a coded column", not any(M[c].astype(str).str.contains(SEP, regex=False).any() for c in coded_cols))
prim_appr = M[M.is_primary & M.is_approved.fillna(False).astype(bool)]
# g1_quickOverride is the deliberate "unclassifiable" marker (no topType by design) — exempt, but list
unclass = prim_appr[prim_appr.g1_quickOverride.fillna(False).astype(bool)]
gap = prim_appr[prim_appr.topType.isna() & ~prim_appr.g1_quickOverride.fillna(False).astype(bool)]
chk("approved primary rows carry a topType (g1_quickOverride exempt)", gap.empty, f"{len(gap)} without; {len(unclass)} unclassifiable by design: {unclass.patent_id.tolist()}")
rej = M[~M.is_approved.fillna(False).astype(bool)]
chk("rejected rows carry no morphology", rej.topType.isna().all(), f"{len(rej)} rejected rows")
noreason = rej[rej.reason.isna()].patent_id.tolist()
log(f"  [{'OK' if not noreason else 'FINDING'}] rejected rows without a reason: {noreason}")
inh = M[M.labels_inherited_from.notna()]
inh_gap = inh[inh.topType.isna() & ~inh.labels_inherited_from.isin(unclass.patent_id)]
chk("inherited rows carry a topType (unclassifiable roots exempt)", inh_gap.empty, f"{len(inh)} inherited rows, {int((inh.topType.isna()).sum())} inherit an unclassifiable root")
chk("(patent_id, variant) unique", not M.duplicated(["patent_id", "variant"]).any())
_pos = pd.Series(range(len(M)), index=M.index); _first = M.groupby("patent_id").apply(lambda g: _pos[g.index].min())
_dups = M[M.dup_root.notna()].drop_duplicates("patent_id")
_before = [r.patent_id for r in _dups.itertuples() if _first.get(r.dup_root, -1) > _first[r.patent_id]]
def _contiguous(groups):
    # each group (an original + everything re-ordered under it, or a D3 + its own copies) must occupy one run of rows
    return {k: bool(_pos[g.index].max() - _pos[g.index].min() + 1 == len(g)) for k, g in groups if len(g)}
_top = _contiguous(M.groupby(M.patent_id.map(anchor)))
_d3  = _contiguous(M[M.patent_id.map(sub_anchor).notna()].groupby(M.patent_id.map(sub_anchor)))
_bad_blocks = [k for k, ok in {**_top, **_d3}.items() if not ok]
chk("every duplicate sits after its dup_root; original blocks and D3 sub-blocks contiguous", not _before and not _bad_blocks,
    f"{len(_before)} before their root; non-contiguous: {_bad_blocks[:6]}")
chk("ML feed covers every patent", not missing_ml, f"{len(missing_ml)} missing")
chk("no ML value landed in a human column", all(not c.startswith("ml_") for c in variant_cols + [d for _, d in PATENT_COLS]))
chk("every edge tag is a known tag", all(t in LISTS["T1_EDGE_TAGS"] for v in M.edgeTags.dropna() for t in str(v).split("|")))
chk("rejected rows carry no identity answers or tags", rej[["uav_final", "is_electric_final", "takeoff_final", "edgeTags"]].isna().all().all())
_removed = {(p, t) for p, t, _ in TAG_REMOVED}
chk("wizard tags removed only where the identity answer contradicts them",
    all((p, t) in _removed for p, w, e in zip(M.patent_id, M.edgeTags_wizard, M.edgeTags) for t in tagset(w) - tagset(e)), f"{len(TAG_REMOVED)} removed")
chk("V/STOL rows carry no STOLSimilar tag", not M[M.takeoff_final == "V/STOL"].edgeTags.map(lambda v: STOL_TAG in tagset(v)).any())
_inh = M[M.labels_inherited_from.notna() & M.is_approved.fillna(False).astype(bool)]
_root_tags = M[M.labels_inherited_from.isna()].set_index(["patent_id", "variant"]).edgeTags.map(tagset)
chk("every D1/D2 row carries its root's tags", all(_root_tags.get((r.labels_inherited_from, r.variant), set()) <= tagset(r.edgeTags) for r in _inh.itertuples()))
log("")
log(f"rows per batch: {M.groupby('batch').size().to_dict()}")
log(f"primary approved variants: {len(prim_appr)}   inherited D1/D2 rows: {len(inh)}   rejected: {len(rej)}")
log(f"topType (primary approved): {prim_appr.topType.value_counts().to_dict()}")
(OUT_DIR / "BUILD_LOG.md").write_text("\n".join(LOG) + "\n")
assert all(ok for _, ok, _ in checks), [n for n, ok, _ in checks if not ok]
print("\nBUILD_LOG.md written; all checks passed.")
""")

md("""
## 13 — ACTION FLAGS — what the human record still needs from you

Everything below is a finding in `labels/` that this notebook reports but must not fix (the human
record is never written here). Written to `joined/ACTION_FLAGS.csv` on every run; a flag disappears
only when the record is corrected in the wizard and re-exported.
""")
code(r"""
flags = []
def flag(kind, pid, detail, action): flags.append(dict(flag=kind, patent_id=pid, detail=detail, action=action))
for pid in rej[rej.reason.isna()].patent_id.unique():
    flag("REJECTED_NO_REASON", pid, "isApproved=False and no t1DisapproveReason", "open in the wizard, pick a disapproval reason, re-export")
for r in REJECTED_WITH_MORPH.itertuples():
    flag("REJECTED_CARRIES_MORPHOLOGY", r.patent_id, f"topType={r.topType}, reason={r.reason_human}",
         "record is rejected but still labelled — blanked in the master; decide whether the rejection or the labels are right")
for r in M[M.dup_of_missing].drop_duplicates("patent_id").itertuples():
    flag("DUP_ROOT_MISSING", r.patent_id, f"dup_type={r.dup_type}, dup_of={r.dup_of}", "the original carries no morphology; fix the link or label the record")
for r in F[(F.status == "approved") & ~F.file_exists].itertuples():
    flag("APPROVED_FIGURE_FILE_MISSING", r.patent_id, f"fig {r.fig_key}: {r.image_path}", "restore the crop or disapprove the figure")
for (nf, k), n in unmapped.items():
    flag("OTHER_NOTE_UNTAGGED", "", f"{nf}: {k[:80]!r} ({n}x)", "add a row to notebooks/04_other_note_tags.csv")
d1 = pd.DataFrame(d1_diff)
if len(d1):
    for pid, g in d1.groupby("patent_id"):
        flag("D1_OVERWRITTEN_BY_ROOT", pid, f"{len(g)} cells differed from root {g.root.iloc[0]}: {', '.join(g.column.tolist()[:6])}",
             "informational — D1 is the same aircraft, the root's labels win (decision 2026-09-09)")
for c in ID_CONFLICTS:
    flag("IDENTITY_DUP_CONFLICT", c["root"], f"{c['field']} (aircraft {c['variant']}): {c['answers']}",
         "reviewed duplicates of one aircraft answered differently — each keeps its own answer and the contested tag does not spread to the group; settle it in the identity review")
for pid, tag, why in TAG_REMOVED:
    flag("WIZARD_TAG_REMOVED", pid, f"wizard edgeTags had {tag} but {why}", "removed in the master (identity review wins); drop it in the wizard too, or add it to WIZARD_TAG_KEEP")
for pid, tag, why, note in TAG_KEPT:
    flag("WIZARD_TAG_KEPT", pid, f"{tag} kept although {why}", f"informational — {note}")
for pid in unclass.patent_id:
    flag("UNCLASSIFIABLE_BY_DESIGN", pid, "g1_quickOverride=True, no topType", "informational — excluded from topType counts")
AF = pd.DataFrame(flags, columns=["flag", "patent_id", "detail", "action"])
AF.to_csv(OUT_DIR / "ACTION_FLAGS.csv", index=False)
pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 90); pd.set_option("display.max_rows", 200)
print(f"{len(AF)} flags -> {OUT_DIR / 'ACTION_FLAGS.csv'}\n")
print(AF.groupby("flag").size().to_string(), "\n")
print(AF[~AF.flag.isin(["D1_OVERWRITTEN_BY_ROOT", "UNCLASSIFIABLE_BY_DESIGN", "WIZARD_TAG_KEPT"])].to_string(index=False))
print("\ninformational:")
print(AF[AF.flag.isin(["D1_OVERWRITTEN_BY_ROOT", "UNCLASSIFIABLE_BY_DESIGN", "WIZARD_TAG_KEPT"])][["flag", "patent_id", "detail"]].to_string(index=False))
""")

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata["kernelspec"] = {"display_name": "nb_01_review", "language": "python", "name": "nb_01_review"}
nb.metadata["language_info"] = {"name": "python"}
out = Path("/home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent-Labelling-Tools/notebooks/04_master_labels.ipynb")
nbf.write(nb, out)
print("wrote", out, len(cells), "cells")
