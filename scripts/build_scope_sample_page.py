#!/usr/bin/env python3
"""Build the BLIND scope page for the 100-patent sample drawn by scope_make_sample.py.

The reviewer reads title + abstract + the full first claim and records the scope with the claim words
that decide it. No machine answer (SBERT, keyword rule, LLM reading) and no stratum is embedded in the
page, so the reviewer's label is independent of every method it is later used to score.

Input : 1639_LABELLED/text_scope/scope_sample_100.csv + the PatSeer export (Title, Abstract, First Claim,
        Independent Claims) + its cached pdf_links.csv
Output: Patent-Labelling-Tools/notebooks/post-process/scope_sample.html  (open with file://, no network)
Export: scope_sample_decisions.csv (Downloads) -> scope_evaluate_sample.py
"""
import json
import re
from pathlib import Path
import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling/inputs")   # 2026-09-17: stage-0 INPUTS of the 1639_LABELLED tree
OUT = ROOT.parent / "outputs"                                                                                   # what notebook 04 writes
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
SAMPLE = ROOT / "text_scope" / "scope_sample_100.csv"
# review pages live together in the repo; they embed their data and load figures by absolute file:// path
OUT = Path(__file__).resolve().parents[1] / "notebooks" / "post-process" / "scope_sample.html"

# the claim's transition word ends the preamble
_PREAMBLE_END = re.compile(r"\b(?:comprising|comprises|comprise|including|includes|having|consisting|"
                           r"characteri[sz]ed|wherein|which\s+comprises|the\s+improvement)\b|:", re.I)


def s(v) -> str:
    return "" if pd.isna(v) else str(v).strip()


def clean_claim(t: str) -> str:
    return re.sub(r"^\s*(?:\d+\s*\.\s*)+", "", t).strip()


def preamble(claim: str) -> str:
    m = _PREAMBLE_END.search(claim[:400])
    return claim[: m.end()].strip() if m else claim[:200].strip()


smp = pd.read_csv(SAMPLE)
ps = pd.read_excel(PATSEER, dtype=str,
                   usecols=["Record Number", "Title", "Abstract", "First Claim", "Independent Claims"]
                   ).set_index("Record Number")
pdf = pd.read_csv(PATSEER.with_suffix(".pdf_links.csv")).set_index("patent_id").pdf_link

data = []
for r in smp.itertuples():
    row = ps.loc[r.patent_id]
    claim = clean_claim(s(row["First Claim"]) or s(row["Independent Claims"]))
    indep = s(row["Independent Claims"])
    data.append({
        "n": int(r.page_order), "pid": r.patent_id, "title": s(row["Title"]), "abstract": s(row["Abstract"]),
        "claim": claim, "pre": preamble(claim) if claim else "",
        # other independent claims only when they add something beyond claim 1
        "indep": indep if indep and len(indep) > len(claim) + 40 else "",
        "pdf": s(pdf.get(r.patent_id, "")),
    })
print("rows:", len(data), "· no claim text:", [d["pid"] for d in data if not d["claim"]])

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Scope sample — blind check</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2128;--mut:#6b7280;--line:#e3e6ea;--acc:#2456c7;--ok:#1a8f4a;--mark:#fff1a8}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 Inter,system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;padding:8px 14px;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0 8px 0 0}header select,header button,header input{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:#fff}
header button{cursor:pointer}#prog{color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:270px 1fr;min-height:calc(100vh - 46px)}
#list{border-right:1px solid var(--line);background:#fff;overflow:auto;max-height:calc(100vh - 46px)}
#list div{padding:6px 10px;border-bottom:1px solid #f0f1f3;cursor:pointer;font-size:12.5px}
#list div.cur{background:#e8efff}#list div.done{color:var(--mut)}
#panel{padding:14px 18px;overflow:auto;max-width:1100px}
.rule{background:#fff;border:1px solid var(--line);border-radius:10px;padding:4px 14px;margin-bottom:12px;font-size:13px}
.rule summary{cursor:pointer;font-weight:600;padding:6px 0}.rule dt{font-weight:600;margin-top:6px}.rule dd{margin:2px 0 0 14px}
.head{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;margin-bottom:6px}.head h2{margin:0;font-size:18px}.head a{color:var(--acc)}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.card h3{margin:0 0 6px;font-size:12px;letter-spacing:.03em;text-transform:uppercase;color:var(--mut)}
.claim{white-space:pre-wrap}mark{background:var(--mark);padding:0 1px}
.cite{background:#f3f6fb;border-left:3px solid var(--acc);border-radius:4px;padding:8px 10px;font-size:13px;margin-top:6px}
.decide{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.decide button{font:inherit;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer}
.decide button.on{outline:2px solid var(--acc);background:#e8efff}.decide kbd{font-size:11px;color:var(--mut);margin-right:4px}
.decide input{font:inherit;flex:1;min-width:220px;padding:7px 8px;border:1px solid var(--line);border-radius:8px}
.mut{color:var(--mut)}.help{color:var(--mut);font-size:12px}
.ptitle{font-size:15.5px;font-weight:600;margin:4px 0 10px;line-height:1.3}
.ltitle{color:var(--mut);font-size:11px;display:block;margin-top:1px;line-height:1.25}
.pick{color:var(--acc);font-weight:600}
</style></head><body>
<header><h1>Scope — blind 100-patent check</h1>
<select id="view"><option value="todo">not decided yet</option><option value="all">all 100</option><option value="done">decided</option></select>
<span id="prog"></span>
<button id="exp">Export CSV</button><label style="font-size:12px">Import CSV <input type="file" id="imp" accept=".csv" style="width:170px"></label>
<button id="clr">Reset</button>
</header>
<main><div id="list"></div><div id="panel"></div></main>
<script>
const DATA=__DATA__;
const LABELS={W:'Whole Aircraft Architecture',S:'Architectural Subsystem Enabler',C:'Component-Level Generic',U:'cannot tell'};
const RULE=`<details class="rule"><summary>Decision rule and acceptance bar (fixed before labelling — read once)</summary>
<p>Scope is a property of the <b>patent</b>: what claim 1 claims. Read the <b>preamble</b> of claim 1 (the words before "comprising / having / wherein / :" — highlighted), then the claim body. The abstract is context only.</p>
<dl>
<dt>1 · Whole Aircraft Architecture</dt><dd>The claimed thing is the aircraft itself (aircraft, VTOL aircraft, air vehicle, rotorcraft, flying car…) <b>and</b> the body lays out the vehicle: its lifting surfaces and/or propulsors and how they are arranged.</dd>
<dt>2 · Architectural Subsystem Enabler</dt><dd>The claimed thing is a system, mechanism, assembly, arrangement or method (of operating, controlling, transitioning…) whose purpose is tied to a particular architecture: a tilt or fold mechanism, a propulsion arrangement, lift-rotor stowing, a transition control method. Also here: a preamble that names the aircraft but whose body adds only one subsystem to an otherwise unspecified aircraft.</dd>
<dt>Two-part claims ("…, characterised in that …")</dt><dd>Common in CN, EP and DE patents: the words before "characterised in that" restate the known art and the words after it are the invention. Judge the part <b>after</b>. An aircraft laid out in the first part whose characterising part is only a tilt drive or a rotor mechanism is a Subsystem Enabler; a characterising part that sets out the arrangement of wings and propulsors is Whole Aircraft.</dd>
<dt>3 · Component-Level Generic</dt><dd>A part that would fit any aircraft, with no architecture-specific context: a bearing, a battery cell, a motor winding, a seat, a fastener.</dd>
<dt>4 · Cannot tell</dt><dd>No claim text, or a translation too garbled to read.</dd>
</dl>
<p><b>Citation.</b> The highlighted preamble is saved as the citation by default. If other words decide it, select them in the claim and press <kbd>Q</kbd> (or the button).</p>
<p><b>Blind.</b> This page holds no machine answer. Do not open the 03a workbook or any scope column until the 100 are exported.</p>
<p><b>Acceptance bar (pre-registered).</b> SBERT scope is adequate for the remaining 595 patents only if, against these 100 decisions, the weighted accuracy has a 95% lower confidence bound ≥ 80% <b>and</b> Cohen's κ ≥ 0.6. Otherwise the LLM reading of claim 1 is used, with every citation confirmed.</p></details>`;
const KEY='scopesample_v1';let DEC={};try{DEC=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){DEC={}}
function save(){try{localStorage.setItem(KEY,JSON.stringify(DEC))}catch(e){}}
let VIEW='todo',CUR=0,ROWS=[];
const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function filterRows(){ROWS=DATA.filter(r=>VIEW==='all'||(VIEW==='todo'?!(DEC[r.pid]&&DEC[r.pid].choice):!!(DEC[r.pid]&&DEC[r.pid].choice)));if(CUR>=ROWS.length)CUR=Math.max(0,ROWS.length-1)}
function claimHTML(r,d){const cite=(d&&d.citation)||r.pre;const i=cite?r.claim.indexOf(cite):-1;
 return i<0?esc(r.claim):esc(r.claim.slice(0,i))+'<mark>'+esc(cite)+'</mark>'+esc(r.claim.slice(i+cite.length))}
function render(){filterRows();const L=document.getElementById('list');L.innerHTML='';
 ROWS.forEach((r,i)=>{const d=DEC[r.pid];const el=document.createElement('div');el.className=(i===CUR?'cur ':'')+(d&&d.choice?'done':'');
  el.innerHTML=`<span><b>${r.n}. ${esc(r.pid)}</b>${d&&d.choice?' <span class="pick">'+d.choice+'</span>':''}<br><span class="ltitle">${esc((r.title||'—').slice(0,70))}</span></span>`;el.onclick=()=>{CUR=i;render()};L.appendChild(el)});
 const n=DATA.filter(r=>DEC[r.pid]&&DEC[r.pid].choice).length;document.getElementById('prog').textContent=`${n} / ${DATA.length} decided · showing ${ROWS.length}`;
 const c=L.children[CUR];if(c)c.scrollIntoView({block:'nearest'});
 const P=document.getElementById('panel');const r=ROWS[CUR];
 if(!r){P.innerHTML=RULE+'<p class="help">Nothing in this view'+(n===DATA.length?' — all 100 decided. Press Export CSV.':'.')+'</p>';return}
 const d=DEC[r.pid]||{};
 P.innerHTML=RULE+`<div class="head"><h2>${r.n}. ${esc(r.pid)}</h2>${r.pdf?`<a href="${esc(r.pdf)}" target="_blank">PDF ↗</a>`:''}<a href="https://patents.google.com/patent/${esc(r.pid)}/en" target="_blank">Google Patents ↗</a></div>
 <div class="ptitle">${r.title?esc(r.title):'<i class="mut">no title in the export</i>'}</div>
 <div class="card"><h3>Claim 1</h3><div class="claim" id="claim">${r.claim?claimHTML(r,d):'<i class="mut">no claim text in the export — use the PDF, or choose Cannot tell</i>'}</div>
  ${r.indep?`<details style="margin-top:8px"><summary class="help">other independent claims</summary><div class="claim mut" style="font-size:13px">${esc(r.indep)}</div></details>`:''}</div>
 <div class="card"><h3>Abstract (context)</h3><div>${esc(r.abstract)||'<i class="mut">none</i>'}</div></div>
 <div class="card"><h3>Decision</h3><div class="decide">
  ${['W','S','C','U'].map((k,i)=>`<button data-c="${k}" class="${d.choice===k?'on':''}"><kbd>${i+1}</kbd>${LABELS[k]}</button>`).join('')}
  <button id="qsel"><kbd>Q</kbd>use selected words as citation</button>
  <input id="cmt" placeholder="comment (optional)" value="${esc(d.comment||'')}"></div>
  <div class="cite"><b>citation</b> (${d.citation_source==='selected'?'your selection':'claim-1 preamble'}): “${esc(d.citation||r.pre)}”</div></div>
 <p class="help">Keys 1–4 decide and move on · Q = selected words become the citation · ←/→ navigate · decisions stay in this browser until Export CSV.</p>`;
 P.querySelectorAll('.decide button[data-c]').forEach(b=>b.onclick=()=>decide(r,b.dataset.c));
 document.getElementById('qsel').onclick=()=>takeSelection(r);
 document.getElementById('cmt').onchange=e=>{DEC[r.pid]=Object.assign(DEC[r.pid]||{},{comment:e.target.value});save()};
}
function takeSelection(r){const t=String(window.getSelection()||'').replace(/\s+/g,' ').trim();if(!t){alert('Select words in the claim first.');return}
 DEC[r.pid]=Object.assign(DEC[r.pid]||{},{citation:t,citation_source:'selected'});save();render()}
function decide(r,c){const d=DEC[r.pid]||{};DEC[r.pid]=Object.assign(d,{choice:c,citation:d.citation||r.pre,citation_source:d.citation_source||'preamble',
 comment:(document.getElementById('cmt')||{}).value||d.comment||'',at:new Date().toISOString().slice(0,16)});save();
 if(VIEW!=='todo')CUR=Math.min(CUR+1,ROWS.length-1);render()}
document.getElementById('view').onchange=e=>{VIEW=e.target.value;CUR=0;render()};
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT'){if(e.key==='Enter')e.target.blur();return}
 const r=ROWS[CUR];if(!r)return;const k={'1':'W','2':'S','3':'C','4':'U'}[e.key];
 if(k)decide(r,k);else if(e.key==='q'||e.key==='Q')takeSelection(r);
 else if(e.key==='ArrowRight'){CUR=Math.min(CUR+1,ROWS.length-1);render()}else if(e.key==='ArrowLeft'){CUR=Math.max(CUR-1,0);render()}});
const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
const HDR=['page_order','patent_id','decision','scope_label','citation','citation_source','comment','decided_at'];
document.getElementById('exp').onclick=()=>{const lines=[HDR.join(',')];
 DATA.forEach(r=>{const d=DEC[r.pid];if(!d||!d.choice)return;lines.push([r.n,r.pid,d.choice,LABELS[d.choice],d.citation||r.pre,d.citation_source||'preamble',d.comment||'',d.at||''].map(q).join(','))});
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/csv'}));a.download='scope_sample_decisions.csv';a.click()};
function parseCSV(t){const out=[];let row=[],f='',i=0,Q=false;for(;i<t.length;i++){const c=t[i];
 if(Q){if(c==='"'){if(t[i+1]==='"'){f+='"';i++}else Q=false}else f+=c}
 else if(c==='"')Q=true;else if(c===','){row.push(f);f=''}else if(c==='\n'||c==='\r'){if(c==='\r'&&t[i+1]==='\n')i++;row.push(f);out.push(row);row=[];f=''}else f+=c}
 if(f||row.length){row.push(f);out.push(row)}return out}
document.getElementById('imp').onchange=e=>{const file=e.target.files[0];if(!file)return;const rd=new FileReader();
 rd.onload=()=>{const rows=parseCSV(rd.result);const h=rows.shift();let n=0;rows.forEach(c=>{const o=Object.fromEntries(h.map((k,i)=>[k,c[i]]));
  if(!o.patent_id||!o.decision)return;DEC[o.patent_id]={choice:o.decision,citation:o.citation,citation_source:o.citation_source,comment:o.comment,at:o.decided_at};n++});
  save();render();alert(n+' decisions imported')};rd.readAsText(file)};
document.getElementById('clr').onclick=()=>{if(confirm('Clear every decision saved in this browser?')){DEC={};save();render()}};
render();
</script></body></html>"""

OUT.write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
print("wrote", OUT, f"{OUT.stat().st_size / 1024:.0f} KB")
