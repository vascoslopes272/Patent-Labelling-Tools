"""
test_taxonomy_alignment.py — drift guard between the Python taxonomy
definitions (src/reviewer.py, src/cross_modal.py, src/excel_schema.py) and
the JS taxonomy arrays/functions in the review wizard HTML.

Why this exists
----------------
The set of valid label ids for each field (e.g. M1.fusShape = Circular/Oval/
Rectangular/Blended) is declared TWICE, independently, in two different
languages:

  - Python: the `_*_DEFS` dicts in src/reviewer.py (keys = label ids used for
    SBERT zero-shot classification), the module-level lists in
    src/cross_modal.py (T2_PER, G1_TOP_TYPES, ...), and the Options strings
    in src/excel_schema.py's _T1_MANUAL/_M1_MANUAL/_WING_MANUAL/_M3_MANUAL.
  - JavaScript: the `var X = [...]` arrays and small option-list functions
    in notebooks/UI_for_taxonomy_caracterization_10.0.html.

Nothing enforces that these stay in sync. If someone adds/renames/removes an
option on one side and forgets the other, the two pipelines silently drift:
a reviewer could pick a label in the HTML the Excel schema doesn't recognize,
or an ML prediction could land in the Excel with a value the HTML wizard has
no option for. This test parses both sides (statically — no browser/Node
required) and fails loudly the moment they diverge, instead of someone
discovering it by hand weeks later.

Scope
-----
Only fields that are validated against an explicit option set on the Excel
side (an Options string emitted by excel_schema.py, or a *_DEFS dict /
canonical list consumed by it) are checked here. Wizard-only UI sugar with
no Excel-schema counterpart (e.g. DUP_TYPES, QUALITY_FLAGS, duplicateType)
is intentionally out of scope — there is nothing on the Python side for it
to drift from.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "notebooks" / "UI_for_taxonomy_caracterization_10.0.html"

sys.path.insert(0, str(REPO_ROOT))

from src.excel_schema import _T1_MANUAL, _G1_MANUAL, _M1_MANUAL, _WING_MANUAL, _M3_MANUAL  # noqa: E402
from src.reviewer import (  # noqa: E402
    _T1_SCOPE_DEFS, _T1_FIELD_DEFS, _T1_TARGET_DEFS,
    _M1_FUS_SHAPE_DEFS, _M1_FUS_KIN_DEFS, _M1_GEAR_ARCH_DEFS, _M1_LAT_SYM_DEFS,
    _M2_WING_CONF_DEFS, _M2_EMP_TYPE_DEFS, _M2_EMP_KIN_DEFS, _M2_WCOUNT_DEFS,
    _M3_CHORD_DEFS, _M3_ORIENT_DEFS, _M3_BMECH_DEFS, _M3_RMECH_DEFS,
)
from src.cross_modal import (  # noqa: E402
    T2_PER, T2_AC_STY, T2_AC_COL, T2_BG_STY, T2_BG_COL, T2_PARTS,
    G1_TOP_TYPES,
)


# ─── HTML/JS-side extraction (static regex parsing, no Node/browser) ────────

@pytest.fixture(scope="module")
def js_src() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    assert blocks, "no inline <script> block found in the HTML — file moved/renamed?"
    return "\n".join(blocks)


def _extract_balanced(src: str, start: int) -> str:
    """Given an index of an opening '{' or '[', return the substring up to
    (and including) its matching closing brace/bracket, ignoring braces
    inside string literals so option labels containing '{'/'}' can't desync
    the scan."""
    open_ch = src[start]
    close_ch = {"{": "}", "[": "]"}[open_ch]
    depth = 0
    in_str = None
    i = start
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ("'", '"'):
            in_str = c
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    raise ValueError("unbalanced braces while scanning JS source")


def extract_var_ids(src: str, var_name: str) -> set[str]:
    """Pull the {id:'X', ...} ids out of `var NAME = [ ... ];`."""
    m = re.search(r"\bvar\s+" + re.escape(var_name) + r"\s*=\s*(\[)", src)
    assert m, f"could not find `var {var_name} = [...]` in the HTML"
    array_src = _extract_balanced(src, m.start(1))
    return set(re.findall(r"id\s*:\s*'([^']*)'", array_src))


def extract_var_strings(src: str, var_name: str) -> set[str]:
    """Pull the plain string values out of `var NAME = ['a','b',...];`."""
    m = re.search(r"\bvar\s+" + re.escape(var_name) + r"\s*=\s*(\[)", src)
    assert m, f"could not find `var {var_name} = [...]` in the HTML"
    array_src = _extract_balanced(src, m.start(1))
    return set(re.findall(r"'([^']*)'", array_src))


def extract_function_ids(src: str, func_name: str) -> set[str]:
    """Pull every {id:'X', ...} id mentioned anywhere inside a function body
    (across all branches/returns) — used for option-list helper functions
    like m3OrientationOptions()/m3ZoneOptions() whose option set depends on
    the call-site state, so the union of every branch is the field's full
    valid-id universe."""
    m = re.search(r"\bfunction\s+" + re.escape(func_name) + r"\s*\([^)]*\)\s*(\{)", src)
    assert m, f"could not find `function {func_name}(...)` in the HTML"
    body = _extract_balanced(src, m.start(1))
    return set(re.findall(r"id\s*:\s*'([^']*)'", body))


def extract_select_options(src: str, data_field: str) -> set[str]:
    """Pull non-empty <option value="..."> ids out of the <select
    data-field="X"> ... </select> block (used for t1DisapproveReason, which
    is a plain <select> rather than an `oc()`-rendered option grid)."""
    m = re.search(r'<select[^>]*data-field="' + re.escape(data_field) + r'"[^>]*>(.*?)</select>', src, re.S)
    assert m, f"could not find <select data-field=\"{data_field}\"> in the HTML"
    return set(re.findall(r'<option value="([^"]+)"', m.group(1)))


def _opts_for(manual_list, field_name: str) -> set[str] | None:
    """Look up the declared Options string for `field_name` in one of
    excel_schema.py's _*_MANUAL lists (e.g. _WING_MANUAL's ("wTilt", "Tilt",
    "Fixed|Tilt")) and split it into an id set. Returns None if the field's
    Options string is empty (free text / no enumerated set, e.g. notes)."""
    for entry in manual_list:
        if entry[0] == field_name:
            opts = entry[2]
            return set(opts.split("|")) if opts else None
    raise KeyError(f"{field_name!r} not found in manual list")


# ─── Comparisons: Python *_DEFS dict keys vs HTML `var X = [{id:...}]` ──────

@pytest.mark.parametrize("py_defs,html_var,label", [
    (G1_TOP_TYPES,        "TOP",         "G1.topType"),
    (_M1_FUS_SHAPE_DEFS,  "FUS_SHAPE",   "M1.fusShape"),
    (_M1_FUS_KIN_DEFS,    "FUS_KIN",     "M1.fusKin"),
    (_M1_GEAR_ARCH_DEFS,  "GEAR_ARCH",   "M1.gearArch"),
    (_M2_WING_CONF_DEFS,  "WING_CONFIG", "M2.wingConf"),
    (_M2_EMP_TYPE_DEFS,   "EMP_TYPE",    "M2.empType"),
    (_M2_EMP_KIN_DEFS,    "EMP_KIN",     "M2.empKin"),
    (_M3_CHORD_DEFS,      "CHORD",       "M3.chord"),
    (_M3_BMECH_DEFS,      "BLADE_MECH",  "M3.bmech"),
    (_M3_RMECH_DEFS,      "RETRACT_MECH", "M3.rmech"),
    (_T1_TARGET_DEFS,     "T1_TGT",      "T1.t1Target"),
])
def test_defs_dict_matches_html_var(js_src, py_defs, html_var, label):
    py_ids = set(py_defs.keys())
    html_ids = extract_var_ids(js_src, html_var)
    assert py_ids == html_ids, (
        f"{label} taxonomy drift between Python and HTML:\n"
        f"  in Python, not in HTML var {html_var}: {sorted(py_ids - html_ids)}\n"
        f"  in HTML var {html_var}, not in Python: {sorted(html_ids - py_ids)}"
    )


# ─── Comparisons: Python *_DEFS dict keys vs HTML option-list function ──────

@pytest.mark.parametrize("py_defs,html_func,label", [
    (_M3_ORIENT_DEFS,  "m3OrientationOptions", "M3.orient"),
    (_T1_SCOPE_DEFS,   "t1ScopeOptions",       "T1.scope"),
    (_T1_FIELD_DEFS,   "t1FieldOptions",       "T1.t1Field"),
])
def test_defs_dict_matches_html_function(js_src, py_defs, html_func, label):
    py_ids = set(py_defs.keys())
    html_ids = extract_function_ids(js_src, html_func)
    assert py_ids == html_ids, (
        f"{label} taxonomy drift between Python and HTML:\n"
        f"  in Python, not in HTML function {html_func}(): {sorted(py_ids - html_ids)}\n"
        f"  in HTML function {html_func}(), not in Python: {sorted(html_ids - py_ids)}"
    )


# ─── Comparisons: Python plain lists (cross_modal.py) vs HTML `var X = [...]` ─

@pytest.mark.parametrize("py_list,html_var,label", [
    (T2_PER,    "T2_PER",            "T2.per"),
    (T2_AC_STY, "T2_AC_STY",         "T2.acSty"),
    (T2_AC_COL, "T2_AC_COL",         "T2.acCol"),
    (T2_BG_STY, "T2_BG_STY",         "T2.bgSty"),
    (T2_BG_COL, "T2_BG_COL",         "T2.bgCol"),
    (T2_PARTS,  "T2_PARTS_DEFAULT",  "T2.parts"),
])
def test_plain_list_matches_html_var(js_src, py_list, html_var, label):
    py_ids = set(py_list)
    html_ids = extract_var_strings(js_src, html_var)
    assert py_ids == html_ids, (
        f"{label} taxonomy drift between Python and HTML:\n"
        f"  in Python, not in HTML var {html_var}: {sorted(py_ids - html_ids)}\n"
        f"  in HTML var {html_var}, not in Python: {sorted(html_ids - py_ids)}"
    )


# ─── Comparisons: excel_schema.py manual Options strings vs HTML ────────────

def test_wing_field_options_match_html(js_src):
    """_WING_MANUAL declares the Options string for each per-wing field
    (wTilt/wPosV/wPosL/wPlan/wRole) — cross-check each against its HTML
    counterpart. wTilt/wRole are declared inline inside pageM2() as
    `var tiltOpts = [...]` / `var roleOpts = [...]`, the rest are top-level
    `var W_POS_V/W_POS_L/W_PLAN = [...]`."""
    checks = [
        ("wTilt", "tiltOpts", extract_var_ids),
        ("wPosV", "W_POS_V",  extract_var_ids),
        ("wPosL", "W_POS_L",  extract_var_ids),
        ("wPlan", "W_PLAN",   extract_var_ids),
        ("wRole", "roleOpts", extract_var_ids),
    ]
    for field, html_var, extractor in checks:
        py_ids = _opts_for(_WING_MANUAL, field)
        html_ids = extractor(js_src, html_var)
        assert py_ids == html_ids, (
            f"_WING_MANUAL[{field!r}] taxonomy drift between Python and HTML:\n"
            f"  in Python, not in HTML var {html_var}: {sorted(py_ids - html_ids)}\n"
            f"  in HTML var {html_var}, not in Python: {sorted(html_ids - py_ids)}"
        )


def test_m3_zone_field_options_match_html(js_src):
    """_M3_MANUAL declares Options strings for zone/zoneChord/zoneSpan —
    cross-check against the HTML's m3ZoneOptions()/m3ZoneChordOptions()/
    m3ZoneSpanOptions() helper functions (m3ZoneOptions branches on whether
    the component is the empennage; the union of both branches is the
    field's full valid-id universe)."""
    checks = [
        ("zone",      "m3ZoneOptions"),
        ("zoneChord", "m3ZoneChordOptions"),
        ("zoneSpan",  "m3ZoneSpanOptions"),
    ]
    for field, html_func in checks:
        py_ids = _opts_for(_M3_MANUAL, field)
        html_ids = extract_function_ids(js_src, html_func)
        assert py_ids == html_ids, (
            f"_M3_MANUAL[{field!r}] taxonomy drift between Python and HTML:\n"
            f"  in Python, not in HTML function {html_func}(): {sorted(py_ids - html_ids)}\n"
            f"  in HTML function {html_func}(), not in Python: {sorted(html_ids - py_ids)}"
        )


def test_t1_disapprove_reason_options_match_html(js_src):
    """_T1_MANUAL declares t1DisapproveReason's Options string — the HTML
    renders it as a plain <select data-field="t1DisapproveReason"> rather
    than an oc()-style option grid, so it needs its own extractor."""
    py_ids = _opts_for(_T1_MANUAL, "t1DisapproveReason")
    html_ids = extract_select_options(js_src, "t1DisapproveReason")
    assert py_ids == html_ids, (
        "T1.t1DisapproveReason taxonomy drift between Python and HTML:\n"
        f"  in Python, not in HTML <select>: {sorted(py_ids - html_ids)}\n"
        f"  in HTML <select>, not in Python: {sorted(html_ids - py_ids)}"
    )


# ─── Boolean / numeric fields with no enumerated HTML option list ───────────
# These render as checkboxes or numeric steppers in the HTML (not a
# `var X = [{id:...}]` array), so there's nothing to regex-extract — instead
# this just pins the Python-side declared Options strings to the boolean/
# numeric domain the HTML actually implements, so a future edit to either
# side (e.g. someone adding a third latSym state) still gets caught.

@pytest.mark.parametrize("manual_list,field,expected", [
    (_M1_MANUAL,  "footAmbiguous", {"true", "false"}),
    (_M1_MANUAL,  "longSym",       {"true", "false"}),
    (_T1_MANUAL,  "isApproved",    {"true", "false"}),
    (_T1_MANUAL,  "isDuplicate",   {"true", "false"}),
    (_G1_MANUAL,  "notPureArch",   {"true", "false"}),
])
def test_manual_boolean_field_domain(manual_list, field, expected):
    assert _opts_for(manual_list, field) == expected


def test_m3_sym_boolean_domain():
    assert _opts_for(_M3_MANUAL, "sym") == {"true", "false"}


def test_lat_sym_defs_are_boolean():
    assert set(_M1_LAT_SYM_DEFS.keys()) == {"true", "false"}


def test_wcount_defs_are_1_to_4():
    # 0 is a sentinel meaning "wingConf is BWB/FW/LB, no discrete panel to
    # count" (see WING_CONFIG's per-option descriptions in the HTML and
    # m3_card_keys() in reviewer.py) — it's not a 5th predicted value, so
    # _M2_WCOUNT_DEFS legitimately only covers 1-4.
    assert set(_M2_WCOUNT_DEFS.keys()) == {"1", "2", "3", "4"}
