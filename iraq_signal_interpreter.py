"""
iraq_signal_interpreter.py
Asifah Analytics -- ME Backend Module
v1.0.0

Signal interpretation engine for the Iraq Rhetoric Tracker.

Iraq's analytical frame is the most complex in the ME theatre --
it is a FIVE-WAY tension that operates simultaneously:

  1. Will Iran-backed Iraqi Shia (PMF/Kata'ib) side with Iran
     in the current conflict and attack US forces/facilities?
  2. Is Iraq fracturing -- PMF pulling toward Iran, Sadr doing
     his own thing, KRG hedging, Sudani holding the middle?
  3. What does the Kurdish triple vector look like:
     Erbil base attacks + Baghdad-KRG tensions + Syria/Turkey
     Kurdish coordination (including Trump arms cache claim)?
  4. Are US interests under direct threat -- Embassy/Green Zone
     vs base attacks are distinct severity levels?
  5. Is ISIS exploiting the governance distraction to reconstitute
     in primary territory (Sinjar/Nineveh) vs Baghdad?

Key contextual factors:
  - PMF is NOT monolithic: Kata'ib Hezbollah is IRGC-directed;
    other factions have more autonomy from Tehran
  - Sadr is the wildcard: anti-Iran AND anti-US AND anti-PMF --
    when he goes silent, historical pattern is mobilization follows
  - Sudani government = de-escalation actor by default;
    his statements provide diplomatic cover, positive signal
  - Trump announced Iran ceasefire April 7, 2026 -- PMF calculus
    shifts if Iran stands down, but Kata'ib may act independently
  - KRG arms cache: Trump claimed Kurds received US arms meant
    for Iran but kept them -- watch for Kurdish leverage signals
  - ISIS in Baghdad = active conflict signal (higher severity)
    ISIS in Sinjar/Nineveh/desert = resurgence watch

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS
# ============================================================
RED_LINES = [
    # ── Category A: US Facilities / Personnel ────────────────
    {
        'id':       'us_embassy_attack',
        'label':    'Attack on US Embassy / Diplomatic Facility',
        'detail':   'Direct attack on US Embassy Baghdad, Consulate Erbil, or diplomatic personnel',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🏛️',
        'category': 'us_facility_trigger',
        'source':   'US policy red line -- Embassy attacks trigger automatic US military response; '
                    'seen in Jan 2020 Green Zone storming and 2024 Iran proxy campaign',
    },
    {
        'id':       'us_base_direct_attack',
        'label':    'Direct Attack on US Military Base in Iraq',
        'detail':   'Rocket/drone attack on Al Asad, Ain al-Assad, Erbil, or Baghdad base with US casualties',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '⚔️',
        'category': 'us_facility_trigger',
        'source':   'CENTCOM doctrine -- base attacks with casualties trigger Operation Inherent Resolve response; '
                    'Kata\'ib Hezbollah responsible for majority of 2023-2024 base attack campaign',
    },
    # ── Category B: PMF / Proxy activation ───────────────────
    {
        'id':       'kataib_activation',
        'label':    "Kata'ib Hezbollah Full Activation",
        'detail':   "Kata'ib Hezbollah announces offensive operations -- most Iran-directed PMF faction",
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🔴',
        'category': 'pmf_trigger',
        'source':   'ISW; CENTCOM -- Kata\'ib is the primary IRGC Quds Force-directed faction in Iraq; '
                    'their activation signals direct Iranian operational command',
    },
    {
        'id':       'pmf_iran_coordination',
        'label':    'PMF + Iran Coordinated Escalation',
        'detail':   'PMF Hashd and Iran signals coordinated within short window -- proxy axis activation',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🔗',
        'category': 'pmf_trigger',
        'source':   'Pattern analysis -- coordinated PMF+Iran statements within 12h historically '
                    'precede kinetic action by PMF factions against US targets',
    },
    {
        'id':       'green_zone_breach',
        'label':    'Green Zone Breach / Baghdad Protest Escalation',
        'detail':   'Armed groups breach Green Zone or mass protest surrounds diplomatic compound',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🚧',
        'category': 'us_facility_trigger',
        'source':   'Historical pattern -- 2020 Green Zone storming, 2022 Sadrist breach; '
                    'Green Zone breaches signal breakdown of Iraqi state authority over armed factions',
    },
    # ── Category C: Kurdish triggers ─────────────────────────
    {
        'id':       'erbil_base_attack',
        'label':    'Erbil / KRG Base Attack',
        'detail':   'Iranian missile/drone attack on Erbil or KRG territory targeting US/Israeli assets',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🏔️',
        'category': 'kurdish_trigger',
        'source':   'ISW -- Iran has repeatedly struck Erbil; Jan 2024 IRGC strike on "Israeli intelligence" '
                    'in Erbil killed civilians; Erbil is forward US logistics hub',
    },
    {
        'id':       'krg_baghdad_fracture',
        'label':    'KRG-Baghdad Armed Confrontation',
        'detail':   'Peshmerga-PMF clash in Kirkuk, Sinjar, or disputed territories',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🗺️',
        'category': 'kurdish_trigger',
        'source':   'Disputed territories -- Kirkuk oil revenues, Sinjar corridor, Article 140; '
                    'KRG-PMF armed standoffs historically resolve without full conflict but '
                    'distract Iraqi state from Iran pressure management',
    },
    {
        'id':       'krg_arms_cache_signal',
        'label':    "KRG Arms Cache / Kurdish Leverage Signal",
        'detail':   'KRG signals use of weapons cache or leverage in regional negotiations',
        'severity': 1,
        'color':    '#f59e0b',
        'icon':     '📦',
        'category': 'kurdish_trigger',
        'source':   'Trump April 2026 claim -- Kurds received US arms intended for Iran route but kept them; '
                    'watch for KRG leveraging this in Baghdad negotiations or regional positioning',
    },
    # ── Category D: ISIS ──────────────────────────────────────
    {
        'id':       'isis_baghdad_attack',
        'label':    'ISIS Attack in Baghdad or Major City',
        'detail':   'ISIS conducts mass casualty attack in Baghdad, Mosul, or Kirkuk -- active conflict signal',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '☠️',
        'category': 'isis_trigger',
        'source':   'ISW -- ISIS urban attacks signal significant reconstitution; '
                    'Baghdad attacks are operationally more complex and signal higher capability',
    },
    {
        'id':       'isis_territory_sinjar',
        'label':    'ISIS Resurgence in Sinjar / Nineveh / Desert',
        'detail':   'ISIS reconstituting in primary territory -- Sinjar, Nineveh plains, Anbar desert routes',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '⚠️',
        'category': 'isis_trigger',
        'source':   'CENTCOM; ISW -- ISIS exploits PMF distraction and governance vacuum; '
                    'Sinjar corridor is key resupply and command route; '
                    'Anbar desert provides training/staging ground',
    },
    # ── Category E: Sadr wildcard ─────────────────────────────
    {
        'id':       'sadr_mobilization',
        'label':    "Sadr Mobilization After Silence",
        'detail':   "Muqtada al-Sadr breaks silence with mobilization call -- historically precedes mass action",
        'severity': 2,
        'color':    '#f97316',
        'icon':     '👁️',
        'category': 'sadr_trigger',
        'source':   'Pattern analysis -- Sadr\'s 2020 silence preceded Soleimani response mobilization; '
                    '2022 political crisis silence preceded Green Zone breach; '
                    'he is anti-Iran, anti-US, and anti-PMF -- mobilization direction unpredictable',
    },
    {
        'id':       'sadr_silence_anomaly',
        'label':    "Sadr Unusual Silence",
        'detail':   "Al-Sadr below baseline statement frequency -- watch for mobilization signal",
        'severity': 1,
        'color':    '#f59e0b',
        'icon':     '🔇',
        'category': 'sadr_trigger',
        'source':   'Pattern analysis -- Sadr silence preceded both 2020 and 2022 mass mobilizations; '
                    'silence is NOT a positive signal for Sadr -- it is a watch signal',
    },
    # ── Category F: De-escalation signals ────────────────────
    {
        'id':       'sudani_deescalation',
        'label':    'Al-Sudani Government De-escalation Statement',
        'detail':   'PM Sudani issues restraint/sovereignty statement -- diplomatic cover signal',
        'severity': 1,
        'color':    '#10b981',
        'icon':     '🤝',
        'category': 'deescalation_signal',
        'source':   'Political analysis -- Sudani government has been broadly helpful in current crisis; '
                    'his statements provide international cover for Iraqi sovereignty position '
                    'while managing PMF pressure internally',
    },
    {
        'id':       'iran_ceasefire_iraq_effect',
        'label':    'Iran Ceasefire Effect on PMF Posture',
        'detail':   "Trump Iran ceasefire (Apr 7) holding -- PMF factions standing down from Iran direction",
        'severity': 1,
        'color':    '#10b981',
        'icon':     '🕊️',
        'category': 'deescalation_signal',
        'source':   'April 7, 2026 -- Trump announced 2-week Iran ceasefire; '
                    'if Iran stands down, IRGC-directed factions (Kata\'ib) should follow; '
                    'but independent PMF factions may continue operations',
    },
]


# ============================================================
# HISTORICAL PRECEDENT LIBRARY
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'soleimani_killing_2020',
        'label':       'Soleimani Killing & PMF Response (Jan 2020)',
        'description': 'US killed Qasem Soleimani and Abu Mahdi al-Muhandis; PMF declared open war on US',
        'source':      'ISW; CENTCOM; Congressional Research Service 2020',
        'signals': {
            'kataib_active':    True,
            'iran_level_min':   4,
            'us_base_attacks':  True,
            'sadr_mobilized':   True,
        },
        'outcome':     'PMF voted to expel US forces from Iraq. 100+ attacks on US bases over 3 months. '
                       'US struck back. Iraq parliament passed non-binding expulsion resolution.',
        'window_hours': 72,
        'confidence':   'High',
    },
    {
        'id':          'green_zone_storming_2020',
        'label':       'Green Zone Storming After Soleimani (Jan 2020)',
        'description': 'PMF supporters stormed US Embassy compound in Green Zone after Soleimani killing',
        'source':      'Reuters; BBC; ISW January 2020',
        'signals': {
            'pmf_level_min':    3,
            'iran_level_min':   3,
            'green_zone':       True,
            'sadr_mobilized':   False,
        },
        'outcome':     'Embassy compound breached, not overrun. US deployed 750 troops to Kuwait. '
                       'De-escalated within 72h. Soleimani killing followed 2 days later.',
        'window_hours': 48,
        'confidence':   'High',
    },
    {
        'id':          'sadr_2022_political_crisis',
        'label':       "Sadr 2022 Political Crisis & Green Zone Breach",
        'description': 'Sadrists stormed Green Zone twice after parliament deadlock; Sadr then withdrew',
        'source':      'ISW; Al-Monitor; Carnegie Endowment Iraq analysis 2022',
        'signals': {
            'sadr_mobilized':   True,
            'green_zone':       True,
            'pmf_level_min':    2,
            'iran_level_min':   1,
        },
        'outcome':     'Sadr withdrew from politics entirely. Pro-Iran Coordination Framework formed government. '
                       'PMF political influence expanded. Sadr remains wildcard outside formal politics.',
        'window_hours': 120,
        'confidence':   'High',
    },
    {
        'id':          'kataib_base_attack_2023_2024',
        'label':       "Kata'ib Hezbollah Base Attack Campaign (2023-2024)",
        'description': 'Kata\'ib led 160+ attacks on US bases following Gaza war, until Tower 22 response',
        'source':      'CENTCOM; Pentagon; ISW 2023-2024',
        'signals': {
            'kataib_active':    True,
            'iran_level_min':   2,
            'us_base_attacks':  True,
            'sadr_mobilized':   False,
        },
        'outcome':     'US struck Kata\'ib leadership after Tower 22 killed 3 US soldiers. '
                       'Kata\'ib announced suspension. Iran-backed groups broadly de-escalated. '
                       'Pattern: attacks escalate until US responds decisively.',
        'window_hours': 96,
        'confidence':   'High',
    },
    {
        'id':          'isis_resurgence_watch_2024',
        'label':       'ISIS Sinjar/Nineveh Resurgence Signals (2024-2025)',
        'description': 'ISIS exploited PMF-KRG tensions in disputed territories to reconstitute desert network',
        'source':      'ISW Syria-Iraq tracker; CENTCOM quarterly assessment 2024',
        'signals': {
            'isis_level_min':   2,
            'pmf_distracted':   True,
            'krg_tensions':     True,
        },
        'outcome':     'ISIS conducted 200+ attacks in 2024, primarily in Diyala, Salah al-Din, Kirkuk. '
                       'No urban reconstitution. CENTCOM + SDF partnership primary counter.',
        'window_hours': 336,
        'confidence':   'Medium',
    },
]


# ============================================================
# SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """Evaluate Iraq signal state against red lines."""
    actors = scan_data.get('actors', {})

    pmf_level    = actors.get('pmf_hashd', {}).get('escalation_level', 0)
    kataib_level = actors.get('kataib',    {}).get('escalation_level', 0)
    iran_level   = actors.get('iran_iraq', {}).get('escalation_level', 0)
    us_level     = actors.get('us_centcom',{}).get('escalation_level', 0)
    sadr_level   = actors.get('sadr',      {}).get('escalation_level', 0)
    krg_level    = actors.get('krg',       {}).get('escalation_level', 0)
    gov_level    = actors.get('iraqi_gov', {}).get('escalation_level', 0)
    isis_level   = actors.get('isis_iraq', {}).get('escalation_level', 0)

    pmf_vec     = scan_data.get('pmf_level',         0)
    iran_vec    = scan_data.get('iran_strike_level',  0)
    us_base_vec = scan_data.get('us_base_level',      0)
    kurd_vec    = scan_data.get('kurdish_level',      0)
    isis_vec    = scan_data.get('isis_level',         0)
    theatre     = scan_data.get('theatre_score',      0)

    silence_anomalies = scan_data.get('silence_anomalies', [])
    sadr_silent = any(a.get('actor_id') == 'sadr' for a in silence_anomalies)
    sadr_count  = actors.get('sadr', {}).get('statement_count', 0)

    def _scan(actor_ids, keywords):
        for aid in actor_ids:
            for art in actors.get(aid, {}).get('top_articles', []):
                title = art.get('title', '').lower()
                if any(kw in title for kw in keywords):
                    return True
        return False

    embassy_attack = _scan(['pmf_hashd', 'kataib', 'iran_iraq'], [
        'embassy attack', 'embassy stormed', 'consulate attack',
        'green zone breach', 'green zone stormed', 'diplomatic compound',
        'embassy baghdad attack', 'consulate erbil attack',
    ])
    base_attack = _scan(['pmf_hashd', 'kataib', 'us_centcom'], [
        'al asad attack', 'ain al-asad', 'base attack iraq',
        'rocket attack us base', 'drone attack base', 'casualties iraq base',
        'us troops killed iraq', 'us soldiers iraq',
    ])
    kataib_active = _scan(['kataib', 'pmf_hashd'], [
        'kataib declares', 'kataib announces', 'kataib launches',
        'kataib operations', 'kataib strikes', 'kataib warns',
        'kata\'ib hezbollah operation', 'islamic resistance iraq operation',
    ])
    green_zone = _scan(['pmf_hashd', 'sadr', 'iran_iraq'], [
        'green zone', 'parliament stormed', 'embassy compound',
        'protest baghdad embassy', 'demonstration green zone',
    ])
    erbil_attack = _scan(['iran_iraq', 'krg', 'us_centcom'], [
        'erbil attack', 'erbil missile', 'erbil drone',
        'kurdistan attack', 'irgc erbil', 'iran strikes erbil',
    ])
    krg_baghdad = _scan(['krg', 'pmf_hashd'], [
        'kirkuk confrontation', 'peshmerga pmf', 'krg pmf clash',
        'disputed territory', 'kirkuk standoff', 'sinjar peshmerga',
        'peshmerga withdraws', 'krg forces advance',
    ])
    krg_arms = _scan(['krg', 'us_centcom', 'iraqi_gov'], [
        'kurdish arms', 'peshmerga weapons', 'krg arms cache',
        'trump kurds weapons', 'kurds kept arms', 'arms cache krg',
    ])
    isis_baghdad = _scan(['isis_iraq'], [
        'isis baghdad', 'daesh baghdad', 'islamic state baghdad',
        'isis mosul', 'isis attack city', 'isis urban', 'mass casualty isis',
    ])
    isis_sinjar = _scan(['isis_iraq'], [
        'sinjar', 'nineveh', 'anbar isis', 'diyala isis', 'salah al-din',
        'desert isis', 'isis resurgence', 'daesh desert',
    ]) or isis_vec >= 2
    sadr_mobilize = _scan(['sadr'], [
        'sadr mobilizes', 'sadr calls', 'sadr warns', 'sadr declares',
        'saraya al-salam mobilize', 'mahdi army', 'sadr movement march',
    ])
    sudani_deescalate = _scan(['iraqi_gov'], [
        'sudani calls for calm', 'sudani sovereignty', 'iraq will not',
        'sudani condemns', 'iraqi government urges', 'iraq mediates',
        'sudani restraint', 'sudani dialogue',
    ])
    ceasefire_effect = _scan(['iran_iraq', 'iraqi_gov', 'us_centcom'], [
        'ceasefire', 'iran ceasefire', 'pmf stands down', 'de-escalation iraq',
        'kataib suspends', 'iran iraq truce',
    ])
    pmf_iran_coord = (pmf_level >= 2 and iran_level >= 2) or \
                     any(c.get('actors', []) == ['pmf_hashd', 'iran_iraq']
                         for c in scan_data.get('coordination_signals', []))

    triggered = []

    if embassy_attack or green_zone:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'us_embassy_attack'),
            'status':  'BREACHED' if embassy_attack else 'APPROACHING',
            'trigger': f'Embassy/diplomatic facility attack language detected -- US facility red line',
        })

    if base_attack or us_base_vec >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'us_base_direct_attack'),
            'status':  'BREACHED' if base_attack else 'APPROACHING',
            'trigger': f'US base attack language detected -- base attack vector L{us_base_vec}',
        })

    if kataib_active or kataib_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'kataib_activation'),
            'status':  'BREACHED' if (kataib_active or kataib_level >= 4) else 'APPROACHING',
            'trigger': f"Kata'ib L{kataib_level} -- IRGC-directed faction activation signals",
        })

    if pmf_iran_coord or (pmf_level >= 3 and iran_level >= 3):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'pmf_iran_coordination'),
            'status':  'BREACHED' if (pmf_level >= 4 and iran_level >= 3) else 'APPROACHING',
            'trigger': f'PMF L{pmf_level} + Iran L{iran_level} -- coordinated proxy axis signals',
        })

    if green_zone and not embassy_attack:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'green_zone_breach'),
            'status':  'APPROACHING',
            'trigger': 'Green Zone / Baghdad protest escalation language detected',
        })

    if erbil_attack or (kurd_vec >= 3 and iran_level >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'erbil_base_attack'),
            'status':  'BREACHED' if erbil_attack else 'APPROACHING',
            'trigger': f'Erbil/KRG attack language + Iran L{iran_level} -- IRGC strike on KRG territory',
        })

    if krg_baghdad or (krg_level >= 3 and pmf_level >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'krg_baghdad_fracture'),
            'status':  'APPROACHING',
            'trigger': f'KRG-PMF confrontation signals -- disputed territory flash point',
        })

    if krg_arms:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'krg_arms_cache_signal'),
            'status':  'APPROACHING',
            'trigger': 'Kurdish arms cache/leverage language detected -- watch KRG negotiating posture',
        })

    if isis_baghdad or isis_vec >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'isis_baghdad_attack'),
            'status':  'BREACHED' if isis_baghdad else 'APPROACHING',
            'trigger': f'ISIS urban/Baghdad attack signals -- higher capability indicator',
        })

    if isis_sinjar:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'isis_territory_sinjar'),
            'status':  'APPROACHING',
            'trigger': f'ISIS resurgence in primary territory -- Sinjar/Nineveh/Anbar signals',
        })

    if sadr_mobilize and sadr_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'sadr_mobilization'),
            'status':  'APPROACHING',
            'trigger': 'Sadr breaking silence with mobilization language -- historical pattern match',
        })

    if sadr_silent or (sadr_count == 0 and theatre >= 15):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'sadr_silence_anomaly'),
            'status':  'APPROACHING',
            'trigger': 'Sadr below baseline -- silence historically precedes mobilization (2020, 2022 pattern)',
        })

    if sudani_deescalate or gov_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'sudani_deescalation'),
            'status':  'APPROACHING',
            'trigger': 'Sudani government restraint/sovereignty language -- de-escalation diplomatic cover',
        })

    if ceasefire_effect:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'iran_ceasefire_iraq_effect'),
            'status':  'APPROACHING',
            'trigger': 'Iran ceasefire language in Iraq context -- PMF posture shift signal',
        })

    # Sort: breached first, then by severity, deescalation last
    triggered.sort(key=lambda x: (
        0 if x['status'] == 'BREACHED' else 1,
        -x['severity'],
        0 if x['category'] not in ('deescalation_signal',) else 1
    ))
    return triggered


def _match_historical(scan_data):
    """Match Iraq signal state against historical precedents."""
    actors = scan_data.get('actors', {})

    pmf_level    = actors.get('pmf_hashd', {}).get('escalation_level', 0)
    kataib_level = actors.get('kataib',    {}).get('escalation_level', 0)
    iran_level   = actors.get('iran_iraq', {}).get('escalation_level', 0)
    sadr_level   = actors.get('sadr',      {}).get('escalation_level', 0)
    krg_level    = actors.get('krg',       {}).get('escalation_level', 0)
    isis_vec     = scan_data.get('isis_level', 0)
    us_base_vec  = scan_data.get('us_base_level', 0)

    silence_anomalies = scan_data.get('silence_anomalies', [])
    sadr_silent  = any(a.get('actor_id') == 'sadr' for a in silence_anomalies)
    sadr_mob     = sadr_level >= 2
    kataib_act   = kataib_level >= 2
    us_attacks   = us_base_vec >= 2
    green_zone   = False  # only from article scan; default false
    krg_tensions = krg_level >= 2
    pmf_dist     = pmf_level >= 2 and krg_level >= 1

    matches = []
    for precedent in HISTORICAL_PRECEDENTS:
        sigs = precedent['signals']
        score = 0
        max_score = 0
        matched = []
        missed = []

        def check(condition, label, weight=1):
            nonlocal score, max_score
            max_score += weight
            if condition:
                score += weight
                matched.append(label)
            else:
                missed.append(label)

        if 'kataib_active'  in sigs: check(kataib_act == sigs['kataib_active'],   f"Kata'ib active: {kataib_act}", weight=3)
        if 'iran_level_min' in sigs: check(iran_level >= sigs['iran_level_min'],   f'Iran L{iran_level} >= L{sigs["iran_level_min"]}', weight=2)
        if 'us_base_attacks'in sigs: check(us_attacks  == sigs['us_base_attacks'], f'US base attacks: {us_attacks}', weight=3)
        if 'sadr_mobilized' in sigs: check(sadr_mob    == sigs['sadr_mobilized'],  f'Sadr mobilized: {sadr_mob}', weight=2)
        if 'pmf_level_min'  in sigs: check(pmf_level   >= sigs['pmf_level_min'],   f'PMF L{pmf_level} >= L{sigs["pmf_level_min"]}', weight=2)
        if 'green_zone'     in sigs: check(green_zone  == sigs['green_zone'],      f'Green Zone: {green_zone}', weight=2)
        if 'isis_level_min' in sigs: check(isis_vec    >= sigs['isis_level_min'],   f'ISIS L{isis_vec}', weight=2)
        if 'pmf_distracted' in sigs: check(pmf_dist    == sigs['pmf_distracted'],  f'PMF distracted: {pmf_dist}', weight=1)
        if 'krg_tensions'   in sigs: check(krg_tensions== sigs['krg_tensions'],    f'KRG tensions: {krg_tensions}', weight=1)

        if max_score == 0:
            continue
        similarity = round((score / max_score) * 100)
        if similarity >= 40:
            matches.append({
                'id':              precedent['id'],
                'label':           precedent['label'],
                'description':     precedent['description'],
                'source':          precedent['source'],
                'outcome':         precedent['outcome'],
                'window_hours':    precedent['window_hours'],
                'confidence':      precedent['confidence'],
                'similarity':      similarity,
                'matched_signals': matched,
                'missed_signals':  missed,
            })

    matches.sort(key=lambda x: x['similarity'], reverse=True)
    return matches[:3]


def _build_so_what(scan_data, red_lines_triggered, historical_matches):
    """
    Iraq command node assessment.
    Frame: Five-way tension -- PMF/Iran, Sadr wildcard, KRG triple vector,
    US facilities, ISIS geography.
    """
    actors = scan_data.get('actors', {})

    pmf_level    = actors.get('pmf_hashd', {}).get('escalation_level', 0)
    kataib_level = actors.get('kataib',    {}).get('escalation_level', 0)
    iran_level   = actors.get('iran_iraq', {}).get('escalation_level', 0)
    sadr_level   = actors.get('sadr',      {}).get('escalation_level', 0)
    krg_level    = actors.get('krg',       {}).get('escalation_level', 0)
    gov_level    = actors.get('iraqi_gov', {}).get('escalation_level', 0)
    isis_vec     = scan_data.get('isis_level',         0)
    us_base_vec  = scan_data.get('us_base_level',      0)
    pmf_vec      = scan_data.get('pmf_level',          0)
    iran_vec     = scan_data.get('iran_strike_level',  0)
    kurd_vec     = scan_data.get('kurdish_level',      0)
    theatre      = scan_data.get('theatre_score',       0)

    silence_anomalies = scan_data.get('silence_anomalies', [])
    sadr_silent  = any(a.get('actor_id') == 'sadr' for a in silence_anomalies)
    sadr_count   = actors.get('sadr', {}).get('statement_count', 0)

    delta = scan_data.get('delta', {}) or {}
    delta_dir    = delta.get('direction', 'stable')
    score_change = delta.get('score_change', 0)

    breached_count   = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    approaching_count= sum(1 for r in red_lines_triggered if r['status'] == 'APPROACHING')
    top_match        = historical_matches[0] if historical_matches else None

    kataib_active    = kataib_level >= 2
    iran_directing   = iran_level >= 2
    us_under_threat  = us_base_vec >= 2 or any(r['id'] in ('us_embassy_attack', 'us_base_direct_attack') for r in red_lines_triggered if r['status'] == 'BREACHED')
    sudani_deesc     = any(r['id'] == 'sudani_deescalation' for r in red_lines_triggered)
    ceasefire_active = any(r['id'] == 'iran_ceasefire_iraq_effect' for r in red_lines_triggered)

    # ── Scenario label ──
    if breached_count >= 2 or (kataib_level >= 4 and us_base_vec >= 3):
        scenario       = 'CRITICAL -- PMF/US Kinetic Conflict Active'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif breached_count == 1 or kataib_level >= 3 or us_base_vec >= 3:
        scenario       = 'ELEVATED -- Proxy Activation / US Facilities at Risk'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif pmf_level >= 2 or iran_level >= 2 or sadr_silent:
        scenario       = 'WARNING -- PMF Mobilization / Sadr Watch'
        scenario_color = '#f59e0b'
        scenario_icon  = '🟡'
    elif ceasefire_active or sudani_deesc:
        scenario       = 'MONITORING -- Ceasefire Effect / Diplomatic Activity'
        scenario_color = '#3b82f6'
        scenario_icon  = '🔵'
    else:
        scenario       = 'MONITORING -- Below Escalation Threshold'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Situation ──
    situation_parts = []

    # Core question 1: Will Iraqi Shia side with Iran?
    if kataib_level >= 2 or pmf_level >= 2:
        situation_parts.append(
            f"Kata'ib Hezbollah at L{kataib_level}, PMF/Hashd at L{pmf_level} -- "
            f"Iran-directed factions showing {'activation' if kataib_level >= 3 else 'mobilization'} signals. "
            f"Kata'ib is the primary IRGC Quds Force-directed faction; their signals are the most direct "
            f"indicator of Iranian operational command in Iraq. "
            f"NOTE: The Trump-Iran ceasefire (April 7, 2026) changes the calculus -- "
            f"if Iran stands down, Kata'ib should follow; independent PMF factions may not."
        )
    elif theatre <= 20:
        situation_parts.append(
            f"Iraq below active escalation threshold at {theatre}/100. "
            f"Core question remains: will Iran-backed Shia factions activate against US forces? "
            f"Current signals suggest restraint -- consistent with the April 7 Iran ceasefire context."
        )

    # Sadr
    if sadr_silent:
        situation_parts.append(
            f"SADR SILENCE DETECTED: Al-Sadr at {sadr_count} statements (below baseline). "
            f"Historical pattern: Sadr silence preceded both the 2020 Soleimani mobilization "
            f"and the 2022 Green Zone breach. Silence is NOT a positive signal for Sadr -- "
            f"it is a watch signal. Direction of any mobilization (pro-Iran, anti-US, or anti-PMF) "
            f"is unpredictable until he breaks silence."
        )

    # KRG
    if krg_level >= 2 or kurd_vec >= 2:
        situation_parts.append(
            f"KRG at L{krg_level} -- Kurdish triple vector active: "
            f"(1) Erbil base attack risk from Iranian missiles, "
            f"(2) Baghdad-KRG political tensions over Kirkuk/disputed territories, "
            f"(3) Syrian/Turkish Kurdish coordination signals. "
            f"Watch for KRG leveraging the reported Trump arms cache in negotiations."
        )

    # ISIS
    if isis_vec >= 2:
        situation_parts.append(
            f"ISIS vector at L{isis_vec} -- resurgence signals in primary territory. "
            f"PMF distraction from Iran conflict creates the governance vacuum ISIS historically exploits. "
            f"Sinjar/Nineveh/Anbar desert routes are the key watch zones."
        )

    # Delta
    if delta_dir == 'rising' and score_change >= 10:
        situation_parts.append(
            f"Score rising sharply (+{round(score_change)} from recent average) -- trajectory accelerating."
        )
    elif delta_dir == 'falling':
        situation_parts.append(
            f"Score falling ({round(score_change)} from recent average) -- "
            f"consistent with ceasefire effect on PMF posture."
        )

    # ── Key indicators ──
    indicators = []

    indicators.append(
        f"KATA'IB HEZBOLLAH WATCH: Kata'ib is the primary IRGC-directed faction -- "
        f"their signals are the most direct indicator of Iranian operational intent in Iraq. "
        f"When Kata'ib activates, US base attacks follow within 24-96h (2023-2024 pattern). "
        f"Current L{kataib_level}."
    )

    if sadr_silent:
        indicators.append(
            "SADR SILENCE -- WATCH SIGNAL: Al-Sadr below baseline. "
            "2020 pattern: silence preceded mass PMF mobilization after Soleimani. "
            "2022 pattern: silence preceded Green Zone breach. "
            "He is anti-Iran, anti-US, and anti-PMF -- mobilization direction is unpredictable."
        )

    indicators.append(
        "IRAN CEASEFIRE EFFECT (April 7, 2026): Trump announced 2-week Iran ceasefire. "
        "Watch whether IRGC-directed factions (Kata'ib) stand down in Iraq. "
        "Independent PMF factions may continue operations regardless of Tehran direction. "
        "Sudani government has been broadly helpful -- leverage his restraint calls as signal."
    )

    if isis_vec >= 1:
        indicators.append(
            f"ISIS GEOGRAPHY MATTERS: ISIS in Baghdad = active conflict signal (complex operation, high capability). "
            f"ISIS in Sinjar/Nineveh/Anbar = resurgence watch (exploiting PMF distraction). "
            f"Current ISIS vector: L{isis_vec}. "
            f"CENTCOM + SDF partnership is the primary counter -- watch for US posture changes."
        )

    # ── Assessment ──
    assessment_parts = []
    if top_match and top_match['similarity'] >= 50:
        assessment_parts.append(
            f"Current pattern shows {top_match['similarity']}% similarity to "
            f"{top_match['label']}. In that case: {top_match['outcome'].lower()}"
        )
        assessment_parts.append(
            f"Confidence: {top_match['confidence']}. "
            f"Historical response window: {top_match['window_hours']}h. Analytical estimate only."
        )

    if not assessment_parts:
        if theatre <= 25:
            assessment_parts.append(
                "Iraq signals below active escalation threshold. "
                "Consistent with Iran ceasefire effect on PMF posture. "
                "Key leading indicators to watch: Kata'ib statement frequency, "
                "Sadr breaking silence, and ISIS activity in Sinjar corridor."
            )

    # ── Watch list ──
    watch_items = [
        "Kata'ib Hezbollah statement frequency -- primary Iran-directed activation signal",
        "Sadr breaks silence -- direction (pro-Iran/anti-US/anti-PMF) determines threat vector",
        "US base attack language -- Al Asad, Erbil, Baghdad base attack claims",
        "Iran ceasefire effect on PMF: do IRGC-directed factions stand down?",
        "ISIS activity in Sinjar/Nineveh corridor -- PMF distraction exploitation window",
        "KRG arms leverage signals -- Kurdish negotiating posture shift",
    ]

    return {
        'scenario':             scenario,
        'scenario_color':       scenario_color,
        'scenario_icon':        scenario_icon,
        'situation':            ' '.join(situation_parts),
        'key_indicators':       indicators[:4],
        'assessment':           ' '.join(assessment_parts),
        'watch_list':           watch_items[:5],
        'sadr_silent':          sadr_silent,
        'kataib_active':        kataib_active,
        'iran_directing':       iran_directing,
        'us_under_threat':      us_under_threat,
        'ceasefire_active':     ceasefire_active,
        'generated_at':         datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Iraq assessment generated from open-source signal data. '
            'PMF is not monolithic -- Kata\'ib Hezbollah is IRGC-directed; '
            'other factions have varying degrees of Iranian influence. '
            'Not a prediction. Verify through official channels.'
        ),
    }


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """Main entry point. Called from rhetoric_tracker_iraq.py."""
    try:
        red_lines  = _score_red_lines(scan_data)
        historical = _match_historical(scan_data)
        so_what    = _build_so_what(scan_data, red_lines, historical)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']

        return {
            'so_what':             so_what,
            'red_lines': {
                'triggered':         red_lines,
                'breached_count':    len(breached),
                'approaching_count': len(approaching),
                'highest_severity':  max((r['severity'] for r in red_lines), default=0),
            },
            'historical_matches':  historical,
            'interpreter_version': '1.0.0',
            'interpreted_at':      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Iraq Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what':            {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines':          {'triggered': [], 'breached_count': 0, 'approaching_count': 0, 'highest_severity': 0},
            'historical_matches': [],
            'interpreter_version': '1.0.0',
            'error':              str(e)[:200],
        }


# ============================================================
# CANONICAL TOP_SIGNALS BUILDER — v2.0 (April 2026)
# ============================================================
# Emits the canonical schema for Iraq signals that feeds:
#   - ME Regional BLUF (me_regional_bluf.py)
#   - Global Pressure Index (global_pressure_index.py)
#
# Signal shape (canonical across platform):
# {
#     'priority':   int,        # higher = more urgent
#     'category':   str,        # red_line_breached / kinetic_pressure / theatre_high /
#                               #   silence_anomaly / regime_fracture / diplomatic_active /
#                               #   crosstheater_iran_iraq
#     'theatre':    'iraq',
#     'level':      int,        # 0-5
#     'icon':       str,        # emoji
#     'color':      str,        # hex
#     'short_text': str,        # ≤80 char headline
#     'long_text':  str,        # ≤200 char tooltip / detail
# }

IRAQ_FLAG = '\U0001f1ee\U0001f1f6'  # 🇮🇶


def build_top_signals(result):
    """
    Build Iraq's top_signals[] for BLUF/GPI consumption.
    Reads from a fully-built scan result (with interpretation attached).
    Returns sorted list (descending priority); BLUF/GPI dedupes globally.
    """
    signals = []

    theatre_level = result.get('theatre_level',
                    result.get('theatre_escalation_level', 0)) or 0
    theatre_score = result.get('theatre_score', 0) or 0

    # Iraq-specific vectors (set by the tracker)
    pmf_level    = result.get('pmf_level',         0) or 0
    iran_level   = result.get('iran_strike_level', 0) or 0
    base_level   = result.get('us_base_level',     0) or 0
    kurd_level   = result.get('kurdish_level',     0) or 0
    isis_level   = result.get('isis_level',        0) or 0

    actors = result.get('actors', {}) or {}
    iraqi_gov_lvl = actors.get('iraqi_gov',  {}).get('escalation_level', 0)
    sadr_lvl      = actors.get('sadr',       {}).get('escalation_level', 0)
    kataib_lvl    = actors.get('kataib',     {}).get('escalation_level', 0)
    krg_lvl       = actors.get('krg',        {}).get('escalation_level', 0)

    # Pull interpretation block (Iraq's interpret_signals output)
    interp = result.get('interpretation', {}) or {}
    so_what = interp.get('so_what', {}) or {}
    rl_obj  = interp.get('red_lines', {}) or {}

    sadr_silent     = so_what.get('sadr_silent', False)
    kataib_active   = so_what.get('kataib_active', False)
    iran_directing  = so_what.get('iran_directing', False)
    us_under_threat = so_what.get('us_under_threat', False)

    # ============================================
    # CATEGORY 1: RED LINES BREACHED (highest priority)
    # ============================================
    for rl in rl_obj.get('triggered', []):
        if rl.get('status') == 'BREACHED':
            severity = int(rl.get('severity', 0) or 0)
            signals.append({
                'priority':   12 if severity >= 3 else 11,
                'category':   'red_line_breached',
                'theatre':    'iraq',
                'level':      max(theatre_level, severity * 2),
                'icon':       rl.get('icon', '🚨'),
                'color':      '#dc2626',
                'short_text': f'{IRAQ_FLAG} IRAQ: {rl.get("label", "Red line breached")[:60]}',
                'long_text':  (f'IRAQ red line breached -- {rl.get("label", "")}: '
                               f'{rl.get("trigger", "")[:140]}'),
            })

    # ============================================
    # CATEGORY 2: US BASE / EMBASSY KINETIC PRESSURE
    # ============================================
    if base_level >= 3:
        signals.append({
            'priority':   11,
            'category':   'kinetic_pressure',
            'theatre':    'iraq',
            'level':      base_level,
            'icon':       '⚔️',
            'color':      '#dc2626',
            'short_text': f'{IRAQ_FLAG} IRAQ: US base/diplomatic pressure (L{base_level})',
            'long_text':  (f'IRAQ US Forces / United States Central Command (CENTCOM) base or '
                           f'diplomatic facility kinetic pressure at L{base_level}. Force protection '
                           f'posture elevated; rocket/drone strikes likely.'),
        })

    # ============================================
    # CATEGORY 3: KATAIB-ACTIVE + SADR-SILENT (Iraq-specific high-signal pattern)
    # ============================================
    # This is the classic pre-escalation pattern flagged by the so_what builder.
    if kataib_active and sadr_silent:
        signals.append({
            'priority':   11,
            'category':   'silence_anomaly',
            'theatre':    'iraq',
            'level':      max(kataib_lvl, 4),
            'icon':       '🚨',
            'color':      '#dc2626',
            'short_text': f'{IRAQ_FLAG} IRAQ: Kata\'ib active + Sadr silent -- pre-mobilization pattern',
            'long_text':  (f'IRAQ: Kata\'ib Hezbollah operationally active while Muqtada al-Sadr '
                           f'has gone silent ({sadr_lvl=}, baseline departure). Historical pattern: '
                           f'Sadr silence precedes mobilization within 1-3 weeks.'),
        })
    elif sadr_silent:
        signals.append({
            'priority':   9,
            'category':   'silence_anomaly',
            'theatre':    'iraq',
            'level':      3,
            'icon':       '🤐',
            'color':      '#f59e0b',
            'short_text': f'{IRAQ_FLAG} IRAQ: Sadr silent -- watch for mobilization',
            'long_text':  (f'IRAQ: Muqtada al-Sadr has gone silent (statement count below baseline). '
                           f'Wildcard actor; historical silence-before-mobilization precedent.'),
        })

    # ============================================
    # CATEGORY 4: IRAN DIRECTING IRAQI PROXIES (cross-theater fingerprint)
    # ============================================
    if iran_directing or iran_level >= 3:
        signals.append({
            'priority':   10,
            'category':   'crosstheater_iran_iraq',
            'theatre':    'iraq',
            'level':      max(iran_level, pmf_level),
            'icon':       '🔗',
            'color':      '#7c3aed',
            'short_text': f'{IRAQ_FLAG} IRAQ: Iran-directing PMF (L{max(iran_level, pmf_level)})',
            'long_text':  (f'IRAQ: Islamic Revolutionary Guard Corps (IRGC) Quds Force directing '
                           f'Popular Mobilization Forces (PMF) / Hashd al-Shaabi posture. '
                           f'Tehran-Baghdad coordination signal active.'),
        })

    # ============================================
    # CATEGORY 5: PMF FRAGMENTATION / REGIME STRESS
    # ============================================
    if pmf_level >= 4 and iraqi_gov_lvl <= 1:
        signals.append({
            'priority':   10,
            'category':   'regime_fracture',
            'theatre':    'iraq',
            'level':      pmf_level,
            'icon':       '⚡',
            'color':      '#ef4444',
            'short_text': f'{IRAQ_FLAG} IRAQ: PMF outpacing government (L{pmf_level})',
            'long_text':  (f'IRAQ: Popular Mobilization Forces (PMF) escalation tempo exceeding '
                           f'Iraqi government statements. Sudani losing control of state monopoly '
                           f'on force; PMF acting independently.'),
        })

    # ============================================
    # CATEGORY 6: THEATRE COMPOSITE HIGH (catch-all)
    # ============================================
    if theatre_level >= 4 or theatre_score >= 70:
        signals.append({
            'priority':   9,
            'category':   'theatre_high',
            'theatre':    'iraq',
            'level':      theatre_level,
            'icon':       '🔴',
            'color':      '#dc2626',
            'short_text': f'{IRAQ_FLAG} IRAQ: Theatre composite L{theatre_level} ({theatre_score}/100)',
            'long_text':  (f'IRAQ composite rhetoric vector at L{theatre_level} '
                           f'(score {theatre_score}/100). Multi-actor escalation across PMF, '
                           f'Iran-Iraq, US base posture vectors.'),
        })

    # ============================================
    # CATEGORY 7: ISIS RECONSTITUTION (background threat resurfacing)
    # ============================================
    if isis_level >= 3:
        signals.append({
            'priority':   8,
            'category':   'kinetic_pressure',
            'theatre':    'iraq',
            'level':      isis_level,
            'icon':       '⚫',
            'color':      '#1f2937',
            'short_text': f'{IRAQ_FLAG} IRAQ: ISIS reconstitution (L{isis_level})',
            'long_text':  (f'IRAQ: Islamic State (ISIS) reconstitution signals at L{isis_level}. '
                           f'Sinjar / Nineveh / contested territory exploitation as governance '
                           f'attention focuses on Iran-US tensions.'),
        })

    # ============================================
    # CATEGORY 8: KURDISH FRICTION (KRG / Erbil tensions)
    # ============================================
    if kurd_level >= 3 or krg_lvl >= 3:
        signals.append({
            'priority':   7,
            'category':   'regime_fracture',
            'theatre':    'iraq',
            'level':      max(kurd_level, krg_lvl),
            'icon':       '🟡',
            'color':      '#eab308',
            'short_text': f'{IRAQ_FLAG} IRAQ: Kurdish/Erbil friction (L{max(kurd_level, krg_lvl)})',
            'long_text':  (f'IRAQ: Kurdistan Regional Government (KRG) / Erbil tensions elevated '
                           f'(L{max(kurd_level, krg_lvl)}). Baghdad-KRG friction or Erbil base '
                           f'attacks; potential triple-vector with Syria/Turkey Kurdish dynamics.'),
        })

    # ============================================
    # CATEGORY 9: SUDANI DIPLOMATIC DE-ESCALATION (positive signal)
    # ============================================
    if iraqi_gov_lvl >= 2 and pmf_level <= 2 and iran_level <= 2:
        signals.append({
            'priority':   6,
            'category':   'diplomatic_active',
            'theatre':    'iraq',
            'level':      iraqi_gov_lvl,
            'icon':       '🕊️',
            'color':      '#10b981',
            'short_text': f'{IRAQ_FLAG} IRAQ: Sudani de-escalation track active (L{iraqi_gov_lvl})',
            'long_text':  (f'IRAQ: Prime Minister Sudani diplomatic posture active while PMF and '
                           f'Iran-Iraq vectors remain restrained. Government providing diplomatic '
                           f'cover; positive de-escalation signal.'),
        })

    # ============================================
    # CATEGORY 10: US-UNDER-THREAT FLAG (composite from so_what)
    # ============================================
    if us_under_threat and base_level < 3:
        # If so_what flags us_under_threat but base level isn't yet high,
        # surface it as an early-warning approaching signal.
        signals.append({
            'priority':   8,
            'category':   'kinetic_pressure',
            'theatre':    'iraq',
            'level':      max(base_level, 3),
            'icon':       '🎯',
            'color':      '#f97316',
            'short_text': f'{IRAQ_FLAG} IRAQ: US forces under elevated threat posture',
            'long_text':  (f'IRAQ: Composite analysis flags US Forces / Embassy / Green Zone under '
                           f'elevated threat posture. Force protection signaling and adversary '
                           f'rhetoric converging.'),
        })

    # Sort descending by priority
    signals.sort(key=lambda s: s.get('priority', 0), reverse=True)
    return signals


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    test_data = {
        'theatre_score':     45,
        'pmf_level':          3,
        'iran_strike_level':  2,
        'us_base_level':      2,
        'kurdish_level':      1,
        'isis_level':         1,
        'delta': {'direction': 'rising', 'score_change': 15},
        'silence_anomalies': [{'actor_id': 'sadr', 'deviation': '80% below baseline'}],
        'coordination_signals': [
            {'actors': ['pmf_hashd', 'iran_iraq'], 'message': 'PMF + Iran coordinated'}
        ],
        'actors': {
            'pmf_hashd': {'escalation_level': 3, 'statement_count': 18, 'top_articles': [
                {'title': 'PMF announces readiness to respond to any aggression against Iraq', 'published': ''},
            ]},
            'kataib':    {'escalation_level': 2, 'statement_count': 8, 'top_articles': [
                {'title': "Kata'ib Hezbollah warns US forces must leave Iraq", 'published': ''},
            ]},
            'iran_iraq': {'escalation_level': 2, 'statement_count': 12, 'top_articles': [
                {'title': 'IRGC Quds Force directs PMF to maintain readiness posture', 'published': ''},
            ]},
            'us_centcom':{'escalation_level': 2, 'statement_count': 6, 'top_articles': []},
            'sadr':      {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
            'iraqi_gov': {'escalation_level': 1, 'statement_count': 4, 'top_articles': [
                {'title': 'Sudani calls for restraint, says Iraq will not be arena for conflict', 'published': ''},
            ]},
            'krg':       {'escalation_level': 1, 'statement_count': 3, 'top_articles': []},
            'isis_iraq': {'escalation_level': 0, 'statement_count': 0, 'top_articles': []},
        },
    }

    result = interpret_signals(test_data)
    sw = result['so_what']
    print('\n' + '='*65)
    print(f'SCENARIO: {sw["scenario"]}')
    print(f'SADR SILENT: {sw.get("sadr_silent")}')
    print(f'KATAIB ACTIVE: {sw.get("kataib_active")}')
    print(f'IRAN DIRECTING: {sw.get("iran_directing")}')
    print(f'US UNDER THREAT: {sw.get("us_under_threat")}')
    print('='*65)
    print('\nSITUATION:')
    print(sw['situation'][:500])
    print('\nKEY INDICATORS:')
    for ind in sw['key_indicators']:
        print(f'  -- {ind[:100]}')
    print('\nWATCH LIST:')
    for item in sw['watch_list']:
        print(f'  -> {item}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} [{rl["category"]}] Sev {rl["severity"]}')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]} | Window: {hm["window_hours"]}h')
