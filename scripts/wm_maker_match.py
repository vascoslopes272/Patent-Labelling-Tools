import pandas as pd, re
EVN="/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/EVTOLNEWS_DS"
P=pd.read_excel("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_LABELLED/0_labelling/outputs/1639_LABELS.xlsx",sheet_name='patseer')
m=pd.read_csv(EVN+'/2_embedding_extraction/selection/sets/main.csv',low_memory=False)
a=pd.read_csv(EVN+'/0_source/aircraft.csv').set_index('slug_key')
x=m[['aircraft_uid','topType']].drop_duplicates().join(a[['company']],on='aircraft_uid')
STOP=set('inc ltd llc gmbh co corp corporation company limited sa sas ag bv srl spa plc kk the group holdings holding technology technologies tech aviation aerospace aero aeronautics aircraft air mobility systems system industries international labs lab motors motor robotics science sciences electric engineering design designs vehicles vehicle research institute university of and urban flying cars car drone drones dynamics innovations solutions ventures'.split())
def key(s):
    s=re.sub(r'\(.*?\)','',str(s).lower()); s=re.sub(r'[^a-z0-9 ]',' ',s)
    t=[w for w in s.split() if w not in STOP and len(w)>1]
    return ' '.join(t)
pk={}
for c in pd.concat([P.company,P.assignee,P.current_assignee]).dropna().astype(str):
    for part in re.split(r'[;/|]',c):
        k=key(part)
        if k: pk.setdefault(k,set()).add(part.strip()[:40])
pkeys=list(pk)
def match(c):
    k=key(c)
    if not k: return None
    for q in pkeys:
        if q==k or q.startswith(k+' ') or k.startswith(q+' '): return q
    return None
mk=x[['company']].drop_duplicates().assign(k=lambda d:d.company.map(match))
x=x.merge(mk,on='company')
g=x.groupby('topType').agg(makers=('company','nunique'),makers_with_patent=('k',lambda s: x.loc[s.index][s.notna()].company.nunique()))
g['share']=(g.makers_with_patent/g.makers*100).round(0)
print(g)
w=x[(x.topType=='WM')&x.k.notna()][['company','k']].drop_duplicates()
w['patent_side']=w.k.map(lambda q:sorted(pk[q])[:2])
pd.set_option('display.width',200,'display.max_colwidth',70)
print(w.to_string(index=False))
x.to_csv(EVN+'/3_embedding_evaluation/wm_gap_check/maker_patent_match.csv',index=False)
