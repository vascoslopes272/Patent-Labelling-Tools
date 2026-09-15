#!/usr/bin/env python3
"""Build the scope review page for EVERY approved patent (1 110): one yes / no question per patent —
does claim 1 claim a WHOLE AIRCRAFT?

Why binary (user, 2026-09-13): the blind 100-patent sample showed neither SBERT (κ 0.06) nor the LLM
claim-1 reading (κ 0.26) is good enough, and the reviewer used Component-Level Generic only 5 times in 96,
so the subsystem / component boundary carried the doubt and almost no information. "Not whole aircraft"
merges Architectural Subsystem Enabler and Component-Level Generic.

The page holds NO machine answer (no SBERT, no LLM label or quote), so these 1 110 labels stay independent
of every method they may later be used to score. Kept from the sample page: title + abstract + full claim 1,
preamble highlighted, citation = preamble unless you select other words (Q), same decision rule.

Speed-ups, none of which decide anything for you:
  · the 100 blind-sample answers are pre-filled (W -> Yes, S/C -> No, cannot tell -> cannot tell);
  · duplicates sit right after their original, with "D2 of X" shown;
  · a claim 1 word-for-word identical to one you already answered says so, and Enter copies that answer.

Input : 1639_LABELLED/joined/aircraft_identity_ALL.xlsx (approved, batch, duplicate links)
        PatSeer export (Title, Abstract, First Claim, Independent Claims) + its pdf_links.csv
        1639_LABELLED/text_scope/scope_sample_decisions_20260913.csv (pre-fill)
Output: Patent-Labelling-Tools/notebooks/post-process/scope_all.html  (open with file://, no network)
Export: 1639_LABELLED/review_decisions/scope_all_decisions.csv (save dialog; Downloads if unavailable)
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
IDENTITY = ROOT / "joined" / "aircraft_identity_ALL.xlsx"
SAMPLE_DECISIONS = ROOT / "text_scope" / "scope_sample_decisions_20260913.csv"
OUT = Path(__file__).resolve().parents[1] / "notebooks" / "post-process" / "scope_all.html"

_PREAMBLE_END = re.compile(r"\b(?:comprising|comprises|comprise|including|includes|having|consisting|"
                           r"characteri[sz]ed|wherein|which\s+comprises|the\s+improvement)\b|:", re.I)
# two-part claims: the words after this are the invention
_CHARACTERISED = re.compile(r"\bcharacteri[sz]ed\s+(?:in\s+that|by)\b|\bthe\s+improvement\s+comprising\b", re.I)
SAMPLE_MAP = {"W": "Y", "S": "N", "C": "N", "U": "U"}


def s(v) -> str:
    return "" if pd.isna(v) else str(v).strip()


def clean_claim(t: str) -> str:
    return re.sub(r"^\s*(?:\d+\s*\.\s*)+", "", t).strip()


def preamble(claim: str) -> str:
    m = _PREAMBLE_END.search(claim[:400])
    return claim[: m.end()].strip() if m else claim[:200].strip()


def split_two_part(claim: str) -> int:
    """Index where the characterising part starts, or -1."""
    m = _CHARACTERISED.search(claim)
    return m.start() if m else -1


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def main() -> None:
    idn = pd.read_excel(IDENTITY, sheet_name="Identity", dtype=object)
    idn = idn[idn.wizard_approved == True].copy()                                  # noqa: E712
    ps = pd.read_excel(PATSEER, dtype=str,
                       usecols=["Record Number", "Title", "Abstract", "First Claim", "Independent Claims"]
                       ).set_index("Record Number")
    pdf = pd.read_csv(PATSEER.with_suffix(".pdf_links.csv")).set_index("patent_id").pdf_link
    sample = {}
    if SAMPLE_DECISIONS.exists():
        sd = pd.read_csv(SAMPLE_DECISIONS, keep_default_na=False)
        for r in sd.itertuples():
            sample[r.patent_id] = {"choice": SAMPLE_MAP.get(r.decision, "U"), "citation": r.citation,
                                   "citation_source": r.citation_source, "comment": r.comment,
                                   "at": r.decided_at, "origin": "sample", "sample3": r.decision}

    # originals first, each followed by its duplicates; batches in order
    idn["root"] = [s(r) or p for r, p in zip(idn.duplicate_root, idn.patent_id)]
    idn["is_dup"] = idn.wizard_duplicate_type.isin(["1", "2", "3"])
    root_batch = idn.drop_duplicates("patent_id").set_index("patent_id").batch
    idn["root_batch"] = [root_batch.get(r, b) for r, b in zip(idn.root, idn.batch)]
    idn = idn.sort_values(["root_batch", "root", "is_dup", "batch", "patent_id"])

    data, seen_claim = [], {}
    for n, r in enumerate(idn.itertuples(), 1):
        row = ps.loc[r.patent_id] if r.patent_id in ps.index else None
        claim = clean_claim(s(row["First Claim"]) or s(row["Independent Claims"])) if row is not None else ""
        indep = s(row["Independent Claims"]) if row is not None else ""
        key = norm(claim)
        twin = seen_claim.get(key) if key else None
        if key and key not in seen_claim:
            seen_claim[key] = r.patent_id
        data.append({
            "n": n, "pid": r.patent_id, "batch": s(r.batch),
            "title": s(row["Title"]) if row is not None else "",
            "abstract": s(row["Abstract"]) if row is not None else "",
            "claim": claim, "pre": preamble(claim) if claim else "", "cut": split_two_part(claim),
            "indep": indep if indep and len(indep) > len(claim) + 40 else "",
            "pdf": s(pdf.get(r.patent_id, "")),
            "dup": (f"D{s(r.wizard_duplicate_type)} of {s(r.wizard_duplicate_of)}" if r.is_dup else ""),
            "twin": twin or "",
        })
    OUT.write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
                       .replace("__SAMPLE__", json.dumps(sample, ensure_ascii=False)), encoding="utf-8")
    print(f"rows {len(data)} · duplicates {int(idn.is_dup.sum())} · identical claim 1 to an earlier row "
          f"{sum(1 for d in data if d['twin'])} · two-part claims {sum(1 for d in data if d['cut'] >= 0)} · "
          f"no claim text {sum(1 for d in data if not d['claim'])} · pre-filled from the sample {len(sample)}")
    print("wrote", OUT, f"{OUT.stat().st_size / 1024:.0f} KB")


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Scope — whole aircraft?</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2128;--mut:#6b7280;--line:#e3e6ea;--acc:#2456c7;--yes:#1a8f4a;--no:#b4532a;--mark:#fff1a8}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 Inter,system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;padding:8px 14px;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0 8px 0 0}header select,header button,header input{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:#fff}
header button{cursor:pointer}#prog{color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:270px 1fr;min-height:calc(100vh - 46px)}
#list{border-right:1px solid var(--line);background:#fff;overflow:auto;max-height:calc(100vh - 46px)}
#list div{padding:6px 10px;border-bottom:1px solid #f0f1f3;cursor:pointer;font-size:12.5px}
#list div.cur{background:#e8efff}#list div.done{color:var(--mut)}#list div.dupl{padding-left:22px}
#panel{padding:14px 18px;overflow:auto;max-width:1100px}
.rule{background:#fff;border:1px solid var(--line);border-radius:10px;padding:4px 14px;margin-bottom:12px;font-size:13px}
.rule summary{cursor:pointer;font-weight:600;padding:6px 0}.rule dt{font-weight:600;margin-top:6px}.rule dd{margin:2px 0 0 14px}
.head{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;margin-bottom:6px}.head h2{margin:0;font-size:18px}.head a{color:var(--acc)}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.card h3{margin:0 0 6px;font-size:12px;letter-spacing:.03em;text-transform:uppercase;color:var(--mut)}
.claim{white-space:pre-wrap}mark{background:var(--mark);padding:0 1px}.charpart{font-weight:600;border-bottom:2px solid #c9d6f5}
.cite{background:#f3f6fb;border-left:3px solid var(--acc);border-radius:4px;padding:8px 10px;font-size:13px;margin-top:6px}
.decide{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.decide button{font:inherit;padding:10px 16px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer}
.decide button.on{outline:2px solid var(--acc);background:#e8efff}.decide kbd{font-size:11px;color:var(--mut);margin-right:4px}
.decide input{font:inherit;flex:1;min-width:220px;padding:7px 8px;border:1px solid var(--line);border-radius:8px}
.mut{color:var(--mut)}.help{color:var(--mut);font-size:12px}
.ptitle{font-size:15.5px;font-weight:600;margin:4px 0 10px;line-height:1.3}
.ltitle{color:var(--mut);font-size:11px;display:block;margin-top:1px;line-height:1.25}
.pick{font-weight:700}.pY{color:var(--yes)}.pN{color:var(--no)}.pU{color:var(--mut)}
.note{background:#fff8e6;border:1px solid #f1d9a6;border-radius:8px;padding:6px 10px;font-size:13px;margin-bottom:10px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;background:#eef1f5;color:var(--mut)}
</style></head><body>
<header><h1>Scope — does claim 1 claim a whole aircraft?</h1>
<select id="batch"></select>
<select id="view"><option value="todo">not decided yet</option><option value="all">all</option><option value="done">decided</option><option value="sample">from your blind sample</option></select>
<span id="prog"></span>
<button id="exp">Export CSV</button><label style="font-size:12px">Import CSV <input type="file" id="imp" accept=".csv" style="width:170px"></label>
<button id="clr">Reset</button>
</header>
<main><div id="list"></div><div id="panel"></div></main>
<script>
// Save straight into 1639_LABELLED/review_decisions (request 2026-09-14). Chrome's save dialog opens on the
// folder chosen last time for this id, so after the first save it lands there by default. Browsers without
// the save dialog fall back to a normal download.
function saveToFolder(blob, name){
  function fallback(){ var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; a.click(); return Promise.resolve('downloads'); }
  if (!window.showSaveFilePicker) return fallback();
  return window.showSaveFilePicker({suggestedName: name, id: 'review_decisions'})
    .then(function(h){ return h.createWritable().then(function(w){ return w.write(blob).then(function(){ return w.close(); }); }); })
    .then(function(){ return 'folder'; })
    .catch(function(e){ return (e && e.name === 'AbortError') ? 'cancelled' : fallback(); });
}

const DATA=__DATA__;
const SAMPLE=__SAMPLE__;
const LABELS={Y:'Whole aircraft',N:'Not whole aircraft',U:'cannot tell'};
const RULE=`<details class="rule"><summary>Decision rule (same as the blind sample, merged to yes / no — read once)</summary>
<p>Scope is a property of the <b>patent</b>: what claim 1 claims. Read the <b>preamble</b> (highlighted), then the body. The abstract is context only.</p>
<dl>
<dt>1 · Yes — whole aircraft</dt><dd>The claimed thing is the aircraft itself (aircraft, VTOL aircraft, air vehicle, rotorcraft, flying car…) <b>and</b> the body lays out the vehicle: its lifting surfaces and/or propulsors and how they are arranged.</dd>
<dt>2 · No — not whole aircraft</dt><dd>A system, mechanism, assembly, arrangement, method (operating, controlling, transitioning…) or a part — whether or not it is tied to one architecture. Also No: a preamble that names the aircraft but whose body adds only <b>one subsystem</b> to an otherwise unspecified aircraft.</dd>
<dt>Two-part claims ("…, characterised in that …")</dt><dd>The words before "characterised in that" restate the known art; the part after (shown in bold) is the invention. Judge the part <b>after</b>: only a tilt drive or a rotor mechanism → No; the arrangement of wings and propulsors → Yes.</dd>
<dt>3 · Cannot tell</dt><dd>No claim text, or a translation too garbled to read.</dd>
</dl>
<p><b>Citation.</b> The highlighted words are saved as the citation (the preamble, or the characterising part of a two-part claim). If other words decide it, select them and press <kbd>Q</kbd>.</p>
<p><b>No machine answer is on this page</b>, so your labels stay independent of SBERT and the LLM reading.</p></details>`;
const KEY='scopeall_v1';let DEC={};try{DEC=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){DEC={}}
// the blind-sample answers seed the page once; anything you change here wins
Object.keys(SAMPLE).forEach(p=>{if(!DEC[p])DEC[p]=Object.assign({},SAMPLE[p])});
function save(){try{localStorage.setItem(KEY,JSON.stringify(DEC))}catch(e){}}
save();
let VIEW='todo',BATCH='all',CUR=0,ROWS=[];
const BY=Object.fromEntries(DATA.map(r=>[r.pid,r]));
const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const decided=r=>!!(DEC[r.pid]&&DEC[r.pid].choice);
function defaultCite(r){return r.cut>=0?r.claim.slice(r.cut,r.cut+260).trim():r.pre}
function filterRows(){ROWS=DATA.filter(r=>(BATCH==='all'||r.batch===BATCH)&&(VIEW==='all'||(VIEW==='todo'?!decided(r):VIEW==='done'?decided(r):(DEC[r.pid]||{}).origin==='sample')));
 if(CUR>=ROWS.length)CUR=Math.max(0,ROWS.length-1)}
function claimHTML(r,d){let body=r.claim;const cite=(d&&d.citation)||defaultCite(r);
 // bold the characterising part of a two-part claim, then highlight the citation inside the plain text
 const parts=r.cut>=0?[[body.slice(0,r.cut),false],[body.slice(r.cut),true]]:[[body,false]];
 return parts.map(([t,ch])=>{const i=cite?t.indexOf(cite):-1;const h=i<0?esc(t):esc(t.slice(0,i))+'<mark>'+esc(cite)+'</mark>'+esc(t.slice(i+cite.length));
  return ch?'<span class="charpart">'+h+'</span>':h}).join('')}
function twinNote(r){if(!r.twin)return'';const t=DEC[r.twin];
 return `<div class="note">Claim 1 is word-for-word the same as <b>${esc(r.twin)}</b>${t&&t.choice?`, which you answered <b class="p${t.choice}">${LABELS[t.choice]}</b> — press <kbd>Enter</kbd> to give the same answer`:' (not answered yet)'}.</div>`}
function render(){filterRows();const L=document.getElementById('list');L.innerHTML='';
 ROWS.forEach((r,i)=>{const d=DEC[r.pid];const el=document.createElement('div');el.className=(i===CUR?'cur ':'')+(decided(r)?'done ':'')+(r.dup?'dupl':'');
  el.innerHTML=`<span><b>${r.n}. ${esc(r.pid)}</b>${d&&d.choice?' <span class="pick p'+d.choice+'">'+(d.choice==='Y'?'yes':d.choice==='N'?'no':'?')+'</span>':''}<br><span class="ltitle">${r.dup?esc(r.dup)+' · ':''}${esc((r.title||'—').slice(0,64))}</span></span>`;
  el.onclick=()=>{CUR=i;render()};L.appendChild(el)});
 const scope=DATA.filter(r=>BATCH==='all'||r.batch===BATCH);const n=scope.filter(decided).length;
 document.getElementById('prog').textContent=`${n} / ${scope.length} decided${BATCH==='all'?'':' in '+BATCH} · showing ${ROWS.length}`;
 const c=L.children[CUR];if(c)c.scrollIntoView({block:'nearest'});
 const P=document.getElementById('panel');const r=ROWS[CUR];
 if(!r){P.innerHTML=RULE+'<p class="help">Nothing in this view'+(n===scope.length?' — everything here is decided. Press Export CSV.':'.')+'</p>';return}
 const d=DEC[r.pid]||{};
 P.innerHTML=RULE+`<div class="head"><h2>${r.n}. ${esc(r.pid)}</h2><span class="tag">${esc(r.batch)}</span>${r.dup?'<span class="tag">'+esc(r.dup)+'</span>':''}${d.origin==='sample'?'<span class="tag">from your blind sample ('+esc(d.sample3)+')</span>':''}
  ${r.pdf?`<a href="${esc(r.pdf)}" target="_blank">PDF ↗</a>`:''}<a href="https://patents.google.com/patent/${esc(r.pid)}/en" target="_blank">Google Patents ↗</a></div>
 <div class="ptitle">${r.title?esc(r.title):'<i class="mut">no title in the export</i>'}</div>
 ${twinNote(r)}
 <div class="card"><h3>Claim 1${r.cut>=0?' <span class="tag">two-part claim — judge the bold part</span>':''}</h3><div class="claim" id="claim">${r.claim?claimHTML(r,d):'<i class="mut">no claim text in the export — use the PDF, or choose Cannot tell</i>'}</div>
  ${r.indep?`<details style="margin-top:8px"><summary class="help">other independent claims</summary><div class="claim mut" style="font-size:13px">${esc(r.indep)}</div></details>`:''}</div>
 <div class="card"><h3>Decision</h3><div class="decide">
  ${['Y','N','U'].map((k,i)=>`<button data-c="${k}" class="${d.choice===k?'on':''}"><kbd>${i+1}</kbd>${LABELS[k]}</button>`).join('')}
  <button id="qsel"><kbd>Q</kbd>use selected words as citation</button>
  <input id="cmt" placeholder="comment (optional)" value="${esc(d.comment||'')}"></div>
  <div class="cite"><b>citation</b> (${d.citation_source==='selected'?'your selection':r.cut>=0?'characterising part':'claim-1 preamble'}): “${esc(d.citation||defaultCite(r))}”</div></div>
 <details class="card"><summary class="help" style="cursor:pointer">abstract (context)</summary><div style="margin-top:6px">${esc(r.abstract)||'<i class="mut">none</i>'}</div></details>
 <p class="help">1 yes · 2 no · 3 cannot tell (each moves on) · Enter = same answer as the identical claim · Q = selected words become the citation · ←/→ navigate · stays in this browser until Export CSV.</p>`;
 P.querySelectorAll('.decide button[data-c]').forEach(b=>b.onclick=()=>decide(r,b.dataset.c));
 document.getElementById('qsel').onclick=()=>takeSelection(r);
 document.getElementById('cmt').onchange=e=>{DEC[r.pid]=Object.assign(DEC[r.pid]||{},{comment:e.target.value});save()};
}
function takeSelection(r){const t=String(window.getSelection()||'').replace(/\s+/g,' ').trim();if(!t){alert('Select words in the claim first.');return}
 DEC[r.pid]=Object.assign(DEC[r.pid]||{},{citation:t,citation_source:'selected'});save();render()}
function decide(r,c,extra){const d=DEC[r.pid]||{};const src=r.cut>=0?'characterising':'preamble';
 DEC[r.pid]=Object.assign(d,{choice:c,citation:d.citation||defaultCite(r),citation_source:d.citation_source||src,
  comment:(document.getElementById('cmt')||{}).value||d.comment||'',at:new Date().toISOString().slice(0,16),origin:d.origin==='sample'?'sample_edited':'page'},extra||{});save();
 if(VIEW!=='todo')CUR=Math.min(CUR+1,ROWS.length-1);render()}
function fillBatch(){const b=[...new Set(DATA.map(r=>r.batch))].sort();document.getElementById('batch').innerHTML='<option value="all">all batches</option>'+b.map(x=>`<option>${x}</option>`).join('')}
document.getElementById('batch').onchange=e=>{BATCH=e.target.value;CUR=0;render()};
document.getElementById('view').onchange=e=>{VIEW=e.target.value;CUR=0;render()};
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT'){if(e.key==='Enter')e.target.blur();return}
 const r=ROWS[CUR];if(!r)return;const k={'1':'Y','2':'N','3':'U'}[e.key];
 if(k)decide(r,k);else if(e.key==='q'||e.key==='Q')takeSelection(r);
 else if(e.key==='Enter'&&r.twin&&DEC[r.twin]&&DEC[r.twin].choice)decide(r,DEC[r.twin].choice,{comment:'same claim 1 as '+r.twin});
 else if(e.key==='ArrowRight'){CUR=Math.min(CUR+1,ROWS.length-1);render()}else if(e.key==='ArrowLeft'){CUR=Math.max(CUR-1,0);render()}});
const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
const HDR=['order','patent_id','batch','decision','scope_binary','citation','citation_source','comment','decided_at','origin','sample_3class'];
function buildCSV(){const lines=[HDR.join(',')];
 DATA.forEach(r=>{const d=DEC[r.pid];if(!d||!d.choice)return;
  lines.push([r.n,r.pid,r.batch,d.choice,LABELS[d.choice],d.citation||defaultCite(r),d.citation_source||(r.cut>=0?'characterising':'preamble'),d.comment||'',d.at||'',d.origin||'page',d.sample3||''].map(q).join(','))});
 return lines.join('\n')}
document.getElementById('exp').onclick=()=>{saveToFolder(new Blob([buildCSV()],{type:'text/csv'}),'scope_all_decisions.csv')};
function parseCSV(t){const out=[];let row=[],f='',i=0,Q=false;for(;i<t.length;i++){const c=t[i];
 if(Q){if(c==='"'){if(t[i+1]==='"'){f+='"';i++}else Q=false}else f+=c}
 else if(c==='"')Q=true;else if(c===','){row.push(f);f=''}else if(c==='\n'||c==='\r'){if(c==='\r'&&t[i+1]==='\n')i++;row.push(f);out.push(row);row=[];f=''}else f+=c}
 if(f||row.length){row.push(f);out.push(row)}return out}
document.getElementById('imp').onchange=e=>{const file=e.target.files[0];if(!file)return;const rd=new FileReader();
 rd.onload=()=>{const rows=parseCSV(rd.result);const h=rows.shift();let n=0;rows.forEach(c=>{const o=Object.fromEntries(h.map((k,i)=>[k,c[i]]));
  if(!o.patent_id||!o.decision||!BY[o.patent_id])return;DEC[o.patent_id]={choice:o.decision,citation:o.citation,citation_source:o.citation_source,comment:o.comment,at:o.decided_at,origin:o.origin,sample3:o.sample_3class};n++});
  save();render();alert(n+' decisions imported')};rd.readAsText(file)};
document.getElementById('clr').onclick=()=>{if(confirm('Clear every decision saved in this browser? (the blind-sample answers come back pre-filled)')){localStorage.removeItem(KEY);location.reload()}};
fillBatch();render();
</script></body></html>"""

if __name__ == "__main__":
    main()
