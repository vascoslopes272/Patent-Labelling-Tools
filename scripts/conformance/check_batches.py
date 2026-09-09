#!/usr/bin/env python3
"""Codebook conformance harness — do the labelled batches still agree with the wizard?

The wizard HTML is the source of truth for the taxonomy (see the ML<->HTML sync
note in the repo). Batches were labelled over months against successive wizard
builds, so an export can disagree with today's codebook in five distinct ways.
This script names all five, per batch, and writes a per-patent worklist so a
finding can actually be acted on.

  C1  invalid option    a Value whose id is in NO current option list
  C2  retired option    an id kept in the array only to render legacy saves
                        (derived automatically: ids(X) - X_CHOICES)
  C2b unguarded list    a list with retired ids but no *_CHOICES guard, so the
                        retired option is STILL PICKABLE today
  C3  retired field     a Field the wizard no longer renders or re-exports
  C4  required gap      a field the wizard now makes mandatory that is absent
                        on rows where its precondition holds
  C5  convention drift  a valid field whose ANSWER DISTRIBUTION differs sharply
                        between batches — same option list, different habit
  C6  META coverage     approved patents missing codebook_version / timestamp

Usage:
    python scripts/conformance/check_batches.py                     # all batches
    python scripts/conformance/check_batches.py --batches Batch_01 Batch_05
    python scripts/conformance/check_batches.py --out report/       # + CSV worklists
"""
from __future__ import annotations
import argparse, collections, difflib, itertools, json, re, subprocess, sys, tempfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DEFAULT_HTML = REPO / "notebooks" / "UI_for_taxonomy_caracterization_15_4.html"
DEFAULT_DIR = Path(
    "/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs"
    "/1639_DS/data/03c_CORRECTED_wizard_exports"
)
DEFAULT_BATCHES = ["Batch_01", "Batch_02", "Batch_03", "Batch_04", "Batch_05"]

# ── how an exported Field maps onto a wizard option list ────────────────────
# Keyed by (Section, field suffix) because the same suffix means different
# things in different sections: M1 `orient` is the boom axis (BOOM_ORIENT),
# M3 `orient` is the thrust axis (a list built at render time, not a var).
FIELD_LIST = {
    ("G1", "topType"): "TOP",
    ("M2", "wingConf"): "WING_CONFIG",
    ("M2", "posV"): "W_POS_V", ("M2", "posL"): "W_POS_L",
    ("M2", "plan"): "W_PLAN", ("M2", "role"): "W_ROLE",
    ("M2", "tilt"): "W_TILT", ("M2", "empType"): "EMP_TYPE",
    ("M3", "chord"): "CHORD", ("M3", "bmech"): "BLADE_MECH",
    ("M3", "rmech"): "RETRACT_MECH", ("M3", "propKin"): "PROP_KIN",
    ("M1", "attach"): "BOOM_ATTACH", ("M1", "long"): "BOOM_POS_LONG",
    ("M1", "span"): "BOOM_POS_SPAN", ("M1", "wingRel"): "BOOM_WING_REL",
    ("M1", "orient"): "BOOM_ORIENT", ("M1", "fusShape"): "FUS_SHAPE",
    ("M1", "fusKin"): "FUS_KIN", ("M1", "gearArch"): "GEAR_ARCH",
    ("M1", "dinoUnderstanding"): "DINO_UNDERSTANDING",
    ("T2", "per"): "T2_PER", ("T2", "acSty"): "T2_AC_STY",
    ("T2", "acCol"): "T2_AC_COL", ("T2", "bgSty"): "T2_BG_STY",
    ("T2", "bgCol"): "T2_BG_COL", ("T2", "acState"): "AC_STATE",
    ("T2", "qualityFlag"): "QUALITY_FLAGS",
    ("META", "duplicateType"): "DUP_TYPES",
    ("T1", "t1DisapproveReason"): "T1_DISAPPROVE_REASONS",
}
# Values that are legitimate but are not ids in the list (render-time defaults).
EXTRA_OK = {("M2", "role"): {"Main"}}
# The HTML does not name its guards uniformly: T1_DISAPPROVE_REASONS is guarded
# by T1_DISAPPROVE_CHOICES, not T1_DISAPPROVE_REASONS_CHOICES. Without this alias
# the "<LIST>_CHOICES" lookup misses and the list reads as having no retirements
# at all — which is how 6 legacy 'Unreadable' rows in Batch_02 went unreported.
# extract_html_schema.js flags any guard that binds to nothing, so a future
# mismatch shows up as a warning instead of a silent gap.
GUARD_ALIAS = {"T1_DISAPPROVE_REASONS": "T1_DISAPPROVE_CHOICES"}
# Lists whose retirement is documented in a code COMMENT but not enforced by a
# *_CHOICES guard, so the retired ids stay pickable. Kept here rather than
# derived, because only a human reading the comment knows they are retired.
# T2_AC_STY was here until 2026-09-02; it now has a real T2_AC_STY_CHOICES guard,
# so C2 derives its retirement on its own and C2b stops flagging it. AC_STATE is
# the last list whose retirement lives only in a comment.
# v15.7 (2026-09-05) declared AC_STATE_CHOICES, so C2 now DERIVES the acState
# retirement on its own and the hardcoded entry would double-report it. GEAR_ARCH
# gained GEAR_ARCH_CHOICES the same day. Nothing is left in this dict — keep it,
# because the next comment-only retirement will need it again.
UNGUARDED_RETIRED: dict[str, set[str]] = {}
# Fields the wizard stopped rendering. It still PARSES them so an old save loads
# (see the retirement notes in the HTML), so they survive a load/save round trip.
DEAD_FIELDS = {
    r"boom\d+_wingSpan": "BOOM_WING_SPAN retired 2026-08-06",
    r"imgApparentArch": "APPARENT_ARCH retired v15.3",
    r"tiltedInView": "TILTED_IN_VIEW retired v14 (C1)",
    r"boom\d+_format": "boomXFormat retired v14 (C5)",
    r"empTiltsNote": "mandatory tilt-mechanism note retired v15.5 (empTilts itself stays)",
    # v15.6 (2026-09-05): dropped from the M3 cards AND from the export. Ticked 4
    # and 6 times in 2,532 each, all in Batch_05, and fed no rule. NOTE the M1 boom
    # group's own boomN_circSym is a DIFFERENT field and is NOT retired, so these
    # patterns are anchored to the M3 card keys only.
    r"(fuselage|emp|boom|core_layout|hull_array|wing\d)(_t\d)?_symLong":
        "M3 card longitudinal symmetry retired v15.6",
    r"(fuselage|emp|boom|core_layout|hull_array|wing\d)(_t\d)?_symCirc":
        "M3 card circular symmetry retired v15.6",
}
# C4 — (label, precondition field regex, precondition ids, required field regex)
# grouped per boom index so a per-group requirement is checked per group.
REQUIRED = [("boom wingRel (mandatory since 2026-08-07 when boom attaches to a wing)",
             r"boom(\d+)_attach", {"Wings", "Both"}, r"boom(\d+)_wingRel"),
            # v17 DEC-1 (2026-09-08): boomNeedsLong(g) is attach !== 'Wings'. A group
            # on BOTH wing and fuselage is fuselage-referenced for LONGITUDINAL, so
            # it must carry long — the mirror of the FORBIDDEN rule below.
            ("boom long (v17: required on every group except a pure Wings attachment)",
             r"boom(\d+)_attach", {"Fuselage", "Both", "Other"}, r"boom(\d+)_long"),
            # v15.6 (2026-09-05): spanwise is measured along the WING, so it is now
            # rendered, required and exported only for a wing-referenced group —
            # the exact mirror of what v15.5 did to boomN_long.
            ("boom span (v15.6: wing-referenced only, and required there)",
             r"boom(\d+)_attach", {"Wings", "Both"}, r"boom(\d+)_span")]
# The mirror of REQUIRED: a field that must be ABSENT where the precondition holds.
# v15.5 made boomN_long fuselage-only, so a value surviving on a wing-attached
# group means the migration has not been run on that batch.
# v17 DEC-1 narrowed this from {Wings, Both} to Wings only: on 2026-09-08 all 12
# "stray" values the old rule reported sat on Both groups, where long is now
# REQUIRED. The check was stale, the data was right.
FORBIDDEN = [("boom long must be blank on a pure Wings-attached group (v17: Both keeps it)",
              r"boom(\d+)_attach", {"Wings"}, r"boom(\d+)_long")]
# The other direction: a field that must be absent where the precondition does NOT
# hold. v15.6 stopped exporting boomN_span for a non-wing-attached group.
FORBIDDEN_UNLESS = [("boom span must be blank on a non-wing-attached group (v15.6)",
                     r"boom(\d+)_attach", {"Wings", "Both"}, r"boom(\d+)_span")]
# C5 — fields whose divergence is expected and uninformative. t1Field/t1Target/
# scope are unreviewed SBERT pre-labels that 02a strips at export, so drift in
# them measures the model, not the labeller.
DRIFT_IGNORE = {"T1.t1Field", "T1.t1Target", "T1.scope", "T1.labelToken"}


# ══ Phase 3 (C7-C10) ═══════════════════════════════════════════════════════
# C1-C6 only ever looked at the 27 fields listed in FIELD_LIST. Phase 3 asks the
# wider question the master sheet needs answered: is EVERY Field/Value in the
# five files still something the wizard would write today?
#
#   C7  mirror coverage  every (Section, field) an export carries, classified as
#                        validated / structurally non-coded / VALIDATED BY
#                        NOTHING. The seven newly-mappable lists are checked here
#                        rather than in FIELD_LIST, so the C1/C2 numbers stay
#                        comparable with every earlier report.
#   C8  free-text leak   prose sitting where a coded id belongs, plus the
#                        "Other + sibling note" escape hatch that hides the same
#                        problem in a place C1 cannot see.
#   C9  dead columns     fields the wizard's export declares that no file
#                        carries, fields present but always empty or constant,
#                        and option ids no record ever picked.
#   C10 label drift      the "id - Label" composite's label half vs the label
#                        the wizard renders today. Phase 0 renamed eight of them
#                        on 2026-09-08, so every file predating that is stale.
#
# FIELD_LIST_EXTRA is deliberately separate from FIELD_LIST: these seven fields
# were validated against NOTHING until now (four of them because their option
# lists are built by render-time FUNCTIONS below the taxonomy block, which the
# schema extractor could not see until it learned to pull them out by name).
FIELD_LIST_EXTRA = {
    ("G1", "edgeTags"): "T1_EDGE_TAGS",
    ("M1", "wingIdx"): "BOOM_WING_IDX",
    ("M3", "orient"): "M3_ORIENT",
    ("M3", "zone"): "M3_ZONE",
    ("M3", "zoneChord"): "M3_ZONE_CHORD",
    ("M3", "zoneSpan"): "M3_ZONE_SPAN",
    ("T2", "parts"): "T2_PARTS_DEFAULT",
}
# Fields the wizard writes as a "|"-joined array (buildExport: parts, edgeTags,
# zone). Splitting is mandatory or every multi-pick reads as one unknown id.
MULTI_VALUE = {("M3", "zone"), ("G1", "edgeTags"), ("T2", "parts")}
# Fields that carry no coded vocabulary and never should. Anything NOT here, not
# in a FIELD_LIST, and not inferable as a boolean/count is reported by C7 as an
# unvalidated coded field — which is the finding, not the noise.
NONCODED = {
    ("T1", "abstract"): "patent bibliographic text",
    ("T1", "title"): "patent bibliographic text",
    ("T1", "assignee"): "patent bibliographic text",
    ("T1", "description_of_drawings"): "patent bibliographic text",
    ("T1", "pdf_link"): "PatSeer URL",
    ("T1", "aircraftName"): "free-text aircraft identity (03a ground truth)",
    ("T1", "duplicateId"): "patent id",
    ("META", "labelToken"): "SBERT pre-label token, stripped at 02a export",
    ("META", "timestamp"): "save stamp",
    ("META", "codebook_version"): "schema stamp (C6)",
    ("META", "familyId"): "hardcoded placeholder, identical on every record",
    ("META", "mainFigure"): "figure id",
    ("T2", "figKey"): "figure id",
    ("T2", "dupOf"): "'<patent> FIG. <n>' reference",
    ("T2", "edgeTags"): "free-form per-figure tag registry (EDGE_TOKENS), NOT "
                        "the coded G1 edgeTags of the same name",
    ("M1", "cards"): "structural marker ('boom'), not an answer",
}
FREE_TEXT_RE = re.compile(r"(notes?|oth|other|othernote|comment|comments)$", re.I)
# Coded fields whose vocabulary is real but lives in JS code instead of an option
# array, so no guard can ever retire a value in them. Reported, with the reason.
HARDCODED_VOCAB = {
    ("T2", "status"): "'approved'/'disapproved' written as string literals in buildExport",
    ("T1", "scope"): "unreviewed SBERT pre-label (02a strips it at export)",
    ("T1", "t1Field"): "unreviewed SBERT pre-label (02a strips it at export)",
    ("T1", "t1Target"): "unreviewed SBERT pre-label (02a strips it at export)",
}
# C8 - a coded field's sibling free-text field, by naming convention. The wizard
# keeps the option id ('Oth'/'Other') in the coded field and rides the prose in
# the sibling, so the categorical column stays clean and the information the
# reviewer actually typed becomes invisible to every downstream consumer.
# C10 - fields the export writes as a BARE id on purpose: M3 orient is passed no
# option list (the comment in buildReviewRows says Horizontal/Vertical/Mixed are
# already plain English), and G1 edgeTags is "|"-joined straight from the array
# without withLabel(). Every other mapped field goes through withLabel(), so a
# bare id there means the row was written by something other than the wizard.
UNLABELLED_BY_DESIGN = {("M3", "orient"), ("G1", "edgeTags")}
OTHER_IDS = {"Oth", "Other", "OTHER"}
SIBLING_SUFFIXES = ("Oth", "_otherNote", "OtherNote")


def label_of(v: object) -> str | None:
    """The 'Label' half of an 'id - Label' composite, or None if unlabelled.

    maxsplit=1 matters: several labels contain the separator themselves
    ('TW - Vectored Thrust - Tilt Wing', 'FusFront - Fuselage - Front (body)').
    """
    s = str(v)
    return s.split(" — ", 1)[1].strip() if " — " in s else None


def split_multi(v: object, multi: bool) -> list[str]:
    s = str(v).strip()
    if s in ("", "nan", "None", "NaT"):
        return []
    return [p for p in (s.split("|") if multi else [s]) if p.strip()]


def declared_fields(html: Path) -> dict[str, set[str]]:
    """(Section -> field suffixes) the wizard's export function actually writes.

    Parsed out of buildReviewRows' reviewRow() calls: the 4th argument is either
    a literal field name or a loop variable, in which case the nearest preceding
    ["a","b",...].forEach list holds the names. Composed names
    (card.component + "_" + field) resolve to their suffix, which is exactly the
    granularity suffix() reduces the files to. Used by C9 to find fields the
    wizard emits that no file has ever carried.
    """
    s = html.read_text(encoding="utf-8", errors="replace")
    call = re.compile(r'reviewRow\(\s*\w+\s*,\s*"(G1|M1|M2|M3|T1|T2|META)"\s*,'
                      r'\s*(?:[^,]|\([^()]*\))*?,\s*([^,]+?)\s*,', re.S)
    # Two loop shapes emit rows: a flat ["a","b"].forEach, and M2's
    # [["plan","Planform",W_PLAN], ...].forEach where only the FIRST element of
    # each inner array is the field name. Reading the flat shape only made the
    # five M2 wing fields look undeclared.
    arr = re.compile(r'\[(?P<body>[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]\s*\.forEach', re.S)
    out: dict[str, set[str]] = {}
    for m in call.finditer(s):
        sec, arg = m.group(1), m.group(2).strip()
        lit = re.fullmatch(r'"([A-Za-z0-9_]+)"', arg)
        if lit:
            out.setdefault(sec, set()).add(suffix(lit.group(1)))
            continue
        # A composed name is BOTH: "wing" + wi + "_" + field takes its name from
        # the enclosing forEach list, while "wing" + wi + "_tipJoin" carries it as
        # a literal in the argument itself — and the two sit inside the same loop.
        # Reading only the forEach list made tipJoin and plan_otherNote look
        # retired when the wizard writes them on every save.
        names = re.findall(r'"_?([A-Za-z0-9_]+)"', arg)
        back = arr.findall(s[max(0, m.start() - 900):m.start()])
        if back:
            body = back[-1]
            names += [n for grp in ([re.findall(r'"([A-Za-z0-9_]+)"', inner)[:1]
                                     for inner in re.findall(r'\[([^\[\]]*)\]', body)]
                                    if body.lstrip().startswith("[")
                                    else [re.findall(r'"([A-Za-z0-9_]+)"', body)])
                      for n in grp]
        for n in names:
            out.setdefault(sec, set()).add(suffix(n))
    # Prefix fragments from composed names ("wing" + wi + "_" + field) are not
    # fields; drop them rather than report a phantom missing column.
    for sec in out:
        out[sec] -= {"", "_", "t", "boom", "wing", "wings", "emp", "fuselage"}
    return out


def code(v: object) -> str:
    """Exported Values are 'ID — Human Label' composites; keep the id."""
    return str(v).split(" — ")[0].strip()


def suffix(field: str) -> str:
    """Strip the group prefixes so wing2_posL and 3_wing1_posL both read posL."""
    f = re.sub(r"^\d+_", "", str(field))
    f = re.sub(r"^(boom|wing|hull_array|core_layout|emp|fuselage)\d*_", "", f)
    return re.sub(r"^t\d+_", "", f)


def load_schema(html: Path) -> dict:
    js = Path(__file__).with_name("extract_html_schema.js")
    out = Path(tempfile.mkstemp(suffix=".json")[1])
    r = subprocess.run(["node", str(js), str(html), str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"schema extraction failed ({html}):\n{r.stderr}")
    print(f"  schema: {html.name} — {r.stderr.strip()}", file=sys.stderr)
    schema = json.loads(out.read_text())
    stray = [g for g in schema.get("unbound_guards", []) if g not in GUARD_ALIAS.values()]
    if stray:
        print(f"  !! guard(s) bound to no option list: {stray} — add a GUARD_ALIAS "
              f"entry or their retirements will not be checked", file=sys.stderr)
    return schema


def load_batches(d: Path, names: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for b in names:
        hits = sorted(d.glob(f"reviewed_patents_{b}*.xlsx"))
        hits = [h for h in hits if re.fullmatch(rf"reviewed_patents_{b} ?\.xlsx", h.name)]
        if not hits:
            print(f"  !! no export for {b} in {d}", file=sys.stderr)
            continue
        df = pd.read_excel(hits[0], sheet_name="Review")
        df["_sfx"] = df["Field"].map(suffix)
        df["_code"] = df["Value"].map(code)
        out[b] = df
        print(f"  {b}: {len(df):>6} rows, {df.Patent_ID.nunique():>4} patents"
              f"  <- {hits[0].name}", file=sys.stderr)
    return out


def retired_ids(schema: dict) -> dict[str, set]:
    """ids(X) - X_CHOICES for every guarded list, plus the comment-only ones."""
    out = {}
    for lst, all_ids in schema["lists"].items():
        guard = schema["choices"].get(GUARD_ALIAS.get(lst, f"{lst}_CHOICES"))
        if guard is not None:
            gone = set(all_ids) - set(guard)
            if gone:
                out[lst] = gone
    for lst, gone in UNGUARDED_RETIRED.items():
        out.setdefault(lst, set()).update(gone)
    return out


def run_c7_c10(schema, batches, hit, html: Path):
    """C7-C10: the full Field/Value mirror the master sheet (stage 04) needs.

    Report only - nothing here writes to a batch file.
    """
    lists = {k: set(v) for k, v in schema["lists"].items()}
    labels = schema.get("labels", {})
    retired = retired_ids(schema)
    B = list(batches)
    span = lambda c: " ".join(f"{b.replace('Batch_', 'B')}={c.get(b, 0):<5}" for b in B)
    head = lambda t: print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")
    MAPPED = {**FIELD_LIST, **FIELD_LIST_EXTRA}

    def nonempty(g):
        v = g.Value.astype(str).str.strip()
        return g[~v.isin(("", "nan", "None", "NaT"))]

    # per-(section, suffix) census over all five files at once
    keys: dict[tuple, dict] = {}
    for b, df in batches.items():
        for (sec, sfx), g in df.groupby([df.Section.astype(str), df._sfx]):
            e = keys.setdefault((sec, sfx), dict(rows={}, ne={}, vals=collections.Counter()))
            ne = nonempty(g)
            e["rows"][b], e["ne"][b] = len(g), len(ne)
            e["vals"].update(ne.Value.astype(str))

    # ── C7 ─────────────────────────────────────────────────────────────────
    head("C7  mirror coverage - is every exported field validated against the wizard?")
    buckets = collections.defaultdict(list)
    for (sec, sfx), e in sorted(keys.items()):
        codes = {code(v) for v in e["vals"]}
        key = (sec, sfx)
        if key in FIELD_LIST:
            buckets["validated by C1/C2"].append((key, FIELD_LIST[key], e))
        elif key in FIELD_LIST_EXTRA:
            buckets["validated by C7 (new)"].append((key, FIELD_LIST_EXTRA[key], e))
        elif key in NONCODED:
            buckets["not coded (by design)"].append((key, NONCODED[key], e))
        elif FREE_TEXT_RE.search(sfx):
            buckets["not coded (by design)"].append((key, "free text (sibling note / comment)", e))
        elif codes <= {"True", "False"}:
            buckets["not coded (by design)"].append((key, "boolean", e))
        elif all(re.fullmatch(r"-?\d+(?:\.\d+)?|True|False", c) for c in codes):
            buckets["not coded (by design)"].append((key, "count / numeric", e))
        elif key in HARDCODED_VOCAB:
            buckets["CODED BUT UNVALIDATED"].append((key, HARDCODED_VOCAB[key], e))
        else:
            buckets["CODED BUT UNVALIDATED"].append(
                (key, f"{len(codes)} distinct values, no option array", e))
    for name in ("validated by C1/C2", "validated by C7 (new)",
                 "CODED BUT UNVALIDATED", "not coded (by design)"):
        items = buckets[name]
        print(f"\n  {name}: {len(items)} fields")
        if name == "not coded (by design)":
            print("      " + ", ".join(f"{s}.{f}" for (s, f), _, _ in items))
            continue
        for (sec, sfx), why, e in items:
            tot = sum(e["ne"].values())
            print(f"      {sec + '.' + sfx:<28} {why:<46} {tot:>6} values")
            if name == "CODED BUT UNVALIDATED":
                sample = ", ".join(f"{code(v)}({n})" for v, n in e["vals"].most_common(5))
                print(f"          {sample[:150]}")
                # No per-patent rows: these four fields are unvalidated on EVERY
                # record, so a worklist entry per patent would be 4,000 rows of
                # the same schema fact and would bury the actionable findings.

    # the seven newly-mapped fields, validated exactly the way C1/C2 do it
    print("\n  C7 findings on the newly-mapped fields (unknown / retired ids):")
    agg = collections.defaultdict(collections.Counter)
    for b, df in batches.items():
        for (sec, sfx), lst in FIELD_LIST_EXTRA.items():
            sub = df[(df.Section == sec) & (df._sfx == sfx)]
            multi = (sec, sfx) in MULTI_VALUE
            for _, r in nonempty(sub).iterrows():
                for part in split_multi(r.Value, multi):
                    v = code(part)
                    kind = ("C7 invalid" if v not in lists[lst] else
                            "C7 retired" if v in retired.get(lst, set()) else None)
                    if kind:
                        agg[(kind, f"{sec}.{sfx}", lst, v)][b] += 1
                        hit(kind, b, patent=r.Patent_ID, field=f"{sec}.{sfx}",
                            value=v, detail=lst)
    if not agg:
        print("      clean - every id in the seven fields is a current option")
    for (kind, fld, lst, v), c in sorted(agg.items(), key=lambda x: -sum(x[1].values())):
        print(f"      {kind}  {fld:<20} {lst:<20} {v!r:<28} {span(c)}")

    # ── C8 ─────────────────────────────────────────────────────────────────
    head("C8  free text where a coded id belongs")
    print("\n  C8a  prose stored IN a categorical field (a value with no id at all)")
    found = False
    for b, df in batches.items():
        for (sec, sfx), lst in MAPPED.items():
            sub = nonempty(df[(df.Section == sec) & (df._sfx == sfx)])
            multi = (sec, sfx) in MULTI_VALUE
            ok = lists[lst] | EXTRA_OK.get((sec, sfx), set())
            for _, r in sub.iterrows():
                for part in split_multi(r.Value, multi):
                    v = code(part)
                    if v in ok:
                        continue
                    if " " in v or len(v) > 24:      # prose, not a mistyped id
                        found = True
                        print(f"      {b} {r.Patent_ID:<24} {sec}.{sfx:<14} {v[:70]!r}")
                        hit("C8 prose in categorical", b, patent=r.Patent_ID,
                            field=f"{sec}.{sfx}", value=v[:80], detail=lst)
    if not found:
        print("      clean - no categorical field holds prose "
              "(the leaks are all in the sibling notes below)")

    print("\n  C8b  the 'Other' escape hatch - coded field says Other, the answer "
          "is in a free-text sibling")
    print("      picked = records answering Other | noted = of those, with text | "
          "orphan = text but not Other")
    for (sec, sfx), lst in sorted(MAPPED.items()):
        if not (OTHER_IDS & lists[lst]):
            continue
        sibs = [s for s in (sfx + x for x in SIBLING_SUFFIXES) if (sec, s) in keys]
        if not sibs:
            continue
        picked, noted, orphan = {}, {}, {}
        texts: collections.Counter = collections.Counter()
        for b, df in batches.items():
            cod = nonempty(df[(df.Section == sec) & (df._sfx == sfx)])
            sib = nonempty(df[(df.Section == sec) & (df._sfx.isin(sibs))])
            # pair on (patent, group prefix) so boom1_wingRel meets boom1_wingRelOth
            gp = lambda s: str(s).rsplit("_", 1)[0] if "_" in str(s) else ""
            oth = {(p, gp(f)) for p, f, v in zip(cod.Patent_ID, cod.Field, cod._code)
                   if v in OTHER_IDS}
            # a sibling's group key is its own name with the coded suffix and the
            # note suffix stripped: boom1_wingRelOth -> boom1, wing2_plan_otherNote
            # -> wing2, so it pairs with the coded row from the same group.
            have = {(p, g) for p, g in zip(sib.Patent_ID, sib.Field.map(
                lambda f: re.sub(r"_?" + re.escape(sfx) + r"(Oth|_?[oO]therNote)$", "", str(f))))}
            picked[b], noted[b] = len(oth), len(oth & have)
            orphan[b] = len(have - oth)
            for _, r in sib.iterrows():
                t = str(r.Value).strip()
                texts[t] += 1
                hit("C8 other-escape", b, patent=r.Patent_ID, field=f"{sec}.{sfx}",
                    value=t[:80], detail=f"free text behind {lst} 'Other'")
        print(f"\n      {sec}.{sfx}  ({lst}, sibling {'/'.join(sibs)})")
        print(f"          picked Other: {span(picked)}")
        print(f"          with note:    {span(noted)}")
        print(f"          orphan notes: {span(orphan)}")
        for t, n in texts.most_common(40):
            lo = t.lower().strip()
            coded = [i for i, l in labels.get(lst, {}).items()
                     if lo == i.lower() or lo == str(l).lower()]
            tag = f"   <- already an option: {coded[0]}" if coded else ""
            print(f"          {n:>3}x {t[:88]!r}{tag}")
        # Near-duplicates: one concept typed several ways is a MISSING OPTION,
        # not a note. Fuzzy, not exact — the corpus writes the same answer as
        # "bridges two wings plus the fuselage", "bridges 2 wings plus the
        # fuselage" and "bridges two wings plus teh fuselage", which an exact
        # normalisation counts as three different answers.
        clusters: list[list[str]] = []
        for t in sorted(texts):
            k = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", t.lower())).strip()
            for cl in clusters:
                if difflib.SequenceMatcher(None, k, cl[0]).ratio() >= 0.82:
                    cl.append(t)
                    break
            else:
                clusters.append([k, t])
        for cl in sorted(clusters, key=lambda c: -len(c)):
            if len(cl) > 2:
                n = sum(texts[t] for t in cl[1:])
                print(f"          !! {n} records, {len(cl) - 1} spellings of ONE "
                      f"answer this list cannot express: {sorted(cl[1:])}")

    # ── C9 ─────────────────────────────────────────────────────────────────
    head("C9  dead columns - declared but never written, always empty, constant")
    decl = declared_fields(html)
    present = {sec: {f for (s, f) in keys if s == sec} for sec in decl}
    print("\n  C9a  the wizard's export writes these, no file carries them")
    for sec in sorted(decl):
        gone = sorted(decl[sec] - present.get(sec, set()))
        if gone:
            print(f"      {sec:<6} {', '.join(gone)}")
    print("\n  C9b  present in a file but the export no longer writes them "
          "(survive a load/save round trip)")
    for sec in sorted(present):
        extra = sorted(f for f in present[sec] - decl.get(sec, set()))
        if extra:
            print(f"      {sec:<6} {', '.join(extra)}")
    print("\n  C9c  fields with NO non-empty value in a batch (empty column there)")
    for (sec, sfx), e in sorted(keys.items()):
        empty = [b for b in B if e["rows"].get(b, 0) and not e["ne"].get(b, 0)]
        if empty:
            print(f"      {sec + '.' + sfx:<28} empty in {', '.join(empty)}"
                  f"   (rows: {span(e['rows'])})")
            for b in empty:
                hit("C9 empty column", b, patent="", field=f"{sec}.{sfx}", value="",
                    detail="field emitted, no non-empty value in this batch")
    print("\n  C9d  constant fields - one distinct value corpus-wide (no information)")
    for (sec, sfx), e in sorted(keys.items()):
        vals = {code(v) for v in e["vals"]}
        if len(vals) == 1 and sum(e["ne"].values()) > 1:
            print(f"      {sec + '.' + sfx:<28} always {vals.pop()!r:<28} "
                  f"{sum(e['ne'].values()):>5} rows")
    print("\n  C9e  mostly-empty fields (>=90% of emitted rows blank)")
    for (sec, sfx), e in sorted(keys.items()):
        rows, ne = sum(e["rows"].values()), sum(e["ne"].values())
        if rows >= 100 and ne / rows <= 0.10:
            print(f"      {sec + '.' + sfx:<28} {ne:>5}/{rows:<6} non-empty "
                  f"({ne / rows * 100:4.1f}%)")
    print("\n  C9f  option ids the wizard offers that NO record ever picked")
    for (sec, sfx), lst in sorted(MAPPED.items()):
        used = set()
        for b, df in batches.items():
            sub = nonempty(df[(df.Section == sec) & (df._sfx == sfx)])
            for v in sub.Value:
                used |= {code(p) for p in split_multi(v, (sec, sfx) in MULTI_VALUE)}
        unused = sorted(lists[lst] - used - retired.get(lst, set()))
        if unused:
            print(f"      {sec + '.' + sfx:<28} {lst:<22} never picked: {unused}")

    # ── C10 ────────────────────────────────────────────────────────────────
    head("C10  label drift - the stored 'id - Label' vs the label the wizard renders now")
    drift = collections.defaultdict(collections.Counter)
    bare = collections.defaultdict(collections.Counter)
    for b, df in batches.items():
        for (sec, sfx), lst in MAPPED.items():
            lab = labels.get(lst) or {}
            if not lab or (sec, sfx) in UNLABELLED_BY_DESIGN:
                continue        # plain string list, or written bare on purpose
            sub = nonempty(df[(df.Section == sec) & (df._sfx == sfx)])
            multi = (sec, sfx) in MULTI_VALUE
            for _, r in sub.iterrows():
                for part in split_multi(r.Value, multi):
                    v, stored = code(part), label_of(part)
                    if v not in lab:
                        continue               # C1/C7 owns unknown ids
                    if stored is None:
                        bare[(f"{sec}.{sfx}", v)][b] += 1
                        hit("C10 bare id", b, patent=r.Patent_ID, field=f"{sec}.{sfx}",
                            value=v, detail=f"stored without ' — {lab[v]}'")
                    elif stored != lab[v]:
                        drift[(f"{sec}.{sfx}", v, stored, lab[v])][b] += 1
                        hit("C10 label drift", b, patent=r.Patent_ID,
                            field=f"{sec}.{sfx}", value=v,
                            detail=f"{stored!r} -> {lab[v]!r}")
    print("\n  C10a  stale display label frozen into the file")
    if not drift:
        print("      clean")
    for (fld, v, stored, now), c in sorted(drift.items(), key=lambda x: -sum(x[1].values())):
        print(f"      {fld:<20} {v:<14} {span(c)}")
        print(f"          file: {stored!r}")
        print(f"          now : {now!r}")
    print("\n  C10b  id stored with NO label, where the wizard writes a composite")
    if not bare:
        print("      clean")
    for (fld, v), c in sorted(bare.items(), key=lambda x: -sum(x[1].values())):
        print(f"      {fld:<20} {v!r:<20} {span(c)}")


def run(schema, batches, out_dir: Path | None, html: Path | None = None):
    lists = {k: set(v) for k, v in schema["lists"].items()}
    retired = retired_ids(schema)
    inv = {v: k for k, v in GUARD_ALIAS.items()}
    guarded = {inv.get(n, n[: -len("_CHOICES")]) for n in schema["choices"]}
    rows: list[dict] = []            # per-patent worklist
    def hit(check, batch, **kw): rows.append(dict(check=check, batch=batch, **kw))

    B = list(batches)
    span = lambda c: " ".join(f"{b.replace('Batch_', 'B')}={c.get(b, 0):<5}" for b in B)
    head = lambda t: print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")

    # ── C1 / C2 ────────────────────────────────────────────────────────────
    head("C1/C2  option ids that today's codebook does not offer")
    agg = collections.defaultdict(collections.Counter)
    for b, df in batches.items():
        for (sec, sfx), lst in FIELD_LIST.items():
            ok = lists[lst] | EXTRA_OK.get((sec, sfx), set())
            sub = df[(df.Section == sec) & (df._sfx == sfx)]
            for v, n in sub._code.value_counts().items():
                if v in ("nan", "", "None"):
                    continue
                kind = ("C1 invalid" if v not in ok else
                        "C2 retired" if v in retired.get(lst, set()) else None)
                if kind:
                    agg[(kind, lst, f"{sec}.{sfx}", v)][b] += n
                    for pid in sub[sub._code == v].Patent_ID.unique():
                        hit(kind, b, patent=pid, field=f"{sec}.{sfx}", value=v, detail=lst)
    if not agg:
        print("  clean")
    for (kind, lst, fld, v), c in sorted(agg.items(), key=lambda x: -sum(x[1].values())):
        pick = "" if lst in guarded or kind.startswith("C1") else "  <- STILL PICKABLE"
        print(f"  {kind}  {fld:<26} {lst:<22} {v!r:<24} {span(c)}{pick}")

    # ── C2b ────────────────────────────────────────────────────────────────
    head("C2b  lists with retired ids but no *_CHOICES guard (reviewers can still pick them)")
    for lst in sorted(retired):
        if lst not in guarded:
            print(f"  {lst:<22} unguarded: {sorted(retired[lst])}")

    # ── C3 ─────────────────────────────────────────────────────────────────
    head("C3  retired FIELDS still carried in an export (survive load/save, never rendered)")
    for pat, why in DEAD_FIELDS.items():
        c = {}
        for b, df in batches.items():
            sub = df[df.Field.astype(str).str.fullmatch(pat, na=False)]
            c[b] = len(sub)
            for pid in sub.Patent_ID.unique():
                hit("C3 retired field", b, patent=pid, field=pat, value="", detail=why)
        if any(c.values()):
            print(f"  {pat:<24} {span(c)} ({why})")

    # ── C4 ─────────────────────────────────────────────────────────────────
    head("C4  fields now mandatory that are missing where their precondition holds")
    for label, pre_pat, pre_ids, req_pat in REQUIRED:
        c, cp = {}, {}
        for b, df in batches.items():
            pre = df[df.Field.astype(str).str.fullmatch(pre_pat, na=False)].copy()
            req = df[df.Field.astype(str).str.fullmatch(req_pat, na=False)].copy()
            if pre.empty:
                c[b] = cp[b] = 0
                continue
            pre["_g"] = pre.Field.astype(str).str.extract(pre_pat)[0]
            req["_g"] = req.Field.astype(str).str.extract(req_pat)[0]
            have = set(zip(req.Patent_ID, req._g))
            need = pre[pre._code.isin(pre_ids)]
            miss = need[[ (p, g) not in have for p, g in zip(need.Patent_ID, need._g) ]]
            c[b], cp[b] = len(miss), miss.Patent_ID.nunique()
            for pid in miss.Patent_ID.unique():
                hit("C4 required gap", b, patent=pid, field=req_pat, value="",
                    detail=label)
        print(f"  {label}\n      groups missing: {span(c)}\n      patents:        {span(cp)}")

    head("C4b  fields that must be BLANK where their precondition holds")
    for label, pre_pat, pre_ids, bad_pat in FORBIDDEN:
        c, cp = {}, {}
        for b, df in batches.items():
            pre = df[df.Field.astype(str).str.fullmatch(pre_pat, na=False)].copy()
            bad = df[df.Field.astype(str).str.fullmatch(bad_pat, na=False)].copy()
            bad = bad[bad.Value.notna() & bad.Value.astype(str).str.strip().ne("")]
            if pre.empty:
                c[b] = cp[b] = 0
                continue
            pre["_g"] = pre.Field.astype(str).str.extract(pre_pat)[0]
            bad["_g"] = bad.Field.astype(str).str.extract(bad_pat)[0]
            hot = {(p, g) for p, g, v in zip(pre.Patent_ID, pre._g, pre._code) if v in pre_ids}
            stray = bad[[(p, g) in hot for p, g in zip(bad.Patent_ID, bad._g)]]
            c[b], cp[b] = len(stray), stray.Patent_ID.nunique()
            for pid in stray.Patent_ID.unique():
                hit("C4b forbidden value", b, patent=pid, field=bad_pat, value="", detail=label)
        print(f"  {label}\n      stray values: {span(c)}\n      patents:      {span(cp)}")

    # C4c is C4b's mirror: the value must be blank where the precondition does NOT
    # hold. v15.6 gave boomN_span the same wing-referenced gate boomN_long got in
    # v15.5, so a fuselage boom carrying a spanwise answer is now stale data.
    for label, pre_pat, pre_ids, bad_pat in FORBIDDEN_UNLESS:
        c, cp = {}, {}
        for b, df in batches.items():
            pre = df[df.Field.astype(str).str.fullmatch(pre_pat, na=False)].copy()
            bad = df[df.Field.astype(str).str.fullmatch(bad_pat, na=False)].copy()
            bad = bad[bad.Value.notna() & bad.Value.astype(str).str.strip().ne("")]
            if pre.empty:
                c[b] = cp[b] = 0
                continue
            pre["_g"] = pre.Field.astype(str).str.extract(pre_pat)[0]
            bad["_g"] = bad.Field.astype(str).str.extract(bad_pat)[0]
            cold = {(p, g) for p, g, v in zip(pre.Patent_ID, pre._g, pre._code) if v not in pre_ids}
            stray = bad[[(p, g) in cold for p, g in zip(bad.Patent_ID, bad._g)]]
            c[b], cp[b] = len(stray), stray.Patent_ID.nunique()
            for pid in stray.Patent_ID.unique():
                hit("C4c forbidden value", b, patent=pid, field=bad_pat, value="", detail=label)
        print(f"  {label}\n      stray values: {span(c)}\n      patents:      {span(cp)}")

    # ── C5 ─────────────────────────────────────────────────────────────────
    head("C5  convention drift — same option list, different habit between batches")
    prof: dict[str, dict[str, dict]] = {}
    for b, df in batches.items():
        k = df.Section.astype(str) + "." + df._sfx
        for key, g in df.assign(_k=k).groupby("_k"):
            if key in DRIFT_IGNORE or len(g) < 40:
                continue
            vc = g._code.value_counts()
            if len(vc) < 2 or len(vc) > 14 or vc.index.str.len().max() > 40:
                continue                       # free text, not a coded field
            prof.setdefault(key, {})[b] = (vc / vc.sum()).to_dict()
    ranked = []
    for key, per in prof.items():
        if len(per) < 3:
            continue
        keys = set().union(*(set(v) for v in per.values()))
        worst, pair = 0.0, None
        for x, y in itertools.combinations(per, 2):
            tvd = 0.5 * sum(abs(per[x].get(k, 0) - per[y].get(k, 0)) for k in keys)
            if tvd > worst:
                worst, pair = tvd, (x, y)
        ranked.append((worst, key, pair, per))
    for w, key, pair, per in sorted(ranked, reverse=True)[:12]:
        flag = "  <<< look at this" if w >= 0.35 else ""
        print(f"  TVD={w:.2f}  {key:<28} worst {pair[0][-2:]}/{pair[1][-2:]}{flag}")
        for b in B:
            if b in per:
                top = sorted(per[b].items(), key=lambda x: -x[1])[:4]
                print(f"        {b}: " + ", ".join(f"{k}={v*100:.0f}%" for k, v in top))

    # ── C6 ─────────────────────────────────────────────────────────────────
    head("C6  META coverage — approved patents with no codebook_version / timestamp")
    for b, df in batches.items():
        ap = df[(df.Field.astype(str) == "isApproved") & (df.Value.astype(str) == "True")]
        ap = set(ap.Patent_ID)
        cv = set(df[df.Field.astype(str) == "codebook_version"].Patent_ID)
        ts = set(df[df.Field.astype(str) == "timestamp"].Patent_ID)
        for pid in (ap - cv) | (ap - ts):
            hit("C6 META gap", b, patent=pid, field="codebook_version/timestamp",
                value="", detail="approved but unstamped")
        print(f"  {b}: patents={df.Patent_ID.nunique():>4} approved={len(ap):>4}"
              f"  no codebook_version={len(ap - cv):>3}  no timestamp={len(ap - ts):>3}")
    stamps = {b: sorted(set(df[df.Field.astype(str) == "codebook_version"]
                            ._code.astype(str))) for b, df in batches.items()}
    print(f"\n  codebook_version values in file: {stamps}")
    print(f"  codebook_version in {'HTML'}: {schema['codebook_version']!r}"
          "   <- never bumped, so this stamp cannot tell two schema revisions apart")

    if html is not None:
        run_c7_c10(schema, batches, hit, html)

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "conformance_worklist.csv"
        pd.DataFrame(rows).drop_duplicates().to_csv(p, index=False)
        print(f"\n  per-patent worklist -> {p}  ({len(set(map(str, rows)))} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--batches", nargs="+", default=DEFAULT_BATCHES)
    ap.add_argument("--out", type=Path, default=None, help="write per-patent CSV here")
    a = ap.parse_args()
    print("loading:", file=sys.stderr)
    schema = load_schema(a.html)
    batches = load_batches(a.dir, a.batches)
    if not batches:
        sys.exit("no batches loaded")
    run(schema, batches, a.out, a.html)


if __name__ == "__main__":
    main()
