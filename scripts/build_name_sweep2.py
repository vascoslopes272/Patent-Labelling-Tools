#!/usr/bin/env python3
"""Second name sweep, built from the name review export (request 2026-09-15).

The user's NAME_DECISIONS.csv gives some real names to several aircraft, and a real name belongs to one aircraft
unless the patents are duplicates of each other. This page answers, for every repeated name, whether the aircraft
really are duplicates (wizard duplicate chain, same patent family, shared inventors, same priority date), and lists
every company name nobody received with the aircraft it could fit (same architecture, existed by the filing year).

Inputs : NAME_DECISIONS.csv (1639_LABELLED/review_decisions/, else ~/Downloads), name_review.html (aircraft + portfolio),
         joined/aircraft_identity_ALL.xlsx, joined/master_labels.xlsx, joined/master_figures.xlsx, the PatSeer export
Output : notebooks/post-process/name_sweep2.html  (Export -> review_decisions/NAME_SWEEP2.csv)
"""
import json
import re
import sys
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED")
PATSEER = Path("/mnt/storage_11tb/Drive_files_to_syncronize/2 - Patente & Validation/"
               "3 -Raw_Patent_Exports_PatSeer_&Gold_Standard/1639__dataset_08_06_26.xlsx")
REVIEW_HTML = REPO / "notebooks" / "post-process" / "name_review.html"
OUT_HTML = REPO / "notebooks" / "post-process" / "name_sweep2.html"
LET = "abcdefghijklmnopqrstuvwxyz"
MAX_FIGS = 3


def s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", s(t).lower())


def find_export() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    cands = [ROOT / "review_decisions" / "NAME_DECISIONS.csv"] + sorted(Path.home().glob("Downloads/NAME_DECISIONS*.csv"))
    cands = [p for p in cands if p.exists()]
    if not cands:
        sys.exit("no NAME_DECISIONS.csv found")
    return max(cands, key=lambda p: p.stat().st_mtime)


def main():
    export = find_export()
    dec = pd.read_csv(export, keep_default_na=False, dtype=str)
    html = REVIEW_HTML.read_text(encoding="utf-8")
    data = {r["pid"]: r for r in json.loads(re.search(r"const DATA=(\[.*?\]);const AUTO=", html, re.S).group(1))}

    idn = pd.read_excel(ROOT / "joined" / "aircraft_identity_ALL.xlsx", sheet_name="Identity")
    idn["duptag"] = idn.wizard_duplicate_type.map(lambda v: "" if pd.isna(v) else f"D{int(v)}")
    by = idn.set_index("patent_id")
    ml = pd.read_excel(ROOT / "joined" / "master_labels.xlsx", keep_default_na=False, dtype=str)
    ml = ml[(ml.is_primary == "True") & (ml.is_approved == "True")].copy()
    ml["variant"] = ml.variant.astype(int)
    # human architecture labels only (no ML guesses, notes, uncertainty flags or identity columns)
    bad = re.compile(r"^ml_|_conf$|[Nn]ote|Uncertain|otherTag|Oth$|^dinoUnderstanding|^uav_|electric|takeoff|identity_from|edgeTags")
    lab_cols = [c for c in ml.columns[list(ml.columns).index("topType"):] if not bad.search(c)]
    labels = ml.assign(k=ml.patent_id + "#" + ml.variant.astype(str)).set_index("k")[lab_cols]

    def label_sim(ka, kb):
        if ka not in labels.index or kb not in labels.index:
            return None, []
        x, y = labels.loc[ka], labels.loc[kb]
        m = (x != "") | (y != "")
        eq = x[m] == y[m]
        return (round(float(eq.mean()), 2) if m.sum() else None), list(eq.index[~eq])

    # what "similar" means in this corpus: D3 vs its original (measured), unrelated aircraft of the same type
    # (median 0.39-0.41 over 800 sampled pairs, 2026-09-15). D1/D2 cannot calibrate: they copy their original's labels.
    d3 = ml[(ml.dup_type == "3") & (ml.variant == 1)]
    d3_sims = pd.Series([v for v in (label_sim(r.patent_id + "#1", r.dup_of + "#1")[0] for r in d3.itertuples()) if v is not None])
    BENCH = {"d3_median": round(float(d3_sims.median()), 2), "unrelated_median": 0.40}
    types = {pid: [s(t) for t in g.sort_values("variant").topType] for pid, g in ml.groupby("patent_id")}
    mf = pd.read_excel(ROOT / "joined" / "master_figures.xlsx")
    mf = mf[(mf.status == "approved") & (mf.file_exists == True)].sort_values(["is_main"], ascending=False)
    figs = defaultdict(list)
    for x in mf.itertuples():
        a = 0 if pd.isna(x.arch) else int(x.arch)
        if len(figs[(x.patent_id, a)]) < MAX_FIGS:
            figs[(x.patent_id, a)].append({"src": "file://" + str(x.image_path), "rot": int(x.rotation_deg or 0)})
    ps = pd.read_excel(PATSEER, usecols=["Record Number", "Simple Family ID", "Extended Family ID", "Inventors",
                                         "Priority Date (Record)", "PDF Link"]).set_index("Record Number")

    # duplicate graph over the whole corpus (edges: patent -- the patent it duplicates), read from the LIVE wizard record
    # (identity_ALL can predate duplicate changes made in the wizard)
    w = pd.read_excel(ROOT / "joined" / "wizard_all" / "reviewed_patents_Batch_ALL.xlsx", dtype=str, keep_default_na=False,
                      usecols=["Patent_ID", "Field", "Value"])
    w = w[w.Field.isin(["isDuplicate", "duplicateId", "duplicateType"])]
    w["pid"] = w.Patent_ID.str.replace(r"_arch\d+$", "", regex=True)
    wl = w.groupby(["pid", "Field"]).Value.first().unstack().fillna("")
    live = {pid: (r.duplicateId.strip(), "D" + r.duplicateType.split(" — ")[0].strip())
            for pid, r in wl.iterrows() if r.get("isDuplicate", "") in ("True", "true") and r.duplicateId.strip()}
    idn["duptag"] = idn.patent_id.map(lambda p: live[p][1] if p in live else "")
    idn["wizard_duplicate_of"] = idn.patent_id.map(lambda p: live[p][0] if p in live else "")
    by = idn.set_index("patent_id")
    g = defaultdict(list)
    for pid, (o, t) in live.items():
        g[pid].append((o, f"{pid} is {t} of {o}", t))
        g[o].append((pid, f"{pid} is {t} of {o}", t))

    def dup_path(a, b):
        seen, q = {a: None}, deque([a])
        while q:
            n = q.popleft()
            if n == b:
                path = []
                while seen[n]:
                    prev, lab, t = seen[n]
                    path.append((lab, t))
                    n = prev
                return path[::-1]
            for m, lab, t in g[n]:
                if m not in seen:
                    seen[m] = (n, lab, t)
                    q.append(m)
        return None

    def inventors(pid):
        return {w.strip().upper() for w in re.split(r"[|;\n]", s(ps.Inventors.get(pid, ""))) if w.strip()}

    def fig_for(pid, v, n):
        f = figs.get((pid, v), []) if n > 1 else []
        return f or figs.get((pid, 0), []) or [x for k, lst in figs.items() if k[0] == pid for x in lst][:MAX_FIGS]

    def aircraft_rec(pid, v, name="", decision=""):
        t = types.get(pid, [""])
        n = len(t)
        r = by.loc[pid]
        gv = [x.strip() for x in s(r.aircraft_group_variants).split(";") if x.strip()]
        return {"pid": pid, "v": v, "n": n, "lab": f"aircraft {LET[v-1]} of {n}" if n > 1 else "",
                "type": t[v - 1] if v - 1 < n else "", "gname": (gv[v - 1] if n > 1 and v - 1 < len(gv) else s(r.aircraft_group)),
                "company": s(r.company_canonical), "assignee": s(r.assignee_raw), "title": s(r.title),
                "year": "" if pd.isna(r.priority_year) else int(r.priority_year), "batch": s(r.batch),
                "dup": (f"{r.duptag} of {s(r.wizard_duplicate_of)}" if r.duptag else ""),
                "family": s(ps["Simple Family ID"].get(pid, "")), "efamily": s(ps["Extended Family ID"].get(pid, "")),
                "prio": s(ps["Priority Date (Record)"].get(pid, ""))[:10], "pdf": s(ps["PDF Link"].get(pid, "")),
                "name": name, "decision": decision, "figs": fig_for(pid, v, n)}

    # ---- 1. names given to more than one aircraft ----
    named = []
    for r in dec.itertuples():
        if r.decision == "clear" or r.patent_id not in by.index:
            continue
        t = types.get(r.patent_id, [""])
        parts = [x.strip() for x in s(r.name_final).split(";")] if len(t) > 1 else [s(r.name_final)]
        for i, nm in enumerate(parts):
            if nm and norm(nm) != norm(aircraft_rec(r.patent_id, i + 1)["gname"]):
                named.append(aircraft_rec(r.patent_id, i + 1, nm, r.decision))
    groups = defaultdict(list)
    for a in named:
        groups[norm(a["name"])].append(a)
    repeated = []
    for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(members) < 2:
            continue
        pairs = []
        for a, b in combinations(members, 2):
            ev, verdict = [], ""
            if a["pid"] == b["pid"]:
                verdict, kind = "same patent, two drawn aircraft → different aircraft", "diff"
            else:
                path = dup_path(a["pid"], b["pid"])
                fam = a["family"] and a["family"] == b["family"]
                efam = a["efamily"] and a["efamily"] == b["efamily"]
                inv = inventors(a["pid"]) & inventors(b["pid"])
                if path:
                    ev.append("duplicate chain: " + " → ".join(lab for lab, _ in path))
                if fam:
                    ev.append("same simple patent family")
                elif efam:
                    ev.append("same extended patent family")
                if inv:
                    ev.append(f"{len(inv)} shared inventor(s)")
                if a["prio"] and a["prio"] == b["prio"]:
                    ev.append("same priority date " + a["prio"])
                if path and all(t in ("D1", "D2") for _, t in path):
                    verdict, kind = "wizard duplicate D1/D2 → the SAME aircraft, sharing the name is right", "same"
                elif path:
                    verdict, kind = "wizard duplicate D3 → a DIFFERENT aircraft, it needs its own name", "diff"
                elif fam or efam:
                    verdict, kind = "same patent family but NOT flagged as a duplicate → probably a missed duplicate", "maybe"
                else:
                    verdict, kind = "no duplicate link → different aircraft unless you now flag one as a duplicate", "diff"
            ls, ldiff = label_sim(f'{a["pid"]}#{a["v"]}', f'{b["pid"]}#{b["v"]}')
            # labels as identical as a D3 pair and no duplicate link at all -> worth a look for a missed duplicate
            if kind == "diff" and a["pid"] != b["pid"] and not dup_path(a["pid"], b["pid"]) and ls is not None and ls >= 0.9:
                verdict, kind = f"no duplicate link, but the labels are {round(ls * 100)}% equal → check: maybe a missed duplicate", "maybe"
            pairs.append({"a": f'{a["pid"]}#{a["v"]}', "b": f'{b["pid"]}#{b["v"]}', "verdict": verdict,
                          "kind": kind, "evidence": ev, "labels": ls, "ldiff": ldiff})
        if all(p["kind"] == "same" for p in pairs):
            continue
        repeated.append({"name": members[0]["name"], "aircraft": members, "pairs": pairs})

    # ---- 2. company names nobody received, with the aircraft they may fit ----
    used = {norm(a["name"]) for a in named}
    decided_name = {}
    for r in dec.itertuples():
        t = types.get(r.patent_id, [""])
        parts = [x.strip() for x in s(r.name_final).split(";")] if len(t) > 1 else [s(r.name_final)]
        for i in range(len(t)):
            decided_name[(r.patent_id, i + 1)] = "" if r.decision == "clear" else (parts[i] if i < len(parts) else "")
    # the WHOLE gazetteer, not only the companies that reached the name page (2026-09-16: VoloCity and EH216 were
    # invisible because no Volocopter/EHang patent ever had a name candidate)
    gaz = pd.read_csv(REPO / "reference" / "evtol_gazetteer.csv")
    gaz = gaz[gaz.company_canonical != "#"]
    known = pd.read_csv(ROOT / "text_architecture" / "known_aircraft_architecture.csv")
    ktype = {(r.company, r.aircraft_name): s(r.known_type) for r in known.itertuples()}
    kbasis = {(r.company, r.aircraft_name): f"{s(r.confidence)} · {s(r.basis)}" for r in known.itertuples()}
    # aircraft that are not in the gazetteer: companies whose patents never got a name candidate (2026-09-16 request
    # "find those everywhere — it does not need to be on the gazetteer"). Proposals, each to be judged from the figures.
    extra = REPO / "reference" / "extra_aircraft_candidates.csv"
    if extra.exists():
        ex = pd.read_csv(extra)
        gaz = pd.concat([gaz, ex[["company_canonical", "aircraft_name", "year_from", "year_to"]]], ignore_index=True)
        for r in ex.itertuples():
            ktype.setdefault((r.company_canonical, r.aircraft_name), s(r.known_type))
            kbasis.setdefault((r.company_canonical, r.aircraft_name), s(r.basis))
    portfolio = {}
    for c, g in gaz.groupby("company_canonical"):
        portfolio[c] = [{"name": r.aircraft_name, "years": f"{int(r.year_from)}–{int(r.year_to)}", "yf": int(r.year_from),
                         "type": ktype.get((c, r.aircraft_name), ""), "basis": kbasis.get((c, r.aircraft_name), "")}
                        for r in g.itertuples()]
    prim = idn[(idn.wizard_approved == True) & ~idn.wizard_duplicate_type.isin([1.0, 2.0])]
    unassigned = []
    for comp, port in sorted(portfolio.items()):
        company_pids = prim[prim.company_canonical == comp].patent_id.tolist()
        if not company_pids:
            # the company field can be "Unknown / Independent" while the assignee names the company (EHang, Opener…)
            words = [w for w in re.split(r"[ /]+", comp) if len(w) > 3]
            if words:
                hit = prim.assignee_raw.astype(str).str.upper().str.contains(words[0].upper(), regex=False)
                company_pids = prim[hit].patent_id.tolist()
        for x in port:
            if norm(x["name"]) in used:
                continue
            # every aircraft of the company (2026-09-16: the architecture/year filter hid the right one — e.g. the
            # Overair Butterfly and the Aurora PAV). Matching ones first; the rest greyed with the reason.
            fits = []
            for pid in company_pids:
                yr = by.at[pid, "priority_year"]
                for v, t in enumerate(types.get(pid, []), 1):
                    why = []
                    if x["type"] and t != x["type"]:
                        why.append(f'architecture {t or "?"} ≠ {x["type"]}')
                    if not pd.isna(yr) and x.get("yf") and int(yr) < x["yf"] - 1:
                        why.append(f'filed {int(yr)}, the aircraft appeared in {x["yf"]}')
                    rec = aircraft_rec(pid, v, decided_name.get((pid, v), ""))
                    rec["gap"] = abs(int(yr) - x["yf"]) if not pd.isna(yr) and x.get("yf") else 99
                    rec["off"] = "; ".join(why)
                    fits.append(rec)
            fits.sort(key=lambda r: (bool(r["off"]), bool(r["name"]), r["gap"], r["pid"]))
            unassigned.append({"name": x["name"], "company": comp, "years": x["years"], "type": x["type"],
                               "basis": x.get("basis", ""), "fits": fits})

    # ---- 3. every real name now in the file, for a final confirmation (2026-09-15: "I want to review all 5") ----
    confirm = []
    for r in dec.itertuples():
        if r.decision == "clear":
            continue
        t = types.get(r.patent_id, [""])
        parts = [x.strip() for x in s(r.name_final).split(";")] if len(t) > 1 else [s(r.name_final)]
        for i, nm in enumerate(parts):
            rec = aircraft_rec(r.patent_id, i + 1, nm, r.decision)
            if not nm or norm(nm) == norm(rec["gname"]):
                continue
            rec["why"] = s(r.comment)
            rec["base"] = re.sub(r"(\s+v\d+)+$", "", nm).strip()
            confirm.append(rec)
    confirm.sort(key=lambda a: (a["base"].lower(), s(a["name"])))
    print("names to confirm:", len(confirm))

    print(f"export: {export}  ({len(dec)} patents, {len(named)} named aircraft)")
    print(f"repeated names: {len(repeated)}")
    for grp in repeated:
        print(f"  {grp['name']} ×{len(grp['aircraft'])}:", "; ".join(f"{p['a']}~{p['b']} {p['kind']}" for p in grp["pairs"]))
    print(f"unassigned names: {len(unassigned)}  (with a fitting aircraft: {sum(bool(u['fits']) for u in unassigned)})")
    for u in unassigned:
        print(f"  {u['company']} — {u['name']} ({u['type'] or '?'}, {u['years']}): {len(u['fits'])} fitting aircraft")

    payload = {"export": str(export), "repeated": repeated, "unassigned": unassigned, "confirm": confirm, "bench": BENCH}
    OUT_HTML.write_text(PAGE.replace("__DATA__", json.dumps(payload, ensure_ascii=False, default=str)), encoding="utf-8")
    print("wrote", OUT_HTML)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Name sweep 2</title>
<style>
:root{--bg:#f6f7f9;--ink:#1c2128;--mut:#6b7280;--line:#e3e6ea;--acc:#2456c7}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 Inter,system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);padding:8px 16px;display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
header h1{font-size:16px;margin:0}header button,header select{font:inherit;padding:5px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
#prog{color:var(--mut);font-size:13px}
main{max-width:1500px;margin:0 auto;padding:12px 16px 60px}
h2{font-size:18px;margin:22px 0 4px}.lead{color:var(--mut);margin:0 0 12px;max-width:900px}
.grp{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 16px}
.grp.done{opacity:.55}.grp h3{margin:0 0 8px;font-size:18px}
.row{display:flex;gap:12px;overflow-x:auto;padding-bottom:6px}
.ac{flex:0 0 330px;border:1px solid var(--line);border-radius:10px;padding:8px;background:#fcfcfd}
.ac.keep{outline:3px solid #16a34a}.ac.dupe{outline:3px solid #2563eb}.ac.other{outline:3px solid #d97706}.ac.clear{outline:3px solid #9ca3af}
.ac img{max-width:100%;max-height:170px;display:block;margin:0 auto 4px;cursor:zoom-in;background:#fff}
.imgs{display:flex;gap:4px;flex-wrap:wrap;justify-content:center;min-height:60px}.imgs img{max-width:150px;max-height:130px}
.pid{font-weight:700}.mut{color:var(--mut)}.small{font-size:12.5px}
.tag{display:inline-block;font-size:11.5px;padding:1px 6px;border-radius:4px;background:#eef;margin:1px 2px}
.pairs{margin:8px 0 10px;font-size:13px;border-collapse:collapse;width:100%}.pairs td{border-top:1px solid #eef0f3;padding:4px 6px;vertical-align:top}
.k-same{color:#15803d;font-weight:600}.k-diff{color:#b91c1c;font-weight:600}.k-maybe{color:#b45309;font-weight:600}
.btns{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}.btns button{font:inherit;font-size:12.5px;padding:4px 7px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
.btns button.on{background:#e8efff;outline:2px solid var(--acc)}
.btns input{font:inherit;font-size:12.5px;padding:3px 6px;border:1px solid var(--line);border-radius:6px;width:100%}
select.dupsel{font:inherit;font-size:12.5px;width:100%;margin-top:3px}
#zoom{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:20}#zoom img{max-width:96vw;max-height:96vh;background:#fff}
</style></head><body>
<header><h1>Name sweep 2</h1>
<select id="view"><option value="all">everything</option><option value="rep">1 · names on several aircraft</option><option value="una">2 · names nobody received</option><option value="set">3 · names now set — confirm</option><option value="open">only what is still open</option></select>
<span id="prog"></span><button id="exp">Export NAME_SWEEP2.csv</button>
<label style="font-size:13px"><input type="checkbox" id="gauto" checked> 🔍 image window</label></header>
<main id="main"></main><div id="zoom"><img></div>
<script>
function saveToFolder(blob, name){
  function fallback(){ var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; a.click(); return Promise.resolve('downloads'); }
  if (!window.showSaveFilePicker) return fallback();
  return window.showSaveFilePicker({suggestedName: name, id: 'review_decisions'})
    .then(function(h){ return h.createWritable().then(function(w){ return w.write(blob).then(function(){ return w.close(); }); }); })
    .then(function(){ return 'folder'; }).catch(function(e){ return (e && e.name === 'AbortError') ? 'cancelled' : fallback(); });
}
const D=__DATA__;const KEY='namesweep2_v1';let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){S={}}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}};
const esc=t=>String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LET='abcdefghijklmnopqrstuvwxyz';const key=a=>a.pid+'#'+a.v;const lab=a=>a.pid+(a.n>1?' '+LET[a.v-1]:'');
// image window (same one as the name review page)
const GNAME='nameReviewImages';let GWIN=null;
function img(q,label){if(!document.getElementById('gauto').checked)return;const msg={type:'nameReviewImages',q,label};
 if(GWIN&&!GWIN.closed){try{GWIN.postMessage(msg,'*');return}catch(e){}}
 GWIN=window.open('name_review_images.html#'+encodeURIComponent(JSON.stringify(msg)),GNAME,`left=${(window.screenX||0)+(window.outerWidth||900)},top=${window.screenY||0},width=${Math.max(700,window.outerWidth||900)},height=${window.outerHeight||screen.availHeight}`);try{window.focus()}catch(e){}}
const q=(n,c)=>n.length<=4?`${(c||'').split('/')[0].trim()} ${n} VTOL aircraft`:`"${n}" ${(c||'').split('/')[0].trim()}`;
function acCard(a,extra){return `<div class="ac" data-k="${esc(key(a))}">
 <div class="imgs">${a.figs.map(f=>`<img src="${esc(f.src)}" style="transform:rotate(${f.rot}deg)" loading="lazy">`).join('')||'<span class="small mut">no figure</span>'}</div>
 <div><span class="pid">${esc(a.pid)}</span>${a.lab?` <b>· ${esc(a.lab)}</b>`:''} <span class="mut small">${esc(a.batch)}</span></div>
 <div class="small">${esc(a.title)}</div>
 <div class="small mut">${esc(a.company)} · filed ${esc(a.year)} · prio ${esc(a.prio)} · type <b>${esc(a.type||'?')}</b></div>
 <div class="small">${a.dup?`<span class="tag">${esc(a.dup)}</span>`:''}${a.family?`<span class="tag">family ${esc(a.family)}</span>`:''}${a.name?`<span class="tag">named: ${esc(a.name)}</span>`:`<span class="tag">now: ${esc(a.gname)}</span>`}
 <a class="small" href="https://patents.google.com/patent/${esc(a.pid)}/en" target="_blank">Google ↗</a>${a.pdf?` <a class="small" href="${esc(a.pdf)}" target="_blank">PDF ↗</a>`:''}</div>${extra||''}</div>`}
// ---- section 1 ----
const ACT1={keep:'✓ keeps the name',dupe:'= same aircraft (duplicate of…)',other:'≠ different → other name',clear:'≠ different → clear'};
function grpDone(g){return g.aircraft.every(a=>S[key(a)]&&S[key(a)].act&&(S[key(a)].act!=='other'||S[key(a)].name)&&(S[key(a)].act!=='dupe'||S[key(a)].of))&&g.aircraft.filter(a=>S[key(a)].act==='keep').length===1}
function renderRep(){return `<h2>1 · The same name on several aircraft (${D.repeated.length} names)</h2>
 <p class="lead">A real name belongs to one aircraft, unless the patents are duplicates. For each name choose the ONE aircraft that keeps it. For every other one say whether it is the same aircraft (a duplicate you did not flag — it will need the duplicate flag in the wizard), or a different aircraft (type its own name, or clear it back to its generated name). The table under each name shows what links the patents.</p>`+
 D.repeated.filter(g=>VIEW!=='open'||!grpDone(g)).map((g,gi)=>`<div class="grp ${grpDone(g)?'done':''}" data-g="${D.repeated.indexOf(g)}"><h3>${esc(g.name)} <span class="mut" style="font-weight:400">× ${g.aircraft.length} aircraft</span> <button class="gi" style="font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer">🔍 images</button></h3>

 <div class="row">${g.aircraft.map(a=>{const st=S[key(a)]||{};return acCard(a,`<div class="btns">${Object.keys(ACT1).map(k=>`<button data-act="${k}" class="${st.act===k?'on':''}">${ACT1[k]}</button>`).join('')}
   ${st.act==='other'?`<input class="nm" placeholder="its own name" value="${esc(st.name||'')}">`:''}
   ${st.act==='dupe'?`<select class="dupsel"><option value="">duplicate of which aircraft?</option>${g.aircraft.filter(b=>b!==a).map(b=>`<option value="${esc(key(b))}" ${st.of===key(b)?'selected':''}>${esc(lab(b))}</option>`).join('')}</select>`:''}
   <input class="note" placeholder="note" value="${esc(st.note||'')}"></div>`)}).join('')}</div>
 <details open><summary class="small mut" style="cursor:pointer;margin-top:6px">what links these patents · labels equal: a D3 and its original ≈ ${Math.round(D.bench.d3_median*100)}%, unrelated aircraft of the same type ≈ ${Math.round(D.bench.unrelated_median*100)}%</summary><table class="pairs">${g.pairs.map(p=>`<tr><td style="white-space:nowrap">${esc(p.a.replace('#1','').replace('#',' '))} ↔ ${esc(p.b.replace('#1','').replace('#',' '))}</td><td class="k-${p.kind}">${esc(p.verdict)}</td><td style="white-space:nowrap"><b>${p.labels==null?'–':Math.round(p.labels*100)+'%'}</b> <span class="mut small">labels equal</span></td><td class="mut">${esc(p.evidence.join(' · ')||'no link found')}${p.ldiff&&p.ldiff.length?`<br><span class="small">differ: ${esc(p.ldiff.slice(0,10).join(', '))}${p.ldiff.length>10?' …+'+(p.ldiff.length-10):''}</span>`:''}</td></tr>`).join('')}</table></details></div>`).join('')}
// ---- section 2 ----
function unaDone(u){const st=S['name:'+u.company+':'+u.name];return !!(st&&st.act)}
function renderUna(){const list=D.unassigned.filter(u=>u.fits.length);const none=D.unassigned.filter(u=>!u.fits.length);
 return `<h2>2 · Company names nobody received (${list.length} with an aircraft that could fit)</h2>
 <p class="lead">These documented aircraft are not the name of any aircraft in your export. The aircraft below have the same architecture and were filed no earlier than a year before that aircraft appeared; unnamed ones first, then the company's other aircraft greyed with the reason they were not proposed. Pick the one it is, or say none. A name you give here to an aircraft that already has a name replaces that name.</p>`+
 list.filter(u=>VIEW!=='open'||!unaDone(u)).map(u=>{const k='name:'+u.company+':'+u.name;const st=S[k]||{};
  return `<div class="grp ${unaDone(u)?'done':''}" data-u="${esc(k)}"><h3>${esc(u.name)} <span class="mut" style="font-weight:400">— ${esc(u.company)} · ${esc(u.years)} · public type ${esc(u.type||'not documented')}</span>
  <button class="gi" style="font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer">🔍 images</button>
  <button class="none" style="font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:6px;background:${st.act==='none'?'#e8efff':'#fff'};cursor:pointer">✗ none of these</button></h3>
  <div class="small mut">${esc(u.basis)}</div>
  <div class="row">${u.fits.map(a=>acCard(a,(a.off?`<div class="small mut">not proposed: ${esc(a.off)}</div>`:'')+`<div class="btns"><button data-pick="${esc(key(a))}" class="${st.act==='pick'&&st.to===key(a)?'on':''}">✓ it is this one</button></div>`)).join('')}</div></div>`}).join('')+
 (none.length?`<p class="small mut">No fitting aircraft in the corpus: ${esc(none.map(u=>u.company+' — '+u.name).join('; '))}</p>`:'')}
let VIEW='all';
// ---- section 3 ----
const ACT3={ok:'✓ correct',wrong:'✗ not this aircraft → clear',other:'✎ another name'};
const setKey=a=>'set:'+key(a);
const setDone=a=>{const st=S[setKey(a)];return !!(st&&st.act&&(st.act!=='other'||st.name))};
function renderSet(){const L=(D.confirm||[]);
 return `<h2>3 · Names now set — confirm (${L.length})</h2>
 <p class="lead">Every aircraft that carries a real name in NAME_DECISIONS.csv. The first patent of a name keeps it plain; the others are v1, v2 … by priority date. Check the drawing against the photos (🔍 images) and confirm, or say it is not that aircraft. Rows marked "to confirm" in the note are the ones proposed for you, not chosen by you.</p>`+
 L.filter(a=>VIEW!=='open'||!setDone(a)).map(a=>{const st=S[setKey(a)]||{};
  return `<div class="grp ${setDone(a)?'done':''}" data-s="${esc(key(a))}"><h3>${esc(a.name)} <span class="mut" style="font-weight:400">— ${esc(a.pid)}${a.lab?' · '+esc(a.lab):''}</span>
   <button class="gi" style="font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer">🔍 images</button></h3>
   ${a.why?`<div class="small mut">${esc(a.why)}</div>`:''}
   <div class="row">${acCard(a,`<div class="btns">${Object.keys(ACT3).map(k=>`<button data-a3="${k}" class="${st.act===k?'on':''}">${ACT3[k]}</button>`).join('')}
    ${st.act==='other'?`<input class="nm3" placeholder="the right name" value="${esc(st.name||'')}">`:''}</div>`)}</div></div>`}).join('')}
function render(){const M=document.getElementById('main');M.innerHTML=VIEW==='set'?renderSet():(VIEW!=='una'?renderRep():'')+(VIEW!=='rep'?renderUna():'')+(VIEW==='all'||VIEW==='open'?renderSet():'');
 const r1=D.repeated.filter(grpDone).length,u=D.unassigned.filter(x=>x.fits.length),u1=u.filter(unaDone).length;
 const c=(D.confirm||[]),c1=c.filter(setDone).length;
 document.getElementById('prog').textContent=`repeated ${r1}/${D.repeated.length} · unassigned ${u1}/${u.length} · names confirmed ${c1}/${c.length} · export read: ${D.export.split('/').pop()}`;
 M.querySelectorAll('.grp[data-g]').forEach(el=>{const g=D.repeated[+el.dataset.g];
  el.querySelector('.gi').onclick=()=>img(q(g.name,g.aircraft[0].company),g.name);
  el.querySelectorAll('.ac').forEach(ac=>{const k=ac.dataset.k;const set=o=>{S[k]=Object.assign({},S[k]||{},o);
    if(o.act==='keep')g.aircraft.forEach(b=>{if(key(b)!==k&&S[key(b)]&&S[key(b)].act==='keep')S[key(b)].act=''});save();render()};
   ac.querySelectorAll('button[data-act]').forEach(b=>b.onclick=()=>set({act:b.dataset.act}));
   const nm=ac.querySelector('.nm');if(nm)nm.onchange=()=>set({name:nm.value});
   const ds=ac.querySelector('.dupsel');if(ds)ds.onchange=()=>set({of:ds.value});
   const nt=ac.querySelector('.note');nt.onchange=()=>{S[k]=Object.assign({},S[k]||{},{note:nt.value});save()};});
  const st=g.aircraft.map(a=>S[key(a)]&&S[key(a)].act);});
 M.querySelectorAll('.grp[data-u]').forEach(el=>{const k=el.dataset.u;const u=D.unassigned.find(x=>'name:'+x.company+':'+x.name===k);
  el.querySelector('.gi').onclick=()=>img(q(u.name,u.company),u.name);
  el.querySelector('.none').onclick=()=>{S[k]={act:'none'};save();render()};
  el.querySelectorAll('button[data-pick]').forEach(b=>b.onclick=()=>{S[k]={act:'pick',to:b.dataset.pick};save();render()})});
 M.querySelectorAll('.grp[data-s]').forEach(el=>{const a=(D.confirm||[]).find(x=>key(x)===el.dataset.s);const k=setKey(a);
  el.querySelector('.gi').onclick=()=>img(q(a.base||a.name,a.company),a.name+' — '+a.pid);
  el.querySelectorAll('button[data-a3]').forEach(b=>b.onclick=()=>{S[k]=Object.assign({},S[k]||{},{act:b.dataset.a3});save();render()});
  const nm=el.querySelector('.nm3');if(nm)nm.onchange=()=>{S[k]=Object.assign({},S[k]||{},{name:nm.value});save();render()}});
 M.querySelectorAll('.imgs img').forEach(im=>im.onclick=()=>{const z=document.getElementById('zoom');z.querySelector('img').src=im.src;z.querySelector('img').style.transform=im.style.transform;z.style.display='flex'});
}
document.getElementById('view').onchange=e=>{VIEW=e.target.value;render()};
document.getElementById('zoom').onclick=e=>e.currentTarget.style.display='none';
const cq=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
document.getElementById('exp').onclick=()=>{const L=[['section','name','patent_id','aircraft','action','new_name','duplicate_of','note'].join(',')];
 D.repeated.forEach(g=>g.aircraft.forEach(a=>{const st=S[key(a)]||{};if(!st.act)return;
  const of=st.of?D.repeated.flatMap(x=>x.aircraft).find(b=>key(b)===st.of):null;
  L.push(['repeated',g.name,a.pid,a.n>1?LET[a.v-1]:'',st.act,st.act==='keep'?g.name:st.act==='other'?st.name:'',of?lab(of):'',st.note].map(cq).join(','))}));
 D.unassigned.forEach(u=>{const st=S['name:'+u.company+':'+u.name];if(!st||!st.act)return;
  const a=st.to?u.fits.find(b=>key(b)===st.to):null;
  L.push(['unassigned',u.name,a?a.pid:'',a&&a.n>1?LET[a.v-1]:'',st.act==='pick'?'assign':'none',a?u.name:'','',a&&a.name?'replaces '+a.name:''].map(cq).join(','))});
 (D.confirm||[]).forEach(a=>{const st=S[setKey(a)];if(!st||!st.act)return;
  L.push(['set',a.name,a.pid,a.n>1?LET[a.v-1]:'',st.act,st.act==='other'?st.name:'','',''].map(cq).join(','))});
 saveToFolder(new Blob([L.join('\n')],{type:'text/csv'}),'NAME_SWEEP2.csv')};
render();
</script></body></html>"""

if __name__ == "__main__":
    main()
