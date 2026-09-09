# Codebook conformance harness

Two questions, two scripts. Both read the **corrected** exports
(`data/03c_CORRECTED_wizard_exports/`) and the **current wizard HTML**, which is
the source of truth for the taxonomy.

```bash
python scripts/conformance/check_batches.py --out <report_dir>
python scripts/conformance/known_issues.py  --out <report_dir>
# other wizard build / other batches:
python scripts/conformance/check_batches.py --html notebooks/UI_..._15_3.html --batches Batch_02
```

Requires `node` (the schema extractor evals the HTML's taxonomy block) and
pandas/openpyxl. Latest run:
`data/03b_CONFORMED_legacy/conformance_20260902_LIVE/`.

## Point `--dir` at the LIVE files

`03c_CORRECTED_wizard_exports/` is the default, but it is **not** automatically the
live copy of every batch — some batches have a fresher export sitting in
`~/Downloads/REVIEWED2/`, and some have a 03c copy that is a stale side branch.
Stage the live file per batch into one directory and point `--dir` at it; record
which is which in a `SOURCES.md` beside the report. The 2026-09-02 run shows why:
Batch_02's 03c copy had already migrated its 6 legacy `Unreadable` disapprove
reasons, so auditing it **hid** a finding the live human export still carries.

## check_batches.py — "does this export still match the wizard?"

Six mechanical checks. Nothing here is a judgement call; every finding is a
disagreement between a file and the HTML.

| | check | what it catches |
|---|---|---|
| C1 | invalid option | a `Value` whose id is in no current option list |
| C2 | retired option | an id kept only to render legacy saves — derived as `ids(X) - X_CHOICES`, so it maintains itself as the codebook changes |
| C2b | unguarded list | a list with retired ids and **no** `*_CHOICES` guard, so the retired option is *still pickable today* |
| C3 | retired field | a `Field` the wizard no longer renders but still parses, so it survives a load/save round trip |
| C4 | required gap | a now-mandatory field absent on rows where its precondition holds |
| C5 | convention drift | a *valid* field whose answer distribution differs sharply between batches (total variation distance) — same options, different habit |
| C6 | META coverage | approved patents with no `codebook_version` / `timestamp` |
| C7 | mirror coverage | every exported field classified validated / non-coded / **validated by nothing**; also validates the seven fields C1 never looked at (four of them have option lists built by render-time *functions*, which the extractor now pulls out by name) |
| C8 | free-text leak | prose stored in a categorical field, and the `Other` + sibling-note escape hatch — with fuzzy clustering, so one answer typed three ways reads as one missing option |
| C9 | dead columns | fields the export declares that no file carries, fields present but always empty or constant, option ids nobody ever picked |
| C10 | label drift | the stored `id — Label`'s label half vs the label the wizard renders today (Phase 0 renamed eight of them on 2026-09-08) |

C7–C10 (added 2026-09-08, Phase 3) widen C1–C6 from the 30 fields in
`FIELD_LIST` to **every** Field/Value in the files, which is what the stage-04
master sheet needs. They are report-only. `FIELD_LIST_EXTRA` is deliberately kept
separate from `FIELD_LIST` so the C1/C2 numbers stay comparable with every earlier
report — verified byte-identical against the pre-C7 script.

C5 is the one that finds problems nobody wrote down. Everything else compares
against a declared rule; C5 compares batches against each other, so it surfaces
a definition that changed meaning without anyone editing an option list.

## known_issues.py — "where do the problems we already know about live?"

One function per open codebook issue, each returning a count and a patent list.
To add an issue, write a function and append it to `ISSUES`. This is the file
that turns "I know about that problem" into "it is 12 patents, here they are".

## Adding a check

- **New option list** → add `(Section, field_suffix): "LIST_NAME"` to `FIELD_LIST`
  in `check_batches.py`, and the list name to `LISTS` in `extract_html_schema.js`.
- **Retiring an option** → add a `X_CHOICES` array in the HTML next to the list.
  C2 then picks the retirement up on its own and C2b stops complaining. If the
  retirement is comment-only, record it in `UNGUARDED_RETIRED` so C2 still sees
  it — but the real fix is the guard, because without one reviewers keep picking it.
- **Retiring a field** → add its regex to `DEAD_FIELDS` with the reason.
- **New mandatory field** → add a `(label, precondition_regex, ids, required_regex)`
  row to `REQUIRED`.
