#!/usr/bin/env python3
"""apply_damage_decisions.py — write the user's damage-review decisions (notebooks/post-process/damage_review.html →
review_decisions/DAMAGE_RESTORE_DECISIONS.csv) and their typed extras (review_decisions/DAMAGE_RESTORE_EXTRA.csv)
into the wizard record; then regenerate the five per-batch copies.
    python scripts/apply_damage_decisions.py            # dry run: every change, per operation
    python scripts/apply_damage_decisions.py --apply    # back up, write the record, re-split
Only rows the decisions name are touched; the dry run lists each one. Checks before writing: every removed figure block
had no status; the lock replay (src/wizard_view.py) finds no new difference; no approved aircraft of a touched patent
ends with 0 or 2+ MAIN figures. Cells keep their types (booleans as True/False, counts as integers — the wizard's
xlBool() reads the text "False" as true). A 'keep' / 'unsure' / empty decision changes nothing.
"""
import sys, json, re, shutil, subprocess, collections
from datetime import datetime
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook, Workbook
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.wizard_view import replay

L0 = Path("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling")
RECORD = L0 / "inputs" / "record" / "reviewed_patents_Batch_ALL.xlsx"
RD = L0 / "inputs" / "review_decisions"
DECISIONS = RD / "DAMAGE_RESTORE_DECISIONS.csv"
EXTRA = RD / "DAMAGE_RESTORE_EXTRA.csv"
IMG_ROOT = L0 / "inputs" / "images"
APPLY = "--apply" in sys.argv[1:]
base = lambda p: re.sub(r"_arch\d+$", "", str(p))
def s(v): return "" if v is None else str(v)
def sid(v): return s(v).split(" — ", 1)[0].strip()

def load(path):
    rows = [list(r) for r in load_workbook(path)["Review"].iter_rows(values_only=True)]
    return rows[0], rows[1:]
hdr, body = load(RECORD)
ix = {c: i for i, c in enumerate(hdr)}
P, SEC, SUB, FLD, VAL, SRC, IMG = (ix[c] for c in ("Patent_ID", "Section", "Sub_Dimension", "Field", "Value", "Source", "Image_Path"))
before = [list(r) for r in body]

# the "id — Label" composite the wizard writes, taken from the record itself
composite = collections.defaultdict(collections.Counter)
for r in body:
    if " — " in s(r[VAL]): composite[(s(r[FLD]), sid(r[VAL]))][s(r[VAL])] += 1
def label(field, vid):
    c = composite[(field, vid)] or composite[(re.sub(r"^(wing|boom)\d+_", r"\g<1>1_", field), vid)]
    return c.most_common(1)[0][0] if c else vid

def find(pid=None, apid=None, sub=None, field=None):
    return [i for i, r in enumerate(body) if (pid is None or base(r[P]) == pid) and (apid is None or s(r[P]) == apid)
            and (sub is None or s(r[SUB]) == sub) and (field is None or s(r[FLD]) == field)]
def apid_of(pid, ua):
    a = f"{pid}_arch{ua}"
    return a if find(apid=a) else pid
def newrow(apid, sec, sub, fld, val, src=None, img=None):
    r = [None] * len(hdr); r[P], r[SEC], r[SUB], r[FLD], r[VAL], r[SRC], r[IMG] = apid, sec, sub, fld, val, src, img; return r

LOG = collections.defaultdict(list)            # operation -> lines
DROP, INSERT_AFTER, REPLACE_BLOCK = set(), collections.defaultdict(list), {}
def setv(i, v, op, why):
    old = body[i][VAL]
    if old == v: return
    body[i][VAL] = v; LOG[op].append(f"{s(body[i][P]):<24} {s(body[i][FLD]):<22} {old!r} -> {v!r}   {why}")
def insert(after_i, row, op, why):
    INSERT_AFTER[after_i].append(row); LOG[op].append(f"{s(row[P]):<24} {s(row[FLD]):<22} + {row[VAL]!r}   {why}")
def drop_block(pid, sub, op, why, require_blank=True):
    idx = find(pid=pid, sub=sub)
    st = [s(body[i][VAL]) for i in idx if s(body[i][FLD]) == "status"]
    assert idx, f"{pid} {sub}: block not in the record"
    assert not require_blank or not any(st), f"{pid} {sub}: refusing to remove a block with status {st}"
    DROP.update(idx); LOG[op].append(f"{pid:<24} - {sub[7:]}  ({len(idx)} rows)   {why}")

def image_path(pid, fname):
    hits = [p for p in IMG_ROOT.rglob(fname) if p.parent.name.split("_")[0] == pid]
    return str(hits[0]) if hits else None

D = pd.read_csv(DECISIONS, dtype=str, keep_default_na=False)
X = pd.read_csv(EXTRA, dtype=str, keep_default_na=False) if EXTRA.exists() else pd.DataFrame(columns=["key", "action", "patent_id", "arch_or_figure", "field", "new_value", "user_words"])
override_keep = set(X[X.action == "keep"].key)
touched = set()

for r in D.itertuples():
    if r.decision != "restore" or r.key in override_keep: continue
    pid, ua = r.patent_id, int(r.ua or 1); aux = json.loads(r.aux) if r.aux else {}
    edits = json.loads(r.edits or "{}"); mains = json.loads(r.main or "{}")
    touched.add(pid)
    if r.bug == "W2" and aux.get("kind") == "lost":
        fname = aux["file"]; sub = "Image: " + fname
        shdr, sbody = load(Path(r.last_good_snapshot)); six = {c: i for i, c in enumerate(shdr)}
        good = [[row[six[c]] if c in six else None for c in hdr] for row in sbody if base(row[six["Patent_ID"]]) == pid and s(row[six["Sub_Dimension"]]) == sub]
        assert good, f"{pid} {fname}: not in {r.last_good_snapshot}"
        ip = image_path(pid, fname); assert ip, f"{pid} {fname}: image file not found in its patent folder"
        e = edits.get(fname, {})
        for g in good:
            g[P] = pid; g[IMG] = ip if g[IMG] else g[IMG]
            f = s(g[FLD])
            if f == "status" and e.get("status"): g[VAL] = e["status"]
            if f == "per" and e.get("per") is not None: g[VAL] = e["per"] or None
            if f == "acState" and e.get("acState") is not None: g[VAL] = label("acState", e["acState"]) if e["acState"] else None
            if f == "arch" and e.get("ua"): g[VAL] = str(e["ua"])
        # a figure that was DISAPPROVED in the backup holds only figKey + status; approved on the page, it needs the full
        # approved block. Take the layout and the style fields from an approved sibling of the same patent — only when all
        # the patent's approved figures agree on them — and the user's view / flight state; it never takes the MAIN here.
        if e.get("status") == "approved" and not any(s(g[FLD]) == "per" for g in good):
            sib = [s(body[i][SUB]) for i in find(pid=pid, field="status") if s(body[i][VAL]) == "approved"]
            STYLE = ("acSty", "acCol", "bgSty", "bgCol", "parts", "qualityFlag", "rotation_deg")
            vals = {f: {s(body[j][VAL]) for sb in sib for j in find(pid=pid, sub=sb, field=f)} for f in STYLE}
            assert sib and all(len(v) == 1 for v in vals.values()), f"{pid}: approved siblings disagree on style {vals} — set it in the wizard"
            tmpl = [list(body[j]) for j in find(pid=pid, sub=sib[0])]
            fk = next(g[VAL] for g in good if s(g[FLD]) == "figKey")
            for t in tmpl:
                t[P], t[SUB], t[IMG] = pid, sub, ip
                f = s(t[FLD])
                if f == "figKey": t[VAL] = fk
                elif f == "per": t[VAL] = e.get("per") or None
                elif f == "acState": t[VAL] = label("acState", e["acState"]) if e.get("acState") else None
                elif f == "status": t[VAL] = "approved"
                elif f == "isMain": t[VAL] = False
                elif f == "arch": t[VAL] = str(e.get("ua") or s(t[VAL]) or "1")
                elif f in ("comment", "dupOf", "edgeTags", "stateNote", "hasLegends"): t[VAL] = None
            good = tmpl
            LOG["W2 restore reviewed figure"].append(f"{pid:<24}   {fname}: approved on the page; style {({k: next(iter(v)) for k, v in vals.items()})} from its approved siblings")
        # one MAIN per aircraft: the restored figure does not take the main unless the user chose it
        g_ua = next((s(g[VAL]) for g in good if s(g[FLD]) == "arch"), "1")
        others = [i for i in find(pid=pid, field="isMain") if body[i][VAL] is True
                  and any(s(body[j][VAL]) == g_ua for j in find(pid=pid, sub=s(body[i][SUB]), field="arch"))]
        for g in good:
            if s(g[FLD]) == "isMain" and g[VAL] is True and others and mains.get(g_ua) != fname: g[VAL] = False
        old = find(pid=pid, sub=sub)
        if old:
            DROP.update(old); INSERT_AFTER[old[-1]].extend(good)
            LOG["W2 restore reviewed figure"].append(f"{pid:<24} ~ {fname}: {len(old)} default rows -> {len(good)} reviewed rows")
        else:
            last = max(i for i in find(pid=pid) if s(body[i][SEC]) == "T2")
            INSERT_AFTER[last].extend(good); LOG["W2 restore reviewed figure"].append(f"{pid:<24} + {fname}: {len(good)} reviewed rows")
        if aux.get("replacement") and aux.get("replacement_blank"):
            drop_block(pid, "Image: " + aux["replacement"], "W2 remove unreviewed replacement", "never reviewed")
        for u, fn in mains.items():
            for i in find(pid=pid, field="isMain"):
                if any(s(body[j][VAL]) == str(u) for j in find(pid=pid, sub=s(body[i][SUB]), field="arch")):
                    setv(i, s(body[i][SUB]) == "Image: " + fn, "MAIN chosen on the page", f"aircraft {u} main = {fn}")
    elif r.bug in ("W2", "W2x") and aux.get("kind") in ("renamed", "leftover"):
        f = aux.get("replacement") if aux["kind"] == "renamed" else aux["file"]
        if f: drop_block(pid, "Image: " + f, "W2 remove unreviewed leftover", "never reviewed, no status")
    elif r.bug == "W1":
        tag = sid(r.good_value); apid = apid_of(pid, ua)
        rows = find(apid=apid, field="edgeTags")
        rows = [i for i in rows if s(body[i][SEC]) == "G1"]
        if rows:
            cur = [t for t in s(body[rows[0]][VAL]).split("|") if t]
            if tag not in cur: setv(rows[0], "|".join(cur + [tag]), "W1 restore tag", "lost on a save")
        else:
            anchor = next(i for i in find(apid=apid) if s(body[i][FLD]) in ("notPureArch", "topType"))
            insert(anchor, newrow(apid, "G1", "Edge-Case Tags", "edgeTags", tag), "W1 restore tag", "lost on a save")
    elif r.bug == "W3":
        apid = apid_of(pid, ua)
        for i in find(apid=apid, field="wCount"): setv(i, False, "W3 wingless", "phantom wing (wizard shows none for this type)")
        for i in find(apid=apid):
            if s(body[i][SEC]) == "M2" and re.match(r"wing\d+_", s(body[i][FLD])):
                DROP.add(i); LOG["W3 wingless"].append(f"{apid:<24} - {s(body[i][FLD])} = {body[i][VAL]!r}")
            if s(body[i][FLD]) == "wingConf" and s(body[i][VAL]): setv(i, None, "W3 wingless", "no wing architecture on a wingless type")
    elif r.bug == "W4":
        apid = apid_of(pid, ua)
        for i in find(apid=apid, field="wing1_plan"): setv(i, label("wing1_plan", "Trap"), "W4 Trap", "reloaded as Other")
        for i in find(apid=apid, field="wing1_plan_otherNote"): setv(i, None, "W4 Trap", "the note was the id")
    elif r.bug == "W6":
        apid = apid_of(pid, ua); fld = r.field.split("/")[-1].split(" ")[0]
        v = sid(r.good_value); v = True if v == "True" else False if v == "False" else int(v)
        rows = find(apid=apid, field=fld)
        if rows: setv(rows[0], v, "W6 quick count", "dropped on a save")
        else:
            card = fld.replace("_quickCount", "")
            anchor = find(apid=apid, field=card + "_quickOverride")[0]
            insert(anchor, newrow(apid, "M3", s(body[anchor][SUB]), fld, v), "W6 quick count", "dropped on a save")
    elif r.bug == "W7":
        fname = aux["file"]; sub = "Image: " + fname; e = edits.get(fname, {})
        for fld, (g, b) in aux["fields"].items():
            v = e.get(fld, g)
            for i in find(pid=pid, sub=sub, field=fld): setv(i, label(fld, v) if fld == "acState" else v, "W7 figure labels", "copied from its duplicate on reload")
        for fld in ("per", "acState", "status"):
            if fld in e and fld not in aux["fields"]:
                for i in find(pid=pid, sub=sub, field=fld): setv(i, label(fld, e[fld]) if fld == "acState" else e[fld], "W7 figure labels", "edited on the page")
    elif r.bug == "W8":
        apid = apid_of(pid, ua); fld = r.field.split("/")[-1].split(" ")[0]
        rows = find(apid=apid, field=fld)
        if rows: setv(rows[0], "Mixed", "W8 Mixed", "stripped on reload")

# ── the user's typed extras ──
for x in X.itertuples():
    if x.action == "set":
        apid = x.arch_or_figure if x.arch_or_figure.startswith(x.patent_id) else x.patent_id
        for i in find(apid=apid, field=x.field): setv(i, label(x.field, x.new_value), "user extras", x.user_words)
        touched.add(x.patent_id)
    elif x.action == "disapprove":
        sub = "Image: " + x.arch_or_figure
        idx = find(pid=x.patent_id, sub=sub); assert idx, (x.patent_id, sub)
        was_main = any(body[i][VAL] is True for i in idx if s(body[i][FLD]) == "isMain")
        assert not was_main, f"{x.patent_id} {x.arch_or_figure} is the MAIN figure — choose another main first"
        for i in idx:
            if s(body[i][FLD]) == "status": setv(i, "disapproved", "user extras", x.user_words)
            elif s(body[i][FLD]) != "figKey": DROP.add(i)
        LOG["user extras"].append(f"{x.patent_id:<24} - {x.arch_or_figure}: labels dropped (a disapproved figure exports only figKey + status)")
        touched.add(x.patent_id)

# ── build + checks ──
after = []
for i, r in enumerate(body):
    if i not in DROP: after.append(r)
    after.extend(INSERT_AFTER.get(i, []))
def frame(rows): return pd.DataFrame([[s(r[ix[c]]) for c in ("Patent_ID", "Section", "Sub_Dimension", "Field", "Value")] for r in rows],
                                     columns=["Patent_ID", "Section", "Sub_Dimension", "Field", "Value"])
new_diff = replay(frame(after)); old_diff = replay(frame(before))
F = frame(after); F["base"] = F.Patent_ID.map(base)
bad_main = []
for pid in sorted(touched):
    t = F[(F.base == pid) & (F.Section == "T2")].pivot_table(index="Sub_Dimension", columns="Field", values="Value", aggfunc="last")
    if "status" not in t: continue
    t = t[t.status == "approved"]
    for a, g in t.groupby(t.get("arch", pd.Series("1", index=t.index)).replace("", "1")):
        n = int((g.get("isMain", pd.Series(dtype=str)) == "True").sum())
        if n != 1: bad_main.append(f"{pid} aircraft {a}: {n} MAIN")

print(f"record {RECORD.name}: {len(before)} rows -> {len(after)} rows ({len(DROP)} removed, {sum(len(v) for v in INSERT_AFTER.values())} added)")
for op, lines in LOG.items():
    print(f"\n== {op}: {len(lines)}")
    for l in lines: print("  " + l)
print(f"\nlock replay: {len(old_diff)} differences before, {len(new_diff)} after")
print(f"MAIN check on {len(touched)} touched patents: " + ("OK" if not bad_main else "; ".join(bad_main)))
assert len(new_diff) <= len(old_diff), "the change would create a screen-vs-record difference"
if not APPLY: print("\ndry run — re-run with --apply"); sys.exit(0)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
bak = RECORD.parent / "_backups" / f"{RECORD.stem}.PRE_DAMAGE_{ts}.xlsx"; shutil.copy2(RECORD, bak)
wb = Workbook(); ws = wb.active; ws.title = "Review"; ws.append(hdr)
for r in after: ws.append(r)
wb.save(RECORD); print(f"\nwritten {RECORD} ({len(after)} rows); backup {bak}")
subprocess.run([sys.executable, str(Path(__file__).with_name("split_wizard_all_export.py")), str(RECORD), "--apply"], check=True)
