const {sandbox:S}=require('./harness.js');
const fs=require('fs');
const name=process.argv[2];
const rows=JSON.parse(fs.readFileSync('testrows.json','utf8'))[name];
const META=new Set(['title','abstract','assignee','pub_year','app_year','familyId','labelToken','scope',
 'description_of_drawings','aircraftName','pdf_link','codebook_version','timestamp','archCount','mainFigure',
 'isMain','arch','status','figKey','parts','per','acCol','acSty','bgCol','bgSty','rotation_deg','qualityFlag',
 'acState','dinoUnderstanding','imgNotReflect','comment','edgeTags','stateNote','tiltedInView','imgApparentArch',
 'patentImageComments','hasLegends','notPureArch','t1Field','t1Target','t1EdgeTags','t1DisapproveReason',
 'isApproved','isDuplicate','duplicateId','duplicateType','dupOf','comments','t1_quickOverride','t1_humanUncertain',
 't1_quickNote','t1_uncertainNote']);
const norm=v=>v===null||v===undefined?'':String(v).trim();
const K=r=>`${r.Patent_ID}||${r.Field}`;
const base=String(rows[0].Patent_ID).replace(/_arch\d+$/,'');
S.BATCH={ids:[base],byId:{}}; S.BATCH.byId[base]=rows.map(r=>Object.assign({},r));
// loadBatchPatent() does `S = fresh()` before ingesting; without it stale
// module state suppresses the per-figure T2 export entirely (all figure
// labels silently vanish). Verified 2026-08-19.
S.S = S.fresh();
S.ingestPatentRows(rows.map(r=>Object.assign({},r)));
const out=S.recordToRows(S.buildExport(),base);
const outMap=new Map(); out.forEach(r=>{if(!outMap.has(K(r)))outMap.set(K(r),r);});
const inMap=new Map(); rows.forEach(r=>{if(!inMap.has(K(r)))inMap.set(K(r),r);});
const res={name,inPids:[...new Set(rows.map(r=>r.Patent_ID))],outPids:[...new Set(out.map(r=>r.Patent_ID))],
           same:0,changed:[],dropped:[],added:[]};
for(const [k,r] of inMap){
  if(META.has(r.Field)||norm(r.Value)==='') continue;
  const o=outMap.get(k);
  if(!o||norm(o.Value)===''){res.dropped.push({f:r.Field,pid:r.Patent_ID,v:norm(r.Value)});continue;}
  if(norm(o.Value)===norm(r.Value)) res.same++;
  else res.changed.push({f:r.Field,pid:r.Patent_ID,from:norm(r.Value),to:norm(o.Value)});
}
for(const [k,r] of outMap){ if(!META.has(r.Field)&&norm(r.Value)!==''&&!inMap.has(k)) res.added.push({f:r.Field,pid:r.Patent_ID,v:norm(r.Value)}); }
console.log(JSON.stringify(res));
