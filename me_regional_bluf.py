"""
me_regional_bluf.py
Asifah Analytics -- ME Backend Module
v2.0.0  (Apr 26 2026)

ME Regional BLUF (Bottom Line Up Front) Engine.

Reads from all SEVEN ME rhetoric tracker Redis caches simultaneously
and synthesizes a single analyst-prose BLUF paragraph + top-5 structured
signals.

v2.0 Architectural Changes:
  - Dual-axis aware (handles Oman threat + influence vectors)
  - Backward compatibility shim — works with v1.x trackers AND
    v2.x trackers that self-emit top_signals[]
  - New signal categories: mediation_active, influence_high, green_line_active
  - Top 5 signals (was top 3) — richer briefing while still scannable
  - Designed to be GPI-compatible: emits regional top_signals[] for
    consumption by global_pressure_index.py at the next altitude

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
TOP_SIGNALS_COUNT = 5  # v2.0: was 3


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
# CACHE KEY MAP -- all SEVEN ME trackers
# ============================================================
TRACKER_KEYS = {
    'israel':  ('rhetoric:israel:latest',   'israel_rhetoric_cache'),
    'iran':    ('rhetoric:iran:latest',      'iran_rhetoric_cache'),
    'lebanon': ('rhetoric:lebanon:latest',   'lebanon_rhetoric_cache'),
    'yemen':   ('yemen_rhetoric_cache',      None),
    'syria':   ('rhetoric:syria:latest',     'syria_rhetoric_cache'),
    'iraq':    ('rhetoric:iraq:latest',      'iraq_rhetoric_cache'),
    'oman':    ('rhetoric:oman:latest',      None),  # v2.0: dual-axis stability anchor
}

THEATRE_FLAGS = {
    'israel':  '\U0001f1ee\U0001f1f1',
    'iran':    '\U0001f1ee\U0001f1f7',
    'lebanon': '\U0001f1f1\U0001f1e7',
    'yemen':   '\U0001f1fe\U0001f1ea',
    'syria':   '\U0001f1f8\U0001f1fe',
    'iraq':    '\U0001f1ee\U0001f1f6',
    'oman':    '\U0001f1f4\U0001f1f2',  # v2.0: Oman flag 🇴🇲
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

# v2.0: Per-region influence-side coloring (for stability anchors like Oman)
INFLUENCE_LABELS = {
    0: 'Standby',
    1: 'Engaged',
    2: 'Active',
    3: 'Mediation Engaged',
    4: 'High-Stakes Mediation',
    5: 'Crisis Mediation',
}

INFLUENCE_COLORS = {
    0: '#6b7280',
    1: '#a78bfa',
    2: '#8b5cf6',
    3: '#7c3aed',
    4: '#6d28d9',
    5: '#5b21b6',
}


# ============================================================
# COMPATIBILITY SHIM -- v2.0
# ============================================================
# Trackers will gradually be upgraded to emit a canonical shape.
# Until then, this shim normalizes ALL trackers (old and new) into
# the same internal representation that the BLUF engine consumes.
#
# Canonical internal shape:
# {
#     'theatre':           str,
#     'flag':              str,
#     'levels': {
#         'threat':         0-5,
#         'influence':      0-5 or None,   # only for stability anchors
#         'green':          0-5 or None,   # only for trackers w/ green lines
#         'dominant_axis':  'threat' | 'influence' | 'green',
#         'dominant_level': 0-5,
#     },
#     'score':             0-100,
#     'so_what':           {...},          # interpreter output
#     'red_lines':         {...},
#     'green_lines':       {...} or None,  # OPTIONAL
#     'diplomatic_track':  {...} or None,  # OPTIONAL
#     'historical_matches':[...] or None,  # OPTIONAL
#     'top_signals':       [...],          # NEW v2.0 — pre-prioritized
#     'silence_anomalies': [...],          # legacy
#     'crosstheater_coordination': [...],  # legacy
#     'raw':               <untouched original>,  # for legacy access
# }
# ============================================================

def _normalize_tracker_data(theatre, raw_data):
    """
    v2.0 compatibility shim.
    Takes raw cached tracker data (any version) and returns canonical shape.
    Trackers that have been upgraded to v2.0 self-emit 'top_signals' — we use it.
    Trackers that haven't been upgraded yet — we synthesize 'top_signals' here.
    """
    if not raw_data:
        return None

    flag = THEATRE_FLAGS.get(theatre, '')

    # ---- THREAT LEVEL ----
    threat = _legacy_get_theatre_level(raw_data, theatre)

    # ---- INFLUENCE LEVEL (Oman & future stability anchors) ----
    influence = raw_data.get('influence_level')
    if influence is None and theatre == 'oman':
        # Fallback: compute from interpreter output if present
        interp = raw_data.get('interpretation', {}) or {}
        so_what = interp.get('so_what', {}) if interp else {}
        influence = so_what.get('influence_level', 0)

    # ---- GREEN LEVEL (Russia & future de-escalation trackers) ----
    green = None
    interp = raw_data.get('interpretation', {}) or {}
    green_lines = interp.get('green_lines') if interp else None
    if green_lines and isinstance(green_lines, dict):
        green = green_lines.get('count', 0)
        if green > 5:
            green = 5  # cap

    # ---- DOMINANT AXIS ----
    threat_int    = int(threat or 0)
    influence_int = int(influence or 0)
    green_int     = int(green or 0)
    dominant_level = max(threat_int, influence_int)
    if influence_int > threat_int:
        dominant_axis = 'influence'
    elif green_int >= 3 and threat_int <= 2:
        dominant_axis = 'green'
        dominant_level = max(dominant_level, green_int)
    else:
        dominant_axis = 'threat'

    # ---- SCORE ----
    score = _legacy_get_theatre_score(raw_data, theatre)

    # ---- TOP SIGNALS (v2.0 native if present, else synthesize) ----
    if 'top_signals' in raw_data and isinstance(raw_data['top_signals'], list):
        # v2.0 tracker — already self-emits
        top_signals = raw_data['top_signals']
    else:
        # Legacy tracker — synthesize from raw fields
        top_signals = _synthesize_top_signals_legacy(theatre, raw_data, threat_int, influence_int, score)

    return {
        'theatre':       theatre,
        'flag':          flag,
        'levels': {
            'threat':         threat_int,
            'influence':      influence_int if influence is not None else None,
            'green':          green_int     if green     is not None else None,
            'dominant_axis':  dominant_axis,
            'dominant_level': dominant_level,
        },
        'score':         score,
        'so_what':       (interp.get('so_what', {}) if interp else {}) or raw_data.get('so_what', {}),
        'red_lines':     (interp.get('red_lines', {}) if interp else {}) or raw_data.get('red_lines', {}),
        'green_lines':   green_lines,
        'diplomatic_track':   (interp.get('diplomatic_track') if interp else None) or raw_data.get('diplomatic_track'),
        'historical_matches': (interp.get('historical_matches') if interp else None) or raw_data.get('historical_matches'),
        'top_signals':   top_signals,
        'silence_anomalies':         raw_data.get('silence_anomalies', []),
        'crosstheater_coordination': raw_data.get('crosstheater_coordination', []),
        'scanned_at':    raw_data.get('scanned_at') or raw_data.get('timestamp', ''),
        'raw':           raw_data,
    }


def _synthesize_top_signals_legacy(theatre, raw_data, threat_int, influence_int, score):
    """
    For trackers not yet upgraded to v2.0 self-emit pattern.
    Synthesize top_signals[] from raw fields using the same logic as
    the original _extract_key_signals() — but per-tracker, ranked by priority.
    Returns list of signal dicts; BLUF will consume them globally.
    """
    flag    = THEATRE_FLAGS.get(theatre, '')
    interp  = raw_data.get('interpretation', {}) or {}
    so_what = interp.get('so_what', {}) if interp else {}
    rl_obj  = interp.get('red_lines', {}) if interp else {}
    signals = []

    # Red lines breached (highest priority)
    for rl in rl_obj.get('triggered', []):
        if rl.get('status') == 'BREACHED':
            signals.append({
                'priority':  10 + threat_int,
                'category':  'red_line_breached',
                'theatre':   theatre,
                'level':     threat_int,
                'icon':      rl.get('icon', '🚨'),
                'color':     '#dc2626',
                'short_text': f'{flag} {theatre.upper()}: {rl.get("label", "Red line breached")[:60]}',
                'long_text':  f'{flag} {theatre.upper()} L{threat_int}: {rl.get("label", "")} — {rl.get("trigger", "")[:120]}',
            })

    # Theatre at high level
    if threat_int >= 4:
        signals.append({
            'priority':  9 + threat_int,
            'category':  'theatre_high',
            'theatre':   theatre,
            'level':     threat_int,
            'icon':      '🔴',
            'color':     ESCALATION_COLORS.get(threat_int, '#6b7280'),
            'short_text': f'{flag} {theatre.upper()} L{threat_int} — {ESCALATION_LABELS.get(threat_int, "")}',
            'long_text':  f'{flag} {theatre.upper()} at L{threat_int} {ESCALATION_LABELS.get(threat_int, "")} (score {score}/100)',
        })

    # Influence-side high (Oman pattern)
    if influence_int >= 3:
        signals.append({
            'priority':  7 + influence_int,
            'category':  'mediation_active' if theatre == 'oman' else 'influence_high',
            'theatre':   theatre,
            'level':     influence_int,
            'icon':      '🕊️',
            'color':     INFLUENCE_COLORS.get(influence_int, '#7c3aed'),
            'short_text': f'{flag} {theatre.upper()}: {INFLUENCE_LABELS.get(influence_int, "Active influence")}',
            'long_text':  f'{flag} {theatre.upper()} influence L{influence_int} — {INFLUENCE_LABELS.get(influence_int, "Active")}; mediation channel engaged.',
        })

    # Silence anomalies
    for anom in raw_data.get('silence_anomalies', []):
        if anom.get('deviation') and '100%' in str(anom.get('deviation', '')):
            actor_name = anom.get('actor_name', anom.get('actor_id', 'Unknown'))
            signals.append({
                'priority':  6 + threat_int,
                'category':  'silence_anomaly',
                'theatre':   theatre,
                'level':     threat_int,
                'icon':      '🔇',
                'color':     '#f59e0b',
                'short_text': f'{flag} {theatre.upper()}: {actor_name} silent',
                'long_text':  f'{flag} {theatre.upper()}: {actor_name} SILENT — {anom.get("signal", "Unusual quiet pattern")}',
            })

    # Cross-theater coordination
    for ct in raw_data.get('crosstheater_coordination', []):
        if ct.get('confidence', 0) >= 60 and ct.get('type') == 'simultaneous_elevation':
            theaters_in = ct.get('theaters', [])
            signals.append({
                'priority':  8,
                'category':  'crosstheater',
                'theatre':   'regional',
                'level':     threat_int,
                'icon':      '🔗',
                'color':     '#7c3aed',
                'short_text': f'CROSS-THEATER: {", ".join(t.upper() for t in theaters_in[:3])}',
                'long_text':  f'CROSS-THEATER: Simultaneous elevation across {", ".join(t.upper() for t in theaters_in)} ({ct.get("confidence", 0)}% confidence) — {ct.get("signal", "")}',
            })

    # Green lines / diplomatic de-escalation (Russia pattern, future trackers)
    green_lines = interp.get('green_lines') if interp else None
    if green_lines and green_lines.get('count', 0) >= 2 and threat_int <= 2:
        signals.append({
            'priority':  5 + threat_int,
            'category':  'green_line_active',
            'theatre':   theatre,
            'level':     threat_int,
            'icon':      '✅',
            'color':     '#10b981',
            'short_text': f'{flag} {theatre.upper()}: De-escalation signals',
            'long_text':  f'{flag} {theatre.upper()}: {green_lines.get("count", 0)} green-line de-escalation triggers active.',
        })

    # Interpreter-specific flags (legacy support)
    if so_what.get('sadr_silent') and theatre == 'iraq':
        signals.append({
            'priority': 7, 'category': 'sadr_silent', 'theatre': 'iraq',
            'level': threat_int, 'icon': '👁️', 'color': '#7c3aed',
            'short_text': '🇮🇶 IRAQ: Al-Sadr silent',
            'long_text':  'IRAQ: Al-Sadr SILENT — historical pattern precedes mobilization (2020, 2022)',
        })
    if so_what.get('dual_chokepoint') and theatre == 'yemen':
        signals.append({
            'priority': 10, 'category': 'dual_chokepoint', 'theatre': 'yemen',
            'level': threat_int, 'icon': '🔱', 'color': '#7c3aed',
            'short_text': '🔱 DUAL CHOKEPOINT: Hormuz + Bab el-Mandeb',
            'long_text':  'DUAL CHOKEPOINT: Hormuz + Bab el-Mandeb simultaneous signals — coordinated blockade risk',
        })
    if so_what.get('laf_enforcement_gap') and theatre == 'lebanon':
        signals.append({
            'priority': 6, 'category': 'laf_gap', 'theatre': 'lebanon',
            'level': threat_int, 'icon': '🏳️', 'color': '#f97316',
            'short_text': '🇱🇧 LEBANON: LAF enforcement gap',
            'long_text':  'LEBANON: LAF enforcement gap persists — Israeli withdrawal conditions not met',
        })
    if so_what.get('iran_expelled') and theatre == 'syria':
        signals.append({
            'priority': 5, 'category': 'iran_expelled', 'theatre': 'syria',
            'level': threat_int, 'icon': '✅', 'color': '#10b981',
            'short_text': '🇸🇾 SYRIA: Iran corridor severed',
            'long_text':  'SYRIA: Iran expelled — Hezbollah resupply corridor severed. Transition holding.',
        })

    return signals


# ============================================================
# DATA INGESTION -- read all SEVEN caches
# ============================================================

def _read_all_trackers():
    """Read all SEVEN ME tracker caches. Returns dict of NORMALIZED tracker data
    (post-shim), keyed by theatre. Each value is the canonical internal shape."""
    results = {}
    for theatre, (primary_key, fallback_key) in TRACKER_KEYS.items():
        raw = _redis_get(primary_key)
        if not raw and fallback_key:
            raw = _redis_get(fallback_key)
        if raw:
            normalized = _normalize_tracker_data(theatre, raw)
            if normalized:
                results[theatre] = normalized
                lvls = normalized['levels']
                axis_str = (f"T{lvls['threat']}" +
                            (f"/I{lvls['influence']}" if lvls['influence'] is not None else ''))
                print(f'[ME BLUF] {theatre}: loaded ({axis_str}, score={normalized["score"]})')
        else:
            print(f'[ME BLUF] {theatre}: no cache available')
    return results


def _legacy_get_theatre_level(data, theatre):
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


def _legacy_get_theatre_score(data, theatre):
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
    """
    v2.0 NEW PIPELINE.
    Each tracker — whether v2.0 self-emitting or v1.x shimmed —
    arrives with a 'top_signals' array attached. This function:
      1. Collects all top_signals from all trackers
      2. Globally sorts by priority (descending)
      3. Dedupes by (theatre, category) key
      4. Returns top N (TOP_SIGNALS_COUNT, default 5)
    """
    all_signals = []
    for theatre, data in trackers.items():
        for sig in data.get('top_signals', []):
            # Backfill defensive fields if a v2.0 tracker omitted any
            sig.setdefault('priority', 5)
            sig.setdefault('category', 'unknown')
            sig.setdefault('theatre', theatre)
            sig.setdefault('icon', '•')
            sig.setdefault('color', '#6b7280')
            sig.setdefault('short_text', '')
            sig.setdefault('long_text', sig.get('short_text', ''))
            all_signals.append(sig)

    # Global sort
    all_signals.sort(key=lambda x: x.get('priority', 0), reverse=True)

    # Dedupe by (theatre, category)
    seen = set()
    deduped = []
    for s in all_signals:
        key = f'{s.get("theatre", "")}:{s.get("category", "")}'
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    return deduped[:TOP_SIGNALS_COUNT]


def _write_bluf_prose(trackers, levels, scores, max_level,
                      theatres_at_l3plus, top_signals):
    """
    Write a single analyst-prose BLUF paragraph.
    Style: direct declarative sentences, no hedging, intelligence product voice.
    v2.0: Reads from normalized trackers (post-shim). Adds Oman/influence handling.
    """
    now_str = datetime.now(timezone.utc).strftime('%d %b %Y %H:%MZ')

    # v2.0: levels = {theatre: int} of THREAT level (not influence)
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

    # Cross-theater coordination sentence (v2.0: from normalized data)
    coordination_theatres = []
    for t, data in trackers.items():
        for ct in data.get('crosstheater_coordination', []) or []:
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

    # Iran/ceasefire context (v2.0: read so_what from normalized shape)
    iran_data = trackers.get('iran', {}) or {}
    iran_so   = iran_data.get('so_what', {}) or {}
    iraq_data = trackers.get('iraq', {}) or {}
    iraq_so   = iraq_data.get('so_what', {}) or {}
    ceasefire = iraq_so.get('ceasefire_active', False)

    raw_iran  = iran_data.get('raw', {}) or {}
    otp_count = raw_iran.get('otp_signal_count', raw_iran.get('otp_count', 0))
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
    leb_data  = trackers.get('lebanon', {}) or {}
    leb_level = levels.get('lebanon', 0)
    leb_so    = leb_data.get('so_what', {}) or {}
    if leb_level >= 4:
        iran_directing = leb_so.get('iran_directing', False)
        laf_gap        = leb_so.get('laf_enforcement_gap', False)
        parts.append(
            f'Hezbollah operating at L{leb_level}'
            f'{" under Iranian direction" if iran_directing else ""}'
            f'{"; LAF enforcement gap persists" if laf_gap else ""}.'
        )

    # Houthi silence if detected
    yemen_data    = trackers.get('yemen', {}) or {}
    raw_yemen     = yemen_data.get('raw', {}) or {}
    houthi_actor  = (raw_yemen.get('actors', {}) or {}).get('houthis', {}) or {}
    houthi_silent = houthi_actor.get('statement_count', 1) == 0
    if houthi_silent:
        parts.append(
            'Houthi/Ansar Allah anomalously silent -- '
            'operational security or patron (Iran) direction to stand down.'
        )

    # Syria positive note if transition holding
    syria_data = trackers.get('syria', {}) or {}
    syria_so   = syria_data.get('so_what', {}) or {}
    if syria_so.get('iran_expelled') and levels.get('syria', 0) <= 1:
        parts.append(
            'Syria transition holding; Iran expelled and corridor severed.'
        )

    # v2.0 NEW: Oman / influence sentence — stability anchor pattern
    oman_data = trackers.get('oman', {}) or {}
    if oman_data:
        oman_lvls       = oman_data.get('levels', {}) or {}
        oman_threat     = oman_lvls.get('threat', 0) or 0
        oman_influence  = oman_lvls.get('influence', 0) or 0
        oman_so         = oman_data.get('so_what', {}) or {}
        oman_scenario   = oman_so.get('scenario', '')

        if oman_influence >= 4:
            parts.append(
                f'Oman in active mediation posture (influence L{oman_influence}); '
                f'Muscat back-channel engaged — de-escalation lever available.'
            )
        elif oman_influence >= 3:
            parts.append(
                f'Oman influence vector elevated (L{oman_influence}); '
                f'mediation channels engaged.'
            )
        elif oman_threat >= 3:
            # Threat to Oman itself (Salalah/Duqm/succession) — escalatory, not stabilizing
            parts.append(
                f'Oman threat vector at L{oman_threat} ({oman_scenario or "external pressure"}); '
                f'stability anchor function compromised.'
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
    Build the ME regional BLUF. Reads all SEVEN caches, synthesizes,
    caches result in Redis. Returns dict.
    v2.0: Uses normalized tracker shape, emits dual-axis-aware output, top-5 signals.
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

    print('[ME BLUF v2.0] Building regional BLUF from all SEVEN tracker caches...')
    trackers = _read_all_trackers()  # Already normalized post-shim

    if not trackers:
        return {
            'success': False,
            'error':   'No tracker data available',
            'bluf':    'BLUF unavailable -- no tracker caches loaded.',
            'signals': [],
        }

    # Pull threat levels and scores from normalized shape
    # (Influence levels live in theatre_summary; not used as primary level)
    levels = {t: d['levels']['threat'] for t, d in trackers.items()}
    scores = {t: d['score']            for t, d in trackers.items()}

    max_level          = max(levels.values()) if levels else 0
    avg_score          = round(sum(scores.values()) / len(scores), 1) if scores else 0
    theatres_at_l3plus = sum(1 for l in levels.values() if l >= 3)
    theatres_live      = len(trackers)

    posture_label, posture_color = _build_posture_label(max_level, theatres_at_l3plus)

    # Extract top 5 signals (was 3)
    top_signals = _extract_key_signals(trackers)

    # Write BLUF prose (now uses normalized shape)
    bluf_prose = _write_bluf_prose(
        trackers, levels, scores,
        max_level, theatres_at_l3plus, top_signals
    )

    # v2.0: Per-theatre summary (now includes BOTH axis levels for dual-axis trackers)
    theatre_summary = {}
    for t, data in trackers.items():
        lvls         = data.get('levels', {}) or {}
        threat_lvl   = lvls.get('threat', 0)
        infl_lvl     = lvls.get('influence')
        green_lvl    = lvls.get('green')
        dom_axis     = lvls.get('dominant_axis', 'threat')
        dom_level    = lvls.get('dominant_level', threat_lvl)
        theatre_summary[t] = {
            'level':            threat_lvl,                                  # back-compat: legacy single-axis
            'label':            ESCALATION_LABELS.get(threat_lvl, 'Unknown'),
            'color':            ESCALATION_COLORS.get(threat_lvl, '#6b7280'),
            'score':            scores[t],
            'flag':             data.get('flag', THEATRE_FLAGS.get(t, '')),
            'timestamp':        data.get('scanned_at', ''),
            # v2.0 NEW dual-axis fields:
            'threat_level':     threat_lvl,
            'influence_level':  infl_lvl,
            'green_level':      green_lvl,
            'dominant_axis':    dom_axis,
            'dominant_level':   dom_level,
            'is_dual_axis':     infl_lvl is not None,
            'influence_label':  INFLUENCE_LABELS.get(infl_lvl, '') if infl_lvl is not None else None,
            'influence_color':  INFLUENCE_COLORS.get(infl_lvl, '#6b7280') if infl_lvl is not None else None,
        }

    result = {
        'success':           True,
        'from_cache':        False,
        'bluf':              bluf_prose,
        'signals':           top_signals,
        'top_signals':       top_signals,  # alias for GPI consumption
        'posture_label':     posture_label,
        'posture_color':     posture_color,
        'max_level':         max_level,
        'avg_score':         avg_score,
        'theatres_at_l3plus':theatres_at_l3plus,
        'theatres_live':     theatres_live,
        'theatre_summary':   theatre_summary,
        'generated_at':      datetime.now(timezone.utc).isoformat(),
        'version':           '2.0.0',
        'region':            'middle_east',  # v2.0: GPI-readable
        'top_signals_count': len(top_signals),
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
