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


# words that mark a sentence as talking about OTHER aircraft (an example, a known design, prior art)
_OTHERS = re.compile(r"prior art|known|conventional|existing|such as|e\.g\.|for example|examples? of|"
                     r"well-known|offered by|developing|attempts? to overcome|limitation of|than either|"
                     r"include the|from [A-Z]", re.I)
# words that mark a sentence as talking about THIS patent's aircraft
_OWN = re.compile(r"embodiment|photograph of the|the present|of the invention|according to|shows the|"
                  r"this aircraft|our aircraft|referred to as", re.I)


def light_for(c: dict, company: str, assignee: str) -> tuple[str, str, str]:
    """(colour, reason, suggestion) for one candidate name.
    green = the evidence points one way (almost always: clear the proposal); yellow = a real judgement,
    usually a documented aircraft whose public type equals the figures; red = the wizard name belongs to
    someone else."""
    src, hit, q, tm = c["source"], c["text_hit"], c["text_quote"], c["type_match"]
    if src.startswith("wizard"):
        # compare in any script (Korean, Cyrillic…), and by first word ("Bell Helicopter 9" vs BELL TEXTRON)
        clean = lambda t: re.sub(r"[\W_]+", " ", str(t).lower(), flags=re.UNICODE).split()
        base = clean(re.sub(r"\s*\d+[a-z]?$", "", c["candidate"]))
        owners = [clean(assignee), clean(company)]
        joined = " ".join(base)
        if base and any(joined and (joined in " ".join(o) or (len(base[0]) >= 3 and o and base[0] == o[0]))
                        for o in owners if o):
            return "green", "the wizard name is the assignee's own name", "clear"
        return "red", "the wizard name does not match this patent's assignee", "fix"
    if hit == "not in the text":
        if tm == "yes":
            why = "not in the patent text, but the company's documented aircraft has the same architecture as the figures"
            return "yellow", why + (" (the company's aircraft differ in architecture)" if c["company_types_differ"] else ""), "known"
        return "green", ("not in the patent text, and its public architecture differs from the figures" if tm == "no"
                         else "not in the patent text"), "clear"
    if _OTHERS.search(q) and not _OWN.search(q):
        return "green", "the text mentions it as another aircraft or an example", "clear"
    if src == "sbert" and not _OWN.search(q):
        return "green", "a word the text search picked up, not an aircraft this patent depicts", "clear"
    return "yellow", "the text may name this patent's own aircraft — read the sentence", "text"


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

    # Ruling 2026-09-14 (user: "two options there, and I don't know to which aircraft it really is"): a name
    # is only a question when the patent's own text may name it, or the wizard name belongs to someone else.
    # Company-list guesses (company + filing year, even when the public architecture matches), prior-art
    # mentions, SBERT word hits and assignee-derived wizard names are cleared automatically, never shown.
    data, auto = [], []
    ORDER = {"green": 0, "yellow": 1, "red": 2}
    for pid, g in df.groupby("patent_id", sort=False):
        first = g.iloc[0]
        cands = g[["candidate", "source", "text_hit", "text_section", "text_quote",
                   "candidate_public_type", "type_match", "company_types_differ"]].to_dict("records")
        for c in cands:
            c["light"], c["why"], c["sugg"] = light_for(c, first.company, first.assignee)
        dropped = [c for c in cands if c["sugg"] in ("clear", "known")]
        cands = [c for c in cands if c["sugg"] not in ("clear", "known")]
        if not cands:
            auto.append({"pid": pid, "cands": " / ".join(c["candidate"] for c in dropped),
                         "why": "; ".join(sorted({c["why"] for c in dropped}))})
            continue
        worst = max(cands, key=lambda c: ORDER[c["light"]])
        plight = worst["light"]
        # the whole patent can be settled from a list only when every candidate says "clear"
        psugg = "clear" if all(c["sugg"] == "clear" for c in cands) else worst["sugg"]
        data.append({"pid": pid, "company": first.company, "assignee": first.assignee, "wizard": first.wizard_name,
                     "group": first.aircraft_group, "nvar": int(first.n_aircraft), "types": first.image_types,
                     "year": first.priority_year, "title": first.title, "pdf": s(pdf.get(pid, "")),
                     "portfolio": portfolio.get(first.company, []), "figs": figs.get(pid, []),
                     "light": plight, "sugg": psugg, "why": worst["why"], "cands": cands})
    from collections import Counter
    print("to review per patent:", Counter(d["light"] for d in data), "· auto-cleared patents:", len(auto))
    OUT_HTML.write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str))
                        .replace("__AUTO__", json.dumps(auto, ensure_ascii=False, default=str)), encoding="utf-8")
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
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle}
.Lgreen{background:#16a34a}.Lyellow{background:#eab308}.Lred{background:#dc2626}
.band{border-radius:10px;padding:10px 14px;margin:10px 0;display:flex;gap:10px;align-items:center;font-size:14px}
.band.green{background:#dcfce7;border:1px solid #86efac}.band.yellow{background:#fef9c3;border:1px solid #fde047}.band.red{background:#fee2e2;border:1px solid #fca5a5}
mark{background:#fde68a;padding:0 2px;border-radius:3px}
table.batch{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line)}
table.batch td{border-top:1px solid #eef0f3;padding:8px 10px;vertical-align:top;font-size:13.5px}
table.batch tr{cursor:pointer}table.batch tr.off td{background:#fef2f2;color:#6b7280}table.batch input{width:18px;height:18px}
.bt{font-weight:600;margin-bottom:3px}.bname{font-size:17px;font-weight:700}
.bbar{display:flex;gap:12px;align-items:center;margin:10px 0}.bbar button{font:inherit;font-size:15px;padding:10px 18px;border-radius:8px;border:1px solid #15803d;background:#16a34a;color:#fff;cursor:pointer}
.sugg{outline:3px solid #16a34a !important}
.thumb{width:190px;text-align:center}.thumb img{max-width:180px;max-height:150px;cursor:zoom-in;background:#fff;border:1px solid var(--line);border-radius:6px}
.figs.top .fig img{max-width:420px;max-height:340px}
details.more summary{cursor:pointer;color:var(--mut);font-size:13px;margin:6px 0}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:20}#zoom img{max-width:96vw;max-height:96vh;background:#fff}
</style></head><body>
<header><h1>Aircraft names — every proposal</h1>
<select id="view"><option value="todo" selected>not decided</option><option value="yellow">🟡 the text may name it — one per screen</option><option value="red">🔴 wizard name belongs to someone else</option><option value="all">all</option><option value="done">decided</option><option value="text">name found in the patent text</option><option value="wizard">wizard name ≠ assignee</option></select>
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

const DATA=__DATA__;const AUTO=__AUTO__;const KEY='namereview_v1';let DEC={};try{DEC=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){DEC={}}
function save(){try{localStorage.setItem(KEY,JSON.stringify(DEC))}catch(e){}}
const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LAB={text:'Keep — the patent text names it',known:'Keep — known aircraft (give the source)',other:'Other name',clear:'Clear → Assignee N',fix:'Fix wizard name'};
let VIEW='todo',CUR=0,ROWS=[];
const LKEY='namereview_listskip_v1';let LSKIP={};try{LSKIP=JSON.parse(localStorage.getItem(LKEY)||'{}')}catch(e){LSKIP={}}
function saveSkip(){try{localStorage.setItem(LKEY,JSON.stringify(LSKIP))}catch(e){}}
const decided=r=>!!(DEC[r.pid]&&DEC[r.pid].choice);
const LISTMODE=()=>VIEW==='lgreen';
const LNAME={green:'Obvious',yellow:'Needs a look',red:'Wizard name conflict'};
// Where a proposed name came from, in plain words (user 2026-09-14: "is it easy to know where the name was taken from?")
function srcPlain(r,c){
 const p=(r.portfolio||[]).find(x=>x.name===c.candidate);
 if(c.source==='gazetteer')return `from the company list: ${esc(r.company)} built the ${esc(c.candidate)}${p?' ('+esc(p.years)+')':''} — picked because of the company and the filing year ${esc(r.year)}, not because the patent says so`;
 if(c.source==='variant proposal')return `from the company list: one of ${esc(r.company)}'s aircraft${p?' ('+esc(p.years)+')':''}, offered for one of the ${r.nvar} aircraft in this patent`;
 if(c.source==='sbert')return `found in the patent text by the automatic text search (${esc(c.text_section||'text')})`;
 if(c.source.startsWith('wizard'))return `the name typed in the labelling wizard — it does not look like the assignee (${esc(r.assignee)})`;
 return esc(c.source)}
function hlName(q,name){let h=esc(q);if(!name)return h;const re=new RegExp(esc(name).replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi');return h.replace(re,m=>'<mark>'+m+'</mark>')}
const intext=r=>r.cands.some(c=>c.text_hit!=='not in the text');
function filt(){
 if(VIEW==='lgreen'){ROWS=DATA.filter(r=>!decided(r)&&!LSKIP[r.pid]&&r.light==='green'&&r.sugg==='clear');CUR=0;return}
 if(VIEW==='yellow'||VIEW==='red'){ROWS=DATA.filter(r=>!decided(r)&&r.light===VIEW);if(CUR>=ROWS.length)CUR=Math.max(0,ROWS.length-1);return}
 if(VIEW==='unticked'){ROWS=DATA.filter(r=>!decided(r)&&LSKIP[r.pid]);if(CUR>=ROWS.length)CUR=Math.max(0,ROWS.length-1);return}
 ROWS=DATA.filter(r=>{const d=DEC[r.pid];return VIEW==='all'||(VIEW==='todo'?!(d&&d.choice):VIEW==='done'?!!(d&&d.choice):VIEW==='text'?intext(r):r.cands.some(c=>c.source.startsWith('wizard')))});if(CUR>=ROWS.length)CUR=Math.max(0,ROWS.length-1)}
function render(){filt();const L=document.getElementById('list');L.innerHTML='';
 ROWS.forEach((r,i)=>{const d=DEC[r.pid];const el=document.createElement('div');el.className=(i===CUR?'cur ':'')+(d&&d.choice?'done':'');
  el.innerHTML=`<span class="dot L${r.light}"></span><b>${esc(r.pid)}</b> <span class="mut">${esc(r.company)}</span><br><span class="small">${esc(r.cands.map(c=>c.candidate).join(' / '))}${d&&d.choice?' ✓ '+esc(d.choice):''}</span>`;el.onclick=()=>{CUR=i;render()};L.appendChild(el)});
 const lf=c=>DATA.filter(r=>!decided(r)&&r.light===c).length;
 document.getElementById('prog').textContent=`🟢 ${lf('green')} · 🟡 ${lf('yellow')} · 🔴 ${lf('red')} left · ${DATA.filter(decided).length} / ${DATA.length} decided · showing ${ROWS.length} · ${AUTO.length} cleared automatically (company-list guesses, prior-art mentions) — included in the export`;
 if(LISTMODE())return renderBatch();
 const c=L.children[CUR];if(c)c.scrollIntoView({block:'nearest'});
 const P=document.getElementById('panel');const r=ROWS[CUR];if(!r){P.innerHTML='<p class="mut">Nothing in this view.</p>';return}
 const d=DEC[r.pid]||{};const hasText=intext(r);const hasWiz=r.cands.some(c=>c.source.startsWith('wizard'));
 P.innerHTML=`<div class="head"><h2>${esc(r.pid)}</h2><span>${esc(r.company)} — <i>${esc(r.assignee)}</i></span>${r.pdf?`<a href="${esc(r.pdf)}" target="_blank">PDF ↗</a>`:''}<a href="https://patents.google.com/patent/${esc(r.pid)}/en" target="_blank">Google Patents ↗</a></div>
 <div style="font-size:16px;font-weight:600;margin:4px 0">${esc(r.title)}</div>
 <div class="mut small">${esc(r.year)} · wizard name <b>${esc(r.wizard)}</b> · current group <b>${esc(r.group)}</b> · ${r.nvar} aircraft, figure types ${esc(r.types)}</div>
 <div class="band ${r.light}"><span class="dot L${r.light}" style="width:14px;height:14px"></span><b>${LNAME[r.light]}</b><span>${esc(r.why)} · suggested: <b>${esc(LAB[r.sugg]||r.sugg)}</b></span></div>
 <div class="figs top">${r.figs.map(f=>`<div class="fig"><img src="${esc(f.src)}" style="transform:rotate(${f.rot}deg)" loading="lazy"><small>${f.arch?'aircraft '+f.arch:''}</small></div>`).join('')||'<p class="small mut">no approved figure on disk</p>'}</div>
 ${r.cands.map(c=>`<div class="card"><h3>${esc(c.candidate)}
   ${c.text_hit.startsWith('names it')?'<span class="tag ok">'+esc(c.text_hit)+'</span>':c.text_hit==='not in the text'?'<span class="tag warn">not in the patent text</span>':'<span class="tag warn">'+esc(c.text_hit)+'</span>'}
   ${c.candidate_public_type?`<span class="tag ${c.type_match==='yes'?'ok':'warn'}">public type ${esc(c.candidate_public_type)} ${c.type_match==='yes'?'= figure type':'≠ figure type'}</span>`:''}
   ${c.company_types_differ?'<span class="tag warn">company aircraft differ in architecture</span>':''}</h3>
   <div class="small"><b>where it came from:</b> ${srcPlain(r,c)}</div>
   <div class="small mut"><span class="dot L${c.light}"></span>${esc(c.why)}</div>
   ${c.text_quote?`<blockquote>“${hlName(c.text_quote,c.candidate)}”</blockquote><div class="small mut">${esc(c.text_section)}</div>`:''}</div>`).join('')}
 ${r.portfolio.length?`<details class="more"><summary>${esc(r.company)} — documented aircraft (gazetteer)</summary><div class="card"><table><tr><th>aircraft</th><th>years</th><th>public type</th><th>basis</th></tr>${r.portfolio.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.years)}</td><td>${esc(x.type)}</td><td class="mut">${esc(x.basis)}</td></tr>`).join('')}</table></div></details>`:''}
 <div class="card"><div class="decide">
  ${['text','known','other','clear','fix'].map(k=>`<button data-c="${k}" class="${d.choice===k?'on':''} ${k===r.sugg&&!d.choice?'sugg':''}" ${(k==='text'&&!hasText)||(k==='fix'&&!hasWiz)?'disabled':''}>${LAB[k]}</button>`).join('')}</div>
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
 let name=nm;if(c==='text'&&!nm.trim())name=(r.cands.find(x=>x.light==='yellow'&&x.text_hit!=='not in the text')||r.cands.find(x=>x.text_hit!=='not in the text')).candidate;
 if(c==='known'&&!nm.trim())name=r.cands[0].candidate;if(c==='clear')name='';
 DEC[r.pid]={choice:c,name,source:src,comment:document.getElementById('cmt').value,at:new Date().toISOString().slice(0,16)};save();
 if(!['todo','yellow','red','unticked'].includes(VIEW))CUR=Math.min(CUR+1,ROWS.length-1);render()}
function renderBatch(){const P=document.getElementById('panel');const rows=ROWS.slice(0,20);
 if(!rows.length){P.innerHTML='<p class="mut">Nothing left in this list. Next: 🟡 needs a look, then 🔴, then ↩ unticked.</p>';return}
 const bar=`<div class="bbar"><button class="okall">✔ Clear the ticked proposals (<span class="nt">${rows.length}</span>) — Enter</button><span class="small mut">Each ticked patent keeps its generated name (Assignee N). Untick a row if the patent really names this aircraft; it moves to ↩ unticked. ${ROWS.length} left in this list.</span></div>`;
 P.innerHTML=bar+`<table class="batch">${rows.map(r=>`<tr data-k="${esc(r.pid)}"><td><input type="checkbox" checked></td>
  <td class="thumb">${r.figs.length?`<img src="${esc(r.figs[0].src)}" style="transform:rotate(${r.figs[0].rot}deg)" loading="lazy">${r.figs.length>1?`<br><small class="mut">+${r.figs.length-1} more</small>`:''}`:'<small class="mut">no figure</small>'}</td>
  <td style="white-space:nowrap"><span class="dot L${r.light}"></span><b>${esc(r.pid)}</b><br><small class="mut">${esc(r.company)} · ${esc(r.year)}</small><br><small>${r.pdf?`<a href="${esc(r.pdf)}" target="_blank">PDF ↗</a> · `:''}<a href="https://patents.google.com/patent/${esc(r.pid)}/en" target="_blank">Google ↗</a></small></td>
  <td><div class="bt">${esc(r.title)}</div>${r.cands.map(c=>`<div style="margin-top:4px"><span class="bname">${esc(c.candidate)}</span><div class="small"><b>where it came from:</b> ${srcPlain(r,c)}</div><small class="mut">${esc(c.why)}</small>${c.text_quote?`<div class="small">“${hlName(c.text_quote,c.candidate)}”</div>`:''}</div>`).join('')}
   <small class="mut">generated name if cleared: <b>${esc(r.group)}</b></small></td></tr>`).join('')}</table>`+bar;
 const count=()=>{const n=P.querySelectorAll('tr[data-k] input:checked').length;P.querySelectorAll('.nt').forEach(x=>x.textContent=n)};
 P.querySelectorAll('tr[data-k]').forEach(tr=>{const cb=tr.querySelector('input');const sync=()=>{tr.classList.toggle('off',!cb.checked);count()};
  cb.onchange=()=>{sync();cb.blur()};tr.onclick=e=>{if(e.target!==cb&&!e.target.closest('a')&&!e.target.closest('.thumb')){cb.checked=!cb.checked;sync()}}});
 P.querySelectorAll('.thumb img').forEach(im=>im.onclick=()=>{const z=document.getElementById('zoom');z.querySelector('img').src=im.src;z.querySelector('img').style.transform=im.style.transform;z.style.display='flex'});
 P.querySelectorAll('.okall').forEach(b=>b.onclick=confirmBatch)}
function confirmBatch(){const at=new Date().toISOString().slice(0,16);
 document.querySelectorAll('#panel tr[data-k]').forEach(tr=>{const k=tr.dataset.k;
  if(tr.querySelector('input').checked)DEC[k]={choice:'clear',name:'',source:'',comment:'cleared from the list',at:at};else LSKIP[k]=1});
 save();saveSkip();render();window.scrollTo(0,0)}
document.getElementById('view').onchange=e=>{VIEW=e.target.value;CUR=0;render()};
document.getElementById('zoom').onclick=e=>e.currentTarget.style.display='none';
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'&&e.target.type!=='checkbox')return;
 if(LISTMODE()&&(e.key==='Enter'||e.key===' ')){e.preventDefault();confirmBatch();return}if(e.key==='ArrowRight'){CUR=Math.min(CUR+1,ROWS.length-1);render()}else if(e.key==='ArrowLeft'){CUR=Math.max(CUR-1,0);render()}});
const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
document.getElementById('exp').onclick=()=>{const L=[['patent_id','decision','name_final','source_note','candidates','comment','decided_at'].join(',')];
 DATA.forEach(r=>{const d=DEC[r.pid];if(!d||!d.choice)return;L.push([r.pid,d.choice,d.name,d.source,r.cands.map(c=>c.candidate).join(' / '),d.comment,d.at].map(q).join(','))});
 // a decision you already made on a patent that is now auto-cleared wins over the automatic clear
 AUTO.forEach(a=>{const d=DEC[a.pid];if(d&&d.choice)L.push([a.pid,d.choice,d.name,d.source,a.cands,d.comment,d.at].map(q).join(','));
  else L.push([a.pid,'clear','','',a.cands,'auto: '+a.why,''].map(q).join(','))});
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
