import pandas as pd, re, collections, sys
D="/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_DS/data"
B=sys.argv[1] if len(sys.argv)>1 else "Batch_01"
# optional 2nd arg: an explicit xlsx to audit (e.g. a fresh wizard download)
SRC=sys.argv[2] if len(sys.argv)>2 else f"{D}/03c_CORRECTED_wizard_exports/reviewed_patents_{B}.xlsx"
n=pd.read_excel(SRC,sheet_name="Review")
def c(v): return str(v).split(' — ')[0].strip()
base=lambda p: re.sub(r'_arch\d+$','',str(p))
P=set(n.Patent_ID.astype(str))
F=collections.defaultdict(dict)                      # patent -> field -> value
FIG=collections.defaultdict(lambda: collections.defaultdict(dict))
for _,r in n.iterrows():
    sd=str(r.Sub_Dimension)
    if sd.startswith("Image: "): FIG[str(r.Patent_ID)][sd[7:]][str(r.Field)]=r.Value
    else: F[str(r.Patent_ID)][str(r.Field)]=r.Value
ap={p for p in P if str(F[p].get('isApproved'))=='True' or str(F[base(p)].get('isApproved'))=='True'}
d2={p for p in P if c(F[p].get('duplicateType'))=='2'}
arch={p for p in P if re.search(r'_arch\d+$',p)}
live=[p for p in P if p in ap and p not in d2 and (p in arch or not any(q.startswith(p+'_arch') for q in P))]
top={p:c(F[p].get('topType')) for p in P if F[p].get('topType') is not None}
FIX={'SLC','RC','MR','HB','PFV','TB','PTC'}; CVTB={'TW','TR','DS','CVT','SRW'}
out=[]
def flag(rule,pid,msg): out.append((rule,pid,msg))
nn=lambda v:1 if str(v)=='True' else (int(float(v)) if re.fullmatch(r'[\d.]+',str(v or '')) else 0)

for p in live:
    f=F[p]; t=top.get(p)
    wc=nn(f.get('wCount'))
    tilts=[c(f.get(f'wing{i}_tilt')) for i in range(1,5) if f.get(f'wing{i}_tilt') is not None]
    pk=[c(v) for k,v in f.items() if k.endswith('_propKin') and v is not None]
    # Which wings actually CARRY propulsors — the wizard's lock turns on this, not
    # on the bare tilt flags: a fixed canard carrying nothing does not make a TW
    # into a CVT, because tilting it would achieve nothing.
    propelled = {i for i in range(1,5) if f.get(f'wing{i}_propKin') is not None
                 or any(k.startswith(f'wing{i}_t') and k.endswith('_propKin') for k in f)}
    tiltw  = {i for i in range(1,5) if c(f.get(f'wing{i}_tilt'))=='Tilt'}
    fixedw = {i for i in range(1,5) if c(f.get(f'wing{i}_tilt'))=='Fixed'}
    # thrust that does NOT tilt with the wing: a propelled wing that stays fixed,
    # or propulsors carried anywhere off the wings.
    offwing = [k for k in f if k.endswith('_propKin') and not k.startswith('wing')]
    # A boom group can tilt as a structure (v14 opt-in "Booms tilt"), which vectors
    # every propulsor it carries WITHOUT any of them being propKin=Tilt. Missing
    # this made three tilt-rotors look like nothing tilted.
    boomtilt = [k for k,v in f.items() if re.match(r'boom\d+_tilts$',k) and str(v)=='True']
    # L1 Tilt Wing — at least one wing tilts, and every PROPELLED wing is a tilting one
    if t=='TW':
        if not tiltw:
            flag('L1','TW with no tilting wing at all',p)
        elif propelled - tiltw:
            flag('L1','TW with a PROPELLED wing that does not tilt (that is CVT)',
                 f"{p}  propelled={sorted(propelled)} tilting={sorted(tiltw)}")
    # L2 Tilt Rotor — the propulsors are what tilt
    if t=='TR' and pk and 'Tilt' not in pk and not tiltw and not boomtilt:
        flag('L2','TR but nothing tilts — no tilting propulsor, wing or boom',
             f"{p}  propKin={sorted(set(pk))}")
    # L3 RETIRED 2026-09-03. It flagged "a fixed architecture with tilting parts",
    # borrowing 02a's FIXED_ARCH_TYPES — but that set exists for Rule A1 (forcing
    # acState=Invariant) and is NOT a physics lock. A tilting boom is legitimate on
    # any architecture: boomN_tilts means the boom rotates RELATIVE TO THE FUSELAGE
    # carrying its propulsors, so a level-cabin tilt-body (TB + fusKin=LevelCabin)
    # and a multirotor with tilting arms (MR + fusKin=Fixed) both have it correctly.
    # The corpus agrees: 6 of the 13 tilting-boom records are MR, which would make
    # "MR cannot tilt" a rule contradicted by half its own subjects.
    #
    # 02a already does this properly — _articulation_evidence() asks the patent's
    # own fields rather than inheriting the answer from topType. Nothing here can
    # improve on that, so this lock is removed rather than narrowed.
    # L4 CVT — the headline definition: "Fixed AND tilting thrust mechanisms
    # present on the same aircraft at the same time". Deliberately NOT the
    # "at least one wing tilts" clause that follows it in the option text: 21 of
    # the 27 labelled CVTs combine a TILTING PROPULSOR with a fixed one and have
    # no tilting wing at all, so that clause would reject 78% of them. The clause
    # is the thing that is wrong, not the labels — see the note to the codebook.
    if t=='CVT':
        pkt=[k for k,v in f.items() if k.endswith('_propKin') and c(v)=='Tilt']
        pkf=[k for k,v in f.items() if k.endswith('_propKin') and c(v)=='Fixed']
        if not tiltw and not pkt and not boomtilt:
            flag('L4','CVT where nothing tilts at all',p)
        elif not (tiltw or pkt) or not (pkf or (propelled & fixedw)):
            flag('L4','CVT with no fixed thrust source alongside the tilting one',
                 f"{p}  tiltingWings={sorted(tiltw)} tiltProp={len(pkt)} fixedProp={len(pkf)}")
    # L5 empennage
    et=c(f.get('empType'))
    if et=='Tailless' and str(f.get('empTilts'))=='True':
        flag('L5','Tailless empennage that tilts',p)
    empprop=[k for k in f if k.startswith('emp_') and k.endswith('_count')]
    if et=='Tailless' and any(nn(f.get(k))>0 for k in empprop):
        flag('L5','Tailless but propulsors recorded on the empennage',p)
    # L6 booms
    bp=str(f.get('boomsPresent'))
    grp=sorted({m.group(1) for k in f if (m:=re.match(r'boom(\d+)_attach$',k))})
    if bp=='True' and not grp: flag('L6','boomsPresent ticked but no boom group',p)
    if bp!='True' and grp:     flag('L6','boom groups present but boomsPresent not ticked',f"{p}  groups={grp}")
    for g in grp:
        if nn(f.get(f'boom{g}_count'))==0:
            flag('L6',f'boom group {g} has a count of 0',p)
    # L7 wings
    panels=[i for i in range(1,5) if f.get(f'wing{i}_role') is not None or f.get(f'wing{i}_posL') is not None]
    if wc and panels and max(panels)>wc:
        flag('L7','a wing panel is labelled beyond wCount',f"{p}  wCount={wc} panels={panels}")
    if t in {'TW','TR','DS','CVT','SLC','SRW','PTC'} and wc==0 and c(f.get('wingConf'))=='W':
        flag('L7','winged architecture with Standard Wings but wCount 0',p)
    # L8 duplicates
    if str(f.get('isDuplicate'))=='True' and not f.get('duplicateId'):
        flag('L8','flagged duplicate with no duplicateId',p)
    di=str(f.get('duplicateId') or '').strip()
    if di and di not in P and di not in {base(x) for x in P}:
        flag('L8','duplicateId points outside this batch',f"{p} -> {di}")
# L9 one main figure per approved architecture
for p in live:
    figs=FIG.get(p) or FIG.get(base(p)) or {}
    mains=[k for k,v in figs.items() if str(v.get('isMain'))=='True' and str(v.get('status'))=='approved']
    aidx=re.search(r'_arch(\d+)$',p)
    if aidx:
        mains=[k for k,v in figs.items() if str(v.get('isMain'))=='True'
               and str(v.get('status'))=='approved' and str(v.get('arch'))==aidx.group(1)]
    if len(mains)>1: flag('L9','more than one main figure',f"{p}  {mains[:3]}")
    if len(mains)==0 and p in ap: flag('L9','no main figure on an approved architecture',p)
# L10 figKey collisions inside one patent
for p,figs in FIG.items():
    keys=collections.defaultdict(list)
    for k,v in figs.items():
        if str(v.get('status'))=='approved' and v.get('figKey') is not None:
            keys[str(v['figKey'])].append(k)
    for k,v in keys.items():
        if len(v)>1: flag('L10',f'two approved figures share figKey {k}',f"{p}  {v}")

print("="*76); print(f"  {B} — CONSISTENCY AUDIT   {len(live)} live architectures"); print("="*76)
if not out: print("  no contradictions found.")
by=collections.defaultdict(list)
for r,m,d in out: by[(r,m)].append(d)
for (r,m),ds in sorted(by.items()):
    print(f"\n  [{r}] {m}  — {len(ds)}")
    for d in ds[:8]: print(f"        {d}")
    if len(ds)>8: print(f"        … and {len(ds)-8} more")
