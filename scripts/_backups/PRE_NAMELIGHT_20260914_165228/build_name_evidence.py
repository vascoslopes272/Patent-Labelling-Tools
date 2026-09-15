#!/usr/bin/env python3
"""Evidence for every aircraft-name proposal on the approved primary patents, and the review page (plan step D).

A row is written for each approved primary patent (D1/D2 duplicates inherit their root's name) that has
  (a) a machine name proposal (gazetteer attribution or SBERT text hit),
  (b) per-aircraft name proposals (patents that draw several aircraft), or
  (c) a name typed in the wizard that is not derived from the assignee (possible wizard slip or a real name).

For each candidate name the evidence is:
  - where the patent's own text names it: full-text search (title, abstract, claims, summary, drawings
    description, full Description) with the sentence quoted; a hit in the Description next to prior-art
    wording is labelled as such, because patents routinely name other companies' aircraft
  - the company's documented aircraft (gazetteer) with each one's public architecture and years
  - whether this patent's figure architecture (annotator topType) equals the candidate's public architecture
  - the patent's approved figures

Outputs:
  1639_LABELLED/joined/name_evidence_20260911.csv          one row per patent x candidate
  Patent-Labelling-Tools/notebooks/post-process/name_review.html   the review page
                                    (Export -> 1639_LABELLED/review_decisions/NAME_DECISIONS.csv -> build_identity_all.py)
"""
import json
import re
import sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.extractor import load_patseer_excel           # noqa: E402
from src.text_citation import (enrich_full_text, find_quote, literal_pattern,  # noqa: E402
                               SIGNAL_SECTIONS, SECTIONS)

ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
GAZ = REPO / "reference" / "evtol_gazetteer.csv"
KNOWN = ROOT / "text_architecture" / "known_aircraft_architecture.csv"
OUT_CSV = ROOT / "joined" / "name_evidence_20260911.csv"
OUT_HTML = REPO / "notebooks" / "post-process" / "name_review.html"
MAX_FIGS = 6
_PRIOR = re.compile(r"prior art|known|conventional|existing|such as|e\.g\.|for example|U\.?S\.? ?Pat|"
                    r"patent|background|previously|unlike|compared", re.I)
_SIGNAL_LABELS = {label for _, label in SIGNAL_SECTIONS}


def s(v) -> str:
    return "" if pd.isna(v) else str(v).strip()


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def assignee_derived(wizard_name: str, companies: list[str]) -> bool:
    base = norm(re.sub(r"\s*\d+[a-z]?$", "", wizard_name))
    return bool(base) and any(base[:6] in c or c[:6] in base for c in map(norm, companies) if c)


def main():
    idn = pd.read_excel(ROOT / "joined" / "aircraft_identity_ALL.xlsx", sheet_name="Identity")
    prim = idn[(idn.wizard_approved == True) & ~idn.wizard_duplicate_type.isin([1.0, 2.0])].copy()
    ml = pd.read_excel(ROOT / "joined" / "master_labels.xlsx",
                       usecols=["patent_id", "variant", "topType", "is_primary", "is_approved"])
    ml = ml[(ml.is_primary == True) & (ml.is_approved == True)]
    types = {pid: [s(t) for t in g.sort_values("variant").topType] for pid, g in ml.groupby("patent_id")}
    gaz = pd.read_csv(GAZ, comment=None)
    gaz = gaz[gaz.company_canonical != "#"]
    known = pd.read_csv(KNOWN)
    ktype = {(r.company, r.aircraft_name): s(r.known_type) for r in known.itertuples()}
    kbasis = {(r.company, r.aircraft_name): f"{s(r.confidence)} · {s(r.basis)}" for r in known.itertuples()}
    portfolio = {}
    for c, g in gaz.groupby("company_canonical"):
        portfolio[c] = [{"name": r.aircraft_name, "years": f"{int(r.year_from)}–{int(r.year_to)}",
                         "type": ktype.get((c, r.aircraft_name), ""), "basis": kbasis.get((c, r.aircraft_name), "")}
                        for r in g.itertuples()]

    rows = []
    for r in prim.itertuples():
        cands = []
        if s(r.aircraft_name_source) in ("gazetteer", "sbert"):
            cands.append((s(r.aircraft_name), s(r.aircraft_name_source)))
        for v in s(r.aircraft_name_variant_proposals).split(";"):
            if v.strip() and v.strip() not in [c for c, _ in cands]:
                cands.append((v.strip(), "variant proposal"))
        wiz = s(r.wizard_aircraft_name)
        mismatch = bool(wiz) and not assignee_derived(wiz, [s(r.company_canonical), s(r.assignee_raw)])
        if mismatch:
            cands.append((wiz, "wizard name, not the assignee"))
        for name, src in cands:
            rows.append({"patent_id": r.patent_id, "candidate": name, "source": src})
    ev = pd.DataFrame(rows)
    print("candidates:", len(ev), "patents:", ev.patent_id.nunique(), ev.source.value_counts().to_dict())

    index = load_patseer_excel(PATSEER)
    enrich_full_text(index, PATSEER)
    pdf = pd.read_csv(PATSEER.with_suffix(".pdf_links.csv")).set_index("patent_id").pdf_link
    mf = pd.read_excel(ROOT / "joined" / "master_figures.xlsx")
    mf = mf[(mf.status == "approved") & (mf.file_exists == True)]
    figs = {}
    for pid, g in mf.groupby("patent_id"):
        g = g.sort_values(["is_main", "arch"], ascending=[False, True]).head(MAX_FIGS)
        figs[pid] = [{"src": "file://" + str(x.image_path), "rot": int(x.rotation_deg or 0),
                      "arch": None if pd.isna(x.arch) else int(x.arch)} for x in g.itertuples()]

    by_pid = prim.set_index("patent_id")
    out = []
    for e in ev.itertuples():
        p = by_pid.loc[e.patent_id]
        meta = index.get(e.patent_id)
        hit = find_quote(meta, literal_pattern(e.candidate), sections=SECTIONS) if len(e.candidate) > 1 else None
        where = ""
        if hit:
            if hit["section"] in _SIGNAL_LABELS:
                where = "names it (" + hit["section"] + ")"
            elif _PRIOR.search(hit["quote"]):
                where = "Description, prior-art wording nearby"
            else:
                where = "Description"
        comp = s(p.company_canonical)
        port = portfolio.get(comp, [])
        ctype = ktype.get((comp, e.candidate), "")
        img = types.get(e.patent_id, [])
        out.append({
            "patent_id": e.patent_id, "batch": s(p.batch), "candidate": e.candidate, "source": e.source,
            "text_hit": where or "not in the text", "text_section": hit["section"] if hit else "",
            "text_quote": hit["quote"] if hit else "",
            "company": comp, "assignee": s(p.assignee_raw), "wizard_name": s(p.wizard_aircraft_name),
            "aircraft_group": s(p.aircraft_group), "n_aircraft": len(img) or 1,
            "image_types": "|".join(img), "candidate_public_type": ctype,
            "type_match": ("yes" if ctype and ctype in img else "no" if ctype else ""),
            "company_types_differ": "yes" if len({x["type"] for x in port if x["type"]}) > 1 else "",
            "company_portfolio": "; ".join(f'{x["name"]} ({x["years"]}, {x["type"] or "?"})' for x in port),
            "priority_year": "" if pd.isna(p.priority_year) else int(p.priority_year), "title": s(p.title),
        })
    df = pd.DataFrame(out)
    df.to_csv(OUT_CSV, index=False)
    print("wrote", OUT_CSV, df.text_hit.str.split(" ").str[0].value_counts().to_dict())

    data = []
    for pid, g in df.groupby("patent_id", sort=False):
        first = g.iloc[0]
        data.append({"pid": pid, "company": first.company, "assignee": first.assignee, "wizard": first.wizard_name,
                     "group": first.aircraft_group, "nvar": int(first.n_aircraft), "types": first.image_types,
                     "year": first.priority_year, "title": first.title, "pdf": s(pdf.get(pid, "")),
                     "portfolio": portfolio.get(first.company, []), "figs": figs.get(pid, []),
                     "cands": g[["candidate", "source", "text_hit", "text_section", "text_quote",
                                 "candidate_public_type", "type_match", "company_types_differ"]].to_dict("records")})
    OUT_HTML.write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str)), encoding="utf-8")
    print("wrote", OUT_HTML, len(data), "patents")


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Aircraft names — review</title>
<style>
:root{--bg:#f6f7f9;--ink:#1c2128;--mut:#6b7280;--line:#e3e6ea;--acc:#2456c7;--ok:#1a8f4a;--warn:#c2410c}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 Inter,system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;padding:8px 14px;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0 8px 0 0}header select,header button,header input{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:#fff}
#prog{color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:250px 1fr;min-height:calc(100vh - 46px)}
#list{border-right:1px solid var(--line);background:#fff;overflow:auto;max-height:calc(100vh - 46px)}
#list div{padding:5px 10px;border-bottom:1px solid #f0f1f3;cursor:pointer;font-size:12.5px}
#list div.cur{background:#e8efff}#list div.done{color:var(--mut)}
#panel{padding:14px 18px;overflow:auto}
.head{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline}.head h2{margin:0;font-size:18px}.head a{color:var(--acc)}
.mut{color:var(--mut)}.small{font-size:12.5px}
.figs{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.fig{background:#fff;border:1px solid var(--line);border-radius:8px;padding:5px}.fig img{max-width:300px;max-height:230px;display:block;cursor:zoom-in}
.fig small{color:var(--mut);font-size:11px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.card h3{margin:0 0 6px;font-size:16px}.tag{font-size:11px;padding:1px 6px;border-radius:4px;background:#eef;margin-left:6px}
.tag.ok{background:#dcfce7;color:#14532d}.tag.warn{background:#ffedd5;color:#7c2d12}
blockquote{margin:6px 0;padding:7px 10px;background:#f3f6fb;border-left:3px solid var(--acc);border-radius:4px;font-size:13px}
table{border-collapse:collapse;font-size:12.5px}td,th{border-bottom:1px solid var(--line);padding:3px 8px;text-align:left}
.decide{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.decide button{font:inherit;padding:7px 11px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer}
.decide button.on{outline:2px solid var(--acc);background:#e8efff}.decide button:disabled{opacity:.4}
.decide input{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:8px;min-width:260px}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:20}#zoom img{max-width:96vw;max-height:96vh;background:#fff}
</style></head><body>
<header><h1>Aircraft names — every proposal</h1>
<select id="view"><option value="todo">not decided</option><option value="all">all</option><option value="done">decided</option><option value="text">name found in the patent text</option><option value="wizard">wizard name ≠ assignee</option></select>
<span id="prog"></span><button id="exp">Export CSV</button>
<label style="font-size:12px">Import CSV <input type="file" id="imp" accept=".csv" style="width:170px"></label></header>
<main><div id="list"></div><div id="panel"></div></main><div id="zoom"><img></div>
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

const DATA=__DATA__;const KEY='namereview_v1';let DEC={};try{DEC=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){DEC={}}
function save(){try{localStorage.setItem(KEY,JSON.stringify(DEC))}catch(e){}}
const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LAB={text:'Keep — the patent text names it',known:'Keep — known aircraft (give the source)',other:'Other name',clear:'Clear → Assignee N',fix:'Fix wizard name'};
let VIEW='todo',CUR=0,ROWS=[];
const intext=r=>r.cands.some(c=>c.text_hit.startsWith('names it'));
function filt(){ROWS=DATA.filter(r=>{const d=DEC[r.pid];return VIEW==='all'||(VIEW==='todo'?!(d&&d.choice):VIEW==='done'?!!(d&&d.choice):VIEW==='text'?intext(r):r.cands.some(c=>c.source.startsWith('wizard')))});if(CUR>=ROWS.length)CUR=Math.max(0,ROWS.length-1)}
function render(){filt();const L=document.getElementById('list');L.innerHTML='';
 ROWS.forEach((r,i)=>{const d=DEC[r.pid];const el=document.createElement('div');el.className=(i===CUR?'cur ':'')+(d&&d.choice?'done':'');
  el.innerHTML=`<b>${esc(r.pid)}</b> <span class="mut">${esc(r.company)}</span><br><span class="small">${esc(r.cands.map(c=>c.candidate).join(' / '))}${d&&d.choice?' ✓ '+esc(d.choice):''}</span>`;el.onclick=()=>{CUR=i;render()};L.appendChild(el)});
 document.getElementById('prog').textContent=`${DATA.filter(r=>DEC[r.pid]&&DEC[r.pid].choice).length} / ${DATA.length} decided · showing ${ROWS.length}`;
 const c=L.children[CUR];if(c)c.scrollIntoView({block:'nearest'});
 const P=document.getElementById('panel');const r=ROWS[CUR];if(!r){P.innerHTML='<p class="mut">Nothing in this view.</p>';return}
 const d=DEC[r.pid]||{};const hasText=intext(r);const hasWiz=r.cands.some(c=>c.source.startsWith('wizard'));
 P.innerHTML=`<div class="head"><h2>${esc(r.pid)}</h2><span>${esc(r.company)} — <i>${esc(r.assignee)}</i></span>${r.pdf?`<a href="${esc(r.pdf)}" target="_blank">PDF ↗</a>`:''}<a href="https://patents.google.com/patent/${esc(r.pid)}/en" target="_blank">Google Patents ↗</a></div>
 <div class="mut small">${esc(r.title)} · ${esc(r.year)} · wizard name <b>${esc(r.wizard)}</b> · current group <b>${esc(r.group)}</b> · ${r.nvar} aircraft, figure types ${esc(r.types)}</div>
 <div class="figs">${r.figs.map(f=>`<div class="fig"><img src="${esc(f.src)}" style="transform:rotate(${f.rot}deg)" loading="lazy"><small>${f.arch?'aircraft '+f.arch:''}</small></div>`).join('')}</div>
 ${r.cands.map(c=>`<div class="card"><h3>${esc(c.candidate)}<span class="tag">${esc(c.source)}</span>
   ${c.text_hit.startsWith('names it')?'<span class="tag ok">'+esc(c.text_hit)+'</span>':c.text_hit==='not in the text'?'<span class="tag warn">not in the patent text</span>':'<span class="tag warn">'+esc(c.text_hit)+'</span>'}
   ${c.candidate_public_type?`<span class="tag ${c.type_match==='yes'?'ok':'warn'}">public type ${esc(c.candidate_public_type)} ${c.type_match==='yes'?'= figure type':'≠ figure type'}</span>`:''}
   ${c.company_types_differ?'<span class="tag warn">company aircraft differ in architecture</span>':''}</h3>
   ${c.text_quote?`<blockquote>“${esc(c.text_quote)}”</blockquote><div class="small mut">${esc(c.text_section)}</div>`:''}</div>`).join('')}
 ${r.portfolio.length?`<div class="card"><h3 style="font-size:13px">${esc(r.company)} — documented aircraft (gazetteer)</h3><table><tr><th>aircraft</th><th>years</th><th>public type</th><th>basis</th></tr>${r.portfolio.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.years)}</td><td>${esc(x.type)}</td><td class="mut">${esc(x.basis)}</td></tr>`).join('')}</table></div>`:''}
 <div class="card"><div class="decide">
  ${['text','known','other','clear','fix'].map(k=>`<button data-c="${k}" class="${d.choice===k?'on':''}" ${(k==='text'&&!hasText)||(k==='fix'&&!hasWiz)?'disabled':''}>${LAB[k]}</button>`).join('')}</div>
  <div class="decide" style="margin-top:8px"><input id="nm" placeholder="${r.nvar>1?'name(s) — one per aircraft separated by ;':'name'}" value="${esc(d.name||'')}">
  <input id="src" placeholder="source (required for known aircraft): URL, directory entry…" value="${esc(d.source||'')}">
  <input id="cmt" placeholder="comment" value="${esc(d.comment||'')}"></div>
  <p class="small mut">Keep a real name only when the patent's own text names it as the depicted aircraft, or when a documented aircraft matches the figures and its public architecture (give the source). Otherwise clear: the aircraft keeps the generated Assignee N (+ letter per aircraft).</p></div>`;
 P.querySelectorAll('.decide button').forEach(b=>b.onclick=()=>decide(r,b.dataset.c));
 ['nm','src','cmt'].forEach(id=>document.getElementById(id).onchange=e=>{DEC[r.pid]=Object.assign(DEC[r.pid]||{},{[{nm:'name',src:'source',cmt:'comment'}[id]]:e.target.value});save()});
 P.querySelectorAll('.fig img').forEach(im=>im.onclick=()=>{const z=document.getElementById('zoom');z.querySelector('img').src=im.src;z.querySelector('img').style.transform=im.style.transform;z.style.display='flex'});
}
function decide(r,c){const nm=document.getElementById('nm').value,src=document.getElementById('src').value;
 if(c==='known'&&!src.trim()){alert('Give the source for a known-aircraft name first.');return}
 if((c==='other'||c==='fix')&&!nm.trim()){alert('Type the name first.');return}
 let name=nm;if(c==='text'&&!nm.trim())name=r.cands.find(x=>x.text_hit.startsWith('names it')).candidate;
 if(c==='known'&&!nm.trim())name=r.cands[0].candidate;if(c==='clear')name='';
 DEC[r.pid]={choice:c,name,source:src,comment:document.getElementById('cmt').value,at:new Date().toISOString().slice(0,16)};save();
 if(VIEW!=='todo')CUR=Math.min(CUR+1,ROWS.length-1);render()}
document.getElementById('view').onchange=e=>{VIEW=e.target.value;CUR=0;render()};
document.getElementById('zoom').onclick=e=>e.currentTarget.style.display='none';
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.key==='ArrowRight'){CUR=Math.min(CUR+1,ROWS.length-1);render()}else if(e.key==='ArrowLeft'){CUR=Math.max(CUR-1,0);render()}});
const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
document.getElementById('exp').onclick=()=>{const L=[['patent_id','decision','name_final','source_note','candidates','comment','decided_at'].join(',')];
 DATA.forEach(r=>{const d=DEC[r.pid];if(!d||!d.choice)return;L.push([r.pid,d.choice,d.name,d.source,r.cands.map(c=>c.candidate).join(' / '),d.comment,d.at].map(q).join(','))});
 saveToFolder(new Blob([L.join('\n')],{type:'text/csv'}),'NAME_DECISIONS.csv')};
function parseCSV(t){const out=[];let row=[],f='',Q=false;for(let i=0;i<t.length;i++){const c=t[i];
 if(Q){if(c==='"'){if(t[i+1]==='"'){f+='"';i++}else Q=false}else f+=c}else if(c==='"')Q=true;else if(c===','){row.push(f);f=''}
 else if(c==='\n'||c==='\r'){if(c==='\r'&&t[i+1]==='\n')i++;row.push(f);out.push(row);row=[];f=''}else f+=c}if(f||row.length){row.push(f);out.push(row)}return out}
document.getElementById('imp').onchange=e=>{const fl=e.target.files[0];if(!fl)return;const rd=new FileReader();rd.onload=()=>{const rows=parseCSV(rd.result);const h=rows.shift();let n=0;
 rows.forEach(c=>{const o=Object.fromEntries(h.map((k,i)=>[k,c[i]]));if(!o.patent_id||!o.decision)return;DEC[o.patent_id]={choice:o.decision,name:o.name_final,source:o.source_note,comment:o.comment,at:o.decided_at};n++});save();render();alert(n+' decisions imported')};rd.readAsText(fl)};
render();
</script></body></html>"""

if __name__ == "__main__":
    main()
