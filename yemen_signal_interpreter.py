"""
yemen_signal_interpreter.py
Asifah Analytics -- ME Backend Module
v1.0.0

Signal interpretation engine for the Yemen / Houthi Rhetoric Tracker.

Core analytical frame: Is the Houthi Red Sea campaign escalating toward
full maritime chokepoint closure, and is it coordinating with Iranian
Hormuz pressure to create a DUAL CHOKEPOINT strategy?

Three analytical outputs:
  1. So What Summary  -- plain-language maritime/strike assessment
  2. Red Line Status  -- Houthi red lines + dual chokepoint convergence
  3. Historical Match -- documented pre-escalation patterns

Yemen-specific red lines fall into TWO categories:
  A. Houthi operational triggers (what signals Houthi escalation)
  B. Dual chokepoint signals (Houthi + Iran coordinated closure threat)

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS
# ============================================================
RED_LINES = [
    # ── Category A: Houthi escalation triggers ──────────────
    {
        'id':       'bab_mandeb_closure_declared',
        'label':    'Bab el-Mandeb Closure Declared',
        'detail':   'Houthis formally declare closure of Bab el-Mandeb -- blocks 10% of global trade',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '⛔',
        'category': 'houthi_trigger',
        'source':   'CENTCOM stated red line -- Bab el-Mandeb closure triggers coalition military response',
    },
    {
        'id':       'dual_chokepoint_convergence',
        'label':    'DUAL CHOKEPOINT -- Iran + Houthi Simultaneous',
        'detail':   'Iran threatening Hormuz WHILE Houthis threatening Mandeb -- coordinated blockade strategy',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🔱',
        'category': 'coordination_trigger',
        'source':   'Strategic pattern -- simultaneous Hormuz+Mandeb threats block 30%+ of global oil transit',
    },
    {
        'id':       'us_carrier_targeted',
        'label':    'US Carrier Strike Group Targeted',
        'detail':   'Houthis fire on or directly threaten a US carrier strike group',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🛳️',
        'category': 'houthi_trigger',
        'source':   'CENTCOM doctrine -- attack on US carrier is act of war triggering full military response',
    },
    {
        'id':       'ballistic_at_israel',
        'label':    'Houthi Ballistic Missile at Israel',
        'detail':   'Houthi ballistic missile strikes Israeli territory -- crosses Israeli red line',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🚀',
        'category': 'houthi_trigger',
        'source':   'Israeli doctrine -- ballistic strike from Yemen triggers IDF response',
    },
    {
        'id':       'iran_directive_signal',
        'label':    'Iran Direct Command Signal to Houthis',
        'detail':   'IRGC direct coordination with Houthi military -- not just political support',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '📡',
        'category': 'coordination_trigger',
        'source':   'Cross-theater fingerprint -- IRGC Quds Force coordinates Houthi ops directly',
    },
    {
        'id':       'ceasefire_collapse',
        'label':    'KSA-Houthi Ceasefire Collapse',
        'detail':   'Breakdown of Saudi-Houthi ceasefire -- Houthis free to redirect to Red Sea campaign',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🕊️',
        'category': 'houthi_trigger',
        'source':   'Pattern analysis -- ceasefire collapse historically precedes Houthi Red Sea escalation',
    },
    {
        'id':       'somaliland_military_access',
        'label':    'US/Israel Somaliland Military Access',
        'detail':   'US or Israeli forces establish presence at Berbera/Somaliland -- flanks Houthi position',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🗺️',
        'category': 'adversary_trigger',
        'source':   'Strategic analysis -- Somaliland access would allow strike on Houthi rear from Horn of Africa',
    },
    {
        'id':       'centcom_strike_escalation',
        'label':    'CENTCOM Escalatory Strike Package',
        'detail':   'US strikes expand beyond anti-missile defense to Houthi command/infrastructure',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🇺🇸',
        'category': 'adversary_trigger',
        'source':   'Escalation pattern -- CENTCOM infrastructure strikes historically precede Houthi mass retaliation',
    },
]


# ============================================================
# HISTORICAL PRECEDENT LIBRARY
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'red_sea_campaign_launch_2023',
        'label':       'Houthi Red Sea Campaign Launch (Nov 2023)',
        'description': 'Houthis begin systematic targeting of commercial shipping in solidarity with Gaza',
        'source':      'CSIS; ISW; UN Panel of Experts Yemen 2024',
        'signals': {
            'maritime_level_min':      3,
            'direct_strike_level_min': 2,
            'iran_coordination':       True,
        },
        'outcome':      'Campaign forced rerouting of 90%+ of container ships away from Red Sea. $200B+ economic impact.',
        'window_hours': 168,
        'confidence':   'High',
    },
    {
        'id':          'operation_prosperity_guardian_2024',
        'label':       'Operation Prosperity Guardian (Dec 2023)',
        'description': 'US/coalition naval response to Houthi shipping attacks',
        'source':      'CENTCOM; IISS; Reuters',
        'signals': {
            'maritime_level_min':      4,
            'us_level_min':            4,
            'direct_strike_level_min': 3,
        },
        'outcome':      'US-led coalition escorts; Houthis escalated to ballistic missiles and anti-ship weapons.',
        'window_hours': 96,
        'confidence':   'High',
    },
    {
        'id':          'houthi_israel_ballistic_2024',
        'label':       'Houthi Ballistic Campaign vs Israel (2024)',
        'description': 'Houthis launch sustained ballistic missile + drone campaign targeting Israel',
        'source':      'ISW; INSS; IDF statements 2024',
        'signals': {
            'direct_strike_level_min': 4,
            'israel_level_min':        3,
            'iran_coordination':       True,
        },
        'outcome':      'Multiple ballistic missiles intercepted by Arrow-3. IDF struck Hodeidah port in retaliation.',
        'window_hours': 72,
        'confidence':   'High',
    },
    {
        'id':          'dual_chokepoint_threat_2026',
        'label':       'Dual Chokepoint Coordination Signal (2026)',
        'description': 'Iran threatens Hormuz while Houthis escalate Mandeb -- simultaneous pressure',
        'source':      'Asifah Analytics cross-theater fingerprint; current pattern analysis',
        'signals': {
            'maritime_level_min':      3,
            'iran_coordination':       True,
            'mandeb_threat':           True,
        },
        'outcome':      'Coordinated chokepoint pressure maximizes economic leverage; forces US to split naval assets.',
        'window_hours': 48,
        'confidence':   'Medium',
    },
    {
        'id':          'ceasefire_collapse_escalation',
        'label':       'Post-Ceasefire Escalation Pattern',
        'description': 'Houthi Red Sea escalation following KSA-Houthi ceasefire breakdown',
        'source':      'UN Yemen Monitoring Mission; ACLED Yemen 2023-2024',
        'signals': {
            'ceasefire_level_min':     2,
            'maritime_level_min':      2,
            'direct_strike_level_min': 2,
        },
        'outcome':      'Ceasefire collapse correlated with Houthi pivot to maritime operations within 2-4 weeks.',
        'window_hours': 336,
        'confidence':   'Medium',
    },
]


# ============================================================
# HELPERS
# ============================================================

def _get_iran_crosstheater(scan_data):
    """Extract Iran Hormuz/coordination signals from crosstheater fingerprint."""
    for signal in scan_data.get('crosstheater_coordination', []):
        if signal.get('is_command_node') or signal.get('type') == 'proxy_activation':
            return True
    # Also check if Iran actor is elevated
    actors = scan_data.get('actors', {})
    iran_level = actors.get('iran', {}).get('escalation_level', 0)
    return iran_level >= 2


def _check_mandeb_language(scan_data):
    """Check for Bab el-Mandeb closure language in Houthi articles."""
    actors = scan_data.get('actors', {})
    for actor_id in ['houthis', 'iran']:
        for art in actors.get(actor_id, {}).get('top_articles', []):
            title = art.get('title', '').lower()
            if any(kw in title for kw in [
                'bab el-mandeb', 'bab al-mandeb', 'mandeb',
                'red sea blockade', 'close red sea', 'block strait',
                'strait closure', 'chokepoint'
            ]):
                return True
    return False


def _check_hormuz_from_iran(scan_data):
    """Read Iran's Hormuz signal from crosstheater data."""
    # Check coordination signals for Hormuz mention
    for sig in scan_data.get('crosstheater_coordination', []):
        msg = sig.get('message', '').lower() + sig.get('signal', '').lower()
        if 'hormuz' in msg or 'chokepoint' in msg:
            return True
    return False


# ============================================================
# CORE SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """Evaluate Yemen signal state against each red line."""
    actors          = scan_data.get('actors', {})
    maritime_level  = scan_data.get('maritime_level', 0)
    strike_level    = scan_data.get('direct_strike_level', 0)
    somaliland_level = scan_data.get('somaliland_level', 0)
    ceasefire_level = scan_data.get('ceasefire_level', 0)
    theatre_score   = scan_data.get('theatre_score', 0)

    houthi_level   = actors.get('houthis', {}).get('escalation_level', 0)
    us_level       = actors.get('usa', {}).get('escalation_level', 0)
    israel_level   = actors.get('israel', {}).get('escalation_level', 0)
    iran_level     = actors.get('iran', {}).get('escalation_level', 0)

    iran_coordination = _get_iran_crosstheater(scan_data)
    mandeb_threat     = _check_mandeb_language(scan_data)
    hormuz_from_iran  = _check_hormuz_from_iran(scan_data)

    triggered = []

    # ── Bab el-Mandeb closure declared ──
    if maritime_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'bab_mandeb_closure_declared'),
            'status':  'BREACHED' if maritime_level >= 5 else 'APPROACHING',
            'trigger': f'Maritime level L{maritime_level} -- active Red Sea/Mandeb closure language',
        })
    elif mandeb_threat and maritime_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'bab_mandeb_closure_declared'),
            'status':  'APPROACHING',
            'trigger': f'Bab el-Mandeb blockade language detected + maritime L{maritime_level}',
        })

    # ── DUAL CHOKEPOINT -- the big one ──
    if mandeb_threat and (iran_coordination or hormuz_from_iran or iran_level >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'dual_chokepoint_convergence'),
            'status':  'BREACHED' if (maritime_level >= 4 and iran_level >= 3) else 'APPROACHING',
            'trigger': f'Mandeb threat language + Iran coordination active -- dual chokepoint pattern',
        })

    # ── US carrier targeted ──
    if strike_level >= 4:
        for art in actors.get('houthis', {}).get('top_articles', []):
            title = art.get('title', '').lower()
            if any(kw in title for kw in ['carrier', 'uss ', 'strike group', 'naval vessel']):
                triggered.append({
                    **next(r for r in RED_LINES if r['id'] == 'us_carrier_targeted'),
                    'status':  'BREACHED',
                    'trigger': 'Carrier/US naval vessel targeting language in Houthi statements',
                })
                break

    # ── Ballistic at Israel ──
    if strike_level >= 4 and israel_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'ballistic_at_israel'),
            'status':  'BREACHED' if strike_level >= 5 else 'APPROACHING',
            'trigger': f'Strike L{strike_level} + Israel actor L{israel_level} -- ballistic posture elevated',
        })

    # ── Iran directive signal ──
    if iran_coordination and iran_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'iran_directive_signal'),
            'status':  'BREACHED' if iran_level >= 4 else 'APPROACHING',
            'trigger': f'Iran L{iran_level} + cross-theater coordination active -- IRGC direction signal',
        })

    # ── Ceasefire collapse ──
    if ceasefire_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'ceasefire_collapse'),
            'status':  'APPROACHING',
            'trigger': f'Ceasefire signal level {ceasefire_level} -- KSA-Houthi negotiations in flux',
        })

    # ── Somaliland ──
    if somaliland_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'somaliland_military_access'),
            'status':  'BREACHED' if somaliland_level >= 3 else 'APPROACHING',
            'trigger': f'Somaliland L{somaliland_level} -- US/Israeli Horn of Africa presence signals',
        })

    # ── CENTCOM escalatory strikes ──
    if us_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'centcom_strike_escalation'),
            'status':  'BREACHED' if us_level >= 5 else 'APPROACHING',
            'trigger': f'CENTCOM actor at L{us_level} -- escalatory strike package language',
        })

    triggered.sort(key=lambda x: (0 if x['status'] == 'BREACHED' else 1, -x['severity']))
    return triggered


def _match_historical(scan_data):
    """Match Yemen signal state against historical precedents."""
    actors          = scan_data.get('actors', {})
    maritime_level  = scan_data.get('maritime_level', 0)
    strike_level    = scan_data.get('direct_strike_level', 0)
    ceasefire_level = scan_data.get('ceasefire_level', 0)

    us_level     = actors.get('usa', {}).get('escalation_level', 0)
    israel_level = actors.get('israel', {}).get('escalation_level', 0)

    iran_coord   = _get_iran_crosstheater(scan_data)
    mandeb       = _check_mandeb_language(scan_data)

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

        if 'maritime_level_min' in sigs:
            check(maritime_level >= sigs['maritime_level_min'],
                  f'Maritime L{maritime_level} >= L{sigs["maritime_level_min"]}', weight=3)

        if 'direct_strike_level_min' in sigs:
            check(strike_level >= sigs['direct_strike_level_min'],
                  f'Strike L{strike_level} >= L{sigs["direct_strike_level_min"]}', weight=2)

        if 'us_level_min' in sigs:
            check(us_level >= sigs['us_level_min'],
                  f'US/CENTCOM L{us_level} >= L{sigs["us_level_min"]}', weight=2)

        if 'israel_level_min' in sigs:
            check(israel_level >= sigs['israel_level_min'],
                  f'Israel L{israel_level} >= L{sigs["israel_level_min"]}', weight=1)

        if 'iran_coordination' in sigs:
            check(iran_coord == sigs['iran_coordination'],
                  'Iran coordination active', weight=2)

        if 'mandeb_threat' in sigs:
            check(mandeb == sigs['mandeb_threat'],
                  'Mandeb blockade language', weight=2)

        if 'ceasefire_level_min' in sigs:
            check(ceasefire_level >= sigs['ceasefire_level_min'],
                  f'Ceasefire signal L{ceasefire_level} >= L{sigs["ceasefire_level_min"]}', weight=1)

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
    """Generate Yemen command node assessment."""
    actors          = scan_data.get('actors', {})
    maritime_level  = scan_data.get('maritime_level', 0)
    strike_level    = scan_data.get('direct_strike_level', 0)
    somaliland_level = scan_data.get('somaliland_level', 0)
    ceasefire_level = scan_data.get('ceasefire_level', 0)
    theatre_score   = scan_data.get('theatre_score', 0)
    delta           = scan_data.get('delta', {}) or {}
    delta_dir       = delta.get('direction', 'stable')
    score_change    = delta.get('score_change', 0)

    houthi_level = actors.get('houthis', {}).get('escalation_level', 0)
    us_level     = actors.get('usa', {}).get('escalation_level', 0)
    israel_level = actors.get('israel', {}).get('escalation_level', 0)
    iran_level   = actors.get('iran', {}).get('escalation_level', 0)

    iran_coord   = _get_iran_crosstheater(scan_data)
    mandeb       = _check_mandeb_language(scan_data)

    breached_count = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    top_match      = historical_matches[0] if historical_matches else None

    # ── Dual chokepoint check ──
    dual_chokepoint = mandeb and (iran_coord or iran_level >= 2)

    # ── Scenario label ──
    if dual_chokepoint and maritime_level >= 3:
        scenario       = 'DUAL CHOKEPOINT -- Iran/Houthi Coordinated Maritime Strategy'
        scenario_color = '#dc2626'
        scenario_icon  = '🔱'
    elif maritime_level >= 4 or strike_level >= 4:
        scenario       = 'ACTIVE CAMPAIGN -- Houthi Multi-Vector Escalation'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif maritime_level >= 3 or strike_level >= 3:
        scenario       = 'ELEVATED -- Red Sea / Strike Posture Rising'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif maritime_level >= 2 or strike_level >= 2:
        scenario       = 'WARNING -- Houthi Escalatory Signals'
        scenario_color = '#f59e0b'
        scenario_icon  = '🟡'
    else:
        scenario       = 'MONITORING -- Below Escalation Threshold'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Situation ──
    situation_parts = []

    if maritime_level >= 2:
        situation_parts.append(
            f'Houthi Red Sea campaign at maritime L{maritime_level} '
            f'({scan_data.get("maritime_label","")}) -- '
            f'{"active closure/blockade operations" if maritime_level >= 4 else "elevated shipping threat"}.'
        )

    if dual_chokepoint:
        situation_parts.append(
            'DUAL CHOKEPOINT SIGNAL ACTIVE: Iran is simultaneously threatening Strait of Hormuz '
            'while Houthis are signaling Bab el-Mandeb pressure -- coordinated strategy to '
            'maximize economic leverage and split US naval assets.'
        )

    if strike_level >= 3:
        situation_parts.append(
            f'Direct strike posture at L{strike_level} -- Houthi ballistic/drone campaign '
            f'{"actively targeting" if strike_level >= 4 else "threatening"} '
            f'{"Israel" if israel_level >= 3 else "regional assets"}.'
        )

    if us_level >= 3:
        situation_parts.append(
            f'CENTCOM posture at L{us_level} -- US counter-Houthi operations '
            f'{"escalating" if us_level >= 4 else "elevated"}.'
        )

    if delta_dir == 'rising' and score_change >= 10:
        situation_parts.append(
            f'Score rising sharply (+{round(score_change)} from recent average) -- accelerating trajectory.'
        )

    # ── Key indicators ──
    indicators = []

    if dual_chokepoint:
        indicators.append(
            'DUAL CHOKEPOINT: Iran threatening Hormuz + Houthis threatening Mandeb simultaneously. '
            'Combined closure would block ~30% of global oil transit and force US to split carrier assets '
            'between Persian Gulf and Red Sea.'
        )

    if iran_coord and iran_level >= 2:
        indicators.append(
            f'Iran coordination signals active (L{iran_level}) -- Houthi operations are '
            f'Iran-directed, not independent. Escalation decisions flow through IRGC Quds Force.'
        )

    if ceasefire_level >= 2:
        indicators.append(
            'KSA-Houthi ceasefire signals in play -- breakdown would free Houthis to '
            'fully redirect military capacity toward Red Sea campaign.'
        )

    if breached_count >= 2:
        indicators.append(
            f'{breached_count} red lines currently breached -- including signals that historically '
            f'precede US/Israeli military response against Houthi infrastructure.'
        )

    # ── Assessment ──
    assessment_parts = []
    if top_match and top_match['similarity'] >= 60:
        assessment_parts.append(
            f'Current signal pattern shows {top_match["similarity"]}% similarity to '
            f'{top_match["label"]}. In that case: {top_match["outcome"].lower()}'
        )
        assessment_parts.append(
            f'Confidence: {top_match["confidence"]} -- '
            f'{"multiple strong signal matches" if top_match["confidence"] == "High" else "partial signal match; outcome not determinative"}. '
            f'Historical response window: {top_match["window_hours"]} hours. Analytical estimate only.'
        )
    elif maritime_level >= 2:
        assessment_parts.append(
            'Active Red Sea/Mandeb signals present. Monitor for escalation toward formal '
            'closure declaration or direct US carrier engagement.'
        )

    # ── Watch list ──
    watch_items = [
        'Bab el-Mandeb -- any formal closure declaration or mine-laying reports',
        'Iran Hormuz signals -- dual chokepoint convergence if both activate simultaneously',
        'CENTCOM carrier deployment orders (splits assets between Gulf and Red Sea)',
        'IDF strike on Hodeidah or Houthi military infrastructure (triggers mass retaliation)',
        'KSA-Houthi ceasefire status -- breakdown = Houthi maritime escalation',
    ]
    if somaliland_level >= 1:
        watch_items.append('Somaliland/Berbera -- US or Israeli military access signals')

    return {
        'scenario':        scenario,
        'scenario_color':  scenario_color,
        'scenario_icon':   scenario_icon,
        'situation':       ' '.join(situation_parts),
        'key_indicators':  indicators,
        'assessment':      ' '.join(assessment_parts),
        'watch_list':      watch_items[:5],
        'dual_chokepoint': dual_chokepoint,
        'generated_at':    datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Yemen/Red Sea assessment generated from open-source signal data. '
            'Not a prediction. Verify through official channels before any operational decision.'
        ),
    }


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Called from rhetoric_tracker_yemen.py with full
    scan_data dict. Returns interpretation dict added as result['interpretation'].
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
        print(f'[Yemen Interpreter] Error: {str(e)[:120]}')
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
# Emits the canonical schema for Yemen signals that feeds:
#   - ME Regional BLUF (me_regional_bluf.py)
#   - Global Pressure Index (global_pressure_index.py)
#
# Yemen signals include the marquee DUAL CHOKEPOINT cross-theater
# fingerprint (Hormuz + Bab el-Mandeb simultaneous) which is detected
# by the GPI's _narrative_dual_chokepoint detector.
#
# Bidirectional migration model also surfaced as canonical signals:
#   - migration_surge: outbound flow (escalatory)
#   - diplomatic_active (return flow): de-escalatory
#
# Signal shape:
# {
#     'priority':   int,
#     'category':   str,        # red_line_breached / kinetic_pressure /
#                               #   dual_chokepoint / diplomatic_active /
#                               #   migration_surge / theatre_high /
#                               #   crosstheater_iran_yemen
#     'theatre':    'yemen',
#     'level':      int,
#     'icon':       str,
#     'color':      str,
#     'short_text': str,        # ≤80 char
#     'long_text':  str,        # ≤200 char
# }

YEMEN_FLAG = '\U0001f1fe\U0001f1ea'  # 🇾🇪


def build_top_signals(result):
    """
    Build Yemen's top_signals[] for BLUF/GPI consumption.
    Reads from a fully-built scan result (with interpretation attached).
    Returns sorted list (descending priority); BLUF/GPI dedupes globally.
    """
    signals = []

    theatre_level = result.get('theatre_escalation_level', 0) or 0
    theatre_score = result.get('theatre_score', result.get('rhetoric_score', 0)) or 0

    # Yemen-specific vectors
    maritime_lvl     = result.get('maritime_level',         0) or 0
    strike_lvl       = result.get('direct_strike_level',    0) or 0
    somaliland_lvl   = result.get('somaliland_level',       0) or 0

    # Diplomatic + migration (canonical multi-axis schema)
    diplomatic_active   = result.get('diplomatic_track_active',   False)
    diplomatic_modifier = result.get('diplomatic_modifier',       0) or 0
    migration_out_lvl   = result.get('migration_out_level',       0) or 0
    migration_return_lvl = result.get('migration_return_level',   0) or 0

    actors = result.get('actors', {}) or {}
    houthi_lvl     = actors.get('houthi',      {}).get('escalation_level', 0)
    ksa_lvl        = actors.get('ksa',         {}).get('escalation_level', 0)
    uae_lvl        = actors.get('uae',         {}).get('escalation_level', 0)
    israel_lvl     = actors.get('israel',      {}).get('escalation_level', 0)
    us_lvl         = actors.get('us',          {}).get('escalation_level', 0)

    # Pull interpretation block
    interp = result.get('interpretation', {}) or {}
    so_what = interp.get('so_what', {}) or {}
    rl_obj  = interp.get('red_lines', {}) or {}

    dual_chokepoint = so_what.get('dual_chokepoint', False)

    # ============================================
    # CATEGORY 1: DUAL CHOKEPOINT (Yemen's marquee cross-theater signal)
    # ============================================
    # When Houthi maritime escalation co-occurs with Iran Hormuz signals,
    # this lights up the GPI dual_chokepoint narrative (priority 13).
    if dual_chokepoint:
        signals.append({
            'priority':   13,
            'category':   'dual_chokepoint',
            'theatre':    'yemen',
            'level':      max(maritime_lvl, 4),
            'icon':       '🚢',
            'color':      '#dc2626',
            'short_text': f'{YEMEN_FLAG} YEMEN: Dual chokepoint -- Bab el-Mandeb + Hormuz',
            'long_text':  (f'YEMEN: Houthi Bab el-Mandeb / Red Sea pressure converging with '
                           f'Iranian Strait of Hormuz signaling. High-impact maritime '
                           f'supply-chain scenario; global energy + shipping shock if activated.'),
        })

    # ============================================
    # CATEGORY 2: RED LINES BREACHED
    # ============================================
    for rl in rl_obj.get('triggered', []):
        if rl.get('status') == 'BREACHED':
            severity = int(rl.get('severity', 0) or 0)
            signals.append({
                'priority':   12 if severity >= 3 else 11,
                'category':   'red_line_breached',
                'theatre':    'yemen',
                'level':      max(theatre_level, severity * 2),
                'icon':       rl.get('icon', '🚨'),
                'color':      '#dc2626',
                'short_text': f'{YEMEN_FLAG} YEMEN: {rl.get("label", "Red line breached")[:60]}',
                'long_text':  (f'YEMEN red line breached -- {rl.get("label", "")}: '
                               f'{rl.get("trigger", "")[:140]}'),
            })

    # ============================================
    # CATEGORY 3: MARITIME THREAT (Bab el-Mandeb / Red Sea)
    # ============================================
    if maritime_lvl >= 4:
        signals.append({
            'priority':   11,
            'category':   'kinetic_pressure',
            'theatre':    'yemen',
            'level':      maritime_lvl,
            'icon':       '🚢',
            'color':      '#dc2626',
            'short_text': f'{YEMEN_FLAG} YEMEN: Maritime threat L{maritime_lvl} -- Bab el-Mandeb',
            'long_text':  (f'YEMEN: Houthi (Ansar Allah) maritime threat at L{maritime_lvl}. '
                           f'Bab el-Mandeb / Red Sea / Suez supply chain pressure; '
                           f'commercial shipping risk window open.'),
        })
    elif maritime_lvl >= 3:
        signals.append({
            'priority':   9,
            'category':   'kinetic_pressure',
            'theatre':    'yemen',
            'level':      maritime_lvl,
            'icon':       '🌊',
            'color':      '#f97316',
            'short_text': f'{YEMEN_FLAG} YEMEN: Maritime pressure L{maritime_lvl}',
            'long_text':  (f'YEMEN: Houthi (Ansar Allah) maritime pressure at L{maritime_lvl}. '
                           f'Red Sea / Bab el-Mandeb activity elevated; commercial shipping '
                           f'monitoring elevated.'),
        })

    # ============================================
    # CATEGORY 4: DIRECT STRIKE THREAT (Israel / KSA / UAE / US bases)
    # ============================================
    if strike_lvl >= 4:
        signals.append({
            'priority':   11,
            'category':   'kinetic_pressure',
            'theatre':    'yemen',
            'level':      strike_lvl,
            'icon':       '🎯',
            'color':      '#dc2626',
            'short_text': f'{YEMEN_FLAG} YEMEN: Direct strike threat L{strike_lvl}',
            'long_text':  (f'YEMEN: Houthi direct strike threat at L{strike_lvl} -- '
                           f'Israel / Kingdom of Saudi Arabia (KSA) / United Arab Emirates '
                           f'(UAE) / US bases. Drone/missile launch posture; air defense '
                           f'tempo elevated.'),
        })
    elif strike_lvl >= 3:
        signals.append({
            'priority':   9,
            'category':   'kinetic_pressure',
            'theatre':    'yemen',
            'level':      strike_lvl,
            'icon':       '🚀',
            'color':      '#f97316',
            'short_text': f'{YEMEN_FLAG} YEMEN: Direct strike rhetoric L{strike_lvl}',
            'long_text':  (f'YEMEN: Houthi direct strike rhetoric at L{strike_lvl}. '
                           f'Threat language vs Israel / KSA / UAE / US elevated; '
                           f'kinetic activity not yet declared.'),
        })

    # ============================================
    # CATEGORY 5: HOUTHI ACTOR HIGH (composite escalation)
    # ============================================
    if houthi_lvl >= 4 and not (maritime_lvl >= 4 or strike_lvl >= 4):
        # Only fire if maritime/strike haven't already covered it
        signals.append({
            'priority':   10,
            'category':   'theatre_high',
            'theatre':    'yemen',
            'level':      houthi_lvl,
            'icon':       '🔴',
            'color':      '#dc2626',
            'short_text': f'{YEMEN_FLAG} YEMEN: Houthi composite L{houthi_lvl}',
            'long_text':  (f'YEMEN: Ansar Allah (Houthi) composite escalation at L{houthi_lvl}. '
                           f'Multi-vector threat language across maritime, direct strike, '
                           f'and political signaling.'),
        })

    # ============================================
    # CATEGORY 6: MIGRATION SURGE OUTBOUND (humanitarian + escalatory)
    # ============================================
    if migration_out_lvl >= 3:
        signals.append({
            'priority':   8,
            'category':   'migration_surge',
            'theatre':    'yemen',
            'level':      migration_out_lvl,
            'icon':       '🚶',
            'color':      '#f59e0b',
            'short_text': f'{YEMEN_FLAG} YEMEN: Migration outflow L{migration_out_lvl}',
            'long_text':  (f'YEMEN: Outbound migration pressure at L{migration_out_lvl} -- '
                           f'Yemen→Oman / KSA / Horn of Africa corridor. Humanitarian '
                           f'precursor signal; ground escalation indicator.'),
        })

    # ============================================
    # CATEGORY 7: MIGRATION RETURN FLOW (de-escalatory positive signal)
    # ============================================
    if migration_return_lvl >= 3:
        signals.append({
            'priority':   6,
            'category':   'diplomatic_active',
            'theatre':    'yemen',
            'level':      migration_return_lvl,
            'icon':       '↩️',
            'color':      '#10b981',
            'short_text': f'{YEMEN_FLAG} YEMEN: Return migration L{migration_return_lvl} (de-escalation)',
            'long_text':  (f'YEMEN: Return migration flow at L{migration_return_lvl} -- '
                           f'Yemenis returning from Oman/KSA. De-escalatory ground signal; '
                           f'humanitarian normalization indicator.'),
        })

    # ============================================
    # CATEGORY 8: DIPLOMATIC TRACK (KSA-Houthi negotiations)
    # ============================================
    if diplomatic_active and diplomatic_modifier <= -3:
        signals.append({
            'priority':   8,
            'category':   'diplomatic_active',
            'theatre':    'yemen',
            'level':      0,
            'icon':       '🕊️',
            'color':      '#10b981',
            'short_text': f'{YEMEN_FLAG} YEMEN: KSA-Houthi diplomatic track active',
            'long_text':  (f'YEMEN: Diplomatic track active (modifier {diplomatic_modifier}) -- '
                           f'KSA-Houthi negotiations / mediator activity. Off-ramp signaling; '
                           f'de-escalation modifier applied to threat score.'),
        })

    # ============================================
    # CATEGORY 9: SOMALILAND / HORN OF AFRICA GROUND OPS
    # ============================================
    if somaliland_lvl >= 3:
        signals.append({
            'priority':   7,
            'category':   'kinetic_pressure',
            'theatre':    'yemen',
            'level':      somaliland_lvl,
            'icon':       '🌍',
            'color':      '#f97316',
            'short_text': f'{YEMEN_FLAG} YEMEN: Somaliland/Horn ground signal L{somaliland_lvl}',
            'long_text':  (f'YEMEN: Somaliland / Horn of Africa ground operation precursor '
                           f'signals at L{somaliland_lvl}. Berbera / US or Israeli military '
                           f'access dynamics; Bab el-Mandeb southern flank activity.'),
        })

    # ============================================
    # CATEGORY 10: THEATRE COMPOSITE HIGH (catch-all)
    # ============================================
    if (theatre_level >= 4 or theatre_score >= 70) and \
       not any(s.get('category') in ('kinetic_pressure', 'theatre_high', 'dual_chokepoint')
               for s in signals):
        signals.append({
            'priority':   9,
            'category':   'theatre_high',
            'theatre':    'yemen',
            'level':      theatre_level,
            'icon':       '🔴',
            'color':      '#dc2626',
            'short_text': f'{YEMEN_FLAG} YEMEN: Theatre composite L{theatre_level} ({theatre_score}/100)',
            'long_text':  (f'YEMEN composite rhetoric at L{theatre_level} '
                           f'(score {theatre_score}/100). Multi-vector pressure across '
                           f'maritime, direct strike, and political channels.'),
        })

    # Sort descending by priority
    signals.sort(key=lambda s: s.get('priority', 0), reverse=True)
    return signals


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    test_data = {
        'theatre_score':      80,
        'maritime_level':     4,
        'maritime_label':     'Attack Declared',
        'direct_strike_level': 3,
        'somaliland_level':   1,
        'ceasefire_level':    2,
        'delta': {'direction': 'rising', 'score_change': 12},
        'crosstheater_coordination': [
            {'is_command_node': True, 'type': 'proxy_activation',
             'message': 'Iran proxy network activation -- Hormuz threat simultaneous'}
        ],
        'actors': {
            'houthis': {'escalation_level': 4, 'statement_count': 22, 'top_articles': [
                {'title': 'Houthis declare all ships in Red Sea are targets for blockade', 'published': ''},
                {'title': 'Bab el-Mandeb closure imminent as Houthi naval forces deploy', 'published': ''},
            ]},
            'usa':     {'escalation_level': 3, 'statement_count': 8, 'top_articles': []},
            'israel':  {'escalation_level': 3, 'statement_count': 5, 'top_articles': []},
            'iran':    {'escalation_level': 3, 'statement_count': 4, 'top_articles': []},
            'ksa':     {'escalation_level': 1, 'statement_count': 2, 'top_articles': []},
            'uae':     {'escalation_level': 1, 'statement_count': 1, 'top_articles': []},
        },
    }

    result = interpret_signals(test_data)

    print('\n' + '='*60)
    print('SCENARIO:', result['so_what']['scenario'])
    print('DUAL CHOKEPOINT:', result['so_what']['dual_chokepoint'])
    print('='*60)
    print('\nSITUATION:')
    print(result['so_what']['situation'])
    print('\nKEY INDICATORS:')
    for ind in result['so_what']['key_indicators']:
        print(f'  -- {ind[:100]}')
    print('\nASSESSMENT:')
    print(result['so_what']['assessment'])
    print('\nWATCH LIST:')
    for item in result['so_what']['watch_list']:
        print(f'  -> {item}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} (Sev {rl["severity"]})')
        print(f'     {rl["trigger"]}')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]} | Window: {hm["window_hours"]}h')
