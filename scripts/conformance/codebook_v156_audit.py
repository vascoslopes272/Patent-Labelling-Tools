#!/usr/bin/env python3
"""v15.6 / v15.7 codebook audit — the rules that C1-C6 and the L-series do not reach.

check_batches.py asks "is this VALUE still in the option list?".
consistency_audit.py asks "do these fields contradict each other?".
This asks the third question: "does the record obey the rules the codebook was
CLARIFIED into on 2026-09-02/03/05?" — the TW/TR/CVT triangle, boom tilt vs body
motion, the boom long/wingIdx split, straddle counting, the fin-count split,
the Line Drawing retirement, empennage tilt, and distinct-architecture identity.

It also REPLAYS the wizard's own nextBlockers() in Python, so a record that
would not be allowed to leave a page today is reported even if every value it
holds is individually legal.

Usage: python codebook_v156_audit.py Batch_05 [/path/to/reviewed.xlsx]
"""
import pandas as pd, re, sys, collections

D = ("/mnt/storage_11tb/Drive_files_to_syncronize/3 - Images DataSets & Labelling Outputs"
     "/1639_DS/data")
B   = sys.argv[1] if len(sys.argv) > 1 else "Batch_05"
SRC = sys.argv[2] if len(sys.argv) > 2 else f"{D}/03c_CORRECTED_wizard_exports/reviewed_patents_{B}.xlsx"

n = pd.read_excel(SRC, sheet_name="Review")
code = lambda v: str(v).split(' — ')[0].strip() if v is not None and str(v) != 'nan' else None
base = lambda p: re.sub(r'_arch\d+$', '', str(p))

F   = collections.defaultdict(dict)
FIG = collections.defaultdict(lambda: collections.defaultdict(dict))
for _, r in n.iterrows():
    sd = str(r.Sub_Dimension)
    v = None if (r.Value is None or str(r.Value) == 'nan') else r.Value
    if sd.startswith("Image: "): FIG[str(r.Patent_ID)][sd[7:]][str(r.Field)] = v
    else:                        F[str(r.Patent_ID)][str(r.Field)] = v

P    = set(F) | set(FIG)
ap   = {p for p in P if str(F[p].get('isApproved')) == 'True' or str(F[base(p)].get('isApproved')) == 'True'}
d2   = {p for p in P if code(F[p].get('duplicateType')) == '2'}
arch = {p for p in P if re.search(r'_arch\d+$', p)}
live = sorted(p for p in P if p in ap and p not in d2
              and (p in arch or not any(q.startswith(p + '_arch') for q in P)))

out = []
def flag(rule, msg, detail): out.append((rule, msg, detail))

def num(v):
    """The wizard writes a count of 1 as the boolean True (openpyxl coercion)."""
    s = str(v)
    if s == 'True': return 1
    if s in ('False', 'None', 'nan', ''): return 0
    try: return int(float(s))
    except ValueError: return 0
truthy = lambda v: str(v) == 'True'

STATIONS = ['fuselage', 'emp', 'boom', 'core_layout', 'hull_array']
WINGED_CONF = {'W', 'Oth'}
WINGED_ARCHS = {'TW','TR','DS','CVT','TB','PTC','SLC','SRW'}   # isWinged()
OTHER_ARCHS  = {'HB','PFV'}                                    # isOtherArch()
FIXED_PK_ARCHS = {'TW','DS','SLC','SRW','MR','TB','PTC','RC'}   # propKinLock()

def rec(p):
    """Everything the rules below need, read once per architecture."""
    f = F[p]
    R = {'f': f, 'top': code(f.get('topType')), 'wc': num(f.get('wCount')),
         'wingConf': code(f.get('wingConf')), 'fusKin': code(f.get('fusKin')),
         'empType': code(f.get('empType')), 'empTilts': truthy(f.get('empTilts')),
         'boomsPresent': truthy(f.get('boomsPresent')),
         'quickOv': truthy(f.get('m1_quickOverride')) or truthy(f.get('g1_quickOverride'))}
    R['wingKeys'] = ['wing%d' % i for i in range(1, R['wc'] + 1)]
    # station propulsor count, honouring a Quick Count Override
    def scount(k):
        if truthy(f.get(k + '_quickOverride')): return num(f.get(k + '_quickCount'))
        return num(f.get(k + '_count'))
    R['scount'] = scount
    # every propKin actually recorded, per station
    def pks(k):
        nt = num(f.get(k + '_ntypes'))
        if nt > 1: return [code(f.get(f'{k}_t{t}_propKin')) for t in range(1, nt + 1)
                           if f.get(f'{k}_t{t}_propKin') is not None]
        return [code(f[k + '_propKin'])] if f.get(k + '_propKin') is not None else []
    R['pks'] = pks
    # 2026-09-05 (#12): a unit ticked "Control / stability only" is NOT a thrust
    # source for the TR-vs-CVT test, so a tilt wing carrying a small stability
    # propeller stays a Tilt Wing rather than becoming Combined.
    def ctrl_only(k):
        nt = num(f.get(k + '_ntypes'))
        if nt > 1:
            vals = [f.get(f'{k}_t{i}_ctrlOnly') for i in range(1, nt + 1)]
        else:
            vals = [f.get(k + '_ctrlOnly')]
        vals = [v for v in vals if v is not None]
        return bool(vals) and all(truthy(v) for v in vals)
    R['ctrlOnly'] = ctrl_only
    R['tiltw'] = {i for i in range(1, R['wc'] + 1) if code(f.get(f'wing{i}_tilt')) == 'Tilt'}
    R['booms'] = sorted({m.group(1) for k in f
                         if (m := re.match(r'boom(\d+)_(attach|count|orient|span|sym|tilts|hasProps|long|wingRel|wingIdx|circSym|cards)$', k))},
                        key=int)
    R['boomTilt'] = {g for g in R['booms'] if truthy(f.get(f'boom{g}_tilts'))}
    return R

# ── the vectoring-mix primitives, mirrored from the wizard ──────────────────
def non_tilting_thrust(R):
    """twNonTiltingThrustStations() + hasFixedBoomThrust()."""
    f, out_ = R['f'], []
    for i in range(1, R['wc'] + 1):
        if code(f.get(f'wing{i}_tilt')) != 'Tilt' and R['scount']('wing%d' % i) > 0:
            out_.append(f'Wing {i}')
    for k, nm in (('fuselage', 'fuselage'), ('emp', 'empennage'),
                  ('hull_array', 'hull array'), ('core_layout', 'hub array')):
        if k == 'emp' and R['empTilts']: continue
        if R['scount'](k) > 0: out_.append(nm)
    if R['boomsPresent'] and R['scount']('boom') > 0:
        fixed = [g for g in R['booms'] if g not in R['boomTilt']
                 and str(f.get(f'boom{g}_hasProps')) != 'False']
        if fixed: out_.append('boom group ' + '/'.join(fixed) + ' (not ticked "booms tilt")')
    return out_

def tilting_thrust(R):
    f, out_ = R['f'], []
    for i in sorted(R['tiltw']):
        if R['scount']('wing%d' % i) > 0: out_.append(f'Wing {i} (tilts, propelled)')
    for k in STATIONS + R['wingKeys']:
        if 'Tilt' in R['pks'](k): out_.append(f'{k} propKin=Tilt')
    if R['boomsPresent'] and R['scount']('boom') > 0:
        t = [g for g in R['boomTilt'] if str(f.get(f'boom{g}_hasProps')) != 'False']
        if t: out_.append('boom group ' + '/'.join(sorted(t)) + ' (booms tilt)')
    return out_

for p in live:
    R = rec(p); f = R['f']; t = R['top']
    tilting, fixed = tilting_thrust(R), non_tilting_thrust(R)

    # ── N1  TR that also carries thrust which does not tilt ──────────────────
    # CVT's own text: "what makes the aircraft CVT is that some other thrust
    # source does NOT tilt with it, such as FIXED ROTORS ON A WING".
    #
    # For a TR the question is about the PROPULSORS, not the wing: "propulsors
    # tilt independently of FIXED wing" is the TR definition, so a fixed wing
    # carrying tilting rotors is TR, not CVT. What makes it CVT is a propulsor
    # set whose own articulation is Fixed sitting alongside one that is Tilt.
    if t == 'TR':
        tilt_st  = [k for k in STATIONS + R['wingKeys'] if 'Tilt'  in R['pks'](k) and R['scount'](k) > 0]
        fixed_st = [k for k in STATIONS + R['wingKeys'] if 'Fixed' in R['pks'](k) and R['scount'](k) > 0
                    and not R['ctrlOnly'](k)]
        # a tilting boom vectors its own thrust even with propKin=Fixed
        tb = [g for g in R['boomTilt'] if str(f.get(f'boom{g}_hasProps')) != 'False']
        if tb and R['scount']('boom') > 0: tilt_st.append('boom(tilting structure)')
        if R['tiltw'] and any(R['scount']('wing%d' % i) > 0 for i in R['tiltw']):
            tilt_st.append('tilting wing')
        if tilt_st and fixed_st:
            flag('N1', 'TR carrying a FIXED thrust source alongside the tilting one — CVT by the boundary settled 2026-09-05',
                 f"{p}   tilt={tilt_st}  fixed={fixed_st}")
        elif not tilt_st:
            flag('N1b', 'TR where no propulsor, wing or boom actually tilts', f"{p}  propKin seen: "
                 + str(sorted({v for k in STATIONS + R['wingKeys'] for v in R['pks'](k) if v})))

    # ── N2  TW propelled-wing / sole-thrust lock (nextBlockers m2 + m3) ──────
    if t == 'TW':
        if not R['tiltw']:
            flag('N2', 'TW with no wing set to Tilt', p)
        else:
            nt = non_tilting_thrust(R)
            if nt: flag('N2', 'TW carrying thrust that does not tilt with the wing — CVT case (c)',
                        f"{p}  -> {', '.join(nt)}")

    # ── N3  CVT must show the mix ───────────────────────────────────────────
    if t == 'CVT':
        if not tilting: flag('N3', 'CVT with no rotating thrust source', p)
        elif not fixed: flag('N3', 'CVT with no non-rotating thrust source',
                             f"{p}  tilts: {', '.join(tilting)}")

    # ── N1c  the inverse of the settled boundary: if EVERYTHING tilts it is a TR
    if t == 'CVT' and tilting and not fixed:
        flag('N1c', 'CVT where every thrust source tilts — that is a Tilt Rotor under the '
                    'boundary settled 2026-09-05', f"{p}  tilts: {', '.join(tilting)}")

    # ── N4  boom tilt vs what the body does ─────────────────────────────────
    # "Not 'the booms move when the aircraft moves': on a tilt-body that rotates
    #  as one, they do not tilt; on a level-cabin layout, they do."
    if R['boomTilt'] and R['fusKin'] == 'TiltBody':
        flag('N4', 'booms ticked as tilting on a TiltBody airframe that rotates as one rigid body',
             f"{p}  groups={sorted(R['boomTilt'])} fusKin=TiltBody")
    if R['boomTilt'] and R['fusKin'] in ('BodyPitch',):
        flag('N4b', 'booms ticked as tilting on a whole-body-pitch airframe — check the booms move RELATIVE to the fuselage',
             f"{p}  groups={sorted(R['boomTilt'])} fusKin=BodyPitch top={t}")

    # ── N5/N6  boom long / wingIdx split (v15.5) ────────────────────────────
    for g in R['booms']:
        at = code(f.get(f'boom{g}_attach'))
        wingrefd = at in ('Wings', 'Both')
        lg, wi, wr = f.get(f'boom{g}_long'), f.get(f'boom{g}_wingIdx'), f.get(f'boom{g}_wingRel')
        if at is None:
            flag('N5', 'boom group has no attachment recorded (mandatory)', f"{p}  group {g}")
            continue
        if wingrefd and lg is not None:
            flag('N5', 'boom long answered on a WING-attached group (v15.5: fuselage-only)', f"{p}  group {g} long={code(lg)}")
        if not wingrefd and lg is None:
            flag('N5', 'boom long missing on a non-wing-attached group (mandatory)', f"{p}  group {g} attach={at}")
        # v15.6 (2026-09-05): spanwise mirrors long — asked, required and exported
        # only for a WING-referenced group.
        sp = f.get(f'boom{g}_span')
        if not wingrefd and sp is not None:
            flag('N5b', 'boom span answered on a non-wing-attached group (v15.6: wing-referenced only)',
                 f"{p}  group {g} span={code(sp)} attach={at}")
        if wingrefd and sp is None:
            flag('N5b', 'wing-attached boom with no spanwise position (mandatory)', f"{p}  group {g}")
        if wingrefd and wr is None:
            flag('N6', 'wing-attached boom with no wingRel (mandatory since 2026-08-07)', f"{p}  group {g} attach={at}")
        if wingrefd and R['wc'] >= 2 and wi is None:
            flag('N6', 'wing-attached boom on a >=2-panel aircraft with no wingIdx (mandatory v15.5)',
                 f"{p}  group {g} attach={at} wCount={R['wc']}")
        if wi is not None and code(wi) not in ('Multi',) and R['wc'] >= 1:
            m = re.fullmatch(r'W(\d)', code(wi) or '')
            if m and int(m.group(1)) > R['wc']:
                flag('N6', 'wingIdx names a panel beyond wCount', f"{p}  group {g} wingIdx={code(wi)} wCount={R['wc']}")
        # ── N7  Straddle vs the counting rule ────────────────────────────────
        if code(wr) == 'Straddle':
            nt = num(f.get('boom_ntypes'))
            chords = {code(f.get(f'boom_t{k}_chord')) for k in range(1, nt + 1)} if nt > 1 \
                     else {code(f.get('boom_chord'))}
            chords.discard(None)
            if {'Front', 'Back'} <= chords:
                flag('N7', 'Straddle boom whose propulsors DO split into a forward and an aft set — '
                           'the counting rule makes this two boom groups',
                     f"{p}  group {g} boom card chords={sorted(chords)}")
        if code(wr) == 'Bridge' and code(wi) not in (None, 'Multi'):
            flag('N7b', '"Bridges two wings" paired with a single-panel wingIdx',
                 f"{p}  group {g} wingRel=Bridge wingIdx={code(wi)}")
        if code(wi) == 'Multi' and code(wr) not in (None, 'Bridge'):
            flag('N7b', 'wingIdx "More than one panel" not paired with wingRel "Bridges two wings"',
                 f"{p}  group {g} wingIdx=Multi wingRel={code(wr)}")

    # ── N8  fin codes are decided by COUNT ──────────────────────────────────
    # VertFin = exactly ONE vertical surface. A twin-boom airframe carrying a fin
    # per boom is two surfaces, so it is Fins under the v15.5 rule.
    if R['empType'] == 'VertFin':
        tot = sum(num(f.get(f'boom{g}_count')) for g in R['booms'])
        if tot >= 2:
            flag('N8', 'VertFin (exactly ONE vertical surface) on a multi-boom airframe — re-read: '
                       'a fin per boom is "Two or More Vertical Fins"',
                 f"{p}  {tot} booms in {len(R['booms'])} group(s)")
    if R['empType'] == 'Tailless' and R['scount']('emp') > 0:
        flag('N8b', 'Tailless empennage carrying propulsors', p)

    # ── N9  empennage tilt ──────────────────────────────────────────────────
    if f.get('empTiltsNote') is not None:
        flag('N9', 'empTiltsNote still carried — v15.5 retired the mandatory description',
             f"{p}  note={str(f.get('empTiltsNote'))[:60]!r}")
    # Exact render gate (pageM2 "Empennage Articulation"):
    #   empType && empType != Tailless
    #   && (empType not in [Fins, VertFin]  ||  the empennage carries propulsors)
    #   && (topType == RC || isWinged())
    _etShown = (R['empType'] and R['empType'] != 'Tailless'
                and (R['empType'] not in ('Fins', 'VertFin') or R['scount']('emp') > 0)
                and (t == 'RC' or t in WINGED_ARCHS))
    if R['empTilts'] and not _etShown:
        flag('N9', 'empTilts ticked but the checkbox is not rendered for this record — '
                   'a legacy value the reviewer cannot see or clear',
             f"{p}  top={t} empType={R['empType']} empPropulsors={R['scount']('emp')}")

    # ── N12  nextBlockers() replay ──────────────────────────────────────────
    if not R['quickOv'] and t not in (None, 'Oth', 'Other') and t not in OTHER_ARCHS:
        miss = []
        if R['boomsPresent'] and not R['booms']: miss.append('boomsPresent ticked, no boom group')
        for g in R['booms']:
            gm = []
            if num(f.get(f'boom{g}_count')) <= 0: gm.append('count')
            if f.get(f'boom{g}_attach') is None:  gm.append('attachment')
            # v15.6: spanwise is required only where it is RENDERED — i.e. on a
            # wing-referenced group. On a fuselage boom the migration correctly
            # cleared it, so demanding it here would re-flag every migrated record.
            _wr = code(f.get(f'boom{g}_attach')) in ('Wings', 'Both')
            if _wr and f.get(f'boom{g}_span') is None:  gm.append('spanwise position')
            if not _wr and f.get(f'boom{g}_long') is None: gm.append('longitudinal position')
            if f.get(f'boom{g}_orient') is None:  gm.append('orientation')
            if f.get(f'boom{g}_hasProps') is None: gm.append('carries propulsors?')
            if gm: miss.append(f'boom group {g}: ' + ', '.join(gm))
        for k in ('fusShape', 'fusKin', 'gearArch'): 
            if f.get(k) is None: miss.append(k)
        if f.get('empType') is None: miss.append('empType')
        if t in WINGED_ARCHS and R['wingConf'] in ('BWB','FW','LB') and f.get('wing1_plan') is None:
            miss.append('integrated-hull planform (wing1_plan)')
        if t in WINGED_ARCHS and R['wingConf'] in WINGED_CONF:
            if R['wc'] < 1: miss.append('wing count')
            for i in range(1, R['wc'] + 1):
                wm = [x for x in ('tilt', 'posV', 'posL', 'plan') if f.get(f'wing{i}_{x}') is None]
                if wm: miss.append(f'wing {i}: ' + ', '.join(wm))
                if i > 1 and f.get(f'wing{i}_role') is None: miss.append(f'wing {i}: role')
        if miss: flag('N12', 'the wizard would not let this record leave its page today',
                      f"{p}  [{t}]  " + ' | '.join(miss[:5]))

# ── N14  v15.6 retirements that a MIGRATION has to clear, not a reviewer ────
_RETIRED_M3_SYM = re.compile(r'^(fuselage|emp|boom|core_layout|hull_array|wing\d)(_t\d)?_(symLong|symCirc)$')
_n14 = collections.Counter()
for p in sorted(F):
    for k, v in F[p].items():
        if _RETIRED_M3_SYM.fullmatch(k) and v is not None:
            _n14[k.split('_')[-1]] += 1
    if code(F[p].get('gearArch')) == 'RetrWheel':
        flag('N14', "gearArch still on 'RetrWheel' — retired v15.6, migrates into 'FixedWheel'", p)
for suffix, n_ in sorted(_n14.items()):
    flag('N14', f'M3 card field {suffix} still exported — RETIRED v15.6, the wizard no longer '
                f'writes it; a reload/save would silently drop it', f'{n_} values across the batch')

# ── N15  legacy acState values awaiting a re-pick ──────────────────────────
_AC_OK = {'Hover', 'Transition', 'Cruise', 'HoverCruise', 'Other'}
_n15 = collections.Counter()
for p, figs in FIG.items():
    for fig, fd in figs.items():
        if str(fd.get('status')) != 'approved': continue
        v = code(fd.get('acState'))
        if v and v not in _AC_OK: _n15[v] += 1
for v, n_ in sorted(_n15.items()):
    flag('N15', 'acState holds a value the T2 grid has never offered — a stored legacy value '
                'awaiting a re-pick (AC_STATE_CHOICES, v15.7)', f'{v}: {n_} approved figures')

# ── N16/N17  populations the new v15.6/15.7 dimensions have never swept ────
_dis = collections.Counter()
for p in sorted(F):
    if str(F[p].get('isApproved')) == 'False':
        _dis[code(F[p].get('t1DisapproveReason'))] += 1
_nv = _dis.get('Out of Domain', 0) + _dis.get('Other', 0)
if _nv:
    flag('N16', "disapprovals on 'Out of TD' / 'Other' that predate the 'Not VTOL' reason "
                "(v15.7) — an electric STOL had nowhere else to go", 
         f"{_nv} records: Out of Domain {_dis.get('Out of Domain',0)}, Other {_dis.get('Other',0)}")
_new_fields = {
    'boomN_retracts (BOOM-6, booms that stow)': r'boom\d+_retracts',
    'ctrlOnly (#12, control-only propulsors)':  r'.*_ctrlOnly$',
    "wingN_plan = 'Trap' (v15.6 taper)":        None,
    't1EdgeTags ElectricSimilar (v15.7)':       None,
}
_seen = collections.Counter()
for p in sorted(F):
    for k, v in F[p].items():
        if re.fullmatch(r'boom\d+_retracts', k) and truthy(v): _seen['boomN_retracts (BOOM-6, booms that stow)'] += 1
        if k.endswith('_ctrlOnly') and truthy(v):               _seen['ctrlOnly (#12, control-only propulsors)'] += 1
        if re.fullmatch(r'wing\d_plan', k) and code(v) == 'Trap': _seen["wingN_plan = 'Trap' (v15.6 taper)"] += 1
        if k == 't1EdgeTags' and 'ElectricSimilar' in str(v):    _seen['t1EdgeTags ElectricSimilar (v15.7)'] += 1
for lbl in _new_fields:
    if not _seen[lbl]:
        flag('N17', 'a dimension added on 2026-09-05 that no record in this batch carries — '
                    'positive-marker fields, so blank is legal, but nothing has swept for them', lbl)

# ── N10  retired rendering style + per-figure completeness ──────────────────
T2_REQ = ['per', 'acSty', 'acCol', 'bgSty', 'bgCol', 'parts', 'acState']
for p, figs in FIG.items():
    if p not in ap and base(p) not in ap: continue
    for fig, fd in figs.items():
        if str(fd.get('status')) != 'approved': continue
        if str(fd.get('acSty')) == 'Simple Line Drawing':
            flag('N10', 'retired rendering style "Simple Line Drawing" (v15.5: it is just Line Drawing)',
                 f"{p}  {fig}")
        gaps = [k for k in T2_REQ if fd.get(k) is None or str(fd.get(k)).strip() in ('', 'nan')]
        if gaps: flag('N10b', 'approved figure missing mandatory T2 fields', f"{p}  {fig}: {', '.join(gaps)}")
        for k, nk in (('acSty','acStyOtherNote'),('acCol','acColOtherNote'),
                      ('bgSty','bgStyOtherNote'),('bgCol','bgColOtherNote')):
            if str(fd.get(k)) == 'Other' and not str(fd.get(nk) or '').strip():
                flag('N10c', f'figure picked "{k}=Other" with no paired note', f"{p}  {fig}")

# ── N11  distinct architectures ────────────────────────────────────────────
IGNORE = re.compile(r'(notes?$|Note$|^comments$|dinoUnderstanding|timestamp|labelToken|'
                    r'humanUncertain|quickNote|uncertainNote|_otherNote$|patentImageComments)')
byparent = collections.defaultdict(list)
for p in live:
    if p in arch: byparent[base(p)].append(p)
for parent, kids in sorted(byparent.items()):
    if len(kids) < 2: continue
    for i in range(len(kids)):
        for j in range(i + 1, len(kids)):
            a, b_ = F[kids[i]], F[kids[j]]
            ka = {k: str(v) for k, v in a.items() if not IGNORE.search(k)}
            kb = {k: str(v) for k, v in b_.items() if not IGNORE.search(k)}
            diff = {k for k in set(ka) | set(kb) if ka.get(k) != kb.get(k)}
            if not diff:
                flag('N11', 'two architecture records that do not differ in ANY aircraft property',
                     f"{kids[i]} == {kids[j]}")
            elif len(diff) <= 2:
                flag('N11b', 'two architectures separated by only 1-2 fields — check they are really distinct',
                     f"{kids[i]} vs {kids[j]}: {sorted(diff)}")

# ── N13  one main figure per architecture ──────────────────────────────────
for p in live:
    figs = FIG.get(p) or FIG.get(base(p)) or {}
    aidx = re.search(r'_arch(\d+)$', p)
    mains = [k for k, v in figs.items() if str(v.get('isMain')) == 'True'
             and str(v.get('status')) == 'approved'
             and (not aidx or str(v.get('arch')) == aidx.group(1))]
    if len(mains) > 1: flag('N13', 'more than one main figure on one architecture', f"{p}  {mains}")
    if not mains:      flag('N13', 'no main figure on an approved architecture', p)

print("=" * 78)
print(f"  {B} — v15.6 CODEBOOK AUDIT   {len(live)} live architectures   {SRC.split('/')[-1]}")
print("=" * 78)
by = collections.defaultdict(list)
for r, m, d in out: by[(r, m)].append(d)
if not by: print("\n  clean — no v15.5 rule violations.")
for (r, m), ds in sorted(by.items()):
    print(f"\n  [{r}] {m}  — {len(ds)}")
    for d in ds[:12]: print(f"        {d}")
    if len(ds) > 12: print(f"        … and {len(ds) - 12} more")
print()
