// blockers_one.js — ask the WIZARD what a patent is still missing.
//
//   node blockers_one.js <rows.json>
//   stdout: {"pid", "archs": n, "blockers": [{"arch":1,"step":"m3","msg":"..."}]}
//
// 02a's own completeness check can only find rows that EXIST with a blank value.
// A question the reviewer never answered has no row at all, so it is invisible to
// it — and knowing which questions SHOULD have been asked means knowing the
// wizard's conditional logic (winged vs wingless card sets, isOtherArch making
// M1-M3 free text, wCount driving the wing blocks, quickOverride hiding the
// structured count, ...). Rather than re-implement that in Python and have two
// copies drift apart, this asks nextBlockers() — the very function that gates the
// Next button in the UI. One source of truth.
//
// ONE PATENT PER PROCESS: S.archProfiles persists between ingestPatentRows()
// calls (see conform_one.js). The driver forks.
const { sandbox: S } = require('../legacy_roundtrip_harness/harness.js');
const fs = require('fs');

const rows = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const base = String(rows[0].Patent_ID).replace(/_arch\d+$/, '');
S.BATCH = { ids: [base], byId: {} };
S.BATCH.byId[base] = rows.map(r => Object.assign({}, r));

const out = { pid: base, archs: 1, blockers: [], error: null };
try {
  S.S = S.fresh();                                   // mirrors loadBatchPatent()
  S.ingestPatentRows(rows.map(r => Object.assign({}, r)));
  const nArch = Math.max(1, S.getArchCount());
  out.archs = nArch;
  const steps = S.STEPS.map(s => s.id).filter(id => id !== 'done');
  for (let a = 0; a < nArch; a++) {
    S.S.curArch = a;
    steps.forEach(function (sid, i) {
      S.S.step = i;
      let msgs = [];
      try { msgs = S.nextBlockers() || []; } catch (e) { msgs = ['<blocker check threw: ' + e.message + '>']; }
      msgs.forEach(function (m) {
        // strip the HTML the UI puts in some blocker strings
        const txt = String(m).replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
        out.blockers.push({ arch: a + 1, step: sid, msg: txt });
      });
    });
  }
} catch (e) {
  out.error = e.message;
}
process.stdout.write(JSON.stringify(out));
