import pandas as pd, json, re
R="/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs/1639_DS/data/03_HUMAN_wizard_exports/"
sel={"B05":("reviewed_patents_Batch_05 .xlsx",["US2021064062A1","US2022348339A1","WO2020003657A1","US2025019086A1","US2021206487A1"]),
     "B01":("reviewed_patents_Batch_01.xlsx",["US2022388647A1","US2023056974A1","US2020223542A1"])}
out={}
for k,(f,pats) in sel.items():
    df=pd.read_excel(R+f, sheet_name="Review")
    df["base"]=df.Patent_ID.map(lambda p: re.sub(r"_arch\d+$","",str(p)))
    for p in pats:
        g=df[df.base==p]
        if not len(g): print("MISSING",p); continue
        rows=[]
        for _,r in g.iterrows():
            rows.append({c:(None if pd.isna(r[c]) else (r[c].item() if hasattr(r[c],'item') else r[c])) for c in ["Patent_ID","Section","Sub_Dimension","Field","Value","Source","Image_Path"]})
        out[f"{k}:{p}"]=rows
json.dump(out,open("testrows.json","w"),default=str)
print("dumped",{k:len(v) for k,v in out.items()})
# also find a fusKin=Variable patent
df=pd.read_excel(R+"reviewed_patents_Batch_05 .xlsx", sheet_name="Review")
v=df[(df.Field=="fusKin")&(df.Value.astype(str).str.startswith("Variable"))]
print("fusKin=Variable patents:", v.Patent_ID.tolist()[:12])
