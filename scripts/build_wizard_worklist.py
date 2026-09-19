#!/usr/bin/env python3
"""build_wizard_worklist.py — the wizard to-do list (review_decisions/PENDING_WIZARD_REVIEW.csv) as a table page.
    python scripts/build_wizard_worklist.py
Writes notebooks/post-process/wizard_worklist.html: one row per patent, grouped by kind of fix, with what to do in the
wizard, a tick box (kept in this browser) and a copy button for the wizard's Jump box. Read-only: the record is untouched.
"""
import json, re
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
L0 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
P = pd.read_csv(L0 / "inputs" / "review_decisions" / "PENDING_WIZARD_REVIEW.csv", dtype=str, keep_default_na=False)
OUT = REPO / "notebooks" / "post-process" / "wizard_worklist.html"
KINDS = [("type", "Type / structure", lambda w: True),
         ("tilt", "Rotor marked Tilt on a surface that already tilts → set the rotor to Fixed", lambda w: "surface that already tilts" in w),
         ("fig", "Figures (T2): give a status or a flight state", lambda w: w.startswith("T2 figures")),
         ("mr", "Multirotor blanks: fill the fields (never recorded)", lambda w: w.startswith("MULTIROTOR BLANKS")),
         ("fix", "Last fixes: overrides and booms (notebook 04 flags)", lambda w: w.startswith("04 FLAG"))]
def kind(w): return next(k for k, _, f in reversed(KINDS) if f(w))
def lines(w):
    """One bullet per figure / per propulsion group; multirotor groups keep their "aircraft N:" prefix."""
    if w.startswith("T2 figures: "): return [x.strip() for x in w[len("T2 figures: "):].split("; ") if x.strip()]
    if w.startswith("MULTIROTOR BLANKS"):
        out = []
        for ac in w.split(" — fill: ", 1)[1].split(" | "):
            pre, _, rest = ac.rpartition(": ") if ac.startswith("aircraft ") else ("", "", ac)
            tail = ""
            if " (D1 duplicate" in rest: rest, tail = rest.split(" (D1 duplicate", 1); tail = " (D1 duplicate" + tail
            out += [f"{pre}: {g}" if pre else g for g in rest.split("; ")]
            if tail: out[-1] += tail
        return out
    return [w]
TABLES = L0 / "outputs" / "tables"
A = pd.read_csv(TABLES / "aircraft_table.csv", dtype=str, keep_default_na=False, low_memory=False)
F = pd.read_csv(TABLES / "figure_table.csv", dtype=str, keep_default_na=False, low_memory=False)
V = pd.read_csv(L0 / "audit_2026-09-18" / "audit_6_codebook_rules" / "violations_now.csv", dtype=str, keep_default_na=False)
REV = pd.read_csv(L0 / "inputs" / "review_decisions" / "REVIEWED_IN_WIZARD.csv", dtype=str, keep_default_na=False)
AF = pd.read_csv(L0 / "outputs" / "ACTION_FLAGS.csv", dtype=str, keep_default_na=False)
# the wizard's own labels (M3 → card → "Propulsor Type N" block), so the row reads like the screen
FN = {"chord": "Tractor / Pusher Arrangement", "orient": "Thrust Kinematics", "rmech": "Retraction Kinematics", "propKin": "Propulsor Articulation"}
ST = {"fuselage": "Fuselage", "boom": "Booms", "emp": "Empennage", "hull_array": "Hull array", "core_layout": "Hub array"}
def mr_gaps(pid):
    """Blank multirotor fields still in the record for this patent, in the worklist's wording."""
    out = []
    for _, r in A[A.patent_id == pid].iterrows():
        pre = f"aircraft {r.ua}: " if r.n_variants not in ("", "1") else ""
        for st, lab in ST.items():
            if r.get(f"{st}_quickOverride") == "True": continue
            multi = r.get(f"{st}_ntypes", "") not in ("", "True", "1", "False", "0")
            for p, pl in ([(f"{st}_t{t}", f"{lab} type {t}") for t in range(1, 8) if r.get(f"{st}_t{t}_count", "") not in ("", "0", "False")] if multi else [(st, lab)]):
                if r.get(p + "_count", "") in ("", "0", "False"): continue
                miss = [FN[f] for f in FN if r.get(f"{p}_{f}", "") == ""]
                if miss: out.append(f"{pre}M3 → {pl.replace(' type ', ' card → Propulsor Type ') if ' type ' in pl else pl + ' card'} → no answer on: {', '.join(miss)}")
    return out
_REC = None
def record_rows(pid, field):
    """Values of one field for a patent (every arch), straight from the wizard record."""
    global _REC
    if _REC is None:
        _REC = pd.read_excel(L0 / "inputs" / "record" / "reviewed_patents_Batch_ALL.xlsx", sheet_name="Review", dtype=str, keep_default_na=False)
    return _REC[(_REC.Patent_ID.str.replace(r"_arch\d+$", "", regex=True) == pid) & (_REC.Field == field)].Value.tolist()
def record_gaps(pid):
    """Blank multirotor fields of a D1/D2 read straight from the wizard record (notebook 04 blanks their morphology)."""
    global _REC
    if _REC is None:
        _REC = pd.read_excel(L0 / "inputs" / "record" / "reviewed_patents_Batch_ALL.xlsx", sheet_name="Review", dtype=str, keep_default_na=False)
    x = _REC[(_REC.Patent_ID.str.replace(r"_arch\d+$", "", regex=True) == pid) & (_REC.Section == "M3")]
    v = dict(zip(x.Field, x.Value)); out = []
    for st, lab in ST.items():
        if v.get(f"{st}_quickOverride") == "True": continue
        multi = v.get(f"{st}_ntypes", "") not in ("", "True", "1", "False", "0")
        for p, pl in ([(f"{st}_t{t}", f"{lab} type {t}") for t in range(1, 8) if v.get(f"{st}_t{t}_count", "") not in ("", "0", "False")] if multi else [(st, lab)]):
            if v.get(p + "_count", "") in ("", "0", "False"): continue
            miss = [FN[f] for f in FN if v.get(f"{p}_{f}", "") == ""]
            if miss: out.append(f"M3 → {pl.replace(' type ', ' card → Propulsor Type ') if ' type ' in pl else pl + ' card'} → no answer on: {', '.join(miss)}")
    return out
def fig_open(line):
    m = re.search(r"\(([^()]+\.png)\)", line)
    if not m: return True
    f = F[F.image_file == m.group(1)]
    if f.empty: return False                                  # figure no longer in the record (removed)
    st = f.iloc[0].status
    return st == "" or (st == "approved" and f.iloc[0].acState == "")
# rules a "type / structure" row is about: the contradiction page's set plus the record-level ones behind the other rows
TYPE_RULES = set(re.findall(r'^    "([A-Z0-9_\-()=/]+)": \(', (REPO / "scripts" / "build_contradiction_review_page.py").read_text(), re.M)) | {
    "SLC_SRW_THRUST_MIXED", "APPROVED_WITH_REJECTION_REASON", "NO_THRUST_ON_APPROVED", "L3_WINGLESS_EXPORTS_WCOUNT_1"}
def check(r):
    """(todo lines still open, status text). Rows whose every item is verified in the record come back empty."""
    k, pid = r["kind"], r["pid"]
    if k == "mr":
        if (A[A.patent_id == pid].topType == "").all():      # D1/D2 duplicate: the table carries no morphology — read the record
            left = record_gaps(pid)
            return left, ("duplicate: all filled in the record" if not left else f"duplicate: {len(left)} group(s) still blank in the record")
        left = mr_gaps(pid); return left, ("all filled" if not left else f"{len(left)} group(s) still blank")
    if k == "fig":
        left = [x for x in r["todo"] if fig_open(x)]; return left, ("all figures done" if not left else f"{len(left)} figure(s) still open")
    if k == "fix":                                            # open while notebook 04 still raises the flag on this patent
        fl = re.match(r"04 FLAG (\S+):", r["todo"][0]).group(1)
        if fl == "PARTIAL_BOOM_TICK":                         # no 04 flag for it: done once re-saved in the wizard since added
            ed = REV[(REV.patent_id == pid) & (REV.source.str[:16] >= r["added"][:16])]
            return (r["todo"] if ed.empty else []), ("edited in the wizard (" + ed.iloc[-1].source + ")" if len(ed) else "")
        still = AF[(AF.patent_id == pid) & (AF.flag == fl)]
        return (r["todo"] if len(still) else []), (("still: " + "; ".join(still.detail)) if len(still) else f"{fl} no longer raised by notebook 04")
    if k == "tilt":
        left = V[(V.patent_id == pid) & V.rule.isin(["ROTOR_TILT_ON_TILTING_WING", "VECTORED_2_OF_3"])]
        return (r["todo"] if len(left) else []), ("no rotor marked Tilt on a tilting surface, and the type fits the 2-of-3 rule" if left.empty
                                                  else "still: " + "; ".join(f"{x.rule}: {x.detail}" for x in left.itertuples()))
    ed = REV[(REV.patent_id == pid) & (REV.source.str[:10] >= r["added"])]    # edited in the wizard since the row was added
    fires = V[(V.patent_id == pid) & V.rule.isin(TYPE_RULES)]
    if "delete the comment" in " ".join(r["todo"]):          # a row about the free-text comment: open while it is there
        c = [x for x in record_rows(pid, "comments") if x.strip()]    # notebook 04 drops free text: read the record
        if c: return r["todo"], "the comment is still in the record: " + "; ".join(sorted(set(c)))
    if len(fires): return r["todo"], "still: " + "; ".join(f"{x.rule}: {x.detail}" for x in fires.itertuples())
    if len(ed): return [], "edited in the wizard (" + ed.iloc[-1].source + ") and no rule fires any more"
    return r["todo"], ""
rows = [dict(pid=r.patent_id, kind=kind(r.what_to_check), todo=[x for part in r.what_to_check.split(" + ") for x in lines(part)], added=r.added)
        for r in P.itertuples()]
for r in rows:
    r["left"], r["status"] = check(r); r["auto"] = not r["left"]
order = [k for k, _, _ in KINDS]
rows.sort(key=lambda r: (order.index(r["kind"]), r["pid"]))
data = json.dumps(dict(rows=rows, kinds=[[k, t] for k, t, _ in KINDS]), ensure_ascii=False)
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Wizard worklist</title><style>
*{box-sizing:border-box}body{font:14px system-ui,sans-serif;margin:0;background:#f4f4f2;color:#222}
header{position:sticky;top:0;z-index:5;background:#1f2d3d;color:#fff;padding:8px 14px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header b{font-size:16px}.hint{font-size:12px;color:#cfd8dc;width:100%}main{padding:10px 14px}
h2{font-size:15px;margin:18px 0 6px}table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}
td,th{border:1px solid #ddd;padding:5px 8px;text-align:left;vertical-align:top}th{background:#eef1f5}
tr.done td{background:#e8f5e9;color:#789}tr.done .pid{text-decoration:line-through}
.pid{font-weight:700;font-family:ui-monospace,monospace;font-size:14px;white-space:nowrap}
.cp{font-size:11px;margin-left:6px;cursor:pointer;border:1px solid #999;background:#fff;border-radius:3px;padding:0 5px}
ul{margin:0;padding-left:18px}.st{font-size:12px;color:#b26a00;margin-top:3px}.st.ok{color:#2e7d32}td.n{width:34px;color:#888}td.c{width:34px;text-align:center}input[type=checkbox]{transform:scale(1.3)}
</style></head><body><header><b>Wizard worklist</b><span id="cnt"></span>
<label><input type="checkbox" id="hide"> hide done</label>
<span class="hint">Open the wizard with the record loaded, type the patent in the Jump box (copy button), fix what the row says, tick it. Multirotor rows: every question named is EMPTY in the record — if the wizard shows 'Propulsor Articulation (Locked)' with Fixed greyed out, it is an old page: reload it and the question becomes a free pick. Rows the record already confirms (after an export is installed) tick themselves. Ticks stay in this browser. Export from the wizard when you are done (or after a batch) and tell Claude: the export is diffed against this list.</span></header>
<main id="m"></main><script>
const D = __DATA__, KEY = 'wizardWorklist_v2';   // v2: a tick belongs to one row (patent + date added), so a new task on an old patent starts unticked
let T = {}; try { T = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
const tk = r => r.pid + '|' + r.added;
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function render(){
  const hide = document.getElementById('hide').checked; let h = '', n = 0;
  D.kinds.forEach(([k, t]) => {
    const rs = D.rows.filter(r => r.kind === k); if (!rs.length) return;
    const done = r => r.auto || T[tk(r)], left = rs.filter(r => !done(r)).length;
    h += '<h2>' + esc(t) + ' — ' + left + ' of ' + rs.length + ' left</h2><table><tr><th></th><th>#</th><th>patent</th><th>what to do in the wizard</th></tr>';
    rs.forEach(r => { n++; if (hide && done(r)) return; const todo = r.auto ? r.todo : r.left;
      h += '<tr class="' + (done(r) ? 'done' : '') + '"><td class="c"><input type="checkbox" data-p="' + esc(tk(r)) + '"' + (done(r) ? ' checked' : '') + (r.auto ? ' disabled title="verified in the record"' : '') + '></td><td class="n">' + n + '</td>'
        + '<td><span class="pid">' + esc(r.pid) + '</span><button class="cp" data-c="' + esc(r.pid) + '">copy</button></td>'
        + '<td>' + (todo.length > 1 ? '<ul>' + todo.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>' : esc(todo[0] || '')) + (r.status ? '<div class="st' + (r.auto ? ' ok' : '') + '">' + (r.auto ? '✓ verified in the record: ' : '') + esc(r.status) + '</div>' : '') + '</td></tr>'; });
    h += '</table>';
  });
  document.getElementById('m').innerHTML = h;
  document.getElementById('cnt').textContent = D.rows.filter(r => r.auto || T[tk(r)]).length + ' / ' + D.rows.length + ' done';
}
document.addEventListener('change', e => { const c = e.target.closest('input[data-p]'); if (c) { if (c.checked) T[c.dataset.p] = 1; else delete T[c.dataset.p]; try { localStorage.setItem(KEY, JSON.stringify(T)); } catch (x) {} render(); } });
document.addEventListener('click', e => { const b = e.target.closest('button.cp'); if (b) { navigator.clipboard && navigator.clipboard.writeText(b.dataset.c); b.textContent = 'copied'; setTimeout(() => b.textContent = 'copy', 900); } });
document.getElementById('hide').onchange = render; render();
</script></body></html>"""
OUT.write_text(PAGE.replace("__DATA__", data), encoding="utf-8")
print(f"wrote {OUT}: {len(rows)} patents", pd.Series([r['kind'] for r in rows]).value_counts().to_dict())
