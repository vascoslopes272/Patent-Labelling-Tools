#!/usr/bin/env python3
"""Concept board (2026-09-17): pick an evtol.news aircraft, then click the dataset aircraft that ARE it.

User 2026-09-17: "it would be easier to have the concepts and assign them to the aircraft on the image, and have a lot
of aircraft to choose from my dataset" + "I have already some decided — create a new list with this in mind".
The reverse of name_evtolnews.html: left = every directory aircraft (text only, link opens one side window);
right = a gallery of every approved unique aircraft (originals + D3) with its main figure, filtered by
same company / same architecture / all. Decisions already taken are shown on the thumbnails:
  named      the aircraft already carries a real name (NAME_DECISIONS.csv via notebook 04)
  said none  the user marked "none of these" for it on name_evtolnews.html (NAME_EVTOLNEWS_page_*.csv)

Export NAME_EVTOLNEWS.csv (same columns as the list page) → scripts/apply_name_evtolnews.py → apply_duplicate_names.py
→ build_identity_all.py → notebook 04.

    python scripts/build_name_concepts.py <evtolnews_pages.jsonl>
"""
import csv
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_name_evtolnews as B  # noqa: E402

PAGE = B.REPO / "notebooks" / "post-process" / "name_concepts.html"
TEMPLATE = B.REPO / "scripts" / "name_concepts_template.html"
# 2026-09-17 user: "a full page organised per rows — one row = the aircraft name and the link, under it the various ua
# that can be that aircraft". Same data and the same saved decisions (localStorage nameConcepts_v1) as the board.
ROWS_PAGE = B.REPO / "notebooks" / "post-process" / "name_rows.html"
ROWS_TEMPLATE = B.REPO / "scripts" / "name_rows_template.html"
DECISIONS = B.ROOT / "inputs" / "review_decisions"


PRECHECK_TIER = 2          # pre-check rows still open (tier 1 were applied)
MAX_PER_ROW = 8


def base_rows(P, concepts, planes):
    """User 2026-09-17: 'only the base name, like Aerial Rider … I don't need to see them all, the 30 more probable'.
    One row per (company, base name); candidates scored: same architecture +2, filing year inside the aircraft's
    years (-4/+1) +1, pre-check suggestion +3, company with few unnamed aircraft +1, said 'none' before -1.
    A candidate needs 3 points (architecture AND year, or the pre-check); rows are ranked by their best candidate."""
    import re
    import pandas as pd
    byaid = {p["aid"]: p for p in planes}
    pre = pd.read_csv(B.PRECHECK, dtype=str, keep_default_na=False) if B.PRECHECK.exists() else pd.DataFrame(columns=["aircraft_id", "suggest_slug"])
    pre_by_slug = {}
    for r in pre.itertuples():
        pre_by_slug.setdefault(r.suggest_slug, set()).add(r.aircraft_id)
    # one row per MAKER: pages of one maker match exactly the same dataset aircraft (same company word), so the
    # candidate set is the group key; the row name is the shared family name, else the company (user: base name only)
    import collections
    groups = {}
    for c in concepts:
        if not c["aids"]:
            continue
        p = P.loc[c["i"]]
        comp, _ = B.split_title(p.title, p["head"])
        g = groups.setdefault(tuple(sorted(c["aids"])), dict(fams=collections.Counter(), comps=collections.Counter(),
                                                               links=[], archs=set(), years=[], slugs=set()))
        g["fams"][B.base_name(p.title, p["head"])] += 1
        if comp:
            g["comps"][comp] += 1
        g["links"].append(dict(title=c["title"], url=c["url"], type=c["type"]))
        g["archs"] |= set(c["archs"])
        g["years"] += [int(y) for y in re.findall(r"\b(19[89]\d|20[0-3]\d)\b", p["desc"]) if int(y) <= 2026]
        g["slugs"].add(p.slug.strip("/"))
    merged = {}                                   # second pass: same company → one row
    for aids, g in groups.items():
        ck = g["comps"].most_common(1)[0][0].lower() if g["comps"] else aids
        m = merged.setdefault(ck, dict(fams=collections.Counter(), comps=collections.Counter(), links=[], archs=set(),
                                       years=[], slugs=set(), aidset=set()))
        for k in ("fams", "comps"):
            m[k].update(g[k])
        m["links"] += g["links"]; m["archs"] |= g["archs"]; m["years"] += g["years"]; m["slugs"] |= g["slugs"]
        m["aidset"] |= set(aids)
    groups = {tuple(sorted(m.pop("aidset"))): m for m in merged.values()}
    for aids, g in groups.items():
        company = g["comps"].most_common(1)[0][0] if g["comps"] else ""
        fam, n = g["fams"].most_common(1)[0]
        g.update(aids=set(aids), company=company,
                 name=fam if len(g["fams"]) == 1 or n * 2 > sum(g["fams"].values()) else (company or fam))
    rows = []
    for aids_key, g in groups.items():
        comp, name = g["company"], g["name"]
        # already named, or marked "none" on the list page (the user's earlier decisions) → not offered again
        unnamed = [a for a in g["aids"] if not byaid[a]["name"] and not byaid[a]["none"]]
        if not unnamed:
            continue
        y0, y1 = (min(g["years"]), max(g["years"])) if g["years"] else (None, None)
        scored = []
        for a in unnamed:
            p = byaid[a]
            why, sc = [], 0
            if p["arch"] in g["archs"]:
                sc += 2; why.append("same architecture")
            if y0 and p["year"].isdigit() and y0 - 4 <= int(p["year"]) <= y1 + 1:
                sc += 1; why.append("year fits")
            if any(a in pre_by_slug.get(sl, ()) for sl in g["slugs"]):
                sc += 3; why.append("pre-check")
            if len(unnamed) <= 5:
                sc += 1; why.append("few company aircraft")
            if sc >= 3 and ("pre-check" in why or ("same architecture" in why and "year fits" in why)):
                scored.append((sc, a, ", ".join(why)))
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[0], byaid[x[1]]["year"]))
        best = scored[0][0]
        rows.append(dict(key=f"{comp}|{name}", name=name, company=g["company"], links=g["links"],
                         archs=sorted(g["archs"]), years=[y0, y1],
                         cands=[dict(aid=a, score=sc, why=w) for sc, a, w in scored[:MAX_PER_ROW]],
                         more=max(0, len(scored) - MAX_PER_ROW), score=best + 1 / (1 + len(scored))))
    rows.sort(key=lambda r: -r["score"])
    return rows


def main():
    P = pd.DataFrame(list(B.page_records(Path(sys.argv[1]))))
    P["archs"] = P.apply(B.page_arch, axis=1)
    M = B.matcher(P)

    a = pd.read_csv(B.OUT / "tables" / "aircraft_table.csv", keep_default_na=False, dtype=str, low_memory=False)
    u = a[(a.dup_type.isin(["", "3"])) & (a.is_approved == "True")].copy()
    nvar = a[(a.is_primary == "True") & (a.is_approved == "True")].groupby("patent_id").size().to_dict()
    ndup = a[a.dup_type.isin(["1", "2"])].groupby("dup_root").size().to_dict()

    said_none = {}
    for f in sorted(DECISIONS.glob("NAME_EVTOLNEWS*.csv")):
        for r in csv.DictReader(open(f, newline="", encoding="utf-8")):
            if r["action"] == "none":
                said_none[r["aircraft_id"]] = r.get("decided_at", "")
            elif r["action"] == "assign":
                said_none.pop(r["aircraft_id"], None)

    concept_aids = {}
    planes = []
    for _, r in u.iterrows():
        for j in B.company_pages(r.assignee, M):
            concept_aids.setdefault(j, []).append(r.aircraft_id)
        v = int(r.variant or 1)
        figs = sorted((B.OUT / "images" / r.aircraft_id).glob("*.png"))
        planes.append(dict(aid=r.aircraft_id, pid=r.patent_id,
                           letter=B.LET[v - 1] if nvar.get(r.patent_id, 1) > 1 else "",
                           asg=r.assignee, year=r.app_year, arch=r.arch_gt or r.topType, title=r.title[:120],
                           name=r.aircraft_name if r.name_is_real == "True" else "",
                           none=r.aircraft_id in said_none, copies=ndup.get(r.patent_id, 0),
                           figs=["file://" + str(f) for f in figs[:8]]))

    concepts = []
    for j, p in P.iterrows():
        aids = concept_aids.get(j, [])
        concepts.append(dict(i=j, title=p.title, url=p.url, type=p.type or p.category, archs=sorted(p.archs),
                             name=B.short_name(p.title, p["head"]), aids=aids,
                             open=sum(1 for x in aids if not next(q for q in planes if q["aid"] == x)["name"])))
    concepts.sort(key=lambda c: (-(c["open"] > 0), c["title"].lower()))

    rows = base_rows(P, concepts, planes)
    for tpl, page in [(TEMPLATE, PAGE), (ROWS_TEMPLATE, ROWS_PAGE)]:
        html = tpl.read_text(encoding="utf-8")
        html = html.replace("/*CONCEPTS*/[]", json.dumps(concepts, ensure_ascii=False))
        html = html.replace("/*ROWS*/[]", json.dumps(rows, ensure_ascii=False))
        html = html.replace("/*PLANES*/[]", json.dumps(planes, ensure_ascii=False))
        page.write_text(html, encoding="utf-8")
    print(f"{len(concepts)} directory aircraft ({sum(c['open'] > 0 for c in concepts)} with unnamed aircraft of their company)")
    print(f"{len(planes)} dataset aircraft: {sum(bool(p['name']) for p in planes)} named, "
          f"{sum(p['none'] for p in planes)} marked none on the list page")
    print(f"rows page: {len(rows)} base names with a probable aircraft (top 30 shown first)")
    print(f"pages → {PAGE}\n        {ROWS_PAGE}")


if __name__ == "__main__":
    main()
