"""
wizard_link.py — join Stage 03a onto the human labels, and name every aircraft.

Stage 03a. Two jobs:

1. **Read the wizard's human record** (`reviewed_patents_Batch_NN.xlsx`, long
   format: Patent_ID / Section / Field / Value) for the handful of T1 fields
   this stage needs — approval, disapproval reason, aircraftName, duplicate
   type and duplicate-of. Every batch file is read, not just the current
   batch's, because a duplicate's original may sit in another batch.

2. **Give every patent an `aircraft_group`** — the working aircraft name:

       wizard aircraftName                      (the annotator's own name)
    >  the original's name, for a D1 / D2       (same aircraft, inherits)
    >  the original's name + letter, for a D3   (a variant: new name, same root)
    >  "<assignee> <N>", generated               (nothing else known)

   N is the next unused number for that assignee across the WHOLE corpus, so
   a name generated for Batch_05 can never collide with one the annotator
   typed in Batch_02. The generated names follow the annotator's own scheme
   (see the duplicate-naming rule: D1/D2 share the original's name, a D3 is a
   different aircraft and takes a new one).

Nothing here decides the REAL aircraft name (S4, Midnight, Vertiia). That is
the reviewer's call, typed into `aircraft_name_human`; `aircraft_group` is the
fallback that guarantees no patent is ever nameless.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

WIZARD_FIELDS = ("isApproved", "t1DisapproveReason", "aircraftName",
                 "isDuplicate", "duplicateType", "duplicateId",
                 # variants: archCount on the base id, topType / notPureArch /
                 # edgeTags on the <pid>_archN ids the wizard writes per aircraft
                 "archCount", "topType", "notPureArch", "edgeTags")

# ─── The annotator's disapproval reason as ground truth ──────────────────────
# When the human threw a patent out FOR a reason, that reason is a decision they
# already made and must not be asked again. Only reasons that name the thing
# count, matched case-insensitively on the reason text.
#
# "Out of Domain / Out of TD" is deliberately NOT here. It is about to be split
# into sub-reasons (ELECTRIC / STOL / UAV PURE / OTHER), so today's single label
# does not say WHICH of them applied — reading it as "not electric" would invent
# a decision the annotator did not make. Add the sub-reasons below once the
# wizard writes them.
HUMAN_TRUTH_REASONS = [
    # (regex over the reason text, field, value)
    (r"not\s*-?\s*vtol|\bstol\b|\bctol\b", "takeoff", "STOL"),
    (r"\bnon[-\s]?electric\b|\bnot\s+electric\b|\bcombustion\b|—\s*electric\b",
     "electric", "No"),
    # "Pure UAV" is a disapproval the annotator made on purpose: no passenger /
    # AAM application. It settles the UAV question for that (disapproved) patent.
    (r"\bpure\s+uav\b", "uav", "Pure"),
]


def human_truth(record: dict | None) -> dict:
    """What the annotator's disapproval reason already settles, if anything.

    Returns {} for an approved patent, for a reason that settles nothing, and
    for every "Out of Domain" reason — see HUMAN_TRUTH_REASONS.
    """
    record = record or {}
    reason = (record.get("disapprove_reason") or "").strip()
    if not reason or record.get("approved") is True:
        return {}
    out = {}
    for pattern, field, value in HUMAN_TRUTH_REASONS:
        if re.search(pattern, reason, re.IGNORECASE):
            out[field] = value
            out[f"{field}_evidence"] = f"annotator disapproved: {reason}"
    if out:
        # A reason that NAMES the thing wins, even under an "Out of TD" heading —
        # that is exactly what the coming sub-reasons will look like
        # ("Out of TD — Electric"), and it is a decision the annotator did make.
        return out
    if re.search(r"out\s+of\s+(domain|td|technological)", reason, re.IGNORECASE):
        # A bare out-of-domain reason names nothing yet. Reading it as
        # "not electric" would invent a decision — leave it for the reviewer.
        return {}
    return {}

# Companies whose canonical label is a bucket, not an assignee. A generated
# name for these uses the actual assignee string instead.
_BUCKET_COMPANIES = {"Individual Inventor", "Unknown / Independent", None, ""}

_TRAILING_CC_RE = re.compile(r"\s*\([^()]*\)\s*$")          # "(US)", "(CHENGDU CITY, CN)"
_GROUP_NAME_RE = re.compile(r"^(?P<prefix>.*?)(?:\s+(?P<num>\d+)(?P<suffix>[a-z])?)?\s*$")


def _truthy(v) -> "bool | None":
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    return None


def _dup_type(v) -> "str | None":
    """'2 — D2 — Same aircraft…' → '2'. The wizard writes 'ID — Label'."""
    if v is None:
        return None
    m = re.match(r"\s*([123])\b", str(v))
    return m.group(1) if m else None


def _id_of(v) -> "str | None":
    """'MR — Wingless — Multirotor' → 'MR' (the wizard writes 'ID — Label')."""
    if v is None or str(v).strip() in ("", "nan"):
        return None
    return str(v).split(" — ")[0].strip()


def _tags(v) -> list[str]:
    """'UAVSimilar|ElectricSimilar' → ['UAVSimilar', 'ElectricSimilar']."""
    if v is None or str(v).strip() in ("", "nan"):
        return []
    return [t.split(" — ")[0].strip() for t in re.split(r"[|;,]", str(v)) if t.strip()]


def _arch_count(raw, n_variant_records: int) -> int:
    """The wizard writes archCount as 'True' for a single aircraft and '2'..'6'
    otherwise; the <pid>_archN records are the authoritative count."""
    if n_variant_records:
        return max(n_variant_records, 1)
    s = str(raw).strip() if raw is not None else ""
    return int(s) if s.isdigit() else 1


def _live_files(dir_path: Path) -> list[Path]:
    """The current per-batch exports only — never the PRE_/BACKUP_ copies."""
    out = []
    for p in sorted(Path(dir_path).glob("reviewed_patents_Batch_*.xlsx")):
        if ".PRE_" in p.name or ".BACKUP_" in p.name or p.name.startswith("~$"):
            continue
        out.append(p)
    return out


def load_wizard_reviews(dir_path: "str | Path", verbose: bool = True) -> dict[str, dict]:
    """patent_id -> the T1 fields Stage 03a cares about, across every batch file."""
    import pandas as pd

    dir_path = Path(dir_path)
    out: dict[str, dict] = {}
    files = _live_files(dir_path) if dir_path.exists() else []
    for f in files:
        try:
            df = pd.read_excel(f, sheet_name="Review",
                               usecols=["Patent_ID", "Section", "Field", "Value"], dtype=object)
        except ValueError as exc:                      # no 'Review' sheet
            if verbose:
                print(f"⚠  {f.name}: {exc} — skipped")
            continue
        df = df[df["Field"].isin(WIZARD_FIELDS)]
        # edgeTags is also a per-IMAGE field on T2 ("Image label is not
        # corresponding"); only the G1 ones are aircraft edge tags.
        df = df[~((df["Field"] == "edgeTags") & (df["Section"] != "G1"))]
        pid_str = df["Patent_ID"].astype(str).str.strip()
        df = df.assign(_base=pid_str.str.replace(r"_arch\d+$", "", regex=True),
                       _arch=pid_str.str.extract(r"_arch(\d+)$")[0])
        m = re.search(r"Batch_\d+", f.name)
        batch = m.group(0) if m else f.stem
        for pid, g in df.groupby("_base"):
            pid = str(pid).strip()
            base_rows = g[g["_arch"].isna()]
            vals = dict(zip(base_rows["Field"], base_rows["Value"]))
            variants = []
            for n, vg in g[g["_arch"].notna()].groupby("_arch"):
                vv = dict(zip(vg["Field"], vg["Value"]))
                variants.append({"n": int(n), "top_type": _id_of(vv.get("topType")),
                                 "not_pure": _truthy(vv.get("notPureArch")),
                                 "edge_tags": _tags(vv.get("edgeTags"))})
            variants.sort(key=lambda v: v["n"])
            edge_tags = sorted(set(_tags(vals.get("edgeTags")))
                               | {t for v in variants for t in v["edge_tags"]})
            name = vals.get("aircraftName")
            name = str(name).strip() if name is not None and str(name).strip() not in ("", "nan") else None
            dup_of = vals.get("duplicateId")
            dup_of = str(dup_of).strip() if dup_of is not None and str(dup_of).strip() not in ("", "nan") else None
            out[pid] = {
                "approved": _truthy(vals.get("isApproved")),
                "disapprove_reason": (str(vals["t1DisapproveReason"]).strip()
                                      if vals.get("t1DisapproveReason") is not None else None),
                "aircraft_name": name,
                "is_duplicate": _truthy(vals.get("isDuplicate")),
                "duplicate_type": _dup_type(vals.get("duplicateType")),
                "duplicate_of": dup_of,
                "arch_count": _arch_count(vals.get("archCount"), len(variants)),
                "variants": variants,            # [{n, top_type, not_pure, edge_tags}]
                "edge_tags": edge_tags,          # G1 tags across base + variants
                "batch": batch,
                "file": f.name,
            }
    if verbose:
        if not files:
            print(f"⚠  No reviewed_patents_Batch_*.xlsx under {dir_path} — "
                  f"every aircraft_group will be generated.")
        else:
            named = sum(1 for v in out.values() if v["aircraft_name"])
            print(f"Wizard record: {len(out)} patents from {len(files)} file(s); "
                  f"{named} carry an aircraftName.")
    return out


# ─── Naming ──────────────────────────────────────────────────────────────────

def split_group_name(name: str | None) -> tuple[str, "int | None", str]:
    """'Bell Helicopter 12b' → ('Bell Helicopter', 12, 'b'); 'Archer Aviation' → (…, None, '')."""
    if not name:
        return "", None, ""
    m = _GROUP_NAME_RE.match(str(name).strip())
    if not m:
        return str(name).strip(), None, ""
    num = int(m.group("num")) if m.group("num") else None
    return m.group("prefix").strip(), num, m.group("suffix") or ""


def _assignee_prefix(company_canonical: str | None, assignee_raw: str | None) -> str:
    if company_canonical not in _BUCKET_COMPANIES:
        return str(company_canonical).strip()
    first = str(assignee_raw or "").split(";")[0].strip()
    first = _TRAILING_CC_RE.sub("", first).strip()
    return first or "Unknown"


def assign_aircraft_groups(
    patent_ids: list[str],
    batch_meta: dict[str, dict],
    excel_index: dict[str, dict],
    wizard: dict[str, dict],
) -> dict[str, dict]:
    """patent_id -> {"aircraft_group", "aircraft_group_source", "aircraft_group_note"}.

    Call it over the WHOLE corpus (every batch's patent ids) so generated
    numbers are unique corpus-wide, then look rows up per batch.
    """
    # 0. One spelling per name. The annotator typed "AERHART LLC" on one patent
    #    and "Aerhart Llc" on its duplicate; those are the same aircraft and must
    #    not read as two. The most-used spelling wins, ties broken by the order
    #    the patents come in, and every later lookup goes through canon_name().
    spellings: dict[str, Counter] = defaultdict(Counter)
    for w in wizard.values():
        if w.get("aircraft_name"):
            n = str(w["aircraft_name"]).strip()
            spellings[n.lower()][n] += 1
    canon = {k: c.most_common(1)[0][0] for k, c in spellings.items()}

    def canon_name(name):
        return canon.get(str(name).strip().lower(), str(name).strip()) if name else name

    # 1. What the annotator already typed, and which prefix they used per company,
    #    so a generated "Bell / Textron 31" does not sit next to "Bell Helicopter 30".
    used: dict[str, set] = defaultdict(set)              # prefix.lower() -> {numbers}
    prefix_by_company: dict[str, Counter] = defaultdict(Counter)
    display_prefix: dict[str, str] = {}                  # prefix.lower() -> as typed
    for pid, w in wizard.items():
        if not w.get("aircraft_name"):
            continue
        prefix, num, _ = split_group_name(canon_name(w["aircraft_name"]))
        key = prefix.lower()
        display_prefix.setdefault(key, prefix)
        used[key].add(num if num is not None else 0)
        comp = (batch_meta.get(pid) or {}).get("company_canonical")
        if comp not in _BUCKET_COMPANIES:
            prefix_by_company[comp][key] += 1        # case-insensitive: "BELL HELICOPTER" == "Bell Helicopter"

    result: dict[str, dict] = {}

    def _order_key(pid):
        m = excel_index.get(pid, {})
        return (str(m.get("app_year") or "9999"), pid)

    ordered = sorted(dict.fromkeys(patent_ids), key=_order_key)

    # 2. Wizard names first — they are the human record.
    for pid in ordered:
        w = wizard.get(pid) or {}
        if w.get("aircraft_name"):
            result[pid] = {"aircraft_group": canon_name(w["aircraft_name"]),
                           "aircraft_group_source": "wizard", "aircraft_group_note": None}

    # 3. Duplicates inherit (D1/D2) or branch (D3) from their original.
    #    Two passes so a chain original->D2->D2 resolves whatever the order.
    for _ in range(3):
        for pid in ordered:
            if pid in result:
                continue
            w = wizard.get(pid) or {}
            orig = w.get("duplicate_of")
            dtype = w.get("duplicate_type")
            if not orig or orig not in result:
                continue
            root = result[orig]["aircraft_group"]
            if dtype in ("1", "2"):
                # A D1/D2 IS the original aircraft, so it takes the original's
                # name even when the annotator typed their own spelling on it.
                result[pid] = {"aircraft_group": root,
                               "aircraft_group_source": f"inherited_D{dtype}",
                               "aircraft_group_note": f"same aircraft as {orig}"}
            elif dtype == "3":
                # A D3 is a DIFFERENT aircraft (same core invention, visible
                # differences) and takes its own next number — the ruled
                # convention. Letters are reserved for the variants INSIDE one
                # patent (see variant_names).
                prefix, _, _ = split_group_name(root)
                key = prefix.lower()
                n = (max(used[key]) + 1) if used[key] else 1
                used[key].add(n)
                result[pid] = {"aircraft_group": f"{display_prefix.get(key, prefix)} {n}",
                               "aircraft_group_source": "generated_D3",
                               "aircraft_group_note": f"D3 of {orig} ({root}) — different aircraft, new number"}

    # 4. Everything else: "<prefix> <N>", N unique for that prefix corpus-wide.
    for pid in ordered:
        if pid in result:
            continue
        bm = batch_meta.get(pid) or {}
        meta = excel_index.get(pid, {})
        comp = bm.get("company_canonical")
        if comp not in _BUCKET_COMPANIES and prefix_by_company.get(comp):
            key = prefix_by_company[comp].most_common(1)[0][0]
            prefix = display_prefix[key]
        else:
            prefix = _assignee_prefix(comp, meta.get("assignee"))
            key = prefix.lower()
            prefix = display_prefix.setdefault(key, prefix)
        n = (max(used[key]) + 1) if used[key] else 1
        used[key].add(n)
        w = wizard.get(pid) or {}
        note = None
        if w.get("duplicate_of"):
            note = f"duplicate of {w['duplicate_of']}, which has no name yet"
        result[pid] = {"aircraft_group": f"{prefix} {n}",
                       "aircraft_group_source": "generated", "aircraft_group_note": note}

    # 5. Consistency flag the naming rule asks for: a D1/D2 whose wizard name
    #    differs from its original's is an error in the human record.
    for pid in ordered:
        w = wizard.get(pid) or {}
        orig = w.get("duplicate_of")
        if w.get("aircraft_name") and w.get("duplicate_type") in ("1", "2") and orig in result:
            # the original's spelling wins, whatever the duplicate says
            result[pid]["aircraft_group"] = result[orig]["aircraft_group"]
        if (w.get("aircraft_name") and w.get("duplicate_type") in ("1", "2")
                and orig in result
                and _same_name(result[orig]["aircraft_group"], w["aircraft_name"]) is False):
            result[pid]["aircraft_group_note"] = (
                f"D{w['duplicate_type']} name differs from original {orig} "
                f"({result[orig]['aircraft_group']})")
    return result


def _same_name(a: str | None, b: str | None) -> "bool | None":
    """Case- and whitespace-insensitive: the annotator typed the same name in
    two casings ("ARCHER AVIATION" / "Archer Aviation") and that is not an error."""
    if a is None or b is None:
        return None
    return " ".join(str(a).split()).lower() == " ".join(str(b).split()).lower()


def group_summary(groups: dict[str, dict], patent_ids: list[str] | None = None) -> Counter:
    ids = patent_ids if patent_ids is not None else list(groups)
    return Counter(groups[p]["aircraft_group_source"] for p in ids if p in groups)
