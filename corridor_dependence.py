"""
corridor_dependence.py  --  Asifah Analytics  (ME backend)
================================================================
EDGE -> NODE.  Turns a corridor state into per-country readings.

THE PROBLEM THIS SOLVES
  corridor_registry.py (Europe) answers "is the route passable."
  convergence_detector.py (ME) asks, per country, "what is happening HERE."
  Nothing joined them, because a corridor is an EDGE and the detector is
  NODE-shaped. Black Sea closure does not happen IN Ukraine; it is the link
  between Ukraine and Lebanon, Egypt, Gaza, Syria.

      corridor state (EDGE)  x  dependence share (THIS FILE)  =  node reading

  Lebanon gets a Black Sea reading not because Lebanon is in the Black Sea,
  but because 80-90%% of Lebanon's wheat arrives through it.

THE RULE THAT KEEPS THIS HONEST -- DEPENDENCE IS A MULTIPLIER, NOT A SIGNAL
  "Lebanon is 85%% Black Sea dependent with one month of reserves" is true and
  alarming and CONSTANT. Emitting it as a convergence would fire every scan
  forever and never change -- which is exactly the monotonous-GPI problem the
  Sep 20 registry audit diagnosed, in a new costume.

  Dependence MODULATES corridor state. It never emits on its own. If the
  corridor is 'unknown', every dependent node is 'unknown' -- a structural
  fact about Lebanon cannot substitute for a reading of the sea.

TWO-HOP DEPENDENCE
  Gaza is not Lebanon with worse numbers. Its wheat crosses a maritime
  corridor AND a land terminal, and either hop fails independently: the sea
  can be open while the crossing is shut, and vice versa. Modelled as an
  ordered chain, with the WORST hop binding -- because a chain does not get
  credit for its healthy links.

PROVENANCE
  Every share carries 'verified'. False means Claude researched it and Rachel
  has not yet confirmed it; those values are drafts, and the payload says so
  rather than letting an unchecked number pass as settled. Shares lifted from
  Rachel's own COUNTRY_COMMODITY_EXPOSURE notes are verified=True because she
  sourced them.

READS   corridor:<id>:latest     (written by Europe's corridor_registry)
WRITES  nothing. Pure analyst overlay, same posture as
        commodity_structural_convergence.py.

SCOPING  claude/CORRIDOR_SENSOR_SCOPING.md  (phase 2)
COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import requests
from datetime import datetime, timezone

__version__ = '1.0.0'

DEPENDENCE_VERSION = __version__
DEPENDENCE_USER_AGENT = (f'AsifahAnalytics-ME-CorridorDep/{DEPENDENCE_VERSION} '
                         f'(OSINT monitoring tool; +https://asifahanalytics.com)')

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
CORRIDOR_KEY_PREFIX = 'corridor:'

# Mirrors corridor_registry.CORRIDOR_STATES. 'unknown' is deliberately absent
# from the severity map -- it is an absence, not a low reading, and max() must
# never swallow it.
CORRIDOR_SEVERITY = {'open': 0, 'strained': 1, 'impaired': 2, 'blocked': 3}


# ======================================================================
# THE DEPENDENCE TABLE
# ======================================================================
# 'share' is the fraction of that commodity's supply reaching the country
# through that corridor. 'hops' models a chain: every hop must hold.
#
# DRAFT STATUS: entries marked verified=False were researched by Claude on
# Oct 4 2026 and need Rachel's correction pass. They are carried, flagged, and
# surfaced in the payload -- not quietly treated as fact.
CORRIDOR_DEPENDENCE = {
    'lebanon': {
        'wheat': {
            'hops': [{'corridor': 'black_sea_grain_corridor', 'share': 0.85}],
            'verified': True,
            'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note (commodity_tracker)",
            'as_of': '2026-07',
            'note': ('~60-67%% from Ukraine alone, ~80-90%% combined Black Sea '
                     '(UA+RU). National reserves ~1 month -- silos never rebuilt '
                     'after the 2020 Beirut port explosion. The reserve depth is '
                     'what turns a corridor event into a hunger event here.'),
            'failure_mode': 'fiscal -- no FX, thin reserves, no storage buffer',
        },
    },
    'egypt': {
        'wheat': {
            'hops': [{'corridor': 'black_sea_grain_corridor', 'share': 0.83}],
            'verified': True,
            'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note (commodity_tracker)",
            'as_of': '2026-07',
            'note': ("World's #1 wheat importer. Russia ~66%% + Ukraine ~17%% = "
                     "~83%% Black Sea; EU/France ~14%% is the substitution margin. "
                     "The baladi bread subsidy covers ~70M people and is the "
                     "political transmission channel."),
            'failure_mode': 'fiscal -- subsidy is load-bearing; budget fails before shelves do',
        },
    },
    'syria': {
        'wheat': {
            # 2026 flipped this. Headline self-sufficiency, compositional gap.
            'hops': [{'corridor': 'black_sea_grain_corridor', 'share': 0.20}],
            'verified': False,
            'source': 'Claude research Oct 4 2026 -- syriadispatch 2026 harvest analysis',
            'as_of': '2026-10',
            'note': ('REVERSAL, and the headline misleads. Syria declared wheat '
                     'self-sufficiency in 2026 for the first time since 2010: '
                     '2.7Mt harvest against a 2.55Mt bread-wheat benchmark. But '
                     'the harvest is ~54%% soft / ~46%% durum while Arabic bread '
                     'needs roughly 80/20 -- leaving a ~570kt SOFT wheat '
                     'shortfall alongside a durum surplus. Aggregate sufficiency '
                     'masks compositional dependence. Residual import need is '
                     'soft wheat specifically. Share is a Claude estimate of '
                     'the Black Sea portion of that residual and is NOT sourced '
                     '-- correct it.'),
            'failure_mode': 'compositional -- tonnage adequate, bread wheat short',
            'needs_rachel': ('Is the residual soft-wheat import actually Black Sea '
                             'sourced, and at what share? Pre-2012 Syria was a '
                             'Levant breadbasket; that history is the substitution '
                             'thesis in the Sep 20 note and may be reviving.'),
        },
    },
    'gaza': {
        'wheat': {
            # TWO HOPS. The sea can be open while the crossing is shut.
            'hops': [
                {'corridor': 'black_sea_grain_corridor', 'share': 0.60,
                 'role': 'origin -- global/WFP procurement is Black Sea heavy'},
                {'corridor': 'kerem_shalom', 'share': 1.00,
                 'role': 'terminal -- ALL overland entry; no substitute route'},
            ],
            'verified': False,
            'source': 'Claude research Oct 4 2026 -- WFP Palestine emergency page',
            'as_of': '2026-10',
            'note': ('Gaza is TERMINAL-BOUND, not corridor-bound. WFP: Kerem '
                     'Shalom "remains the main entry point for aid". The crossing '
                     'share is 1.00 because there is no alternative land route -- '
                     'that hop is a single point of failure in a way no maritime '
                     'corridor is. ~1.4M people at crisis-or-worse food insecurity '
                     '(WFP, undated on the page). No covered storage at the '
                     'crossing, so precipitation is a spoilage vector for grain '
                     'that survived every upstream hop.'),
            'failure_mode': 'physical -- one crossing, no storage, fast to famine',
            'needs_rachel': ('Is Zikim operating alongside Kerem Shalom, and does '
                             'commercial (non-WFP) wheat enter separately? The '
                             'origin share of 0.60 is a guess at WFP procurement '
                             'mix and is the weakest number in this table.'),
        },
    },
    'turkey': {
        'wheat': {
            'hops': [{'corridor': 'black_sea_grain_corridor', 'share': 0.45}],
            'verified': False,
            'source': 'Claude estimate from COUNTRY_COMMODITY_EXPOSURE weight 1.2',
            'as_of': '2026-10',
            'note': ('Turkey is both a dependent importer AND the Bosphorus '
                     'gatekeeper -- the only node on this list that sits on both '
                     'sides of its own exposure. Substantial domestic production '
                     'cushions it. Share is an estimate, not sourced.'),
            'failure_mode': 'absorbed -- domestic production plus milling re-export',
        },
    },
}

# Transit states are NOT dependents. Poland carries other countries' grain; a
# corridor event there is a flow problem for Ukraine, not a hunger problem for
# Poland. Listed so nobody later "fixes" the omission.
TRANSIT_NOT_DEPENDENT = ('poland', 'romania')


def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}",
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                                  'User-Agent': DEPENDENCE_USER_AGENT},
                         timeout=8)
        if not r.ok:
            return None
        raw = r.json().get('result')
        if raw is None:
            return None
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        print(f"[CorridorDep] Redis GET {key}: {str(e)[:80]}")
        return None


def read_corridor_states():
    """Pull every corridor this table depends on. Missing => 'unknown'."""
    wanted = set()
    for commodities in CORRIDOR_DEPENDENCE.values():
        for entry in commodities.values():
            for hop in entry['hops']:
                wanted.add(hop['corridor'])
    out = {}
    for cid in sorted(wanted):
        rec = _redis_get(f'{CORRIDOR_KEY_PREFIX}{cid}:latest')
        if isinstance(rec, dict) and rec.get('live_state'):
            out[cid] = {'state': rec['live_state'], 'sensed': rec.get('sensed', False),
                        'baseline_tier': rec.get('baseline_tier'),
                        'generated_at': rec.get('generated_at')}
        else:
            # A corridor with no key is NOT open. It is unread.
            out[cid] = {'state': 'unknown', 'sensed': False, 'baseline_tier': None,
                        'generated_at': None, 'note': 'no corridor record in Redis'}
    return out


def _intensity(state, share):
    """Corridor severity scaled by how much of the supply actually rides it.

    Deliberately coarse. A share is a rough fraction and pretending a 0.83
    multiplies cleanly into a 0-3 ladder would be false precision. Three bands:

      share >= 0.50   full severity   -- the corridor IS the supply
      0.20-0.49       one band down   -- material, substitutable at cost
      < 0.20          two bands down  -- exposed, not dependent

    Returns None for 'unknown' -- never 0, because 0 means "covered and quiet"
    to convergence_detector and would read as calm.
    """
    if state not in CORRIDOR_SEVERITY:
        return None
    sev = CORRIDOR_SEVERITY[state]
    if sev == 0:
        return 0
    if share >= 0.50:
        drop = 0
    elif share >= 0.20:
        drop = 1
    else:
        drop = 2
    return max(0, sev - drop)


def read_country(country_id, corridor_states=None):
    """Per-country logistics reading. Never invents a state."""
    commodities = CORRIDOR_DEPENDENCE.get(country_id)
    if not commodities:
        return None
    states = corridor_states if corridor_states is not None else read_corridor_states()

    readings, worst_intensity, any_unknown, unverified = [], None, False, []
    for commodity, entry in commodities.items():
        hop_reads, binding = [], None
        for hop in entry['hops']:
            cs = states.get(hop['corridor'], {'state': 'unknown', 'sensed': False})
            inten = _intensity(cs['state'], hop['share'])
            hop_reads.append({
                'corridor': hop['corridor'], 'share': hop['share'],
                'role': hop.get('role'), 'corridor_state': cs['state'],
                'sensed': cs.get('sensed', False), 'intensity': inten,
            })
            if inten is None:
                any_unknown = True
            elif binding is None or inten > binding:
                binding = inten
        if not entry.get('verified', False):
            unverified.append(f'{country_id}.{commodity}')
        readings.append({
            'commodity': commodity, 'hops': hop_reads,
            'binding_intensity': binding,
            'chain_complete': all(h['intensity'] is not None for h in hop_reads),
            'verified': entry.get('verified', False),
            'source': entry.get('source'), 'as_of': entry.get('as_of'),
            'note': entry.get('note'), 'failure_mode': entry.get('failure_mode'),
            'needs_rachel': entry.get('needs_rachel'),
        })
        if binding is not None and (worst_intensity is None or binding > worst_intensity):
            worst_intensity = binding

    # A chain with ANY unread hop is unread. A sea we can see does not tell us
    # about a crossing we cannot.
    sensed = (worst_intensity is not None) and not any_unknown

    return {
        'country': country_id,
        'axis': 'logistics',
        'intensity': worst_intensity if sensed else None,
        'sensed': sensed,
        'has_unread_hop': any_unknown,
        'commodities': readings,
        'unverified_entries': unverified,
        'read': _prose(country_id, readings, worst_intensity, sensed, any_unknown),
        'version': DEPENDENCE_VERSION,
    }


def _prose(country_id, readings, intensity, sensed, any_unknown):
    disp = country_id.replace('_', ' ').title()
    if not sensed:
        why = ('one or more corridors in the chain are not currently sensed'
               if any_unknown else 'no corridor reading available')
        return (f'{disp}: logistics axis NOT SENSED -- {why}. Structural '
                f'dependence is on file and unchanged; it is a multiplier, not '
                f'a reading, and cannot stand in for one.')
    top = max(readings, key=lambda r: (r['binding_intensity'] or 0))
    hop = max(top['hops'], key=lambda h: (h['intensity'] or 0))
    return (f"{disp}: {top['commodity']} supply exposed via "
            f"{hop['corridor']} (share {hop['share']:.0%}, corridor "
            f"{hop['corridor_state']}) -- intensity {intensity}. "
            f"Failure mode: {top.get('failure_mode')}. Convergence reading, "
            f"not a forecast of shortage.")


def read_all(corridor_states=None):
    states = corridor_states if corridor_states is not None else read_corridor_states()
    records = [read_country(c, states) for c in sorted(CORRIDOR_DEPENDENCE)]
    records = [r for r in records if r]
    sensed = [r for r in records if r['sensed']]
    unverified = sorted({u for r in records for u in r['unverified_entries']})
    return {
        'version': DEPENDENCE_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'corridor_states': states,
        'country_count': len(records),
        'sensed_count': len(sensed),
        'any_sensed': bool(sensed),
        'countries': records,
        'transit_not_dependent': list(TRANSIT_NOT_DEPENDENT),
        'unverified_entries': unverified,
        'draft_warning': (
            f'{len(unverified)} dependence entries are UNVERIFIED Claude '
            f'research pending Rachel\'s correction: {", ".join(unverified)}. '
            f'They are carried and flagged rather than treated as settled.'
        ) if unverified else None,
        'disclaimer': (
            'Dependence is a MULTIPLIER on corridor state, never a signal on '
            'its own. A country is reported only when the corridors it depends '
            'on are actually sensed. Structural exposure is constant and says '
            'nothing about today.'
        ),
    }


def register_corridor_dependence_endpoints(app):
    from flask import jsonify, request

    @app.route('/api/corridor-dependence', methods=['GET', 'OPTIONS'])
    def corridor_dependence_all():
        if request.method == 'OPTIONS':
            return ('', 204)
        try:
            return jsonify(read_all()), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/corridor-dependence/<country_id>', methods=['GET', 'OPTIONS'])
    def corridor_dependence_one(country_id):
        if request.method == 'OPTIONS':
            return ('', 204)
        rec = read_country((country_id or '').strip().lower())
        if not rec:
            return jsonify({'success': False, 'error': f"no dependence profile for '{country_id}'",
                            'known': sorted(CORRIDOR_DEPENDENCE)}), 404
        return jsonify(rec), 200

    print('[CorridorDep] endpoints registered (/api/corridor-dependence)')


# ======================================================================
# SELF-TEST
# ======================================================================
if __name__ == '__main__':
    print(f'Corridor Dependence v{__version__} -- self-test\n')
    ALL_UNKNOWN = {c: {'state': 'unknown', 'sensed': False}
                   for c in ('black_sea_grain_corridor', 'kerem_shalom')}

    print('TEST 1 -- unsensed corridors => unsensed countries')
    p = read_all(ALL_UNKNOWN)
    assert p['any_sensed'] is False and p['sensed_count'] == 0
    for r in p['countries']:
        assert r['intensity'] is None and 'NOT SENSED' in r['read']
    print(f"  {p['country_count']} countries, 0 sensed, none claim an intensity\n")

    print('TEST 2 -- THE MULTIPLIER RULE: dependence alone never emits')
    leb = read_country('lebanon', ALL_UNKNOWN)
    assert leb['intensity'] is None, 'structural dependence must not become a reading'
    assert 'multiplier, not' in leb['read']
    print('  Lebanon at 85% dependence + unknown corridor -> intensity None\n')

    print('TEST 3 -- share scales severity into bands')
    imp = {'black_sea_grain_corridor': {'state': 'impaired', 'sensed': True},
           'kerem_shalom': {'state': 'open', 'sensed': True}}
    leb = read_country('lebanon', imp)   # share .85 -> full severity
    syr = read_country('syria', imp)     # share .20 -> one band down
    assert leb['intensity'] == 2, leb['intensity']
    assert syr['intensity'] == 1, syr['intensity']
    print(f"  impaired corridor: Lebanon(.85)->{leb['intensity']}  "
          f"Syria(.20)->{syr['intensity']}  (same shock, different exposure)\n")

    print('TEST 4 -- TWO HOPS: the worst hop binds, and an unread hop blinds')
    # sea open, crossing blocked -> Gaza still reads the crossing
    g = read_country('gaza', {'black_sea_grain_corridor': {'state': 'open', 'sensed': True},
                              'kerem_shalom': {'state': 'blocked', 'sensed': True}})
    assert g['intensity'] == 3, g['intensity']
    print(f"  sea open + crossing blocked -> Gaza {g['intensity']} (crossing binds)")
    # sea blocked, crossing open -> still reads
    g2 = read_country('gaza', {'black_sea_grain_corridor': {'state': 'blocked', 'sensed': True},
                               'kerem_shalom': {'state': 'open', 'sensed': True}})
    assert g2['intensity'] == 3, g2['intensity']
    print(f"  sea blocked + crossing open -> Gaza {g2['intensity']} (origin binds)")
    # one hop unread -> the whole chain is unread
    g3 = read_country('gaza', {'black_sea_grain_corridor': {'state': 'impaired', 'sensed': True},
                               'kerem_shalom': {'state': 'unknown', 'sensed': False}})
    assert g3['sensed'] is False and g3['intensity'] is None, g3['intensity']
    assert g3['has_unread_hop'] is True
    print('  impaired sea + UNREAD crossing -> None  (a chain is only as read '
          'as its blindest link)\n')

    print('TEST 5 -- open corridor reads 0, not None')
    op = {'black_sea_grain_corridor': {'state': 'open', 'sensed': True},
          'kerem_shalom': {'state': 'open', 'sensed': True}}
    leb = read_country('lebanon', op)
    assert leb['intensity'] == 0 and leb['sensed'] is True
    print('  open -> intensity 0 sensed=True  (covered and quiet != unread)\n')

    print('TEST 6 -- transit states are not dependents')
    assert 'poland' not in CORRIDOR_DEPENDENCE
    assert 'poland' in TRANSIT_NOT_DEPENDENT
    print('  Poland carries grain, does not eat it -- excluded by design\n')

    print('TEST 7 -- unverified research is flagged, not laundered')
    p = read_all(ALL_UNKNOWN)
    assert p['draft_warning'] and 'UNVERIFIED' in p['draft_warning']
    assert set(p['unverified_entries']) == {'syria.wheat', 'gaza.wheat', 'turkey.wheat'}
    for r in p['countries']:
        for c in r['commodities']:
            if not c['verified']:
                assert c['source'] and c['as_of'], 'unverified needs provenance'
    print(f"  {len(p['unverified_entries'])} draft entries flagged with source + "
          f"as_of: {', '.join(p['unverified_entries'])}\n")

    print('TEST 8 -- Syria carries the compositional finding, not just a share')
    syr = read_country('syria', ALL_UNKNOWN)
    n = syr['commodities'][0]['note']
    assert 'self-sufficiency' in n and 'soft' in n and '570kt' in n
    assert syr['commodities'][0]['needs_rachel']
    print('  aggregate-vs-composition caveat preserved + question for Rachel\n')

    print('ALL CORRIDOR DEPENDENCE TESTS PASSED')
