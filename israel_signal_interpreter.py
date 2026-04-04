"""
israel_signal_interpreter.py
Asifah Analytics — ME Backend Module
v1.0.0 - April 4, 2026

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

    return {
        'scenario':          scenario,
        'scenario_color':    scenario_color,
        'scenario_icon':     scenario_icon,
        'situation':         ' '.join(situation_parts),
        'key_indicators':    indicators,
        'assessment':        ' '.join(assessment_parts),
        'watch_list':        watch_items[:4],  # Top 4 most relevant
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
