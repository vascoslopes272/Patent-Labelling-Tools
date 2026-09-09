// Dump the wizard HTML's option lists to JSON so Python can validate exports
// against them. Slices the taxonomy block out of the single <script> tag and
// evals it in a bare VM context — that block is pure data + a few helpers, so
// it runs with no DOM.
//
// Usage:  node extract_html_schema.js <UI_for_taxonomy_*.html> <out.json>
const fs = require('fs'), vm = require('vm');

const html = fs.readFileSync(process.argv[2], 'utf8').split('\n');
// The block runs from the CODEBOOK_VERSION stamp to the first STEPS/function
// definition that touches the DOM. Both markers are stable across v13..v15.
const start = html.findIndex(l => /^var CODEBOOK_VERSION/.test(l));
let end = html.findIndex(l => /^var STEPS\s*=/.test(l));
if (start < 0) { console.error('CODEBOOK_VERSION marker not found'); process.exit(2); }
if (end < 0) end = start + 800;

const ctx = { console, document: {}, window: {} };
vm.createContext(ctx);
try { vm.runInContext(html.slice(start, end).join('\n'), ctx); }
catch (e) { console.error('WARN partial eval:', e.message); }

// Every option list we validate against, plus the *_CHOICES guards. A list that
// has a matching *_CHOICES array declares its retired ids implicitly:
//   retired(X) = ids(X) - X_CHOICES.  A list with NO guard cannot retire
// anything, which is itself worth reporting (see checks.py, C2b).
const LISTS = ['TOP','WING_CONFIG','W_POS_V','W_POS_L','W_PLAN','W_ROLE','W_TILT',
  'T1_DISAPPROVE_REASONS','EMP_TYPE','CHORD','BLADE_MECH','RETRACT_MECH','PROP_KIN',
  'AC_STATE','BOOM_ATTACH','BOOM_POS','BOOM_POS_LONG','BOOM_POS_SPAN','BOOM_WING_REL',
  'BOOM_ORIENT','BOOM_WING_IDX','FUS_SHAPE','FUS_KIN','GEAR_ARCH','T2_PER','T2_AC_STY','T2_AC_COL',
  'T2_BG_STY','T2_BG_COL','T2_PARTS_DEFAULT','DUP_TYPES','QUALITY_FLAGS',
  'DINO_UNDERSTANDING','T1_EDGE_TAGS'];
// DISCOVERED, not hardcoded (2026-09-06). A hand-maintained list has exactly the
// failure mode this harness exists to catch: v15.7 added AC_STATE_CHOICES and
// v15.6 added GEAR_ARCH_CHOICES, neither was registered here, and both
// retirements went unreported — C2 saw no guard, and C2b called AC_STATE
// unguarded when it had just been guarded. Every `*_CHOICES` array the taxonomy
// block defines is now picked up automatically, so a new guard can never again
// be invisible to the checks.

// Render-time option sets (C7). These live in FUNCTIONS far below the taxonomy
// block — m3ZoneOptions() even branches on which propulsion card is being drawn —
// so the block eval above never sees them and four exported M3 fields (zone,
// zoneChord, zoneSpan, orient) were validated against nothing. Pull each function
// by name, eval it in isolation and call it, so these lists stay derived from the
// HTML instead of being copied here (a copy is the failure mode this harness exists
// to catch). isIndependentThrust() is a state predicate, so orient is the UNION of
// both branches — an export cannot say which mode was on when it was written.
const src = fs.readFileSync(process.argv[2], 'utf8');
function fnSource(name) {                       // brace-match one function decl
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) return null;
  let d = 0, j = src.indexOf('{', i);
  if (j < 0) return null;
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') d++;
    else if (src[k] === '}' && --d === 0) return src.slice(i, k + 1);
  }
  return null;
}
const RENDER_FNS = ['m3OrientationOptions', 'm3ZoneOptions', 'm3ZoneChordOptions',
                    'm3ZoneSpanOptions'];
const rctx = { console };
vm.createContext(rctx);
for (const n of RENDER_FNS) {
  const body = fnSource(n);
  if (body) vm.runInContext(body, rctx); else console.error(`WARN ${n} not found`);
}
const RENDER_LISTS = {};
try {
  // union of the independent-thrust and the vectoring branch
  rctx.isIndependentThrust = () => true;
  const a = rctx.m3OrientationOptions();
  rctx.isIndependentThrust = () => false;
  const b = rctx.m3OrientationOptions();
  RENDER_LISTS.M3_ORIENT = b.concat(a.filter(o => !b.some(x => x.id === o.id)));
  // union of the empennage card's zone vocabulary and every other card's
  const e = rctx.m3ZoneOptions({ key: 'emp' }), o = rctx.m3ZoneOptions({ key: 'fuselage' });
  RENDER_LISTS.M3_ZONE = o.concat(e.filter(x => !o.some(y => y.id === x.id)));
  RENDER_LISTS.M3_ZONE_EMP = e;
  RENDER_LISTS.M3_ZONE_CHORD = rctx.m3ZoneChordOptions();
  RENDER_LISTS.M3_ZONE_SPAN = rctx.m3ZoneSpanOptions();
} catch (e) { console.error('WARN render-time list extraction:', e.message); }

const out = { codebook_version: ctx.CODEBOOK_VERSION, lists: {}, labels: {},
               choices: {}, missing: [], unbound_guards: [], render_lists: [] };
const idsOf = a => a.map(o => (o && typeof o === 'object') ? o.id : o);
// withLabel() writes `id + ' \u2014 ' + (o.n || o.name)`, so the display string a
// file carries is checkable against the list only if we export it (C10). A plain
// string list has no separate label and gets an empty map.
const labelsOf = a => Object.fromEntries(a.filter(o => o && typeof o === 'object')
                                          .map(o => [o.id, o.n || o.name]));
for (const n of LISTS) {
  if (Array.isArray(ctx[n])) { out.lists[n] = idsOf(ctx[n]); out.labels[n] = labelsOf(ctx[n]); }
  else out.missing.push(n);
}
for (const [n, a] of Object.entries(RENDER_LISTS)) {
  out.lists[n] = idsOf(a); out.labels[n] = labelsOf(a); out.render_lists.push(n);
}
for (const n of Object.keys(ctx))
  if (/_CHOICES$/.test(n) && Array.isArray(ctx[n])) out.choices[n] = ctx[n];

// A guard is only useful if it binds to a list. The HTML's naming is NOT uniform
// (T1_DISAPPROVE_REASONS is guarded by T1_DISAPPROVE_CHOICES, dropping the
// _REASONS), so report every guard whose "<LIST>_CHOICES" name has no list —
// check_batches.py must alias it explicitly or the retirement goes unnoticed.
for (const n of Object.keys(out.choices)) {
  const lst = n.replace(/_CHOICES$/, '');
  if (!(lst in out.lists)) out.unbound_guards.push(n);
}

fs.writeFileSync(process.argv[3], JSON.stringify(out, null, 1));
console.error(`extracted ${Object.keys(out.lists).length} lists ` +
              `(${out.render_lists.length} render-time), ` +
              `${Object.keys(out.choices).length} guards, missing: ${out.missing.join(',') || 'none'}` +
              (out.unbound_guards.length ? `, UNBOUND GUARDS: ${out.unbound_guards.join(',')}` : ''));
