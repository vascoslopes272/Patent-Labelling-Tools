// conform_one.js — push ONE patent's legacy rows through the v15_3 wizard and
// emit the re-exported rows plus a per-field diff.
//
//   node conform_one.js <rows.json>       # rows.json = array of export rows
//
// stdout: {"pid","inPids","outPids","rows":[...],"same","changed":[],"dropped":[],"added":[]}
//
// ONE PATENT PER PROCESS. S.archProfiles persists between ingestPatentRows()
// calls, so a single-architecture patent ingested after a multi-architecture one
// is re-exported with _arch1 suffixes it should not have (recordToRows line 4573
// keys off archs.length). The driver forks; do not batch inside one process.
const {sandbox:S}=require('./harness.js');
const fs=require('fs');

// Patent metadata is supplied by the loaded BATCH, not by the reviewed rows, so
// it is not part of the label round-trip and is carried over verbatim below.
const META=new Set(['title','abstract','assignee','pub_year','app_year','familyId','labelToken','scope',
 'description_of_drawings','aircraftName','pdf_link','codebook_version','timestamp','archCount','mainFigure',
 'isMain','arch','status','figKey','parts','per','acCol','acSty','bgCol','bgSty','rotation_deg','qualityFlag',
 'acState','dinoUnderstanding','imgNotReflect','comment','edgeTags','stateNote','tiltedInView','imgApparentArch',
 'patentImageComments','hasLegends','notPureArch','t1Field','t1Target','t1EdgeTags','t1DisapproveReason',
 'isApproved','isDuplicate','duplicateId','duplicateType','dupOf','comments','t1_quickOverride',
 't1_humanUncertain','t1_quickNote','t1_uncertainNote']);
const norm=v=>v===null||v===undefined?'':String(v).trim();
const K=r=>`${r.Patent_ID}||${r.Field}`;

const rows=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const base=String(rows[0].Patent_ID).replace(/_arch\d+$/,'');
S.BATCH={ids:[base],byId:{}};
S.BATCH.byId[base]=rows.map(r=>Object.assign({},r));

let out;
try{
  // loadBatchPatent() does `S = fresh()` before ingesting; without it stale
// module state suppresses the per-figure T2 export entirely (all figure
// labels silently vanish). Verified 2026-08-19.
S.S = S.fresh();
S.ingestPatentRows(rows.map(r=>Object.assign({},r)));
  out=S.recordToRows(S.buildExport(),base);
}catch(e){
  console.log(JSON.stringify({pid:base,error:e.message,stack:String(e.stack).split('\n').slice(0,5)}));
  process.exit(0);
}

const outMap=new Map(); out.forEach(r=>{ if(!outMap.has(K(r))) outMap.set(K(r),r); });
const inMap =new Map(); rows.forEach(r=>{ if(!inMap.has(K(r)))  inMap.set(K(r),r); });

const res={pid:base,
  inPids:[...new Set(rows.map(r=>r.Patent_ID))].sort(),
  outPids:[...new Set(out.map(r=>r.Patent_ID))].sort(),
  same:0,changed:[],dropped:[],added:[]};
for(const [k,r] of inMap){
  if(META.has(r.Field)||norm(r.Value)==='') continue;
  const o=outMap.get(k);
  if(!o||norm(o.Value)===''){ res.dropped.push({pid:r.Patent_ID,f:r.Field,v:norm(r.Value)}); continue; }
  if(norm(o.Value)===norm(r.Value)) res.same++;
  else res.changed.push({pid:r.Patent_ID,f:r.Field,from:norm(r.Value),to:norm(o.Value)});
}
for(const [k,r] of outMap){
  if(META.has(r.Field)||norm(r.Value)==='') continue;
  if(!inMap.has(k)) res.added.push({pid:r.Patent_ID,f:r.Field,v:norm(r.Value)});
}

// ── What we KEEP from the wizard, and what we carry verbatim ───────────────
// The wizard is trusted ONLY for the morphology sections (G1/M1/M2/M3) — that is
// what every codebook conformance item touches and what the round-trip is
// verified good at.
//
// T1/T2/META are carried through VERBATIM from the frozen original. Reason,
// measured 2026-08-19 over the 8-patent sample: the T2 figure round-trip is NOT
// lossless in this harness. 4 of 8 patents dropped per-figure labels outright
// (the "Image: <filename>" Sub_Dimension <-> figKey pair does not always
// re-associate), and US2022348339A1 had T2_APPEARANCE_DEFAULTS re-applied over
// the human's picks (Top->Front-Isometric, Render->Line Drawing,
// Grayscale->B/W) because the `figReviewed = fig.status != null` gate did not
// hold. Those are the annotator's per-figure labels and NOTHING in the
// conformance touches them, so the safe move is not to regenerate them at all.
//
// The two T2-side conformance items (qualityFlag 'draft' x1, bgSty
// 'Grid/Pattern' x5) are applied by the notebook as explicit rules, not here.
const MORPH=new Set(['G1','M1','M2','M3']);
const morphOut=out.filter(r=>MORPH.has(r.Section));
const carried=rows.filter(r=>!MORPH.has(r.Section));
res.rows=morphOut.concat(carried.map(r=>Object.assign({},r)));
res.nMorph=morphOut.length;
res.nCarried=carried.length;
// The diff above is computed over ALL sections; restrict the reported one to
// what we actually take from the wizard, so the harmonisation log records only
// changes that are really applied.
res.changed=res.changed.filter(c=>{const r=inMap.get(`${c.pid}||${c.f}`);return r&&MORPH.has(r.Section);});
res.dropped=res.dropped.filter(c=>{const r=inMap.get(`${c.pid}||${c.f}`);return r&&MORPH.has(r.Section);});
res.added  =res.added.filter(c=>{const r=outMap.get(`${c.pid}||${c.f}`);return r&&MORPH.has(r.Section);});
console.log(JSON.stringify(res));
