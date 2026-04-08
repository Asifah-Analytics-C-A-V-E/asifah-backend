"""
me_regional_bluf.py
Asifah Analytics -- ME Backend Module
v1.0.0

ME Regional BLUF (Bottom Line Up Front) Engine.

Reads from all six ME rhetoric tracker Redis caches simultaneously
and synthesizes a single analyst-prose BLUF paragraph + three
structured top-line signals.

Updated every time any tracker scan completes, or on-demand via
/api/rhetoric/me/bluf endpoint.

No new scanning -- pure synthesis layer over existing cached data.

Author: RCGG / Asifah Analytics
"""

import json
import time
import requests
from datetime import datetime, timezone

import os
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

BLUF_CACHE_KEY = 'rhetoric:me:regional_bluf'
BLUF_CACHE_TTL = 14 * 3600  # 14h -- outlasts any individual tracker TTL


# ============================================================
# REDIS HELPERS
# ============================================================

def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        result = resp.json().get('result')
        return json.loads(result) if result else None
    except Exception as e:
        print(f'[ME BLUF] Redis GET error ({key}): {e}')
        return None


def _redis_set(key, value, ttl=BLUF_CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str)
        params = {'EX': ttl} if ttl else {}
        resp = requests.post(
            f'{UPSTASH_REDIS_URL}/set/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json'
            },
            data=payload,
            params=params,
            timeout=5
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f'[ME BLUF] Redis SET error ({key}): {e}')
        return False


# ============================================================
# CACHE KEY MAP -- all six ME trackers
# ============================================================
TRACKER_KEYS = {
    'israel':  ('rhetoric:israel:latest',   'israel_rhetoric_cache'),
    'iran':    ('rhetoric:iran:latest',      'iran_rhetoric_cache'),
    'lebanon': ('rhetoric:lebanon:latest',   'lebanon_rhetoric_cache'),
    'yemen':   ('yemen_rhetoric_cache',      None),
    'syria':   ('rhetoric:syria:latest',     'syria_rhetoric_cache'),
    'iraq':    ('rhetoric:iraq:latest',      'iraq_rhetoric_cache'),
}

THEATRE_FLAGS = {
    'israel':  '\U0001f1ee\U0001f1f1',
    'iran':    '\U0001f1ee\U0001f1f7',
    'lebanon': '\U0001f1f1\U0001f1e7',
    'yemen':   '\U0001f1fe\U0001f1ea',
    'syria':   '\U0001f1f8\U0001f1fe',
    'iraq':    '\U0001f1ee\U0001f1f6',
}

ESCALATION_LABELS = {
    0: 'Monitoring',
    1: 'Rhetoric',
    2: 'Warning',
    3: 'Direct Threat',
    4: 'Incident',
    5: 'Active Conflict',
}

ESCALATION_COLORS = {
    0: '#6b7280',
    1: '#3b82f6',
    2: '#f59e0b',
    3: '#f97316',
    4: '#ef4444',
    5: '#dc2626',
}


# ============================================================
# DATA INGESTION -- read all six caches
# ============================================================

def _read_all_trackers():
    """Read all six ME tracker caches. Returns dict keyed by theatre."""
    results = {}
    for theatre, (primary_key, fallback_key) in TRACKER_KEYS.items():
        data = _redis_get(primary_key)
        if not data and fallback_key:
            data = _redis_get(fallback_key)
        if data:
            results[theatre] = data
            print(f'[ME BLUF] {theatre}: loaded (score={data.get("theatre_score", data.get("rhetoric_score", "?"))})')
        else:
            print(f'[ME BLUF] {theatre}: no cache available')
    return results


def _get_theatre_level(data, theatre):
    """Normalize theatre level across different tracker field names."""
    if theatre == 'israel':
        # Israel uses inbound/outbound; use inbound as primary
        return data.get('inbound_max_level', data.get('theatre_escalation_level', 0))
    elif theatre == 'iran':
        return data.get('theatre_escalation_level', 0)
    elif theatre == 'yemen':
        # Yemen uses string level
        score = data.get('theatre_score', 0)
        if score >= 80: return 5
        if score >= 60: return 4
        if score >= 40: return 3
        if score >= 25: return 2
        if score >= 10: return 1
        return 0
    else:
        return data.get('theatre_escalation_level',
               data.get('theatre_level', 0))


def _get_theatre_score(data, theatre):
    return data.get('theatre_score',
           data.get('rhetoric_score', 0))


# ============================================================
# SYNTHESIS ENGINE
# ============================================================

def _build_posture_label(max_level, theatres_at_l3plus):
    """Derive regional posture label from signal state."""
    if max_level == 5:
        return ('ACTIVE CONFLICT', '#dc2626')
    elif max_level >= 4 or theatres_at_l3plus >= 3:
        return ('ELEVATED -- INCIDENT LEVEL', '#ef4444')
    elif max_level >= 3 or theatres_at_l3plus >= 2:
        return ('ELEVATED -- DIRECT THREAT', '#f97316')
    elif max_level >= 2:
        return ('WARNING', '#f59e0b')
    elif max_level >= 1:
        return ('MONITORING -- RHETORIC LEVEL', '#3b82f6')
    return ('MONITORING', '#6b7280')


def _extract_key_signals(trackers):
    """Extract the top 3 structured signal bullets from all theatres."""
    signals = []

    # Collect raw signals from each tracker
    for theatre, data in trackers.items():
        level = _get_theatre_level(data, theatre)
        score = _get_theatre_score(data, theatre)
        interp = data.get('interpretation', {})
        so_what = interp.get('so_what', {}) if interp else {}
        red_lines = interp.get('red_lines', {}) if interp else {}

        # Breached red lines are highest priority
        breached_count = red_lines.get('breached_count', 0)
        triggered = red_lines.get('triggered', [])
        for rl in triggered:
            if rl.get('status') == 'BREACHED':
                signals.append({
                    'priority': 10 + level,
                    'theatre':  theatre,
                    'level':    level,
                    'type':     'red_line_breached',
                    'text':     f'{THEATRE_FLAGS[theatre]} {theatre.upper()} L{level}: '
                                f'{rl["label"]} -- {rl.get("trigger", "")[:80]}',
                    'color':    '#dc2626',
                    'icon':     rl.get('icon', '🚨'),
                })

        # Silence anomalies
        for anom in data.get('silence_anomalies', []):
            if anom.get('deviation') and '100%' in str(anom.get('deviation', '')):
                actor_name = anom.get('actor_name', anom.get('actor_id', 'Unknown'))
                signals.append({
                    'priority': 6 + level,
                    'theatre':  theatre,
                    'level':    level,
                    'type':     'silence_anomaly',
                    'text':     f'{THEATRE_FLAGS[theatre]} {theatre.upper()}: '
                                f'{actor_name} SILENT -- {anom.get("signal", "Unusual quiet")}',
                    'color':    '#f59e0b',
                    'icon':     '🔇',
                })

        # Cross-theater coordination
        crosstheater = data.get('crosstheater_coordination', [])
        for ct in crosstheater:
            if ct.get('confidence', 0) >= 60 and ct.get('type') == 'simultaneous_elevation':
                theaters_in = ct.get('theaters', [])
                signals.append({
                    'priority': 8,
                    'theatre':  'regional',
                    'level':    level,
                    'type':     'crosstheater',
                    'text':     f'CROSS-THEATER: Simultaneous elevation across '
                                f'{", ".join(t.upper() for t in theaters_in)} '
                                f'({ct.get("confidence", 0)}% confidence) -- '
                                f'{ct.get("signal", "")}',
                    'color':    '#7c3aed',
                    'icon':     '🔗',
                })

        # High-level theatre signals
        if level >= 4:
            signals.append({
                'priority': 9 + level,
                'theatre':  theatre,
                'level':    level,
                'type':     'theatre_high',
                'text':     f'{THEATRE_FLAGS[theatre]} {theatre.upper()} at L{level} '
                            f'{ESCALATION_LABELS.get(level, "")} '
                            f'(score {score}/100)',
                'color':    ESCALATION_COLORS.get(level, '#6b7280'),
                'icon':     '🔴',
            })

        # Interpreter-specific flags
        if so_what:
            if so_what.get('sadr_silent'):
                signals.append({
                    'priority': 7,
                    'theatre': 'iraq',
                    'level':   level,
                    'type':    'sadr',
                    'text':    'IRAQ: Al-Sadr SILENT -- historical pattern precedes mobilization (2020, 2022)',
                    'color':   '#7c3aed',
                    'icon':    '👁️',
                })
            if so_what.get('dual_chokepoint'):
                signals.append({
                    'priority': 10,
                    'theatre': 'yemen',
                    'level':   level,
                    'type':    'dual_chokepoint',
                    'text':    'DUAL CHOKEPOINT: Hormuz + Bab el-Mandeb simultaneous signals -- '
                               'coordinated blockade risk',
                    'color':   '#7c3aed',
                    'icon':    '🔱',
                })
            if so_what.get('laf_enforcement_gap'):
                signals.append({
                    'priority': 6,
                    'theatre': 'lebanon',
                    'level':   level,
                    'type':    'laf_gap',
                    'text':    'LEBANON: LAF enforcement gap persists -- '
                               'Israeli withdrawal conditions not met',
                    'color':   '#f97316',
                    'icon':    '🏳️',
                })
            if so_what.get('iran_expelled') and theatre == 'syria':
                signals.append({
                    'priority': 5,
                    'theatre': 'syria',
                    'level':   level,
                    'type':    'iran_expelled',
                    'text':    'SYRIA: Iran expelled -- Hezbollah resupply corridor severed. '
                               'Transition holding.',
                    'color':   '#10b981',
                    'icon':    '✅',
                })

    # Sort by priority descending, deduplicate by type+theatre
    signals.sort(key=lambda x: x['priority'], reverse=True)
    seen = set()
    deduped = []
    for s in signals:
        key = f'{s["theatre"]}:{s["type"]}'
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    return deduped[:3]


def _write_bluf_prose(trackers, levels, scores, max_level,
                      theatres_at_l3plus, top_signals):
    """
    Write a single analyst-prose BLUF paragraph.
    Style: direct declarative sentences, no hedging, intelligence product voice.
    """
    now_str = datetime.now(timezone.utc).strftime('%d %b %Y %H:%MZ')

    # Lead: posture + active conflict theatres
    l5_theatres  = [t for t, l in levels.items() if l >= 5]
    l4_theatres  = [t for t, l in levels.items() if l == 4]
    l3_theatres  = [t for t, l in levels.items() if l == 3]
    low_theatres = [t for t, l in levels.items() if l <= 1]

    parts = []

    # Opening posture sentence
    if l5_theatres and l4_theatres:
        active = ', '.join(t.upper() for t in l5_theatres)
        incident = ', '.join(t.upper() for t in l4_theatres)
        parts.append(
            f'ME BLUF ({now_str}): Regional posture is CRITICAL with {len(l5_theatres)+len(l4_theatres)} '
            f'theatres at L4+. Active conflict in {active}; incident-level in {incident}.'
        )
    elif l5_theatres:
        active = ', '.join(t.upper() for t in l5_theatres)
        parts.append(
            f'ME BLUF ({now_str}): Active conflict confirmed in {len(l5_theatres)} '
            f'theatre{"s" if len(l5_theatres) > 1 else ""} ({active}). '
            f'Regional posture ELEVATED.'
        )
    elif l4_theatres:
        incident = ', '.join(t.upper() for t in l4_theatres)
        parts.append(
            f'ME BLUF ({now_str}): Incident-level signals in {incident}. '
            f'Regional posture ELEVATED.'
        )
    elif l3_theatres:
        parts.append(
            f'ME BLUF ({now_str}): Direct threat signals in '
            f'{", ".join(t.upper() for t in l3_theatres)}. '
            f'Regional posture at WARNING level.'
        )
    else:
        parts.append(
            f'ME BLUF ({now_str}): All ME theatres below direct threat threshold. '
            f'Regional posture MONITORING.'
        )

    # Cross-theater coordination sentence
    iran_data = trackers.get('iran', {})
    iran_interp = iran_data.get('interpretation', {})
    iran_so = iran_interp.get('so_what', {}) if iran_interp else {}

    coordination_theatres = []
    for t, data in trackers.items():
        for ct in data.get('crosstheater_coordination', []):
            if ct.get('confidence', 0) >= 60:
                for theatre in ct.get('theaters', []):
                    if theatre not in coordination_theatres:
                        coordination_theatres.append(theatre)

    if len(coordination_theatres) >= 2:
        parts.append(
            f'Cross-theater coordination signals detected across '
            f'{", ".join(t.upper() for t in coordination_theatres[:3])} -- '
            f'watch for synchronized proxy operations.'
        )

    # Iran/ceasefire context
    iraq_data  = trackers.get('iraq', {})
    iraq_interp = iraq_data.get('interpretation', {})
    iraq_so    = iraq_interp.get('so_what', {}) if iraq_interp else {}
    ceasefire  = iraq_so.get('ceasefire_active', False)

    # Check for OTP signals in Iran
    otp_count = iran_data.get('otp_signal_count', iran_data.get('otp_count', 0))
    if otp_count and otp_count >= 10:
        parts.append(
            f'Iran Operation True Promise signals at {otp_count} -- '
            f'axis-wide escalation posture active.'
        )
    elif ceasefire:
        parts.append(
            'Trump-Iran ceasefire (7 Apr) in effect -- '
            'watch IRGC-directed proxies in Iraq/Lebanon for compliance signals.'
        )

    # Lebanon/Hezbollah sentence if active
    leb_data   = trackers.get('lebanon', {})
    leb_level  = levels.get('lebanon', 0)
    leb_interp = leb_data.get('interpretation', {})
    leb_so     = leb_interp.get('so_what', {}) if leb_interp else {}
    if leb_level >= 4:
        iran_directing = leb_so.get('iran_directing', False)
        laf_gap        = leb_so.get('laf_enforcement_gap', False)
        parts.append(
            f'Hezbollah operating at L{leb_level}'
            f'{" under Iranian direction" if iran_directing else ""}'
            f'{"; LAF enforcement gap persists" if laf_gap else ""}.'
        )

    # Houthi silence if detected
    yemen_data   = trackers.get('yemen', {})
    houthi_actor = yemen_data.get('actors', {}).get('houthis', {})
    houthi_silent = houthi_actor.get('statement_count', 1) == 0
    if houthi_silent:
        parts.append(
            'Houthi/Ansar Allah anomalously silent -- '
            'operational security or patron (Iran) direction to stand down.'
        )

    # Syria positive note if transition holding
    syria_data   = trackers.get('syria', {})
    syria_interp = syria_data.get('interpretation', {})
    syria_so     = syria_interp.get('so_what', {}) if syria_interp else {}
    if syria_so.get('iran_expelled') and levels.get('syria', 0) <= 1:
        parts.append(
            'Syria transition holding; Iran expelled and corridor severed.'
        )

    # Closing risk sentence
    if max_level >= 4:
        parts.append(
            'Primary risk: ceasefire collapse triggering simultaneous multi-axis activation '
            'across Lebanon, Iraq, and Yemen vectors.'
        )
    elif max_level >= 3:
        parts.append(
            'Primary risk: proxy escalation without direct state direction '
            'expanding conflict footprint.'
        )

    return ' '.join(parts)


# ============================================================
# MAIN BUILD FUNCTION
# ============================================================

def build_regional_bluf(force=False):
    """
    Build the ME regional BLUF. Reads all six caches, synthesizes,
    caches result in Redis. Returns dict.
    """
    if not force:
        cached = _redis_get(BLUF_CACHE_KEY)
        if cached and cached.get('generated_at'):
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(cached['generated_at'])).total_seconds()
                if age < BLUF_CACHE_TTL:
                    cached['from_cache'] = True
                    return cached
            except Exception:
                pass

    print('[ME BLUF] Building regional BLUF from all six tracker caches...')
    trackers = _read_all_trackers()

    if not trackers:
        return {
            'success': False,
            'error':   'No tracker data available',
            'bluf':    'BLUF unavailable -- no tracker caches loaded.',
            'signals': [],
        }

    # Normalize levels and scores
    levels = {t: _get_theatre_level(d, t) for t, d in trackers.items()}
    scores = {t: _get_theatre_score(d, t) for t, d in trackers.items()}

    max_level         = max(levels.values()) if levels else 0
    avg_score         = round(sum(scores.values()) / len(scores), 1) if scores else 0
    theatres_at_l3plus = sum(1 for l in levels.values() if l >= 3)
    theatres_live      = len(trackers)

    posture_label, posture_color = _build_posture_label(max_level, theatres_at_l3plus)

    # Extract top 3 signals
    top_signals = _extract_key_signals(trackers)

    # Write BLUF prose
    bluf_prose = _write_bluf_prose(
        trackers, levels, scores,
        max_level, theatres_at_l3plus, top_signals
    )

    # Per-theatre summary (for display)
    theatre_summary = {}
    for t, data in trackers.items():
        lvl = levels[t]
        theatre_summary[t] = {
            'level':       lvl,
            'label':       ESCALATION_LABELS.get(lvl, 'Unknown'),
            'color':       ESCALATION_COLORS.get(lvl, '#6b7280'),
            'score':       scores[t],
            'flag':        THEATRE_FLAGS[t],
            'timestamp':   data.get('timestamp', data.get('scanned_at', '')),
        }

    result = {
        'success':           True,
        'from_cache':        False,
        'bluf':              bluf_prose,
        'signals':           top_signals,
        'posture_label':     posture_label,
        'posture_color':     posture_color,
        'max_level':         max_level,
        'avg_score':         avg_score,
        'theatres_at_l3plus':theatres_at_l3plus,
        'theatres_live':     theatres_live,
        'theatre_summary':   theatre_summary,
        'generated_at':      datetime.now(timezone.utc).isoformat(),
        'version':           '1.0.0',
    }

    _redis_set(BLUF_CACHE_KEY, result)
    print(f'[ME BLUF] Built: posture={posture_label}, max_level={max_level}, '
          f'avg_score={avg_score}, signals={len(top_signals)}')
    return result


# ============================================================
# ROUTE REGISTRATION
# ============================================================

def register_me_bluf_routes(app):
    """Register BLUF endpoint on ME Flask app."""
    from flask import jsonify, request as flask_request

    @app.route('/api/rhetoric/me/bluf', methods=['GET'])
    def me_regional_bluf():
        force = flask_request.args.get('force', 'false').lower() == 'true'
        result = build_regional_bluf(force=force)
        return jsonify(result)

    print('[ME BLUF] Routes registered: /api/rhetoric/me/bluf')


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    print("ME Regional BLUF Engine -- standalone test")
    print("(Requires Redis env vars to actually read tracker caches)")
    print()

    # Simulate what the output looks like with mock data
    mock_result = {
        'bluf': (
            'ME BLUF (08 Apr 2026 00:00Z): Regional posture is CRITICAL with 3 theatres at L4+. '
            'Active conflict in ISRAEL, IRAN, LEBANON; incident-level in IRAQ. '
            'Cross-theater coordination signals detected across LEBANON, IRAQ, YEMEN -- '
            'watch for synchronized proxy operations. '
            'Iran Operation True Promise signals at 46 -- axis-wide escalation posture active. '
            'Hezbollah operating at L5 under Iranian direction; LAF enforcement gap persists. '
            'Houthi/Ansar Allah anomalously silent -- operational security or patron direction to stand down. '
            'Syria transition holding; Iran expelled and corridor severed. '
            'Primary risk: ceasefire collapse triggering simultaneous multi-axis activation '
            'across Lebanon, Iraq, and Yemen vectors.'
        ),
        'signals': [
            {
                'icon': '🔴', 'color': '#dc2626',
                'text': '🇮🇱 ISRAEL at L5 Active Conflict (score 97/100)',
            },
            {
                'icon': '🔗', 'color': '#7c3aed',
                'text': 'CROSS-THEATER: Simultaneous elevation across LEBANON, IRAQ, YEMEN (90% confidence)',
            },
            {
                'icon': '🔇', 'color': '#f59e0b',
                'text': '🇾🇪 YEMEN: Ansar Allah (Houthis) SILENT -- possible operational security',
            },
        ],
        'posture_label': 'ELEVATED -- INCIDENT LEVEL',
        'posture_color': '#ef4444',
        'max_level': 5,
        'avg_score': 56.8,
        'theatres_at_l3plus': 4,
        'theatres_live': 6,
    }

    print('BLUF:')
    print(mock_result['bluf'])
    print()
    print('TOP SIGNALS:')
    for s in mock_result['signals']:
        print(f'  {s["icon"]} {s["text"][:100]}')
    print()
    print(f'POSTURE: {mock_result["posture_label"]} | MAX L{mock_result["max_level"]} | AVG {mock_result["avg_score"]}')
