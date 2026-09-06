import pandas as pd, re, collections, sys
D="/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_DS/data"
B=sys.argv[1] if len(sys.argv)>1 else "Batch_01"
n=pd.read_excel(f"{D}/03c_CORRECTED_wizard_exports/reviewed_patents_{B}.xlsx",sheet_name="Review")
H=open("/home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent-Labelling-Tools/notebooks/UI_for_taxonomy_caracterization_15_4.html",encoding='utf-8').read()
def c(v): return str(v).split(' — ')[0].strip()
fl=lambda p: n[n.Field.astype(str).str.fullmatch(p,na=False)]
base=lambda p: re.sub(r'_arch\d+$','',str(p))
P=set(n.Patent_ID.astype(str)); OK=[]; BAD=[]
def chk(cond,msg,detail=""):
    (OK if cond else BAD).append((msg,detail))
print("="*74); print(f"  {B} — FULL AUDIT   {len(n)} rows · {n.Patent_ID.nunique()} patents"); print("="*74)

ap={str(r.Patent_ID) for _,r in fl('isApproved').iterrows() if str(r.Value)=='True'}
dis={str(r.Patent_ID) for _,r in fl('isApproved').iterrows() if str(r.Value)=='False'}
d2={str(r.Patent_ID) for _,r in fl('duplicateType').iterrows() if c(r.Value)=='2'}
live=lambda p: p in ap or base(p) in ap
print(f"  approved={len(ap)}  disapproved={len(dis)}  type-2 duplicates={len(d2)}\n")

# A INTEGRITY
st=fl('status'); chk(len(st[~st.Value.astype(str).isin(['approved','disapproved'])])==0,
    "every figure has a status", str(len(st[~st.Value.astype(str).isin(['approved','disapproved'])])))
gh=n[n.Sub_Dimension.astype(str).str.startswith('Image:')&n.duplicated(['Patent_ID','Sub_Dimension','Field'],keep=False)]
chk(len(gh)==0,"no ghost duplicate image rows",str(len(gh)))
ph=n[n.Sub_Dimension.astype(str).str.match(r'Image: \(fig ',na=False)]
pa=ph[(ph.Field.astype(str)=='status')&(ph.Value.astype(str)=='approved')]
chk(len(pa)==0,"no APPROVED '(fig N)' placeholder (would block 02a export)",
    ", ".join(sorted(pa.Patent_ID.unique())[:5]))
# B FIELD HYGIENE
sfx=lambda f: re.sub(r'^t\d+_','',re.sub(r'^(boom|wing|hull_array|core_layout|emp|fuselage)\d*_','',re.sub(r'^\d+_','',str(f))))
dead=sorted({sfx(f) for f in n.Field.astype(str)} - {s for s in {sfx(f) for f in n.Field.astype(str)} if s in H})
chk(not dead,"every field name exists in the HTML", str(dead))
# C VOCABULARY
RET={'acState':{'Ground','Unclear','NonApplicable'},'acSty':{'Simple Line Drawing'},
     'topType':{'TP'},'fusKin':{'VarInc','Variable'}}
for f,ids in RET.items():
    s=fl(f); h=s[s.Value.map(c).isin(ids)]
    chk(len(h)==0 or f=='acState', f"no retired {f} values", f"{len(h)}"+(" (02a Rules A1/E remap these)" if f=='acState' else ""))
rm=fl(r'.*_rmech'); chk((rm.Value.map(c)=='Retractable').sum()==0,"no legacy rmech 'Retractable'")
pk=fl(r'.*_propKin'); chk(pk.Value.map(c).isin({'Cyclic','Vectored'}).sum()==0,"no retired propKin")
# D BOOM CONTRACT
at=fl(r'boom\d+_attach').copy(); at['g']=at.Field.astype(str).str.extract(r'boom(\d+)_')[0]; at['c']=at.Value.map(c)
wing={(p,g) for p,g,cc in zip(at.Patent_ID,at.g,at.c) if cc in ('Wings','Both')}
lo=fl(r'boom\d+_long').copy()
sur=0
if len(lo):
    lo['g']=lo.Field.astype(str).str.extract(r'boom(\d+)_')[0]
    sur=sum(1 for p,g,v in zip(lo.Patent_ID,lo.g,lo.Value) if (p,g) in wing and pd.notna(v))
chk(sur==0,"boom_long blank on every wing-attached group",str(sur))
for fld,lbl in [('wingRel','wingRel present on every wing-attached group'),]:
    s=fl(rf'boom\d+_{fld}').copy(); hv=set()
    if len(s):
        s['g']=s.Field.astype(str).str.extract(r'boom(\d+)_')[0]
        hv={(p,g) for p,g,v in zip(s.Patent_ID,s.g,s.Value) if pd.notna(v)}
    m=[(p,g) for p,g in wing if (p,g) not in hv and live(p)]
    chk(not m,lbl,str(m[:6]))
nn=lambda v:1 if str(v)=='True' else (int(float(v)) if re.fullmatch(r'[\d.]+',str(v)) else 0)
wc=fl('wCount').set_index('Patent_ID').Value.map(nn).to_dict()
wi=fl(r'boom\d+_wingIdx').copy(); hv=set()
if len(wi):
    wi['g']=wi.Field.astype(str).str.extract(r'boom(\d+)_')[0]
    hv={(p,g) for p,g,v in zip(wi.Patent_ID,wi.g,wi.Value) if pd.notna(v)}
m=[(p,g) for p,g in wing if wc.get(p,0)>=2 and (p,g) not in hv and live(p)]
chk(not m,"wingIdx present wherever it is required",str(m[:6]))
# E COMPLETENESS
need=[p for p in ap if p not in d2 and not any(q.startswith(p+'_arch') for q in P)]
tt=set(fl('topType').Patent_ID.astype(str))
qo={str(r.Patent_ID) for _,r in fl('g1_quickOverride').iterrows() if str(r.Value)=='True'}
miss=[p for p in need if p not in tt and p not in qo]
chk(not miss,"every approved non-duplicate patent has a topType",str(miss))
# wingConf/empType are only asked of WINGED architectures — G1's wingless and
# 'other' branches (RC/MR/HB/PFV) never render them, so absence there is correct.
WINGED={'TW','TR','DS','CVT','TB','PTC','SLC','SRW'}
top={str(r.Patent_ID):c(r.Value) for _,r in fl('topType').iterrows()}
for m_,l_ in [(fl('empType'),'empType'),(fl('wingConf'),'wingConf')]:
    have=set(m_.Patent_ID.astype(str))
    arch=[p for p in P if re.search(r'_arch\d+$',p)]
    tgt=[p for p in (need+arch) if live(p) and p not in d2 and top.get(p) in WINGED]
    mm=[p for p in tgt if p not in have]
    chk(len(mm)==0,f"every WINGED architecture has {l_}",str(mm[:6]))
wl=[p for p in P if top.get(p) in {'RC','MR','HB','PFV'} and live(p)]
print(f"  (wingless/other architectures, wingConf not asked: {len(wl)})\n")
print("  PASS")
for m_,d_ in OK: print(f"     ✓ {m_}"+(f"  [{d_}]" if d_ else ""))
if BAD:
    print("\n  ATTENTION")
    for m_,d_ in BAD: print(f"     ✗ {m_}"+(f"  -> {d_}" if d_ else ""))
else: print("\n  no findings.")
