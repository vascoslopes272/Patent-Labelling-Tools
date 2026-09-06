"""
triage_report.py — a standalone review page for one batch's Stage 03a labels.

Generates ONE self-contained .html file you open from disk. No server, no
network, no dependency on the taxonomy wizard — it does not read, write or
modify `UI_for_taxonomy_caracterization_*.html` or anything the wizard touches.

What it is for
--------------
Reviewing ~350 patents by hand is the bottleneck. This page exists to make the
common case a single keystroke and to put the rows that actually need thought
at the top, so time is spent where the pipeline is unsure rather than where it
is already right.

Ordering is the feature. Rows are sorted by how much your attention they need:

    1. rejectable suggestions      you asked to see these first
    2. low-confidence labels       the pipeline guessed and said so
    3. contradictions              e.g. VTOL text but a combustion powertrain
    4. everything else             confident, consistent, skim or accept

Keyboard: J/K move, A accept the row as-is, X confirm rejectable, D dismiss the
rejectable flag, E edit a label, N add a note. Decisions are held in the
browser (localStorage, so a refresh does not lose them) and exported as a CSV
you feed back with `identity_pipeline.read_triage_decisions()`.

Nothing here decides anything. The page records what YOU decided; the CSV is
applied by the notebook, which sets the field's `*_source` to "human" so the
next run keeps your call.

Public API
----------
build_triage_html(rows, batch, out_path) -> Path
triage_sort_key(row)                     -> tuple
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from src.identity_schema import NEEDS_REVIEW_BELOW

# Fields shown on each card, in the order you said they matter.
REVIEW_FIELDS = [
    ("takeoff_mode", "Takeoff", "VTOL|STOL|CTOL|VSTOL|Unknown"),
    ("powertrain", "Propulsion",
     "BatteryElectric|HybridElectric|HydrogenFuelCell|Turbine|Piston|Unspecified"),
    ("scope", "Scope",
     "Whole Aircraft Architecture|Architectural Subsystem Enabler|Component-Level Generic"),
    ("architecture_primary_label", "Architecture", ""),
    ("innovation_field", "Field", ""),
    ("industry_primary", "Mission", ""),
    ("aircraft_name", "Aircraft", ""),
]


def triage_sort_key(row: dict) -> tuple:
    """Worst-first ordering. Lower sorts earlier.

    Rejectable rows lead because they are the ones you asked to act on. After
    that it is genuine uncertainty — the mean confidence across the reviewable
    labels — rather than anything cosmetic, so the queue drains from "needs a
    decision" toward "already right".
    """
    rejectable = bool(row.get("rejectable"))

    confs = [row.get(f"{f}_confidence") for f, _, _ in REVIEW_FIELDS]
    confs = [float(c) for c in confs if isinstance(c, (int, float))]
    mean_conf = sum(confs) / len(confs) if confs else 0.0

    # A VTOL claim with a combustion powertrain is one of the two labels being
    # wrong, and which one is not knowable from the text alone.
    contradiction = (row.get("takeoff_mode") == "VTOL"
                     and row.get("powertrain") in ("Turbine", "Piston"))

    missing = sum(1 for f, _, _ in REVIEW_FIELDS if not row.get(f))

    return (0 if rejectable else 1,
            0 if contradiction else 1,
            round(mean_conf, 3),
            -missing)


def _conf_class(value) -> str:
    if not isinstance(value, (int, float)):
        return "none"
    return "lo" if value < NEEDS_REVIEW_BELOW else "mid" if value < 0.8 else "hi"


def _card(row: dict, index: int) -> str:
    pid = html.escape(str(row.get("patent_id") or ""))
    title = html.escape(str(row.get("title") or "")[:150])
    company = html.escape(str(row.get("company_canonical") or "—"))
    year = html.escape(str(row.get("app_year") or "—"))

    chips = []
    for field, label, options in REVIEW_FIELDS:
        value = row.get(field)
        conf = row.get(f"{field}_confidence")
        conf_txt = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
        chips.append(
            f'<div class="f" data-field="{field}" data-options="{html.escape(options)}">'
            f'<span class="fl">{html.escape(label)}</span>'
            f'<span class="fv {_conf_class(conf)}" tabindex="0">'
            f'{html.escape(str(value)) if value else "<em>empty</em>"}'
            f'<span class="c">{conf_txt}</span></span></div>'
        )

    flag = ""
    if row.get("rejectable"):
        flag = (f'<div class="flag"><b>REJECTABLE</b> '
                f'{html.escape(str(row.get("rejectable_reason") or ""))}</div>')

    ev = row.get("takeoff_evidence") or row.get("specificity_reason") or ""
    ev_html = f'<div class="ev">{html.escape(str(ev)[:280])}</div>' if ev else ""

    link = row.get("aircraft_link")
    link_html = ""
    if link and link != "None":
        cls = "ok" if link == "Depicted" else "warn"
        link_html = f'<span class="lk {cls}">{html.escape(str(link))}</span>'

    return f"""<article class="card" id="p{index}" data-pid="{pid}" data-idx="{index}">
<header><span class="n">{index + 1}</span><code>{pid}</code>
<span class="meta">{company} &middot; {year}</span>{link_html}</header>
<h3>{title}</h3>{flag}
<div class="fields">{''.join(chips)}</div>{ev_html}
<div class="acts">
  <button data-act="accept">Accept <kbd>A</kbd></button>
  <button data-act="confirm_reject" class="danger">Confirm reject <kbd>X</kbd></button>
  <button data-act="dismiss_flag">Not rejectable <kbd>D</kbd></button>
  <button data-act="note">Note <kbd>N</kbd></button>
  <span class="state"></span>
</div></article>"""


_CSS = """
:root{--bg:#FBFAF8;--fg:#15191E;--mut:#5D6670;--line:#E2DFD9;--card:#fff;
--red:#B02A25;--redbg:#FBEDEB;--amb:#8A6208;--ambbg:#FAF2E0;--grn:#2C6A4E;--grnbg:#E8F1EB;}
@media(prefers-color-scheme:dark){:root{--bg:#12161B;--fg:#ECEAE5;--mut:#98A1AB;
--line:#2B323A;--card:#181D23;--red:#E8756B;--redbg:#2C1D1C;--amb:#D8AC55;--ambbg:#2A2317;
--grn:#7FBE9C;--grnbg:#17251F;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
.top{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:2px solid var(--fg);
padding:14px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.top h1{font-size:17px;margin:0;font-weight:700}
.top .sp{flex:1}
.prog{font:12px ui-monospace,monospace;color:var(--mut)}
button{font:inherit;padding:5px 11px;border:1px solid var(--line);background:var(--card);
color:var(--fg);border-radius:5px;cursor:pointer}
button:hover{border-color:var(--fg)}
button.danger{color:var(--red);border-color:var(--red)}
button.primary{background:var(--fg);color:var(--bg);border-color:var(--fg);font-weight:600}
kbd{font:11px ui-monospace,monospace;opacity:.55;margin-left:5px}
main{max-width:900px;margin:0 auto;padding:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:7px;
padding:15px 17px;margin-bottom:12px;scroll-margin-top:78px}
.card.cur{border-color:var(--fg);box-shadow:0 0 0 2px var(--fg)}
.card.done{opacity:.42}
.card header{display:flex;gap:11px;align-items:center;flex-wrap:wrap;font-size:13px}
.card header .n{font:11px ui-monospace,monospace;color:var(--mut);min-width:30px}
.card code{font:12.5px ui-monospace,monospace;font-weight:600}
.meta{color:var(--mut)}
.lk{font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:99px;letter-spacing:.04em}
.lk.ok{background:var(--grnbg);color:var(--grn)}
.lk.warn{background:var(--ambbg);color:var(--amb)}
.card h3{font-size:14.5px;font-weight:500;margin:7px 0 10px;color:var(--mut);line-height:1.4}
.flag{background:var(--redbg);color:var(--red);border-left:3px solid var(--red);
padding:7px 11px;margin:0 0 10px;font-size:13px;border-radius:0 4px 4px 0}
.fields{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:9px}
.f{display:flex;flex-direction:column;gap:2px}
.fl{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.fv{font-size:13px;padding:3px 9px;border-radius:4px;border:1px solid var(--line);
cursor:pointer;display:flex;gap:7px;align-items:center}
.fv:hover,.fv:focus{border-color:var(--fg);outline:none}
.fv .c{font:10.5px ui-monospace,monospace;opacity:.65}
.fv.lo{background:var(--redbg);border-color:var(--red)}
.fv.mid{background:var(--ambbg)}
.fv.hi{background:var(--grnbg)}
.fv.edited{border-color:var(--fg);border-width:2px;font-weight:600}
.fv em{opacity:.5}
.ev{font-size:12px;color:var(--mut);border-left:2px solid var(--line);
padding-left:10px;margin-bottom:10px;font-style:italic}
.acts{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
.state{font-size:12px;font-weight:600;margin-left:5px}
.state.accept{color:var(--grn)}.state.confirm_reject{color:var(--red)}
.state.dismiss_flag{color:var(--amb)}
.hint{font-size:12px;color:var(--mut);padding:0 20px 26px;max-width:900px;margin:0 auto}
"""

_JS = r"""
const KEY = 'triage_' + BATCH;
let dec = {};
try { dec = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { dec = {}; }
let cur = 0;
const cards = [...document.querySelectorAll('.card')];

function save(){ try{ localStorage.setItem(KEY, JSON.stringify(dec)); }catch(e){} paint(); }

function paint(){
  cards.forEach((c,i)=>{
    const d = dec[c.dataset.pid];
    c.classList.toggle('cur', i===cur);
    c.classList.toggle('done', !!(d && d.action));
    const s = c.querySelector('.state');
    s.textContent = d && d.action ? ({accept:'accepted',confirm_reject:'rejected',
      dismiss_flag:'kept',note:'noted'})[d.action] || d.action : '';
    s.className = 'state ' + (d && d.action ? d.action : '');
    c.querySelectorAll('.fv').forEach(v=>{
      const f = v.parentElement.dataset.field;
      v.classList.toggle('edited', !!(d && d.edits && d.edits[f] !== undefined));
    });
  });
  const n = Object.values(dec).filter(d=>d.action).length;
  document.getElementById('prog').textContent =
    n + ' / ' + cards.length + ' reviewed  ·  ' + (cards.length - n) + ' left';
}

function go(i){ cur = Math.max(0, Math.min(cards.length-1, i));
  cards[cur].scrollIntoView({block:'center',behavior:'smooth'}); paint(); }

function act(a, i){
  i = i === undefined ? cur : i;
  const pid = cards[i].dataset.pid;
  dec[pid] = Object.assign({edits:{}}, dec[pid], {action:a, at:new Date().toISOString()});
  save();
  if (a !== 'note' && i === cur && cur < cards.length-1) go(cur+1);
}

function edit(el){
  const wrap = el.parentElement, field = wrap.dataset.field;
  const opts = (wrap.dataset.options||'').split('|').filter(Boolean);
  const now = el.childNodes[0].textContent.trim();
  const val = opts.length
    ? prompt(field + '\n\n' + opts.map((o,k)=>(k+1)+'. '+o).join('\n')
             + '\n\nType the new value (or a number), blank to cancel:', now)
    : prompt(field + '\n\nNew value (blank to cancel):', now);
  if (val === null || val.trim() === '') return;
  let v = val.trim();
  if (opts.length && /^\d+$/.test(v) && opts[+v-1]) v = opts[+v-1];
  const pid = el.closest('.card').dataset.pid;
  dec[pid] = Object.assign({action:null, edits:{}}, dec[pid]);
  dec[pid].edits[field] = v;
  dec[pid].at = new Date().toISOString();
  el.childNodes[0].textContent = v;
  save();
}

document.addEventListener('click', e=>{
  const fv = e.target.closest('.fv'); if (fv){ edit(fv); return; }
  const b = e.target.closest('button[data-act]');
  if (b){ const c = b.closest('.card'); cur = +c.dataset.idx;
    if (b.dataset.act === 'note') note(); else act(b.dataset.act); }
});

function note(){
  const pid = cards[cur].dataset.pid;
  const t = prompt('Note for ' + pid + ':', (dec[pid]||{}).note || '');
  if (t === null) return;
  dec[pid] = Object.assign({action:'note', edits:{}}, dec[pid], {note:t});
  save();
}

document.addEventListener('keydown', e=>{
  if (e.target.tagName === 'INPUT' || e.metaKey || e.ctrlKey) return;
  const k = e.key.toLowerCase();
  if (k === 'j' || k === 'arrowdown'){ go(cur+1); e.preventDefault(); }
  else if (k === 'k' || k === 'arrowup'){ go(cur-1); e.preventDefault(); }
  else if (k === 'a') act('accept');
  else if (k === 'x') act('confirm_reject');
  else if (k === 'd') act('dismiss_flag');
  else if (k === 'n'){ note(); e.preventDefault(); }
  else if (k === 'e'){ const f = cards[cur].querySelector('.fv'); if (f) edit(f); e.preventDefault(); }
});

function csv(){
  const fields = FIELDS;
  const head = ['patent_id','action','note','reviewed_at']
    .concat(fields.map(f=>f+'_human'));
  const lines = [head.join(',')];
  cards.forEach(c=>{
    const pid = c.dataset.pid, d = dec[pid];
    if (!d || (!d.action && !Object.keys(d.edits||{}).length)) return;
    const row = [pid, d.action||'', (d.note||'').replace(/"/g,'""'), d.at||''];
    fields.forEach(f=>row.push(((d.edits||{})[f]||'').replace(/"/g,'""')));
    lines.push(row.map(v=>'"'+v+'"').join(','));
  });
  return lines.join('\n');
}

document.getElementById('dl').onclick = ()=>{
  const b = new Blob([csv()], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'triage_decisions_' + BATCH + '.csv';
  a.click();
};
document.getElementById('clr').onclick = ()=>{
  if (confirm('Clear every decision on this page? This cannot be undone.')){
    dec = {}; save(); location.reload();
  }
};
paint(); go(0);
"""


def build_triage_html(rows: list[dict], batch: str, out_path: "str | Path") -> Path:
    """Write the review page for one batch. Returns the path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ordered = sorted(rows, key=triage_sort_key)
    cards = "\n".join(_card(r, i) for i, r in enumerate(ordered))
    n_flag = sum(1 for r in ordered if r.get("rejectable"))
    fields_json = json.dumps([f for f, _, _ in REVIEW_FIELDS])

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Triage {html.escape(batch)}</title><style>{_CSS}</style></head><body>
<div class="top">
  <h1>Triage &middot; {html.escape(batch)}</h1>
  <span class="prog" id="prog"></span>
  <span class="prog">{n_flag} flagged rejectable</span>
  <span class="sp"></span>
  <button id="dl" class="primary">Download decisions CSV</button>
  <button id="clr">Clear</button>
</div>
<main>{cards}</main>
<p class="hint"><b>Keys:</b> <kbd>J</kbd>/<kbd>K</kbd> move &middot;
<kbd>A</kbd> accept &middot; <kbd>X</kbd> confirm rejectable &middot;
<kbd>D</kbd> not rejectable &middot; <kbd>E</kbd> edit first label &middot;
<kbd>N</kbd> note. Click any label to change it.
Decisions are kept in this browser until you download the CSV — generated
{datetime.now():%Y-%m-%d %H:%M}. Sorted worst-first: flagged rows, then
contradictions, then lowest confidence.</p>
<script>const BATCH={json.dumps(batch)};const FIELDS={fields_json};{_JS}</script>
</body></html>"""

    out_path.write_text(doc, encoding="utf-8")
    return out_path
