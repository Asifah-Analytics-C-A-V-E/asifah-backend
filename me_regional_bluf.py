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
BLUF_LASTGOOD_TTL   = 7 * 24 * 3600   # 7d ceiling for held last-known-good tracker snapshots (C)
BLUF_INCOMPLETE_TTL = 30 * 60         # 30min cache when the picture is incomplete (A: don't freeze gaps)

def _lastgood_key(theatre):
    """Durable last-known-good snapshot key for a tracker (C)."""
    return 'rhetoric:' + str(theatre) + ':lastgood'
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
    'qatar':        ('rhetoric:qatar:latest',        None),  # v1.0 Jul 2026: mediation class
    'saudi_arabia': ('rhetoric:saudi_arabia:latest', None),  # v1.0 Jul 2026: friction + detente shim
    'uae':          ('rhetoric:uae:latest',          None),  # v1.0 Jul 2026: aligned hub
}

THEATRE_FLAGS = {
    'israel':  '\U0001f1ee\U0001f1f1',
    'iran':    '\U0001f1ee\U0001f1f7',
    'lebanon': '\U0001f1f1\U0001f1e7',
    'yemen':   '\U0001f1fe\U0001f1ea',
    'syria':   '\U0001f1f8\U0001f1fe',
    'iraq':    '\U0001f1ee\U0001f1f6',
    'oman':    '\U0001f1f4\U0001f1f2',  # v2.0: Oman flag 🇴🇲
    'qatar':        '\U0001f1f6\U0001f1e6',
    'saudi_arabia': '\U0001f1f8\U0001f1e6',
    'uae':          '\U0001f1e6\U0001f1ea',
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
    """Read all SEVEN ME tracker caches. Returns (results, missing, stale).

    Cold-start resilience (Jun 13 2026 -- A/B/C):
      C: primary -> fallback -> durable last-known-good (rhetoric:<x>:lastgood,
         7d ceiling) so a cold tracker is HELD in the rollup, not dropped.
      B: report which trackers are live / stale-fallback / fully absent.
    """
    results = {}
    missing = []   # no live AND no last-known-good -> truly absent (honest)
    stale   = []   # served from last-known-good fallback
    for theatre, (primary_key, fallback_key) in TRACKER_KEYS.items():
        raw = _redis_get(primary_key)
        if not raw and fallback_key:
            raw = _redis_get(fallback_key)
        if raw:
            normalized = _normalize_tracker_data(theatre, raw)
            if normalized:
                normalized['freshness'] = 'live'
                results[theatre] = normalized
                _redis_set(_lastgood_key(theatre), raw, ttl=BLUF_LASTGOOD_TTL)
                lvls = normalized['levels']
                axis_str = (f"T{lvls['threat']}" +
                            (f"/I{lvls['influence']}" if lvls['influence'] is not None else ''))
                print(f'[ME BLUF] {theatre}: loaded ({axis_str}, score={normalized["score"]})')
                continue
        # primary+fallback missing/unparseable -> last-known-good (C)
        lg = _redis_get(_lastgood_key(theatre))
        if lg:
            normalized = _normalize_tracker_data(theatre, lg)
            if normalized:
                normalized['freshness'] = 'stale'
                results[theatre] = normalized
                stale.append(theatre)
                print(f'[ME BLUF] {theatre}: STALE fallback (last-known-good held)')
                continue
        missing.append(theatre)
        print(f'[ME BLUF] {theatre}: no cache available (absent from rollup)')
    return results, missing, stale


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
        # Composite-family trackers (Gulf trio, Jul 2026): map composite_level -> 0-5 int
        if 'theatre_escalation_level' not in data and 'composite_level' in data:
            _comp_map = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
            return _comp_map.get(str(data.get('composite_level', 'low')).lower(), 0)
        return data.get('theatre_escalation_level',
               data.get('theatre_level', 0))


def _legacy_get_theatre_score(data, theatre):
    # Composite-family trackers score 0-10; ME rollup expects ~0-100
    if 'theatre_score' not in data and 'rhetoric_score' not in data and 'composite_score' in data:
        try:
            return round(float(data.get('composite_score', 0)) * 10, 1)
        except Exception:
            return 0
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
      4. Enforces per-theatre quota
      5. Returns full deduped pool — caller is responsible for display capping.
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

    # Dedupe by (theatre, category) and enforce per-theatre quota.
    seen = set()
    theatre_counts = {}
    deduped = []

    for s in all_signals:
        theatre = s.get('theatre', '')
        key = f'{theatre}:{s.get("category", "")}'

        if key in seen:
            continue

        if theatre != 'regional' and theatre_counts.get(theatre, 0) >= MAX_PER_THEATRE:
            continue

        seen.add(key)
        theatre_counts[theatre] = theatre_counts.get(theatre, 0) + 1
        deduped.append(s)

    return deduped

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
        # Jul 23 2026: was 15s. This call has graceful stale-cache fallback
        # below, so a long timeout buys nothing -- it just holds the entire
        # regional read hostage to one country's humanitarian sub-fetch, past
        # the point where GPI gives up waiting.
        resp = requests.get(url, timeout=5)
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


def _convergence_is_fresh(conv_id, actual_alert, signals_count):
    """Is a commodity convergence RISING (fresh -> topline) or a steady baseline
    (-> watch)? Compares the current 7-day signal_count + alert tier against the
    prior reading stored in Redis, then persists the current reading for next cycle.

    Fresh when the signal count rises meaningfully (>= max(2, 15%)) OR the alert tier
    steps up. Cold start (no prior baseline): only an intrinsically-high alert
    (high/surge) is fresh; a mere 'elevated' waits for a baseline. Fail-open.
    """
    try:
        from convergence_registry import alert_meets_threshold
    except ImportError:
        alert_meets_threshold = lambda a, b: False

    key = f'convergence_freshness:{conv_id}'
    prior = _redis_get(key) or {}
    prior_count = prior.get('count')
    prior_alert = prior.get('alert')

    if prior_count is None:
        is_fresh = alert_meets_threshold(actual_alert, 'high')
    else:
        rose_count = (signals_count - prior_count) >= max(2, prior_count * 0.15)
        rose_alert = (actual_alert != prior_alert
                      and alert_meets_threshold(actual_alert, prior_alert))
        is_fresh = bool(rose_count or rose_alert)

    # Persist current reading for next cycle (14-day TTL; self-heals if it goes quiet).
    _redis_set(key, {'count': signals_count, 'alert': actual_alert,
                     'ts': datetime.now(timezone.utc).isoformat()}, ttl=1209600)
    return is_fresh


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

        # Freshness gate (Jun 2026): is this commodity pressure RISING, or a steady
        # baseline? signal_count is a 7-day rolling count; flat = no new info in the
        # news this cycle. is_fresh -> GPI topline; stale -> GPI watch tier.
        is_fresh = _convergence_is_fresh(entry['id'], actual_alert, signals_count)

        enrichment_text = format_enrichment_text(entry, actual_alert, signals_count)
        long_text_parts.append(enrichment_text)

        # Set per-convergence flag on the signal so Layer 1 (GPI) can detect it.
        # Convention: signal['{convergence_id}_active'] = True
        # AND signal['convergence_states'][{id}] = full state dict
        signal_dict[f'{entry["id"]}_active'] = True
        signal_dict.setdefault('convergence_states', {})[entry['id']] = {
            'alert_level':     actual_alert,
            'signal_count':    signals_count,
            'is_fresh':        is_fresh,
            'commodity':       commodity_id,
            'commodity_state': commodity_state,
        }
        activated.append(entry['id'])
        tier_word = 'TOPLINE' if is_fresh else 'WATCH'
        print(f'[ME BLUF] Convergence activated: {entry["id"]} ({commodity_id} at {actual_alert.upper()}, {tier_word})')

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


# ════════════════════════════════════════════════════════════════════════
# BLUF PROSE V2 (May 22 2026 — cloned from WHA pattern)
# ────────────────────────────────────────────────────────────────────────
# Human-language regional analytical synthesis.
# Emits 3-paragraph structure with markdown bolding, directional language,
# "Why this matters" anchor. Replaces verbose legacy prose with FSO-grade
# briefing voice while preserving legacy `bluf` field for backwards compat.
# ════════════════════════════════════════════════════════════════════════

THEATRE_DISPLAY_NAMES = {
    'iran':       'Iran',
    'israel':     'Israel',
    'lebanon':    'Lebanon',
    'iraq':       'Iraq',
    'yemen':      'Yemen',
    'oman':       'Oman',
    'syria':      'Syria',
    'saudi':      'Saudi Arabia',
    'saudi_arabia': 'Saudi Arabia',
    'qatar':      'Qatar',
    'uae':        'the UAE',
    'jordan':     'Jordan',
    'turkey':     'Turkey',
    'egypt':      'Egypt',
    'palestine':  'Palestine',
}


def _read_history_snapshot(theatre, depth=3):
    """
    Read the last N history snapshots for a theatre from Redis.

    Returns a list of snapshot dicts (most recent first), or [] on miss/error.
    Each snapshot is guaranteed to be a dict with at least 'theatre_level' if
    the tracker is on the canonical (May 22 2026) schema.
    """
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return []
    history_key = f'rhetoric:{theatre}:history'
    try:
        # LRANGE 0..depth-1 returns most recent snapshots first
        url = f"{UPSTASH_REDIS_URL}/lrange/{history_key}/0/{depth - 1}"
        resp = requests.get(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if resp.status_code != 200:
            return []
        result = resp.json().get('result', [])
        snapshots = []
        for entry in result or []:
            try:
                snap = json.loads(entry) if isinstance(entry, str) else entry
                if isinstance(snap, dict):
                    snapshots.append(snap)
            except (json.JSONDecodeError, TypeError):
                continue
        return snapshots
    except Exception as e:
        print(f"[WHA BLUF v2] History read error for {theatre}: {str(e)[:120]}")
        return []


def _compute_direction(current_level, history_snapshots):
    """
    Compare current theatre_level vs. the previous snapshot's level.

    Returns dict with:
        direction: 'up' | 'down' | 'steady' | 'first_scan' | 'no_history'
        delta:     int (current - previous)
        previous:  int previous level (or None)
        phrase:    short human phrase for inline prose
    """
    if not history_snapshots:
        return {'direction': 'no_history', 'delta': 0, 'previous': None, 'phrase': ''}

    # Snapshots are stored most-recent-first via LPUSH.
    # Index 0 IS the current scan, index 1 is the previous one.
    if len(history_snapshots) < 2:
        return {'direction': 'first_scan', 'delta': 0, 'previous': None, 'phrase': ''}

    previous = history_snapshots[1]
    prev_level = previous.get('theatre_level')
    if prev_level is None:
        return {'direction': 'no_history', 'delta': 0, 'previous': None, 'phrase': ''}

    delta = current_level - prev_level

    if delta > 0:
        return {'direction': 'up', 'delta': delta, 'previous': prev_level,
                'phrase': f'up from L{prev_level} last cycle'}
    elif delta < 0:
        return {'direction': 'down', 'delta': delta, 'previous': prev_level,
                'phrase': f'down from L{prev_level} last cycle'}
    else:
        return {'direction': 'steady', 'delta': 0, 'previous': prev_level,
                'phrase': f'steady at L{current_level}'}


def _extract_so_what_phrase(raw_data):
    """
    Pull a short analytical phrase from a tracker's so_what dict.

    Resolves the so_what LOCATION (two conventions on the platform) then its shape:
        - top-level   raw['so_what']                     (legacy: VZ/Peru/Chile/Cuba)
        - nested      raw['interpretation']['so_what']   (v2.0: Yemen/Iran/Israel/Lebanon/Iraq/Syria)
    Shape: {factor} preferred over {scenario}; scenario snake_case -> readable;
           missing -> ''.
    """
    if not isinstance(raw_data, dict):
        return ''
    so_what = raw_data.get('so_what')
    if not isinstance(so_what, dict):
        # v2.0 trackers nest so_what under interpretation. Without this fallback the
        # analytical-read slot comes up empty for every nested-so_what theater.
        interp = raw_data.get('interpretation')
        if isinstance(interp, dict):
            so_what = interp.get('so_what')
    if not isinstance(so_what, dict):
        return ''

    factor = so_what.get('factor')
    if factor and isinstance(factor, str) and factor.strip():
        return factor.strip()

    scenario = so_what.get('scenario')
    if scenario and isinstance(scenario, str) and scenario.strip():
        # snake_case -> readable
        return scenario.replace('_', ' ').strip()

    return ''


def _extract_active_vectors(raw_data, threshold=2):
    """
    Return vector-level fields at or above threshold as (display_name, level) tuples.

    Normalizes 3 different vector shapes:
        - VZ:    raw['vectors'] = {us_pressure: 3, ...}                   (int)
        - Peru:  raw['vector_levels'] = {'domestic_stability': 'high', ...} (string)
        - Chile: raw['vector_levels'] = {...}                              (string)
        - Cuba:  raw['us_pressure'] = 3 (flat top-level)                   (int)
    """
    if not isinstance(raw_data, dict):
        return []

    VECTOR_LVL_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}

    VECTOR_DISPLAY = {
        'us_pressure':         'U.S. pressure',
        'regime_legitimacy':   'regime legitimacy',
        'regime_fracture':     'regime fracture',
        'adversary_access':    'adversary access',
        'oil_extraction':      'oil sector',
        'migration_outflow':   'migration outflow',
        'essequibo_dispute':   'Essequibo dispute',
        'domestic_stability':  'domestic stability',
        'resource_sector':     'resource sector',
        'us_alignment':        'U.S. alignment',
        'china_alignment':     'China alignment',
    }

    active = []

    # VZ pattern (raw.vectors, int values)
    vectors = raw_data.get('vectors')
    if isinstance(vectors, dict):
        for key, val in vectors.items():
            try:
                lvl = int(val)
                if lvl >= threshold:
                    active.append((VECTOR_DISPLAY.get(key, key.replace('_', ' ')), lvl))
            except (ValueError, TypeError):
                continue
        return sorted(active, key=lambda x: -x[1])

    # Peru/Chile pattern (raw.vector_levels, string OR int)
    vector_levels = raw_data.get('vector_levels')
    if isinstance(vector_levels, dict):
        for key, val in vector_levels.items():
            if isinstance(val, str):
                lvl = VECTOR_LVL_INT.get(val, 0)
            elif isinstance(val, int):
                lvl = val
            else:
                lvl = 0
            if lvl >= threshold:
                active.append((VECTOR_DISPLAY.get(key, key.replace('_', ' ')), lvl))
        return sorted(active, key=lambda x: -x[1])

    # Cuba pattern (flat top-level)
    for key in ['us_pressure', 'regime_fracture', 'adversary_access']:
        val = raw_data.get(key)
        try:
            lvl = int(val) if val is not None else 0
            if lvl >= threshold:
                active.append((VECTOR_DISPLAY.get(key, key.replace('_', ' ')), lvl))
        except (ValueError, TypeError):
            continue
    return sorted(active, key=lambda x: -x[1])


def _iran_offramp_sentence(trackers):
    """Estimative US-Iran off-ramp sentence for BLUF prose (v1.7.0 - Jun 18 2026).

    Reads the maturity tag + contradiction flags the Iran tracker now emits and
    renders a single convergence-framed sentence (or None when no off-ramp).
    Shared by both prose builders so legacy `bluf` and preferred `bluf_v2` stay
    in sync. Estimative voice only: consistent with / historically / pending /
    reversible -- never probabilities, dates, or "will".
    """
    iran_raw = (trackers.get('iran', {}) or {}).get('raw', {}) or {}
    maturity = iran_raw.get('de_escalation_maturity', 'none')
    if maturity not in ('framework', 'signed', 'implementing'):
        return None
    milestones = iran_raw.get('implementation_milestones', []) or []
    contra     = iran_raw.get('contradiction_active', False)
    flags      = iran_raw.get('contradiction_flags', []) or []

    if maturity == 'implementing':
        n = len(milestones)
        s = (f"US-Iran de-escalation is moving from framework toward implementation "
             f"({n} delivered milestone{'s' if n != 1 else ''} observed) -- consistent "
             f"with a durable off-ramp, though reversibility language persists.")
    elif maturity == 'signed':
        s = ("A signed US-Iran framework is in place -- consistent with de-escalation, "
             "but implementation is pending and explicitly reversible on the 60-day "
             "track; no delivered milestones observed yet.")
    else:  # framework
        s = ("An active US-Iran negotiation track is consistent with an emerging "
             "off-ramp, not yet signed.")

    if contra:
        bits = []
        if 'israel_lebanon' in flags:
            bits.append('continued Israeli operations in Lebanon')
        if 'syria_hezbollah' in flags:
            bits.append('calls for Syria to act against Hezbollah')
        contra_txt = ' and '.join(bits) if bits else 'an unresolved Lebanon-front contradiction'
        s += (f" The all-fronts ceasefire is contradicted by {contra_txt}, "
              f"which caps how deep the de-escalation reads.")

    return 'Iran -- ' + s


def _yemen_action_clause(so_what):
    """
    Regional-altitude read on Yemen's two founding questions -- Bab el-Mandeb
    closure and direct strikes on Israel -- derived from the Yemen tracker's own
    action_reads BANDS (read via the computed level + color), then re-expressed in
    a tight regional analytical voice. This is a recompute, not a copy of the Yemen
    page prose: the BLUF owns its regional framing.

    Surfaces only the two convergent bands (#dc2626 strong, #f97316 elevated);
    the rising-but-below (#f59e0b) and baseline (#6b7280) bands are intentionally
    NOT named at regional altitude. Estimative, convergence-framed; the reader
    completes the inference.

    Absence-honest: returns '' when neither read is convergent.
    """
    if not isinstance(so_what, dict):
        return ''
    reads = so_what.get('action_reads')
    if not isinstance(reads, list) or not reads:
        return ''

    mandeb_bit = ''
    israel_bit = ''
    for ar in reads:
        if not isinstance(ar, dict):
            continue
        q = (ar.get('question') or '').lower()
        color = ar.get('color', '')
        lvl = ar.get('level', 0)
        if 'mandeb' in q:
            if color == '#dc2626':
                mandeb_bit = (f'Houthi maritime signals consistent with movement toward '
                              f'Bab el-Mandeb closure (L{lvl})')
            elif color == '#f97316':
                mandeb_bit = (f'Houthi maritime pressure elevated short of Bab el-Mandeb '
                              f'closure (L{lvl})')
        elif 'israel' in q:
            if color == '#dc2626':
                israel_bit = (f'direct-strike posture toward Israel consistent with an '
                              f'active campaign (L{lvl})')
            elif color == '#f97316':
                israel_bit = (f'direct-strike posture toward Israel consistent with a '
                              f'resumption posture (L{lvl})')

    bits = [b for b in (mandeb_bit, israel_bit) if b]
    if not bits:
        return ''

    clause = 'Yemen read: ' + '; '.join(bits) + '.'
    if so_what.get('dual_chokepoint') and mandeb_bit:
        clause += ' The Iran-Hormuz dual-chokepoint pattern is active.'
    return clause


def _build_bluf_prose_v2(posture, trackers):
    """
    BLUF prose v2 — human-language regional analytical summary.

    Structure (per editorial decisions May 22 2026):
        Para 1: Regional posture headline + theater count + most-volatile theater dive
                with so_what.factor + active vectors + directional language
        Para 2: Soft-name the other elevated theaters (L2+) with brief factor
        Para 3: Cascade closer

    Graceful degradation: missing data fields adapt the prose, never error.
    """
    if not trackers:
        return ('Middle East Rhetoric Monitor: no live tracker data '
                'available at this scan. BLUF will populate as trackers come online.')

    today = datetime.now(timezone.utc).strftime('%B %d, %Y')
    posture_label = posture.get('label', 'BASELINE')
    peak_level = posture.get('peak_level', 0)
    theatres_at_l3plus = posture.get('theatres_at_l3plus', 0)
    breached = posture.get('breached_count', 0)

    # Sort trackers by threat level descending (most-volatile first)
    sorted_theatres = sorted(
        trackers.items(),
        key=lambda kv: -kv[1].get('levels', {}).get('threat', 0),
    )

    # ════════ PARA 1: Posture + most-volatile theater dive ════════
    para1_parts = [f"**Middle East -- {today}**"]

    n_live = len(trackers)
    if theatres_at_l3plus >= 2:
        posture_sentence = (
            f"Regional posture at {posture_label}, with {theatres_at_l3plus} theaters "
            f"at L3 or higher simultaneously across {n_live} live trackers."
        )
    elif peak_level >= 3:
        posture_sentence = (
            f"Regional posture at {posture_label}, with peak escalation L{peak_level} "
            f"across {n_live} live trackers."
        )
    else:
        posture_sentence = (
            f"Regional posture at {posture_label} -- {n_live} live trackers, "
            f"peak L{peak_level} (baseline range)."
        )
    if breached >= 1:
        posture_sentence += f" {breached} red line{'s' if breached > 1 else ''} breached."

    para1_parts.append(posture_sentence)

    # Dive into top theater
    top_theatre, top_data = sorted_theatres[0]
    top_level = top_data.get('levels', {}).get('threat', 0)
    top_name = THEATRE_DISPLAY_NAMES.get(top_theatre, top_theatre.title())
    top_raw = top_data.get('raw', {}) or {}

    top_history = _read_history_snapshot(top_theatre, depth=3)
    top_direction = _compute_direction(top_level, top_history)
    top_factor = _extract_so_what_phrase(top_raw)
    top_vectors = _extract_active_vectors(top_raw, threshold=2)

    if top_level >= 3:
        dive = f"The most volatile theater is **{top_name}** (composite L{top_level}"
        if top_direction.get('phrase'):
            dive += f", {top_direction['phrase']}"
        dive += ")"
        if top_factor:
            dive += f" -- analytical read: {top_factor}."
        else:
            dive += "."
        if top_vectors:
            top_3 = top_vectors[:3]
            vec_phrases = [f"{name} L{lvl}" for name, lvl in top_3]
            dive += f" Active vectors: {', '.join(vec_phrases)}."
        para1_parts.append(dive)
    elif top_level >= 1:
        dive = f"Highest tracker is **{top_name}** at L{top_level}"
        if top_direction.get('phrase'):
            dive += f" ({top_direction['phrase']})"
        if top_factor:
            dive += f" -- {top_factor}."
        else:
            dive += "."
        para1_parts.append(dive)

    # Yemen regional chokepoint/strike read -- names the Bab el-Mandeb + Israel
    # action reads at regional altitude (recomputed from the action_reads bands).
    if top_theatre == 'yemen':
        _yclause = _yemen_action_clause(top_data.get('so_what'))
        if _yclause:
            para1_parts.append(_yclause)

    # ════════ PARA 2: Other elevated theaters + baselines ════════
    para2_parts = []
    other_elevated = [
        (t, d) for t, d in sorted_theatres[1:]
        if d.get('levels', {}).get('threat', 0) >= 2
    ]
    baseline_theatres = [
        t for t, d in sorted_theatres[1:]
        if d.get('levels', {}).get('threat', 0) < 2
    ]

    for theatre, data in other_elevated:
        level = data.get('levels', {}).get('threat', 0)
        name = THEATRE_DISPLAY_NAMES.get(theatre, theatre.title())
        raw = data.get('raw', {}) or {}
        history = _read_history_snapshot(theatre, depth=3)
        direction = _compute_direction(level, history)
        factor = _extract_so_what_phrase(raw)

        sent = f"**{name}** registers L{level}"
        if direction.get('phrase'):
            sent += f" ({direction['phrase']})"
        if factor:
            sent += f" -- {factor}."
        else:
            vecs = _extract_active_vectors(raw, threshold=2)
            if vecs:
                sent += f" -- {vecs[0][0]} elevated at L{vecs[0][1]}."
            else:
                sent += "."
        if theatre == 'yemen':
            _yclause = _yemen_action_clause(data.get('so_what'))
            if _yclause:
                sent += f" {_yclause}"
        para2_parts.append(sent)

    if baseline_theatres:
        names = [THEATRE_DISPLAY_NAMES.get(t, t.title()) for t in baseline_theatres]
        if len(names) == 1:
            para2_parts.append(f"{names[0]} remains at baseline.")
        elif len(names) == 2:
            para2_parts.append(f"{names[0]} and {names[1]} remain at baseline.")
        else:
            para2_parts.append(f"{', '.join(names[:-1])}, and {names[-1]} remain at baseline.")

    # ════════ PARA 3: Cascade closer ════════
    # -- v1.7.0 (Jun 18 2026): US-Iran off-ramp into body para (estimative) --
    # Appends to para2_parts (assembled below), surfaced before the cascade closer.
    iran_offramp = _iran_offramp_sentence(trackers)
    if iran_offramp:
        para2_parts.append(iran_offramp)

    para3_parts = []
    if theatres_at_l3plus >= 3:
        para3_parts.append(
            f"**Why this matters:** {theatres_at_l3plus} simultaneous L3+ theaters in the "
            "Middle East is a structurally rare convergence. Concrete cascade risks "
            "across migration corridors, sanctions-evasion routes (oil/gold/wheat), and "
            "adversary-access vectors (Russia/China/Iran) are now active simultaneously."
        )
    elif theatres_at_l3plus == 2:
        para3_parts.append(
            "**Why this matters:** Two simultaneous L3+ theaters create real migration and "
            "sanctions cascade risk. Monitor for adversary-axis amplification."
        )
    elif peak_level >= 4:
        para3_parts.append(
            "**Why this matters:** A single L4+ theater is the floor for cross-region cascade "
            "concerns -- particularly when red lines have been breached."
        )
    elif peak_level >= 3:
        para3_parts.append(
            "**Why this matters:** L3 pressure represents direct-threat language. "
            "Single-theater dynamics, but trajectory bears watching."
        )

    # Assemble paragraphs (separated by blank lines for frontend rendering)
    paragraphs = [' '.join(para1_parts)]
    if para2_parts:
        paragraphs.append(' '.join(para2_parts))
    if para3_parts:
        paragraphs.append(' '.join(para3_parts))
    return '\n\n'.join(paragraphs)


# ============================================================
# TOP SIGNALS COLLECTOR
# ============================================================



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

    # -- v1.7.0 (Jun 18 2026): US-Iran off-ramp (maturity-aware, estimative) --
    iran_offramp = _iran_offramp_sentence(trackers)
    if iran_offramp:
        parts.append(iran_offramp)

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

# ── Approach B: structured blocks + multi-axis tagging (Jun 13 2026) ──
# ME already emits prose_v2 as a markdown string (\n\n paragraphs, **bold**
# markers). To share ONE front-end renderer platform-wide, we ALSO emit a
# bluf_v2 block array [{label,text}]. The markdown is preserved as bluf_v2_md.
_ME_REGIONAL_AXIS_SETS = {
    'kinetic_pressure': ['kinetic'], 'red_line_breached': ['kinetic'],
    'theatre_high': ['kinetic'], 'theatre_active': ['kinetic'],
    'dual_chokepoint': ['kinetic', 'economic'], 'strike_window': ['kinetic'],
    'nuclear_signaling': ['kinetic'], 'kinetic_threshold': ['kinetic'],
    'commodity': ['economic'], 'economic_stress': ['economic'],
    'oil': ['economic'], 'sanctions': ['economic', 'diplomatic'],
    'diplomatic_track_active': ['diplomatic'], 'diplomatic_active': ['diplomatic'],
    'green_line_active': ['diplomatic'], 'mediation': ['diplomatic'],
    'ceasefire': ['diplomatic'], 'humanitarian': ['humanitarian'],
    'humanitarian_lebanon': ['humanitarian'], 'displacement': ['humanitarian'],
    'migration': ['humanitarian'], 'health_emergency': ['humanitarian'],
}
_ME_AXIS_KEYWORD_HINTS = [
    ('economic', ['economic', 'oil', 'commodity', 'wheat', 'sanction', 'currency', 'gold', 'trade']),
    ('humanitarian', ['humanitarian', 'displace', 'refugee', 'migration', 'famine', 'idp', 'health']),
    ('diplomatic', ['diplomatic', 'ceasefire', 'mediation', 'negotiat', 'off-ramp', 'envoy', 'brokering']),
]

def _me_axes_for_signal(sig):
    sig = sig if isinstance(sig, dict) else {}
    pt = sig.get('pressure_type')
    cat = str(sig.get('category') or '').lower()
    if cat in _ME_REGIONAL_AXIS_SETS:
        axes = list(_ME_REGIONAL_AXIS_SETS[cat])
        if pt and pt in ('kinetic','economic','diplomatic','humanitarian') and pt not in axes:
            axes.insert(0, pt)
        return axes
    if pt and pt in ('kinetic','economic','diplomatic','humanitarian'):
        return [pt]
    blob = (cat + ' ' + str(sig.get('short_text') or '') + ' ' + str(sig.get('long_text') or '')).lower()
    for axis, kws in _ME_AXIS_KEYWORD_HINTS:
        if any(k in blob for k in kws):
            return [axis]
    return ['kinetic']

def _me_tag_signal_axes(signals):
    out = []
    for s in (signals or []):
        s2 = dict(s)
        axes = _me_axes_for_signal(s2)
        s2['axes'] = axes
        s2.setdefault('pressure_type', axes[0])
        out.append(s2)
    return out

def _me_prose_v2_to_blocks(md):
    """Parse the markdown prose_v2 string into {label,text} blocks.
    Para 1 starts '**Middle East -- date**' then posture + dive.
    Para 3 starts '**Why this matters:**'. Bold inline names stay inline."""
    if not md or not isinstance(md, str):
        return []
    paras = [p.strip() for p in md.split('\n\n') if p.strip()]
    blocks = []
    for i, para in enumerate(paras):
        # Header para: leading '**Middle East -- date**'
        import re as _re
        hm = _re.match(r'^\*\*([^*]+)\*\*\s*(.*)$', para, _re.S)
        if i == 0 and hm:
            header_label = hm.group(1).strip()       # 'Middle East -- date'
            rest = hm.group(2).strip()               # posture + dive sentences
            blocks.append({'label': header_label, 'text': ''})
            if rest:
                # First sentence is the posture line; rest is theatre dive.
                # Split at the first '. ' that ends the posture sentence.
                # The posture sentence begins 'Regional posture at ...'
                pm = _re.match(r'^(Regional posture[^.]*\.(?:\s+\d+\s+red line[^.]*\.)?)\s*([\s\S]*)$', rest)
                if pm:
                    posture_txt = pm.group(1).strip()
                    dive_txt = pm.group(2).strip()
                    if posture_txt.lower().startswith('regional posture'):
                        posture_txt = posture_txt[len('Regional posture'):].lstrip(' at').strip()
                        posture_txt = posture_txt[0].upper() + posture_txt[1:] if posture_txt else posture_txt
                    blocks.append({'label': 'Regional Posture', 'text': posture_txt})
                    if dive_txt:
                        blocks.append({'label': 'Theatre Reads', 'text': dive_txt})
                else:
                    blocks.append({'label': 'Regional Posture', 'text': rest})
            continue
        # 'Why this matters:' closer
        wm = _re.match(r'^\*\*Why this matters:\*\*\s*([\s\S]*)$', para)
        if wm:
            blocks.append({'label': 'Why This Matters', 'text': wm.group(1).strip()})
            continue
        # Otherwise: other-elevated / baseline paragraph -> Theatre Reads (append)
        # strip stray ** markers for clean display
        clean = _re.sub(r'\*\*', '', para)
        blocks.append({'label': 'Theatre Reads', 'text': clean})
    return blocks


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
    trackers, trackers_missing, trackers_stale = _read_all_trackers()  # Already normalized post-shim

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
    all_signals = _me_tag_signal_axes(all_signals)           # Jun 13 2026: multi-axis pills
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

    # ── v2.1.0 (May 22 2026): Build prose_v2 — markdown-bolded 3-paragraph synthesis ──
    # Mirrors WHA pattern: dual-emit legacy `bluf` + new `bluf_v2`.
    # Frontend prefers bluf_v2 when present, falls back to bluf for compat.
    try:
        posture_for_v2 = {
            'label':              posture_label,
            'peak_level':         max_level,
            'theatres_at_l3plus': theatres_at_l3plus,
            'breached_count':     sum(1 for l in levels.values() if l >= 4),
            'region':             'me',
        }
        bluf_v2_md = _build_bluf_prose_v2(posture_for_v2, trackers)
        bluf_v2 = _me_prose_v2_to_blocks(bluf_v2_md)   # approach B blocks
    except Exception as e:
        print(f"[ME BLUF] prose_v2 build error: {str(e)[:200]}")
        bluf_v2_md = None
        bluf_v2 = []   # Graceful degrade — legacy bluf still works

    result = {
        'success':           True,
        'from_cache':        False,
        'bluf':              bluf_prose,
        'bluf_v2':           bluf_v2,                 # Jun 13 2026: {label,text} block array (approach B)
        'bluf_v2_md':        bluf_v2_md,              # v2.1.0: original markdown-bolded prose (preserved)
        'signals':           all_signals,             # v2.3.0: FULL signal pool — for GPI axis aggregation
        'top_signals':       top_signals_capped,      # v2.3.0: capped — for display + prose synthesis
        'posture_label':     posture_label,
        'posture_color':     posture_color,
        'max_level':         max_level,
        'avg_score':         avg_score,
        'theatres_at_l3plus':theatres_at_l3plus,
        'theatres_live':     theatres_live,
        'trackers_stale':    trackers_stale,    # B: served from last-known-good
        'trackers_missing':  trackers_missing,  # B: no live AND no last-known-good
        'picture_complete':  (len(trackers_missing) == 0),
        'theatre_summary':   theatre_summary,
        'generated_at':      datetime.now(timezone.utc).isoformat(),
        'version':           '2.1.0',  # bumped for prose_v2 + strike window awareness
        'region':            'middle_east',  # v2.0: GPI-readable
        'top_signals_count': len(top_signals_capped),
    }

    _bluf_ttl = BLUF_INCOMPLETE_TTL if (trackers_missing or trackers_stale) else BLUF_CACHE_TTL
    _redis_set(BLUF_CACHE_KEY, result, ttl=_bluf_ttl)
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
