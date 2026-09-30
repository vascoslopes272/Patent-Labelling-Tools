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

const out = { codebook_version: ctx.CODEBOOK_VERSION, lists: {}, choices: {},
               missing: [], unbound_guards: [] };
const idsOf = a => a.map(o => (o && typeof o === 'object') ? o.id : o);
for (const n of LISTS) {
  if (Array.isArray(ctx[n])) out.lists[n] = idsOf(ctx[n]); else out.missing.push(n);
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
console.error(`extracted ${Object.keys(out.lists).length} lists, ` +
              `${Object.keys(out.choices).length} guards, missing: ${out.missing.join(',') || 'none'}` +
              (out.unbound_guards.length ? `, UNBOUND GUARDS: ${out.unbound_guards.join(',')}` : ''));
