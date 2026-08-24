# Batch audit — v15.4

Read-only. Generated from `03c_CORRECTED_wizard_exports/` (Batch_01, 02, 03, 05).
Nothing in this report changes any data. Ids are matched on the part before the em-dash,
because the label half of the `ID — Label` composite has drifted between wizard versions.

## B1 — T1 disapprovals recorded as "Other" that read like a missing/insufficient image

18 records carry reason `Other`; 9 of them mention one of: insufficient, not enough, too few, no image, few image, lacking, missing image, sufficient, suficient, only cruise, only a image, only one image, decipher, not enought, no information.

| Batch | Patent ID | Variant aircraft name | Recorded reason | Full text |
|---|---|---|---|---|
| Batch_02 | `US2024213855A1` | _(no aircraft name)_ | Other | Images non-Sufficient for architecture deciphering |
| Batch_02 | `US2024317416A1` | _(no aircraft name)_ | Other | Images non-Sufficient for architecture deciphering |
| Batch_02 | `US2025238031A1` | _(no aircraft name)_ | Other | Images non-Sufficient for architecture deciphering |
| Batch_02 | `US2025373119A1` | _(no aircraft name)_ | Other | Images non-Sufficient for architecture deciphering |
| Batch_02 | `US2022144410A1` | _(no aircraft name)_ | Other | no information suficient in the image to amke it a vtol |
| Batch_02 | `US2020031464A1` | _(no aircraft name)_ | Other | Only a image at cruise, if using only it it would seem only like an airplane |
| Batch_02 | `FR2830237A1` | _(no aircraft name)_ | Other | only cruise configuration shown |
| Batch_02 | `US2004232279A1` | _(no aircraft name)_ | Other | images are not enough to decipher the archiecture |
| Batch_03 | `US2016288903A1` | _(no aircraft name)_ | Other | only cruise mode is shown and it is impossibel by the images t say if it is a eVTOL or not |

The other 9 `Other` records, for completeness:

| Batch | Patent ID | Variant aircraft name | Full text |
|---|---|---|---|
| Batch_02 | `US2009008499A1` | _(no aircraft name)_ | It is not the aircraft itself, it is a set of modular vehicles to transport other vehicles like cars... |
| Batch_02 | `US2006202081A1` | _(no aircraft name)_ | too strange to analyse, would corrupt the data, by being too out ot the scope of labelling |
| Batch_02 | `US2006054736A1` | _(no aircraft name)_ | too strange to analyse, would corrupt the data, by being too out ot the scope of labelling |
| Batch_02 | `US2009218438A1` | _(no aircraft name)_ | too strange to analyse, would corrupt the data, by being too out ot the scope of labelling |
| Batch_03 | `US2019263515A1` | _(no aircraft name)_ | All of the aircrafts in the domain, but all seem to be duplicated from other patents, it can be valuable to train a model, but stays out of this dataset since it makes the statisticall analysis wrong |
| Batch_05 | `US2013112804A1` | _(no aircraft name)_ | _(no text recorded — this batch predates `t1DisapproveReason_otherNote`)_ |
| Batch_05 | `US2017283052A1` | _(no aircraft name)_ | _(no text recorded — this batch predates `t1DisapproveReason_otherNote`)_ |
| Batch_05 | `FR3127478A1` | _(no aircraft name)_ | _(no text recorded — this batch predates `t1DisapproveReason_otherNote`)_ |
| Batch_05 | `US2010051740A1` | _(no aircraft name)_ | _(no text recorded — this batch predates `t1DisapproveReason_otherNote`)_ |

## B1b — records under the retired `Unreadable/Insufficient image quality`

25 records. In v15.4 this reason is retired and every case it covered is recorded under
`No Usable, Sufficient, or Legible Aircraft Image`. These are the records to migrate in 03c.

| Batch | Patent ID | Variant aircraft name | Text recorded |
|---|---|---|---|
| Batch_01 | `WO2025222250A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `WO2021070363A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2013082135A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2006198732A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2024140601A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2026116528A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2022063799A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2008243313A1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2022119100A1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `RU2727787C1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `CA2958445A1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2012298789A1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `DE202018104519U1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `DE102018113265A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2016368601A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2018281953A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `CN108706104A` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2020207467A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `FR3104333A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2022194568A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2022355944A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2023278702A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `JP2026505730A` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2022089276A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `WO2023272353A1` | _(no aircraft name)_ | _(none)_ |

## B2 — vertical boom groups with symmetry ticked

17 boom groups. Symmetry means mirrored LEFT/RIGHT for every orientation — the proposed
above/below reading was rejected in v15.4. Confirm each is a genuine left/right pair of vertical
booms and not one boom straddling a wing above and below, which would be a single boom and is
here being double-counted.

| Batch | Patent ID | Variant aircraft name | Boom group | Count/side | Total after doubling | Attach | Long. |
|---|---|---|---|---|---|---|---|
| Batch_01 | `US2018339773A1` | BELL HELICOPTER 7 | 1 | True |  | Fuselage | NA |
| Batch_01 | `US2023091705A1` | TEXTRON INNOVATIONS 6 | 1 | True |  | Fuselage | NA |
| Batch_02 | `DE102016001771A1` | DAIMLER AG | 1 | True |  | Fuselage | Fore |
| Batch_02 | `DE102016001771A1` | DAIMLER AG | 2 | True |  | Fuselage | Aft |
| Batch_02 | `DE102016015461A1` | Daimler Ag | 1 | True |  | Fuselage | Fore |
| Batch_02 | `DE102016015461A1` | Daimler Ag | 2 | True |  | Fuselage | Aft |
| Batch_02 | `US2014158815A1` | RENTERIA JOSEPH | 1 | True |  | Fuselage | Aft |
| Batch_02 | `WO2015089679A1` | CONCA GARCIA | 1 | True |  | Fuselage | Fore |
| Batch_02 | `US2009212166A1` | GARREAU OLIVER | 1 | True |  | Fuselage | Mid |
| Batch_02 | `CN202728574U` | TIAN YU | 1 | 2 | 4 | Wings | Mid |
| Batch_02 | `US2015175260A1` | HESSELBARTH JONATHAN | 1 | 2 | 4 | Wings | NA |
| Batch_03 | `US2020361601A1` | JOBY AERO 4 | 1 | True |  | Wings | NA |
| Batch_03 | `US2024375799A1` | Nasa 4 | 1 | True |  | Fuselage | Mid |
| Batch_03 | `US2021122466A1` | Uber Technology 4 | 1 | True |  | Wings | NA |
| Batch_03 | `CN106314794A` | YANG DING | 1 | 3 | 6 | Fuselage | FullSpan |
| Batch_03 | `DE102019004808A1` | PFEIFER FLORIAN | 2 | True |  | Wings | NA |
| Batch_05 | `WO2025255583A1` | _(no aircraft name)_ | 1 | False |  | Fuselage | NA |

## B3 — empennage `Fins`

18 records under `Fins` — Minimal Stabilizing Fins (Two or More). Confirm: two or more fins, never one small fin.
Figures for a visual pass are in `_TEMP_v154_review/A2_minimal_stabilizing_fins/`.

| Batch | Patent ID | Variant aircraft name | Notes |
|---|---|---|---|
| Batch_01 | `US2020269975A1_arch3` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2025083808A1` | ANDURIL INDUSTRY | _(none)_ |
| Batch_02 | `US2022033071A1` | HAMILTON SUNDSTRAND CORP 1 | the propeller rotat inside the "nacellle", very dificult for the model to see it  |
| Batch_03 | `US2025256840A1` | LOCKHEED 4 | _(none)_ |
| Batch_03 | `US12325540B1` | PIPISTREL DOO | _(none)_ |
| Batch_03 | `US2025256841A1` | Pipistrel Doo | _(none)_ |
| Batch_03 | `DE102023108565B3` | Porcsche P3X GMBH | _(none)_ |
| Batch_03 | `DE102024105439A1` | Porcsche P3X Gmbh | _(none)_ |
| Batch_03 | `DE102023122141A1` | Porcsche P3X Gmbh | _(none)_ |
| Batch_03 | `US2021371117A1` | Porsche 10 | _(none)_ |
| Batch_03 | `US2022097835A1` | SUBARU CORP | _(none)_ |
| Batch_03 | `DE102019001240A1` | ANDRA GABOR | _(none)_ |
| Batch_03 | `EP3290334A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_03 | `EP3290334A1_arch2` | _(no aircraft name)_ | _(none)_ |
| Batch_03 | `US2013026303A1` | AGUSTAWESTLAND | _(none)_ |
| Batch_05 | `US10913529B1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `CN108928471A` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2021339842A1` | _(no aircraft name)_ | _(none)_ |

## B3 — empennage `VertFin`

83 records under `VertFin` — Vertical Fin(s) Only. Confirm: a proper vertical tail, count not part of the test.
Figures for a visual pass are in `_TEMP_v154_review/A2_vertfin/`.

| Batch | Patent ID | Variant aircraft name | Notes |
|---|---|---|---|
| Batch_01 | `US2016347447A1` | AIRBUS DEFENCE 2 | _(none)_ |
| Batch_01 | `US2016207625A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2016207625A1_arch3` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2019382106A1` | X DEVELOPMENT LLC | _(none)_ |
| Batch_01 | `US2019329898A1` | X Development Llc 2 | _(none)_ |
| Batch_01 | `US2022388649A1` | ARCHER AVIATION 3 | _(none)_ |
| Batch_01 | `US2021300527A1` | AURORA FLIGHT 7 | _(none)_ |
| Batch_01 | `CN111301676A` | SHANGHAI AUTOFLIGHT | _(none)_ |
| Batch_01 | `US2021362850A1` | Shanghai Autoflight | _(none)_ |
| Batch_01 | `DE102020007836A1` | BAAZ GMBH | _(none)_ |
| Batch_01 | `DE102020007834A1` | BAAZ GMBH 2 | _(none)_ |
| Batch_01 | `GB202302720D0` | BAE SYSTEM | _(none)_ |
| Batch_01 | `CN120397241A` | BEIHANG UNIV 8 | _(none)_ |
| Batch_01 | `US2018002003A1` | _(no aircraft name)_ | _(none)_ |
| Batch_01 | `US2021331794A1` | AERHART LLC | _(none)_ |
| Batch_01 | `US2018044012A1` | BELL HELICOPTER 12 | _(none)_ |
| Batch_01 | `US2019144107A1` | BELL HELICOPTER 19 | _(none)_ |
| Batch_01 | `US2020140079A1` | Textron Innovations 2 | _(none)_ |
| Batch_01 | `US2021316849A1` | BELL TEXTRON 15 | _(none)_ |
| Batch_02 | `US2018222580A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2021354816A1` | EMBRAER SA 1 | _(none)_ |
| Batch_02 | `US2020354048A1` | EMBRAER SA 4 | _(none)_ |
| Batch_02 | `US2018362155A1` | GENERAL ELECTRIC 2 | _(none)_ |
| Batch_02 | `US2024059393A1` | HONDA MOTOR 2 | _(none)_ |
| Batch_02 | `US2024300663A1` | Honda Motor 2 | _(none)_ |
| Batch_02 | `US11001377B1` | HORIZON AIRCRAFT | _(none)_ |
| Batch_02 | `US11548621B1` | Horizon Aircraft | _(none)_ |
| Batch_02 | `CN116215850A` | HUBEI INSTITUTE 1 | _(none)_ |
| Batch_02 | `DE202013011072U1` | SALBAUM MAXIMILIAN | _(none)_ |
| Batch_02 | `US2018141652A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `WO2016004852A1` | WU JIANWEI | _(none)_ |
| Batch_02 | `US2021078701A1` | SHARIFZADEH DARIUS 1 | _(none)_ |
| Batch_02 | `US2021245872A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2021245872A1_arch3` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `AU2020100605A4_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2025145283A1` | WANG XI 4 | _(none)_ |
| Batch_02 | `US2004155143A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2004155143A1_arch3` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2004155143A1_arch4` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `US2005230519A1` | HURLEY FRANCIS | _(none)_ |
| Batch_02 | `ES2288083A1_arch3` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `DE102007055313A1` | HITSCHLER ALEXANDER | _(none)_ |
| Batch_02 | `US2009283644A1` | STICHTING NATIONAAL | _(none)_ |
| Batch_02 | `WO2010132901A1` | SMITH ERIC NORMAN | _(none)_ |
| Batch_02 | `FR2993245A1` | CABARBAYE ADRIEN | _(none)_ |
| Batch_02 | `CN202728574U` | TIAN YU | it seems to have the possibility for landing and taking off horiozontally, thus, but it is a tailsitter |
| Batch_02 | `DE202014004877U1_arch2` | _(no aircraft name)_ | _(none)_ |
| Batch_02 | `CN104229137A` | MATSUDA HARI | _(none)_ |
| Batch_03 | `WO2024252755A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_03 | `WO2024252755A1_arch2` | _(no aircraft name)_ | _(none)_ |
| Batch_03 | `KR20230075012A` | KOREA AEROSPACE 3 | _(none)_ |
| Batch_03 | `KR20250038333A` | KOREA AEROSPACE 6 | _(none)_ |
| Batch_03 | `US2023257132A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_03 | `CN118457914A` | NANJING UNIV OF AERONAUTICS & ASTRONAUTICS 2 | _(none)_ |
| Batch_03 | `US2021229802A1_arch2` | _(no aircraft name)_ | _(none)_ |
| Batch_03 | `US2020010188A1` | PORSCHE 2 | _(none)_ |
| Batch_03 | `DE102024105440A1` | PORSCHE 6 | _(none)_ |
| Batch_03 | `CN109263968A` | SHENFENG SCIENCE & TECHNOLOGY OF AVIATION | _(none)_ |
| Batch_03 | `CN109263914A` | Shenfeng Science & Technology Of Aviation 2 | _(none)_ |
| Batch_03 | `US2025042543A1` | TETRA AVIATION | _(none)_ |
| Batch_03 | `CN120863869A` | XU BIN | _(none)_ |
| Batch_03 | `DE102019006484B3` | GRIMM FRIEDRICH | _(none)_ |
| Batch_03 | `ES2775773A1` | OUTON TRILLO PEDRO | _(none)_ |
| Batch_05 | `US2018170517A1` | _(no aircraft name)_ | wings tilt, but the aircraft directional movement is controlled by the 3 propulsors that are on the fuselge
 |
| Batch_05 | `US2019337612A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `CN113460300A` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2024300644A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `CN113844648A` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `USD1017462S` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `WO2023051929A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2023249816A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `USD1082648S` | _(no aircraft name)_ | these wings are tilted in a diferent manner than "Tilt-wing" architecture normally, so it may be cnsidered vectired trhust-combined  |
| Batch_05 | `CN118770545A` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `CN120135432A` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2008283673A1_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2008283673A1_arch2` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2008283673A1_arch3` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2008283673A1_arch4` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `US2019161188A1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `CN110450948A_arch1` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `CN110450948A_arch2` | _(no aircraft name)_ | _(none)_ |
| Batch_05 | `EP4134301A1` | ZURI COM SE | _(none)_ |
| Batch_05 | `US2023211877A1` | ZURI COM SE 2 | _(none)_ |

## B4 — boom groups that may have been one boom entered as two

92 records have two or more boom groups sharing the same `attach` and `orient`, with one
`long = Fore` and another `long = Aft`. These may be a single nose-to-tail or straddling boom
split before the convention settled. The fix, where it applies, is one group with
`long = FullSpan` (Full length, nose-to-tail) — not two.

> **Decision 2026-08-24: INFORMATIONAL ONLY — not being corrected.** A `boomSplit` review
> queue was built for this and then dropped. Validated against 8 drawings it found 4 genuine
> splits, 2 false positives and 2 unreadable, so answering the ~101 items by hand was judged
> not worth the reviewer time for the yield. The labels stay as recorded. This section is kept
> as a record of the known imprecision, not as a to-do list.

### Batch_01 — `US2023033507A1` — AERONEXT INC 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Long | True | True | False | — | True |
| 3 | Fuselage | — | — | Inboard | Mid | Lat | True | True | False | — | True |

### Batch_01 — `US2018244367A1` — AIRBUS HELICOPTERS

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | Full | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_01 — `EP3770063A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_01 — `EP3770063A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |
| 3 | Fuselage | — | — | Inboard | Mid | Lat | True | True | False | — | True |

### Batch_01 — `US2020269975A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

_Notes:_ 2 booms connect to the empenage too, the gorup one

### Batch_01 — `US2020269975A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2020269975A1_arch3` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2020269975A1_arch4` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

_Notes:_ 2 booms connect to the empenage too, the gorup one

### Batch_01 — `US2020269980A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |
| 4 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2020269980A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |
| 4 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2020269980A1_arch3` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2016207625A1_arch4` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2016207625A1_arch5` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022267016A1` — Airbus Helicopters 5

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

_Notes:_ 2 booms connect to the empenage too, the gorup one

### Batch_01 — `US2020115045A1` — AIRBUS HELICOPTERS 9

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 4 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2019382106A1` — X DEVELOPMENT LLC

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2019329898A1` — X Development Llc 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Aft | Long | True | True | False | — | True |

### Batch_01 — `US11124286B1` — AMAZON TECHNOLOGY

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 3 | Wings | — | Half | MidSpan | Aft | Long | True | True | False | — | True |

### Batch_01 — `US10450062B1` — Amazon Technology 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2021362849A1` — ARCHER AVIATION

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Full | Spanning | Fore | Long | 3 | True | False | — | True |
| 2 | Wings | — | Half | Spanning | Aft | Long | 3 | True | False | — | True |

### Batch_01 — `US2022250742A1` — ARCHER AVIATION 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Full | Spanning | Fore | Long | 3 | True | False | — | True |
| 2 | Wings | — | Half | Spanning | Aft | Long | 3 | True | False | — | True |

### Batch_01 — `US2022388649A1` — ARCHER AVIATION 3

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2017203839A1` — AURORA FLIGHT 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | NA | Aft | Lat | True | True | False | — | True |

_Notes:_ Propellers are joined forming 2 "wings", because there are no wings but yes a conjunction  of propellers in a main wing and a canard one

### Batch_01 — `US2021016876A1` — AURORA FLIGHT 5

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Spanning | Fore | Long | 2 | True | False | — | True |
| 2 | Wings | — | Half | Spanning | Aft | Long | 2 | True | False | — | True |

### Batch_01 — `DE102020007836A1` — BAAZ GMBH

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_01 — `DE102020007834A1` — BAAZ GMBH 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | MidSpan | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | MidSpan | Aft | Lat | True | True | False | — | True |

### Batch_01 — `CN113086184A` — BEIHANG UNIV 5

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | NA | Aft | Lat | True | True | False | — | True |

### Batch_01 — `US2018354613A1` — AIRBUS DEFENCE 4

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_01 — `US2021094674A1` — BELL TEXTRON

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_01 — `US2020391879A1` — BELL TEXTRON 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_01 — `US2020391862A1` — Bell Textron 5

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2019135424A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 4 | Wings | — | Half | MidSpan | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2019135424A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2019135424A1_arch3` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2021107640A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2021107640A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022306292A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022306292A1_arch3` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022306292A1_arch4` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Fuselage | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022306292A1_arch5` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022306293A1` — BELL TEXTRON 9

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022324558A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022324558A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2019100303A1` — BELL HELICOPTER 18

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2019100313A1` — BELL HELICOPTER 17

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2022371727A1_arch3` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `US2023056974A1` — Textron Innovations 5

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_01 — `WO2025216782A2` — TEXTRON SYSTEM 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | MidSpan | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | MidSpan | Aft | Long | True | True | False | — | True |

### Batch_02 — `WO2023211639A1` — Beta Air 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `US2022402602A1` — Beta Air 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `US2022315236A1` — BETA AIR 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `US11208206B1` — Beta Air 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `US2025350216A1` — Beta Air 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `US2019092461A1` — THE BOEING CO 6

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | — | Spanning | Fore | Long | 2 | True | False | — | True |
| 2 | Wings | — | — | Spanning | Aft | Long | 2 | True | False | — | True |

### Batch_02 — `CN117682065A` — BEIJING AERONAUTICAL 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | — | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | — | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `DE102016001771A1` — DAIMLER AG

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Vert | True | True | False | — | False |
| 2 | Fuselage | — | — | NA | Aft | Vert | True | True | False | — | False |

### Batch_02 — `DE102016015461A1` — Daimler Ag

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Vert | True | True | False | — | False |
| 2 | Fuselage | — | — | NA | Aft | Vert | True | True | False | — | False |

### Batch_02 — `DE102012020498A1` — EMT INGENIEURGESELLSCHAFT 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_02 — `US2020354048A1` — EMBRAER SA 4

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | Fore | — | Outboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | Aft | — | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | Fore | — | Outboard | Aft | Long | True | True | False | — | True |
| 4 | Wings | Aft | — | Outboard | Aft | Long | True | True | False | — | True |
| 5 | Wings | Aft | — | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `EP2669195A1_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | MidSpan | Mid | Lat | True | True | False | — | True |
| 3 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_02 — `EP2669195A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_02 — `EP2669195A1_arch3` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | — | True |

### Batch_02 — `US2019308723A1` — HOVERSURF INC 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Long | True | True | False | — | True |

_Notes:_ wings rotate beween hhover and cruise not for thrust vectoring purposes

### Batch_02 — `US2019310660A1` — Hoversurf Inc 1

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `WO2019211875A1` — ANTHONY ALVIN

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | Aft | — | Spanning | Fore | Long | 3 | True | False | — | True |
| 2 | Wings | Fore | — | Inboard | Aft | Long | True | True | False | — | True |
| 3 | Wings | Fore | — | Spanning | Aft | Long | 2 | True | False | — | True |

### Batch_02 — `US2013092799A1_arch4` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Long | True | True | False | — | False |
| 2 | Fuselage | — | — | Inboard | Aft | Long | True | True | False | — | True |

### Batch_02 — `US2009084890A1` — REINHARDT GERT

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | NA | Aft | Lat | True | True | False | — | True |

### Batch_03 — `JP7438589B1` — ISHIKAWA ENERGY

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | Fore | — | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | Aft | — | Inboard | Aft | Long | True | True | False | — | True |

### Batch_03 — `US10526079B1` — KITTY HAWK

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Lat | True | True | False | — | True |
| 2 | Fuselage | — | — | NA | Aft | Lat | True | True | False | — | True |
| 3 | Other | — | — | MidSpan | FullSpan | Long | True | True | False | — | True |

### Batch_03 — `CN120270494A` — NORTHWESTERN POLYTECHNIC UNIV 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | Fore | — | Inboard | Fore | Long | True | True | False | False | True |
| 2 | Wings | Aft | — | Inboard | Aft | Long | True | True | False | False | True |

### Batch_03 — `US2025042543A1` — TETRA AVIATION

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | Fore | — | Spanning | Fore | Long | 4 | True | False | False | True |
| 2 | Wings | Aft | — | Spanning | Fore | Long | 4 | True | False | False | True |
| 3 | Wings | Fore | — | Spanning | Aft | Long | 4 | True | False | False | True |
| 4 | Wings | Aft | — | Spanning | Aft | Long | 4 | True | False | False | True |

### Batch_03 — `WO2022180755A1` — TETRA AVIATION 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | Fore | — | Spanning | Fore | Long | 4 | True | False | False | True |
| 2 | Wings | Aft | — | Spanning | Fore | Long | 4 | True | False | False | True |
| 3 | Wings | Fore | — | Spanning | Aft | Long | 4 | True | False | False | True |
| 4 | Wings | Aft | — | Spanning | Aft | Long | 4 | True | False | False | True |

### Batch_03 — `CN113306714A` — ZENG ZHAODA

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Lat | True | True | False | True | True |
| 2 | Fuselage | — | — | NA | Aft | Lat | True | True | False | True | True |
| 3 | Fuselage | — | — | NA | Aft | Long | True | False | False | False | True |

### Batch_03 — `CN120887008A` — LI YOUZHI

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | False | False | True |
| 2 | Fuselage | — | — | Inboard | Mid | Lat | True | True | False | False | True |
| 3 | Fuselage | — | — | Inboard | Aft | Lat | True | True | False | False | True |

### Batch_05 — `EP4151521A1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | — | Outboard | Fore | Long | True | True | — | — | — |
| 2 | Wings | — | — | Inboard | Aft | Long | True | True | — | — | — |

_Notes:_ 2 boooms that connect to the empenage, and 2 at the wing tips

### Batch_05 — `GB202302628D0_arch1` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | — | — | — |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | False | True | — | — | — |

### Batch_05 — `GB202302628D0_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | — | Spanning | Fore | Long | 2 | True | — | — | — |
| 2 | Wings | — | — | Spanning | Aft | Long | 2 | True | — | — | — |

### Batch_05 — `CN120135432A` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | NA | Fore | Lat | True | True | — | — | True |
| 2 | Fuselage | — | — | NA | Aft | Lat | True | True | — | — | True |

### Batch_05 — `US2008283673A1_arch2` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | — | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | — | — | True |

### Batch_05 — `US2008283673A1_arch3` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Lat | True | True | — | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Lat | True | True | — | — | True |

### Batch_05 — `US2023286650A1` — VERTICAL AEROSPACE

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | — | Spanning | Fore | Long | 2 | True | — | — | True |
| 2 | Wings | — | — | Spanning | Aft | Long | 2 | True | — | — | True |

### Batch_05 — `GB202410221D0` — Vertical Aerospace

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | — | Spanning | Fore | Long | 2 | True | — | — | True |
| 2 | Wings | — | — | Spanning | Aft | Long | 2 | True | — | — | True |

### Batch_05 — `US2024409209A1` — Whisper Aero

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fuselage | — | — | Inboard | Fore | Long | 4 | True | False | — | True |
| 2 | Fuselage | — | — | Inboard | Aft | Long | 4 | True | False | — | True |

### Batch_05 — `US2021245873A1` — WISK AERO

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Spanning | Fore | Long | 2 | True | False | — | True |
| 2 | Wings | — | — | Spanning | Aft | Long | 2 | True | False | — | True |

### Batch_05 — `US2022126996A1` — Wisk Aero 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Spanning | Fore | Long | 3 | True | False | — | True |
| 2 | Wings | — | Half | Spanning | Aft | Long | 3 | True | False | — | True |

### Batch_05 — `US12486026B1` — WISK AERO 4

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Spanning | Fore | Long | 3 | True | False | — | True |
| 2 | Wings | — | Half | Spanning | Aft | Long | 3 | True | False | — | True |

### Batch_05 — `CN119231794A` — SICHUAN WOFEI

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_05 — `CN119262274A` — SICHUAN WOFEI 2

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 4 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_05 — `US2024097521A1` — wisk aero 5

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Spanning | Fore | Long | 3 | True | False | — | True |
| 2 | Wings | — | Half | Spanning | Aft | Long | 3 | True | False | — | True |

### Batch_05 — `CN114449860A` — SHANGHAI WOLLANT

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 4 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_05 — `CN114954905A` — Shanghai Wollant

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Outboard | Fore | Long | True | True | False | — | True |
| 3 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |
| 4 | Wings | — | Half | Outboard | Aft | Long | True | True | False | — | True |

### Batch_05 — `EP3974315A1_arch4` — _(no aircraft name)_

| Group | attach | wingRel | wingSpan | span | long | orient | count | sym | circSym | tilts | hasProps |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wings | — | Half | Inboard | Fore | Long | True | True | False | — | True |
| 2 | Wings | — | Half | Inboard | Aft | Long | True | True | False | — | True |

## B5 — summary

| Check | Records affected |
|---|---|
| B1 — `Other` disapprovals matching the keyword list | 9 (of 18 `Other` total) |
| B1b — records under the retired `Unreadable` | 25 |
| B2 — vertical boom groups with symmetry ticked | 17 groups |
| B3 — `Fins` records | 18 |
| B3 — `VertFin` records | 83 |
| B4 — possible split boom groups | 92 |

| Scope | Count |
|---|---|
| Records (variant aircraft) scanned | 1508 |
| Distinct patents | 1363 |
| Multi-variant records (`_archN`) | 145 |
| Records carrying at least one boom group | 295 |
|  Batch_01 | 393 |
|  Batch_02 | 449 |
|  Batch_03 | 424 |
|  Batch_05 | 242 |
