"""
timer_analysis_battery.py
Schedules six UNATTENDED prompts (A → B → C and D → E → F) that build and refine 
the eVTOL structural taxonomy and execute the Core Analysis Battery, pasted 
into VSCode Claude via clipboard.

Taxonomy Suite:
  Prompt A → Structural Taxonomy Design (Coarse to Fine)
  Prompt B → Adversarial Review & MECE/Decidability Verification
  Prompt C → Hard Configuration Stress-Testing & Edge Cases

Core Analysis Suite:
  Prompt D → Labels layer: wizard XLSX → canonical labels_v1.parquet + QC + grouped folds
  Prompt E → Probe battery + confounds (supervised separability, ladder stages 5–7)
  Prompt F → Clustering vs labels + retrieval + layer comparison + visuals (ladder 2–4, 8)

Usage:
  1. pip install pyautogui pyperclip
  2. Click inside the VSCode chat input so the cursor is blinking there.
  3. python timer_analysis_battery.py
  4. Edit target times below to the times you want.
  5. Edit the <<EDIT-ME>> placeholders in the configurations below before firing.
"""

import os
import time
import datetime
import subprocess
import pyautogui
import pyperclip

# ── TAXONOMY SUITE TARGET TIMES (24h HH:MM) ──────────────────────────────────
TARGET_TIME_A = "15:23"   # Taxonomy Design
TARGET_TIME_B = "15:45"   # Adversarial Review
TARGET_TIME_C = "04:20"   # Hard Configuration Stress-Testing

# ── CORE ANALYSIS SUITE TARGET TIMES (24h HH:MM) ──────────────────────────────
TARGET_TIME_D = "05:10"   # Labels layer (fastest; XLSX -> parquet + QC)
TARGET_TIME_E = "06:00"   # Probe battery — leave generous gap; E depends on D
TARGET_TIME_F = "07:30"   # Clustering + retrieval + visuals — F depends on D and E

# Folder constraint containment
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Patent-Labelling-Tools")
LOG_PATH = os.path.join(LOG_DIR, "timer_analysis.log")

# ── CORE ANALYSIS SUITE CONFIGURATION PARAMETERS ─────────────────────────────
# <<EDIT-ME: absolute path to the DINOv2_eVTOL_frozen_Analysis worktree to edit>>
_REPO = "/home/vasco/Vasco Workspace/Tese_Vasco_Lnx/DINOv2_eVTOL_frozen_Analysis.worktrees/<<EDIT-ME: worktree name>>"

# <<EDIT-ME: absolute path (or glob) to the wizard xlsx export(s)>>
_LABELS_EXPORT_GLOB = "/mnt/storage_11tb/<<EDIT-ME: path to reviewed_patents_*.xlsx>>"

# <<EDIT-ME: patent-level metadata file + exact column names>>
_META_PATH = "/mnt/storage_11tb/<<EDIT-ME: PatSeer metadata xlsx/csv>>"
_META_COL_PATENT_ID = "<<EDIT-ME: e.g. Publication Number>>"
_META_COL_ASSIGNEE = "<<EDIT-ME: e.g. Assignee/Applicant>>"
_META_COL_YEAR     = "<<EDIT-ME: e.g. Publication Year>>"

# Shared unattended-safety header pasted at the top of the core analysis battery prompts.
_HEADER = """╔══════════════════════════════════════════════════════════════════════════╗
║ SCHEDULED / UNATTENDED. The user may be away. Do NOT call AskUserQuestion / ║
║ EnterPlanMode or wait for approval — it hangs the run. Decide, act, verify,  ║
║ finish, leave one short report. If you truly cannot proceed safely, STOP   ║
║ and say why. Make reasonable choices and WRITE DOWN any assumption.        ║
╚══════════════════════════════════════════════════════════════════════════╝"""

_HARD_RULES = """HARD RULES (apply to every task in this sequence):
 - NO external API calls of any kind. No anthropic imports, no network model calls,
   no OpenAI, no HuggingFace inference API. Local compute only.
 - Raw input files are IMMUTABLE — never modify or delete them.
 - Thin notebooks: only import/call/display from src/. No business logic inline.
 - All paths via src/config_loader.py -> config.yaml (paths: block, optional
   $DRIVE_PATH from .env). No hardcoded paths anywhere.
 - Environment: conda env doclayout_yolo2, torch 2.5.1, transformers >=4.35,<5.0.
 - Surgical, minimal diffs. New functionality goes in NEW files; do not refactor
   working modules."""

_DONT_TOUCH = """DO NOT MODIFY these existing files (they are the historical record of the
binary shrouded/open study and must remain intact):
 - src/analysis.py                 (Stage-1 binary machinery: binary_labels(),
                                    permutation_separation, structure_report, etc.)
 - notebooks/11_structure_separation.ipynb
You may READ them for conventions (statistical discipline: never in-sample scores,
PCA before probing because p >> n, permutation nulls) — but you may not edit them."""

_VERIFY_PYTHON = """VERIFY BEFORE FINISHING (do not skip):
 - `python -m py_compile` passes on every new .py file.
 - Execute the new notebook end-to-end with `jupyter nbconvert --to notebook
   --execute --inplace` on a SMOKE subset first (see task-specific smoke knob),
   then launch the full run.
 - Sanity assertions listed per task must actually run and pass in code
   (assert statements, not just prose).
 - If the full run cannot finish in the session, leave the cache resumable
   and document EXACTLY how to resume in the report."""


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_A = """You are an Expert Aerospace Patent Analyst and Machine Learning Data Architect.

MISSION
Design a structural taxonomy for labeling ~1,500 eVTOL patents (~30,000 figures) to train
a self-supervised vision encoder (DINOv2) to recover structural grammar from isolated
black-and-white patent line drawings. I do the labeling; you design the schema.

HARD CONSTRAINTS
1. MECE: every category set must be mutually exclusive and collectively exhaustive.
2. Visual decidability: every field must be resolvable from a B&W line drawing alone,
   with no reference to patent text/claims. If a distinction requires reading text,
   it does not belong in the visual taxonomy — flag it instead for a separate
   text-classification layer (e.g. PatentSBERTa over patent claims/description).
3. Pragmatic scale: must be labelable by one human annotator at a rate that reaches
   statistical significance across 1,500 patents. Favor fewer, higher-signal fields
   over exhaustive completism.
4. Academic grounding: justify every top-level category against at least one of:
   - EASA SC-VTOL-01 (means of compliance / configuration classes)
   - FAA/AAM literature and VFS (Vertical Flight Society) eVTOL taxonomy
   - Ugwueze et al., "Investigation of a Mission-Based Sizing Method for eVTOL
     Aircraft Preliminary Design" (AIAA 2022-1931) — G1 topology precedent
   - Established conceptual-design texts (Roskam-style propulsion/structure
     integration logic)
   Cite the specific concept you're drawing from, not just the source name.
5. Zero-variance fields are forbidden: if a candidate field would take the same value
   for ~100% of the dataset (e.g. "propulsion is electric"), exclude it — it carries
   no classification signal.

DELIVERABLE STRUCTURE
Produce a multi-stage taxonomy, from coarse to fine:
- STAGE 1 (patent-level triage): does this patent describe an eVTOL aircraft at all,
   and at what level of relevance/completeness?
- STAGE 2 (image-level characterization): what TYPE of drawing is this (isometric view,
   detail callout, exploded diagram, schematic, table/text page) and is it usable for
   structural labeling?
- STAGE 3 (architecture/topology): the aircraft's overall lift/thrust architecture —
   treat this as parallel, orthogonal branches (not a nested tree), covering how lift
   and cruise thrust are generated and whether they use shared or dedicated propulsors.
- STAGE 4+ (component morphology): fuselage/structure, lifting surfaces, and
   propulsion matrix as separate orthogonal modules, each independently classifiable.

For each field, specify: name, allowed values (as a closed enum where possible),
one-sentence visual decision rule a human can apply in under 5 seconds, and which
academic source justifies its inclusion as a category (not just as a real-world
distinction).

Do NOT design a labeling UI or write code — this is schema design only. Output as a
structured outline I can review and iterate on."""

PROMPT_B = """You are the same Expert Aerospace Patent Analyst. I already have a working taxonomy
(attached/pasted below — six stages: T1 meta/triage, T2 image characterization,
G1 architecture topology, M1 structure/fuselage, M2 aero/lifting surfaces,
M3 propulsion matrix). Your job now is adversarial review, not fresh design.

For each field in the taxonomy, check:
1. MECE violation — do any two allowed values overlap in practice, or is there a
   real-world eVTOL configuration that fits none of the values?
2. Visual decidability failure — can a human actually resolve this field from the
   B&W drawing alone, or does it secretly require the patent text/claims?
3. Zero-variance risk — across a real eVTOL patent corpus, would >95% of instances
   take the same value?
4. Missing orthogonal axis — is there a structurally distinct dimension this taxonomy
   conflates with an existing field (e.g. topology vs. per-image tilt state)?
5. Granularity mismatch — is this field too fine to hit statistical significance at
   n≈1,500 patents, or too coarse to be useful for a vision model trying to learn
   structural grammar?

For every issue found, propose the smallest surgical fix (do not propose wholesale
restructuring) and cite the academic/certification source that supports your fix.
Flag explicitly if you find NO issues in a given stage — do not manufacture findings.

[PASTE TAXONOMY / CODEBOOK HERE]"""

PROMPT_C = """Take the finalized taxonomy and stress-test it against these known-hard eVTOL
configurations, stating exactly which field/value each one maps to and flagging
any case where no valid combination exists:

- Tiltwing vs. tilt-fan-in-wing (same visual silhouette, different pivot mechanism)
- Stopped-rotor / stopped-rotor-lift+cruise hybrids
- Distributed electric propulsion with >8 identical lift rotors plus 1-2 dedicated
   cruise propellers
- Compound helicopters with auxiliary wings (partial lift offload, not full VTOL
   wing-borne cruise)
- Ducted-fan lift arrays embedded in a lifting-body fuselage (no discrete "wing")
- A patent showing two genuinely distinct architectures in different figure sets
   (continuation/family patents)
- A patent whose only usable figure is a schematic block diagram, not a 3D rendering

For each, state pass/fail and, on failure, propose the minimal taxonomy adjustment."""

PROMPT_D = f"""UNATTENDED ANALYSIS TASK D of F — Labels layer.

{_HEADER}

Repo: {_REPO}
This is the frozen-DINOv2 analysis repo ("evtol_frozen_baseline").

{_HARD_RULES}

{_DONT_TOUCH}

CONTEXT — existing code to READ (do not modify):
 - src/embeddings.py — saves emb_layer{{L}}_{{pool}}.npy + metadata.parquet
   (columns figure_id, patent_id, figure_type) + model_info.json under
   <output_dir>/embeddings/. Row order aligned across arrays and metadata.
 - src/config_loader.py — config.yaml loader with $DRIVE_PATH expansion.
 - src/data.py — figure-listing utilities.

NEW INPUT DATA
Taxonomy labels exported from my HTML labeling wizard as LONG-FORMAT xlsx:
one row per (patent, section, subdimension, field, value), produced by the wizard's
recordToRows(). Multi-architecture patents export with an "_arch{{N}}" suffix on the
patent id. Files at:
  {_LABELS_EXPORT_GLOB}

Patent-level metadata at:
  {_META_PATH}
with columns:
  - patent id : {_META_COL_PATENT_ID}
  - assignee  : {_META_COL_ASSIGNEE}
  - year      : {_META_COL_YEAR}

TASK — create EXACTLY these new files, nothing else:

1) src/labels.py with:
   - inspect_exports(cfg) -> prints the distinct (section, subDim, field) triples
     found in the xlsx files with row counts, so the report documents the actual
     schema encountered.
   - build_canonical(cfg) -> DataFrame, one row per base patent_id, wide format:
       * Pivot the long rows to columns named "{{section}}_{{field}}"
         (e.g. G1_topology, M2_wingConf, M2_wCount, M3_propKin ...).
       * Base patent id = id with any "_arch{{N}}" suffix stripped. Add columns
         n_architectures (int) and multi_arch (bool). For multi_arch patents keep
         arch 1's values in the main columns but set multi_arch=True.
       * Join assignee and year from the metadata file; add year_bin
         (config: labels.year_bins, default 3 quantile bins).
       * Provenance columns: label_source_file, ingest_date.
   - validate_canonical(df, cfg) -> QC DataFrame of issues: duplicate base ids,
     patents in labels but with no embedding rows in
     <output_dir>/embeddings/metadata.parquet (and vice versa), fields whose value
     sets exceed config-declared vocabularies (labels.vocab, optional — if absent,
     just report the observed value set per column), null rates per column.
   - assign_folds(df, cfg) -> adds column "fold" via sklearn GroupKFold
     (n_splits = labels.n_folds, default 5) grouped by base patent_id, computed
     ONCE with labels.random_state and FROZEN into the output file. Also add
     "fold_assignee" using GroupKFold grouped by assignee (robustness splits).
   - save_canonical(df, cfg) -> writes <output_dir>/analysis_v2/labels_v1.parquet
     and labels_v1.csv, plus labels_v1_dictionary.csv (column, dtype, observed
     values, null %, n per value).

2) notebooks/10_labels_qc.ipynb — thin: load config, run inspect_exports,
   build_canonical, validate_canonical, assign_folds, save_canonical; display the
   QC table and a per-attribute label-coverage table (attribute x class -> count),
   flagging every class with count < config labels.min_class_count (default 15).

3) config.yaml — ADD (do not remove anything) a labels: block with keys used above
   plus labels.target_attributes: an explicit list of the wide columns intended for
   probing (fill it with the attributes you actually found, commented for my review)
   and labels.confound_cols: [assignee, year_bin, figure_type].

{_VERIFY_PYTHON}

TASK-SPECIFIC ASSERTIONS (must exist as `assert` in code):
 - No duplicate base patent_id in the canonical output.
 - Every fold contains >= 1 patent.
 - Row counts printed for: raw long rows in, unique base patents out, multi_arch count.

HANDOFF: write a short report at <output_dir>/analysis_v2/REPORT_A.md:
schema found (list of (section, field) triples with counts), attribute coverage
summary, multi_arch count, assumptions made, and the exact filenames written.
Final line MUST be: "TASK E (probe battery) can proceed." """

PROMPT_E = f"""UNATTENDED ANALYSIS TASK E of F — Probe battery + confounds.

{_HEADER}

Repo: {_REPO}

STEP 0 — READ THE HANDOFF FIRST: read <output_dir>/analysis_v2/REPORT_A.md. If it
does not end with "TASK E (probe battery) can proceed.", STOP and report the failure
in REPORT_B.md — do not attempt to rebuild the labels layer.

{_HARD_RULES}

{_DONT_TOUCH}

CONTEXT — existing code to READ (not modify):
 - src/embeddings.py — arrays dict keyed (layer, pooling), row-aligned
   metadata.parquet with figure_id/patent_id/figure_type.
 - src/analysis.py — Stage-1 binary study. REUSE its statistical discipline
   (never in-sample scores, PCA before probing because p >> n, permutation nulls),
   but do NOT edit it.
 - src/labels.py + <output_dir>/analysis_v2/labels_v1.parquet produced by Task D
   (canonical labels, one row per base patent_id, frozen "fold" and
   "fold_assignee" columns, labels.target_attributes and labels.confound_cols in
   config).

TASK — create EXACTLY these new files:

1) src/probe_battery.py with:
   - attach_labels(metadata, labels_df, cfg) -> per-FIGURE frame: join canonical
     labels onto embedding metadata rows by base patent_id. Exclude multi_arch
     patents when cfg probe.exclude_multi_arch (default true). Return the join plus
     an exclusion report (n figures dropped and why).
   - For EACH attribute in labels.target_attributes x EACH embedding matrix
     (layer, pooling) — the full grid:
       a) probe_linear(X, y, groups, folds) -> grouped-CV logistic regression
          (multinomial), pipeline StandardScaler -> PCA(probe.n_pca, default 50)
          -> LogisticRegression(max_iter=5000, class_weight="balanced").
          Use the FROZEN fold column (GroupKFold semantics: all figures of a patent
          share a fold). Metrics: balanced accuracy, macro-F1, per-class F1.
          Baselines: majority-class and stratified-random. Permutation null:
          probe.n_perm (default 500 given corpus size) label shuffles AT THE PATENT
          LEVEL (shuffle patent->label mapping, then broadcast to figures — never
          shuffle figure rows independently), -> empirical p-value.
          Bootstrap CI (probe.n_boot, default 1000) on the out-of-fold predictions.
       b) knn_leave_one_patent_out(X, y, patent_ids, k=cfg probe.knn_k default 10,
          cosine) -> for each figure, neighbors EXCLUDING all figures of the same
          patent; majority-vote accuracy + macro-F1.
     Before probing an attribute: drop classes with support < labels.min_class_count
     and record what was dropped. Skip attribute entirely if <2 classes remain.
   - confound_battery(...) -> identical probe_linear machinery but y = each of
     labels.confound_cols (assignee: keep top-N assignees by count, N = probe
     .assignee_top_n default 15, rest -> "OTHER"; year_bin; figure_type).
   - within_between(X, labels_df) -> mean cosine similarity for pairs:
     (same architecture, different assignee) vs (same assignee, different
     architecture), with bootstrap CIs and Cohen's d. "Architecture" = the config
     key probe.primary_attribute (default the G1 topology column).
   - save_battery(...) -> <output_dir>/analysis_v2/probe_scores.parquet
     (columns: attribute, layer, pooling, metric, value, ci_lo, ci_hi, p_perm,
     n_patents, n_figures, n_classes, dropped_classes) + confound_scores.parquet
     + within_between.csv + heatmap PNGs (attribute x matrix, one per metric,
     matplotlib, no seaborn dependency if not already in requirements).

2) notebooks/12_probe_battery.ipynb — thin: run the grid, display the two score
   tables and heatmaps, and print an automatic interpretation block implementing
   the decision logic: architecture-probe vs confound-probe comparison per matrix
   (if assignee decodability >= architecture decodability, print the explicit
   warning that style dominates).

3) config.yaml — ADD a probe: block with every knob above.

COMPUTE NOTE: full grid = n_attributes x 6 matrices x (CV + permutations). Write it
resumable: cache each (attribute, layer, pooling) result to
<output_dir>/analysis_v2/probe_cache/ as parquet and skip completed cells on rerun.

{_VERIFY_PYTHON}

TASK-SPECIFIC ASSERTIONS (must exist as `assert` in code):
 - No patent appears in more than one fold.
 - Every permutation p-value is in [0, 1].
 - Row alignment: len(X) == len(y) == len(patent_ids) for every (attribute, matrix).
 - Do NOT assert majority-baseline <= probe score — it can legitimately fail;
   report it instead.

SMOKE MODE FIRST: probe.smoke=true limits to 2 attributes x 2 matrices x 50
permutations. Confirm outputs, then launch the full run.

HANDOFF: report at <output_dir>/analysis_v2/REPORT_B.md: grid completed (yes/no,
which cells cached vs full), top-3 and bottom-3 decodable attributes, confound
verdict (does assignee decodability exceed architecture decodability on any matrix?
name them), assumptions. Final line MUST be: "TASK F (clustering + retrieval) can
proceed." """

PROMPT_F = f"""UNATTENDED ANALYSIS TASK F of F — Clustering, retrieval, layer comparison, visuals.

{_HEADER}

Repo: {_REPO}

STEP 0 — READ THE HANDOFFS FIRST: read <output_dir>/analysis_v2/REPORT_A.md AND
REPORT_B.md. If REPORT_B does not end with "TASK F (clustering + retrieval) can
proceed.", STOP and report the failure in REPORT_C.md.

{_HARD_RULES}

{_DONT_TOUCH}

CONTEXT — depends on: <output_dir>/analysis_v2/labels_v1.parquet (Task D) and
probe_scores.parquet / confound_scores.parquet (Task E). READ src/embeddings.py,
src/labels.py, src/probe_battery.py for conventions.

TASK — create EXACTLY these new files:

1) src/cluster_alignment.py with:
   - For EACH embedding matrix (layer, pooling), on L2-normalized vectors:
       a) cluster_all(X, cfg) -> k-means (k sweep over cluster.k_range default
          4..20, on PCA-50), Ward hierarchical (cosine via PCA-50 euclidean
          approximation — document this choice), HDBSCAN (min_cluster_size =
          cluster.hdbscan_min default 15). Internal metrics IN ORIGINAL SPACE
          (silhouette cosine, Davies-Bouldin, Calinski-Harabasz), never on
          UMAP-reduced data.
       b) alignment(cluster_labels, y_attribute) -> ARI, NMI, purity vs EACH
          attribute in labels.target_attributes, each with a permutation null
          (cluster.n_perm default 1000, shuffle at patent level) -> p-values.
       c) stability(X, cfg) -> bootstrap resampling (cluster.n_boot default 100):
          mean pairwise ARI between bootstrap clusterings (k fixed at the sweep's
          best silhouette k).
   - retrieval(X, y, patent_ids, cfg) -> precision@k for k in {{5, 10}}: fraction of
     cosine nearest neighbors sharing the query's attribute value, ALWAYS excluding
     same-patent figures from the neighbor pool. Per attribute. Compare against the
     analytical chance level (class prevalence).
   - consolidate(cfg) -> merge probe_scores.parquet + this stage's alignment and
     retrieval tables into ONE summary: for each (layer, pooling), the mean rank
     across {{probe macro-F1, kNN acc, ARI vs primary attribute, precision@10}} ->
     winner_matrix.csv naming the best (layer, pooling) per attribute and overall.
   - visuals(cfg) -> PCA (2D) and UMAP (umap-learn, default params, random_state
     fixed) scatter grids for the winning matrix ONLY, colored by each target
     attribute AND each confound (assignee top-N, year_bin, figure_type). Every
     figure title MUST carry the literal suffix "(exploratory — no metric claims)".
     PNGs to <output_dir>/analysis_v2/figures/.

2) notebooks/13_cluster_alignment.ipynb — thin: run everything, display
   cluster_metrics table, alignment table (with p-values), stability, retrieval
   table, winner_matrix, then the visuals. Final markdown cell auto-fills the
   ladder decision table verdicts (stages 2, 3, 8) from the computed numbers.

3) config.yaml — ADD a cluster: block with the knobs above.

Outputs: cluster_metrics.parquet, label_alignment.parquet, stability.csv,
retrieval_scores.parquet, winner_matrix.csv, figures/ — all under
<output_dir>/analysis_v2/. Cache and resume like Task E (cluster_cache/).

{_VERIFY_PYTHON}

TASK-SPECIFIC ASSERTIONS (must exist as `assert` in code):
 - Row alignment between every loaded array and the labels join
   (same length, same figure_id order).
 - Every permutation p-value is in [0, 1].
 - Same-patent exclusion actually happens in retrieval (assert no returned
   neighbor shares the query's patent_id).

SMOKE MODE FIRST: cluster.smoke=true -> 1 matrix, 100 perms, 20 bootstraps.
Confirm outputs, then launch the full run.

HANDOFF: report at <output_dir>/analysis_v2/REPORT_C.md: best matrix per attribute,
cluster-vs-label verdict per the decision table (stages 2, 3, 8), stability verdict,
retrieval vs chance, assumptions. Include a "next steps" section listing what is
deliberately NOT in this battery (temporal / genealogy — conditional on B's confound
verdict; attention rollout + perturbation study — needs patch tokens; CKA
DINOv2-vs-SigLIP — needs aligned SigLIP matrices; patent-level aggregation study —
depends on multi-image consistency test) and which of them REPORT_B's findings
justify prioritizing next. """


# ─────────────────────────────────────────────────────────────────────────────
# CORE EXECUTION UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(msg)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def disable_sleep_and_lock():
    """Best-effort prevention of screensaver locks to safeguard window focus."""
    try:
        subprocess.run(["xset", "s", "off"], check=False)
        subprocess.run(["xset", "-dpms"], check=False)
        subprocess.run(["xset", "s", "noblank"], check=False)
        log("Disabled X11 screensaver/DPMS parameters.")
    except FileNotFoundError:
        log("WARNING: xset executable missing — could not adjust screensaver settings.")


def preflight():
    """Validates baseline OS interface environments and configuration flags."""
    problems = []
    if not os.environ.get("DISPLAY"):
        problems.append("DISPLAY environment variable unset — pyautogui GUI actions missing.")
    if os.environ.get("WAYLAND_DISPLAY"):
        problems.append("Wayland display server detected — standard hotkeys may fail. Switch to X11.")
    try:
        token = f"__timer_selftest_{int(time.time())}__"
        pyperclip.copy(token)
        time.sleep(0.2)
        if pyperclip.paste() != token:
            problems.append("Clipboard interface mismatch — verify xclip or xsel configurations.")
    except Exception as e:
        problems.append(f"Clipboard operational breakdown: {e}")
        
    # Check for placeholder edits inside user variables
    if "<<EDIT-ME" in _REPO:
        problems.append(f"_REPO path includes unmodified placeholder tag: {_REPO}")
    if "<<EDIT-ME" in _LABELS_EXPORT_GLOB:
        problems.append(f"_LABELS_EXPORT_GLOB path includes unmodified placeholder tag: {_LABELS_EXPORT_GLOB}")
    if "<<EDIT-ME" in _META_PATH:
        problems.append(f"_META_PATH path includes unmodified placeholder tag: {_META_PATH}")
        
    return problems


def _next_occurrence(hhmm: str) -> datetime.datetime:
    """Computes the next logical occurrence of an arbitrary 24h timestamp."""
    now = datetime.datetime.now()
    hh, mm = [int(x) for x in hhmm.split(":")]
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


def send_prompt(label: str, text: str):
    log(f"Transmitting prompt sequence: {label}...")
    pyperclip.copy(text)
    time.sleep(0.5)                     
    pyautogui.hotkey("ctrl", "v")       
    time.sleep(0.8)                     
    pyautogui.press("enter")            
    log(f"{label} transmission pipeline executed successfully ({len(text)} characters compiled).")


def wait_until(target_dt: datetime.datetime, label: str):
    """Execution block loop that holds thread processing until target datetime bounds meet."""
    log(f"Holding pipeline for {label}. Fire scheduled at {target_dt.strftime('%Y-%m-%d %H:%M')} "
        f"({(target_dt - datetime.datetime.now()).total_seconds()/60:.1f} minutes remaining)...")
    while datetime.datetime.now() < target_dt:
        remaining = (target_dt - datetime.datetime.now()).total_seconds()
        time.sleep(min(15, max(1, remaining)))


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    log("=" * 70)
    log("  Unified Master Analysis Battery — Automation Pipeline")
    log("=" * 70)

    # 1. Resolve day-roll constraints internal to separate suites
    dt_a = _next_occurrence(TARGET_TIME_A)
    dt_b = _next_occurrence(TARGET_TIME_B)
    if dt_b <= dt_a:
        dt_b += datetime.timedelta(days=1)
    dt_c = _next_occurrence(TARGET_TIME_C)
    if dt_c <= dt_b:
        dt_c += datetime.timedelta(days=1)

    dt_d = _next_occurrence(TARGET_TIME_D)
    dt_e = _next_occurrence(TARGET_TIME_E)
    if dt_e <= dt_d:
        dt_e += datetime.timedelta(days=1)
    dt_f = _next_occurrence(TARGET_TIME_F)
    if dt_f <= dt_e:
        dt_f += datetime.timedelta(days=1)

    # 2. Consolidate and sort across the global timeline
    master_timeline = [
        (dt_a, "Prompt A (Taxonomy Design)", PROMPT_A),
        (dt_b, "Prompt B (Adversarial Review)", PROMPT_B),
        (dt_c, "Prompt C (Stress-Testing)", PROMPT_C),
        (dt_d, "Prompt D (Labels Layer Process)", PROMPT_D),
        (dt_e, "Prompt E (Probe Battery Matrix)", PROMPT_E),
        (dt_f, "Prompt F (Cluster/Retrieval Evaluation)", PROMPT_F),
    ]
    master_timeline.sort(key=lambda item: item[0])

    # Print planned sequence for confirmation
    for idx, (target_time, label, _) in enumerate(master_timeline, start=1):
        log(f"  [{idx}] Scheduled: {target_time.strftime('%Y-%m-%d %H:%M')} ➔ {label}")
    log("=" * 70)

    # Preflight evaluations
    problems = preflight()
    if problems:
        log("PRE-FLIGHT CHECKS FAILURE — Automation execution terminated:")
        for p in problems:
            log("    - " + p)
        raise SystemExit(1)
    log("Pre-flight state verified: X11 interface ready, path configurations parsed.")

    disable_sleep_and_lock()

    log("")
    log("ATTENTION: Focus target VSCode interface chat frame input window now.")
    log("           Ensure interface cursor is actively pulsing. Leave input setup clear.")
    log("")

    # 3. Global execution run loop
    for target_time, label, prompt_payload in master_timeline:
        wait_until(target_time, label)
        send_prompt(label, prompt_payload)

    log("Global overnight analysis matrix execution completed successfully.")