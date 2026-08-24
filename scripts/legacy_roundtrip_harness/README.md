# legacy_roundtrip_harness

Runs `UI_for_taxonomy_caracterization_15_3.html`'s inline script in Node's `vm` with a
Proxy DOM mock, so a legacy reviewed export can be pushed through the wizard's own
`ingestPatentRows() → buildExport() → recordToRows()` path with no browser.

    python3 dump.py                  # legacy rows -> testrows.json
    node one.js "B05:US2021064062A1" # one patent -> JSON diff on stdout

`one.js` emits `{same, changed[], dropped[], added[]}` per patent.

**Run one patent per process.** `S.archProfiles` persists between `ingestPatentRows()`
calls, so a single-architecture patent ingested after a multi-architecture one inherits
the higher `archs.length` and is re-exported with `_arch1` suffixes it should not have.
`recordToRows` itself is correct (line 4573); the leak is in the shared state.

Findings from the first run: `03b_CONFORMED_legacy/STEP1_roundtrip_report.md`.
