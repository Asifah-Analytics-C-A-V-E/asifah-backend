"""
Libya Signal Interpreter -- v1.0.0 -- July 17, 2026
Asifah Analytics -- ME/North Africa backend

THE ANALYTICAL LAYER for rhetoric_tracker_libya.py. This file was imported by the
tracker from day one but never existed -- so Libya has been running with no
So-What, no Red Lines, no historical matching, and (critically) no canonical
top_signals[], which means Libya has been INVISIBLE to the regional BLUF and the
GPI. This closes that gap.

Libya is the platform's DUAL-WHEEL showcase: the same civil war read from two
external-patron wheels at once --
  * RUSSIA wheel: Africa Corps at al-Khadim/al-Jufra, the Tobruk naval-base
    pursuit ("Tartus Plan-B"), Haftar/LNA backing.
  * TURKEY wheel: GNU backing, Bayraktar drones, the maritime MoU, al-Watiya.
The interpreter reads BOTH and frames the contest as: is Libya's frozen
partition being reactivated, and by which patron's move?

Contract (exactly what rhetoric_tracker_libya.py consumes):
  interpret_signals(result) -> {
      'so_what': {... incl. 'africacorps_naval_gap', 'russia_directing',
                  and the back-compat aliases 'laf_enforcement_gap',
                  'iran_directing' the tracker's print line reads},
      'red_lines': {'triggered':[...], 'breached_count', 'approaching_count',
                    'highest_severity'},
      'green_lines': {...},
      'diplomatic_track': {...},
      'historical_matches': [ {similarity, ...}, ... ],   # tracker reads [0]['similarity']
      ...
  }
  build_top_signals(result) -> canonical top_signals[] for BLUF + GPI.

Estimative voice, precedent-anchored, absence-honest. Convergence, not prediction.
"""

from datetime import datetime, timezone

INTERPRETER_VERSION = '1.0.0'

LIBYA_FLAG = '\U0001f1f1\U0001f1fe'  # 🇱🇾

DISCLAIMER = (
    'This is a CONVERGENCE indicator, NOT a probability of action. It reads '
    'Libya as a dual-patron contest -- Russia (Africa Corps / east) vs Turkey '
    '(GNU / west) -- and reports where the frozen partition shows reactivation '
    'pressure, never that conflict will resume. The reader completes the inference.'
)

_ESC_LABELS = {
    0: 'Monitoring', 1: 'Routine', 2: 'Elevated Rhetoric',
    3: 'Heightened Posture', 4: 'Active Signaling', 5: 'Active Conflict',
}


# ============================================================
# RED LINES -- the dual-wheel breaches
# ============================================================

RED_LINES = [
    {
        'id':       'africacorps_naval_base',
        'label':    'Russia Naval-Base Activation at Tobruk/Benghazi',
        'detail':   'Africa Corps secures or operationalizes a Red Sea/Mediterranean '
                    'naval facility in eastern Libya -- the "Tartus Plan-B" after Syria. '
                    'A permanent Russian warm-water foothold on NATO\'s southern flank.',
        'severity': 3,
        'color':    '#b91c1c',
        'icon':     '\u2693',
        'category': 'russia_wheel',
        'source':   'Russia has pursued Tobruk/Benghazi port access since the Tartus '
                    'uncertainty; base activation is the strategic step-change.',
        'triggers_breached': [
            'russia tobruk naval base', 'russia benghazi naval base',
            'russian warships libya base', 'africa corps naval libya',
            'russia libya permanent base', 'russian naval facility libya',
        ],
        'triggers_approaching': [
            'russia libya port talks', 'russia tobruk port', 'russia libya naval',
            'russian ships benghazi', 'russia libya logistics base',
        ],
    },
    {
        'id':       'civil_war_reactivation',
        'label':    'Civil-War Reactivation / Major Offensive',
        'detail':   'LNA or GNU-aligned forces launch a major offensive across the '
                    'Sirte-Jufra line or toward the rival capital -- ending the frozen '
                    'partition that has held (uneasily) since the 2020 ceasefire.',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '\u2694\ufe0f',
        'category': 'kinetic',
        'source':   'The 2019-20 LNA assault on Tripoli is the precedent; the '
                    'Sirte-Jufra line is Egypt\'s stated red line.',
        'triggers_breached': [
            'lna offensive tripoli', 'lna advance west', 'libya major offensive',
            'haftar attacks tripoli', 'libya war resumes', 'sirte offensive',
            'libya frontline collapse',
        ],
        'triggers_approaching': [
            'lna mobilization', 'libya troop buildup', 'libya military escalation',
            'sirte jufra tension', 'libya forces advance',
        ],
    },
    {
        'id':       'patron_direct_friction',
        'label':    'Turkey-Russia Direct Friction in Theater',
        'detail':   'Turkish and Russian forces (or their proxies) come into direct '
                    'confrontation in Libya -- the dual-wheel collision the frozen '
                    'partition has so far managed to avoid.',
        'severity': 3,
        'color':    '#ea580c',
        'icon':     '\U0001f525',
        'category': 'dual_wheel',
        'source':   'Turkey (west) and Russia (east) have deconflicted since 2020; '
                    'direct friction would break that management.',
        'triggers_breached': [
            'turkey russia clash libya', 'turkish russian forces libya confrontation',
            'turkey africa corps clash', 'libya proxy war escalation turkey russia',
        ],
        'triggers_approaching': [
            'turkey russia libya tension', 'turkey warns russia libya',
            'turkey russia deconfliction libya', 'ankara moscow libya friction',
        ],
    },
    {
        'id':       'oil_blockade',
        'label':    'Oil Blockade / NOC Seizure',
        'detail':   'Eastern forces blockade oil terminals or seize NOC revenue -- the '
                    'economic weapon that has repeatedly frozen Libyan politics and '
                    'sent shocks into global crude.',
        'severity': 2,
        'color':    '#f59e0b',
        'icon':     '\U0001f6e2\ufe0f',
        'category': 'economic',
        'source':   'The 2020 and 2022 blockades cut ~1M bpd; oil is the recurring '
                    'coercive lever in Libyan politics.',
        'triggers_breached': [
            'libya oil blockade', 'libya oil terminals closed', 'noc seizure',
            'libya oil shutdown', 'libya crude blockade', 'sharara field shut',
        ],
        'triggers_approaching': [
            'libya oil threat', 'libya noc dispute', 'libya oil revenue standoff',
            'libya oil field tension',
        ],
    },
    {
        'id':       'migration_weaponization',
        'label':    'Migration Weaponization',
        'detail':   'A Libyan faction (or patron) deliberately opens the central-Med '
                    'route as leverage against the EU/Italy -- the coercive use of the '
                    'migration valve.',
        'severity': 2,
        'color':    '#7c3aed',
        'icon':     '\U0001f6df',
        'category': 'migration',
        'source':   'Central-Med departures are a standing EU pressure point; '
                    'deliberate opening has precedent as political leverage.',
        'triggers_breached': [
            'libya opens migration route', 'libya migration surge deliberate',
            'libya weaponize migration', 'libya coast guard stands down',
        ],
        'triggers_approaching': [
            'libya migration threat', 'libya eu migration standoff',
            'central mediterranean surge', 'libya migration leverage',
        ],
    },
    {
        'id':       'haftar_succession_crisis',
        'label':    'Haftar Succession Crisis',
        'detail':   'A contested succession within the Haftar family/LNA -- Khalifa '
                    'Haftar is aging, and his sons (Saddam, Khaled) are positioning. '
                    'An LNA fracture would reshuffle the whole eastern-patron board.',
        'severity': 2,
        'color':    '#a16207',
        'icon':     '\U0001f451',
        'category': 'succession',
        'source':   'Authoritarian-succession instability precedent; an LNA fracture '
                    'reopens the eastern question Russia and Egypt both depend on.',
        'triggers_breached': [
            'haftar succession crisis', 'haftar family split', 'lna fracture',
            'saddam haftar power struggle', 'haftar dies', 'haftar incapacitated',
        ],
        'triggers_approaching': [
            'haftar succession', 'haftar health', 'saddam haftar positioning',
            'haftar sons rivalry', 'haftar aging',
        ],
    },
]


# ============================================================
# GREEN LINES -- the off-ramp (UN process / unification)
# ============================================================

GREEN_LINES = [
    {
        'id':       'unified_elections',
        'label':    'Unified Elections / Roadmap Progress',
        'detail':   'Concrete movement toward national elections or a unified '
                    'government -- the UN-brokered path out of partition.',
        'triggers_active': [
            'libya elections date', 'libya unified government', 'libya election roadmap agreed',
            'libya political agreement', 'libya constitutional basis agreed',
            '5+5 committee agreement', 'libya unified cabinet',
        ],
        'triggers_signaled': [
            'libya elections', 'libya political dialogue', 'libya roadmap',
            'libya unification talks', 'unsmil progress',
        ],
    },
    {
        'id':       'ceasefire_holding',
        'label':    'Ceasefire Holding / 5+5 Active',
        'detail':   'The 2020 ceasefire and the 5+5 Joint Military Commission remain '
                    'functional -- mercenary-withdrawal talks, deconfliction holding.',
        'triggers_active': [
            'libya ceasefire holds', '5+5 joint military commission meets',
            'libya mercenary withdrawal', 'libya deconfliction agreement',
            'foreign forces withdrawal libya',
        ],
        'triggers_signaled': [
            'libya ceasefire', '5+5 committee', 'libya truce', 'libya calm',
        ],
    },
    {
        'id':       'foreign_forces_drawdown',
        'label':    'Foreign Forces / Mercenary Drawdown',
        'detail':   'Actual withdrawal of foreign forces -- Africa Corps, Turkish '
                    'contingents, Syrian mercenaries. Every drawdown lowers both '
                    'patrons\' leverage.',
        'triggers_active': [
            'wagner libya withdrawal', 'africa corps leaves libya', 'russia withdraws libya',
            'turkey withdraws libya', 'syrian mercenaries leave libya',
            'foreign fighters exit libya',
        ],
        'triggers_signaled': [
            'libya foreign forces talks', 'libya mercenary drawdown',
            'libya withdrawal discussion',
        ],
    },
]


# ============================================================
# HISTORICAL PRECEDENT LIBRARY
# ============================================================

HISTORICAL_PRECEDENTS = [
    {
        'id':          'tripoli_offensive_2019',
        'label':       'LNA Tripoli Offensive (April 2019)',
        'description': 'Haftar launched a surprise assault on Tripoli, ending the '
                       'post-2015 political process and triggering 14 months of war.',
        'source':      'Contemporaneous reporting; UN Panel of Experts',
        'outcome':     'kinetic_action',
        'window_hours': 72,
        'confidence':  'high',
        'signals': {
            'lna_min': 4, 'russia_coordination': True, 'diplomatic_collapse': True,
        },
    },
    {
        'id':          'sirte_jufra_standoff_2020',
        'label':       'Sirte-Jufra Standoff (Summer 2020)',
        'description': 'After the LNA was pushed back from Tripoli, Turkey-backed GNU '
                       'forces advanced east; Egypt declared Sirte-Jufra a red line and '
                       'Russia reinforced. Direct Turkey-Russia-Egypt friction, frozen '
                       'by deconfliction into the current partition.',
        'source':      'Contemporaneous reporting',
        'outcome':     'averted_frozen',
        'window_hours': 168,
        'confidence':  'high',
        'signals': {
            'lna_min': 3, 'turkey_min': 3, 'russia_coordination': True,
            'egypt_uae_min': 3,
        },
    },
    {
        'id':          'oil_blockade_2022',
        'label':       'Oil Blockade (2022)',
        'description': 'Eastern forces blockaded oil terminals amid the Bashagha-Dbeibah '
                       'dual-PM crisis, cutting ~1M bpd and pressuring the west '
                       'economically without a kinetic offensive.',
        'source':      'NOC statements; contemporaneous reporting',
        'outcome':     'economic_coercion',
        'window_hours': 336,
        'confidence':  'medium',
        'signals': {
            'lna_min': 2, 'oil_blockade': True, 'diplomatic_collapse': True,
        },
    },
    {
        'id':          'ceasefire_2020',
        'label':       'Libya Ceasefire (October 2020)',
        'description': 'The 5+5 JMC agreed a nationwide ceasefire that froze the front '
                       'and created the current partition -- the off-ramp precedent.',
        'source':      'UNSMIL',
        'outcome':     'diplomatic_pivot',
        'window_hours': 240,
        'confidence':  'high',
        'signals': {
            'unsmil_min': 3, 'diplomatic_collapse': False,
        },
    },
]


# ============================================================
# KEYWORD MATCHING
# ============================================================

def _corpus_blob(scan_data):
    parts = []
    actors = scan_data.get('actors', {})
    for a in actors.values():
        for art in (a.get('top_articles') or [])[:6]:
            parts.append((art.get('title') or '').lower())
            parts.append((art.get('description') or '').lower())
    for ct in (scan_data.get('conditional_threats') or []):
        if isinstance(ct, dict) and ct.get('phrase'):
            parts.append(ct['phrase'].lower())
    for ca in (scan_data.get('coordination_alerts') or []):
        if isinstance(ca, dict) and ca.get('message'):
            parts.append(ca['message'].lower())
    return ' '.join(parts)


def _count_hits(blob, keywords):
    return sum(1 for kw in keywords if kw.lower() in blob)


def _actor_level(scan_data, actor_id):
    a = scan_data.get('actors', {}).get(actor_id, {})
    return a.get('max_escalation_level', a.get('escalation_level', 0)) or 0


# ============================================================
# RED / GREEN SCORING
# ============================================================

def _score_red_lines(scan_data):
    blob = _corpus_blob(scan_data)
    out = []
    for rl in RED_LINES:
        breached = _count_hits(blob, rl.get('triggers_breached', []))
        approaching = _count_hits(blob, rl.get('triggers_approaching', []))
        if breached >= 2:
            status = 'BREACHED'
        elif breached >= 1 or approaching >= 3:
            status = 'APPROACHING'
        elif approaching >= 1:
            status = 'WATCHING'
        else:
            status = 'INACTIVE'
        out.append({
            'id': rl['id'], 'label': rl['label'], 'detail': rl['detail'],
            'severity': rl['severity'], 'color': rl['color'], 'icon': rl['icon'],
            'category': rl['category'], 'source': rl['source'],
            'status': status, 'breached_hits': breached, 'approaching_hits': approaching,
        })
    return out


def _score_green_lines(scan_data):
    blob = _corpus_blob(scan_data)
    out = []
    for gl in GREEN_LINES:
        active = _count_hits(blob, gl.get('triggers_active', []))
        signaled = _count_hits(blob, gl.get('triggers_signaled', []))
        status = 'ACTIVE' if active >= 1 else ('SIGNALED' if signaled >= 1 else 'DORMANT')
        out.append({
            'id': gl['id'], 'label': gl['label'], 'detail': gl['detail'],
            'status': status, 'active_hits': active, 'signaled_hits': signaled,
        })
    return out


def _score_diplomatic_track(scan_data, green_lines):
    """Libya's diplomatic posture already computed in the tracker; surface it +
    layer the green-line reads. Active UN process REDUCES threat."""
    ceasefire_level = scan_data.get('ceasefire_level', 0)
    active = scan_data.get('diplomatic_track_active', False)
    active_gl = [g for g in green_lines if g['status'] == 'ACTIVE']
    label = scan_data.get('diplomatic_label_detailed', 'Quiet')
    score = min(100, ceasefire_level * 20 + len(active_gl) * 10)
    if active_gl and ceasefire_level >= 2:
        scenario = 'UN process active -- off-ramp open'
    elif active:
        scenario = 'Diplomatic push underway'
    else:
        scenario = 'No active off-ramp'
    return {
        'score': score, 'scenario': scenario, 'label': label,
        'ceasefire_level': ceasefire_level, 'active': active,
        'active_green_lines': [g['id'] for g in active_gl],
        'modifier': scan_data.get('diplomatic_modifier', 0),
    }


# ============================================================
# HISTORICAL MATCHING
# ============================================================

def _match_historical(scan_data):
    blob = _corpus_blob(scan_data)
    lna     = _actor_level(scan_data, 'lna_hor')
    gnu     = _actor_level(scan_data, 'gnu_tripoli')
    russia  = _actor_level(scan_data, 'russia_africacorps')
    turkey  = _actor_level(scan_data, 'turkey_libya')
    egypt   = _actor_level(scan_data, 'egypt_uae_libya')
    unsmil  = _actor_level(scan_data, 'unsmil')

    russia_coord = russia >= 2
    oil_blockade = ('libya oil blockade' in blob or 'oil terminals closed' in blob
                    or 'noc seizure' in blob)
    diplomatic_collapse = unsmil < 2 and (lna >= 3 or gnu >= 3)

    matches = []
    for p in HISTORICAL_PRECEDENTS:
        sigs = p['signals']
        score = 0
        max_score = 0
        matched, missed = [], []

        def check(cond, label, weight=1):
            nonlocal score, max_score
            max_score += weight
            if cond:
                score += weight
                matched.append(label)
            else:
                missed.append(label)

        if 'lna_min' in sigs:
            check(lna >= sigs['lna_min'], f'LNA L{lna} >= L{sigs["lna_min"]}', 3)
        if 'turkey_min' in sigs:
            check(turkey >= sigs['turkey_min'], f'Turkey L{turkey} >= L{sigs["turkey_min"]}', 2)
        if 'egypt_uae_min' in sigs:
            check(egypt >= sigs['egypt_uae_min'], f'Egypt/UAE L{egypt} >= L{sigs["egypt_uae_min"]}', 1)
        if 'unsmil_min' in sigs:
            check(unsmil >= sigs['unsmil_min'], f'UNSMIL L{unsmil} >= L{sigs["unsmil_min"]}', 2)
        if 'russia_coordination' in sigs:
            check(russia_coord == sigs['russia_coordination'], 'Russia coordination', 2)
        if 'oil_blockade' in sigs:
            check(oil_blockade == sigs['oil_blockade'], 'Oil blockade active', 2)
        if 'diplomatic_collapse' in sigs:
            check(diplomatic_collapse == sigs['diplomatic_collapse'],
                  f'Diplomatic collapse: {diplomatic_collapse}', 1)

        if max_score == 0:
            continue
        similarity = round((score / max_score) * 100)
        if similarity >= 50:
            matches.append({
                'id': p['id'], 'label': p['label'], 'description': p['description'],
                'source': p['source'], 'outcome': p['outcome'],
                'window_hours': p['window_hours'], 'confidence': p['confidence'],
                'similarity': similarity, 'matched_signals': matched,
                'missed_signals': missed,
            })
    matches.sort(key=lambda x: x['similarity'], reverse=True)
    return matches[:3]


# ============================================================
# SO-WHAT
# ============================================================

def _build_so_what(scan_data, red_lines, historical, green_lines, diplomatic):
    breached = [r for r in red_lines if r['status'] == 'BREACHED']
    approaching = [r for r in red_lines if r['status'] == 'APPROACHING']
    active_gl = [g for g in green_lines if g['status'] == 'ACTIVE']

    lna    = _actor_level(scan_data, 'lna_hor')
    gnu    = _actor_level(scan_data, 'gnu_tripoli')
    russia = _actor_level(scan_data, 'russia_africacorps')
    turkey = _actor_level(scan_data, 'turkey_libya')
    unsmil = _actor_level(scan_data, 'unsmil')

    # ── Dual-wheel reads ──
    # Africa Corps naval gap: Russia pursuing the base while the off-ramp is quiet
    naval_rl = next((r for r in red_lines if r['id'] == 'africacorps_naval_base'), {})
    africacorps_naval_gap = naval_rl.get('status') in ('BREACHED', 'APPROACHING')
    # Russia "directing" the eastern board (patron escalation via LNA)
    russia_directing = russia >= 2 and lna >= 3
    # Turkey projecting (west)
    turkey_projecting = turkey >= 2 and gnu >= 3
    # dual-wheel collision
    friction_rl = next((r for r in red_lines if r['id'] == 'patron_direct_friction'), {})
    dual_wheel_friction = friction_rl.get('status') in ('BREACHED', 'APPROACHING')

    if breached:
        scenario = 'Partition reactivation breaching'
    elif approaching:
        scenario = 'Partition pressure building'
    elif active_gl:
        scenario = 'Off-ramp active'
    else:
        scenario = 'Frozen partition holding'

    assessment = diplomatic['scenario'] + '. '
    if africacorps_naval_gap:
        assessment += ('Russia\'s naval-base pursuit in the east is consistent with the '
                       'Tartus Plan-B pattern -- a permanent Mediterranean foothold on '
                       'NATO\'s southern flank. ')
    if dual_wheel_friction:
        assessment += ('Turkey-Russia direct friction signals the dual-patron '
                       'deconfliction that has frozen the partition may be under strain. ')
    if russia_directing and turkey_projecting:
        assessment += ('Both patrons active simultaneously -- the compound pattern that '
                       'historically precedes either a Sirte-Jufra standoff or a '
                       'renewed offensive. ')
    if breached:
        assessment += 'Breached: ' + ', '.join(r['label'] for r in breached) + '. '
    if active_gl:
        assessment += 'Off-ramp active: ' + ', '.join(g['label'] for g in active_gl) + '. '
    assessment += ('The dual-wheel question: is Libya\'s frozen partition being '
                   'reactivated, and by which patron\'s move?')

    return {
        'scenario': scenario,
        'assessment': assessment,
        # ── dual-wheel flags ──
        'africacorps_naval_gap': africacorps_naval_gap,
        'russia_directing':      russia_directing,
        'turkey_projecting':     turkey_projecting,
        'dual_wheel_friction':   dual_wheel_friction,
        # ── back-compat aliases (the tracker's print line reads these two;
        #    Libya has no LAF/Iran, so map to the nearest dual-wheel meaning) ──
        'laf_enforcement_gap':   diplomatic['scenario'] == 'No active off-ramp',
        'iran_directing':        russia_directing,   # alias: patron-directing-east
        'breached_labels':       [r['label'] for r in breached],
        'watch_list': [
            'Russia: al-Khadim/al-Jufra activity, Tobruk/Benghazi naval-base talks',
            'Kinetic: Sirte-Jufra line, LNA mobilization toward the west',
            'Dual-wheel: Turkey-Russia deconfliction strain',
            'Economic: oil-terminal blockade, NOC revenue standoff',
            'Off-ramp: 5+5 JMC activity, election-roadmap progress, foreign-forces drawdown',
        ],
    }


# ============================================================
# MAIN ENTRY
# ============================================================

def interpret_signals(scan_data):
    try:
        red_lines   = _score_red_lines(scan_data)
        green_lines = _score_green_lines(scan_data)
        diplomatic  = _score_diplomatic_track(scan_data, green_lines)
        historical  = _match_historical(scan_data)
        so_what     = _build_so_what(scan_data, red_lines, historical,
                                     green_lines, diplomatic)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']
        active_gl   = [g for g in green_lines if g['status'] == 'ACTIVE']

        return {
            'so_what':      so_what,
            'red_lines': {
                'triggered':         red_lines,
                'breached_count':    len(breached),
                'approaching_count': len(approaching),
                'highest_severity':  max((r['severity'] for r in red_lines), default=0),
            },
            'green_lines': {
                'triggered':      green_lines,
                'active_count':   len(active_gl),
                'signaled_count': len(green_lines) - len(active_gl),
                'diplomatic_score': diplomatic['score'],
            },
            'diplomatic_track':   diplomatic,
            'historical_matches': historical,
            'interpreter_version': INTERPRETER_VERSION,
            'interpreted_at':     datetime.now(timezone.utc).isoformat(),
            'disclaimer':         DISCLAIMER,
        }
    except Exception as e:
        print(f'[Libya Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what': {'scenario': 'Interpreter error', 'assessment': str(e)[:200],
                        'africacorps_naval_gap': False, 'russia_directing': False,
                        'laf_enforcement_gap': False, 'iran_directing': False},
            'red_lines':   {'triggered': [], 'breached_count': 0,
                            'approaching_count': 0, 'highest_severity': 0},
            'green_lines': {'triggered': [], 'active_count': 0,
                            'signaled_count': 0, 'diplomatic_score': 0},
            'diplomatic_track':   {'score': 0, 'scenario': 'Unknown'},
            'historical_matches': [],
            'interpreter_version': INTERPRETER_VERSION,
            'error':              str(e)[:200],
            'disclaimer':         DISCLAIMER,
        }


# ============================================================
# CANONICAL top_signals[]  (BLUF + GPI consumption)
# ============================================================

def build_top_signals(scan_data):
    """Convert Libya scan_data into canonical top_signals[] for the regional BLUF
    and the GPI. Same schema as Lebanon/Ukraine. Always returns a list."""
    signals = []
    interp   = scan_data.get('interpretation') or {}
    so_what  = interp.get('so_what') or {}
    rl_block = interp.get('red_lines') or {}
    gl_block = interp.get('green_lines') or {}
    dipl     = interp.get('diplomatic_track') or {}
    triggered_rls = rl_block.get('triggered') or []
    triggered_gls = gl_block.get('triggered') or []

    theatre_level = int(scan_data.get('theatre_escalation_level',
                        scan_data.get('theatre_level', 0)) or 0)
    theatre_score = int(scan_data.get('rhetoric_score',
                        scan_data.get('theatre_score', 0)) or 0)

    russia = _actor_level(scan_data, 'russia_africacorps')
    turkey = _actor_level(scan_data, 'turkey_libya')
    lna    = _actor_level(scan_data, 'lna_hor')

    # 1) breached / approaching red lines -> top priority
    for r in triggered_rls:
        if r['status'] == 'BREACHED':
            pri, lvl = 14, 5
        elif r['status'] == 'APPROACHING':
            pri, lvl = 10, 4
        else:
            continue
        ptype = ('economic' if r['category'] in ('economic', 'migration')
                 else 'diplomatic' if r['category'] == 'dual_wheel'
                 else 'kinetic')
        signals.append({
            'priority': pri + r['severity'], 'category': 'red_line_breached',
            'theatre': 'libya', 'level': lvl, 'icon': r['icon'], 'color': r['color'],
            'short_text': f"{r['label']} -- {r['status']}"[:80],
            'long_text': r['detail'][:200], 'pressure_type': ptype,
        })

    # 2) Russia dual-wheel signal (the Africa Corps read)
    if so_what.get('africacorps_naval_gap') or russia >= 3:
        signals.append({
            'priority': 12, 'category': 'crosstheater_russia_libya',
            'theatre': 'libya', 'level': max(3, russia), 'icon': '\u2693',
            'color': '#b91c1c',
            'short_text': 'Russia/Africa Corps active in eastern Libya'[:80],
            'long_text': ('Africa Corps footprint + naval-base pursuit -- Libya as the '
                          'Tartus Plan-B on NATO\'s southern flank.')[:200],
            'pressure_type': 'kinetic',
        })

    # 3) Turkey projection signal
    if turkey >= 3:
        signals.append({
            'priority': 9, 'category': 'crosstheater_turkey_libya',
            'theatre': 'libya', 'level': turkey, 'icon': '\U0001f319',
            'color': '#ea580c',
            'short_text': 'Turkey projecting in western Libya'[:80],
            'long_text': ('GNU backing, Bayraktar drones, maritime MoU -- the western '
                          'half of the dual-wheel contest.')[:200],
            'pressure_type': 'kinetic',
        })

    # 4) composite theatre high
    if theatre_level >= 4:
        signals.append({
            'priority': 11, 'category': 'theatre_high', 'theatre': 'libya',
            'level': theatre_level, 'icon': '\U0001f1f1\U0001f1fe', 'color': '#dc2626',
            'short_text': f'Libya theatre elevated (L{theatre_level})'[:80],
            'long_text': (so_what.get('scenario', '') or 'Elevated Libya activity')[:200],
            'pressure_type': 'kinetic',
        })

    # 5) diplomatic / off-ramp active
    if dipl.get('active') or dipl.get('scenario', '').startswith('UN process'):
        active_gls = [g for g in triggered_gls if g['status'] == 'ACTIVE']
        signals.append({
            'priority': 6, 'category': 'diplomatic_active', 'theatre': 'libya',
            'level': min(3, dipl.get('ceasefire_level', 0)), 'icon': '\u262e\ufe0f',
            'color': '#0ea5e9',
            'short_text': (dipl.get('label') or 'Diplomatic track active')[:80],
            'long_text': (dipl.get('scenario', '')
                          + (' | ' + ', '.join(g['label'] for g in active_gls) if active_gls else ''))[:200],
            'pressure_type': 'diplomatic',
        })

    signals.sort(key=lambda s: s['priority'], reverse=True)
    return signals
