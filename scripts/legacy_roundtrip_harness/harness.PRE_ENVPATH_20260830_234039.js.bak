// Round-trip harness: legacy export rows -> rowsToAIData -> ingestAI -> buildExport
// -> recordToRows -> compare. Runs the wizard's own inline <script> in a vm with a
// permissive DOM mock. Nothing is written to disk by the wizard code.
const fs=require('fs'), vm=require('vm'), path=require('path');
const HTML="/home/vasco/Vasco Workspace/Tese_Vasco_Lnx/Patent-Labelling-Tools/notebooks/UI_for_taxonomy_caracterization_15_3.html";
let src=fs.readFileSync(HTML,"utf8");

// --- pull every inline <script> that is not src= ---
const scripts=[];
src.replace(/<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/gi,(m,body)=>{scripts.push(body);return m;});
let code=scripts.join("\n;\n");
console.error(`[harness] ${scripts.length} inline script block(s), ${code.length} chars`);

// --- neutralize top-level bootstrapping that touches the DOM/localStorage ---
const NEUTRALIZE=[
  /^\s*restoreSession\s*\([^)]*\)\s*;?\s*$/gm,
  /^\s*render\s*\(\s*\)\s*;?\s*$/gm,
  /^\s*boot\s*\(\s*\)\s*;?\s*$/gm,
];
for(const re of NEUTRALIZE){ code=code.replace(re,"/*neutralized*/"); }

// --- permissive DOM mock ---
function mkProxy(name){
  const target=function(){};
  target._name=name;
  return new Proxy(target,{
    get(t,p){
      if(p==='length') return 0;
      if(p===Symbol.iterator) return function*(){}; 
      if(p==='then') return undefined;
      if(p==='toString'||p===Symbol.toPrimitive) return ()=>'';
      if(p==='nodeType') return 1;
      if(p==='style') return mkProxy(name+'.style');
      if(p==='classList') return mkProxy(name+'.classList');
      if(p==='dataset') return {};
      if(p==='value'||p==='innerHTML'||p==='textContent'||p==='id'||p==='className') return '';
      if(p==='checked') return false;
      if(p==='files') return [];
      if(p==='parentNode'||p==='parentElement') return mkProxy(name+'.parent');
      if(p==='children') return [];
      return mkProxy(name+'.'+String(p));
    },
    set(){return true;},
    apply(){return mkProxy(name+'()');},
    has(){return true;},
  });
}
const store={};
const localStorage={getItem:k=>(k in store?store[k]:null),setItem:(k,v)=>{store[k]=String(v);},removeItem:k=>{delete store[k];},clear:()=>{for(const k in store)delete store[k];}};
const document=new Proxy({},{get(t,p){
  if(p==='getElementById'||p==='querySelector'||p==='createElement') return ()=>mkProxy('el:'+String(p));
  if(p==='querySelectorAll'||p==='getElementsByClassName'||p==='getElementsByTagName') return ()=>[];
  if(p==='addEventListener'||p==='removeEventListener') return ()=>{};
  if(p==='body'||p==='documentElement'||p==='head') return mkProxy('doc.'+String(p));
  if(p==='readyState') return 'complete';
  if(p==='cookie') return '';
  return mkProxy('doc.'+String(p));
}});
const sandbox={
  console:{log:()=>{},warn:()=>{},error:()=>{},info:()=>{}},
  document, localStorage, sessionStorage:localStorage,
  setTimeout:(f)=>{return 0;}, clearTimeout:()=>{}, setInterval:()=>0, clearInterval:()=>{},
  requestAnimationFrame:()=>0, cancelAnimationFrame:()=>{},
  alert:()=>{}, confirm:()=>true, prompt:()=>null,
  fetch:()=>Promise.resolve({ok:false}),
  XLSX:{utils:{book_new:()=>({}),json_to_sheet:()=>({}),book_append_sheet:()=>{},sheet_to_json:()=>[]},writeFile:()=>{},read:()=>({SheetNames:[],Sheets:{}})},
  navigator:{userAgent:'node',clipboard:{writeText:()=>Promise.resolve()}},
  location:{href:'file:///x.html',search:'',hash:''},
  history:{replaceState:()=>{},pushState:()=>{}},
  matchMedia:()=>({matches:false,addEventListener:()=>{},addListener:()=>{}}),
  getComputedStyle:()=>mkProxy('cs'),
  Image:function(){return mkProxy('img');},
  FileReader:function(){return mkProxy('fr');},
  Blob:function(){return {};}, URL:{createObjectURL:()=>'blob:x',revokeObjectURL:()=>{}},
};
sandbox.window=sandbox; sandbox.globalThis=sandbox; sandbox.self=sandbox;
sandbox.addEventListener=()=>{}; sandbox.removeEventListener=()=>{};
vm.createContext(sandbox);
try{ vm.runInContext(code,sandbox,{filename:'wizard.js'}); }
catch(e){ console.error("[harness] LOAD ERROR:",e.message); console.error(e.stack.split("\n").slice(0,6).join("\n")); process.exit(3); }

const need=['rowsToAIData','ingestAI','buildExport','recordToRows'];
const missing=need.filter(n=>typeof sandbox[n]!=='function');
console.error("[harness] loaded. missing fns:",missing.length?missing:"(none)");
if(missing.length) process.exit(4);
module.exports={sandbox};
