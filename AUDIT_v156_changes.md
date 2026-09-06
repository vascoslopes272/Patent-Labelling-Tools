# v15.6 migration — every changed cell

2026-09-05. **207 cells** across Batch_01/02/03/05. Batch_04 untouched.
Backups: `reviewed_patents_<Batch>.PRE_V156_20260905_1633*.xlsx` in 03c_CORRECTED.

Verified: no field outside the four below changed; no row removed; row count grew
by exactly the 22 new tip-joined rows.

| change | cells | reversible | invents a value? |
|---|---|---|---|
| `boomN_span` cleared on non-wing booms | 160 (+2 spanOth) | yes | no — clears only |
| `gearArch` RetrWheel -> Wheeled Gear | 23 | yes | no — total mapping |
| `wingN_tipJoin` back-filled True | 22 | yes | **yes — evidence below** |
| `wingN_plan` Oth -> Trapezoidal | 0 (all in Batch_04) | — | — |

## The only step that asserts something new

`wingN_tipJoin` was set True **only** where your own Wing Architecture note already
said the panels connect at the tips. The note that justified each one:

| batch | patent | panel | your note |
|---|---|---|---|
| Batch_01 | `CN120397241A` | W1 | both wings connect at the tip |
| Batch_01 | `CN120397241A` | W2 | both wings connect at the tip |
| Batch_01 | `US2019144107A1` | W1 | wings have swept and connect at the wingtip |
| Batch_01 | `US2019144107A1` | W2 | wings have swept and connect at the wingtip |
| Batch_01 | `US2020269980A1_arch1` | W1 | wings with swept connect at the wingtip |
| Batch_01 | `US2020269980A1_arch1` | W2 | wings with swept connect at the wingtip |
| Batch_01 | `US2020269980A1_arch2` | W1 | wings with swept connect at the wingtip |
| Batch_01 | `US2020269980A1_arch2` | W2 | wings with swept connect at the wingtip |
| Batch_02 | `DE202013011072U1` | W1 | wings connect at the tips |
| Batch_02 | `DE202013011072U1` | W2 | wings connect at the tips |
| Batch_02 | `US2022266995A1` | W1 | wings connect in their tips |
| Batch_02 | `US2022266995A1` | W2 | wings connect in their tips |
| Batch_02 | `WO2019211875A1` | W1 | connect at the tips |
| Batch_02 | `WO2019211875A1` | W2 | connect at the tips |
| Batch_03 | `CN118457914A` | W1 | 3 wings that connect in the middle of the 3, at the middle wing tip |
| Batch_03 | `CN118457914A` | W2 | 3 wings that connect in the middle of the 3, at the middle wing tip |
| Batch_03 | `CN118457914A` | W3 | 3 wings that connect in the middle of the 3, at the middle wing tip |
| Batch_03 | `US2018290736A1` | W1 | connected at the tips |
| Batch_03 | `US2021122465A1` | W1 | both the middle and the aft wing connect at their tipds where a propeller is in |
| Batch_03 | `US2021122465A1` | W2 | both the middle and the aft wing connect at their tipds where a propeller is in |
| Batch_03 | `US2021122465A1` | W3 | both the middle and the aft wing connect at their tipds where a propeller is in |
| Batch_05 | `US2024300644A1` | W1 | connected at the tips |

> Check these. If a note describes a winglet or a tip fence rather than a real
> join to another panel, untick it in the wizard — the flag is reviewer-editable.

## Spanwise clears — sample of 15 (full list in the CSV)

Each was a boom whose attachment is Fuselage / Empennage / Other, so the
spanwise question had no wing to be measured along.

| batch | patent | field | value removed |
|---|---|---|---|
| Batch_01 | `CN113086184A` | boom1_span | NA — N/A |
| Batch_01 | `CN113086184A` | boom2_span | NA — N/A |
| Batch_01 | `EP3770063A1_arch1` | boom1_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `EP3770063A1_arch1` | boom2_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `EP3770063A1_arch2` | boom1_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `EP3770063A1_arch2` | boom2_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `EP3770063A1_arch2` | boom3_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `US2017203839A1` | boom1_span | NA — N/A |
| Batch_01 | `US2017203839A1` | boom2_span | NA — N/A |
| Batch_01 | `US2018208305A1` | boom1_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `US2018354613A1` | boom1_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `US2018354613A1` | boom2_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `US2020164975A1` | boom1_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `US2020239134A1` | boom1_span | Inboard — Inboard (near root/fuselage) |
| Batch_01 | `US2020361622A1` | boom1_span | Inboard — Inboard (near root/fuselage) |

## Landing gear — all 23

| batch | patent |
|---|---|
| Batch_01 | `US2012061526A1` |
| Batch_01 | `US2014360830A1` |
| Batch_01 | `US2017203839A1` |
| Batch_01 | `US2018327086A1` |
| Batch_01 | `US2020115035A1` |
| Batch_01 | `USD739335S` |
| Batch_02 | `US2022033071A1` |
| Batch_02 | `US2018362155A1` |
| Batch_02 | `US2007158494A1` |
| Batch_02 | `US2021078701A1` |
| Batch_02 | `US2005230519A1` |
| Batch_02 | `US2009261209A1` |
| Batch_02 | `CN202728574U` |
| Batch_03 | `CN108674654A` |
| Batch_05 | `CN113460300A` |
| Batch_05 | `US2017174335A1` |
| Batch_05 | `US2019063574A1` |
| Batch_05 | `US2022363374A1` |
| Batch_05 | `GB202410221D0` |
| Batch_05 | `US2023286650A1` |
| Batch_05 | `US2019337612A1` |
| Batch_05 | `ITTO20130495A1` |
| Batch_05 | `US2006239824A1_arch1` |

All 23 were `Retractable Wheeled Gear` -> `Wheeled Gear`. The mapping is total:
every retractable gear is wheeled gear, so no record can be mapped wrongly.

## To undo any of it

```bash
cd '<03c_CORRECTED dir>'
cp reviewed_patents_Batch_01.PRE_V156_20260905_163301.xlsx reviewed_patents_Batch_01.xlsx
```
