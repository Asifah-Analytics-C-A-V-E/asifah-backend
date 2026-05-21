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

# ════════════════════════════════════════════════════════════════════
# DEPLOY MARKER v2.1.0 — fires ONCE when this module is imported.
# If you see this in Render logs, the new code is loaded into the worker.
# If you DON'T see this, Render is running an older cached version.
# ════════════════════════════════════════════════════════════════════
print('[ME BLUF DEPLOY MARKER v2.1.0] Module loaded — Lebanon humanitarian + convergence registry active')

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

# ============================================================
# LEBANON HUMANITARIAN BACKEND (cross-backend HTTP fetch)
# ============================================================
# lebanon_humanitarian module lives on a SEPARATE Render backend
# (lebanon-stability-backend.onrender.com). ME BLUF fetches via HTTP
# and caches in its own Redis to avoid hammering the Lebanon backend.
#
# Pattern mirrors commodity_proxy_europe.py:
#   1. Try Redis cache (12hr TTL) — return if fresh
#   2. On miss → HTTP fetch from Lebanon backend
#   3. Write-through cache → return fresh data
#   4. On Lebanon backend failure → return None (humanitarian signal omitted, BLUF still works)
LEBANON_HUMANITARIAN_BACKEND = os.environ.get(
    'LEBANON_HUMANITARIAN_BACKEND_URL',
    'https://lebanon-stability-backend.onrender.com'
)
LEBANON_HUMANITARIAN_CACHE_KEY = 'me_bluf:lebanon_humanitarian'
LEBANON_HUMANITARIAN_CACHE_TTL = 12 * 3600    # 12 hours — humanitarian data is structural, not minute-by-minute

BLUF_CACHE_KEY = 'rhetoric:me:regional_bluf'
BLUF_CACHE_TTL = 14 * 3600  # 14h -- outlasts any individual tracker TTL
TOP_SIGNALS_COUNT = 12  # v2.4.0 May 21 2026: was 5 (was 3 in v2.0); supports per-theatre quota
MAX_PER_THEATRE   = 3   # v2.4.0 May 21 2026 — per-tracker quota during selection


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
        # v2.0 tracker — already self-emits kinetic/threat/anomaly signals
        top_signals = list(raw_data['top_signals'])
    else:
        # Legacy tracker — synthesize from raw fields
        top_signals = _synthesize_top_signals_legacy(theatre, raw_data, threat_int, influence_int, score)

    # ALWAYS augment with BLUF-level diplomatic signals (v3.2.0).
    # Diplomatic propagation is a BLUF-level concern, not per-tracker. v2.0 trackers
    # don't self-emit diplomatic signals (they emit kinetic/threat/anomaly), so without
    # this we'd lose them entirely. We deduplicate by category to avoid double-add for
    # the legacy path (where _synthesize_top_signals_legacy ALSO calls the helper).
    diplomatic_sigs = _extract_diplomatic_signals(theatre, raw_data, threat_int)
    existing_categories = {s.get('category') for s in top_signals}
    for ds in diplomatic_sigs:
        if ds.get('category') not in existing_categories:
            top_signals.append(ds)

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


def _extract_diplomatic_signals(theatre, raw_data, threat_int):
    """
    BLUF-level diplomatic signal extractor (v3.2.0 — extracted for cross-path reuse).

    Reads diplomatic_track + green_lines from a tracker's interpretation block and
    emits diplomatic-axis signals. Runs for EVERY tracker regardless of whether the
    tracker is v2.0-self-emit or legacy-synthesized — diplomatic propagation is a
    BLUF-level architectural responsibility, not a per-tracker concern.

    Why this matters: v2.0 trackers like Lebanon emit their own top_signals[] but
    don't include diplomatic signals (they emit kinetic/threat/anomaly). Without
    this helper, diplomatic data exists in interpretation.diplomatic_track but never
    surfaces to BLUF top_signals → GPI diplomatic axis stays at L0.

    Returns list of signal dicts (possibly empty).
    """
    flag    = THEATRE_FLAGS.get(theatre, '')
    interp  = raw_data.get('interpretation', {}) or {}
    signals = []

    # Green lines / diplomatic de-escalation (UNGATED + dual-schema).
    # Previously gated on threat_int <= 2, which meant diplomatic signals were
    # SUPPRESSED during exactly the periods (high-threat) when off-ramps matter
    # most analytically. Now fires whenever ≥1 green-line trigger is active.
    # Schema compat: handles both legacy {'count': N} (Russia, etc.) AND newer
    # {'active_count': N, 'signaled_count': M, 'triggered': [...]} (Lebanon Apr 2026+).
    green_lines = interp.get('green_lines') if interp else None
    if green_lines and isinstance(green_lines, dict):
        # Read count from whichever schema is present
        if 'count' in green_lines:
            gl_count = green_lines.get('count', 0)
        else:
            gl_count = green_lines.get('active_count', 0) + green_lines.get('signaled_count', 0)
        if gl_count >= 1:
            # Priority scales with threat — high threat + diplomatic signal is more
            # analytically valuable than low-threat + diplomatic
            gl_priority = 6 + min(threat_int, 4)   # 6→10 sliding scale
            signals.append({
                'priority':       gl_priority,
                'category':       'green_line_active',
                'theatre':        theatre,
                'level':          min(threat_int, 4),  # cap at 4 — green lines never "active conflict"
                'icon':           '✅',
                'color':          '#10b981',
                'pressure_type':  'diplomatic',
                'short_text':     f'{flag} {theatre.upper()}: De-escalation signals ({gl_count})',
                'long_text':      f'{flag} {theatre.upper()}: {gl_count} green-line de-escalation '
                                  f'trigger{"s" if gl_count != 1 else ""} active.',
            })

    # Diplomatic track — Witkoff mediation, Salalah talks, LAF enforcement, etc.
    # Tracker layer emits the rich data; BLUF surfaces it to top_signals → GPI.
    diplomatic_track = interp.get('diplomatic_track') if interp else None
    if diplomatic_track and isinstance(diplomatic_track, dict):
        active_count   = diplomatic_track.get('active_count', 0)
        signaled_count = diplomatic_track.get('signaled_count', 0)
        scenario       = diplomatic_track.get('scenario', '')
        score          = diplomatic_track.get('score', 0)
        # Fire when there's any diplomatic activity (active OR signaled)
        if active_count + signaled_count > 0:
            # Priority scales with threat — diplomatic signals during high threat
            # carry more analytical weight (off-ramp during crisis > off-ramp during calm)
            dt_priority = 7 + min(threat_int, 4)   # 7→11 sliding scale
            short_status = 'ACTIVE' if active_count > 0 else 'SIGNALED'
            signals.append({
                'priority':       dt_priority,
                'category':       'diplomatic_track_active',
                'theatre':        theatre,
                'level':          min(threat_int, 4),
                'icon':           '🕊️',
                'color':          '#0ea5e9',          # sky blue — matches GPI diplomatic axis
                'pressure_type':  'diplomatic',
                'short_text':     f'{flag} {theatre.upper()}: Diplomatic track {short_status} ({scenario[:40]})',
                'long_text':      f'{flag} {theatre.upper()} diplomatic track: {active_count} active + '
                                  f'{signaled_count} signaled off-ramp triggers (score {score}/100). '
                                  f'Scenario: {scenario}.',
                # Pass through structured data for GPI / frontend rendering
                'diplomatic_active_count':   active_count,
                'diplomatic_signaled_count': signaled_count,
                'diplomatic_score':          score,
                'diplomatic_scenario':       scenario,
            })

    return signals


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
    # L5 GATE (v1.1.0 — May 21 2026): Per platform L5 Reservation Contract,
    # L5 "Active Conflict" requires an explicit kinetic/humanitarian/economic/
    # diplomatic trigger. If tracker emits l5_gate dict, we honor its decision.
    # If tracker doesn't emit l5_gate (legacy trackers), we trust their level
    # as-is until they're upgraded per the weekend audit.
    # NOTE: v2.0+ self-emit trackers (Lebanon, Israel) bypass this synth
    # entirely via the shortcut earlier in this file. Their L5 signals are
    # not affected by this gate.
    # LABEL PRESERVATION: prefer tracker's own theatre_label + signal_text_short
    # if emitted. Falls back to ESCALATION_LABELS dict for legacy trackers.
    effective_level = threat_int
    l5_gate = raw_data.get('l5_gate')
    if threat_int >= 5 and isinstance(l5_gate, dict):
        # If tracker emits l5_gate, cap at L4 unless at least one axis gate is True
        if not any(l5_gate.get(axis) for axis in ('kinetic', 'humanitarian', 'economic', 'diplomatic')):
            effective_level = 4
            print(f"[ME BLUF] L5 gate enforced: {theatre} capped at L4 "
                  f"(no l5_gate axes fired; tracker score {score})")

    if effective_level >= 4:
        # Prefer tracker's own label; fall back to canonical dict
        tracker_label = raw_data.get('theatre_label') or ESCALATION_LABELS.get(effective_level, '')
        signals.append({
            'priority':  9 + effective_level,
            'category':  'theatre_high',
            'theatre':   theatre,
            'level':     effective_level,
            'icon':      '🔴',
            'color':     ESCALATION_COLORS.get(effective_level, '#6b7280'),
            'short_text': raw_data.get('signal_text_short') or
                          f'{flag} {theatre.upper()} L{effective_level} — {tracker_label}',
            'long_text':  raw_data.get('signal_text_long') or
                          f'{flag} {theatre.upper()} at L{effective_level} {tracker_label} (score {score}/100)',
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

    # Diplomatic signals (green_lines + diplomatic_track) extracted via shared helper.
    # The helper runs at the _normalize_tracker level too (for v2.0 trackers), but
    # legacy synthesis also needs them — they're part of the canonical signal set.
    signals.extend(_extract_diplomatic_signals(theatre, raw_data, threat_int))

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
    v2.0 NEW PIPELINE — v2.3.0 update: returns FULL deduped pool (not capped).
    Each tracker — whether v2.0 self-emitting or v1.x shimmed —
    arrives with a 'top_signals' array attached. This function:
      1. Collects all top_signals from all trackers
      2. Globally sorts by priority (descending)
      3. Dedupes by (theatre, category) key
      4. Returns full deduped pool — caller is responsible for capping for display.
         (Axis aggregation in GPI needs the full pool to honor axis-quota.)
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

    # Dedupe by (theatre, category) AND enforce per-theatre quota (v2.4.0 May 21 2026)
    # Per-tracker quota: max MAX_PER_THEATRE signals per country tracker.
    # Cross-tracker signals (theatre='regional', e.g. cross-theater convergence)
    # bypass the quota — they're platform-level signals, not per-country emissions.
    # Lebanon's multiple legitimate L5 signals (kinetic, humanitarian, BREACH,
    # diplomatic) will each count against Lebanon's quota of 3; the strongest 3
    # by priority will surface.
    seen           = set()
    theatre_counts = {}
    deduped        = []
    for s in all_signals:
        theatre = s.get('theatre', '')
        key     = f'{theatre}:{s.get("category", "")}'
        if key in seen:
            continue
        if theatre != 'regional' and theatre_counts.get(theatre, 0) >= MAX_PER_THEATRE:
            continue
        seen.add(key)
        theatre_counts[theatre] = theatre_counts.get(theatre, 0) + 1
        deduped.append(s)


# ============================================================
# LEBANON HUMANITARIAN — CROSS-BACKEND FETCH + CACHE
# ============================================================
def _fetch_lebanon_humanitarian():
    """
    Fetch Lebanon humanitarian data from lebanon-stability-backend with
    Redis caching. Pattern mirrors commodity_proxy_europe.py.

    Returns:
        dict — humanitarian data payload (matches /api/lebanon/humanitarian schema)
        None — if backend unreachable AND no cache available (BLUF continues without humanitarian)
    """
    # 1. Try cache first
    cached = _redis_get(LEBANON_HUMANITARIAN_CACHE_KEY)
    if cached:
        try:
            data = json.loads(cached) if isinstance(cached, str) else cached
            cached_at_str = data.get('_cached_at')
            if cached_at_str:
                cached_at = datetime.fromisoformat(cached_at_str)
                age = (datetime.now(timezone.utc) - cached_at).total_seconds()
                if age < LEBANON_HUMANITARIAN_CACHE_TTL:
                    print(f'[ME BLUF] Lebanon humanitarian: cache hit (age {age/3600:.1f}h)')
                    return data
        except Exception as e:
            print(f'[ME BLUF] Lebanon humanitarian cache parse error: {e}')

    # 2. Cache miss or stale — fetch from Lebanon backend
    try:
        url = f'{LEBANON_HUMANITARIAN_BACKEND}/api/lebanon/humanitarian'
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f'[ME BLUF] Lebanon backend HTTP {resp.status_code}; using stale cache if any')
            return cached  # may be stale but better than nothing
        data = resp.json()
        # Stamp cached_at and write through
        data['_cached_at'] = datetime.now(timezone.utc).isoformat()
        try:
            _redis_set(LEBANON_HUMANITARIAN_CACHE_KEY, json.dumps(data, default=str),
                       ttl=LEBANON_HUMANITARIAN_CACHE_TTL)
            print(f'[ME BLUF] Lebanon humanitarian: fresh fetch + cached ({LEBANON_HUMANITARIAN_CACHE_TTL/3600:.0f}h TTL)')
        except Exception as e:
            print(f'[ME BLUF] Lebanon humanitarian cache write failed: {e}')
        return data
    except Exception as e:
        print(f'[ME BLUF] Lebanon humanitarian fetch failed: {e}; returning stale cache if any')
        return cached  # graceful degradation


def _fetch_commodity_pressure(commodity_id):
    """
    Generic helper: fetch the global commodity pressure state for any commodity.
    Used by Layer 2 convergence enrichment — replaces bespoke per-commodity fetchers.

    Reads commodity_tracker output via in-process helper. Imported lazily so
    ME BLUF still works if commodity_tracker is unavailable.

    Args:
        commodity_id: e.g. 'wheat', 'oil', 'cobalt' — must match commodity_tracker.COMMODITY_TYPES key

    Returns:
        dict — {'alert_level': str, 'pressure_score': float, 'signal_count': int,
                'top_signal': str}
               where alert_level is one of: 'normal', 'elevated', 'high', 'surge'
        None — if commodity_tracker unavailable or no data yet
    """
    try:
        # commodity_tracker lives in the same backend process — direct import OK
        from commodity_tracker import load_commodity_cache
        cache = load_commodity_cache()
        if not cache:
            return None

        # commodity_summaries is a DICT keyed by commodity_id (e.g. 'wheat', 'oil', 'cobalt')
        # Each value is a summary dict with alert_level, signal_count, top_signals, etc.
        commodity_summaries = cache.get('commodity_summaries', {}) or {}
        cs = commodity_summaries.get(commodity_id)
        if not cs or not isinstance(cs, dict):
            return None

        return {
            'alert_level':     cs.get('alert_level', 'normal'),
            'pressure_score':  cs.get('total_score', 0),    # commodity_tracker uses 'total_score', not 'pressure_score'
            'signal_count':    cs.get('signal_count', 0),
            'top_signal':      (cs.get('top_signals') or [{}])[0].get('title', '') if cs.get('top_signals') else '',
        }
    except ImportError:
        return None
    except Exception as e:
        print(f'[ME BLUF] Commodity pressure fetch failed for {commodity_id}: {e}')
        return None


def _apply_convergence_enrichments(country, signal_dict, long_text_parts):
    """
    Generic Layer 2 enrichment: looks up CONVERGENCE_REGISTRY for any convergences
    registered for this country. For each match, checks if the relevant commodity
    is at or above its configured threshold. If yes, appends enrichment text to
    long_text_parts AND sets the convergence flag on signal_dict.

    Args:
        country:       country name (must match registry entries)
        signal_dict:   the signal dict being built — convergence flags get added IN PLACE
        long_text_parts: list of strings being assembled into long_text — appended IN PLACE

    Returns:
        list of activated convergence ids (empty if none matched)
    """
    activated = []
    try:
        from convergence_registry import (
            find_convergences_for_country,
            alert_meets_threshold,
            format_enrichment_text,
        )
    except ImportError:
        # Registry module not available — silent no-op (defensive)
        return activated

    convergences = find_convergences_for_country(country)
    if not convergences:
        return activated

    for entry in convergences:
        commodity_id = entry['commodity']
        threshold    = entry['commodity_threshold']

        commodity_state = _fetch_commodity_pressure(commodity_id)
        if not commodity_state:
            continue

        actual_alert = commodity_state.get('alert_level', 'normal')
        if not alert_meets_threshold(actual_alert, threshold):
            continue

        # Convergence is active — enrich the signal
        signals_count = commodity_state.get('signal_count', 0)
        enrichment_text = format_enrichment_text(entry, actual_alert, signals_count)
        long_text_parts.append(enrichment_text)

        # Set per-convergence flag on the signal so Layer 1 (GPI) can detect it.
        # Convention: signal['{convergence_id}_active'] = True
        # AND signal['convergence_states'][{id}] = full state dict
        signal_dict[f'{entry["id"]}_active'] = True
        signal_dict.setdefault('convergence_states', {})[entry['id']] = {
            'alert_level':     actual_alert,
            'signal_count':    signals_count,
            'commodity':       commodity_id,
            'commodity_state': commodity_state,
        }
        activated.append(entry['id'])
        print(f'[ME BLUF] Convergence activated: {entry["id"]} ({commodity_id} at {actual_alert.upper()})')

    return activated



def _build_lebanon_humanitarian_signal():
    """
    Build a high-priority humanitarian signal for Lebanon, sourced via HTTP
    from lebanon-stability-backend.

    Returns a dict matching the top_signals canonical schema, or None if:
      - backend unreachable AND no cache
      - data fetch fails
      - casualty/displacement counts below salience threshold

    Pressure type: humanitarian (purple #a855f7) — gets dedicated treatment in GPI.
    Priority:      9 (very high — humanitarian crises >L4 should lead the BLUF)
    Category:      'humanitarian_lebanon' (uniqueness key for dedupe)
    """
    print('[ME BLUF MARKER] _build_lebanon_humanitarian_signal() called')
    data = _fetch_lebanon_humanitarian()
    if not data:
        print('[ME BLUF MARKER] _fetch_lebanon_humanitarian returned None — aborting signal build')
        return None

    # Lebanon humanitarian endpoint returns FLAT structure (not nested under 'static').
    # Casualties / displacement / etc. are top-level keys.
    # DTM live data lives under 'dtm_raw' (not 'dtm_displacement').
    casualties   = data.get('casualties', {}) or {}
    displacement = data.get('displacement', {}) or {}
    healthcare   = data.get('healthcare', {}) or {}
    appeal       = data.get('flash_appeal', {}) or {}
    food         = data.get('food_security', {}) or {}
    last_update  = data.get('last_manual_update', 'unknown')

    # Live DTM displacement count — nested inside dtm_raw.country_level if present
    dtm_raw      = data.get('dtm_raw', {}) or {}
    dtm_country  = (dtm_raw.get('country_level') or {}) if dtm_raw else {}
    live_idps    = dtm_country.get('total_idps') if dtm_country else None

    killed   = casualties.get('killed') or 0
    injured  = casualties.get('injured') or 0
    hw_killed   = healthcare.get('health_workers_killed_since_mar2') or 0
    hc_attacks  = healthcare.get('healthcare_attacks_since_mar2') or 0

    # Live DTM total preferred over static when available
    live_total = (live_idps
                  or displacement.get('total_displaced_registered')
                  or 0)

    print(f'[ME BLUF MARKER] Humanitarian metrics: killed={killed}, injured={injured}, live_total={live_total}, hc_attacks={hc_attacks}')

    # Salience filter — don't surface humanitarian signal if all metrics below threshold
    if killed < 100 and live_total < 100000:
        print(f'[ME BLUF MARKER] Salience filter triggered — signal suppressed (killed={killed}, live_total={live_total})')
        return None
    print('[ME BLUF MARKER] Salience filter passed — building signal')

    # Format numbers for display
    killed_fmt   = f'{killed:,}'  if killed   else '?'
    injured_fmt  = f'{injured:,}' if injured  else '?'
    idp_fmt      = f'{live_total/1_000_000:.1f}M' if live_total >= 1_000_000 else f'{live_total:,}'
    appeal_pct   = appeal.get('funded_pct')

    # Compose human-readable signal text
    short_text = (
        f'LEBANON humanitarian crisis: {idp_fmt} displaced, '
        f'{killed_fmt} killed, {injured_fmt} injured'
    )
    if hc_attacks and hw_killed:
        short_text += f' ({hc_attacks} healthcare attacks, {hw_killed} health workers killed)'

    # Compose long_text with full context
    long_text_parts = [
        f'Lebanon humanitarian situation as of {last_update}: '
        f'{idp_fmt} people displaced ({displacement.get("total_displaced_pct_population", "?")}% of population), '
        f'{killed_fmt} killed and {injured_fmt} injured since 2 March 2026.',
    ]
    if hc_attacks:
        long_text_parts.append(
            f'WHO has documented {hc_attacks} attacks on healthcare; '
            f'{hw_killed} health workers killed, '
            f'{healthcare.get("hospitals_closed", "?")} hospitals closed.'
        )
    if food.get('people_in_ipc_phase3_or_above'):
        food_count = food['people_in_ipc_phase3_or_above']
        long_text_parts.append(
            f'{food_count/1_000_000:.2f}M people projected to face acute food insecurity '
            f'(IPC Phase 3+) through August 2026.'
        )
    if appeal_pct is not None and appeal_pct < 60:
        long_text_parts.append(
            f'Flash Appeal only {appeal_pct}% funded '
            f'(${appeal.get("received_usd", 0)/1_000_000:.0f}M of '
            f'${appeal.get("amount_usd", 0)/1_000_000:.0f}M target).'
        )

    # ── UNIFIL peacekeeper casualties — national-stake diplomatic signal ──
    # Each killed peacekeeper triggers high-level reaction from contributing nation.
    # Currently: 4 Indonesian + 2 French = 6 dead in 2026. France maintains Lebanon
    # commitment after UNIFIL drawdown end-2026 per Macron April 22 statement.
    unifil_killed = healthcare.get('unifil_peacekeepers_killed') or 0
    if unifil_killed > 0:
        unifil_id = healthcare.get('unifil_peacekeepers_killed_indonesian') or 0
        unifil_fr = healthcare.get('unifil_peacekeepers_killed_french') or 0
        if unifil_id and unifil_fr:
            breakdown = f' ({unifil_id} Indonesian, {unifil_fr} French)'
        elif unifil_id:
            breakdown = f' ({unifil_id} Indonesian)'
        elif unifil_fr:
            breakdown = f' ({unifil_fr} French)'
        else:
            breakdown = ''
        long_text_parts.append(
            f'{unifil_killed} UNIFIL peacekeepers killed{breakdown} '
            f'— national-stake diplomatic signal; April 18 Ghandouriyeh ambush '
            f'attributed to Hezbollah by France/UNIFIL/Israel.'
        )

    # Build the signal first so we can pass it into the registry-driven enrichment.
    # The enrichment helper mutates signal_dict and long_text_parts in place,
    # adding any active convergences (e.g. wheat-Lebanon if global wheat is in surge).
    signal = {
        'priority':       12,                  # v3.1.0: bumped from 9 → 12 so a 1M-displaced humanitarian
                                                #         crisis reliably leads BLUF over composite kinetic signals
                                                #         (kinetic_pressure=14, multi_axis=11, inbound=10, etc.)
        'category':       'humanitarian_lebanon',
        'theatre':        'lebanon',
        'level':          5 if killed >= 1000 or live_total >= 500000 else 4,
        'icon':           '🆘',
        'color':          '#a855f7',           # purple — humanitarian (matches GPI PRESSURE_HUMANITARIAN axis)
        'pressure_type':  'humanitarian',       # explicit so GPI doesn't have to infer
        'short_text':     short_text[:120],
    }

    # ── Layer 2 enrichment: registry-driven convergence detection ──
    # Looks up CONVERGENCE_REGISTRY for any convergences registered for this country,
    # checks each commodity's threshold, and appends enrichment text + sets flags.
    # Adding a new convergence for Lebanon (e.g. lebanon-fertilizer) needs zero code change here.
    _apply_convergence_enrichments('lebanon', signal, long_text_parts)

    # Finalize long_text after all enrichments have appended
    signal['long_text'] = ' '.join(long_text_parts)

    return signal


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

    # Lebanon humanitarian crisis sentence — derived from top_signals injection upstream.
    # Phrasing pulls directly from the humanitarian signal so prose + signal stay consistent.
    leb_humanitarian = next(
        (s for s in top_signals if s.get('category') == 'humanitarian_lebanon'),
        None
    )
    if leb_humanitarian:
        parts.append(leb_humanitarian['short_text'] + '.')

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

    # Inject Lebanon humanitarian signal (cross-backend fetch — see _build_lebanon_humanitarian_signal).
    # Function returns None if backend unreachable, data missing, or below salience threshold.
    humanitarian_sig = _build_lebanon_humanitarian_signal()
    if humanitarian_sig:
        # Insert at top — humanitarian crisis at this scale leads the analyst-prose BLUF.
        # If we already have N signals, this becomes N+1 — global sort handles it.
        top_signals = [humanitarian_sig] + top_signals
        # Re-sort by priority (humanitarian sig at priority 12 → leads naturally)
        top_signals.sort(key=lambda x: x.get('priority', 0), reverse=True)
        print(f'[ME BLUF] Lebanon humanitarian signal injected: {humanitarian_sig["short_text"][:60]}...')

    # v2.3.0: keep full signal pool separate from capped top_signals.
    # `all_signals` retains every BLUF-level signal for downstream axis aggregation
    # (GPI's diplomatic + humanitarian axis cards need the full pool, not top 5).
    # `top_signals_capped` is the trimmed display version used for prose synthesis.
    all_signals = list(top_signals)                          # full pool — preserved
    top_signals_capped = top_signals[:TOP_SIGNALS_COUNT]      # capped for prose

    # Write BLUF prose using capped top_signals (prose has limited word count)
    bluf_prose = _write_bluf_prose(
        trackers, levels, scores,
        max_level, theatres_at_l3plus, top_signals_capped
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
        'signals':           all_signals,             # v2.3.0: FULL signal pool — for GPI axis aggregation
        'top_signals':       top_signals_capped,      # v2.3.0: capped — for display + prose synthesis
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
        'top_signals_count': len(top_signals_capped),
    }

    _redis_set(BLUF_CACHE_KEY, result)
    print(f'[ME BLUF] Built: posture={posture_label}, max_level={max_level}, '
          f'avg_score={avg_score}, signals={len(top_signals_capped)}')
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

    @app.route('/debug/me-bluf-version', methods=['GET'])
    def me_bluf_version():
        """
        Diagnostic endpoint — returns version info from the live deployed code.
        If you can hit this URL and see the v2.1.0 marker, new code is running.
        If you get 404, the new code isn't deployed.
        """
        # Probe what functions exist in the current module
        existing_functions = []
        for fn_name in (
            '_fetch_lebanon_humanitarian',
            '_fetch_commodity_pressure',
            '_apply_convergence_enrichments',
            '_build_lebanon_humanitarian_signal',
        ):
            if fn_name in globals():
                existing_functions.append(fn_name)

        # Probe convergence registry availability
        try:
            from convergence_registry import CONVERGENCE_REGISTRY
            registry_available = True
            registry_count = len(CONVERGENCE_REGISTRY)
            registry_ids = [e['id'] for e in CONVERGENCE_REGISTRY]
        except ImportError:
            registry_available = False
            registry_count = 0
            registry_ids = []

        return jsonify({
            'deploy_marker':         'v2.1.0',
            'lebanon_humanitarian_backend': LEBANON_HUMANITARIAN_BACKEND,
            'cache_key':             LEBANON_HUMANITARIAN_CACHE_KEY,
            'cache_ttl_hours':       LEBANON_HUMANITARIAN_CACHE_TTL / 3600,
            'expected_new_functions': [
                '_fetch_lebanon_humanitarian',
                '_fetch_commodity_pressure',
                '_apply_convergence_enrichments',
                '_build_lebanon_humanitarian_signal',
            ],
            'actual_existing_functions': existing_functions,
            'all_functions_present':  len(existing_functions) == 4,
            'convergence_registry_available': registry_available,
            'convergence_registry_count':     registry_count,
            'convergence_registry_ids':       registry_ids,
        })

    print('[ME BLUF] Routes registered: /api/rhetoric/me/bluf, /debug/me-bluf-version')


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
