#!/usr/bin/env python3
"""Build the crewed-multicopter review page for the WM gap check.

Reads the new-family tables written by wm_gap_check.py (patents) and writes one
self-contained HTML page: T1_plausible (all), T1_rest_sample (30, seeded),
T2_all (all). Decisions autosave in the browser and export as CSV
(wm_review_decisions.csv), which wm_gap_check.py score-review reads.
"""
import json
from pathlib import Path
import pandas as pd

OUT_DIR = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/EVTOLNEWS_DS/3_embedding_evaluation/wm_gap_check")
SEED = 20261001

t1 = pd.read_csv(OUT_DIR / "new_T1.csv")
t2 = pd.read_csv(OUT_DIR / "new_T2.csv")
plaus_mask = t1.has_multirotor & ~t1.has_wing
plaus = t1[plaus_mask].copy()
plaus["sub"] = plaus.flagged.map({True: "crew term", False: "no crew term"})
plaus = plaus.sort_values(["flagged", "title"], ascending=[False, True])
rest = t1[~plaus_mask]
samp = rest.sample(n=30, random_state=SEED).assign(sub="random 30 of %d" % len(rest))
t2 = t2.assign(sub="drone filter relaxed")

idx_path = OUT_DIR / "figs" / "index.json"
FIGIDX = json.loads(idx_path.read_text()) if idx_path.exists() else {}
pdf_path = OUT_DIR / "figs" / "pdf_index.json"
PDFIDX = json.loads(pdf_path.read_text()) if pdf_path.exists() else {}
items = []
for tab, df in [("T1_plausible", plaus), ("T1_rest_sample", samp), ("T2_all", t2)]:
    for _, r in df.iterrows():
        rec = str(r.record).replace(" ", "")
        items.append(dict(tab=tab, sub=r["sub"], fam=str(r.family_id), rec=rec,
                          title=str(r.title or ""), abs=str(r.abstract or "") if pd.notna(r.abstract) else "",
                          cpc=str(r.cpc or "") if pd.notna(r.cpc) else "",
                          imgs=FIGIDX.get(rec, []), pdf=PDFIDX.get(rec, "")))
meta = dict(n_plaus=len(plaus), n_rest=len(rest), n_t2=len(t2), seed=SEED)
data = json.dumps(dict(items=items, meta=meta), ensure_ascii=False).replace("</", "<\\/")

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crewed Multicopter Review</title>
<style>
:root{--bg:#f6f6f4;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#dcdcd6;--acc:#2f5d8a;
 --y:#2e7d4f;--n:#b3402e;--q:#b07d12;--pend:#c4c4bd;--crew:#d7ecdc;--multi:#dbe6f3;--wing:#f6dcd6}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink)}
header{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);padding:8px 14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}
.bar{flex:1;min-width:140px;height:8px;background:#ececE6;border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--y)}
.cnt{color:var(--mute);font-size:13px}
.btn{font:inherit;border:1px solid var(--line);background:#fff;border-radius:6px;padding:5px 10px;cursor:pointer}
.btn:hover{border-color:var(--acc)}.btn.primary{background:var(--acc);color:#fff;border-color:var(--acc)}
.wrap{display:grid;grid-template-columns:270px 1fr;min-height:calc(100vh - 50px)}
nav{border-right:1px solid var(--line);background:#fbfbf9;overflow-y:auto;max-height:calc(100vh - 50px);position:sticky;top:50px}
nav h3{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);margin:12px 12px 4px}
nav a{display:flex;gap:7px;align-items:center;padding:3px 12px;color:var(--ink);text-decoration:none;font-size:12.5px;cursor:pointer;white-space:nowrap;overflow:hidden}
nav a span.tt{overflow:hidden;text-overflow:ellipsis}
nav a.cur{background:#e3ebf3}
.dot{width:9px;height:9px;border-radius:50%;background:var(--pend);flex:none}
.dot.y{background:var(--y)}.dot.n{background:var(--n)}.dot.q{background:var(--q)}
main{padding:16px 22px;max-width:1100px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:14px}
.meta{display:flex;gap:8px;flex-wrap:wrap;align-items:center;color:var(--mute);font-size:13px}
.pill{border-radius:10px;padding:1px 8px;font-size:12px;background:#eee;color:#333}
h2{font-size:19px;margin:8px 0 10px}
.abs{font-size:14.5px;line-height:1.6}
.cpc{margin-top:10px;font-size:12px;color:var(--mute);word-break:break-word}
mark.crew{background:var(--crew)}mark.multi{background:var(--multi)}mark.wing{background:var(--wing)}
mark{padding:0 2px;border-radius:3px}
.dec{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;align-items:center}
.dec .btn{min-width:150px;padding:9px 12px;font-weight:600}
.dec .btn.on.y{background:var(--y);color:#fff;border-color:var(--y)}
.dec .btn.on.n{background:var(--n);color:#fff;border-color:var(--n)}
.dec .btn.on.q{background:var(--q);color:#fff;border-color:var(--q)}
textarea{width:100%;font:inherit;margin-top:10px;border:1px solid var(--line);border-radius:6px;padding:6px;min-height:44px}
.rule{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:13px}
.rule summary{cursor:pointer;font-weight:600}
.links a{margin-right:12px}
.legend mark{font-size:12px}
kbd{border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 5px;font-size:12px;background:#fafafa}
.figs{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 12px}
.figs img{height:300px;max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:zoom-in;object-fit:contain}
.nofig{color:var(--mute);font-size:13px;margin:6px 0 12px}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;z-index:20;align-items:center;justify-content:center;cursor:zoom-out}
#zoom img{max-width:96vw;max-height:96vh;background:#fff}
@media (max-width:760px){.wrap{grid-template-columns:1fr}nav{display:none}}
</style></head><body>
<header><h1>Crewed multicopter review</h1>
<div class="bar"><i id="bar"></i></div><span class="cnt" id="cnt"></span>
<select class="btn" id="filter"><option value="all">all</option><option value="todo">to do</option><option value="y">y</option><option value="n">n</option><option value="q">?</option></select>
<button class="btn primary" id="save">Download CSV</button></header>
<div class="wrap"><nav id="nav"></nav><main>
<details class="rule" open><summary>Rule and keys</summary>
<p><b>y</b> = crewed wingless multicopter: a person on board (pilot or passenger), lift from rotors only, no wing, rotors not tilting for cruise.
<b>n</b> = anything else (uncrewed drone, part or component without a crewed aircraft, winged, tilting, single main rotor helicopter).
<b>?</b> = cannot tell from text, open the patent; say why in the note.</p>
<p><kbd>y</kbd> <kbd>n</kbd> <kbd>?</kbd> decide and move on · <kbd>←</kbd> <kbd>→</kbd> move · <kbd>p</kbd> open the patent PDF · <kbd>o</kbd> open Google Patents · <kbd>e</kbd> Espacenet · <kbd>u</kbd> next undecided · click a drawing to enlarge, <kbd>Esc</kbd> closes · Decisions autosave in this browser.</p>
<p class="legend">Highlights: <mark class="crew">crew term</mark> <mark class="multi">multirotor term</mark> <mark class="wing">wing or tilt term</mark></p></details>
<div id="card"></div></main></div><div id="zoom"><img id="zimg" alt=""></div>
<script>
const D = __DATA__;
const KEY = 'wm_crewed_multicopter_review_v1';
let S = {d:{}, note:{}};
try { const raw = localStorage.getItem(KEY); if (raw) S = Object.assign({d:{}, note:{}}, JSON.parse(raw)); } catch (e) {}
const persist = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} };
const id = it => it.tab + '|' + it.fam;
let cur = 0;
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const RX = [['crew',/\b(passengers?|occupants?|pilot(?:s|ed|ing)?|cabins?|seat(?:s|ed|ing)?|persons?|manned|human|riders?|drivers?|crew|people)\b/gi],
            ['multi',/\b(multi-?copters?|multi-?rotors?|quad-?copters?|octo-?copters?|hexa-?copters?|plurality of (?:rotors|propellers)|(?:four|six|eight|4|6|8)[- ]rotors?|(?:four|six|eight)-axis)\b/gi],
            ['wing',/\b(fixed[- ]wings?|wings?|tilt\w*)\b/gi]];
function hl(t){ let s = esc(t);
  RX.forEach(([c, r]) => { s = s.replace(r, m => '<mark class="' + c + '">' + m + '</mark>'); });
  return s.replace(/<mark class="wing">(wings?)<\/mark>/gi, (m, w, off, all) => /(rotor|rotary)[- ]$/i.test(all.slice(Math.max(0, off - 7), off)) ? w : m); }
const tabs = [['T1_plausible','T1: all '+D.meta.n_plaus+' naming a multirotor, no wing'],['T1_rest_sample','T1: 30 random of the other '+D.meta.n_rest],['T2_all','T2: all '+D.meta.n_t2]];
function visible(it){ const f = document.getElementById('filter').value, d = S.d[id(it)];
  return f === 'all' || (f === 'todo' ? !d : d === f); }
function nav(){ const n = document.getElementById('nav'); let h = '';
  tabs.forEach(([t, lab]) => { const its = D.items.map((it, i) => [it, i]).filter(([it]) => it.tab === t);
    const done = its.filter(([it]) => S.d[id(it)]).length;
    h += '<h3>' + esc(lab) + ' · ' + done + '/' + its.length + '</h3>';
    its.filter(([it]) => visible(it)).forEach(([it, i]) => { const d = S.d[id(it)] || '';
      h += '<a data-i="' + i + '" class="' + (i === cur ? 'cur' : '') + '"><span class="dot ' + d + '"></span><span class="tt">' + esc(it.title || it.rec) + '</span></a>'; }); });
  n.innerHTML = h; n.querySelectorAll('a').forEach(a => a.onclick = () => go(+a.dataset.i));
  const c = n.querySelector('a.cur'); if (c && c.scrollIntoView) c.scrollIntoView({block:'nearest'}); }
function prog(){ const done = D.items.filter(it => S.d[id(it)]).length;
  document.getElementById('bar').style.width = (100 * done / D.items.length) + '%';
  const y = D.items.filter(it => S.d[id(it)] === 'y').length;
  document.getElementById('cnt').textContent = done + ' / ' + D.items.length + ' decided · ' + y + ' y'; }
const gp = it => 'https://patents.google.com/patent/' + encodeURIComponent(it.rec);
const ep = it => 'https://worldwide.espacenet.com/patent/search?q=pn%3D' + encodeURIComponent(it.rec);
function card(){ const it = D.items[cur], d = S.d[id(it)] || '';
  const tabLab = tabs.find(t => t[0] === it.tab)[1];
  document.getElementById('card').innerHTML =
   '<div class="card"><div class="meta"><span class="pill">' + esc(tabLab) + '</span><span class="pill">' + esc(it.sub) + '</span><span>' + (cur + 1) + ' of ' + D.items.length + '</span><span>' + esc(it.rec) + ' · family ' + esc(it.fam) + '</span></div>' +
   '<h2>' + hl(it.title) + '</h2>' + (it.imgs.length ? '<div class="figs">' + it.imgs.map(u => '<img loading="lazy" src="' + encodeURI(u) + '" alt="drawing">').join('') + '</div>' : '<div class="nofig">No drawings online for this record. Use Espacenet (e).</div>') + '<div class="abs">' + hl(it.abs || '(no abstract)') + '</div>' +
   '<div class="cpc">CPC: ' + esc(it.cpc) + '</div>' +
   '<div class="links" style="margin-top:10px">' + (it.pdf ? '<a href="' + it.pdf + '" target="_blank" rel="noopener"><b>PDF (p)</b></a>' : '<span class="nofig">no PDF online</span> ') + '<a href="' + gp(it) + '" target="_blank" rel="noopener">Google Patents (o)</a><a href="' + ep(it) + '" target="_blank" rel="noopener">Espacenet (e)</a></div>' +
   '<div class="dec"><button class="btn y ' + (d === 'y' ? 'on' : '') + '" data-v="y">y · crewed multicopter</button><button class="btn n ' + (d === 'n' ? 'on' : '') + '" data-v="n">n · not</button><button class="btn q ' + (d === 'q' ? 'on' : '') + '" data-v="q">? · unclear</button></div>' +
   '<textarea id="note" placeholder="note (optional, needed for ?)">' + esc(S.note[id(it)] || '') + '</textarea></div>';
  document.querySelectorAll('.dec .btn').forEach(b => b.onclick = () => setDec(b.dataset.v));
  document.querySelectorAll('.figs img').forEach(im => im.onclick = () => { document.getElementById('zimg').src = im.src; document.getElementById('zoom').style.display = 'flex'; });
  document.getElementById('note').oninput = e => { S.note[id(it)] = e.target.value; persist(); }; }
function render(){ card(); prog(); nav(); }
function go(i){ cur = Math.max(0, Math.min(D.items.length - 1, i)); render(); try { window.scrollTo(0, 0); } catch (e) {} }
function setDec(v){ S.d[id(D.items[cur])] = v; persist(); if (v === 'q') { render(); document.getElementById('note').focus(); } else go(cur + 1); }
function nextTodo(){ for (let k = 1; k <= D.items.length; k++){ const i = (cur + k) % D.items.length; if (!S.d[id(D.items[i])]) return go(i); } }
document.getElementById('filter').onchange = nav;
document.getElementById('zoom').onclick = () => { document.getElementById('zoom').style.display = 'none'; };
document.addEventListener('keydown', e => {
  const typing = document.activeElement && document.activeElement.tagName === 'TEXTAREA';
  if (e.key === 'Escape'){ document.getElementById('zoom').style.display = 'none'; if (typing) document.activeElement.blur(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === 'y') return setDec('y'); if (e.key === 'n') return setDec('n'); if (e.key === '?') return setDec('q');
  if (e.key === 'ArrowRight') return go(cur + 1); if (e.key === 'ArrowLeft') return go(cur - 1);
  if (e.key === 'u') return nextTodo();
  if (e.key === 'p'){ const it = D.items[cur]; return window.open(it.pdf || ep(it), '_blank', 'noopener'); }
  if (e.key === 'o') return window.open(gp(D.items[cur]), '_blank', 'noopener');
  if (e.key === 'e') return window.open(ep(D.items[cur]), '_blank', 'noopener'); });
document.getElementById('save').onclick = () => {
  const q = v => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
  const rows = [['tab','subgroup','family_id','record','decision','note','title'].map(q).join(',')];
  D.items.forEach(it => rows.push([it.tab, it.sub, it.fam, it.rec, S.d[id(it)] || '', S.note[id(it)] || '', it.title].map(q).join(',')));
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([rows.join('\n')], {type:'text/csv'}));
  a.download = 'wm_review_decisions.csv'; a.click(); };
{ const f = D.items.findIndex(it => !S.d[id(it)]); go(f < 0 ? 0 : f); }
</script></body></html>"""

out = OUT_DIR / "REVIEW_crewed_multicopter.html"
out.write_text(HTML.replace("__DATA__", data), encoding="utf-8")
print(f"{len(items)} items -> {out}")
