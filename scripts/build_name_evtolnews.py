#!/usr/bin/env python3
"""evtol.news name pass (2026-09-17): which unnamed aircraft could be a named aircraft of the eVTOL directory?

User ruling 2026-09-17: "enrich my dataset — tell me the patents that could match the name, I review, then the
names go to the names review". Only the TEXT of the directory pages is read (no photos are downloaded or stored);
the review page links each candidate to its evtol.news page, which opens in one side window.

Input   <scratch>/evtolnews_pages.jsonl        text of every https://evtol.news/<slug> page (scrape_evtolnews.py)
Writes  reference/evtolnews_directory.csv      slug, url, title, type, category — no page text
        notebooks/post-process/name_evtolnews.html
Export  NAME_EVTOLNEWS.csv → scripts/apply_name_evtolnews.py → NAME_DECISIONS.csv

A candidate = an unnamed approved aircraft (original or D3) whose assignee's distinctive company word is in the
page title / company line, or — for a person assignee — whose every name word is in the page text (founders).
The page's aircraft type is compared with our architecture only to rank the candidates.

    python scripts/build_name_evtolnews.py <evtolnews_pages.jsonl>
"""
import collections
import html as H
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
ROOT = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
OUT = ROOT / "outputs"
DEC = ROOT / "inputs" / "review_decisions" / "NAME_DECISIONS.csv"
PAGE = REPO / "notebooks" / "post-process" / "name_evtolnews.html"
DIRECTORY = REPO / "reference" / "evtolnews_directory.csv"
# 2026-09-17 pre-check (user: "those are a lot … which ones really matter?"): Claude compared every type-and-year
# plausible figure with the directory text; tier 1 = strong match, 2 = worth a look. The page shows these first.
PRECHECK = REPO / "reference" / "evtolnews_precheck.csv"
LET = "abcdefghijklmnopqrstuvwxyz"
NOT_AIRCRAFT = {"aircraft", "news", "home", "contact", "about"}

STOP = set("""inc llc ltd co corp corporation gmbh the company limited technology technologies tech aviation aerospace aero air sa ag
se and of for group systems system industries industry international intellectual property holdings holding operations aircraft ip
de mobility kg bv ab oy spa srl llp plc sas sarl kk univ university institute inst research development res dev science sciences
national china chinese korea korean japan beijing shanghai shenzhen guangzhou zhejiang jiangsu nanjing tianjin chengdu hangzhou xian
municipal city district province provincial electric electronics motor motors general new innovations innovation drone drones uav
flying flight vehicle vehicles engineering eng design designs services service solutions global usa dynamics labs lab ltda
automotive automobile energy power network networks robotics jiaotong normal polytechnic academy center centre state school
foundation works europe america american aeronautics aeronautical astronautics astronautic texas australia australian vtol
evtol autonomous office agency israel arizona detroit tian hamilton anthony california florida germany german france french
canada canadian india indian russia russian italy united kingdom british swiss singapore taiwan hong kong south north east
west advanced applied commerce commercial federal department ministry government defense defence space lift helicopter
helicopters aerodynamics aerodynamic aeronautic cool smith oklahoma sichuan jiangxi wuhan hubei hunan changsha zhuhai guangdong
shandong henan anhui fujian hebei shaanxi liaoning jilin chongqing xiamen suzhou wuxi ningbo qingdao dalian harbin shenyang
wang zhang chen yang huang zhao zhou liu sun zhu guo wu xu hu lin gao luo zheng liang song tang han feng deng cao peng administration century""".split())
ORG = re.compile(r"\b(univ|university|inst|institute|inc|corp|co|ltd|llc|gmbh|ag|sa|sas|spa|company|academy|school|"
                 r"center|centre|agency|office|administration|lab|laboratory|textron|aeronautics|aviation|technology)\b", re.I)
MAX_CANDS = 6


def page_records(path):
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r["slug"] in NOT_AIRCRAFT or not r.get("title"):
            continue
        t = r.get("text", "")
        k = t.rfind("Search Home ")
        body = (t[k + 12:] if k >= 0 else t).split("Recent Pages")[0]
        title = r["title"]
        head = body.replace(title, "", 2).strip()
        m = re.search(r"Aircraft type:\s*(.*?)\s*(?:Piloting|Capacity|First flight|Cruise|Propellers|Maximum|Range|$)", body)
        folder = " ".join(r.get("img_folder", [])).replace("Aircraft Directory Images", "").strip(" ()")
        yield dict(slug=r["slug"], url=r["url"], title=title, type=(m.group(1) if m else "")[:140],
                   category=folder, head=head[:300], desc=body[:5000])


def page_arch(p):
    s = (p["category"] + " " + p["type"] + " " + p["desc"][:3000]).lower()
    a = set()
    if re.search(r"lift ?(plus|\+|and) ?cruise", s): a.add("SLC")
    if re.search(r"tilt[- ]?rotor|vectored thrust|tilting (propellers|rotors)", s): a |= {"TR", "CVT", "DS"}
    if re.search(r"tilt[- ]?wing", s): a |= {"TW", "CVT"}
    if re.search(r"tilt[- ]?duct", s): a |= {"TR", "CVT"}
    if re.search(r"multicopter|wingless|quadcopter|hexacopter|octocopter|multirotor", s): a.add("MR")
    if re.search(r"helicopter|gyroplane|autogyro|gyrocopter", s): a.add("RC")
    if re.search(r"hover ?bike", s): a.add("HB")
    if re.search(r"tail[- ]?sitter", s): a.add("TB")
    if re.search(r"jetpack|jet pack|personal flying", s): a.add("PFV")
    if re.search(r"stopped rotor|slowed rotor", s): a.add("SRW")
    if re.search(r"pitch[- ]to[- ]cruise|winged multicopter", s): a.add("PTC")
    return a


def words(s):
    s = re.sub(r"\(.*?\)", " ", s)
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP and len(t) >= 4 and not t.isdigit()]


VERSION = re.compile(r"(\s+|^)(alpha|beta|gen(eration)?|v|mk|mark|prototype|model|version|series|block)\s*[-.]?\s*"
                     r"(\d+|one|two|three|four|[ivx]+)\b.*$"
                     r"|\s+(\d+-seater|cargo|drone|ems|military|winged|subscale|demonstrator|air taxi|production|mockup)\b.*$", re.I)


def family(name):
    """User ruling 2026-09-17: the name is the FAMILY name — 'Vahana', not 'Vahana Alpha One'; versions are
    numbered later by apply_duplicate_names.py (vN)."""
    name = re.sub(r"^generation\s*\d+,\s*", "", name, flags=re.I)          # 'Generation 4, Cora' → 'Cora'
    out = VERSION.sub("", name).strip(" ,-")
    out = re.sub(r"\s+(\d+\.\d+|alpha|beta)$", "", out, flags=re.I).strip()
    return out or name


GENERIC = {"drone", "pod", "evtol", "air taxi", "concept", "aircraft", "cargo drone", "one", "two"}


def split_title(title, head=""):
    """(company, aircraft part). The page header reads '<aircraft> <company> <city>, <country> www…', so the company
    is the longest start of the title that appears again in the header after position 0
    ('Kitty Hawk Heaviside' → 'Kitty Hawk', 'Heaviside')."""
    t = re.sub(r"\s*\((?:defunct|concept design|prototype|technology demonstrator|production models?|[^)]*)\)\s*", " ", title)
    t = re.sub(r"\s+", " ", t).strip()
    h = re.sub(r"\((?:photo|image) credit:[^)]*\)", " ", head, flags=re.I)
    h = re.sub(r"\s+", " ", h).strip().lower()
    w = t.split()
    for k in range(len(w) - 1, 0, -1):
        comp = " ".join(w[:k])
        if h.find(comp.lower(), 1) > 0:
            return comp, " ".join(w[k:])
    return "", t


def short_name(title, head=""):
    """Suggested (family) name typed into the box; the reviewer edits it."""
    comp, rest = split_title(title, head)
    t = (comp + " " + rest).strip()
    out = family(rest)
    return t if out.lower() in GENERIC or out.lower().startswith("unnamed") else out


def base_name(title, head=""):
    """The row name of the rows page (user 2026-09-17: 'only the base name, like Aerial Rider'): the family name, or the
    company when the family is only a model code (1A Series, 5A07, X8, AB-2)."""
    comp, rest = split_title(title, head)
    fam = short_name(title, head)
    code = re.fullmatch(r"[A-Za-z]{0,3}[-\s]?\d[\w.\-/]*(\s+series)?", fam, re.I) or fam.lower() in GENERIC
    return (comp or fam) if code else fam


def matcher(P):
    return dict(tf=collections.Counter(t for x in P.title for t in set(re.findall(r"[a-z0-9]+", x.lower()))),
                titles=[x.lower() for x in P.title], heads=[x.lower() for x in P["head"]],
                descs=[x.lower() for x in P["desc"]])


def company_pages(assignee, M):
    """{page index: reasons} — pages of the assignee's company (or naming the person assignee)."""
    found = {}
    for party in [x.strip() for x in assignee.split(";") if x.strip()]:
        w = words(party)
        if not w:
            continue
        person = not re.search(r"\([A-Z]{2}\)", party) and not ORG.search(party)
        for j in range(len(M["titles"])):
            if person:
                if len(w) >= 2 and all(re.search(rf"\b{re.escape(t)}\b", M["descs"][j]) for t in w):
                    found.setdefault(j, set()).add(f"inventor/founder {party.title()} named on the page")
            elif M["tf"][w[0]] <= 25 and (re.search(rf"\b{re.escape(w[0])}\b", M["titles"][j])
                                          or re.search(rf"\b{re.escape(w[0])}\b", M["heads"][j][:200])):
                found.setdefault(j, set()).add(f"company word “{w[0]}”")
    return found


def main():
    src = Path(sys.argv[1])
    P = pd.DataFrame(list(page_records(src)))
    P["archs"] = P.apply(page_arch, axis=1)
    DIRECTORY.parent.mkdir(exist_ok=True)
    P[["slug", "url", "title", "type", "category"]].to_csv(DIRECTORY, index=False)

    a = pd.read_csv(OUT / "tables" / "aircraft_table.csv", keep_default_na=False, dtype=str, low_memory=False)
    u = a[(a.dup_type.isin(["", "3"])) & (a.is_approved == "True") & (a.name_is_real != "True")].copy()
    nvar = a[(a.is_primary == "True") & (a.is_approved == "True")].groupby("patent_id").size().to_dict()
    dec = {r["patent_id"]: r for r in pd.read_csv(DEC, keep_default_na=False, dtype=str).to_dict("records")}

    M = matcher(P)
    pre = pd.read_csv(PRECHECK, dtype=str, keep_default_na=False).set_index("aircraft_id") if PRECHECK.exists() else pd.DataFrame()
    by_slug = {sl.strip("/"): j for j, sl in enumerate(P.slug)}
    items = []
    for _, r in u.iterrows():
        found = company_pages(r.assignee, M)
        pc = pre.loc[r.aircraft_id] if r.aircraft_id in pre.index else None
        if pc is not None and by_slug.get(pc.suggest_slug) is not None:
            found.setdefault(by_slug[pc.suggest_slug], set()).add("suggested by the pre-check")
        if not found:
            continue
        arch = r.arch_gt or r.topType
        cands = []
        for j, why in found.items():
            p = P.iloc[j]
            ok = (arch in p.archs) if p.archs else None
            cands.append(dict(title=p.title, url=p.url, type=p.type or p.category, ok=ok, why="; ".join(sorted(why)),
                              name=short_name(p.title, p['head'])))
            if pc is not None and p.slug.strip("/") == pc.suggest_slug:
                cands[-1].update(suggested=True, name=pc.suggest_name)
        cands.sort(key=lambda c: (not c.get("suggested"), {True: 0, None: 1, False: 2}[c["ok"]], c["title"]))
        if len(cands) > MAX_CANDS:          # a big maker (Airbus, Bell…): only the pages whose type fits
            cands = [c for c in cands if c["ok"] is not False or c.get("suggested")][:MAX_CANDS] or cands[:MAX_CANDS]
        v = int(r.variant or 1)
        figs = sorted((OUT / "images" / r.aircraft_id).glob("*.png"))
        d = dec.get(r.patent_id, {})
        items.append(dict(aid=r.aircraft_id, pid=r.patent_id, v=v, letter=LET[v - 1] if nvar.get(r.patent_id, 1) > 1 else "",
                          assignee=r.assignee, year=r.app_year, arch=arch, title=r.title, name=r.aircraft_name,
                          prior=(f"{d.get('decision','')}: {d.get('comment','')}" if d else ""),
                          figs=["file://" + str(f) for f in figs[:6]], cands=cands,
                          best=sum(c["ok"] is True for c in cands),
                          tier=int(pc.tier) if pc is not None else 9, pre=pc.note if pc is not None else ""))
    items.sort(key=lambda x: (x["tier"], -(x["best"] > 0), x["assignee"], x["aid"]))
    tpl = (REPO / "scripts" / "name_evtolnews_template.html").read_text(encoding="utf-8")
    PAGE.write_text(tpl.replace("/*DATA*/[]", json.dumps(items, ensure_ascii=False)), encoding="utf-8")
    n_ok = sum(x["best"] > 0 for x in items)
    print(f"{len(P)} directory pages → {DIRECTORY}")
    print(f"{len(u)} unnamed aircraft; {len(items)} with a candidate ({n_ok} with a type match); "
          f"{sum(len(x['cands']) for x in items)} candidates")
    print(f"pre-check: {sum(x['tier'] == 1 for x in items)} strong, {sum(x['tier'] == 2 for x in items)} worth a look")
    print(f"page → {PAGE}")


if __name__ == "__main__":
    main()
