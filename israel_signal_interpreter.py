"""
israel_signal_interpreter.py
Asifah Analytics — ME Backend Module
v1.0.0 - April 4, 2026 v1

Signal interpretation engine for the Israel Rhetoric Tracker.
Provides three analytical outputs from current tracker state:

  1. So What Summary  — plain-language executive assessment
  2. Red Line Status  — proximity scoring against Israel's stated red lines
  3. Historical Match — pattern matching against documented pre-action signals

Called by rhetoric_tracker_israel.py after scan completes.
Returns structured dict consumed by /api/rhetoric/israel endpoint.
Frontend renders three new cards on rhetoric-israel.html.

Architecture:
  _score_red_lines()      → red line proximity scores
  _match_historical()     → pattern match against precedent library
  _build_so_what()        → plain language summary from scored signals
  interpret_signals()     → public entry point, returns full interpretation dict

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS
# Israel's publicly stated and analytically documented red lines.
# Each has a trigger condition, severity, and plain-language label.
# Severity: 1 (approaching) → 2 (crossed) → 3 (critical breach)
# ============================================================
RED_LINES = [
    {
        'id':        'nuclear_facility_targeting',
        'label':     'Nuclear Facility Targeted',
        'detail':    'Dimona or Nahal Soreq explicitly targeted by adversary fire',
        'severity':  3,
        'color':     '#dc2626',
        'icon':      '☢️',
        'source':    'Israeli doctrine — stated red line, multiple senior official statements',
    },
    {
        'id':        'multi_axis_simultaneous',
        'label':     'Simultaneous Multi-Axis Attack',
        'detail':    'Iran + Hezbollah + Houthi all elevated (≥L3) simultaneously',
        'severity':  3,
        'color':     '#dc2626',
        'icon':      '🔱',
        'source':    'INSS analysis — coordinated axis attack triggers automatic escalation review',
    },
    {
        'id':        'houthi_ballistic_strategic',
        'label':     'Houthi Ballistic / Hypersonic Strike',
        'detail':    'Houthi ballistic or hypersonic missile targeting Israeli population centers or military sites',
        'severity':  2,
        'color':     '#f97316',
        'icon':      '🚀',
        'source':    'Escalation pattern — harder-to-intercept systems represent qualitative escalation',
    },
    {
        'id':        'iran_direct_ballistic',
        'label':     'Iran Direct Ballistic Strike on Israeli Soil',
        'detail':    'IRGC ballistic missiles confirmed impacting Israeli territory',
        'severity':  3,
        'color':     '#dc2626',
        'icon':      '💥',
        'source':    'Operation True Promise precedent — direct state-on-state attack triggers response',
    },
    {
        'id':        'hezbollah_mass_rocket',
        'label':     'Hezbollah Mass Rocket Barrage',
        'detail':    'Hezbollah rocket rate exceeds 30/24h targeting multiple population centers',
        'severity':  2,
        'color':     '#f97316',
        'icon':      '🎯',
        'source':    'IDF doctrine — sustained mass fire triggers escalation authorization review',
    },
    {
        'id':        'hezbollah_litani_crossing',
        'label':     'Hezbollah Crosses Litani River',
        'detail':    'Hezbollah ground forces operating south of Litani River in force',
        'severity':  3,
        'color':     '#dc2626',
        'icon':      '🌊',
        'source':    'UN SCR 1701 red line — IDF has stated this triggers ground operation',
    },
    {
        'id':        'us_brake_absent_escalation',
        'label':     'US Brake Signal Absent During Escalation',
        'detail':    'No US coordination/restraint signals while inbound threat score exceeds 80',
        'severity':  2,
        'color':     '#f97316',
        'icon':      '🟡',
        'source':    'Historical pattern — US silence during escalation historically precedes Israeli action',
    },
    {
        'id':        'cabinet_silence_pre_strike',
        'label':     'War Cabinet Operational Silence',
        'detail':    'War cabinet statement count drops to zero during active multi-axis attack',
        'severity':  2,
        'color':     '#f97316',
        'icon':      '🤫',
        'source':    'Operational security pattern — cabinet silence precedes strike authorization',
    },
]


# ============================================================
# HISTORICAL PRECEDENT LIBRARY
# Documented pre-action signal patterns from open-source analysis.
# Each entry: signal fingerprint → documented outcome.
# Sources: INSS, IISS, CSIS, ISW, Bellingcat post-event analysis.
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'operation_rising_lion_2024',
        'label':       'Operation Rising Lion (April 2024)',
        'description': 'Israeli multi-site strike on Iran following Operation True Promise 1',
        'source':      'ISW / INSS post-event analysis, April 2024',
        'signals': {
            'iran_level_min':        4,
            'hezbollah_level_min':   3,
            'cabinet_silence':       True,
            'us_coordination_min':   0,   # US absent or brake-only
            'inbound_score_min':     75,
            'delta_direction':       'rising',
        },
        'outcome':     'Israeli precision strikes on Iranian military infrastructure within 72 hours',
        'window_hours': 72,
        'confidence':  'Medium',
    },
    {
        'id':          'iron_swords_launch_2023',
        'label':       'Operation Iron Swords Launch (October 2023)',
        'description': 'Full IDF mobilization following Hamas mass infiltration attack',
        'source':      'IISS Strategic Comments, November 2023; Bellingcat October 2023',
        'signals': {
            'iran_level_min':        3,
            'hezbollah_level_min':   2,
            'cabinet_silence':       False,  # Cabinet was publicly authorizing
            'inbound_score_min':     85,
            'delta_direction':       'rising',
            'asymmetric_level_min':  3,
        },
        'outcome':     'Full ground operation authorization within 24 hours of mass casualty event',
        'window_hours': 24,
        'confidence':  'High',
    },
    {
        'id':          'april_2024_exchange',
        'label':       'Iran-Israel Direct Exchange (April 2024)',
        'description': 'First direct Iranian ballistic attack on Israeli soil; Israeli response',
        'source':      'CSIS Missile Defense Project, May 2024; INSS analysis April 2024',
        'signals': {
            'iran_level_min':        5,
            'houthi_level_min':      3,
            'ballistic_level_min':   3,
            'cabinet_silence':       True,
            'us_coordination_min':   0,
            'inbound_score_min':     80,
            'delta_direction':       'rising',
        },
        'outcome':     'Israeli limited strike on Iranian air defense radar within 72 hours',
        'window_hours': 72,
        'confidence':  'Medium',
    },
    {
        'id':          'pre_strike_silence_pattern',
        'label':       'Pre-Strike Cabinet Silence Pattern (Multiple)',
        'description': 'Recurring pattern: War cabinet goes silent 24-48h before strike authorization',
        'source':      'INSS "Decision-Making in Crisis" series; multiple documented cases 2023-2024',
        'signals': {
            'cabinet_silence':       True,
            'inbound_score_min':     70,
            'delta_direction':       'rising',
            'us_coordination_min':   0,
        },
        'outcome':     'Strike authorization issued within 24-48 hours in majority of documented cases',
        'window_hours': 48,
        'confidence':  'Medium-Low',
    },
    {
        'id':          'axis_coordination_escalation',
        'label':       'Full Axis Simultaneous Activation',
        'description': 'Iran + Hezbollah + Houthi coordinated elevation preceding Israeli action',
        'source':      'CSIS "Iranian Proxy Networks" 2024; ISW Iran coverage',
        'signals': {
            'iran_level_min':        4,
            'hezbollah_level_min':   4,
            'houthi_level_min':      3,
            'inbound_score_min':     80,
            'delta_direction':       'rising',
        },
        'outcome':     'Israeli escalation response within 72-96 hours in documented cases',
        'window_hours': 96,
        'confidence':  'Medium',
    },
]


# ============================================================
# CORE SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """
    Evaluate current signal state against each red line.
    Returns list of triggered red lines with severity and status.
    """
    actors        = scan_data.get('actors', {})
    alerts_24h    = scan_data.get('alerts_24h', {})
    inbound_score = scan_data.get('inbound_score', 0)
    fp            = scan_data  # fingerprint fields at top level

    iran_level    = fp.get('iran_threat_level', 0)
    hzb_level     = fp.get('hezbollah_threat_level', 0)
    houthi_level  = fp.get('houthi_threat_level', 0)
    ballistic_lv  = fp.get('ballistic_level', 0)

    rockets_24h   = alerts_24h.get('rockets', 0)
    by_city       = alerts_24h.get('by_city', {})
    dimona_hit    = 'dimona' in by_city

    cab_count     = actors.get('war_cabinet', {}).get('statement_count', 0)
    us_count      = actors.get('us_coordination', {}).get('statement_count', 0)
    cabinet_silent = cab_count == 0
    us_silent      = us_count == 0

    triggered = []

    # ── Red line: Nuclear facility targeted ──
    if dimona_hit:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'nuclear_facility_targeting'),
            'status':  'BREACHED',
            'trigger': f'Dimona appears in 24h alert city list ({by_city.get("dimona", 0)} alerts)',
        })

    # ── Red line: Multi-axis simultaneous ──
    if iran_level >= 3 and hzb_level >= 3 and houthi_level >= 3:
        sev = 3 if (iran_level >= 5 and hzb_level >= 4) else 2
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'multi_axis_simultaneous'),
            'status':  'BREACHED' if sev == 3 else 'APPROACHING',
            'trigger': f'Iran L{iran_level} + Hezbollah L{hzb_level} + Houthi L{houthi_level} simultaneous',
            'severity': sev,
        })

    # ── Red line: Houthi ballistic / hypersonic ──
    if houthi_level >= 3 and ballistic_lv >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'houthi_ballistic_strategic'),
            'status':  'BREACHED' if houthi_level >= 4 else 'APPROACHING',
            'trigger': f'Houthi L{houthi_level} with ballistic indicators (ballistic score: {ballistic_lv})',
        })

    # ── Red line: Iran direct ballistic ──
    if iran_level >= 4 and ballistic_lv >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'iran_direct_ballistic'),
            'status':  'BREACHED' if iran_level >= 5 else 'APPROACHING',
            'trigger': f'Iran L{iran_level} with ballistic score {ballistic_lv} — Operation True Promise active',
        })

    # ── Red line: Hezbollah mass rocket barrage ──
    if rockets_24h >= 20 or hzb_level >= 4:
        sev = 3 if rockets_24h >= 50 else 2
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'hezbollah_mass_rocket'),
            'status':  'BREACHED' if rockets_24h >= 30 else 'APPROACHING',
            'trigger': f'{rockets_24h} rockets in 24h, Hezbollah L{hzb_level}',
            'severity': sev,
        })

    # ── Red line: US brake absent during escalation ──
    if us_silent and inbound_score >= 70:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'us_brake_absent_escalation'),
            'status':  'BREACHED' if inbound_score >= 85 else 'APPROACHING',
            'trigger': f'US coordination: 0 statements, inbound score: {inbound_score}',
        })

    # ── Red line: Cabinet operational silence ──
    if cabinet_silent and inbound_score >= 65:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'cabinet_silence_pre_strike'),
            'status':  'BREACHED' if inbound_score >= 80 else 'APPROACHING',
            'trigger': f'War cabinet: 0 statements while inbound score at {inbound_score}',
        })

    # Sort: BREACHED first, then by severity descending
    triggered.sort(key=lambda x: (0 if x['status'] == 'BREACHED' else 1, -x['severity']))

    return triggered


def _match_historical(scan_data):
    """
    Match current signal state against historical precedent library.
    Returns list of matching precedents with similarity scores.
    """
    fp             = scan_data
    actors         = scan_data.get('actors', {})

    iran_level     = fp.get('iran_threat_level', 0)
    hzb_level      = fp.get('hezbollah_threat_level', 0)
    houthi_level   = fp.get('houthi_threat_level', 0)
    ballistic_lv   = fp.get('ballistic_level', 0)
    asymmetric_lv  = fp.get('asymmetric_level', 0)
    inbound_score  = fp.get('inbound_score', 0)
    delta          = fp.get('delta', {})
    delta_dir      = delta.get('direction', 'stable')

    cab_count      = actors.get('war_cabinet', {}).get('statement_count', 0)
    us_count       = actors.get('us_coordination', {}).get('statement_count', 0)
    cabinet_silent = cab_count == 0
    us_silent      = us_count == 0

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

        # Check each signal condition
        if 'iran_level_min' in sigs:
            check(iran_level >= sigs['iran_level_min'],
                  f'Iran L{iran_level} ≥ L{sigs["iran_level_min"]}', weight=2)

        if 'hezbollah_level_min' in sigs:
            check(hzb_level >= sigs['hezbollah_level_min'],
                  f'Hezbollah L{hzb_level} ≥ L{sigs["hezbollah_level_min"]}', weight=2)

        if 'houthi_level_min' in sigs:
            check(houthi_level >= sigs['houthi_level_min'],
                  f'Houthi L{houthi_level} ≥ L{sigs["houthi_level_min"]}', weight=1)

        if 'ballistic_level_min' in sigs:
            check(ballistic_lv >= sigs['ballistic_level_min'],
                  f'Ballistic L{ballistic_lv} ≥ L{sigs["ballistic_level_min"]}', weight=1)

        if 'asymmetric_level_min' in sigs:
            check(asymmetric_lv >= sigs['asymmetric_level_min'],
                  f'Asymmetric L{asymmetric_lv} ≥ L{sigs["asymmetric_level_min"]}', weight=1)

        if 'cabinet_silence' in sigs:
            check(cabinet_silent == sigs['cabinet_silence'],
                  'Cabinet silence' if sigs['cabinet_silence'] else 'Cabinet active',
                  weight=2)

        if 'us_coordination_min' in sigs:
            check(us_count <= sigs['us_coordination_min'],
                  f'US coordination silent/minimal ({us_count} statements)',
                  weight=2)

        if 'inbound_score_min' in sigs:
            check(inbound_score >= sigs['inbound_score_min'],
                  f'Inbound score {inbound_score} ≥ {sigs["inbound_score_min"]}',
                  weight=1)

        if 'delta_direction' in sigs:
            check(delta_dir == sigs['delta_direction'],
                  f'Score {delta_dir}',
                  weight=1)

        if max_score == 0:
            continue

        similarity = round((score / max_score) * 100)

        if similarity >= 50:  # Only surface meaningful matches
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

    # Sort by similarity descending
    matches.sort(key=lambda x: x['similarity'], reverse=True)
    return matches[:3]  # Return top 3 matches


def _extract_commodity_signals(scan_data):
    """
    Phase 3 — extract commodity pressure signals for Israel.
    Returns:
        {
          'has_signal':     bool,
          'global_alert':   str,   # normal|elevated|high|surge
          'wheat_surge':    bool,
          'oil_pressure':   bool,
          'watch_text':     str | None,   # always emitted if any pressure
          'indicator_text': str | None,   # only if surge — promoted to key indicators
        }
    Returns has_signal=False if no commodity data or all clear.
    """
    cp = scan_data.get('commodity_pressure') or {}
    summaries = cp.get('commodity_summaries') or []
    global_alert = str(cp.get('alert_level', 'normal')).lower()

    if not summaries or global_alert == 'normal':
        return {'has_signal': False}

    wheat_alert  = 'normal'
    oil_alert    = 'normal'
    elevated_commodities = []

    for s in summaries:
        cid    = str(s.get('commodity', '')).lower()
        alert  = str(s.get('global_alert_level', 'normal')).lower()
        if cid == 'wheat':
            wheat_alert = alert
        if cid == 'oil':
            oil_alert = alert
        if alert in ('high', 'surge'):
            elevated_commodities.append((cid, alert))

    if not elevated_commodities:
        return {'has_signal': False}

    # Watch list text — always emitted when any pressure detected
    watch_parts = []
    if wheat_alert in ('high', 'surge'):
        watch_parts.append(f'wheat ({wheat_alert})')
    if oil_alert in ('high', 'surge'):
        watch_parts.append(f'oil ({oil_alert})')
    other = [c for c, a in elevated_commodities if c not in ('wheat', 'oil')]
    if other:
        watch_parts.append('+ ' + ', '.join(other))

    watch_text = (
        'Commodity supply chain pressure: ' + ', '.join(watch_parts) +
        ' — Black Sea grain corridor, Hormuz, Suez are bread/fuel chokepoints for Israel.'
    )

    # Key indicator text — only on surge (promoted to top-level indicator)
    indicator_text = None
    if global_alert == 'surge':
        if wheat_alert == 'surge':
            indicator_text = (
                'Wheat in SURGE — bread inflation reaching coalition-stress threshold. '
                'Israel imports ~80% of consumption; Black Sea or Suez disruption directly hits food security.'
            )
        elif oil_alert == 'surge':
            indicator_text = (
                'Oil in SURGE — fuel cost spike compounds wartime operational expense. '
                'Eilat-Ashkelon pipeline + Mediterranean tankers = single-points-of-failure.'
            )
        else:
            indicator_text = (
                f'Commodity pressure index in SURGE across {len(elevated_commodities)} exposures — '
                'multi-commodity stress on Israeli supply chains.'
            )

    return {
        'has_signal':     True,
        'global_alert':   global_alert,
        'wheat_surge':    wheat_alert == 'surge',
        'oil_pressure':   oil_alert in ('high', 'surge'),
        'watch_text':     watch_text,
        'indicator_text': indicator_text,
    }


def _extract_gaza_wb_signals(scan_data):
    """
    Country-altitude So-What read for the reframed Gaza + West Bank lanes
    (June 2026 ceasefire era). Estimative voice ONLY -- consistent with /
    historically precedes / likely indicates. No probabilities, dates, or 'will'.

    Gaza: ceasefire-phase proxy posture (disarmament defiance vs rearm/rebuild).
    West Bank: DUAL READ -- Iran-activation (the threat signal that feeds the
    Iran wheel) vs destabilization tinder (settler violence + PA fiscal stress),
    which is context, NOT a threat level on its own. The compound read is when
    both co-occur.
    """
    actors = scan_data.get('actors', {})
    gz = actors.get('hamas_gaza', {})
    wb = actors.get('west_bank_civil', {})
    gz_level = gz.get('max_level', 0)
    wb_level = wb.get('max_level', 0)

    def _titles(a):
        return ' '.join((art.get('title') or '').lower()
                        for art in a.get('top_articles', []))
    gz_txt = _titles(gz)
    wb_txt = _titles(wb)

    sit = []
    indicator_text = ''

    # ---- Gaza: ceasefire-phase proxy read ----
    GZ_DISARM = ('disarm', 'decommission', 'board of peace', 'mladenov')
    GZ_REARM  = ('rearm', 'rebuild', 'tunnel', 'smuggl')
    GZ_VIOL   = ('violation', 'ceasefire breach', 'reinvade', 'strike gaza')
    if gz_level >= 2 or gz.get('statement_count', 0) >= 3:
        if any(k in gz_txt for k in GZ_DISARM):
            sit.append(
                'In Gaza, Hamas signaling is consistent with refusal to decommission under '
                'the Board of Peace framework -- the disarmament deadlock that has historically '
                'preceded ceasefire-phase breakdown.'
            )
        elif any(k in gz_txt for k in GZ_REARM):
            sit.append(
                'In Gaza, rebuild and rearm signals are consistent with proxy reconstitution '
                'during the ceasefire pause rather than de-escalation.'
            )
        elif any(k in gz_txt for k in GZ_VIOL):
            sit.append(
                'In Gaza, ceasefire-violation signals are present -- consistent with a brittle '
                'rather than a consolidating truce.'
            )
        else:
            sit.append(
                'Gaza proxy signal is active (L%d) without a clear disarmament or rearm flavor '
                'this cycle.' % gz_level
            )

    # ---- West Bank: dual read (Iran-activation vs destabilization tinder) ----
    WB_ACTIVATION = ('islamic jihad', 'pij', 'jenin battalion', 'tulkarm', 'nur shams',
                     'lions den', 'smuggl', 'weapons cache', 'cell', 'foiled', 'irgc')
    WB_TINDER = ('settler', 'jewish terror', 'authority collapse', 'clearance revenue',
                 'palestinian banks', 'annexation', 'outpost')
    wb_has_act = any(k in wb_txt for k in WB_ACTIVATION)
    wb_has_tin = any(k in wb_txt for k in WB_TINDER)

    if wb_has_act and wb_has_tin:
        sit.append(
            'In the West Bank, Iran-aligned faction activity (smuggling / cell signals) is '
            'co-occurring with destabilization tinder (settler violence, PA fiscal stress) -- '
            'the compound pattern that has historically preceded a widening security vacuum.'
        )
        indicator_text = (
            'West Bank shows BOTH Iran-activation and destabilization tinder this cycle -- '
            'the co-occurrence is the compound read, not two separate stories.'
        )
    elif wb_has_act:
        sit.append(
            'In the West Bank, faction activity is consistent with Iran\'s stated third-front '
            'effort -- smuggling and cell signals have historically preceded attack-cell maturation.'
        )
    elif wb_has_tin:
        sit.append(
            'In the West Bank, the active signal is destabilization tinder (settler violence, '
            'PA fiscal stress) -- on its own a civil-unrest read; it compounds only if Iran-aligned '
            'faction activation co-occurs.'
        )

    watch_text = ''
    if gz_level >= 2 or wb_level >= 2:
        watch_text = ('Gaza disarmament-track collapse signals; West Bank smuggling-route or '
                      'cell-dismantlement reporting (Iran third-front maturation)')

    situation_text = ' '.join(sit)
    return {
        'has_signal':     bool(situation_text),
        'situation_text': situation_text,
        'indicator_text': indicator_text,
        'watch_text':     watch_text,
    }


def _build_so_what(scan_data, red_lines_triggered, historical_matches):
    """
    Generate plain-language executive assessment from current signals.
    Tone: direct but appropriately hedged.
    """
    fp             = scan_data
    iran_level     = fp.get('iran_threat_level', 0)
    hzb_level      = fp.get('hezbollah_threat_level', 0)
    houthi_level   = fp.get('houthi_threat_level', 0)
    inbound_score  = fp.get('inbound_score', 0)
    theatre_level  = fp.get('theatre_level', 0)
    delta          = fp.get('delta', {})
    alerts_24h     = fp.get('alerts_24h', {})
    actors         = fp.get('actors', {})

    delta_dir      = delta.get('direction', 'stable')
    score_change   = delta.get('score_change', 0)
    rockets_24h    = alerts_24h.get('rockets', 0)
    by_city        = alerts_24h.get('by_city', {})
    dimona_hit     = 'dimona' in by_city

    cab_count      = actors.get('war_cabinet', {}).get('statement_count', 0)
    us_count       = actors.get('us_coordination', {}).get('statement_count', 0)
    cabinet_silent = cab_count == 0
    us_silent      = us_count == 0

    breached_count  = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    top_match       = historical_matches[0] if historical_matches else None
    top_similarity  = top_match['similarity'] if top_match else 0

    # ── Determine overall scenario label ──
    if theatre_level >= 5 and breached_count >= 3:
        scenario       = 'CRITICAL — Multiple Red Lines Breached'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif theatre_level >= 5 and breached_count >= 1:
        scenario       = 'HIGH — Active Conflict, Red Lines Crossed'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif theatre_level >= 4 or breached_count >= 2:
        scenario       = 'ELEVATED — Pre-Escalation Indicators Present'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif theatre_level >= 3 or breached_count >= 1:
        scenario       = 'ELEVATED — Warning Signals Active'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    else:
        scenario       = 'MONITORING — Below Escalation Threshold'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Build situation summary ──
    situation_parts = []

    # Inbound threat summary
    active_threats = []
    if iran_level >= 4:
        active_threats.append(f'Iran (L{iran_level} — Operation True Promise active)')
    elif iran_level >= 2:
        active_threats.append(f'Iran (L{iran_level})')
    if hzb_level >= 3:
        active_threats.append(f'Hezbollah (L{hzb_level}, {rockets_24h} rockets/24h)')
    elif hzb_level >= 1:
        active_threats.append(f'Hezbollah (L{hzb_level})')
    if houthi_level >= 3:
        active_threats.append(f'Houthis (L{houthi_level} — ballistic capable)')
    elif houthi_level >= 1:
        active_threats.append(f'Houthis (L{houthi_level})')

    if active_threats:
        situation_parts.append(
            'Israel is under active multi-axis pressure from: ' + ', '.join(active_threats) + '.'
        )

    # Dimona flag
    if dimona_hit:
        situation_parts.append(
            f'⚠️ Dimona nuclear facility has been targeted ({by_city.get("dimona", 0)} alerts in 24h) — '
            'this represents Israel\'s most sensitive stated red line.'
        )

    # Trend
    if delta_dir == 'rising' and score_change >= 10:
        situation_parts.append(
            f'Threat trajectory is rising sharply (+{round(score_change, 1)} points from recent average), '
            'indicating accelerating escalation rather than steady-state conflict.'
        )
    elif delta_dir == 'rising':
        situation_parts.append(f'Threat trajectory is rising (+{round(score_change, 1)} from recent average).')

    # ── Build key indicator summary ──
    indicators = []

    if cabinet_silent and inbound_score >= 70:
        indicators.append(
            'War cabinet has issued zero public statements during active multi-axis attack — '
            'historically a significant pre-authorization indicator.'
        )
    if us_silent and inbound_score >= 70:
        indicators.append(
            'No US coordination or restraint signals detected. Absent US brake during escalation '
            'has historically preceded Israeli independent action.'
        )
    if breached_count >= 2:
        indicators.append(
            f'{breached_count} of Israel\'s stated red lines are currently breached or approaching breach simultaneously.'
        )

    # ── Build assessment ──
    assessment_parts = []

    if top_match and top_similarity >= 70:
        assessment_parts.append(
            f'Current signal pattern shows {top_match["similarity"]}% similarity to pre-action conditions '
            f'during {top_match["label"]}. In that case, {top_match["outcome"].lower()}'
        )
        assessment_parts.append(
            f'Assess: signal pattern consistent with elevated probability of Israeli military response. '
            f'Confidence: {top_match["confidence"]} — {_confidence_caveat(top_match["confidence"])}.'
        )
        window = top_match['window_hours']
        assessment_parts.append(
            f'Historical window for response in comparable scenarios: {window} hours. '
            'This is an analytical estimate, not a prediction.'
        )
    elif top_match and top_similarity >= 50:
        assessment_parts.append(
            f'Current signals show partial similarity ({top_match["similarity"]}%) to {top_match["label"]}. '
            'Pattern is suggestive but not conclusive.'
        )
        assessment_parts.append(
            'Assess: elevated vigilance warranted. Monitor war cabinet and US coordination channels '
            'for confirmation or reversal signals.'
        )
    else:
        if theatre_level >= 4:
            assessment_parts.append(
                'Current signals reflect active conflict conditions. No strong historical pattern match '
                'at this time — situation may be evolving in a novel direction or insufficient '
                'data for confident pattern matching.'
            )
        else:
            assessment_parts.append(
                'Current signals are below pattern-match threshold. Continue monitoring.'
            )

    # ── What to watch ──
    watch_items = []
    if cabinet_silent:
        watch_items.append('War cabinet public statements resuming (would suggest decision made or crisis passed)')
    if us_silent:
        watch_items.append('US coordination signals (brake = restraint applied; greenlight = action authorized)')
    if dimona_hit:
        watch_items.append('Additional Dimona targeting (escalation) or ceasefire signals (de-escalation)')
    watch_items.append('IDF mobilization orders or reserve call-up announcements')
    watch_items.append('NOTAM closures over Israeli or Iranian airspace')

    # ── Phase 3 commodity signals (May 5 2026) ──
    # Promote SURGE-level commodity pressure to key_indicators (rare, high-signal).
    # Always inject pressure into watch_list (broad situational awareness).
    commodity_signals = _extract_commodity_signals(scan_data)
    if commodity_signals.get('has_signal'):
        if commodity_signals.get('indicator_text'):
            indicators.insert(0, commodity_signals['indicator_text'])  # Prepend — high-priority signal
        if commodity_signals.get('watch_text'):
            watch_items.insert(0, commodity_signals['watch_text'])

    # -- Gaza + West Bank ceasefire-era read (June 2026; estimative voice) --
    gaza_wb = _extract_gaza_wb_signals(scan_data)
    if gaza_wb.get('has_signal'):
        if gaza_wb.get('situation_text'):
            situation_parts.append(gaza_wb['situation_text'])
        if gaza_wb.get('indicator_text'):
            indicators.append(gaza_wb['indicator_text'])
        if gaza_wb.get('watch_text'):
            watch_items.append(gaza_wb['watch_text'])

    return {
        'scenario':          scenario,
        'scenario_color':    scenario_color,
        'scenario_icon':     scenario_icon,
        'situation':         ' '.join(situation_parts),
        'key_indicators':    indicators,
        'assessment':        ' '.join(assessment_parts),
        'watch_list':        watch_items[:5],  # Top 5 most relevant (was 4 — bumped to fit commodity)
        'generated_at':      datetime.now(timezone.utc).isoformat(),
        'confidence_note':   (
            'This assessment is generated algorithmically from open-source signal data. '
            'It is not a prediction and should not be used as the sole basis for any decision. '
            'Verify through official channels.'
        ),
    }


def _confidence_caveat(confidence_label):
    """Return appropriate hedging language for each confidence level."""
    caveats = {
        'High':        'multiple strong signal matches with well-documented precedent',
        'Medium':      'partial signal match; outcome not determinative',
        'Medium-Low':  'pattern suggestive but historical base rate limited',
        'Low':         'weak match only; treat as background signal',
    }
    return caveats.get(confidence_label, 'confidence assessment pending more data')


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Takes full scan_data dict from rhetoric_tracker_israel
    scan result. Returns structured interpretation dict for API response.

    Usage in rhetoric_tracker_israel.py:
        from israel_signal_interpreter import interpret_signals
        ...
        result['interpretation'] = interpret_signals(result)
    """
    try:
        red_lines  = _score_red_lines(scan_data)
        historical = _match_historical(scan_data)
        so_what    = _build_so_what(scan_data, red_lines, historical)

        breached   = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']

        return {
            'so_what':             so_what,
            'red_lines': {
                'triggered':       red_lines,
                'breached_count':  len(breached),
                'approaching_count': len(approaching),
                'highest_severity': max((r['severity'] for r in red_lines), default=0),
            },
            'historical_matches':  historical,
            'interpreter_version': '1.0.0',
            'interpreted_at':      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Israel Interpreter] Error: {str(e)[:120]}')
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
# Israel is the STRIKE ACTOR + dual-dashboard tracker — it both reads
# cross-theater fingerprints from Iran (command node), Lebanon, Yemen,
# Syria, Iraq AND emits its own outbound strike posture. It carries the
# richest cross-theater context of any tracker in the platform.
#
# This emitter maps Israel's dual-dashboard scan into canonical signal
# categories consumed by me_regional_bluf.py and global_pressure_index.py.
#
# Categories Israel emits:
#   red_line_breached            -- severity 3 red lines (multi-axis,
#                                   nuclear facility, mass-cas crossing)
#   multi_axis_convergence       -- TCI >= 3 AND ≥2 inbound theaters L3+
#                                   (high-leverage GPI signal — feeds the
#                                   ME regional BLUF's most urgent narrative)
#   kinetic_pressure             -- alerts_24h significant (ballistic >= 1
#                                   or rockets >= 20) or ballistic_level L4+
#   theatre_high                 -- composite L4+ catch-all
#   inbound_threat_high          -- inbound_max_level >= 4
#   outbound_strike_posture      -- strike_posture_level >= 4
#                                   (Israel preparing to strike)
#   crosstheater_iran_israel     -- iran_threat_level >= 4
#   crosstheater_lebanon_israel  -- hezbollah_threat_level >= 4
#   crosstheater_yemen_israel    -- houthi_threat_level >= 4
#   crosstheater_syria_israel    -- syria_threat_level >= 3
#   crosstheater_iraq_israel     -- iraq_threat_level >= 3
#   silence_anomaly              -- war_cabinet/US-coord quiet during
#                                   high tempo (operational planning)
#   diplomatic_active            -- inbound_diplomatic_active (cross-theater
#                                   off-ramps active in Lebanon/Iran/etc.)
# ============================================================

ISRAEL_FLAG = '\U0001f1ee\U0001f1f1'  # 🇮🇱

_ISR_ESC_LABELS = {
    0: 'Monitoring',
    1: 'Routine',
    2: 'Elevated Rhetoric',
    3: 'Heightened Posture',
    4: 'Active Signaling',
    5: 'Active Conflict',
}


def build_top_signals(scan_data):
    """
    Convert Israel scan_data into canonical top_signals[] for ME regional
    BLUF and Global Pressure Index. Returns a list (possibly empty),
    sorted by priority desc.

    Signal schema (canonical platform-wide):
        priority   int 0-15  (higher == more urgent)
        category   str       (canonical bucket)
        theatre    'israel'
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

    # Theatre composite
    theatre_level   = int(scan_data.get('theatre_level', 0) or 0)
    theatre_score   = int(scan_data.get('theatre_score', 0) or 0)

    # Inbound dashboard
    inbound_lvl     = int(scan_data.get('inbound_max_level', 0) or 0)
    iran_lvl        = int(scan_data.get('iran_threat_level', 0) or 0)
    hez_lvl         = int(scan_data.get('hezbollah_threat_level', 0) or 0)
    houthi_lvl      = int(scan_data.get('houthi_threat_level', 0) or 0)
    syria_lvl       = int(scan_data.get('syria_threat_level', 0) or 0)
    iraq_lvl        = int(scan_data.get('iraq_threat_level', 0) or 0)
    tci             = int(scan_data.get('threat_convergence_index', 0) or 0)
    convergence_msg = str(scan_data.get('convergence_signal', '') or '')[:120]
    iran_cmd_node   = bool(scan_data.get('iran_is_command_node', False))

    # Alerts (Pikud HaOref / Telegram-detected)
    alerts          = scan_data.get('alerts_24h') or {}
    alerts_total    = int(alerts.get('total', 0) or 0)
    alerts_rockets  = int(alerts.get('rockets', 0) or 0)
    alerts_ballistic= int(alerts.get('ballistic', 0) or 0)
    alerts_recent_1h= int(alerts.get('recent_1h', 0) or 0)

    # Article-detected vectors
    ballistic_lvl   = int(scan_data.get('ballistic_level', 0) or 0)
    asymmetric_lvl  = int(scan_data.get('asymmetric_level', 0) or 0)

    # Outbound dashboard
    outbound_lvl    = int(scan_data.get('outbound_max_level', 0) or 0)
    strike_lvl      = int(scan_data.get('strike_posture_level', 0) or 0)
    annex_lvl       = int(scan_data.get('annexation_level', 0) or 0)

    # Diplomatic shim (cross-theater off-ramps)
    dipl_active     = bool(scan_data.get('inbound_diplomatic_active', False))
    dipl_modifier   = int(scan_data.get('inbound_diplomatic_modifier', 0) or 0)
    theaters_in_dipl= scan_data.get('theaters_in_diplomacy') or []

    actors          = scan_data.get('actors') or {}
    silence_alerts  = scan_data.get('silence_anomalies') or []

    # ── Color helper ─────────────────────────────────────────────────
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
        rl_id = str(rl.get('id', '')).lower()
        # Multi-axis attack red line gets special multi_axis_convergence flavor
        if 'multi_axis' in rl_id or 'multi-axis' in label.lower() or 'simultaneous' in rl_id:
            signals.append({
                'priority':   14,   # highest possible — this is the strategic alarm
                'category':   'multi_axis_convergence',
                'theatre':    'israel',
                'level':      max(theatre_level, 4),
                'icon':       '⚡',
                'color':      '#dc2626',
                'short_text': (f'{ISRAEL_FLAG} ISRAEL: Multi-axis convergence '
                               f'breached (TCI {tci})'),
                'long_text':  (f'{ISRAEL_FLAG} ISRAEL multi-axis red line breached '
                               f'— Iran L{iran_lvl}, Hezbollah L{hez_lvl}, Houthi '
                               f'L{houthi_lvl} elevated simultaneously. '
                               f'{convergence_msg}.'),
            })
            continue
        # Nuclear facility targeting red line
        if 'nuclear' in rl_id:
            signals.append({
                'priority':   14,
                'category':   'red_line_breached',
                'theatre':    'israel',
                'level':      max(theatre_level, 4),
                'icon':       '☢️',
                'color':      '#dc2626',
                'short_text': (f'{ISRAEL_FLAG} ISRAEL: Nuclear facility '
                               f'targeting — {label[:30]}'),
                'long_text':  (f'{ISRAEL_FLAG} ISRAEL nuclear facility red line '
                               f'breached: {rl.get("label", "")[:140]}'),
            })
            continue
        # Generic breach
        signals.append({
            'priority':   12 if sev >= 3 else 10,
            'category':   'red_line_breached',
            'theatre':    'israel',
            'level':      max(theatre_level, 4),
            'icon':       rl.get('icon', '🚨'),
            'color':      '#dc2626',
            'short_text': f'{ISRAEL_FLAG} ISRAEL: BREACH — {label}',
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL red line breached: '
                           f'{rl.get("label", "")[:140]}'),
        })

    # ── 2. Multi-axis convergence (even without explicit red line) ──
    # If TCI >= 3 AND we haven't already emitted a multi_axis signal,
    # surface this as a soft (not breach) convergence signal.
    has_multi_axis_signal = any(s.get('category') == 'multi_axis_convergence'
                                 for s in signals)
    if tci >= 3 and not has_multi_axis_signal:
        signals.append({
            'priority':   11,
            'category':   'multi_axis_convergence',
            'theatre':    'israel',
            'level':      max(inbound_lvl, 3),
            'icon':       '⚡',
            'color':      lvl_color(max(inbound_lvl, 3)),
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Multi-axis convergence '
                           f'(TCI {tci})'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL Threat Convergence Index '
                           f'{tci}/5 — {convergence_msg or "multiple Iran-axis theaters elevated simultaneously"}.'),
        })

    # ── 3. Kinetic pressure: live alerts (Pikud HaOref + ballistic) ──
    if alerts_ballistic >= 1:
        signals.append({
            'priority':   13,   # ballistic = strategic — even one is huge
            'category':   'kinetic_pressure',
            'theatre':    'israel',
            'level':      5,
            'icon':       '☄️',
            'color':      '#dc2626',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: {alerts_ballistic} ballistic '
                           f'alert(s) in 24h'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL Pikud HaOref: '
                           f'{alerts_ballistic} ballistic missile alert(s) in '
                           f'last 24h, {alerts_rockets} rocket alerts. '
                           f'Recent 1h: {alerts_recent_1h}.'),
        })
    elif alerts_rockets >= 20 or alerts_total >= 30:
        signals.append({
            'priority':   12,
            'category':   'kinetic_pressure',
            'theatre':    'israel',
            'level':      4,
            'icon':       '🚀',
            'color':      '#dc2626',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: {alerts_total} alerts in 24h '
                           f'({alerts_rockets} rockets)'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL elevated alert tempo — '
                           f'{alerts_total} total alerts in 24h, '
                           f'{alerts_rockets} rocket alerts, recent 1h: '
                           f'{alerts_recent_1h}.'),
        })
    elif ballistic_lvl >= 4:
        signals.append({
            'priority':   11,
            'category':   'kinetic_pressure',
            'theatre':    'israel',
            'level':      ballistic_lvl,
            'icon':       '☄️',
            'color':      lvl_color(ballistic_lvl),
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Ballistic vector '
                           f'L{ballistic_lvl} (article-detected)'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL ballistic missile language '
                           f'L{ballistic_lvl} {_ISR_ESC_LABELS.get(ballistic_lvl, "")} — '
                           f'detected in article corpus.'),
        })

    # ── 4. Outbound strike posture (Israel preparing to strike) ──────
    if strike_lvl >= 4:
        signals.append({
            'priority':   11,
            'category':   'outbound_strike_posture',
            'theatre':    'israel',
            'level':      strike_lvl,
            'icon':       '🎯',
            'color':      lvl_color(strike_lvl),
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Outbound strike posture '
                           f'L{strike_lvl}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL IDF outbound strike posture '
                           f'L{strike_lvl} {_ISR_ESC_LABELS.get(strike_lvl, "")} — '
                           f'mobilization, target language, strike '
                           f'authorizations elevated.'),
        })

    # ── 5. Inbound threat composite high (when no specific actor surfaces) ──
    if inbound_lvl >= 4:
        signals.append({
            'priority':   10,
            'category':   'inbound_threat_high',
            'theatre':    'israel',
            'level':      inbound_lvl,
            'icon':       '🛡️',
            'color':      lvl_color(inbound_lvl),
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Inbound threat composite '
                           f'L{inbound_lvl}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL inbound threat L{inbound_lvl} '
                           f'{_ISR_ESC_LABELS.get(inbound_lvl, "")} — composite '
                           f'across Iran, Lebanon, Yemen, Syria, Iraq '
                           f'fingerprints.'),
        })

    # ── 6-10. Cross-theater per-actor signals ───────────────────────
    if iran_lvl >= 4:
        signals.append({
            'priority':   11 if iran_cmd_node else 10,
            'category':   'crosstheater_iran_israel',
            'theatre':    'israel',
            'level':      iran_lvl,
            'icon':       '🇮🇷',
            'color':      '#7c3aed',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Iran threat L{iran_lvl}'
                           f'{" (command node)" if iran_cmd_node else ""}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL inbound from Iran L{iran_lvl} — '
                           f'IRGC / Khamenei / OTP signaling read from Iran '
                           f'command node fingerprint.'),
        })
    if hez_lvl >= 4:
        signals.append({
            'priority':   10,
            'category':   'crosstheater_lebanon_israel',
            'theatre':    'israel',
            'level':      hez_lvl,
            'icon':       '🇱🇧',
            'color':      '#7c3aed',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Hezbollah (Hizbullah) threat '
                           f'L{hez_lvl}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL inbound from Lebanon L{hez_lvl} — '
                           f'Hezbollah kinetic / rocket / cross-border activity '
                           f'read from Lebanon fingerprint.'),
        })
    # -- Turkey mirror-friction lane (Jun 11 2026): read from the Turkey
    # swing-state fingerprint. Distinct lane from the Iran axis.
    turkey_friction = str(scan_data.get('turkey_israel_friction', 'normal'))
    turkey_lb_vector = str(scan_data.get('turkey_lebanon_vector', 'dormant'))
    if turkey_friction in ('elevated', 'high'):
        signals.append({
            'priority':   10 if turkey_friction == 'high' else 8,
            'category':   'crosstheater_turkey_israel',
            'theatre':    'israel',
            'level':      4 if turkey_friction == 'high' else 3,
            'icon':       '🇹🇷',
            'color':      '#e11d48',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Turkey friction '
                           f'{turkey_friction.upper()}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL: Turkey-Israel mirror-friction '
                           f'reads {turkey_friction} from the Turkey swing-state '
                           f'fingerprint -- both capitals framing the other as the '
                           f'Levant expansionist. Turkey Lebanon-vector: '
                           f'{turkey_lb_vector}. Synchronized escalation of mutual '
                           f'threat narratives has historically preceded '
                           f'deconfliction strain in shared Syrian space.'),
        })

    if houthi_lvl >= 4:
        signals.append({
            'priority':   10,
            'category':   'crosstheater_yemen_israel',
            'theatre':    'israel',
            'level':      houthi_lvl,
            'icon':       '🇾🇪',
            'color':      '#7c3aed',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Houthi threat L{houthi_lvl}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL inbound from Yemen L{houthi_lvl} — '
                           f'Houthi missile / drone / Bab el-Mandeb activity '
                           f'read from Yemen fingerprint.'),
        })
    if syria_lvl >= 3:
        signals.append({
            'priority':   9,
            'category':   'crosstheater_syria_israel',
            'theatre':    'israel',
            'level':      syria_lvl,
            'icon':       '🇸🇾',
            'color':      '#7c3aed',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Syria threat L{syria_lvl}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL inbound from Syria L{syria_lvl} — '
                           f'corridor / weapons-transfer / HTS activity read '
                           f'from Syria fingerprint.'),
        })
    if iraq_lvl >= 3:
        signals.append({
            'priority':   9,
            'category':   'crosstheater_iraq_israel',
            'theatre':    'israel',
            'level':      iraq_lvl,
            'icon':       '🇮🇶',
            'color':      '#7c3aed',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Iraq threat L{iraq_lvl}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL inbound from Iraq L{iraq_lvl} — '
                           f'PMF / Kataib Hezbollah / Iran-aligned militia '
                           f'activity read from Iraq fingerprint.'),
        })

    # ── 11. Theatre composite high (catch-all) ──────────────────────
    if theatre_level >= 4 or theatre_score >= 70:
        signals.append({
            'priority':   9,
            'category':   'theatre_high',
            'theatre':    'israel',
            'level':      theatre_level,
            'icon':       '🔴' if theatre_level >= 4 else '🟠',
            'color':      lvl_color(theatre_level),
            'short_text': (f'{ISRAEL_FLAG} ISRAEL L{theatre_level} — '
                           f'{_ISR_ESC_LABELS.get(theatre_level, "")}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL theatre composite L{theatre_level} '
                           f'{_ISR_ESC_LABELS.get(theatre_level, "")} '
                           f'(score {theatre_score}/100). Inbound L{inbound_lvl}, '
                           f'outbound L{outbound_lvl}.'),
        })

    # ── 12. Silence anomalies (war cabinet / US coord quiet) ────────
    for sa in silence_alerts[:2]:
        if not isinstance(sa, dict):
            continue
        actor_id   = sa.get('actor_id', 'actor')
        actor_name = sa.get('actor_name', actor_id)
        # War cabinet / US coordination silence is the most operationally significant
        is_critical = ('war_cabinet' in str(actor_id).lower() or
                       'us_coordination' in str(actor_id).lower() or
                       'idf_military' in str(actor_id).lower())
        signals.append({
            'priority':   11 if is_critical else 9,
            'category':   'silence_anomaly',
            'theatre':    'israel',
            'level':      4 if is_critical else 3,
            'icon':       '🔇',
            'color':      '#dc2626' if is_critical else '#f59e0b',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Silence anomaly — '
                           f'{actor_name[:35]}'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL unusual silence from '
                           f'{actor_name}. '
                           f'{"Pre-strike comms blackout indicator." if is_critical else "May indicate message coordination."}'),
        })

    # ── 13. Diplomatic active (cross-theater off-ramps) ─────────────
    if dipl_active:
        n_theaters = len(theaters_in_dipl)
        theater_list = ', '.join(theaters_in_dipl[:3]).title() if theaters_in_dipl else 'multiple'
        signals.append({
            'priority':   8,
            'category':   'diplomatic_active',
            'theatre':    'israel',
            'level':      3,
            'icon':       '🕊️',
            'color':      '#10b981',
            'short_text': (f'{ISRAEL_FLAG} ISRAEL: Cross-theater diplomacy '
                           f'({n_theaters} theaters)'),
            'long_text':  (f'{ISRAEL_FLAG} ISRAEL inbound diplomatic shim active — '
                           f'{theater_list} in negotiation track. Aggregate '
                           f'modifier: {dipl_modifier} pts.'),
        })

    # ── Sort and return ─────────────────────────────────────────────
    signals.sort(key=lambda s: s.get('priority', 0), reverse=True)
    return signals


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    # Test with current signal state from today's scan
    test_data = {
        'iran_threat_level':      5,
        'hezbollah_threat_level': 5,
        'houthi_threat_level':    4,
        'ballistic_level':        1,
        'asymmetric_level':       1,
        'inbound_score':          94,
        'theatre_level':          5,
        'delta': {
            'direction':    'rising',
            'score_change': 15.1,
            'current_score': 94,
            'prior_avg_score': 78.9,
        },
        'alerts_24h': {
            'rockets':  38,
            'ballistic': 11,
            'by_city': {
                'dimona': 1, 'haifa': 2, 'tel aviv': 3,
                'jerusalem': 4, 'nahariya': 2, 'acre': 2,
            },
        },
        'actors': {
            'war_cabinet':    {'statement_count': 0},
            'us_coordination': {'statement_count': 0},
            'idf_military':   {'statement_count': 9},
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
    print('\nRED LINES TRIGGERED:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} (Sev {rl["severity"]})')
        print(f'     {rl["trigger"]}')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% — {hm["label"]}')
        print(f'     Outcome: {hm["outcome"]}')
        print(f'     Window: {hm["window_hours"]}h | Confidence: {hm["confidence"]}')
    print()
