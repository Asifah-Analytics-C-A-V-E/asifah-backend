"""
iran_signal_interpreter.py
Asifah Analytics -- ME Backend Module
v1.0.0

Signal interpretation engine for the Iran Rhetoric Tracker.
Iran is the COMMAND NODE -- the analytical frame is fundamentally
different from the Israel interpreter.

Key question: Is Iran orchestrating a coordinated multi-theater
axis activation, and how close is it to triggering direct
US/Israeli military response?

Three analytical outputs:
  1. So What Summary  -- plain-language command node assessment
  2. Red Line Status  -- Iran's red lines AND adversary red lines re: Iran
  3. Historical Match -- documented pre-escalation patterns

Iran-specific red lines fall into TWO categories:
  A. Iran's own red lines (what would trigger Iranian direct action)
  B. Adversary red lines re: Iran (what triggers US/Israeli response)

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone



# ============================================================
# RED LINE DEFINITIONS -- DUAL CATEGORY
# ============================================================
RED_LINES = [
    # ── Category A: Iran's own escalation triggers ──────────
    {
        'id':       'direct_us_strike_iran',
        'label':    'Direct US Strike on Iranian Territory',
        'detail':   'CENTCOM conducts kinetic strike on Iranian soil or naval assets',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🇺🇸',
        'category': 'adversary_trigger',
        'source':   'IRGC doctrine -- direct attack triggers mandatory retaliation (Operation True Promise precedent)',
    },
    {
        'id':       'strait_of_hormuz_closure',
        'label':    'Strait of Hormuz Closure / Mining',
        'detail':   'Iran moves to close or mine Strait of Hormuz -- triggers US/coalition military response',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '⚓',
        'category': 'iran_trigger',
        'source':   'US Central Command stated red line; triggers Article 5-equivalent response',
    },
    {
        'id':       'nuclear_threshold_crossed',
        'label':    'Nuclear Weapons-Grade Enrichment',
        'detail':   'Iran enriches uranium to 90%+ weapons grade -- triggers Israeli/US preemptive consideration',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '☢️',
        'category': 'adversary_trigger',
        'source':   'Israeli red line -- stated multiple times by PM, Defense Minister, Mossad',
    },
    {
        'id':       'otp_wave_acceleration',
        'label':    'Operation True Promise -- Wave Acceleration',
        'detail':   'OTP wave count accelerating (multiple waves in 24h) signals coordinated campaign escalation',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🌊',
        'category': 'iran_trigger',
        'source':   'Pattern analysis -- OTP wave acceleration preceded direct Iranian escalation in 2024',
    },
    {
        'id':       'proxy_simultaneous_activation',
        'label':    'Full Axis Simultaneous Activation',
        'detail':   'Hezbollah + Houthi + PMF Iraq all activated simultaneously under Iranian direction',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🔱',
        'category': 'iran_trigger',
        'source':   'CSIS / INSS -- simultaneous proxy activation is Iranian command node signal',
    },
    {
        'id':       'khamenei_direct_statement',
        'label':    'Khamenei Direct Threat Statement',
        'detail':   'Supreme Leader issues direct public threat (not IRGC spokesperson) -- elevated authorization signal',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '👁️',
        'category': 'iran_trigger',
        'source':   'Pattern analysis -- Khamenei direct statements precede major IRGC operations',
    },
    {
        'id':       'trump_iran_ultimatum',
        'label':    'Trump Issues Iran Ultimatum',
        'detail':   'US president issues direct ultimatum to Iran with timeline -- forces Iranian response decision',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '⏱️',
        'category': 'adversary_trigger',
        'source':   'Historical pattern -- Trump maximum pressure + ultimatum language forces Iranian hand',
    },
    {
        'id':       'irgc_silence_pre_op',
        'label':    'IRGC Command Silence Before Operation',
        'detail':   'IRGC public statements drop to zero while proxy activation increases -- pre-operation pattern',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🤫',
        'category': 'iran_trigger',
        'source':   'Operational security pattern -- IRGC silence preceded OTP launches in 2024',
    },
    {
        'id':       'hormuz_transit_threat',
        'label':    'Strait of Hormuz Transit Threat Language',
        'detail':   'Iranian officials threaten to close Hormuz -- escalatory signaling even before action',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🚢',
        'category': 'iran_trigger',
        'source':   'Escalation pattern -- Hormuz closure threats historically precede kinetic IRGC naval action',
    },
    {
        'id':       'us_carrier_deployment',
        'label':    'US Carrier Strike Group Persian Gulf Deployment',
        'detail':   'Additional US carrier deployed to Persian Gulf/Arabian Sea -- force posture signal to Iran',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🛳️',
        'category': 'adversary_trigger',
        'source':   'CENTCOM posture -- carrier deployment historically signals US strike readiness',
    },
]


# ============================================================
# HISTORICAL PRECEDENT LIBRARY
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'otp1_april_2024',
        'label':       'Operation True Promise 1 (April 2024)',
        'description': 'First direct Iranian ballistic missile attack on Israeli soil -- 300+ projectiles',
        'source':      'CSIS Missile Defense Project; INSS April 2024; ISW analysis',
        'signals': {
            'irgc_level_min':        4,
            'proxy_activation_min':  3,
            'otp_signals_min':       5,
            'us_iran_level_min':     3,
            'khamenei_level_min':    2,
        },
        'outcome':      'Direct Iranian ballistic + drone strike on Israel -- first in history. Israeli limited response within 72h.',
        'window_hours': 72,
        'confidence':   'High',
    },
    {
        'id':          'otp2_october_2024',
        'label':       'Operation True Promise 2 (October 2024)',
        'description': 'Second direct Iranian attack following Nasrallah assassination',
        'source':      'ISW / INSS post-event analysis, October 2024',
        'signals': {
            'irgc_level_min':        4,
            'proxy_activation_min':  2,
            'otp_signals_min':       3,
            'khamenei_level_min':    3,
        },
        'outcome':      'Iranian ballistic missile salvo at Israel. More limited than OTP1 -- Israeli/US interception successful.',
        'window_hours': 48,
        'confidence':   'High',
    },
    {
        'id':          'maximum_pressure_2019',
        'label':       'Iran Maximum Pressure Response (2019)',
        'description': 'IRGC tanker seizures and Abqaiq strike following US max pressure campaign',
        'source':      'IISS Strategic Survey 2020; CSIS Gulf Security Analysis',
        'signals': {
            'us_iran_level_min':     4,
            'irgc_level_min':        3,
            'hormuz_threat':         True,
            'khamenei_level_min':    2,
        },
        'outcome':      'IRGC seized tankers, struck Abqaiq oil facility via proxies. US did not respond militarily.',
        'window_hours': 168,
        'confidence':   'Medium',
    },
    {
        'id':          'soleimani_retaliation_2020',
        'label':       'Soleimani Assassination Retaliation (Jan 2020)',
        'description': 'Iranian ballistic missile strike on Al Asad airbase following Soleimani killing',
        'source':      'RAND Corporation; ISW; INSS January 2020 analysis',
        'signals': {
            'irgc_level_min':        5,
            'khamenei_level_min':    4,
            'us_iran_level_min':     5,
            'proxy_activation_min':  2,
        },
        'outcome':      'Iran fired 16 ballistic missiles at Al Asad -- first direct Iranian state attack on US forces.',
        'window_hours': 96,
        'confidence':   'High',
    },
    {
        'id':          'axis_coordination_otp4',
        'label':       'OTP4 Multi-Theater Coordination (2026)',
        'description': 'Iran coordinates simultaneous Hezbollah + Houthi + direct IRGC action',
        'source':      'Current pattern analysis -- Asifah Analytics cross-theater fingerprint',
        'signals': {
            'irgc_level_min':        4,
            'proxy_activation_min':  4,
            'otp_signals_min':       10,
            'us_iran_level_min':     2,
            'khamenei_level_min':    2,
        },
        'outcome':      'Sustained multi-theater campaign with numbered wave operations. Israeli/US response ongoing.',
        'window_hours': 48,
        'confidence':   'Medium',
    },
]


# ============================================================
# CORE SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """
    Evaluate current Iran signal state against each red line.
    Handles both Iran-trigger and adversary-trigger red lines.
    """
    actors       = scan_data.get('actors', {})
    fp           = scan_data

    irgc_level    = actors.get('irgc', {}).get('escalation_level', 0)
    khamenei_lv   = actors.get('khamenei', {}).get('escalation_level', 0)
    us_iran_lv    = actors.get('us_iran', {}).get('escalation_level', 0)
    israel_iran_lv = actors.get('israel_iran', {}).get('escalation_level', 0)

    irgc_count    = actors.get('irgc', {}).get('statement_count', 0)
    khamenei_cnt  = actors.get('khamenei', {}).get('statement_count', 0)

    otp_signals   = fp.get('operation_true_promise_count', fp.get('otp_signal_count', 0))
    proxy_level   = fp.get('proxy_activation_level', 0)
    theatre_score = fp.get('theatre_score', 0)
    theatre_level = fp.get('theatre_level', 0)

    # Check for Hormuz language across ALL actors + us_iran articles
    hormuz_threat = False
    bab_mandeb_threat = False
    for actor_id in actors:
        for art in actors.get(actor_id, {}).get('top_articles', []):
            title = art.get('title', '').lower()
            if any(kw in title for kw in ['hormuz', 'strait of hormuz', 'close strait',
                                           'block strait', 'hormuz strait', '48 hours',
                                           'open hormuz', 'hell', 'all hell']):
                hormuz_threat = True
            if any(kw in title for kw in ['bab el-mandeb', 'bab al-mandeb', 'mandeb',
                                           'red sea blockade', 'block red sea']):
                bab_mandeb_threat = True

    # Check for OTP wave acceleration (multiple waves in recent articles)
    otp_wave_count = 0
    for actor_id in ['irgc']:
        for art in actors.get(actor_id, {}).get('top_articles', []):
            title = art.get('title', '').lower()
            if 'wave' in title and ('true promise' in title or 'otp' in title):
                otp_wave_count += 1

    triggered = []

    # ── Direct US strike on Iran ──
    if us_iran_lv >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'direct_us_strike_iran'),
            'status':  'BREACHED' if us_iran_lv >= 5 else 'APPROACHING',
            'trigger': f'US/CENTCOM actor at L{us_iran_lv} -- strike posture language detected',
        })

    # ── Strait of Hormuz closure ──
    if hormuz_threat:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'strait_of_hormuz_closure'),
            'status':  'APPROACHING',
            'trigger': 'Hormuz closure/blocking language detected in Iranian actor statements',
        })

    # ── Nuclear threshold ──
    if israel_iran_lv >= 3 and theatre_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'nuclear_threshold_crossed'),
            'status':  'APPROACHING' if israel_iran_lv < 5 else 'BREACHED',
            'trigger': f'Israel re: Iran at L{israel_iran_lv} -- nuclear red line language elevated',
        })

    # ── OTP wave acceleration ──
    if otp_signals >= 10 or otp_wave_count >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'otp_wave_acceleration'),
            'status':  'BREACHED' if otp_signals >= 20 else 'APPROACHING',
            'trigger': f'{otp_signals} OTP signals detected, {otp_wave_count} wave announcements',
        })

    # ── Full proxy axis simultaneous activation ──
    if proxy_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'proxy_simultaneous_activation'),
            'status':  'BREACHED' if proxy_level >= 5 else 'APPROACHING',
            'trigger': f'Proxy activation level L{proxy_level} -- multiple theater coordination detected',
        })

    # ── Khamenei direct statement ──
    if khamenei_lv >= 3 and khamenei_cnt >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'khamenei_direct_statement'),
            'status':  'BREACHED' if khamenei_lv >= 4 else 'APPROACHING',
            'trigger': f'Khamenei at L{khamenei_lv} with {khamenei_cnt} statements -- direct authorization signal',
        })

    # ── Trump ultimatum -- scan articles at any level ──
    ultimatum_found = False
    for actor_id in ['us_iran', 'khamenei', 'iran_gov']:
        for art in actors.get(actor_id, {}).get('top_articles', []):
            title = art.get('title', '').lower()
            if any(kw in title for kw in ['ultimatum', '60 days', '48 hours', 'deadline',
                                           'final warning', 'last chance', 'all hell',
                                           'hell will rain', 'make a deal or', 'open hormuz']):
                ultimatum_found = True
                break
    if ultimatum_found or us_iran_lv >= 2:
        status = 'BREACHED' if ultimatum_found else 'APPROACHING'
        trigger = 'Ultimatum language detected in US/Trump statements -- forces Iranian response decision' if ultimatum_found \
                  else f'US/CENTCOM at L{us_iran_lv} -- escalatory pressure language present'
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'trump_iran_ultimatum'),
            'status':  status,
            'trigger': trigger,
        })

    # ── IRGC silence pre-operation ──
    if irgc_count == 0 and proxy_level >= 3 and theatre_score >= 50:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'irgc_silence_pre_op'),
            'status':  'APPROACHING',
            'trigger': f'IRGC 0 direct statements while proxy activation at L{proxy_level} -- operational security pattern',
        })

    # ── Hormuz transit threat ──
    if hormuz_threat:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'hormuz_transit_threat'),
            'status':  'BREACHED' if irgc_level >= 3 else 'APPROACHING',
            'trigger': f'Hormuz {"closure/48h ultimatum" if hormuz_threat else "threat"} language detected + IRGC L{irgc_level}',
        })

    # ── Bab el-Mandeb coordination signal (new -- Iran/Houthi chokepoint coordination) ──
    if bab_mandeb_threat:
        triggered.append({
            'id':       'bab_mandeb_coordination',
            'label':    'Bab el-Mandeb Blockade Signal',
            'detail':   'Iran hinting at Bab el-Mandeb blockade -- coordinates with Houthi Red Sea ops',
            'severity': 3,
            'color':    '#dc2626',
            'icon':     '🚢',
            'category': 'iran_trigger',
            'source':   'Strategic pattern -- simultaneous Hormuz+Mandeb threats = dual chokepoint strategy',
            'status':   'APPROACHING',
            'trigger':  'Bab el-Mandeb blockade language detected -- Iran/Houthi chokepoint coordination signal',
        })

    # ── US carrier deployment ──
    if us_iran_lv >= 3:
        for art in actors.get('us_iran', {}).get('top_articles', []):
            title = art.get('title', '').lower()
            if any(kw in title for kw in ['carrier', 'strike group', 'b-52', 'b-2', 'diego garcia', 'persian gulf']):
                triggered.append({
                    **next(r for r in RED_LINES if r['id'] == 'us_carrier_deployment'),
                    'status':  'APPROACHING',
                    'trigger': 'US carrier/strategic bomber deployment language detected',
                })
                break

    # Sort: BREACHED first, then severity
    triggered.sort(key=lambda x: (0 if x['status'] == 'BREACHED' else 1, -x['severity']))
    return triggered


def _match_historical(scan_data):
    """
    Match current Iran signal state against historical precedents.
    """
    actors       = scan_data.get('actors', {})
    fp           = scan_data

    irgc_level    = actors.get('irgc', {}).get('escalation_level', 0)
    khamenei_lv   = actors.get('khamenei', {}).get('escalation_level', 0)
    us_iran_lv    = actors.get('us_iran', {}).get('escalation_level', 0)
    proxy_level   = fp.get('proxy_activation_level', 0)
    otp_signals   = fp.get('operation_true_promise_count', fp.get('otp_signal_count', 0))

    # Hormuz check
    hormuz = False
    for actor_id in ['irgc', 'iran_gov']:
        for art in actors.get(actor_id, {}).get('top_articles', []):
            if any(kw in art.get('title', '').lower() for kw in ['hormuz', 'strait']):
                hormuz = True

    matches = []

    for precedent in HISTORICAL_PRECEDENTS:
        sigs = precedent['signals']
        score = 0
        max_score = 0
        matched_signals = []
        missed_signals = []

        def check(condition, label, weight=1):
            nonlocal score, max_score
            max_score += weight
            if condition:
                score += weight
                matched_signals.append(label)
            else:
                missed_signals.append(label)

        if 'irgc_level_min' in sigs:
            check(irgc_level >= sigs['irgc_level_min'],
                  f'IRGC L{irgc_level} ≥ L{sigs["irgc_level_min"]}', weight=3)

        if 'khamenei_level_min' in sigs:
            check(khamenei_lv >= sigs['khamenei_level_min'],
                  f'Khamenei L{khamenei_lv} ≥ L{sigs["khamenei_level_min"]}', weight=2)

        if 'proxy_activation_min' in sigs:
            check(proxy_level >= sigs['proxy_activation_min'],
                  f'Proxy activation L{proxy_level} ≥ L{sigs["proxy_activation_min"]}', weight=2)

        if 'otp_signals_min' in sigs:
            check(otp_signals >= sigs['otp_signals_min'],
                  f'{otp_signals} OTP signals ≥ {sigs["otp_signals_min"]}', weight=2)

        if 'us_iran_level_min' in sigs:
            check(us_iran_lv >= sigs['us_iran_level_min'],
                  f'US/Iran L{us_iran_lv} ≥ L{sigs["us_iran_level_min"]}', weight=1)

        if 'hormuz_threat' in sigs:
            check(hormuz == sigs['hormuz_threat'],
                  'Hormuz closure threat language', weight=2)

        if max_score == 0:
            continue

        similarity = round((score / max_score) * 100)

        if similarity >= 50:
            matches.append({
                'id':              precedent['id'],
                'label':           precedent['label'],
                'description':     precedent['description'],
                'source':          precedent['source'],
                'outcome':         precedent['outcome'],
                'window_hours':    precedent['window_hours'],
                'confidence':      precedent['confidence'],
                'similarity':      similarity,
                'matched_signals': matched_signals,
                'missed_signals':  missed_signals,
            })

    matches.sort(key=lambda x: x['similarity'], reverse=True)
    return matches[:3]


def _build_so_what(scan_data, red_lines_triggered, historical_matches):
    """
    Generate plain-language Iran command node assessment.
    Frame: Is Iran orchestrating a coordinated axis activation?
    """
    actors        = scan_data.get('actors', {})
    fp            = scan_data

    irgc_level    = actors.get('irgc', {}).get('escalation_level', 0)
    khamenei_lv   = actors.get('khamenei', {}).get('escalation_level', 0)
    us_iran_lv    = actors.get('us_iran', {}).get('escalation_level', 0)
    israel_iran_lv = actors.get('israel_iran', {}).get('escalation_level', 0)
    irgc_count    = actors.get('irgc', {}).get('statement_count', 0)

    theatre_score = fp.get('theatre_score', 0)
    theatre_level = fp.get('theatre_level', 0)
    proxy_level   = fp.get('proxy_activation_level', 0)
    otp_signals   = fp.get('operation_true_promise_count', fp.get('otp_signal_count', 0))
    delta         = fp.get('delta', {}) or {}
    delta_dir     = delta.get('direction', 'stable')
    score_change  = delta.get('score_change', 0)

    breached_count = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    top_match      = historical_matches[0] if historical_matches else None

    # ── Scenario label ──
    if theatre_level >= 5 and irgc_level >= 5:
        scenario       = 'ACTIVE COMMAND -- Iran Directing Multi-Theater Campaign'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif theatre_level >= 4 or (irgc_level >= 4 and proxy_level >= 3):
        scenario       = 'ELEVATED -- Iran Coordinating Proxy Activation'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif theatre_level >= 3 or irgc_level >= 3:
        scenario       = 'WARNING -- Escalatory Command Signals'
        scenario_color = '#f59e0b'
        scenario_icon  = '🟡'
    else:
        scenario       = 'MONITORING -- Below Escalation Threshold'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Situation ──
    situation_parts = []

    if irgc_level >= 4:
        otp_txt = f' -- Operation True Promise active ({otp_signals} wave signals detected)' if otp_signals >= 3 else ''
        situation_parts.append(
            f'Iran\'s IRGC is operating at L{irgc_level}{otp_txt}.'
        )

    if proxy_level >= 3:
        situation_parts.append(
            f'Proxy activation level L{proxy_level} -- Iran is coordinating simultaneous '
            f'operations across multiple theaters (Hezbollah, Houthi, PMF Iraq).'
        )

    if khamenei_lv >= 3:
        situation_parts.append(
            f'Supreme Leader Khamenei is at L{khamenei_lv} -- direct leadership authorization '
            f'signals present, not just IRGC spokesperson statements.'
        )

    if us_iran_lv >= 3:
        situation_parts.append(
            f'US/CENTCOM posture re: Iran at L{us_iran_lv} -- significant adversary pressure '
            f'signals including {"Trump direct statements and " if us_iran_lv >= 4 else ""}CENTCOM force posture language.'
        )

    if israel_iran_lv >= 3:
        situation_parts.append(
            f'Israeli strike posture re: Iran at L{israel_iran_lv} -- '
            f'IDF and war cabinet language targeting Iranian assets elevated.'
        )

    if delta_dir == 'rising' and score_change >= 8:
        situation_parts.append(
            f'Command node score rising sharply (+{round(score_change, 1)} from recent average) '
            f'-- accelerating trajectory, not steady-state.'
        )

    # ── Key indicators ──
    indicators = []

    if irgc_count == 0 and proxy_level >= 3:
        indicators.append(
            'IRGC has issued zero direct public statements while proxy activation is elevated -- '
            'operational security pattern historically precedes major IRGC operations.'
        )

    if otp_signals >= 10:
        indicators.append(
            f'{otp_signals} Operation True Promise signals detected -- numbered wave operations '
            f'indicate sustained coordinated campaign, not isolated strikes.'
        )

    if us_iran_lv >= 3 and israel_iran_lv >= 3:
        indicators.append(
            f'Both US (L{us_iran_lv}) and Israel (L{israel_iran_lv}) adversary postures elevated '
            f'simultaneously -- Iran facing dual-front pressure with limited diplomatic off-ramp.'
        )

    if breached_count >= 2:
        indicators.append(
            f'{breached_count} red lines currently breached or approaching -- '
            f'including adversary-defined thresholds that could trigger US/Israeli response.'
        )

    # ── Assessment ──
    assessment_parts = []

    if top_match and top_match['similarity'] >= 70:
        assessment_parts.append(
            f'Current signal pattern shows {top_match["similarity"]}% similarity to '
            f'{top_match["label"]}. In that case: {top_match["outcome"].lower()}'
        )
        assessment_parts.append(
            f'Assess: Iran is operating in command node mode -- directing rather than merely '
            f'supporting proxy operations. Confidence: {top_match["confidence"]} -- '
            f'{_confidence_caveat(top_match["confidence"])}.'
        )
        assessment_parts.append(
            f'Historical response window in comparable scenarios: {top_match["window_hours"]} hours. '
            f'Analytical estimate only -- not a prediction.'
        )
    elif top_match and top_match['similarity'] >= 50:
        assessment_parts.append(
            f'Partial pattern match ({top_match["similarity"]}%) to {top_match["label"]}. '
            f'Signals are suggestive but not conclusive of imminent escalation.'
        )
    else:
        if theatre_level >= 3:
            assessment_parts.append(
                'Active command node signals present. No strong historical pattern match -- '
                'situation may be evolving in novel direction or data insufficient for confident pattern match.'
            )

    # ── Watch list ──
    watch_items = []
    if irgc_count == 0:
        watch_items.append('IRGC public statements resuming (signals decision made or operation underway)')
    watch_items.append('Strait of Hormuz -- any Iranian naval movement or mining language')
    watch_items.append('Trump/Rubio direct Iran statements (ultimatum language = forced Iranian response)')
    watch_items.append('IDF strike posture changes (Israeli preemptive action would reset Iranian calculus)')
    watch_items.append('NOTAM closures over Iranian or Israeli airspace')
    if otp_signals >= 5:
        watch_items.append(f'OTP wave count -- currently at {otp_signals} signals, acceleration = escalation')

    return {
        'scenario':        scenario,
        'scenario_color':  scenario_color,
        'scenario_icon':   scenario_icon,
        'situation':       ' '.join(situation_parts),
        'key_indicators':  indicators,
        'assessment':      ' '.join(assessment_parts),
        'watch_list':      watch_items[:5],
        'generated_at':    datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Iran command node assessment generated from open-source signal data. '
            'Not a prediction. Verify through official channels before any operational decision.'
        ),
    }


def _confidence_caveat(label):
    caveats = {
        'High':       'multiple strong signal matches with well-documented precedent',
        'Medium':     'partial signal match; outcome not determinative',
        'Medium-Low': 'pattern suggestive but historical base rate limited',
        'Low':        'weak match only -- treat as background signal',
    }
    return caveats.get(label, 'confidence assessment pending more data')


# ============================================================
# COMMODITY PRESSURE EXTRACTION (Phase 2B)
# ============================================================
# Reads commodity-pressure data injected into scan_data by
# rhetoric_tracker_iran.py (which fetches it from the shared
# commodity_tracker_cache Redis key).
#
# Iran has 5 commodity exposures (defined in commodity_tracker.py):
#   oil           -- producer, Hormuz leverage           → dual_chokepoint
#   natural_gas   -- producer, Hormuz/sanctions          → dual_chokepoint
#   uranium       -- producer, nuclear program           → nuclear_signaling
#   gold          -- consumer, sanctions evasion         → commodity_pressure (NEW)
#   wheat         -- consumer, bread/regime stability    → commodity_pressure (NEW)
#
# The first three map to existing Iran categories (oil/gas reinforce
# Hormuz signal; uranium reinforces nuclear signal). Gold and wheat
# are genuinely different stories (sanctions evasion + domestic
# stability) and need their own category.
# ============================================================

# Commodity → canonical category mapping for Iran
_IRAN_COMMODITY_CATEGORY_MAP = {
    'oil':         'dual_chokepoint',
    'natural_gas': 'dual_chokepoint',
    'uranium':     'nuclear_signaling',
    'gold':        'commodity_pressure',
    'wheat':       'commodity_pressure',
}

# Threshold: only emit if global commodity is at this level or above
# normal=skip, elevated=skip (too much noise), high=emit, surge=emit (priority boost)
_IRAN_COMMODITY_EMIT_THRESHOLD = {'high', 'surge'}


def _extract_commodity_signals(scan_data):
    """
    Extract canonical-schema signals from commodity_pressure data.

    Looks for scan_data['commodity_pressure'] (injected by rhetoric_tracker_iran
    after it reads commodity_tracker_cache from Redis). Returns a list of
    canonical signal dicts ready to merge into top_signals[].

    Expected input shape (from commodity_tracker.get_commodity_pressure('iran')):
        {
            'commodity_pressure': N,
            'alert_level': 'normal'|'elevated'|'high'|'surge',
            'commodity_summaries': [
                {
                    'commodity': 'oil',
                    'name': 'Oil',
                    'icon': '🛢️',
                    'role': 'producer',
                    'rank': 6,
                    'note': '...',
                    'signal_count': N,
                    'global_alert_level': 'normal'|...,
                    'global_signal_count': N,
                    ...
                },
                ...
            ],
        }

    Returns: list of canonical signal dicts (may be empty).
    """
    signals = []

    cp = scan_data.get('commodity_pressure') or {}
    summaries = cp.get('commodity_summaries') or []
    if not summaries:
        return signals

    # Iran-flag emoji constant (already defined elsewhere in module)
    iran_flag = '\U0001f1ee\U0001f1f7'

    # Track categories already emitted, to avoid duplicates from oil+gas
    # both mapping to dual_chokepoint. NOTE: commodity_pressure is allowed
    # to emit multiple times (gold and wheat are genuinely different stories).
    emitted_categories = set()
    _DEDUPE_CATEGORIES = {'dual_chokepoint', 'nuclear_signaling'}

    for summary in summaries:
        commodity_id = str(summary.get('commodity', '')).lower()
        if not commodity_id:
            continue

        category = _IRAN_COMMODITY_CATEGORY_MAP.get(commodity_id)
        if not category:
            continue  # Unknown commodity for Iran, skip

        # Use GLOBAL alert level (e.g. wheat surging worldwide is meaningful
        # for Iran the consumer even if Iran-specific signals are quiet)
        global_alert = str(summary.get('global_alert_level', 'normal')).lower()
        if global_alert not in _IRAN_COMMODITY_EMIT_THRESHOLD:
            continue

        # Dedupe ONLY for categories where multiple commodities reinforce
        # the same narrative (oil+gas → dual_chokepoint, both sing Hormuz).
        # commodity_pressure category covers gold AND wheat which are
        # different stories — let both emit.
        if category in _DEDUPE_CATEGORIES and category in emitted_categories:
            continue
        emitted_categories.add(category)

        commodity_name = summary.get('name', commodity_id.title())
        commodity_icon = summary.get('icon', '📊')
        role           = summary.get('role', '')
        rank           = summary.get('rank')
        signal_count   = int(summary.get('global_signal_count', 0) or 0)
        is_surge       = (global_alert == 'surge')

        # ── Build signal based on category ──────────────────
        if category == 'dual_chokepoint':
            # Reinforces Hormuz/oil-gas chokepoint story — Iran as producer
            priority   = 12 if is_surge else 11
            level      = 5 if is_surge else 4
            color      = '#dc2626' if is_surge else '#f97316'
            rank_txt   = f' (#{rank} producer)' if rank else ''
            short_text = (f'{iran_flag} IRAN: {commodity_name} market '
                          f'{global_alert.upper()}{rank_txt}')
            long_text  = (f'{iran_flag} IRAN {commodity_name} commodity pressure '
                          f'{global_alert.upper()}: {signal_count} global signals. '
                          f'Iran is {role}{rank_txt}. Hormuz transit leverage '
                          f'reinforces chokepoint signal.')
            icon = '⚓'

        elif category == 'nuclear_signaling':
            # Reinforces nuclear program story
            priority   = 12 if is_surge else 11
            level      = 5 if is_surge else 4
            color      = '#dc2626' if is_surge else '#f97316'
            short_text = (f'{iran_flag} IRAN: Uranium market '
                          f'{global_alert.upper()} (nuclear signal)')
            long_text  = (f'{iran_flag} IRAN uranium commodity pressure '
                          f'{global_alert.upper()}: {signal_count} global signals. '
                          f'Reinforces nuclear program signaling — '
                          f'Natanz/Fordow/enrichment narrative.')
            icon = '☢️'

        elif category == 'commodity_pressure':
            # Gold (sanctions evasion) or wheat (regime stability)
            if commodity_id == 'gold':
                priority   = 9 if is_surge else 8
                level      = 4 if is_surge else 3
                color      = '#f59e0b' if is_surge else '#facc15'
                short_text = (f'{iran_flag} IRAN: Gold market '
                              f'{global_alert.upper()} (sanctions evasion)')
                long_text  = (f'{iran_flag} IRAN gold commodity pressure '
                              f'{global_alert.upper()}: {signal_count} global signals. '
                              f'Iran-Russia-China gold trade + central bank '
                              f'reserve diversification under sanctions.')
                icon = '🥇'
            elif commodity_id == 'wheat':
                priority   = 10 if is_surge else 9
                level      = 4 if is_surge else 3
                color      = '#f59e0b' if is_surge else '#facc15'
                short_text = (f'{iran_flag} IRAN: Wheat market '
                              f'{global_alert.upper()} (bread / regime risk)')
                long_text  = (f'{iran_flag} IRAN wheat commodity pressure '
                              f'{global_alert.upper()}: {signal_count} global signals. '
                              f'Iran net importer ~5-7M tonnes/yr. Subsidized '
                              f'bread = political stability lever (1979 echo).')
                icon = '🌾'
            else:
                # Generic fallback (shouldn't happen given the map)
                priority   = 8
                level      = 3
                color      = '#facc15'
                short_text = (f'{iran_flag} IRAN: {commodity_name} market '
                              f'{global_alert.upper()}')
                long_text  = (f'{iran_flag} IRAN {commodity_name} commodity '
                              f'pressure {global_alert.upper()}.')
                icon = commodity_icon

        else:
            continue  # Defensive: unknown category

        signals.append({
            'priority':   priority,
            'category':   category,
            'theatre':    'iran',
            'level':      level,
            'icon':       icon,
            'color':      color,
            'short_text': short_text[:80],
            'long_text':  long_text[:200],
        })

    return signals


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Takes full scan_data dict from rhetoric_tracker_iran.
    Returns structured interpretation dict added to API response as
    result['interpretation'].
    """
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
        print(f'[Iran Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what':            {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines':          {'triggered': [], 'breached_count': 0, 'approaching_count': 0, 'highest_severity': 0},
            'historical_matches': [],
            'interpreter_version': '1.0.0',
            'error':              str(e)[:200],
        }


# ============================================================
# CANONICAL SIGNAL EMITTER (v2.0)
# ============================================================
# Iran is the COMMAND NODE — its signals carry the richest cross-theater
# weight in the platform. This emitter maps Iran's six-vector matrix
# (irgc_direct / proxy_activation / nuclear / domestic / regional /
# soft_power) plus the diplomatic track plus axis posture (China-Iran,
# Russia-Iran) into canonical platform-wide signal categories consumed
# by me_regional_bluf.py and global_pressure_index.py.
#
# Categories Iran emits:
#   red_line_breached            -- severity 3 red lines triggered
#   nuclear_signaling            -- nuclear_level >= 3 (GPI cross-theater)
#   dual_chokepoint              -- Hormuz mining/closure language (paired
#                                   with Yemen BAM = global supply-chain risk)
#   kinetic_pressure             -- IRGC direct L4+ or active OTP wave
#   crosstheater_iran_proxies    -- proxy_activation_level >= 4
#                                   (Hezbollah/Houthi/IRGC orchestration)
#   crosstheater_russia_iran     -- russia_iran axis activation
#   crosstheater_china_iran      -- china_iran axis activation
#   theatre_high                 -- composite L4+ catch-all
#   regime_fracture              -- domestic stress L4+
#   influence_high               -- soft_power / influence ops L3+
#                                   (PressTV, Lego/rap viral, "resistance" framing)
#   silence_anomaly              -- IRGC/Khamenei suspicious quiet
#   diplomatic_active            -- ceasefire_level >= 2 (off-ramp)
#   commodity_pressure           -- Gold sanctions evasion / wheat bread
#                                   stability surge (oil/gas reinforce
#                                   dual_chokepoint, uranium reinforces
#                                   nuclear_signaling — see _extract_
#                                   commodity_signals helper)
# ============================================================

IRAN_FLAG = '\U0001f1ee\U0001f1f7'  # 🇮🇷

_IRAN_ESC_LABELS = {
    0: 'Monitoring',
    1: 'Routine',
    2: 'Elevated Rhetoric',
    3: 'Heightened Posture',
    4: 'Active Signaling',
    5: 'Active Conflict',
}


def build_top_signals(scan_data):
    """
    Convert Iran scan_data into canonical top_signals[] for ME regional BLUF
    and Global Pressure Index. Returns a list (possibly empty), sorted by
    priority desc.

    Signal schema (canonical platform-wide):
        priority   int 0-15  (higher == more urgent)
        category   str       (canonical bucket)
        theatre    'iran'
        level      int 0-5
        icon       str (emoji)
        color      str (hex)
        short_text str (<=80 char)
        long_text  str (<=200 char)
    """
    signals = []

    interp        = scan_data.get('interpretation') or {}
    so_what       = interp.get('so_what') or {}
    rl_block      = interp.get('red_lines') or {}
    triggered_rls = rl_block.get('triggered') or []

    theatre_level   = int(scan_data.get('theatre_level', 0) or 0)
    theatre_score   = int(scan_data.get('theatre_score', 0) or 0)
    irgc_lvl        = int(scan_data.get('irgc_direct_level', 0) or 0)
    proxy_lvl       = int(scan_data.get('proxy_activation_level', 0) or 0)
    nuclear_lvl     = int(scan_data.get('nuclear_level', 0) or 0)
    domestic_lvl    = int(scan_data.get('domestic_level', 0) or 0)
    regional_lvl    = int(scan_data.get('regional_level', 0) or 0)
    soft_power_lvl  = int(scan_data.get('soft_power_level', 0) or 0)
    ceasefire_lvl   = int(scan_data.get('ceasefire_level', 0) or 0)
    otp_count       = int(scan_data.get('operation_true_promise_count', 0) or 0)

    actors          = scan_data.get('actors') or {}
    silence_alerts  = scan_data.get('silence_anomalies') or []

    # ── Color helpers ────────────────────────────────────────────────
    def lvl_color(lvl):
        return {0:'#6b7280', 1:'#16a34a', 2:'#facc15', 3:'#f59e0b',
                4:'#f97316', 5:'#dc2626'}.get(int(lvl), '#6b7280')

    # ── 1. Red lines BREACHED ────────────────────────────────────────
    for rl in triggered_rls:
        if not isinstance(rl, dict):
            continue
        if rl.get('status') != 'BREACHED':
            continue
        sev   = int(rl.get('severity', 0) or 0)
        label = str(rl.get('label', 'Red line'))[:55]
        # Hormuz red line gets special dual_chokepoint flavor
        rl_id = str(rl.get('id', '')).lower()
        if 'hormuz' in rl_id or 'hormuz' in label.lower():
            signals.append({
                'priority':   13,
                'category':   'dual_chokepoint',
                'theatre':    'iran',
                'level':      max(theatre_level, 4),
                'icon':       '⚓',
                'color':      '#dc2626',
                'short_text': (f'{IRAN_FLAG} IRAN: Hormuz chokepoint pressure — '
                               f'{label[:35]}'),
                'long_text':  (f'{IRAN_FLAG} IRAN Strait of Hormuz pressure language '
                               f'detected: {rl.get("label", "")[:130]}. '
                               f'Watch Yemen BAM for paired chokepoint risk.'),
            })
            continue
        # Nuclear red line gets nuclear_signaling category
        if 'nuclear' in rl_id or 'nuclear' in label.lower():
            signals.append({
                'priority':   13,
                'category':   'nuclear_signaling',
                'theatre':    'iran',
                'level':      max(theatre_level, 4),
                'icon':       '☢️',
                'color':      '#dc2626',
                'short_text': (f'{IRAN_FLAG} IRAN: Nuclear red line — {label[:40]}'),
                'long_text':  (f'{IRAN_FLAG} IRAN nuclear red line breached: '
                               f'{rl.get("label", "")[:130]}'),
            })
            continue
        # Generic breach
        signals.append({
            'priority':   12 if sev >= 3 else 10,
            'category':   'red_line_breached',
            'theatre':    'iran',
            'level':      max(theatre_level, 4),
            'icon':       rl.get('icon', '🚨'),
            'color':      '#dc2626',
            'short_text': f'{IRAN_FLAG} IRAN: BREACH — {label}',
            'long_text':  (f'{IRAN_FLAG} IRAN red line breached: '
                           f'{rl.get("label", "")[:140]}'),
        })

    # ── 2. Nuclear signaling (vector >= 3, even without red-line breach) ──
    if nuclear_lvl >= 3:
        signals.append({
            'priority':   10 + nuclear_lvl,   # L3=13, L4=14, L5=15
            'category':   'nuclear_signaling',
            'theatre':    'iran',
            'level':      nuclear_lvl,
            'icon':       '☢️',
            'color':      lvl_color(nuclear_lvl),
            'short_text': (f'{IRAN_FLAG} IRAN: Nuclear posture L{nuclear_lvl} '
                           f'({_IRAN_ESC_LABELS.get(nuclear_lvl, "")})'),
            'long_text':  (f'{IRAN_FLAG} IRAN nuclear vector L{nuclear_lvl} — '
                           f'enrichment / breakout / facility signaling above '
                           f'baseline. JCPOA / Natanz / Fordow language elevated.'),
        })

    # ── 3. Kinetic pressure: IRGC direct L4+ or OTP wave ─────────────
    if irgc_lvl >= 4 or otp_count >= 5:
        kinetic_lvl = max(irgc_lvl, 4 if otp_count >= 5 else 0)
        otp_note = f' OTP wave at {otp_count} signals.' if otp_count >= 5 else ''
        signals.append({
            'priority':   9 + kinetic_lvl,    # L4=13, L5=14
            'category':   'kinetic_pressure',
            'theatre':    'iran',
            'level':      kinetic_lvl,
            'icon':       '🚀',
            'color':      lvl_color(kinetic_lvl),
            'short_text': (f'{IRAN_FLAG} IRAN: IRGC direct L{irgc_lvl}'
                           f'{" + OTP wave" if otp_count >= 5 else ""}'),
            'long_text':  (f'{IRAN_FLAG} IRAN IRGC direct vector L{irgc_lvl} '
                           f'({_IRAN_ESC_LABELS.get(irgc_lvl, "")}).{otp_note} '
                           f'Operation True Promise = direct missile/drone '
                           f'retaliation signaling.'),
        })

    # ── 4. Cross-theater proxy orchestration (axis activation) ───────
    if proxy_lvl >= 4:
        signals.append({
            'priority':   10 + (proxy_lvl - 4),  # L4=10, L5=11
            'category':   'crosstheater_iran_proxies',
            'theatre':    'iran',
            'level':      proxy_lvl,
            'icon':       '🕸️',
            'color':      '#7c3aed',
            'short_text': (f'{IRAN_FLAG} IRAN: Proxy activation L{proxy_lvl} '
                           f'(axis orchestrating)'),
            'long_text':  (f'{IRAN_FLAG} IRAN proxy activation L{proxy_lvl} — '
                           f'Hezbollah (Hizbullah), Houthis, Iraqi militias, '
                           f'PMF coordinated directive language detected. '
                           f'Command node tempo elevated.'),
        })

    # ── 5. Cross-theater axis: Russia-Iran ───────────────────────────
    russia_actor = actors.get('russia_iran_axis') or {}
    russia_lvl   = int(russia_actor.get('max_level',
                       russia_actor.get('escalation_level', 0)) or 0)
    if russia_lvl >= 3:
        signals.append({
            'priority':   10,
            'category':   'crosstheater_russia_iran',
            'theatre':    'iran',
            'level':      russia_lvl,
            'icon':       '🇷🇺',
            'color':      '#7c3aed',
            'short_text': (f'{IRAN_FLAG} IRAN: Russia-Iran axis L{russia_lvl}'),
            'long_text':  (f'{IRAN_FLAG} IRAN Russia-Iran axis L{russia_lvl} '
                           f'— Moscow-Tehran defense / drone / sanctions '
                           f'coordination signaling above baseline.'),
        })

    # ── 6. Cross-theater axis: China-Iran ────────────────────────────
    china_actor = actors.get('china_iran_axis') or {}
    china_lvl   = int(china_actor.get('max_level',
                      china_actor.get('escalation_level', 0)) or 0)
    if china_lvl >= 3:
        signals.append({
            'priority':   10,
            'category':   'crosstheater_china_iran',
            'theatre':    'iran',
            'level':      china_lvl,
            'icon':       '🇨🇳',
            'color':      '#7c3aed',
            'short_text': (f'{IRAN_FLAG} IRAN: China-Iran axis L{china_lvl}'),
            'long_text':  (f'{IRAN_FLAG} IRAN China-Iran axis L{china_lvl} '
                           f'— Beijing-Tehran economic / oil / diplomatic '
                           f'cover signaling above baseline.'),
        })

    # ── 7. Theatre composite high (catch-all) ────────────────────────
    if theatre_level >= 4 or theatre_score >= 70:
        signals.append({
            'priority':   9,
            'category':   'theatre_high',
            'theatre':    'iran',
            'level':      theatre_level,
            'icon':       '🔴' if theatre_level >= 4 else '🟠',
            'color':      lvl_color(theatre_level),
            'short_text': (f'{IRAN_FLAG} IRAN L{theatre_level} — '
                           f'{_IRAN_ESC_LABELS.get(theatre_level, "")}'),
            'long_text':  (f'{IRAN_FLAG} IRAN command node at L{theatre_level} '
                           f'{_IRAN_ESC_LABELS.get(theatre_level, "")} '
                           f'(score {theatre_score}/100).'),
        })

    # ── 8. Regime fracture: domestic stress ──────────────────────────
    if domestic_lvl >= 4:
        signals.append({
            'priority':   9,
            'category':   'regime_fracture',
            'theatre':    'iran',
            'level':      domestic_lvl,
            'icon':       '🪧',
            'color':      lvl_color(domestic_lvl),
            'short_text': (f'{IRAN_FLAG} IRAN: Domestic stress L{domestic_lvl}'),
            'long_text':  (f'{IRAN_FLAG} IRAN domestic vector L{domestic_lvl} — '
                           f'protest / strike / clerical fracture / IRGC '
                           f'internal coercion language elevated.'),
        })

    # ── 9. Influence operations / soft power (Iran-specific) ─────────
    if soft_power_lvl >= 3:
        signals.append({
            'priority':   7 + soft_power_lvl,   # L3=10, L4=11, L5=12
            'category':   'influence_high',
            'theatre':    'iran',
            'level':      soft_power_lvl,
            'icon':       '📡',
            'color':      '#0ea5e9',
            'short_text': (f'{IRAN_FLAG} IRAN: Influence ops L{soft_power_lvl} '
                           f'(PressTV / viral media)'),
            'long_text':  (f'{IRAN_FLAG} IRAN soft-power vector L{soft_power_lvl} '
                           f'— Iranian state media (PressTV, Tasnim) / viral '
                           f'artifacts / "resistance" framing targeting Western '
                           f'audiences elevated.'),
        })

    # ── 10. Silence anomalies (Khamenei/IRGC suspicious quiet) ───────
    for sa in silence_alerts[:2]:
        if not isinstance(sa, dict):
            continue
        actor_id   = sa.get('actor_id', 'actor')
        actor_name = sa.get('actor_name', actor_id)
        # IRGC silence is the most operationally significant
        is_irgc = 'irgc' in str(actor_id).lower() or 'khamenei' in str(actor_id).lower()
        signals.append({
            'priority':   11 if is_irgc else 9,
            'category':   'silence_anomaly',
            'theatre':    'iran',
            'level':      4 if is_irgc else 3,
            'icon':       '🔇',
            'color':      '#dc2626' if is_irgc else '#f59e0b',
            'short_text': (f'{IRAN_FLAG} IRAN: Silence anomaly — '
                           f'{actor_name[:35]}'),
            'long_text':  (f'{IRAN_FLAG} IRAN unusual silence from '
                           f'{actor_name}. '
                           f'{"IRGC quiet during active tempo = operational " if is_irgc else ""}'
                           f'{"planning indicator." if is_irgc else "May indicate message coordination or internal stress."}'),
        })

    # ── 11. Diplomatic active (off-ramp signaling) ───────────────────
    if ceasefire_lvl >= 2:
        prio = 6 + min(ceasefire_lvl, 3)   # L2=8, L3=9, L4=9, L5=9
        dipl_label = scan_data.get('diplomatic_label_detailed', 'Diplomatic Push')
        signals.append({
            'priority':   prio,
            'category':   'diplomatic_active',
            'theatre':    'iran',
            'level':      ceasefire_lvl,
            'icon':       '🕊️',
            'color':      '#10b981',
            'short_text': (f'{IRAN_FLAG} IRAN: Diplomatic track L{ceasefire_lvl} '
                           f'({dipl_label})'),
            'long_text':  (f'{IRAN_FLAG} IRAN diplomatic momentum L{ceasefire_lvl} '
                           f'— {dipl_label}. Witkoff envoy / Muscat back-channel '
                           f'/ JCPOA framing detected. Modifier: '
                           f'{scan_data.get("diplomatic_modifier", 0)} pts.'),
        })

    # ── 12. Commodity pressure (Phase 2B) ────────────────────────────
    # Pull from commodity_pressure dict injected by rhetoric_tracker_iran.
    # Maps to 3 categories: dual_chokepoint (oil/gas), nuclear_signaling
    # (uranium), commodity_pressure (gold/wheat). Helper handles dedupe
    # so oil+gas don't both emit dual_chokepoint.
    try:
        commodity_signals = _extract_commodity_signals(scan_data)
        if commodity_signals:
            signals.extend(commodity_signals)
    except Exception as _cp_err:
        # Non-fatal — never let a commodity bug break top_signals
        print(f'[Iran Interpreter] Commodity signals error (non-fatal): {str(_cp_err)[:100]}')

    # ── Sort and return ──────────────────────────────────────────────
    signals.sort(key=lambda s: s.get('priority', 0), reverse=True)
    return signals


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    test_data = {
        'theatre_score':          56,
        'theatre_level':          5,
        'proxy_activation_level': 4,
        'otp_signal_count':       79,
        'delta': {'direction': 'stable', 'score_change': 2.1},
        'actors': {
            'irgc':        {'escalation_level': 5, 'statement_count': 0, 'top_articles': []},
            'khamenei':    {'escalation_level': 2, 'statement_count': 1, 'top_articles': []},
            'iran_gov':    {'escalation_level': 1, 'statement_count': 4, 'top_articles': []},
            'us_iran':     {'escalation_level': 3, 'statement_count': 2, 'top_articles': [
                {'title': 'Trump warns Iran: 60 days to make deal or face consequences', 'published': ''}
            ]},
            'israel_iran': {'escalation_level': 3, 'statement_count': 5, 'top_articles': []},
            'houthi_iran': {'escalation_level': 4, 'statement_count': 8, 'top_articles': []},
            'hezbollah_iran': {'escalation_level': 5, 'statement_count': 12, 'top_articles': []},
        },
    }

    result = interpret_signals(test_data)

    print('\n' + '='*60)
    print('SCENARIO:', result['so_what']['scenario'])
    print('='*60)
    print('\nSITUATION:')
    print(result['so_what']['situation'])
    print('\nKEY INDICATORS:')
    for ind in result['so_what']['key_indicators']:
        print(f'  • {ind}')
    print('\nASSESSMENT:')
    print(result['so_what']['assessment'])
    print('\nWATCH LIST:')
    for item in result['so_what']['watch_list']:
        print(f'  → {item}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} (Sev {rl["severity"]})')
        print(f'     {rl["trigger"]}')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]}')
        print(f'     {hm["outcome"]}')
        print(f'     Window: {hm["window_hours"]}h | Confidence: {hm["confidence"]}')
